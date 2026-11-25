"""Four things the mac keeps about the owner that are not chats: contacts, reminders, calls and voice memos.

  contacts     the contacts app. builds the name book (ctx/namebook.py: whose number is this), and gives one row for
               each contact the owner wrote a note on. src "contacts"
  reminders    every reminder: title, notes, list, due, done or not. src "reminders", who "me"
  calls        phone and facetime calls from the mac's call history, and whatsapp calls from whatsapp's own. who, when,
               how long, which way. there is nothing said in a row: no call is recorded. src "calls"
  voice_memos  title, date and length of each recording. the words are the media reader's work. src "voice_memo"

All read only. The apple stores sit behind full disk access: a process macos keeps out gets PermissionError, which the
collector records as "blocked by macOS: grant Full Disk Access ..." and keeps the rows from the last read.
"""
import glob, json, os, shutil, sqlite3
from . import namebook, paths
from .collect import APPLE, FDA, H, iso, put, rid, since

REMINDERS = "~/Library/Group Containers/group.com.apple.reminders"
CALLS = "~/Library/Application Support/CallHistoryDB/CallHistory.storedata"
MEMOS = ("~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/CloudRecordings.db",
         "~/Library/Application Support/com.apple.voicememos/Recordings/CloudRecordings.db")
WA_CALLS = namebook.WA_ROOT + "/CallHistory.sqlite"
ABSENT = "not installed or no data"


def _open(path):
    """A read-only connection to one of the mac's own stores (a copy when the app holds it), or the plain reason."""
    try:
        os.stat(path)
    except FileNotFoundError:
        raise FileNotFoundError(ABSENT)
    except PermissionError:
        raise PermissionError(FDA)
    try:
        return namebook._open(path)
    except (sqlite3.Error, OSError):
        raise PermissionError(FDA)


def _close(con, tmp):
    con.close()
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)


def _cols(con, table):
    return namebook._cols(con, table)


def _when(t):
    return iso(t + APPLE) if isinstance(t, (int, float)) and t else ""


def _length(secs):
    secs = int(secs or 0)
    return "%d min" % round(secs / 60) if secs >= 90 else "%d sec" % secs


# ---------------------------------------------------------------- contacts

def contacts(days, out):
    """Build the name book, then one row per contact that has a note. The book is built from whatever can be read (so a
    blocked contacts app still leaves whatsapp's and google's names in it); the rows need the contacts app itself."""
    namebook.build()
    try:
        cards = namebook.apple_contacts()
    except PermissionError:
        raise PermissionError(FDA)
    n = 0
    for c in cards:
        if not c["note"].strip() or (days and c["at"] + APPLE < since(days)):
            continue
        put(out, {"id": rid("AB", c["uid"]), "src": "contacts", "ts": _when(c["at"]), "title": c["name"], "text": c["note"].strip()[:6000], "who": "me"})
        n += 1
    return n


# ---------------------------------------------------------------- reminders

def reminders(days, out):
    root = H(REMINDERS)
    try:
        os.listdir(root)
    except FileNotFoundError:
        raise FileNotFoundError(ABSENT)
    except PermissionError:
        raise PermissionError(FDA)
    stores = sorted(glob.glob(os.path.join(glob.escape(root), "Container_v1", "Stores", "Data-*.sqlite")))
    if not stores:
        raise FileNotFoundError(ABSENT)
    n, seen, cutoff, bad = 0, set(), since(days), 0
    for path in stores:
        try:
            con, tmp = _open(path)
        except (PermissionError, FileNotFoundError):
            bad += 1
            continue
        try:
            c = _cols(con, "ZREMCDREMINDER")
            if "ZTITLE" not in c:
                continue
            lists = {}
            for table in ("ZREMCDBASELIST", "ZREMCDLIST", "ZREMCDOBJECT"):
                if "ZNAME" in _cols(con, table):
                    lists = {pk: str(name or "") for pk, name in con.execute('select Z_PK, ZNAME from "%s"' % table)}
                    break
            pick = lambda col, alt="null": col if col in c else alt
            q = "select Z_PK, ZTITLE, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s from ZREMCDREMINDER" % (
                pick("ZNOTES"), pick("ZCOMPLETED", "0"), pick("ZCOMPLETIONDATE"), pick("ZCREATIONDATE"), pick("ZLASTMODIFIEDDATE"), pick("ZDUEDATE"),
                pick("ZLIST"), pick("ZCKIDENTIFIER"), pick("ZMARKEDFORDELETION", "0"), pick("ZFLAGGED", "0"))
            for pk, title, notes, done, done_at, made, changed, due, lst, ck, gone, flagged in con.execute(q):
                title, key = " ".join(str(title or "").split()), str(ck or "%s:%s" % (os.path.basename(path), pk))
                if not title or gone or key in seen or ((changed or made or 0) + APPLE < cutoff):
                    continue
                seen.add(key)
                row = {"id": rid("RM", key), "src": "reminders", "ts": _when(made or changed), "title": title,
                       "text": "\n".join(x for x in (title, str(notes or "").strip()) if x)[:6000], "who": "me", "list": lists.get(lst, ""),
                       "due": _when(due), "done": bool(done), "done_at": _when(done_at) if done else ""}
                if flagged:
                    row["flagged"] = True
                put(out, row)
                n += 1
        except sqlite3.Error:
            bad += 1
        finally:
            _close(con, tmp)
    if bad == len(stores):
        raise PermissionError(FDA)
    return n


