import json, os, subprocess, sys, tempfile, time, unittest
from tests import files as _f
from unittest import mock
from tests import fixture
from ctx import llm, models, paths, serve, settings

BOTH = {"claude": {"signed_in": True}, "codex": {"signed_in": True}, "api_key": False}
CLAUDE = {"claude": {"signed_in": True}, "codex": {"signed_in": False}, "api_key": False}
SPEED = {"haiku": ("claude-haiku-9", 1.2), "sonnet": ("claude-sonnet-9", 1.3), "opus": ("claude-opus-9", 5.1), "fable": ("claude-fable-9", 1.7),
         "gpt-sol": ("gpt-sol", 3.0), "gpt-luna": ("gpt-luna", 0.9)}
DEFAULTS = (llm.FAST, llm.CHEAP, llm.STRONG)


def fake_probe(speeds=SPEED, dead=()):
    def probe(plan, ask):
        if ask in dead or ask not in speeds:
            return {"ok": False, "error": "this plan cannot run it", "at": int(time.time())}
        return {"ok": True, "id": speeds[ask][0], "first": speeds[ask][1], "total": speeds[ask][1] + 0.1, "at": int(time.time())}
    return probe


class Base(unittest.TestCase):
    def setUp(self):
        self.clean()
        self.addCleanup(self.clean)
        self.home = tempfile.mkdtemp(prefix="ctx-userhome-")
        os.makedirs(os.path.join(self.home, ".codex"))
        with open(os.path.join(self.home, ".codex", "models_cache.json"), "w") as f:
            json.dump({"models": [{"slug": "gpt-luna", "display_name": "GPT Luna", "description": "small and fast", "visibility": "list", "priority": 2},
                                  {"slug": "gpt-sol", "display_name": "GPT Sol", "description": "the most capable", "visibility": "list", "priority": 1},
                                  {"slug": "gpt-hidden", "display_name": "Hidden", "visibility": "hide", "priority": 0}]}, f)
        p = mock.patch.dict(os.environ, {"HOME": self.home})
        p.start()
        self.addCleanup(p.stop)
        for k in ("CTX_FAST_MODEL", "CTX_CHEAP_MODEL", "CTX_STRONG_MODEL"):
            os.environ.pop(k, None)
        models._memo.update(at=0, stamp=None, roles={})

    def clean(self):
        for f in (models.FILE, settings.FILE):
            if os.path.exists(f):
                os.remove(f)
        models._memo.update(at=0, stamp=None, roles={})
        llm._tl.override = None

    def measure(self, status=CLAUDE, **kw):
        models.refresh(force=True, status=status, probe=fake_probe(**kw))
        return models.rows(status)


