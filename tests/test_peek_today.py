import json, os, subprocess, sys, time, unittest
from tests import files as _f
from unittest import mock
from tests import fixture
from ctx import collect, llm, paths, peek, schedule, today


class Peek(unittest.TestCase):
    def test_a_message_with_its_neighbours_in_order(self):
        out = peek.thread("V700", 15, 15)
        self.assertEqual((out["thread"], out["title"], out["src"], out["rows_total"], out["from"], out["to"], out["focus"]),
                         ("Ravi Anand", "Ravi Anand", "whatsapp", 3000, "2023-01-01", "2024-12-25", "V700"))
        self.assertEqual([r["id"] for r in out["rows"]], [f"V{n}" for n in range(685, 716)])
        self.assertEqual([r["id"] for r in out["rows"] if r["here"]], ["V700"])
        self.assertEqual(set(out["rows"][0]), {"id", "ts", "at", "who", "me", "sender", "text", "here"})
        self.assertEqual([r["ts"] for r in out["rows"]], sorted(r["ts"] for r in out["rows"]))
        me = next(r for r in out["rows"] if r["id"] == "V699")
        them = next(r for r in out["rows"] if r["id"] == "V700")
        self.assertEqual((me["who"], me["me"], me["sender"], them["who"], them["me"], them["sender"]), ("me", True, "", "them", False, "Ravi Anand"))
        self.assertEqual(time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(them["at"])), them["ts"][:19])

    def test_before_and_after_and_the_ends_of_a_thread(self):
        self.assertEqual([r["id"] for r in peek.thread("V700", 2, 1)["rows"]], ["V698", "V699", "V700", "V701"])
        self.assertEqual([r["id"] for r in peek.thread("V0", 5, 2)["rows"]], ["V0", "V1", "V2"])
        self.assertEqual([r["id"] for r in peek.thread("V2999", 1, 9)["rows"]], ["V2998", "V2999"])
        self.assertEqual(len(peek.thread("V700", 0, 0)["rows"]), 1)
        self.assertEqual(len(peek.thread("V1500", 10 ** 9, 10 ** 9)["rows"]), 1001)

    def test_nothing_is_masked_here(self):
        text = peek.thread("W9")["rows"]
        self.assertIn("+1 415 555 0100", next(r for r in text if r["here"])["text"])
        self.assertIn("teapot@example.com", next(r for r in text if r["here"])["text"])

    def test_a_doc_comes_whole_with_its_url(self):
        out = peek.thread("B1")
        self.assertEqual((out["src"], out["open"], out["rows_total"], len(out["rows"])), ("x_bookmarks", "https://example.com/b/1", 1, 1))
        self.assertEqual((out["rows"][0]["who"], out["rows"][0]["here"], out["rows"][0]["text"]), ("saved", True, "a thread on pottery kilns 1"))
        note = peek.thread("N1")
        self.assertEqual((note["rows"][0]["who"], note["rows"][0]["me"], note["open"], note["thread"]), ("me", True, None, "rest"))
        self.assertEqual(peek.thread("P1")["rows"][0]["me"], True)
        self.assertIn("kiln timer is done", peek.thread("S1")["rows"][0]["text"])

    def test_unknown_id(self):
        self.assertIn("error", peek.thread("NOPE123"))
        self.assertIn("error", peek.thread(""))

    def test_the_id_index_is_cached_and_follows_the_archive(self):
        peek.thread("V700")
        self.assertTrue(os.path.exists(peek.CACHE))
        with mock.patch.object(peek, "build", side_effect=AssertionError("rebuilt")):
            n = peek.thread("W1")["rows_total"]
        self.assertEqual(n, sum(1 for r in fixture.rows()["messages.jsonl"] if r["thread"] == "ada lovelace" and r["src"] == "whatsapp"))
        keep = _f.read(paths.MESSAGES, "rb")
        try:
            with open(paths.MESSAGES, "a") as f:
                f.write(json.dumps(fixture.msg("NEW1", "a brand new line", thread="ada lovelace", ts="2026-01-01T10:00:00Z")) + "\n")
            out = peek.thread("NEW1")
            self.assertEqual((out["rows"][-1]["id"], out["rows_total"]), ("NEW1", n + 1))
        finally:
            _f.write(keep, paths.MESSAGES, "wb")
        self.assertIn("error", peek.thread("NEW1"))

    def test_fast_once_the_index_exists(self):
        peek.thread("V700")
        t = time.monotonic()
        for i in (5, 900, 2500):
            peek.thread(f"V{i}", 10, 10)
        self.assertLess((time.monotonic() - t) / 3, 5)                    # about 5 ms on a quiet mac; without the index each is a read of the whole file. room for a loaded one

    def test_command_line(self):
        env = dict(os.environ, CTX_HOME=fixture.HOME, PYTHONPATH=fixture.REPO)
        run = lambda *a: subprocess.run([sys.executable, "-m", "ctx", "thread", *a], capture_output=True, text=True, env=env, cwd=fixture.REPO, timeout=60)
        out = json.loads(run("V700", "--around", "2", "--json").stdout)
        self.assertEqual([r["id"] for r in out["rows"]], ["V698", "V699", "V700", "V701", "V702"])
        out = json.loads(run("--before", "1", "--after", "0", "V700", "--json").stdout)
        self.assertEqual([r["id"] for r in out["rows"]], ["V699", "V700"])
        plain = run("V700", "--around", "1")
        self.assertEqual(plain.returncode, 0)
        self.assertIn("> 2023-", plain.stdout)
        self.assertEqual(run("NOPE", "--json").returncode, 1)
        self.assertEqual(run().returncode, 1)


