"""Contacts and the name book, reminders, calls and voice memos, on tiny made-up stores of the same shape as the mac's,
in the made-up home. And a store macos keeps this process out of: a plain "blocked" reason, the old rows kept."""
import io, json, os, shutil, sqlite3, stat, unittest
from unittest import mock
from tests import fixture
from ctx import apple, collect, namebook, paths

APPLE = 978307200
T0 = 1772359200 - APPLE         # 2026-03-01 10:00 utc, as the mac counts it


def home():
    """The made-up home, as it is right now: readers ask the environment each time, so the tests do too. Never the real one."""
    h = os.path.expanduser("~")
    if "ctx-test-" not in h:
        raise unittest.SkipTest("home() is not the made-up home")
    return h


def db(path, schema, **tables):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    for stmt in schema:
        con.execute(stmt)
    for table, rows in tables.items():
        for r in rows:
            con.execute("insert into %s values (%s)" % (table, ",".join("?" * len(r))), r)
    con.commit()
    con.close()


def contacts_store(source="", people=()):
    """people: (pk, first, last, org, uid, [phones], [emails], note)"""
    root = os.path.join(home(), "Library", "Application Support", "AddressBook", *(["Sources", source] if source else []))
    db(os.path.join(root, "AddressBook-v22.abcddb"),
       ["create table ZABCDRECORD (Z_PK integer primary key, ZFIRSTNAME, ZLASTNAME, ZNICKNAME, ZORGANIZATION, ZUNIQUEID, ZMODIFICATIONDATE)",
        "create table ZABCDPHONENUMBER (ZOWNER, ZFULLNUMBER)", "create table ZABCDEMAILADDRESS (ZOWNER, ZADDRESS)", "create table ZABCDNOTE (ZCONTACT, ZTEXT)"],
       ZABCDRECORD=[(p[0], p[1], p[2], None, p[3], p[4], T0) for p in people],
       ZABCDPHONENUMBER=[(p[0], n) for p in people for n in p[5]], ZABCDEMAILADDRESS=[(p[0], e) for p in people for e in p[6]],
       ZABCDNOTE=[(p[0], p[7]) for p in people if p[7]])


