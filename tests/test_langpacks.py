"""Words of particular languages live in ctx/langpacks.py and nowhere else; every pack is used alike, and a pack added
is in use at once. Every line here is made up."""
import os, re, unittest
from tests import fixture
from ctx import events, langpacks, now, scrub
from ctx.scrub import R

OTHERS = [c for c in langpacks.codes() if c != "en"]


class Packs(unittest.TestCase):
    def test_several_languages_from_different_regions_with_like_coverage(self):
        self.assertGreaterEqual(len(langpacks.codes()), 8)
        for want in ("de", "es", "fr", "hi", "id", "ja", "pt"):
            self.assertIn(want, OTHERS)
        for key in ("is", "not_a_password", "everyday", "account", "asks", "promises", "not_promises", "done", "intro", "not_found", "automated"):
            sizes = {c: len(langpacks.PACKS[c].get(key) or []) for c in OTHERS}
            self.assertTrue(all(sizes.values()), (key, sizes))            # no language is left without a list another has
            if key in ("not_a_password", "everyday"):
                self.assertLessEqual(max(sizes.values()), 1.5 * min(sizes.values()), (key, sizes))      # and none is far ahead
        for c in langpacks.codes():
            self.assertTrue(langpacks.PACKS[c].get("name"), c)
            self.assertEqual(set(langpacks.PACKS[c]) - set(langpacks.KEYS) - set(langpacks.FLAGS) - {"name"}, set(), c)
        self.assertGreaterEqual(sum(bool(langpacks.PACKS[c].get("verb_last")) for c in langpacks.codes()), 2)      # a property of languages, not of one

    def test_every_piece_is_a_pattern_and_no_everyday_word_could_be_in_a_seed_phrase(self):
        for c in langpacks.codes():
            for key in ("account", "asks", "promises", "not_promises", "done", "intro", "not_found", "automated"):
                for piece in langpacks.PACKS[c].get(key) or []:
                    re.compile(piece)
            for w in langpacks.PACKS[c].get("everyday") or []:
                self.assertNotIn(w, scrub._BIP39, (c, w))
                self.assertTrue(w.isascii() and w.isalpha() and 3 <= len(w) <= 8, (c, w))

    def test_each_language_is_read_the_same_way(self):
        lines = {"de": ("das password ist Tiger@12", "ich schicke es dir morgen", "hab es geschickt", "sag mir bescheid", "ich stelle dich sam vor"),
                 "en": ("the password is Tiger@12", "i'll send it tomorrow", "sent, have a look", "can you call me", "let me intro you two"),
                 "fr": ("le password est Tigre@12", "je t'envoie ça demain", "c'est fait", "tu me tiens au courant", "je te présente ines"),
                 "ja": ("password wa Tora@12 desu", "ashita okurimasu", "okurimashita", "oshiete kudasai", "ravi wo shoukai shimasu"),
                 "es": ("el password es Tigre@12", "te lo mando mañana", "ya lo envié", "me avisas cuando llegues", "te presento a maya"),
                 "hi": ("password hai Sher@12", "kal bhej dunga", "bhej diya", "bata do kab aana hai", "tumhe sam se milwata hun"),
                 "id": ("password adalah Macan@12", "besok aku kirim", "sudah dikirim", "tolong kabari aku", "aku kenalin kamu sama ines"),
                 "pt": ("o password é Tigre@12", "vou mandar amanhã", "já enviei", "me avisa quando chegar", "te apresento a ada")}
        self.assertEqual(sorted(lines), langpacks.codes())
        for c, (secret, promise, done, ask, intro) in lines.items():
            self.assertIn(R, scrub.scrub(secret), (c, secret))
            self.assertNotIn("@12", scrub.scrub(secret), (c, secret))
            self.assertTrue(now.PROMISE.search(promise), (c, promise))
            self.assertTrue(now.DONE.search(done), (c, done))
            self.assertTrue(now.ASKS.search(ask), (c, ask))
            self.assertTrue(events.INTRO.search(intro), (c, intro))

    def test_what_is_not_a_secret_stays_in_each_language(self):
        for line in ("the password is wrong", "el password es incorrecta", "password galat hai", "password itu salah", "o password é errada", "password adalah rahasia kita",
                     "das password ist falsch", "le password est incorrect", "password wa chigau", "ein neues konto bei der bank", "un nouveau compte demain",
                     "mi cuenta de correo es nueva", "conta nova no banco", "rekening baru ya"):
            self.assertEqual(scrub.scrub(line), line)
        for line, digits in (("cuenta 123456789012", "123456789012"), ("conta 123456789012", "123456789012"), ("rekening 123456789012", "123456789012"), ("khata 123456789012", "123456789012"), ("konto 123456789012", "123456789012"), ("compte 123456789012", "123456789012"), ("kouza 123456789012", "123456789012"),
                             ("account 123456789012", "123456789012")):
            self.assertNotIn(digits, scrub.scrub(line), line)

    def test_a_new_language_pack_entry_is_picked_up(self):
        secret, promise, done, ask, intro = "password ni Simba@12", "nitatuma kesho", "nimeshatuma", "tafadhali nijulishe", "nakutambulisha kwa ravi"
        account, sentence = "akaunti 123456789012", " ".join(["kwa"] + "apple river stone cloud table window garden pencil yellow market bridge candle".split())
        before = (scrub.scrub(secret), bool(now.PROMISE.search(promise)), bool(now.DONE.search(done)), bool(now.ASKS.search(ask)), bool(events.INTRO.search(intro)), scrub.scrub(account))
        self.assertEqual(before, (secret, False, False, False, False, account))                 # nothing knows the language yet
        self.assertNotIn("kwa", scrub._STOP)
        self.assertEqual(scrub.scrub("password simbamkuu ndiyo"), "password simbamkuu ndiyo")
        langpacks.add("sw", {"name": "Swahili", "is": ["ni"], "not_a_password": ["sahihi"], "everyday": ["kwa", "sana"], "account": ["akaunti"], "asks": ["tafadhali"],
                             "promises": ["nitatuma"], "done": ["nimeshatuma"], "intro": [r"nakutambulisha\w*"]})
        self.addCleanup(langpacks.remove, "sw")
        self.assertIn("sw", langpacks.codes())
        self.assertNotIn("Simba@12", scrub.scrub(secret))
        self.assertEqual(scrub.scrub("password ni sahihi"), "password ni sahihi")
        self.assertNotIn("123456789012", scrub.scrub(account))
        self.assertIn("kwa", scrub._STOP)
        self.assertTrue(now.PROMISE.search(promise) and now.DONE.search(done) and now.ASKS.search(ask) and events.INTRO.search(intro))
        self.assertTrue(now._asks("tafadhali nijulishe ukifika"))
        langpacks.add("sw", {"is": ["ndiyo"], "verb_last": True})                               # a language that says "is" after the value: one property, and that order is read too
        self.assertNotIn("simbamkuu", scrub.scrub("password simbamkuu ndiyo"))
        langpacks.add("sw", {"done": ["tayari"]})                                               # a list can be added to later
        self.assertTrue(now.DONE.search("tayari") and now.DONE.search(done))
        with self.assertRaises(ValueError):
            langpacks.add("sw", {"no_such_list": ["x"]})
        langpacks.remove("sw")
        after = (scrub.scrub(secret), bool(now.PROMISE.search(promise)), bool(now.DONE.search(done)), bool(now.ASKS.search(ask)), bool(events.INTRO.search(intro)), scrub.scrub(account))
        self.assertEqual(after, before)                                                         # and taken out again, it is gone everywhere
        self.assertTrue(now.PROMISE.search("i'll send it") and now.PROMISE.search("kal bhej dunga"))
        self.assertEqual(scrub.scrub("password simbamkuu ndiyo"), "password simbamkuu ndiyo")

    def test_an_answer_that_says_it_is_unsure_is_heard_in_each_language(self):
        from ctx import agent
        for line in ("couldn't find it in your archive", "no lo encontré en tus chats", "nahi mila yaar", "nggak ketemu di arsip", "não achei nas conversas",
                     "nichts gefunden dazu", "rien trouvé là-dessus", "mitsukaranai desu"):
            self.assertTrue(agent._unsure(line), line)
        self.assertFalse(agent._unsure("the kettle fund closes on friday"))

    def test_a_pack_edited_in_place_is_picked_up_when_told(self):
        langpacks.PACKS["en"]["done"].append("all wrapped up")
        try:
            self.assertFalse(now.DONE.search("all wrapped up"))
            langpacks.changed()
            self.assertTrue(now.DONE.search("all wrapped up"))
        finally:
            langpacks.PACKS["en"]["done"].remove("all wrapped up")
            langpacks.changed()


if __name__ == "__main__":
    unittest.main()
