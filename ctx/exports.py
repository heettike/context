"""Official exports. Drop the unzipped folder (or the file) anywhere under ~/.context/v2/imports/ and run collect.

  X archive        x.com/settings/download_your_data   -> data/tweets.js, like.js, direct-messages.js
  Google Takeout   takeout.google.com (Mail)           -> *.mbox
"""
import email, email.policy, email.utils, glob, html, json, mailbox, os, re, shutil, time
from datetime import datetime, timezone
from . import paths
from .collect import iso, put, rid, stable

IMPORTS = os.path.join(paths.HOME, "imports")


def _find(pattern):
    return glob.glob(os.path.join(IMPORTS, "**", pattern), recursive=True) + glob.glob(os.path.expanduser("~/Downloads/twitter-*/data/" + pattern))


def _ytd(path):
    with open(path, encoding="utf-8") as f:
        s = f.read()
    return json.loads(s[s.index("["):])


def _x_files(*names):
    """The archive's files of one kind. A big archive splits a file into parts (tweets.js, tweets-part1.js, ...), and an
    older one calls the posts file tweet.js. An unreadable file is left out, never a reason to lose the rest."""
    out = []
    for n in names:
        part = lambda p: int((re.search(r"-part(\d+)\.js$", p) or [0, 0])[1])
        out += sorted(_find(n)) + sorted(_find(n[:-3] + "-part*.js"), key=lambda p: (os.path.dirname(p), part(p)))
    return list(dict.fromkeys(out))


def _x_rows(path, key):
    try:
        got = _ytd(path)
    except (OSError, ValueError):
        return []
    return [(r.get(key, r) if isinstance(r, dict) else {}) for r in got if isinstance(r, dict)]