NOW = time.mktime((2026, 6, 2, 9, 0, 0, 0, 0, -1))


class Today(unittest.TestCase):
    def setUp(self):
        self.extra = [fixture.msg("PR1", "i'll send the kiln invoice to mira by friday", who="me", thread="Mira Sol", ts="2026-05-30T10:00:00Z"),
                      fixture.msg("PR0", "i'll send the old thing someday", who="me", thread="Mira Sol", ts="2026-03-01T10:00:00Z"),
                      fixture.msg("YA1", "a long letter to myself about the workshop " * 12, who="me", thread="Mira Sol", ts="2024-06-03T10:00:00Z"),
                      fixture.msg("YA2", "short", who="me", thread="Mira Sol", ts="2024-06-02T10:00:00Z"),
                      fixture.msg("YA3", "their long letter, not the owner's " * 12, thread="Mira Sol", ts="2024-06-02T10:00:00Z")]
        self.docs = [fixture.doc("YN1", "a note from two years ago about why the studio matters to me and what i owe it " * 3, "apple_notes", title="why", ts="2024-06-01T09:00:00Z"),
                     fixture.doc("SV1", "a thread on kilnworks glazes and firing schedules", "x_bookmarks", url="https://example.com/sv1", ts="2026-01-05T09:00:00Z"),
                     fixture.doc("SV2", "kilnworks studio tour", "x_bookmarks", url="https://example.com/sv2", ts="2026-01-06T09:00:00Z"),
                     fixture.doc("HV2", "", "browser_history", title="opened it", url="https://example.com/sv2", ts="2026-02-01T09:00:00Z")]
        self.keep = {p: _f.read(p, "rb") for p in (paths.MESSAGES, paths.DOCS)}
        for path, rows in ((paths.MESSAGES, self.extra), (paths.DOCS, self.docs)):
            with open(path, "a") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
        self.card_file = os.path.join(fixture.HOME, "memory", "cards", "work_kilnworks.json")
        with open(self.card_file, "w") as f:
            json.dump({"_title": "kilnworks", "_kind": "project", "_to": "2026-05-20", "_mine": 50, "who": "the studio app"}, f)
        self.addCleanup(self.restore)
        self.calls = []

    def restore(self):
        for p, b in self.keep.items():
            _f.write(b, p, "wb")
        for p in (self.card_file, today.FILE):
            if os.path.exists(p):
                os.remove(p)

    def model(self, reply):
        def ask_json(system, prompt, model=None, tag=""):
            self.calls.append({"system": system, "prompt": prompt, "tag": tag, "model": model})
            if isinstance(reply, Exception):
                raise reply
            return reply
        return mock.patch.object(llm, "ask_json", ask_json)

    def test_candidates_of_each_kind_without_a_model(self):
        with mock.patch.object(llm, "ask_json", side_effect=AssertionError("no model here")):
            rows = {r["id"]: r["kind"] for r in today.candidates(NOW)}
        self.assertEqual(rows.get("PR1"), "promised")
        self.assertNotIn("PR0", rows)                                   # older than 14 days
        self.assertEqual((rows.get("YN1"), rows.get("YA1")), ("years_ago", "years_ago"))
        self.assertNotIn("YA2", rows)                                   # too short to matter
        self.assertNotIn("YA3", rows)                                   # not the owner's words
        self.assertEqual(rows.get("SV1"), "saved")
        self.assertNotIn("SV2", rows)                                   # opened again since: not "never revisited"
        self.assertNotIn("PR1", {r["id"] for r in today.candidates(NOW, spent=["PR1"])})

    def test_a_strong_pick_becomes_the_card(self):
        with self.model({"pick": "PR1", "kind": "promised", "line": "you told mira on 30 may you would send the kiln invoice by friday.", "action": "reply", "strength": 5}):
            card = today.build(NOW)["card"]
        self.assertEqual((card["id"], card["kind"], card["state"], card["action"]["label"]), ("2026-06-02-promised-1", "promised", "unread", "reply"))
        self.assertEqual((card["cite"]["id"], card["cite"]["src"], card["cite"]["who"], card["cite"]["ts"]), ("PR1", "whatsapp", "me", "2026-05-30"))
        self.assertIn("kiln invoice", card["cite"]["quote"])
        self.assertEqual((self.calls[0]["tag"], self.calls[0]["model"]), ("today", llm.FAST))
        self.assertIn("No card is better than a weak card", self.calls[0]["system"])
        self.assertIn("[PR1] promised 2026-05-30", self.calls[0]["prompt"])

    def test_the_floor(self):
        line = "you told mira you would send the kiln invoice by friday."
        for reply in ({"pick": None}, {"pick": "PR1", "line": line, "strength": 3}, {"pick": "PR1", "line": line}, {"pick": "MADE_UP", "line": line, "strength": 5},
                      {"pick": "PR1", "line": "ok", "strength": 5}, {"pick": ["PR1"], "line": line, "strength": 5}, [], "text", None):
            with self.model(reply):
                self.assertEqual(today.build(NOW, force=True), {"card": None}, reply)

    def test_made_once_a_day(self):
        with self.model({"pick": "PR1", "line": "you told mira you would send the kiln invoice by friday.", "action": "open", "strength": 4}):
            first = today.build(NOW)
            again = today.build(NOW + 3600)
            self.assertEqual(first, again)
            self.assertEqual(len(self.calls), 1)
            today.build(NOW + 86400)
            self.assertEqual(len(self.calls), 2)

    def test_done_folds_and_dismiss_removes_and_neither_comes_back(self):
        reply = {"pick": "PR1", "line": "you told mira you would send the kiln invoice by friday.", "action": "ask", "q": "what did i promise mira", "strength": 5}
        with self.model(reply), mock.patch.object(today, "_day", lambda now=None: "2026-06-02"):
            card = today.build(NOW)["card"]
            self.assertEqual(card["action"], {"label": "ask", "q": "what did i promise mira"})
            self.assertIn("error", today.mark("nope", "done"))
            self.assertEqual(today.mark(card["id"], "done")["card"]["state"], "done")
            self.assertEqual(today.get()["card"]["state"], "done")
            self.assertEqual(today.mark(card["id"], "dismissed"), {"card": None})
            self.assertEqual(today.get(), {"card": None})
        with self.model(reply):
            self.assertEqual(today.build(NOW + 86400), {"card": None})  # the model picks it again; it is no longer a candidate
            self.assertNotIn("[PR1]", self.calls[-1]["prompt"])

    def test_shown_twice_is_enough(self):
        reply = {"pick": "YN1", "line": "two years ago this week you wrote why the studio matters to you.", "action": "open", "strength": 5}
        with self.model(reply):
            self.assertTrue(today.build(NOW)["card"])
            self.assertTrue(today.build(NOW + 86400)["card"])
            self.assertEqual(today.build(NOW + 2 * 86400), {"card": None})

    def test_no_candidates_no_model_call(self):
        with self.model({"pick": "x"}), mock.patch.object(today, "candidates", lambda now, spent=(): []):
            self.assertEqual(today.build(NOW), {"card": None})
        self.assertEqual(self.calls, [])

    def test_a_model_that_fails_is_said_plainly_and_cached_reads_never_call_it(self):
        row = {"id": "PR1", "src": "whatsapp", "ts": "2026-05-30", "thread": "Mira Sol", "who": "me", "text": "i'll send it", "url": "", "kind": "promised"}
        with self.model(RuntimeError("claude: /Users/someone/x")), mock.patch.object(today, "candidates", lambda now, spent=(): [row]):
            out = today.get(cached=False)
            self.assertEqual(out["card"], None)
            self.assertNotIn("/Users", out["error"])
            n = len(self.calls)
            self.assertEqual(today.get(cached=True), {"card": None})
            self.assertEqual(len(self.calls), n)


