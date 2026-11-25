"""The model-driven answer path, with a made-up CLI: no model is called."""
import io, json, os, time, unittest
from unittest import mock
from tests import fixture
from ctx import agent, answer, guard, mcp, tools

fixture.index()


def ev(kind, **more):
    return json.dumps({"type": "stream_event", "event": dict(type=kind, **more)}) + "\n"


def text(s):
    return ev("content_block_delta", delta={"type": "text_delta", "text": s})


class FakeCLI:
    """Stands in for the CLI process: plays a script of event lines, and runs the tool calls in it through tools.call
    with the environment the real MCP child would get, so the log of rows is real."""

    def __init__(self, script):
        self.script, self.cmd = script, None

    def __call__(self, cmd, **kw):
        self.cmd = cmd
        with open(cmd[cmd.index("--mcp-config") + 1]) as f:          # files, as the real CLI is handed them: gone when the run ends
            self.config = json.load(f)
        with open(cmd[cmd.index("--system-prompt-file") + 1]) as f:
            self.system = f.read()
        self.files = [cmd[cmd.index(flag) + 1] for flag in ("--mcp-config", "--system-prompt-file")]
        self.modes = [os.stat(p).st_mode & 0o777 for p in self.files]
        cfg = self.config["mcpServers"]["ctx"]
        self.env = cfg["env"]
        tools._calls[0] = 0                                  # the real child is a new process: its count of calls starts at zero, whatever other tests called
        lines = []
        for item in self.script:
            if isinstance(item, tuple):                      # a tool call: (id, name, args)
                tid, name, args = item[:3]
                if len(item) == 3:                           # a fourth item: the call comes in a message already begun
                    lines.append(ev("message_start", message={"usage": {"input_tokens": 100}}))
                lines.append(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": "mcp__ctx__" + name, "input": args}]}}) + "\n")
                lines.append(ev("message_delta", delta={"stop_reason": "tool_use"}, usage={"output_tokens": 10}))
                lines.append(("call", tid, name, args))
            else:
                lines.append(item)
        me = self

        class P:
            pid, stdin = 0, io.StringIO()

            def poll(self):
                return 0

            def kill(self):
                pass

            def wait(self, timeout=None):
                return 0

            @property
            def stdout(self):
                class Out:
                    def __iter__(s):
                        for l in lines:
                            if isinstance(l, tuple):
                                with mock.patch.dict(os.environ, {k: v for k, v in me.env.items() if k.startswith("CTX_AGENT")}):
                                    out = tools.call(l[2], l[3])
                                yield json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": l[1], "content": out}]}}) + "\n"
                            else:
                                yield l

                    def close(s):
                        pass
                return Out()
        P.stdin.close = lambda: None
        self.p = P()
        return self.p


def last(final):
    return [ev("message_start", message={"usage": {"input_tokens": 200}}), text(final),
            ev("message_delta", delta={"stop_reason": "end_turn"}, usage={"output_tokens": 30}), ev("message_stop")]


class Loop(unittest.TestCase):
    def run_it(self, script, q="where is the harbour lease", **kw):
        events = []
        cli = FakeCLI(script)
        with mock.patch("ctx.llm._claude_bin", return_value="/made/up/claude"), mock.patch("ctx.llm._log"), \
                mock.patch.object(agent, "DIR", os.path.join(fixture.HOME, "cache", "agent")):
            reply = agent.run(q, emit=events.append, start=cli, model="made-up-model", **kw)
        return reply, events, cli

    def test_a_message_with_a_unicode_line_break_keeps_its_rows(self):
        row = {"id": "U1", "src": "whatsapp", "ts": "2024-01-01T10:00:00", "thread": "made up", "who": "me", "text": "first part\u2028second part\x85third", "url": "", "sender": ""}
        with mock.patch.object(tools, "run", return_value=("[U1] first part", [row])):
            reply, events, cli = self.run_it([("t1", "search", {"query": "odd breaks"})] + last('it is there [U1]\n===\n{"strength": "strong", "kind": "lookup"}'))
        self.assertEqual([c["id"] for c in reply["cites"]], ["U1"])
        self.assertEqual([e["step"]["found"] for e in events if "step" in e and "found" in e["step"] and e["step"]["tool"] == "search"], [1])

    def test_the_question_reaches_the_cli_before_the_first_look_runs(self):
        seen, real = [], agent.first_look
        cli = FakeCLI(last("nothing.\n===\n{}"))

        def look(question, scope=None, whole=0):
            seen.append(cli.p.stdin.getvalue())         # what the CLI has been sent by the time the local search starts
            return real(question, scope, whole)
        with mock.patch("ctx.llm._claude_bin", return_value="/made/up/claude"), mock.patch("ctx.llm._log"), mock.patch.object(agent, "first_look", look), \
                mock.patch.object(agent, "DIR", os.path.join(fixture.HOME, "cache", "agent")):
            agent.run("where is the harbour lease", start=cli, model="made-up-model")
        self.assertIn("# Question\nwhere is the harbour lease", seen[0])
        self.assertIn("# First look", cli.p.stdin.getvalue())

    def test_gathering_ends_when_it_searches_past_its_budget(self):
        script = [("t1", "search", {"query": "harbour lease"}), ("t2", "search", {"query": "lease clause"}), ("t3", "search", {"query": "harbour"})] + last("- a claim [V700]")
        with mock.patch.dict(agent.MODES, {"gather": {"calls": 1, "secs": 60, "kill": 60}}), mock.patch.object(tools, "_calls", [0]):
            got, events, cli = self.run_it(script, q="how has the harbour lease changed over the years", gather=True, brief=("", []))
        self.assertEqual((got["claims"], got["cut"]), ("", True))               # the second call was told the budget is used up; the third ended the run
        self.assertEqual(got["usage"]["tools"], 2)
        self.assertIn("V700", got["by_id"])                                      # what it read is kept for the writer

    def test_a_quick_run_that_keeps_searching_is_answered_by_code(self):
        script = [("t%d" % n, "search", {"query": "harbour lease %d" % n}) for n in range(1, 7)] + last("never reached [V700]")
        with mock.patch.dict(agent.MODES, {"quick": {"calls": 1, "secs": 60, "kill": 60}}), mock.patch.object(tools, "_calls", [0]):
            reply, events, cli = self.run_it(script)
        self.assertEqual((reply["path"], reply["strength"], reply["found_it"], reply["error"]), ("cut", "weak", False, ""))
        self.assertIn("ran out of time", reply["answer"])
        self.assertTrue(reply["cites"])                                          # the closest messages of the first look, so there is something to open
        self.assertNotIn("never reached", reply["answer"])
        self.assertEqual(reply["usage"]["tools"], 4)                             # one in budget, one told to stop, two rounds of grace, then ended
        self.assertEqual(events[-1], {"done": reply})

    def test_no_time_left_starts_no_run(self):
        cli = FakeCLI(last("never"))
        with mock.patch("ctx.llm._claude_bin", return_value="/made/up/claude"), mock.patch("ctx.llm._log"):
            reply = agent.run("where is the harbour lease", start=cli, model="made-up-model", deadline=time.time() + 3)
        self.assertIsNone(cli.cmd)
        self.assertEqual((reply["path"], reply["strength"]), ("cut", "weak"))

    def test_the_tools_stop_in_time_for_the_answer_to_be_written(self):
        _, _, cli = self.run_it(last("nothing.\n===\n{}"), deadline=time.time() + 30)
        self.assertLessEqual(float(cli.env["CTX_AGENT_UNTIL"]), time.time() + 30 - agent.WRITE_ROOM + 0.5)

    def test_an_analysis_is_handed_the_wikis_paragraphs(self):
        row = {"id": "WK1", "src": "whatsapp", "ts": "2024-01-01T10:00:00", "thread": "made up", "who": "me", "text": "the lease was signed in june", "url": "", "sender": ""}
        with mock.patch.object(agent, "_wiki_brief", return_value=("## the harbour lease (projects/harbour-lease)\nhe signed the lease in june [WK1]", [row])):
            got, events, cli = self.run_it(last("- he signed in june [WK1]"), q="how has the harbour lease changed over the years", gather=True)
        self.assertIn("# From the wiki", cli.p.stdin.getvalue())
        self.assertIn("WK1", got["by_id"])                                       # the messages its sentences rest on count as shown

    def test_a_tool_call_then_an_answer(self):
        reply, events, cli = self.run_it([("t1", "search", {"query": "harbour lease"})] +
                                         last('the lease clause came up twice [V700] and again [V2200]. see https://made.up/x and [NOPE1]\n===\n{"strength": "strong", "kind": "lookup"}'))
        self.assertEqual(reply["error"], "")
        self.assertIn("[1]", reply["answer"])
        self.assertIn("[2]", reply["answer"])
        self.assertNotIn("V700", reply["answer"])
        self.assertNotIn("NOPE1", reply["answer"])                     # a mark for a row no tool showed is dropped
        self.assertNotIn("===", reply["answer"])
        self.assertEqual([c["id"] for c in reply["cites"]], ["V700", "V2200"])
        self.assertEqual(reply["links"], [])                            # a url no row holds is not a link
        self.assertEqual(reply["strength"], "strong")
        for k in ("answer", "cites", "links", "threads", "maybe", "strength", "searched", "found", "secs", "error", "steps", "usage"):
            self.assertIn(k, reply)
        steps = [e["step"] for e in events if "step" in e and e["step"]["tool"] == "search"]
        self.assertEqual(steps[0]["args"], {"query": "harbour lease"})
        self.assertNotIn("found", steps[0])
        self.assertEqual(steps[1]["found"], 2)
        self.assertEqual("".join(e["delta"] for e in events if "delta" in e), reply["answer"])
        self.assertEqual([e["cite"]["n"] for e in events if "cite" in e], [1, 2])
        self.assertEqual(events[-1], {"done": reply})
        self.assertEqual([(c["who"], c["sender"]) for c in reply["cites"]], [("them", "Ravi Anand"), ("them", "Ravi Anand")])     # who wrote it, by name
        self.assertEqual(reply["usage"]["calls"], 2)
        self.assertEqual(reply["usage"]["tools"], 1)

    def test_the_cli_gets_our_tools_and_nothing_else(self):
        _, _, cli = self.run_it(last("nothing.\n===\n{}"))
        cmd = cli.cmd
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", cmd)
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "")
        self.assertIn("--no-session-persistence", cmd)
        allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
        self.assertEqual(allowed, ["mcp__ctx__" + t for t in tools.AGENT])
        self.assertEqual(list(cli.config["mcpServers"]), ["ctx"])
        self.assertNotIn("CTX_AGENT", cli.env)                               # no word in the environment says "this is the app": a pass made for this run does
        self.assertRegex(cli.env[guard.AGENT_RUN], r"^[0-9a-f]{64}$")
        self.assertFalse(guard.agent_run(cli.env))                           # and it opens nothing once the run is over
        # the pass and the system text reach the CLI in files only the owner can read, never on its command line (ps shows
        # that to every account), and the files are gone once the run ends
        self.assertNotIn("--system-prompt", cmd)
        self.assertFalse(any(cli.env[guard.AGENT_RUN] in a or "# Today" in a for a in cmd))
        self.assertEqual(cli.modes, [0o600, 0o600])
        self.assertFalse(any(os.path.exists(p) for p in cli.files))
        self.assertEqual(cli.config["mcpServers"]["ctx"]["args"][:2], ["-I", "-S"])

    def test_text_before_a_tool_call_is_taken_back(self):
        reply, events, _ = self.run_it([ev("message_start", message={}), text("let me look into that for you. " * 8)] + [("t1", "search", {"query": "harbour lease"}, "same message")] + last("it is in clause 700 [V700]\n===\n{}"))
        kinds = [next(iter(e)) for e in events]
        self.assertIn("retract", kinds)
        self.assertLess(kinds.index("retract"), len(kinds) - 1)
        self.assertNotIn("let me look", reply["answer"])
        after = events[max(i for i, e in enumerate(events) if "retract" in e):]
        self.assertEqual("".join(e["delta"] for e in after if "delta" in e), reply["answer"])

    def test_a_text_written_for_the_owner_to_send_is_marked_a_draft(self):
        reply, events, _ = self.run_it(last('sounds good, friday works\n===\n{"strength": "strong", "draft": true}'), q="write a reply to ravi about friday")
        self.assertIs(reply["draft"], True)
        self.assertEqual(agent.kind_of("write a reply to ravi about friday"), "draft")
        other, _, _ = self.run_it(last('it is friday\n===\n{"strength": "strong", "draft": false}'))
        self.assertNotIn("draft", other)

    def test_a_loop_that_never_ran_gives_none(self):
        reply, events, _ = self.run_it([])
        self.assertIsNone(reply)

    def test_a_none_answer_is_weak_and_says_so(self):
        reply, _, _ = self.run_it(last('your archive doesn\'t show that.\n===\n{"strength": "none"}'), q="zorblax")
        self.assertEqual((reply["strength"], reply["found_it"], reply["cites"]), ("weak", False, []))

    def test_a_follow_up_gets_the_rows_the_last_answer_rested_on(self):
        reply, _, _ = self.run_it([("t1", "search", {"query": "harbour lease"})] + last("clause 700 [V700]\n===\n{}"))
        with mock.patch.object(agent, "DIR", os.path.join(fixture.HOME, "cache", "agent")):
            past = agent._past([{"q": "where is the harbour lease", "a": reply["answer"]}])
        self.assertIn("[V700]", past)
        self.assertIn("harbour lease clause 700", past)


