"""The owner's public voice: measured by code, a guide by a stub model, retrieval, the bands, the enhance and long-form paths.
No model is called; every post here is made up."""
import json, os, shutil, tempfile, unittest
from tests import files as _f
from unittest import mock
from tests import fixture
from ctx import agent, llm, mcp, tools, voice

fixture.index()


def post(i, text, ts="2025-03-01T10:00:00Z", likes=0, channel="x_posts", title=""):
    return {"id": i, "src": "x_posts" if channel != "blog" else "canvas_made_up", "ts": ts, "text": text, "likes": likes, "channel": channel, "url": "", "title": title}


SHORT = [post("P%d" % n, t, "20%d-0%d-01T10:00:00Z" % (24 + n % 2, 1 + n % 9), likes=n * 3) for n, t in enumerate([
    "kettles are a tax on patience", "the gazebo is still the best room in the house\nno roof, no excuses", "nobody ships pottery on a friday",
    "the lease was the easy part", "a kiln teaches you to wait", "glaze first, regret later", "the harbour is cheaper than it looks",
    "three kettles in, still no tea", "you do not need a bigger wheel", "clay does not care about your deadline",
    "the samovar outlived two landlords", "pottery is just slow software"] * 4)]
LONG = [post("B%d" % n, "why the kiln waits\n\n" + "\n\n".join("the kiln does not hurry and neither should the glaze, which is the whole point of %d firings in a row here." % (k + n) for k in range(6)), channel="blog", title="the kiln")
        for n in range(4)]


