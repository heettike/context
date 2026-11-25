import json, os, subprocess, sys, tempfile, time, unittest
from tests import files as _f
from unittest import mock
from tests import fixture
from ctx import llm, mcp, paths, schedule, settings


def clear():
    for f in (settings.FILE, os.path.join(paths.HOME, "model.json")):
        if os.path.exists(f):
            os.remove(f)


class Values(unittest.TestCase):
    def setUp(self):
        clear()
        self.addCleanup(clear)

    def test_defaults(self):
        self.assertEqual(settings.load(), settings.DEFAULTS)
        self.assertEqual(set(settings.ABOUT), set(settings.DEFAULTS))

    def test_good_values(self):
        for pair, want in (("fast_minutes=30", 30), ("daily_hour=7", 7), ("daily_hour=any", "any"), ("weekly_day=Sunday", "sun"), ("weekly_day=tue", "tue"),
                           ("read_through=off", "off"), ("reread_weekly=true", "on"), ("backend=codex", "codex"), (" Backend = AUTO ", "auto")):
            res = settings.set_(pair)
            key = pair.split("=")[0].strip().lower()
            self.assertEqual((res["ok"], res["error"], res["settings"][key]), (True, "", want), pair)
            self.assertEqual(settings.load()[key], want)

    def test_remote_settings(self):
        self.assertNotIn("page", settings.load()["remote_tools"])
        self.assertEqual(settings.set_("remote_tools=search, about_me,search")["settings"]["remote_tools"], ["search", "about_me"])
        for bad in ("remote_tools=", "remote_tools=search,delete_everything", "remote_autostart=sometimes"):
            self.assertFalse(settings.set_(bad)["ok"], bad)
        self.assertEqual(settings.load()["remote_tools"], ["search", "about_me"])
        self.assertEqual(settings.load()["remote_autostart"], "off")

    def test_bad_values_change_nothing(self):
        settings.set_("fast_minutes=30")
        for pair in ("fast_minutes=2", "fast_minutes=9999", "fast_minutes=ten", "fast_minutes=-5", "daily_hour=24", "daily_hour=noon", "weekly_day=someday",
                     "weekly_day=sunny", "read_through=maybe", "backend=gpt", "nope=1", "fast_minutes", "", "=5"):
            res = settings.set_(pair)
            self.assertFalse(res["ok"], pair)
            self.assertTrue(res["error"])
        self.assertEqual(settings.load(), dict(settings.DEFAULTS, fast_minutes=30))

    def test_a_damaged_file_falls_back_to_defaults_value_by_value(self):
        for text in ("{nope", "[1]", json.dumps({"fast_minutes": 9999, "daily_hour": 6, "junk": 1, "backend": 5})):
            with open(settings.FILE, "w") as f:
                f.write(text)
            got = settings.load()
            self.assertEqual(got["fast_minutes"], 15)
            self.assertEqual(set(got), set(settings.DEFAULTS))
        self.assertEqual(got["daily_hour"], 6)

    def test_choosing_a_backend_forgets_the_remembered_one(self):
        memo = os.path.join(paths.HOME, "model.json")
        with open(memo, "w") as f:
            json.dump({"using": "claude", "at": time.time()}, f)
        settings.set_("fast_minutes=20")
        self.assertTrue(os.path.exists(memo))
        settings.set_("backend=codex")
        self.assertFalse(os.path.exists(memo))

    def test_command_line(self):
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, CTX_HOME=home, PYTHONPATH=fixture.REPO)
            run = lambda *a: subprocess.run([sys.executable, "-m", "ctx", "settings", *a], capture_output=True, text=True, env=env, cwd=fixture.REPO, timeout=60)
            ok = run("--set", "daily_hour=6", "weekly_day=mon")
            self.assertEqual(ok.returncode, 0, ok.stderr[-300:])
            self.assertEqual((json.loads(ok.stdout)["settings"]["daily_hour"], json.loads(ok.stdout)["settings"]["weekly_day"]), (6, "mon"))
            bad = run("--set", "daily_hour=99")
            self.assertEqual(bad.returncode, 1)
            self.assertFalse(json.loads(bad.stdout)["ok"])
            self.assertEqual(run("--set").returncode, 1)
            self.assertEqual(_f.load(os.path.join(home, "settings.json"))["daily_hour"], 6)


