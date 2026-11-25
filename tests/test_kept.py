"""What the owner marked to keep: flagged mail, starred whatsapp, pinned notes, safari and browser bookmarks. All made up,
in temp folders; none of this mac's own mail, chats, notes or bookmarks is opened."""
import datetime, gzip, io, json, os, plistlib, shutil, sqlite3, tempfile, unittest
from unittest import mock
from tests import fixture
from ctx import canvas, collect, connect, kept, local_apps, mail


def _ld(num, payload):
    return bytes([num << 3 | 2, len(payload)]) + payload


class Kept(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ctx-kept-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(lambda: [canvas.remove(d["id"]) for d in list(canvas._defs().values())])
        self.said = []

    def read(self, name, st=None, prev=None):
        rows = []
        info = canvas.READ["builtin"](canvas._make("builtin", name), rows.append, False, self.said.append, {} if st is None else st, prev or {})
        return rows, info

    def mailbox(self, flagged_column=True):
        root = os.path.join(self.tmp, "Mail")
        box = os.path.join(root, "V10", "ACCT", "INBOX.mbox", "Messages")
        os.makedirs(box)
        os.makedirs(os.path.join(root, "V10", "MailData"))
        con = sqlite3.connect(os.path.join(root, "V10", "MailData", "Envelope Index"))
        con.execute("create table subjects (subject text)")
        con.execute("create table addresses (address text)")
        con.execute("create table summaries (summary text)")
        con.execute("create table messages (subject int, sender int, summary int, date_received int, flags int, deleted int%s)" % (", flagged int" if flagged_column else ""))
        con.executemany("insert into subjects values (?)", [("the kiln invoice",), ("weekly gull digest",), ("an old flagged one",)])
        con.executemany("insert into addresses values (?)", [("potter@example.com",), ("digest@example.org",)])
        con.execute("insert into summaries values ('please find the invoice for the kiln shelves')")
        for i, (subj, sender, summ, ts, star, gone) in enumerate([(1, 1, 1, 1700000000, 1, 0), (2, 2, None, 1700100000, 0, 0), (3, 1, None, 1600000000, 1, 1)], 1):
            con.execute("insert into messages (subject, sender, summary, date_received, flags, deleted%s) values (?,?,?,?,?,?%s)" % ((", flagged", ",?") if flagged_column else ("", "")),
                        (subj, sender, summ, ts, 16 if star else 0, gone) + ((star,) if flagged_column else ()))
        con.commit()
        con.close()
        for n, frm, subj, body in ((1, "potter@example.com", "the kiln invoice", "the shelves come to forty pounds, payable by friday"), (2, "digest@example.org", "weekly gull digest", "nine gulls")):
            msg = ("From: %s\nTo: me@example.com\nSubject: %s\nDate: Tue, 14 Nov 2023 22:13:20 +0000\nMessage-ID: <m%d@example.com>\n\n%s\n" % (frm, subj, n, body)).encode()
            with open(os.path.join(box, "%d.emlx" % n), "wb") as f:
                f.write(b"%d\n" % len(msg) + msg + b"<plist></plist>")
        return root

    def test_flagged_mail(self):
        for column in (True, False):                # the newer index has a column for it, the older one a bit in a number
            shutil.rmtree(os.path.join(self.tmp, "Mail"), True)
            with mock.patch.object(kept, "MAIL", self.mailbox(column)):
                rows, info = self.read("mail_starred")
                self.assertEqual(len(rows), 1, column)
                r = rows[0]
                self.assertEqual((r["title"], r["ts"], r["kept"], r["src"]), ("the kiln invoice", "2023-11-14T22:13:20Z", "starred", "canvas_mail_starred"))
                self.assertEqual(r["text"], "from potter@example.com\nthe shelves come to forty pounds, payable by friday")
                self.assertIn("1 emails", info["how"])
                self.assertEqual(kept.mail_flagged_files(), {"1"})
                t = canvas.connect("builtin:mail_starred", say=self.said.append)       # a trial reads the index only
                self.assertEqual((t["state"], t["sample"]["rows"], t["sample"]["since"], t["kind"]), ("ready", 1, "2023-11", "builtin"))
        with mock.patch.object(kept, "MAIL", os.path.join(self.tmp, "nowhere")):
            t = canvas.connect("builtin:mail_starred", say=self.said.append)
            self.assertEqual(t["state"], "cannot")
            self.assertIn("apple mail is not set up", t["detail"])
            self.assertEqual(kept.mail_flagged_files(), set())

    def test_mail_rows_say_starred(self):
        root = self.mailbox()
        out, index = io.StringIO(), io.StringIO()
        with mock.patch.object(kept, "MAIL", root), mock.patch.object(mail, "ROOT", root), mock.patch.dict(os.environ, {"CTX_MY_EMAILS": "me@example.com"}):
            mail.mail(None, out, index)
        got = {r["text"]: r for r in map(json.loads, index.getvalue().splitlines())}
        self.assertIs(got["the kiln invoice"].get("starred"), True)
        self.assertNotIn("starred", got["weekly gull digest"])

    def test_whatsapp_and_notes(self):
        wa, notes = os.path.join(self.tmp, "wa.sqlite"), os.path.join(self.tmp, "notes.sqlite")
        con = sqlite3.connect(wa)
        con.execute("create table ZWACHATSESSION (Z_PK integer primary key, ZPARTNERNAME text)")
        con.execute("create table ZWAMESSAGE (Z_PK integer primary key, ZMESSAGEDATE real, ZISFROMME int, ZTEXT text, ZCHATSESSION int, ZSTARRED int)")
        con.execute("insert into ZWACHATSESSION values (1, 'grace hopper')")
        con.executemany("insert into ZWAMESSAGE values (?,?,?,?,1,?)", [(1, 700000000, 0, "the shed key is under the pot", 1), (2, 700000100, 1, "ok", 0)])
        con.commit()
        con.close()
        con = sqlite3.connect(notes)
        con.execute("create table ZICCLOUDSYNCINGOBJECT (Z_PK integer primary key, ZTITLE1 text, ZMODIFICATIONDATE1 real, ZISPINNED int, ZMARKEDFORDELETION int, ZISPASSWORDPROTECTED int)")
        con.execute("create table ZICNOTEDATA (ZNOTE int, ZDATA blob)")
        for pk, title, pinned, text in ((1, "glaze recipes", 1, b"celadon: cone six"), (2, "shopping", 0, b"bread")):
            con.execute("insert into ZICCLOUDSYNCINGOBJECT values (?,?,700000000,?,0,0)", (pk, title, pinned))
            con.execute("insert into ZICNOTEDATA values (?,?)", (pk, gzip.compress(_ld(2, _ld(3, _ld(2, text))))))
        con.commit()
        con.close()
        with mock.patch.object(collect, "WA_DB", wa), mock.patch.object(collect, "NOTES_DB", notes):
            rows, _ = self.read("whatsapp_starred")
            self.assertEqual([(r["title"], r["text"], r["kept"], r["msg"], r["ts"][:4]) for r in rows], [("grace hopper", "grace hopper: the shed key is under the pot", "starred", "W1", "2023")])
            rows, _ = self.read("notes_pinned")
            self.assertEqual([(r["title"], r["text"], r["kept"]) for r in rows], [("glaze recipes", "celadon: cone six", "pinned")])
        with mock.patch.object(collect, "WA_DB", os.path.join(self.tmp, "none.sqlite")):
            self.assertEqual(canvas.connect("builtin:whatsapp_starred", say=self.said.append)["state"], "cannot")

    def test_safari_and_browser_bookmarks(self):
        plist = os.path.join(self.tmp, "Bookmarks.plist")
        page = lambda url, title, **kw: dict({"URLString": url, "URIDictionary": {"title": title}, "WebBookmarkType": "WebBookmarkTypeLeaf"}, **kw)
        tree = {"Children": [
            {"Title": "BookmarksBar", "Children": [page("https://example.com/kilns", "kilns"), {"Title": "clay", "Children": [page("https://example.com/glaze", "glaze notes")]}]},
            {"Title": "com.apple.ReadingList", "Children": [page("https://example.org/tides", "tide tables explained",
                                                               ReadingList={"DateAdded": datetime.datetime(2024, 3, 2, 10, 0, 0), "PreviewText": "why the tide turns"})]}]}
        with open(plist, "wb") as f:
            plistlib.dump(tree, f)
        with mock.patch.object(kept, "SAFARI_BOOKMARKS", plist):
            rows, _ = self.read("safari_reading_list")
            self.assertEqual([(r["title"], r["url"], r["ts"], r["kept"]) for r in rows], [("tide tables explained", "https://example.org/tides", "2024-03-02T10:00:00Z", "reading list")])
            self.assertIn("why the tide turns", rows[0]["text"])
            st = {}
            rows, _ = self.read("safari_bookmarks", st)
            self.assertEqual(sorted((r["title"], r["ts"]) for r in rows), [("glaze notes", ""), ("kilns", "")])       # the first read cannot date them
            self.assertIn("in favourites / clay", [r for r in rows if r["title"] == "glaze notes"][0]["text"])
            tree["Children"][0]["Children"].append(page("https://example.com/new", "a new one"))
            with open(plist, "wb") as f:
                plistlib.dump(tree, f)
            rows, _ = self.read("safari_bookmarks", st)
            self.assertTrue([r for r in rows if r["title"] == "a new one"][0]["ts"].startswith("20"))                    # one added later is dated the day it was seen
        prof = os.path.join(self.tmp, "appdata", "Google", "Chrome", "Default")
        os.makedirs(prof)
        with open(os.path.join(prof, "Bookmarks"), "w") as f:
            json.dump({"roots": {"bookmark_bar": {"type": "folder", "name": "Bookmarks bar", "children": [
                {"type": "url", "name": "gull atlas", "url": "https://example.net/gulls", "date_added": str(int((1700000000 + kept.WEBKIT_EPOCH) * 1e6))},
                {"type": "folder", "name": "bread", "children": [{"type": "url", "name": "starter", "url": "https://example.net/starter", "date_added": "0"}]},
                {"type": "url", "name": "a script", "url": "javascript:void(0)"}]}}}, f)
        with mock.patch.object(local_apps, "APPDATA", os.path.join(self.tmp, "appdata")):
            rows, info = self.read("browser_bookmarks")
        by = {r["title"]: r for r in rows}
        self.assertEqual(sorted(by), ["gull atlas", "starter"])
        self.assertEqual((by["gull atlas"]["ts"], by["gull atlas"]["browser"], by["gull atlas"]["kept"]), ("2023-11-14T22:13:20Z", "chrome", "bookmark"))
        self.assertIn("in Bookmarks bar / bread", by["starter"]["text"])

    def test_search_offers_them_and_enable_makes_a_source(self):
        ids = lambda q: [c["id"] for c in connect.search_all(q) if c["kind"] == "builtin"]
        self.assertEqual(ids("starred"), ["builtin:mail_starred", "builtin:whatsapp_starred"])
        self.assertEqual(ids("gmail starred"), ["builtin:mail_starred"])
        self.assertEqual(ids("flagged"), ["builtin:mail_starred"])
        self.assertEqual(ids("bookmarks"), ["builtin:safari_reading_list", "builtin:safari_bookmarks", "builtin:browser_bookmarks"])
        self.assertEqual(ids("reading list"), ["builtin:safari_reading_list"])
        self.assertEqual(ids("pinned notes"), ["builtin:notes_pinned"])
        self.assertEqual(ids("zzqx"), [])
        row = [c for c in connect.search_all("gmail starred") if c["kind"] == "builtin"][0]
        self.assertTrue(row["installed"] and "flag" in row["what"])
        on = canvas.enable("builtin:mail_starred")
        self.assertEqual((on["source"], on["tier"], on["enabled"]), ("canvas_mail_starred", "fast", True))
        self.assertIn("canvas_mail_starred", collect.BY_NAME)
        self.assertIn("canvas_mail_starred", canvas.due("fast"))
        canvas.remove("builtin:mail_starred")
        self.assertNotIn("canvas_mail_starred", collect.BY_NAME)


if __name__ == "__main__":
    unittest.main()
