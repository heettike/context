"""The commands a newcomer types first, run as they would run them, in a made-up home folder.

Each command is a child process with HOME pointing at a temp folder, so nothing of the real user is read and
nothing is written outside that folder. Every name and message here is invented.
"""
import json, os, shutil, subprocess, sys, tempfile, unittest, zipfile
from tests import files as _f

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Cli(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="ctx-cli-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.v2 = os.path.join(self.home, ".context", "v2")

    def ctx(self, *args, code=None, env=None):
        e = {"HOME": self.home, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8", "CTX_ANY_OS": "1",
             "CTX_CLI_PATH": os.path.join(self.home, "no-cli"), "ANTHROPIC_API_KEY": ""}       # the model CLIs of this mac are never found, nor a key in .env
        e.update(env or {})
        cmd = [sys.executable, "-m", "ctx", *args] if code is None else [sys.executable, "-c", code, *args]
        return subprocess.run(cmd, cwd=REPO, env=e, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)

    def put(self, rel, text):
        p = os.path.join(self.home, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    def rows(self, name):
        with open(os.path.join(self.v2, name + ".jsonl"), encoding="utf-8") as f:
            return [json.loads(l) for l in f]

    def test_not_a_mac_is_one_line_and_makes_nothing(self):
        # the check runs before anything is imported: one sentence, exit 1, no folder made
        r = self.ctx("doctor", code="import sys, runpy; sys.platform = 'linux'; sys.argv = ['ctx'] + sys.argv[1:]; runpy.run_module('ctx', run_name='__main__')",
                     env={"CTX_ANY_OS": ""})
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertEqual(r.stderr.strip(), "context reads mac apps and only runs on macos. (CTX_ANY_OS=1 skips this check.)")
        self.assertFalse(os.path.exists(os.path.join(self.home, ".context")))

    def test_no_command_and_wrong_command(self):
        self.assertIn("python3 -m ctx <command>", self.ctx().stdout)
        r = self.ctx("nope")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no such command: nope", r.stderr)

    def test_help_lists_every_command_on_one_screen(self):
        import re
        text = self.ctx("--help").stdout
        self.assertEqual(text, self.ctx().stdout)
        self.assertLessEqual(len(text.splitlines()), 56)      # one screen on a normal terminal
        src = _f.read(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ctx", "__main__.py"))
        for cmd in sorted(set(re.findall(r'cmd == "([a-z-]+)"', src))):
            self.assertRegex(text, r"(?m)(^  | \| )" + re.escape(cmd) + r"( |$)", cmd)
        for group in ("collect:", "ask:", "connect:", "maintain:"):
            self.assertIn("\n" + group, text)

    def test_each_command_explains_itself_and_runs_nothing(self):
        for cmd, want in (("answer", "--stream"), ("mcp", "--install"), ("remote", "--rotate"), ("collect", "read every source"), ("rank", "left hanging"), ("serve", "json lines")):
            r = self.ctx(cmd, "--help")
            self.assertEqual(r.returncode, 0, cmd)
            self.assertRegex(r.stdout, r"python3 -m ctx (\S+ \| )*" + cmd)
            self.assertIn(want, r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".context", "v2", "status.json")))      # `collect --help` did not collect
        self.assertRegex(self.ctx("version").stdout, r"^context \d+\.\d+\.\d+")

    def test_collect_on_an_empty_home(self):
        r = self.ctx("collect")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        with open(os.path.join(self.v2, "status.json")) as f:
            st = json.load(f)
        self.assertGreaterEqual(len(st), 28)
        for name, s in st.items():      # every source says a row count or one plain reason
            self.assertTrue(s.get("rows") == 0 or s.get("skipped"), (name, s))
            self.assertNotIn("error:", s.get("skipped", ""), name)
        self.assertEqual(self.rows("messages"), [])
        made = {n for n in os.listdir(self.home)}
        self.assertLessEqual(made, {".context", "Library"}, "collect wrote outside ~/.context")       # Library: python's own bytecode cache

    def test_collect_reads_made_up_sources_and_scrubs_them(self):
        key = "sk-ant-api03-" + "Zq9fK2mVx7Lr4TnB8cWd" * 3
        phrase = "abandon ability able about above absent absorb abstract absurd abuse access accident"
        self.put("Library/Application Support/obsidian/obsidian.json", json.dumps({"vaults": {"a": {"path": os.path.join(self.home, "vault")}}}))
        self.put("vault/keys.md", "my key " + key + " and the words " + phrase + "\n")
        self.put("vault/日記/plan [2026].md", "call zoë about the lease\n")
        self.put(".claude/projects/-p/0a1b2c3d-0000.jsonl", "\n".join(json.dumps(x) for x in [
            {"type": "user", "cwd": "/Users/sam/proj", "timestamp": "2026-10-01T09:00:00.000Z", "message": {"content": "the importer drops rows. key " + key}},
            {"type": "assistant", "cwd": "/Users/sam/proj", "timestamp": "2026-10-01T09:01:00.000Z", "message": {"content": [{"type": "text", "text": "found it"}]}}]) + "\nnot json\n")
        for _ in range(2):      # twice: the second read must give the same rows with the same ids
            r = self.ctx("collect")
            self.assertEqual(r.returncode, 0, r.stderr)
            docs, sessions, prompts = self.rows("docs"), self.rows("sessions"), self.rows("prompts")
            self.assertEqual(sorted(d["title"] for d in docs), ["keys", "plan [2026]"])
            self.assertEqual([s["id"] for s in sessions], ["C0a1b2c3d0000"])      # the whole of the app's own id, not its first eight
            self.assertEqual([p["id"] for p in prompts], ["C0a1b2c3d0000:0"])
        for root, _, files in os.walk(os.path.join(self.home, ".context")):
            for f in files:
                with open(os.path.join(root, f), encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
                self.assertNotIn(key[:30], text, f)
                self.assertNotIn("absent absorb", text, f)

    def test_ingest_unpacks_archives_and_ids_do_not_repeat(self):
        ig = lambda s: s.encode("utf-8").decode("latin1")      # instagram writes utf-8 as latin-1 escapes
        os.makedirs(os.path.join(self.home, "Downloads"))
        with zipfile.ZipFile(os.path.join(self.home, "Downloads", "instagram-sam-2026-11-01-xyz.zip"), "w") as z:
            z.writestr("your_instagram_activity/messages/inbox/zoe_1234567890/message_1.json", json.dumps({
                "participants": [{"name": ig("Zoë")}, {"name": "Sam"}], "title": ig("Zoë"), "messages": [
                    {"sender_name": ig("Zoë"), "timestamp_ms": 1650000000000, "content": ig("café tomorrow?")},
                    {"sender_name": "Sam", "timestamp_ms": 1650000060000, "content": "yes"},
                    {"sender_name": "Sam", "timestamp_ms": 1650000060000, "content": "at ten"}]}))      # same millisecond as the one before
            z.writestr("your_instagram_activity/messages/inbox/lee_22/message_1.json", json.dumps({
                "participants": [{"name": "Lee"}, {"name": "Sam"}], "title": "Lee", "messages": [{"sender_name": "Lee", "timestamp_ms": 1660000000000, "content": "hi"}]}))
            z.writestr("media/posts/1.mp4", "not text: must not be unpacked")
        with zipfile.ZipFile(os.path.join(self.home, "Downloads", "Basic_LinkedInDataExport_11-01-2026.zip"), "w") as z:
            z.writestr("Connections.csv", "Notes:\n\"a note\"\n\nFirst Name,Last Name,URL,Email Address,Company,Position,Connected On\nLee,Park,https://example.com/in/lee,,Acme,Engineer,05 Jan 2022\n")
        r = self.ctx("ingest")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("instagram", r.stdout.splitlines()[0])
        for tz in ("Pacific/Auckland", "America/Los_Angeles"):      # a date with no time must not move with the mac's time zone
            self.assertEqual(self.ctx("collect", env={"TZ": tz}).returncode, 0)
            msgs = [m for m in self.rows("messages") if m["src"] == "instagram"]
            self.assertEqual(len(msgs), 4)
            self.assertEqual(len({m["id"] for m in msgs}), 4)
            self.assertIn("café tomorrow?", [m["text"] for m in msgs])
            who = [d for d in self.rows("docs") if d["src"] == "linkedin_connections"]
            self.assertEqual([(d["title"], d["ts"]) for d in who], [("Lee Park", "2022-01-05T00:00:00Z")])
        self.assertFalse([f for _, _, fs in os.walk(self.v2) for f in fs if f.endswith(".mp4")])
        self.assertIn("new archives: none", self.ctx("ingest").stdout)      # the same zips are not unpacked twice

    def test_ingest_unpacks_a_tgz_takeout_text_files_only(self):
        import io, tarfile
        os.makedirs(os.path.join(self.home, "Downloads"))
        with tarfile.open(os.path.join(self.home, "Downloads", "takeout-20260101T000000Z-001.tgz"), "w:gz") as t:
            for name, data in (("Takeout/Keep/list.json", json.dumps({"title": "to buy", "textContent": "clay"})), ("Takeout/Photos/1.jpg", "binary"), ("../escape.txt", "no")):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data.encode()))
        _f.write("not a zip yet", os.path.join(self.home, "Downloads", "takeout-half.zip"), "w")       # still downloading: left alone
        r = self.ctx("ingest")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = sorted(os.path.relpath(os.path.join(d, f), self.v2) for d, _, fs in os.walk(os.path.join(self.v2, "imports")) for f in fs if not f.startswith("."))
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0].endswith("Takeout/Keep/list.json"), got)
        self.assertFalse(os.path.exists(os.path.join(self.v2, "escape.txt")))
        self.assertEqual([d["text"] for d in self.rows("docs") if d["src"] == "google_keep"], ["clay"])

    def test_answer_without_a_model_says_how_to_sign_in(self):
        r = self.ctx("answer", "x", env={"CTX_MODEL": "claude"})     # forced to a cli that is not on this PATH
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["answer"], "")
        self.assertTrue(out["error"])
        self.assertNotIn("Traceback", r.stderr)

    def test_facts_do_not_call_sixty_words_a_novel(self):
        self.put(".context/v2/messages.jsonl", json.dumps({"id": "W1", "src": "whatsapp", "ts": "2025-06-01T10:00:00Z", "thread_id": "t", "thread": "ada",
                                                         "kind": "dm", "mine_total": 4, "who": "me", "sender": "", "text": "see you at ten"}) + "\n")
        out = json.loads(self.ctx("facts").stdout)
        self.assertFalse([l for l in out["lines"] if "novel" in l], out["lines"])


if __name__ == "__main__":
    unittest.main()
