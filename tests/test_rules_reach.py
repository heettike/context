"""The owner's rules, the never list and a forget hold for every way a row can be reached, and for what was kept from
before they were made: an answer kept from an earlier ask, a row fetched by its id, the wiki build's own reading, and
the copies of a forgotten row in the per-source files and the caches. The archive is the made-up one; no model is called."""
import json, os, shutil, tempfile, unittest
from unittest import mock
from tests import fixture
from ctx import agent, api, paths, rules, semantic, wiki

GRACE = ("kettle memo", "kalam wrote about rockets", "milte hain kal subah", "The quorum vote passed, with")


class Base(unittest.TestCase):
    def setUp(self):
        fixture.write()
        self.tmp = tempfile.mkdtemp(prefix="ctx-reach-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for mod, name in ((rules, "FILE"), (rules, "GONE"), (api, "NEVER"), (api, "CONF")):
            p = mock.patch.object(mod, name, os.path.join(self.tmp, name.lower() + ".json"))
            p.start()
            self.addCleanup(p.stop)
        rules._mem.clear()
        self.addCleanup(rules._mem.clear)

    def leave_out(self, **target):
        r = rules.save({"kind": "leave_out", "said": "made up", "target": target})
        self.assertNotIn("error", r, r)
        return r


class Kept(Base):
    def keep(self, question):
        path = agent._kept(question, None, "quick")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"answer": "grace said the kettle memo was late [1]", "cites": [{"id": "W2"}]}, f)
        return path

    def test_an_answer_kept_before_a_rule_is_not_handed_back_after_it(self):
        q = "what did grace say about the kettle memo"
        changes = (lambda: api.set_never(people=["grace hopper"]), lambda: api.set_never(sources=["whatsapp"]), lambda: api.set_never(sources=[], people=[]),
                   lambda: self.leave_out(threads=["whatsapp:grace hopper"]), lambda: rules.turn(rules.listing()[0]["id"], False), lambda: rules.remove(rules.listing()[0]["id"]))
        for n, change in enumerate(changes):
            path = self.keep(q)
            self.assertEqual(agent.answer_for(q)["path"], "kept", n)             # the same question on the same archive under the same rules: at once
            change()
            self.assertNotEqual(agent._kept(q, None, "quick"), path, n)          # it would not be looked for under that name again
            self.assertFalse(os.path.exists(path), n)                            # and it is not left on disk either
            with mock.patch.object(agent, "run", lambda *a, **k: None), mock.patch.object(agent, "lean", lambda *a, **k: None, create=True):
                self.assertNotEqual((agent.answer_for(q, keep=True) or {}).get("path"), "kept", n)

    def test_the_name_changes_with_the_content_of_the_rules_not_their_date(self):
        a = rules.stamp()
        api.set_never(people=["grace hopper"])
        b = rules.stamp()
        os.utime(api.NEVER, (1, 1))
        self.assertEqual(rules.stamp(), b)
        self.assertNotEqual(a, b)
        api.set_never(people=[])
        self.leave_out(sources=["apple_notes"])
        self.assertNotIn(rules.stamp(), (a, b))


class ById(Base):
    def test_a_row_reached_by_its_id_is_held_to_the_same_rules(self):
        self.assertEqual((semantic.row_by_id("W2")["thread"], semantic.row_by_id("N1")["src"], semantic.row_by_id("P1")["src"]), ("grace hopper", "apple_notes", "claude_code"))
        r = self.leave_out(threads=["whatsapp:grace hopper"])
        self.assertIsNone(semantic.row_by_id("W2"))
        self.assertTrue(semantic.row_by_id("W1"))
        rules.remove(r["id"])
        self.assertTrue(semantic.row_by_id("W2"))
        api.set_never(people=["grace hopper"], sources=["apple_notes"])
        self.assertEqual((semantic.row_by_id("W2"), semantic.row_by_id("W13"), semantic.row_by_id("N1")), (None, None, None))
        self.assertTrue(semantic.row_by_id("O1"))
        api.set_never(people=[], sources=[])
        with open(rules.GONE, "w") as f:
            json.dump({"ids": ["W3"], "by": {}}, f)
        rules._mem.clear()
        self.assertIsNone(semantic.row_by_id("W3"))                              # forgotten, and written back by a later read of its source

    def test_a_rated_row_that_a_rule_leaves_out_is_not_put_in_front_of_a_search(self):
        from ctx import answer
        fb = mock.Mock(yes=["W2"], near=["W3", "W1"], no=set())                 # the owner once marked her lines right for this question
        rows, yes, near = answer._rated([], fb)
        self.assertEqual((sorted(r["id"] for r in rows), yes, near), (["W1", "W2", "W3"], {"W2"}, {"W3", "W1"}))
        self.leave_out(threads=["whatsapp:grace hopper"])
        rows, yes, near = answer._rated([], fb)
        self.assertEqual(([r["id"] for r in rows], yes, near), (["W1"], set(), {"W1"}))


