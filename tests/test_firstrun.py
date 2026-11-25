"""What a stranger meets on a clean mac: commands run in an empty made-up home, and the small rules behind them.

Listings create nothing and send nothing to a browser, estimates on an empty archive say they cannot know, errors
exit non-zero, and what context made is taken away again. Every name here is invented.
"""
import contextlib, io, json, os, shutil, stat, subprocess, sys, tempfile, unittest
from unittest import mock

from tests import fixture
from ctx import api, bridge, mcp, media, request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class EmptyHome(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="ctx-first-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def ctx(self, *args, module="ctx"):
        e = {"HOME": self.home, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8", "CTX_ANY_OS": "1",
             "CTX_CLI_PATH": os.path.join(self.home, "no-cli"), "ANTHROPIC_API_KEY": ""}
        return subprocess.run([sys.executable, "-m", module, *args], cwd=REPO, env=e, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)

    def test_a_listing_makes_no_folder(self):
        for args in (("remove",), ("--help",), ("doctor", "--json"), ("driver", "--status"), ("catchup", "--status"), ("wiki", "--estimate")):
            self.ctx(*args)
            self.assertNotIn(".context", os.listdir(self.home), args)      # (python itself may leave a Library/Caches folder)

    def test_a_write_keeps_its_folder(self):
        self.assertEqual(self.ctx("note", "kiln", "--append", "the kiln is booked for friday").returncode, 0)
        self.assertTrue(os.path.isdir(os.path.join(self.home, ".context", "v2")))

    def test_the_wiki_estimate_says_it_cannot_know_yet(self):
        got = json.loads(self.ctx("wiki", "--estimate").stdout)["estimate"]
        self.assertEqual(got["calls_total"], 0)
        self.assertIs(got["cannot_know_yet"], True)
        self.assertTrue(got["why"])

    def test_catchup_is_off_with_nothing_to_read_and_no_model(self):
        got = json.loads(self.ctx("catchup", "--status").stdout)
        self.assertIs(got["may_run_now"], False)
        self.assertIs(got["on"], False)
        self.assertTrue(got["why_not"])

    def test_doctor_names_the_extension_first_and_no_other_model(self):
        out = self.ctx("doctor").stdout + self.ctx("doctor", "--json").stdout
        self.assertNotIn("brew install", out.lower())
        if "--enable-browser" in out:
            self.assertIn("bridge --install", out)
            self.assertLess(out.index("bridge --install"), out.index("--enable-browser"))

    def test_the_name_book_runs_as_a_module(self):
        r = self.ctx(module="ctx.namebook")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.strip())
        self.assertEqual(self.ctx("--build", module="ctx.namebook").returncode, 0)

    def test_an_unknown_name_is_an_error(self):
        for args in (("made", "--get", "nosuch"), ("rules", "--off", "nosuch")):
            r = self.ctx(*args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertTrue((r.stdout + r.stderr).strip(), args)

    def test_cost_help_is_about_cost(self):
        out = self.ctx("cost", "--help").stdout
        self.assertIn("cost", out)
        self.assertNotIn("rawscrub", out)

    def test_nothing_printed_assumes_who_the_owner_is(self):
        import re
        for args in (("--help",), ("doctor",), ("voice", "--status"), ("understand", "--help"), ("collect", "--help"), ("media", "--help")):
            r = self.ctx(*args)
            self.assertIsNone(re.search(r"\b(he|his|him|himself)\b", r.stdout + r.stderr, re.I), args)


class Rules(unittest.TestCase):
    def test_a_listing_never_asks_a_running_browser(self):
        asked = []
        with mock.patch.object(request, "_running", lambda name: True), mock.patch.object(request, "osa", lambda *a, **k: asked.append(a) or "1"), \
                mock.patch.object(request, "APPDATA", os.path.join(fixture.HOME, "no-such-appdata")):
            request._scripting("Chrome", "com.google.Chrome", "Google/Chrome")
            self.assertEqual(asked, [])
            self.assertIs(request._scripting("Chrome", "com.google.Chrome", "Google/Chrome", ask=True), True)
            self.assertEqual(len(asked), 1)

    def test_the_extension_folder_must_be_the_owners_alone(self):
        d = tempfile.mkdtemp(prefix="ctx-ext-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        os.chmod(d, 0o755)
        for n in ("readers.js", "manifest.json"):
            with open(os.path.join(d, n), "w") as f:
                f.write("{}")
            os.chmod(os.path.join(d, n), 0o644)
        self.assertEqual(bridge.extension_ok(d), "")
        os.chmod(os.path.join(d, "readers.js"), 0o664)
        self.assertIn("readers.js", bridge.extension_ok(d))
        os.chmod(os.path.join(d, "readers.js"), 0o644)
        os.chmod(d, 0o775)
        self.assertTrue(bridge.extension_ok(d))
        os.chmod(d, 0o755)
        os.remove(os.path.join(d, "manifest.json"))
        os.symlink(os.path.join(d, "readers.js"), os.path.join(d, "manifest.json"))
        self.assertIn("link", bridge.extension_ok(d))

    def test_the_api_stops_when_its_last_key_goes(self):
        left, stopped = [["kiln"]], []
        out = io.StringIO()
        with mock.patch.object(api, "revoke", lambda name: bool(left[0].pop())), mock.patch.object(api, "keys", lambda: list(left[0])), \
                mock.patch.object(api, "_state", lambda: {"port": 1}), mock.patch.object(api, "stop", lambda: stopped.append(1)), contextlib.redirect_stdout(out):
            api.main(["--revoke", "kiln"])
        self.assertEqual(stopped, [1])
        self.assertIn("stopped", json.loads(out.getvalue()))

    def test_a_codex_config_that_held_only_our_entry_is_removed(self):
        home = tempfile.mkdtemp(prefix="ctx-codex-")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        path = os.path.join(home, ".codex", "config.toml")
        os.makedirs(os.path.dirname(path))
        run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", "")
        self.assertEqual(mcp.install(home=home, claude=None, run=run, say=lambda s: None, only="codex")["codex"], "registered")
        self.assertEqual(mcp.remove("codex", home=home, claude=None, run=run, say=lambda s: None), {"codex": "removed"})
        self.assertFalse(os.path.exists(path))
        with open(path, "w") as f:
            f.write('model = "made-up"\n')
        mcp.install(home=home, claude=None, run=run, say=lambda s: None, only="codex")
        mcp.remove("codex", home=home, claude=None, run=run, say=lambda s: None)
        with open(path) as f:
            self.assertEqual(f.read(), 'model = "made-up"\n')

    def test_speech_follows_the_mac_until_a_voice_note_has_been_read(self):
        say = lambda text: (lambda *a, **k: subprocess.CompletedProcess(a, 0, text, ""))
        with mock.patch.object(media.subprocess, "run", say("fr_FR\n")):
            self.assertEqual(media.system_locale(), "fr-FR")
        with mock.patch.object(media.subprocess, "run", say("")), mock.patch.dict(os.environ, {"LANG": "de_DE.UTF-8"}):
            self.assertEqual(media.system_locale(), "de-DE")
        with mock.patch.object(media.subprocess, "run", say("")), mock.patch.dict(os.environ, {"LANG": "C"}):
            self.assertEqual(media.system_locale(), "en-US")
        d = tempfile.mkdtemp(prefix="ctx-loc-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        used = os.path.join(d, "media", "speech_locale")
        with mock.patch.object(media, "system_locale", lambda: "fr-FR"), mock.patch.object(media, "USED", used), mock.patch.object(media, "CONFIG", os.path.join(d, "media.json")):
            self.assertEqual(media.config()["speech_locale"], "fr-FR")
            media._keep_locale("pt-PT")                 # the first voice note was read in this language
            media._keep_locale("de-DE")                 # a later one does not change it
            with mock.patch.object(media, "system_locale", lambda: "ja-JP"):        # nor does the mac changing its own
                self.assertEqual(media.config()["speech_locale"], "pt-PT")
            with open(os.path.join(d, "media.json"), "w") as f:
                json.dump({"speech_locale": "en-GB"}, f)
            self.assertEqual(media.config()["speech_locale"], "en-GB")


if __name__ == "__main__":
    unittest.main()
