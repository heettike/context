"""The tester report must carry nothing personal.

A made-up home folder is filled with obviously private strings in every place the report reads from: the source
record, the schedule, the model record, the ledger, the logs, the app's files, the indexes, other apps' config
files, the browser folder. The report is run the way a tester runs it, as a child process with HOME pointing at
that folder. None of the private strings may come out, as text or as json.

Every name, address, number, key and file name here is invented.
"""
import json, os, re, shutil, subprocess, sys, tempfile, time, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

USER = "zorblat"
HOST = "Quibblethorpe-MacBook-Pro"
PERSON = "Priya Raman"
MAIL = "priya.raman@fernhollow.example"
PHONE = "+1 415 555 0142"
KEY = "sk-ant-api03-FAKE-FAKE-FAKE-Q7mWx2-not-a-real-key"
LINK = "https://fernhollow.example/board/q3-layoffs"
FOLDER = "Divorce Papers"
FILE = "final settlement draft.pdf"
THREAD = "Lisbon trip planning"
# no piece of the above may appear in the report, in any letter case
PRIVATE = ["zorblat", "quibblethorpe", "priya", "raman", "fernhollow", "0142", "q7mwx2", "sk-ant", "layoffs", "divorce", "settlement", "lisbon", "marmalade", "hunter"]