class WikiBuild(Base):
    def units(self):
        return {uid: [l for _, l in lines] for uid, _, lines in wiki._units(None, [])}

    def test_the_build_reads_no_note_post_or_prompt_the_rules_leave_out(self):
        got = self.units()
        self.assertEqual(sorted(got), ["docs/apple_notes", "docs/gdrive", "docs/obsidian", "docs/saved", "work/prompts"])
        self.assertTrue(any("pottery is how i rest" in l for l in got["docs/apple_notes"]))
        self.leave_out(sources=["apple_notes"])
        got = self.units()
        self.assertNotIn("docs/apple_notes", got)
        self.assertNotIn("pottery is how i rest", json.dumps(got))
        api.set_never(sources=["x_bookmarks", "claude_code"])
        got = self.units()
        self.assertNotIn("work/prompts", got)
        self.assertNotIn("pottery kilns", json.dumps(got))
        self.assertTrue(any("saved reel" in l for l in got["docs/saved"]))       # what no rule names is still read
        api.set_never(sources=[])
        with open(rules.GONE, "w") as f:
            json.dump({"ids": ["O1"], "by": {}}, f)
        rules._mem.clear()
        self.assertNotIn("docs/obsidian", self.units())

    def test_the_count_of_messages_by_month_leaves_them_out_too_and_is_counted_again_when_a_rule_changes(self):
        from ctx import answer

        class B(wiki.Base):
            def __init__(self):
                self._act, self.idx = None, answer._thread_index()
        made = os.path.join(paths.HOME, "cache", "wiki")
        self.addCleanup(shutil.rmtree, made, True)
        tid = "whatsapp:grace hopper"
        self.assertIn(tid, B().activity().get("2025-06", {}))
        self.leave_out(threads=[tid])
        self.assertFalse(any(tid in m for m in B().activity().values()))
        rules.remove(rules.listing()[0]["id"])
        self.assertIn(tid, B().activity().get("2025-06", {}))


