"""Pictures, pdfs, documents, voice notes and videos as rows. Every file here is made up and lives in a temp folder:
text drawn into a pdf by hand, a picture rendered from it, a database built in the test. None of this mac's own
pictures, chats or recordings is opened."""
import json, os, shutil, sqlite3, subprocess, sys, tempfile, time, unittest
from unittest import mock
from tests import fixture
from ctx import collect, media
from ctx.media import scrub_layout
from ctx.scrub import R, scrub

WORDS = "cradle orbit puzzle velvet harbor lizard mango noble quartz ribbon sunset tunnel".split()
CARD = "4242 4242 4242 4242"
SAID = "the lease for the flat on marlow street is signed and the deposit is paid"


def grid(per_line, numbered=False, gap=" "):
    cell = (lambda i: "%d. %s" % (i + 1, WORDS[i])) if numbered else (lambda i: WORDS[i])
    return "\n".join(gap.join(cell(j) for j in range(i, i + per_line)) for i in range(0, 12, per_line))


class LayoutScrub(unittest.TestCase):
    """Text read off a picture: the secret is the same, the spacing and the line breaks are not."""

    def gone(self, text, *secrets):
        out = scrub_layout(text)
        self.assertIn(R, out, text)
        for s in secrets or WORDS[1:-1]:
            self.assertNotIn(s, out.lower(), text)
        return out

    def test_seed_phrase_in_a_grid(self):
        for text in (grid(3), grid(4), grid(2), grid(3, gap="    "), grid(3, numbered=True, gap="  "), grid(4, numbered=True),
                     grid(3).replace("\n", "\n\n")):
            self.gone(text)

    def test_seed_phrase_with_the_numbers_on_their_own_lines(self):
        self.gone("\n".join("%d\n%s" % (i + 1, w) for i, w in enumerate(WORDS)))
        self.gone("\n".join(str(i + 1) for i in range(12)) + "\n" + "\n".join(WORDS))

    def test_seed_phrase_under_a_heading_and_inside_a_chat(self):
        self.gone("Secret Recovery Phrase\nWrite these down\n" + grid(2, numbered=True, gap="   "))
        out = self.gone("ok sending it now, keep it safe please\n" + grid(4) + "\nthanks, got it. will move it to the vault tonight")
        self.assertTrue(out.startswith("ok sending it now"))
        self.assertTrue(out.endswith("vault tonight"))

    def test_card_number_split_across_lines(self):
        for text in ("card\n4242 4242\n4242 4242\nvalid", "4242\n4242\n4242\n4242", "Card number\n4242 4242 4242\n4242\nVALID THRU 12/29",
                     "4242•4242•4242•4242", "4242  4242  4242  4242", "3782\n822463\n10005"):
            out = self.gone(text, "4242 4242", "4242\n4242", "822463")
            self.assertNotIn("4242•4242", out)

    def test_card_number_next_to_other_digits(self):
        out = self.gone("4242 4242 4242 4242 123", "4242 4242")
        self.assertTrue(out.endswith("123"))

    def test_named_keys_still_go(self):
        key = "sk-ant-api03-" + "Zq9fK2mVx7Lr4TnB8cWd" * 3
        self.assertNotIn(key, scrub_layout("API key\n" + key + "\ncopy"))

    def test_ordinary_pictures_of_text_stay(self):
        for keep in ("milk\neggs\nbread\nrice", "Total 1200\nTax 216\nPaid 1416\nRef 20251104\nTable 12", "Mon Tue Wed\nThu Fri Sat\nSun",
                     "call 98765 43210\nor 91234 56789", "Order 4242 4242\n4242 4243", "2024\n2025\n2026\n2027",
                     "20\n21\n22\n23\n24\n25\n26\n27", "203\n204\n205\n206\n207",       # line numbers whose digits happen to pass a card's check
                     "can you send the lease by friday?\ni will look at the invoice tonight\nand call you when it lands",
                     "Invoice 1042\n12 x widget 4,500.00\n3 x gasket 1,250.00\nTotal 5,750.00\nPaid 14 March 2025"):
            self.assertEqual(scrub_layout(keep), keep)

    def test_same_answer_as_scrub_on_plain_text(self):
        for text in ("the wifi password is hunter2horse", "DB_PASSWORD=s3cretValue99", "nothing to hide here at all", "0x52908400098527886E0F7030069857D2E4169EE7"):
            self.assertEqual(scrub_layout(text), scrub(text))
        self.assertNotIn("4242", scrub_layout("here it is: " + CARD + " ok"))


class Fake:
    """Stands in for the swift helper: answers by file name, and remembers what it was asked."""

    def __init__(self, answers=None):
        self.answers, self.calls = answers or {}, []

    def ask(self, kind, path, timeout=0, **more):
        self.calls.append((kind, os.path.basename(path)))
        if os.path.basename(path) in self.answers:
            return self.answers[os.path.basename(path)]
        return {"image": {"ok": True, "text": SAID, "conf": 0.9, "labels": [["document", 0.9]], "w": 800, "h": 600},
                "pdf": {"ok": True, "text": SAID, "pages": 2, "chars": len(SAID), "ocr_pages": 0},
                "audio": {"ok": True, "text": SAID, "secs": 42.0, "conf": 0.9, "locale": "en-US"},
                "video": {"ok": True, "secs": 80.0, "w": 640, "h": 480}}[kind]

    def close(self):
        pass


