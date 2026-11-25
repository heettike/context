import json, os, random, shutil, tempfile, time, unittest
from tests import files as _f
from unittest import mock
from tests import fixture
from ctx import answer, paths, wordindex

PROBES = [[["kettle", "fund"]], [["invest"]], [["kal"]], [["mine_total"]], [["whatsapp"]], [["i'll", "send"]], [["पढ़ाई"]], [["kiln", "timer"]],
          [["inventory", "script"]], [["zzzznope"]], [["kettle"]], [["pottery"]], [["pottery"], ["celadon"]], [["lantern"]], [["lantern", "festival"]],
          [["quorum"]], [["zeppelin"]], [["wheels"]], [["samovar"]], [["gazebo"]], [["harbour", "lease"]], [["on", "it"]], [["a1"]], [["me"]],
          [["example.com"]], [["https", "example"]], [["small", "talk"], ["tide"]], [["text"]], [["2025-07"]], [["day", "12"]], [["ada"], ["grace"]],
          [["ot"]], [["x"]], [["the"], ["and"], ["zeppelin"]], [["415", "555"]], [["teapot@example.com"]], [["c++"]], [["+"]], [["v700"]], [["friend", "7"]]]
KW = [{}, {"who": "me"}, {"who": "saved"}, {"who": "me_only", "limit": 5}, {"after": "2024-01", "before": "2024-12"}, {"src": "x_bookmarks"}, {"oldest": True, "limit": 9},
      {"limit": 400}]


def ix_of(path):
    """The index over a file that has no parts (the made-up archive), after a warm()."""
    wordindex.warm()
    st = os.stat(path)
    plan = wordindex.plan_for(path, st.st_size, st.st_mtime_ns)
    return plan[0][2] if plan else None


def both(probes, **kw):
    with mock.patch.dict(os.environ, {"CTX_WORD_INDEX": "0"}):
        scan = answer.search(probes, **kw)
    with mock.patch.dict(os.environ, {"CTX_WORD_INDEX": "1"}):
        fast = answer.search(probes, **kw)
    return scan, fast


