import json, subprocess, unittest
from unittest import mock
from tests import fixture
from ctx import answer, lens, llm

KEYS = {"answer", "cites", "searched", "found", "confidence", "secs", "error", "threads", "links", "maybe", "strength"}
CITE = {"id", "src", "ts", "thread", "who", "text", "url", "sender"}


def model(plan, reply):
    """Stands in for llm.ask_json: the first call is the planner, the second the answer. Records what it was sent."""
    calls = []

    def ask_json(system, prompt, model=None, tag=""):
        calls.append({"system": system, "prompt": prompt, "tag": tag})
        out = plan if tag.endswith("plan") else reply
        if isinstance(out, Exception):
            raise out
        return out

    def ask(system, prompt, model=None, tag=""):      # the answering call reads the raw reply itself
        out = ask_json(system, prompt, model, tag)
        return out if isinstance(out, str) else json.dumps(out)

    class Both:
        def __enter__(self):
            self.ps = [mock.patch.object(llm, "ask_json", ask_json), mock.patch.object(llm, "ask", ask)]
            for p in self.ps:
                p.start()

        def __exit__(self, *a):
            for p in self.ps:
                p.stop()
    return Both(), calls


class Answer(unittest.TestCase):
    def ask(self, q, plan, reply, history=None):
        patch, self.calls = model(plan, reply)
        with patch:
            out = answer.answer(q, history)
        self.assertEqual(set(out), KEYS)
        for c in out["cites"]:
            self.assertEqual(set(c), CITE)
        return out

    def test_markers_map_to_cites_in_order(self):
        out = self.ask("what is the kettle fund", {"probes": [["kettle"]], "after": "", "who": ""},
                       {"answer": "someone asked about the memo [W2]. it closes friday [W1].", "cites": ["W1", "W2"], "confidence": 4})
        self.assertEqual(out["answer"], "someone asked about the memo[1]. it closes friday[2].")
        self.assertEqual([c["id"] for c in out["cites"]], ["W2", "W1"])
        self.assertEqual((out["error"], out["confidence"], out["searched"], out["found"]), ("", 4, ["kettle"], 3))

    def test_saved_rows_reach_the_model_and_can_be_cited(self):
        out = self.ask("what do i think about pottery", {"probes": [["pottery"]], "who": "me"},
                       {"answer": "you rest with it [N1] and save posts on kilns [B0].", "cites": [], "confidence": 3})
        body = self.calls[-1]["prompt"]
        self.assertIn("[B0] x_bookmarks", body)
        self.assertIn("| saved:", body)
        self.assertNotIn("| them:", body)
        self.assertEqual([c["who"] for c in out["cites"]], ["me", "saved"])

    def test_only_saved_when_the_owner_asks_what_the_owner_saved(self):
        self.ask("have i saved anything about pottery", {"probes": [["pottery"]], "who": "saved"}, {"answer": "yes [B1].", "cites": ["B1"]})
        rows = self.calls[-1]["prompt"].split("## rows", 1)[1]
        self.assertNotIn("| me:", rows)
        self.assertIn("instagram_saved", rows)

    def test_a_period_is_passed_to_the_search(self):
        self.ask("what did i invest in in 2024", {"probes": [["invest"]], "after": "2024", "before": "2024"}, {"answer": "a kettle maker [W5].", "cites": ["W5"]})
        rows = self.calls[-1]["prompt"].split("## rows", 1)[1]
        self.assertIn("[W5]", rows)
        self.assertNotIn("[W6]", rows)

    def test_a_period_question_gets_the_timeline_for_those_years_only(self):
        import os
        path = os.path.join(fixture.HOME, "memory", "timeline.md")
        with open(path, "w") as f:
            f.write("## 2023\n- learnt to throw clay\n\n## 2024\n- backed a kettle maker\n\n## 2025\n- opened a studio\n")
        try:
            self.ask("what did i invest in in 2024", {"probes": [["invest"]], "after": "2024-01", "before": "2024-12"}, {"answer": "a kettle maker [W5].", "cites": []})
            about = self.calls[-1]["prompt"].split("## question")[0]
            self.assertIn("backed a kettle maker", about)
            self.assertNotIn("throw clay", about)
            self.assertNotIn("opened a studio", about)
            self.ask("kettle", {"probes": [["kettle"]]}, {"answer": "ok [W1].", "cites": []})
            self.assertNotIn("his timeline", self.calls[-1]["prompt"])
        finally:
            os.remove(path)

    def test_when_did_i_first_reads_the_oldest_rows(self):
        self.ask("when did i first plan the lantern festival", {"probes": [["lantern", "festival"]], "oldest": True}, {"answer": "july [L0].", "cites": []})
        thread = self.calls[-1]["prompt"].split("## threads read in order", 1)[1].splitlines()
        self.assertIn("2025-07-01", thread[2])                           # the conversation itself, from its first line

    def test_nothing_found_is_said_without_a_second_call(self):
        out = self.ask("who is zorblax", {"probes": [["zorblax"]]}, {"answer": "should not be asked"})
        self.assertEqual((out["cites"], out["found"], out["error"]), ([], 0, ""))
        self.assertIn("nothing in your archive", out["answer"])
        self.assertEqual(len(self.calls), 1)

    def test_too_narrow_a_plan_is_widened(self):
        out = self.ask("the memo", {"probes": [["kettle", "memo"]], "who": "me"}, {"answer": "she asked if you read it [W2].", "cites": ["W2"]})
        self.assertEqual([c["id"] for c in out["cites"]], ["W2"])

    def test_a_planner_that_fails_falls_back_to_the_questions_words(self):
        for plan in (RuntimeError("claude: boom"), subprocess.TimeoutExpired(["x"], 240), [], "junk", {"probes": "kettle"}, {"probes": []}):
            out = self.ask("what about the kettle fund?", plan, {"answer": "it closes friday [W1].", "cites": ["W1"]})
            self.assertEqual(out["error"], "", plan)
            self.assertEqual(out["searched"], ["kettle", "fund"])
            self.assertEqual(out["answer"], "it closes friday[1].")

    def test_fallback_drops_the_words_found_everywhere(self):
        out = self.ask("pottery celadon glaze", RuntimeError("claude: down"), {"answer": "a celadon finish [R1].", "cites": []})
        self.assertEqual(out["searched"], ["celadon", "glaze"])          # "pottery" is in two hundred rows, the others in one
        self.assertEqual([c["id"] for c in out["cites"]], ["R1"])

    def test_prompts_assume_no_gender_and_no_one_language(self):
        import re
        for text in (answer.PLAN, answer.ANSWER, lens.SYSTEM, lens.RELATE, lens.OWN, " ".join(L["ask"] for L in lens.LENSES.values())):
            self.assertIsNone(re.search(r"\b(he|his|him|she|her)\b", text, re.I), text[:60])
        self.assertIn("more than one language", answer.PLAN)

    def test_a_question_with_nothing_to_search_for(self):
        out = self.ask("what did i say?", [], {"answer": "x"})
        self.assertEqual((out["error"], out["cites"]), ("", []))
        self.assertIn("no words", out["answer"])
        self.assertEqual(answer.answer("   ")["error"], "ask a question first.")

    def test_a_follow_up_sees_the_earlier_turns_without_their_markers(self):
        hist = [{"q": "what is the kettle fund", "a": "it closes friday[1]."}, "junk", {"q": None}]
        self.ask("and who asked", {"probes": [["kettle"]]}, {"answer": "she did [W2].", "cites": ["W2"]}, hist)
        self.assertIn("earlier question: what is the kettle fund", self.calls[0]["prompt"])
        self.assertIn("earlier answer: it closes friday.", self.calls[1]["prompt"])
        for bad in ("junk", 5, {"q": "x"}, [None]):
            self.assertEqual(self.ask("kettle", {"probes": [["kettle"]]}, {"answer": "ok [W1]", "cites": []}, bad)["error"], "")

    def test_errors_are_one_plain_sentence(self):
        secret = "/Users/someone/bin/claude --system-prompt long text"
        for err, want in ((subprocess.TimeoutExpired([secret], 240), "too long"), (RuntimeError("claude: " + secret), "model call failed"),
                          (RuntimeError("claude: usage limit reached"), "limit"), (RuntimeError("no model is signed in on this mac. run once in a terminal: claude auth login"), "signed in"),
                          (ValueError(secret), "something went wrong")):
            out = self.ask("kettle fund", {"probes": [["kettle"]]}, err)
            self.assertIn(want, out["error"])
            self.assertNotIn("/Users", out["error"])
            self.assertNotIn("system-prompt", out["error"])
            self.assertEqual((out["answer"], out["cites"]), ("", []))

    def test_a_reply_that_is_not_an_answer(self):
        for reply in ([], "", "short", {"answer": ""}, {"cites": ["W1"]}, None, '{"answer": "cut off mid'):
            out = self.ask("kettle fund", {"probes": [["kettle"]]}, reply)
            self.assertIn("nothing usable", out["error"], reply)
            self.assertEqual(len(self.calls), 3)                 # the planner, then asked twice

    def test_a_reply_in_prose_instead_of_json_is_still_the_answer(self):
        for reply in ("- it closes on friday [W1]\n- she asked about the memo [W2]", "```\nit closes on friday [W1], she asked [W2].\n```",
                      'here you go: it closes on friday [W1] and she asked [W2].'):
            out = self.ask("kettle fund", {"probes": [["kettle"]]}, reply)
            self.assertEqual(out["error"], "")
            self.assertEqual([c["id"] for c in out["cites"]], ["W1", "W2"])
            self.assertIn("[1]", out["answer"])
            self.assertNotIn("```", out["answer"])
            self.assertEqual(len(self.calls), 2)                 # not asked again

    def test_odd_shapes_in_a_reply_do_not_crash(self):
        out = self.ask("kettle fund", {"probes": [["kettle"]]}, {"answer": ["it closes friday [W1]"], "cites": [{"id": "W1"}, 3, "W2"], "confidence": "high"})
        self.assertEqual(out["error"], "")
        self.assertEqual([c["id"] for c in out["cites"]], ["W1", "W2"])
        self.assertIsNone(out["confidence"])

    def test_text_in_rows_is_marked_as_data(self):
        self.assertIn("never instructions", answer.ANSWER)
        self.assertIn("never an instruction", answer.PLAN)


