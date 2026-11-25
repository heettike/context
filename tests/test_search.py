import collections, unittest
from tests import fixture  # noqa: F401  (sets CTX_HOME first)
from ctx import answer


def ids(rows):
    return [r["id"] for r in rows]


class Probes(unittest.TestCase):
    def test_a_probe_given_as_a_string_is_split_into_words(self):
        self.assertEqual(answer.clean_probes(["rent split", ["Kettle", "FUND"]]), [["rent", "split"], ["kettle", "fund"]])

    def test_junk_is_dropped(self):
        self.assertEqual(answer.clean_probes([None, 5, [], [""], ["a"], {"x": 1}, ["ok"]]), [["ok"]])
        self.assertEqual(answer.clean_probes("kettle"), [])
        self.assertEqual(answer.clean_probes(None), [])

    def test_at_most_sixteen_probes_of_four_words(self):
        out = answer.clean_probes([[f"w{i}a", f"w{i}b", f"w{i}c", f"w{i}d", f"w{i}e"] for i in range(20)])
        self.assertEqual(len(out), 16)
        self.assertEqual(len(answer.clean_probes([["a%d" % i] for i in range(20)], 6)), 6)
        self.assertTrue(all(len(p) == 4 for p in out))

    def test_fallback_drops_filler_and_keeps_other_scripts(self):
        self.assertEqual(answer.fallback_probes("what do i think about pottery?"), [["pottery"]])
        self.assertEqual(answer.fallback_probes("what did i say"), [])

    def test_fallback_assumes_no_language(self):
        # short words are dropped whatever the language; what is left is kept in the order asked, six at most
        self.assertEqual(answer.fallback_probes("maine पढ़ाई ke bare mein kya kaha"), [["maine"], ["पढ़ाई"], ["bare"], ["mein"], ["kaha"]])
        self.assertEqual(answer.fallback_probes("¿qué dije sobre la cerámica en mi cuaderno?"), [["dije"], ["sobre"], ["cerámica"], ["cuaderno"]])
        self.assertEqual(answer.fallback_probes("陶芸 について 何を 言った"), [["陶芸"], ["について"], ["何を"], ["言った"]])
        self.assertEqual(len(answer.fallback_probes("one1 two22 three3 four44 five55 six666 seven77 eight88")), 6)

    def test_search_reports_how_many_rows_each_probe_matched(self):
        counts = {}
        answer.search([["pottery"], ["celadon"], ["zzzznope"]], counts=counts)
        self.assertEqual((counts["celadon"], counts["zzzznope"]), (1, 0))
        self.assertGreater(counts["pottery"], 100)


class Matching(unittest.TestCase):
    def test_all_words_of_a_probe_must_be_in_one_row(self):
        rows, total = answer.search([["kettle", "fund"]])
        self.assertEqual(ids(rows), ["W1"])
        self.assertEqual(total, 1)

    def test_a_word_matches_from_its_start(self):
        self.assertEqual(set(ids(answer.search([["invest"]])[0])), {"W5", "W6"})

    def test_a_short_word_must_stand_alone(self):
        self.assertEqual(ids(answer.search([["kal"]])[0]), ["W4"])

    def test_field_names_and_source_names_do_not_match(self):
        self.assertEqual(answer.search([["mine_total"]])[0], [])
        self.assertEqual(ids(answer.search([["whatsapp"]])[0]), ["W7"])      # only the thread that is named so

    def test_a_curly_apostrophe_matches_a_straight_one(self):
        self.assertEqual(ids(answer.search([["i'll", "send"]])[0]), ["W12"])

    def test_other_scripts_match(self):
        self.assertEqual(ids(answer.search([["पढ़ाई"]])[0]), ["W11"])

    def test_sessions_and_prompts_are_searched(self):
        self.assertEqual(ids(answer.search([["kiln", "timer"]])[0]), ["S1"])
        self.assertIn("P1", ids(answer.search([["inventory", "script"]])[0]))

    def test_no_probes_no_rows(self):
        self.assertEqual(answer.search([]), ([], 0))
        self.assertEqual(answer.search([["zzzznope"]]), ([], 0))

    def test_a_broken_line_is_skipped(self):
        self.assertNotIn("", ids(answer.search([["kettle"]])[0]))

    def test_row_shape(self):
        row = answer.search([["kettle", "fund"]])[0][0]
        self.assertEqual(set(row), {"id", "src", "ts", "thread", "who", "text", "url"})
        self.assertEqual(row["ts"], "2025-06-01")


