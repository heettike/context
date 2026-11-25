"""The last look before an answer is shown, what the owner reads, and what each step is called: no model is called."""
import os, unittest
from unittest import mock
from tests import fixture
from ctx import agent, answer, profile, tools, understand

fixture.index()
ROW = {"id": "V700", "src": "whatsapp", "ts": "2023-06-16", "thread": "Ravi Anand", "who": "them", "sender": "Ravi Anand", "text": "harbour lease clause 700 is at https://example.org/lease/700", "url": ""}


def made(text, cites=(ROW,), **more):
    return dict(answer._tiered(answer._reply(0, text, list(cites)), (), "strong"), usage={"calls": 2, "tools": 1, "in": 5000, "out": 100}, found_it=True, **more)


class Check(unittest.TestCase):
    def test_code_sees_a_quote_or_a_link_nothing_holds_and_facts_with_nothing_cited(self):
        self.assertEqual(agent.code_check(made('ada wrote "harbour lease clause 700"[1].')), [])
        self.assertEqual(agent.code_check(made('ada wrote "the gazebo burned down in march"[1].')), ["a quote no message that was read holds"])
        self.assertEqual(agent.code_check(made("it is https://example.org/lease/700 [1].")), [])
        self.assertEqual(agent.code_check(made("it is https://example.org/other [1].")), ["a link no message that was read holds"])
        self.assertEqual(agent.code_check(made("it was signed on 3 may 2021.", cites=())), ["nothing cited"])
        self.assertEqual(agent.code_check(made("your archive doesn't show that.", cites=())), [])
        seen = {"X1": dict(ROW, id="X1", text="the gazebo burned down in march")}
        self.assertEqual(agent.code_check(made('ada wrote "the gazebo burned down in march"[1].'), seen), [])

    def test_a_find_that_fits_only_in_part_is_never_shown_as_settled(self):
        events, reply = [], made("it is clause 700[1].")
        with mock.patch("ctx.llm.ask_json", return_value={"details": [{"detail": "in the old port", "shown": "no"}], "verdict": "partial",
                                                           "caveat": "not sure this is the one you mean: nothing shows these rows are about the old port."}) as ask:
            agent.check("the lease clause for the old port", reply, emit=events.append, force=True)
        ask.assert_called_once()
        self.assertTrue(reply["answer"].startswith("not sure this is the one you mean: nothing shows these messages are about the old port.\n\nit is clause 700[1]."))
        self.assertEqual((reply["strength"], reply["check"]["verdict"], reply["usage"]["calls"]), ("weak", "partial", 3))
        self.assertIn({"retract": True}, events)
        self.assertEqual(events[-1], {"delta": reply["answer"]})

    def test_a_settled_answer_is_left_alone_and_a_clean_lean_answer_costs_no_call(self):
        reply = made("it is clause 700[1].")
        with mock.patch("ctx.llm.ask_json", return_value={"details": [], "verdict": "settled", "caveat": ""}) as ask:
            agent.check("harbour lease clause", reply, force=True)
            self.assertEqual((reply["answer"], reply["strength"], reply["check"]["verdict"]), ("it is clause 700[1].", "strong", "settled"))
            agent.check("harbour lease clause", made("it is clause 700[1]."))
        ask.assert_called_once()

    def test_facts_with_nothing_cited_are_marked_unverified_without_a_call(self):
        reply = made("it was signed on 3 may 2021.", cites=())
        with mock.patch("ctx.llm.ask_json") as ask:
            agent.check("when was the lease signed", reply, force=True)
        ask.assert_not_called()
        self.assertEqual((reply["strength"], reply["found_it"]), ("weak", False))
        self.assertIn("unverified", reply["answer"].split("\n")[0])

    def test_marks_that_point_at_nothing_that_was_read_make_it_unverified(self):
        reply = made("it was signed on 3 may 2021[1], witnessed by two people, and renewed in 2023.")
        reply["usage"].update(marks=7, dropped=6)
        with mock.patch("ctx.llm.ask_json") as ask:
            agent.check("when was the lease signed", reply, force=True)
        ask.assert_not_called()
        self.assertEqual((reply["strength"], reply["check"]["verdict"]), ("weak", "unsupported"))

    def test_a_link_or_quote_written_with_no_mark_gets_the_row_that_holds_it(self):
        by = {"V700": ROW}
        self.assertEqual(agent._attach("here: https://example.org/lease/700", by), "here: https://example.org/lease/700 [V700]")
        self.assertEqual(agent._attach('ravi said "harbour lease clause 700" back then', by), 'ravi said "harbour lease clause 700" [V700] back then')
        self.assertEqual(agent._attach("clause 700 [V700]", by), "clause 700 [V700]")
        self.assertEqual(agent._attach("nothing to tie", by), "nothing to tie")


