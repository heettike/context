"""Scrubbing the raw export files in place (ctx/rawscrub.py) must not give any row a new id or a second copy.
A made-up linkedin and instagram export with secrets in them: read, scrub the files, read again."""
import io, json, os, shutil, tempfile, unittest
from unittest import mock
from tests import fixture  # noqa: F401  (sets CTX_HOME before ctx is imported)
from ctx import collect, exports, linkedin, rawscrub

SECRET = "my api_key = sk-abcdefghijklmnopqrstuvwxyz012345 and the wifi password is hunter2hunter2"
PLAIN = "see you at the kiln on friday,\nstall nine"


class Ids(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ctx-scrubids-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.imports = os.path.join(self.dir, "imports")
        p = mock.patch.object(exports, "IMPORTS", self.imports)
        p.start()
        self.addCleanup(p.stop)

    def put(self, rel, text):
        path = os.path.join(self.imports, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def read(self, name):
        out = io.StringIO()
        collect.BY_NAME[name][1](None, out)
        return [json.loads(l) for l in out.getvalue().split("\n") if l]

    def export(self):
        q = lambda s: '"' + s.replace('"', '""') + '"'
        self.put("linkedin-made-up/messages.csv", "CONVERSATION ID,CONVERSATION TITLE,FROM,SENDER PROFILE URL,TO,RECIPIENT PROFILE URLS,DATE,SUBJECT,CONTENT,FOLDER,ATTACHMENTS,IS MESSAGE DRAFT\n"
                 "c1,,Maya Okafor,,Ada Teapot,,2025-03-01 10:00:00 UTC,,%s,INBOX,,No\nc1,,Ada Teapot,,Maya Okafor,,2025-03-01 10:05:00 UTC,,%s,INBOX,,No\n" % (q(PLAIN), q(SECRET)))
        self.put("linkedin-made-up/Comments.csv", "Date,Link,Message\n2025-03-06 10:00:00,https://made.up/p/1,%s\n2025-03-06 11:00:00,https://made.up/p/1,%s\n" % (q(PLAIN), q(SECRET)))
        self.put("linkedin-made-up/SearchQueries.csv", "Time,Search Query\n2025/03/09 10:00:00 UTC,kiln repair\n2025/03/09 10:05:00 UTC,%s\n" % q(SECRET))
        self.put("linkedin-made-up/Recommendations_Given.csv", "First Name,Last Name,Company,Job Title,Text,Creation Date,Status\nMaya,Okafor,,,%s,\"3/12/25, 9:00 AM\",\n" % q(SECRET))
        msgs = [{"sender_name": "Ada", "timestamp_ms": 1700000000000, "content": PLAIN}, {"sender_name": "Ada", "timestamp_ms": 1700000000000, "content": SECRET},
                {"sender_name": "Maya", "timestamp_ms": 1700000001000, "content": "ok"}]
        self.put("instagram-made-up/your_instagram_activity/messages/inbox/maya_1234567890123456/message_1.json",
                 json.dumps({"participants": [{"name": "Maya"}, {"name": "Ada"}], "title": "Maya", "messages": msgs}))

    NAMES = ("linkedin", "linkedin_comments", "linkedin_searches", "linkedin_recommendations", "instagram")

    def test_no_id_moves_and_no_row_doubles_when_the_raw_files_are_scrubbed(self):
        self.export()
        before = {n: self.read(n) for n in self.NAMES}
        self.assertEqual([len(before[n]) for n in self.NAMES], [2, 2, 2, 1, 3])
        got = rawscrub.run(root=self.imports, apply=True)
        self.assertGreaterEqual(sum(v.get("changed", 0) for v in got["by_export"].values()), 5)      # the secrets really were in the files, and are gone
        for d, _, files in os.walk(self.imports):
            for f in files:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    self.assertNotIn("sk-abcdefghijklmnop", fh.read(), f)
        after = {n: self.read(n) for n in self.NAMES}
        for n in self.NAMES:
            self.assertEqual([r["id"] for r in after[n]], [r["id"] for r in before[n]], n)
            self.assertEqual(len({r["id"] for r in after[n]}), len(after[n]), n)
        self.assertEqual(rawscrub.run(root=self.imports, apply=True)["rules"], {})                   # a second scrub changes nothing, so the ids hold from then on

    def test_a_row_with_nothing_to_scrub_keeps_the_id_it_always_had(self):
        self.export()
        msgs = self.read("linkedin")
        self.assertEqual(msgs[0]["id"], collect.rid("LI", "c1", "2025-03-01 10:00:00 UTC", "Maya Okafor", PLAIN))      # the id made from the text as written
        self.assertNotEqual(msgs[1]["id"], collect.rid("LI", "c1", "2025-03-01 10:05:00 UTC", "Ada Teapot", SECRET))   # this one moves once, to the scrubbed text's id
        self.assertEqual((exports.idtext(PLAIN), exports.idtext(None)), (PLAIN, None))
        self.assertEqual(exports.idtext(exports.idtext(SECRET)), exports.idtext(SECRET))
        self.assertEqual(self.read("linkedin_comments")[0]["id"], collect.rid("LM", "https://made.up/p/1", "2025-03-06 10:00:00", PLAIN[:120]))

    def test_every_reader_that_makes_an_id_from_text_goes_through_idtext(self):
        import re
        for mod in (exports, linkedin):
            with open(mod.__file__) as f:
                src = f.read()
            for line in src.split("\n"):
                m = re.search(r'rid\("(LI|LM|LE|LQ)"[^\n]*', line)
                if m:
                    self.assertIn("idtext(", m.group(0), line.strip()[:80])
            if mod is exports:
                self.assertIn('stable(idtext(m["content"]), 6)', src)


if __name__ == "__main__":
    unittest.main()
