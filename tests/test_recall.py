"""The second, wider look: guessed words, conversations ranked first, stretches second. No model is called and every row is made up."""
import os, re, shutil, tempfile, unittest
from unittest import mock
from tests import fixture
from ctx import agent, answer, recall, semantic, tools
from tests.test_semantic import Base

GUESS = {"passages": ["pottery glaze with a celadon finish"], "terms": ["celadon", "glaze"], "kind": "chat", "after": "", "before": ""}


class Expand(unittest.TestCase):
    def test_one_call_per_question_then_from_disk(self):
        home = tempfile.mkdtemp(prefix="ctx-expand-")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        said = {"passages": ["a line", 7, "x" * 900], "terms": ["glaze", None], "kind": "poem", "after": "2024-03-09"}
        with mock.patch.object(recall, "DIR", home), mock.patch("ctx.llm.ask_json", return_value=said) as ask:
            first = recall.expand("that  ceramic coating")
            again = recall.expand("that ceramic coating")
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(first, again)
        self.assertEqual((first["terms"], first["kind"], first["after"], len(first["passages"]), len(first["passages"][1])), (["glaze"], "any", "2024-03", 2, 300))

    def test_a_failed_call_is_no_guess(self):
        home = tempfile.mkdtemp(prefix="ctx-expand-")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        with mock.patch.object(recall, "DIR", home), mock.patch("ctx.llm.ask_json", side_effect=RuntimeError("no")):
            self.assertEqual(recall.expand("anything"), {})

    def test_words_are_weighed_by_where_they_come_from(self):
        got = dict(recall.groups("that ceramic coating", GUESS))
        self.assertEqual((got["ceramic"], got["celadon"], got["finish"]), (recall.WQ, recall.WT, recall.WP))
        self.assertNotIn("that", got)


class Wide(Base):
    def test_no_index_no_second_look(self):
        with mock.patch.object(semantic, "index", return_value=None):
            self.assertEqual(recall.rank("kettle")[0], [])
            self.assertEqual(recall.wide("kettle", ex={})[0], "")

    def test_guessed_words_find_what_the_question_does_not_say(self):
        plain = recall.wide("that ceramic coating someone recommended", ex={})
        self.assertNotIn("R1", [r["id"] for r in plain[1]])
        text, rows, ex, marks, brief = recall.wide("that ceramic coating someone recommended", ex=GUESS)
        self.assertIn("R1", [r["id"] for r in rows])
        mark = next(m for m, r in marks.items() if r["id"] == "R1")
        self.assertRegex(mark, r"^z\d+$")
        self.assertIn(f"[{mark}]", text)
        self.assertNotIn("[R1]", text)                      # a line carries its short mark, never the long id
        self.assertIn("## rare one (whatsapp", text)
        self.assertIn("thread id: whatsapp:rare one", brief)
        self.assertNotIn("celadon", brief)                  # the map quotes nothing

    def test_a_conversation_takes_one_place(self):
        tids, idfs = recall.conversations("lantern festival plan", {})
        self.assertEqual(len(tids), len(set(tids)))
        self.assertIn("whatsapp:loud group", tids)
        self.assertGreater(len(tids), 3)                    # forty messages of one group did not fill the list

    def test_a_long_conversation_gives_its_best_stretches(self):
        _, idfs = recall.rank("harbour lease clause", {}, vectors=False)
        got = recall.stretches("whatsapp:Ravi Anand", idfs, k=2)
        ids = [str(m["id"]) for _, msgs in got for m in msgs]
        self.assertIn("V700", ids)
        self.assertIn("V2200", ids)
        self.assertLess(len(ids), 30)

    def test_a_named_person_is_read_first(self):
        idx = answer.thread_index()
        with mock.patch("ctx.people.everyone", return_value=[{"_key": "ravi anand", "aliases": [], "messages": 3000, "_tids": ["whatsapp:Ravi Anand"]}]):
            self.assertEqual(recall._named("what did ravi say about the tide", idx), ["whatsapp:Ravi Anand"])
            text = recall.wide("what did ravi say about the lantern and the harbour", ex={})[0]
        self.assertTrue(text.startswith("## Ravi Anand"))

    def test_notes_are_ranked_apart_from_chats(self):
        self.assertIn("N1", recall.docs("how do i rest", {"terms": ["pottery"]}))
        self.assertIn("N1", [t[0] for t in recall.titles("how do i rest", {"terms": ["pottery"]})])
        text, rows, _, marks, brief = recall.wide("how do i rest", ex={"terms": ["pottery"]})
        self.assertIn("## your own notes and docs", text)
        self.assertIn("N1", [r["id"] for r in rows])

    def test_scope_is_kept(self):
        text, rows, _, _, _ = recall.wide("pottery glaze", {"sources": ["telegram"]}, ex=GUESS)
        self.assertFalse([r for r in rows if r["src"] != "telegram"])


