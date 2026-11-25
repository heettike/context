"""Search by meaning: units, the index, fusion, tiers, ratings. The embedding helper is replaced by a fake that
hashes words into a vector, so nothing here needs a swift compiler. Every row is made up."""
import array, hashlib, json, math, os, re, shutil, unittest
from tests import files as _f
from unittest import mock
from tests import fixture
from ctx import answer, llm, paths, semantic
from tests.test_answer import KEYS, model

fixture.write()
NEAR = {"film": [("clip", 0.6)], "money": [("fund", 0.55)], "glaze": [("glazing", 0.6)]}        # what the word vectors would say


def fake_embed(texts):
    """Deterministic: each word adds to one of 512 places. Texts that share words are close."""
    out = array.array("f")
    for t in texts:
        v = [0.0] * semantic.DIM
        for w in semantic.tokens(t):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % semantic.DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.extend(x / n for x in v)
    return out.tobytes()


def fake_ask(question, words, name, vectors, emb="test", dim=512):
    q = array.array("f")
    q.frombytes(fake_embed([question if isinstance(question, str) else " ".join(question)]))
    cos = array.array("f")
    if vectors and os.path.exists(vectors):
        m = array.array("f")
        with open(vectors, "rb") as f:
            m.frombytes(f.read())
        for i in range(len(m) // semantic.DIM):
            cos.append(sum(a * b for a, b in zip(q, m[i * semantic.DIM:(i + 1) * semantic.DIM])))
    return {w: NEAR[w] for w in words if w in NEAR}, (cos if len(cos) else None)


def clean():
    shutil.rmtree(semantic.DIR, ignore_errors=True)
    if os.path.exists(semantic.FEEDBACK):
        os.remove(semantic.FEEDBACK)
    semantic._open.clear()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        clean()
        cls.patches = [mock.patch.object(semantic, "ask_helper", fake_ask), mock.patch.object(semantic, "helper", lambda: "")]
        for p in cls.patches:
            p.start()
        cls.calls = []

        def emb(texts):
            cls.calls.append(len(texts))
            return fake_embed(texts)
        cls.emb = staticmethod(emb)
        cls.meta = semantic.build(embedder=emb, say=lambda **kw: None, workers=1)

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()
        clean()         # the other test files expect an archive with no index


class Units(unittest.TestCase):
    def test_windows_overlap_and_cover_every_message(self):
        msgs = ["x" * 50] * 37
        ws = semantic.windows(msgs)
        self.assertEqual(ws[0][0], 0)
        self.assertEqual(ws[-1][1], 37)
        for (a, b), (c, d) in zip(ws, ws[1:]):
            self.assertEqual(c, b - semantic.OVERLAP)           # two messages shared with the window before
            self.assertLessEqual(b - a, semantic.WIN_MSGS)
        self.assertLessEqual(max(sum(len(m) for m in msgs[a:b]) for a, b in ws), semantic.WIN_CHARS)

    def test_new_messages_leave_earlier_windows_alone(self):
        msgs = [f"message number {n} about the garden" for n in range(40)]
        before, after = semantic.windows(msgs), semantic.windows(msgs + ["one more", "and another"])
        self.assertEqual(before[:-1], after[:len(before) - 1])

    def test_one_long_message_is_its_own_window(self):
        self.assertEqual(semantic.windows(["a" * 5000, "b"]), [(0, 1), (1, 2)])

    def test_chunks_overlap_and_end(self):
        text = " ".join(f"word{n}" for n in range(600))
        parts = semantic.chunks(text)
        self.assertGreater(len(parts), 3)
        self.assertTrue(all(len(p) <= semantic.CHUNK for p in parts))
        self.assertTrue(text.endswith(parts[-1]))
        self.assertIn(parts[1].split()[0], parts[0])            # the second piece starts inside the first
        self.assertEqual(semantic.chunks("short"), ["short"])
        self.assertEqual(semantic.chunks(""), [])


class Built(Base):
    def test_every_source_is_in_the_index(self):
        st = semantic.status()
        for src in ("whatsapp", "telegram", "instagram", "instagram_likes", "x_bookmarks", "instagram_saved", "apple_notes", "obsidian",
                    "gdrive", "browser_history", "claude_code", "codex"):
            self.assertGreater(st["per_source"][src]["units"], 0, src)
        self.assertEqual(st["per_source"]["browser_history"]["vectors"], 0)       # a title only: found by its words, not embedded
        self.assertEqual(st["per_source"]["x_bookmarks"]["vectors"], st["per_source"]["x_bookmarks"]["units"])
        self.assertEqual(st["pending"], 0)

    def test_second_run_embeds_nothing_and_a_new_row_only_itself(self):
        n = len(self.calls)
        semantic.build(embedder=self.emb, say=lambda **kw: None, workers=1)
        self.assertEqual(len(self.calls), n)
        with open(paths.DOCS, "a") as f:
            f.write(json.dumps(fixture.doc("NEW1", "a made-up note about growing saffron on a balcony", "apple_notes", title="saffron")) + "\n")
        try:
            semantic.build(embedder=self.emb, say=lambda **kw: None, workers=1)
            self.assertEqual(sum(self.calls[n:]), 1)
            self.assertEqual(semantic.search("saffron on the balcony", k=5)[0]["id"], "NEW1")
        finally:
            fixture.write()
            semantic.build(embedder=self.emb, say=lambda **kw: None, workers=1)

    def test_a_stopped_run_keeps_what_it_did(self):
        clean()
        seen = []

        def dies(texts):
            if len(seen) >= 2:
                raise RuntimeError("stopped")
            seen.append(len(texts))
            return fake_embed(texts)
        with self.assertRaises(RuntimeError):
            semantic.build(embedder=dies, say=lambda **kw: None, workers=1, batch=50)
        kept = len(semantic._known())
        self.assertEqual(kept, 100)
        self.assertTrue(semantic.ready())                           # searchable by words while vectors are missing
        n = len(self.calls)
        meta = semantic.build(embedder=self.emb, say=lambda **kw: None, workers=1)
        self.assertEqual(sum(self.calls[n:]) + kept, meta["vectors"])
        self.assertEqual(meta["pending"], 0)

    def test_row_shape_and_filters(self):
        rows = semantic.search("pottery kilns", k=30)
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(set(r), {"id", "src", "ts", "thread", "who", "text", "url", "score"})
            self.assertTrue(0 <= r["score"] <= 1)
        self.assertEqual({r["src"] for r in semantic.search("pottery", k=30, src="x_bookmarks")}, {"x_bookmarks"})
        self.assertTrue(all(r["who"] == "saved" for r in semantic.search("pottery", k=30, who="saved")))
        self.assertEqual(semantic.search("harbour lease clause", k=10, after="2031-01"), [])

    def test_a_neighbour_in_meaning_finds_a_row_with_none_of_the_words(self):
        with open(paths.MESSAGES, "a") as f:
            f.write(json.dumps(fixture.msg("CL1", "here is the clip from the regatta", thread="otto")) + "\n")
        try:
            semantic.build(embedder=self.emb, say=lambda **kw: None, workers=1)
            self.assertEqual(answer.search([["film", "regatta"]])[0], [])                 # word matching: nothing
            self.assertEqual(semantic.search("film of the boat race", k=5)[0]["id"], "CL1")
        finally:
            fixture.write()
            semantic.build(embedder=self.emb, say=lambda **kw: None, workers=1)

    def test_words_spread_over_a_window_still_match_it(self):
        with open(paths.MESSAGES, "a") as f:
            f.write(json.dumps(fixture.msg("SP1", "the walrus invoice is overdue", thread="ines", ts="2025-06-01T10:00:00Z")) + "\n")
            f.write(json.dumps(fixture.msg("SP2", "paid it, receipt https://example.com/r/77", who="me", thread="ines", ts="2025-06-01T10:01:00Z")) + "\n")
        try:
            semantic.build(embedder=self.emb, say=lambda **kw: None, workers=1)
            got = semantic.find("walrus invoice receipt", k=5, link=True)
            self.assertEqual({r["id"] for r in got["rows"][:2]}, {"SP1", "SP2"})         # no single row holds all three words
            self.assertIn("whatsapp:ines", got["windows"])
        finally:
            fixture.write()
            semantic.build(embedder=self.emb, say=lambda **kw: None, workers=1)

    def test_cover(self):
        q = semantic.Query("film about money")
        self.assertEqual(q.cover("nothing related"), 0)
        self.assertGreater(q.cover("a film on money"), q.cover("a clip on a fund"))
        self.assertGreater(q.cover("a clip on a fund"), 0)


class Fusion(unittest.TestCase):
    def test_reciprocal_rank_fusion(self):
        a = [{"id": "A"}, {"id": "B"}, {"id": "C"}]
        b = [{"id": "C", "score": 0.9}, {"id": "A", "score": 0.5}, {"id": "D", "score": 0.4}]
        out = semantic.fuse([a, b])
        self.assertEqual([r["id"] for r in out], ["A", "C", "B", "D"])                   # in both lists beats high in one
        self.assertEqual(out[0]["score"], 0.5)
        self.assertEqual(len({r["id"] for r in out}), 4)
        self.assertEqual(semantic.fuse([a, []])[0]["id"], "A")

    def test_tiers(self):
        rows = [{"id": str(n)} for n in range(70)]
        rel = {str(n): (0.9 if n < 15 else 0.4 if n < 25 else 0.05) for n in range(70)}
        strong, maybe, dropped = semantic.tiers(rows, rel)
        self.assertEqual(len(strong), 15)                                                # 15 good rows, not 70 weak ones
        self.assertEqual(len(maybe), 10)
        self.assertEqual(dropped, 45)
        strong, maybe, dropped = semantic.tiers(rows, rel, exempt={"69"})
        self.assertIn("69", [r["id"] for r in maybe])                                    # a named source's row is never dropped
        self.assertEqual(semantic.tiers(rows, {}), ([], [], 70))
        strong, maybe, dropped = semantic.tiers(rows, {str(n): 0.05 for n in range(70)})
        self.assertEqual(strong, [])                                                     # nothing is strong when everything is faint


class Ratings(Base):
    def setUp(self):
        if os.path.exists(semantic.FEEDBACK):
            os.remove(semantic.FEEDBACK)

    def test_rating_file_and_stats(self):
        line = semantic.rate("what is the kettle fund", "W1", True)
        semantic.rate("what is the kettle fund", "W2", False, kind="maybe")
        self.assertEqual((line["id"], line["ok"], line["src"], line["tid"]), ("W1", True, "whatsapp", "whatsapp:ada lovelace"))
        rows = [json.loads(l) for l in _f.lines(semantic.FEEDBACK)]
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(rows[0]), {"q", "qh", "id", "ok", "kind", "src", "tid", "at"})
        st = semantic.rate_stats()
        self.assertEqual((st["ratings"], st["yes"], st["no"], st["maybe_rated"], st["questions"]), (2, 1, 1, 1, 1))

    def test_no_excludes_and_yes_promotes_for_the_same_question(self):
        q = "pottery kilns thread"
        first = [r["id"] for r in semantic.find(q, k=10)["rows"]]
        gone = first[0]
        semantic.rate(q, gone, False)
        semantic.rate("kilns pottery thread?", "N1", True)                              # the same question, reworded
        fb = semantic.feedback(q)
        self.assertEqual((fb.no, fb.yes), ({gone}, ["N1"]))
        self.assertNotIn(gone, [r["id"] for r in semantic.find(q, k=10, fb=fb)["rows"]])
        rows, yes, near = answer._rated([{"id": gone, "src": "x", "text": ""}, {"id": "Z", "src": "x", "text": ""}], fb)
        self.assertEqual([r["id"] for r in rows], ["N1", "Z"])                           # the wrong row is out, the right one is first
        self.assertEqual(yes, {"N1"})
        self.assertEqual(semantic.feedback("something else entirely").no, set())         # another question is not touched
        semantic.rate(q, gone, True)                                                     # the latest rating of a row wins
        self.assertEqual(semantic.feedback(q).no, set())

    def test_yes_on_a_maybe_is_found_by_a_nearby_question(self):
        semantic.rate("which pottery studio did i shortlist", "O1", True, kind="maybe")
        fb = semantic.feedback("pottery studio near the river")
        self.assertEqual(fb.near, ["O1"])
        self.assertEqual(fb.yes, [])
        rows, yes, near = answer._rated([{"id": "Z", "src": "x", "text": ""}], fb)
        self.assertEqual(([r["id"] for r in rows], near), (["Z", "O1"], {"O1"}))
        self.assertEqual(semantic.feedback("harbour lease").near, [])

    def test_priors_are_small_and_bounded(self):
        for n in range(40):
            semantic.rate(f"question number {n} zebra{n}", f"L{n}", False)               # one loud thread, marked wrong 40 times
        for n in range(40):
            semantic.rate(f"another question {n} yak{n}", f"B{n % 3}", True)
        fb = semantic.feedback("lantern")
        self.assertEqual(fb.prior("whatsapp", "whatsapp:loud group"), -semantic.PRIOR_SRC - semantic.PRIOR_THREAD)
        self.assertEqual(fb.prior("x_bookmarks"), semantic.PRIOR_SRC)
        self.assertLessEqual(abs(fb.prior("whatsapp", "whatsapp:loud group")), 0.2)
        semantic.rate("q", "W1", True)
        self.assertAlmostEqual(semantic.feedback("lantern").prior("nowhere", "whatsapp:ada lovelace"), semantic.STEP)
        plain = {r["id"]: r["score"] for r in semantic.find("lantern festival plan", k=60)["rows"]}
        sunk = {r["id"]: r["score"] for r in semantic.find("lantern festival plan", k=60, fb=fb)["rows"]}
        both = [i for i in plain if i in sunk and i.startswith("L")]
        self.assertTrue(both and all(sunk[i] < plain[i] for i in both))                  # the thread the owner keeps rejecting sinks


