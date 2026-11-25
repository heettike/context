"""A complete LinkedIn export, beside a basic one and an older one: every kind of thing that is the owner's own is read,
nothing doubles across the three, and the files about their account are left alone. All made up."""
import io, json, os, shutil, tempfile, time, unittest, zipfile
from unittest import mock
from tests import fixture  # noqa: F401  (sets CTX_HOME before ctx is imported)
from ctx import collect, exports, linkedin

POST = "https://www.linkedin.com/feed/update/urn%3Ali%3Ashare%3A7000000000000000001"
SEEN = "https://www.linkedin.com/feed/update/urn%3Ali%3Aactivity%3A7000000000000000002"

COMPLETE = {
    "Profile.csv": 'First Name,Last Name,Maiden Name,Address,Birth Date,Headline,Summary,Industry,Zip Code,Geo Location,Twitter Handles,Websites,Instant Messengers\n'
                   'Ada,Teapot,,"12 Kiln Lane, Flat 3","Mar 1, 1980",potter and founder,"i make pots.\nand tools for potters.",Ceramics,0000-001,"Porto, Portugal",[teapot],[COMPANY:https://example.com],\n',
    "Positions.csv": 'Company Name,Title,Description,Location,Started On,Finished On\nKiln Co,Founder,"built the wheel, sold the wheel",Porto,Feb 2008,\nClay Ltd,Potter,,Faro,Sep 2003,Jan 2008\n',
    "Education.csv": "School Name,Start Date,End Date,Notes,Degree Name,Activities\nSchool of Glaze,1999,2003,,BA Ceramics,pottery club\n",
    "Skills.csv": "Name\nThrowing\nGlazing\n",
    "Publications.csv": "Name,Published On,Description,Publisher,Url\nOn Kilns,\"Jan 5, 2023\",how hot is hot,Clay Press,https://example.com/kilns\n",
    "Shares.csv": 'Date,ShareLink,ShareCommentary,SharedUrl,MediaUrl,Visibility\n'
                  '2025-03-03 10:00:00,%s,"we shipped the wheel.\n""finally"", said the team. my key is sk-abcdefghijklmnopqrstuvwxyz012345",https://example.com/wheel,,MEMBER_NETWORK\n'
                  '2025-03-04 10:00:00,https://www.linkedin.com/feed/update/urn%%3Ali%%3Ashare%%3A7000000000000000009,,,,MEMBER_NETWORK\n' % POST,
    "InstantReposts.csv": "Date,Link\n2025-03-05 10:00:00,%s\n" % SEEN,
    "Comments.csv": 'Date,Link,Message\n2025-03-06 10:00:00,%s,"lovely glaze, how long in the kiln?"\n2025-03-06 11:00:00,%s,"a comment\nover two lines"\nstray,,\n' % (SEEN, SEEN),
    "Reactions.csv": "Date,Type,Link\n2025-03-07 10:00:00,PRAISE,%s\n2025-03-07 10:01:00,LIKE,%s\n" % (SEEN, POST),
    "Saved_Items.csv": "savedItem,CreatedTime\nhttps://www.linkedin.com/feed/update/urn:li:activity:7000000000000000003,2025-03-08 10:00:00\n",
    "SearchQueries.csv": "Time,Search Query\n2025/03/09 10:00:00 UTC,kiln repair\n2025/03/09 10:05:00 UTC,kiln repair\n",
    "Invitations.csv": 'From,To,Sent At,Message,Direction,inviterProfileUrl,inviteeProfileUrl\n'
                       'Ada Teapot,Maya Okafor,"3/10/25, 9:05 AM","loved your talk on glazes, would like to stay in touch",OUTGOING,https://example.com/in/ada,https://example.com/in/maya\n'
                       'Ravi Anand,Ada Teapot,"3/11/25, 10:15 PM",,INCOMING,https://example.com/in/ravi,https://example.com/in/ada\n'
                       'Lee Park,Ada Teapot,"12/1/24, 1:00 PM",met you at the fair,INCOMING,https://example.com/in/lee,https://example.com/in/ada\n',
    "Recommendations_Given.csv": 'First Name,Last Name,Company,Job Title,Text,Creation Date,Status\nMaya,Okafor,Glaze Inc,Chemist,"the best glaze chemist i know","3/12/25, 9:00 AM",\n',
    "Recommendations_Received.csv": 'First Name,Last Name,Company,Job Title,Text,Creation Date,Status\nRavi,Anand,,,"ada throws a fine pot","3/13/25, 9:00 AM",VISIBLE\n',
    "Articles/Articles/2024-05-01 09:00:00.0-Why Kilns Crack.html":
        '<html><head><title>Why Kilns Crack</title><style>p{}</style></head><body><h1>Why Kilns Crack</h1><p class="created">Created on 2024-04-30 08:00</p>'
        '<p class="published">Published on 2024-05-01 09:00</p><div><p>Heat moves <em>unevenly</em> &amp; clay remembers.</p><blockquote>fire slowly</blockquote></div></body></html>',
    "messages.csv": 'CONVERSATION ID,CONVERSATION TITLE,FROM,SENDER PROFILE URL,TO,RECIPIENT PROFILE URLS,DATE,SUBJECT,CONTENT,FOLDER,ATTACHMENTS,IS MESSAGE DRAFT\n'
                    'c1,,Maya Okafor,,Ada Teapot,,2025-03-01 10:00:00 UTC,,are you at the fair,INBOX,,No\nc1,,Ada Teapot,,Maya Okafor,,2025-03-01 10:05:00 UTC,,"yes,\nstall nine",INBOX,,No\n'
                    'c1,,Ada Teapot,,Maya Okafor,,2025-03-01 10:06:00 UTC,,never sent this,INBOX,,Yes\nc2,,Ravi Anand,,Ada Teapot,,2025-03-02 10:00:00 UTC,,only in the complete export,ARCHIVE,,No\n',
    "Connections.csv": "Notes:\n\"When exporting your connection data, you may notice that some of the email addresses are missing.\"\n\nFirst Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
                       "Maya,Okafor,https://example.com/in/maya,,Glaze Inc,Chemist,05 Jan 2022\nLee,Park,https://example.com/in/lee,,Acme,Engineer,06 Jan 2022\n",
    "Ad_Targeting.csv": "Member Age,Buyer Groups\n35-44,pottery buyers the owner never chose\n",
    "Inferences_about_you.csv": "Category,Type of inference,Description,Inference\nx,y,z,a guess linkedin made\n",
    "Logins.csv": "Login Date,IP Address,User Agent,Login Type\n2025-03-01,203.0.113.9,agent,x\n",
    "PhoneNumbers.csv": "Extension,Number,Type\n,+1 415 555 0100,MOBILE\n",
    "Receipts_v2.csv": "First Name,Last Name,Total Amount\nAda,Teapot,29.99\n",
}
BASIC = {"messages.csv": COMPLETE["messages.csv"].split("c2,,Ravi")[0], "Profile.csv": COMPLETE["Profile.csv"],
         "Connections.csv": COMPLETE["Connections.csv"].split("Lee,Park")[0]}
