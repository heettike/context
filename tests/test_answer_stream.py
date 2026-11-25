import json, os, signal, subprocess, sys, time, unittest
from unittest import mock
from tests import fixture
from ctx import answer, llm

PLAN = {"probes": [["kettle"]], "after": "", "who": ""}
TRAILER = '\n===\n{"cites": ["W1"], "confidence": 4, "links": [], "strength": "strong"}'


def pieces(text, n=7):
    return [text[i:i + n] for i in range(0, len(text), n)]


class Stream(unittest.TestCase):
    def run_(self, reply, plan=PLAN, question="what is the kettle fund", chunk=7, history=None):
        self.events, self.sent = [], []

        def stream(system, prompt, model=None, tag=""):
            self.sent.append({"system": system, "prompt": prompt, "tag": tag})
            if isinstance(reply, Exception):
                raise reply
            for p in (reply if isinstance(reply, list) else pieces(reply, chunk)):
                if isinstance(p, Exception):
                    raise p
                yield p

        def ask_json(system, prompt, model=None, tag=""):
            if isinstance(plan, Exception):
                raise plan
            return plan
        with mock.patch.object(llm, "stream", stream), mock.patch.object(llm, "ask_json", ask_json), \
                mock.patch.object(llm, "ask", side_effect=AssertionError("the stream path makes no second answering call")):
            self.reply = answer.answer_stream(question, history, self.events.append)
        return self.events

    def read(self):
        """The read of the planned search (a first look at the question's own words may come before it)."""
        return next(e for e in self.events if e.get("phase") == "read" and not e.get("first"))

    def kinds(self):
        return ["phase:" + e["phase"] if "phase" in e else next(iter(e)) for e in self.events]

    def text(self):
        return "".join(e["delta"] for e in self.events if "delta" in e)

    def plain(self, reply_dict, plan=PLAN, question="what is the kettle fund"):
        def ask_json(system, prompt, model=None, tag=""):
            return plan
        with mock.patch.object(llm, "ask_json", ask_json), mock.patch.object(llm, "ask", lambda *a, **k: json.dumps(reply_dict)):
            return answer.answer(question)

    def test_events_in_order(self):
        self.run_("someone asked about the memo [W2]. it closes friday [W1]." + TRAILER)
        k = self.kinds()
        self.assertEqual(k[:2], ["phase:plan", "phase:read"])
        self.assertEqual(k.count("phase:read"), 1 + sum(1 for e in self.events if e.get("first")))
        self.assertEqual(k[-1], "done")
        self.assertEqual([x for x in k if x == "cite"], ["cite", "cite"])
        self.assertLess(k.index("cite"), len(k) - 1)
        read = self.read()
        self.assertEqual((read["rows"] > 0, read["sources"], [t["thread"] for t in read["threads"]]), (True, ["whatsapp"], ["ada lovelace"]))

    def test_deltas_join_to_the_final_answer_with_marks_numbered(self):
        for chunk in (1, 2, 3, 5, 7, 11, 40, 400):
            self.run_("someone asked about the memo [W2]. it closes friday [W1]. again [W2]." + TRAILER, chunk=chunk)
            self.assertEqual(self.text(), "someone asked about the memo[1]. it closes friday[2]. again[1].", chunk)
            self.assertEqual(self.reply["answer"], self.text())
            self.assertNotIn("W2", self.text())
            self.assertNotIn("===", self.text())

    def test_a_cite_is_announced_once_before_its_mark(self):
        self.run_("memo [W2]. friday [W1]. memo again [W2]." + TRAILER, chunk=4)
        cites = [(i, e["cite"]) for i, e in enumerate(self.events) if "cite" in e]
        self.assertEqual([(c["id"], c["n"]) for _, c in cites], [("W2", 1), ("W1", 2)])
        self.assertEqual(set(cites[0][1]), {"id", "src", "ts", "thread", "who", "text", "url", "n"})
        for at, c in cites:
            first = next(i for i, e in enumerate(self.events) if "delta" in e and f'[{c["n"]}]' in e["delta"])
            self.assertLess(at, first)

    def test_done_is_the_plain_reply(self):
        self.run_("someone asked about the memo [W2]. it closes friday [W1]." + TRAILER)
        done = self.events[-1]["done"]
        plain = self.plain({"answer": "someone asked about the memo [W2]. it closes friday [W1].", "cites": ["W1"], "confidence": 4, "links": [], "strength": "strong"})
        self.assertEqual(set(done), set(plain))
        for k in set(plain) - {"secs"}:
            self.assertEqual(done[k], plain[k], k)
        self.assertIs(done, self.reply)

    def test_an_id_that_is_not_a_row_never_reaches_the_screen(self):
        self.run_("true [W1]. invented [W9z9z9z]. kept [sic] and [2024]." + TRAILER, chunk=3)
        self.assertEqual(self.text(), "true[1]. invented. kept [sic] and [2024].")

    def test_no_trailer_is_fine(self):
        self.run_("it closes friday [W1].")
        self.assertEqual((self.text(), self.reply["error"], [c["id"] for c in self.reply["cites"]]), ("it closes friday[1].", "", ["W1"]))
        self.run_("it closes friday [W1].\n===\nnot json at all")
        self.assertEqual(self.reply["answer"], "it closes friday[1].")

    def test_json_sent_after_all_is_shown_whole_at_the_end(self):
        for reply in ('{"answer": "it closes friday [W1].", "cites": ["W1"], "confidence": 3}', '```json\n{"answer": "it closes friday [W1].", "cites": []}\n```'):
            self.run_(reply, chunk=5)
            self.assertEqual([e["delta"] for e in self.events if "delta" in e], ["it closes friday[1]."])
            self.assertEqual(self.kinds()[-3:], ["cite", "delta", "done"])
            self.assertNotIn("{", self.text())

    def test_the_model_is_asked_for_text_first(self):
        self.run_("ok [W1]." + TRAILER)
        self.assertIn("===", self.sent[0]["system"])
        self.assertTrue(self.sent[0]["system"].startswith(answer.ANSWER))
        self.assertEqual(self.sent[0]["tag"], "answer")
        self.assertIn("## question\nwhat is the kettle fund", self.sent[0]["prompt"])

    def test_a_failure_mid_stream_is_one_plain_error(self):
        self.run_(["it closes ", "friday [W1]", subprocess.TimeoutExpired(["/Users/someone/claude"], 90)])
        self.assertEqual(self.kinds()[-1], "error")
        self.assertIn("too long", self.events[-1]["error"])
        self.assertNotIn("/Users", json.dumps(self.events))
        self.assertNotIn("done", self.kinds())
        self.run_(RuntimeError("no model is signed in on this mac. run once in a terminal: claude auth login"))
        self.assertIn("signed in", self.events[-1]["error"])

    def test_an_empty_reply_is_an_error(self):
        self.run_("")
        self.assertIn("nothing usable", self.events[-1]["error"])

    def test_nothing_found_and_nothing_asked(self):
        self.run_("unused", plan={"probes": [["zorblax"]]}, question="who is zorblax")
        self.assertEqual([k for k in self.kinds() if k != "phase:read"], ["phase:plan", "delta", "done"])
        self.assertIn("nothing in your archive", self.text())
        self.assertEqual(self.sent, [])
        self.run_("unused", question="  ")
        self.assertEqual(self.kinds(), ["phase:plan", "error"])

    def test_a_thread_question_reports_the_threads_read(self):
        self.run_("the permit came first [MW0]." + TRAILER.replace("W1", "MW0"), plan={"probes": [["gazebo"]], "threads": ["maya okafor"], "need": "whole"}, question="maya and the gazebo")
        read = self.read()
        self.assertEqual([t["whole"] for t in read["threads"]], [True, True, True])
        self.assertEqual(self.events[-1]["done"]["threads"], read["threads"])

    def test_a_first_look_at_the_questions_own_words_comes_while_the_planner_thinks(self):
        import threading, time
        gate = threading.Event()

        def slow_plan(system, prompt, model=None, tag=""):
            gate.wait(10)                                               # the planner is still thinking
            return PLAN
        events = []

        def emit(e):
            events.append(e)
            if e.get("first"):
                gate.set()                                              # the first look arrived before any plan
        with mock.patch.object(llm, "ask_json", slow_plan), mock.patch.object(llm, "stream", lambda *a, **k: iter(["it closes friday [W1]."])):
            answer.answer_stream("what is the kettle fund", None, emit)
        first = next(e for e in events if e.get("first"))
        self.assertEqual((first["phase"], first["rows"] > 0, first["sources"]), ("read", True, ["whatsapp"]))
        self.assertLess(events.index(first), next(i for i, e in enumerate(events) if e.get("phase") == "read" and not e.get("first")))
        self.assertIn("done", events[-1])

    def test_a_first_look_that_finds_nothing_or_fails_says_nothing(self):
        with mock.patch.object(answer, "fallback_probes", lambda q: [["zzzznope"]]):
            self.run_("it closes friday [W1]." + TRAILER)
        self.assertFalse(any(e.get("first") for e in self.events))
        self.assertIn("done", self.events[-1])

    def test_every_event_is_one_json_line(self):
        self.run_("memo [W2]. friday [W1]." + TRAILER)
        for e in self.events:
            line = json.dumps(e, ensure_ascii=False)
            self.assertNotIn("\n", line)
            self.assertEqual(json.loads(line), e)


