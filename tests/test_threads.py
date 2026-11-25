import json, os, re, unittest
from unittest import mock
from tests import fixture
from tests.test_answer import model, KEYS, CITE
from ctx import answer, paths


def tid(src, name):
    return src + ":" + name


fixture_tid = tid("whatsapp", "Ravi Anand")


class Index(unittest.TestCase):
    def test_every_conversation_is_indexed_in_time_order(self):
        idx = answer.thread_index()
        t = idx["threads"][tid("whatsapp", "Ravi Anand")]
        self.assertEqual((t["n"], t["mine"], t["src"], t["kind"], t["thread"]), (3000, 1000, "whatsapp", "dm", "Ravi Anand"))
        self.assertEqual((t["from"], t["to"]), ("2023-01-01", "2024-12-25"))
        rows = answer.thread_rows(tid("whatsapp", "Ravi Anand"))
        self.assertEqual(len(rows), 3000)
        self.assertEqual([r["ts"] for r in rows], sorted(r["ts"] for r in rows))
        self.assertEqual(sum(t["n"] for t in idx["threads"].values()), len(fixture.rows()["messages.jsonl"]))

    def test_the_index_is_cached_and_reused(self):
        answer.thread_index()
        self.assertTrue(os.path.exists(answer.CACHE))
        answer._idx.clear()
        with mock.patch.object(answer.json, "loads", wraps=json.loads) as loads:
            answer.thread_index()
        self.assertLess(loads.call_count, 5)                             # the header, not three thousand lines

    def test_the_index_is_rebuilt_when_messages_change(self):
        before = answer.thread_index()["threads"][tid("whatsapp", "Maya Okafor")]["n"]
        with open(paths.MESSAGES, "rb") as f:
            keep = f.read()
        try:
            with open(paths.MESSAGES, "a") as f:
                f.write(json.dumps(fixture.msg("MW99", "gazebo is finished", thread="Maya Okafor", ts="2025-03-20T09:00:00Z")) + "\n")
            self.assertEqual(answer.thread_index()["threads"][tid("whatsapp", "Maya Okafor")]["n"], before + 1)
            self.assertEqual(answer.thread_rows(tid("whatsapp", "Maya Okafor"))[-1]["id"], "MW99")
        finally:
            with open(paths.MESSAGES, "wb") as f:
                f.write(keep)
        self.assertEqual(answer.thread_index()["threads"][tid("whatsapp", "Maya Okafor")]["n"], before)

    def test_a_broken_cache_file_is_rebuilt(self):
        answer.thread_index()
        answer._idx.clear()
        with open(answer.CACHE, "wb") as f:
            f.write(b"\x05\x00\x00\x00\x00\x00\x00\x00junk")
        self.assertEqual(answer.thread_index()["threads"][tid("whatsapp", "Ravi Anand")]["n"], 3000)

    def test_stale_offsets_never_return_another_threads_rows(self):
        idx = dict(answer.thread_index())
        a, b = idx["threads"][tid("whatsapp", "Maya Okafor")], idx["threads"][tid("whatsapp", "Ravi Anand")]
        idx["threads"] = dict(idx["threads"], **{tid("whatsapp", "Maya Okafor"): dict(a, at=b["at"])})
        self.assertEqual(answer.thread_rows(tid("whatsapp", "Maya Okafor"), idx), [])


