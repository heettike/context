"""What the owner marked to keep, in places this mac already holds: flagged mail (a star in gmail is a flag in Apple
Mail), starred whatsapp messages, pinned notes, safari's reading list and bookmarks, the bookmarks of chromium browsers.

Each is a small read-only reader in canvas.py's pattern, of kind "builtin": `connect --search "starred"` offers it,
`connect builtin:mail_starred` tries it, `--enable` makes it the docs source canvas_mail_starred (canvas_whatsapp_starred,
canvas_notes_pinned, canvas_safari_reading_list, canvas_safari_bookmarks, canvas_browser_bookmarks). Every row carries
"kept": "starred" | "pinned" | "reading list" | "bookmark". Nothing is on unless the owner switches it on. No model.
"""
import glob, gzip, json, os, plistlib, shutil, sqlite3, time
from datetime import timezone
from . import canvas
from .canvas import Stop, _iso, _rid, _rows

H = os.path.expanduser
MAIL = H("~/Library/Mail")
SAFARI_BOOKMARKS = H("~/Library/Safari/Bookmarks.plist")
WEBKIT_EPOCH = 11644473600          # chromium counts microseconds from 1601
FDA = "blocked by macos: grant full disk access to context (system settings > privacy & security > full disk access), then try again"


def _db(path, missing):
    """A read-only connection (a copy when the app holds a lock), or the plain reason there is none."""
    from . import connect
    try:
        os.stat(path)
    except FileNotFoundError:
        raise Stop("cannot", missing)
    except PermissionError:
        raise Stop("needs_you", FDA)
    try:
        return connect._open_ro(path)
    except (sqlite3.Error, OSError, PermissionError):
        raise Stop("needs_you", FDA)


def _cols(con, table):
    return {r[1].lower() for r in con.execute('pragma table_info("%s")' % table)}


def _done(con, tmp):
    con.close()
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- flagged mail

def _indexes():
    try:
        os.listdir(MAIL)
    except FileNotFoundError:
        raise Stop("cannot", "apple mail is not set up on this mac; add the account to apple mail and its starred mail can be read")
    except PermissionError:
        raise Stop("needs_you", FDA)
    found = sorted(glob.glob(os.path.join(glob.escape(MAIL), "V*", "MailData", "Envelope Index")))
    if not found:
        raise Stop("cannot", "apple mail has no index of its mail on this mac yet")
    return found


def _flagged(con):
    """[(rowid, subject, sender, summary, unix time)] of flagged mail that is not deleted, whatever the version of the index."""
    c = _cols(con, "messages")
    if not c:
        return []
    flag = "m.flagged = 1" if "flagged" in c else "(m.flags & 16) != 0"       # the old bitfield: bit 4 is the flag
    tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    subj = "(select s.subject from subjects s where s.ROWID = m.subject)" if "subjects" in tables else "m.subject"
    sender = "(select a.address from addresses a where a.ROWID = m.sender)" if "addresses" in tables else "m.sender"
    summ = "(select s.summary from summaries s where s.ROWID = m.summary)" if "summaries" in tables and "summary" in c else "''"
    q = "select m.ROWID, %s, %s, %s, m.date_received from messages m where %s%s" % (subj, sender, summ, flag, " and m.deleted = 0" if "deleted" in c else "")
    return [(r[0], str(r[1] or ""), str(r[2] or ""), str(r[3] or ""), r[4] or 0) for r in con.execute(q)]


def mail_flagged_files():
    """The file names (a message's number in the index) of flagged mail. mail.py marks those rows "starred". Empty when
    the index cannot be read: a star is extra, never a reason to fail the mail read."""
    out = set()
    try:
        for p in _indexes():
            con, tmp = _db(p, "")
            try:
                out.update(str(r[0]) for r in _flagged(con))
            finally:
                _done(con, tmp)
    except (Stop, sqlite3.Error, OSError):
        pass
    return out