class Answers(Base):
    def setUp(self):
        if os.path.exists(semantic.FEEDBACK):
            os.remove(semantic.FEEDBACK)
        # words and their neighbours only: in so small an archive the fake vectors would call every row close
        p = mock.patch.object(semantic, "ask_helper", lambda question, words, name, vectors, *a: ({w: NEAR[w] for w in words if w in NEAR}, None))
        p.start()
        self.addCleanup(p.stop)

    def ask(self, q, plan, reply):
        patch, self.calls_ = model(plan, reply)
        with patch:
            out = answer.answer(q)
        self.assertEqual(set(out), KEYS)
        return out, self.calls_[-1]["prompt"]

    def test_tiers_reach_the_model_and_the_reply(self):
        out, prompt = self.ask("celadon glaze pottery", {"probes": [["pottery"]]},
                               {"answer": "a celadon glaze [R1].", "cites": ["R1"], "confidence": 4, "strength": "strong",
                                "maybe": [{"id": "IS1", "why": "a saved reel on glazing", "score": 0.4}, {"id": "R1", "why": "cited", "score": 1}, {"id": "nope"}]})
        rows = re.split(r"## (?:other )?rows", prompt, maxsplit=1)[1].split("## maybe rows")[0]
        self.assertIn("[R1]", rows)
        self.assertIn("## maybe rows", prompt)
        self.assertRegex(prompt, r"\d+ more rows matched only weakly and were left out")
        self.assertLess(rows.count("\n["), 45)                                           # not 70 rows of chat on one common word
        self.assertEqual(out["strength"], "strong")
        self.assertEqual([m["id"] for m in out["maybe"]], ["IS1"])                       # never a cited row, never an unknown id
        self.assertEqual(set(out["maybe"][0]), {"id", "src", "ts", "thread", "who", "text", "url", "why", "score", "sender"})
        self.assertEqual(out["cites"][0]["id"], "R1")
        self.assertEqual(set(out["cites"][0]), {"id", "src", "ts", "thread", "who", "text", "url", "sender"})

    def test_weak_when_the_model_cites_nothing(self):
        out, prompt = self.ask("celadon glaze pottery", {"probes": [["pottery"]]}, {"answer": "i am not sure.", "cites": []})
        self.assertEqual(out["strength"], "weak")
        self.assertTrue(out["maybe"])                                                    # the best of the maybe tier is offered anyway
        self.assertLessEqual(len(out["maybe"]), 6)

    def test_a_rating_changes_the_next_answer(self):
        q = "celadon glaze pottery"
        semantic.rate(q, "R1", False)
        semantic.rate(q, "G1", True)
        out, prompt = self.ask(q, {"probes": [["pottery"]]}, {"answer": "see the budget [G1].", "cites": ["G1"]})
        rows = re.split(r"## (?:other )?rows", prompt, maxsplit=1)[1].split("## maybe rows")[0]
        self.assertNotIn("[R1]", prompt)                                                 # marked wrong: gone
        self.assertEqual(rows.split("\n")[1][:4], "[G1]")                                # marked right: the first strong row
        self.assertEqual(out["strength"], "strong")


