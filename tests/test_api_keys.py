"""Keys for other programs: a key reads nothing until it is opened, it expires, what it reads is counted and held when
unusual, and one never list and the owner's rules sit above every key on every route. Made-up data only."""
import io, json, os, shutil, subprocess, sys, tempfile, threading, time, unittest, urllib.error, urllib.request
from contextlib import redirect_stdout
from unittest import mock
from tests import fixture
from ctx import api, rules

GRACE = ("kettle memo", "kalam", "milte hain", "admiral", "old colleague")      # words only the conversation with grace hopper, and the page line about her, hold


class Base(unittest.TestCase):
    def setUp(self):
        fixture.write()
        self.tmp = tempfile.mkdtemp(prefix="ctx-keys-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for mod, name in ((api, "CONF"), (api, "RUN"), (api, "LOG"), (api, "NEVER"), (rules, "FILE"), (rules, "GONE")):
            p = mock.patch.object(mod, name, os.path.join(self.tmp, name.lower()))
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(api, "start", lambda *a, **k: {"url": "http://127.0.0.1:1/v1"})      # making a key must not start a real server
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.reset)
        self.reset()
        self.srv = api.make_server(0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def reset(self):
        rules._mem.clear()

    def call(self, key, path, method="GET", body=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": "Bearer " + key})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b"{}")

    def leave_out_grace(self):
        with open(rules.FILE, "w") as f:
            json.dump({"rules": [{"id": "r1", "kind": "leave_out", "said": "leave her out", "on": True, "target": {"threads": ["whatsapp:grace hopper"], "people": ["grace hopper"]}}]}, f)
        rules._mem.clear()

    def cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            api.main(list(args))
        return json.loads(out.getvalue())

    def log(self, key, day_offset, rows, status=200, n=1):
        at = time.strftime("%Y-%m-%dT12:00:00+0000", time.localtime(time.time() - day_offset * 86400))
        with open(api.LOG, "a") as f:
            for _ in range(n):
                f.write(json.dumps({"key": key, "method": "GET", "path": "/v1/search", "status": status, "bytes": 100, "rows": rows, "src": ["whatsapp"], "at": at}) + "\n")


ALL_ROUTES = [("GET", "/v1/search?q=kettle;kalam;memo", None), ("GET", "/v1/people/grace", None), ("GET", "/v1/people/grace%20hopper", None), ("GET", "/v1/wiki?q=grace", None),
              ("GET", "/v1/profile/core", None), ("GET", "/v1/profile/people", None), ("GET", "/v1/profile/timeline", None), ("GET", "/v1/briefing", None), ("GET", "/v1/sources", None),
              ("POST", "/v1/tools/search", {"query": "kalam; kettle memo"}), ("POST", "/v1/tools/read_thread", {"thread": "grace hopper"}), ("POST", "/v1/tools/read_thread", {"around": "W2"}),
              ("POST", "/v1/tools/person", {"name": "grace"}), ("POST", "/v1/tools/card", {"thread": "grace hopper"}), ("POST", "/v1/tools/doc", {"id": "W2"}),
              ("POST", "/v1/tools/page", {"name": "people"}), ("POST", "/v1/tools/about_me", {}), ("POST", "/v1/tools/profile", {"section": "people"}),
              ("POST", "/v1/tools/stats", {"what": "people"}), ("POST", "/v1/tools/stats", {"what": "person", "person": "grace hopper"}), ("POST", "/v1/tools/timeline", {}),
              ("POST", "/v1/tools/links", {"query": "kettle"}), ("POST", "/v1/tools/saved", {"query": "kettle"}), ("POST", "/v1/tools/wiki", {"query": "grace"}),
              ("POST", "/v1/tools/facts", {}), ("POST", "/v1/tools/open_loops", {}), ("POST", "/v1/tools/lapsed", {}), ("POST", "/v1/tools/shared", {})]


class DenyByDefault(Base):
    def test_a_new_key_reads_nothing_and_says_how_to_open_it(self):
        made = self.cli("--key", "new-app")
        self.assertEqual(made["reads"], "nothing yet")
        for flag in ("--preset work|writing|people|profile", "--sources", "--people", "--all", "api --set new-app"):
            self.assertIn(flag, made["note"])
        st, out = self.call(made["key"], "/v1")
        self.assertEqual(st, 200)
        self.assertIn("reads nothing yet", out["this_key_reads"])
        self.assertEqual([e["path"] for e in out["endpoints"]], ["/v1", "/v1/openapi.json"])
        st, doc = self.call(made["key"], "/v1/openapi.json")
        self.assertEqual((st, sorted(doc["paths"])), (200, ["/v1", "/v1/openapi.json"]))
        for method, path, body in ALL_ROUTES + [("POST", "/v1/ask", {"question": "who is grace"}), ("GET", "/v1/tools", None)]:
            st, out = self.call(made["key"], path, method, body)
            self.assertEqual(st, 403, path)
            self.assertNotIn("text", out)

    def test_everything_needs_the_word_all_and_gets_a_warning(self):
        made = self.cli("--key", "big", "--all")
        self.assertEqual(made["reads"], "everything in the archive")
        self.assertIn("whole archive", made["warning"])
        self.assertEqual(self.call(made["key"], "/v1/sources")[0], 200)
        with self.assertRaises(SystemExit):
            self.cli("--key", "both", "--all", "--sources", "whatsapp")

    def test_what_each_preset_opens(self):
        self.assertEqual(api.preset("profile"), {"profile": True})
        self.assertEqual(api.preset("people")["sources"], ["imessage", "instagram", "linkedin", "slack", "telegram", "whatsapp", "x_dms"])
        self.assertEqual((api.preset("writing")["mine"], "apple_notes" in api.preset("writing")["sources"], "whatsapp" in api.preset("writing")["sources"]), (True, True, False))
        self.assertEqual(("slack" in api.preset("work")["sources"], "whatsapp" in api.preset("work")["sources"]), (True, False))
        self.assertEqual(api.preset("people", {"people": "Ada Lovelace", "after": "2025"}), dict(api.preset("people"), people=["ada lovelace"], after="2025-01-01"))
        with self.assertRaises(api.Bad):
            api.preset("everything")
        key = self.cli("--key", "chat", "--preset", "people")["key"]
        st, out = self.call(key, "/v1/search?q=kettle")
        self.assertEqual(st, 200)
        self.assertIn("[W1]", out["text"])
        own = self.cli("--key", "own", "--preset", "writing")["key"]                      # only what the owner wrote, in the places they write
        self.assertNotIn("[W", self.call(own, "/v1/search?q=kettle")[1]["text"])
        mine = api.make_key("mine", {"sources": "whatsapp", "mine": True})
        got = self.call(mine, "/v1/search?q=kettle")[1]["text"]
        self.assertIn("[W1]", got)                                                       # W1 is the owner's own line
        self.assertNotIn("[W2]", got)                                                    # W2 is someone else's

    def test_no_key_reads_everything_because_it_is_old(self):
        key = "ctx_" + "k" * 43
        for form in ({}, {"v": 2}):                                                       # the two forms a key file had before this one
            with api._changing():                                                         # under the store's own lock: the server writes its counts back after a call
                if os.path.exists(api.LOG):
                    os.remove(api.LOG)
                with open(api.CONF + ".old", "w") as f:
                    json.dump(dict(form, keys={"old-app": dict({"hash": api._hash(key), "made": 1700000000, "used": 0, "calls": 7}, **({"all": True} if form else {})),
                                               "old-narrow": {"hash": api._hash(key + "2"), "made": 1700000000, "used": 0, "calls": 0, "scope": {"sources": ["whatsapp"]}},
                                               **({"old-none": {"hash": api._hash(key + "3"), "made": 1700000000, "used": 0, "calls": 0}} if form else {})}), f)
                os.replace(api.CONF + ".old", api.CONF)
            self.assertEqual(self.call(key, "/v1/sources")[0], 403, form)                 # before anything was migrated, and after: nothing
            self.assertEqual(self.call(key, "/v1/search?q=kettle")[0], 403, form)
            listed = {k["name"]: k for k in self.cli("--keys")}
            self.assertEqual((listed["old-app"]["kind"], listed["old-app"]["calls"] >= 7), ("none", True), form)
            self.assertIn("api --set old-app --all", listed["old-app"]["narrowed"])
            self.assertEqual((listed["old-narrow"]["kind"], listed["old-narrow"]["reads"], "narrowed" in listed["old-narrow"]), ("rows", "only whatsapp", False))
            if form:                                                                      # under the second form a key with no limits read nothing: nothing was taken from it
                self.assertEqual((listed["old-none"]["kind"], "narrowed" in listed["old-none"]), ("none", False))
            for k in listed.values():
                self.assertAlmostEqual(k["expires"], time.time() + 30 * 86400, delta=120)
            with open(api.CONF) as f:
                saved = json.load(f)
            self.assertEqual((saved["v"], "all" in saved["keys"]["old-app"], saved["narrowed"]), (3, False, ["old-app"]))
            self.assertEqual(self.call(key, "/v1/sources")[0], 403)
            self.assertEqual(self.call(key + "2", "/v1/search?q=kettle")[0], 200)
            self.cli("--set", "old-app", "--all")                                         # only the owner's own word opens it
            self.assertEqual(self.call(key, "/v1/sources")[0], 200)
            self.assertNotIn("narrowed", {k["name"]: k for k in self.cli("--keys")}["old-app"])


class Expiry(Base):
    def test_a_key_lasts_thirty_days_unless_told(self):
        a, b, c = self.cli("--key", "a", "--all"), self.cli("--key", "b", "--all", "--days", "3"), self.cli("--key", "c", "--all", "--never")
        day = lambda n: time.strftime("%Y-%m-%d", time.localtime(time.time() + n * 86400))
        self.assertEqual((a["expires"], b["expires"], c["expires"]), (day(30), day(3), "never"))
        self.assertIn("never expires", c["expires_note"])
        with self.assertRaises(SystemExit):
            self.cli("--key", "d", "--days", "0")

    def test_an_expired_key_is_told_so_and_can_be_renewed(self):
        key = api.make_key("short", all_=True, days=1)
        self.assertEqual(self.call(key, "/v1")[0], 200)
        with mock.patch("time.time", lambda t=time.time: t() + 2 * 86400):
            st, out = self.call(key, "/v1")
            self.assertEqual(st, 401)
            self.assertIn("expired", out["error"])
            self.assertIn("python3 -m ctx api --renew short", out["error"])
            self.assertTrue(next(k for k in api.keys() if k["name"] == "short")["expired"])
            self.cli("--renew", "short", "--days", "10")
            self.assertEqual(self.call(key, "/v1")[0], 200)


class Log(Base):
    def test_the_log_counts_and_never_holds_what_was_asked(self):
        key = api.make_key("reader", all_=True)
        self.call(key, "/v1/search?q=zeppelin")
        self.call(key, "/v1/people/ada")
        self.call(key, "/v1/nothing-here")
        narrow = api.make_key("narrow", {"sources": "whatsapp"})
        self.call(narrow, "/v1/profile/core")                                             # refused: counted as a refusal
        self.call(narrow, "/v1/search?q=kettle")
        with open(api.LOG) as f:
            text = f.read()
        for word in ("zeppelin", "ada", "kettle", "lovelace", "landed"):
            self.assertNotIn(word, text)
        today = api.log_for("reader", 3)[-1]
        self.assertEqual((today["calls"], today["refusals"], today["sources"]), (3, 1, ["whatsapp"]))
        self.assertGreaterEqual(today["rows"], 1)
        self.assertEqual(len(api.log_for("reader", 3)), 3)
        n = api.log_for("narrow", 1)[0]
        self.assertEqual((n["calls"], n["refusals"]), (2, 1))
        self.assertEqual(self.cli("--log", "reader", "--days", "2")["days"][-1]["calls"], 3)
        row = next(k for k in api.command("api-keys", {})["keys"] if k["name"] == "reader")
        self.assertEqual((row["calls_today"], row["rows_today"], row["unusual"], row["held"]), (3, today["rows"], False, False))
        self.assertNotIn("hash", json.dumps(api.command("api-keys", {})))

    def test_a_day_far_past_the_usual_is_held_until_the_owner_clears_it(self):
        key = api.make_key("scraper", all_=True)
        for d in range(1, 8):
            self.log("scraper", d, 100)                                                   # a usual day: 100 messages
        self.log("scraper", 0, 1500)
        self.assertEqual(self.call(key, "/v1/sources")[0], 200)                           # 15 times the usual day, and still under the floor
        self.srv.RequestHandlerClass.gate.rows.clear()
        self.log("scraper", 0, 700)                                                       # past the floor of 2,000 now
        st, out = self.call(key, "/v1/sources")
        self.assertEqual(st, 429)
        for part in ("far more today", "a usual day is 100", "api --clear scraper"):
            self.assertIn(part, out["error"])
        row = next(k for k in api.keys() if k["name"] == "scraper")
        self.assertEqual((row["unusual"], row["held"]), (True, True))
        self.assertEqual(api.command("api-key-set", {"name": "scraper", "clear": True})["held"], False)
        self.assertEqual(self.call(key, "/v1/sources")[0], 200)
        self.assertTrue(next(k for k in api.keys() if k["name"] == "scraper")["unusual"])   # still shown as unusual, no longer held

    def test_the_hold_is_a_setting(self):
        key = api.make_key("scraper", all_=True)
        self.log("scraper", 0, 5000)
        self.assertEqual(self.call(key, "/v1/sources")[0], 429)
        self.assertEqual(api.command("api-never", {"hold_unusual": False})["hold_unusual"], False)
        self.assertEqual(self.call(key, "/v1/sources")[0], 200)
        self.assertEqual(self.cli("--hold", "on"), {"hold_unusual": True})

    def test_a_daily_ceiling_on_messages(self):
        key = api.make_key("capped", {"sources": "whatsapp"})
        api.set_key("capped", rows_per_day=3)
        st, out = self.call(key, "/v1/search?q=pottery&limit=20")
        self.assertEqual(st, 200)                                                         # the call that crosses it is answered
        st, out = self.call(key, "/v1/search?q=pottery")
        self.assertEqual(st, 429)
        self.assertIn("its 3 messages for today", out["error"])
        self.assertEqual(next(k for k in api.keys() if k["name"] == "capped")["rows_per_day"], 3)
        self.assertEqual(api.ROWS_PER_DAY, 20000)


class NeverAndRules(Base):
    def hits(self, obj):
        text = json.dumps(obj, ensure_ascii=False).lower()
        return [w for w in GRACE if w in text]

    def test_the_owners_rules_hold_on_every_route(self):
        key = api.make_key("full", all_=True)
        self.assertTrue(self.hits(self.call(key, "/v1/search?q=kalam")[1]))               # she is there to be found
        self.assertTrue(self.hits(self.call(key, "/v1/profile/people")[1]))
        self.leave_out_grace()
        for method, path, body in ALL_ROUTES:
            st, out = self.call(key, path, method, body)
            self.assertIn(st, (200, 400), path)
            self.assertEqual(self.hits(out), [], (path, body))
        self.assertIn("ada", json.dumps(self.call(key, "/v1/profile/people")[1]).lower())  # the rest of the page is still there

    def test_the_rules_hold_for_a_limited_key_a_profile_key_and_mcp(self):
        from ctx import mcp
        self.leave_out_grace()
        rows = api.make_key("rows", {"sources": "whatsapp"})
        for method, path, body in (("GET", "/v1/search?q=kalam;kettle;memo", None), ("POST", "/v1/tools/read_thread", {"thread": "grace hopper"}),
                                   ("POST", "/v1/tools/read_thread", {"around": "W2"}), ("POST", "/v1/tools/search", {"query": "kalam", "people": ["grace hopper"]})):
            self.assertEqual(self.hits(self.call(rows, path, method, body)[1]), [], path)
        prof = api.make_key("prof", {"profile": True})
        for path in ("/v1/profile", "/v1/profile/core", "/v1/briefing"):
            st, out = self.call(prof, path)
            self.assertEqual((st, self.hits(out)), (200, []), path)
        for name, args in (("page", {"name": "people"}), ("person", {"name": "grace"}), ("about_me", {}), ("search", {"query": "kalam"}), ("profile", {"section": "people"})):
            self.assertEqual(self.hits(mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})), [], name)

    def test_the_never_list_sits_above_every_key(self):
        full = api.make_key("full", all_=True)
        rows = api.make_key("rows", {"sources": "whatsapp", "people": "grace hopper"})        # a key made for exactly that conversation
        prof = api.make_key("prof", {"profile": True})
        self.assertIn("[W2]", self.call(rows, "/v1/search?q=kettle")[1]["text"])
        self.assertEqual(self.cli("--never-list", "people=Grace")["people"], ["grace"])       # part of the name, as the owner would type it
        for method, path, body in ALL_ROUTES:
            self.assertEqual(self.hits(self.call(full, path, method, body)[1]), [], path)
        self.assertEqual(self.hits(self.call(rows, "/v1/search?q=kettle;kalam")[1]), [])
        self.assertEqual(self.hits(self.call(rows, "/v1/tools/read_thread", "POST", {"thread": "grace hopper"})[1]), [])
        for path in ("/v1/profile", "/v1/briefing"):
            self.assertEqual(self.hits(self.call(prof, path)[1]), [])
        self.assertIn("[W1]", self.call(full, "/v1/search?q=kettle")[1]["text"])              # everyone else is still there

    def test_never_by_source_and_by_dates(self):
        full = api.make_key("full", all_=True)
        self.assertIn("[W5]", self.call(full, "/v1/search?q=kettle")[1]["text"])              # a line from march 2024
        api.command("api-never", {"ranges": [["2024-01", "2024-12"]]})
        got = self.call(full, "/v1/search?q=kettle")[1]["text"]
        self.assertNotIn("[W5]", got)
        self.assertIn("[W1]", got)
        api.command("api-never", {"ranges": [], "sources": ["whatsapp"]})
        self.assertNotIn("[W", self.call(full, "/v1/search?q=kettle;pottery")[1]["text"])
        self.assertNotIn("[W", self.call(full, "/v1/tools/read_thread", "POST", {"thread": "ada lovelace"})[1].get("text", ""))
        self.assertEqual(self.cli("--never-list", "--empty"), {"sources": [], "people": [], "ranges": []})
        self.assertIn("[W1]", self.call(full, "/v1/search?q=kettle")[1]["text"])
        for bad in ({"ranges": [["2025", "2024"]]}, {"ranges": [["soon", ""]]}, {"people": ["a"]}):
            self.assertIn("error", api.command("api-never", bad))

    def test_nothing_about_the_list_is_passed_through_the_environment(self):
        api.set_never(people=["grace hopper"])
        full = api.make_key("full", all_=True)
        self.call(full, "/v1/search?q=kettle")
        self.assertEqual([k for k in os.environ if "NEVER" in k], [])            # it used to be put there, and leaked into every later child

    def test_another_process_reads_the_list_from_the_store(self):
        """The model's tool server for /v1/ask and for the app's own answers, and mcp over stdio, are other processes: each
        reads never.json itself. Here one is started on the made-up archive with a list beside it."""
        mine = os.path.join(fixture.HOME, "never.json")
        self.addCleanup(lambda: os.path.exists(mine) and os.remove(mine))
        ask = lambda tool, args, **env: json.loads(subprocess.run(
            [sys.executable, "-m", "ctx", "mcp"], cwd=fixture.REPO, capture_output=True, text=True, timeout=120, env=dict(os.environ, PYTHONPATH=fixture.REPO, **env),
            input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}) + "\n").stdout)["result"]["content"][0]["text"]
        made = [os.path.join(fixture.HOME, n) for n in ("api.json", "api.json.lock", "api.log") if not os.path.exists(os.path.join(fixture.HOME, n))]
        self.addCleanup(lambda: [os.remove(p) for p in made if os.path.exists(p)])
        with mock.patch.object(api, "CONF", os.path.join(fixture.HOME, "api.json")):
            api.mcp_client("unnamed", all_=True)                                  # the owner opened the app that reads over stdio
        own = fixture.own_run()
        self.assertIn("W2", ask("search", {"query": "kalam; kettle"}))
        with mock.patch.object(api, "NEVER", mine):
            api.set_never(people=["grace"])
        for env in ({}, own):                                      # another app over stdio; the app's own answering loop
            text = ask("search", {"query": "kalam; kettle"}, **env)
            self.assertIn("W1", text)
            self.assertEqual([w for w in GRACE if w in text.lower()], [], env)
            self.assertEqual([w for w in GRACE if w in ask("profile" if env else "page", {"section": "people"} if env else {"name": "people"}, **env).lower()], [], env)
            self.assertEqual([w for w in GRACE if w in ask("read_thread", {"thread": "grace hopper"}, **env).lower()], [], env)