class Home(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ctx-voice-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for p in (mock.patch.object(voice, "DIR", os.path.join(self.tmp, "voice")), mock.patch.object(voice, "posts", lambda fresh=False: SHORT + LONG),
                  mock.patch.object(voice, "baseline", lambda grams, **k: ({"the": 900, "is": 500, "you": 400, "a": 800}, 20000))):
            p.start()
            self.addCleanup(p.stop)
        voice._mem.clear()
        self.addCleanup(voice._mem.clear)


class Measured(Home):
    def test_a_post_in_numbers(self):
        f = voice.features("the gazebo is still the best room\nno roof, no excuses https://made.up/x?y=1")
        self.assertEqual((f["lines"], f["all_lower"], f["links"], f["emoji"], f["end"], f["question"]), (2, True, 1, 0, "open", False))
        g = voice.features("Big News! We launched \U0001F680 #pottery @maya 40% off.")
        self.assertEqual((g["all_lower"], g["exclaim"], g["emoji"], g["hashtags"], g["mentions"], g["numbers"] > 0, g["end"]), (False, True, 1, 1, 1, True, "period"))

    def test_what_is_his_and_what_is_a_repost(self):
        self.assertEqual(voice.channel_of({"src": "x_posts", "who": "me", "text": "kettles"}), "x_posts")
        self.assertEqual(voice.channel_of({"src": "x_posts", "who": "me", "text": "@maya yes", "title": "reply to maya"}), "x_replies")
        self.assertEqual(voice.channel_of({"src": "x_posts", "who": "", "text": "RT @maya: kettles"}), "")
        self.assertEqual(voice.channel_of({"src": "linkedin_posts", "who": "me", "text": "https://made.up/only-a-link"}), "")
        self.assertEqual(voice.channel_of({"src": "canvas_made_up", "text": "a long page"}), "blog")
        self.assertEqual(voice.channel_of({"src": "x_bookmarks", "text": "someone else"}), "")
        self.assertEqual(voice.body("@maya @ravi yes exactly", "x_replies"), "yes exactly")

    def test_every_channel_is_measured_with_no_model(self):
        with mock.patch.object(llm, "ask") as model:
            got = voice.build(model=False)
        model.assert_not_called()
        self.assertEqual((got["measured"]["x_posts"], got["measured"]["blog"], got["measured"]["linkedin_posts"], got["calls"]), (48, 4, 0, 0))
        m = voice.load()
        x = m["x_posts"]
        self.assertEqual(x["lowercase"]["all_lower"], 1.0)
        self.assertEqual((x["emoji"]["posts_with"], x["uses"]["hashtags"]), (0.0, 0.0))
        self.assertIn("2025", x["by_year"])
        self.assertTrue(any(p[0] in ("kettles", "kiln", "gazebo", "pottery", "glaze") for p in x["own_phrases"]))     # the owner's words, not everyone's
        self.assertFalse(any(p[0] in ("the", "is", "a") for p in x["own_phrases"]))
        self.assertEqual(x["bands"]["lowercase"], True)
        self.assertTrue(x["bands"]["no_emoji"] and x["bands"]["no_hashtags"] and x["bands"]["no_exclaim"])
        st = m["blog"]["structure"]
        self.assertEqual((st["pieces"], st["title"]["lowercase"], st["paragraphs"]["p50"]), (4, 1.0, 6))

    def test_shorthand_and_units_are_the_owners_own_not_a_list(self):
        """Two made-up owners who clip different words and count in different units: each is measured by what they write."""
        ada = [post("A%d" % n, t) for n, t in enumerate(["thx for the kettle, ppl loved it", "pls bring 3kg of clay", "ppl ask abt the kiln, about 40kg a firing", "thx, the glaze cost 12fr",
                                                         "pls no more teapots", "abt 5kg left and 30fr in the tin", "ppl pls, thx", "the gazebo is about done"] * 5)]
        sam = [post("S%d" % n, t) for n, t in enumerate(["gracias x todo, tmb por el horno", "son 20eur xq subio la arcilla", "tmb quedan 3 teteras", "xq no vienes, cuesta 15eur",
                                                         "el huerto abre tmb el lunes", "todo bien xq llovio", "pago 40eur y listo", "la tetera nueva ya llego"] * 5)]
        a, b = voice.lexicon(ada), voice.lexicon(sam)
        self.assertTrue(a["measured"] and b["measured"])
        self.assertEqual(set(a["shorthand"]) & {"thx", "ppl", "pls", "abt", "tmb", "xq"}, {"thx", "ppl", "pls", "abt"})     # "abt" because this owner also writes "about"
        self.assertEqual(set(b["shorthand"]) & {"thx", "ppl", "pls", "abt", "tmb", "xq"}, {"tmb", "xq"})
        self.assertEqual((a["units"], b["units"]), (["kg", "fr"], ["eur"]))
        self.assertNotIn("the", a["shorthand"])
        self.assertNotIn("todo", b["shorthand"])
        line = "ppl pls send 5kg, tmb 20eur xq si"
        fa, fb = voice.features(line, a), voice.features(line, b)
        self.assertEqual((fa["shorthand"], fb["shorthand"]), (2, 2))            # each owner's own two, not the other's
        self.assertEqual((fa["numbers"], fb["numbers"]), (1, 1))                # "5kg" is a figure to one, "20eur" to the other
        ma, mb = voice.measure(ada, lex=a), voice.measure(sam, lex=b)
        self.assertEqual((ma["shorthand_used"][:3], mb["shorthand_used"]), (["pls", "ppl", "thx"], ["tmb", "xq"]))
        self.assertIn("chat shorthand (pls, ppl, thx, abt)", voice._numbers(ma))
        self.assertIn("chat shorthand (tmb, xq)", voice._numbers(mb))

    def test_too_little_writing_gets_the_small_stand_in(self):
        few = [post("F%d" % n, "pls bring the kettle, about 3kg") for n in range(voice.LEAST - 1)]
        got = voice.lexicon(few)
        self.assertEqual((got["measured"], got["shorthand"], got["units"]), (False, sorted(voice.SHORTHAND), list(voice.UNITS)))
        self.assertLessEqual(len(voice.SHORTHAND), 8)
        self.assertEqual(voice.cuts([voice.features(r["text"], got) for r in few]), voice.CUTS)
        self.assertEqual(voice.features("thx, 5k of them", got)["shorthand"], 1)
        self.assertEqual(voice.features("paid 5k and 40% and \u20ac30 and \u00a312 and \u20b910", got)["numbers"], 5)      # any currency sign, none expected

    def test_what_counts_as_rare_comes_from_the_owners_own_writing(self):
        steady = [voice.features(t) for t in ["the kiln waits for nobody here", "glaze first and regret it later on"] * 40]
        self.assertEqual(voice.cuts(steady)["rare"], 0.02)                      # nothing moves between the halves: the floor
        mixed = [voice.features(t) for t in (["the kiln waits!"] * 3 + ["the kiln waits"] * 5) * 10]
        loose = voice.cuts(mixed)["rare"]
        self.assertGreater(loose, 0.02)                                         # an owner whose habits come and go is held to them less tightly
        self.assertLessEqual(loose, 0.10)
        voice.build(model=False)
        m = voice.load()
        self.assertEqual(m["x_posts"]["cuts"]["rare"], m["x_posts"]["recent"]["cuts"]["rare"])
        self.assertTrue(0.02 <= m["x_posts"]["cuts"]["rare"] <= 0.10)
        self.assertEqual(m["_"]["lexicon"]["measured"], True)
        old = dict(m["x_posts"]["recent"])
        old.pop("cuts")
        self.assertEqual(voice.bands(old)["no_emoji"], True)                    # a measurement kept before cuts were: the plain defaults

    def test_a_magnitude_in_words_is_told_in_every_pack_and_a_new_one(self):
        for line in ("clay made me a million dollars", "gane dos millones con el horno", "ek crore ka kiln", "dua juta untuk teko", "ganhei dois milhões"):
            self.assertTrue(voice.features(line)["spelled"], line)
        for line in ("it cost 5 million", "smile at the kiln", "40% off"):
            self.assertFalse(voice.features(line)["spelled"], line)
        self.assertGreaterEqual(len(voice.MAGNITUDES), 4)
        self.assertFalse(voice.features("elfu moja za chai")["spelled"])
        with mock.patch.dict(voice.MAGNITUDES, {"sw": ["elfu", "milioni"]}):
            self.assertTrue(voice.features("elfu moja za chai")["spelled"])
        self.assertFalse(voice.features("elfu moja za chai")["spelled"])

    def test_the_lexicon_in_use_is_the_one_measured_from_the_owners_posts(self):
        """After a build, what counts as shorthand and as a figure is what this owner's posts showed, kept with the measurement."""
        mine = [post("K%d" % n, t) for n, t in enumerate(["thx for the kettle, 3kg of clay came", "pls bring the 5kg bag", "thx again, pls come by", "the kiln took 12kg today",
                                                          "pls no more teapots thx", "about 2kg left in the shed"] * 8)]
        with mock.patch.object(voice, "posts", lambda fresh=False: mine):
            voice.build(model=False)
        lex = voice.load()["_"]["lexicon"]
        self.assertEqual((lex["measured"], lex["n"]), (True, 48))
        self.assertEqual((sorted(lex["shorthand"]), lex["units"]), (["pls", "thx"], ["kg"]))
        f = voice.features("pls send 5kg thx, btw 3k is fine")
        self.assertEqual((f["shorthand"], f["numbers"]), (2, 1))                # this owner's own two words and one unit; "btw" and "3k" are another writer's
        self.assertEqual(voice.load()["x_posts"]["shorthand_used"], ["pls", "thx"])
        self.assertEqual(voice.load()["x_posts"]["habits"]["own_shorthand"], 0.667)       # four of the six kinds of post hold one
        few = mine[:voice.LEAST - 1]
        with mock.patch.object(voice, "posts", lambda fresh=False: few):
            voice.build(model=False)
        lex = voice.load()["_"]["lexicon"]
        self.assertEqual((lex["measured"], lex["shorthand"], lex["units"]), (False, sorted(voice.SHORTHAND), list(voice.UNITS)))      # under the threshold: the small stand-in
        f = voice.features("pls send 5kg thx, btw 3k is fine")
        self.assertEqual((f["shorthand"], f["numbers"]), (3, 1))                # now "btw" counts with the others, and "3k" is the figure

    def test_every_language_pack_has_its_magnitudes(self):
        from ctx import langpacks
        self.assertEqual(sorted(voice.MAGNITUDES), langpacks.codes())
        for line in ("ich habe tausend dinge zu tun", "mille mercis pour le four", "sen en desu"):
            self.assertTrue(voice.features(line)["spelled"], line)

    def test_a_draft_is_held_to_the_owners_bands(self):
        voice.build(model=False)
        self.assertEqual(voice.check("a wheel is a patient thing", "x_posts"), [])
        got = " | ".join(voice.check("Big News! We are SO excited to launch \U0001F680 #pottery " + "really " * 40, "x_posts"))
        for part in ("length", "capital", "emoji", "hashtag", "exclamation", "intensifiers"):
            self.assertIn(part, got)

    def test_what_gave_drafts_away_is_counted_and_checked(self):
        voice.build(model=False)
        f = voice.features("the kiln waits.\n> one\n> two\nit is not a tool, it's a teacher. why? because. so true. very very true (really).\n(a whole line in brackets, like this one here)\nfu*k \u2192 a million dollars")
        self.assertEqual((f["quote_bullets"], f["contrast"], f["tiny_questions"], f["paren_paragraphs"], f["censored"], f["arrows"], f["spelled"] > 0, f["fragments"] >= 3), (2, True, 1, 1, 1, 1, True, True))
        b = voice.load()["x_posts"]["bands"]
        self.assertTrue(all(b.get(k) for k in ("no_contrast", "no_quote_bullets", "no_tiny_questions", "no_arrows", "no_spelled", "no_censored", "no_stock")), b)
        for draft, tell in (("the kiln is not a tool, it's a teacher", "not x, it's y"), ("> glaze first\n> regret later", "'>'"), ("why? because clay does not care", "question the owner then answers"),
                            ("clay made me a million dollars", "spelled out"), ("we must leverage the kiln", "stock word"), ("glaze \u2192 regret", "arrow"), ("clay. waits. always. for you my friend", "fragments")):
            self.assertTrue(any(tell in x for x in voice.check(draft, "x_posts")), (draft, voice.check(draft, "x_posts")))
        self.assertEqual(voice.check("the kiln teaches you to wait, and the glaze teaches you why", "x_posts"), [])
        self.assertIn("never the turn", voice.limits("x_posts"))
        rh = voice.load()["x_posts"]["rhythm"]
        self.assertEqual(sorted(rh)[:3], ["a_figure", "commas_per_100_words", "intensifiers_per_100_words"])

    def test_rules_learned_from_a_blind_test_reach_the_writer(self):
        voice.build(model=False)
        self.assertEqual(voice.tells("x_posts"), "")
        voice._put(os.path.join(voice.DIR, "tells_x_posts.json"), json.dumps([{"tell": "t", "kind": "rule", "rule": "stop when the claim is made"}, {"tell": "no rule"}]))
        self.assertIn("- stop when the claim is made", voice.tells("x_posts"))
        self.assertIn("stop when the claim is made", voice.tells("x_replies"))       # replies share the posts' rules until they have their own
        self.assertEqual(voice.tells("blog"), "")
        self.assertEqual(voice.check("anything", "linkedin_posts"), [])     # nothing measured there: nothing to hold it to
        self.assertIn("all lowercase", voice.limits("x_posts"))

    def test_a_guide_per_channel_then_nothing_on_a_second_run(self):
        calls = []

        def ask(system, prompt, model=None, tag=""):
            calls.append(tag)
            if tag == "voice:overall":
                return "## what the owner does\n- short\n=====\n## close friends\n- as before\n\n## in public\n- lowercase on x"
            return "## what the owner does\n- opens on the claim\n## what the owner never does\n- hashtags\nexemplars: " + ", ".join(i for i in ("P1", "P2", "P3", "NOPE", "B0", "B1", "B2", "B3") if "[%s]" % i in prompt)
        os.makedirs(os.path.join(self.tmp, "mem"))
        with mock.patch.object(llm, "ask", ask), mock.patch.object(voice.paths, "HOME", self.tmp), mock.patch("ctx.profile.BACKUPS", os.path.join(self.tmp, "backups")):
            os.makedirs(os.path.join(self.tmp, "memory"))
            with open(os.path.join(self.tmp, "memory", "voice.md"), "w") as f:
                f.write("## close friends\n- as before\n")
            got = voice.build()
            self.assertEqual((got["wrote"], got["calls"]), (["x_posts", "blog", "overall", "voice.md"], 3))
            again = voice.build()
            self.assertEqual((again["wrote"], again["calls"]), ([], 0))             # nothing new to read: no call
            page = _f.read(os.path.join(self.tmp, "memory", "voice.md"))
            self.assertIn("as before", page)                                         # what it said about chat is kept
            self.assertIn("## in public", page)
            self.assertEqual(len(os.listdir(os.path.join(self.tmp, "backups"))), 1)  # and the page it replaced
            self.assertIn("## in public", voice.with_public("## close friends\n- written again from chats\n"))       # put back after the read-through rewrites the page
        text, ex = voice.guide("x_posts")
        self.assertIn("opens on the claim", text)
        self.assertEqual([e["id"] for e in ex], ["P1", "P2", "P3"])                  # an id the model made up is not an exemplar
        self.assertEqual(ex[0]["text"], SHORT[1]["text"])                            # word for word
        self.assertLessEqual(len(voice.guide("blog")[1]), 3)                         # whole pieces, a few
        self.assertIn("how the owner builds a piece", [c for c in calls if c == "voice:guide"] and voice.LONG)

    def test_a_source_that_drops_out_of_the_archive_keeps_what_was_learned(self):
        voice.build(model=False)
        with mock.patch.object(voice, "posts", lambda fresh=False: LONG):
            got = voice.build(model=False)
        self.assertEqual((got["measured"]["x_posts"], got["missing"]), (48, ["x_posts"]))
        self.assertTrue(voice.load()["x_posts"]["missing_since"])
        self.assertEqual(voice.check("a wheel is a patient thing", "x_posts"), [])           # its bands still hold a draft
        self.assertEqual(voice.body("glaze &amp; regret", "x_posts"), "glaze & regret")       # an export's escapes are not the owner's hand

    def test_held_back_posts_are_in_nothing(self):
        got = voice.build(model=False, skip=["P0", "P1"])
        self.assertEqual(got["measured"]["x_posts"], 46)

    def test_the_tool_another_ai_reads(self):
        voice.build(model=False)
        text = voice.tool("x_posts")
        self.assertIn("hard limits", text)
        self.assertIn("all lowercase", text)
        self.assertIn("nothing of theirs on this channel", voice.tool("linkedin_posts"))
        self.assertIn("channel must be one of", voice.tool("nope"))
        self.assertIn("voice", mcp.TOOLS)
        with mock.patch.object(voice, "tool", return_value="the guide") as t:
            self.assertIn("the guide", tools.run("voice", {"channel": "blog"})[0])
            t.assert_called_once_with("blog", "")


class Asked(unittest.TestCase):
    def test_what_is_a_request_to_improve_his_writing(self):
        for q in ("sharpen this tweet: the harbour lease is a tax on patience and nobody tells you until you sign", "rewrite my linkedin post about kettles in my voice",
                  "improve this idea: a fund for kettles", "make this punchier \"the lease is a tax on patience, and you only learn it late\"",
                  "write a blog post about the harbour lease from my notes", "extend this into an essay: kettles are underrated"):
            self.assertEqual(agent.kind_of(q), "enhance", q)
        for q in ("what did ravi say about the rewrite", "when did i post about the gazebo", "find the tweet i saved about pottery", "how do i improve my sleep",
                  "which ideas did i drop", "who agreed to extend the lease", "what ideas did maya want to improve", "where is the harbour lease", "what was the first draft of the lease about"):
            self.assertNotEqual(agent.kind_of(q), "enhance", q)

    def test_the_channel_comes_from_the_words(self):
        self.assertEqual([voice.channel_for(q) for q in ("sharpen this tweet", "improve my linkedin post", "tighten this blog paragraph", "improve my reply to maya", "sharpen this idea")],
                         ["x_posts", "linkedin_posts", "blog", "x_replies", "x_posts"])


class Written(Home):
    def setUp(self):
        Home.setUp(self)
        voice.build(model=False)
        self.near = {"subject": [dict(SHORT[0], thread="", who="me", sender="")], "form": [dict(SHORT[4], thread="", who="me", sender="")],
                     "saved": [{"id": "XB1", "src": "x_bookmarks", "ts": "2025-01-01", "thread": "", "who": "saved", "text": "a saved post about kettles and patience, 40 firings", "url": "https://made.up/kettle", "sender": ""}]}
        for p in (mock.patch.object(voice, "nearest", lambda *a, **k: self.near), mock.patch("ctx.llm._claude_bin", return_value="/made/up/claude"), mock.patch("ctx.llm._log"),
                  mock.patch.object(agent, "model_for", return_value="made-up-model")):
            p.start()
            self.addCleanup(p.stop)

    def says(self, *replies):
        left, seen = list(replies), []

        def stream(system, prompt, model, usage):
            seen.append((system, prompt))
            yield left.pop(0)
        self.seen = seen
        return mock.patch("ctx.llm._claude_stream", stream)

    def test_versions_in_his_voice_with_what_they_lean_on(self):
        first = ("=== 1\nkettles are a tax on patience, paid in tea\n--- leans on: their line on patience [P0]\n=== 2\nBig News! Kettles \U0001F680\n--- leans on: the saved post [XB1]\n"
                 "=== 3\na kettle makes you wait, the kiln makes you mean it. 99 firings\n--- leans on: the kiln line [P4] [NOPE]")
        again = "=== 2\nthree kettles in and the tea is still an idea\n--- leans on: the saved post [XB1]\n=== 3\na kettle makes you wait, the kiln makes you mean it\n--- leans on: the kiln line [P4]"
        events = []
        with self.says(first, again):
            reply = voice.enhance("sharpen this tweet: kettles are a tax on patience", emit=events.append)
        self.assertEqual((reply["path"], reply["draft"], reply["usage"]["calls"]), ("voice", True, 2))
        self.assertEqual(reply["voice"], {"channel": "x_posts", "versions": 3, "passed_first": 1, "flagged": 0})
        self.assertNotIn("Big News", reply["answer"])                                # outside the owner's bands: written again
        self.assertNotIn("99", reply["answer"])                                      # a figure no source holds: written again
        self.assertEqual(sorted(c["id"] for c in reply["cites"]), ["P0", "P4", "XB1"])
        self.assertIn("leans on", reply["answer"])
        self.assertNotIn("NOPE", reply["answer"])
        self.assertIn("all lowercase", self.seen[0][0])                              # the measured limits are in the prompt as hard limits
        self.assertIn("broke the hard limits", self.seen[1][0])
        self.assertEqual(events[-1], {"done": reply})

    def test_a_version_still_outside_is_flagged(self):
        bad = "=== 1\nBig News! Kettles\n--- leans on: nothing [P0]"
        with self.says(bad, bad):
            reply = voice.enhance("sharpen this tweet: kettles are a tax on patience")
        self.assertEqual((reply["voice"]["flagged"], reply["strength"]), (1, "partial"))
        self.assertIn("outside your usual range", reply["answer"])

    def test_no_voice_measured_leaves_it_to_the_ordinary_path(self):
        with mock.patch.object(voice, "load", return_value={}):
            self.assertIsNone(voice.enhance("sharpen this tweet: kettles"))

    def test_a_long_piece_is_outlined_then_written_a_section_at_a_time_then_read_for_flow(self):
        outline = "title: the kettle waits\nwords: 300\n1. open on the wait [P0]\n2. what the kiln adds [XB1]\n3. end on the tea"
        para = lambda n: ("the kettle waits\n\n" if n == 0 else "") + " ".join("section %d says the kettle does not hurry and neither should the glaze, which is the whole point of waiting for it here," % n for _ in range(4)) + " and so on.\n--- leans on: their line on waiting [P0]"
        whole = "the kettle waits\n\n" + "\n\n".join(" ".join("part %d says the kettle does not hurry and neither should the glaze, which is the whole point of waiting for it here," % n for _ in range(4)) + " and so on." for n in range(3))
        with self.says(outline, para(0), para(1), para(2), whole), mock.patch.object(voice, "_notes", return_value=[]):
            reply = voice.enhance("write a blog post about kettles from my notes: they are slow, and that is the point")
        self.assertEqual((reply["voice"]["channel"], reply["voice"]["sections"], reply["usage"]["calls"], reply["draft"]), ("blog", 3, 5, True))       # outline, three sections, the flow pass
        self.assertIn("**outline**", reply["answer"])
        self.assertIn("part 2 says", reply["answer"])                                # the piece as the flow pass left it
        self.assertEqual(sorted(c["id"] for c in reply["cites"]), ["P0", "XB1"])        # only rows it was handed
        self.assertIn("OUTLINE only", self.seen[0][0])
        self.assertIn("ONE section", self.seen[1][0])
        self.assertIn("section 2 of 3", self.seen[2][0])
        self.assertRegex(self.seen[2][0], r"About \d+ words, not more")              # the owner's length, shared out among the sections
        self.assertIn("# This section draws on", self.seen[2][1])                    # each section has its own ground
        self.assertIn("# Written so far", self.seen[2][1])
        self.assertIn("section 0 says", self.seen[2][1])
        self.assertIn("Read it as one piece", self.seen[4][0])
        with self.says(outline, para(0), para(1), para(2), "too short"), mock.patch.object(voice, "_notes", return_value=[]):
            reply = voice.enhance("write a blog post about kettles from my notes: they are slow")
        self.assertIn("section 2 says", reply["answer"])                             # a flow pass that lost the piece is not used

    def test_the_route_sends_such_a_request_here(self):
        made = {"answer": "x", "cites": [], "error": "", "strength": "strong", "path": "voice", "draft": True}
        with mock.patch.object(voice, "enhance", return_value=made) as e, mock.patch.object(agent, "lean") as small, mock.patch.object(agent, "run") as loop, mock.patch("ctx.made.keep") as kept:
            reply = agent.answer_for("sharpen this tweet: kettles are a tax on patience", keep=False)
        e.assert_called_once()
        small.assert_not_called()
        loop.assert_not_called()
        self.assertEqual(reply["path"], "voice")
        kept.assert_called_once()                                                    # what was written for the owner is kept as a document
        with mock.patch.object(voice, "enhance", return_value=None), mock.patch.object(agent, "run", return_value=None) as loop:
            agent.answer_for("sharpen this tweet: kettles are a tax on patience", keep=False)
        loop.assert_called_once()                                                    # nothing measured: the ordinary path answers


class Found(unittest.TestCase):
    def test_his_nearest_posts_and_what_he_saved(self):
        with mock.patch.object(voice, "posts", lambda fresh=False: SHORT):
            got = voice.nearest("kettles and patience", "x_posts", most=6)
        self.assertEqual(sorted(got), ["form", "saved", "subject"])
        self.assertTrue(got["form"] and all(r["who"] == "me" and "likes" in r for r in got["form"]))
        self.assertTrue(all(r["src"] in voice.SAVED for r in got["saved"]))
        with mock.patch.object(voice, "posts", lambda fresh=False: SHORT):
            held = voice.nearest("kettles and patience", "x_posts", most=6, skip=[r["id"] for r in SHORT[:24]])
        self.assertFalse({r["id"] for r in held["form"]} & {r["id"] for r in SHORT[:24]})