class Spelling(Base):
    def test_fold(self):
        self.assertEqual({semantic.fold(w) for w in ("nahin", "nahi", "nahiin")}, {"nahi"})
        self.assertEqual(semantic.fold("habeebi"), semantic.fold("habibi"))             # the same rules, whichever language is written in latin letters
        self.assertEqual(semantic.fold("arigatou"), semantic.fold("arigato"))
        self.assertEqual(semantic.fold("inshaallah"), semantic.fold("inshallah"))
        self.assertEqual(semantic.fold("kya"), semantic.fold("kia"))
        self.assertEqual(semantic.fold("zyada"), semantic.fold("jyada"))
        self.assertEqual(semantic.fold("phir"), semantic.fold("fir"))
        self.assertNotEqual(semantic.fold("bahut"), semantic.fold("bohot"))             # no rule guesses a vowel
        self.assertEqual(semantic.fold("पढ़ाई"), "पढ़ाई")

    def test_another_spelling_finds_the_row(self):
        with open(paths.MESSAGES, "a") as f:
            f.write(json.dumps(fixture.msg("HG1", "shaadi ki tayyari zyada ho gayi", thread="uma")) + "\n")
        try:
            semantic.build(embedder=self.emb, say=lambda **kw: None, workers=1)
            with mock.patch.object(semantic, "ask_helper", lambda *a: ({}, None)):
                self.assertEqual(semantic.search("shadi jyada", k=3)[0]["id"], "HG1")
                with mock.patch.object(semantic, "FOLD", False):
                    self.assertEqual(semantic.search("shadi jyada", k=3), [])
        finally:
            fixture.write()
            semantic.build(embedder=self.emb, say=lambda **kw: None, workers=1)

    def test_the_owners_word_list_bridges_two_languages(self):
        os.makedirs(os.path.dirname(semantic.GLOSS), exist_ok=True)
        with open(semantic.GLOSS, "w") as f:
            json.dump({"mitti": ["clay", "pottery"]}, f)
        try:
            with mock.patch.object(semantic, "GLOSSED", True):
                self.assertIn("pottery", semantic.Query("mitti").groups[0][2])
                self.assertIn("mitti", semantic.Query("pottery").groups[0][2])
            self.assertNotIn("mitti", semantic.Query("pottery").groups[0][2])           # off unless switched on
        finally:
            os.remove(semantic.GLOSS)


