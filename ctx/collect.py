"""Stream local sources to disk. One row at a time; every row passes through scrub() before it is written.

Collects everything each source holds, back to its first row. Windows (90 days for open loops) are applied
later, when questions are made, not here.
  messages.jsonl  chats with people
  sessions.jsonl  one summary per AI coding-agent session
  prompts.jsonl   every message the owner typed to an AI agent
  docs.jsonl      notes and saved things
A source that cannot be read is skipped with a one-line reason in status.json.
"""
import sys, glob, gzip, hashlib, json, os, re, sqlite3, threading, time
from datetime import datetime, timezone
from . import paths
from .scrub import scrub

APPLE = 978307200
H = os.path.expanduser
WA_DB = H("~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite")
IM_DB = H("~/Library/Messages/chat.db")
NOTES_DB = H("~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite")
CURSOR_DB = H("~/Library/Application Support/Cursor/User/globalStorage/state.vscdb")
FDA = "blocked by macOS: grant Full Disk Access to the app running this (System Settings > Privacy & Security)"


def since(days):
    return time.time() - days * 86400 if days else 0


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stable(text, digits=8):
    """A number that is the same on every run for the same text. (hash() is not: python salts it per process.)"""
    return int(hashlib.sha1(text.encode("utf-8", "surrogateescape")).hexdigest()[:15], 16) % 10 ** digits


def rid(prefix, *parts):
    """A row id made from what the row is (who, when, what), not from where it sat in a file: an export downloaded
    again with rows added keeps every old row's id."""
    return prefix + hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8", "surrogateescape")).hexdigest()[:14]


def ro(path):
    try:
        os.stat(path)
    except FileNotFoundError:
        raise FileNotFoundError("not installed or no data")
    except PermissionError:
        raise PermissionError(FDA)
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.execute("select 1 from sqlite_master limit 1").fetchall()
        return con
    except sqlite3.Error:
        raise PermissionError(FDA)


_tl = threading.local()     # which source this thread is reading, for live progress


def _say(obj):
    """A progress line for whoever is listening. A listener that went away (the app quit, a closed pipe) must not stop
    the read: a source that takes minutes to read is not skipped for a line nobody was there to see."""
    if getattr(_say, "deaf", False):
        return
    try:
        print("@" + json.dumps(obj, ensure_ascii=False), flush=True)
    except (BrokenPipeError, OSError, ValueError):
        _say.deaf = True
        try:
            sys.stdout = open(os.devnull, "w")       # so the interpreter's own flush at exit does not raise either
        except OSError:
            pass


def note(phase):
    """A source says what it is doing right now (shown live in the app)."""
    if getattr(_tl, "name", None):
        _say({"src": _tl.name, "phase": phase, "rows": getattr(_tl, "n", 0)})


def put(out, row):
    for k in ("text", "title", "first_user", "last_user", "last_agent"):
        if row.get(k):
            row[k] = scrub(row[k])
    out.write(json.dumps(row, ensure_ascii=False) + "\n")
    if out is getattr(_tl, "out", None):          # live progress: a few lines a second while a source is read
        _tl.n += 1
        now = time.monotonic()
        if now - _tl.t > 0.12:
            _tl.t = now
            ts = str(row.get("ts") or row.get("last_agent_ts") or "")
            _say({"src": _tl.name, "rows": _tl.n, "at": ts[:7],
                  "label": str(row.get("thread") or row.get("title") or os.path.basename(str(row.get("project") or "")))[:48]})


# ---------- messages ----------

def _names():
    """The name book (ctx/namebook.py): whose number or address is this. Built if it is missing or hours old."""
    from . import namebook
    return namebook, namebook.fresh()


def whatsapp(days, out):
    """A chat whatsapp knows only by a number is called by the person's name when the name book has one, and so is
    whoever wrote a message in a group. The thread's id does not change."""
    con, n = ro(WA_DB), 0
    nb, book = _names()
    cols = lambda t: {r[1] for r in con.execute('pragma table_info("%s")' % t)}
    mine = dict(con.execute("select ZCHATSESSION, count(*) from ZWAMESSAGE where ZISFROMME=1 group by 1"))
    jid_col = "ZCONTACTJID" if "ZCONTACTJID" in cols("ZWACHATSESSION") else "''"
    chats = {pk: (nb.thread_name(name, jid, book) if stype == 0 else name, stype)
             for pk, name, stype, jid in con.execute("select Z_PK, ZPARTNERNAME, ZSESSIONTYPE, %s from ZWACHATSESSION" % jid_col)}
    members = {}
    if "ZGROUPMEMBER" in cols("ZWAMESSAGE") and "ZMEMBERJID" in cols("ZWAGROUPMEMBER"):
        members = {pk: str(jid or "") for pk, jid in con.execute("select Z_PK, ZMEMBERJID from ZWAGROUPMEMBER")}
    said = {}       # who wrote in a group: their name, else the end of their number as before
    q = "select Z_PK, ZMESSAGEDATE, ZISFROMME, ZTEXT, ZFROMJID, ZCHATSESSION, %s from ZWAMESSAGE where ZMESSAGEDATE>? and ZTEXT is not null" % ("ZGROUPMEMBER" if members else "null")
    for pk, ts, me, text, jid, spk, member in con.execute(q, (since(days) - APPLE,)):
        name, stype = chats.get(spk, ("?", 0))
        if stype not in (0, 1):
            continue
        who = members.get(member) or jid or ""
        if who not in said:
            said[who] = (nb.name_for(who, book) if stype == 1 else "") or who.split("@")[0][-4:]
        put(out, {"id": f"W{pk}", "src": "whatsapp", "ts": iso(ts + APPLE), "thread_id": f"wa{spk}", "thread": name or "?",
                  "kind": "group" if stype == 1 else "dm", "mine_total": mine.get(spk, 0), "who": "me" if me else "them",
                  "sender": "" if me else said[who], "text": text})
        n += 1
    return n


def _attributed(blob):
    """Newer iMessages keep the text in a typedstream blob. Pull the first NSString out of it."""
    try:
        i = blob.index(b"NSString") + 8
        i = blob.index(b"+", i) + 1
        n = blob[i]
        if n == 0x81:
            n, i = int.from_bytes(blob[i + 1:i + 3], "little"), i + 2
        return blob[i + 1:i + 1 + n].decode("utf-8", "ignore")
    except (ValueError, IndexError):
        return ""