class DeepRead(Base):
    def units(self):
        from ctx import deep
        return {k: [r[3] for r in rows or ()] for k, _, rows in deep.units() if not k.startswith("chat:")}

    def test_the_close_read_sends_no_note_or_prompt_the_rules_leave_out(self):
        docs, prompts = os.path.join(self.tmp, "docs.jsonl"), os.path.join(self.tmp, "prompts.jsonl")
        with open(docs, "w") as f:
            for i in range(3):
                f.write(json.dumps({"id": "DN%d" % i, "src": "apple_notes", "ts": "2025-01-0%dT10:00:00Z" % (i + 1), "title": "glaze", "text": "glaze note %d" % i}) + "\n")
        with open(prompts, "w") as f:
            for i in range(3):
                f.write(json.dumps({"id": "DP%d" % i, "src": "claude_code", "ts": "2025-02-0%dT10:00:00Z" % (i + 1), "thread": "kiln", "text": "kiln prompt %d" % i}) + "\n")
        with mock.patch.object(paths, "DOCS", docs), mock.patch.object(paths, "PROMPTS", prompts):
            self.assertEqual(sorted(self.units()), ["notes:apple_notes", "work:kiln"])
            self.leave_out(sources=["apple_notes"])
            self.assertEqual(sorted(self.units()), ["work:kiln"])
            api.set_never(sources=["claude_code"])
            self.assertEqual(self.units(), {})
            api.set_never(sources=[])
            rules.remove(rules.listing()[0]["id"])
            with open(rules.GONE, "w") as f:
                json.dump({"ids": ["DP0"], "by": {}}, f)
            rules._mem.clear()
            self.assertEqual(sorted(self.units()), ["notes:apple_notes"])        # one prompt forgotten leaves two: fewer than a unit is made of

    def test_what_the_close_read_wrote_from_a_row_the_rules_leave_out_is_not_handed_on(self):
        from ctx import deep
        d = os.path.join(self.tmp, "deep")
        os.makedirs(d)
        with open(os.path.join(d, "facts.jsonl"), "w") as f:            # written before any rule, from her line and from the owner's own
            f.write(json.dumps({"s": "kettle memo", "p": "was", "o": "late per grace", "when": "2025-06-01", "ids": ["W2"]}) + "\n")
            f.write(json.dumps({"s": "kettle fund", "p": "closes", "o": "friday", "when": "2025-06-01", "ids": ["W1"]}) + "\n")
        deep._mem.clear()
        self.addCleanup(deep._mem.clear)
        with mock.patch.object(deep, "DIR", d):
            said = lambda: deep.lookup("kettle memo late grace")[0] + deep.lookup("kettle fund closes friday")[0]
            self.assertIn("late per grace", said())
            self.assertIn("friday", said())
            self.assertEqual(sorted(u["id"] for u in deep.key_units()), ["W1", "W2"])
            r = self.leave_out(threads=["whatsapp:grace hopper"])
            self.assertNotIn("late per grace", said())
            self.assertIn("friday", said())
            self.assertEqual([u["id"] for u in deep.key_units()], ["W1"])
            rules.remove(r["id"])
            self.assertIn("late per grace", said())
            with open(rules.GONE, "w") as f:
                json.dump({"ids": ["W1"], "by": {}}, f)
            rules._mem.clear()
            self.assertNotIn("friday", said())                               # forgotten: what was written from it goes with it