def put(path, data=b"x" * 20000):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="ctx-media-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(shutil.rmtree, media.DIR, True)
        self.addCleanup(lambda: os.path.exists(media.CONFIG) and os.remove(media.CONFIG))
        shutil.rmtree(media.DIR, True)
        for name in ("WA_DIR", "IM_DB", "VOICE_MEMOS", "NOTES_MEDIA", "PHOTOS", "TELEGRAM"):       # nothing of the kind on this made-up mac
            p = mock.patch.object(media, name, os.path.join(self.tmp, "none", name))
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(media, "_shots", set())
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(media, "battery", lambda: (False, 100))      # this mac's own charge decides nothing here: a scan stops on a low battery
        p.start()
        self.addCleanup(p.stop)
        self.docs = os.path.join(self.tmp, "Papers")
        self.cfg = dict(media.DEFAULTS, folders=[self.docs], leave_out=[])

    def scan(self, tool=None, **kw):
        kw.setdefault("can_speak", (True, "en-US", ""))
        return media.scan(tool=tool or Fake(), cfg=self.cfg, **kw)

    def names(self, **kw):
        items, blocked, counts = media.listing(self.cfg, **kw)
        return sorted(os.path.basename(it["path"]) for it in items), blocked, counts


class Listing(Base):
    def test_kinds_and_what_is_left_alone(self):
        for rel in ("scan.png", "note.pdf", "memo.m4a", "clip.mov", "letter.docx", "list.txt", "sheet.xlsx", "setup.dmg", "face.ttf",
                    ".hidden/secret.png", "site/package.json", "site/logo.png", "site/docs/guide.md", "tool/.git/x", "tool/shot.png",
                    "Thing.app/Contents/icon.png", "deep/node_modules/pkg/a.png", "vault/.obsidian/app.json", "vault/day.md",
                    "trip/beach.jpg", "trip/notes.md"):
            put(os.path.join(self.docs, rel))
        put(os.path.join(self.docs, "icon.png"), b"x" * 900)        # an icon, not a picture
        names, blocked, counts = self.names()
        self.assertEqual(names, ["beach.jpg", "clip.mov", "letter.docx", "list.txt", "memo.m4a", "note.pdf", "notes.md", "scan.png"])
        self.assertEqual(blocked, {})
        self.assertEqual(counts, {"unread": 1})          # the spreadsheet is counted, not read

    def test_a_marker_file_in_the_folder_itself_does_not_hide_the_folder(self):
        put(os.path.join(self.docs, "package.json"))
        put(os.path.join(self.docs, "scan.png"))
        self.assertEqual(self.names()[0], ["scan.png"])

    def test_left_out_folders(self):
        put(os.path.join(self.docs, "open", "a.png"))
        put(os.path.join(self.docs, "Passport scans", "b.png"))
        self.cfg["leave_out"] = [os.path.join(self.docs, "Passport scans")]
        self.assertEqual(self.names()[0], ["a.png"])
        self.cfg["leave_out"] = [self.docs]
        self.assertEqual(self.names()[0], [])

    def test_nothing_under_library_is_walked(self):
        lib = os.path.join(fixture.USER_HOME, "Library", "Whatever")           # the made-up home of the test run, never this mac's own
        self.assertEqual(os.path.expanduser("~"), fixture.USER_HOME)
        put(os.path.join(lib, "a.png"))
        self.addCleanup(shutil.rmtree, lib, True)
        self.cfg["folders"] = [lib]
        self.assertEqual(self.names()[0], [])

    def test_screenshots_are_the_owners(self):
        put(os.path.join(self.docs, "Screenshot 2025-03-02 at 10.11.12.png"))
        put(os.path.join(self.docs, "poster.png"))
        items = {os.path.basename(it["path"]): it for it in media.listing(self.cfg)[0]}
        self.assertEqual((items["Screenshot 2025-03-02 at 10.11.12.png"]["what"], items["Screenshot 2025-03-02 at 10.11.12.png"]["who"]), ("screenshot", "me"))
        self.assertEqual((items["poster.png"]["what"], items["poster.png"].get("who", "")), ("picture", ""))

    def test_a_blocked_place_is_named_and_the_rest_goes_on(self):
        put(os.path.join(self.docs, "a.png"))
        real = os.listdir

        def listdir(p):
            if p == media.VOICE_MEMOS:
                raise PermissionError(1, "Operation not permitted")
            return real(p)
        os.makedirs(os.path.dirname(media.IM_DB))
        put(media.IM_DB, b"not a database")
        with mock.patch.object(os, "listdir", listdir):
            names, blocked, _ = self.names()
            inv = media.inventory(self.cfg)
            st = media.status(self.cfg)
        self.assertEqual(names, ["a.png"])
        self.assertEqual(blocked, {"voice memos": media.BLOCKED, "imessage": media.BLOCKED})
        self.assertEqual(inv["blocked"], blocked)
        self.assertEqual(st["blocked"], blocked)
        self.assertEqual(media.BLOCKED, "blocked: needs full disk access")

    def test_a_file_kept_in_icloud_is_counted_and_left_alone(self):
        put(os.path.join(self.docs, "here.png"))
        away = put(os.path.join(self.docs, "away.png"))
        real = os.stat

        def stat(p, *a, **kw):
            st = real(p, *a, **kw)
            if p == away:
                st = mock.Mock(st_size=st.st_size, st_mtime=st.st_mtime, st_flags=media.DATALESS, st_mode=st.st_mode)
            return st
        tool = Fake()
        with mock.patch.object(os, "stat", stat):
            r = self.scan(tool)
            self.assertEqual((r["read"], r["in_icloud"]), (1, 1))
            self.assertEqual([c[1] for c in tool.calls], ["here.png"])              # the other was never opened
            self.assertEqual(media.status(self.cfg)["kinds"]["image"], {"files": 1, "read": 1, "left": 0, "rows": 1, "no_row": 0, "in_icloud": 1})
            self.assertEqual(media.inventory(self.cfg)["in_icloud"], {"papers": [1, 20000]})
            self.cfg["icloud_files"] = "on"                                          # the owner said macos may fetch them
            self.assertEqual(self.scan(tool)["read"], 1)

    def test_telegram_cache_is_counted_but_read_only_when_switched_on(self):
        d = os.path.join(media.TELEGRAM, "account-1", "postbox", "media")
        put(os.path.join(d, "telegram-cloud-photo-1"), b"\xff\xd8\xff\xe0" + b"x" * 20000)
        put(os.path.join(d, "telegram-cloud-photo-1.meta"), b"x" * 20000)
        put(os.path.join(d, "blob"), b"\x00" * 20000)
        self.assertEqual(self.names()[0], [])
        self.assertEqual(self.names(every=True)[0], ["telegram-cloud-photo-1"])
        self.cfg["telegram_cache"] = "on"
        self.assertEqual(self.names()[0], ["telegram-cloud-photo-1"])


