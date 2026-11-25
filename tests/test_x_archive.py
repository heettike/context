"""The x archive, in the shape x really sends it: files split into parts, long posts kept apart, likes with no date,
chats that name nobody. And the merge: a post read from the browser and from the archive is one row. All made up."""
import io, json, os, shutil, tempfile, unittest, zipfile
from unittest import mock
from tests import fixture  # noqa: F401  (sets CTX_HOME before ctx is imported)
from ctx import collect, exports

ME, HANDLE = "1001", "teapot"


def ytd(name, rows):
    return "window.YTD.%s.part0 = %s" % (name, json.dumps(rows, indent=1))


def tweet(i, text, at="Mon Mar 03 10:00:00 +0000 2025", **more):
    return {"tweet": dict({"id_str": str(i), "id": str(i), "full_text": text, "created_at": at, "favorite_count": "2", "entities": {"urls": []}}, **more)}


def dm(i, sender, text, at="2025-03-03T10:00:00.000Z", **more):
    return {"messageCreate": dict({"id": str(i), "senderId": sender, "recipientId": ME, "text": text, "createdAt": at, "urls": [], "mediaUrls": [], "reactions": []}, **more)}


class Archive(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ctx-xa-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        p = mock.patch.object(exports, "IMPORTS", self.dir)
        p.start()
        self.addCleanup(p.stop)

    def put(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def account(self, where="x-one"):
        self.put(where + "/data/account.js", ytd("account", [{"account": {"accountId": ME, "username": HANDLE, "email": "teapot@example.com"}}]))

    def read(self, fn):
        out = io.StringIO()
        n = fn(None, out)
        rows = [json.loads(l) for l in out.getvalue().splitlines()]
        self.assertEqual(n, len(rows))
        return rows

    def test_posts_from_every_part_once_with_their_links_words_and_kind(self):
        self.account()
        long = "a long post about kettles " + "and spouts " * 40
        self.put("x-one/data/tweets.js", ytd("tweets", [
            tweet(1, "tea &amp; toast https://t.co/abc", entities={"urls": [{"url": "https://t.co/abc", "expanded_url": "https://example.com/tea"}]}),
            tweet(2, "@kettle yes https://t.co/pic", in_reply_to_screen_name="kettle",
                  entities={"urls": [], "media": [{"url": "https://t.co/pic", "expanded_url": "https://x.com/teapot/status/2/photo/1"}]}),
            tweet(3, "RT @samovar: steam is up"),
            tweet(4, long[:270] + "… https://t.co/long", at="Tue Mar 04 09:30:15 +0000 2025")]))
        self.put("x-one/data/tweets-part1.js", ytd("tweets", [tweet(5, "from the second part"), tweet(1, "tea &amp; toast https://t.co/abc")]))
        self.put("x-one/data/community-tweet.js", ytd("community_tweet", [tweet(6, "said in a community")]))
        self.put("x-one/data/deleted-tweets.js", ytd("deleted_tweets", [tweet(7, "taken down by the owner")]))
        self.put("x-one/data/note-tweet.js", ytd("note_tweet", [{"noteTweet": {"noteTweetId": "9", "createdAt": "2025-03-04T09:30:16.000Z", "core": {"text": long, "urls": []}}},
                                                                {"noteTweet": {"noteTweetId": "8", "createdAt": "2025-03-04T09:30:16.000Z", "core": {"text": "another long post made the same second", "urls": []}}}]))
        self.put("x-two/data/tweets.js", ytd("tweets", [tweet(5, "from the second part"), tweet(8, "only in the newer archive")]))      # a second archive, downloaded later
        self.put("x-one/data/like.js", "window.YTD.like.part0 = [")                                                                  # cut short: left out, the rest still read
        rows = {r["id"]: r for r in self.read(exports.x_archive_docs)}
        self.assertEqual(sorted(rows), ["P1", "P2", "P3", "P4", "P5", "P6", "P8"])
        self.assertEqual(rows["P1"]["text"], "tea & toast https://example.com/tea")
        self.assertEqual((rows["P1"]["src"], rows["P1"]["who"], rows["P1"]["url"], rows["P1"]["likes"], rows["P1"]["ts"]),
                         ("x_posts", "me", "https://x.com/teapot/status/1", 2, "2025-03-03T10:00:00Z"))
        self.assertEqual((rows["P2"]["title"], rows["P3"]["title"], rows["P3"]["who"]), ("reply to @kettle", "repost of @samovar", ""))
        self.assertEqual(rows["P2"]["text"], "@kettle yes https://x.com/teapot/status/2/photo/1")
        self.assertEqual(rows["P4"]["text"], long)                               # the whole long post, not its first 280 letters
        self.assertNotIn("P7", rows)

    def test_an_older_archive_names_the_file_tweet_js_and_has_no_account_file(self):
        self.put("x-old/tweet.js", ytd("tweet", [tweet(1, "from 2019")]))
        rows = self.read(exports.x_archive_docs)
        self.assertEqual([(r["id"], "url" in r) for r in rows], [("P1", False)])

    def test_likes_have_no_date_and_some_have_no_words(self):
        self.put("x-one/data/tweets.js", ytd("tweets", []))
        self.put("x-one/data/like.js", ytd("like", [{"like": {"tweetId": "50", "fullText": "a liked post &gt; most", "expandedUrl": "https://twitter.com/i/web/status/50"}},
                                                    {"like": {"tweetId": "51", "expandedUrl": "https://twitter.com/i/web/status/51"}}, {"like": {"tweetId": "50", "fullText": "again"}}, {"like": {}}]))
        self.put("x-one/data/like-part1.js", ytd("like", [{"like": {"tweetId": "52", "fullText": "in the second part"}}]))
        rows = self.read(exports.x_archive_docs)
        self.assertEqual([(r["id"], r["src"], r["ts"], r["text"]) for r in rows],
                         [("L50", "x_likes", "", "a liked post > most"), ("L51", "x_likes", "", ""), ("L52", "x_likes", "", "in the second part")])

    def test_no_archive_says_how_to_get_one(self):
        with self.assertRaises(FileNotFoundError):
            exports.x_archive_docs(None, io.StringIO())
        with self.assertRaises(FileNotFoundError):
            exports.x_archive_dms(None, io.StringIO())

    def test_chats_one_to_one_and_group(self):
        self.account()
        self.put("x-one/data/direct-messages.js", ytd("direct_messages", [{"dmConversation": {"conversationId": "1001-2002", "messages": [
            dm(11, "2002", "are you coming https://t.co/x1", urls=[{"url": "https://t.co/x1", "expanded": "https://example.com/party", "display": "example.com/party"}]),
            dm(12, ME, "yes. my key is sk-abcdefghijklmnopqrstuvwxyz012345", recipientId="2002"),
            dm(13, "2002", ""), {"reactionCreate": {"senderId": "2002"}}, "junk"]}}]))
        self.put("x-one/data/direct-messages-part1.js", ytd("direct_messages", [{"dmConversation": {"conversationId": "1001-3003", "messages": [dm(21, "3003", "from the second part"), dm(11, "2002", "a repeat")]}}]))
        self.put("x-one/data/direct-messages-group.js", ytd("direct_messages_group", [{"dmConversation": {"conversationId": "777888999000", "messages": [
            {"joinConversation": {"initiatingUserId": "2002", "participantsSnapshot": [ME, "2002", "4004"]}}, {"conversationNameUpdate": {"name": "kiln club", "initiatingUserId": "2002"}},
            dm(31, "4004", "who brings the clay"), dm(32, ME, "i will")]}},
            {"dmConversation": {"conversationId": "555666", "messages": [dm(41, "4004", "a group nobody named")]}}]))
        rows = {r["id"]: r for r in self.read(exports.x_archive_dms)}
        self.assertEqual(sorted(rows), ["XD11", "XD12", "XD21", "XD31", "XD32", "XD41"])
        a, b = rows["XD11"], rows["XD12"]
        self.assertEqual((a["src"], a["kind"], a["who"], a["sender"], a["thread"], a["thread_id"], a["ts"]), ("x_dm", "dm", "them", "2002", "x dm 2002", "xd1001-2002", "2025-03-03T10:00:00Z"))
        self.assertEqual(a["text"], "are you coming https://example.com/party")
        self.assertEqual((b["who"], b["sender"], b["mine_total"]), ("me", "", 4))
        self.assertNotIn("sk-abcdefghijklmnop", b["text"])                                # a chat is scrubbed like everything else
        self.assertEqual((rows["XD31"]["kind"], rows["XD31"]["thread"], rows["XD32"]["who"]), ("group", "kiln club", "me"))
        self.assertEqual(rows["XD41"]["thread"], "x group 555666")

    def test_a_chat_takes_the_name_the_owners_own_posts_give_that_account(self):
        self.account()
        mention = lambda i, handle, name: {"id_str": i, "screen_name": handle, "name": name, "indices": ["0", "5"]}
        self.put("x-one/data/tweets.js", ytd("tweets", [
            tweet(1, "@maya_o hello", entities={"urls": [], "user_mentions": [mention("2002", "maya_o", "Maya  Okafor"), mention("4004", "tomas", "")]}),
            tweet(2, "@ravi yes", in_reply_to_screen_name="ravi", in_reply_to_user_id_str="3003")]))
        self.put("x-one/data/direct-messages.js", ytd("direct_messages", [
            {"dmConversation": {"conversationId": "1001-2002", "messages": [dm(11, "2002", "named in a mention")]}},
            {"dmConversation": {"conversationId": "3003-1001", "messages": [dm(12, "3003", "named by a reply")]}},
            {"dmConversation": {"conversationId": "1001-9009", "messages": [dm(13, "9009", "never mentioned anywhere")]}}]))
        self.put("x-one/data/direct-messages-group.js", ytd("direct_messages_group", [{"dmConversation": {"conversationId": "555666", "messages": [dm(21, "4004", "in a group"), dm(22, "9009", "also there")]}}]))
        self.assertEqual(exports.x_names(), {"2002": "Maya Okafor (@maya_o)", "4004": "@tomas", "3003": "@ravi"})
        rows = {r["id"]: r for r in self.read(exports.x_archive_dms)}
        self.assertEqual([rows["XD%d" % n]["thread"] for n in (11, 12, 13)], ["Maya Okafor (@maya_o)", "@ravi", "x dm 9009"])
        self.assertEqual((rows["XD11"]["thread_id"], rows["XD11"]["sender"]), ("xd1001-2002", "Maya Okafor (@maya_o)"))     # the thread's id does not change
        self.assertEqual((rows["XD21"]["sender"], rows["XD22"]["sender"], rows["XD21"]["thread"]), ("@tomas", "9009", "x group 555666"))
        from ctx import namebook
        book = os.path.join(self.dir, "book.json")
        with mock.patch.object(namebook, "PATH", book), mock.patch.object(namebook, "apple_contacts", side_effect=FileNotFoundError), mock.patch.object(namebook, "_whatsapp", lambda: ([], [])), \
                mock.patch.object(namebook, "_vcards", lambda: []):
            namebook._mem.clear()
            b = namebook.build()
            self.assertEqual((b["sources"]["x archive"], namebook.name_for("x:2002"), namebook.name_for("x:9009")), (3, "Maya Okafor (@maya_o)", ""))
        namebook._mem.clear()

    def test_the_zip_from_x_is_unpacked_without_its_photos(self):
        down = os.path.join(self.dir, "Downloads")
        os.makedirs(down)
        with zipfile.ZipFile(os.path.join(down, "twitter-2025-04-17-0a1b2c3d4e5f.zip"), "w") as z:
            z.writestr("data/tweets.js", ytd("tweets", [tweet(1, "in the zip")]))
            z.writestr("data/account.js", ytd("account", [{"account": {"accountId": ME, "username": HANDLE}}]))
            z.writestr("data/tweets_media/1-abc.jpg", "not really a photo")
            z.writestr("Your archive.html", "<html></html>")
        imports = os.path.join(self.dir, "imports")
        with mock.patch.object(exports, "IMPORTS", imports):
            self.assertEqual([k for k, _ in exports.ingest(downloads=down)], ["x"])
            self.assertEqual(exports.ingest(downloads=down), [])                         # not unpacked twice
            self.assertEqual([r["id"] for r in self.read(exports.x_archive_docs)], ["P1"])
        got = [f for _, _, fs in os.walk(imports) for f in fs]
        self.assertIn("tweets.js", got)
        self.assertNotIn("1-abc.jpg", got)


class Merge(unittest.TestCase):
    """One id is one row in the file every reader uses, whichever sources brought it."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ctx-merge-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.docs = os.path.join(self.dir, "docs.jsonl")
        table = [(n, self.docs, None) for n in ("x_web_likes", "x_web_posts", "x_archive")]
        for p in (mock.patch.object(collect, "PARTS", os.path.join(self.dir, "parts")), mock.patch.object(collect, "D", self.docs), mock.patch.object(collect, "TABLE", table)):
            p.start()
            self.addCleanup(p.stop)
        os.makedirs(collect.PARTS)

    def part(self, name, rows):
        with open(collect._part(name), "w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def merged(self):
        collect.assemble(self.docs)
        with open(self.docs) as f:
            return [json.loads(l) for l in f]

    def test_a_post_from_the_browser_and_from_the_archive_is_one_row_that_says_the_most(self):
        web = {"id": "P1", "src": "x_posts", "ts": "2025-03-03T10:00:00Z", "title": "A Teapot @teapot", "text": "tea and toast", "url": "https://x.com/teapot/status/1", "who": "me"}
        arch = {"id": "P1", "src": "x_posts", "ts": "2025-03-03T10:00:00Z", "title": "", "text": "tea and toast", "likes": 7, "who": "me"}
        self.part("x_web_likes", [{"id": "L5", "src": "x_likes", "ts": "2024-01-01T00:00:00Z", "title": "A Kettle @kettle", "text": "a liked post", "url": "https://x.com/kettle/status/5", "who": ""}])
        self.part("x_web_posts", [web, {"id": "P2", "src": "x_posts", "ts": "2025-03-04T10:00:00Z", "title": "", "text": "only on the web", "url": "u", "who": "me"}])
        self.part("x_archive", [arch, {"id": "P3", "src": "x_posts", "ts": "2019-01-01T00:00:00Z", "title": "", "text": "only in the archive", "likes": 0},
                                {"id": "L5", "src": "x_likes", "ts": "", "title": "", "text": "a liked post", "url": "https://twitter.com/i/web/status/5"}])
        got = self.merged()
        self.assertEqual([r["id"] for r in got], ["L5", "P1", "P2", "P3"])                  # each once, where its first copy stood
        by = {r["id"]: r for r in got}
        self.assertEqual(by["P1"], dict(web, likes=7))                                     # the fuller row, with what only the other knew
        self.assertEqual((by["L5"]["ts"], by["L5"]["url"]), ("2024-01-01T00:00:00Z", "https://x.com/kettle/status/5"))

    def test_with_no_repeated_id_the_parts_are_joined_as_they_are(self):
        self.part("x_web_posts", [{"id": "P2", "src": "x_posts", "text": "a"}])
        self.part("x_archive", [{"id": "P3", "src": "x_posts", "text": "b"}])
        collect.assemble(self.docs)
        with open(self.docs, "rb") as f, open(collect._part("x_web_posts"), "rb") as a, open(collect._part("x_archive"), "rb") as b:
            self.assertEqual(f.read(), a.read() + b.read())

    def test_what_was_typed_is_one_row_too_when_a_session_sits_in_two_folders(self):
        prompts = os.path.join(self.dir, "prompts.jsonl")
        table = [("teapot_sessions", collect.S, None), ("teapot_prompts", collect.P, None)]
        with mock.patch.object(collect, "TABLE", table), mock.patch.object(collect.paths, "PROMPTS", prompts):
            self.part("teapot_sessions.prompts", [{"id": "C1:0", "src": "claude_code", "text": "typed once"}, {"id": "C1:0", "src": "claude_code", "text": "typed once"}])
            self.part("teapot_prompts", [{"id": "CH9", "src": "claude_code", "text": "from the list"}])
            collect.assemble(prompts)
        with open(prompts) as f:
            self.assertEqual([json.loads(l)["id"] for l in f], ["C1:0", "CH9"])

    def test_a_thing_an_export_holds_twice_is_one_row(self):
        self.part("x_archive", [{"id": "P3", "src": "x_posts", "text": "b"}, {"id": "P3", "src": "x_posts", "text": "b"}, {"id": "P4", "src": "x_posts", "text": "c"}])
        self.assertEqual([r["id"] for r in self.merged()], ["P3", "P4"])


if __name__ == "__main__":
    unittest.main()