def imessage(days, out):
    con, n = ro(IM_DB), 0
    nb, book = _names()
    named = {}      # a thread known only by a number or an address takes the person's name from the name book
    mine_by = dict(con.execute("""select j.chat_id, count(*) from chat_message_join j join message m on m.ROWID=j.message_id
                                  where m.is_from_me=1 group by 1"""))
    q = """select m.ROWID, m.date, m.is_from_me, m.text, m.attributedBody, c.ROWID, coalesce(nullif(c.display_name,''), c.chat_identifier), c.style
           from message m join chat_message_join j on j.message_id=m.ROWID join chat c on c.ROWID=j.chat_id where m.date>?"""
    for pk, ts, me, text, blob, cid, name, style in con.execute(q, ((since(days) - APPLE) * 1e9,)):
        text = text or (_attributed(blob) if blob else "")
        if not text or text == "￼":
            continue
        if cid not in named:
            named[cid] = nb.thread_name(name, book=book) if style != 43 else name
        name = named[cid]
        put(out, {"id": f"I{pk}", "src": "imessage", "ts": iso(ts / 1e9 + APPLE), "thread_id": f"im{cid}", "thread": name or "?",
                  "kind": "group" if style == 43 else "dm", "mine_total": mine_by.get(cid, 0), "who": "me" if me else "them",
                  "sender": "", "text": text})
        n += 1
    return n


class _telegram_client:
    """A connected, logged-in client, or one plain reason. Never telethon's own prompt for a phone number."""
    def __init__(self, cls):
        from . import llm  # loads .env
        api_id, api_hash = os.environ.get("TELEGRAM_API_ID", ""), os.environ.get("TELEGRAM_API_HASH", "")
        if not api_id.strip().isdigit() or not api_hash.strip():
            raise FileNotFoundError("needs TELEGRAM_API_ID (a number) and TELEGRAM_API_HASH in .env (my.telegram.org > api development tools)")
        self.tg = cls(os.path.join(paths.HOME, "telegram"), int(api_id), api_hash.strip())

    def __enter__(self):
        self.tg.connect()
        if not self.tg.is_user_authorized():
            self.tg.disconnect()
            raise PermissionError("not logged in: sign in to telegram once with the sign-in card in the app's sources page")
        return self.tg

    def __exit__(self, *a):
        self.tg.disconnect()


def _packages_pinned(site, told=None):
    """May telegram's packages be loaded from this folder? They run inside a process that can read the whole archive, so
    the folder must belong to this account and be writable by no one else, and its code must be what it was the first time
    it was used: a sha256 over it is kept in packages.pin beside the archive. Different code is not loaded; the message
    says how to accept it if the owner changed it themselves. told: a list the reason is added to as well."""
    from . import guard

    def say(said):
        note(said)
        if told is not None:
            told.append(said)
    why = guard.packages_ok(site)
    if why:
        say("telegram's packages were not loaded: %s" % why)
        return False
    pin, now = os.path.join(paths.HOME, "packages.pin"), guard.tree_hash(site)
    try:
        with open(pin) as f:
            pins = json.load(f)
    except (OSError, ValueError):
        pins = {}
    if not isinstance(pins, dict):
        pins = {}
    if site not in pins:
        pins[site] = now
        try:
            with os.fdopen(os.open(pin + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
                json.dump(pins, f)
            os.replace(pin + ".new", pin)
        except OSError:
            pass
        return True
    if pins[site] != now:
        say("telegram's packages were not loaded: the code in %s is not what was first installed. if you updated it yourself, remove packages.pin from the archive folder and run this again" % os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(site)))))
        return False
    return True


def telegram_packages():
    """Telegram's packages (telethon, qrcode) put on sys.path, from a folder of paths.venv_sites() only when _packages_pinned
    passes it: ours alone, writable by no one else, holding the code first installed there. Every path that imports them
    goes through here first: the collector, the app's sign-in card (telegram_login) and the sign-in in a terminal.
    Returns why a folder was passed over, "" when none was: a caller that then finds no telethon says that, not "install it"."""
    told = []
    for s in paths.venv_sites():
        if _packages_pinned(s, told) and s not in sys.path:
            sys.path.append(s)
    return "; ".join(told)


def _telethon():
    """telethon's client class, from this python or the repo's .venv; None when it is not installed."""
    try:
        from telethon.sync import TelegramClient
    except ImportError:
        telegram_packages()          # only a folder that is ours alone and holds what was first installed
        try:
            from telethon.sync import TelegramClient
        except ImportError:
            return None
    return TelegramClient


def telegram(days, out):
    """Needs telegram's packages (requirements-telegram.txt), TELEGRAM_API_ID / TELEGRAM_API_HASH in .env, and one login: python3 -m ctx telegram-login."""
    TelegramClient = _telethon()
    if TelegramClient is None:
        raise FileNotFoundError("needs setup: python3 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements-telegram.txt")
    n, k, since_dt = 0, 0, datetime.fromtimestamp(since(days), timezone.utc)
    with _telegram_client(TelegramClient) as tg:
        for d in tg.iter_dialogs():
            k += 1
            ent = d.entity
            if (d.is_channel and not d.is_group) or getattr(ent, "bot", False) or (d.date and d.date < since_dt):
                continue          # broadcast channels and bots are not conversations
            big = d.is_group and (getattr(ent, "participants_count", 0) or 0) > 300
            # people and small groups: everything. big public groups: only what the owner wrote there.
            it = tg.iter_messages(d, from_user="me", limit=3000) if big else tg.iter_messages(d, limit=None if d.is_user else 5000)
            rows = []
            for m in it:
                if m.date < since_dt:
                    break
                if m.message:
                    rows.append({"id": f"T{d.id}_{m.id}", "src": "telegram", "ts": iso(m.date.timestamp()), "thread_id": f"tg{d.id}",
                                 "thread": d.name or "?", "kind": "group" if d.is_group else "dm", "who": "me" if m.out else "them",
                                 "sender": "" if m.out else str(m.sender_id or "")[-4:], "text": m.message})
            mine = sum(r["who"] == "me" for r in rows)
            for r in reversed(rows):
                put(out, dict(r, mine_total=mine + 3 if not d.is_group and mine else mine))
            n += len(rows)
            if k % 25 == 0:
                out.flush()
                print(f"  telegram: {k} chats, {n} messages", flush=True)
    return n


