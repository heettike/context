"""The lean route and the knowledge layer behind it, with made-up model replies: no model is called."""
import json, os, time, unittest
from unittest import mock
from tests import fixture
from ctx import agent, answer, deep, tools

fixture.index()
HERE = os.path.join(fixture.HOME, "cache", "agent-lean")


def says(text):
    def stream(system, prompt, model, usage):
        usage.update({"in": 900, "out": 40})
        for i in range(0, len(text), 7):
            yield text[i:i + 7]
    return stream


class Route(unittest.TestCase):
    def setUp(self):
        self.p = [mock.patch.object(agent, "DIR", HERE), mock.patch("ctx.llm._log"), mock.patch.object(agent, "model_for", return_value="made-up")]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_what_kind_of_question(self):
        self.assertEqual(agent.kind_of("where is the link to the harbour lease"), "lookup")
        self.assertEqual(agent.kind_of("how has my view on leases changed over the years"), "analysis")
        self.assertEqual(agent.kind_of("what went wrong with the gazebo"), "analysis")
        self.assertEqual(agent.kind_of("how many times did ravi mention the lease"), "count")

    def test_one_small_call_answers_a_lookup(self):
        events = []
        with mock.patch("ctx.llm._claude_stream", says('clause 700 covers it [V700].\n===\n{"strength": "strong"}')) as s, mock.patch.object(agent, "run") as loop:
            reply = agent.answer_for("harbour lease clause", emit=events.append, keep=False)
        loop.assert_not_called()
        self.assertEqual((reply["path"], reply["usage"]["calls"], reply["usage"]["tools"]), ("lean", 1, 0))
        self.assertEqual([c["id"] for c in reply["cites"]], ["V700"])
        self.assertEqual(reply["answer"], "clause 700 covers it[1].")
        self.assertEqual("".join(e["delta"] for e in events if "delta" in e), reply["answer"])
        self.assertEqual(events[-1], {"done": reply})

    def test_not_settled_goes_to_the_loop_and_shows_nothing_first(self):
        events = []
        made = dict(answer._tiered(answer._reply(0, "from the loop"), (), "strong"), usage={"calls": 2, "tools": 1, "in": 5000, "out": 100})
        with mock.patch("ctx.llm._claude_stream", says("ESCALATE")), mock.patch.object(agent, "run", return_value=made) as loop:
            reply = agent.answer_for("harbour lease clause", emit=events.append, keep=False)
        loop.assert_called_once()
        self.assertEqual((reply["path"], reply["usage"]["calls"], reply["usage"]["in"]), ("loop", 3, 5900))     # the small call is counted
        self.assertFalse([e for e in events if "delta" in e])

    def test_a_quick_lookup_has_a_ceiling_and_each_step_gets_what_is_left(self):
        made = dict(answer._tiered(answer._reply(0, "from the loop"), (), "strong"), usage={"calls": 2, "tools": 1, "in": 5000, "out": 100})
        with mock.patch("ctx.llm._claude_stream", says("ESCALATE")), mock.patch.object(agent, "_wide", return_value=None), mock.patch.object(agent, "run", return_value=made) as loop:
            t0 = time.time()
            agent.answer_for("harbour lease clause", keep=False)
            self.assertLessEqual(loop.call_args[1]["deadline"], t0 + agent.CEILING - 2.9)     # the loop must be over before the ceiling, with room for the last check
            self.assertGreater(loop.call_args[1]["deadline"], t0 + agent.CEILING - 6)
            self.assertFalse(loop.call_args[1]["whole"])
            row = {"id": "V700", "src": "whatsapp", "ts": "2023-06-16 08:00", "thread": "Ravi Anand", "who": "Ravi Anand", "text": "harbour lease clause 700", "url": ""}
            late = lambda q, sc: (time.sleep(0.3), ("## a conversation\n[z1] 08:00 Ravi Anand: harbour lease clause 700", [row], 0.3, "map", {"z1": row}))[1]
            with mock.patch.object(agent, "_wide", late), mock.patch.dict(os.environ, {"CTX_QUICK_CEILING": "32"}), mock.patch.object(agent, "lean", wraps=agent.lean) as small:
                agent.answer_for("harbour lease clause", keep=False)
            self.assertEqual(small.call_count, 1)                                             # no time for a small call on the second look and the loop after it:
            self.assertTrue(loop.call_args[1]["whole"])                                       # the loop reads the second look itself
            agent.answer_for("harbour lease clause", mode="deep", keep=False)
            self.assertIsNone(loop.call_args[1]["deadline"])                                  # a deep answer takes the time it needs

    def test_an_answer_with_no_row_behind_it_is_not_an_answer(self):
        with mock.patch("ctx.llm._claude_stream", says("it is surely clause nine, trust me on this one.\n===\n{}")), mock.patch.object(agent, "run", return_value=None) as loop:
            agent.answer_for("harbour lease clause", keep=False)
        loop.assert_called_once()

    def test_analysis_and_deep_skip_the_small_call(self):
        with mock.patch("ctx.llm._claude_stream") as small, mock.patch.object(agent, "run", return_value=None) as loop:
            agent.answer_for("how has the harbour lease changed over the years", keep=False)
            agent.answer_for("harbour lease clause", mode="deep", keep=False)
        small.assert_not_called()
        self.assertGreaterEqual(loop.call_count, 2)        # an analysis first tries its gathering pass, also the loop

    def test_an_analysis_in_two_passes_writes_only_from_what_was_gathered(self):
        row = {"id": "V700", "src": "whatsapp", "ts": "2023-06-16 08:00", "thread": "Ravi Anand", "who": "Ravi Anand", "text": "harbour lease clause 700", "url": ""}
        got = {"claims": "- the lease clause came up in june 2023 [V700]\nmissing: the signed copy", "by_id": {"V700": row}, "steps": [{"n": 1, "tool": "search", "args": {}, "found": 1}],
               "usage": {"calls": 3, "tools": 4, "in": 9000, "out": 300}}
        seen, events = {}, []

        def stream(system, prompt, model, usage):
            seen.update(system=system, prompt=prompt)
            usage.update({"in": 2000, "out": 200})
            yield "**the lease was settled early.** it came up in june 2023 [V700]. my read: you moved fast [V700]. and a made-up thing [ZZ999].\n===\n{\"strength\": \"partial\"}"
        with mock.patch.object(agent, "run", return_value=got) as gather, mock.patch("ctx.llm._claude_stream", stream):
            reply = agent.two_pass("how has the harbour lease changed over the years", emit=events.append)
        self.assertTrue(gather.call_args[1]["gather"])
        self.assertIn("harbour lease clause 700", seen["prompt"])              # the writer is handed the rows, and has no tools
        self.assertEqual((reply["path"], reply["usage"]["calls"], reply["usage"]["in"]), ("two-pass", 4, 11000))
        self.assertEqual([c["id"] for c in reply["cites"]], ["V700"])
        self.assertNotIn("ZZ999", reply["answer"])
        self.assertEqual(events[-1], {"done": reply})

    def test_the_same_question_again_costs_nothing(self):
        with mock.patch("ctx.llm._claude_stream", says('clause 700 covers it [V700].\n===\n{"strength": "strong"}')):
            first = agent.answer_for("Harbour lease clause?")
        events = []
        with mock.patch("ctx.llm._claude_stream") as small, mock.patch.object(agent, "run") as loop:
            again = agent.answer_for("harbour  lease clause", emit=events.append)
            small.assert_not_called()
            loop.assert_not_called()
        self.assertEqual((again["path"], again["answer"], again["usage"]["calls"]), ("kept", first["answer"], 0))
        self.assertEqual(events[-1], {"done": again})
        with mock.patch.object(agent, "_stamp", return_value=[[1, 1]]), mock.patch("ctx.llm._claude_stream", says("ESCALATE")), mock.patch.object(agent, "run", return_value=None) as loop:
            agent.answer_for("harbour lease clause")            # the archive changed: asked afresh
            loop.assert_called_once()


