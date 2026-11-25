"""The nightly catch-up, with a stand-in for the model: what it reads first, where it stops, what it records. No model
call is made: the read-through's own calls are replaced, and a ledger is written by hand."""
import json, os, time, unittest
from tests import files as _f
from unittest import mock
from tests import fixture  # noqa: F401  (sets CTX_HOME before ctx is imported)
from ctx import catchup, llm, paths, settings, understand, wiki

POWER = catchup.power       # the real one: the tests below replace it
ALLOWED = catchup.allowed
NOW = time.mktime((2026, 3, 10, 2, 30, 0, 0, 0, -1))       # half past two at night, by this mac's clock


def unit(key, mine, last, size=100):
    return (key, {"title": key, "src": "whatsapp", "kind": "dm", "mine": mine, "n": mine * 2}, [(last + "T10:00:00Z", "me", "x" * size)])


class Night(unittest.TestCase):
    def setUp(self):
        for p in (catchup.STATE, paths.LEDGER):
            was = _f.read(p, "rb") if os.path.exists(p) else None
            self.addCleanup(lambda p=p, was=was: (_f.write(was, p, "wb") if was is not None else os.path.exists(p) and os.remove(p)))
            if os.path.exists(p):
                os.remove(p)
        self.units = [unit("old-heavy", 900, "2024-01-01"), unit("recent-light", 5, "2026-03-01"), unit("recent-heavy", 300, "2026-02-20"), unit("old-light", 9, "2023-05-05")]
        self.read, self.flags, self.breaks = [], [], {}

        def one(key, meta, rows):
            self.flags.append(getattr(llm._tl, "no_fallback", False))
            if key in self.breaks:
                raise self.breaks[key]
            self.read.append(key)
            self.log("understand:read")
            return {"ok": 1}

        def many(batch):
            for k, _, _ in batch:
                one(k, None, None)
            return len(batch)
        self.pages = []

        def build(max_calls=600, say=None, dry=False, **kw):
            if dry:
                return {"estimate": {"pages_to_write": {"people": 3, "years": 1}, "calls_total": 12}}
            self.pages.append(max_calls)
            return {"written": 2, "calls": min(max_calls, 3), "stopped": ""}
        patches = [mock.patch.object(understand, "units", lambda: list(self.units)), mock.patch.object(understand, "_current", lambda k, m: k in self.read),
                   mock.patch.object(understand, "jobs", lambda todo: [("one", u) for u in todo]), mock.patch.object(understand, "_read_unit", one),
                   mock.patch.object(understand, "_read_many", many), mock.patch.object(understand, "CHUNK", 1000), mock.patch.object(wiki, "build", build),
                   mock.patch.object(understand, "status", lambda: {"left": len([u for u in self.units if u[0] not in self.read]), "calls_left_about": 2 * len([u for u in self.units if u[0] not in self.read])}),
                   mock.patch.object(catchup, "power", lambda: (True, "")), mock.patch.object(catchup, "allowed", lambda: (True, "")), mock.patch.object(settings, "load", lambda: dict(settings.DEFAULTS, nightly_calls=self.calls, nightly_hour=2))]
        self.calls = 40
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def log(self, tag, at=None, **more):
        with open(paths.LEDGER, "a") as f:
            f.write(json.dumps(dict({"tag": tag, "in": 100, "out": 10, "at": at or NOW}, **more)) + "\n")

    def test_recent_conversations_first_then_the_ones_the_owner_wrote_most_in_then_the_pages(self):
        rec = catchup.run(40, NOW, busy=lambda: False)
        self.assertEqual(self.read, ["recent-heavy", "recent-light", "old-heavy", "old-light"])
        self.assertEqual(self.pages, [32])                                           # each conversation was sized at two calls: what is left goes to the wiki
        self.assertEqual((rec["conversations"], rec["pages"], rec["stopped"], rec["calls"], rec["in"], rec["out"]), (4, 2, "", 4, 400, 40))      # as the ledger has them
        self.assertTrue(all(self.flags))
        self.assertFalse(getattr(llm._tl, "no_fallback", False))

    def test_the_budget_ends_the_night_and_the_next_night_goes_on(self):
        rec = catchup.run(5, NOW, busy=lambda: False)
        self.assertEqual((self.read, self.pages, rec["conversations"]), (["recent-heavy", "recent-light"], [1], 2))      # two fit; the call left over goes to the pages
        catchup.run(5, NOW + 86400, busy=lambda: False)
        self.assertEqual(self.read, ["recent-heavy", "recent-light", "old-heavy", "old-light"])      # nothing read twice

    def test_a_usage_limit_stops_at_once_and_is_not_tried_again_that_night(self):
        self.breaks["recent-light"] = RuntimeError("claude: usage limit reached. resets at 5am")
        rec = catchup.run(40, NOW, busy=lambda: False, night="2026-03-10")
        self.assertEqual((self.read, self.pages), (["recent-heavy"], []))
        self.assertIn("limit", rec["stopped"])
        self.assertEqual(len(self.flags), 2)                                         # the call that hit the limit was the last
        with mock.patch.object(catchup, "night_of", lambda now, hour: "2026-03-10"):
            n, why = catchup.due(NOW + 900)
        self.assertEqual(n, 0)
        self.assertIn("stopped for tonight", why)

    def test_a_plan_at_its_limit_gets_no_smaller_model_when_the_switch_is_on(self):
        from ctx import models
        err = RuntimeError("usage limit reached")
        with mock.patch.object(models, "limited", lambda *a, **k: None), mock.patch.object(models, "lean_for", lambda name=None: {"plan": "claude", "ask": "lean-model", "name": "lean"}), \
                mock.patch.object(models, "note", lambda t: None):
            self.assertEqual(llm._recover(err, "claude", "big-model", "big-model", "routine", set()), ("claude", "lean-model"))
            llm._tl.no_fallback = True
            try:
                self.assertIsNone(llm._recover(err, "claude", "big-model", "big-model", "routine", set()))
            finally:
                llm._tl.no_fallback = False

    def test_an_answer_being_written_stops_it_and_a_conversation_too_big_for_a_night_is_passed_over(self):
        rec = catchup.run(40, NOW, busy=lambda: True)
        self.assertEqual((self.read, self.pages, rec["stopped"]), ([], [], "an answer is being written"))
        self.units.insert(0, unit("huge", 5000, "2026-03-05", size=90000))           # 92 calls by its size
        rec = catchup.run(40, NOW, busy=lambda: False)
        self.assertNotIn("huge", self.read)
        self.assertEqual((len(self.read), rec["too_big"]), (4, 1))

    def test_when_it_may_run(self):
        self.assertEqual(catchup.night_of(NOW, 2), "2026-03-10")
        self.assertEqual(catchup.night_of(NOW + 5 * 3600, 2), "")                     # half past seven: over for today
        self.assertEqual(catchup.night_of(NOW - 3600, 2), "")
        self.assertEqual(catchup.night_of(time.mktime((2026, 3, 11, 1, 0, 0, 0, 0, -1)), 23), "2026-03-10")      # a window that crosses midnight belongs to the day it began
        self.assertEqual(catchup.due(NOW), (40, ""))
        self.assertIn("runs from 02:00", catchup.due(NOW + 6 * 3600)[1])
        with mock.patch.object(catchup, "power", lambda: (False, "on battery at 31%")):
            self.assertEqual(catchup.due(NOW), (0, "on battery at 31%"))
        self.log("answer:write", at=NOW - 30)
        self.assertIn("answer is being written", catchup.due(NOW)[1])
        self.assertEqual(catchup.due(NOW + 600)[0], 40)
        self.log("understand:read", at=NOW + 590)                                    # a read-through the owner started is running
        self.assertEqual(catchup.due(NOW + 600)[0], 0)
        self.calls = 0
        self.assertIn("switched off", catchup.due(NOW + 5000)[1])

    def test_battery_is_read_from_the_mac(self):
        import subprocess
        for text, want in (("Now drawing from 'AC Power'\n -InternalBattery-0 (id=1)\t12%; charging", True), ("Now drawing from 'Battery Power'\n -InternalBattery-0\t77%; discharging", True),
                           ("Now drawing from 'Battery Power'\n -InternalBattery-0\t50%; discharging", False), ("", True)):
            with mock.patch.object(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, text, "")):
                self.assertEqual(POWER()[0], want, text[:30])

    def test_a_tick_spends_a_slice_and_the_night_adds_up(self):
        self.units += [unit("more-%d" % n, 20 - n, "2026-03-0%d" % (n + 1)) for n in range(8)]
        first = catchup.tick(NOW)
        self.assertEqual((first["ran"], first["conversations"]), (True, 5))           # ten calls a tick, two a conversation
        self.assertEqual(self.pages, [])                                             # there is still reading to do
        with open(paths.LEDGER, "w") as f:
            f.write("")                                                              # those calls were long ago by the next tick
        second = catchup.tick(NOW + 900)
        self.assertEqual(second["conversations"], 10)
        st = catchup.status(NOW + 1000, fresh=True)
        self.assertEqual((st["tonight"]["conversations"], st["tonight"]["runs"], st["behind"]["conversations"], st["behind"]["wiki_pages"], st["behind"]["wiki_calls"]), (10, 2, 2, 4, 12))
        self.assertEqual((st["nightly_calls"], st["nights_to_catch_up"], st["last_night"]), (40, 1, {}))
        self.assertEqual(catchup.tick(NOW + 6 * 3600)["ran"], False)
        rec = catchup.run(4, NOW + 86400, busy=lambda: False, night="2026-03-11")
        self.assertEqual((rec["night"], catchup.status(NOW + 86400)["last_night"]["conversations"]), ("2026-03-11", 10))

    def test_it_is_off_until_the_owner_has_said_yes_and_never_runs_with_nothing_to_read_or_no_model(self):
        import shutil, tempfile
        d = tempfile.mkdtemp(prefix="ctx-catchup-")
        self.addCleanup(shutil.rmtree, d, True)
        msgs, cards, sfile = os.path.join(d, "messages.jsonl"), os.path.join(d, "cards"), os.path.join(d, "settings.json")
        signed = {"using": "claude"}
        with mock.patch.object(catchup, "allowed", ALLOWED), mock.patch.object(paths, "MESSAGES", msgs), mock.patch.object(understand, "CARDS", cards), \
                mock.patch.object(settings, "FILE", sfile), mock.patch.object(llm, "status", lambda: dict(signed)):
            self.assertEqual(ALLOWED(), (False, "there is nothing in the archive to read yet"))      # an empty archive
            _f.write("{}\n", msgs, "w")
            ok, why = ALLOWED()
            self.assertFalse(ok)
            self.assertIn("after the first read-through, which only you start", why)             # a new archive: nobody has said yes
            self.assertEqual(catchup.due(NOW), (0, why))
            st = catchup.status(NOW)
            self.assertEqual((st["on"], st["may_run_now"], st["why_not"]), (False, False, why))
            os.makedirs(cards)
            _f.write("{}", os.path.join(cards, "a.json"), "w")                                 # the read-through has been run here: that was the yes
            self.assertEqual(ALLOWED(), (True, ""))
            self.assertEqual(catchup.due(NOW), (40, ""))
            os.remove(os.path.join(cards, "a.json"))
            _f.dump({"nightly_calls": 25}, sfile)                                  # or the owner set the number
            self.assertEqual(ALLOWED(), (True, ""))
            signed["using"] = "none"
            self.assertEqual(ALLOWED(), (False, "no model is signed in on this mac"))
            self.assertEqual(catchup.due(NOW), (0, "no model is signed in on this mac"))
            self.assertEqual(catchup.status(NOW)["may_run_now"], False)

    def test_the_settings_take_the_two_new_keys(self):
        self.assertEqual((settings.check("nightly_calls", "0"), settings.check("nightly_calls", "400"), settings.check("nightly_hour", "23")), ((0, ""), (400, ""), (23, "")))
        self.assertIsNone(settings.check("nightly_calls", "401")[0])
        self.assertIsNone(settings.check("nightly_hour", "24")[0])
        self.assertEqual((settings.DEFAULTS["nightly_calls"], settings.DEFAULTS["nightly_hour"]), (40, 2))


if __name__ == "__main__":
    unittest.main()