class Listing(Base):
    def test_tiers_come_from_the_family_and_nothing_is_guessed(self):
        self.assertEqual([models.tier(x) for x in ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "opus", "something-new")], ["fast", "balanced", "strongest", "strongest", ""])
        self.assertEqual([models.tier("x", d) for d in ("Fast and affordable model for easier tasks.", "Our most capable model for complex work.",
                                                        "Fast, go-to model for coding and everyday work.", "A model.")], ["fast", "strongest", "balanced", ""])
        self.assertEqual(models.tier("gpt-anything-sol"), "")              # a codex name alone says nothing: only its own description does

    def test_candidates_per_connected_plan(self):
        got = models.candidates(BOTH)
        self.assertEqual([c["ask"] for c in got if c["plan"] == "claude"], ["haiku", "sonnet", "opus", "fable"])
        self.assertEqual([c["ask"] for c in got if c["plan"] == "codex"], ["gpt-sol", "gpt-luna"])           # the cli's own list, in its order, hidden ones left out
        self.assertEqual(models.candidates({"claude": {"signed_in": False}, "codex": {"signed_in": False}, "api_key": False}), [])
        os.remove(os.path.join(self.home, ".codex", "models_cache.json"))
        self.assertEqual([c["ask"] for c in models.candidates(BOTH) if c["plan"] == "codex"], ["default"])
        self.assertEqual({c["plan"] for c in models.candidates({"claude": {"signed_in": False}, "codex": {"signed_in": False}, "api_key": True})}, {"api"})

    def test_each_model_is_tested_once_a_day(self):
        calls = []

        def probe(plan, ask):
            calls.append(ask)
            return fake_probe()(plan, ask)
        self.assertEqual(models.refresh(status=CLAUDE, probe=probe), 4)
        self.assertEqual(models.refresh(status=CLAUDE, probe=probe), 0)
        self.assertEqual(models.refresh(force=True, status=CLAUDE, probe=probe), 4)
        d = _f.load(models.FILE)
        d["probed"]["claude:opus"]["at"] -= 2 * 86400
        _f.dump(d, models.FILE)
        self.assertEqual(models.refresh(status=CLAUDE, probe=probe), 1)
        self.assertEqual(calls[-1], "opus")

    def test_rows_say_what_was_served_how_fast_and_what_cannot_run(self):
        rows = {r["name"]: r for r in self.measure(dead=("fable",))}
        self.assertEqual((rows["claude opus"]["id"], rows["claude opus"]["tier"], rows["claude opus"]["first_secs"], rows["claude opus"]["usage"]),
                         ("claude-opus-9", "strongest", 5.1, "uses more of your plan"))
        self.assertEqual(rows["claude haiku"]["usage"], "uses the least of your plan")
        self.assertEqual((rows["claude fable"]["ok"], rows["claude fable"]["why_not"]), (False, "this plan cannot run it"))
        self.assertTrue(all(set(r) >= {"id", "name", "plan", "tier", "ok"} for r in rows.values()))

    def test_before_anything_is_measured_rows_come_from_the_table_and_say_so(self):
        rows = models.rows(CLAUDE)
        self.assertEqual([(r["id"], r["measured"]) for r in rows], [("haiku", False), ("sonnet", False), ("opus", False), ("fable", False)])
        self.assertIn("not measured on this mac yet", models.recommend(rows)["routine"]["why"])

    def test_the_real_probe_reads_the_served_model_and_times_the_first_words(self):
        def stream(system, prompt, model, usage):
            usage["model"] = "claude-served-1"
            time.sleep(0.05)
            yield "ok"
        with mock.patch.object(llm, "_claude_stream", stream):
            got = models.probe("claude", "sonnet")
        self.assertEqual((got["ok"], got["id"]), (True, "claude-served-1"))
        self.assertGreaterEqual(got["first"], 0.04)

        def gone(system, prompt, model, usage):
            raise RuntimeError("claude: There's an issue with the selected model (x). It may not exist")
            yield
        with mock.patch.object(llm, "_claude_stream", gone):
            self.assertEqual(models.probe("claude", "x")["error"], "this plan cannot run it")


