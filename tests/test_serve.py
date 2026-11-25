import io, json, os, subprocess, sys, threading, time, unittest
from tests import files as _f
from unittest import mock
from tests import fixture
from ctx import answer, llm, paths, serve

PLAN = {"probes": [["kettle"]]}


class Lines:
    """What the server wrote, as parsed lines, with a way to wait for one."""

    def __init__(self):
        self.got, self.cv = [], threading.Condition()

    def write(self, text):
        with self.cv:
            self.got += [json.loads(l) for l in text.splitlines() if l]
            self.cv.notify_all()

    def flush(self):
        pass

    def wait(self, test, timeout=30):
        end = time.monotonic() + timeout
        with self.cv:
            while True:
                hit = [e for e in self.got if test(e)]
                if hit:
                    return hit[0]
                left = end - time.monotonic()
                if left <= 0:
                    raise AssertionError("never came. got: " + json.dumps(self.got)[:600])
                self.cv.wait(left)

    def of(self, rid):
        with self.cv:
            return [e for e in self.got if e.get("id") == rid]


class InProcess(unittest.TestCase):
    def setUp(self):
        self.out = Lines()
        self.srv = serve.Server(self.out)
        self.addCleanup(lambda: self.srv.pool.shutdown(wait=True))

    def send(self, **req):
        self.srv.handle(json.dumps(req))

    def result(self, rid, timeout=30):
        return self.out.wait(lambda e: e.get("id") == rid and ("result" in e or "error" in e or "done" in e or "cancelled" in e), timeout)

    def test_every_command_answers_with_its_id(self):
        row = {"id": "PR1", "src": "whatsapp", "ts": "2026-05-30", "thread": "x", "who": "me", "text": "i'll send it", "url": "", "kind": "promised"}
        with mock.patch("ctx.today.candidates", lambda now, spent=(): []), mock.patch("ctx.llm.status", lambda: {"using": "none", "plan": "", "fix": "x", "api_key": False,
                "claude": {"installed": False, "signed_in": False}, "codex": {"installed": False, "signed_in": False}}), mock.patch("ctx.mcp.status", lambda: []):
            self.send(id=1, cmd="ping")
            self.send(id="two", cmd="thread", msg="V700", around=2)
            self.send(id=3, cmd="facts")
            self.send(id=4, cmd="today", cached=True)
            self.send(id=5, cmd="settings", fast=True)
            self.send(id=6, cmd="mcp-status")
            self.send(id=7, cmd="nope")
            self.send(id=8, cmd="thread", msg="NOPE")
            self.assertEqual(self.result(1)["result"], "ok")
            self.assertEqual([r["id"] for r in self.result("two")["result"]["rows"]], ["V698", "V699", "V700", "V701", "V702"])
            self.assertIn("total", self.result(3)["result"])
            self.assertEqual(self.result(4)["result"], {"card": None})
            self.assertIn("archive", self.result(5)["result"])
            self.assertEqual(self.result(6)["result"], [])
            self.assertIn("no such command", self.result(7)["error"])
            self.assertEqual(self.result(7)["error"].split("commands: ")[1].split(", "), serve.commands())      # the list it names is the list it handles
            self.assertIn("error", self.result(8)["result"])

    def test_the_commands_named_are_the_ones_handled(self):
        import inspect, re
        names = serve.commands()
        src = inspect.getsource(serve.Server.run)
        self.assertEqual(len(names), len(set(names)))
        for must in ("answer", "ping", "now", "rules-list", "journal-edit", "made-save", "api-keys", "connect-list", "note", "cancel"):
            self.assertIn(must, names)
        for name in names:
            self.assertTrue(name == "cancel" or '"%s"' % name in src, name)
        tested = set(re.findall(r'cmd == "([a-z-]+)"', src)) | {n for group in re.findall(r"cmd in \(([^)]*)\)", src) for n in re.findall(r'"([a-z-]+)"', group)}
        self.assertEqual(tested - set(names), set())                     # nothing run() answers is left unsaid

    def test_bad_lines(self):
        for line in ("{nope", "[1]", '"text"', ""):
            self.srv.handle(line)
        self.assertEqual(len([e for e in self.out.got if e.get("id") is None and "error" in e]), 3)

    def test_an_answer_streams_under_its_id(self):
        with mock.patch.object(llm, "ask_json", lambda *a, **k: PLAN), mock.patch.object(llm, "stream", lambda *a, **k: iter(["it closes ", "friday [W1]."])):
            self.send(id=9, cmd="answer", q="what is the kettle fund", stream=True)
            done = self.result(9)["done"]
        events = self.out.of(9)
        self.assertEqual(events[0], {"phase": "plan", "id": 9})
        self.assertEqual("".join(e["delta"] for e in events if "delta" in e), "it closes friday[1].")
        self.assertEqual(done["answer"], "it closes friday[1].")
        self.assertTrue(all(e["id"] == 9 for e in events))

    def test_every_request_ends_with_an_end_line_and_nothing_after_it(self):
        with mock.patch("ctx.peek.thread", side_effect=RuntimeError("x")):
            self.send(id="crash", cmd="thread", msg="V1")
            self.out.wait(lambda e: e.get("id") == "crash" and e.get("end"))
        for rid, req in (("ok", {"cmd": "ping"}), ("bad", {"cmd": "nope"}), ("peek", {"cmd": "thread", "msg": "V700"}), ("c", {"cmd": "cancel", "target": "nothing"})):
            self.send(id=rid, **req)
            self.out.wait(lambda e, rid=rid: e.get("id") == rid and e.get("end"))
        time.sleep(0.2)
        for rid in ("crash", "ok", "bad", "peek", "c"):
            lines = self.out.of(rid)
            self.assertEqual(lines[-1], {"id": rid, "end": True}, rid)
            self.assertEqual(sum(1 for e in lines if e.get("end")), 1)

    def answer_events(self, rid, first, second=None, **req):
        """A streamed answer whose first reply is `first`; answer.deep is made up, so no model and no second search run."""
        def stream(q, history=None, emit=print, dig="auto", scope=None):
            emit({"phase": "plan"})
            emit({"done": first})
            if dig is True or (dig == "auto" and answer.needs_dig(first)):
                emit({"phase": "dig", "round": 1, "doing": "looking in notes"})
                if second:
                    emit({"done": second, "deep": True})
        with mock.patch.object(answer, "answer_stream", stream):
            self.send(id=rid, cmd="answer", q="q", stream=True, **req)
            self.out.wait(lambda e: e.get("id") == rid and e.get("end"))
        return [("deep-done" if e.get("deep") else "done") if "done" in e else e.get("phase") or ("end" if e.get("end") else "?") for e in self.out.of(rid)]

    def test_scope_is_passed_to_both_answer_calls_and_other_keys_are_not(self):
        got = []
        with mock.patch.object(answer, "answer_stream", lambda q, history=None, emit=print, dig="auto", scope=None: got.append(("stream", scope))), \
                mock.patch.object(answer, "answer", lambda q, history=None, dig=False, scope=None: got.append(("plain", scope)) or {"answer": "x"}):
            self.send(id="sc1", cmd="answer", q="q", stream=True, sources=["whatsapp"], after="2024-01", before="2024-12", people=["ada"], kind="analysis", junk=1)
            self.send(id="sc2", cmd="answer", q="q", sources=["apple_notes"])
            self.send(id="sc3", cmd="answer", q="q")
            for rid in ("sc1", "sc2", "sc3"):
                self.out.wait(lambda e, rid=rid: e.get("id") == rid and e.get("end"))
        self.assertEqual(sorted(got, key=str), sorted([("stream", {"sources": ["whatsapp"], "after": "2024-01", "before": "2024-12", "people": ["ada"], "kind": "analysis"}),
                                                       ("plain", {"sources": ["apple_notes"]}), ("plain", {})], key=str))

    def test_any_event_the_answer_emits_goes_out_unchanged_with_the_id(self):
        step = {"step": {"n": 1, "tool": "search", "args": {"query": "kiln"}, "found": 12}}

        def stream(q, history=None, emit=print, dig="auto", scope=None):
            emit(step)
            emit({"some_new_event": [1, 2, {"x": None}]})
            emit({"done": {"answer": "ok", "cites": [], "strength": "strong", "error": ""}})
        with mock.patch.object(answer, "answer_stream", stream):
            self.send(id="st", cmd="answer", q="q", stream=True)
            self.out.wait(lambda e: e.get("id") == "st" and e.get("end"))
        lines = self.out.of("st")
        self.assertEqual(lines[0], dict(step, id="st"))
        self.assertEqual(lines[1], {"some_new_event": [1, 2, {"x": None}], "id": "st"})
        self.assertEqual(lines[-1], {"id": "st", "end": True})

    def test_title(self):
        with mock.patch.object(answer, "title", lambda q, a: f"{q[:4]} / {a[:4]}"):
            self.send(id="t1", cmd="title", q="what is the kettle fund", a="it closes friday")
            self.assertEqual(self.result("t1")["result"], {"title": "what / it c"})
            self.send(id="t2", cmd="title")
            self.assertEqual(self.result("t2")["result"], {"title": " / "})

    def test_a_sure_first_answer_ends_right_after_done(self):
        strong = {"answer": "it closes friday[1].", "cites": [{"id": "W1"}], "strength": "strong", "error": ""}
        self.assertEqual(self.answer_events("s1", strong), ["plan", "done", "end"])

    def test_an_unsure_first_answer_says_a_deeper_search_is_coming(self):
        weak = {"answer": "your archive does not show it.", "cites": [], "strength": "weak", "error": ""}
        deep = {"answer": "found it in a note[1].", "cites": [{"id": "N1"}], "strength": "strong", "error": "", "deep": True}
        self.assertEqual(self.answer_events("w1", weak, deep), ["plan", "done", "dig-pending", "dig", "deep-done", "end"])
        self.assertEqual(self.answer_events("w2", weak), ["plan", "done", "dig-pending", "dig", "end"])        # the deeper search found nothing surer: still an end
        self.assertEqual(self.answer_events("w3", weak, deep, deep=False), ["plan", "done", "end"])              # forbidden: no pending, no dig
        strong = {"answer": "it closes friday[1].", "cites": [{"id": "W1"}], "strength": "strong", "error": ""}
        self.assertEqual(self.answer_events("s2", strong, deep, deep=True), ["plan", "done", "dig-pending", "dig", "deep-done", "end"])

    def test_an_answer_without_stream_is_one_result(self):
        with mock.patch.object(llm, "ask_json", lambda *a, **k: PLAN), mock.patch.object(llm, "ask", lambda *a, **k: json.dumps({"answer": "it closes friday [W1].", "cites": []})):
            self.send(id=10, cmd="answer", q="what is the kettle fund")
            self.assertEqual(self.result(10)["result"]["answer"], "it closes friday[1].")
        self.out.wait(lambda e: e.get("id") == 10 and e.get("end"))
        self.assertEqual([sorted(e) for e in self.out.of(10)], [["id", "result"], ["end", "id"]])

    def test_requests_run_side_by_side(self):
        gate, started = threading.Event(), threading.Event()

        def slow(*a, **k):
            started.set()
            gate.wait(20)
            yield "late [W1]."
        with mock.patch.object(llm, "ask_json", lambda *a, **k: PLAN), mock.patch.object(llm, "stream", slow):
            self.send(id="slow", cmd="answer", q="what is the kettle fund", stream=True)
            self.assertTrue(started.wait(20))
            t = time.monotonic()
            for n in range(6):
                self.send(id=f"p{n}", cmd="thread", msg=f"V{n * 100}", around=1)
            for n in range(6):
                self.assertEqual(self.result(f"p{n}")["result"]["focus"], f"V{n * 100}")
            self.assertLess(time.monotonic() - t, 10)                         # all answered while the slow one waits
            self.assertFalse([e for e in self.out.of("slow") if "done" in e])
            gate.set()
            self.assertEqual(self.result("slow")["done"]["answer"], "late[1].")

    def test_cancel_stops_the_events_and_the_model_call(self):
        started, killed = threading.Event(), []

        def stuck(*a, **k):
            yield "first words "
            started.set()
            time.sleep(4)
            yield "never"
        real = llm.cancel
        with mock.patch.object(llm, "ask_json", lambda *a, **k: PLAN), mock.patch.object(llm, "stream", stuck), \
                mock.patch.object(llm, "cancel", lambda ident: killed.append(ident) or real(ident)):
            self.send(id=20, cmd="answer", q="what is the kettle fund", stream=True)
            self.assertTrue(started.wait(20))
            self.send(id=21, cmd="cancel", target=20)
            self.assertEqual(self.result(21)["result"], {"cancelled": True})
            self.assertEqual(len(killed), 1)
            self.send(id=22, cmd="cancel", target="nothing")
            self.assertEqual(self.result(22)["result"], {"cancelled": False})
        # the worker is parked in the made-up sleep; what matters is that nothing more is written for it
        n = len(self.out.of(20))
        time.sleep(0.3)
        self.assertEqual(len(self.out.of(20)), n)
        self.assertFalse([e for e in self.out.of(20) if "done" in e])
        self.srv.pool.shutdown(wait=False)
        self.srv.pool = serve.ThreadPoolExecutor(2)

    def test_a_cancelled_request_says_so_when_it_unwinds(self):
        started, gate = threading.Event(), threading.Event()

        def waits(*a, **k):
            yield "first words "
            started.set()
            gate.wait(20)
            yield "more"
        with mock.patch.object(llm, "ask_json", lambda *a, **k: PLAN), mock.patch.object(llm, "stream", waits):
            self.send(id=30, cmd="answer", q="what is the kettle fund", stream=True)
            self.assertTrue(started.wait(20))
            self.send(id=31, cmd="cancel", target=30)
            self.result(31)
            gate.set()
            self.assertEqual(self.out.wait(lambda e: e.get("id") == 30 and e.get("cancelled")), {"id": 30, "cancelled": True})
        self.assertFalse([e for e in self.out.of(30) if "done" in e or "more" in str(e.get("delta"))])

    def test_status_commands(self):
        with mock.patch("ctx.doctor.report", lambda: {"system": {"python_ok": True}, "sources": {}}):
            self.send(id=60, cmd="doctor")
            self.assertEqual(self.result(60)["result"]["system"], {"python_ok": True})
        from ctx import wordindex
        wordindex.warm()
        self.send(id=61, cmd="index-status")
        got = self.result(61)["result"]
        self.assertEqual((got["words"]["whole"], set(got) >= {"words", "meaning", "threads", "ids"}), (True, True))
        self.send(id=62, cmd="collect-status")
        got = self.result(62)["result"]
        self.assertEqual((got["running"], "whatsapp" in got["sources"]), (False, True))

    def test_subscribe_says_when_a_read_lands_rows(self):
        path = os.path.join(paths.HOME, "status.json")
        keep = _f.read(path)
        try:
            self.send(id=70, cmd="subscribe", every=0.05)
            self.out.wait(lambda e: e.get("id") == 70 and e.get("event") == "subscribed")
            time.sleep(0.1)
            for st in ({"whatsapp": {"rows": 212, "new": 12}, "obsidian": {"rows": 3, "new": 0}}, {"whatsapp": {"rows": 212, "new": 12}, "obsidian": {"rows": 3, "new": 0}},
                       {"whatsapp": {"rows": 215, "new": 3}, "obsidian": {"skipped": "x", "new": 0}}):
                with open(path + ".t", "w") as f:
                    json.dump(st, f)
                os.replace(path + ".t", path)
                time.sleep(0.3)
            self.out.wait(lambda e: e.get("id") == 70 and e.get("new") == 3)
            sync = [e for e in self.out.of(70) if e.get("event") == "sync"]
            self.assertEqual(sync, [{"event": "sync", "src": "whatsapp", "new": 12, "rows": 212, "id": 70}, {"event": "sync", "src": "whatsapp", "new": 3, "rows": 215, "id": 70}])
            self.send(id=71, cmd="cancel", target=70)
            self.assertEqual(self.out.wait(lambda e: e.get("id") == 70 and e.get("cancelled")), {"id": 70, "cancelled": True})
        finally:
            _f.write(keep, path, "w")

    def test_collect_passes_progress_lines_on(self):
        import subprocess

        class Child:
            def __init__(self, cmd, **kw):
                Child.cmd = cmd
                self.stdout = io.StringIO('@{"src": "obsidian", "phase": "starting", "rows": 0}\nnot progress\n@{"src": "obsidian", "rows": 3}\nobsidian     {...}\n')

            def poll(self):
                return 0

            def wait(self):
                return 0
        with mock.patch.object(subprocess, "Popen", Child):
            self.send(id=80, cmd="collect", src="obsidian")
            res = self.result(80)["result"]
        self.assertEqual(Child.cmd[-2:], ["collect-one", "obsidian"])
        self.assertEqual([e for e in self.out.of(80) if e.get("event") == "progress"],
                         [{"src": "obsidian", "phase": "starting", "rows": 0, "event": "progress", "id": 80}, {"src": "obsidian", "rows": 3, "event": "progress", "id": 80}])
        self.assertEqual((res["exit"], res["last"]), (0, "obsidian     {...}"))
        with mock.patch.object(subprocess, "Popen", Child):
            self.send(id=81, cmd="collect", tick=["fast", "nonsense"])
            self.result(81)
        self.assertEqual(Child.cmd[-2:], ["tick", "fast"])

    def test_today_reads_the_cache_and_never_builds_unless_asked(self):
        with mock.patch("ctx.today.build", side_effect=AssertionError("built")):
            self.send(id=90, cmd="today")
            self.assertEqual(self.result(90)["result"], {"card": None})

    def test_a_crash_in_a_command_is_one_plain_line(self):
        with mock.patch("ctx.peek.thread", side_effect=RuntimeError("/Users/someone/secret")):
            self.send(id=40, cmd="thread", msg="V1")
            e = self.result(40)
        self.assertIn("did not work", e["error"])
        self.assertNotIn("/Users", json.dumps(e))

    def test_facts_are_kept_until_messages_change(self):
        calls = []
        with mock.patch("ctx.facts.facts", lambda: calls.append(1) or {"total": len(calls)}):
            self.assertEqual(self.srv.facts(), {"total": 1})
            self.assertEqual(self.srv.facts(), {"total": 1})
            keep = _f.read(paths.MESSAGES, "rb")
            try:
                with open(paths.MESSAGES, "ab") as f:
                    f.write(b'{"id": "ZZ", "src": "whatsapp", "ts": "2026-01-01T00:00:00Z", "thread_id": "t", "thread": "t", "kind": "dm", "who": "me", "sender": "me", "text": "x"}\n')
                self.assertEqual(self.srv.facts(), {"total": 2})         # the file changed: counted again
            finally:
                _f.write(keep, paths.MESSAGES, "wb")

    def test_indexes_follow_the_archive_while_the_server_lives(self):
        self.send(id=50, cmd="thread", msg="W1", around=50)
        n = self.result(50)["result"]["rows_total"]
        keep = _f.read(paths.MESSAGES, "rb")
        try:
            with open(paths.MESSAGES, "a") as f:
                f.write(json.dumps(fixture.msg("LIVE1", "written while the server runs", thread="ada lovelace", ts="2026-02-02T10:00:00Z")) + "\n")
            self.send(id=51, cmd="thread", msg="LIVE1", around=1)
            got = self.result(51)["result"]
            self.assertEqual((got["focus"], got["rows_total"]), ("LIVE1", n + 1))
        finally:
            _f.write(keep, paths.MESSAGES, "wb")