class Resolve(unittest.TestCase):
    def names(self, *q):
        idx = answer.thread_index()
        return [(idx["threads"][t]["src"], idx["threads"][t]["thread"]) for t in answer.resolve_threads(list(q))]

    def test_one_person_across_apps_and_spellings(self):
        got = self.names("maya okafor")
        self.assertEqual({s for s, _ in got}, {"whatsapp", "telegram", "instagram"})
        self.assertNotIn(("whatsapp", "Maya Stone"), got)
        self.assertEqual(got[0], ("whatsapp", "Maya Okafor"))            # the exact name first

    def test_case_accents_and_word_order(self):
        for q in ("MAYA OKAFOR", "okafor maya", "Máya Okafor", " maya   okafor. "):
            self.assertEqual(len(self.names(q)), 3, q)

    def test_a_first_name_alone_prefers_where_the_owner_writes_most(self):
        got = self.names("maya")
        self.assertEqual(got[0], ("whatsapp", "Maya Okafor"))
        self.assertIn(("whatsapp", "Maya Stone"), got)

    def test_the_start_of_a_name_and_a_near_spelling(self):
        self.assertEqual(self.names("oka")[0][1], "Maya Okafor")
        self.assertEqual({s for s, _ in self.names("mya okafur")}, {"whatsapp", "telegram", "instagram"})
        self.assertEqual(self.names("ravi anand"), [("whatsapp", "Ravi Anand")])

    def test_a_group_by_its_title(self):
        self.assertEqual(self.names("gazebo crew"), [("whatsapp", "gazebo crew")])
        self.assertEqual(self.names("the gazebo crew group chat"), [("whatsapp", "gazebo crew")])
        self.assertEqual(self.names("my chat with ravi anand"), [("whatsapp", "Ravi Anand")])

    def test_a_nickname_through_the_people_page(self):
        self.assertEqual(self.names("the admiral"), [("whatsapp", "grace hopper")])

    def test_nobody(self):
        self.assertEqual(self.names("zorblax"), [])
        self.assertEqual(self.names("", "a", None, 5), [])
        self.assertEqual(answer.resolve_threads("maya"), [])
        self.assertEqual(answer.resolve_threads(None), [])


class Window(unittest.TestCase):
    def setUp(self):
        self.rows = answer.thread_rows(tid("whatsapp", "Ravi Anand"))
        self.rx = [[answer._rx("harbour"), answer._rx("lease")]]

    def size(self, picked):
        return sum(len(answer._tline(self.rows[i])) + 1 for i in picked)

    def test_a_thread_that_fits_is_sent_whole(self):
        rows = answer.thread_rows(tid("whatsapp", "Maya Okafor"))
        self.assertEqual(answer.thread_window(rows, "sample", 60_000), (list(range(12)), True))

    def test_recent_is_the_newest_that_fit(self):
        picked, whole = answer.thread_window(self.rows, "recent", 20_000)
        self.assertFalse(whole)
        self.assertEqual(picked, list(range(picked[0], 3000)))
        self.assertLessEqual(self.size(picked), 20_000)
        self.assertGreater(self.size(picked), 19_000)

    def test_first_is_the_oldest_that_fit(self):
        picked, whole = answer.thread_window(self.rows, "first", 20_000)
        self.assertEqual((picked[0], whole), (0, False))
        self.assertEqual(picked, list(range(len(picked))))
        self.assertLessEqual(self.size(picked), 20_000)

    def test_a_topic_gets_the_messages_around_each_match(self):
        for need in ("whole", "sample"):
            picked, whole = answer.thread_window(self.rows, need, 20_000, self.rx)
            self.assertFalse(whole)
            for hit in (700, 2200):
                self.assertTrue(set(range(hit - 15, hit + 16)) <= set(picked))
            self.assertTrue({0, 1, 2, 2999, 2992} <= set(picked))       # how it opened and where it stands
            self.assertEqual(picked, sorted(picked))
            self.assertEqual(len(picked), 31 * 2 + 3 + 8)

    def test_the_span_shrinks_to_fit(self):
        picked, _ = answer.thread_window(self.rows, "whole", 2_000, self.rx)
        self.assertTrue({700, 2200} <= set(picked))
        self.assertLessEqual(self.size(picked), 2_000)
        self.assertLess(len(picked), 40)

    def test_first_with_a_topic_reads_around_the_earliest_match_not_the_start(self):
        picked, _ = answer.thread_window(self.rows, "first", 20_000, self.rx)
        self.assertTrue(set(range(685, 716)) <= set(picked))
        picked, _ = answer.thread_window(self.rows, "first", 900, self.rx)
        self.assertIn(700, picked)
        self.assertNotIn(2200, picked)
        picked, _ = answer.thread_window(self.rows, "sample", 900, self.rx)
        self.assertIn(2200, picked)
        self.assertNotIn(700, picked)

    def test_no_match_falls_back_to_the_newest(self):
        picked, _ = answer.thread_window(self.rows, "whole", 5_000, [[answer._rx("zzzz")]])
        self.assertEqual(picked[-1], 2999)

    def test_a_period_narrows_the_thread_first(self):
        picked, whole = answer.thread_window(self.rows, "whole", 10 ** 9, (), "2024-01", "2024-12")
        self.assertEqual((picked, whole), (list(range(1500, 3000)), True))      # all of that period
        picked, whole = answer.thread_window(self.rows, "recent", 5_000, (), "2023-01", "2023-12")
        self.assertEqual(picked[-1], 1499)


