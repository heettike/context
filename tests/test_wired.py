"""Things that must be reachable, not only written: the commands, the app's lists, one count of what is unread, the
telegram sign-in as a stream, the look-only walk of the export pages, media rows through the collector. All made up."""
import asyncio, io, json, os, subprocess, sys, threading, time, unittest
from tests import files as _f
from unittest import mock
from tests import fixture
from ctx import answer, catchup, collect, driver, media, profile, request, serve, telegram_login, understand

fixture.write() if not os.path.exists(os.path.join(fixture.HOME, "messages.jsonl")) else None


# the three places `media --status` reaches past the home folder it is given, turned off in the child: spotlight's index
# covers the whole disk (the real home included), the swift helper is built and asked about speech (which can raise a
# macos prompt), and `defaults` reads this account's own preferences. every program the child starts is written down.
QUIET = """import atexit, json
started = []
sys.addaudithook(lambda ev, a: started.append(str(a[1])[:200]) if ev == "subprocess.Popen" else None)
from ctx import media
media.screenshots, media.helper, media.system_locale = (lambda: set()), (lambda: ""), (lambda: "en-US")
atexit.register(lambda: sys.stderr.write("\\nstarted: " + json.dumps(started) + "\\n"))
import runpy
runpy.run_module("ctx", run_name="__main__", alter_sys=True)
"""


