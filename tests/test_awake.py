"""Limits, waits and pauses count time awake. A mac that sleeps moves the wall clock minutes ahead in seconds of running
time; nothing in one process may read that as time spent. Each test leaps the wall clock and expects the work done."""
import json, os, threading, time, unittest
from unittest import mock

from tests import fixture
from ctx import answer, bridge, collect, guard, llm, media, models, remote, request, semantic

fixture.write()
REAL = time.time


def leaping(step=600):
    """time.time() that jumps ten minutes whenever it is looked at, as it does across a sleep. time.monotonic() is left alone."""
    n = [0]

    def wall():
        n[0] += step
        return REAL() + n[0]
    return mock.patch.object(time, "time", wall)


class Awake(unittest.TestCase):
    def test_a_dig_is_not_cut_short_by_a_sleep(self):           # answer.py
        digs = [{"probes": [["celadon"]], "doing": "trying the glaze's name", "why": "another word"}, {"keep": ["R1"], "stop": "found", "why": "R1 names it"}]
        good = {"answer": "a celadon glaze [R1].", "cites": ["R1"], "confidence": 4, "strength": "strong"}
        seen = []

        def ask_json(system, prompt, model=None, tag=""):
            seen.append(tag)
            return digs[min(len([t for t in seen if t.endswith("dig")]), len(digs)) - 1] if tag.endswith("dig") else {"probes": [["zeppelin"]]}
        with mock.patch.object(llm, "ask_json", ask_json), mock.patch.object(llm, "ask", lambda *a, **k: json.dumps(good)), \
                mock.patch.object(semantic, "ready", lambda: False), leaping():
            out = answer.deep("what finish did they suggest for the pots", None, {"answer": "the archive does not show it.", "cites": [], "strength": "weak", "searched": ["pots finish"]})
        self.assertEqual([d["round"] for d in out["dug"]], [1, 2])          # both rounds ran: no time awake had passed

    def test_a_job_handed_to_the_extension_waits_through_a_sleep(self):     # bridge.py
        import shutil, tempfile
        d = tempfile.mkdtemp(prefix="ctx-awake-bridge-")        # its own folder: the shared made-up archive never gets a bridge
        self.addCleanup(shutil.rmtree, d, True)
        for name, sub_ in (("ROOT", ""), ("JOBS", "jobs"), ("RESULTS", "results"), ("BEAT", "heartbeat"), ("KEY", "key")):
            p = mock.patch.object(bridge, name, os.path.join(d, sub_) if sub_ else d)
            p.start()
            self.addCleanup(p.stop)
        bridge._dirs()
        stop = threading.Event()

        def extension():                    # takes the job a moment later and answers it
            while not stop.is_set():
                for n in os.listdir(bridge.JOBS):
                    if n.endswith(".json"):
                        os.remove(os.path.join(bridge.JOBS, n))
                        with open(os.path.join(bridge.RESULTS, n), "w") as f:
                            json.dump({"ok": True, "result": 7}, f)
                        return
                stop.wait(0.05)
        t = threading.Thread(target=extension, daemon=True)
        self.addCleanup(lambda: (stop.set(), t.join(5)))
        with leaping():
            t.start()
            self.assertEqual(bridge.submit({"reader": "made_up"}, timeout=5, pickup=5), 7)

    def test_a_page_is_waited_for_in_time_awake(self):          # request.py
        tab = request.Tab.__new__(request.Tab)
        answers = ["", "", "ready"]
        tab.check = lambda: None
        tab.js = lambda body: answers.pop(0)
        with leaping(), mock.patch.object(request.time, "sleep", lambda s: None):
            self.assertEqual(tab.wait("return 1", secs=20), "ready")

    def test_a_scan_with_a_time_limit_reads_through_a_sleep(self):          # media.py
        import shutil, tempfile
        d = os.path.realpath(tempfile.mkdtemp(prefix="ctx-awake-"))
        self.addCleanup(shutil.rmtree, d, True)
        self.addCleanup(shutil.rmtree, media.DIR, True)
        shutil.rmtree(media.DIR, True)
        for n in range(3):
            with open(os.path.join(d, "scan %d.png" % n), "wb") as f:
                f.write(b"x" * 20000)

        class Tool:
            def ask(self, kind, path, timeout=0, **more):
                return {"ok": True, "text": "the lease for marlow street was signed on friday by both sides", "conf": 0.9, "labels": [], "w": 800, "h": 600}

            def close(self):
                pass
        items = [{"path": os.path.join(d, n), "kind": "image", "size": 20000, "mtime": 1, "ts": 1, "place": "papers", "what": "x"} for n in sorted(os.listdir(d))]
        with mock.patch.object(media, "battery", lambda: (False, 100)), mock.patch.object(media, "_shots", set()), leaping():
            r = media.scan(tool=Tool(), cfg=dict(media.DEFAULTS, folders=[d], leave_out=[]), seconds=60, items=items, can_speak=(True, "en-US", ""))
        self.assertEqual((r["read"], r["stopped"]), (3, ""), r)

    def test_a_ticks_media_budget_is_not_handed_back_by_a_sleep(self):      # media.py
        with mock.patch.object(media, "_turn", [time.monotonic(), 40.0]), leaping():
            self.assertEqual(media._budget({"tick_seconds": 60}), 20.0)     # the turn began now: a leap of the wall clock does not start a new one

    def test_the_models_in_use_are_kept_for_a_minute_awake(self):           # models.py
        asked = []
        with mock.patch.object(models, "roles", lambda: (asked.append(1), ({"tools": {"plan": "claude", "ask": "made-up"}}, ""))[1]), \
                mock.patch.object(models, "role_of", lambda tag, model, defaults: "tools"), \
                mock.patch.object(models, "_memo", {"at": float("-inf"), "roles": {}, "stamp": None}), leaping():
            for _ in range(3):
                self.assertEqual(models.route("answer:plan", "x", {})[1], "made-up")
        self.assertEqual(len(asked), 1)

    def test_the_cap_on_calls_a_minute_is_a_minute_awake(self):             # remote.py
        with mock.patch.object(remote, "_calls", lambda day: (0, 0)):
            gate = remote.Gate(per_minute=2, per_day=100)
        with leaping(step=30):              # under a day in all, so the day's count is not what answers
            self.assertEqual([gate.take(), gate.take(), gate.take()], ["", "", "minute"])

    def test_progress_lines_are_spaced_in_time_awake(self):     # collect.py
        said = []
        tl, out = collect._tl, type("Out", (), {"write": lambda self, s: None})()
        with mock.patch.object(collect, "_say", said.append), leaping():
            tl.out, tl.name, tl.n, tl.t = out, "made_up", 0, time.monotonic()
            try:
                for i in range(5):
                    collect.put(out, {"id": "A%d" % i, "src": "made_up", "ts": "2025-01-01T00:00:00Z", "thread": "a", "text": "hello there"})
            finally:
                tl.out = None
        self.assertEqual(said, [])          # five rows in a blink: no line yet, whatever the wall clock says


if __name__ == "__main__":
    unittest.main()
