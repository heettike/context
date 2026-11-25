"""Readers for local Mac app data: browser history (every Chromium browser, Safari), Grok Bot, ChatGPT.

Same contract as collect.py: fn(days, out) streams rows through put() and returns the count, or raises
FileNotFoundError / PermissionError with a one-line reason. Nothing is ever written into an app's folder:
browser databases are copied to a temp dir and read there, because the running browser holds a lock.

  docs      browser_history, safari_history
  sessions  grok_bot, chatgpt_app, chatgpt_export
  prompts   grok_bot_prompts, chatgpt_app_prompts, chatgpt_export_prompts
"""
import base64, glob, hashlib, json, os, plistlib, re, shutil, sqlite3, tempfile
from datetime import datetime
from urllib.parse import urlsplit
from . import paths
from .collect import APPLE, FDA, H, _noise, _session, iso, put, sid, since
from .scrub import scrub

APPDATA = os.environ.get("CTX_BROWSER_DATA", H("~/Library/Application Support"))
# every chromium browser keeps the same History file, one per profile, and all are read alike, in the order of the alphabet
CHROMIUM = [("arc", "Arc/User Data"), ("brave", "BraveSoftware/Brave-Browser"), ("chrome", "Google/Chrome"), ("chromium", "Chromium"),
            ("dia", "Dia/User Data"), ("edge", "Microsoft Edge"), ("opera", "com.operasoftware.Opera"), ("vivaldi", "Vivaldi")]
SAFARI = H("~/Library/Safari/History.db")
GROK = H("~/Library/Application Support/Grok Bot")
CHATGPT = H("~/Library/Application Support/com.openai.chat")
CHROMIUM_EPOCH = 11644473600   # seconds from 1601 to 1970


# ---------- browser history ----------

_AUTH_LABEL = {"accounts", "account", "auth", "login", "signin", "sso", "oauth", "idp", "identity", "id", "appleid", "secure"}
_AUTH_HOST = re.compile(r"(okta|auth0|onelogin|duosecurity|pingidentity)\.com$")       # sign-in services: a visit there is a login, not a page read
_AUTH_PATH = re.compile(r"(?i)(^|/)(log[-_]?in|sign[-_]?in|sign[-_]?up|log[-_]?out|sign[-_]?out|oauth2?|authorize|auth|sso|saml2?"
                        r"|callback|(reset|forgot|change)?[-_]?password|verify|verification|2fa|mfa|otp|magic[-_]?link|challenge"
                        r"|checkpoint|session/new|token)(/|\.|$)")
_LOCAL = re.compile(r"^(localhost|0\.0\.0\.0|127\.\d+\.\d+\.\d+|::1|.*\.(localhost|local|test))$")


def _clean(url):
    """scheme://host/path with no user, query or fragment; None for pages that should not be kept."""
    try:
        u = urlsplit(url or "")
        host = (u.hostname or "").lower()
        port = f":{u.port}" if u.port else ""
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not host or _LOCAL.match(host):
        return None
    if _AUTH_LABEL & set(host.split(".")) or _AUTH_HOST.search(host) or _AUTH_PATH.search(u.path):
        return None
    return f"{u.scheme}://{host}{port}{u.path}"


def _copy(path, tmp, i):
    """Copy a sqlite file (and its journal / wal) to tmp and open the copy. The original is only read."""
    try:
        os.stat(path)
    except FileNotFoundError:
        raise FileNotFoundError("not installed or no data")
    except PermissionError:
        raise PermissionError(FDA)
    dst = os.path.join(tmp, f"db{i}")
    try:
        shutil.copyfile(path, dst)
        for ext in ("-wal", "-shm", "-journal"):
            if os.path.exists(path + ext):
                shutil.copyfile(path + ext, dst + ext)
    except PermissionError:
        raise PermissionError(FDA)
    return sqlite3.connect(dst)


