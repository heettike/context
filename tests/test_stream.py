import json, os, stat, subprocess, sys, tempfile, time, unittest
from tests import files as _f
from unittest import mock
from tests import fixture
from ctx import llm, paths

FAKE = r'''#!%s
import json, os, re, sys, time
mode = os.environ.get("FAKE_MODE", "ok")
prompt, argv = sys.stdin.read(), sys.argv[1:]
system = argv[argv.index("--system-prompt") + 1] if "--system-prompt" in argv else ""
if "--system-prompt-file" in argv:          # how the engine hands it over: a file of the owner's alone, never the command line
    system = open(argv[argv.index("--system-prompt-file") + 1]).read()
# the engine hands the prompt over between two marker lines whose number the system text names (guard.Seal). a prompt
# without them is refused, as a hard error: no test of this file passes on a call that went out unsealed
lines = prompt.rstrip("\n").split("\n")
seal = re.fullmatch(r"<<material ([0-9a-f]{16})>>", lines[0])
if not seal or len(lines) < 2 or lines[-1] != "<<end of material %%s>>" %% seal.group(1) or seal.group(0) not in system:
    print(json.dumps({"type": "result", "subtype": "error", "is_error": True, "result": "the prompt came without its seal"}), flush=True)
    sys.exit(7)
prompt = "\n".join(lines[1:-1])          # what is counted is what lies between the marks
with open(os.environ["FAKE_PID"], "w") as f:
    f.write(str(os.getpid()))
def ev(d):
    print(json.dumps(d), flush=True)
ev({"type": "system", "subtype": "init"})
if mode == "garbage":
    print("not json at all", flush=True)
    sys.exit(3)
if mode == "whole":
    ev({"type": "result", "subtype": "success", "is_error": False, "result": "all at once", "usage": {"input_tokens": 3, "output_tokens": 2}})
    sys.exit(0)
for piece in ["hel", "lo ", "you: ", str(len(prompt))]:
    ev({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": piece}}})
    if mode == "slow":
        time.sleep(30)
ev({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": "{"}}})
ev({"type": "assistant", "message": {"content": [{"type": "text", "text": "ignored"}]}})
if mode == "error":
    ev({"type": "result", "subtype": "error", "is_error": True, "result": "usage limit reached"})
    sys.exit(1)
if mode == "tail":         # the real cli: usage and message_stop, then seconds of its own bookkeeping before "result"
    ev({"type": "stream_event", "event": {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"input_tokens": 10, "cache_read_input_tokens": 5, "output_tokens": 4}}})
    ev({"type": "stream_event", "event": {"type": "message_stop"}})
    time.sleep(30)
ev({"type": "result", "subtype": "success", "is_error": False, "result": "hello you", "usage": {"input_tokens": 10, "cache_read_input_tokens": 5, "output_tokens": 4}})
'''


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class Stream(unittest.TestCase):
    """llm.stream against a made-up claude CLI: a small script that prints the same event lines."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ctx-fake-")
        self.bin = os.path.join(self.dir, "claude")
        with open(self.bin, "w") as f:
            f.write(FAKE % sys.executable)
        os.chmod(self.bin, 0o755)
        self.pidfile = os.path.join(self.dir, "pid")
        self.ledger = _f.read(paths.LEDGER) if os.path.exists(paths.LEDGER) else None
        ps = [mock.patch.object(llm, "_claude_bin", lambda: self.bin), mock.patch.object(llm, "_backend", lambda: "claude")]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.restore)

    def restore(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)
        if self.ledger is None:
            if os.path.exists(paths.LEDGER):
                os.remove(paths.LEDGER)
        else:
            _f.write(self.ledger, paths.LEDGER, "w")

    def run_(self, mode="ok", prompt="abc", **env):
        with mock.patch.dict(llm._ENV, dict(FAKE_MODE=mode, FAKE_PID=self.pidfile, **env)):
            return list(llm.stream("sys", prompt, "m", tag="answer"))

    def last(self):
        return json.loads(_f.read(paths.LEDGER).splitlines()[-1])

    def pid(self):
        for _ in range(100):
            if os.path.exists(self.pidfile) and _f.read(self.pidfile):
                return int(_f.read(self.pidfile))
            time.sleep(0.05)
        self.fail("the fake cli never started")

    def test_pieces_arrive_in_order_and_only_text(self):
        self.assertEqual(self.run_(prompt="x" * 70_000), ["hel", "lo ", "you: ", "70000"])         # a long prompt goes in whole

    def test_it_is_a_generator_that_yields_before_the_reply_ends(self):
        with mock.patch.dict(llm._ENV, dict(FAKE_MODE="slow", FAKE_PID=self.pidfile)):
            g = llm.stream("sys", "abc", "m", tag="answer")
            t = time.monotonic()
            self.assertEqual(next(g), "hel")
            self.assertLess(time.monotonic() - t, 10)
            g.close()

    def test_the_ledger_gets_one_row_like_ask(self):
        self.run_()
        row = self.last()
        self.assertEqual((row["tag"], row["model"], row["backend"], row["in"], row["out"], row["usd"], row["prompt_chars"], row["stream"]),
                         ("answer", "m", "claude", 15, 4, 0.0, 3, True))
        self.assertIn("at", row)

    def test_the_call_ends_when_the_text_does_not_when_the_cli_has_tidied_up(self):
        t = time.monotonic()
        self.assertEqual("".join(self.run_("tail")), "hello you: 3")
        self.assertLess(time.monotonic() - t, 15)
        self.assertFalse(alive(self.pid()))
        row = self.last()
        self.assertEqual((row["in"], row["out"]), (15, 4))
        with mock.patch.dict(llm._ENV, dict(FAKE_MODE="tail", FAKE_PID=self.pidfile)):
            t = time.monotonic()
            self.assertEqual(llm.ask("sys", "abc", "m", tag="t"), "hello you: 3")       # ask() takes the same road
            self.assertLess(time.monotonic() - t, 15)

    def test_another_thread_can_stop_a_call(self):
        import threading
        got = {}

        def work():
            got["id"] = threading.get_ident()
            try:
                with mock.patch.dict(llm._ENV, dict(FAKE_MODE="slow", FAKE_PID=self.pidfile)):
                    got["out"] = list(llm.stream("sys", "abc", "m", tag="answer"))
            except Exception as e:
                got["err"] = type(e).__name__
        th = threading.Thread(target=work)
        th.start()
        pid = self.pid()
        self.assertTrue(llm.cancel(got["id"]))
        th.join(20)
        self.assertFalse(th.is_alive())
        self.assertEqual(got.get("err"), "RuntimeError")
        self.assertFalse(alive(pid))
        self.assertFalse(llm.cancel(got["id"]))

    def test_the_made_up_cli_refuses_a_prompt_that_came_unsealed(self):
        """Every other test here passes only because the engine sealed the prompt: the stand-in says so when it was not."""
        for stdin, system in (("abc", "sys"), ("<<material 0123456789abcdef>>\nabc\n<<end of material 0123456789abcdef>>", "sys"),
                              ("<<material 0123456789abcdef>>\nabc", "sys <<material 0123456789abcdef>>")):
            r = subprocess.run([self.bin, "--system-prompt", system], input=stdin, capture_output=True, text=True, timeout=30,
                               env=dict(os.environ, FAKE_PID=self.pidfile))
            self.assertEqual(r.returncode, 7, stdin)
            self.assertIn("without its seal", r.stdout)
        sealed = "<<material 0123456789abcdef>>\nabc\n<<end of material 0123456789abcdef>>"
        r = subprocess.run([self.bin, "--system-prompt", "sys <<material 0123456789abcdef>>"], input=sealed, capture_output=True, text=True, timeout=30,
                           env=dict(os.environ, FAKE_PID=self.pidfile))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn('"you: "', r.stdout)
        self.assertIn('"3"', r.stdout)                  # the three letters between the marks, and nothing else, were counted
        with mock.patch.object(llm.guard, "sealed", lambda system, prompt: (system, prompt)), self.assertRaisesRegex(RuntimeError, "without its seal"):
            self.run_()                                 # and a stream that did not seal its prompt fails here

    def test_a_reply_with_no_partial_lines_still_comes_through(self):
        self.assertEqual(self.run_("whole"), ["all at once"])

    def test_walking_away_kills_the_child(self):
        with mock.patch.dict(llm._ENV, dict(FAKE_MODE="slow", FAKE_PID=self.pidfile)):
            g = llm.stream("sys", "abc", "m", tag="answer")
            next(g)
            pid = self.pid()
            self.assertTrue(alive(pid))
            g.close()
        for _ in range(60):
            if not alive(pid):
                break
            time.sleep(0.05)
        self.assertFalse(alive(pid))
        self.assertTrue(self.last()["stopped"])

    def test_dropping_the_generator_kills_the_child_too(self):
        with mock.patch.dict(llm._ENV, dict(FAKE_MODE="slow", FAKE_PID=self.pidfile)):
            g = llm.stream("sys", "abc", "m", tag="answer")
            next(g)
            pid = self.pid()
            del g
            import gc
            gc.collect()
        for _ in range(60):
            if not alive(pid):
                break
            time.sleep(0.05)
        self.assertFalse(alive(pid))

    def test_timeout_kills_the_child_and_raises(self):
        """The wait is counted from when the first piece is in, not from when the test began: on a busy machine the made-up
        cli can take longer than any fixed second to start, and the wait then ran out before the first piece (seen so)."""
        import threading
        go = threading.Event()

        class Held(threading.Thread):
            """llm's clock, held until the test lets it run: then it counts the wait, awake time only."""
            def __init__(self, interval, fn):
                threading.Thread.__init__(self, daemon=True)
                self.interval, self.fn, self.off = interval, fn, threading.Event()

            def run(self):
                go.wait()
                end = time.monotonic() + self.interval
                while not self.off.is_set() and time.monotonic() < end:
                    self.off.wait(0.02)
                if not self.off.is_set():
                    self.fn()

            def cancel(self):
                self.off.set()
                go.set()
        with mock.patch.object(llm, "_wait", lambda: 0.3), mock.patch.object(llm.threading, "Timer", Held), mock.patch.dict(llm._ENV, dict(FAKE_MODE="slow", FAKE_PID=self.pidfile)):
            g = llm.stream("sys", "abc", "m", tag="answer")
            got = [next(g)]                 # however long the child took to start
            go.set()                        # now the wait begins
            with self.assertRaises(subprocess.TimeoutExpired):
                got += list(g)
        self.assertEqual(got, ["hel"])
        self.assertFalse(alive(self.pid()))
        self.assertIn("error", self.last())

    def test_an_error_result_raises_after_what_was_written(self):
        with mock.patch.dict(llm._ENV, dict(FAKE_MODE="error", FAKE_PID=self.pidfile)):
            g = llm.stream("sys", "abc", "m", tag="answer")
            got = []
            with self.assertRaisesRegex(RuntimeError, "usage limit"):
                for piece in g:
                    got.append(piece)
        self.assertEqual("".join(got), "hello you: 3")
        self.assertIn("usage limit", self.last()["error"])

    def test_a_cli_that_dies_without_a_reply(self):
        with self.assertRaisesRegex(RuntimeError, "claude: not json at all"):
            self.run_("garbage")

    def test_codex_yields_the_whole_reply_once(self):
        with mock.patch.object(llm, "_backend", lambda: "codex"), mock.patch.object(llm, "_codex", lambda s, p, m: ("whole reply", 0, 0, 0.0)):
            self.assertEqual(list(llm.stream("sys", "abc", "m", tag="t")), ["whole reply"])
        self.assertEqual(self.last()["backend"], "codex")

    def test_no_model_signed_in(self):
        def none():
            raise RuntimeError("no model is signed in on this mac. x")
        with mock.patch.object(llm, "_backend", none):
            with self.assertRaisesRegex(RuntimeError, "signed in"):
                next(llm.stream("s", "p", "m"))


if __name__ == "__main__":
    unittest.main()