class Tools(unittest.TestCase):
    def test_scope_limits_every_tool(self):
        with mock.patch.dict(os.environ, {"CTX_AGENT_SCOPE": json.dumps({"sources": ["telegram"]})}):
            out, rows = tools.run("search", {"query": "gazebo"})
            self.assertTrue(rows and all(r["src"] == "telegram" for r in rows))
            self.assertIn("outside the sources", tools.run("doc", {"id": "N1"})[0])
            self.assertIn("outside the sources", tools.run("read_thread", {"thread": "Ravi Anand"})[0])
        with mock.patch.dict(os.environ, {"CTX_AGENT_SCOPE": json.dumps({"after": "2025-04", "before": "2025-04"})}):
            out, rows = tools.run("search", {"query": "gazebo", "after": "2020"})
            self.assertTrue(rows and all(r["ts"].startswith("2025-04") for r in rows))

    def test_the_budget_ends_the_looking(self):
        with mock.patch.dict(os.environ, {"CTX_AGENT_CALLS": "1"}), mock.patch.object(tools, "_calls", [0]):
            self.assertIn("gazebo", tools.call("search", {"query": "gazebo"}))
            self.assertIn("budget", tools.call("search", {"query": "gazebo"}))
        with mock.patch.dict(os.environ, {"CTX_AGENT_UNTIL": "1"}):
            self.assertIn("budget", tools.call("search", {"query": "gazebo"}))

    def test_search_inside_a_person_across_apps(self):
        out, rows = tools.run("search", {"query": "paint colour", "people": ["maya okafor"]})
        self.assertEqual({r["src"] for r in rows}, {"telegram"})
        self.assertIn("whatsapp:Maya Okafor", out)                     # every conversation with them is listed

    def test_order_and_dates(self):
        out, rows = tools.run("search", {"query": "harbour lease", "order": "oldest"})
        self.assertEqual([r["id"] for r in rows], ["V700", "V2200"])
        out, rows = tools.run("search", {"query": "harbour lease", "after": "2024"})
        self.assertEqual([r["id"] for r in rows], ["V2200"])

    def test_read_around_and_by_period(self):
        out, rows = tools.run("read_thread", {"around": "V700", "limit": 4})
        self.assertEqual([r["id"] for r in rows], ["V698", "V699", "V700", "V701", "V702"])
        out, rows = tools.run("read_thread", {"thread": "Ravi Anand", "query": "lease"})
        self.assertIn("V2200", [r["id"] for r in rows])
        self.assertIn("2 messages mention", out)
        out, rows = tools.run("read_thread", {"thread": "Maya Okafor", "after": "2025-03-05", "before": "2025-03-06"})
        self.assertEqual([r["id"] for r in rows], ["MW4", "MW5"])

    def test_counts_are_computed(self):
        self.assertIn("23 rows contain gazebo", tools.run("stats", {"what": "count", "query": "gazebo"})[0])
        self.assertIn("22 messages with maya okafor", tools.run("stats", {"what": "person", "person": "maya okafor"})[0])
        self.assertIn("Ravi Anand (whatsapp): 3000 messages", tools.run("stats", {"what": "people"})[0])

    def test_every_tool_stays_small(self):
        for name, args in (("search", {"query": "day", "limit": 40}), ("read_thread", {"thread": "Ravi Anand", "limit": 150}), ("stats", {"what": "months"}),
                           ("timeline", {"after": "2023"}), ("links", {"query": "pottery", "limit": 40}), ("sources", {})):
            self.assertLessEqual(len(tools.run(name, args)[0]), tools.MOST + 60, name)

    def test_the_agent_sees_only_its_tools_and_reads_unmasked(self):
        with mock.patch.dict(os.environ, fixture.own_run()):
            listed = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
            self.assertEqual([t["name"] for t in listed], [t for t in mcp.TOOLS if t in tools.AGENT])
            self.assertIn("0100", mcp.call("search", {"query": "samovar"}))
        self.assertNotIn("0100", mcp.call("search", {"query": "samovar"}))
        gone = fixture.own_run()
        guard.agent_close(gone[guard.AGENT_RUN])
        for said in ({"CTX_AGENT": "1"}, {"CTX_AGENT": "1", guard.AGENT_RUN: "1"}, {"CTX_AGENT": "1", guard.AGENT_RUN: "0" * 64}, dict(gone, CTX_AGENT="1")):
            with mock.patch.dict(os.environ, said):                          # saying so is not being so: the word, a made-up pass, the pass of a run that ended
                listed = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
                self.assertEqual([t["name"] for t in listed], ["context_" + t for t in mcp.TOOLS], said)
                self.assertNotIn("0100", mcp.call("search", {"query": "samovar"}), said)
                out = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "search", "arguments": {"query": "samovar"}}})["result"]["content"][0]["text"]
                self.assertTrue(out.startswith(guard.NOTE), said)


