"""Codex sessions: the app's own history database first, its session files for what that lacks, and never a thread
another agent started. A made-up ~/.codex in the made-up home."""
import io, json, os, shutil, sqlite3, unittest
from tests import fixture
from ctx import collect

def home():
    """The made-up home, as it is right now: readers ask the environment each time, so the tests do too. Never the real one."""
    h = os.path.expanduser("~")
    if "ctx-test-" not in h:
        raise unittest.SkipTest("HOME is not the made-up home")
    return h


def root():
    return os.path.join(home(), ".codex")


A, B, C, D, E = ("0199aaaa-0000-7000-8000-%012d" % n for n in range(1, 6))


def meta(cwd, sub=False):
    return json.dumps({"type": "session_meta", "timestamp": "2026-03-01T10:00:00Z",
                       "payload": {"id": "x", "cwd": cwd, "source": {"subagent": {"parent": "p"}} if sub else "vscode"}}) + "\n"


class Codex(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(root(), ignore_errors=True)
        self.addCleanup(shutil.rmtree, root(), ignore_errors=True)
        os.makedirs(os.path.join(root(), "sessions", "2026", "03", "01"))
        self.items = []

    def file(self, tid, text, name="sessions/2026/03/01/rollout-2026-03-01T10-00-00-%s.jsonl"):
        path = os.path.join(root(), name % tid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        return path

    def item(self, tid, kind, text, client=""):
        body = {"type": kind, "id": "i%d" % len(self.items), "text": text} if kind == "agentMessage" else \
            {"type": kind, "id": "i%d" % len(self.items), "clientId": client, "content": [{"type": "text", "text": text}, {"type": "localImage", "path": "/made/up.png"}]}
        self.items.append((tid, "t", "i%d" % len(self.items), len(self.items), 1772359200000 + 1000 * len(self.items), json.dumps(body), kind))

    def db(self):
        con = sqlite3.connect(os.path.join(root(), "thread_history_1.sqlite"))
        con.execute("create table thread_items (thread_id, turn_id, item_id, rollout_ordinal, created_at_ms, item_json, item_type)")
        con.executemany("insert into thread_items values (?,?,?,?,?,?,?)", self.items + [(A, "t", "r", 99, 1, json.dumps({"type": "reasoning"}), "reasoning")])
        con.commit()
        con.close()

    def read(self, days=None):
        out, prompts = io.StringIO(), io.StringIO()
        collect._tl.prompts = prompts
        try:
            n = collect.codex(days, out)
        finally:
            collect._tl.prompts = None
        rows = [json.loads(l) for l in out.getvalue().split("\n") if l]
        self.assertEqual(n, len(rows))
        return {r["id"]: r for r in rows}, [json.loads(l) for l in prompts.getvalue().split("\n") if l]

    def test_threads_come_from_the_database_and_only_the_owners(self):
        self.item(A, "userMessage", "build a kiln timer", client="c1")           # typed in the app, no file left
        self.item(A, "agentMessage", "the kiln timer is done")
        self.item(A, "userMessage", "<environment_context>not typed</environment_context>")
        self.item(B, "userMessage", "count the glaze jars")                      # its file says a person started it
        self.item(B, "agentMessage", "there are nine")
        self.item(C, "userMessage", "you are a helper: list the files")          # its file says another agent started it
        self.item(C, "agentMessage", "listed")
        self.item(D, "userMessage", "summarise this for the parent agent")       # no file and nothing from the input box
        self.item(D, "agentMessage", "summarised")
        self.db()
        self.file(B, meta("/made/up/glaze"))
        self.file(C, meta("/made/up/glaze", sub=True))
        rows, prompts = self.read()
        want = {collect.sid("X", A, tail=True), collect.sid("X", B, tail=True)}
        self.assertEqual(set(rows), want)
        a, b = rows[collect.sid("X", A, tail=True)], rows[collect.sid("X", B, tail=True)]
        self.assertEqual((a["src"], a["user_turns"], a["first_user"], a["last_agent"], a["last_user_ts"][:4]), ("codex", 1, "build a kiln timer", "the kiln timer is done", "2026"))
        self.assertEqual((b["project"], b["first_user"]), ("/made/up/glaze", "count the glaze jars"))
        self.assertEqual(sorted(p["text"] for p in prompts), ["build a kiln timer", "count the glaze jars"])      # what another agent wrote is not "what the owner typed"

    def test_a_file_the_database_lacks_is_read_in_both_of_its_shapes(self):
        old = meta("/made/up/old") + "".join(json.dumps(x) + "\n" for x in (
            {"type": "event_msg", "timestamp": "2026-03-01T10:00:01Z", "payload": {"type": "user_message", "message": "the old shape"}},
            {"type": "event_msg", "timestamp": "2026-03-01T10:00:02Z", "payload": {"type": "agent_message", "message": "answered"}},
            {"type": "response_item", "timestamp": "2026-03-01T10:00:02Z", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "the old shape"}]}}))
        new = meta("/made/up/new") + "".join(json.dumps(x) + "\n" for x in (
            {"type": "response_item", "timestamp": "2026-03-01T10:00:00Z", "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "rules for the model"}]}},
            {"type": "response_item", "timestamp": "2026-03-01T10:00:01Z", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<user_instructions>not typed</user_instructions>"}]}},
            {"type": "response_item", "timestamp": "2026-03-01T10:00:02Z", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "the new shape second line"}]}},
            {"type": "response_item", "timestamp": "2026-03-01T10:00:03Z", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "answered too"}]}})) + "not json\n"
        self.file(A, old)
        self.file(B, new)
        self.file(C, meta("/made/up/sub", sub=True) + new.split("\n", 1)[1])
        self.file(D, meta("/made/up/one-sided") + json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "nobody answered"}]}}) + "\n")
        rows, prompts = self.read()
        a, b = rows[collect.sid("X", A, tail=True)], rows[collect.sid("X", B, tail=True)]
        self.assertEqual(len(rows), 2)
        self.assertEqual((a["user_turns"], a["first_user"], a["project"]), (1, "the old shape", "/made/up/old"))          # not counted twice
        self.assertEqual((b["user_turns"], b["first_user"], b["last_agent"], b["project"]), (1, "the new shape second line", "answered too", "/made/up/new"))
        self.assertEqual(len(prompts), 2)

    def test_a_thread_in_both_is_one_row_and_no_codex_is_no_error(self):
        self.item(A, "userMessage", "from the database", client="c1")
        self.item(A, "agentMessage", "ok")
        self.db()
        self.file(A, meta("/made/up/both") + json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "from the file"}}) + "\n")
        rows, _ = self.read()
        self.assertEqual([(r["first_user"], r["project"]) for r in rows.values()], [("from the database", "/made/up/both")])
        self.assertEqual(self.read(days=1)[0], {})                                # made long ago: outside a one-day window
        shutil.rmtree(root())
        self.assertEqual(self.read()[0], {})

    def test_a_packed_file_is_read_where_python_can_unpack_it(self):
        try:
            from compression import zstd
        except ImportError:
            self.skipTest("this python cannot unpack .zst; those sessions come from the database")
        text = meta("/made/up/packed") + "".join(json.dumps(x) + "\n" for x in (
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "packed away"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "still here"}]}}))
        os.makedirs(os.path.join(root(), "archived_sessions"))
        with open(os.path.join(root(), "archived_sessions", "rollout-2026-03-01T10-00-00-%s.jsonl.zst" % E), "wb") as f:
            f.write(zstd.compress(text.encode()))
        rows, _ = self.read()
        self.assertEqual([(r["first_user"], r["last_agent"], r["project"]) for r in rows.values()], [("packed away", "still here", "/made/up/packed")])