def telegram_new():
    """Only what arrived since the saved export. Seconds to a few minutes, against hours for a full export.
    Appends to imports/telegram_full.jsonl. Returns {"new", "state", "detail"}."""
    full = os.path.join(paths.HOME, "imports", "telegram_full.jsonl")
    part = full + ".part"
    if not os.path.exists(full):
        return {"new": 0, "state": "skipped", "detail": "telegram needs its first full export"}
    if os.path.exists(part) and time.time() - os.path.getmtime(part) < 600:
        return {"new": 0, "state": "skipped", "detail": "a full telegram export is running"}
    if not os.path.exists(os.path.join(paths.HOME, "telegram.session")):
        return {"new": 0, "state": "needs_you", "detail": "telegram needs one login"}
    TelegramClient = _telethon()
    if TelegramClient is None:
        return {"new": 0, "state": "skipped", "detail": "telethon is not installed"}
    last, mine = {}, {}
    with open(full) as f:
        for line in f:
            m = re.match(r'\{"id": "T(-?\d+)_(\d+)"', line)
            if not m:
                continue
            d, i = int(m.group(1)), int(m.group(2))
            last[d] = max(i, last.get(d, 0))
            mine[d] = mine.get(d, 0) + ('"who": "me"' in line)
    new, quiet = [], 0
    try:
        client = _telegram_client(TelegramClient)
        tg = client.__enter__()
    except FileNotFoundError as e:
        return {"new": 0, "state": "needs_you", "detail": str(e)}
    except PermissionError:
        return {"new": 0, "state": "needs_you", "detail": "telegram needs one login: use the sign-in card in the app's sources page"}
    try:
        for d in tg.iter_dialogs():                    # newest activity first
            ent = d.entity
            if (d.is_channel and not d.is_group) or getattr(ent, "bot", False):
                continue
            top = d.message.id if d.message else 0
            if top <= last.get(d.id, 0):
                quiet += 1
                if quiet >= 40:                         # forty unchanged chats in a row: the rest are older still
                    break
                continue
            quiet = 0
            big = d.is_group and (getattr(ent, "participants_count", 0) or 0) > 300
            it = tg.iter_messages(d, from_user="me", min_id=last.get(d.id, 0), limit=3000) if big else tg.iter_messages(d, min_id=last.get(d.id, 0), limit=5000)
            rows = [m for m in it if m.message]
            me = mine.get(d.id, 0) + sum(1 for m in rows if m.out)
            for m in reversed(rows):
                new.append({"id": f"T{d.id}_{m.id}", "src": "telegram", "ts": iso(m.date.timestamp()), "thread_id": f"tg{d.id}",
                            "thread": d.name or "?", "kind": "group" if d.is_group else "dm", "who": "me" if m.out else "them",
                            "sender": "" if m.out else str(m.sender_id or "")[-4:], "text": scrub(m.message),
                            "mine_total": me + 3 if not d.is_group and me else me})
            note(f"telegram: {len(new)} new messages")
    finally:
        client.__exit__()
    if new:
        with open(full, "a") as f:
            for r in new:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"new": len(new), "state": "ok", "detail": ""}


# ---------- agent sessions ----------

def _noise(t):
    t = t.lstrip()
    return (not t or t.startswith("<") or t.startswith("[Request interrupted") or t.startswith("Caveat:")
            or t.startswith("This session is being continued") or t.startswith("Base directory for this skill"))


def sid(prefix, raw, tail=False):
    """A session id from the app's own id: up to 16 of its letters and digits (the first, or the last when the name
    starts with a date). Eight were too few: two sessions could share them and one would overwrite the other's rows."""
    clean = re.sub(r"[^0-9A-Za-z]", "", str(raw))
    return prefix + (clean[-16:] if tail else clean[:16])


def _session(sid, src):
    return {"id": sid, "src": src, "title": "", "project": "", "first_user": "", "last_user": "", "last_user_ts": "",
            "last_agent": "", "last_agent_ts": "", "user_turns": 0}




def _turn(s, role, txt, ts):
    prompts = getattr(_tl, "prompts", None)
    if role == "user" and prompts and len(txt) < 6000:
        put(prompts, {"id": f'{s["id"]}:{s["user_turns"]}', "src": s["src"], "ts": ts, "thread": os.path.basename(s["project"]) or s["title"],
                      "who": "me", "text": txt})
    if role == "user":
        s["user_turns"] += 1
        s["first_user"] = s["first_user"] or txt[:600]
        s["last_user"], s["last_user_ts"] = txt[:600], ts
    else:
        s["last_agent"], s["last_agent_ts"] = txt[-1800:], ts


def _keep(out, s):
    """Write a session that has both sides of a conversation; 1 if written. A session with no reply is not worth a row."""
    if not (s["user_turns"] and s["last_agent"]):
        return 0
    put(out, s)
    return 1


def _lines(f):
    with open(f) as fh:
        for line in fh:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _recent(pattern, days):
    cutoff = since(days)
    return [f for f in glob.glob(H(pattern)) if os.path.getmtime(f) > cutoff]


def claude_code(days, out):
    n = 0
    for f in _recent("~/.claude/projects/*/*.jsonl", days):
        s = _session(sid("C", os.path.basename(f)[:-6]), "claude_code")
        for d in _lines(f):
            t = d.get("type")
            if t in ("custom-title", "summary"):
                s["title"] = d.get("customTitle") or d.get("summary") or s["title"]
            if d.get("isSidechain") or d.get("isMeta") or t not in ("user", "assistant"):
                continue
            s["project"] = d.get("cwd") or s["project"]
            c = (d.get("message") or {}).get("content")         # a string, or blocks of which only the text ones are words
            texts = [c] if isinstance(c, str) else [b.get("text", "") for b in c or [] if isinstance(b, dict) and b.get("type") == "text"]
            txt = "\n".join(x for x in texts if not _noise(x)).strip()
            if txt:
                _turn(s, t, txt, d.get("timestamp") or "")
        n += _keep(out, s)
    return n


def claude_history(days, out):
    """What the owner typed to Claude Code, from its own list of prompts (~/.claude/history.jsonl). Claude Code deletes a
    session's transcript after a month but keeps this list, so it reaches back further than the sessions do. A prompt
    whose session is still on disk is left to the session reader, which has it with its place in the conversation."""
    path = H("~/.claude/history.jsonl")
    if not os.path.exists(path):
        raise FileNotFoundError("not installed or no data")
    have = {os.path.basename(f)[:-6] for f in glob.glob(H("~/.claude/projects/*/*.jsonl"))}
    cutoff, n = since(days), 0
    for d in _lines(path):
        if not isinstance(d, dict):
            continue
        text, at, session = str(d.get("display") or "").strip(), d.get("timestamp"), str(d.get("sessionId") or "")
        if not isinstance(at, (int, float)) or session in have:
            continue
        at = at / 1000 if at > 1e11 else at
        if at < cutoff or text.startswith("/") or _noise(text):        # a slash command is an instruction to the tool, not words
            continue
        put(out, {"id": rid("CH", session, int(at), text[:80]), "src": "claude_code", "ts": iso(at), "thread": os.path.basename(str(d.get("project") or "")),
                  "who": "me", "text": text[:6000]})
        n += 1
    return n