class Commands(unittest.TestCase):
    def ctx(self, *args):
        """The engine as a person runs it, in a process of its own, with a home folder made for this call: nothing of this
        mac's own is read, no macos prompt can be raised, and no program is started."""
        import shutil, tempfile
        from ctx import guard
        home = tempfile.mkdtemp(prefix="ctx-wired-home-")
        self.addCleanup(shutil.rmtree, home, True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        env.update(CTX_HOME=fixture.HOME, HOME=home, CTX_BROWSER_DATA=os.path.join(home, "Library", "Application Support"))
        r = subprocess.run(guard.python_code(QUIET) + list(args), capture_output=True, text=True, env=env, cwd=home, timeout=120, stdin=subprocess.DEVNULL)
        started = [l for l in r.stderr.splitlines() if l.startswith("started: ")]
        self.assertEqual(started, ["started: []"], r.stderr[-300:])
        return r

    def test_the_three_commands_answer(self):
        r = self.ctx("driver", "--status")
        self.assertEqual((r.returncode, sorted(json.loads(r.stdout))), (0, ["done", "reminders", "services"]), r.stderr[-300:])
        r = self.ctx("catchup", "--status")
        self.assertEqual(r.returncode, 0, r.stderr[-300:])
        self.assertIn("behind", json.loads(r.stdout))
        r = self.ctx("media", "--status", "--json")
        self.assertEqual(r.returncode, 0, r.stderr[-300:])
        help_ = self.ctx().stdout + self.ctx("help").stdout
        for word in ("driver --status", "catchup --status", "media --status"):
            self.assertIn(word, help_)

    def test_what_the_owner_saved_and_liked_on_linkedin_counts_as_saved(self):
        self.assertEqual((answer.SAVED["linkedin_saved"], answer.SAVED["linkedin_likes"]), (answer.SAVED["x_bookmarks"], answer.SAVED["x_likes"]))


class OneCount(unittest.TestCase):
    def test_unread_is_the_same_number_wherever_it_is_asked(self):
        with mock.patch("ctx.wiki.build", lambda **kw: {"estimate": {"pages_to_write": {}, "calls_total": 0}}), mock.patch("ctx.llm.status", lambda: {"plan": ""}):
            est, st, behind = profile.estimate(), understand.status(), catchup.behind()
        self.assertGreater(est["unread"], 0)
        self.assertEqual((behind["conversations"], st["left"]), (est["unread"], est["unread"]))
        self.assertEqual((behind["reading_calls"], st["calls_left_about"]), (est["reading_calls"], est["reading_calls"]))


class Lines:
    def __init__(self):
        self.lines, self.cv = [], threading.Condition()

    def write(self, s):
        with self.cv:
            self.lines += [json.loads(l) for l in s.splitlines() if l.strip()]
            self.cv.notify_all()

    def flush(self):
        pass

    def wait(self, test, timeout=30):
        end = time.monotonic() + timeout
        with self.cv:
            while True:
                hit = [l for l in self.lines if test(l)]
                if hit:
                    return hit[0]
                if not self.cv.wait(max(0.01, end - time.monotonic())) and time.monotonic() > end:
                    raise AssertionError("no such line: %s" % self.lines[-5:])


class FakeTelegram:
    """What telethon's client does during a QR sign-in, played back: `scan_at` is the code on which the phone scans."""
    class Password(Exception):
        pass

    def __init__(self, scan_at=2, signed_in=False, password=False):
        self.scan_at, self.signed_in, self.password, self.n, self.closed = scan_at, signed_in, password, 0, False

    async def connect(self):
        pass

    async def disconnect(self):
        self.closed = True

    async def is_user_authorized(self):
        return self.signed_in

    async def get_me(self):
        return {"id": 1} if self.signed_in else None

    async def qr_login(self):
        tg = self

        class QR:
            @property
            def url(q):
                return "tg://login?token=made-up-%d" % tg.n

            async def wait(q, secs):
                tg.n += 1
                if tg.password and tg.n >= tg.scan_at:
                    raise FakeTelegram.Password()
                if tg.scan_at and tg.n >= tg.scan_at:
                    tg.signed_in = True
                    return
                raise asyncio.TimeoutError()

            async def recreate(q):
                pass
        return QR()


class Served(unittest.TestCase):
    def setUp(self):
        self.out = Lines()
        self.srv = serve.Server(self.out)
        self.addCleanup(lambda: self.srv.pool.shutdown(wait=True))
        for p in (driver.STATE, request.STATE):
            was = _f.read(p, "rb") if os.path.exists(p) else None
            self.addCleanup(lambda p=p, was=was: (_f.write(was, p, "wb") if was is not None else os.path.exists(p) and os.remove(p)))
            if os.path.exists(p):
                os.remove(p)

    def ask(self, **req):
        self.srv.handle(json.dumps(req))
        return self.out.wait(lambda e: e.get("id") == req["id"] and ("result" in e or "error" in e))

    def test_exports_an_arrived_one_shows_no_row_and_a_declined_one_is_denied_and_can_be_started_again(self):
        with mock.patch.object(request, "_arrived", lambda sid, since: __import__("datetime").datetime.now(__import__("datetime").timezone.utc) if sid == "google" else None), \
                mock.patch.object(request, "browser", lambda ask=False: {"name": "", "scripting": False}):
            request._save("notion", "declined")
            request._save("x", "needs_you", "x is asking for your password in the tab")
            rows = {r["id"]: r for r in self.ask(id=1, cmd="exports")["result"]["rows"]}
            self.assertEqual((rows["google"]["state"], rows["google"]["show"]), ("in", False))
            self.assertEqual((rows["notion"]["state"], rows["notion"]["show"], rows["notion"]["restart"]), ("denied", True, True))
            self.assertEqual((rows["x"]["state"], rows["x"]["show"], rows["x"]["restart"]), ("waiting on you", True, False))
            self.assertIn("password", rows["x"]["detail"])
            self.assertEqual((rows["linkedin"]["state"], rows["linkedin"]["show"]), ("idle", False))
            again = {r["id"]: r for r in self.ask(id=2, cmd="exports-restart", service="notion")["result"]["rows"]}
            self.assertEqual((again["notion"]["state"], request.service("notion")["state"]), ("asked", "idle"))      # no longer declined: the driver asks on its next tick
            self.assertIn("error", self.ask(id=3, cmd="exports-restart", service="nope")["result"])
            every = {r["id"]: r for r in self.ask(id=4, cmd="exports-every", service="x", every="weekly")["result"]["rows"]}
            self.assertEqual(every["x"]["every"], "weekly")
            self.assertIn("error", self.ask(id=5, cmd="exports-every", service="x", every="hourly")["result"])

    def test_the_catch_up_status_is_served(self):
        with mock.patch.object(catchup, "behind", lambda: {"conversations": 3, "reading_calls": 6, "wiki_pages": 2, "wiki_calls": 9}):
            got = self.ask(id=1, cmd="catchup-status", fresh=True)["result"]
        self.assertEqual((got["behind"]["conversations"], got["nights_to_catch_up"], got["nightly_calls"]), (3, 1, 40))
        os.path.exists(catchup.STATE) and os.remove(catchup.STATE)

    def test_telegram_sign_in_streams_each_code_and_then_says_how_it_went(self):
        tg = FakeTelegram(scan_at=3)
        real = telegram_login.login
        with mock.patch.object(telegram_login, "login", lambda emit, stop=None: real(emit, stop, client=(tg, FakeTelegram.Password), each=0)):
            got = self.ask(id="t", cmd="telegram-login")
        codes = [l for l in self.out.lines if l.get("id") == "t" and l.get("event") == "qr"]
        self.assertEqual(([c["n"] for c in codes], codes[0]["of"], got["result"]["state"], tg.closed), ([1, 2, 3], 8, "ok", True))
        self.assertTrue(all(c["qr"].startswith("tg://login?token=") for c in codes))


class TelegramLogin(unittest.TestCase):
    def run_it(self, tg, **kw):
        seen = []
        return telegram_login.login(seen.append, client=(tg, FakeTelegram.Password), each=0, **kw), seen

    def test_already_in_never_scanned_a_password_and_a_stop(self):
        got, seen = self.run_it(FakeTelegram(signed_in=True))
        self.assertEqual((got["state"], seen), ("ok", []))
        got, seen = self.run_it(FakeTelegram(scan_at=0), tries=3)
        self.assertEqual((got["state"], len(seen)), ("needs_you", 3))
        self.assertIn("link desktop device", got["detail"])
        got, seen = self.run_it(FakeTelegram(scan_at=2, password=True))
        self.assertEqual(got["state"], "needs_you")
        self.assertIn("open terminal on the sign-in card", got["detail"])              # the password is never asked for over the pipe
        self.assertNotIn("python3", got["detail"])                                      # nor is a command the installed app has no line for
        stop = threading.Event()
        stop.set()
        got, seen = self.run_it(FakeTelegram(scan_at=5), stop=stop)
        self.assertEqual((got["state"], seen), ("cannot", []))

    def test_without_keys_or_the_package_it_says_what_to_do(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_API_ID": "", "TELEGRAM_API_HASH": ""}):
            got = telegram_login.login(lambda e: None)
        self.assertEqual(got["state"], "cannot")
        self.assertTrue("TELEGRAM_API_ID" in got["detail"] or "telethon" in got["detail"])


class FakeTab:
    """A made-up export page: what its text says, which controls it shows, and whether it stands behind a wall."""
    opened, scripts = [], []

    def __init__(self, page):
        self.page, self.closed, self.fronted = page, False, False

    def js(self, body):
        FakeTab.scripts.append(body)
        if body == request.WALL:
            return self.page.get("wall", "")
        return any(k in body for k in self.page.get("shows", ()))

    def check(self):
        if self.page.get("wall"):
            raise request.Needs(self.page["wall"])

    def said(self, rx):
        return bool(self.page.get("pending"))

    def wait(self, body, secs=20, why="x"):
        self.check()
        if self.js(body):
            return True
        raise request.Fail(why)

    def front(self):
        self.fronted = True

    def close(self):
        self.closed = True


class DryRun(unittest.TestCase):
    def setUp(self):
        for p in (driver.STATE, request.STATE):
            was = _f.read(p, "rb") if os.path.exists(p) else None
            self.addCleanup(lambda p=p, was=was: (_f.write(was, p, "wb") if was is not None else os.path.exists(p) and os.remove(p)))
            if os.path.exists(p):
                os.remove(p)
        FakeTab.scripts, self.tabs = [], []
        self.pages = {"x.com": {"wall": "password"},
                      "takeout.google.com": {"shows": ("Create new request",), "pending": True},
                      "linkedin.com": {"shows": ("Select archive you want to download", "Request archive")},
                      "instagram.com": {"wall": "login"},
                      "chatgpt.com": {"shows": ()}}

    def open_tab(self, url):
        t = FakeTab(next((v for k, v in self.pages.items() if k in url), {"shows": ()}))
        self.tabs.append(t)
        return t

    def test_it_looks_as_far_as_the_button_presses_nothing_and_changes_nothing(self):
        request._save("notion", "declined")
        before = _f.read(request.STATE)
        got = {r["id"]: r for r in driver.dry(open_tab=self.open_tab)}
        self.assertEqual({k: v["reached"] for k, v in got.items()},
                         {"x": "password", "google": "an export already pending", "linkedin": "the request button", "instagram": "sign-in", "chatgpt": "not found", "notion": "declined"})
        self.assertIn("x asks for your password", got["x"]["detail"])
        self.assertEqual(len(self.tabs), 5)                                            # the declined one was not opened
        self.assertTrue(all(t.closed and not t.fronted for t in self.tabs))            # every tab closed, none brought forward
        self.assertFalse([s for s in FakeTab.scripts if any(p in s.replace(" ", "") for p in driver.PRESSES)])
        self.assertEqual(_f.read(request.STATE), before)                           # no state was written
        self.assertFalse(os.path.exists(driver.STATE))
        self.assertEqual([r["id"] for r in driver.dry("linkedin", open_tab=self.open_tab)], ["linkedin"])

    def test_a_tab_that_can_only_be_read_refuses_every_way_of_pressing(self):
        look = driver._Look(FakeTab({"shows": ("Request archive",)}))
        for body in ("return hit(document,'Request archive','button')", "press(o[0]);return 1", "b.click();return 1", "return radio(top(),'JSON')", "i.value = 'x'", "f.submit()"):
            with self.assertRaises(PermissionError):
                look.js(body)
            with self.assertRaises(PermissionError):
                look.wait(body)
        with self.assertRaises(PermissionError):
            look.go("https://made.up/elsewhere")
        self.assertTrue(look.js("return !!find(document,'Request archive','button')"))
        for sid, body in driver.LOOK.items():                                          # what the real pages are asked is itself read-only
            self.assertFalse([p for p in driver.PRESSES if p in body.replace(" ", "")], sid)
        self.assertEqual(set(driver.LOOK), {s["id"] for s in request.SERVICES})

    def test_the_real_request_flows_do_press_which_is_why_the_dry_run_never_calls_them(self):
        tab = FakeTab({"shows": ("Request archive",)})
        with self.assertRaises(PermissionError):
            request.BY_ID["x"]["run"](driver._Look(tab))

    def test_with_no_browser_to_drive_it_says_so_and_opens_nothing(self):
        with mock.patch.object(request, "browser", lambda ask=False: {"name": "", "scripting": False, "how_to_enable": "install a browser"}):
            got = driver.dry()
        self.assertEqual({r["reached"] for r in got}, {"no browser"})


class MediaRows(unittest.TestCase):
    """What the media reader saved (media/done.jsonl) reaches the archive through the collector, and only one thing
    writes that file at a time."""

    def test_rows_already_read_are_collected_while_another_read_is_running(self):
        import tempfile, shutil
        d = tempfile.mkdtemp(prefix="ctx-media-")
        self.addCleanup(shutil.rmtree, d, True)
        done = os.path.join(d, "done.jsonl")
        row = lambda i, kind: {"k": "k%d" % i, "p": "/made/up/%d" % i, "kind": kind, "at": 1, "row": {"id": "MI%d" % i, "src": "media_" + kind, "ts": "2026-03-0%dT10:00:00Z" % i, "title": "t", "text": "made-up words %d" % i}}
        with open(done, "w") as f:
            f.write("".join(json.dumps(r) + "\n" for r in (row(1, "image"), row(2, "image"), row(3, "audio"), {"k": "k4", "p": "/made/up/4", "kind": "image", "why": "no text"})) + '{"k": "half-writ')
        before = _f.read(done, "rb")
        held = collect.take_lock("media_scan")                                         # the first pass, running in the owner's terminal
        self.addCleanup(collect.drop_lock, held)
        with mock.patch.object(media, "DONE", done), mock.patch.object(media, "DIR", d), mock.patch.object(media, "STARTED", os.path.join(d, "started")), \
                mock.patch.object(media, "read_one", side_effect=AssertionError("must not read a file while another read holds the lock")):
            open(media.STARTED, "w").close()
            media._memo[0], media._memo[1], media._turn[0] = time.monotonic(), [{"path": "/made/up/9", "kind": "image", "size": 1, "mtime": 1, "ts": time.time(), "place": "x", "what": "x"}], 0.0
            out = io.StringIO()
            n = media.images(None, out)
            self.assertEqual((n, [json.loads(l)["id"] for l in out.getvalue().split("\n") if l]), (2, ["MI1", "MI2"]))
            self.assertEqual(media.audio(None, io.StringIO()), 1)
        self.assertEqual(_f.read(done, "rb"), before)                              # the collector wrote nothing to it
        for name in ("media_images", "media_audio", "media_files", "media_video"):
            self.assertEqual(collect.BY_NAME[name][0], collect.D)


class SmallThings(unittest.TestCase):
    """Found by reading the code against its own help: each a small promise the engine now keeps."""

    def setUp(self):
        for p in (driver.STATE, request.STATE):
            was = _f.read(p, "rb") if os.path.exists(p) else None
            self.addCleanup(lambda p=p, was=was: (_f.write(was, p, "wb") if was is not None else os.path.exists(p) and os.remove(p)))
            if os.path.exists(p):
                os.remove(p)

    def test_one_clock_for_exports_the_plan_shows_the_drivers(self):
        from ctx import schedule
        with mock.patch.object(request, "_arrived", lambda sid, since: None), mock.patch.object(request, "browser", lambda ask=False: {"name": "", "scripting": False}):
            request._save("google", "requested", "", "2026-01-01T00:00:00+00:00")
            request._save("linkedin", "requested", "", "2026-01-01T00:00:00+00:00")
            w = schedule.plan(now=1767225600 + 8 * 86400)["weekly"]            # eight days after both were asked for
            self.assertEqual((w["google"]["every"], w["google"]["due"], w["linkedin"]["every"]), ("monthly", False, "monthly"))      # the driver's cadence, not "weekly"
            self.assertEqual(w["google"]["next_in"], 22 * 86400)
            driver.every("google", "weekly")
            w = schedule.plan(now=1767225600 + 8 * 86400)["weekly"]
            self.assertEqual((w["google"]["every"], w["google"]["due"], w["google"]["next_in"]), ("weekly", True, 0))
            driver.every("google", "off")
            w = schedule.plan(now=1767225600 + 80 * 86400)["weekly"]
            self.assertEqual((w["google"]["every"], w["google"]["due"], w["google"]["next_in"]), ("off", False, None))
            rows = {r["id"]: r for r in driver.rows(now=1767225600 + 8 * 86400)}
            self.assertEqual(rows["google"]["every"], "off")                       # the same word the app's exports list shows

    def test_reading_and_asking_are_two_abilities_of_the_browser(self):
        from ctx import bridge
        with mock.patch.object(bridge, "connected", lambda: True):
            only_extension = request.ways({"scripting": False, "how_to_enable": "switch page scripting on"})
        self.assertEqual(only_extension, {"can_read": True, "reads_through": "extension", "can_request": False, "request_needs": "switch page scripting on"})
        with mock.patch.object(bridge, "connected", lambda: False):
            self.assertEqual(request.ways({"scripting": True, "how_to_enable": ""}), {"can_read": True, "reads_through": "page scripting", "can_request": True, "request_needs": ""})
            self.assertEqual(request.ways({"scripting": False, "how_to_enable": "x"})["can_read"], False)
            with mock.patch.object(request, "pick", lambda: None):
                b = request.browser()
        self.assertEqual((b["name"], b["can_read"], b["can_request"]), ("", False, False))
        self.assertIn("install", b["request_needs"])

    def test_a_rule_that_forgets_is_not_saved_on_yes_alone_and_says_so(self):
        from ctx import rules
        proposal = {"rule": {"kind": "forget", "target": {}}, "says": "forget every message with the old landlord", "ask": "", "affects": {"rows": 42, "threads": 1}, "destructive": True}
        saved = []
        out = io.StringIO()
        with mock.patch.object(rules, "propose", lambda s: dict(proposal)), mock.patch.object(rules, "save", lambda r: saved.append(r) or {"id": "r9"}), mock.patch("sys.stdout", out):
            rules.main(["--add", "forget the old landlord", "--yes"])
        got = json.loads(out.getvalue())
        self.assertEqual((saved, got["saved"]), ([], None))
        self.assertIn("nothing was saved", got["not_saved"])
        self.assertIn("42 messages", got["not_saved"])
        self.assertIn("--forget", got["not_saved"])
        out = io.StringIO()
        with mock.patch.object(rules, "propose", lambda s: dict(proposal)), mock.patch.object(rules, "save", lambda r: saved.append(r) or {"id": "r9"}), mock.patch("sys.stdout", out):
            rules.main(["--add", "forget the old landlord", "--yes", "--forget"])
            self.assertEqual((len(saved), json.loads(out.getvalue())["saved"]), (1, {"id": "r9"}))
            out.seek(0), out.truncate()
            rules.main(["--add", "forget the old landlord"])                       # with no --yes it is only shown, as before
        self.assertNotIn("not_saved", json.loads(out.getvalue()))

    def test_every_command_explains_all_of_its_own_flags(self):
        env = dict(os.environ, CTX_HOME=fixture.HOME, PYTHONPATH=fixture.REPO)
        usage = lambda cmd: subprocess.run([sys.executable, "-m", "ctx", cmd, "--help"], capture_output=True, text=True, env=env, cwd=fixture.REPO, timeout=60).stdout
        want = {"rules": ["--on", "--off", "--remove", "--forget"], "voice": ["--check", "--no-model", "--force"], "api": ["--start", "--stop", "--serve"],
                "bridge": ["--deep", "--reload"], "request": ["--check", "--decline", "--reset", "--enable-browser"], "catchup": ["--fresh", "--run"],
                "media": ["--leave-out", "--take-in", "--folder", "--drop-folder", "--set", "--scan", "--estimate"], "wiki": ["--estimate", "--build", "--page", "--search", "--short"],
                "understand": ["--estimate", "--status", "--deep"], "events": ["estimate", "run", "status"], "rawscrub": ["--apply", "--yes"], "namebook": ["--build"],
                "driver": ["--dry", "--every", "--status"], "mcp": ["--install", "--status", "--remove", "--http"]}
        for cmd, flags in want.items():
            text = usage(cmd)
            for f in flags:
                self.assertIn(f, text, cmd)
            self.assertNotIn("python3 -m ctx." + cmd, text, cmd)                   # the form that works from the command list, not the module's dotted name
        self.assertNotIn("model calls and tokens", usage("rawscrub"))              # a command that shares a line on the first screen has its own page
        self.assertNotIn("events estimate", usage("wiki"))
        for mod in ("driver", "catchup", "rawscrub"):
            with open(os.path.join(fixture.REPO, "ctx", mod + ".py")) as f:
                self.assertNotIn("python3 -m ctx." + mod, f.read(), mod)
        with open(os.path.join(fixture.REPO, "ctx", "mcp.py")) as f:
            self.assertNotIn("claude mcp add", f.read())

    def test_an_app_connect_calls_built_in_names_a_source_the_collector_has(self):
        from ctx import connect
        names = {t[0] for t in collect.TABLE}
        self.assertEqual({app: src for app, src in connect.BUILT_IN.items() if src not in names}, {})
        self.assertEqual(connect.BUILT_IN["dia"], "browser_history")             # dia's history is read with every chromium browser's

    def test_telegram_tells_the_owner_where_to_sign_in_not_a_command_the_app_has_not_got(self):
        import ast, inspect
        from ctx import telegram_login
        for mod in (collect, telegram_login):
            tree = ast.parse(inspect.getsource(mod))
            notes = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                     and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}       # docstrings: notes for developers
            said = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and "telegram-login" in n.value and id(n) not in notes]
            self.assertEqual(said, [], mod.__name__)                              # an installed app has no command line to run it in
        self.assertIn("sign-in card", inspect.getsource(collect.telegram_new) + inspect.getsource(collect._telegram_any))

    def test_the_name_book_has_a_command(self):
        env = dict(os.environ, CTX_HOME=fixture.HOME, PYTHONPATH=fixture.REPO)
        r = subprocess.run([sys.executable, "-m", "ctx", "namebook"], capture_output=True, text=True, env=env, cwd=fixture.REPO, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-300:])
        self.assertEqual(sorted(json.loads(r.stdout)), ["addresses", "file", "numbers", "self-given names", "sources", "whatsapp ids"])


if __name__ == "__main__":
    unittest.main()