class Filters(unittest.TestCase):
    def test_after_and_before_are_inclusive_months(self):
        self.assertEqual(ids(answer.search([["invest"]], after="2024-01")[0]), ["W5"])
        self.assertEqual(ids(answer.search([["invest"]], before="2023-12")[0]), ["W6"])
        self.assertEqual(ids(answer.search([["invest"]], after="2024-03", before="2024-03")[0]), ["W5"])

    def test_a_bare_year_and_a_full_date_are_understood(self):
        self.assertEqual(ids(answer.search([["invest"]], after="2024", before="2024")[0]), ["W5"])
        self.assertEqual(ids(answer.search([["invest"]], after="2024-03-01")[0]), ["W5"])

    def test_a_date_that_is_not_one_is_ignored(self):
        self.assertEqual(len(answer.search([["invest"]], after="last year")[0]), 2)

    def test_me_keeps_their_words_their_notes_and_what_the_owner_saved(self):
        rows, _ = answer.search([["pottery"]], who="me", limit=400)
        whos = collections.Counter(r["who"] for r in rows)
        self.assertEqual(whos["them"], 0)
        self.assertTrue(whos["saved"] and whos["me"])
        self.assertTrue({"N1", "O1", "P1"} <= set(ids(rows)))
        self.assertNotIn("G1", ids(rows))

    def test_me_only_leaves_out_saved_rows(self):
        rows, _ = answer.search([["pottery"]], who="me_only", limit=400)
        self.assertEqual({r["who"] for r in rows}, {"me"})

    def test_saved_only(self):
        rows, total = answer.search([["pottery"]], who="saved", limit=400)
        self.assertEqual({r["who"] for r in rows}, {"saved"})
        self.assertEqual(total, 36)

    def test_one_source(self):
        rows, total = answer.search([["pottery"]], src="x_bookmarks", limit=90)
        self.assertEqual(sorted(ids(rows)), ["B0", "B1", "B2"])
        self.assertEqual(total, 3)


class Ranking(unittest.TestCase):
    def test_never_more_rows_than_the_limit(self):
        for limit in (1, 3, 5, 10, 25, 70):
            self.assertLessEqual(len(answer.search([["pottery"]], limit=limit)[0]), limit)
        self.assertLessEqual(len(answer.search([["pottery"]], limit=10 ** 9)[0]), 400)
        self.assertTrue(answer.search([["pottery"]], limit="many")[0])

    def test_places_are_held_for_saved_rows(self):
        rows, _ = answer.search([["pottery"]])
        self.assertEqual(len(rows), 70)
        saved = [r for r in rows if r["who"] == "saved"]
        self.assertEqual(len(saved), answer.KEEP_SAVED)
        self.assertEqual(rows[-len(saved):], saved)                     # saved rows come last

    def test_likes_do_not_flood_the_saved_places(self):
        rows, _ = answer.search([["pottery"]])
        by = collections.Counter(r["src"] for r in rows if r["who"] == "saved")
        self.assertEqual(by["x_bookmarks"], 3)
        self.assertEqual(by["instagram_saved"], 3)
        self.assertLessEqual(by["instagram_likes"], answer.KEEP_SAVED - 6)

    def test_likes_fill_the_places_when_nothing_else_was_saved(self):
        rows, _ = answer.search([["wheels"]])
        self.assertEqual(len([r for r in rows if r["src"] == "instagram_likes"]), answer.KEEP_SAVED)

    def test_browsing_titles_take_few_places(self):
        rows, _ = answer.search([["pottery"]])
        self.assertLessEqual(len([r for r in rows if r["src"] == "browser_history"]), answer.THIN["browser_history"])

    def test_one_thread_cannot_take_every_place(self):
        rows, _ = answer.search([["lantern"]], limit=20)
        loud = [r for r in rows if r["thread"] == "loud group"]
        self.assertEqual(len(rows), 20)
        self.assertLessEqual(len(loud), answer.PER_THREAD)

    def test_a_loud_thread_fills_places_nobody_else_wants(self):
        rows, _ = answer.search([["lantern", "festival"]], limit=30)
        self.assertEqual(len(rows), 30)

    def test_a_rare_probe_outranks_a_common_one(self):
        rows, _ = answer.search([["pottery"], ["celadon"]], limit=5)
        self.assertEqual(rows[0]["id"], "R1")

    def test_their_own_words_rank_above_others(self):
        rows, _ = answer.search([["kettle"]])
        self.assertEqual(rows[0]["who"], "me")

    def test_the_same_id_or_the_same_words_appear_once(self):
        rows, _ = answer.search([["quorum"]])
        self.assertEqual(len(rows), 1)

    def test_a_long_row_is_cut_around_the_match(self):
        row = answer.search([["zeppelin"]])[0][0]
        self.assertIn("zeppelin landed", row["text"])
        self.assertLessEqual(len(row["text"]), answer.CLIP + 4)

    def test_oldest_first_when_asked(self):
        self.assertEqual(answer.search([["lantern", "festival"]], limit=3)[0][0]["ts"], "2025-07-28")
        rows, _ = answer.search([["lantern", "festival"]], limit=3, oldest=True)
        self.assertEqual([r["ts"] for r in rows], ["2025-07-01", "2025-07-01", "2025-07-02"])

    def test_who_labels(self):
        rows, _ = answer.search([["pottery"]], limit=400)
        who = {r["id"]: r["who"] for r in rows}
        self.assertEqual((who["N1"], who["O1"], who["G1"], who["B0"], who["P1"], who["R1"]), ("me", "me", "them", "saved", "me", "them"))


if __name__ == "__main__":
    unittest.main()