def open_reminders(most=50):
    """Reminders not yet done, soonest due first then newest: [{id, title, due, list, ts}]. For the home's "you said you
    would": read from the rows the collector last wrote, so it costs nothing and needs no permission."""
    from . import collect
    out = []
    try:
        with open(collect._part("reminders"), encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if not r.get("done"):
                    out.append({"id": r["id"], "title": r.get("title", ""), "due": r.get("due", ""), "list": r.get("list", ""), "ts": r.get("ts", "")})
    except OSError:
        return []
    out.sort(key=lambda r: r["ts"], reverse=True)
    out.sort(key=lambda r: r["due"] or "9999")
    return out[:most]


def promised(now=None, most=4):
    """Open reminders in the shape the home keeps things the owner said they would do (ctx/now.py, "promised"):
    [{"what", "when", "days", "thread", "id", "src"}], the overdue and the soonest due first. `days` is how long ago it
    was written down."""
    import time
    from datetime import datetime, timezone
    now, out = now or time.time(), []
    for r in open_reminders(most=10 ** 6):
        try:
            made = datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            made = now
        out.append({"what": r["title"], "when": r["due"] or r["ts"], "days": max(0, int((now - made) // 86400)), "thread": r["list"] or "reminders",
                    "id": r["id"], "src": "reminders"})
    return out[:most]


# ---------------------------------------------------------------- calls

KINDS = {1: "phone", 8: "facetime video", 16: "facetime audio"}


def _call_row(key, at, secs, direction, via, people, group=False):
    who = ", ".join(people) or "an unknown number"
    if direction == "missed":
        text = "missed %s call from %s" % (via, who)
    elif direction == "out":
        text = "%s call to %s, %s" % (via, who, _length(secs) if secs else "no answer")
    else:
        text = "%s call from %s, %s" % (via, who, _length(secs) if secs else "not answered")
    return {"id": key, "src": "calls", "ts": at, "title": who, "text": text, "who": "me" if direction == "out" else "them", "with": people,
            "secs": int(secs or 0), "direction": direction, "via": via, "group": bool(group)}


def _apple_calls(cutoff, book):
    con, tmp = _open(H(CALLS))
    try:
        c = _cols(con, "ZCALLRECORD")
        if "ZDATE" not in c:
            return []
        pick = lambda col, alt="null": col if col in c else alt
        q = "select Z_PK, ZDATE, %s, %s, %s, %s, %s, %s, %s, %s from ZCALLRECORD where ZDATE > ?" % (
            pick("ZDURATION", "0"), pick("ZADDRESS"), pick("ZORIGINATED", "0"), pick("ZANSWERED", "1"), pick("ZCALLTYPE", "1"),
            pick("ZSERVICE_PROVIDER"), pick("ZUNIQUE_ID"), pick("ZNAME"))
        out = []
        for pk, at, secs, addr, mine, answered, kind, provider, uid, name in con.execute(q, (cutoff - APPLE,)):
            if isinstance(addr, (bytes, bytearray)):
                addr = bytes(addr).decode("utf-8", "ignore")
            addr, provider = str(addr or "").strip(), str(provider or "").lower()
            via = "whatsapp" if "whatsapp" in provider else KINDS.get(kind, "phone") if "facetime" not in provider or kind in (8, 16) else "facetime audio"
            who = namebook.name_for(addr, book) or " ".join(str(name or "").split()) or addr
            direction = "out" if mine else "in" if answered or (secs or 0) > 0 else "missed"
            out.append((at + APPLE, via, _call_row(rid("CL", uid or (at, addr)), iso(at + APPLE), secs, direction, via, [who] if who else [])))
        return out
    finally:
        _close(con, tmp)


def _whatsapp_calls(cutoff, book):
    con, tmp = _open(H(WA_CALLS))
    try:
        if "ZDATE" not in _cols(con, "ZWACDCALLEVENT"):
            return []
        who = {}
        if "ZJIDSTRING" in _cols(con, "ZWACDCALLEVENTPARTICIPANT"):
            for group, jid in con.execute("select Z1PARTICIPANTS, ZJIDSTRING from ZWACDCALLEVENTPARTICIPANT"):       # tied to the call's summary row, not to the event
                who.setdefault(group, []).append(str(jid or ""))
        agg = {}
        if "ZINCOMING" in _cols(con, "ZWAAGGREGATECALLEVENT"):
            agg = {pk: (inc, missed, video) for pk, inc, missed, video in con.execute("select Z_PK, ZINCOMING, ZMISSED, ZVIDEO from ZWAAGGREGATECALLEVENT")}
        out = []
        for pk, at, secs, parent, cid, group in con.execute("select Z_PK, ZDATE, ZDURATION, Z1CALLEVENTS, ZCALLIDSTRING, ZGROUPJIDSTRING from ZWACDCALLEVENT where ZDATE > ?", (cutoff - APPLE,)):
            inc, missed, video = agg.get(parent, (0, 0, 0))
            people = [namebook.name_for(j, book) or ("someone on whatsapp" if j.endswith("@lid") else j.split("@")[0]) for j in who.get(parent, [])]
            people = list(dict.fromkeys(people))
            direction = "missed" if inc and missed and not secs else "in" if inc else "out"
            via = "whatsapp video" if video else "whatsapp"
            out.append((at + APPLE, via, _call_row(rid("CW", cid, int(at or 0)), iso(at + APPLE), secs, direction, via, people, group=bool(group) or len(people) > 1)))
        return out
    finally:
        _close(con, tmp)


def calls(days, out):
    """Calls from the mac's own history and from whatsapp's. A whatsapp call the mac's history also holds is one row."""
    cutoff, book, got, blocked = since(days), namebook.fresh(), [], False
    try:
        mac = _apple_calls(cutoff, book)
    except PermissionError:
        raise           # the mac's history is there and this process may not read it: keep the rows of the last full read
    except (FileNotFoundError, sqlite3.Error):
        mac, blocked = [], True
    try:
        wa = _whatsapp_calls(cutoff, book)
    except (PermissionError, FileNotFoundError, sqlite3.Error):
        wa = []
        if blocked:
            raise FileNotFoundError(ABSENT)
    times = sorted(t for t, _, _ in wa)
    for t, via, row in mac:
        if via == "whatsapp" and any(abs(t - w) < 120 for w in times):
            continue
        got.append((t, row))
    got += [(t, row) for t, _, row in wa]
    seen, n = set(), 0
    for _, row in sorted(got, key=lambda x: x[0]):
        if row["id"] not in seen:           # whatsapp can hold one call twice
            seen.add(row["id"])
            put(out, row)
            n += 1
    return n


# ---------------------------------------------------------------- voice memos

def voice_memos(days, out):
    """Title, date and length of each recording. Nothing is listened to here."""
    err = FileNotFoundError(ABSENT)
    for path in MEMOS:
        try:
            con, tmp = _open(H(path))
        except (PermissionError, FileNotFoundError) as e:
            err = e if isinstance(e, PermissionError) or not isinstance(err, PermissionError) else err
            continue
        try:
            c = _cols(con, "ZCLOUDRECORDING")
            if "ZDATE" not in c:
                continue
            title = "coalesce(%s)" % ", ".join([x for x in ("ZENCRYPTEDTITLE", "ZCUSTOMLABEL") if x in c] + ["''"])
            pick = lambda col, alt="null": col if col in c else alt
            n = 0
            for pk, name, at, secs, file, uid in con.execute("select Z_PK, %s, ZDATE, %s, %s, %s from ZCLOUDRECORDING where ZDATE > ?" % (
                    title, pick("ZDURATION", "0"), pick("ZPATH"), pick("ZUNIQUEID")), (since(days) - APPLE,)):
                name = " ".join(str(name or "").split()) or "recording"
                put(out, {"id": rid("VM", uid or (at, pk)), "src": "voice_memo", "ts": _when(at), "title": name,
                          "text": "voice memo: %s, %s" % (name, _length(secs)), "who": "me", "secs": int(secs or 0), "file": os.path.basename(str(file or ""))})
                n += 1
            return n
        except sqlite3.Error:
            raise PermissionError(FDA)
        finally:
            _close(con, tmp)
    raise err