def whatsapp_stores():
    root = os.path.join(home(), "Library", "Group Containers", "group.net.whatsapp.WhatsApp.shared")
    db(os.path.join(root, "ContactsV2.sqlite"), ["create table ZWAADDRESSBOOKCONTACT (ZFULLNAME, ZPHONENUMBER, ZWHATSAPPID, ZLID)"],
       ZWAADDRESSBOOKCONTACT=[("Grace Hopper", "+14155550111", "14155550111@s.whatsapp.net", "700111@lid"), ("Maya From Whatsapp", "+5511912345678", "5511912345678@s.whatsapp.net", "700222@lid")])
    db(os.path.join(root, "ChatStorage.sqlite"),
       ["create table ZWAPROFILEPUSHNAME (ZJID, ZPUSHNAME)",
        "create table ZWACHATSESSION (Z_PK integer primary key, ZPARTNERNAME, ZSESSIONTYPE, ZCONTACTJID)",
        "create table ZWAGROUPMEMBER (Z_PK integer primary key, ZMEMBERJID, ZCHATSESSION)",
        "create table ZWAMESSAGE (Z_PK integer primary key, ZMESSAGEDATE, ZISFROMME, ZTEXT, ZFROMJID, ZCHATSESSION, ZGROUPMEMBER)"],
       ZWAPROFILEPUSHNAME=[("700333@lid", "Tomas ~ pots"), ("14155550111@s.whatsapp.net", "gracie"), ("700444@lid", "🙂")],
       ZWACHATSESSION=[(1, "+1 (415) 555-0111", 0, "14155550111@s.whatsapp.net"), (2, "‪+55 11 91234 5678‬", 0, "700222@lid"), (3, "+44 20 7946 0000", 0, "442079460000@s.whatsapp.net"),
                       (4, "Ada Lovelace", 0, "15550001111@s.whatsapp.net"), (5, "kiln club", 1, "1203630@g.us"), (6, "+1 555 000 3333", 0, "700333@lid")],
       ZWAGROUPMEMBER=[(1, "700111@lid", 5), (2, "700333@lid", 5), (3, "700999@lid", 5)],
       ZWAMESSAGE=[(1, T0, 0, "hello from a number", "14155550111@s.whatsapp.net", 1, None), (2, T0, 1, "hello back", None, 1, None), (3, T0, 0, "oi", "700222@lid", 2, None),
                   (4, T0, 0, "nobody knows me", "442079460000@s.whatsapp.net", 3, None), (5, T0, 0, "already named", "15550001111@s.whatsapp.net", 4, None),
                   (6, T0, 0, "who brings the clay", "1203630@g.us", 5, 1), (7, T0, 0, "i will", "1203630@g.us", 5, 2), (8, T0, 0, "me too", "1203630@g.us", 5, 3),
                   (9, T0, 0, "self-named only", "700333@lid", 6, None)])
    db(os.path.join(root, "CallHistory.sqlite"),
       ["create table ZWAAGGREGATECALLEVENT (Z_PK integer primary key, ZINCOMING, ZMISSED, ZVIDEO)",
        "create table ZWACDCALLEVENT (Z_PK integer primary key, ZDATE, ZDURATION, Z1CALLEVENTS, ZCALLIDSTRING, ZGROUPJIDSTRING)",
        "create table ZWACDCALLEVENTPARTICIPANT (Z_PK integer primary key, Z1PARTICIPANTS, ZJIDSTRING)"],
       ZWAAGGREGATECALLEVENT=[(10, 0, 0, 0), (11, 1, 1, 1), (12, 1, 0, 0)],
       ZWACDCALLEVENT=[(501, T0, 600, 10, "call-a", None), (502, T0 + 3600, 0, 11, "call-b", None), (503, T0 + 7200, 45, 12, "call-c", "1203630@g.us"), (504, T0 + 7200, 45, 12, "call-c", "1203630@g.us")],
       ZWACDCALLEVENTPARTICIPANT=[(1, 10, "700111@lid"), (2, 11, "700333@lid"), (3, 12, "700111@lid"), (4, 12, "700999@lid")])


class Base(unittest.TestCase):
    def setUp(self):
        self.wipe()
        self.addCleanup(self.wipe)
        book = os.path.join(paths.HOME, "namebook-test.json")
        p = mock.patch.object(namebook, "PATH", book)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(lambda: os.path.exists(book) and os.remove(book))
        namebook._mem.clear()

    def wipe(self):
        lib = os.path.join(home(), "Library")
        for d, dirs, _ in os.walk(lib):
            for x in dirs:
                os.chmod(os.path.join(d, x), 0o700)
        shutil.rmtree(lib, ignore_errors=True)
        namebook._mem.clear()

    def block(self, *parts):
        d = os.path.join(home(), "Library", *parts)
        os.makedirs(d, exist_ok=True)
        os.chmod(d, 0)
        if os.access(d, os.R_OK):
            os.chmod(d, 0o700)
            self.skipTest("this user can read anything: a blocked folder cannot be made")

    def rows(self, fn, days=None):
        out = io.StringIO()
        n = fn(days, out)
        got = [json.loads(l) for l in out.getvalue().split("\n") if l]
        self.assertEqual(n, len(got))
        return got


class Numbers(unittest.TestCase):
    def test_one_number_however_it_is_written(self):
        for ways, one in ((("+55 11 91234 5678", "011 91234 5678", "11912345678", "0055-11-91234-5678", "\u202a+55 11 91234 5678\u202c", "5511912345678@s.whatsapp.net".split("@")[0]), "1912345678"),
                          (("+62 812 3456 7890", "0812-3456-7890", "6281234567890"), "1234567890"),
                          (("+91 98765 43210", "098765 43210", "9876543210", "0091-98765-43210"), "9876543210"),
                          (("+1 (415) 555-0100", "4155550100", "1-415-555-0100", "001 415 555 0100"), "4155550100")):
            keys = {namebook.key(n) for n in ways}
            self.assertEqual(keys, {one}, ways)                           # however a number is written, in whichever country's way, it is one number
        self.assertNotEqual(namebook.key("+1 415 555 0100"), namebook.key("+1 415 555 0101"))
        self.assertEqual(namebook.key("+47 22 33 44 55"), "4722334455")                 # a shorter national number keeps its country code
        self.assertEqual((namebook.key("12345"), namebook.key(""), namebook.key("no digits")), ("", "", ""))


