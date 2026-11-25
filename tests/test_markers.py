import unittest
from tests import fixture  # noqa: F401
from ctx.answer import number_cites

ROWS = {i: {"id": i} for i in ("W1a2b3", "T-100_5", "IGabc9", "B77", "claude:9:1", "N5")}


def num(text, listed=()):
    return number_cites(text, list(listed), ROWS)


class Markers(unittest.TestCase):
    def test_ids_become_numbers_in_order_of_first_use(self):
        text, order = num("ada said yes [T-100_5]. then no [W1a2b3]. then yes again [T-100_5].")
        self.assertEqual(text, "ada said yes[1]. then no[2]. then yes again[1].")
        self.assertEqual(order, ["T-100_5", "W1a2b3"])

    def test_the_listed_order_does_not_override_the_order_of_use(self):
        text, order = num("first [B77] second [N5]", ["N5", "B77", "IGabc9"])
        self.assertEqual(text, "first[1] second[2]")
        self.assertEqual(order, ["B77", "N5", "IGabc9"])                # cited but never marked: listed after

    def test_several_ids_in_one_bracket(self):
        for inner in ("W1a2b3, B77", "W1a2b3,B77", "W1a2b3; B77", "W1a2b3 B77", "W1a2b3 and B77"):
            text, order = num(f"both agree [{inner}].")
            self.assertEqual(text, "both agree[1][2].", inner)
            self.assertEqual(order, ["W1a2b3", "B77"])

    def test_brackets_side_by_side(self):
        self.assertEqual(num("both agree [W1a2b3][B77].")[0], "both agree[1][2].")

    def test_an_id_with_a_colon_or_dash(self):
        self.assertEqual(num("typed it [claude:9:1]")[0], "typed it[1]")

    def test_an_id_that_is_not_a_row_is_removed(self):
        text, order = num("true [W1a2b3]. invented [W9z9z9z]. also [Xq12345, T-100_5].")
        self.assertEqual(text, "true[1]. invented. also[2].")
        self.assertEqual(order, ["W1a2b3", "T-100_5"])

    def test_ordinary_brackets_survive(self):
        for s in ("ada wrote teh [sic] plan", "back then [2024] it worked", "the key was [redacted] in the file",
                  "see [the long note] for more", "a [maybe] from her", "done [x] and [ ] not done", "price [approx 90] held"):
            self.assertEqual(num(s), (s, []), s)

    def test_a_number_the_model_made_up_cannot_pass_as_a_marker(self):
        text, order = num("claim one [1]. claim two [W1a2b3]. claim three [12].")
        self.assertEqual(text, "claim one. claim two[1]. claim three.")
        self.assertEqual(order, ["W1a2b3"])

    def test_no_marker_points_past_the_list(self):
        rows = {f"W{n}x{n}y{n}": {} for n in range(12)}
        text, order = number_cites(" ".join(f"s{n} [{i}]." for n, i in enumerate(rows)), [], rows)
        self.assertEqual(len(order), 8)
        import re
        self.assertEqual([int(n) for n in re.findall(r"\[(\d+)\]", text)], list(range(1, 9)))
        self.assertNotRegex(text, r"W\d+x")

    def test_a_marker_at_the_start_of_a_list_line_keeps_its_space(self):
        self.assertEqual(num("- [W1a2b3] first\n- second [B77]")[0], "- [1] first\n- second[2]")

    def test_the_same_marker_twice_in_a_row_is_one(self):
        self.assertEqual(num("so [W1a2b3] [W1a2b3, W1a2b3] it is")[0], "so[1] it is")

    def test_the_tail_of_a_long_id_is_accepted_when_it_can_mean_one_row_only(self):
        rows = {"T-1001_67543": {}, "T-1001_67544": {}, "T-2002_555123": {}, "W-9_555123": {}}
        text, order = number_cites("she owes a cookie [67543] [67544]. unclear [555123]. unknown [99887].", [], rows)
        self.assertEqual(text, "she owes a cookie[1][2]. unclear. unknown.")
        self.assertEqual(order, ["T-1001_67543", "T-1001_67544"])
        self.assertEqual(number_cites("in [2024] it held", [], rows)[0], "in [2024] it held")

    def test_wide_brackets(self):
        self.assertEqual(num("yes 【W1a2b3】.")[0], "yes[1].")

    def test_junk_in(self):
        self.assertEqual(number_cites(None, None, {}), ("", []))
        self.assertEqual(number_cites("plain", [{"id": 1}, 5, None, "nope"], ROWS), ("plain", []))
        self.assertEqual(number_cites("plain", "W1a2b3", ROWS), ("plain", []))
        self.assertEqual(num("no marks at all", ["B77"]), ("no marks at all", ["B77"]))

    def test_every_marker_maps_to_a_cite(self):
        import re
        text, order = num("a [IGabc9] b [nope12345] c [N5, B77] d [2] e [T-100_5]", ["W1a2b3"])
        marks = [int(n) for n in re.findall(r"\[(\d+)\]", text)]
        self.assertTrue(marks and max(marks) <= len(order))
        self.assertEqual(sorted(set(marks)), list(range(1, max(marks) + 1)))
        self.assertFalse(any(i in text for i in ROWS))


if __name__ == "__main__":
    unittest.main()