class Recommend(Base):
    def test_defaults_follow_the_table_and_the_speeds_measured_here(self):
        rec = models.recommend(self.measure())
        self.assertEqual({r: rec[r]["id"] for r in models.ROLES},
                         {"routine": "claude-sonnet-9", "analysis": "claude-opus-9", "first_parse": "claude-opus-9", "tools": "claude-haiku-9"})
        self.assertIn("1.3 s", rec["routine"]["why"])
        self.assertIn("uses more of your plan", rec["first_parse"]["why"])
        self.assertTrue(all(rec[r]["why"] for r in models.ROLES))

    def test_a_strongest_model_that_is_very_slow_here_gives_way(self):
        rec = models.recommend(self.measure(speeds=dict(SPEED, opus=("claude-opus-9", 42.0))))
        self.assertEqual(rec["analysis"]["id"], "claude-fable-9")

    def test_nothing_capable_is_quick_enough_for_everyday_answers(self):
        rec = models.recommend(self.measure(speeds=dict(SPEED, sonnet=("claude-sonnet-9", 9.0), opus=("claude-opus-9", 12.0), fable=("claude-fable-9", 11.0))))
        self.assertEqual(rec["routine"]["id"], "claude-haiku-9")
        self.assertIn("too slow for everyday answers", rec["routine"]["why"])

    def test_one_model_does_every_job(self):
        rec = models.recommend(self.measure(dead=("sonnet", "opus", "fable")))
        self.assertEqual({rec[r]["id"] for r in models.ROLES}, {"claude-haiku-9"})
        self.assertEqual(models.recommend([]), {})

    def test_presets(self):
        pre = models.presets(self.measure())
        self.assertEqual(set(pre), {"balanced", "best", "lean"})
        self.assertEqual(pre["balanced"]["roles"], models.recommend(models.rows(CLAUDE)))
        self.assertEqual((pre["best"]["roles"]["routine"]["id"], pre["best"]["roles"]["tools"]["id"]), ("claude-opus-9", "claude-sonnet-9"))
        self.assertEqual({pre["lean"]["roles"][r]["id"] for r in models.ROLES}, {"claude-haiku-9"})
        self.assertIn("shallower", pre["lean"]["about"])

    def test_a_mixed_house(self):
        rows = self.measure(status=BOTH)
        self.assertEqual({r["plan"] for r in rows}, {"claude", "codex"})
        rec = models.recommend(rows)
        self.assertEqual((rec["tools"]["id"], rec["tools"]["plan"]), ("gpt-luna", "codex"))          # the quickest fast model, whoever makes it
        settings.set_("model.routine=gpt-sol")
        who, notes = models.roles(rows)
        self.assertEqual((who["routine"]["plan"], who["routine"]["source"], who["analysis"]["plan"], notes), ("codex", "your choice", "claude", []))