def _history(dbs, sql, cutoff, to_unix, days, prefix, out):
    """Merge every profile into one temp table keyed by the cleaned URL, then write one row per URL, oldest first."""
    with tempfile.TemporaryDirectory(prefix="ctx-history-") as tmp:
        merged = sqlite3.connect(os.path.join(tmp, "merged"))
        merged.execute("create table h (url text, title text, n int, ts real)")
        bad = []
        for i, path in enumerate(dbs):
            con = None
            try:
                con = _copy(path, tmp, i)
                rows = con.execute(sql, (cutoff,))
                merged.executemany("insert into h values (?,?,?,?)", (
                    (c, title or "", max(seen, 0 if days else total or 0), to_unix(last))
                    for url, title, total, seen, last in rows for c in [_clean(url)] if c))
            except (sqlite3.DatabaseError, OSError) as e:    # one unreadable profile must not lose the others
                bad.append(e if isinstance(e, PermissionError) else
                           PermissionError(f"cannot read {os.path.basename(os.path.dirname(path))}/{os.path.basename(path)}: {e}"))
            finally:
                if con:
                    con.close()
        if bad and len(bad) == len(dbs):
            merged.close()
            raise bad[0]
        merged.execute("create index hu on h (url)")
        n = 0
        # with max(), sqlite takes the other bare columns from the row that holds the max: title of the latest visit
        for url, title, visits, ts in merged.execute(
                "select url, title, sum(n), max(ts) as last from h group by url order by last"):
            host = urlsplit(url).hostname or ""
            title = " ".join(title.split()) or host + urlsplit(url).path
            put(out, {"id": prefix + hashlib.sha1(url.encode()).hexdigest()[:12], "src": "browser_history", "ts": iso(ts),
                      "title": title[:300], "text": f"{title[:300]} | {host} | visits {visits}", "url": scrub(url)})
            n += 1
        merged.close()
    return n


def chromium_profiles():
    """[(browser, path of a History file)] for every chromium browser profile on this mac."""
    return [(name, p) for name, d in CHROMIUM for p in sorted(glob.glob(os.path.join(glob.escape(os.path.join(APPDATA, d)), "*", "History")))]


def browser_history(days, out):
    """Browsing history from every chromium browser on this mac (CHROMIUM above), as one source."""
    dbs = [p for _, p in chromium_profiles()]
    if not dbs:
        raise FileNotFoundError("no chromium browser history on this mac (looked for " + ", ".join(n for n, _ in CHROMIUM) + ")")
    cutoff = int((since(days) + CHROMIUM_EPOCH) * 1e6) if days else 0
    return _history(dbs, """select u.url, u.title, u.visit_count, count(v.id), max(v.visit_time)
                            from visits v join urls u on u.id = v.url where v.visit_time > ? group by u.id""",
                    cutoff, lambda t: t / 1e6 - CHROMIUM_EPOCH, days, "HD", out)


def safari_history(days, out):
    cutoff = since(days) - APPLE if days else -1e18
    return _history([SAFARI], """select i.url, v.title, i.visit_count, count(v.id), max(v.visit_time)
                                 from history_visits v join history_items i on i.id = v.history_item
                                 where v.visit_time > ? group by i.id""",
                    cutoff, lambda t: t + APPLE, days, "HS", out)


# ---------- agent sessions: shared ----------

def _add(s, prompts, role, txt, ts, cutoff):
    """collect._turn, but prompts go to a list so the session and prompt functions can share one reader."""
    if role == "user":
        if len(txt) < 6000 and ts >= cutoff:
            prompts.append({"id": f'{s["id"]}:{s["user_turns"]}', "src": s["src"], "ts": iso(ts), "thread": s["title"],
                            "who": "me", "text": txt})
        s["user_turns"] += 1
        s["first_user"] = s["first_user"] or txt[:600]
        s["last_user"], s["last_user_ts"] = txt[:600], iso(ts)
    else:
        s["last_agent"], s["last_agent_ts"] = txt[-1800:], iso(ts)


