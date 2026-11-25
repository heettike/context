"""The clock for export re-requests. The browser is never driven: the tab and the site are stubs."""
import json, os, time, unittest
from unittest import mock
from tests import fixture
from ctx import schedule


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def keep(test, *files):
    """Put these files back as they were when the test ends (the made-up archive is shared by every test)."""
    for path in files:
        try:
            with open(path, "rb") as f:
                was = f.read()
        except OSError:
            was = None

        def back(path=path, was=was):
            if was is None:
                if os.path.exists(path):
                    os.remove(path)
            else:
                with open(path, "wb") as f:
                    f.write(was)
        test.addCleanup(back)


class ExportClock(unittest.TestCase):
    """A filed export request starts the clock for the next one. The browser is never driven: the tab and the site are stubs."""

    def setUp(self):
        from ctx import request
        self.request = request
        keep(self, request.STATE, schedule.STATE)
        for p in (request.STATE, schedule.STATE):
            if os.path.exists(p):
                os.remove(p)
        self.clicked = []

        class Tab:
            def __init__(tab, *a):
                pass

            def close(tab):
                pass

            def front(tab):
                pass
        sid = "chatgpt"
        fake = dict(request.BY_ID[sid], run=lambda t: self.clicked.append(sid))
        fake.pop("pending", None)
        for p in (mock.patch.object(request, "Tab", Tab), mock.patch.object(request, "browser", lambda ask=False: {"name": request.BROWSERS[0][0], "scripting": True}),
                  mock.patch.dict(request.BY_ID, {sid: fake}), mock.patch.object(request, "osa", side_effect=AssertionError("drove the browser"))):
            p.start()
            self.addCleanup(p.stop)

    def test_a_request_is_noted_and_the_plan_shows_when_the_next_is_due(self):
        self.assertIsNone(schedule.plan()["weekly"]["chatgpt"]["next_in"])
        t0 = time.time()
        self.assertEqual(self.request.request("chatgpt")["state"], "requested")
        self.assertEqual(self.clicked, ["chatgpt"])
        noted = json.loads(read(schedule.STATE))["exports"]["chatgpt"]
        self.assertTrue(t0 - 1 <= noted <= time.time() + 1)
        w = schedule.plan()["weekly"]["chatgpt"]
        every = schedule.EVERY[w["every"]]
        self.assertEqual((w["state"], w["due"], w["last"]), ("requested", False, noted))
        self.assertTrue(every - 5 <= w["next_in"] <= every)
        with mock.patch.object(schedule, "day_ok", lambda now, cfg: True):
            late = schedule.plan(now=noted + every + 60)["weekly"]["chatgpt"]
        self.assertEqual((late["due"], late["next_in"]), (True, 0))

    def test_a_failed_request_starts_no_clock(self):
        with mock.patch.dict(self.request.BY_ID, {"chatgpt": dict(self.request.BY_ID["chatgpt"], run=mock.Mock(side_effect=self.request.Fail("the button is gone")))}):
            self.assertEqual(self.request.request("chatgpt")["state"], "failed")
        self.assertFalse(os.path.exists(schedule.STATE))
        self.assertIsNone(schedule.plan()["weekly"]["chatgpt"]["next_in"])

    def test_a_request_made_before_the_clock_was_kept_still_counts(self):
        from datetime import datetime, timezone
        at = time.time() - 3 * 86400
        self.request._save("chatgpt", "requested", "", datetime.fromtimestamp(at, timezone.utc).isoformat(timespec="seconds"))
        w = schedule.plan()["weekly"]["chatgpt"]
        self.assertTrue(abs(w["last"] - at) < 2)
        self.assertTrue(0 < w["next_in"] <= schedule.EVERY[w["every"]] - 3 * 86400 + 2)


if __name__ == "__main__":
    unittest.main()