class Roles(Base):
    def test_preset_then_a_choice_per_job(self):
        rows = self.measure()
        self.assertEqual(models.roles(rows)[0]["routine"]["source"], "preset balanced")
        self.assertTrue(settings.set_("preset=lean")["ok"])
        self.assertEqual({v["id"] for v in models.roles(rows)[0].values()}, {"claude-haiku-9"})
        self.assertTrue(settings.set_("model.analysis=fable")["ok"])                               # an alias or a full id both name it
        who, notes = models.roles(rows)
        self.assertEqual((who["analysis"]["id"], who["analysis"]["source"], who["routine"]["id"], notes), ("claude-fable-9", "your choice", "claude-haiku-9", []))
        self.assertTrue(settings.set_("model.analysis=preset")["ok"])
        self.assertEqual(models.roles(rows)[0]["analysis"]["id"], "claude-haiku-9")

    def test_settings_refuse_what_cannot_be(self):
        self.measure()
        for bad in ("preset=fastest", "model.routine=gpt-nope", "model.thinking=sonnet", "fallback_when_limited=maybe"):
            res = settings.set_(bad)
            self.assertFalse(res["ok"], bad)
        self.assertEqual((settings.load()["preset"], settings.load()["models"], settings.load()["fallback_when_limited"]), ("balanced", {}, "on"))

    def test_a_model_that_has_gone_falls_back_to_the_preset_with_a_note(self):
        rows = self.measure()
        settings.set_("model.routine=claude-fable-9")
        rows = self.measure(dead=("fable",))                             # tomorrow the plan no longer runs it
        who, notes = models.roles(rows)
        self.assertEqual(who["routine"]["id"], "claude-sonnet-9")
        self.assertIn("claude-fable-9, set for routine, is not a model your plans can run now", notes[0])

    def test_which_job_a_call_is(self):
        F, C, S = DEFAULTS
        for tag, model, want in (("answer", C, "routine"), ("answer", S, "analysis"), ("answer:plan", F, "tools"), ("answer:rerank", F, "tools"), ("answer:dig", F, "tools"),
                                 ("title", F, "tools"), ("today", F, "tools"), ("lens:tasks", C, "routine"), ("relate", C, "routine"), ("understand:core", S, "first_parse"),
                                 ("understand:merge", C, "first_parse"), ("understand:read", F, "first_read"), ("rank", S, "analysis"), ("test", F, None),
                                 ("answer", "some-model-the-caller-named", None)):
            self.assertEqual(models.role_of(tag, model, DEFAULTS), want, (tag, model))

    def test_nothing_changes_until_a_plan_has_been_measured(self):
        self.assertEqual(models.route("answer", llm.CHEAP, DEFAULTS), (None, llm.CHEAP, "routine"))
        self.assertEqual(models.route("answer:plan", llm.FAST, DEFAULTS), (None, llm.FAST, "tools"))

    def test_routes_once_measured(self):
        self.measure()
        self.assertEqual(models.route("answer", llm.CHEAP, DEFAULTS), ("claude", "sonnet", "routine"))
        self.assertEqual(models.route("answer", llm.STRONG, DEFAULTS), ("claude", "opus", "analysis"))
        self.assertEqual(models.route("answer:plan", llm.FAST, DEFAULTS), ("claude", "haiku", "tools"))
        self.assertEqual(models.route("answer", "pinned-by-the-caller", DEFAULTS), (None, "pinned-by-the-caller", None))

    def test_the_bulk_read_stays_on_the_fast_model_unless_asked_otherwise(self):
        self.measure()
        self.assertEqual(models.route("understand:read", llm.FAST, DEFAULTS)[1], "haiku")           # millions of tokens: not moved by the default preset
        self.assertEqual(models.route("understand:core", llm.STRONG, DEFAULTS)[1], "opus")
        settings.set_("preset=best")
        models._memo["at"] = 0
        self.assertEqual(models.route("understand:read", llm.FAST, DEFAULTS)[1], "opus")
        settings.set_("preset=balanced")
        settings.set_("model.first_parse=sonnet")
        models._memo["at"] = 0
        self.assertEqual(models.route("understand:read", llm.FAST, DEFAULTS)[1], "sonnet")

    def test_one_answer_can_name_its_model(self):
        self.measure()
        self.assertEqual(models.route("answer", llm.CHEAP, DEFAULTS, override="claude-fable-9"), ("claude", "fable", "routine"))
        self.assertEqual(models.route("answer:plan", llm.FAST, DEFAULTS, override="claude-fable-9")[1], "haiku")     # the search is still steered by the tools model
        self.assertEqual(models.route("answer", llm.CHEAP, DEFAULTS, override="retired-model")[1], "sonnet")
        self.assertIn("retired-model is not a model your plans can run now", _f.load(models.FILE)["notes"][-1]["text"])


