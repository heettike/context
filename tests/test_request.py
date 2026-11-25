"""Which browser is driven, and how page scripting is switched on in it: every chromium browser by the same rules.
No browser is started and no AppleScript is sent; every call that would is replaced."""
import inspect, re, unittest
from unittest import mock
from tests import fixture
from ctx import request


class Browsers(unittest.TestCase):
    def patched(self, installed, running=(), default="", scripting=False):
        return [mock.patch.object(request, "_installed", lambda bundle: bundle in installed), mock.patch.object(request, "_running", lambda name: name in running),
                mock.patch.object(request, "_default_bundle", lambda: default), mock.patch.object(request, "_scripting", lambda *a, **k: scripting)]

    def within(self, patches):
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_the_table_is_in_the_order_of_the_alphabet(self):
        names = [b[0] for b in request.BROWSERS]
        self.assertEqual(names, sorted(names))
        self.assertGreaterEqual(len(names), 5)
        self.assertEqual(request.HOST_SOURCES, sorted(request.HOST_SOURCES))

    def test_the_default_then_a_running_one_then_the_first_installed(self):
        every = {b[1] for b in request.BROWSERS}
        for b in request.BROWSERS:                                       # whichever is the default is the one picked
            with mock.patch.object(request, "_installed", lambda bundle: bundle in every), mock.patch.object(request, "_running", lambda name: False), \
                    mock.patch.object(request, "_default_bundle", lambda b=b: b[1]):
                self.assertEqual(request.pick(), b)
        for b in request.BROWSERS:                                       # with no default among them, whichever is running
            with mock.patch.object(request, "_installed", lambda bundle: bundle in every), mock.patch.object(request, "_running", lambda name, b=b: name == b[0]), \
                    mock.patch.object(request, "_default_bundle", lambda: "com.made-up.browser"):
                self.assertEqual(request.pick(), b)
        self.within(self.patched(every, default="com.made-up.browser"))
        self.assertEqual(request.pick(), request.BROWSERS[0])            # else the first by name
        self.assertEqual(request.pick()[0], min(b[0] for b in request.BROWSERS))

    def test_no_function_names_a_browser(self):
        """What differs between browsers is in the tables at the top; below them the code asks the tables."""
        src = inspect.getsource(request)
        body = src[src.index("def osa("):]
        for name, bundle, _ in request.BROWSERS:
            self.assertIsNone(re.search(r"[\"']%s[\"']" % re.escape(name), body), name)
            self.assertNotIn(bundle, body)

    def test_switching_scripting_on_is_one_path_for_every_browser(self):
        ran, said = [], []
        for name, bundle, data in request.BROWSERS:
            launch = request._launch(bundle)
            with mock.patch.object(request, "pick", lambda b=(name, bundle, data): b), mock.patch.object(request, "_running", lambda n: False), \
                    mock.patch.object(request, "_scripting", lambda *a, **k: False), mock.patch.object(request.time, "sleep", lambda s: None), \
                    mock.patch.object(request.subprocess, "run", lambda cmd, **k: ran.append((bundle, cmd))), mock.patch.object(request, "osa", lambda *a, **k: said.append(a)), \
                    mock.patch.object(request, "routes", lambda *a, **k: []):
                got = request.enable_browser()
            self.assertEqual(got["name"], name)
            self.assertFalse(got["scripting"])
            if launch:                                                   # reopened with the option, by its own bundle id
                self.assertEqual(ran[-1][0], bundle)
                self.assertEqual(ran[-1][1][:4], ["open", "-b", bundle, "--args"])
                self.assertIn(request.SCRIPT_FLAG, ran[-1][1])
                self.assertIn("quits %s" % name.lower(), got["how_to_enable"])
            else:                                                        # nothing is started; the owner is told the menu item, by this browser's name
                self.assertNotIn(bundle, [b for b, _ in ran])
                self.assertEqual(got["how_to_enable"], request.MENU.format(name.lower()))
        self.assertEqual(said, [])                                       # none was running: none was told to quit

    def test_a_quirk_added_to_the_table_is_all_it_takes(self):
        name, bundle, data = next(b for b in request.BROWSERS if not request._launch(b[1]))
        with mock.patch.dict(request.QUIRKS, {bundle: {"launch": True, "focus": "focus t"}}):
            self.assertTrue(request._launch(bundle))
            self.assertTrue(request.routes(name, data, False, bundle)[0]["one_click"])
            self.assertIn(name.lower(), request.routes(name, data, False, bundle)[0]["fix"])
        self.assertFalse(request.routes(name, data, False, bundle)[0]["one_click"])

    def test_with_no_browser_every_one_is_named(self):
        self.within(self.patched(set()))
        how = request.browser()["how_to_enable"]
        for name, _, _ in request.BROWSERS:
            self.assertIn(name.lower(), how)


if __name__ == "__main__":
    unittest.main()