class Layer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = mock.patch.multiple(deep, DIR=os.path.join(fixture.HOME, "memory", "deep"), UNITS=os.path.join(fixture.HOME, "memory", "deep", "units"))
        cls.dir.start()
        made = {"facts": [{"s": "me", "p": "renewed the lease for", "o": "one year", "when": "2023-06-16", "conf": 0.9, "rows": [1]},
                          {"s": "me", "p": "renewed the lease for", "o": "two years", "when": "2024-06-16", "conf": 0.9, "rows": [2]},
                          {"s": "nobody", "p": "said", "o": "nothing", "rows": []}, {"s": "x", "p": "y", "o": "z", "rows": [99]}],
                "questions": [{"q": "how long is the dock rental for", "a": "two years", "rows": [2]}],
                "commitments": [{"by": "me", "to": "Ravi Anand", "what": "send the signed papers", "status": "open", "rows": [2]}],
                "people": [{"name": "Ravi Anand", "aka": ["ravi"], "relation": "landlord", "rows": [1]}], "opinions": "not a list"}
        rows = [("V700", "2023-06-16T08:00:00Z", "Ravi Anand", "harbour lease clause 700"), ("V2200", "2024-06-16T08:00:00Z", "Ravi Anand", "harbour lease clause 2200")]
        with mock.patch("ctx.llm.ask_json", return_value=made):
            cls.n = deep.read_unit("chat:whatsapp:Ravi Anand", {"title": "Ravi Anand", "src": "whatsapp", "kind": "dm", "n": 3000, "to": "2024-12-25"}, rows)
        cls.tables = deep.merge()

    @classmethod
    def tearDownClass(cls):
        cls.dir.stop()

    def test_only_items_that_rest_on_a_row_are_kept(self):
        self.assertEqual(self.n, 5)
        self.assertEqual((self.tables["facts"], self.tables["questions"], self.tables["commitments"], self.tables["people"]), (2, 1, 1, 1))
        facts = deep._table("facts")
        self.assertEqual([f["ids"] for f in facts], [["V700"], ["V2200"]])

    def test_a_later_fact_supersedes_the_earlier(self):
        old, new = deep._table("facts")
        self.assertEqual(old["superseded_by"], new["key"])
        self.assertNotIn("superseded_by", new)

    def test_links_are_catalogued_by_code(self):
        urls = [l["url"] for l in deep._table("links")]
        self.assertIn("https://example.com/b/0", urls)
        self.assertFalse([u for u in urls if "/shop/" in u])           # browsing is not a link someone sent

    def test_a_question_in_other_words_lands_on_the_row(self):
        text, rows = deep.lookup("how long did i take the dock rental for")
        self.assertIn("[V2200]", text)
        self.assertIn("V2200", [r["id"] for r in rows])
        self.assertEqual(deep.lookup("zorblax quux"), ("", []))

    def test_the_keys_join_the_meaning_index(self):
        keys = list(deep.key_units())
        self.assertIn(("V2200", "how long is the dock rental for two years"), [(k["id"], k["text"]) for k in keys])

    def test_a_page_per_person(self):
        deep._people_pages({t: deep._table(t) for t in deep.TABLES}, least=1)
        with open(os.path.join(deep.DIR, "people", "ravi_anand.md")) as f:
            page = f.read()
        self.assertIn("landlord", page)
        self.assertIn("send the signed papers", page)

    def test_a_read_unit_is_not_read_again_until_it_grows(self):
        self.assertTrue(deep._done("chat:whatsapp:Ravi Anand", {"n": 3000}))
        self.assertTrue(deep._done("chat:whatsapp:Ravi Anand", {"n": 3100}))
        self.assertFalse(deep._done("chat:whatsapp:Ravi Anand", {"n": 3400}))
        self.assertFalse(deep._done("chat:whatsapp:someone else", {"n": 10}))

    def test_the_estimate_reads_nothing(self):
        with mock.patch("ctx.llm.ask_json") as ask, mock.patch("ctx.llm.status", return_value={"plan": "made up"}):
            e = deep.estimate()
        ask.assert_not_called()
        self.assertTrue(e["units"] > 0 and e["calls"] >= e["units"] and e["tokens_in"] > 0)

    def test_the_lean_route_is_handed_the_layer(self):
        text, rows = agent.evidence("how long did i take the dock rental for")
        self.assertIn("knowledge layer", text)
        self.assertIn("V2200", [r["id"] for r in rows])


if __name__ == "__main__":
    unittest.main()