def seed(root):
    """The made-up home. Returns (home, archive)."""
    home = os.path.join(root, "Users", USER)
    v2 = os.path.join(home, ".context", "v2")
    secret = os.path.join(home, "Documents", FOLDER)
    now = int(time.time())

    def put(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text if isinstance(text, str) else json.dumps(text))

    def lines(rows):
        return "".join(json.dumps(r) + "\n" for r in rows)
    everything = f"{PERSON} <{MAIL}> {PHONE} {KEY} {LINK} on {HOST} in {secret}/{FILE} about {THREAD}"
    put(os.path.join(v2, "status.json"), {
        "whatsapp": {"rows": 3, "secs": 1.2, "new": 1},
        "imessage": {"skipped": "blocked by macOS: grant Full Disk Access to the app running this (System Settings > Privacy & Security)", "new": 0},
        "telegram": {"skipped": f"error: KeyError: '{PERSON}'", "new": 0},
        "slack": {"rows": 2, "stale": True, "why": f"[Errno 2] No such file or directory: '{secret}/{FILE}'", "new": 0},
        "email": {"skipped": f"error: OperationalError: no such table: {PERSON.replace(' ', '_')}_notes", "new": 0},
        "claude_code": {"rows": 1, "stale": True, "why": "read nothing this time, so the rows from last time are kept", "new": 0},
        "codex": {"skipped": everything, "new": 0},
        "cursor": {"skipped": f"error: RuntimeError: could not sign in as {MAIL} at {LINK}, call {PHONE}", "new": 0},
        "obsidian": {"skipped": f"the vault at {secret}/{THREAD} could not be opened by {USER} on {HOST}", "new": 0},
        "apple_notes": {"skipped": "not installed or no data", "new": 0},
        "custom_marmalade_diary": {"rows": 4, "secs": 0.3, "new": 4}})
    put(os.path.join(v2, "custom", "enabled.json"), ["marmalade_diary"])
    put(os.path.join(v2, "custom", "marmalade_diary.json"), {"kind": "messages", "name": "Marmalade Diary", "folders": [secret]})
    put(os.path.join(v2, "schedule.json"), {"fast": now, "daily": now, "calendar": now, "exports": {"x": now, PERSON: now},
                                             "daily_results": {"slack": {"state": "needs_you", "detail": f"sign in to slack as {MAIL}"},
                                                               "calendar": {"state": "failed", "detail": f"RuntimeError: {THREAD} could not be listed"},
                                                               "gdrive": {"state": "skipped", "detail": "no refresher for this source yet"},
                                                               "x_bookmarks": {"state": PERSON, "detail": everything}}})
    put(os.path.join(v2, "models.json"), {
        "refreshed": now, "limited": {"claude": {"until": now + 3600, "why": f"your plan's limit was reached; it resets when {PERSON} pays."}, PERSON: {"until": now + 3600}},
        "probed": {"claude:haiku": {"ok": True, "id": "claude-haiku-5-5", "first": 0.82, "total": 1.9, "at": now, "plan": "claude", "ask": "haiku", "name": "haiku", "description": ""},
                   "codex:x": {"ok": False, "error": f"the account {MAIL} is suspended", "plan": "codex", "ask": "gpt-priya-raman", "name": PERSON, "at": now},
                   "claude:" + PERSON: {"ok": True, "id": f"claude-{USER}-20250929", "first": 1.1, "total": 2.2, "at": now, "plan": PERSON, "ask": "sonnet", "name": PERSON}}})
    put(os.path.join(v2, "settings.json"), {"preset": PERSON, "models": {"routine": "priya-private-model"}, "embedder": f"file:{secret}/embed"})
    put(os.path.join(v2, "model.json"), {"using": PERSON, "at": now})
    put(os.path.join(v2, "ledger.jsonl"), lines([
        {"tag": "answer:plan", "model": "haiku", "backend": "claude", "in": 10, "out": 5, "usd": 0, "secs": 1.5, "at": now},
        {"tag": "answer:plan", "model": "haiku", "backend": "claude", "in": 10, "out": 5, "usd": 0, "secs": 2.5, "at": now},
        {"tag": "answer:rerank", "model": "haiku", "backend": "claude", "in": 10, "out": 5, "usd": 0, "secs": 0.7, "at": now},
        {"tag": "answer", "model": "sonnet", "backend": "claude", "in": 10, "out": 5, "usd": 0, "secs": 9.0, "at": now},
        {"tag": "answer", "model": "sonnet", "backend": "claude", "error": f"claude: usage limit reached for {MAIL}", "at": now},
        {"tag": "bench_" + PERSON.replace(" ", "_"), "model": PERSON, "backend": "claude", "error": everything, "at": now},
        {"tag": PERSON + ":" + THREAD, "model": "x", "backend": "claude", "in": 1, "out": 1, "secs": 1, "at": now},
        {"tag": "priya:raman", "model": "x", "backend": "claude", "in": 1, "out": 1, "secs": 1, "at": now},
        {"tag": "answer:agent:quick", "model": "sonnet", "backend": "claude", "error": "Not logged in · Please run /login", "at": now - 90000},
        {"tag": "answer", "model": "sonnet", "backend": "claude", "at": now, "error": f"Command '['claude', '-p', 'what did {PERSON} say about the settlement']' timed out after 240 seconds"},
        {"tag": "understand:read", "model": "sonnet", "backend": "claude", "error": f"{KEY} is not a valid key", "at": now}]) + "not json " + everything + "\n")
    rows = [{"id": f"W{i}", "src": "whatsapp", "ts": f"20{19 + i}-0{i + 3}-11T10:00:00Z", "thread_id": "wa1", "thread": THREAD, "kind": "dm", "who": "them", "sender": "0142",
             "text": everything} for i in range(3)]
    put(os.path.join(v2, "parts", "whatsapp.jsonl"), lines(rows))
    put(os.path.join(v2, "parts", "slack.jsonl"), lines([dict(r, src="slack", id="S" + r["id"]) for r in rows[:2]]))
    put(os.path.join(v2, "parts", "claude_code.jsonl"), lines([{"id": "C1", "src": "claude_code", "title": THREAD, "project": secret, "first_user": everything, "last_agent_ts": "2025-08-02T10:00:00Z"}]))
    put(os.path.join(v2, "parts", "custom_marmalade_diary.jsonl"), lines([dict(r, src="custom_marmalade_diary") for r in rows]))
    put(os.path.join(v2, "messages.jsonl"), lines(rows))
    put(os.path.join(v2, "sessions.jsonl"), lines([{"id": "C1", "src": "claude_code", "title": THREAD, "project": secret, "first_user": everything, "last_agent_ts": "2025-08-02T10:00:00Z"}]))
    put(os.path.join(v2, "docs.jsonl"), lines([{"id": "D1", "src": "obsidian", "ts": "2024-01-02T10:00:00Z", "title": FILE, "text": everything}]))
    put(os.path.join(v2, "prompts.jsonl"), "")
    put(os.path.join(v2, "collect.log"), "\n".join([
        '@' + json.dumps({"src": "whatsapp", "rows": 12, "at": "2024-03", "label": THREAD}),
        '@' + json.dumps({"src": PERSON, "rows": 12, "at": everything, "phase": everything}),
        "whatsapp     {'rows': 3, 'secs': 1.2, 'new': 1}",
        "telegram     {'skipped': \"error: KeyError: '%s'\", 'new': 0}" % PERSON,
        "Traceback (most recent call last):",
        f'  File "{secret}/context/ctx/collect.py", line 321, in claude_code',
        f"    for f in _recent('{secret}/{FILE}', days):",
        '  File "/usr/lib/python3.9/json/decoder.py", line 355, in raw_decode',
        f"KeyError: '{PERSON} <{MAIL}>'",
        "Traceback (most recent call last):",
        f'  File "{REPO}/ctx/mail.py", line 44, in mail',
        "sqlite3.OperationalError: database is locked",
        everything]) + "\n")
    put(os.path.join(v2, "telegram.log"), f"2025-02-14 10:00:01 login failed for {PHONE} on {HOST}\n" + json.dumps({"error": f"FloodWaitError: wait 30 seconds, {PERSON}"}) + "\n")
    put(os.path.join(v2, PERSON.lower().replace(" ", "-") + "-debug.log"), everything + "\nerror: " + everything + "\n")
    put(os.path.join(v2, "bad_replies.log"), json.dumps({"tag": "answer", "chars": 12, "head": "xxxx"}) + "\n")
    put(os.path.join(v2, "app.log"), "\n".join([
        f"2025-02-14 09:00:00 opened chat '{THREAD}' with {PERSON}",
        "2025-02-14 09:00:02 read nothing this time, so the rows from last time are kept",
        "09:00:03 " + json.dumps({"event": "sync", "src": "whatsapp", "new": 3, "rows": 120, "label": PERSON, "at": "2024-03"}),
        f"error: could not open {secret}/{FILE}",
        json.dumps({"event": "sync", "src": "custom_marmalade_diary", "new": 1, "rows": 4}),
        f"mailto:{MAIL} {LINK} {KEY} hunter2 {HOST}",
        everything] + [f"line {i} about {THREAD}" for i in range(40)]) + "\n")
    put(os.path.join(v2, "app.json"), {"python": f"{secret}/venv/bin/python3", "onboarded": True, "hadDisk": False, "hotkey": PERSON, PERSON: True})
    put(os.path.join(v2, "repo"), REPO + "\n")
    put(os.path.join(v2, "chats", "20261120-101010-abc123.json"), {"title": THREAD})
    put(os.path.join(v2, "chats", "lisbon-trip.json"), {"title": THREAD})
    put(os.path.join(v2, "imports", "priya-raman-whatsapp-export.zip"), "x")
    put(os.path.join(v2, "cache", "semantic", "meta.json"), {"built": "2025-02-14T10:00:00Z", "units": 12, "vectors": 10, "pending": 2, "embedder": f"file:{secret}/embed",
                                                             "model": PERSON, "per_source": {"whatsapp": 10, PERSON: 2, "custom_marmalade_diary": 1}, "archive": everything})
    put(os.path.join(v2, "memory", "wiki", "index.json"), {"pages": [{"id": "person:priya-raman", "kind": "person", "words": 120}, {"id": "x", "kind": PERSON, "words": 3}]})
    put(os.path.join(v2, "memory", "wiki", "_work", "state.json"), {"sig": {}, "dropped": {PERSON: 2}})
    put(os.path.join(v2, "memory", "wiki", "_work", "coverage.json"), {PERSON: 3, "note": everything})
    put(os.path.join(v2, "memory", "deep", "events", "events.jsonl"), lines([{"t": "intro", "a": PERSON, "rows": ["W0"]}, {"t": PERSON, "with": PERSON}]))
    entry = {"command": f"{secret}/venv/bin/python3", "args": ["-m", "ctx", "mcp"], "env": {"PYTHONPATH": f"{secret}/context"}}
    put(os.path.join(home, ".cursor", "mcp.json"), {"mcpServers": {"context": entry, "priya-notes": {"command": "node", "args": [FILE]}}})
    put(os.path.join(home, "Library", "Application Support", "Claude", "claude_desktop_config.json"), {"mcpServers": {"context": {"command": "node", "args": [LINK]}}})
    put(os.path.join(home, ".codex", "config.toml"), f'[mcp_servers.priya]\ncommand = "{secret}/run"\n\n[mcp_servers.context]\ncommand = "{secret}/venv/bin/python3"\nargs = ["-m", "ctx", "mcp"]\n')
    put(os.path.join(home, ".claude.json"), {"mcpServers": {"context": entry}, "oauthAccount": {"emailAddress": MAIL}})
    chrome = os.path.join(home, "Library", "Application Support", "Google", "Chrome")
    put(os.path.join(chrome, "Local State"), {"profile": {"last_used": PERSON}})
    put(os.path.join(chrome, PERSON, "History"), "x")
    put(os.path.join(chrome, PERSON, "Preferences"), {"browser": {"allow_javascript_apple_events": True}, "account_info": [{"email": MAIL}]})
    put(os.path.join(home, ".claude", "projects", "-Users-zorblat-Documents-Divorce-Papers", "session-1.jsonl"), lines([
        {"type": "user", "cwd": secret, "timestamp": "2025-08-02T10:00:00Z", "message": {"content": everything}},
        {"type": "assistant", "cwd": secret, "timestamp": "2025-08-02T10:00:05Z", "message": {"content": [{"type": "text", "text": "noted: " + everything}]}}]))
    put(os.path.join(home, "Library", "Logs", "context", "priya.log"), everything + "\n")
    return home, v2


