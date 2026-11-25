"""Questions about the whole person are answered from what is already written about the owner, with no search for
messages. No model is called; the archive and every name are made up."""
import os, time, unittest
from unittest import mock
from tests import fixture
from ctx import agent, made, rules, understand, whole, wiki

fixture.index()
WIKI = os.path.join(os.path.dirname(__file__), "fixtures", "wiki")
ROAST = "from all you know about me, write me a toast for the allotment supper, be blunt. say it in harbour-town slang and add puns"


class Asked(unittest.TestCase):
    def test_what_is_a_question_about_the_whole_of_the_owner(self):
        for q in (ROAST, "roast me", "what do you know about me", "describe me to a stranger", "what are my blind spots", "write my bio", "who am i", "who am i really?",
                  "what kind of person am i", "tell me about myself", "summarise me in three lines", "write a dating profile about me in esperanto", "what does my archive say about me",
                  "what would a stranger say about me", "psychoanalyse me, be brutal", "what are my worst habits", "write my linkedin bio"):
            self.assertEqual(agent.kind_of(q), "self", q)

    def test_near_misses_stay_with_the_other_routes(self):
        for q in ("what did sam say about me", "what does maya think of me", "what do you know about my trip to the harbour", "who am i meeting tomorrow", "describe the harbour lease",
                  "what did i say about myself in 2021", "write a reply to maya", "roast ravi", "what are ravi's blind spots", "when did grace describe me as stubborn",
                  "what do you know about ravi", "where is the harbour lease", "write a bio for maya", "who am i seeing on friday"):
            self.assertNotEqual(agent.kind_of(q), "self", q)

    def test_how_to_say_it_is_not_what_to_read(self):
        self.assertEqual(whole.subject(ROAST), "from all you know about me, write me a toast for the allotment supper")
        self.assertEqual(whole.subject("write a dating profile about me in esperanto"), "write a dating profile about me")
        self.assertEqual(whole.subject("describe me to a stranger in broad scots, 80 words"), "describe me to a stranger")       # any language or register, not a list of them
        self.assertEqual(whole.subject("psychoanalyse me, be brutal"), "psychoanalyse me")
        self.assertEqual(whole.subject("what are my blind spots"), "what are my blind spots")


