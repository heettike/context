"""One message in its conversation, for the app's peek. No model, nothing leaves the Mac, nothing is masked: this is
the owner's own app reading the owner's own archive (masking is for the MCP tools, where another program reads).

  python3 -m ctx thread <id> [--around N | --before N --after N] [--json]

A message id gives the message and N lines either side (default 15), oldest first. A doc id (note, bookmark,
saved post, prompt, session) gives that row whole with its url. Rows are found through an id index kept in
CTX_HOME/cache and rebuilt when any archive file changes, so a peek does not scan the archive.
"""
import array, calendar, hashlib, json, mmap, os, tempfile, time
from . import answer, paths

FILES = (paths.MESSAGES, paths.DOCS, paths.PROMPTS, paths.SESSIONS)
CACHE = os.path.join(paths.HOME, "cache", "ids.idx")


def _h(i):
    return int.from_bytes(hashlib.blake2b(str(i).encode(), digest_size=8).digest(), "little")


def _stamp():
    out = []
    for p in FILES:
        try:
            st = os.stat(p)
            out.append([st.st_size, st.st_mtime_ns])
        except OSError:
            out.append([0, 0])
    return out


def build():
    """(hash of id, file number and byte offset) for every row, sorted by hash. Written as: 8 bytes of header length,
    the header as JSON, then 16 bytes per row. A few seconds for a large archive, so the tick does it after each
    collect and a peek rarely has to."""
    stamp, pairs = _stamp(), []
    blake, add = hashlib.blake2b, pairs.append
    for n, path in enumerate(FILES):
        top = n << 56
        try:
            with open(path, "rb") as f:
                off = 0
                for line in f:
                    here, off = off, off + len(line)
                    i = line.find(b'"id": "')
                    if i < 0:
                        continue
                    raw = line[i + 7:line.find(b'"', i + 7)]
                    if b"\\" in raw:            # an id with an escape in it: read it the slow, exact way
                        try:
                            raw = str(json.loads(line).get("id")).encode()
                        except (ValueError, AttributeError):
                            continue
                    add((int.from_bytes(blake(raw, digest_size=8).digest(), "little"), top | here))
        except OSError:
            continue
    pairs.sort()
    flat = array.array("Q")
    for h, v in pairs:
        flat.append(h)
        flat.append(v)
    head = json.dumps({"v": 1, "stamp": stamp, "rows": len(pairs)}).encode()
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CACHE), suffix=".new")
        with os.fdopen(fd, "wb") as f:
            f.write(len(head).to_bytes(8, "little") + head + flat.tobytes())
        os.replace(tmp, CACHE)
    except OSError:
        pass
    return flat


def warm():
    """Bring both indexes up to date now, so the next peek is instant. Called at the end of a tick."""
    try:
        with open(CACHE, "rb") as f:
            n = int.from_bytes(f.read(8), "little")
            if json.loads(f.read(n)).get("stamp") == _stamp():
                answer.thread_index()
                return False
    except (OSError, ValueError):
        pass
    build()
    answer.thread_index()
    return True


def _lookup(rid):
    """Every (file number, offset) whose id hashes like this one. Usually one."""
    want, stamp = _h(rid), _stamp()
    try:
        with open(CACHE, "rb") as f:
            n = int.from_bytes(f.read(8), "little")
            head = json.loads(f.read(n))
            if head.get("stamp") != stamp or head.get("v") != 1:
                raise ValueError
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
                base, lo, hi = 8 + n, 0, head["rows"]
                key = lambda k: int.from_bytes(m[base + 16 * k:base + 16 * k + 8], "little")
                while lo < hi:
                    mid = (lo + hi) // 2
                    if key(mid) < want:
                        lo = mid + 1
                    else:
                        hi = mid
                out = []
                while lo < head["rows"] and key(lo) == want:
                    v = int.from_bytes(m[base + 16 * lo + 8:base + 16 * lo + 16], "little")
                    out.append((v >> 56, v & (1 << 56) - 1))
                    lo += 1
                return out
    except (OSError, ValueError, KeyError):
        flat = build()
        return [(flat[k + 1] >> 56, flat[k + 1] & (1 << 56) - 1) for k in range(0, len(flat), 2) if flat[k] == want]


def find(rid):
    """(file number, the row) for an id, or (None, None)."""
    for n, off in _lookup(rid):
        try:
            with open(FILES[n], "rb") as f:
                f.seek(off)
                d = json.loads(f.readline())
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and str(d.get("id")) == str(rid):
            return n, d
    return None, None