class Chats(Base):
    def whatsapp(self):
        os.makedirs(media.WA_DIR)
        con = sqlite3.connect(os.path.join(media.WA_DIR, "ChatStorage.sqlite"))
        con.executescript("""create table ZWACHATSESSION (Z_PK integer primary key, ZPARTNERNAME text, ZSESSIONTYPE integer);
            create table ZWAMESSAGE (Z_PK integer primary key, ZMESSAGEDATE real, ZISFROMME integer, ZCHATSESSION integer, ZTEXT text);
            create table ZWAMEDIAITEM (Z_PK integer primary key, ZMESSAGE integer, ZMEDIALOCALPATH text);
            insert into ZWACHATSESSION values (1, 'Ada Lovelace', 0), (2, 'Kettle Club', 1), (3, 'status', 3);
            insert into ZWAMESSAGE values (1, 700000000, 1, 1, null), (2, 700000100, 0, 1, null), (3, 700000200, 0, 2, null),
                                          (4, 700000300, 0, 3, null), (5, 700000400, 1, 1, null), (6, 700000500, 0, 1, null);
            insert into ZWAMEDIAITEM values (1, 1, 'Media/1/a/shot.jpg'), (2, 2, 'Media/1/b/voice.opus'), (3, 3, 'Media/2/c/clip.mp4'),
                                            (4, 4, 'Media/3/d/status.jpg'), (5, 5, 'Media/1/e/Lease draft.pdf'), (6, 6, 'Media/1/f/sticker.webp'),
                                            (7, 6, 'Media/1/g/gone.jpg');""")
        con.commit()
        con.close()
        for rel in ("Media/1/a/shot.jpg", "Media/1/b/voice.opus", "Media/2/c/clip.mp4", "Media/3/d/status.jpg", "Media/1/e/Lease draft.pdf", "Media/1/f/sticker.webp"):
            put(os.path.join(media.WA_DIR, "Message", rel), (rel * 2000).encode())

    def test_whatsapp_files_are_tied_to_their_conversation(self):
        self.whatsapp()
        r = self.scan()
        self.assertEqual((r["read"], r["rows"], r["left"]), (4, 4, 0))        # not the status, the sticker or the file that is gone
        shot = media.rows("image")[0]
        self.assertEqual((shot["src"], shot["who"], shot["thread_id"], shot["thread"], shot["kind"]), ("image", "me", "wa1", "Ada Lovelace", "dm"))
        self.assertEqual(shot["title"], "picture you sent Ada Lovelace")
        self.assertEqual(shot["ts"], "2023-03-08T20:26:40Z")          # when it was sent, not when the file was written
        self.assertTrue(shot["url"].startswith("file://") and shot["url"].endswith("shot.jpg"))
        self.assertEqual(shot["text"], SAID)
        voice = media.rows("audio")[0]
        self.assertEqual((voice["src"], voice["who"], voice["title"]), ("voice_note", "them", "voice note Ada Lovelace sent you, 0:42"))
        clip = media.rows("video")[0]
        self.assertEqual((clip["src"], clip["title"], clip["kind"], clip["secs"]), ("video", "video sent in Kettle Club, 1:20", "group", 80.0))
        self.assertIn("not transcribed", clip["text"])
        pdf = media.rows("file")[0]
        self.assertEqual((pdf["src"], pdf["title"], pdf["pages"]), ("file", "Lease draft.pdf (pdf you sent Ada Lovelace)", 2))

    def test_imessage_attachments(self):
        os.makedirs(os.path.dirname(media.IM_DB))
        att = put(os.path.join(self.tmp, "Attachments", "ab", "IMG_1.heic"))
        con = sqlite3.connect(media.IM_DB)
        con.executescript("""create table attachment (ROWID integer primary key, filename text, transfer_name text, mime_type text);
            create table message (ROWID integer primary key, date integer, is_from_me integer);
            create table message_attachment_join (message_id integer, attachment_id integer);
            create table chat (ROWID integer primary key, display_name text, chat_identifier text, style integer);
            create table chat_message_join (chat_id integer, message_id integer);
            insert into chat values (7, '', '+15550100', 45);
            insert into message values (1, 700000000000000000, 0);
            insert into chat_message_join values (7, 1);
            insert into message_attachment_join values (1, 1), (1, 2);""")
        con.execute("insert into attachment values (1, ?, 'IMG_1.heic', 'image/heic')", (att,))
        con.execute("insert into attachment values (2, ?, 'x.pluginPayloadAttachment', '')", (os.path.join(self.tmp, "x.pluginPayloadAttachment"),))
        con.commit()
        con.close()
        self.scan()
        row = media.rows("image")[0]
        self.assertEqual((row["thread_id"], row["who"], row["title"], row["ts"]), ("im7", "them", "picture +15550100 sent you", "2023-03-08T20:26:40Z"))

    def test_photos_library_is_read_through_its_database(self):
        os.makedirs(os.path.join(media.PHOTOS, "database"))
        con = sqlite3.connect(os.path.join(media.PHOTOS, "database", "Photos.sqlite"))
        con.executescript("""create table ZASSET (Z_PK integer primary key, ZDIRECTORY text, ZFILENAME text, ZKIND integer, ZDATECREATED real,
                                                  ZISDETECTEDSCREENSHOT integer, ZTRASHEDSTATE integer);
            insert into ZASSET values (1, 'A', 'one.heic', 0, 700000000, 0, 0), (2, 'B', 'two.png', 0, 700000100, 1, 0),
                                      (3, 'C', 'three.mov', 1, 700000200, 0, 0), (4, 'D', 'cloud.heic', 0, 700000300, 0, 0),
                                      (5, 'E', 'binned.heic', 0, 700000400, 0, 1);""")
        con.commit()
        con.close()
        for rel in ("A/one.heic", "B/two.png", "C/three.mov", "E/binned.heic"):
            put(os.path.join(media.PHOTOS, "originals", rel))
        items, blocked, counts = media.listing(self.cfg)
        self.assertEqual(sorted((os.path.basename(it["path"]), it["what"], it.get("who", "")) for it in items),
                         [("one.heic", "photo", ""), ("three.mov", "video", ""), ("two.png", "screenshot", "me")])
        self.assertEqual(counts, {"in icloud, not on this mac": 1})
        self.assertEqual(media._photos_count(), {"photos": 3, "videos": 1, "screenshots": 1})
        self.cfg["leave_out"] = [media.PHOTOS]
        self.assertEqual(media.listing(self.cfg)[0], [])

    def test_voice_memos_and_notes_attachments(self):
        put(os.path.join(media.VOICE_MEMOS, "20250302 101112.m4a"))
        put(os.path.join(media.VOICE_MEMOS, "CloudRecordings.db"))
        put(os.path.join(media.NOTES_MEDIA, "ACC", "Media", "U1", "1_x", "whiteboard.jpeg"))
        self.scan()
        memo, pic = media.rows("audio")[0], media.rows("image")[0]
        self.assertEqual((memo["who"], memo["place"], memo["title"]), ("me", "voice memos", "20250302 101112 (voice memo in voice memos, 0:42)"))
        self.assertEqual((pic["who"], pic["place"], pic["title"]), ("me", "apple notes", "picture in apple notes"))