class Book(Base):
    def test_names_from_every_place_the_best_first(self):
        contacts_store(people=[(1, "Maya", "Okafor", None, "U1", ["011 91234 5678"], ["Maya@Example.com"], "met at the kiln"),
                               (2, None, None, "Clay & Co", "U2", ["+1 415 555 0199"], [], None), (3, None, None, None, "U3", ["+1 415 555 0000"], [], None)])
        contacts_store(source="AAAA-BBBB", people=[(1, "Maya", "Okafor", None, "U1", ["+55 11 91234 5678"], [], "a copy in another account"),
                                                   (2, "Ravi", "Anand", None, "U9", ["020 7946 0018"], ["ravi@example.com"], None)])
        whatsapp_stores()
        os.makedirs(os.path.join(paths.HOME, "imports", "google-made-up", "Takeout", "Contacts"), exist_ok=True)
        vcf = os.path.join(paths.HOME, "imports", "google-made-up", "Takeout", "Contacts", "All.vcf")
        self.addCleanup(shutil.rmtree, os.path.join(paths.HOME, "imports", "google-made-up"), True)
        with open(vcf, "w") as f:
            f.write("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Lee Park\r\nN:Park;Lee;;;\r\nitem1.TEL;TYPE=CELL:+1 415 555 0177\r\nEMAIL;TYPE=INTERNET:lee@exam\r\n ple.com\r\nEND:VCARD\r\n"
                    "BEGIN:VCARD\r\nN:Hopper;Grace;;;\r\nTEL:+1 415 555 0111\r\nEND:VCARD\r\nBEGIN:VCARD\r\nFN:No Way To Reach\r\nEND:VCARD\r\n")
        book = namebook.build()
        self.assertEqual(book["sources"], {"apple contacts": 3, "whatsapp contacts": 2, "google contacts": 2, "whatsapp push names": 2, "x archive": 0})
        self.assertEqual(stat.S_IMODE(os.stat(namebook.PATH).st_mode), 0o600)
        name = namebook.name_for
        self.assertEqual((name("+55 11 91234 5678"), name("11912345678"), name("maya@example.com"), name("5511912345678@s.whatsapp.net")), ("Maya Okafor",) * 4)      # the owner's own card wins over whatsapp's
        self.assertEqual((name("+1 415 555 0199"), name("+44 20 7946 0018"), name("ravi@example.com")), ("Clay & Co", "Ravi Anand", "Ravi Anand"))
        self.assertEqual((name("700111@lid"), name("+14155550111"), name("700222@lid")), ("Grace Hopper", "Grace Hopper", "Maya From Whatsapp"))
        self.assertEqual((name("+1 415 555 0177"), name("lee@example.com")), ("Lee Park", "Lee Park"))
        self.assertEqual((name("700333@lid"), name("700333@lid", weak=False), name("700444@lid")), ("~Tomas ~ pots", "", ""))          # a self-given name only when asked, an emoji never
        self.assertEqual((name("+1 415 555 0000"), name("someone@nowhere.example"), name("Ada Lovelace"), name("")), ("", "", "", ""))
        t = namebook.thread_name
        self.assertEqual((t("+55 11 91234 5678"), t("maya@example.com"), t("Ada Lovelace"), t("+1 999 999 9999"), t("+1 555 000 3333", "700333@lid")),
                         ("Maya Okafor", "Maya Okafor", "Ada Lovelace", "+1 999 999 9999", "~Tomas ~ pots"))

    def test_a_process_kept_out_of_contacts_builds_from_the_rest_and_never_shrinks_a_fuller_book(self):
        whatsapp_stores()
        self.block("Application Support", "AddressBook")
        book = namebook.build()
        self.assertEqual((book["sources"]["apple contacts"], namebook.name_for("700111@lid")), ("blocked by macos", "Grace Hopper"))
        with self.assertRaises(PermissionError) as e:
            apple.contacts(None, io.StringIO())
        self.assertIn("Full Disk Access", str(e.exception))
        with open(namebook.PATH, "w") as f:                                             # the app, which may read contacts, wrote a fuller one
            json.dump({"v": 1, "phones": {"4155550123": "Only In Contacts"}, "emails": {}, "ids": {}, "weak": {}, "sources": {"apple contacts": 40}}, f)
        namebook._mem.clear()
        namebook.build()
        self.assertEqual(namebook.name_for("+1 415 555 0123"), "Only In Contacts")

    def test_contacts_with_a_note_are_rows(self):
        contacts_store(people=[(1, "Maya", "Okafor", None, "U1", ["011 91234 5678"], [], "met at the kiln. my key is sk-abcdefghijklmnopqrstuvwxyz012345"),
                               (2, "Ravi", "Anand", None, "U2", ["+1 415 555 0100"], [], None)])
        got = self.rows(apple.contacts)
        self.assertEqual([(r["id"][:2], r["src"], r["title"], r["ts"][:10]) for r in got], [("AB", "contacts", "Maya Okafor", "2026-03-01")])
        self.assertIn("met at the kiln", got[0]["text"])
        self.assertNotIn("sk-abcdefghijklmnop", got[0]["text"])
        self.assertEqual(self.rows(apple.contacts), got)
        self.assertEqual(namebook.name_for("4155550100"), "Ravi Anand")                   # reading contacts wrote the book

    def test_no_contacts_app_is_a_plain_reason(self):
        with self.assertRaises(FileNotFoundError):
            apple.contacts(None, io.StringIO())


