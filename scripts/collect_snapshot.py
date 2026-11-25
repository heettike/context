"""Collect a made-up Mac and print a fingerprint of every row file it wrote.

Used when collect code is rearranged without meaning to change what it writes: run it before and after, and the two
outputs must be the same, byte for byte.

  python3 scripts/collect_snapshot.py            prints {file: [rows, sha256]} as json
  python3 scripts/collect_snapshot.py --keep     also prints the folder and leaves it there to look at

Everything it reads is invented here: a whatsapp database, an obsidian vault, agent sessions, and export zips for
instagram, linkedin, x, google takeout and notion. Nothing of the real user's is touched (HOME points at a temp folder).
"""
import hashlib, json, os, shutil, sqlite3, subprocess, sys, tempfile, zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXED = 1767268800      # 2026-01-01 12:00 utc: every made-up file gets this time, so "when it was changed" is the same on every run
APPLE = 978307200


def put(home, rel, text):
    path = os.path.join(home, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def build(home):
    ig = lambda s: s.encode("utf-8").decode("latin1")      # instagram writes utf-8 as latin-1 escapes
    # whatsapp
    db = os.path.join(home, "Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite")
    os.makedirs(os.path.dirname(db))
    con = sqlite3.connect(db)
    con.executescript("create table ZWACHATSESSION (Z_PK integer primary key, ZPARTNERNAME text, ZSESSIONTYPE integer);"
                      "create table ZWAMESSAGE (Z_PK integer primary key, ZMESSAGEDATE real, ZISFROMME integer, ZTEXT text, ZFROMJID text, ZCHATSESSION integer);")
    con.executemany("insert into ZWACHATSESSION values (?,?,?)", [(1, "Ada Lovelace", 0), (2, "Kiln crew", 1), (3, "Status", 3), (4, None, 0)])
    rows = [(n, FIXED - APPLE - 86400 * (40 - n), n % 2, f"message {n} about the kiln" if n % 7 else None, "4155550100@s.whatsapp.net", 1 + n % 4) for n in range(1, 41)]
    con.executemany("insert into ZWAMESSAGE values (?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    # notes and plans
    put(home, "Library/Application Support/obsidian/obsidian.json", json.dumps({"vaults": {"a": {"path": os.path.join(home, "vault")}}}))
    put(home, "vault/studio.md", "why the studio matters\n\n- glaze tests\n- the wheel\n")
    put(home, "vault/日記/plan [2026].md", "call zoë about the lease\n")
    put(home, "vault/.obsidian/workspace.json", "{}")
    put(home, ".context/v2/journal/2026-01-01.md", "throw six bowls. ring mira.\n")
    # agent sessions
    put(home, ".claude/projects/-p/0a1b2c3d-0000-4000-8000-000000000001.jsonl", "\n".join(json.dumps(x) for x in [
        {"type": "summary", "summary": "kiln timer"},
        {"type": "user", "cwd": "/Users/sam/proj", "timestamp": "2025-12-30T09:00:00.000Z", "message": {"content": "the timer drifts. fix it"}},
        {"type": "assistant", "cwd": "/Users/sam/proj", "timestamp": "2025-12-30T09:01:00.000Z", "message": {"content": [{"type": "text", "text": "found it"}]}},
        {"type": "user", "isMeta": True, "timestamp": "2025-12-30T09:02:00.000Z", "message": {"content": "meta"}},
        {"type": "user", "cwd": "/Users/sam/proj", "timestamp": "2025-12-30T09:03:00.000Z", "message": {"content": [{"type": "text", "text": "ship it"}]}},
        {"type": "assistant", "cwd": "/Users/sam/proj", "timestamp": "2025-12-30T09:04:00.000Z", "message": {"content": [{"type": "text", "text": "shipped"}]}}]) + "\nnot json\n")
    put(home, ".codex/sessions/2025/12/30/rollout-2025-12-30T10-00-00-0f3a9c1e-77aa-4b2e-9d10-aabbccddeeff.jsonl", "\n".join(json.dumps(x) for x in [
        {"type": "session_meta", "timestamp": "2025-12-30T10:00:00.000Z", "payload": {"cwd": "/Users/sam/glaze", "id": "0f3a9c1e"}},
        {"type": "event_msg", "timestamp": "2025-12-30T10:00:05.000Z", "payload": {"type": "user_message", "message": "list the glazes we have tried"}},
        {"type": "event_msg", "timestamp": "2025-12-30T10:00:09.000Z", "payload": {"type": "agent_message", "message": "celadon, tenmoku"}},
        {"type": "event_msg", "timestamp": "2025-12-30T10:00:10.000Z", "payload": {"type": "token_count"}}]) + "\n")
    # a chromium browser's history, two profiles
    for prof, rows in (("Default", [(1, "https://example.com/kilns?x=1#top", "Kilns  for sale", 3), (2, "https://accounts.example.com/login", "Sign in", 9),
                                    (3, "http://localhost:3000/", "dev", 1)]), ("Profile 1", [(1, "https://example.com/kilns", "Kilns", 2), (2, "https://example.org/glaze/", "", 1)])):
        db = os.path.join(home, "Library/Application Support/Google/Chrome", prof, "History")
        os.makedirs(os.path.dirname(db))
        con = sqlite3.connect(db)
        con.executescript("create table urls (id integer primary key, url text, title text, visit_count integer); create table visits (id integer primary key, url integer, visit_time integer);")
        con.executemany("insert into urls values (?,?,?,?)", rows)
        con.executemany("insert into visits (url, visit_time) values (?,?)", [(r[0], int((FIXED - 86400 * (k + 1) + 11644473600) * 1e6)) for r in rows for k in range(r[3])])
        con.commit()
        con.close()
    # grok bot: one thread and the roster that names it
    import base64
    blob = lambda key: os.path.join("Library/Application Support/Grok Bot/sand-client-persistence", base64.b32encode(key.encode()).decode().rstrip("=").lower() + ".blob")
    put(home, blob("sand.client.slice.account.u1.roster.last-roster"), json.dumps({"value": {"rows": [{"id": "agent0123456789abcdef", "name": "Kiln helper"}]}}))
    put(home, blob("sand.client.slice.account.u1.transcript.replicas.agent0123456789abcdef"), json.dumps({"value": {"entries": [
        {"seq": 2, "kind": "send-message", "timestampMs": (FIXED - 3000) * 1000, "message": {"type": "text", "content": "cone 6 for stoneware"}},
        {"seq": 1, "kind": "message", "role": "user", "timestampMs": (FIXED - 3600) * 1000, "content": "what cone for stoneware"},
        {"seq": 3, "kind": "message", "role": "user", "fromAgent": "x", "timestampMs": (FIXED - 2000) * 1000, "content": "agent chatter"},
        {"seq": 4, "kind": "message", "role": "user", "timestampMs": (FIXED - 1000) * 1000, "content": "<system>noise</system>"}]}}))
    put(home, blob("sand.client.slice.account.u1.transcript.replicas.broken"), "{not json")
    # export zips, as they land in Downloads
    dl = os.path.join(home, "Downloads")
    os.makedirs(dl)
    with zipfile.ZipFile(os.path.join(dl, "instagram-sam-2026-01-01-xyz.zip"), "w") as z:
        z.writestr("your_instagram_activity/messages/inbox/zoe_1234567890/message_1.json", json.dumps({
            "participants": [{"name": ig("Zoë")}, {"name": "Sam"}], "title": ig("Zoë"), "messages": [
                {"sender_name": ig("Zoë"), "timestamp_ms": 1650000000000, "content": ig("café tomorrow?")}, {"sender_name": "Sam", "timestamp_ms": 1650000060000, "content": "yes"},
                {"sender_name": "Sam", "timestamp_ms": 1650000060000, "content": "at ten"}, {"sender_name": "Sam", "timestamp_ms": 1650000070000}]}))
        z.writestr("your_instagram_activity/messages/message_requests/lee_22/message_1.json", json.dumps({
            "participants": [{"name": "Lee"}, {"name": "Sam"}, {"name": "Bo"}], "title": "Lee", "messages": [{"sender_name": "Lee", "timestamp_ms": 1660000000000, "content": "hi"}]}))
        post = lambda url, cap, user, ts: {"timestamp": ts, "label_values": [{"label": "URL", "value": url}, {"dict": [{"dict": [{"label": "Caption", "value": cap}, {"label": "Username", "value": user}]}]}]}
        z.writestr("your_instagram_activity/saved/saved_posts.json", json.dumps([post("https://example.com/p/AAA/", ig("a kiln café"), "potter", 1700000000),
                                                                                post("https://example.com/p/AAA/", "again", "potter", 1700000001), post("", "", "x", 1700000002)]))
        z.writestr("your_instagram_activity/likes/liked_posts.json", json.dumps([post("https://example.com/p/BBB/", "glaze drip", "glazer", 1700000100), post("", "no url here", "who", 1700000200)]))
        z.writestr("media/posts/1.mp4", "not text: must not be unpacked")
    with zipfile.ZipFile(os.path.join(dl, "Basic_LinkedInDataExport_01-01-2026.zip"), "w") as z:
        z.writestr("Profile.csv", "First Name,Last Name\nSam,Potter\n")
        z.writestr("messages.csv", "CONVERSATION ID,CONVERSATION TITLE,FROM,TO,DATE,CONTENT\nc1,,Lee Park,Sam Potter,2024-01-01 10:00:00 UTC,are you hiring\n"
                                   "c1,,Sam Potter,Lee Park,2024-01-01 11:00:00 UTC,not yet\nc2,Old chat,Ada Byron,Sam Potter,2023-05-05 09:00:00 UTC,\nc2,Old chat,Ada Byron,Sam Potter,2023-05-05 09:01:00 UTC,hello\n")
        z.writestr("Connections.csv", "Notes:\n\"a note\"\n\nFirst Name,Last Name,URL,Email Address,Company,Position,Connected On\nLee,Park,https://example.com/in/lee,,Acme,Engineer,05 Jan 2022\n"
                                      ",,,,,,\nAda,Byron,,,Engines,,bad date\n")
    with zipfile.ZipFile(os.path.join(dl, "twitter-2026-01-01-abcdef.zip"), "w") as z:
        z.writestr("data/account.js", "window.YTD.account.part0 = " + json.dumps([{"account": {"accountId": "11"}}]))
        z.writestr("data/tweets.js", "window.YTD.tweets.part0 = " + json.dumps([
            {"tweet": {"id_str": "1001", "created_at": "Wed Oct 10 20:19:24 +0000 2018", "full_text": "first bowl", "favorite_count": "3"}},
            {"tweet": {"id_str": "1002", "created_at": "garbage", "full_text": "a reply", "in_reply_to_screen_name": "lee"}}]))
        z.writestr("data/like.js", "window.YTD.like.part0 = " + json.dumps([{"like": {"tweetId": "2001", "fullText": "nice glaze", "expandedUrl": "https://example.com/t/2001"}}]))
        z.writestr("data/direct-messages.js", "window.YTD.direct_messages.part0 = " + json.dumps([{"dmConversation": {"conversationId": "11-22", "messages": [
            {"messageCreate": {"id": "9001", "senderId": "11", "createdAt": "2024-02-02T10:00:00.000Z", "text": "hello lee"}},
            {"messageCreate": {"id": "9002", "senderId": "22", "createdAt": "2024-02-02T10:01:00.000Z", "text": "hello sam"}},
            {"messageCreate": {"id": "9003", "senderId": "22", "createdAt": "2024-02-02T10:02:00.000Z", "text": ""}}, {"reactionCreate": {}}]}}]))
    with zipfile.ZipFile(os.path.join(dl, "takeout-20260101T000000Z-001.zip"), "w") as z:
        z.writestr("Takeout/YouTube and YouTube Music/history/watch-history.json", json.dumps([
            {"title": "Watched throwing a bowl", "titleUrl": "https://www.youtube.com/watch?v=abc&t=1", "time": "2024-03-03T10:00:00.000Z", "subtitles": [{"name": "Clay Channel"}]}]))
        z.writestr("Takeout/Keep/list.json", json.dumps({"title": "to buy", "userEditedTimestampUsec": 1700000000000000, "listContent": [{"text": "clay", "isChecked": True}, {"text": "sponge"}]}))
        z.writestr("Takeout/Keep/empty.json", json.dumps({"title": "nothing", "textContent": "  "}))
        z.writestr("Takeout/Mail/All mail.mbox", "".join(
            f"From x@example.com Mon Jan  1 00:00:00 2024\nFrom: {frm}\nTo: {to}\nSubject: {subj}\nDate: Mon, 01 Jan 2024 1{n}:00:00 +0000\nMessage-ID: <m{n}@example.com>\n"
            f"X-Gmail-Labels: {labels}\nContent-Type: text/plain; charset=utf-8\n\n{body}\n\n"
            for n, (frm, to, subj, labels, body) in enumerate([
                ("sam@example.com", "lee@example.com", "the kiln", "Sent", "can you lend me the kiln on friday?"), ("lee@example.com", "sam@example.com", "Re: the kiln", "Inbox", "yes, friday works."),
                ("news@shop.example", "sam@example.com", "50% off clay", "Inbox", "buy now"), ("lee@example.com", "sam@example.com", "Fwd: re: the kiln", "Inbox", "")])))
    node = lambda i, parent, role, text, kids=(), hidden=False: (i, {"parent": parent, "children": list(kids), "message": {
        "author": {"role": role}, "create_time": FIXED - 5000 + len(i), "metadata": {"is_visually_hidden_from_conversation": hidden},
        "content": {"content_type": "text", "parts": [text]}}})
    with zipfile.ZipFile(os.path.join(dl, "0123456789abcdef0123456789abcdef-2026-01-01.zip"), "w") as z:
        z.writestr("conversations.json", json.dumps([
            {"conversation_id": "conv-aaaa-bbbb-cccc-dddd-0001", "title": "glaze chemistry", "update_time": FIXED - 4000, "current_node": "n3", "mapping": dict([
                node("n0", None, "system", "you are helpful", ["n1"], hidden=True), node("n1", "n0", "user", "why does celadon craze", ["n2"]),
                node("n2", "n1", "assistant", "the glaze shrinks more than the body", ["n3"]), node("n3", "n2", "user", "how do i fix it")])},
            {"id": "conv-no-pointer-0002", "title": "no pointer", "update_time": FIXED - 3000, "mapping": dict([
                node("a", None, "user", "one question", ["b"]), node("b", "a", "assistant", "one answer")])},
            {"conversation_id": "conv-aaaa-bbbb-cccc-dddd-0001", "title": "the same chat again", "mapping": {}}, "not a conversation", {"title": "no mapping"}]))
    with zipfile.ZipFile(os.path.join(dl, "Export-0f3a9c1e-77aa.zip"), "w") as z:
        z.writestr("Studio plan 0123456789abcdef0123456789abcdef.md", "# studio plan\n\nrent the unit by march\n")
        z.writestr("img/photo.png", "binary")


def fix_times(home):
    for root in (os.path.join(home, "vault"), os.path.join(home, ".context", "v2", "imports"), os.path.join(home, ".context", "v2", "journal")):
        for d, _, files in os.walk(root):
            for f in files:
                os.utime(os.path.join(d, f), (FIXED, FIXED))


def snapshot(keep=False):
    home = os.path.join(tempfile.gettempdir(), "ctx-snapshot-home")      # the same path every run: some ids are made from a file's path
    shutil.rmtree(home, ignore_errors=True)
    os.makedirs(home)
    env = dict(os.environ, HOME=home, PYTHONPATH=REPO, TZ="UTC", CTX_ANY_OS="1")
    env.pop("CTX_HOME", None)
    run = lambda *a: subprocess.run([sys.executable, "-m", "ctx", *a], cwd=REPO, env=env, capture_output=True, text=True, timeout=600)
    try:
        build(home)
        first = run("ingest")
        fix_times(home)
        second = run("collect")
        for r in (first, second):
            if r.returncode:
                raise SystemExit("collect failed:\n" + r.stderr[-2000:])
        v2, out = os.path.join(home, ".context", "v2"), {}
        for d, _, files in os.walk(v2):
            for f in sorted(files):
                if f.endswith(".jsonl") and "imports" not in d and f != "ledger.jsonl":
                    data = open(os.path.join(d, f), "rb").read()
                    out[os.path.relpath(os.path.join(d, f), v2)] = [data.count(b"\n"), hashlib.sha256(data).hexdigest()]
        status = json.load(open(os.path.join(v2, "status.json")))
        out["status.json"] = {k: {x: v[x] for x in sorted(v) if x != "secs"} for k, v in sorted(status.items())}      # the time a read took is not part of what it wrote
        if keep:
            print(home, file=sys.stderr)
        return out
    finally:
        if not keep:
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    print(json.dumps(snapshot("--keep" in sys.argv), indent=1, sort_keys=True))
