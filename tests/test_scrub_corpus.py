"""The scrubber measured on made-up text: how much of each kind of secret it catches, and how much ordinary chat it changes.

tests/scrub_corpus.py builds both sets from a fixed seed, so the numbers are the same on every run. The floors below sit
just under what ctx/scrub.py reaches today: a change that loses secrets, starts changing plain chat or makes a pattern
crawl fails here. Nothing is real: every key, card, phrase and number is generated.
"""
import time, unittest
from tests import scrub_corpus as corpus
from ctx import scrub as S
from ctx.scrub import R, scrub

# least share of each class that must be caught. reached today: provider keys 207/207, pem 20/20, jwt 8/8, seed phrases 54/57,
# private keys 50/50, cards 44/44, passwords 62/68, one-time codes and 2fa 78/81, bank and identity 75/78, session 69/69.
FLOOR = {"provider_key": 0.99, "pem": 0.95, "jwt": 1.0, "seed_phrase": 0.93, "private_key": 0.98, "card": 0.97,
         "password": 0.90, "otp_2fa": 0.95, "bank_identity": 0.95, "session": 0.98}
# what is still missed, on purpose: nothing in the text says these are secrets, and a rule that took them would take chat too
KNOWN_MISSES = {
    ("seed_phrase", "first_six_then_note_then_six"),     # the phrase is cut in two by other words: neither half is 12 long
    ("password", "wifi_password_no_sep/short_lower"),    # "wifi password tigers": reads the same as "wifi password problem"
    ("password", "pass_dash/short_lower"),               # "pass - tigers": reads the same as "pass - through"
    ("password", "bare_no_cue"),                         # a short lower-case word with nothing that names it
    ("otp_2fa", "bare_six_digits_no_cue"),               # six digits alone
    ("bank_identity", "aadhaar_plain_no_cue"),           # twelve digits alone: one phone number in ten has the same check digit
}
# ordinary lines that are still changed, on purpose or because no rule can tell them from a secret
KNOWN_CHANGED = {
    "tx_hash_redacted_on_purpose",                       # 64 hex is a private key as often as a hash
    "google_docs_link", "uuid_bare", "image_name",       # long opaque ids: kept in a row's url field by the callers, redacted in text
    "comma_list_12plus_words", "telegraphic_12plus_no_joining_words", "prose_long_12plus_words",   # twelve plain words in a row
}
CEILING = 0.06      # share of ordinary lines changed, tx hashes aside


class Corpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items, cls.lines = corpus.secrets(), corpus.benign()
        cls.caught = corpus.catch_table(scrub, cls.items)
        cls.changed = corpus.fp_table(scrub, cls.lines)

    def test_the_corpus_is_big_enough_to_mean_something(self):
        self.assertGreaterEqual(len(self.items), 650)
        self.assertGreaterEqual(len(self.lines), 1500)
        self.assertEqual(set(self.caught), set(FLOOR))
        self.assertEqual([i["text"] for i in corpus.secrets()], [i["text"] for i in self.items])      # the same on every run

    def test_catch_rate_by_class(self):
        for cls, (got, total) in sorted(corpus.rates(self.caught).items()):
            self.assertGreaterEqual(got / total, FLOOR[cls], "%s: caught %d of %d" % (cls, got, total))

    def test_only_the_known_shapes_are_missed(self):
        missed = set((c, v) for c, vs in self.caught.items() for v, (got, total) in vs.items() if got < total)
        self.assertEqual(missed - KNOWN_MISSES, set())

    def test_a_caught_secret_leaves_a_marker(self):
        for it in self.items:
            out = scrub(it["text"])
            if not corpus.leaks(it, out):
                self.assertIn(R, out, it["variant"])

    def test_plain_chat_is_not_changed(self):
        for kind in corpus.MUST_SURVIVE:
            bad, total = self.changed[kind]
            self.assertEqual(bad, 0, "%s: %d of %d lines changed" % (kind, bad, total))

    def test_only_the_known_kinds_of_line_are_changed(self):
        self.assertEqual(set(k for k, (bad, _) in self.changed.items() if bad) - KNOWN_CHANGED, set())

    def test_share_of_ordinary_lines_changed(self):
        rest = [v for k, v in self.changed.items() if k != "tx_hash_redacted_on_purpose"]
        bad, total = sum(v[0] for v in rest), sum(v[1] for v in rest)
        self.assertLessEqual(bad / total, CEILING, "%d of %d ordinary lines changed" % (bad, total))

    def test_scrubbing_twice_changes_nothing_more(self):
        # the archive holds scrubbed text and is scrubbed again when it is read into a wiki page or a report
        for text in [i["text"] for i in self.items] + [b["text"] for b in self.lines]:
            once = scrub(text)
            self.assertEqual(scrub(once), once)

    def test_why_names_the_pass_and_matches_scrub(self):
        names = set(p[0] for p in S.PASSES)
        for it in self.items[::7]:
            fired = S.why(it["text"])
            self.assertTrue(set(fired) <= names)
            self.assertEqual(bool(fired), scrub(it["text"]) != it["text"])
        self.assertEqual(S.why("see you at 9 tomorrow"), [])
        self.assertEqual(S.why(""), [])

    def test_no_input_makes_a_pattern_crawl(self):
        # the old password rule took 48 seconds on "password" written 12,500 times with no space. each of these takes
        # a tenth of a second or less on a laptop: five seconds leaves room for a busy machine and still catches a blow-up.
        for name, text in corpus.slow_inputs().items():
            start = time.perf_counter()
            scrub(text)
            self.assertLess(time.perf_counter() - start, 5.0, name)