class Process(unittest.TestCase):
    """`python3 -u -m ctx serve` as the app starts it."""

    def start(self):
        # the server is a process of its own: it is told where to look for a model cli (an empty folder made here), given no
        # api key and no model by name, so no line it is sent can reach a real model whatever the mac it runs on has
        import tempfile, shutil
        self.no_cli = tempfile.mkdtemp(prefix="ctx-no-cli-")
        self.addCleanup(shutil.rmtree, self.no_cli, ignore_errors=True)
        env = dict(os.environ, CTX_HOME=fixture.HOME, PYTHONPATH=fixture.REPO, CTX_CLI_PATH=self.no_cli, ANTHROPIC_API_KEY="", CTX_AGENT="0", CTX_NO_API="1")
        for k in ("CTX_MODEL", "CTX_ANSWER_MODEL", "CTX_AGENT_MODEL", "CTX_AGENT_DEEP_MODEL"):
            env.pop(k, None)
        return subprocess.Popen([sys.executable, "-u", "-m", "ctx", "serve"], cwd=fixture.REPO, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)

    def test_ready_then_requests_then_exit_when_stdin_closes(self):
        p = self.start()
        try:
            t = time.monotonic()
            ready = json.loads(p.stdout.readline())
            self.assertEqual((ready["ready"], ready["pid"]), (True, p.pid))
            p.stdin.write(json.dumps({"id": 1, "cmd": "ping"}) + "\n" + json.dumps({"id": 2, "cmd": "thread", "msg": "V700", "around": 1}) + "\n")
            p.stdin.flush()
            got = {}
            ends = set()
            while len(ends) < 2:
                e = json.loads(p.stdout.readline())
                if e.get("end"):
                    ends.add(e["id"])
                else:
                    got[e["id"]] = e
            self.assertEqual(got[1]["result"], "ok")
            self.assertEqual(len(got[2]["result"]["rows"]), 3)
            p.stdin.close()
            self.assertEqual(p.wait(20), 0)
            self.assertEqual(p.stderr.read(), "")
        finally:
            if p.poll() is None:
                p.kill()
            p.stdout.close()
            p.stderr.close()

    def test_plan_is_said_at_once(self):
        p = self.start()
        try:
            json.loads(p.stdout.readline())
            t = time.monotonic()
            p.stdin.write(json.dumps({"id": "a", "cmd": "answer", "q": "what is the kettle fund", "stream": True}) + "\n")
            p.stdin.flush()
            first = json.loads(p.stdout.readline())
            took = time.monotonic() - t
            self.assertEqual(first, {"phase": "plan", "id": "a"})
            self.assertLess(took, 20)                                    # about 20 ms on a quiet mac. that it comes first is the point; the bound only catches a hang
            p.stdin.close()
            self.assertEqual(p.wait(60), 0)                              # stdin closed mid-answer: it ends, with nothing left running
            rest = [json.loads(l) for l in p.stdout.read().splitlines() if l]
            self.assertEqual([e for e in rest if "delta" in e or "done" in e], [])       # no model wrote a word: there is none to find
            for e in rest:
                if "error" in e:
                    self.assertIn("no model is signed in", e["error"])
            self.assertEqual(os.listdir(self.no_cli), [])
        finally:
            if p.poll() is None:
                p.kill()
            p.stdout.close()
            p.stderr.close()


if __name__ == "__main__":
    unittest.main()