def _at(ts):
    try:
        return calendar.timegm(time.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S"))        # the archive keeps utc
    except (ValueError, TypeError):
        return 0


def thread(rid, before=15, after=15):
    """The row with that id in its place. {"thread", "title", "src", "focus", "open", "rows_total", "from", "to", "rows": [...]}
    where each row is {"id", "ts", "at", "who", "me", "sender", "text", "here"}; or {"error"}."""
    before, after = max(0, min(int(before), 500)), max(0, min(int(after), 500))
    n, d = find(rid)
    if d is None:
        return {"error": "no row with that id in your archive."}
    src = str(d.get("src") or "")
    if n != 0:      # a note, a bookmark, a saved post, a prompt, a session: the row itself, whole
        text = str(d.get("text") or " … ".join(str(d.get(k) or "") for k in ("first_user", "last_agent") if d.get(k)))
        ts = str(d.get("ts") or d.get("last_agent_ts") or "")
        mine = n == 2 or src in answer.OWN
        title = str(d.get("title") or d.get("thread") or d.get("project") or "")
        return {"thread": title, "title": title, "src": src, "focus": str(rid), "open": d.get("url") or None, "rows_total": 1, "from": ts[:10], "to": ts[:10],
                "rows": [{"id": str(rid), "ts": ts, "at": _at(ts), "who": "me" if mine else "saved" if src in answer.SAVED else "them", "me": mine,
                          "sender": "", "text": text, "here": True}]}
    tid = str(d.get("thread_id") or "")
    idx = answer.thread_index()
    t = idx["threads"].get(tid)
    if not t:
        return {"error": "that message's conversation is not in the index yet. try again."}
    offs = idx["offs"][t["at"][0]:t["at"][0] + t["at"][1]]
    rows = []
    from . import rules
    act = rules.active()
    with open(paths.MESSAGES, "rb") as f:
        where = None
        for k, off in enumerate(offs):          # where the message sits in its conversation: read only ids until it is found
            f.seek(off)
            line = f.readline()
            if (b'"id": ' + json.dumps(str(rid)).encode()) in line:
                where = k
                break
        if where is None:
            return {"error": "that message's conversation changed while reading. try again."}

        def at(k):             # the row at a place, when the owner's rules and the never list let it through
            f.seek(offs[k])
            try:
                m = json.loads(f.readline())
            except ValueError:
                return None
            return m if isinstance(m, dict) and not act.hides(m) else None
        older, newer = [], []           # its neighbours, counted among the rows a reader may see: one left out is not shown, nor counted
        for k in range(where - 1, -1, -1):
            if len(older) >= before:
                break
            m = at(k)
            if m is not None:
                older.append(m)
        for k in range(where, len(offs)):
            if len(newer) > after:
                break
            m = at(k)
            if m is not None:
                newer.append(m)
        for m in older[::-1] + newer:
            ts, me = str(m.get("ts") or ""), m.get("who") == "me"
            rows.append({"id": str(m.get("id", "")), "ts": ts, "at": _at(ts), "who": "me" if me else "them", "me": me,
                         "sender": "" if me else str(m.get("sender") or ""), "text": str(m.get("text") or ""), "here": str(m.get("id")) == str(rid)})
    return {"thread": t["thread"], "title": t["thread"], "src": t["src"], "kind": t["kind"], "focus": str(rid), "open": d.get("url") or None,
            "rows_total": t["n"], "from": t["from"], "to": t["to"], "rows": rows}


def main(args):
    num = lambda flag, default: next((int(args[i + 1]) for i, a in enumerate(args[:-1]) if a == flag and args[i + 1].isdigit()), default)
    ids = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] not in ("--around", "--before", "--after"))]
    if not ids:
        print(json.dumps({"error": "give a message id: thread <id> [--around N] [--json]"}))
        return 1
    around = num("--around", 15)
    out = thread(ids[0], num("--before", around), num("--after", around))
    if "--json" in args or "error" in out:
        print(json.dumps(out, ensure_ascii=False))
        return 1 if "error" in out else 0
    print(f'{out["thread"]} ({out["src"]}), {out["rows_total"]} rows, {out["from"]} to {out["to"]}')
    for r in out["rows"]:
        print(("> " if r["here"] else "  ") + f'{r["ts"][:16].replace("T", " ")} {"me" if r["me"] else (r["sender"] or r["who"])}: ' + " ".join(r["text"].split())[:300])
    if out["open"]:
        print(out["open"])
    return 0


# ---------------------------------------------------------------- the owner's rules (rules.py)

_find = find


def find(rid):
    """(file number, the row) for an id, or (None, None); also (None, None) for a row the owner's rules leave out."""
    from . import rules
    n, d = _find(rid)
    return (None, None) if d is not None and rules.hidden(d) else (n, d)