class Reading(Base):
    def test_what_becomes_a_row(self):
        for name in ("text.png", "photo.jpg", "blank.png", "broken.png", "two words.png", "locked.pdf", "scan.pdf"):
            put(os.path.join(self.docs, name), name.encode() * 2000)
        tool = Fake({"photo.jpg": {"ok": True, "text": "", "conf": 0, "labels": [["receipt", 0.8], ["document", 0.7]]},
                     "blank.png": {"ok": True, "text": "", "conf": 0, "labels": []},
                     "broken.png": {"ok": False, "why": "could not be read as a picture"},
                     "two words.png": {"ok": True, "text": "Sale 50%", "conf": 0.9, "labels": [["sign", 0.6]]},
                     "locked.pdf": {"ok": False, "why": "locked"},
                     "scan.pdf": {"ok": True, "text": "x" * 30000 + " and more words here", "pages": 90, "chars": 250000, "ocr_pages": 8}})
        r = self.scan(tool)
        self.assertEqual((r["read"], r["rows"]), (7, 4))
        by = {os.path.basename(x["url"]): x for k in media.KINDS for x in media.rows(k)}
        self.assertEqual(sorted(by), ["photo.jpg", "scan.pdf", "text.png", "two words.png"])
        self.assertEqual((by["photo.jpg"]["text"], by["photo.jpg"]["labels"], by["photo.jpg"]["light"]), ("a picture of: receipt, document.", ["receipt", "document"], 1))
        self.assertEqual(by["two words.png"]["text"], "a picture of: sign. the words on it: Sale 50%.")
        self.assertNotIn("light", by["text.png"])
        self.assertEqual(by["text.png"]["title"], "text.png (picture in papers)")
        self.assertTrue(by["scan.pdf"]["text"].endswith("[the first 20,000 of 250,000 characters]"))
        self.assertLess(len(by["scan.pdf"]["text"]), 20100)
        why = {os.path.basename(d["p"]): d.get("why") for d in media.done().values()}
        self.assertEqual((why["locked.pdf"], why["broken.png"], why["blank.png"]), ("locked", "could not be read as a picture", "no text and nothing recognised in it"))

    def test_recognised_text_is_scrubbed_before_it_is_saved(self):
        put(os.path.join(self.docs, "wallet.png"))
        put(os.path.join(self.docs, "card.png"), b"y" * 20000)
        tool = Fake({"wallet.png": {"ok": True, "text": "Secret Recovery Phrase\n" + grid(3, numbered=True, gap="   "), "conf": 0.9, "labels": [["screenshot", 0.9]]},
                     "card.png": {"ok": True, "text": "Card number\n4242 4242\n4242 4242\nVALID THRU 12/29 the name on it is sam vimes", "conf": 0.9, "labels": []}})
        self.scan(tool)
        with open(media.DONE) as f:
            saved = f.read()
        for secret in WORDS[1:-1] + ["4242 4242", "4242\\n4242"]:
            self.assertNotIn(secret, saved)
        self.assertIn(R, saved)
        self.assertIn("sam vimes", saved)

    def test_plain_text_and_documents(self):
        put(os.path.join(self.docs, "plan.md"), "# plan\n" + SAID + "\n")
        put(os.path.join(self.docs, "long.txt"), ("the kettle fund closes on friday. " * 4000))
        put(os.path.join(self.docs, "empty.txt"), "ok")
        tool = Fake()
        self.scan(tool)
        self.assertEqual(tool.calls, [])                 # plain text needs no helper
        by = {os.path.basename(x["url"]): x for x in media.rows("file")}
        self.assertEqual(sorted(by), ["long.txt", "plan.md"])
        self.assertIn(SAID, by["plan.md"]["text"])
        self.assertRegex(by["long.txt"]["text"], r"\[the first 20,000 of 1\d\d,\d\d\d characters\]$")

    @unittest.skipUnless(shutil.which("textutil"), "needs macos's textutil")
    def test_word_documents_through_textutil(self):
        src = put(os.path.join(self.tmp, "src.txt"), SAID)
        os.makedirs(self.docs)
        subprocess.run(["textutil", "-convert", "docx", src, "-output", os.path.join(self.docs, "lease.docx")], check=True, capture_output=True)
        subprocess.run(["textutil", "-convert", "rtf", src, "-output", os.path.join(self.docs, "lease.rtf")], check=True, capture_output=True)
        self.scan()
        self.assertEqual(sorted((os.path.basename(x["url"]), x["text"]) for x in media.rows("file")), [("lease.docx", SAID), ("lease.rtf", SAID)])

    def test_a_videos_length_comes_from_its_own_header(self):
        def box(name, body):
            return (len(body) + 8).to_bytes(4, "big") + name + body
        mvhd = b"\x00" * 12 + (600).to_bytes(4, "big") + (600 * 95).to_bytes(4, "big") + b"\x00" * 80
        mp4 = box(b"ftyp", b"isom" + b"\x00" * 12) + box(b"mdat", b"\x00" * 30000) + box(b"moov", box(b"mvhd", mvhd))
        put(os.path.join(self.docs, "walk.mp4"), mp4)
        put(os.path.join(self.docs, "other.mkv"), b"\x1aE\xdf\xa3" + b"\x00" * 30000)
        tool = Fake()
        self.scan(tool)
        self.assertEqual(tool.calls, [("video", "other.mkv")])           # only the one whose header python cannot read
        by = {os.path.basename(x["url"]): x for x in media.rows("video")}
        self.assertEqual((by["walk.mp4"]["secs"], by["walk.mp4"]["title"]), (95.0, "walk.mp4 (video in papers, 1:35)"))
        self.assertEqual(by["other.mkv"]["secs"], 80.0)
        self.assertEqual(media.mp4_seconds(os.path.join(self.docs, "other.mkv")), 0)

    def test_audio_that_could_not_be_made_out_is_still_a_row(self):
        for name in ("clear.m4a", "another-language.m4a", "music.mp3"):
            put(os.path.join(self.docs, name), name.encode() * 3000)
        tool = Fake({"another-language.m4a": {"ok": True, "text": "a cat on the hi me too yes so what", "secs": 30.0, "conf": 0.21, "locale": "en-US"},
                     "music.mp3": {"ok": True, "text": "", "secs": 200.0, "conf": 0, "locale": "en-US"}})
        self.scan(tool)
        by = {os.path.basename(x["url"]): x for x in media.rows("audio")}
        self.assertEqual(by["clear.m4a"]["text"], SAID)
        self.assertEqual(media._used(), "en-US")                          # the language the first voice note was read in stays with the archive
        self.assertEqual(by["another-language.m4a"]["text"], "audio, 0:30 long. its words could not be made out on this mac.")
        self.assertEqual((by["music.mp3"]["light"], by["music.mp3"]["secs"]), (1, 200.0))

    def test_audio_waits_when_this_mac_cannot_transcribe_and_is_read_when_it_can(self):
        put(os.path.join(self.docs, "memo.m4a"))
        cannot = Fake({"memo.m4a": {"ok": False, "why": "needs permission", "secs": 12.0}})
        r = self.scan(cannot, can_speak=(False, "en-US", "needs the app"))
        self.assertEqual((r["read"], r["rows"], r["audio"]), (1, 1, "needs the app"))
        self.assertIn("not transcribed yet", media.rows("audio")[0]["text"])
        self.assertEqual(self.scan(cannot, can_speak=(False, "en-US", "needs the app"))["read"], 0)       # counted once, not asked again every run
        self.assertEqual(media.status(self.cfg)["kinds"]["audio"]["left"], 1)
        self.assertEqual(self.scan(Fake())["read"], 1)
        self.assertEqual([x["text"] for x in media.rows("audio")], [SAID])