class CitedOnly(unittest.TestCase):
    def test_marks_after_the_full_stop_stay_with_their_sentence(self):
        by = {"V700": {}, "V701": {}}
        text = "**it changed twice.** The lease was signed on 3 June. [V700] Ravi paid 400 that week. [V701] [V700] Then a made-up fact about 2019.\n\n- The clause moved in March. [V701]"
        out = agent.cited_only(text, by)
        self.assertIn("signed on 3 June. [V700]", out)
        self.assertIn("paid 400 that week. [V701] [V700]", out)
        self.assertNotIn("2019", out)                               # a fact with no mark still goes
        self.assertFalse([l for l in out.split("\n") if agent.re.match(r"\s*(?:[-*]\s+)?(?:\[[^\]]+\]\s*)+$", l)])       # and no line is left holding marks alone

    def test_what_is_missing_is_kept_whole(self):
        by = {"V700": {}}
        text = "The lease was signed in June [V700].\n\n## What is missing\n\nThe signed copy from 2023 is nowhere. Ravi may hold it since March.\n\n## After\n\nAn unmarked fact about 2021."
        out = agent.cited_only(text, by)
        self.assertIn("The signed copy from 2023 is nowhere. Ravi may hold it since March.", out)
        self.assertNotIn("2021", out)