class Chats(Base):
    def setUp(self):
        super().setUp()         # the chat readers fixed their store paths when ctx was first imported: point them at the made-up home of now
        for name, rel in (("WA_DB", "Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite"), ("IM_DB", "Library/Messages/chat.db")):
            p = mock.patch.object(collect, name, os.path.join(home(), rel))
            p.start()
            self.addCleanup(p.stop)

    def test_whatsapp_threads_and_group_senders_get_their_names(self):
        whatsapp_stores()
        got = {r["id"]: r for r in self.rows(collect.whatsapp)}
        self.assertEqual([got["W%d" % n]["thread"] for n in (1, 3, 4, 5, 9)], ["Grace Hopper", "Maya From Whatsapp", "+44 20 7946 0000", "Ada Lovelace", "~Tomas ~ pots"])
        self.assertEqual((got["W1"]["thread_id"], got["W2"]["thread"], got["W2"]["who"]), ("wa1", "Grace Hopper", "me"))
        self.assertEqual([(got["W%d" % n]["thread"], got["W%d" % n]["kind"], got["W%d" % n]["sender"]) for n in (6, 7, 8)],
                         [("kiln club", "group", "Grace Hopper"), ("kiln club", "group", "~Tomas ~ pots"), ("kiln club", "group", "0999")])

    def test_an_older_whatsapp_store_without_those_columns_still_reads(self):
        root = os.path.join(home(), "Library", "Group Containers", "group.net.whatsapp.WhatsApp.shared")
        db(os.path.join(root, "ChatStorage.sqlite"),
           ["create table ZWACHATSESSION (Z_PK integer primary key, ZPARTNERNAME, ZSESSIONTYPE)", "create table ZWAMESSAGE (Z_PK integer primary key, ZMESSAGEDATE, ZISFROMME, ZTEXT, ZFROMJID, ZCHATSESSION)"],
           ZWACHATSESSION=[(1, "+1 415 555 0111", 0)], ZWAMESSAGE=[(1, T0, 0, "hello", "14155550111@s.whatsapp.net", 1)])
        got = self.rows(collect.whatsapp)
        self.assertEqual([(r["thread"], r["sender"]) for r in got], [("+1 415 555 0111", "0111")])

    def test_imessage_threads_known_by_a_number_or_an_address(self):
        contacts_store(people=[(1, "Maya", "Okafor", None, "U1", ["+55 11 91234 5678"], ["maya@example.com"], None)])
        db(os.path.join(home(), "Library", "Messages", "chat.db"),
           ["create table message (ROWID integer primary key, date, is_from_me, text, attributedBody)", "create table chat (ROWID integer primary key, display_name, chat_identifier, style)",
            "create table chat_message_join (chat_id, message_id)"],
           message=[(1, T0 * 1e9, 0, "from her phone", None), (2, T0 * 1e9, 0, "from her mail", None), (3, T0 * 1e9, 0, "a stranger", None), (4, T0 * 1e9, 0, "in a named group", None)],
           chat=[(1, "", "+5511912345678", 45), (2, None, "maya@example.com", 45), (3, "", "+14155550000", 45), (4, "kiln club", "chat123", 43)],
           chat_message_join=[(1, 1), (2, 2), (3, 3), (4, 4)])
        got = {r["id"]: r for r in self.rows(collect.imessage)}
        self.assertEqual([got["I%d" % n]["thread"] for n in (1, 2, 3, 4)], ["Maya Okafor", "Maya Okafor", "+14155550000", "kiln club"])
        self.assertEqual((got["I1"]["thread_id"], got["I2"]["thread_id"]), ("im1", "im2"))