class Same(unittest.TestCase):
    def setUp(self):
        wordindex.warm()

    def test_the_index_is_whole_for_the_made_up_archive(self):
        st = wordindex.status()
        self.assertTrue(st["whole"], st)
        self.assertEqual(st["files"]["messages.jsonl"]["lines"], len(fixture.rows()["messages.jsonl"]) + 1)

    def test_search_gives_the_same_rows_with_and_without_it(self):
        n = 0
        for probes in PROBES:
            for kw in KW:
                scan, fast = both(probes, **kw)
                self.assertEqual(scan, fast, (probes, kw))
                n += 1
        self.assertEqual(n, len(PROBES) * len(KW))

    def test_counts_and_thread_hits_are_the_same_too(self):
        for probes in PROBES[:20]:
            out = []
            for flag in ("0", "1"):
                counts, threads = {}, {}
                with mock.patch.dict(os.environ, {"CTX_WORD_INDEX": flag}):
                    answer.search(probes, counts=counts, threads=threads)
                out.append((counts, threads))
            self.assertEqual(out[0], out[1], probes)

    def test_every_line_that_holds_the_words_is_named(self):
        """The promise the index rests on, tried on random pieces of real lines: no matching line is ever left out."""
        rnd = random.Random(7)
        with open(paths.MESSAGES, "rb") as f:
            lines = f.read().splitlines()
        ix = ix_of(paths.MESSAGES)
        for _ in range(400):
            src = lines[rnd.randrange(len(lines))].lower()
            words = []
            for _ in range(rnd.choice((1, 1, 2, 3))):
                a = rnd.randrange(len(src))
                w = src[a:a + rnd.randrange(1, 14)].split()
                if w:
                    words.append(w[0])
            if not words:
                continue
            want = {n for n, l in enumerate(lines) if all(w in l.lower() for w in words)}
            got = ix.candidates([words])
            self.assertTrue(got is None or want <= set(got), words)

    def test_it_reads_only_the_lines_that_can_match(self):
        raw = [[b"zeppelin"]]
        with open(paths.MESSAGES, "rb") as f:
            got = list(wordindex.lines(f, paths.MESSAGES, raw))
        self.assertEqual(len(got), 1)
        self.assertIn(b"zeppelin", got[0][1])
        with open(paths.MESSAGES, "rb") as f:
            f.seek(got[0][0])
            self.assertEqual(f.readline(), got[0][1])                    # the offset is the line's place in the file
        with open(paths.MESSAGES, "rb") as f, mock.patch.dict(os.environ, {"CTX_WORD_INDEX": "0"}):
            self.assertGreater(len(list(wordindex.lines(f, paths.MESSAGES, raw))), 3000)

    def test_words_too_common_or_too_short_to_narrow_mean_every_line(self):
        ix = ix_of(paths.MESSAGES)
        self.assertIsNone(ix.candidates([[b"text"]]))                    # a field name: in every line
        self.assertIsNone(ix.candidates([[b"+"]]))                       # no letters or digits at all
        self.assertIsNone(ix.candidates([[b"zeppelin"], [b"text"]]))     # one probe that narrows nothing is enough
        self.assertEqual(len(ix.candidates([[b"text", b"zeppelin"]])), 1)

    def test_a_line_with_a_very_long_token_is_always_checked(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.jsonl")
            with open(p, "w") as f:
                f.write(json.dumps({"id": "A", "text": "plain words"}) + "\n" + json.dumps({"id": "B", "text": "q" * 200 + "needle" + "z" * 9}) + "\n")
            with mock.patch.object(wordindex, "DIR", d):
                ix = wordindex.load(wordindex.build(p))
                self.assertEqual(ix.candidates([[b"needle"]]), [1])
                self.assertEqual(ix.candidates([[b"plain"]]), [0, 1])

    def test_a_changed_file_is_read_whole_until_it_is_indexed_again(self):
        keep = _f.read(paths.MESSAGES, "rb")
        try:
            with open(paths.MESSAGES, "a") as f:
                f.write(json.dumps(fixture.msg("NEWZ", "a zeppelin again", who="me", ts="2026-01-01T10:00:00Z")) + "\n")
            self.assertFalse(wordindex.status()["files"]["messages.jsonl"]["current"])
            self.assertIn("NEWZ", [r["id"] for r in answer.search([["zeppelin"]])[0]])
            self.assertEqual(wordindex.warm(), ["messages.jsonl"])
            self.assertEqual(wordindex.warm(), [])
            scan, fast = both([["zeppelin"]])
            self.assertEqual(scan, fast)
            self.assertEqual(len(fast[0]), 2)
        finally:
            _f.write(keep, paths.MESSAGES, "wb")
            wordindex.warm()

    def test_a_damaged_index_file_is_ignored(self):
        st = os.stat(paths.DOCS)
        man = _f.load(wordindex._manifest(paths.DOCS))
        f = wordindex._file(man["segs"][0][0])
        keep = _f.read(f, "rb")
        try:
            wordindex._open.clear()
            _f.write(b"\x09\x00\x00\x00\x00\x00\x00\x00garbage!!", f, "wb")
            self.assertIsNone(wordindex.plan_for(paths.DOCS, st.st_size, st.st_mtime_ns))
            self.assertTrue(answer.search([["pottery"]], src="x_bookmarks")[0])
        finally:
            _f.write(keep, f, "wb")
            wordindex._open.clear()

    def test_a_missing_or_broken_manifest_means_the_whole_file_is_read(self):
        mf = wordindex._manifest(paths.DOCS)
        keep = _f.read(mf)
        try:
            for text in ("{nope", "[]", json.dumps({"v": 0})):
                _f.write(text, mf, "w")
                self.assertEqual(both([["pottery"]])[0], both([["pottery"]])[1])
                self.assertFalse(wordindex.status()["files"]["docs.jsonl"]["current"])
            os.remove(mf)
            self.assertTrue(answer.search([["pottery"]])[0])
        finally:
            _f.write(keep, mf, "w")
            wordindex.warm()


class Parts(unittest.TestCase):
    """The real layout: a joined file made of per-source parts, each with its own index."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ctx-parts-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        with open(paths.MESSAGES, "rb") as f:
            lines = f.read().splitlines(keepends=True)
        self.a, self.b, self.joined = (os.path.join(self.dir, n) for n in ("a.jsonl", "b.jsonl", "joined.jsonl"))
        _f.write(b"".join(lines[:1500]), self.a, "wb")
        _f.write(b"".join(lines[1500:]), self.b, "wb")
        self.join()
        self.built = []
        real = wordindex.build
        ps = [mock.patch.object(wordindex, "DIR", os.path.join(self.dir, "idx")), mock.patch.object(wordindex, "JOINED", (self.joined,)),
              mock.patch.object(wordindex, "parts_of", lambda path: [self.a, self.b]),
              mock.patch.object(wordindex, "build", lambda seg: (self.built.append(os.path.basename(seg)), real(seg))[1])]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        wordindex._open.clear()
        wordindex._plans.clear()
        self.addCleanup(wordindex._open.clear)
        self.addCleanup(wordindex._plans.clear)

    def join(self):
        _f.write(_f.read(self.a, "rb") + _f.read(self.b, "rb"), self.joined, "wb")

    def read(self, word):
        with open(self.joined, "rb") as f:
            got = list(wordindex.lines(f, self.joined, [[word]]))
            for off, line in got:
                f.seek(off)
                self.assertEqual(f.readline(), line)
        return got

    def scan(self, word):
        with open(self.joined, "rb") as f:
            return [l for l in f if word in l.lower()]

    def test_lines_come_from_both_parts_in_file_order_at_their_joined_offsets(self):
        self.assertEqual(wordindex.warm(), ["a.jsonl", "b.jsonl"])
        for word in (b"harbour", b"gazebo", b"zeppelin", b"pottery", b"lantern"):
            got = self.read(word)
            self.assertEqual([l for _, l in got if word in l.lower()], self.scan(word), word)
            self.assertEqual([o for o, _ in got], sorted(o for o, _ in got))
            self.assertLess(len(got), 400)

    def test_without_a_warm_the_whole_file_is_read(self):
        self.assertGreater(len(self.read(b"harbour")), 3000)

    def test_only_the_part_that_changed_is_indexed_again(self):
        wordindex.warm()
        with open(self.b, "ab") as f:
            f.write(json.dumps(fixture.msg("TAIL", "one more harbour line")).encode() + b"\n")
        self.join()
        self.assertGreater(len(self.read(b"harbour")), 3000)                # stale until the next warm: read whole, still right
        del self.built[:]
        self.assertEqual(wordindex.warm(), ["b.jsonl"])
        self.assertEqual(self.built, ["b.jsonl"])
        got = self.read(b"harbour")
        self.assertEqual(len([1 for _, l in got if b"harbour" in l]), 3)
        self.assertLess(len(got), 400)

    def test_a_part_written_again_with_the_same_rows_costs_nothing(self):
        wordindex.warm()
        time.sleep(0.01)
        data = _f.read(self.a, "rb")
        _f.write(data, self.a, "wb")                                      # what a collect does when nothing is new
        self.join()
        del self.built[:]
        self.assertEqual(wordindex.warm(), [])
        self.assertLess(len(self.read(b"harbour")), 400)

    def test_same_size_other_bytes_is_another_file(self):
        wordindex.warm()
        data = _f.read(self.a, "rb")
        _f.write(data.replace(b"permit", b"PERMIT"), self.a, "wb")
        self.join()
        del self.built[:]
        self.assertEqual(wordindex.warm(), ["a.jsonl"])

    def test_a_joined_file_that_is_not_its_parts_is_never_trusted(self):
        wordindex.warm()
        with open(self.joined, "ab") as f:
            f.write(b'{"id": "X", "text": "harbour stray"}\n')               # longer than the parts: a collect is half way
        self.assertGreater(len(self.read(b"harbour")), 3000)
        wordindex.warm()                                                    # warm sees the mismatch and writes no plan
        self.assertGreater(len(self.read(b"harbour")), 3000)
        self.assertEqual(len([1 for _, l in self.read(b"harbour") if b"harbour" in l]), 3)
        # same total size, parts in another order: the bytes do not line up, so no plan either
        _f.write(_f.read(self.b, "rb") + _f.read(self.a, "rb"), self.joined, "wb")
        wordindex.warm()
        self.assertGreater(len(self.read(b"harbour")), 3000)
        self.join()
        wordindex.warm()
        self.assertLess(len(self.read(b"harbour")), 400)

    def test_old_indexes_are_cleared_out(self):
        wordindex.warm()
        stale = os.path.join(wordindex.DIR, "0" * 32 + ".idx")
        _f.write(b"x", stale, "wb")
        os.utime(stale, (time.time() - 7200, time.time() - 7200))
        wordindex.warm()
        self.assertFalse(os.path.exists(stale))
        self.assertEqual(len([n for n in os.listdir(wordindex.DIR) if n.endswith(".idx")]), 2)


if __name__ == "__main__":
    unittest.main()