def _pair(reader, name):
    """The two sources one reader feeds: its sessions (those with both sides, touched in the window) and the prompts
    the owner typed in them. Named so status lines and errors say which source they are."""
    def sessions(days, out):
        n = 0
        for s, _, last in reader(days):
            if s["user_turns"] and s["last_agent"] and last >= since(days):
                put(out, s)
                n += 1
        return n

    def prompts(days, out):
        n = 0
        for _, typed, _ in reader(days):
            for p in typed:
                put(out, p)
                n += 1
        return n
    sessions.__name__, prompts.__name__ = name, name + "_prompts"
    return sessions, prompts


# ---------- Grok Bot ----------
# Electron app. Conversations are plain JSON, one file per agent thread:
#   sand-client-persistence/<base32 of the key>.blob, key = sand.client.slice.account.<user>.transcript.replicas.<agentId>
#   {"value": {"entries": [...]}} with entries ordered by seq:
#     kind "message", role "user", no fromAgent   what the owner typed
#     kind "send-message", message.type "text"    what the agent sent back to the owner
#     kind "message" with fromAgent / toAgent     agent-to-agent traffic, skipped
# This is the app's local replica of each thread: it holds what the app has synced, which may be less than the server has.

def _grok(days):
    files = {}                  # blob file -> the key its name spells in base32 ("" when it is not one)
    for f in glob.glob(os.path.join(GROK, "sand-client-persistence", "*.blob")):
        b = os.path.basename(f)[:-5].upper()
        try:
            files[f] = base64.b32decode(b + "=" * (-len(b) % 8)).decode()
        except (ValueError, UnicodeDecodeError):
            files[f] = ""
    threads = sorted(f for f, k in files.items() if ".transcript.replicas." in k)
    if not os.path.isdir(GROK):
        raise FileNotFoundError("not installed or no data")
    if not threads:
        raise FileNotFoundError("no transcripts in sand-client-persistence/ (plain JSON .blob files): open the app and sign in once")
    names = {}
    for f in (f for f, k in files.items() if k.endswith(".roster.last-roster")):
        try:
            names.update({r["id"]: r.get("name") or "" for r in paths.read_json(f)["value"]["rows"]})
        except (OSError, ValueError, KeyError, TypeError):
            pass
    cutoff = since(days)
    for f in threads:
        aid = files[f].rsplit(".", 1)[-1]
        try:
            entries = paths.read_json(f)["value"]["entries"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        s, prompts, last = _session(sid("G", aid), "grok_bot"), [], 0
        s["title"] = names.get(aid, "")
        for e in sorted(entries, key=lambda e: e.get("seq") or 0):
            ts, kind = (e.get("timestampMs") or 0) / 1000, e.get("kind")
            if kind == "message" and e.get("role") == "user" and not e.get("fromAgent") and not e.get("suppressed"):
                role, txt = "user", e.get("content")
            elif kind == "send-message" and (e.get("message") or {}).get("type") == "text":
                role, txt = "assistant", e["message"].get("content")
            else:
                continue
            txt = txt.strip() if isinstance(txt, str) else ""
            if txt and not (role == "user" and _noise(txt)):
                _add(s, prompts, role, txt, ts, cutoff)
                last = max(last, ts)
        yield s, prompts, last


grok_bot, grok_bot_prompts = _pair(_grok, "grok_bot")


# ---------- ChatGPT ----------

def _conversation(c, cutoff, src):
    """One conversation of the export format: follow parent links from current_node back to the root, then read forward."""
    mapping = c.get("mapping") or {}
    cid = c.get("conversation_id") or c.get("id") or ""
    s, prompts, last = _session(sid("O", cid), src), [], 0
    s["title"] = c.get("title") or ""
    node = c.get("current_node")
    if node not in mapping:   # no pointer: take the last child at every step from the root
        node = next((k for k, v in mapping.items() if not (v or {}).get("parent")), None)
        while node and (mapping[node].get("children") or []) and mapping[node]["children"][-1] in mapping:
            node = mapping[node]["children"][-1]
    chain, seen = [], set()
    while node in mapping and node not in seen:
        seen.add(node)
        chain.append(mapping[node])
        node = mapping[node].get("parent")
    for n in reversed(chain):
        m = n.get("message") or {}
        role, content = (m.get("author") or {}).get("role"), m.get("content") or {}
        if (role not in ("user", "assistant") or content.get("content_type") not in ("text", "multimodal_text")
                or (m.get("metadata") or {}).get("is_visually_hidden_from_conversation")):
            continue
        txt = "\n".join(p for p in content.get("parts") or [] if isinstance(p, str)).strip()
        ts = m.get("create_time") or c.get("update_time") or c.get("create_time") or 0
        if txt:
            _add(s, prompts, role, txt, ts, cutoff)
            last = max(last, ts)
    return s, prompts, max(last, c.get("update_time") or 0)


def _array(path):
    """Yield the items of a top-level JSON array without holding the file in memory (the export can be very large)."""
    dec, buf, pos = json.JSONDecoder(), "", 0
    with open(path, encoding="utf-8") as f:
        while True:
            while pos < len(buf) and buf[pos] in " \t\r\n,[":
                pos += 1
            if pos < len(buf) and buf[pos] == "]":
                return
            try:
                if pos >= len(buf):
                    raise ValueError
                item, pos = dec.raw_decode(buf, pos)
                yield item
            except ValueError:   # item is cut off at the end of the buffer: read more
                more = f.read(1 << 20)
                if not more:
                    return
                buf, pos = buf[pos:] + more, 0


def _when(text):
    """Seconds since 1970 for a time the export wrote as text; 0 when it is not one."""
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


def _group_chats(path, cutoff, me):
    """group_chats.json: chats with other people and the assistant in one room. A message says only "user" or
    "assistant", never which person wrote it, so what was typed counts as the owner's only in a room whose one member
    is the owner (the export's own user.json says who that is)."""
    try:
        with open(path, encoding="utf-8") as f:
            chats = (json.load(f) or {}).get("chats") or []
    except (OSError, ValueError, AttributeError):
        return
    for c in chats:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        members = [str(m.get("id") or "") for m in c.get("members") or [] if isinstance(m, dict)]
        alone = len(members) == 1 and (not me or members[0] == me)
        s, prompts, last = _session(sid("OG", c["id"]), "chatgpt"), [], 0
        s["title"] = str(c.get("name") or "")
        for m in sorted((m for m in c.get("messages") or [] if isinstance(m, dict)), key=lambda m: str(m.get("created_at") or "")):
            role, txt, ts = m.get("role"), str(m.get("text") or "").strip(), _when(m.get("created_at"))
            if role in ("user", "assistant") and txt:
                _add(s, prompts if alone else [], role, txt, ts, cutoff)
                last = max(last, ts)
        yield c["id"], (s, prompts, last)


def _id_time(ident):
    """OpenAI starts an id with the second it was made, in hex. 0 when this one does not."""
    m = re.search(r"(?:^|_)([0-9a-f]{8})[0-9a-f]{8,}", str(ident))
    at = int(m.group(1), 16) if m else 0
    return at if 1500000000 < at < 2200000000 else 0


def _codex_tasks(path, cutoff):
    """codex.json: tasks given to codex in the cloud (not the sessions of the codex app on this mac, which collect.codex
    reads; the two never share an id). A task has turns: what was asked, and what codex wrote back. The file gives no
    times, so a task is dated by its id."""
    try:
        with open(path, encoding="utf-8") as f:
            tasks = json.load(f)
    except (OSError, ValueError):
        return
    for t in tasks if isinstance(tasks, list) else []:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        s, prompts, at = _session(sid("OT", t["id"], tail=True), "codex"), [], _id_time(t["id"])
        s["title"] = str(t.get("title") or "")
        for turn in t.get("turns") or []:
            if not isinstance(turn, dict):
                continue
            role = turn.get("role")
            items = turn.get("input_items" if role == "user" else "output_items") or []
            txt = "\n".join(str(b.get("text") or "") for it in items if isinstance(it, dict) and it.get("type") == "message"
                            for b in it.get("content") or [] if isinstance(b, dict) and b.get("content_type") == "text").strip()
            if role in ("user", "assistant") and txt:
                _add(s, prompts, role, txt, _id_time(turn.get("id")) or at, cutoff)
        yield t["id"], (s, prompts, at)


def _export(days):
    root, files, more = os.path.join(paths.HOME, "imports"), [], []
    for d, _, names in os.walk(root):
        files += [os.path.join(d, x) for x in names if re.fullmatch(r"conversations(-\d+)?\.json", x)]
        if "export_manifest.json" in names or "user.json" in names:     # the other files of a chatgpt export that hold what was typed
            more += [os.path.join(d, x) for x in ("group_chats.json", "codex.json") if x in names]
    if not files:
        raise FileNotFoundError("no ChatGPT export: chatgpt.com > Settings > Data controls > Export data, then python3 -m ctx ingest when the zip is in downloads (it unpacks it under imports/)")
    seen, cutoff, newest = set(), since(days), {}
    for path in sorted(files):          # the same chat in two exports, or in an export and read since from the site: the copy changed last
        for c in _array(path):
            if isinstance(c, dict) and "mapping" in c:
                cid, at = c.get("conversation_id") or c.get("id"), c.get("update_time") or 0
                at = at if isinstance(at, (int, float)) else 0
                if cid not in newest or at > newest[cid][0]:
                    newest[cid] = (at, path)
    for path in sorted(files):
        for c in _array(path):
            if not isinstance(c, dict) or "mapping" not in c:
                continue
            cid = c.get("conversation_id") or c.get("id")
            if cid in seen or newest.get(cid, (0, path))[1] != path:
                continue
            seen.add(cid)
            yield _conversation(c, cutoff, "chatgpt")
    for path in sorted(more):
        me = ""
        try:
            with open(os.path.join(os.path.dirname(path), "user.json"), encoding="utf-8") as f:
                me = str((json.load(f) or {}).get("id") or "")
        except (OSError, ValueError, AttributeError):
            pass
        for key, got in (_group_chats(path, cutoff, me) if path.endswith("group_chats.json") else _codex_tasks(path, cutoff)):
            if key not in seen:
                seen.add(key)
                yield got


chatgpt_export, chatgpt_export_prompts = _pair(_export, "chatgpt_export")


def _app(days):
    """The ChatGPT chat app (com.openai.chat). Builds before mid-2024 kept conversations as plain JSON files in
    conversations-<id>/; later builds write conversations-v2/v3-<id>/*.data encrypted with a key held in the Keychain."""
    dirs = [d for base in [CHATGPT] + glob.glob(H("~/Library/Group Containers/*openai*")) + glob.glob(H("~/Library/Group Containers/*openai*/Library/Application Support/*"))
            for d in glob.glob(os.path.join(base, "conversations*")) if os.path.isdir(d)]
    if not dirs:
        if os.path.isdir(CHATGPT):
            raise FileNotFoundError("encrypted on disk: use the account export from chatgpt.com")
        other = ""
        try:
            with open("/Applications/ChatGPT.app/Contents/Info.plist", "rb") as f:
                if plistlib.load(f).get("CFBundleIdentifier") == "com.openai.codex":
                    other = " (the installed ChatGPT.app is the Codex app, com.openai.codex; the codex source reads its sessions)"
        except (OSError, ValueError):
            pass
        raise FileNotFoundError("ChatGPT chat app has no data on this Mac: no com.openai.chat folder" + other
                                + "; use the account export from chatgpt.com")
    cutoff, readable = since(days), 0
    for d in dirs:
        for f in sorted(glob.glob(os.path.join(d, "*"))):
            try:
                with open(f, "rb") as fh:
                    if fh.read(1) != b"{":
                        continue
                c = paths.read_json(f, encoding="utf-8")
            except (OSError, ValueError):
                continue
            if isinstance(c, dict) and "mapping" in c:
                readable += 1
                yield _conversation(c, cutoff, "chatgpt")
    if not readable:
        raise FileNotFoundError("encrypted on disk: use the account export from chatgpt.com")


chatgpt_app, chatgpt_app_prompts = _pair(_app, "chatgpt_app")