class Reminders(Base):
    def store(self, name="Data-AAAA.sqlite", rows=(), lists=((7, "errands"),)):
        """rows: (pk, title, notes, done, done_at, made, due, list, ck, gone, flagged)"""
        db(os.path.join(home(), "Library", "Group Containers", "group.com.apple.reminders", "Container_v1", "Stores", name),
           ["create table ZREMCDREMINDER (Z_PK integer primary key, ZTITLE, ZNOTES, ZCOMPLETED, ZCOMPLETIONDATE, ZCREATIONDATE, ZLASTMODIFIEDDATE, ZDUEDATE, ZLIST, ZCKIDENTIFIER, ZMARKEDFORDELETION, ZFLAGGED)",
            "create table ZREMCDBASELIST (Z_PK integer primary key, ZNAME)"],
           ZREMCDREMINDER=[(r[0], r[1], r[2], r[3], r[4], r[5], r[5], r[6], r[7], r[8], r[9], r[10]) for r in rows], ZREMCDBASELIST=list(lists))

    def test_every_reminder_with_its_list_and_whether_it_is_done(self):
        self.store(rows=[(1, "send maya the glaze notes", "the blue one", 0, None, T0, T0 + 86400, 7, "CK1", 0, 1),
                         (2, "order clay", None, 1, T0 + 3600, T0 - 86400, None, 7, "CK2", 0, 0),
                         (3, "thrown away", None, 0, None, T0, None, 7, "CK3", 1, 0), (4, "  ", None, 0, None, T0, None, 7, "CK4", 0, 0)])
        self.store(name="Data-local.sqlite", rows=[(1, "send maya the glaze notes", "the blue one", 0, None, T0, T0 + 86400, 7, "CK1", 0, 1), (2, "water the fern", None, 0, None, T0 + 60, None, None, None, 0, 0)])
        got = {r["title"]: r for r in self.rows(apple.reminders)}
        self.assertEqual(sorted(got), ["order clay", "send maya the glaze notes", "water the fern"])      # the one in two stores once
        a, b = got["send maya the glaze notes"], got["order clay"]
        self.assertEqual((a["src"], a["who"], a["list"], a["done"], a["due"], a["ts"], a.get("flagged")), ("reminders", "me", "errands", False, "2026-03-02T10:00:00Z", "2026-03-01T10:00:00Z", True))
        self.assertEqual(a["text"], "send maya the glaze notes\nthe blue one")
        self.assertEqual((b["done"], b["done_at"], b["due"]), (True, "2026-03-01T11:00:00Z", ""))
        self.assertEqual(self.rows(apple.reminders), list(self.rows(apple.reminders)))
        self.assertEqual(len({r["id"] for r in got.values()}), 3)
        # what is still to do, for the home: the one with a date first
        part = collect._part("reminders")
        os.makedirs(os.path.dirname(part), exist_ok=True)
        self.addCleanup(lambda: os.path.exists(part) and os.remove(part))
        with open(part, "w") as f:
            f.write("".join(json.dumps(r) + "\n" for r in got.values()))
        self.assertEqual([r["title"] for r in apple.open_reminders()], ["send maya the glaze notes", "water the fern"])
        said = apple.promised(now=1772359200 + 3 * 86400 + 120)
        self.assertEqual([(p["what"], p["when"], p["days"], p["thread"], p["src"], p["id"][:2]) for p in said],
                         [("send maya the glaze notes", "2026-03-02T10:00:00Z", 3, "errands", "reminders", "RM"), ("water the fern", "2026-03-01T10:01:00Z", 3, "reminders", "reminders", "RM")])

    def test_blocked_and_absent_are_plain_reasons(self):
        with self.assertRaises(FileNotFoundError):
            apple.reminders(None, io.StringIO())
        self.assertEqual(apple.open_reminders(), [])
        self.block("Group Containers", "group.com.apple.reminders")
        with self.assertRaises(PermissionError) as e:
            apple.reminders(None, io.StringIO())
        self.assertIn("Full Disk Access", str(e.exception))