class Quiet(unittest.TestCase):
    """A signed-in source nobody uses stops being tried every day and stops asking for anything."""
    DAY = 86400
    TAB = {"rows": 40, "new": 0, "state": "skipped", "detail": "needs a tab open on the site"}

    def days(self, st, name, results, start=1000000.0):
        """Play one daily read per day; returns what was recorded each day, and whether the source was really tried."""
        out = []
        for k, r in enumerate(results):
            now = start + k * self.DAY
            resting = schedule.quiet_now(st, name, now)
            out.append((resting or schedule.quiet_note(st, name, dict(r), now), resting is None))
        return out

    def test_a_week_of_the_same_skip_makes_it_quiet_and_it_is_then_tried_weekly(self):
        st = {}
        got = self.days(st, "teashop", [self.TAB] * 22)
        for rec, tried in got[:6]:
            self.assertEqual((rec["detail"], tried), (self.TAB["detail"], True))
        self.assertEqual([tried for _, tried in got[6:]], [True] + [False] * 6 + [True] + [False] * 6 + [True, False])     # days 7, 14, 21
        for rec, _ in got[6:]:
            self.assertEqual((rec["state"], rec["detail"], rec["rows"], rec["new"]), ("skipped", schedule.QUIET_NOTE, 40, 0))
        self.assertIn("nothing is needed", schedule.QUIET_NOTE)

    def test_needing_the_owner_for_a_week_goes_quiet_too(self):
        st = {}
        got = self.days(st, "teashop", [dict(self.TAB, state="needs_you", detail="sign in to teashop in your browser")] * 8)
        self.assertEqual([r["state"] for r, _ in got], ["needs_you"] * 6 + ["skipped"] * 2)
        self.assertEqual(got[7][0]["detail"], schedule.QUIET_NOTE)

    def test_a_source_with_no_saved_rows_keeps_its_note(self):
        st = {}
        got = self.days(st, "teashop", [dict(self.TAB, rows=0)] * 12)
        self.assertEqual({(r["detail"], tried) for r, tried in got}, {(self.TAB["detail"], True)})
        self.assertEqual(st["quiet"], {})

    def test_a_read_that_works_or_a_new_reason_starts_the_count_again(self):
        st = {}
        ok = {"rows": 41, "new": 1, "state": "ok", "detail": ""}
        got = self.days(st, "teashop", [self.TAB] * 5 + [ok] + [self.TAB] * 6 + [dict(self.TAB, detail="another reason")] * 6)
        self.assertTrue(all(tried for _, tried in got))
        self.assertNotIn(schedule.QUIET_NOTE, [r["detail"] for r, _ in got])
        # and a quiet source that reads again wakes up for good
        st = {}
        self.days(st, "teashop", [self.TAB] * 7)
        self.assertEqual(schedule.quiet_note(st, "teashop", dict(ok), 1000000.0 + 14 * self.DAY), ok)
        self.assertIsNone(schedule.quiet_now(st, "teashop", 1000000.0 + 15 * self.DAY))
        self.assertNotIn("teashop", st["quiet"])

    def test_many_reads_in_one_day_count_once(self):
        st = {}
        for k in range(30):
            rec = schedule.quiet_note(st, "teashop", dict(self.TAB), 1000000.0 + k * 600)
        self.assertEqual((rec["detail"], st["quiet"]["teashop"]["n"]), (self.TAB["detail"], 1))

    def test_a_source_another_read_was_busy_with_is_not_counted_and_one_named_by_hand_is_tried(self):
        from ctx import collect
        st = {}
        busy = {"rows": 40, "new": 0, "state": "skipped", "detail": collect.BUSY}
        self.assertEqual([r["detail"] for r, _ in self.days(st, "teashop", [busy] * 9)], [collect.BUSY] * 9)
        self.days(st, "teashop", [self.TAB] * 7)
        now = 1000000.0 + 8 * self.DAY
        self.assertIsNotNone(schedule.quiet_now(st, "teashop", now))
        self.assertIsNone(schedule.quiet_now(st, "teashop", now, force=("teashop",)))

    def test_the_daily_read_leaves_a_quiet_source_alone_and_records_the_note(self):
        from ctx import collect, signed_in
        keep(self, schedule.STATE)
        now = time.time()
        with open(schedule.STATE, "w") as f:
            json.dump({"fast": now, "daily": 0, "calendar": now,
                       "quiet": {"slack": {"why": ["skipped", "needs a tab open on the site"], "n": 9, "counted": now - 3600, "tried": now - 3600, "rows": 40}}}, f)
        called = []

        def reader(name, result):
            def run():
                called.append(name)
                return dict(result)
            return run
        ok = {"rows": 3, "new": 0, "state": "ok", "detail": ""}
        patches = [mock.patch("ctx.exports.ingest", lambda: []), mock.patch.object(collect, "run", lambda only=None: {}),
                   mock.patch.object(collect, "telegram_new", lambda: {"new": 0, "state": "ok", "detail": ""}),
                   mock.patch("ctx.models.refresh", lambda: None), mock.patch("ctx.today.build", lambda: {}),
                   mock.patch("ctx.semantic.build", lambda say=None: {}), mock.patch("ctx.peek.warm", lambda: None), mock.patch("ctx.wordindex.warm", lambda: None),
                   mock.patch.object(schedule, "plan", lambda now=None: {"fast": {"due": False}, "daily": {"due": True}, "weekly": {}, "read_through": {"due": False}}),
                   mock.patch.object(schedule, "_canvas", lambda tier: [])]
        patches += [mock.patch.object(signed_in, n, reader(n, self.TAB if n == "gdrive" else ok)) for n in ("slack", "gdrive", "calendar", "x_bookmarks", "x_likes", "x_posts", "x_replies")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        schedule.tick()
        self.assertNotIn("slack", called)
        self.assertIn("gdrive", called)
        st = json.loads(read(schedule.STATE))
        self.assertEqual(st["daily_results"]["slack"], {"rows": 40, "new": 0, "state": "skipped", "detail": schedule.QUIET_NOTE})
        self.assertEqual(st["daily_results"]["gdrive"]["detail"], self.TAB["detail"])       # its first skip: the note stays
        self.assertEqual(st["quiet"]["gdrive"]["n"], 1)
        self.assertEqual(st["quiet"]["slack"]["n"], 9)


class Spends(unittest.TestCase):
    """The two model calls the engine makes on its own, each with a switch: the morning card and the daily try of each model."""

    def setUp(self):
        from ctx import settings
        self.settings = settings
        keep(self, settings.FILE, settings.APP, schedule.STATE)
        for p in (settings.FILE, settings.APP):
            if os.path.exists(p):
                os.remove(p)

    def write(self, path, data):
        with open(path, "w") as f:
            json.dump(data, f)

    def daily(self):
        """One daily read with every reader a stub; returns which of the two calls were made."""
        from ctx import collect, signed_in
        made = []
        self.write(schedule.STATE, {"fast": time.time(), "daily": 0, "calendar": time.time()})
        ok = {"rows": 1, "new": 0, "state": "ok", "detail": ""}
        patches = [mock.patch("ctx.exports.ingest", lambda: []), mock.patch.object(collect, "run", lambda only=None: {}), mock.patch.object(collect, "telegram_new", lambda: dict(ok)),
                   mock.patch("ctx.models.refresh", lambda: made.append("model_check")), mock.patch("ctx.today.build", lambda: made.append("morning_card") or {"card": {"id": "c"}}),
                   mock.patch("ctx.semantic.build", lambda say=None: {}), mock.patch("ctx.peek.warm", lambda: None), mock.patch("ctx.wordindex.warm", lambda: None),
                   mock.patch.object(schedule, "plan", lambda now=None: {"fast": {"due": False}, "daily": {"due": True}, "weekly": {}, "read_through": {"due": False}}),
                   mock.patch.object(schedule, "_canvas", lambda tier: [])]
        patches += [mock.patch.object(signed_in, n, lambda: dict(ok)) for n in ("slack", "gdrive", "calendar", "x_bookmarks", "x_likes", "x_posts", "x_replies")]
        for p in patches:
            p.start()
        try:
            done = schedule.tick()
        finally:
            for p in patches:
                p.stop()
        return sorted(made), done

    def test_before_setup_nothing_is_spent_whatever_the_switches_say(self):
        """The app writes onboarded in app.json when its setup is done. Until then neither call is made: not on the daily
        read, and not at launch, where serve.py asks models.refresh_in_background()."""
        from ctx import models, serve
        tried = []
        thread = lambda target, daemon: tried.append(target) or type("T", (), {"start": lambda self: None})()
        with mock.patch.object(models, "_load", lambda: {}), mock.patch.object(models, "refresh", lambda: tried.append(1)), \
                mock.patch.object(models.threading, "Thread", thread):
            for app in (None, {}, {"theme": "dark"}, {"onboarded": False, "morningCard": True, "modelCheck": True}, {"onboarded": "yes"}, "{not json", ["onboarded"]):
                if app is None and os.path.exists(self.settings.APP):
                    os.remove(self.settings.APP)
                elif isinstance(app, str):
                    with open(self.settings.APP, "w") as f:
                        f.write(app)
                elif app is not None:
                    self.write(self.settings.APP, app)
                self.assertEqual((self.settings.spend("morning_card"), self.settings.spend("model_check")), (False, False), app)
                self.assertEqual(self.daily()[0], [], app)
                self.assertFalse(models.refresh_in_background(), app)
                serve.Server.warm(None)                                   # what the engine does as it starts
        self.assertEqual(tried, [])                                          # no check was started, nor its thread

    def test_after_setup_both_are_on_said_nowhere(self):
        from ctx import models, serve
        self.write(self.settings.APP, {"onboarded": True})
        self.assertTrue(self.settings.spend("morning_card") and self.settings.spend("model_check"))
        made, done = self.daily()
        self.assertEqual(made, ["model_check", "morning_card"])
        self.assertEqual(done["today"], True)
        started = []
        with mock.patch.object(models, "_load", lambda: {}), mock.patch.object(models, "refresh", lambda: None), \
                mock.patch.object(models.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda self: started.append(1)})()):
            self.assertTrue(models.refresh_in_background())
            serve.Server.warm(None)
        self.assertEqual(started, [1, 1])                                    # once asked directly, once by the launch warm-up

    def test_after_setup_the_apps_switches_are_honoured_off_on_and_absent(self):
        self.write(self.settings.APP, {"onboarded": True, "morningCard": False, "modelCheck": True, "something": "else"})
        self.assertEqual((self.settings.spend("morning_card"), self.settings.spend("model_check")), (False, True))
        made, done = self.daily()
        self.assertEqual((made, done["today"]), (["model_check"], "switched off"))
        self.write(self.settings.APP, {"onboarded": True, "morningCard": True, "modelCheck": False})
        made, done = self.daily()
        self.assertEqual((made, done["today"], done["models"]), (["morning_card"], True, "switched off"))
        self.write(self.settings.APP, {"onboarded": True, "morningCard": False, "modelCheck": False})
        self.assertEqual(self.daily()[0], [])
        self.write(self.settings.APP, {"onboarded": True, "theme": "dark"})      # set up, and the switches are not there: on
        self.assertEqual(self.daily()[0], ["model_check", "morning_card"])

    def test_the_engines_own_settings_do_the_same(self):
        self.write(self.settings.APP, {"onboarded": True})
        self.assertEqual(self.settings.load()["morning_card"], "on")
        self.assertEqual(self.settings.load()["model_check"], "on")
        self.assertTrue(self.settings.set_("morning_card=off")["ok"])
        self.assertEqual(self.daily()[0], ["model_check"])
        self.assertTrue(self.settings.set_("model_check=false")["ok"])
        self.assertEqual(self.settings.load()["model_check"], "off")
        self.assertEqual(self.daily()[0], [])
        self.write(self.settings.APP, {"onboarded": True, "morningCard": True, "modelCheck": True})       # off in either place is off
        self.assertEqual(self.daily()[0], [])
        self.assertTrue(self.settings.set_("morning_card=on")["ok"] and self.settings.set_("model_check=on")["ok"])
        self.assertEqual(self.daily()[0], ["model_check", "morning_card"])
        self.assertFalse(self.settings.set_("morning_card=sometimes")["ok"])
        for key in ("morning_card", "model_check"):
            self.assertIn(key, self.settings.ABOUT)

    def test_the_daily_try_started_with_the_app_is_switched_off_too(self):
        from ctx import models
        started = []
        with mock.patch.object(models, "refresh", lambda *a, **k: started.append(1)), mock.patch.object(models, "_load", lambda: {"refreshed": 0}):
            self.write(self.settings.APP, {"onboarded": True, "modelCheck": False})
            self.assertFalse(models.refresh_in_background())
            self.write(self.settings.APP, {"onboarded": True, "modelCheck": True})
            self.assertTrue(models.refresh_in_background())
            for _ in range(100):
                if started:
                    break
                time.sleep(0.02)
        self.assertEqual(started, [1])