class Embedders(unittest.TestCase):
    """A stub of ollama's local http api: 3 numbers per text, from its length and first letters."""

    @classmethod
    def setUpClass(cls):
        import http.server, threading
        cls.seen = []

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({"models": [{"name": "bge-m3:latest"}, {"name": "llama3:latest"}]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                cls.seen.append((self.path, d["model"], len(d["input"])))
                out = [[float(len(t)), float(ord(t[0])), 1.0] for t in d["input"]]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"embeddings": out}).encode())
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.env = mock.patch.dict(os.environ, {"CTX_OLLAMA_URL": f"http://127.0.0.1:{cls.srv.server_port}", "CTX_EMBEDDER": "ollama:bge-m3"})
        cls.env.start()
        cls.h = mock.patch.object(semantic, "helper", lambda: "")
        cls.h.start()
        clean()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.env.stop()
        cls.h.stop()
        clean()

    def test_names(self):
        self.assertEqual(semantic.check_embedder("Apple")[0], "apple")
        self.assertEqual(semantic.check_embedder("ollama:bge-m3")[0], "ollama:bge-m3")
        self.assertIsNone(semantic.check_embedder("ollama:")[0])
        self.assertIsNone(semantic.check_embedder("file:relative/path")[0])
        self.assertIsNone(semantic.check_embedder("https://example.com")[0])
        self.assertEqual(semantic.embedder(), "ollama:bge-m3")
        with mock.patch.dict(os.environ, {"CTX_EMBEDDER": "nonsense"}):
            self.assertEqual(semantic.embedder(), "apple")

    def test_ollama_is_called_in_batches_on_this_mac_only(self):
        raw = semantic.embed_with(["a" * 5] * 70, "ollama:bge-m3")
        self.assertEqual(len(raw), 70 * 3 * 4)
        v = array.array("f")
        v.frombytes(raw[:12])
        self.assertAlmostEqual(sum(x * x for x in v), 1.0, places=5)                     # unit length
        self.assertEqual([n for _, _, n in self.seen[-3:]], [32, 32, 6])
        with mock.patch.dict(os.environ, {"CTX_OLLAMA_URL": "http://example.com:11434"}):
            with self.assertRaises(RuntimeError):
                semantic.embed_with(["x"], "ollama:bge-m3")

    def test_switching_keeps_units_and_words_and_each_embedders_vectors(self):
        meta = semantic.build(say=lambda **kw: None, workers=1)
        self.assertEqual((meta["embedder"], meta["dim"], meta["pending"]), ("ollama:bge-m3", 3, 0))
        self.assertGreater(meta["vectors"], 100)
        self.assertEqual(os.path.getsize(semantic._p("vectors.ollama-bge-m3.f32")), meta["vectors"] * 3 * 4)
        n = len(self.seen)
        semantic.build(say=lambda **kw: None, workers=1)
        self.assertEqual(len(self.seen), n + 1)                                          # the one-text probe for its size; nothing embedded again
        rep = semantic.embedder_report()
        self.assertEqual((rep["embedder"], rep["indexed_with"], rep["dims"], rep["needs_index"]), ("ollama:bge-m3", "ollama:bge-m3", 3, False))
        self.assertEqual(rep["quality"], "good, multilingual")
        self.assertEqual(rep["ollama_models_here"], ["bge-m3:latest"])
        with mock.patch.dict(os.environ, {"CTX_EMBEDDER": "apple"}):                     # back to apple, no compiler here: words only
            self.assertTrue(semantic.embedder_report()["needs_index"])
            self.assertIn("ollama:bge-m3", semantic.embedder_report()["better"])
            back = semantic.build(say=lambda **kw: None, workers=1)
            self.assertEqual((back["embedder"], back["vectors"], back["units"]), ("apple", 0, meta["units"]))
            self.assertEqual(semantic.search("celadon finish glaze", k=3)[0]["id"], "R1")
        again = semantic.build(say=lambda **kw: None, workers=1)                         # and forward again: its vectors were kept
        self.assertEqual(again["vectors"], meta["vectors"])
        self.assertEqual(len(self.seen), n + 2)

    def test_an_embedder_that_does_not_answer_leaves_a_words_only_index(self):
        with mock.patch.dict(os.environ, {"CTX_EMBEDDER": "ollama:not-pulled", "CTX_OLLAMA_URL": "http://127.0.0.1:9"}):
            said = []
            meta = semantic.build(say=lambda **kw: said.append(kw), workers=1)
        self.assertEqual(meta["vectors"], 0)
        self.assertTrue(any("did not answer" in str(x.get("phase", "")) for x in said))