class New(unittest.TestCase):
    def test_ids_are_read_without_parsing(self):
        self.assertEqual(len(collect._ids(paths.PROMPTS)), 1)
        self.assertEqual(collect._ids("/nonexistent"), set())

    def test_collect_one_counts_rows_that_were_not_there(self):
        calls = {"n": 0}

        def reader(days, out):
            calls["n"] += 1
            ids = ["a", "b"] if calls["n"] == 1 else ["a", "b", "c", "d", "e"] if calls["n"] == 2 else ["a", "b", "c", "d", "e"]
            for i in ids:
                out.write(json.dumps({"id": "ZZ" + i, "src": "ztest", "ts": "2026-01-01T00:00:00Z", "title": "", "text": "zeta " + i}) + "\n")
            return len(ids)
        keep = {p: (_f.read(p, "rb") if os.path.exists(p) else None) for p in (paths.DOCS, os.path.join(paths.HOME, "status.json"))}
        part = collect._part("ztest")
        try:
            with mock.patch.dict(collect.BY_NAME, {"ztest": (collect.D, reader)}), mock.patch.object(collect, "assemble", lambda g: None):
                self.assertEqual(collect.collect_one("ztest", join=False)["new"], 2)
                st = collect.collect_one("ztest", join=False)
                self.assertEqual((st["new"], st["rows"]), (3, 5))
                self.assertEqual(collect.collect_one("ztest", join=False)["new"], 0)

                def broken(days, out):
                    raise FileNotFoundError("gone")
                with mock.patch.dict(collect.BY_NAME, {"ztest": (collect.D, broken)}):
                    st = collect.collect_one("ztest", join=False)
                self.assertEqual((st["new"], st["rows"], st["stale"]), (0, 5, True))
        finally:
            for p in (part,):
                if os.path.exists(p):
                    os.remove(p)
            for p, b in keep.items():
                if b is None:
                    if os.path.exists(p):
                        os.remove(p)
                else:
                    _f.write(b, p, "wb")

    def test_tick_reports_new_rows_in_total_and_by_source(self):
        status = {"whatsapp": {"rows": 10, "new": 12}, "obsidian": {"rows": 3, "new": 0}, "imessage": {"skipped": "blocked", "new": 0}, "cursor": {"rows": 1}}
        with mock.patch.object(collect, "run", lambda only=None: status), mock.patch.object(schedule, "_load", lambda: {"daily": time.time()}), \
                mock.patch.object(schedule, "_save", lambda st: None), mock.patch.object(schedule, "_locked", lambda: False), \
                mock.patch("ctx.exports.ingest", lambda: []), mock.patch.object(schedule, "LOCK", os.path.join(fixture.HOME, "tick.test.lock")):
            done = schedule.tick(force={"fast"})
        self.assertEqual((done["new"], done["new_by_source"]), (12, {"whatsapp": 12}))


if __name__ == "__main__":
    unittest.main()