def mail_starred(d, emit, trial, say, st, prev):
    sl, rows = d["slug"], []
    say("looking in apple mail's index for flagged mail")
    for p in _indexes():
        con, tmp = _db(p, "")
        try:
            rows += [(os.path.dirname(os.path.dirname(p)),) + r for r in _flagged(con)]
        except sqlite3.Error:
            raise Stop("cannot", "apple mail's index is in a form this version does not read")
        finally:
            _done(con, tmp)
    new = [r for r in rows if _rid(sl, r[1], r[5]) not in prev]
    bodies = {}
    if new and not trial:                           # the words of a flagged mail are in its own file, named by its number
        want = {str(r[1]) for r in new}
        say("reading %d flagged emails" % len(want))
        from . import mail
        for root in sorted({r[0] for r in new}):
            for folder, _, files in os.walk(root):
                for f in files:
                    if f.endswith(".emlx") and f.split(".")[0] in want and f.split(".")[0] not in bodies:
                        try:
                            bodies[f.split(".")[0]] = mail._body(mail._read(os.path.join(folder, f)))
                        except Exception:
                            pass
    for root, rowid, subject, sender, summary, ts in rows:
        pid = _rid(sl, rowid, ts)
        if pid in prev:
            for r in prev[pid]:
                emit(r)
            continue
        text = "from %s\n%s" % (sender, bodies.get(str(rowid)) or summary or subject)
        for r in _rows(sl, pid, "", subject or "(no subject)", text, _iso(ts) if ts else ""):
            emit(dict(r, kept="starred", who_from=sender))
    return {"how": "reads the mail you flagged in apple mail (a star in gmail is a flag here): %d emails, each with its sender, subject and text" % len(rows),
            "detail": "" if rows else "no mail is flagged", "why": "no mail is flagged in apple mail", "stats": {"found": len(rows), "kept": len(rows), "route": "disk"}}


# ---------------------------------------------------------------- whatsapp starred, notes pinned

def whatsapp_starred(d, emit, trial, say, st, prev):
    from . import collect
    con, tmp = _db(collect.WA_DB, "whatsapp for mac is not on this mac")
    try:
        if "zstarred" not in _cols(con, "ZWAMESSAGE"):
            raise Stop("cannot", "this version of whatsapp does not keep its stars where they can be read")
        chats = dict(con.execute("select Z_PK, ZPARTNERNAME from ZWACHATSESSION"))
        got = con.execute("select Z_PK, ZMESSAGEDATE, ZISFROMME, ZTEXT, ZCHATSESSION from ZWAMESSAGE where ZSTARRED = 1 and ZTEXT is not null").fetchall()
    except sqlite3.Error:
        raise Stop("needs_you", FDA)
    finally:
        _done(con, tmp)
    for pk, ts, me, text, chat in got:
        name = chats.get(chat) or "?"
        for r in _rows(d["slug"], _rid(d["slug"], pk), "", name, "%s: %s" % ("me" if me else name, text), _iso(ts + collect.APPLE)):
            emit(dict(r, kept="starred", msg="W%s" % pk))
    return {"how": "reads the messages you starred in whatsapp: %d, each with its chat and date" % len(got), "detail": "",
            "why": "no message is starred in whatsapp", "stats": {"found": len(got), "kept": len(got), "route": "disk"}}