class NoIndex(unittest.TestCase):
    def test_without_an_index_the_answer_is_built_from_word_matches_as_before(self):
        clean()
        self.assertFalse(semantic.ready())
        self.assertEqual(semantic.search("pottery"), [])
        self.assertEqual(semantic.status()["units"], 0)
        with mock.patch.object(semantic, "ask_helper", side_effect=AssertionError("the helper must not run")), \
             mock.patch.object(semantic, "helper", side_effect=AssertionError("nothing is compiled")):
            patch, calls = model({"probes": [["kettle"]]}, {"answer": "it closes friday [W1].", "cites": ["W1"], "confidence": 4})
            with patch:
                out = answer.answer("what is the kettle fund")
        self.assertEqual(set(out), KEYS)
        self.assertEqual(out["cites"][0]["id"], "W1")
        self.assertEqual((out["maybe"], out["strength"]), ([], "strong"))
        self.assertNotIn("## maybe rows", calls[-1]["prompt"])
        self.assertNotIn("left out", calls[-1]["prompt"])
        self.assertIn("## other rows (1 of 3 matches)", calls[-1]["prompt"])

    def test_no_compiler_means_words_only(self):
        clean()
        try:
            with mock.patch.object(semantic, "helper", lambda: ""):
                meta = semantic.build(say=lambda **kw: None)
                self.assertEqual((meta["vectors"], meta["model"]), (0, ""))
                self.assertEqual(semantic.search("celadon finish glaze", k=3)[0]["id"], "R1")
        finally:
            clean()


if __name__ == "__main__":
    unittest.main()