class Forgotten(Base):
    def holding(self, skip=("backups",)):
        """Every file of the archive, its per-source files, its caches and its backups that still holds one of her lines.
        (Pages a model wrote and the owner's own corrections are another matter: docs/SECURITY.md says what stays in those.)"""
        out = []
        for root, dirs, files in os.walk(paths.HOME):
            if root == paths.HOME:
                dirs[:] = [d for d in dirs if d in ("parts", "cache", "backups")]
            dirs[:] = [d for d in dirs if d not in skip]
            for f in files:
                try:
                    with open(os.path.join(root, f), "rb") as fh:
                        blob = fh.read()
                except OSError:
                    continue
                if any(g.encode() in blob for g in GRACE):
                    out.append(os.path.relpath(os.path.join(root, f), paths.HOME))
        return sorted(out)

    def test_a_forgotten_row_is_left_in_no_per_source_file_and_no_cache(self):
        from ctx import answer, mcp, wordindex
        home = paths.HOME
        parts, sem, kept = os.path.join(home, "parts"), os.path.join(home, "cache", "semantic"), os.path.join(home, "cache", "agent", "answers")
        made = [p for p in (parts, sem, os.path.join(home, "cache", "agent"), os.path.join(home, "backups")) if not os.path.exists(p)]
        mine = [os.path.join(parts, "whatsapp.jsonl"), os.path.join(parts, "claude_code.jsonl")] + [os.path.join(sem, n) for n in ("units.jsonl", "terms.txt", "meta.json", "vectors.f32", "hashes.txt")]

        def tidy():             # nothing this test wrote is left for another: a per-source file left behind would stand for messages.jsonl in every test after
            for p in mine:
                if os.path.lexists(p):
                    os.remove(p)
            for p in made:
                shutil.rmtree(p, True)
            fixture.write()
            fixture.index()
        self.addCleanup(tidy)
        for p in (parts, sem, kept):
            os.makedirs(p, exist_ok=True)
        rows = fixture.rows()
        with open(os.path.join(parts, "whatsapp.jsonl"), "w") as f:              # the per-source file the archive is put together from
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows["messages.jsonl"] if r["src"] == "whatsapp")
        with open(os.path.join(parts, "claude_code.jsonl"), "w") as f:           # prompts: not what a rule targets, left as it is
            f.write(json.dumps(dict(rows["prompts.jsonl"][0], text="i quoted her: kalam wrote about rockets")) + "\n")
        with open(os.path.join(sem, "units.jsonl"), "w") as f:                   # the search index's text side, as a build leaves it
            f.write(json.dumps({"h": "abc", "k": "win", "src": "whatsapp", "text": "grace hopper: kalam wrote about rockets", "ids": ["W3"]}) + "\n")
        for name, body in (("terms.txt", b"kalam\nrockets\n"), ("meta.json", b"{}"), ("vectors.f32", b"\x00" * 2048), ("hashes.txt", b"abc\n")):
            with open(os.path.join(sem, name), "wb") as f:
                f.write(body)
        with open(os.path.join(kept, "0" * 24 + ".json"), "w") as f:
            json.dump({"answer": "she said: kalam wrote about rockets"}, f)
        fixture.index()
        mcp.call("search", {"query": "kalam; kettle"})
        mcp.call("stats", {"what": "people"})
        self.assertTrue({"parts/whatsapp.jsonl", "messages.jsonl", "cache/semantic/units.jsonl"} <= set(self.holding()))
        r = rules.save({"kind": "forget", "said": "delete my chat with grace hopper for good", "target": {"threads": ["whatsapp:grace hopper"]}})
        self.assertEqual(r["affects"]["rows"], 4)
        self.assertEqual(self.holding(), ["parts/claude_code.jsonl"])            # only what the owner typed to an agent themselves, which no rule reaches
        self.assertEqual(sorted(os.listdir(sem)), ["hashes.txt", "vectors.f32"])     # numbers under a hash of their text: kept, so the next build embeds only what changed
        self.assertFalse(os.path.exists(os.path.join(home, "cache", "agent")))
        self.assertNotIn(b"grace", open(os.path.join(home, "cache", "threads.idx"), "rb").read() if os.path.exists(os.path.join(home, "cache", "threads.idx")) else b"")
        with open(os.path.join(parts, "whatsapp.jsonl")) as f:
            left = [json.loads(l)["id"] for l in f]
        self.assertEqual((len(left), {"W2", "W3", "W4", "W13"} & set(left)), (len([x for x in rows["messages.jsonl"] if x["src"] == "whatsapp"]) - 4, set()))
        kept = [p for p in self.holding(skip=()) if p.startswith("backups/forgotten-")]      # the one copy kept on purpose, so the rule can be taken back
        self.assertEqual(kept, ["backups/" + os.path.relpath(os.path.join(r["backup"], "rows.jsonl"), os.path.join(home, "backups"))])
        # the source is read again and writes them into its own file: the sweep takes them out of both again
        with open(os.path.join(parts, "whatsapp.jsonl"), "a") as f:
            f.write(json.dumps(next(x for x in rows["messages.jsonl"] if x["id"] == "W3")) + "\n")
        with open(paths.MESSAGES, "a") as f:
            f.write(json.dumps(next(x for x in rows["messages.jsonl"] if x["id"] == "W3")) + "\n")
        self.assertEqual(rules.sweep(), 1)
        self.assertEqual(self.holding(), ["parts/claude_code.jsonl"])
        # taking the rule away within thirty days puts them back, in the per-source file as well
        got = rules.remove(r["id"])
        self.assertEqual(got["restored"], 4)
        with open(os.path.join(parts, "whatsapp.jsonl")) as f:
            self.assertTrue({"W2", "W3", "W4", "W13"} <= {json.loads(l)["id"] for l in f})
        self.assertTrue(semantic.row_by_id("W3"))


if __name__ == "__main__":
    unittest.main()