def run(home, *args, timeout=300):
    env = {"HOME": home, "USER": USER, "LOGNAME": USER, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8", "CTX_ANY_OS": "1", "CTX_MODEL": "none",
           "CTX_BROWSER_DATA": os.path.join(home, "Library", "Application Support"), "SHELL": "/bin/zsh",
           "CTX_CLI_PATH": os.path.join(home, "no-cli"), "ANTHROPIC_API_KEY": ""}       # the model CLIs of this mac are never found, nor a key in .env
    return subprocess.run([sys.executable, "-m", "ctx", "report", *args], cwd=REPO, env=env, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


def leaks(text, private=PRIVATE):
    """Everything in a report that should not be there: a private word, an @, a link, a long run of digits."""
    low = text.lower()
    found = [w for w in private if w in low]
    found += ["@"] if "@" in text else []
    found += ["http"] if "http" in low else []
    found += re.findall(r"\d{7,}", text)
    return found


class Seeded(unittest.TestCase):
    """One run of each form of the report over the made-up home, checked many ways."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="ctx-report-test-")
        cls.home, cls.v2 = seed(cls.root)
        cls.out = os.path.join(cls.root, "out", "report.txt")
        cls.text_run = run(cls.home, "--out", cls.out)
        cls.text = ""
        if os.path.exists(cls.out):
            with open(cls.out, encoding="utf-8") as f:
                cls.text = f.read()
        cls.json_run = run(cls.home, "--json")
        try:
            cls.data = json.loads(cls.json_run.stdout)
        except ValueError:
            cls.data = {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_it_runs_and_says_to_read_it(self):
        self.assertEqual(self.text_run.returncode, 0, self.text_run.stderr[-800:])
        self.assertEqual(self.json_run.returncode, 0, self.json_run.stderr[-800:])
        said = self.text_run.stdout.strip().splitlines()
        self.assertEqual(said[0], self.out)
        self.assertIn("read it before you send it", said[1])

    def test_no_private_string_in_the_text(self):
        self.assertTrue(self.text)
        self.assertEqual(leaks(self.text), [])

    def test_no_private_string_in_the_json(self):
        self.assertTrue(self.data)
        self.assertEqual(leaks(self.json_run.stdout), [])

    def test_nothing_private_on_the_terminal_either(self):
        # the only private thing either stream may hold is the path the tester asked for, which is theirs to see
        for s in (self.text_run.stderr, self.json_run.stderr, self.text_run.stdout.replace(self.out, "")):
            self.assertEqual(leaks(s), [])

    def test_the_text_is_short_lowercase_and_starts_by_saying_what_it_is(self):
        lines = self.text.splitlines()
        self.assertLessEqual(len(lines), 300)
        self.assertEqual(self.text, self.text.lower())
        head = " ".join(lines[:9])
        for words in ("it holds counts, states, versions and timings", "it does not hold any message", "read it before you send it"):
            self.assertIn(words, head)
        for section in ("tool", "this mac", "browsers and apps", "permissions, as the engine saw them", "sources", "model plan", "index, read-through, events, wiki",
                        "other ai apps (mcp)", "the mac app", "engine errors (the last 30)", "timings"):
            self.assertIn("\n" + section + "\n" + "-" * len(section) + "\n", self.text)
        self.assertLessEqual(max(len(l) for l in lines), 240)

    def test_sources_are_counts_states_and_months(self):
        rows = {r["source"]: r for r in self.data["sources"]["rows"]}
        self.assertEqual((rows["whatsapp"]["state"], rows["whatsapp"]["rows"], rows["whatsapp"]["earliest"], rows["whatsapp"]["latest"], rows["whatsapp"]["secs"]),
                         ("ok", 3, "2019-03", "2021-05", 1.2))
        self.assertEqual((rows["imessage"]["state"], rows["telegram"]["state"], rows["slack"]["state"], rows["claude_code"]["state"]), ("skipped", "failed", "stale", "stale"))
        self.assertEqual(rows["whatsapp"]["tier"], "fast")
        self.assertEqual(rows["notion"]["state"], "not tried")
        self.assertIn("2019-03", self.text)
        self.assertNotIn("2019-03-11", self.text)       # a month, never a day

    def test_a_reason_of_ours_is_kept_and_any_other_becomes_its_length(self):
        rows = {r["source"]: r for r in self.data["sources"]["rows"]}
        self.assertEqual(rows["imessage"]["reason"], "blocked by macOS: grant Full Disk Access to the app running this (System Settings > Privacy & Security)")
        self.assertEqual(rows["claude_code"]["reason"], "read nothing this time, so the rows from last time are kept")
        self.assertEqual(rows["apple_notes"]["reason"], "not installed or no data")
        self.assertEqual(rows["telegram"]["reason"], "error: KeyError: <13 chars>")
        self.assertTrue(rows["email"]["reason"].startswith("error: OperationalError: no such table: <"))
        self.assertRegex(rows["codex"]["reason"], r"^<\d+ chars>$")
        self.assertRegex(rows["slack"]["reason"], r"^\[Errno 2\] No such file or directory: '~/Documents/…'$")
        self.assertEqual(rows["gdrive"]["reason"], "no refresher for this source yet")
        self.assertEqual(self.data["permissions"]["sources_blocked_by_macos"], ["imessage"])

    def test_a_source_the_owner_added_is_numbered_not_named(self):
        names = [r["source"] for r in self.data["sources"]["rows"]]
        self.assertFalse([n for n in names if n.startswith("custom_") and not re.fullmatch(r"custom_\d+", n)])

    def test_model_calls_are_counted_by_our_own_tags_and_error_classes(self):
        c = self.data["calls"]
        self.assertEqual(c["calls"], 11)
        self.assertEqual(c["failed"], 5)
        self.assertEqual(c["error_classes"], {"limit": 1, "other": 2, "not signed in": 1, "timeout": 1})
        self.assertEqual(c["today_by_tag"]["answer:plan"], 2)
        self.assertEqual(set(c["today_by_tag"]) - {"answer", "answer:plan", "answer:rerank", "bench", "understand:read", "other"}, set())
        self.assertEqual(self.data["timings"]["answer_steps"]["plan"], {"median_secs": 2.0, "calls": 2})
        self.assertEqual(self.data["timings"]["first_token_secs"], 1.0)

    def test_the_model_plan_names_no_account(self):
        m = self.data["model"]
        self.assertEqual(m["using"], "none")
        self.assertEqual(m["preset"], "balanced")           # the made-up one was not a preset
        got = {x["model"]: x for x in m["measured"]}
        self.assertEqual(got["claude-haiku-5-5"]["first_secs"], 0.82)
        self.assertIn("claude-…-2025-09-29", got)
        self.assertEqual(m["plans_at_limit"], ["claude", "other"])

    def test_errors_are_a_type_our_own_file_and_line_and_a_redacted_message(self):
        last = self.data["errors"]["last"]
        self.assertLessEqual(len(last), 30)
        self.assertIn({"when": time.strftime("%Y-%m-%d"), "where": "collect.log", "type": "OperationalError", "at": "mail.py:44", "message": "database is locked"}, last)
        key = [e for e in last if e["type"] == "KeyError"]
        self.assertTrue(key and all(re.fullmatch(r"<\d+ chars>", e["message"]) for e in key))
        self.assertIn("collect.py:321", [e["at"] for e in key])
        self.assertEqual({l["log"] for l in self.data["errors"]["logs"]}, {"collect.log", "telegram.log", "bad_replies.log", "app.log", "other.log"})

    def test_the_apps_log_is_kept_only_where_it_is_ours(self):
        log = self.data["app"]["log"]
        self.assertLessEqual(len(log), 50)
        self.assertEqual(self.data["app"]["log_lines"], 47)
        self.assertIn("2025-02-14 09:00:02 read nothing this time, so the rows from last time are kept", log)
        self.assertIn("09:00:03 event=sync src=whatsapp new=3 rows=120 at=2024-03 (+1 fields not shown)", log)
        self.assertIn("event=sync src=other new=1 rows=4", log)
        self.assertEqual(log[-1], "(42 lines that held none of our own messages: not shown)")
        self.assertEqual(len(log), 6)
        self.assertEqual(self.data["app"]["python"], "~/Documents/…")
        self.assertEqual(self.data["app"]["state"], {"onboarded": True, "hadDisk": False})
        self.assertEqual(self.data["app"]["finds_engine"], True)
        self.assertEqual(self.data["app"]["chats_saved"], 2)

    def test_other_apps_are_states_by_id_with_home_relative_config_names(self):
        rows = {r["id"]: r for r in self.data["mcp"]}
        self.assertEqual(rows["cursor"]["config"], "~/.cursor/mcp.json")
        self.assertEqual(rows["claude_desktop"]["config"], "~/Library/Application Support/Claude/claude_desktop_config.json")
        self.assertEqual(rows["cursor"]["state"], "not registered")
        for r in self.data["mcp"]:
            self.assertIn(r["state"], ("connected", "registered", "not registered", "app not found", "needs remote", "remote on", "remote off"))

    def test_indexes_are_counts(self):
        ix = self.data["indexes"]
        self.assertEqual((ix["meaning"]["units"], ix["meaning"]["vectors"], ix["meaning"]["embedder"], ix["meaning"]["built"]), (12, 10, "file", "2025-02-14"))
        self.assertEqual(ix["meaning"]["per_source"]["whatsapp"], 10)
        self.assertEqual(ix["wiki"]["pages"], 2)
        self.assertEqual(ix["events"]["events"], 2)

    def test_serve_returns_the_same_report_as_data(self):
        env = {"HOME": self.home, "USER": USER, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8", "CTX_ANY_OS": "1", "CTX_MODEL": "none",
               "CTX_CLI_PATH": os.path.join(self.home, "no-cli"), "ANTHROPIC_API_KEY": ""}
        p = subprocess.Popen([sys.executable, "-u", "-m", "ctx", "serve"], cwd=REPO, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.addCleanup(p.kill)
        p.stdin.write(json.dumps({"id": 7, "cmd": "report"}) + "\n")
        p.stdin.flush()
        got, raw = [], ""
        for line in p.stdout:               # stdin stays open until the answer is in: closing it cancels what is running
            raw += line
            got.append(json.loads(line))
            if got[-1] == {"id": 7, "end": True}:
                break
        p.stdin.close()
        p.wait(timeout=30)
        p.stdout.close()
        result = next(g["result"] for g in got if g.get("id") == 7 and "result" in g)
        self.assertEqual(list(result), list(self.data))
        self.assertEqual(result["sources"]["rows"], self.data["sources"]["rows"])
        self.assertEqual(leaks(raw), [])

    def test_this_mac_is_described_without_its_name(self):
        m = self.data["machine"]
        self.assertIn(m["arch"], ("arm64", "x86_64", "other"))
        self.assertEqual(m["archive"], "~/.context/v2")
        self.assertTrue(m["python"])
        self.assertNotIn(os.path.basename(os.path.expanduser("~")).lower() + "/", json.dumps(m).lower())


class Try(unittest.TestCase):
    def test_try_reads_into_a_temp_folder_times_each_step_and_leaks_nothing(self):
        root = tempfile.mkdtemp(prefix="ctx-report-try-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        home, v2 = seed(root)
        before = sorted(os.listdir(os.path.join(v2, "parts")))
        with open(os.path.join(v2, "status.json")) as f:
            status = f.read()
        r = run(home, "--json", "--try", timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertEqual(leaks(r.stdout), [])
        steps = {s["step"]: s for s in json.loads(r.stdout)["try"]["steps"]}
        self.assertEqual(list(steps), ["doctor", "read the file sources", "mcp self-test", "one tiny model call"])
        self.assertTrue(all(isinstance(s["secs"], (int, float)) for s in steps.values()))
        self.assertTrue(steps["doctor"]["ok"])
        read = steps["read the file sources"]
        self.assertEqual(read["into"], "a temp folder, removed after")
        self.assertEqual((read["by_source"]["claude_code"]["state"], read["by_source"]["claude_code"]["rows"]), ("ok", 1))     # the made-up session was really read
        self.assertEqual(steps["mcp self-test"]["checks"], {"initialize": True, "tools_list": True, "one_call": True})
        self.assertIsNone(steps["one tiny model call"]["ok"])           # no plan is signed in here, so no call was made
        # the archive that was already there was not touched
        self.assertEqual(sorted(os.listdir(os.path.join(v2, "parts"))), before)
        with open(os.path.join(v2, "status.json")) as f:
            self.assertEqual(f.read(), status)


class Rules(unittest.TestCase):
    """The redactor's rules, one at a time."""

    @classmethod
    def setUpClass(cls):
        from tests import fixture  # noqa: F401  (ctx.paths is fixed at import: point it at the made-up archive first)
        from ctx import report
        cls.report = report
        cls.R = report.Redactor(extra=["hunter2"], home="/Users/" + USER, users={USER, PERSON, "Priya", "Raman"}, hosts={HOST, HOST + ".local"})

    def test_home_user_and_host(self):
        c = self.R.clean
        self.assertEqual(c(f"/Users/{USER}/.context/v2 is missing"), "~/.context/v2 is missing")
        self.assertEqual(c(f"saved by {USER} on {HOST}.local"), "saved by <user> on <host>")
        self.assertEqual(c("quibblethorpe macbook pro, PRIYA_RAMAN"), "<host>, <user>")
        self.assertEqual(c("/Users/someoneelse/x"), "/Users/<user>/…")
        self.assertEqual(c("the word hunter2 goes"), "the word <removed> goes")

    def test_paths_keep_only_what_describes_a_setup(self):
        p = self.R.path
        self.assertEqual(p(f"/Users/{USER}/Documents/{FOLDER}/{FILE}"), "~/Documents/…")
        self.assertEqual(p(f"/Users/{USER}/Desktop"), "~/Desktop")
        self.assertEqual(p(f"/Users/{USER}/Library/Application Support/Claude/claude_desktop_config.json"), "~/Library/Application Support/Claude/claude_desktop_config.json")
        self.assertEqual(p(f"/Users/{USER}/work/acme-secret/context"), "~/…/context")
        self.assertEqual(p("/opt/homebrew/Cellar/python@3.11/3.11.6/bin/python3.11"), "/opt/homebrew/Cellar/…/3.11.6/bin/python3.11")
        self.assertEqual(p("/Volumes/Priya Backup/context"), "/Volumes/…/context")
        self.assertEqual(p(f"/Users/{USER}/.pyenv/versions/3.12.1/bin/python3"), "~/.pyenv/versions/3.12.1/bin/python3")

    def test_a_path_with_spaces_inside_a_sentence_is_hidden_to_its_end(self):
        c = self.R.clean
        self.assertEqual(c(f"could not open /Users/{USER}/Documents/{FOLDER}/{FILE}"), "could not open ~/Documents/…")
        self.assertEqual(c(f"could not open /Users/{USER}/Documents/My Secret Plan"), "could not open ~/Documents/…")
        self.assertEqual(c(f"'/Users/{USER}/Library/Application Support/Claude/claude_desktop_config.json' was read"),
                         "'~/Library/Application Support/Claude/claude_desktop_config.json' was read")

    def test_mail_links_numbers_and_secrets_go(self):
        c = self.R.clean
        self.assertEqual(c(f"write to {MAIL} or see {LINK}"), "write to <mail> or see <link>")
        self.assertEqual(c("docs at fernhollow.example.com/board and www.fernhollow.org"), "docs at <link> and <link>")
        self.assertEqual(c(f"call {PHONE} now"), "call <number> now")
        self.assertEqual(c("id 12345678901 and 1234567 but 123456"), "id <number> and <number> but 123456")
        self.assertNotIn("Q7mWx2", c(f"key {KEY}"))
        self.assertEqual(c("a@b"), "ab")
        self.assertEqual(c("read on 2025-02-14 10:00 and 2019-03"), "read on 2025-02-14 10:00 and 2019-03")       # dates are not phone numbers
        self.assertEqual(c("mcp --http"), "mcp --web")

    def test_a_message_is_kept_only_when_it_is_ours(self):
        ph = self.R.phrase
        self.assertEqual(ph("not installed or no data"), "not installed or no data")
        self.assertEqual(ph("telegram needs one login: python3 -m ctx telegram-login"), "telegram needs one login: python3 -m ctx telegram-login")
        said = f"{PERSON} said the fund closes on friday"
        self.assertEqual(ph(said), "<%d chars>" % len(said))
        self.assertEqual(ph("error: ValueError: " + THREAD), "error: ValueError: <20 chars>")
        self.assertEqual(ph("OperationalError: database is locked"), "OperationalError: database is locked")
        self.assertEqual(ph(f"[Errno 13] Permission denied: '/Users/{USER}/Library/Messages/chat.db'"), "[Errno 13] Permission denied: '~/Library/…'")
        self.assertEqual(leaks(ph(f"[Errno 2] {PERSON}'s notes")), [])
        self.assertEqual(ph(""), "")
        self.assertEqual(ph("ModuleNotFoundError: No module named 'telethon'"), "ModuleNotFoundError: No module named 'telethon'")
        # a format of ours with one filling left empty, as signed_in.py writes it
        self.assertEqual(ph("needs to open a tab in dia, which takes over the window"),
                         "needs to open a tab in dia, which takes over the window")
        # mostly someone else's words: one length, not a skeleton of the sentence
        self.assertEqual(ph("codex: aaa bbb. ccc ddd: eee. fff: ggg. hhh: iii jjj"), "<52 chars>")
        # one of our format strings with a filling that is not ours: our words stay, the filling is counted
        self.assertEqual(ph(f"cannot read {PERSON}/History: database is locked"), "cannot read <11 chars>/history: database is locked")
        # one of ours with something else after it: ours stays, the rest is counted
        self.assertEqual(ph("read nothing this time, so the rows from last time are kept. " + THREAD), "read nothing this time, so the rows from last time are kept. <20 chars>")
        # a message cut short by the engine is still ours
        self.assertEqual(ph("blocked by macOS: grant Full Disk Access to the app"), "blocked by macOS: grant Full Disk Access to the app")

    def test_a_format_string_of_ours_is_kept_with_safe_fillings_only(self):
        ph = self.R.phrase
        ours = "needs: sign in to slack in chrome (the last read found no session)"       # doctor.py writes it with %s for the site and the browser
        self.assertEqual(ph(ours), ours)
        got = ph(f"needs: sign in to {PERSON} in {THREAD} (the last read found no session)")
        self.assertEqual(leaks(got), [])
        self.assertIn("chars>", got)

    def test_model_ids_and_tags_are_built_from_known_parts(self):
        r = self.report
        self.assertEqual(r._model_id("claude-sonnet-4-5-20250929"), "claude-sonnet-4-5-2025-09-29")
        self.assertEqual(r._model_id("gpt-5.2-codex"), "gpt-5.2-codex")
        self.assertEqual(r._model_id(PERSON), "…-…")
        self.assertEqual(r._tag("answer:agent:quick"), "answer:agent:quick")
        self.assertEqual(r._tag("bench_" + PERSON), "bench")
        self.assertEqual(r._tag(PERSON + ":plan"), "other")
        self.assertEqual(r._tag("answer:" + PERSON), "answer")

    def test_a_log_line_keeps_known_fields_and_drops_the_rest(self):
        line = self.report.logline
        known = {"whatsapp"}
        self.assertEqual(line(self.R, '@' + json.dumps({"src": "whatsapp", "rows": 12, "at": "2024-03", "label": THREAD}), known), "src=whatsapp rows=12 at=2024-03 (+1 fields not shown)")
        self.assertEqual(line(self.R, json.dumps({"src": PERSON, "at": PERSON, "error": PERSON}), known), "src=other at=? error=<11 chars>")
        self.assertEqual(line(self.R, f"2025-02-14 09:00:00 opened chat '{THREAD}'", known), "2025-02-14 09:00:00 <34 chars>")
        self.assertEqual(line(self.R, "09:00:02 not installed or no data", known), "09:00:02 not installed or no data")

    def test_seal_cleans_every_string_and_key(self):
        got = self.R.seal({MAIL: [f"at {LINK}", {"n": 3, PERSON: PHONE}], "ok": True, "x": None})
        self.assertEqual(got, {"<mail>": ["at <link>", {"n": 3, "<user>": "<number>"}], "ok": True, "x": None})

    def test_the_fixed_paragraph_passes_its_own_rules(self):
        self.assertEqual(leaks(self.report.ABOUT), [])
        self.assertEqual(self.report.ABOUT, self.report.ABOUT.lower())

    def test_property_no_seeded_token_survives_any_route(self):
        # every private string, alone and inside each kind of carrier, through each way text can leave
        carriers = ["{}", "error: KeyError: '{}'", "RuntimeError: {}", "needs: {}", "needs: sign in to {} in {} (the last read found no session)",
                    "[Errno 2] No such file or directory: '{}'", "{} timed out", "not installed or no data {}",
                    "read nothing this time, so the rows from last time are kept ({})", "no such table: {}", "{}: {}", "{}, {}. {} - {}"]
        path = f"/Users/{USER}/Documents/{FOLDER}/{FILE}"
        seeds = [USER, HOST, PERSON, MAIL, PHONE, KEY, LINK, FOLDER, FILE, THREAD, path, "hunter2", MAIL.upper(), PERSON.lower(), f"{PERSON} <{MAIL}> {PHONE} {KEY} {LINK} {path}"]
        for carrier in carriers:
            for s in seeds:
                text = carrier.replace("{}", s)
                for name, got in (("phrase", self.R.phrase(text)), ("log line", self.report.logline(self.R, "10:00:00 " + text)),
                                  ("log line, json", self.report.logline(self.R, json.dumps({"error": text, "label": text, "src": text, "at": text, "why": text}))),
                                  ("path", self.R.path(text)), ("model id", self.report._model_id(text)), ("tag", self.report._tag(text))):
                    self.assertEqual(leaks(got), [], (name, carrier, got))
        # the last pass alone (no allowlist before it) still removes what has a shape: names of this user and mac, mail, links, numbers, keys, user folders
        for s in (USER, HOST, PERSON, MAIL, PHONE, KEY, LINK, path, "hunter2"):
            for carrier in carriers:
                text = carrier.replace("{}", s)
                for got in (self.R.clean(text), json.dumps(self.R.seal({text: [text, {"k": text}]}), ensure_ascii=False)):
                    self.assertEqual(leaks(got), [], (carrier, got))


if __name__ == "__main__":
    unittest.main()