class Calls(Base):
    def mac(self, rows):
        """rows: (pk, when, secs, address, outgoing, answered, type, provider, uid)"""
        db(os.path.join(home(), "Library", "Application Support", "CallHistoryDB", "CallHistory.storedata"),
           ["create table ZCALLRECORD (Z_PK integer primary key, ZDATE, ZDURATION, ZADDRESS, ZORIGINATED, ZANSWERED, ZCALLTYPE, ZSERVICE_PROVIDER, ZUNIQUE_ID, ZNAME)"],
           ZCALLRECORD=[r + (None,) for r in rows])

    def test_calls_from_the_mac_and_from_whatsapp_named_and_counted_once(self):
        contacts_store(people=[(1, "Maya", "Okafor", None, "U1", ["+55 11 91234 5678"], ["maya@example.com"], None)])
        whatsapp_stores()
        self.mac([(1, T0 - 100, 754, b"+5511912345678", 1, 1, 1, "com.apple.Telephony", "A"), (2, T0 - 50, 0, "+14155550000", 0, 0, 1, "com.apple.Telephony", "B"),
                  (3, T0 - 20, 30, "maya@example.com", 0, 1, 8, "com.apple.FaceTime", "C"), (4, T0 + 5, 600, "+14155550111", 1, 1, 1, "net.whatsapp.WhatsApp", "D"),
                  (5, T0 + 90000, 60, "+14155550111", 0, 1, 1, "net.whatsapp.WhatsApp", "E")])
        got = self.rows(apple.calls)
        self.assertEqual([r["text"] for r in got], [
            "phone call to Maya Okafor, 13 min", "missed phone call from +14155550000", "facetime video call from Maya Okafor, 30 sec",
            "whatsapp call to Grace Hopper, 10 min",                                      # in both histories: once
            "missed whatsapp video call from ~Tomas ~ pots", "whatsapp call from Grace Hopper, someone on whatsapp, 45 sec",      # held twice by whatsapp: once
            "whatsapp call from Grace Hopper, 60 sec"])
        a = got[0]
        self.assertEqual((a["src"], a["who"], a["with"], a["secs"], a["direction"], a["via"], a["ts"][:10], a["title"]), ("calls", "me", ["Maya Okafor"], 754, "out", "phone", "2026-03-01", "Maya Okafor"))
        self.assertEqual((got[5]["group"], got[1]["who"], got[1]["direction"]), (True, "them", "missed"))
        self.assertEqual(len({r["id"] for r in got}), 7)
        self.assertEqual(self.rows(apple.calls), got)
        self.assertEqual(len(self.rows(apple.calls, days=1)), 0)

    def test_whatsapp_alone_when_the_mac_has_no_call_history_and_nothing_when_it_is_kept_out(self):
        whatsapp_stores()
        self.assertEqual(len(self.rows(apple.calls)), 3)
        self.block("Application Support", "CallHistoryDB")
        with self.assertRaises(PermissionError) as e:                                    # a part of the calls must not replace all of them
            apple.calls(None, io.StringIO())
        self.assertIn("Full Disk Access", str(e.exception))

    def test_no_call_history_anywhere(self):
        with self.assertRaises(FileNotFoundError):
            apple.calls(None, io.StringIO())