class Written(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.object(wiki, "DIR", WIKI), mock.patch("ctx.llm._claude_bin", return_value="/made/up/claude"), mock.patch("ctx.llm._log"),
                  mock.patch.object(agent, "model_for", return_value="made-up-model"), mock.patch.object(rules, "FILE", os.path.join(fixture.HOME, "no-rules-here.json"))):
            p.start()
            self.addCleanup(p.stop)
        wiki._mem.clear()
        rules._mem.clear()
        self.addCleanup(wiki._mem.clear)
        self.addCleanup(rules._mem.clear)

    def says(self, text, fail_after=None):
        seen = []

        def stream(system, prompt, model, usage):
            seen.append((system, prompt))
            if fail_after is not None:
                yield text[:fail_after]
                raise RuntimeError("claude: ended without a reply")
            yield text
        self.seen = seen
        return mock.patch("ctx.llm._claude_stream", stream)

    def test_the_pages_are_read_with_no_search(self):
        asked = []
        real = wiki.excerpt
        with mock.patch("ctx.tools._search_rows") as search, mock.patch("ctx.answer.search") as words, mock.patch.object(wiki, "excerpt", lambda q, **kw: (asked.append(q), real(q, **kw))[1]):
            t0 = time.time()
            text, by, profile = whole.pages(ROAST)
            took = time.time() - t0
        search.assert_not_called()
        words.assert_not_called()
        self.assertLess(took, 2.0)
        self.assertIn("# About the owner", text)
        self.assertTrue(profile)
        self.assertTrue(by)                                              # the messages the wiki's sentences rest on, to cite
        self.assertNotIn("[[", text)
        self.assertNotIn("slang", asked[0])                              # the slang the owner asked for is not a thing to look up
        self.assertNotIn("puns", asked[0])

    def test_one_call_writes_it_in_the_tone_the_owner_asked_for_with_the_wikis_evidence(self):
        _, by, _ = whole.pages(ROAST)
        rid = sorted(by)[0]
        events = []
        with self.says("oi, you absolute kettle-hoarder, you signed the lease late again [%s]. and a made-up mark [NOPE1].\n===\n{\"strength\": \"strong\"}" % rid), \
                mock.patch.object(agent, "lean") as small, mock.patch.object(agent, "run") as loop, mock.patch.object(made, "keep") as kept:
            reply = agent.answer_for(ROAST, emit=events.append, keep=False)
        small.assert_not_called()                                        # not a lookup: no search for messages, no loop
        loop.assert_not_called()
        self.assertEqual((reply["path"], reply["kind"], reply["usage"]["calls"], reply["strength"], reply["error"]), ("self", "self", 1, "strong", ""))
        self.assertEqual([c["id"] for c in reply["cites"]], [rid])
        self.assertIn("kettle-hoarder", reply["answer"])
        self.assertNotIn("NOPE1", reply["answer"])
        self.assertNotIn("ran out of time", reply["answer"])
        system, prompt = self.seen[0]
        self.assertIn("TONE AND LANGUAGE ARE THE OWNER'S TO SET", system)
        self.assertIn("harbour-town slang", prompt)                      # their words reach the writer whole
        self.assertIn("# About the owner", prompt)
        self.assertEqual(events[-1], {"done": reply})
        self.assertEqual("".join(e["delta"] for e in events if "delta" in e), reply["answer"])
        kept.assert_called_once()                                        # a piece written about the owner is kept as a made thing

    def test_out_of_time_gives_the_short_version_from_the_profile_never_closest_messages(self):
        events = []
        with self.says("", fail_after=0):
            reply = whole.answer(ROAST, emit=events.append)
        self.assertEqual((reply["path"], reply["strength"], reply["error"]), ("self-short", "partial", ""))
        self.assertIn("short version", reply["answer"])
        self.assertIn(whole._short(understand.core())[:30], reply["answer"])
        self.assertNotIn("closest messages", reply["answer"])
        self.assertNotIn("nothing here is confirmed", reply["answer"])
        self.assertEqual(events[-1], {"done": reply})
        long_ = "you hoard kettles and call it a fund. " * 20
        with self.says(long_, fail_after=500):                           # most of an answer was written when the clock ran out: it is kept
            reply = whole.answer(ROAST)
        self.assertEqual(reply["path"], "self")
        self.assertIn("this stops short", reply["answer"])
        self.assertIn("you hoard kettles", reply["answer"])

    def test_the_clock_and_their_rules_reach_the_call(self):
        with self.says("you are fine.\n===\n{}"), mock.patch.object(agent, "_Until", wraps=agent._Until) as clock, mock.patch.object(agent, "_rules", return_value="\n\n# The owner's standing instructions\n- call maya didi"), \
                mock.patch.object(rules, "veil", side_effect=lambda t: t.replace("gazebo", "")) as veil:
            end = time.time() + 30
            whole.answer("what do you know about me", until=end)
        clock.assert_called_once_with(end)
        self.assertIn("call maya didi", self.seen[0][0])
        self.assertTrue(veil.called)                                     # lines naming someone the owner left out are not handed over
        self.assertNotIn("gazebo", self.seen[0][1].split("# About the owner")[1])

    def test_with_nothing_written_the_other_routes_answer(self):
        with mock.patch.object(whole, "pages", return_value=("", {}, "")):
            self.assertIsNone(whole.answer("roast me"))
        with mock.patch.object(whole, "answer", return_value=None), mock.patch.object(agent, "run", return_value=None) as loop:
            agent.answer_for("roast me", keep=False)
        loop.assert_called_once()