class Recency(unittest.TestCase):
    """A question about the present ranks the last weeks first; one that names a past time is left alone."""

    def test_which_questions_are_about_the_present(self):
        for q in ("what am i working on", "what is open", "what do i owe people", "how am i doing", "what's on my mind lately", "what should i do next",
                  "what are my priorities", "who have i been talking to these days", "what is the latest on the harbour lease", "any deadlines this week"):
            self.assertTrue(agent.present(q), q)
        for q in ("what was i working on in 2023", "what were my plans last year", "when did i first talk about the gazebo project", "what did i plan with maya",
                  "which projects did i start two years ago", "what was on my mind back then", "who is the plumber", "where is the harbour lease",
                  "what tasks did ravi send", "the first time i mentioned my goals", "my plans in march", "have i ever been stressed about money"):
            self.assertFalse(agent.present(q), q)

    def test_recent_rows_are_lifted_and_nothing_is_dropped(self):
        now = time.mktime(time.strptime("2025-06-01", "%Y-%m-%d"))
        rows = [{"id": "old1", "ts": "2021-01-01"}, {"id": "old2", "ts": "2022-01-01"}, {"id": "q", "ts": "2025-03-20"}, {"id": "old3", "ts": "2020-01-01"},
                {"id": "new", "ts": "2025-05-25T10:00:00"}, {"id": "nodate", "ts": ""}]
        got = [r["id"] for r in tools.fresh(rows, now=now)]
        self.assertEqual(got[0], "new")                                 # from the last 30 days: first, from fifth place
        self.assertEqual(sorted(got), sorted(r["id"] for r in rows))
        self.assertEqual([i for i in got if i.startswith("old")], ["old1", "old2", "old3"])        # the older keep their order
        self.assertLess(got.index("q"), got.index("old2"))              # the last 90 days: a smaller lift
        self.assertEqual([r["id"] for r in tools.fresh(rows[:4], now=now + 400 * 86400)], ["old1", "old2", "q", "old3"])     # nothing recent: nothing moves

    def test_only_a_question_about_the_present_is_ranked_that_way(self):
        seen = []
        real = tools._search_rows

        def spy(a, *rest, **kw):
            seen.append(a.fresh)
            return real(a, *rest, **kw)
        with mock.patch.object(tools, "_search_rows", spy):
            agent.first_look("what am i working on with the harbour lease")
            agent.first_look("what was i working on in 2023 with the harbour lease")
            agent.first_look("where is the harbour lease")
        self.assertEqual(seen, [True, False, False])
        with mock.patch.object(tools, "fresh", side_effect=lambda rows, **kw: rows) as lift:
            tools._search_rows(tools.Args({"query": "harbour lease", "after": "2023-01-01"}, {"fresh": True}), [["harbour", "lease"]], "words", 5)
            lift.assert_not_called()                                    # dates asked for outright say which time is meant
            tools._search_rows(tools.Args({"query": "harbour lease"}, {"fresh": True}), [["harbour", "lease"]], "words", 5)
            lift.assert_called_once()

    def test_the_model_is_told_the_newest_evidence_wins(self):
        loop = Loop()
        _, _, cli = loop.run_it(last("nothing.\n===\n{}"), q="what am i working on")
        self.assertIn("NEWEST evidence wins", cli.system)
        self.assertTrue(json.loads(cli.env["CTX_AGENT_SCOPE"]).get("fresh"))
        _, _, cli = loop.run_it(last("nothing.\n===\n{}"), q="what was i working on in 2023")
        self.assertNotIn("NEWEST evidence wins", cli.system)
        self.assertNotIn("fresh", json.loads(cli.env["CTX_AGENT_SCOPE"]))

    def test_likes_from_a_small_source_are_not_pushed_out_by_a_large_one(self):
        row = lambda i, src, ts: {"id": i, "src": src, "ts": ts, "thread": "", "who": "saved", "text": "pottery " + i, "url": "", "sender": ""}
        big = [row("IG%d" % n, "instagram_likes", "2024-01-%02d" % (n + 1)) for n in range(25)]
        small = [row("XL%d" % n, "x_likes", "2025-05-%02d" % (n + 1)) for n in range(3)]

        def found(a, probes, mode, limit, **kw):
            return ({"instagram_likes": big, "x_likes": small}.get(a.sources[0], [])[:limit], 28, {})
        with mock.patch.object(tools, "_search_rows", found):
            text, rows = tools.run("saved", {"query": "pottery", "kind": "likes", "limit": 6})
        self.assertEqual([r["src"] for r in rows], ["instagram_likes", "x_likes"] * 3)          # a turn for each source
        with mock.patch.object(tools, "_search_rows", found):
            _, rows = tools.run("saved", {"query": "pottery", "kind": "likes", "limit": 6, "order": "newest"})
        self.assertEqual([r["id"] for r in rows if r["src"] == "x_likes"], ["XL2", "XL1", "XL0"])    # newest first within each
        text, rows = tools.run("saved", {"kind": "likes", "limit": 4})                           # no words: the latest of each
        self.assertIn("the latest of each source", text)
        self.assertTrue(rows and all(r["src"] == "instagram_likes" for r in rows))               # the made-up archive has no x likes
        self.assertEqual([r["ts"] for r in rows], sorted((r["ts"] for r in rows), reverse=True))

    def test_the_briefing_opens_with_what_the_last_30_days_hold(self):
        from ctx import understand
        with mock.patch.object(understand, "NOW", os.path.join(fixture.HOME, "cache", "now-test.json")):
            text = understand.now(today="2024-05-20")
            self.assertTrue(text.startswith("# Now: the last 30 days, 2024-04-20 to 2024-05-20"), text[:80])
            self.assertIn("wrote with most", text)
            self.assertLessEqual(len(text), 1200)
            self.assertEqual(understand.now(today="2024-05-20"), text)                             # kept until the archive or the day changes
            self.assertEqual(understand.now(today="1999-01-01"), "")                               # nothing dated then: no block
            with mock.patch.object(understand, "now", return_value=text), mock.patch.object(understand, "core", return_value="the page"):
                self.assertEqual(understand.about(), text + "\n\nthe page")
            with mock.patch("ctx.llm.ask") as model:
                understand.now(today="2024-05-19")
            model.assert_not_called()