def _xdate(s):
    try:
        return iso(datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y").timestamp())
    except (ValueError, TypeError):
        return (s or "")[:19] + "Z"


def _x_account():
    """(account id, handle) of the archive's owner, from account.js. ("", "") when it is not there."""
    for f in _x_files("account.js"):
        for a in _x_rows(f, "account"):
            if a.get("accountId"):
                return str(a["accountId"]), str(a.get("username") or "")
    return "", ""


def _x_links(text, urls):
    """x writes every link as a t.co address; the archive keeps the real one beside it."""
    for u in urls or []:
        if isinstance(u, dict) and u.get("url") and (u.get("expanded_url") or u.get("expanded")):
            text = text.replace(u["url"], u.get("expanded_url") or u.get("expanded"))
    return text


def _x_notes():
    """Long posts. tweets.js holds only their first 280 letters; the whole text is in note-tweet.js, tied to the post by
    the second it was made. {second: [text, ...]}"""
    out = {}
    for f in _x_files("note-tweet.js"):
        for n in _x_rows(f, "noteTweet"):
            text, at = ((n.get("core") or {}).get("text") or ""), str(n.get("createdAt") or "")[:19]
            if text and at:
                out.setdefault(at, []).append(_x_links(text, (n.get("core") or {}).get("urls")))
    return out


def _x_note_for(notes, t, shown):
    """The whole text of a long post, when note-tweet.js has one made within two seconds that starts the same way."""
    try:
        at = datetime.strptime(t.get("created_at") or "", "%a %b %d %H:%M:%S %z %Y").timestamp()
    except ValueError:
        return ""
    head = re.sub(r"\s+", " ", html.unescape(shown))[:30]
    for d in (0, 1, -1, 2, -2):
        for text in notes.get(datetime.fromtimestamp(at + d, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), []):
            if len(text) > len(shown) and re.sub(r"\s+", " ", text)[:30] == head:
                return text
    return ""


def x_archive_docs(days, out):
    """Every post, reply, repost and like in the x archive. Goes to docs. A post is one row however many archives hold
    it. Posts the owner deleted (deleted-tweets.js) are left out."""
    tw = _x_files("tweets.js", "tweet.js", "community-tweet.js")
    if not tw:
        raise FileNotFoundError("no X archive yet: ask for it (python3 -m ctx request x, or x.com/settings/download_your_data); when the zip is in downloads: python3 -m ctx ingest")
    handle, notes, seen, n = _x_account()[1], _x_notes(), set(), 0
    for f in tw:
        for t in _x_rows(f, "tweet"):
            tid = str(t.get("id_str") or t.get("id") or "")
            if not tid or tid in seen:
                continue
            seen.add(tid)
            shown = t.get("full_text") or t.get("text") or ""
            ent = t.get("entities") or {}        # a photo or video is written as a t.co link too; its real address is with the media
            text = _x_note_for(notes, t, shown) or html.unescape(_x_links(shown, (ent.get("urls") or []) + (ent.get("media") or [])))
            rt = re.match(r"RT @(\w+):", shown)
            title = "repost of @" + rt.group(1) if rt else "reply to @" + t["in_reply_to_screen_name"] if t.get("in_reply_to_screen_name") else ""
            row = {"id": "P" + tid, "src": "x_posts", "ts": _xdate(t.get("created_at")), "title": title, "text": text,
                   "likes": int(t.get("favorite_count") or 0), "who": "" if rt else "me"}
            if handle:
                row["url"] = "https://x.com/%s/status/%s" % (handle, tid)
            put(out, row)
            n += 1
    seen = set()
    for f in _x_files("like.js"):
        for l in _x_rows(f, "like"):
            tid = str(l.get("tweetId") or "")
            if not tid or tid in seen:
                continue
            seen.add(tid)       # the archive gives a like no date, and no words when the post has since gone
            put(out, {"id": "L" + tid, "src": "x_likes", "ts": "", "title": "", "text": html.unescape(l.get("fullText") or ""), "url": l.get("expandedUrl") or ""})
            n += 1
    return n


def x_names():
    """{account number: "Name (@handle)"} for every account the archive can name. The chats file names nobody, but the
    owner's own posts do: whoever the owner mentioned or replied to is there with their number, handle and name."""
    out = {}
    for f in _x_files("tweets.js", "tweet.js", "community-tweet.js"):
        for t in _x_rows(f, "tweet"):
            for m in (t.get("entities") or {}).get("user_mentions") or []:
                if isinstance(m, dict) and m.get("id_str") and m.get("screen_name"):
                    name = " ".join(str(m.get("name") or "").split())
                    out[str(m["id_str"])] = ("%s (@%s)" % (name, m["screen_name"])) if name else "@" + m["screen_name"]
            if t.get("in_reply_to_user_id_str") and t.get("in_reply_to_screen_name"):
                out.setdefault(str(t["in_reply_to_user_id_str"]), "@" + t["in_reply_to_screen_name"])
    return out


def x_archive_dms(days, out):
    """X direct messages, one to one and group. Goes to messages. The chats file names nobody: the other side is an
    account number. Where the owner's own posts name that account (x_names) the thread takes the name; otherwise it is
    called by the end of the number, and a group by the name it was given."""
    dm, groups = _x_files("direct-messages.js"), _x_files("direct-messages-group.js")
    if not dm and not groups:
        raise FileNotFoundError("no X archive in imports/")
    me, seen, n, names = _x_account()[0], set(), 0, x_names()
    for f in dm + groups:
        group = f in groups
        for c in _x_rows(f, "dmConversation"):
            cid = str(c.get("conversationId") or "")
            events = [e for e in (c.get("messages") or []) if isinstance(e, dict)]
            msgs = [e["messageCreate"] for e in events if isinstance(e.get("messageCreate"), dict)]
            named = [e["conversationNameUpdate"].get("name") for e in events if isinstance(e.get("conversationNameUpdate"), dict)]
            mine = sum(str(m.get("senderId")) == me for m in msgs)
            other = next((x for x in cid.split("-") if x != me), cid) if not group else cid
            thread = (next((x for x in named if x), "") or "x group " + cid[-8:]) if group else names.get(other) or "x dm " + other[-8:]
            for m in msgs:
                mid = str(m.get("id") or "")
                if not m.get("text") or not mid or mid in seen:
                    continue
                seen.add(mid)
                from_me = bool(me) and str(m.get("senderId")) == me
                put(out, {"id": "XD" + mid, "src": "x_dm", "ts": (m.get("createdAt") or "")[:19] + "Z", "thread_id": "xd" + cid, "thread": thread,
                          "kind": "group" if group else "dm", "mine_total": mine + 3 if mine else 0, "who": "me" if from_me else "them",
                          "sender": "" if from_me else (names.get(str(m.get("senderId") or ""), "") or str(m.get("senderId") or "")[-4:])[:40],
                          "text": _x_links(m["text"], m.get("urls"))})
                n += 1
    return n


def gmail_takeout(days, out, index_out=None):
    """Gmail from a Takeout .mbox. Same rule as Apple Mail: keep mail you sent and mail from people you write to."""
    from .mail import _addr, _body, _ts
    boxes = _find("*.mbox")
    if not boxes:
        raise FileNotFoundError("no Takeout mail yet: ask for it (python3 -m ctx request google, or takeout.google.com with Mail ticked); when the zip is in downloads: python3 -m ctx ingest")
    me, peers, n = set(), set(), 0
    for path in boxes:                       # pass 1: headers only
        for m in mailbox.mbox(path, factory=lambda f: email.message_from_binary_file(f, policy=email.policy.default)):
            if "Sent" in str(m.get("X-Gmail-Labels", "")):
                me.add(_addr(m["From"]))
                peers.update(a.lower() for _, a in email.utils.getaddresses([str(m["To"] or ""), str(m["Cc"] or "")]) if a)
    peers -= me
    for path in boxes:
        for m in mailbox.mbox(path, factory=lambda f: email.message_from_binary_file(f, policy=email.policy.default)):
            frm, ts, subj = _addr(m["From"]), _ts(m), str(m["Subject"] or "")[:150]
            if frm not in me and frm not in peers:      # a stranger or a list: sender and subject only, when an index is kept
                if index_out is not None:
                    put(index_out, {"id": rid("GI", m["Message-ID"] or (frm, ts, subj)), "src": "email_index", "ts": iso(ts), "title": frm, "text": subj})
                continue
            text = _body(m)
            if not text:
                continue
            thread = re.sub(r"^((re|fwd?|fw):\s*)+", "", subj.strip(), flags=re.I).lower()[:70]
            put(out, {"id": rid("GM", m["Message-ID"] or (frm, ts, subj, text[:200])), "src": "email", "ts": iso(ts), "thread_id": "em:" + thread, "thread": subj[:80] or "(no subject)", "kind": "dm",
                      "mine_total": 3, "who": "me" if frm in me else "them", "sender": "" if frm in me else frm.split("@")[0][:12], "text": text})
            n += 1
    return n


# ---------- archives that arrive as a zip in ~/Downloads ----------

KNOWN = [("x", r"^twitter-.*\.zip$"), ("google", r"^takeout-.*\.(zip|tgz)$"), ("linkedin", r"LinkedIn.?Data.?Export.*\.zip$"),
         ("instagram", r"^instagram-.*\.zip$"), ("notion", r"^Export-.*\.zip$"), ("chatgpt", r"^[0-9a-f]{20,}.*\.zip$")]
KEEP = (".js", ".json", ".mbox", ".csv", ".html", ".md", ".txt", ".vcf", ".ics")


def _is_chatgpt(names):
    """Is this list of file names a chatgpt export? Told by what is in it, never by what it is called: the conversations
    (one file, or split into conversations-000.json, -001.json, ...) beside the export's own manifest or user file."""
    names = {n.split("/")[-1] for n in names if n.count("/") <= 1}
    return any(re.fullmatch(r"conversations(-\d+)?\.json", n) for n in names) and bool(names & {"export_manifest.json", "user.json", "chat.html"})


def _take_folder(src, dest):
    """Copy an export's text files (not its pictures and attachments) from a folder the owner unzipped. The folder is left as it is."""
    for d, dirs, names in os.walk(src):
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        for n in names:
            if n.lower().endswith(KEEP) and not os.path.islink(os.path.join(d, n)):
                to = os.path.join(dest, os.path.relpath(os.path.join(d, n), src))
                os.makedirs(os.path.dirname(to), exist_ok=True)
                shutil.copyfile(os.path.join(d, n), to)


def ingest(downloads="~/Downloads"):
    """Unpack any known export zip from Downloads into imports/, text files only (no photos or videos). Returns what was new."""
    import tarfile, zipfile
    new, sizes = [], os.path.join(IMPORTS, ".ingested.json")
    wanted = lambda name: name.lower().endswith(KEEP) and ".." not in name and not name.startswith("/")
    for f in sorted(glob.glob(os.path.join(os.path.expanduser(downloads), "*"))):
        base = os.path.basename(f)
        try:
            with open(sizes) as fh:
                seen = json.load(fh)
        except (OSError, ValueError):
            seen = {}
        if os.path.isdir(f):        # an export the owner unzipped themselves: only chatgpt's is known by its contents
            try:
                inside = os.listdir(f)
            except OSError:
                continue
            dest = os.path.join(IMPORTS, f"chatgpt-{re.sub(r'[^A-Za-z0-9]+', '_', base)[:60]}")
            if not _is_chatgpt(inside) or os.path.exists(dest):
                continue
            key = "chatgpt:%d" % sum(os.path.getsize(os.path.join(f, n)) for n in inside if re.fullmatch(r"conversations(-\d+)?\.json", n))
            if key in seen:         # the same export as a zip already read, or this folder under another name
                continue
            seen[key] = base
            os.makedirs(IMPORTS, exist_ok=True)
            with open(sizes, "w") as fh:
                json.dump(seen, fh)
            _take_folder(f, dest)
            new.append(("chatgpt", base))
            continue
        kind = next((k for k, rx in KNOWN if re.search(rx, base)), None)
        if not kind and base.lower().endswith(".zip") and ("not:%s:%d" % (base, os.path.getsize(f))) not in seen:
            try:                    # a chatgpt export under any name: look inside once, and remember a zip that is not one
                kind = "chatgpt" if zipfile.is_zipfile(f) and _is_chatgpt(zipfile.ZipFile(f).namelist()) else None
            except (OSError, zipfile.BadZipFile):
                kind = None
            if not kind and zipfile.is_zipfile(f):
                seen["not:%s:%d" % (base, os.path.getsize(f))] = 1
                os.makedirs(IMPORTS, exist_ok=True)
                with open(sizes, "w") as fh:
                    json.dump(seen, fh)
        dest = os.path.join(IMPORTS, f"{kind}-{re.sub(r'[^A-Za-z0-9]+', '_', base)[:60]}") if kind else None
        if not kind or os.path.exists(dest):
            continue
        key, tgz = f"{kind}:{os.path.getsize(f)}", base.endswith(".tgz")
        # the same archive downloaded twice (same kind, same size) is read once; one still downloading or cut short
        # is left alone and looked at again next time
        if key in seen or not (tarfile.is_tarfile(f) if tgz else zipfile.is_zipfile(f)):
            continue
        seen[key] = base
        os.makedirs(IMPORTS, exist_ok=True)
        with open(sizes, "w") as fh:
            json.dump(seen, fh)
        if kind == "chatgpt":
            inside = zipfile.ZipFile(f).infolist()
            if not _is_chatgpt([i.filename for i in inside]):
                continue
            same = "chatgpt:%d" % sum(i.file_size for i in inside if re.fullmatch(r"conversations(-\d+)?\.json", i.filename.split("/")[-1]))
            if same in seen and seen[same] != base:     # the owner already unzipped this one and it was read as a folder
                continue
            seen[same] = base
            with open(sizes, "w") as fh:
                json.dump(seen, fh)
        os.makedirs(dest)
        with (tarfile.open(f) if tgz else zipfile.ZipFile(f)) as box:
            for m in (box if tgz else box.namelist()):
                if tgz and not (m.isfile() and wanted(m.name)) or not tgz and not wanted(m):
                    continue
                try:
                    box.extract(m, dest, filter="data") if tgz else box.extract(m, dest)
                except TypeError:      # python before 3.12 has no extraction filters; the checks above stand in
                    box.extract(m, dest)
        new.append((kind, base))
    return new


def idtext(s):
    """The text an id may be made from. Some ids are made from what a row says (an export gives the row no number of its
    own). The raw export files can be scrubbed in place (ctx/rawscrub.py), which changes what a row says where it held
    a secret: so the id is made from the text as that scrub leaves it, which is the same before the scrub and after.
    For text with nothing to scrub, which is nearly all of it, this is the text itself and the id is what it always was."""
    from .rawscrub import careful
    return careful(s) if isinstance(s, str) else s


def _fix(s):   # Instagram and Facebook exports store UTF-8 as Latin-1 escapes
    try:
        return s.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def instagram_dms(days, out):
    import collections
    files = [f for f in _find("message_*.json") if "/inbox/" in f or "/message_requests/" in f]
    if not files:
        raise FileNotFoundError("no Instagram export in imports/")
    names = collections.Counter(p.get("name", "") for f in files for p in paths.read_json(f).get("participants", []))
    me, n, used = names.most_common(1)[0][0], 0, set()       # the owner is the one name in every conversation
    for f in files:
        d = paths.read_json(f)
        tid, title = os.path.basename(os.path.dirname(f)), _fix(d.get("title", ""))
        mine = sum(m.get("sender_name") == me for m in d.get("messages", []))
        for m in d.get("messages", []):
            if not m.get("content"):
                continue
            mid = f"IG{tid[-10:]}_{m.get('timestamp_ms')}"
            if mid in used:       # two messages in the same millisecond: the later ones are told apart by what they say
                mid += "_%d" % stable(idtext(m["content"]), 6)
            used.add(mid)
            put(out, {"id": mid, "src": "instagram", "ts": iso(m.get("timestamp_ms", 0) / 1000), "thread_id": "ig" + tid,
                      "thread": title or tid, "kind": "group" if len(d.get("participants", [])) > 2 else "dm", "mine_total": mine + 3 if mine else 0,
                      "who": "me" if m.get("sender_name") == me else "them", "sender": "" if m.get("sender_name") == me else _fix(m.get("sender_name", ""))[:20],
                      "text": _fix(m["content"])})
            n += 1
    return n


def _ig_post(row):
    """One saved or liked post from the export: (url, caption, account). The export nests labelled values."""
    url = cap = user = ""
    def walk(items, top):
        nonlocal url, cap, user
        for x in items or []:
            if not isinstance(x, dict):
                continue
            label, val = x.get("label"), x.get("value") or x.get("href") or ""
            if label == "URL" and top and not url:
                url = val
            elif label == "Caption" and not cap:
                cap = val
            elif label == "Username" and not user:
                user = val
            for sub in x.get("dict") or []:
                walk(sub.get("dict") if isinstance(sub, dict) else None, False)
    walk(row.get("label_values"), True)
    return url, _fix(cap), _fix(user)


def _ig_posts(name, src, prefix, out):
    files = [f for f in _find(name) if "/your_instagram_activity/" in f]
    if not files:
        raise FileNotFoundError("no Instagram export in imports/")
    seen, n = set(), 0
    for f in files:
        rows = paths.read_json(f)
        for r in rows if isinstance(rows, list) else []:
            url, cap, user = _ig_post(r)
            key = url or f"{r.get('timestamp')}{user}"
            if key in seen or not (cap or url):
                continue
            seen.add(key)
            put(out, {"id": prefix + (url.rstrip("/").rsplit("/", 1)[-1] if url else str(r.get("timestamp")))[:24], "src": src,
                      "ts": iso(r.get("timestamp", 0)), "title": user, "text": cap[:2000], "url": url})
            n += 1
    return n


def instagram_saved(days, out):
    """Posts and reels the owner saved: the caption and the account, not the video."""
    return _ig_posts("saved_posts.json", "instagram_saved", "IS", out)


def instagram_likes(days, out):
    """Posts and reels the owner liked: the caption and the account."""
    return _ig_posts("liked_posts.json", "instagram_likes", "IL", out)


def linkedin_dms(days, out):
    """LinkedIn messages from every export in imports/ (a basic one, a complete one, an older one): a message in two of
    them is one row, since its id is made from what it says. A draft was never sent and is left out."""
    from .linkedin import table
    files = sorted(_find("messages.csv"), key=os.path.getmtime, reverse=True)
    if not files:
        raise FileNotFoundError("no LinkedIn export in imports/")
    me = ""
    for f in sorted(_find("Profile.csv"), key=os.path.getmtime, reverse=True):
        r = (table(f, ("First Name", "Last Name")) or [{}])[0]
        me = f'{r.get("First Name", "")} {r.get("Last Name", "")}'.strip()
        if me:
            break
    rows, seen = [], set()
    for f in files:
        for r in table(f, ("CONVERSATION ID", "FROM", "CONTENT")):
            cid = r.get("CONVERSATION ID", "")
            key = rid("LI", cid, r.get("DATE"), r.get("FROM"), idtext(r.get("CONTENT")))
            if not r.get("CONTENT") or key in seen or r.get("IS MESSAGE DRAFT", "").lower() == "yes":
                continue
            seen.add(key)
            rows.append((key, cid, r))
    mine, n = {}, 0
    for _, cid, r in rows:
        mine[cid] = mine.get(cid, 0) + (r.get("FROM") == me)
    for key, cid, r in rows:
        put(out, {"id": key, "src": "linkedin", "ts": (r.get("DATE") or "")[:19].replace(" ", "T") + "Z", "thread_id": "li" + cid,
                  "thread": r.get("CONVERSATION TITLE") or (r.get("TO") if r.get("FROM") == me else r.get("FROM")) or "?", "kind": "dm",
                  "mine_total": mine[cid] + 3 if mine[cid] else 0, "who": "me" if r.get("FROM") == me else "them",
                  "sender": "" if r.get("FROM") == me else (r.get("FROM") or "")[:20], "text": r["CONTENT"]})
        n += 1
    return n


def takeout_docs(days, out):
    """YouTube watch and search history, Keep notes, Chrome history from a Google Takeout."""
    n = 0
    for f in _find("watch-history.json") + _find("search-history.json"):
        for e in paths.read_json(f):
            put(out, {"id": f"YT{stable(e.get('titleUrl', '') + e.get('time', ''), 10)}", "src": "youtube", "ts": (e.get("time") or "")[:19] + "Z",
                      "title": ", ".join(s.get("name", "") for s in e.get("subtitles", [])), "text": e.get("title", ""), "url": (e.get("titleUrl") or "").split("&")[0]})
            n += 1
    for f in _find("watch-history.html") + _find("search-history.html"):
        s = paths.read_text(f, encoding="utf-8", errors="ignore")
        for m in re.finditer(r'<a href="(https://www\.youtube\.com/[^"]+)">([^<]+)</a>(?:<br>\s*<a [^>]*>([^<]*)</a>)?<br>([^<]{8,40})<', s):
            put(out, {"id": f"YH{stable(m.group(1) + m.group(4), 10)}", "src": "youtube", "ts": "", "title": m.group(3) or "", "text": m.group(2) + " | " + m.group(4).strip(), "url": m.group(1).split("&")[0]})
            n += 1
    for f in (f for f in _find("*.json") if "/Keep/" in f):
        d = paths.read_json(f)
        text = d.get("textContent") or "\n".join(("[x] " if i.get("isChecked") else "[ ] ") + i.get("text", "") for i in d.get("listContent", []))
        if not text.strip():
            continue
        put(out, {"id": "KP" + os.path.basename(f)[:-5][-12:], "src": "google_keep", "ts": iso(d.get("userEditedTimestampUsec", 0) / 1e6),
                  "title": d.get("title", ""), "text": text[:20000]})
        n += 1
    if not n:
        raise FileNotFoundError("no Google Takeout (YouTube, Keep) in imports/")
    return n


def notion_docs(days, out):
    files = [f for f in _find("*.md") if "/notion-" in f]
    if not files:
        raise FileNotFoundError("no Notion export in imports/")
    for f in files:
        put(out, {"id": "NO" + str(stable(os.path.relpath(f, IMPORTS), 10)), "src": "notion", "ts": iso(os.path.getmtime(f)),
                  "title": re.sub(r"\s[0-9a-f]{32}$", "", os.path.basename(f)[:-3]), "text": paths.read_text(f, encoding="utf-8", errors="ignore")[:20000]})
    return len(files)


def linkedin_connections(days, out):
    """Who you know on LinkedIn: name, role, company, when you connected. Goes to docs. From every export in imports/,
    the newest first; a person in two of them is one row."""
    from .linkedin import table
    files = sorted(_find("Connections.csv"), key=os.path.getmtime, reverse=True)
    if not files:
        raise FileNotFoundError("no LinkedIn export in imports/")
    n, seen = 0, set()
    for f in files:
        for r in table(f, ("First Name", "Last Name", "Connected On")):      # the file opens with a notes block
            name = f'{r.get("First Name", "")} {r.get("Last Name", "")}'.strip()
            key = rid("LC", r.get("URL") or (name, r.get("Connected On"), r.get("Company")))
            if not name or key in seen:
                continue
            seen.add(key)
            try:
                ts = datetime.strptime(r.get("Connected On", ""), "%d %b %Y").strftime("%Y-%m-%dT00:00:00Z")      # the day as written, in no time zone
            except ValueError:
                ts = ""
            put(out, {"id": key, "src": "linkedin_connections", "ts": ts, "title": name,
                      "text": f'{r.get("Position", "")} at {r.get("Company", "")}'.strip(" at"), "url": r.get("URL", "")})
            n += 1
    return n