def notes_pinned(d, emit, trial, say, st, prev):
    from . import collect
    con, tmp = _db(collect.NOTES_DB, "apple notes has nothing on this mac")
    n = 0
    try:
        if "zispinned" not in _cols(con, "ZICCLOUDSYNCINGOBJECT"):
            raise Stop("cannot", "this version of notes does not keep its pins where they can be read")
        q = """select o.Z_PK, o.ZTITLE1, o.ZMODIFICATIONDATE1, d.ZDATA from ZICCLOUDSYNCINGOBJECT o join ZICNOTEDATA d on d.ZNOTE = o.Z_PK
               where o.ZISPINNED = 1 and d.ZDATA is not null and coalesce(o.ZMARKEDFORDELETION, 0) = 0 and coalesce(o.ZISPASSWORDPROTECTED, 0) = 0"""
        for pk, title, ts, data in con.execute(q).fetchall():
            try:
                text = collect._field(collect._field(collect._field(gzip.decompress(data), 2), 3), 2).decode("utf-8", "ignore")
            except (OSError, IndexError):
                continue
            if text.strip():
                for r in _rows(d["slug"], _rid(d["slug"], pk), "", title or "", text, _iso((ts or 0) + collect.APPLE)):
                    emit(dict(r, kept="pinned", note="N%s" % pk))
                n += 1
    except sqlite3.Error:
        raise Stop("needs_you", FDA)
    finally:
        _done(con, tmp)
    return {"how": "reads the notes you pinned in apple notes: %d" % n, "detail": "", "why": "no note is pinned", "stats": {"found": n, "kept": n, "route": "disk"}}


# ---------------------------------------------------------------- bookmarks

def _safari(want_list):
    try:
        with open(SAFARI_BOOKMARKS, "rb") as f:
            tree = plistlib.load(f)
    except FileNotFoundError:
        raise Stop("cannot", "safari has no bookmarks file on this mac")
    except PermissionError:
        raise Stop("needs_you", FDA)
    except Exception:
        raise Stop("cannot", "safari's bookmarks file could not be read")
    out = []

    def walk(node, trail, in_list):
        if not isinstance(node, dict):
            return
        title = node.get("Title") or ""
        in_list = in_list or title == "com.apple.ReadingList"
        if node.get("URLString") and in_list == want_list:
            rl = node.get("ReadingList") or {}
            name = (node.get("URIDictionary") or {}).get("title") or node["URLString"]
            when = rl.get("DateAdded")          # a plist date is utc with no zone written on it
            ts = when.replace(tzinfo=timezone.utc).timestamp() if hasattr(when, "timestamp") and when.tzinfo is None else when.timestamp() if hasattr(when, "timestamp") else 0
            out.append((node["URLString"], str(name), str(rl.get("PreviewText") or ""), " / ".join(trail), ts))
        shown = {"BookmarksBar": "favourites", "BookmarksMenu": "bookmarks menu"}.get(title, title)
        for ch in node.get("Children") or []:
            walk(ch, trail + [shown] if shown and not shown.startswith("com.apple.") and node is not tree else trail, in_list)
    walk(tree, [], False)
    return out


def _safari_reader(want_list):
    def fn(d, emit, trial, say, st, prev):
        seen = st.get("seen") or {}
        got, now, first = _safari(want_list), _iso(time.time()), not st.get("seen")
        for url, name, preview, folder, ts in got:
            # a bookmark has no date of its own: the first read leaves it undated, later ones date what is new
            seen[url] = _iso(ts) if ts else seen.get(url, "" if first or trial else now)
            text = "\n".join(x for x in (name, preview, "in " + folder if folder else "", url) if x)
            for r in _rows(d["slug"], _rid(d["slug"], url), url, name, text, seen[url]):
                emit(dict(r, kept="reading list" if want_list else "bookmark"))
        st["seen"] = {u: seen[u] for u, _, _, _, _ in got}
        what = "safari's reading list" if want_list else "your safari bookmarks"
        return {"how": "reads %s: %d pages, each with its title and address%s" % (what, len(got), ", and the day it was saved" if want_list else ""),
                "detail": "", "why": "%s is empty" % what, "stats": {"found": len(got), "kept": len(got), "route": "disk"}}
    return fn