class Incremental(Base):
    def fill(self, n=6):
        for i in range(n):
            p = put(os.path.join(self.docs, "p%d.png" % i), ("picture %d " % i).encode() * 2000)
            os.utime(p, (1700000000 + i * 1000, 1700000000 + i * 1000))

    def test_a_file_is_read_once(self):
        self.fill()
        tool = Fake()
        self.assertEqual(self.scan(tool)["read"], 6)
        self.assertEqual(self.scan(tool)["read"], 0)
        self.assertEqual(len(tool.calls), 6)

    def test_newest_first_and_a_stopped_run_goes_on(self):
        self.fill()
        tool = Fake()
        r = self.scan(tool, limit=2)
        self.assertEqual((r["read"], r["left"], r["stopped"]), (2, 4, "limit"))
        self.assertEqual([c[1] for c in tool.calls], ["p5.png", "p4.png"])
        with open(media.DONE, "a") as f:
            f.write('{"k": "half a line, the run was kil')          # killed mid-write
        r = self.scan(tool)
        self.assertEqual((r["read"], r["left"]), (4, 0))
        self.assertEqual(len(media.rows("image")), 6)

    def test_time_cap(self):
        self.fill()
        r = self.scan(seconds=0)
        self.assertEqual((r["read"], r["stopped"]), (0, "time"))

    def test_it_stops_on_a_low_battery(self):
        self.fill()
        with mock.patch.object(media, "battery", lambda: (True, 22)):
            r = self.scan()
        self.assertEqual((r["read"], r["stopped"]), (0, "on battery under 30%"))
        with mock.patch.object(media, "battery", lambda: (False, 22)):       # plugged in: goes on
            self.assertEqual(self.scan()["read"], 6)

    def test_a_changed_file_is_read_again_and_its_row_replaced(self):
        p = put(os.path.join(self.docs, "notes.txt"), "first version of the plan for the kettle fund")
        self.scan()
        first = media.rows("file")
        put(p, "second version of the plan for the kettle fund, longer now")
        os.utime(p, (time.time() + 5, time.time() + 5))
        self.assertEqual(self.scan()["read"], 1)
        second = media.rows("file")
        self.assertEqual(len(second), 1)
        self.assertIn("second version", second[0]["text"])
        self.assertNotEqual(first[0]["id"], second[0]["id"])

    def test_the_same_file_in_two_places_is_one_row_and_the_chat_copy_wins(self):
        put(os.path.join(self.docs, "a", "same.png"), b"z" * 30000)
        put(os.path.join(self.docs, "b", "copy.png"), b"z" * 30000)
        self.scan()
        self.assertEqual(len(media.rows("image")), 1)
        known = media.done()
        k = next(iter(known))
        linked = json.loads(json.dumps(known[k]))
        linked.update(k="other", p="/elsewhere/sent.jpg")
        linked["row"].update(thread_id="wa1", thread="Ada Lovelace", ts="2030-01-01T00:00:00Z")
        with open(media.DONE, "a") as f:
            f.write(json.dumps(linked) + "\n")
        rows = media.rows("image")
        self.assertEqual((len(rows), rows[0]["thread_id"]), (1, "wa1"))

    def test_ids_come_from_content(self):
        a = put(os.path.join(self.docs, "a.png"), b"q" * 30000)
        self.scan()
        first = media.rows("image")[0]["id"]
        os.rename(a, os.path.join(self.docs, "renamed.png"))
        self.scan()
        self.assertEqual({r["id"] for r in media.rows("image")}, {first})
        self.assertRegex(first, r"^MI[0-9a-f]{14}$")

    def test_a_file_that_failed_is_not_tried_again_unless_asked(self):
        put(os.path.join(self.docs, "bad.png"))
        tool = Fake({"bad.png": {"ok": False, "why": "took too long"}})
        self.scan(tool)
        self.scan(tool)
        self.assertEqual(len(tool.calls), 1)
        self.scan(tool, retry=True)
        self.assertEqual(len(tool.calls), 2)

    def test_one_scan_at_a_time(self):
        self.fill(2)
        lock = collect.take_lock("media_scan")
        try:
            r = self.scan()
        finally:
            collect.drop_lock(lock)
        self.assertEqual((r["read"], r["stopped"]), (0, "another media read is running"))

    def test_no_compiler_is_a_reason_not_a_traceback(self):
        self.fill(2)
        with mock.patch.object(media, "helper", lambda: ""):
            r = media.scan(cfg=self.cfg)
            st = media.status(self.cfg)
        self.assertEqual(r["read"], 0)
        self.assertIn("swift", r["stopped"])
        self.assertFalse(st["tool"])
        self.assertFalse(st["speech"]["works_here"])


