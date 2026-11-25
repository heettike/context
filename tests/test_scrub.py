"""Secrets are removed before a row is written. Every string here is made up."""
import unittest
from ctx.scrub import R, scrub

PHRASE = "abandon ability able about above absent absorb abstract absurd abuse access accident"
WORDS = "cradle orbit puzzle velvet harbor lizard mango noble quartz ribbon sunset tunnel".split()


class Keys(unittest.TestCase):
    def gone(self, secret, text=None):
        out = scrub(text or "here it is: " + secret + " ok")
        self.assertNotIn(secret, out)
        self.assertIn(R, out)

    def test_named_keys(self):
        self.gone("sk-ant-api03-" + "Zq9fK2mVx7Lr4TnB8cWd" * 3)
        self.gone("ghp_" + "a1B2c3D4e5" * 4)
        self.gone("xoxb-1234567890-abcdefghij")
        self.gone("AKIA" + "ABCDEFGHIJKLMNOP")
        self.gone("123456789:" + "AAbbCCddEEffGGhhIIjjKKllMMnnOOppQQr")

    def test_jwt(self):
        self.gone("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")

    def test_private_key_hex_and_pem(self):
        self.gone("0x" + "4c0883a69102937d6231471b5dbb6204fe512961708279f3a1b2c3d4e5f60718")
        self.gone("MIIEvQIBADANBg", "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg\n-----END PRIVATE KEY-----")

    def test_password_in_words_and_in_a_url(self):
        self.gone("hunter2horse", "the wifi password is hunter2horse")
        self.gone("hunter2horse", "https://sam:hunter2horse@files.example.net/x")
        self.gone("s3cretValue99", "DB_PASSWORD=s3cretValue99")

    def test_card_number(self):
        self.gone("4242 4242 4242 4242")

    def test_public_things_stay(self):
        for keep in ("0x52908400098527886E0F7030069857D2E4169EE7", "docs.example.com/setup/guide", "call me at 9 tomorrow", "1234567890"):
            self.assertEqual(scrub(keep), keep)


class SeedPhrase(unittest.TestCase):
    def test_alone(self):
        self.assertEqual(scrub(PHRASE), R)

    def test_inside_a_sentence(self):
        # the words before and after it are ordinary; the phrase must still go
        out = scrub("here is the staging key and the words " + PHRASE)
        self.assertNotIn("abandon ability", out)
        self.assertTrue(out.startswith("here is the staging key and the"))
        out = scrub(PHRASE + " is the phrase and you should keep it")
        self.assertNotIn("absurd abuse", out)
        self.assertIn("is the phrase", out)

    def test_numbered_capitalised_and_one_per_line(self):
        for text in (" ".join("%d. %s" % (i + 1, w) for i, w in enumerate(WORDS)),
                     " ".join(w.capitalize() for w in WORDS),
                     " ".join(w.upper() for w in WORDS),
                     "\n".join(WORDS),
                     "\n".join("%d) %s" % (i + 1, w) for i, w in enumerate(WORDS))):
            out = scrub("my words:\n" + text)
            for w in WORDS[1:-1]:
                self.assertNotIn(w, out.lower(), text)

    def test_twenty_four_words(self):
        self.assertNotIn("puzzle", scrub(" ".join(WORDS + WORDS[::-1][:6] + "fabric zebra window ticket rubber pencil".split())))

    def test_ordinary_writing_stays(self):
        for keep in ("can you send the lease by friday? i will look at the invoice tonight and call you when it lands",
                     "ship the thing on friday. call the landlord about the lease renewal before the first of the month",
                     "The Quick Brown Fox Jumps Over The Lazy Dog And Runs Away From Here Today",
                     "milk\neggs\nbread\nrice",
                     "ha ha ha ha ha ha ha ha ha ha ha ha ha ha"):
            self.assertEqual(scrub(keep), keep)

    def test_known_limit_eleven_words(self):
        # stated in the readme: fewer than twelve words in a row is not treated as a phrase
        self.assertEqual(scrub(" ".join(WORDS[:11])), " ".join(WORDS[:11]))


if __name__ == "__main__":
    unittest.main()