def browser_bookmarks(d, emit, trial, say, st, prev):
    from . import local_apps
    files = sorted({os.path.join(os.path.dirname(p), "Bookmarks") for _, p in local_apps.chromium_profiles()}
                   | set(glob.glob(os.path.join(glob.escape(local_apps.APPDATA), "*", "*", "Bookmarks")) + glob.glob(os.path.join(glob.escape(local_apps.APPDATA), "*", "*", "*", "Bookmarks"))))
    names = {os.path.join(local_apps.APPDATA, sub): name for name, sub in local_apps.CHROMIUM}
    done, n = set(), 0
    for path in files:
        browser = next((name for root, name in names.items() if path.startswith(root + os.sep)), "")
        if not browser:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                roots = (json.load(f).get("roots") or {})
        except (OSError, ValueError, AttributeError):
            continue
        stack = [(v, []) for v in roots.values() if isinstance(v, dict)]
        while stack:
            node, trail = stack.pop()
            if node.get("type") == "url" and node.get("url") and node["url"] not in done and node["url"].startswith(("http://", "https://")):
                done.add(node["url"])
                try:
                    ts = int(node.get("date_added") or 0) / 1e6 - WEBKIT_EPOCH
                except (TypeError, ValueError):
                    ts = 0
                name = str(node.get("name") or node["url"])
                text = "\n".join(x for x in (name, "in " + " / ".join(trail) if trail else "", node["url"]) if x)
                for r in _rows(d["slug"], _rid(d["slug"], node["url"]), node["url"], name, text, _iso(ts) if ts > 0 else ""):
                    emit(dict(r, kept="bookmark", browser=browser))
                n += 1
            for ch in node.get("children") or []:
                if isinstance(ch, dict):
                    stack.append((ch, trail + [str(node.get("name") or "")] if node.get("name") else trail))
    if not n and not files:
        raise Stop("cannot", "no chromium browser (arc, brave, chrome, dia, edge, opera, vivaldi) keeps bookmarks on this mac")
    return {"how": "reads the bookmarks of the browsers on this mac: %d, each with its title, folder, address and the day it was saved" % n,
            "detail": "", "why": "no bookmark is saved in those browsers", "stats": {"found": n, "kept": n, "route": "disk"}}


KEPT = {
    "mail_starred": ("starred mail", "the mail you starred or flagged, from apple mail on this mac (a gmail star arrives as a flag): sender, subject and text",
                     "starred star stars flagged flag mail gmail email important kept", mail_starred),
    "whatsapp_starred": ("starred whatsapp messages", "the messages you starred in whatsapp, each with its chat and date",
                         "starred star stars whatsapp kept saved", whatsapp_starred),
    "notes_pinned": ("pinned notes", "the notes you pinned in apple notes", "pinned pin pins notes kept", notes_pinned),
    "safari_reading_list": ("safari reading list", "the pages you saved to safari's reading list, with the day each was saved",
                            "reading list read later safari saved kept bookmarks", _safari_reader(True)),
    "safari_bookmarks": ("safari bookmarks", "your safari bookmarks: title, folder and address", "bookmarks bookmark safari favourites favorites saved", _safari_reader(False)),
    "browser_bookmarks": ("browser bookmarks", "the bookmarks of every chromium browser on this mac (arc, brave, chrome, dia, edge and others)",
                          "bookmarks bookmark arc brave chrome chromium dia edge opera vivaldi browser saved favourites favorites", browser_bookmarks),
}
NOT_YET = {"slack": "pinned and starred messages in slack are not read yet", "telegram": "telegram's saved messages are not read as their own source yet"}


def read(d, emit, trial, say, st, prev):
    if d["address"] not in KEPT:
        raise Stop("cannot", "no such built-in source")
    return KEPT[d["address"]][3](d, emit, trial, say, st, prev)


def match(q):
    """The built-in kept-things sources that what was typed asks for, best first: "starred", "gmail starred", "bookmarks"."""
    words = [w for w in str(q).lower().replace("-", " ").split() if len(w) >= 3]
    scored = []
    for key, (name, what, tags, _) in KEPT.items():
        tags = tags.split()
        hit = sum(2 if w in tags else 1 if any(t.startswith(w) for t in tags) else 0 for w in words)
        if hit and all(w in tags or any(t.startswith(w) for t in tags) for w in words):
            scored.append((-hit, list(KEPT).index(key), key))
    return [key for _, _, key in sorted(scored)]