class Source(Base):
    def read(self, kind):
        path = os.path.join(self.tmp, kind + ".jsonl")
        with open(path, "w") as out:
            n = media.source(kind)(None, out)
        with open(path) as f:
            return n, [json.loads(l) for l in f]

    def test_nothing_read_yet_is_a_plain_reason(self):
        with self.assertRaises(FileNotFoundError) as e:
            self.read("image")
        self.assertIn("media --estimate", str(e.exception))

    def test_rows_reach_the_collector_in_the_shape_it_knows(self):
        put(os.path.join(self.docs, "Screenshot 2025-03-02 at 10.11.12.png"))
        self.scan()
        with mock.patch.object(media, "config", lambda: dict(self.cfg, tick_seconds=0)):
            n, rows = self.read("image")
        self.assertEqual(n, 1)
        row = rows[0]
        self.assertEqual((row["src"], row["who"], row["text"], row["place"]), ("image", "me", SAID, "papers"))
        self.assertEqual(row["title"], "Screenshot 2025-03-02 at 10.11.12.png (screenshot in papers)")
        for field in ("id", "ts", "url"):
            self.assertTrue(row[field])

    def test_the_15_minute_read_takes_recent_files_only(self):
        old = put(os.path.join(self.docs, "old.png"), b"o" * 20000)
        os.utime(old, (time.time() - 90 * 86400,) * 2)
        put(os.path.join(self.docs, "first.png"), b"f" * 20000)
        self.scan(limit=1)                                           # a sample was read
        put(os.path.join(self.docs, "new.png"), b"n" * 20000)
        tool = Fake()
        real = media.scan
        with mock.patch.object(media, "config", lambda: self.cfg), mock.patch.object(media, "_memo", [0.0, None]), \
                mock.patch.object(media, "_turn", [0.0, 0.0]), \
                mock.patch.object(media, "scan", lambda **kw: real(tool=tool, can_speak=(True, "en-US", ""), **kw)):
            n, rows = self.read("image")
            self.assertEqual((tool.calls, n), ([], 1))               # nothing is read on the clock before the owner starts the first pass
            with open(media.STARTED, "w"):
                pass
            n, rows = self.read("image")
            self.assertEqual([c[1] for c in tool.calls], ["new.png"])
            self.assertEqual(n, 2)
            put(os.path.join(self.docs, "newer.png"), b"m" * 20000)
            media._memo[1] = None
            media._turn[1] = self.cfg["tick_seconds"]                # this tick's seconds are used up: the next source reads nothing new
            self.assertEqual(self.read("image")[0], 2)
            self.assertEqual(len(tool.calls), 1)

    def test_registered_with_the_collector_and_the_15_minute_read(self):
        from ctx import schedule
        for name in ("media_images", "media_audio", "media_files", "media_video"):
            self.assertEqual(collect.BY_NAME[name][0], collect.D)
            self.assertIn(name, schedule.FAST)

    def test_collected_rows_are_found_by_the_existing_search(self):
        # in a process of its own, with an archive of its own: joining the docs file here would drop the other tests' rows
        script = """
import json, os, sys
from tests import fixture
from tests.test_media import Fake, put, SAID
from ctx import answer, collect, media, paths, semantic
docs = os.path.join(fixture.HOME, "Papers")
put(os.path.join(docs, "Screenshot 2025-03-02 at 10.11.12.png"))
put(os.path.join(docs, "memo.m4a"), b"m" * 20000)
put(os.path.join(docs, "lease.pdf"), b"p" * 20000)
put(os.path.join(docs, "glacier.mov"), b"v" * 20000)
cfg = dict(media.DEFAULTS, folders=[docs])
media.config = lambda: cfg
media._shots = set()
media.battery = lambda: (False, 100)
tool = Fake({"memo.m4a": {"ok": True, "text": "we agreed the zeppelin fund closes on friday at noon", "secs": 42.0, "conf": 0.9, "locale": "en-US"},
             "lease.pdf": {"ok": True, "text": "minutes of the quince growers club, held in the long barn", "pages": 1, "chars": 60, "ocr_pages": 0}})
media.scan(tool=tool, cfg=cfg, can_speak=(True, "en-US", ""))
st = {n: collect.collect_one(n, join=False) for n in ("media_images", "media_audio", "media_files", "media_video")}
collect.assemble(paths.DOCS)
rows = answer.search([["marlow", "street"]])[0] + answer.search([["zeppelin"]])[0] + answer.search([["quince", "growers"]])[0] + answer.search([["glacier"]])[0]
units = sorted((u["src"], bool(u.get("url")), u.get("thread", "")[:10]) for u in semantic.doc_units() if u["src"] in ("image", "voice_note", "file", "video"))
print("@@" + json.dumps({"found": sorted((r["id"][:2], r["src"]) for r in rows if r["src"] in ("image", "voice_note", "file", "video")), "mine": [r["src"] for r in rows if r.get("who") == "me" and r["id"].startswith("M")], "units": units, "st": st}))
"""
        env = dict(os.environ)
        env.pop("CTX_HOME", None)
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=fixture.REPO, env=env, timeout=300)
        line = [l for l in r.stdout.splitlines() if l.startswith("@@")]
        self.assertTrue(line, r.stderr[-800:])
        got = json.loads(line[0][2:])
        self.assertEqual(got["found"], [["MA", "voice_note"], ["MF", "file"], ["MI", "image"], ["MV", "video"]])
        self.assertEqual(got["mine"], ["image"])             # the screenshot is the owner's own; the rest are not said to be
        self.assertEqual([u[0] for u in got["units"]], ["file", "image", "video", "voice_note"])
        self.assertTrue(all(u[1] for u in got["units"]))
        self.assertEqual([got["st"][n]["rows"] for n in ("media_images", "media_audio", "media_files", "media_video")], [1, 1, 1, 1])