FAKE = r'''#!%s
import json, os, sys, time
if sys.argv[1:3] == ["auth", "--help"]:
    print("commands: login, status")
    sys.exit(0)
if sys.argv[1:3] == ["auth", "status"]:
    print(json.dumps({"loggedIn": True}))
    sys.exit(0)
sys.stdin.read()
open(os.environ["FAKE_PID"], "w").write(str(os.getpid()))
def ev(text):
    print(json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}}), flush=True)
if "--output-format" in sys.argv and sys.argv[sys.argv.index("--output-format") + 1] == "json":
    print(json.dumps({"result": json.dumps({"probes": [["kettle"]]}), "usage": {}}))
    sys.exit(0)
ev("it closes ")
ev("friday [W1]. and then ")
if os.environ.get("FAKE_MODE") == "hang":
    time.sleep(60)
ev("nothing more.\n===\n{\"cites\": [\"W1\"], \"confidence\": 4}")
print(json.dumps({"type": "result", "is_error": False, "result": "x", "usage": {"input_tokens": 1, "output_tokens": 1}}), flush=True)
'''


class Command(unittest.TestCase):
    """`python3 -u -m ctx answer ... --stream` as the app runs it, with a made-up claude CLI on the path."""

    def setUp(self):
        import tempfile, shutil
        self.dir = tempfile.mkdtemp(prefix="ctx-fakebin-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.home = os.path.join(self.dir, "home")
        shutil.copytree(fixture.HOME, self.home, ignore=shutil.ignore_patterns("cache", "*.log"))
        with open(os.path.join(self.home, "model.json"), "w") as f:
            json.dump({"using": "claude", "at": time.time()}, f)
        fake_home = os.path.join(self.dir, "user")
        os.makedirs(os.path.join(fake_home, ".local", "bin"))
        self.bin = os.path.join(fake_home, ".local", "bin", "claude")
        with open(self.bin, "w") as f:
            f.write(FAKE % sys.executable)
        os.chmod(self.bin, 0o755)
        self.pidfile = os.path.join(self.dir, "pid")
        self.env = dict(os.environ, CTX_HOME=self.home, PYTHONPATH=fixture.REPO, HOME=fake_home, FAKE_PID=self.pidfile, CTX_MODEL="claude",
                        CTX_CLI_PATH=os.path.dirname(self.bin))     # the made-up cli, and no other

    def start(self, mode="ok"):
        return subprocess.Popen([sys.executable, "-u", "-m", "ctx", "answer", "what", "is", "the", "kettle", "fund", "--stream"], cwd=fixture.REPO,
                                env=dict(self.env, FAKE_MODE=mode), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def test_lines_then_done(self):
        p = self.start()
        out, err = p.communicate(timeout=120)
        events = [json.loads(l) for l in out.splitlines()]
        if events and "error" in events[-1] and "signed in" in events[-1]["error"]:
            self.skipTest("the made-up cli is not picked up on this machine")
        self.assertEqual(p.returncode, 0, err[-300:])
        self.assertEqual(events[0], {"phase": "plan"})
        self.assertEqual(events[1]["phase"], "read")
        self.assertTrue(any(e.get("phase") == "read" and "threads" in e for e in events))
        self.assertEqual("".join(e["delta"] for e in events if "delta" in e), "it closes friday[1]. and then nothing more.")
        self.assertEqual(events[-1], {"end": True})                      # the last line, always
        done = events[-2]["done"]
        self.assertEqual((done["answer"], [c["id"] for c in done["cites"]], done["error"]), ("it closes friday[1]. and then nothing more.", ["W1"], ""))
        self.assertEqual(err, "")

    def test_sigterm_mid_stream_exits_clean_and_leaves_no_child(self):
        import threading
        p = self.start("hang")
        lines = []
        reader = threading.Thread(target=lambda: lines.extend(json.loads(l) for l in iter(p.stdout.readline, "")), daemon=True)
        reader.start()
        # the answer is held back until it has been checked, so no text arrives while the model is still writing: wait for
        # the model process itself. (waiting for the first text meant waiting out the made-up model's whole minute.)
        child, end = 0, time.monotonic() + 120
        while time.monotonic() < end and p.poll() is None:
            if any("error" in l and "signed in" in l["error"] for l in list(lines)):
                break
            try:
                with open(self.pidfile) as f:
                    pid = int(f.read())
                os.kill(pid, 0)
                time.sleep(0.4)
                os.kill(pid, 0)                                         # still there: the answering call, not the planning call that came and went
                with open(self.pidfile) as f:
                    if int(f.read()) == pid:
                        child = pid
                        break
            except (OSError, ValueError):
                time.sleep(0.05)
        if not child:
            p.kill()
            p.wait(10)
            reader.join(5)
            p.stdout.close(); p.stderr.close()
            if any("error" in l and "signed in" in l["error"] for l in lines):
                self.skipTest("the made-up cli is not picked up on this machine")
            self.fail("the model process never started")
        t = time.monotonic()
        p.send_signal(signal.SIGTERM)
        p.wait(20)
        reader.join(10)
        took = time.monotonic() - t
        err = p.stderr.read()
        p.stdout.close(); p.stderr.close()
        self.assertLess(took, 10)
        self.assertFalse(any("done" in l for l in lines[-1:]))            # every line read was whole json; the answer did not finish
        self.assertEqual(p.returncode, 0)
        self.assertEqual(err, "")
        for _ in range(60):
            try:
                os.kill(child, 0)
            except OSError:
                break
            time.sleep(0.05)
        else:
            self.fail("the model process outlived the answer")


if __name__ == "__main__":
    unittest.main()


class Flags(unittest.TestCase):
    """`python3 -m ctx answer ... --stream` run once, as the app runs it cold: whether it may look longer is the caller's to say."""

    def cold(self, *flags):
        import io, runpy
        seen, out = {}, io.StringIO()

        def stream(question, history=None, emit=print, dig="auto", scope=None):
            seen.update(question=question, dig=dig)
            emit({"done": {"answer": "not sure this is the one", "cites": [], "strength": "weak", "found_it": False, "error": ""}})
        with mock.patch.object(answer, "answer_stream", stream), mock.patch.object(sys, "argv", ["ctx", "answer", "what", "is", "the", "kettle", "fund", "--stream"] + list(flags)), \
                mock.patch.object(sys, "stdout", out), mock.patch.object(signal, "signal", lambda *a: None):
            with self.assertRaises(SystemExit) as stop:
                runpy.run_module("ctx", run_name="__main__")
        self.assertEqual(stop.exception.code, 0)
        return seen, [json.loads(l) for l in out.getvalue().splitlines()]

    def test_no_dig_means_one_answer_and_no_longer_look(self):
        seen, events = self.cold("--no-dig")
        self.assertEqual(seen, {"question": "what is the kettle fund", "dig": False})        # the flag is not part of the question
        self.assertEqual([sorted(e) for e in events], [["done"], ["end"]])                   # an unsure answer, and still no "dig-pending"

    def test_left_out_it_looks_longer_only_when_unsure_and_deep_always(self):
        seen, events = self.cold()
        self.assertEqual(seen["dig"], "auto")
        self.assertIn({"phase": "dig-pending"}, events)                                      # this answer is unsure: a longer look is said to follow
        seen, events = self.cold("--deep")
        self.assertEqual((seen["dig"], seen["question"]), (True, "what is the kettle fund"))
        seen, events = self.cold("--no-deep")                                                # the same flag's older name
        self.assertEqual(seen["dig"], False)
        self.assertNotIn({"phase": "dig-pending"}, events)

    def test_the_flag_is_in_the_help(self):
        r = subprocess.run([sys.executable, "-m", "ctx", "help"], cwd=fixture.REPO, env=dict(os.environ, PYTHONPATH=fixture.REPO), capture_output=True, text=True, timeout=60)
        self.assertIn("--no-dig", r.stdout + r.stderr)