class ClaudeHistory(unittest.TestCase):
    """What was typed to Claude Code outlives the sessions: its own list of prompts is read for the ones whose session is gone."""
    @property
    def ROOT(self):
        return os.path.join(home(), ".claude")

    def setUp(self):
        shutil.rmtree(self.ROOT, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.ROOT, ignore_errors=True)
        os.makedirs(os.path.join(self.ROOT, "projects", "-made-up-kiln"))

    def test_prompts_of_sessions_that_are_gone(self):
        rows = [{"display": "write a kiln timer", "pastedContents": {}, "timestamp": 1764583200000, "project": "/made/up/kiln", "sessionId": "gone-1"},
                {"display": "/clear", "pastedContents": {}, "timestamp": 1764583300000, "project": "/made/up/kiln", "sessionId": "gone-1"},
                {"display": "my key is sk-abcdefghijklmnopqrstuvwxyz012345", "pastedContents": {}, "timestamp": 1764583400000, "project": "/made/up/kiln", "sessionId": "gone-1"},
                {"display": "still on disk", "pastedContents": {}, "timestamp": 1764583500000, "project": "/made/up/kiln", "sessionId": "here-2"},
                {"display": "no time on this one", "project": "/made/up/kiln", "sessionId": "gone-3"}, "junk"]
        with open(os.path.join(self.ROOT, "history.jsonl"), "w") as f:
            f.write("".join(json.dumps(r) + "\n" for r in rows) + "not json\n")
        with open(os.path.join(self.ROOT, "projects", "-made-up-kiln", "here-2.jsonl"), "w") as f:
            f.write("{}\n")
        out = io.StringIO()
        n = collect.claude_history(None, out)
        got = [json.loads(l) for l in out.getvalue().split("\n") if l]
        self.assertEqual((n, [g["text"][:10] for g in got]), (2, ["write a ki", "my key is "]))
        self.assertEqual((got[0]["src"], got[0]["who"], got[0]["thread"], got[0]["ts"][:7]), ("claude_code", "me", "kiln", "2025-12"))
        self.assertNotIn("sk-abcdefghijklmnop", got[1]["text"])
        again = io.StringIO()
        collect.claude_history(None, again)
        self.assertEqual(again.getvalue(), out.getvalue())                        # the same ids on every read
        self.assertEqual(collect.claude_history(1, io.StringIO()), 0)             # typed long ago: outside a one-day window
        self.assertIn(("claude_history", collect.P), [(n, g) for n, g, _ in collect.TABLE])

    def test_no_claude_code_is_a_plain_reason(self):
        shutil.rmtree(self.ROOT)
        with self.assertRaises(FileNotFoundError):
            collect.claude_history(None, io.StringIO())


if __name__ == "__main__":
    unittest.main()