class Words(unittest.TestCase):
    def test_the_owner_never_reads_rows(self):
        said = agent._plain("these rows show the direction, and the cited rows agree. no matching rows after may. one row says so? the last row is ada's. ada rows a boat.")
        self.assertNotRegex(said.replace("ada rows a boat", ""), r"(?i)\brows?\b")
        self.assertIn("ada rows a boat", said)
        for prompt in (agent.SYSTEM, agent.LEAN, agent.WRITE):
            self.assertIn('never write the word "rows"', prompt)

    def test_a_word_fixed_later_never_changes_what_was_already_shown(self):
        full = "these rows show it [V700] plainly"
        shown = ""
        for n in range(1, len(full) + 1):
            part = agent._body(full[:n])
            self.assertTrue(part.startswith(shown) or shown.startswith(part), (shown, part))
            shown = part if len(part) > len(shown) else shown
        self.assertEqual(agent._body(full, True), "these messages show it [V700] plainly")

    def test_steps_are_named_in_plain_words_by_code(self):
        L = agent.label
        self.assertEqual(L({"tool": "first_look"}), "searching your archive")
        self.assertEqual(L({"tool": "search", "args": {"query": "harbour lease clause nine; port", "sources": ["whatsapp", "telegram"]}}), "searching whatsapp and telegram for harbour lease clause")
        self.assertEqual(L({"tool": "search", "args": {"query": "lease", "people": ["Ravi Anand"]}}), "searching your chats with Ravi Anand for lease")
        self.assertEqual(L({"tool": "read_thread", "args": {"around": "LI11211"}, "thread": "Ravi Anand", "from": "2024-11-02", "to": "2024-12-05"}), "reading your thread with Ravi Anand, nov to dec 2024")
        self.assertEqual(L({"tool": "read_thread", "args": {"around": "LI11211"}}), "reading a conversation")
        self.assertEqual(L({"tool": "doc", "args": {"id": "N1"}, "src": "apple_notes", "thread": "rest"}), "reading your note 'rest'")
        self.assertEqual(L({"tool": "doc", "args": {"id": "LI11211"}, "src": "linkedin", "from": "2020-05-03"}), "reading a linkedin message from may 2020")
        for step in ({"tool": "doc", "args": {"id": "LI11211"}}, {"tool": "read_thread", "args": {"around": "W123456", "thread": "whatsapp:12345678"}}, {"tool": "person", "args": {"name": "Ravi"}},
                     {"tool": "stats", "args": {"what": "people"}}, {"tool": "links", "args": {"query": "lease"}}, {"tool": "timeline", "args": {"after": "2024-01", "before": "2024-06"}}):
            self.assertNotRegex(L(step), r"[A-Z]{1,3}\d{3,}|\d{6,}")


class Docs(unittest.TestCase):
    def test_a_doc_is_read_whole_and_says_where_it_was_cut(self):
        text, rows = tools.run("doc", {"id": "N1"})
        self.assertIn("(whole)", text)
        self.assertIn("pottery is how i rest", text)
        long = {"id": "N9", "src": "apple_notes", "ts": "2025-05-01", "thread": "long", "who": "me", "text": "a" * 30000 + "the end", "url": "", "tid": ""}
        with mock.patch("ctx.peek.find", return_value=(1, {})), mock.patch.object(tools, "_row", return_value=long):
            first = tools.run("doc", {"id": "N9"})[0]
            rest = tools.run("doc", {"id": "N9", "from": tools.DOC})[0]
        self.assertGreater(len(first), 20000)
        self.assertIn(f"call doc with id N9 and from {tools.DOC} for the rest", first)
        self.assertTrue(rest.rstrip().endswith("the end"))

    def test_a_clipped_doc_hit_says_how_to_read_all_of_it(self):
        r = {"id": "N9", "src": "apple_notes", "ts": "2025-05-01", "thread": "long", "who": "doc", "text": "word " * 400, "url": "", "tid": ""}
        self.assertIn("(clipped: call doc with this id for all of it)", tools._line(r, (), 300))
        self.assertNotIn("clipped", tools._line(dict(r, text="short note"), (), 300))


class Pages(unittest.TestCase):
    def test_a_rebuilt_page_honours_the_owners_corrections(self):
        asked = []

        def ask(system, body, model, tag=""):
            asked.append((system, body))
            return "**Ada Lovelace**\n- who: a close friend\n- owes her: the kettle memo\n- likes tea\n"
        mem = os.path.join(fixture.HOME, "memory-distil")
        os.makedirs(mem, exist_ok=True)
        with mock.patch.object(profile, "LOG", os.path.join(mem, "corrections.jsonl")), mock.patch.object(profile, "MEM", mem), mock.patch.object(understand, "MEM", mem), \
                mock.patch.object(understand, "cards", return_value=[{"who": "ada", "_mine": 3}]), mock.patch("ctx.llm.ask", ask), mock.patch.dict(understand.DISTIL, {"people": "write the people page"}, clear=True), \
                mock.patch("builtins.print"):
            profile.correct("people", "- owes her: the kettle memo", wrong=True)
            profile.correct("people", "- who: a close friend", fix="- who: her cousin")
            self.assertEqual(understand.distil(), ["people"])
            with open(os.path.join(mem, "people.md")) as f:
                page = f.read()
        self.assertIn("the kettle memo", asked[0][1])        # the model is told, in the material: the corrected line is a model's words about the archive
        self.assertNotIn("the kettle memo", asked[0][0])
        self.assertIn("override anything the cards say", asked[0][0])
        self.assertEqual(page, "**Ada Lovelace**\n- who: her cousin\n- likes tea\n")         # and what it let through is put right


if __name__ == "__main__":
    unittest.main()