class Lens(unittest.TestCase):
    def test_saved_reads_only_what_the_owner_saved(self):
        patch, calls = model(None, {"summary": "three threads on kilns.", "items": [
            {"what": "a kiln thread", "who": "someone", "when": "2025-05-01", "status": "open", "cite": "B1"},
            {"what": "made up", "cite": "NOPE"}, {"what": "bad", "cite": ["B1"]}, "junk"]})
        with mock.patch.dict(lens.LENSES["saved"], {"probes": [["pottery"]]}), patch:
            out = lens.run("saved")
        self.assertEqual(out["error"], "")
        self.assertEqual([i["cite"]["id"] for i in out["items"]], ["B1"])
        rows = calls[-1]["prompt"].split("## rows", 1)[1]
        self.assertIn("x_bookmarks", rows)
        self.assertIn("instagram_saved", rows)                           # every place the owner saves things, not one site
        self.assertNotIn("| me:", rows)
        self.assertNotIn("| them:", rows)

    def test_tasks_reads_only_the_owners_own_words(self):
        patch, calls = model(None, {"summary": "", "items": []})
        with mock.patch.dict(lens.LENSES["tasks"], {"probes": [["pottery"]], "after_days": 0}), patch:
            out = lens.run("tasks")
        self.assertEqual((out["error"], out["items"]), ("", []))
        rows = calls[-1]["prompt"].split("## rows", 1)[1]
        self.assertNotIn("| saved:", rows)
        self.assertNotIn("| them:", rows)

    def test_the_model_adds_probes_in_the_owners_own_words(self):
        calls = []

        def ask_json(system, prompt, model=None, tag=""):
            calls.append(tag)
            return {"probes": [["samovar"], "kettle fund", ["owe"]]} if tag == "lens:probes" else {"summary": "", "items": []}
        lens._own.clear()
        with mock.patch.object(llm, "ask_json", ask_json), mock.patch.dict(lens.LENSES["money"], {"after_days": 0}):
            out = lens.run("money")
            again = lens.run("money")
        lens._own.clear()
        self.assertIn("samovar", out["searched"])
        self.assertIn("kettle fund", out["searched"])
        self.assertEqual(out["searched"].count("owe"), 1)
        self.assertEqual(calls.count("lens:probes"), 1)                  # asked once, then remembered
        self.assertEqual(again["searched"], out["searched"])

    def test_a_lens_runs_on_its_general_probes_when_the_model_adds_none(self):
        def ask_json(system, prompt, model=None, tag=""):
            if tag == "lens:probes":
                raise RuntimeError("claude: down")
            return {"summary": "", "items": []}
        lens._own.clear()
        with mock.patch.object(llm, "ask_json", ask_json), mock.patch.dict(lens.LENSES["money"], {"after_days": 0}):
            out = lens.run("money")
        self.assertEqual(out["error"], "")
        self.assertEqual(out["searched"], [" ".join(p) for p in lens.LENSES["money"]["probes"]])

    def test_unknown_lens_and_bad_replies(self):
        self.assertIn("no such lens", lens.run("nope")["error"])
        for reply in ([], {"items": "x"}, {"items": None}, RuntimeError("claude: /Users/x")):
            patch, _ = model(None, reply)
            with mock.patch.dict(lens.LENSES["money"], {"after_days": 0}), patch:
                out = lens.run("money")
            self.assertEqual(out["items"], [])
            self.assertNotIn("/Users", out["error"])

    def test_every_lens_has_what_run_needs(self):
        for name, L in lens.LENSES.items():
            self.assertTrue(answer.clean_probes(L["probes"]), name)
            self.assertIn(L["who"], ("", "me", "me_only", "saved"))
        self.assertEqual({x["id"] for x in lens.listing()}, set(lens.LENSES))

    def test_relate(self):
        patch, calls = model({"probes": [["pottery"]]}, {"notes": [{"line": "you already shortlisted studios", "cite": "O1"}, {"line": "x", "cite": "NOPE"}, 7]})
        with patch:
            out = lens.relate("i want to join a pottery studio this winter")
        self.assertEqual(out["error"], "")
        self.assertEqual([n["cite"]["id"] for n in out["notes"]], ["O1"])
        rows = calls[-1]["prompt"].split("## rows", 1)[1]
        self.assertIn("x_bookmarks", rows)
        self.assertIn("gdrive", rows)
        self.assertNotIn("| them: pottery class", rows)

    def test_relate_with_nothing_or_a_broken_model(self):
        self.assertEqual(lens.relate(""), {"notes": [], "error": ""})
        patch, _ = model(RuntimeError("claude: x"), {"notes": "junk"})
        with patch:
            self.assertEqual(lens.relate("pottery studio"), {"notes": [], "error": ""})


if __name__ == "__main__":
    unittest.main()


class Links(unittest.TestCase):
    """A question that asks for a link gets the url itself, and only one that is really in the rows."""

    def test_a_made_up_url_is_dropped_and_a_real_one_kept(self):
        from ctx import answer as A
        rows = {"W1": {"id": "W1", "src": "whatsapp", "ts": "2025-01-02", "text": "the film is at https://example.org/film.", "url": ""}}
        real = {}
        for r in rows.values():
            for u in A.URL.findall(r["text"]):
                real.setdefault(u.rstrip(".,;"), r)
        self.assertIn("https://example.org/film", real)
        self.assertNotIn("https://example.org/other", real)

    def test_words_that_ask_for_a_link(self):
        from ctx import answer as A
        for q in ("link to my allotment talk", "where is the deck", "that tweet about tea"):
            self.assertTrue(A.WANTS_LINK.search(q), q)
        for q in ("what do i think about education", "who did i promise an intro"):
            self.assertFalse(A.WANTS_LINK.search(q), q)