class Read(unittest.TestCase):
    def test_a_whole_thread_in_order_with_its_header(self):
        text, by_id, read = answer.read_threads([tid("whatsapp", "Maya Okafor")], "whole")
        lines = text.splitlines()
        self.assertIn("the whole conversation, 12 messages, 2025-03-01 to 2025-03-12, verbatim", lines[0])
        self.assertEqual([l.split("]")[0][1:] for l in lines[1:]], [f"MW{n}" for n in range(12)])
        self.assertIn("2025-03-01 09:00 Maya Okafor: gazebo permit step 0", lines[1])
        self.assertIn(" me: ", lines[2])
        self.assertEqual(read, [{"thread": "Maya Okafor", "src": "whatsapp", "rows": 12, "from": "2025-03-01", "to": "2025-03-12", "whole": True}])
        self.assertEqual(set(by_id["MW1"]), CITE - {"sender"})      # the sender's name is added when the row is cited in a reply
        self.assertEqual((by_id["MW1"]["who"], by_id["MW0"]["who"]), ("me", "them"))

    def test_a_long_thread_says_what_was_left_out_and_adds_the_summary(self):
        text, by_id, read = answer.read_threads([tid("whatsapp", "Ravi Anand")], "whole", [["harbour", "lease"]])
        self.assertLessEqual(len(text), answer.THREAD_CHARS + 2500)
        self.assertIn("of 3000 messages verbatim", text)
        self.assertIn("the conversation runs 2023-01-01 to 2024-12-25", text)
        gaps = re.findall(r"… (\d+) messages from (\S+) to (\S+) not shown …", text)
        self.assertEqual(len(gaps), 3)
        self.assertEqual(sum(int(g[0]) for g in gaps) + len(by_id), 3000)
        self.assertIn("a summary, not verbatim", text)
        self.assertIn("renewed for two years", text)
        self.assertLess(text.index("V700]"), text.index("V2200]"))
        self.assertEqual((read[0]["whole"], read[0]["rows"]), (False, len(by_id)))

    def test_several_threads_share_the_budget(self):
        tids = [tid("whatsapp", "Maya Okafor"), tid("whatsapp", "Ravi Anand")]
        text, by_id, read = answer.read_threads(tids, "recent", budget=10_000)
        self.assertLessEqual(len(text), 10_000 + 2500)
        self.assertEqual([r["whole"] for r in read], [True, False])
        self.assertIn("V2999", by_id)
        self.assertIn("… 2", text)                                        # the earlier messages of the long one are counted, not shown

    def test_a_probe_word_that_is_the_threads_own_name_does_not_block_the_match(self):
        text, by_id, _ = answer.read_threads([fixture_tid], "whole", [["ravi", "harbour"], ["anand", "lease"]], budget=20_000)
        self.assertTrue({"V690", "V700", "V2200", "V2215"} <= set(by_id))

    def test_a_period_read_in_full_says_so(self):
        text, _, read = answer.read_threads([tid("whatsapp", "Maya Okafor")], "whole", after="2025-03", before="2025-03")
        self.assertIn("the whole conversation", text)
        text, by_id, read = answer.read_threads([fixture_tid], "whole", after="2024-12", before="2024-12")
        self.assertIn("every message from 2024-12-01 to 2024-12-25, verbatim (125 of the 3000", text)
        self.assertEqual((read[0]["whole"], read[0]["rows"]), (False, 125))

    def test_short_threads_leave_their_room_to_long_ones(self):
        tids = [fixture_tid, tid("whatsapp", "Maya Okafor"), tid("telegram", "maya okafor 🌿")]
        text, by_id, read = answer.read_threads(tids, "recent", budget=12_000)
        self.assertEqual([r["whole"] for r in read], [False, True, True])
        self.assertGreater(len(text), 10_500)                             # the long one got what the short ones left

    def test_unknown_threads(self):
        self.assertEqual(answer.read_threads(["nope"], "whole"), ("", {}, []))


