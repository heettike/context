"""The x lists read through the extension (likes, posts, bookmarks), against a made-up x. Nothing here touches a
browser: the extension's answers are played back from a list of invented posts."""
import json, os, shutil, tempfile, unittest
from unittest import mock
from tests import fixture  # noqa: F401  (sets CTX_HOME before ctx is imported)
from ctx import bridge, signed_in

ME = "teapot"


def post(n, who=ME, **more):
    return dict({"u": "https://x.com/%s/status/%d" % (who, n), "d": "2025-01-%02dT10:00:00.000Z" % (n % 28 + 1), "n": "A Teapot @" + who,
                 "t": "made-up post %d" % n, "l": [], "m": 0, "r": "", "rt": False}, **more)


class FakeX:
    """Plays x_api: a list of posts newest first, served in pages of `size`. `slow_at` makes the nth request answer
    'slow down'; `lose` makes that answer come without a cursor, as an old reader did."""
    def __init__(self, posts, size=2, slow_at=None, lose=False, url="https://x.com/" + ME):
        self.posts, self.size, self.slow_at, self.lose, self.url, self.calls, self.requests = posts, size, slow_at, lose, url, [], 0

    def submit(self, job, timeout=0, pickup=0):
        assert job["type"] == "page" and job["fn"] == "x_api", job
        op, known, pages, start, vars_, part = job["args"]
        self.calls.append({"op": op, "known": list(known), "from": start, "vars": vars_, "part": part, "url": job["url"]})
        seen, at, out, why = {u.rsplit("/", 1)[-1] for u in known}, int(start or 0), [], ""
        nxt = ""
        for _ in range(pages):
            self.requests += 1
            if self.slow_at and self.requests == self.slow_at:
                why, nxt = "x asked to slow down", ("" if self.lose else (str(at) if at else ""))
                break
            page = self.posts[at:at + self.size]
            hit = False
            for b in page:
                if b["u"].rsplit("/", 1)[-1] in seen:
                    hit = True
                else:
                    seen.add(b["u"].rsplit("/", 1)[-1])
                    out.append(b)
            at += self.size
            if (hit and known) or at >= len(self.posts):
                nxt = ""
                break
            nxt = str(at)
        return {"url": self.url, "value": {"items": out, "pages": 1, "why": why, "next": nxt, "wait": 600 if why else 0}}