class Honoured(unittest.TestCase):
    def setUp(self):
        clear()
        self.addCleanup(clear)

    def at(self, hour, day=18):          # a wednesday
        return time.mktime((2026, 11, day, hour, 0, 0, 0, 0, -1))

    def test_fast_minutes(self):
        now = self.at(12)
        self.assertEqual(schedule.due_in("fast", now, now - 16 * 60, settings.load()), (True, 0))
        settings.set_("fast_minutes=60")
        self.assertEqual(schedule.due_in("fast", now, now - 16 * 60, settings.load()), (False, 44 * 60))
        self.assertEqual(schedule.due_in("fast", now, now - 61 * 60, settings.load())[0], True)

    def test_daily_any_hour_is_every_24_hours(self):
        now = self.at(12)
        self.assertEqual(schedule.due_in("daily", now, now - 23 * 3600, settings.load()), (False, 3600))
        self.assertTrue(schedule.due_in("daily", now, now - 25 * 3600, settings.load())[0])

    def test_daily_hour(self):
        settings.set_("daily_hour=7")
        cfg = settings.load()
        self.assertEqual(schedule.due_in("daily", self.at(6), self.at(8, day=17), cfg), (False, 3600))        # ran yesterday after 7, today's 7 not here yet
        self.assertEqual(schedule.due_in("daily", self.at(8), self.at(8, day=17), cfg), (True, 0))            # 7 has passed, not yet run today
        self.assertEqual(schedule.due_in("daily", self.at(9), self.at(8), cfg), (False, 22 * 3600))           # ran today
        self.assertTrue(schedule.due_in("daily", self.at(6), self.at(6, day=17), cfg)[0])                     # missed yesterday's 7
        self.assertTrue(schedule.due_in("daily", self.at(8), 0, cfg)[0])

    def test_weekly_day(self):
        self.assertTrue(schedule.day_ok(self.at(12), settings.load()))
        settings.set_("weekly_day=wed")
        self.assertTrue(schedule.day_ok(self.at(12), settings.load()))
        settings.set_("weekly_day=thu")
        self.assertFalse(schedule.day_ok(self.at(12), settings.load()))
        self.assertTrue(schedule.day_ok(self.at(12, day=19), settings.load()))

    def test_plan_uses_them_and_the_weekly_reread_is_off_until_asked_for(self):
        now = self.at(12)
        with mock.patch.object(schedule, "_load", lambda: {"fast": now - 20 * 60, "daily": now - 3600}):
            p = schedule.plan(now)
            self.assertTrue(p["fast"]["due"])
            self.assertEqual(p["read_through"], {"last": 0, "enabled": False, "due": False})
            settings.set_("fast_minutes=30")
            settings.set_("reread_weekly=on")
            p = schedule.plan(now)
            self.assertEqual((p["fast"]["due"], p["fast"]["next_in"]), (False, 600))
            self.assertEqual((p["read_through"]["enabled"], p["read_through"]["due"]), (True, True))
            settings.set_("read_through=off")
            self.assertEqual(schedule.plan(now)["read_through"]["due"], False)

    def test_the_model_backend(self):
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(llm, "_claude_bin", lambda: None), mock.patch.object(llm, "_codex_bin", lambda: None):
            os.environ.pop("CTX_MODEL", None)
            self.assertNotIn("codex is set", llm.status()["fix"])
            settings.set_("backend=codex")
            st = llm.status()
            self.assertEqual(st["using"], "none")
            self.assertIn("codex", st["fix"])
            os.environ["CTX_MODEL"] = "claude"                       # the environment still wins
            self.assertIn("claude", llm.status()["fix"])

    def test_the_ledger_keeps_the_time_of_each_call(self):
        keep = _f.read(paths.LEDGER) if os.path.exists(paths.LEDGER) else None
        try:
            llm._log({"tag": "t", "in": 1, "out": 2, "usd": 0.0})
            row = json.loads(_f.read(paths.LEDGER).splitlines()[-1])
            self.assertLess(abs(row["at"] - time.time()), 5)
        finally:
            if keep is None:
                os.remove(paths.LEDGER)
            else:
                _f.write(keep, paths.LEDGER, "w")