class Command(Base):
    def run_main(self, *argv):
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), mock.patch.object(media, "DEFAULTS", dict(media.DEFAULTS, folders=[self.docs])), \
                mock.patch.object(media, "helper", lambda: ""):
            code = media.main(list(argv))
        return code, buf.getvalue()

    def test_status_with_nothing_there(self):
        code, out = self.run_main("--status", "--json")
        st = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(st["kinds"]["image"], {"files": 0, "read": 0, "left": 0, "rows": 0, "no_row": 0, "in_icloud": 0})

    def test_leave_out_is_kept_and_undone(self):
        self.run_main("--leave-out", os.path.join(self.docs, "private"))
        self.assertEqual(media.config()["leave_out"], [os.path.join(self.docs, "private")])
        self.run_main("--take-in", os.path.join(self.docs, "private"))
        self.assertEqual(media.config()["leave_out"], [])

    def test_settings(self):
        self.assertEqual(self.run_main("--set", "tick_seconds=0")[0], 0)
        self.assertEqual(media.config()["tick_seconds"], 0)
        self.assertEqual(self.run_main("--set", "speech_locale=en-US")[0], 0)
        self.assertEqual(media.config()["speech_locale"], "en-US")
        self.assertEqual(self.run_main("--set", "telegram_cache=maybe")[0], 1)
        self.assertEqual(media.config()["telegram_cache"], "off")
        self.assertEqual(self.run_main("--set", "nonsense=1")[0], 1)

    def test_estimate_counts_without_reading_when_asked_for_no_sample(self):
        put(os.path.join(self.docs, "a.png"))
        put(os.path.join(self.docs, "b.pdf"))
        code, out = self.run_main("--estimate", "--json", "--sample", "0")
        est = json.loads(out)
        self.assertEqual((est["kinds"]["image"]["files"], est["kinds"]["file"]["files"]), (1, 1))
        self.assertEqual(est["inventory"]["places"]["papers"], {"image": [1, 20000], "pdf": [1, 20000]})
        self.assertFalse(os.path.exists(media.DONE))

    def test_estimate_times_a_sample_and_keeps_none_of_it(self):
        for n in range(3):
            put(os.path.join(self.docs, "scan %d.png" % n))
        real, tool = media.scan, Fake()
        with mock.patch.object(media, "scan", lambda **kw: real(tool=tool, can_speak=(True, "en-US", ""), **kw)):
            code, out = self.run_main("--estimate", "--json", "--sample", "2")
        est = json.loads(out)
        self.assertEqual(len(tool.calls), 2)                    # two files were read to time them
        self.assertEqual((est["kinds"]["image"]["files"], est["kinds"]["image"]["left"]), (3, 3))       # and all three are still to read
        self.assertFalse(os.path.exists(media.DONE))            # nothing they said was written down
        self.assertEqual(media.done(), {})
        self.assertEqual([n for _, _, names in os.walk(media.DIR) for n in names if n.endswith(".jsonl")], [])


# ---------------------------------------------------------------- the real helper, on made-up files