class Wired(unittest.TestCase):
    def test_answer_stream_lets_the_model_drive_when_it_can(self):
        made = dict(answer._tiered(answer._reply(0, "it is there"), (), "strong"), agent="quick")
        with mock.patch.object(agent, "available", return_value=True), mock.patch.object(agent, "answer_for", return_value=made) as run:
            self.assertIs(answer.answer_stream("q", emit=lambda e: None), made)
            self.assertEqual(run.call_args[0][4], "quick")
            answer.answer_stream("q", emit=lambda e: None, dig=True)
            self.assertEqual(run.call_args[0][4], "deep")

    def test_an_unsure_quick_answer_is_looked_into_again(self):
        weak = dict(answer._tiered(answer._reply(0, "not sure")), agent="quick")
        sure = dict(answer._tiered(answer._reply(0, "found it"), (), "strong"), agent="deep")
        events = []
        with mock.patch.object(agent, "available", return_value=True), mock.patch.object(agent, "answer_for", return_value=weak), mock.patch.object(agent, "run", return_value=sure):
            out = answer.answer_stream("q", emit=events.append)
        self.assertEqual(out["answer"], "found it")
        self.assertEqual(events[-1], {"done": out, "deep": True})

    def test_the_longer_look_stays_inside_the_quick_ceiling(self):
        weak = dict(answer._tiered(answer._reply(0, "not sure")), agent="quick")
        sure = dict(answer._tiered(answer._reply(0, "found it"), (), "strong"), agent="deep")
        with mock.patch.object(agent, "available", return_value=True), mock.patch.object(agent, "answer_for", return_value=weak), mock.patch.object(agent, "run", return_value=sure) as dig:
            t0 = time.time()
            answer.answer_stream("q", emit=lambda e: None)
            self.assertLessEqual(dig.call_args[1]["deadline"], t0 + agent.CEILING + 1)       # it gets what is left of the ceiling
            dig.reset_mock()
            with mock.patch.dict(os.environ, {"CTX_QUICK_CEILING": "10"}):                    # too little left to read and write in: the first answer stands
                self.assertEqual(answer.answer_stream("q", emit=lambda e: None)["answer"], "not sure")
            dig.assert_not_called()
            cut = dict(weak, path="cut")
            with mock.patch.object(agent, "answer_for", return_value=cut):                    # an answer already cut off for time is not looked into again
                answer.answer_stream("q", emit=lambda e: None)
            dig.assert_not_called()

    def test_ending_a_call_at_a_clock_time(self):
        import threading
        with mock.patch("ctx.llm.cancel") as stop:
            with agent._Until(time.time() + 0.05) as u:
                time.sleep(0.3)
            self.assertTrue(u.hit)
            stop.assert_called_once_with(threading.get_ident())
            with agent._Until(time.time() + 5), agent._Until(None):
                pass
            stop.assert_called_once()

    def test_the_fixed_pipeline_answers_when_the_loop_cannot_start(self):
        with mock.patch.object(agent, "available", return_value=True), mock.patch.object(agent, "answer_for", return_value=None), \
                mock.patch.object(answer, "_prepare", return_value=(answer._tiered(answer._reply(0, "from the pipeline")), None)):
            self.assertEqual(answer.answer("q")["answer"], "from the pipeline")


if __name__ == "__main__":
    unittest.main()