class Tiers(Base):
    def test_a_profile_key_gets_the_profile_and_the_briefing_and_nothing_else(self):
        key = self.cli("--key", "greeter", "--preset", "profile")["key"]
        st, out = self.call(key, "/v1")
        self.assertEqual([e["path"] for e in out["endpoints"]], ["/v1", "/v1/openapi.json", "/v1/profile/{section}", "/v1/briefing"])
        self.assertEqual(self.call(key, "/v1/profile")[0], 200)
        self.assertEqual(self.call(key, "/v1/profile/core")[0], 200)
        self.assertEqual(self.call(key, "/v1/briefing")[0], 200)
        for method, path, body in [r for r in ALL_ROUTES if r[1] not in ("/v1/profile/core", "/v1/briefing")] + [
                ("GET", "/v1/profile/voice", None), ("GET", "/v1/tools", None), ("POST", "/v1/ask", {"question": "x"}), ("GET", "/v1/wiki/people", None)]:
            st, out = self.call(key, path, method, body)
            self.assertEqual(st, 403, path)
            self.assertIn("no messages, no search, no people, no wiki", out["error"])
        self.assertEqual(api.log_for("greeter", 1)[0]["rows"], 0)

    def test_a_limited_key_cannot_reach_the_whole_archive_by_any_path(self):
        key = api.make_key("narrow", {"sources": "whatsapp", "people": "ann"})
        tools = {t["name"] for t in self.call(key, "/v1/tools")[1]["tools"]}
        self.assertEqual(tools, set(api.SCOPED_TOOLS))
        from ctx import mcp
        tries = [("GET", "/v1/Profile/core"), ("GET", "/V1/profile/core"), ("GET", "/v1/profile%2Fcore"), ("GET", "/v1/%70rofile/core"), ("GET", "/v1//profile/core"),
                 ("GET", "/v1/search/../profile/core"), ("GET", "/v1/search/%2e%2e/sources"), ("GET", "/v1/profile/core/"), ("GET", "/v1/profile/core?q=x"),
                 ("GET", "/v1/sources#x"), ("GET", "/v1/wiki/people"), ("GET", "/v1/briefing"), ("GET", "/v1/people/ann"), ("POST", "/v1/ask"), ("POST", "/v1/ASK"),
                 ("POST", "/v1/tools/Search"), ("POST", "/v1/tools/%61bout_me"), ("POST", "/v1/tools/search/../about_me"), ("POST", "/v1/tools/about_me%00")]
        tries += [("POST", "/v1/tools/" + t) for t in mcp.TOOLS if t not in api.SCOPED_TOOLS]      # every tool the full api lists
        for method, path in tries:
            st, out = self.call(key, path, method, {"query": "kettle", "name": "ada", "section": "core", "question": "x"} if method == "POST" else None)
            self.assertIn(st, (400, 403, 404), path)
            self.assertNotIn("text", out, path)
            self.assertNotIn("answer", out, path)

    def test_no_route_answers_without_a_key_and_a_key_is_good_for_this_server_only(self):
        """A server that reads its key and then forgets to check it on one route is the classic mistake. Every address the api
        knows, and ones it does not, is tried with no key, a wrong key, an expired key and another server's secret."""
        from ctx import mcp, remote
        good = api.make_key("good", all_=True)
        old = api.make_key("old", all_=True, days=1)
        closed = api.make_key("closed")
        paths_ = [p.split("?")[0].replace("{name}", "search").replace("{section}", "core").replace("{page id}", "people") for m, p, d in api.ENDPOINTS]
        paths_ += ["/v1/tools/" + n for n in mcp.TOOLS] + ["/", "/v1/", "/v2", "/mcp", "/mcp/x", "/v1/keys", "/v1/admin", "/health", "/favicon.ico", "/.well-known/oauth-authorization-server"]
        with mock.patch.object(remote, "CONF", os.path.join(self.tmp, "remote.json")):
            other = remote.secret()                                       # the secret of the remote endpoint: a different server
            for path in paths_:
                for method in ("GET", "POST"):
                    body = {} if method == "POST" else None
                    for key, label in (("", "no key"), ("ctx_" + "x" * 43, "a made-up key"), (other, "another server's secret"), (good[:-1], "a key cut short"), (good.upper(), "the key in capitals")):
                        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), method=method, data=json.dumps(body).encode() if body is not None else None,
                                                     headers={"Authorization": "Bearer " + key} if key else {})
                        try:
                            with urllib.request.urlopen(req, timeout=30) as r:
                                self.fail("%s %s answered %d with %s" % (method, path, r.status, label))
                        except urllib.error.HTTPError as e:
                            with e:
                                self.assertEqual(e.code, 401, (method, path, label))
                                self.assertEqual(sorted(json.loads(e.read())), ["error"])      # and the refusal says nothing about what is here
            with mock.patch("time.time", lambda t=time.time: t() + 3 * 86400):
                self.assertEqual({self.call(old, p)[0] for p in paths_[:6]}, {401})
            self.assertEqual({self.call(closed, p)[0] for p in paths_ if p not in ("/v1", "/v1/openapi.json", "/v1/", "/")} - {403, 404}, set())
            gate = remote.Gate()                                          # and the other way: an api key does not open the remote endpoint
            self.assertFalse(gate.opens("/mcp/" + good, None))
            self.assertFalse(gate.opens("/mcp", "Bearer " + good))
            self.assertTrue(gate.opens("/mcp/" + other, None))

    def test_a_name_is_matched_as_whole_words(self):
        row = lambda thread, sender="": {"src": "whatsapp", "ts": "2025-06-01", "thread": thread, "sender": sender, "who": "them"}
        scope = api.clean_scope({"people": "ann"})
        self.assertTrue(api.in_scope(row("ann"), scope))
        self.assertTrue(api.in_scope(row("Ann Lee"), scope))
        self.assertTrue(api.in_scope(row("book club", "ann"), scope))
        for other in ("joanna", "annabel", "hannah", "dann"):                             # "ann" inside another name is another person
            self.assertFalse(api.in_scope(row(other), scope), other)
        self.assertTrue(api.never_hides(row("grace hopper"), {"sources": [], "people": ["grace"], "ranges": []}))
        self.assertFalse(api.never_hides(row("gracelyn"), {"sources": [], "people": ["grace"], "ranges": []}))
        key = api.make_key("fr", {"people": "friend 1"})                                  # "friend 1" is not "friend 10" to "friend 19"
        text = self.call(key, "/v1/search?q=pottery&limit=40")[1]["text"]
        self.assertIn("friend 1 |", text)
        self.assertNotIn("friend 1" + "0", text)

    def test_the_apps_commands(self):
        made = api.command("api-key-make", {"name": "from-app", "preset": "people", "scope": {"people": ["ada lovelace"]}, "days": 7})
        self.assertEqual((made["name"], made["reads"][:9], made["key"][:4]), ("from-app", "only imes", "ctx_"))
        self.assertAlmostEqual(made["expires"], time.time() + 7 * 86400, delta=60)
        self.assertIn("error", api.command("api-key-make", {"name": "from-app"}))
        self.assertIn("warning", api.command("api-key-make", {"name": "wide", "all": True, "never": True}))
        got = api.command("api-keys", {})
        self.assertEqual(sorted(got), ["hold_unusual", "keys", "never", "presets", "running", "turned_away", "url"])
        self.assertEqual(sorted(got["presets"]), ["people", "profile", "work", "writing"])
        self.assertEqual({k["name"]: (k["kind"], k["preset"], k["expires"] == 0) for k in got["keys"]}, {"from-app": ("rows", "people", False), "wide": ("all", "", True)})
        row = api.command("api-key-set", {"name": "wide", "preset": "profile", "days": 2, "rows_per_day": 50})
        self.assertEqual((row["kind"], row["preset"], row["rows_per_day"]), ("profile", "profile", 50))
        self.assertEqual(api.command("api-key-set", {"name": "wide", "all": False})["kind"], "none")
        self.assertEqual(api.command("api-log", {"key": "wide", "days": 2})["days"][-1]["calls"], 0)
        self.assertEqual(api.command("api-never", {"sources": ["calendar"]})["never"]["sources"], ["calendar"])
        self.assertEqual(api.command("api-key-revoke", {"name": "wide"}), {"revoked": True})
        self.assertIn("error", api.command("api-key-set", {"name": "wide", "all": True}))
        from ctx import serve
        with open(serve.__file__, encoding="utf-8") as f:
            self.assertIn('"api-keys"', f.read())


if __name__ == "__main__":
    unittest.main()