OLD = {"Shares.csv": "Date,ShareLink,ShareCommentary,SharedUrl,MediaUrl,Visibility\n2025-03-03 10:00:00,%s,we shipped the wheel.,,,MEMBER_NETWORK\n"
                     "2023-01-01 10:00:00,https://www.linkedin.com/feed/update/urn%%3Ali%%3Ashare%%3A6000000000000000001,a post since deleted,,,MEMBER_NETWORK\n" % POST}


class Export(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ctx-li-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        p = mock.patch.object(exports, "IMPORTS", os.path.join(self.dir, "imports"))
        p.start()
        self.addCleanup(p.stop)

    def put(self, folder, files, age=0):
        for name, text in files.items():
            path = os.path.join(exports.IMPORTS, folder, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            os.utime(path, (time.time() - age,) * 2)

    def three(self):
        self.put("linkedin-old", OLD, age=86400 * 700)
        self.put("linkedin-basic", BASIC, age=86400)
        self.put("linkedin-complete", COMPLETE)

    def read(self, name):
        fn = collect.BY_NAME[name][1]
        out = io.StringIO()
        n = fn(None, out)
        rows = [json.loads(l) for l in out.getvalue().split("\n") if l]
        self.assertEqual(n, len(rows))
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        return rows

    def test_posts_reposts_and_comments(self):
        self.three()
        posts = self.read("linkedin_posts")
        self.assertEqual([(r["src"], r["who"], r["ts"], r["title"]) for r in posts],
                         [("linkedin_posts", "me", "2025-03-03T10:00:00Z", ""), ("linkedin_posts", "me", "2023-01-01T10:00:00Z", ""), ("linkedin_posts", "", "2025-03-05T10:00:00Z", "repost")])
        first = posts[0]                                                               # the newer export's copy of the post that is in two
        self.assertEqual(first["url"], "https://www.linkedin.com/feed/update/urn:li:share:7000000000000000001")
        self.assertIn('we shipped the wheel.\n"finally", said the team.', first["text"])
        self.assertIn("https://example.com/wheel", first["text"])
        self.assertNotIn("sk-abcdefghijklmnop", first["text"])
        comments = self.read("linkedin_comments")
        self.assertEqual([(r["text"], r["url"][-28:], r["who"], r["title"]) for r in comments],
                         [("lovely glaze, how long in the kiln?", "activity:7000000000000000002", "me", "comment"), ("a comment\nover two lines", "activity:7000000000000000002", "me", "comment")])

    def test_articles_invitations_recommendations(self):
        self.three()
        a = self.read("linkedin_articles")
        self.assertEqual([(r["title"], r["ts"][:10], r["who"]) for r in a], [("Why Kilns Crack", "2024-05-01", "me")])
        self.assertIn("Heat moves unevenly & clay remembers.", " ".join(a[0]["text"].split()))
        self.assertNotIn("<", a[0]["text"])
        inv = self.read("linkedin_invitations")
        self.assertEqual([(r["title"], r["who"], r["ts"]) for r in inv],
                         [("invitation to Maya Okafor", "me", "2025-03-10T09:05:00Z"), ("invitation from Lee Park", "them", "2024-12-01T13:00:00Z")])      # one with no note is not a row
        rec = self.read("linkedin_recommendations")
        self.assertEqual([(r["title"], r["who"], r["text"]) for r in rec],
                         [("recommendation for Maya Okafor (Chemist, Glaze Inc)", "me", "the best glaze chemist i know"), ("recommendation from Ravi Anand", "them", "ada throws a fine pot")])

    def test_saved_reactions_and_searches(self):
        self.three()
        saved = self.read("linkedin_saved")
        self.assertEqual([(r["url"], r["ts"], r["src"]) for r in saved], [("https://www.linkedin.com/feed/update/urn:li:activity:7000000000000000003", "2025-03-08T10:00:00Z", "linkedin_saved")])
        likes = self.read("linkedin_likes")
        self.assertEqual([(r["title"], r["ts"], r["url"][-28:]) for r in likes], [("celebrated", "2025-03-07T10:00:00Z", "activity:7000000000000000002"), ("liked", "2025-03-07T10:01:00Z", "li:share:7000000000000000001")])
        searches = self.read("linkedin_searches")
        self.assertEqual([(r["text"], r["ts"], r["who"]) for r in searches], [("kiln repair", "2025-03-09T10:00:00Z", "me"), ("kiln repair", "2025-03-09T10:05:00Z", "me")])

    def test_one_row_for_their_career_without_their_street_or_birthday(self):
        self.three()
        (p,) = self.read("linkedin_profile")
        self.assertEqual((p["src"], p["who"], p["title"]), ("linkedin_profile", "me", "linkedin profile: Ada Teapot"))
        for want in ("potter and founder", "i make pots.\nand tools for potters.", "Founder at Kiln Co (Feb 2008 to now), Porto", "built the wheel, sold the wheel",
                     "Potter at Clay Ltd (Sep 2003 to Jan 2008)", "School of Glaze, BA Ceramics (1999 to 2003)", "skills: Throwing, Glazing", "On Kilns, Clay Press", "based in: Porto, Portugal"):
            self.assertIn(want, p["text"])
        for never in ("Kiln Lane", "1980", "0000-001", "415 555"):
            self.assertNotIn(never, p["text"])
        self.assertEqual(self.read("linkedin_profile")[0]["id"], p["id"])

    def test_messages_and_connections_from_three_exports_do_not_double(self):
        self.three()
        msgs = self.read("linkedin")
        self.assertEqual(sorted(m["text"] for m in msgs), ["are you at the fair", "only in the complete export", "yes,\nstall nine"])       # the draft is not a message
        self.assertEqual({m["who"] for m in msgs if m["text"].startswith("yes")}, {"me"})
        self.assertEqual(sorted(c["title"] for c in self.read("linkedin_connections")), ["Lee Park", "Maya Okafor"])
        shutil.rmtree(os.path.join(exports.IMPORTS, "linkedin-complete"))
        self.assertEqual(len(self.read("linkedin")), 2)                                 # the same ids as before from the basic export alone
        self.assertEqual({m["id"] for m in self.read("linkedin")} - {m["id"] for m in msgs}, set())

    def test_a_basic_export_has_none_of_these_and_says_what_to_ask_for(self):
        self.put("linkedin-basic", BASIC)
        for name in linkedin.SOURCES:
            if name == "linkedin_profile":
                self.assertEqual(len(self.read(name)), 1)
                continue
            with self.assertRaises(FileNotFoundError) as e:
                collect.BY_NAME[name][1](None, io.StringIO())
            self.assertIn("complete archive", str(e.exception))

    def test_what_is_about_their_account_is_never_read(self):
        self.three()
        everything = " ".join(json.dumps(r) for name in list(linkedin.SOURCES) + ["linkedin", "linkedin_connections"] for r in self.read(name))
        for never in ("the owner never chose", "a guess linkedin made", "203.0.113.9", "415 555 0100", "29.99"):
            self.assertNotIn(never, everything)

    def test_the_zip_is_unpacked_and_every_new_kind_is_collected_with_it(self):
        from ctx import schedule
        down = os.path.join(self.dir, "Downloads")
        os.makedirs(down)
        with zipfile.ZipFile(os.path.join(down, "Complete_LinkedInDataExport_03-14-2025.zip.zip"), "w") as z:
            for name, text in COMPLETE.items():
                z.writestr(name, text)
        self.assertEqual([k for k, _ in exports.ingest(downloads=down)], ["linkedin"])
        self.assertEqual(len(self.read("linkedin_posts")), 2)
        for name in linkedin.SOURCES:
            self.assertIn(name, schedule.FROM_EXPORT["linkedin"])
            self.assertEqual(collect.BY_NAME[name][0], collect.D)

    def test_a_header_after_notes_and_times_in_every_shape(self):
        self.put("x", {"t.csv": "Notes:\n\"a note, with a comma\"\n\nName,When\nAda,1\n\n"})
        self.assertEqual(linkedin.table(os.path.join(exports.IMPORTS, "x", "t.csv"), ("Name", "When")), [{"Name": "Ada", "When": "1"}])
        self.assertEqual(linkedin.table(os.path.join(exports.IMPORTS, "x", "t.csv"), ("Nope",)), [])
        self.assertEqual([linkedin.when(t) for t in ("2025-03-03 10:00:00", "2025/03/09 10:00:00 UTC", "3/10/25, 9:05 AM", "12/1/24, 1:00 PM", "Jan 2022", "stray", "")],
                         ["2025-03-03T10:00:00Z", "2025-03-09T10:00:00Z", "2025-03-10T09:05:00Z", "2024-12-01T13:00:00Z", "2022-01-01T00:00:00Z", "", ""])


if __name__ == "__main__":
    unittest.main()