class Rules(unittest.TestCase):
    """One made-up line per rule, so a failure names the rule."""

    def stays(self, *texts):
        for t in texts:
            self.assertEqual(scrub(t), t)

    def gone(self, secret, text):
        out = scrub(text)
        self.assertNotIn(secret, out, text)
        self.assertIn(R, out)

    def test_cue_inside_another_word_is_no_cue(self):
        self.stays("compass: north123", "author: sam123", "spin: 4821 rpm", "pincode: 000000", "tokenizer: 40 words",
                   "password reset link bhej", "password is wrong", "netflix ka password kya hai", "el password es incorrecta", "password itu salah", "das password ist falsch",
                   "le password est incorrect", "secret santa list")
        self.gone("abc123xyz", "userPassword: 'abc123xyz'")
        self.gone("abcdef123456", "auth token: abcdef123456")          # the value of the first cue is the second cue

    def test_code_is_not_a_password(self):
        self.stays("password_hash = bcrypt.hashpw(password, salt)", "const apiKey = process.env.API_KEY", "token = os.environ['API_TOKEN']")

    def test_public_addresses_stay_after_a_cue(self):
        self.stays("token 0x52908400098527886E0F7030069857D2E4169EE7 is the one",
                   "https://etherscan.io/address/0x52908400098527886E0F7030069857D2E4169EE7",
                   "https://github.com/example/app/commit/" + "0a1b2c3d4e" * 4)
        self.gone("0a1b2c3d4e", "https://api.example.com/hooks/" + "0a1b2c3d4e" * 4)        # 40 hex in a link that is no commit

    def test_links_keep_their_host(self):
        out = scrub("rpc https://mainnet.infura.io/v3/" + "0a1b2c3d" * 4)
        self.assertEqual(out, "rpc https://mainnet.infura.io/v3/" + R)
        out = scrub("https://app.example.com/orders/" + "3f2b8c1e-9a4d-4e6f-8b2a-1c3d5e7f9a0b")
        self.assertNotIn(R, out)

    def test_names_built_from_words_stay(self):
        self.stays("PXL_20260120_515378121.mp4", "~/Downloads/kiln-glaze-shelf-notes_final_v3.pdf", "process.env.NEXT_PUBLIC_SUPABASE_URL")
        self.gone("tiger-mango", "use tiger-mango-sunset-rocket-48217 ok")              # hyphens alone, no link: maybe a passphrase

    def test_one_time_codes(self):
        self.gone("483920", "483920 is your verification code")
        self.gone("483-920", "use code 483-920 to sign in")
        self.gone("483920", "OTP for txn of INR 4,500.00 is 483920. valid for 10 mins")
        self.assertIn("4,500.00", scrub("OTP for txn of INR 4,500.00 is 483920. valid for 10 mins"))
        for said in ("tu codigo es 483920", "kode verifikasi 483920 jangan dibagikan", "votre code de vérification est 483920", "ihr bestätigungscode 483920", "ninshou koudo 483920 desu",
                     "seu código é 483920", "otp hai 483920"):
            self.gone("483920", said)                                    # the word for a code in every pack, read the same way
        self.stays("zip code 123456", "error code 500123", "use code SAVE20", "otp nahi aaya abhi tak", "code review at 4", "codigo postal 280012", "código promocional 123456", "kode pos 123450")
        self.assertIn("123456 shipped", scrub("order 123456 shipped, code 654321"))

    def test_cards_and_numbers_that_only_look_like_one(self):
        self.gone("4242-4242", "card: 4242-4242-4242-4242")
        self.gone("3782 822463", "amex 3782 822463 10005")
        self.assertEqual(scrub("4242 4242 4242 4242 exp 04/27 cvv 123"), R + " exp " + R + " cvv " + R)
        self.stays("exp 04/27", "https://x.com/sam/status/1000000000001234567", "ts 1700000000000", "amazon order 402-1234567-1234566")

    def test_identity_numbers_need_their_check_or_their_name(self):
        self.assertTrue(S._verhoeff("2363") and not S._verhoeff("2364"))
        self.gone("GB82", "iban GB82 WEST 1234 5698 7654 32")
        self.stays("GB83 WEST 1234 5698 7654 32", "call 5550 1234 5678", "HELLO ABCDE1234F", "2026-03-09", "account 2026 looks good")
        self.gone("ABCPE1234F", "pan ABCPE1234F")
        self.gone("123-45-6789", "ssn 123-45-6789")
        self.gone("K1234567", "passport no K1234567")
        # each country's own numbers and payment names, read alike: none of the values is a real one
        for secret, said in (("4821", "upi pin 4821 hai"), ("4821", "m-pesa pin 4821"), ("4821", "gopay pin 4821 ya"), ("4821", "gcash pin is 4821"), ("4821", "opay pin 4821"),
                             ("000.000.000-00", "meu cpf: 000.000.000-00"), ("0000000000000000", "nik saya 0000000000000000"), ("QQ000000C", "my national insurance number is QQ000000C"),
                             ("XEXX000000MXXXXXA0", "mi curp es XEXX000000MXXXXXA0"), ("000000000", "ssn 000000000"), ("0000 0000 0000", "aadhaar 0000 0000 0000")):
            self.gone(secret, said)
        for said in ("account number 000000000012", "mi cuenta es 000000000012", "rekening 000000000012", "konto 000000000012", "compte 000000000012", "conta 000000000012", "khata 000000000012",
                     "kouza 000000000012"):
            self.gone("000000000012", said)
        self.assertEqual(scrub("account number 000000000012 ifsc ABCD0000000"), "account number " + R + " ifsc ABCD0000000")
        self.assertEqual(sorted(S.ID_NUMBERS), ["br", "gb", "id", "in", "mx", "us"])       # by country code, none first by habit
        self.assertGreaterEqual(len(S.PAY_PIN), 5)

    def test_headers_and_commands(self):
        self.assertEqual(scrub("cookie: sid=abc123; theme=dark"), "cookie: sid=" + R + "; theme=" + R)
        self.gone("dXNlcjpwYXNz", "Authorization: Basic dXNlcjpwYXNz")
        self.gone("hunter2", "curl -u admin:hunter2 https://api.example.com/health")
        self.gone("hunter2", "sshpass -p hunter2 ssh root@10.0.0.4")
        self.gone("hunter22", "cache is at redis://:hunter22@10.0.0.9:6379/0")
        self.stays("cookie: chocolate chip", "mysql -u root -p -h host", "login / signup page", "login 10:30 pe karna", "Basic understanding of things")

    def test_seed_phrase_layouts(self):
        w = "cradle orbit puzzle velvet harbor lizard mango noble quantum ribbon sunset tunnel".split()     # all in the bip39 list
        for text in ("\n".join("   ".join(w[i:i + 3]) for i in range(0, 12, 3)), "-".join(w), " ".join(w[:6]) + "\n" + " ".join(w[6:]),
                     "\n".join("- " + x for x in w), " | ".join(w), "\r\n".join(w)):
            out = scrub("words:\n" + text)
            for x in w[1:-1]:
                self.assertNotIn(x, out, text)
        self.stays("https://news.example.com/2026/11/" + "-".join(w) + ".html")          # hyphens in a link join ordinary words


if __name__ == "__main__":
    unittest.main()