class Lists(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ctx-x-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        for p in (mock.patch.object(signed_in, "IMPORTS", self.dir), mock.patch.object(bridge, "connected", lambda: True),
                  mock.patch.object(signed_in.time, "sleep", lambda s: None), mock.patch.object(signed_in, "note", lambda *a: None)):
            p.start()
            self.addCleanup(p.stop)
        with open(os.path.join(self.dir, "x_me.json"), "w") as f:
            json.dump({"handle": ME}, f)

    def path(self, name):
        return os.path.join(self.dir, name)

    def load(self, name):
        with open(self.path(name)) as f:
            return json.load(f)

    def saved(self, name):
        return [int(b["u"].rsplit("/", 1)[-1]) for b in self.load(name)]

    def put(self, name, posts, mark=None):
        with open(self.path(name), "w") as f:
            json.dump([{k: b[k] for k in "udntlm"} for b in posts], f)
        if mark is not None:
            with open(self.path(name + ".at"), "w") as f:
                json.dump(mark, f)

    def run_with(self, x, fn):
        with mock.patch.object(bridge, "submit", x.submit):
            return fn()

    def test_a_first_read_goes_to_the_end_and_says_so(self):
        x = FakeX([post(n) for n in range(9, 0, -1)])
        r = self.run_with(x, signed_in.x_posts)
        self.assertEqual((r["state"], r["rows"], r["new"], r["detail"]), ("ok", 9, 9, ""))
        self.assertEqual(self.saved("x_posts.json"), list(range(9, 0, -1)))
        self.assertEqual(self.load("x_posts.json.at"), {"next": "", "end": True})

    def test_a_half_read_list_with_no_cursor_goes_on_past_what_is_saved(self):
        # 7, 6, 5 are saved, the stop lost the cursor; 9 and 8 were posted since, 4..1 were never read
        self.put("x_posts.json", [post(7), post(6), post(5)], mark={"next": ""})
        x = FakeX([post(n) for n in range(9, 0, -1)])
        r = self.run_with(x, signed_in.x_posts)
        self.assertEqual((r["rows"], r["new"], r["detail"]), (9, 6, ""))
        self.assertEqual(self.saved("x_posts.json"), list(range(9, 0, -1)))          # newer in front, older at the end, none twice
        self.assertEqual(x.calls[0]["known"], [])                                    # it must not stop at the first saved post
        self.assertEqual(x.calls[0]["from"], "")
        self.assertTrue(self.load("x_posts.json.at")["end"])

    def test_a_slow_down_keeps_the_place_and_the_next_read_goes_on_from_it(self):
        self.put("x_posts.json", [post(7), post(6), post(5)], mark={"next": ""})
        posts = [post(n) for n in range(9, 0, -1)]
        x = FakeX(posts, slow_at=4)
        r = self.run_with(x, signed_in.x_posts)
        self.assertIn("x asked to slow down for 10 minutes", r["detail"])
        self.assertIn("more to read", r["detail"])
        mark = self.load("x_posts.json.at")
        self.assertEqual((mark["next"], mark["end"]), ("6", False))
        self.assertEqual(self.saved("x_posts.json"), [9, 8, 7, 6, 5, 4])
        x2 = FakeX(posts)
        r = self.run_with(x2, signed_in.x_posts)
        self.assertEqual(x2.calls[0]["from"], "6")
        self.assertEqual(self.saved("x_posts.json"), list(range(9, 0, -1)))
        self.assertEqual((r["new"], r["detail"]), (3, ""))

    def test_a_slow_down_that_loses_the_cursor_is_not_taken_for_the_end(self):
        x = FakeX([post(n) for n in range(9, 0, -1)], slow_at=2, lose=True)
        self.run_with(x, signed_in.x_posts)
        self.assertEqual(self.load("x_posts.json.at"), {"next": "", "end": False})
        r = self.run_with(FakeX([post(n) for n in range(9, 0, -1)]), signed_in.x_posts)
        self.assertEqual((r["rows"], self.saved("x_posts.json")), (9, list(range(9, 0, -1))))

    def test_a_list_read_to_its_end_only_looks_for_newer_posts(self):
        self.put("x_likes.json", [post(n, "kettle") for n in (7, 6, 5)], mark={"next": "", "end": True})
        x = FakeX([post(n, "kettle") for n in range(9, 0, -1)], url="https://x.com/i/history/likes")
        r = self.run_with(x, signed_in.x_likes)
        self.assertEqual((r["rows"], r["new"]), (5, 2))
        self.assertEqual(self.saved("x_likes.json"), [9, 8, 7, 6, 5])
        self.assertEqual(len(x.calls[0]["known"]), 3)
        self.assertEqual(x.requests, 2)                                              # it stopped at the first saved post

    def test_a_saved_list_with_no_mark_file_was_read_to_its_end_by_an_older_version(self):
        self.put("x_likes.json", [post(n, "kettle") for n in (7, 6, 5)])
        x = FakeX([post(n, "kettle") for n in range(9, 0, -1)], url="https://x.com/i/history/likes")
        self.run_with(x, signed_in.x_likes)
        self.assertEqual(self.saved("x_likes.json"), [9, 8, 7, 6, 5])

    def test_posts_keep_only_what_the_owner_wrote_and_who_a_reply_answers(self):
        x = FakeX([post(4), post(3, rt=True), post(2, "kettle"), post(1, r="kettle")])
        r = self.run_with(x, signed_in.x_posts)
        self.assertEqual(self.saved("x_posts.json"), [4, 1])
        rows = self.load("x_posts.json")
        self.assertEqual(rows[1]["r"], "kettle")
        self.assertNotIn("r", rows[0])
        self.assertEqual(r["rows"], 2)

    def test_replies_keep_only_the_owners_replies(self):
        x = FakeX([post(5, r="kettle"), post(4, "kettle"), post(3), post(2, r=ME), post(1, r="samovar", rt=True)], url="https://x.com/%s/with_replies" % ME)
        r = self.run_with(x, signed_in.x_replies)
        self.assertEqual((r["state"], r["rows"]), ("ok", 2))
        self.assertEqual([(int(b["u"].rsplit("/", 1)[-1]), b["r"]) for b in self.load("x_replies.json")], [(5, "kettle"), (2, ME)])
        self.assertEqual((x.calls[0]["op"], x.calls[0]["url"]), ("UserRepliesTimeline", "https://x.com/%s/with_replies" % ME))

    def test_replies_reach_the_archive_as_posts_titled_like_the_x_archive_titles_them(self):
        import io
        from ctx import collect
        self.put("x_posts.json", [post(9), post(2)])
        with open(self.path("x_replies.json"), "w") as f:
            json.dump([dict({k: b[k] for k in "udntlm"}, r=b["r"]) for b in (post(5, r="kettle"), post(2, r=ME))], f)
        os.makedirs(os.path.join(self.dir, "home", "imports"))
        for n in ("x_posts.json", "x_replies.json"):
            shutil.copy(self.path(n), os.path.join(self.dir, "home", "imports", n))
        out = io.StringIO()
        with mock.patch.object(collect.paths, "HOME", os.path.join(self.dir, "home")):
            n = collect.BY_NAME["x_web_replies"][1](None, out)
        rows = [json.loads(l) for l in out.getvalue().splitlines()]
        self.assertEqual(n, 1)                                                         # post 2 is in the posts file already
        self.assertEqual([(r["id"], r["src"], r["title"], r["who"]) for r in rows], [("P5", "x_posts", "reply to @kettle", "me")])
        self.assertEqual(rows[0]["url"], "https://x.com/%s/status/5" % ME)

    def test_bookmarks_come_from_the_data_address_and_keep_their_shape(self):
        self.put("bookmarks.json", [post(n, "Kettle") for n in (7, 6, 5)])
        x = FakeX([post(n, "kettle", r="someone") for n in range(9, 0, -1)], url="https://x.com/i/history")      # the handle is spelled another way now
        r = self.run_with(x, signed_in.x_bookmarks)
        self.assertEqual((r["state"], r["rows"], r["new"]), ("ok", 5, 2))
        self.assertEqual(self.saved("bookmarks.json"), [9, 8, 7, 6, 5])
        for b in self.load("bookmarks.json"):
            self.assertEqual(sorted(b), sorted("udntlm"))
        c = x.calls[0]
        self.assertEqual((c["op"], c["part"], c["url"]), ("Bookmarks", "Bookmarks", "https://x.com/i/bookmarks"))
        self.assertNotIn("userId", c["vars"])
        r = self.run_with(FakeX([post(n, "kettle") for n in range(9, 0, -1)], url="https://x.com/i/history"), signed_in.x_bookmarks)
        self.assertEqual((r["rows"], r["new"]), (5, 0))                              # a second read adds nothing

    def test_a_sign_in_page_asks_for_the_owner_and_keeps_the_rows(self):
        self.put("bookmarks.json", [post(7, "kettle")])
        r = self.run_with(FakeX([], url="https://x.com/i/flow/login"), signed_in.x_bookmarks)
        self.assertEqual((r["state"], r["rows"]), ("needs_you", 1))
        self.assertEqual(self.saved("bookmarks.json"), [7])

    def test_without_the_extension_likes_are_skipped_with_a_reason(self):
        with mock.patch.object(bridge, "connected", lambda: False):
            r = signed_in.x_likes()
        self.assertEqual((r["state"], r["detail"]), ("skipped", "needs the context extension in your browser"))


class Helper(unittest.TestCase):
    def test_the_helper_passes_only_the_jobs_the_extension_has(self):
        with open(os.path.join(fixture.REPO, "extension", "background.js")) as f:
            src = f.read()
        for kind in ("fetch", "page", "about", "reload"):
            self.assertIn("\n  %s: " % kind, src)
        self.assertNotIn("scroll_read", src)
        with open(os.path.join(fixture.REPO, "ctx", "bridge.py")) as f:
            self.assertNotIn("scroll_read", f.read())

    def test_a_list_cursor_is_not_taken_for_a_secret(self):
        import base64, random                                                        # built here from a seeded source, in the shape x uses: two 8-byte fields and a small one
        r = random.Random(7)
        field = lambda: bytes(r.randrange(256) for _ in range(8))
        cursor = base64.urlsafe_b64encode(b"\x0c\x00\x01\x0a\x00\x01" + field() + b"\x0a\x00\x02" + field() + b"\x08\x00\x03\x00\x00\x00\x02\x00\x00").decode().rstrip("=")
        got = bridge.clean({"value": {"next": cursor, "items": [{"t": cursor}]}})
        self.assertEqual(got["value"]["next"], cursor)
        self.assertNotEqual(got["value"]["items"][0]["t"], cursor)                   # the same letters in a post's text are still scrubbed


if __name__ == "__main__":
    unittest.main()