class Calls(Base):
    """llm.ask and llm.stream with made-up backends: which plan and model each call really reaches."""

    def setUp(self):
        super().setUp()
        self.seen, self.fail = [], {}
        self.ledger = _f.read(paths.LEDGER) if os.path.exists(paths.LEDGER) else None

        def backend(plan):
            def call(system, prompt, model):
                self.seen.append((plan, model))
                if (plan, model) in self.fail:
                    raise RuntimeError(self.fail[(plan, model)])
                return f"{plan}:{model}", 1, 1, 0.0
            return call

        def streamer(plan):
            def call(system, prompt, model, usage):
                self.seen.append((plan, model))
                if (plan, model) in self.fail:
                    raise RuntimeError(self.fail[(plan, model)])
                yield f"{plan}:{model}"
            return call
        ps = [mock.patch.object(llm, "_claude", backend("claude")), mock.patch.object(llm, "_codex", backend("codex")), mock.patch.object(llm, "_backend", lambda: "claude"),
              mock.patch.object(llm, "_claude_stream", streamer("claude")), mock.patch.object(llm, "_codex_stream", streamer("codex")), mock.patch("time.sleep", lambda s: None)]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.restore)

    def restore(self):
        if self.ledger is None:
            if os.path.exists(paths.LEDGER):
                os.remove(paths.LEDGER)
        else:
            _f.write(self.ledger, paths.LEDGER, "w")

    def test_unmeasured_plans_call_as_before(self):
        self.assertEqual(llm.ask("s", "p", llm.CHEAP, tag="answer"), "claude:" + llm.CHEAP)
        self.assertEqual("".join(llm.stream("s", "p", llm.STRONG, tag="answer")), "claude:" + llm.STRONG)

    def test_each_job_reaches_its_model(self):
        self.measure(status=BOTH)
        settings.set_("model.routine=gpt-sol")
        models._memo["at"] = 0
        self.assertEqual(llm.ask("s", "p", llm.CHEAP, tag="answer"), "codex:gpt-sol")               # another plan for one job
        self.assertEqual(llm.ask("s", "p", llm.STRONG, tag="answer"), "claude:opus")
        self.assertEqual("".join(llm.stream("s", "p", llm.FAST, tag="answer:plan")), "codex:gpt-luna")
        self.assertEqual(json.loads(_f.read(paths.LEDGER).splitlines()[-2])["job"], "analysis")

    def test_a_size_pinned_in_env_is_left_alone(self):
        self.measure()
        with mock.patch.dict(os.environ, {"CTX_CHEAP_MODEL": llm.CHEAP}):
            self.assertEqual(llm.ask("s", "p", llm.CHEAP, tag="answer"), "claude:" + llm.CHEAP)

    def test_a_retired_model_never_fails_an_answer(self):
        self.measure()
        self.fail[("claude", "sonnet")] = "claude: There's an issue with the selected model (sonnet). It may not exist or you may not have access to it."
        self.assertEqual(llm.ask("s", "p", llm.CHEAP, tag="answer"), "claude:" + llm.CHEAP)
        self.assertEqual("".join(llm.stream("s", "p", llm.CHEAP, tag="answer")), "claude:" + llm.CHEAP)
        self.assertIn("could not be run on your claude plan", _f.load(models.FILE)["notes"][-1]["text"])

    def test_a_plan_at_its_limit_drops_everyday_answers_to_the_lean_model(self):
        self.measure()
        self.fail[("claude", "sonnet")] = "claude: You've hit your usage limit. Your limit resets 3pm."
        self.assertEqual(llm.ask("s", "p", llm.CHEAP, tag="answer"), "claude:haiku")
        d = _f.load(models.FILE)
        self.assertGreater(d["limited"]["claude"]["until"], time.time())
        self.assertIn("resets 3pm", d["limited"]["claude"]["why"])
        self.seen.clear()
        models._memo["at"] = 0
        self.assertEqual(llm.ask("s", "p", llm.CHEAP, tag="answer"), "claude:haiku")                # for the rest of the window: straight to lean
        self.assertEqual(self.seen, [("claude", "haiku")])
        who, notes = models.roles()
        self.assertEqual(who["routine"]["source"], "plan limit")
        self.assertIn("hit its limit", notes[0])

    def test_with_another_plan_connected_the_limit_moves_the_answer_there(self):
        self.measure(status=BOTH)
        self.fail[("claude", "sonnet")] = "claude: usage limit reached"
        self.assertEqual(llm.ask("s", "p", llm.CHEAP, tag="answer"), "codex:gpt-luna")

    def test_the_owner_can_forbid_the_drop_and_other_jobs_never_drop(self):
        self.measure()
        self.fail[("claude", "sonnet")] = self.fail[("claude", "opus")] = "claude: usage limit reached"
        with self.assertRaisesRegex(RuntimeError, "usage limit"):
            llm.ask("s", "p", llm.STRONG, tag="answer")                  # analysis is not quietly given to a weaker model
        settings.set_("fallback_when_limited=off")
        _f.dump(dict(_f.load(models.FILE), limited={}), models.FILE)
        models._memo["at"] = 0
        with self.assertRaisesRegex(RuntimeError, "usage limit"):
            llm.ask("s", "p", llm.CHEAP, tag="answer")

    def test_limit_messages(self):
        self.assertEqual(models.limit_text(RuntimeError("claude: something else broke")), "")
        self.assertEqual(models.limit_text(RuntimeError("usage limit reached. resets at 5:30pm (Pacific/Auckland)")), "your plan's limit was reached; it resets at 5:30pm (Pacific/Auckland).")
        self.assertEqual(models.limit_text(RuntimeError("429 Too Many Requests")), "your plan's limit was reached.")
        now = time.mktime((2026, 11, 20, 14, 0, 0, 0, 0, -1))
        self.assertEqual(time.strftime("%d %H:%M", time.localtime(models.limited("claude", "limit reached, resets 5:30pm", now))), "20 17:30")
        self.assertEqual(time.strftime("%d %H:%M", time.localtime(models.limited("claude", "limit reached, resets 9am", now))), "21 09:00")
        self.assertEqual(round(models.limited("claude", "rate limit", now) - now), 3600)

    def test_the_composers_pick_is_for_one_answer(self):
        self.measure()
        with llm.use_model("claude-fable-9"):
            self.assertEqual(llm.ask("s", "p", llm.CHEAP, tag="answer"), "claude:fable")
            self.assertEqual(llm.ask("s", "p", llm.FAST, tag="answer:plan"), "claude:haiku")
        self.assertEqual(llm.ask("s", "p", llm.CHEAP, tag="answer"), "claude:sonnet")

    def test_codex_is_told_which_model(self):
        got = {}

        def run(cmd, **kw):
            got["cmd"] = cmd
            _f.write("ok", cmd[cmd.index("-o") + 1], "w")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        mock.patch.stopall()                                             # the real _codex, with only the program it would run made up
        with mock.patch.object(llm, "_codex_bin", lambda: "/fake/codex"), mock.patch.object(llm.subprocess, "run", run), \
                mock.patch.object(llm, "learn_codex_features", lambda path: None), mock.patch.object(llm, "codex_ready", lambda path: (["--ignore-user-config", "--ignore-rules", "--disable", "shell_tool", "--disable", "unified_exec"], "")):
            llm._codex("s", "p", "gpt-sol")
            self.assertEqual(got["cmd"][got["cmd"].index("-m") + 1], "gpt-sol")
            llm._codex("s", "p", llm.CHEAP)                              # a claude size means "codex's own default"
            self.assertNotIn("-m", got["cmd"])