class Ask(unittest.TestCase):
    def ask(self, q, plan, reply):
        patch, self.calls = model(plan, reply)
        with patch:
            out = answer.answer(q)
        self.assertEqual(set(out), KEYS)
        self.prompt = self.calls[-1]["prompt"]
        return out

    def test_a_named_person_is_read_whole_across_apps(self):
        out = self.ask("what did maya and i agree about the gazebo", {"probes": [["gazebo"]], "threads": ["maya okafor"], "need": "whole"},
                       {"answer": "the permit came first [MW0], then the paint [MT5].", "cites": []})
        self.assertEqual(out["error"], "")
        self.assertEqual([(t["src"], t["rows"], t["whole"]) for t in out["threads"]], [("whatsapp", 12, True), ("telegram", 6, True), ("instagram", 4, True)])
        self.assertEqual([c["id"] for c in out["cites"]], ["MW0", "MT5"])
        self.assertEqual(out["answer"], "the permit came first[1], then the paint[2].")
        thread, other = self.prompt.split("## threads read in order")[1].split("## other rows")
        self.assertEqual(len(re.findall(r"^\[M[WTI]\d+\]", thread, re.M)), 22)
        self.assertIn("[GZ0]", other)                                    # the group that mentions it stays alongside
        self.assertNotIn("[MW", other)

    def test_last_said_reads_the_end_of_a_long_thread(self):
        out = self.ask("what did ravi last say", {"probes": [["ravi"]], "threads": ["ravi anand"], "need": "recent"}, {"answer": "about the tide [V2999].", "cites": []})
        self.assertEqual((out["threads"][0]["whole"], out["threads"][0]["to"]), (False, "2024-12-25"))
        self.assertEqual([c["id"] for c in out["cites"]], ["V2999"])
        self.assertIn("summary of the whole conversation", self.prompt)

    def test_first_mention_reads_the_start(self):
        out = self.ask("when did ravi first write", {"probes": [["ravi"]], "threads": ["ravi anand"], "need": "first"}, {"answer": "in january 2023 [V0].", "cites": []})
        self.assertEqual(out["threads"][0]["from"], "2023-01-01")
        self.assertEqual([c["id"] for c in out["cites"]], ["V0"])

    def test_a_period_limits_what_is_read(self):
        out = self.ask("summarise my chat with ravi in 2024", {"probes": [["ravi"]], "threads": ["ravi anand"], "need": "whole", "after": "2024-01", "before": "2024-12"},
                       {"answer": "mostly the tide [V1500].", "cites": []})
        self.assertGreaterEqual(out["threads"][0]["from"], "2024-01-01")

    def test_matches_piled_in_one_thread_make_it_the_focus_without_the_planner_saying_so(self):
        out = self.ask("the harbour lease", {"probes": [["harbour", "lease"]]}, {"answer": "raised twice [V700] [V2200].", "cites": []})
        self.assertEqual([t["thread"] for t in out["threads"]], ["Ravi Anand"])
        self.assertIn("[V690]", self.prompt)                             # the messages around the match, which no probe finds

    def test_a_topic_spread_over_many_threads_stays_a_sample(self):
        out = self.ask("pottery", {"probes": [["pottery"]]}, {"answer": "you rest with it [N1].", "cites": []})
        self.assertEqual(out["threads"], [])
        self.assertNotIn("## threads read in order", self.prompt)

    def test_a_name_that_matches_no_thread_is_just_a_search(self):
        out = self.ask("what did zorblax say about pottery", {"probes": [["pottery"]], "threads": ["zorblax"], "need": "whole"}, {"answer": "nothing from them; you rest with it [N1].", "cites": []})
        self.assertEqual((out["threads"], out["error"]), ([], ""))

    def test_a_thread_is_read_even_when_no_probe_matches(self):
        out = self.ask("what did maya say about zzqq", {"probes": [["zzqq"]], "threads": ["maya okafor"], "need": "whole"}, {"answer": "nothing on that; the last was a photo [MI3].", "cites": []})
        self.assertEqual(out["error"], "")
        self.assertEqual(len(out["threads"]), 3)
        self.assertEqual([c["id"] for c in out["cites"]], ["MI3"])

    def test_junk_from_the_planner(self):
        for plan in ({"probes": [["gazebo"]], "threads": "maya", "need": 5}, {"probes": [["gazebo"]], "threads": [None, 3, {"a": 1}], "need": "everything"}):
            self.assertEqual(self.ask("gazebo", plan, {"answer": "ok [MW0].", "cites": []})["error"], "")


if __name__ == "__main__":
    unittest.main()