class Report(unittest.TestCase):
    def setUp(self):
        clear()
        self.addCleanup(clear)

    def test_usage_by_day_and_tag(self):
        now = time.mktime((2026, 11, 18, 15, 0, 0, 0, 0, -1))
        rows = [{"tag": "answer:plan", "in": 10, "out": 1, "usd": 0.0, "at": now - 3600}, {"tag": "answer", "in": 100, "out": 20, "usd": 0.0, "at": now - 7200},
                {"tag": "coach", "in": 5, "out": 5, "usd": 0.0, "at": now - 3 * 86400}, {"tag": "old", "in": 7, "out": 7, "usd": 0.0},
                {"tag": "lens:x", "in": 1, "out": 1, "usd": 0.0, "at": now - 30 * 86400}, {"tag": "answer", "error": "boom", "at": now}]
        with open(paths.LEDGER, "w") as f:
            f.write("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
        self.addCleanup(os.remove, paths.LEDGER)
        u = settings.usage(now)
        self.assertEqual(u["today"], {"answer": {"calls": 2, "tokens_in": 110, "tokens_out": 21}})
        self.assertEqual(set(u["week"]), {"answer", "coach"})
        self.assertEqual(u["undated"], {"old": {"calls": 1, "tokens_in": 7, "tokens_out": 7}})
        self.assertEqual((u["failed"], u["usd"]), (1, 0.0))
        self.assertIn("$0", u["cost"])

    def test_keys_are_names_only(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write('# c\nTELEGRAM_API_ID=123456\nexport TELEGRAM_API_HASH="s3cr3tvalue"\nANTHROPIC_API_KEY=\nCTX_X_HANDLE=someone\nbroken line\n')
        self.addCleanup(os.remove, f.name)
        k = settings.keys(f.name)
        self.assertEqual(k["present"], ["CTX_X_HANDLE", "TELEGRAM_API_HASH", "TELEGRAM_API_ID"])
        self.assertIn("ANTHROPIC_API_KEY", k["not_set"])
        out = json.dumps(k)
        for secret in ("123456", "s3cr3tvalue", "someone"):
            self.assertNotIn(secret, out)
        self.assertNotRegex(out, r"\d")                                   # no values and no lengths
        self.assertEqual(settings.keys("/nonexistent/.env")["present"], [])

    def test_archive(self):
        a = settings.archive()
        self.assertEqual(a["rows"]["messages"], len(fixture.rows()["messages.jsonl"]) + 1)
        self.assertGreater(a["bytes"], 100_000)
        self.assertGreater(a["last_collect"], 0)
        self.assertNotIn(os.path.expanduser("~") + "/", a["folder"] if a["folder"].startswith("~") else "")

    def test_the_whole_page(self):
        fake = {"using": "claude", "plan": "your claude plan", "fix": "", "api_key": False,
                "claude": {"installed": True, "signed_in": True, "path": "/x", "fix": ""}, "codex": {"installed": False, "signed_in": False, "path": "", "fix": "y"}}
        with mock.patch.object(llm, "status", lambda: fake), mock.patch.object(mcp, "status", lambda: [{"id": "cursor", "state": "registered"}]), \
                mock.patch.object(llm, "ask", side_effect=AssertionError("no model call")), mock.patch.object(llm, "ask_json", side_effect=AssertionError("no model call")):
            out = settings.report(fast=True)
        self.assertEqual(set(out), {"plan", "sync", "mcp", "archive", "read_through", "usage", "keys", "settings", "permissions", "remote", "search", "models"})
        self.assertEqual((out["remote"]["running"], out["remote"]["autostart"]), (False, False))
        self.assertEqual((out["plan"]["using"], out["plan"]["signed_in"], out["plan"]["backend_setting"]), ("claude", True, "auto"))
        self.assertEqual(set(out["plan"]["models"]), {"fast", "cheap", "strong"})
        self.assertNotIn("path", out["plan"]["claude"])
        self.assertEqual(set(out["sync"]) >= {"fast", "daily", "weekly", "watching", "settings"}, True)
        self.assertEqual(out["mcp"], [{"id": "cursor", "state": "registered"}])
        self.assertEqual((out["read_through"]["core"], out["read_through"]["enabled"]), (True, True))
        self.assertEqual(out["settings"]["values"], settings.DEFAULTS)
        json.dumps(out)

    def test_one_part_failing_does_not_lose_the_page(self):
        def boom():
            raise RuntimeError("/Users/someone/secret")
        with mock.patch.object(llm, "status", boom), mock.patch.object(mcp, "status", lambda: []):
            out = settings.report(fast=True)
        self.assertEqual(out["plan"], {"error": "could not read this part (RuntimeError)"})
        self.assertIn("rows", out["archive"])


if __name__ == "__main__":
    unittest.main()