def make_pdf(path, lines, size=26):
    """A one-page pdf with these lines as real text, written by hand."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    body = ("BT /F1 %d Tf 50 720 Td %d TL " % (size, size + 12) + " ".join("(%s) Tj T*" % esc(l) for l in lines) + " ET").encode()
    _write_pdf(path, [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                      b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
                      b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"])


def make_scan_pdf(path, jpeg, w, h):
    """A one-page pdf that is only a picture: no text layer, as a scanner makes it."""
    with open(jpeg, "rb") as f:
        data = f.read()
    body = b"q 612 0 0 792 0 0 cm /Im1 Do Q"
    _write_pdf(path, [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                      b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /XObject << /Im1 5 0 R >> >> >>",
                      b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
                      b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n"
                      % (w, h, len(data)) + data + b"\nendstream"])


def _write_pdf(path, objs):
    out, at = b"%PDF-1.4\n", []
    for i, o in enumerate(objs):
        at.append(len(out))
        out += b"%d 0 obj\n" % (i + 1) + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % a for a in at)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(out)


def render(pdf, out, fmt="png"):
    """Draw a pdf's page into a picture with sips, which every mac has. Through jpeg first, so the page is white and not see-through."""
    jpeg = out if fmt == "jpeg" else out + ".jpg"
    r = subprocess.run(["sips", "-s", "format", "jpeg", "-Z", "1800", pdf, "--out", jpeg], capture_output=True)
    if r.returncode == 0 and fmt != "jpeg":
        r = subprocess.run(["sips", "-s", "format", fmt, jpeg, "--out", out], capture_output=True)
        os.remove(jpeg)
    return r.returncode == 0 and os.path.exists(out)


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("swiftc") and shutil.which("sips"), "needs macos, swiftc and sips")
class RealHelper(Base):
    """The swift helper itself: text drawn into a picture is read back, a pdf with and without a text layer, a spoken
    sentence. Skipped where the helper cannot be built."""
    built = None

    @classmethod
    def setUpClass(cls):
        RealHelper.built = media.helper()

    def setUp(self):
        super().setUp()
        if not RealHelper.built:
            self.skipTest("the helper could not be built here")
        self.work = os.path.join(self.tmp, "work")
        os.makedirs(self.work)

    def picture(self, name, lines):
        pdf = os.path.join(self.work, name + ".pdf")
        make_pdf(pdf, lines)
        out = os.path.join(self.docs, name)
        os.makedirs(self.docs, exist_ok=True)
        if not render(pdf, out, "jpeg" if name.endswith(".jpg") else "png"):
            self.skipTest("sips could not draw the picture")
        return out

    def real_scan(self, **kw):
        return media.scan(cfg=self.cfg, gentle=False, **kw)

    def test_info(self):
        about = media.info()
        self.assertIn("en-US", about["ocr_languages"])
        self.assertIn(about["speech"]["permission"], ("not asked", "granted", "denied", "restricted"))

    def test_words_in_a_picture(self):
        self.picture("Screenshot 2025-03-02 at 10.11.12.png", ["Invoice 1042 for Marlow Street", "The deposit of 900 pounds is paid", "Keys are with the porter"])
        r = self.real_scan()
        self.assertEqual((r["read"], r["rows"]), (1, 1))
        row = media.rows("image")[0]
        self.assertIn("Marlow Street", row["text"])
        self.assertIn("porter", row["text"])
        self.assertEqual((row["who"], row["media"]), ("me", "screenshot"))
        self.assertNotIn("light", row)

    def test_a_seed_phrase_and_a_card_in_a_picture_never_reach_the_disk(self):
        self.picture("wallet.png", ["Secret Recovery Phrase"] + ["%d. %s      %d. %s      %d. %s" % (i + 1, WORDS[i], i + 2, WORDS[i + 1], i + 3, WORDS[i + 2])
                                                                 for i in range(0, 12, 3)])
        self.picture("card.png", ["Card number", "4242 4242", "4242 4242", "The name on it is Sam Vimes of Ankh"])
        self.real_scan()
        with open(media.DONE) as f:
            saved = f.read()
        self.assertEqual(saved.count('"row"'), 2)
        for w in WORDS[1:-1] + ["4242 4242", "4242\\n4242"]:
            self.assertNotIn(w, saved.lower())
        self.assertIn(R, saved)
        self.assertIn("Sam Vimes", saved)

    def test_pdf_with_text_and_pdf_that_is_only_a_scan(self):
        os.makedirs(self.docs)
        make_pdf(os.path.join(self.docs, "typed.pdf"), ["Minutes of the kettle club", "The fund closes on Friday at noon"])
        page = os.path.join(self.work, "page.pdf")
        make_pdf(page, ["Scanned letter from the landlord", "The lease is renewed for two years"])
        jpeg = os.path.join(self.work, "page.jpg")
        if not render(page, jpeg, "jpeg"):
            self.skipTest("sips could not draw the page")
        dims = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", jpeg], capture_output=True, text=True).stdout
        w, h = [int(line.split(":")[1]) for line in dims.splitlines() if "pixel" in line]
        make_scan_pdf(os.path.join(self.docs, "scanned.pdf"), jpeg, w, h)
        self.real_scan()
        by = {os.path.basename(x["url"]): x for x in media.rows("file")}
        self.assertIn("fund closes on Friday", by["typed.pdf"]["text"])
        self.assertEqual((by["typed.pdf"]["pages"], by["typed.pdf"].get("ocr_pages")), (1, None))
        self.assertIn("lease is renewed", by["scanned.pdf"]["text"])
        self.assertEqual(by["scanned.pdf"]["ocr_pages"], 1)

    def test_a_file_that_is_not_what_its_name_says(self):
        put(os.path.join(self.docs, "fake.png"), b"this is not a picture " * 1000)
        put(os.path.join(self.docs, "fake.pdf"), b"this is not a pdf " * 1000)
        put(os.path.join(self.docs, "fake.mp4"), b"this is not a video " * 1000)
        r = self.real_scan()
        self.assertEqual((r["read"], r["rows"]), (3, 0))
        self.assertEqual(sorted(d["why"] for d in media.done().values()),
                         ["could not be read as a pdf", "could not be read as a picture", "could not be read as a video"])

    def test_a_spoken_sentence(self):
        ok, locale, why = media.speech(self.cfg)
        if not ok or not shutil.which("say"):
            self.skipTest("this mac cannot transcribe from a command-line tool: " + why)
        os.makedirs(self.docs)
        wav = os.path.join(self.docs, "memo.aiff")
        if subprocess.run(["say", "-o", wav, "The quarterly budget meeting moved to Thursday afternoon"], capture_output=True).returncode != 0 or not os.path.exists(wav):
            self.skipTest("say could not make a recording here")
        self.real_scan()
        row = media.rows("audio")[0]
        self.assertIn("budget meeting", row["text"].lower())
        self.assertEqual(row["src"], "voice_note")
        self.assertGreater(row["secs"], 1)


if __name__ == "__main__":
    unittest.main()