class Surfaces(Base):
    def test_report_for_the_settings_page(self):
        self.measure()
        rep = models.report(CLAUDE)
        self.assertEqual(set(rep) >= {"models", "roles", "preset", "presets", "recommended", "notes", "fallback_when_limited", "limited", "measured_at", "lean_costs"}, True)
        by = {m["name"]: m for m in rep["models"]}
        self.assertEqual((by["claude sonnet"]["recommended_for"], by["claude opus"]["recommended_for"], by["claude haiku"]["recommended_for"], by["claude fable"]["recommended_for"]),
                         (["routine"], ["analysis", "first_parse"], ["tools"], []))
        self.assertEqual((rep["preset"], rep["fallback_when_limited"], set(rep["roles"])), ("balanced", True, set(models.ROLES)))
        json.dumps(rep)

    def test_doctor_line(self):
        self.measure()
        self.assertEqual(models.line(CLAUDE), "balanced preset: routine claude sonnet, analysis claude opus, first_parse claude opus, tools claude haiku")
        self.assertEqual(models.line({"claude": {"signed_in": False}, "codex": {"signed_in": False}, "api_key": False}), "no model signed in")

    def test_bench_runs_only_when_asked_and_needs_the_eval(self):
        self.measure()
        real = os.path.exists
        with mock.patch("os.path.exists", lambda p: False if str(p).endswith("eval_answers.py") else real(p)):
            self.assertIn("no answer eval yet", models.bench()["error"])
        ran = []

        def run(cmd, **kw):
            ran.append((cmd, kw["env"]["CTX_ANSWER_MODEL"]))
            table = "config                   n  right partly missed wrong bluff  cite ok    med    p90\n" \
                    "fixed@bench_x           20    90%     5%     5%    0%    0%      95%    6.0   11.2     3     0    9000     400\n   by kind (right/n): fact 9/10\n"
            return subprocess.CompletedProcess(cmd, 0, table if kw["env"]["CTX_ANSWER_MODEL"] != "haiku" else "nothing graded\n", "")
        with mock.patch("os.path.exists", lambda p: True if str(p).endswith("eval_answers.py") else real(p)):
            got = models.bench(limit=20, run=run)
        self.assertEqual([m for _, m in ran], ["haiku", "sonnet", "opus", "fable"])
        self.assertTrue(all("--live" in c and c[c.index("--slice") + 1] == "20" for c, _ in ran))
        self.assertEqual(got["claude:claude-sonnet-9"], dict(got["claude:claude-sonnet-9"], accuracy=90, bluffed=0, secs=6.0, questions=20))
        self.assertIn("error", got["claude:claude-haiku-9"])
        self.assertIn("90% right on the eval", models.recommend(models.rows(CLAUDE))["routine"]["why"])
        self.assertNotIn("bench(", _f.read(os.path.join(fixture.REPO, "ctx", "schedule.py")) + _f.read(os.path.join(fixture.REPO, "ctx", "serve.py")))      # never by itself

    def test_a_whole_run_can_be_pinned_to_one_answer_model(self):
        self.measure()
        with mock.patch.dict(os.environ, {"CTX_ANSWER_MODEL": "fable"}):
            self.assertEqual(llm._route(llm.CHEAP, "answer")[1], "fable")
            self.assertEqual(llm._route(llm.FAST, "answer:plan")[1], "haiku")

    def test_serve_models_and_a_model_for_one_answer(self):
        from tests.test_serve import Lines
        from ctx import answer
        self.measure()
        out = Lines()
        srv = serve.Server(out)
        self.addCleanup(lambda: srv.pool.shutdown(wait=True))
        with mock.patch.object(models, "report", lambda: {"preset": "balanced"}):
            srv.handle(json.dumps({"id": 1, "cmd": "models"}))
            self.assertEqual(out.wait(lambda e: e.get("id") == 1 and "result" in e)["result"], {"preset": "balanced"})
        seen = []
        with mock.patch.object(answer, "answer", lambda q, history=None, dig=False, scope=None: seen.append(getattr(llm._tl, "override", None)) or {"answer": "x"}):
            srv.handle(json.dumps({"id": 2, "cmd": "answer", "q": "q", "model": "claude-fable-9"}))
            out.wait(lambda e: e.get("id") == 2 and e.get("end"))
            for n in range(3, 12):                                       # the same worker threads again: the pick must not linger
                srv.handle(json.dumps({"id": n, "cmd": "answer", "q": "q"}))
            for n in range(3, 12):
                out.wait(lambda e, n=n: e.get("id") == n and e.get("end"))
        self.assertEqual(seen[0], "claude-fable-9")
        self.assertEqual(set(seen[1:]), {None})

    def test_command_line(self):
        self.measure()
        env = dict(os.environ, CTX_HOME=fixture.HOME, PYTHONPATH=fixture.REPO, CTX_MODEL="none-of-them")
        r = subprocess.run([sys.executable, "-m", "ctx", "settings", "--set", "preset=lean"], capture_output=True, text=True, env=env, cwd=fixture.REPO, timeout=60)
        self.assertEqual((r.returncode, json.loads(r.stdout)["settings"]["preset"]), (0, "lean"))
        r = subprocess.run([sys.executable, "-m", "ctx", "settings", "--set", "model.tools=sonnet"], capture_output=True, text=True, env=env, cwd=fixture.REPO, timeout=60)
        self.assertEqual(json.loads(r.stdout)["settings"]["models"], {"tools": "sonnet"})
        r = subprocess.run([sys.executable, "-m", "ctx", "models", "--help"], capture_output=True, text=True, env=env, cwd=fixture.REPO, timeout=60)
        self.assertIn("which model does which job", r.stdout)


if __name__ == "__main__":
    unittest.main()