def _codex_lines(path):
    """The lines of one codex session file. Codex packs older ones away as .zst, which python can open from 3.14 on;
    before that those files are left out (the history database below holds the same sessions)."""
    if path.endswith(".zst"):
        try:
            from compression import zstd
        except ImportError:
            return
        try:
            with zstd.open(path, "rt", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    yield line
        except (OSError, EOFError, ValueError):
            return
    else:
        with open(path, errors="replace") as fh:
            for line in fh:
                yield line


def _codex_head(path):
    """(folder it worked in, was it started by another agent) from the first lines of a session file."""
    for k, line in enumerate(_codex_lines(path)):
        try:
            d = json.loads(line)
        except ValueError:
            d = {}
        if d.get("type") == "session_meta":
            p = d.get("payload") or {}
            return p.get("cwd") or "", isinstance(p.get("source"), dict)       # a session a person started names its source in a word
        if k >= 4:
            break
    return "", False


def _codex_text(blocks):
    return "\n".join(b.get("text") or "" for b in blocks or [] if isinstance(b, dict) and b.get("type") in ("text", "input_text", "output_text")).strip()


def _codex_file(path, s):
    """Fill a session from its file. Two shapes: event lines (user_message, agent_message), and, in newer files that
    have none of those, the messages themselves (response_item, role user or assistant)."""
    events, items = [], []
    for line in _codex_lines(path):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        p, ts = d.get("payload") or {}, d.get("timestamp") or ""
        if d.get("type") == "session_meta":
            s["project"] = p.get("cwd") or s["project"]
        elif d.get("type") == "event_msg" and p.get("type") in ("user_message", "agent_message"):
            events.append(("user" if p["type"] == "user_message" else "assistant", (p.get("message") or "").strip(), ts))
        elif d.get("type") == "response_item" and p.get("type") == "message" and p.get("role") in ("user", "assistant"):
            items.append((p["role"], _codex_text(p.get("content")), ts))
    turns = [(role, txt, ts) for role, txt, ts in events or items if txt and not (role == "user" and _noise(txt))]
    if any(r == "user" for r, _, _ in turns) and any(r == "assistant" for r, _, _ in turns):       # a one-sided session leaves nothing, not even in the list of what was typed
        for role, txt, ts in turns:
            _turn(s, role, txt, ts)


def codex(days, out):
    """Codex sessions the owner started. The app keeps every thread in a database (~/.codex/thread_history_*.sqlite) and
    only the recent ones as files, so the database is read first and the files fill in what it lacks. A thread another
    agent started (its prompts were not typed by the owner) is left out: its file says so, and a thread with no file
    counts as the owner's only when one of its messages came from the app's own input box."""
    files = _recent("~/.codex/sessions/*/*/*/*.jsonl", days) + _recent("~/.codex/archived_sessions/*.jsonl.zst", days)
    key = lambda f: os.path.basename(f).split(".jsonl")[0][-36:]
    head = {key(f): _codex_head(f) for f in files}
    cutoff, done, n = since(days) * 1000, set(), 0
    for db in sorted(glob.glob(H("~/.codex/thread_history_*.sqlite"))):
        try:
            con = ro(db)
            rows = con.execute("select thread_id, item_type, item_json, created_at_ms from thread_items "
                               "where item_type in ('userMessage', 'agentMessage') order by thread_id, rollout_ordinal")
        except (FileNotFoundError, PermissionError, sqlite3.Error):
            continue
        cur, turns, typed, last = None, [], False, 0

        def close():        # nothing is written, not even to the list of what the owner typed, until the thread is known to be theirs
            cwd, sub = head.get(cur, ("", False))
            if cur is None or cur in done or sub or not (typed or cur in head) or last < cutoff:
                return 0
            s = _session(sid("X", cur, tail=True), "codex")
            s["project"] = cwd
            if any(r == "user" for r, _, _ in turns) and any(r == "assistant" for r, _, _ in turns):
                for role, txt, ts in turns:
                    _turn(s, role, txt, ts)
            done.add(cur)
            return _keep(out, s)
        try:
            for tid, typ, raw, ms in rows:
                if tid != cur:
                    n += close()
                    cur, turns, typed, last = tid, [], False, 0
                try:
                    d = json.loads(raw)
                except ValueError:
                    continue
                ts, last = iso((ms or 0) / 1000) if ms else "", max(last, ms or 0)
                if typ == "userMessage":
                    txt = _codex_text(d.get("content"))
                    typed = typed or bool(d.get("clientId"))
                    if txt and not _noise(txt):
                        turns.append(("user", txt, ts))
                elif (d.get("text") or "").strip():
                    turns.append(("assistant", d["text"].strip(), ts))
            n += close()
        except sqlite3.Error:
            pass
        finally:
            con.close()
    for f in files:
        if key(f) in done or head[key(f)][1]:
            continue
        s = _session(sid("X", key(f), tail=True), "codex")
        _codex_file(f, s)
        done.add(key(f))
        n += _keep(out, s)
    return n


def cursor(days, out):
    con, n, cutoff = ro(CURSOR_DB), 0, since(days) * 1000
    for key, val in con.execute("select key, value from cursorDiskKV where key like 'composerData:%'"):
        try:
            c = json.loads(val)
        except (TypeError, json.JSONDecodeError):
            continue
        last = c.get("lastUpdatedAt") or c.get("createdAt") or 0
        if last < cutoff:
            continue
        cid = c.get("composerId") or key.split(":", 1)[1]
        s = _session(sid("U", cid), "cursor")
        s["title"], ts = c.get("name") or "", iso(last / 1000)
        for h in c.get("fullConversationHeadersOnly") or []:
            row = con.execute("select value from cursorDiskKV where key=?", (f"bubbleId:{cid}:{h.get('bubbleId')}",)).fetchone()
            try:
                b = json.loads(row[0]) if row and row[0] else {}
            except json.JSONDecodeError:
                continue
            if (b.get("text") or "").strip():
                _turn(s, "user" if b.get("type") == 1 else "assistant", b["text"].strip(), ts)
        n += _keep(out, s)
    return n


# ---------- docs ----------

def obsidian(days, out):
    cfg = H("~/Library/Application Support/obsidian/obsidian.json")
    if not os.path.exists(cfg):
        raise FileNotFoundError("not installed")
    n, cutoff = 0, since(days)
    try:
        vaults = [v.get("path") for v in (paths.read_json(cfg, encoding="utf-8").get("vaults") or {}).values() if isinstance(v, dict) and v.get("path")]
    except (OSError, ValueError, AttributeError):
        raise FileNotFoundError("obsidian's list of vaults could not be read")
    if not vaults:
        raise FileNotFoundError("obsidian has no vault yet")
    denied = 0
    for root in vaults:
        try:
            os.listdir(root)      # macos can keep an app out of the folder a vault is in; glob would then just find nothing
        except PermissionError:
            raise PermissionError(FDA)
        except OSError:
            continue
        for f in glob.glob(os.path.join(glob.escape(root), "**", "*.md"), recursive=True):
            try:
                mt = os.path.getmtime(f)
                if mt <= cutoff:
                    continue
                put(out, {"id": f"O{stable(f)}", "src": "obsidian", "ts": iso(mt),
                          "title": os.path.basename(f)[:-3], "text": paths.read_text(f, encoding="utf-8", errors="ignore")[:20000]})
                n += 1
            except PermissionError:
                denied += 1
            except OSError:      # a file in icloud that is not downloaded, or one that went away
                continue
    if denied and not n:        # macos lists the vault but will not let this app open the notes in it
        raise PermissionError("macos is keeping this app out of the folder your vault is in (documents or desktop): allow it in privacy & security > files and folders")
    return n


def journal(days, out):
    """What the owner wrote in the app's plan tab, one row per day."""
    files = sorted(glob.glob(os.path.join(paths.HOME, "journal", "*.md")))
    if not files:
        raise FileNotFoundError("nothing written in the plan tab yet")
    n = 0
    for f in files:
        text, day = paths.read_text(f, errors="ignore").strip(), os.path.basename(f)[:-3]
        if not text:
            continue
        put(out, {"id": "J" + day, "src": "journal", "ts": day + "T12:00:00Z", "title": "plan " + day, "who": "me", "text": text[:20000]})
        n += 1
    return n


def _varint(b, i):
    v = s = 0
    while True:
        v |= (b[i] & 0x7F) << s
        i += 1
        if not b[i - 1] & 0x80:
            return v, i
        s += 7


def _field(b, want):
    """First length-delimited protobuf field numbered `want`."""
    i = 0
    while i < len(b):
        tag, i = _varint(b, i)
        num, wt = tag >> 3, tag & 7
        if wt == 0:
            _, i = _varint(b, i)
        elif wt == 2:
            n, i = _varint(b, i)
            if num == want:
                return b[i:i + n]
            i += n
        elif wt == 1:
            i += 8
        elif wt == 5:
            i += 4
        else:
            return b""
    return b""


def apple_notes(days, out):
    try:
        con, n = ro(NOTES_DB), 0
    except PermissionError:   # no Full Disk Access: ask Notes itself
        from . import applescript
        return applescript.notes(days, out)
    q = """select o.Z_PK, o.ZTITLE1, o.ZMODIFICATIONDATE1, d.ZDATA from ZICCLOUDSYNCINGOBJECT o
           join ZICNOTEDATA d on d.ZNOTE=o.Z_PK where o.ZMODIFICATIONDATE1>? and d.ZDATA is not null
           and coalesce(o.ZMARKEDFORDELETION,0)=0 and coalesce(o.ZISPASSWORDPROTECTED,0)=0"""
    for pk, title, ts, data in con.execute(q, (since(days) - APPLE,)):
        try:
            text = _field(_field(_field(gzip.decompress(data), 2), 3), 2).decode("utf-8", "ignore")
        except (OSError, IndexError):
            continue
        if not text.strip():
            continue
        put(out, {"id": f"N{pk}", "src": "apple_notes", "ts": iso(ts + APPLE), "title": title or "", "text": text[:20000]})
        n += 1
    return n


def _import(name):
    p = os.path.join(paths.HOME, "imports", name)
    if not os.path.exists(p):
        raise FileNotFoundError(f"no imports/{name} yet: python3 -m ctx tick daily reads it from your signed-in browser (docs/PERMISSIONS.md)")
    return paths.read_json(p), os.path.getmtime(p)


def x_bookmarks(days, out):
    """imports/bookmarks.json: list of {u: url, d: iso date, n: author, t: text, l: [links]} read from x.com/i/bookmarks."""
    rows, mt = _import("bookmarks.json")
    for b in rows:
        put(out, {"id": "B" + b["u"].rsplit("/", 1)[-1], "src": "x_bookmarks", "ts": (b.get("d") or iso(mt))[:19] + "Z",
                  "title": (b.get("n") or "").replace("\n", " "), "text": ((b.get("t") or "") + " " + " ".join(b.get("l") or [])).strip()[:2000],
                  "url": b["u"]})
    return len(rows)


def _x_web(file, src, prefix):
    """imports/<file>: posts read from the owner's own x pages by the extension (signed_in.py). Ids match the x archive's,
    so the same post from both is one row."""
    def read(days, out):
        rows, mt = _import(file)
        skip = set()
        if file == "x_replies.json":        # a reply in the owner's own thread is on their profile too: the posts file has it
            try:
                skip = {b["u"].rsplit("/", 1)[-1] for b in _import("x_posts.json")[0]}
            except (FileNotFoundError, ValueError):
                pass
        n = 0
        for b in rows:
            if b["u"].rsplit("/", 1)[-1] in skip:
                continue
            mine = src == "x_posts"
            put(out, {"id": prefix + b["u"].rsplit("/", 1)[-1], "src": src, "ts": (b.get("d") or iso(mt))[:19] + "Z",
                      "title": "reply to @" + b["r"] if mine and b.get("r") else (b.get("n") or "").replace("\n", " "),       # as the x archive titles a reply
                      "text": ((b.get("t") or "") + " " + " ".join(b.get("l") or [])).strip()[:2000],
                      "url": b["u"], "who": "me" if mine else ""})
            n += 1
        return n
    return read


def _import_messages(name, src):
    """imports/<name>.jsonl written by the host agent from a signed-in browser tab. Rows already have the message shape."""
    def f(days, out):
        p = os.path.join(paths.HOME, "imports", name)
        if not os.path.exists(p):
            raise FileNotFoundError(f"no imports/{name} yet: python3 -m ctx tick daily reads it from your signed-in browser (docs/PERMISSIONS.md)")
        rows = [json.loads(l) for l in paths.read_lines(p)]
        mine = {}
        for r in rows:
            mine[r["thread_id"]] = mine.get(r["thread_id"], 0) + (r["who"] == "me")
        rows.sort(key=lambda r: r["ts"])
        for r in rows:
            if not isinstance(r["ts"], str):
                r["ts"] = iso(r["ts"])
            if src == "slack":   # <@U123> mentions are noise without the name map
                r["text"] = re.sub(r"<@[A-Z0-9]+\|?([^>]*)>", lambda m: "@" + (m.group(1) or "someone"), r["text"])
            put(out, dict(r, src=src, mine_total=mine[r["thread_id"]] + (3 if r["kind"] == "dm" and mine[r["thread_id"]] else 0)))
        return len(rows)
    return f


def _import_docs(name, src):
    """imports/<name>.jsonl of {id, ts, title, text} rows written by the host agent (Drive docs, calendar events)."""
    def f(days, out):
        p = os.path.join(paths.HOME, "imports", name)
        if not os.path.exists(p):
            raise FileNotFoundError(f"no imports/{name} yet: python3 -m ctx tick daily reads it (docs/PERMISSIONS.md)")
        n = 0
        for line in paths.read_lines(p):
            r = json.loads(line)
            put(out, {"id": r["id"], "src": src, "ts": (r.get("ts") or "")[:19] + "Z", "title": r.get("title") or "", "text": (r.get("text") or "")[:20000]})
            n += 1
        return n
    return f


def _telegram_any(days, out):
    """Telegram rows from the last full API export (`python3 -m ctx collect-telegram`), else the browser-read files.
    A full export takes hours, so a normal collect never starts one: it reuses the saved copy."""
    for name in ("telegram_full.jsonl", "telegram_history.jsonl", "telegram.jsonl"):
        if os.path.exists(os.path.join(paths.HOME, "imports", name)):
            return _import_messages(name, "telegram")(days, out)
    raise FileNotFoundError("needs setup: sign in once with the sign-in card in the app's sources page, then telegram's first full export (python3 -m ctx collect-telegram)")


def _lazy(module, fn, *extra):
    def call(days, out):
        f = getattr(__import__("ctx." + module, fromlist=["x"]), fn)
        return f(days, out, *[getattr(_tl, e, None) for e in extra])
    return call


def _linkedin(name):
    """One of the kinds of thing a complete linkedin export holds: ctx/linkedin.py."""
    def call(days, out):
        from . import linkedin
        return linkedin.READERS[name](days, out)
    return call


def _instagram_posts_web(file, src, prefix):
    """imports/<file>: posts the owner saved or liked, read from instagram.com (signed_in.py). Ids match the export's."""
    def read(days, out):
        rows, mt = _import(file)
        for b in rows:
            code = str(b["id"])
            put(out, {"id": prefix + code[:24], "src": src, "ts": iso(b.get("at") or mt), "title": b.get("user") or "", "text": (b.get("text") or "")[:2000],
                      "url": "https://www.instagram.com/%s/%s/" % ("reel" if b.get("reel") else "p", code)})
        return len(rows)
    return read


# every source, in reading order: (name, which file it belongs to, function)
M, S, P, D = paths.MESSAGES, paths.SESSIONS, paths.PROMPTS, paths.DOCS
TABLE = [
    ("whatsapp", M, whatsapp), ("imessage", M, imessage), ("telegram", M, _telegram_any),
    ("slack", M, _import_messages("slack.jsonl", "slack")), ("x_dms", M, _lazy("exports", "x_archive_dms")),
    ("instagram", M, _lazy("exports", "instagram_dms")), ("linkedin", M, _lazy("exports", "linkedin_dms")),
    ("gmail_takeout", M, _lazy("exports", "gmail_takeout", "index")), ("email", M, _lazy("mail", "mail", "index")),
    ("claude_code", S, claude_code), ("codex", S, codex), ("cursor", S, cursor), ("grok_bot", S, _lazy("local_apps", "grok_bot")),
    ("grok_bot_prompts", P, _lazy("local_apps", "grok_bot_prompts")), ("claude_history", P, claude_history), ("chatgpt_export", S, _lazy("local_apps", "chatgpt_export")),
    ("chatgpt_export_prompts", P, _lazy("local_apps", "chatgpt_export_prompts")),
    ("browser_history", D, _lazy("local_apps", "browser_history")), ("safari_history", D, _lazy("local_apps", "safari_history")),
    ("journal", D, journal), ("obsidian", D, obsidian), ("apple_notes", D, apple_notes),
    ("contacts", D, _lazy("apple", "contacts")), ("reminders", D, _lazy("apple", "reminders")), ("calls", D, _lazy("apple", "calls")),
    ("voice_memos", D, _lazy("apple", "voice_memos")), ("x_bookmarks", D, x_bookmarks),
    ("instagram_saved", D, _lazy("exports", "instagram_saved")), ("instagram_likes", D, _lazy("exports", "instagram_likes")),
    ("instagram_saved_web", D, _instagram_posts_web("instagram_saved_web.json", "instagram_saved", "IS")),
    ("x_web_likes", D, _x_web("x_likes.json", "x_likes", "L")), ("x_web_posts", D, _x_web("x_posts.json", "x_posts", "P")),
    ("x_web_replies", D, _x_web("x_replies.json", "x_posts", "P")),
    ("x_archive", D, _lazy("exports", "x_archive_docs")), ("google_takeout", D, _lazy("exports", "takeout_docs")),
    ("linkedin_connections", D, _lazy("exports", "linkedin_connections")),
    ("linkedin_posts", D, _linkedin("linkedin_posts")), ("linkedin_comments", D, _linkedin("linkedin_comments")), ("linkedin_articles", D, _linkedin("linkedin_articles")),
    ("linkedin_invitations", D, _linkedin("linkedin_invitations")), ("linkedin_recommendations", D, _linkedin("linkedin_recommendations")), ("linkedin_saved", D, _linkedin("linkedin_saved")),
    ("linkedin_likes", D, _linkedin("linkedin_likes")), ("linkedin_searches", D, _linkedin("linkedin_searches")), ("linkedin_profile", D, _linkedin("linkedin_profile")),
    ("notion", D, _lazy("exports", "notion_docs")),
    ("gdrive", D, _import_docs("gdrive.jsonl", "gdrive")), ("calendar", D, _import_docs("calendar.jsonl", "calendar")),
    ("media_images", D, _lazy("media", "images")), ("media_audio", D, _lazy("media", "audio")),      # pictures, voice notes, files and
    ("media_files", D, _lazy("media", "files")), ("media_video", D, _lazy("media", "video")),        # videos on this mac: ctx/media.py
]
try:     # sources the owner added themselves (ctx connect): vetted readers, each run in a child process
    from . import connect as _connect
    for _slug, _kind in _connect.enabled():
        TABLE.append(("custom_" + _slug, M if _kind == "messages" else D, _connect.reader(_slug)))
except Exception:       # a broken custom reader must never stop the built-in sources
    pass
BY_NAME = {n: (g, f) for n, g, f in TABLE}


def load_canvas():
    """Sources the owner pointed at themselves (a website, a feed, a folder, a file, their own notes): ctx/canvas.py. Each is a
    docs source named canvas_<slug>. Called again whenever one is switched on, off or removed."""
    try:
        from . import canvas
        mine = [("canvas_" + s, D, canvas.reader(s)) for s in canvas.enabled()]
    except Exception:       # a broken definition must never stop the built-in sources
        return
    TABLE[:] = [t for t in TABLE if not t[0].startswith("canvas_")] + mine
    BY_NAME.clear()
    BY_NAME.update({n: (g, f) for n, g, f in TABLE})


load_canvas()
PARTS = os.path.join(paths.HOME, "parts")
_status_lock = threading.Lock()

def _part(name, kind=""):
    return os.path.join(PARTS, name + (("." + kind) if kind else "") + ".jsonl")


def _count(path):
    if not os.path.exists(path):
        return 0
    with open(path, "rb") as f:
        return sum(1 for _ in f)


def _ids(path):
    """The ids in one part file, read without parsing each row. Used to count what a read brought that was not there before."""
    got = set()
    try:
        with open(path, "rb") as f:
            for line in f:
                i = line.find(b'"id": "')
                if i >= 0:
                    got.add(line[i + 7:line.find(b'"', i + 7)])
    except OSError:
        pass
    return got


def _line_id(line):
    i = line.find(b'"id": "')
    return line[i + 7:line.find(b'"', i + 7)] if i >= 0 else None


def _filled(row):
    return sum(1 for v in row.values() if v not in ("", None, [], {}))


def _twice(parts):
    """{id: the one row to keep} for every id that more than one row carries. The same post can come from two sources
    (x read through the browser and the x archive), and an export can hold a thing twice. The row that says more is
    kept, and takes from the other whatever it lacks. Empty when no id repeats, which is the usual case."""
    seen, again = set(), set()
    for p in parts:
        with open(p, "rb") as f:
            for line in f:
                k = _line_id(line)
                if k is None:
                    continue
                (again if k in seen else seen).add(k)
    if not again:
        return {}
    best = {}
    for p in parts:
        with open(p, "rb") as f:
            for line in f:
                k = _line_id(line)
                if k not in again:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if k not in best:
                    best[k] = row
                    continue
                keep, other = (best[k], row) if _filled(best[k]) >= _filled(row) else (row, best[k])
                best[k] = dict(keep, **{f: v for f, v in other.items() if keep.get(f) in ("", None, [], {}) and v not in ("", None, [], {})})
    return best


def _groups():
    return os.path.join(PARTS, "groups.json")


OWNERS = ("canvas_", "custom_")       # sources the owner added: whether their rows are in is their switch, not a question of which engine runs


def _group_word(group):
    return {M: "messages", S: "sessions", P: "prompts", D: "docs"}.get(group, "")


def _note_group(name, group):
    """Remember which file a source's rows belong to, beside the parts. An engine that has no reader for a source
    (an older copy than the one that read it) joins by this."""
    try:
        with open(_groups()) as f:
            cur = json.load(f)
    except (OSError, ValueError):
        cur = {}
    if cur.get(name) != _group_word(group):
        cur[name] = _group_word(group)
        tmp = "%s.new.%d" % (_groups(), os.getpid())
        with open(tmp, "w") as f:
            json.dump(cur, f, indent=1, sort_keys=True)
        os.replace(tmp, _groups())


def _sniff(path):
    """Which file a part's rows belong to, told from its first row, when nothing was noted for it."""
    try:
        with open(path) as f:
            d = json.loads(f.readline() or "{}")
    except (OSError, ValueError):
        return ""
    if "user_turns" in d or "first_user" in d:
        return "sessions"
    if "thread_id" in d:
        return "messages"
    if d.get("who") == "me" and "thread" in d and "title" not in d:
        return "prompts"
    return "docs" if d.get("id") else ""


def _strangers(group):
    """Parts on disk of sources this engine has no reader for, that belong in this file. They were read by a newer copy
    of the engine (the app and a checkout can run different ones): an engine never drops the rows of a source it does
    not know. Sources the owner added themselves are not strangers: those are in or out by their own switch."""
    known = {n for n, _, _ in TABLE}
    try:
        names = sorted(os.listdir(PARTS))
    except OSError:
        return []
    try:
        with open(_groups()) as f:
            noted = json.load(f)
    except (OSError, ValueError):
        noted = {}
    want, out = _group_word(group), []
    for f in names:
        if not f.endswith(".jsonl"):
            continue
        base = f[:-6]
        name, kind = (base.rsplit(".", 1) + [""])[:2] if base.endswith((".prompts", ".index")) else (base, "")
        if name in known or name.startswith(OWNERS) or not name:
            continue
        p = os.path.join(PARTS, f)
        if kind == "prompts":
            if group == paths.PROMPTS:
                out.append(p)
        elif kind == "index":
            if group == paths.MAIL_INDEX:
                out.append(p)
        elif (noted.get(name) or _sniff(p)) == want and want:
            out.append(p)
    return out


def assemble(group):
    """Join the per-source parts into the one file readers use. Swapped in whole, so readers never see half a file."""
    if group == paths.PROMPTS:
        parts = [_part(n, "prompts") for n, g, _ in TABLE if g == S] + [_part(n) for n, g, _ in TABLE if g == P]
    elif group == paths.MAIL_INDEX:
        parts = [_part(n, "index") for n, g, _ in TABLE if g == M]
    else:
        parts = [_part(n) for n, g, _ in TABLE if g == group]
    parts = [p for p in parts if os.path.exists(p)] + _strangers(group)
    twice = _twice(parts) if group != paths.MAIL_INDEX else {}       # sessions and prompts too: the same session can sit in two project folders
    tmp = "%s.new.%d.%d" % (group, os.getpid(), threading.get_ident())      # its own name: another read may be joining the same file right now
    with open(tmp, "wb") as out:
        for p in parts:
            with open(p, "rb") as f:
                if not twice:
                    while chunk := f.read(1 << 20):
                        out.write(chunk)
                    continue
                for line in f:
                    k = _line_id(line)
                    if k not in twice:
                        out.write(line)
                    elif twice[k] is not None:          # the one row for this id goes where its first copy stood
                        out.write((json.dumps(twice[k], ensure_ascii=False) + "\n").encode("utf-8"))
                        twice[k] = None
    os.replace(tmp, group)


def _save_status(name, st):
    """Put one source's result into status.json. Read, changed and swapped in under a lock that other processes honour
    too, so two reads that end together both keep their line."""
    with _status_lock:
        p = os.path.join(paths.HOME, "status.json")
        with open(p + ".lock", "w") as gate:
            try:
                import fcntl
                fcntl.flock(gate, fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            try:
                with open(p) as f:
                    cur = json.load(f)
            except (OSError, ValueError):
                cur = {}
            cur[name] = st
            order = [n for n, _, _ in TABLE]
            # a source this engine has no reader for keeps its line (a newer copy of the engine wrote it); one the owner
            # added and has since removed does not
            order += sorted(k for k in cur if k not in order and not k.startswith(OWNERS))
            tmp = "%s.new.%d" % (p, os.getpid())
            with open(tmp, "w") as f:
                json.dump({k: cur[k] for k in order if k in cur}, f, indent=1)
            os.replace(tmp, p)


LOCKS = os.path.join(paths.HOME, "locks")
LOCK_STALE = 6 * 3600       # a lock older than this was left by a read that died: no source takes this long


def _lock_live(path):
    """Is the read that wrote this lock file still going? Its process must be alive and the lock not too old."""
    try:
        with open(path) as f:
            pid, at = f.read().split()
        pid, at = int(pid), float(at)
    except (OSError, ValueError):
        try:        # being written this instant by another read, or damaged: young means taken
            return time.time() - os.path.getmtime(path) < 10
        except OSError:
            return False
    if time.time() - at > LOCK_STALE:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:     # it is there, and not ours to signal
        return True
    return True


def take_lock(name):
    """One read of a source at a time, across processes (the app's own schedule and a hand-run collect). Returns the
    lock file's path, or None when another read of this source is going on. Give it back with drop_lock."""
    os.makedirs(LOCKS, exist_ok=True)
    path = os.path.join(LOCKS, re.sub(r"[^A-Za-z0-9_.-]", "_", name) + ".lock")
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if _lock_live(path):
                return None
            try:
                os.remove(path)     # left by a read that died
            except OSError:
                pass
            continue
        with os.fdopen(fd, "w") as f:
            f.write("%d %f" % (os.getpid(), time.time()))
        return path
    return None


def drop_lock(path):
    try:
        os.remove(path)
    except OSError:
        pass


BUSY = "already being read"


def collect_one(name, days=None, join=True):
    """Read one source now. Prints live progress lines (starting with @) and one final line.
    A source that is blocked, missing or broken keeps the rows it had. So does one that another read (the app's own
    schedule, say) is in the middle of: this one steps aside, and the result on record is the other read's."""
    lock = take_lock(name)
    if not lock:
        st = {"rows": _count(_part(name)), "new": 0, "skipped": BUSY}
        print(f"{name:12} {st}", flush=True)
        return st
    try:
        return _read_one(name, days, join)
    finally:
        drop_lock(lock)


def _read_one(name, days, join):
    group, fn = BY_NAME[name]
    os.makedirs(PARTS, exist_ok=True)
    with _status_lock:
        _note_group(name, group)
    part, t0 = _part(name), time.time()
    extras = {"prompts": _part(name, "prompts")} if group == S else {"index": _part(name, "index")} if group == M else {}
    files = {k: open(v + ".new", "w") for k, v in extras.items()}
    _tl.name, _tl.n, _tl.t = name, 0, 0.0
    _tl.prompts, _tl.index = files.get("prompts"), files.get("index")
    _say({"src": name, "phase": "starting", "rows": 0})
    had = _ids(part)
    try:
        with open(part + ".new", "w") as out:
            _tl.out = out
            rows = fn(days, out)
        if not rows and _count(part):       # a source that had rows and now reads none is blocked or broken, not empty: keep what it had
            raise FileNotFoundError("read nothing this time, so the rows from last time are kept")
        os.replace(part + ".new", part)
        for k, f in files.items():
            f.close()
            os.replace(extras[k] + ".new", extras[k])
        st = {"rows": rows, "secs": round(time.time() - t0, 1), "new": len(_ids(part) - had)}       # rows that were not there last time
    except Exception as e:
        for k, f in files.items():
            f.close()
        for p in [extras[k] + ".new" for k in files] + [part + ".new"]:     # some may already be in place, or taken by another read of the same source
            try:
                os.remove(p)
            except OSError:
                pass
        kept = _count(part)
        known = isinstance(e, (FileNotFoundError, PermissionError, sqlite3.Error))
        why = str(e) if known else f"error: {type(e).__name__}: {e}"[:200]
        st = {"rows": kept, "stale": True, "why": why, "new": 0} if kept else {"skipped": why, "new": 0}
    finally:
        _tl.out = _tl.prompts = _tl.index = None
    _save_status(name, st)
    print(f"{name:12} {st}", flush=True)
    if join:
        # never rebuild a combined file from an incomplete set of parts: read the missing neighbours first. a source that
        # has been tried before is in the record, so its missing part means "nothing there", not "never read"
        try:
            tried = set(paths.read_json(os.path.join(paths.HOME, "status.json")))
        except (OSError, ValueError):
            tried = set()
        for n, g, _ in TABLE:
            if n != name and (g == group or (group == S and g == P)) and not os.path.exists(_part(n)) and n not in tried:
                collect_one(n, days, join=False)
        assemble(group)
        if group == S:
            assemble(paths.PROMPTS)
        if group == M:
            assemble(paths.MAIL_INDEX)
    return st


def run(days=None, only=None):
    """Read every source, or just the ones named in `only`. The files fill at the same time, so a slow source
    (mail) does not hold up the rest."""
    def lane(group):
        for n, g, _ in TABLE:
            if (g == group or (group == S and g == P)) and (only is None or n in only):
                collect_one(n, days, join=False)
        assemble(group)
    lanes = [threading.Thread(target=lane, args=(g,)) for g in (M, S, D)]
    for t in lanes:
        t.start()
    for t in lanes:
        t.join()
    assemble(paths.PROMPTS)
    assemble(paths.MAIL_INDEX)
    return paths.read_json(os.path.join(paths.HOME, "status.json"))