class Route(Base):
    def setUp(self):
        self.here = tempfile.mkdtemp(prefix="ctx-route-")
        self.addCleanup(shutil.rmtree, self.here, ignore_errors=True)
        self.p = [mock.patch.object(agent, "DIR", self.here), mock.patch("ctx.llm._log"), mock.patch.object(agent, "model_for", return_value="made-up"),
                  mock.patch.object(recall, "expand", return_value=GUESS)]
        for p in self.p:
            p.start()
            self.addCleanup(p.stop)

    def stream(self, second):
        seen = []

        def go(system, prompt, model, usage):
            usage.update({"in": 900, "out": 40})
            seen.append((system, prompt))
            if "SECOND, wider look" not in system:
                yield "ESCALATE"
                return
            yield second(prompt)
        return go, seen

    def test_the_second_look_answers_before_the_loop(self):
        def second(prompt):
            mark = re.search(r"\[(z\d+)\] [\d:]+ [^\n]*celadon", prompt).group(1)
            return f'it was the celadon finish [{mark}].\n===\n{{"strength": "strong"}}'
        go, seen = self.stream(second)
        with mock.patch("ctx.llm._claude_stream", go), mock.patch.object(agent, "run") as loop, mock.patch.object(agent, "check", side_effect=lambda q, r, **kw: r):
            reply = agent.answer_for("that ceramic coating someone recommended", keep=False)
        loop.assert_not_called()
        self.assertEqual(len(seen), 2)
        self.assertEqual((reply["path"], [c["id"] for c in reply["cites"]]), ("wide", ["R1"]))
        self.assertEqual(reply["answer"], "it was the celadon finish[1].")
        self.assertEqual((reply["usage"]["calls"], reply["usage"]["in"]), (3, 1800))        # the first call, the guess, the second look

    def test_still_not_settled_goes_to_the_loop_with_the_map(self):
        go, seen = self.stream(lambda prompt: "ESCALATE")
        made = dict(answer._tiered(answer._reply(0, "from the loop"), (), "strong"), usage={"calls": 2, "tools": 1, "in": 5000, "out": 100})
        with mock.patch("ctx.llm._claude_stream", go), mock.patch.object(agent, "run", return_value=made) as loop, mock.patch.object(agent, "check", side_effect=lambda q, r, **kw: r):
            reply = agent.answer_for("that ceramic coating someone recommended", keep=False)
        seed = loop.call_args[1]["seed"]
        self.assertIn("thread id: whatsapp:rare one", seed[3])
        self.assertEqual((reply["path"], reply["usage"]["calls"], reply["usage"]["in"]), ("loop", 5, 6800))

    def test_switched_off(self):
        go, seen = self.stream(lambda prompt: "ESCALATE")
        with mock.patch("ctx.llm._claude_stream", go), mock.patch.object(agent, "run", return_value=None) as loop, mock.patch.dict(os.environ, {"CTX_WIDE": "0"}):
            agent.answer_for("that ceramic coating someone recommended", keep=False)
        self.assertEqual(len(seen), 1)
        self.assertIsNone(loop.call_args[1]["seed"])


class ReadThread(unittest.TestCase):
    def test_words_pick_the_stretches_where_they_sit_together(self):
        out, rows = tools.run("read_thread", {"thread": "Ravi Anand", "query": "harbour; tide"})
        ids = [r["id"] for r in rows]
        self.assertIn("V700", ids)                          # 2,998 messages say tide; the two that say harbour are shown, not the latest thirteen
        self.assertIn("V2200", ids)
        self.assertIn("the best", out)

    def test_few_places_are_all_shown(self):
        out, rows = tools.run("read_thread", {"thread": "Ravi Anand", "query": "lease"})
        self.assertIn("2 messages mention", out)
        self.assertIn("the latest", out)


class Analysis(Base):
    def test_leads_are_cards_and_pages_never_rows(self):
        text = recall.leads("what happened with the harbour lease")
        self.assertIn("## Ravi Anand (whatsapp", text)
        self.assertIn("thread id: whatsapp:Ravi Anand", text)
        self.assertIn("renewed for two years", text)
        self.assertNotIn("[V700]", text)

    def test_a_fact_with_no_row_is_taken_out(self):
        by = {"W1": {}, "W2": {}}
        text = ('**you dropped it because the money ran out.** The fund closed in March 2024 [W1]. Sam asked for 40 kettles. That felt wrong to you [W2].\n\n'
                '- Maya said "no more" in June.\n- my read: you were tired, and Sam knew it.\n\n## what is missing\nThe bank statements from 2024 are missing.')
        got = agent.cited_only(text, by)
        self.assertNotIn("40 kettles", got)
        self.assertNotIn("no more", got)
        for kept in ("**you dropped it because the money ran out.**", "closed in March 2024 [W1]", "felt wrong to you [W2]", "my read: you were tired", "## what is missing", "bank statements from 2024"):
            self.assertIn(kept, got)

    def test_a_second_look_that_opens_on_a_guess_is_not_an_answer(self):
        self.assertTrue(agent.HEDGE.search("the main reason looks like the weather"))
        self.assertFalse(agent.HEDGE.search("you told her to plan for 10"))


if __name__ == "__main__":
    unittest.main()