class Memos(Base):
    def test_titles_dates_and_lengths_only(self):
        db(os.path.join(home(), "Library", "Group Containers", "group.com.apple.VoiceMemos.shared", "Recordings", "CloudRecordings.db"),
           ["create table ZCLOUDRECORDING (Z_PK integer primary key, ZENCRYPTEDTITLE, ZCUSTOMLABEL, ZDATE, ZDURATION, ZPATH, ZUNIQUEID)"],
           ZCLOUDRECORDING=[(1, "kiln ideas", None, T0, 185.4, "/made/up/20260301 100000.m4a", "V1"), (2, None, "older label", T0 - 86400 * 400, 12, "b.m4a", "V2"), (3, None, None, T0 + 60, 5, None, None)])
        got = self.rows(apple.voice_memos)
        self.assertEqual([(r["title"], r["text"], r["secs"], r["file"], r["src"], r["who"]) for r in got],
                         [("kiln ideas", "voice memo: kiln ideas, 3 min", 185, "20260301 100000.m4a", "voice_memo", "me"),
                          ("older label", "voice memo: older label, 12 sec", 12, "b.m4a", "voice_memo", "me"), ("recording", "voice memo: recording, 5 sec", 5, "", "voice_memo", "me")])
        self.assertEqual(got[0]["ts"], "2026-03-01T10:00:00Z")
        self.assertEqual(self.rows(apple.voice_memos), got)

    def test_blocked_and_absent(self):
        with self.assertRaises(FileNotFoundError):
            apple.voice_memos(None, io.StringIO())
        self.block("Group Containers", "group.com.apple.VoiceMemos.shared")
        with self.assertRaises(PermissionError):
            apple.voice_memos(None, io.StringIO())


class Wired(unittest.TestCase):
    def test_the_four_are_sources_read_with_the_files_on_this_mac(self):
        from ctx import schedule
        names = {n: g for n, g, _ in collect.TABLE}
        for n in ("contacts", "reminders", "calls", "voice_memos"):
            self.assertEqual(names.get(n), collect.D, n)
            self.assertIn(n, schedule.FAST)
        order = [n for n, _, _ in collect.TABLE]
        self.assertLess(order.index("contacts"), order.index("calls"))

    def test_a_blocked_store_is_a_skip_with_the_reason_and_keeps_its_rows(self):
        lib = os.path.join(home(), "Library", "Group Containers", "group.com.apple.reminders")
        shutil.rmtree(os.path.join(home(), "Library"), ignore_errors=True)
        os.makedirs(lib)
        os.chmod(lib, 0)
        self.addCleanup(lambda: (os.chmod(lib, 0o700), shutil.rmtree(os.path.join(home(), "Library"), ignore_errors=True)))
        if os.access(lib, os.R_OK):
            self.skipTest("this user can read anything")
        part = collect._part("reminders")
        os.makedirs(os.path.dirname(part), exist_ok=True)
        with open(part, "w") as f:
            f.write(json.dumps({"id": "RMold", "src": "reminders", "title": "kept from the last read"}) + "\n")
        self.addCleanup(lambda: os.path.exists(part) and os.remove(part))
        with mock.patch.object(collect, "assemble", lambda g: None), mock.patch.object(collect, "_save_status", lambda n, st: None):
            st = collect.collect_one("reminders", join=False)
        self.assertEqual((st["rows"], st["stale"]), (1, True))
        self.assertIn("blocked by macOS", st["why"])


if __name__ == "__main__":
    unittest.main()
