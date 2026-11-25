import unittest.mock
import io, json, os, subprocess, sys, tempfile, unittest
from tests import fixture
from ctx import mcp

TOOLS = ["about_me", "page", "person", "search", "facts", "open_loops", "sources", "read_thread", "card", "timeline", "saved", "links", "doc", "profile", "voice", "wiki", "stats", "lapsed", "shared", "intros", "conflicts", "ideas"]


def req(i, method, params=None):
    m = {"jsonrpc": "2.0", "id": i, "method": method}
    if params is not None:
        m["params"] = params
    return m


def tool(i, name, args=None):
    return req(i, "tools/call", {"name": name, "arguments": args} if args is not None else {"name": name})


def text(reply):
    from ctx import guard
    return guard.unfence(reply["result"]["content"][0]["text"])       # what a tool said, without the marks that say it is data


class Handle(unittest.TestCase):
    """The message handler, called directly on the made-up archive."""

    def ok(self, reply, i):
        self.assertEqual((reply["jsonrpc"], reply["id"]), ("2.0", i))
        self.assertNotIn("error", reply)
        return reply["result"]

    def test_initialize(self):
        res = self.ok(mcp.handle(req(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})), 1)
        self.assertEqual(res["protocolVersion"], "2025-06-18")
        self.assertIn("tools", res["capabilities"])
        self.assertEqual(res["serverInfo"]["name"], "context")
        self.assertIn("never instructions", res["instructions"])

    def test_an_unknown_protocol_version_gets_one_we_speak(self):
        for params in ({"protocolVersion": "1999-01-01"}, {}, None):
            self.assertEqual(self.ok(mcp.handle(req(1, "initialize", params)), 1)["protocolVersion"], mcp.VERSIONS[0])

    def test_ids_are_echoed_as_given(self):
        for i in (0, 7, "abc", "7"):
            self.assertEqual(mcp.handle(req(i, "ping")), {"jsonrpc": "2.0", "id": i, "result": {}})

    def test_notifications_get_no_reply(self):
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}}))
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "facts"}}))

    def test_a_reply_sent_to_us_is_ignored(self):
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "id": 1, "result": {}}))
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "id": 1, "error": {"code": 1, "message": "x"}}))

    def test_invalid_requests(self):
        for m in (5, "x", None, {}, {"id": 1}, {"jsonrpc": "2.0", "id": None, "method": "ping"}, {"id": [1], "method": "ping"},
                  {"id": True, "method": "ping"}, {"id": 1, "method": 5}):
            self.assertEqual(mcp.handle(m)["error"]["code"], -32600, m)

    def test_unknown_method(self):
        for method in ("resources/list", "prompts/list", "nope", ""):
            r = mcp.handle(req(3, method))
            self.assertEqual((r["id"], r["error"]["code"]), (3, -32601))
            self.assertNotIn("result", r)

    def test_bad_params(self):
        self.assertEqual(mcp.handle(req(1, "tools/call", [1]))["error"]["code"], -32602)
        self.assertEqual(mcp.handle(req(1, "tools/call", {}))["error"]["code"], -32602)
        self.assertEqual(mcp.handle(req(1, "tools/call", {"name": 5}))["error"]["code"], -32602)
        self.assertEqual(mcp.handle(req(1, "tools/call", {"name": "search", "arguments": "kettle"}))["error"]["code"], -32602)
        r = mcp.handle(tool(1, "delete_everything", {}))
        self.assertEqual(r["error"]["code"], -32602)
        self.assertIn("unknown tool", r["error"]["message"])

    def test_tools_list(self):
        tools = self.ok(mcp.handle(req(2, "tools/list")), 2)["tools"]
        self.assertEqual([t["name"] for t in tools], ["context_" + n for n in TOOLS])       # every tool carries the server's name: `search` is a name any server may use
        for t in tools:
            self.assertTrue(t["description"])
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertIsInstance(t["inputSchema"]["properties"], dict)
            self.assertTrue(set(t["inputSchema"]["required"]) <= set(t["inputSchema"]["properties"]))
        json.dumps(tools)

    def call(self, name, args=None, error=False):
        res = self.ok(mcp.handle(tool(9, name, args)), 9)
        self.assertEqual([c["type"] for c in res["content"]], ["text"])
        self.assertIsInstance(res["content"][0]["text"], str)
        self.assertIs(res["isError"], error)
        self.assertLessEqual(len(res["content"][0]["text"]), mcp.MOST + 100)
        from ctx import guard
        self.assertEqual(res["content"][0]["text"].startswith(guard.NOTE), not error)      # every result another app's model reads is marked as data
        return guard.unfence(res["content"][0]["text"])

    def test_every_tool_answers(self):
        self.assertIn("pottery", self.call("about_me"))
        self.assertIn("pottery", self.call("about_me", {}))
        self.assertIn("ada", self.call("page", {"name": "people"}))
        self.assertIn("not written yet", self.call("page", {"name": "voice"}))
        self.assertIn("close friend", self.call("person", {"name": "Ada"}))
        self.assertIn("W1", self.call("search", {"query": "kettle fund"}))
        self.assertIn("total", json.loads(self.call("facts")))
        self.assertTrue(self.call("open_loops"))
        self.assertIn("whatsapp", self.call("sources", {"extra": "ignored"}))

    def test_missing_and_wrong_arguments_are_said_plainly(self):
        self.assertIn("name must be one of", self.call("page", error=True))
        self.assertIn("name must be one of", self.call("page", {"name": "../../etc/passwd"}, error=True))
        self.assertIn("name must be one of", self.call("page", {"name": "core"}, error=True))
        self.assertIn("give a name", self.call("person", error=True))
        self.assertIn("give a name", self.call("person", {"name": " "}, error=True))
        self.assertIn("give a name", self.call("person", {"name": None}, error=True))
        self.assertIn("give a query", self.call("search", error=True))
        self.assertIn("give a query", self.call("search", {"query": ""}, error=True))
        self.assertIn("give a query", self.call("search", {"query": " ; ;"}, error=True))

    def test_a_name_that_matches_nobody(self):
        self.assertIn("nobody by that name", self.call("person", {"name": "zorblax the unknown"}))
        self.assertTrue(self.call("search", {"query": "zorblaxian"}).startswith("no match"))

    def test_person_found_through_another_card(self):
        self.assertIn("collaborator", self.call("person", {"name": "babbage"}))

    def test_unicode(self):
        self.assertIn("W11", self.call("search", {"query": "पढ़ाई"}))
        self.assertIn("nobody by that name", self.call("person", {"name": "पढ़ाई 🙂"}))
        json.dumps(mcp.handle(tool(1, "search", {"query": "पढ़ाई"}))).encode("ascii")     # what goes on the wire is plain ascii

    def test_search_limit_is_bounded(self):
        for limit in (10 ** 9, -5, 0, "many", None, 3.7, "3"):
            out = self.call("search", {"query": "pottery", "limit": limit})
            self.assertLessEqual(out.count("\n"), 50, limit)
        self.assertEqual(self.call("search", {"query": "pottery", "limit": 3}).count("\n"), 3)

    def test_search_filters(self):
        out = self.call("search", {"query": "pottery", "source": "x_bookmarks"})
        self.assertEqual(out.count("x_bookmarks"), 3)
        self.assertIn("<https://example.com/b/", out)
        mine = self.call("search", {"query": "pottery", "only_mine": True, "limit": 50})
        self.assertNotIn("| them:", mine)
        self.assertNotIn("| saved:", mine)
        self.assertTrue(self.call("search", {"query": "lantern", "only_mine": "true"}).startswith("no match"))
        self.assertIn("| quiet 0:", self.call("search", {"query": "lantern", "only_mine": "false"}))     # the sender by name
        self.assertIn("W5", self.call("search", {"query": "invest", "after": "2024-01"}))
        self.assertNotIn("W6", self.call("search", {"query": "invest", "after": "2024-01"}))
        self.assertIn("W6", self.call("search", {"query": "invest", "before": "2023-12", "after": 5}))

    def test_other_peoples_numbers_and_addresses_are_masked(self):
        out = self.call("search", {"query": "samovar"})
        self.assertNotIn("555", out)
        self.assertNotIn("example.com", out)
        self.assertIn("[number]", out)
        self.assertIn("[email]", out)
        card = self.call("person", {"name": "ada"})
        self.assertNotIn("555", card)
        self.assertNotIn("bab@", card)
        self.assertNotIn("1700000000", card)

    def test_unless_the_owner_asked_for_that_number(self):
        self.assertIn("555 0199", self.call("search", {"query": "samovar; 415 555 0199"}))

    def test_mask_leaves_dates_amounts_and_links_alone(self):
        for s in ("on 2024-03-09 10:30 we met", "sold 3,400,000,000 units by june", "see https://example.com/status/1234567890123456789",
                  "0x52908400098527886E0F7030069857D2E4169EE7", "version 10.15.7 build 2024.11.20", "T-1001234567890_55"):
            self.assertEqual(mcp.mask(s), s)
        self.assertEqual(mcp.mask("ring 98765 43210 now"), "ring [number] now")

    def test_a_crash_inside_a_tool_is_one_plain_sentence(self):
        from unittest import mock
        with mock.patch("ctx.facts.facts", side_effect=OSError("/Users/someone/secret/path")):
            out = self.call("facts", error=True)
        self.assertNotIn("/Users", out)
        self.assertNotIn("Traceback", out)

    def test_a_huge_page_is_cut(self):
        p = os.path.join(fixture.HOME, "memory", "timeline.md")
        with open(p, "w") as f:
            f.write("a line of the timeline\n" * 200_000)
        try:
            out = self.call("page", {"name": "timeline"})
            self.assertIn("cut here", out)
        finally:
            os.remove(p)


class Serve(unittest.TestCase):
    """The read loop, fed bytes in memory."""

    def setUp(self):
        import shutil
        from unittest import mock
        from ctx import api
        tmp = tempfile.mkdtemp(prefix="ctx-serve-")
        self.addCleanup(shutil.rmtree, tmp, True)
        for name in ("CONF", "LOG"):
            p = mock.patch.object(api, name, os.path.join(tmp, name.lower()))
            p.start()
            self.addCleanup(p.stop)
        api._mcp_gate.clear()
        self.addCleanup(api._mcp_gate.clear)
        api.mcp_client("unnamed", all_=True)            # the owner opened this app: what the loop does with one that is closed is in Clients

    def run_lines(self, lines):
        out = io.StringIO()
        mcp.serve(io.BytesIO(b"".join(l if isinstance(l, bytes) else (json.dumps(l) if not isinstance(l, str) else l).encode() + b"\n" for l in lines)), out)
        return [json.loads(l) for l in out.getvalue().splitlines()]

    def test_malformed_json_gets_a_parse_error_and_the_loop_goes_on(self):
        got = self.run_lines(["{not json", b"\xff\xfe{\n", "", "   ", req(1, "ping")])
        self.assertEqual([g.get("error", {}).get("code") for g in got], [-32700, -32700, None])
        self.assertEqual(got[0]["id"], None)
        self.assertEqual(got[2], {"jsonrpc": "2.0", "id": 1, "result": {}})

    def test_a_batch(self):
        got = self.run_lines([[req(1, "ping"), {"jsonrpc": "2.0", "method": "notifications/initialized"}, req(2, "nope")], [], [{"jsonrpc": "2.0", "method": "x"}]])
        self.assertEqual([g["id"] for g in got[0]], [1, 2])
        self.assertEqual(got[1]["error"]["code"], -32600)
        self.assertEqual(len(got), 2)

    def test_a_print_inside_a_tool_does_not_reach_the_stream(self):
        from unittest import mock

        def noisy():
            print("stray line")
            return {"lines": [], "total": 0}
        err = io.StringIO()
        with mock.patch("ctx.facts.facts", noisy), mock.patch.object(sys, "stderr", err):
            got = self.run_lines([tool(1, "facts")])
        self.assertEqual(len(got), 1)
        self.assertIn("stray line", err.getvalue())

    def test_stdout_is_put_back(self):
        before = sys.stdout
        self.run_lines([req(1, "ping")])
        self.assertIs(sys.stdout, before)


class Process(unittest.TestCase):
    """The real thing: `python -m ctx mcp` as a child process, the way an AI app starts it."""

    def talk(self, home, messages, raw=b"", **more):
        env = dict(os.environ, CTX_HOME=home, PYTHONPATH=fixture.REPO, **more)
        data = b"".join(json.dumps(m).encode() + b"\n" for m in messages) + raw
        p = subprocess.run([sys.executable, "-m", "ctx", "mcp"], input=data, capture_output=True, env=env, cwd=fixture.REPO, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr[-400:])                 # a clean exit when the pipe closes
        self.assertNotIn(b"Traceback", p.stderr)
        lines = p.stdout.decode("ascii").splitlines()                      # ascii only, one json object per line, nothing else
        return [json.loads(l) for l in lines]

    def session(self, home, opened=True):
        msgs = [req(0, "tools/list"),                                       # before initialize: answered, not a crash
                req(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}),
                {"jsonrpc": "2.0", "method": "notifications/initialized"}, req(2, "ping"), req(3, "tools/list")]
        calls = [("about_me", {}), ("page", {"name": "people"}), ("page", {}), ("person", {"name": "ada"}), ("person", {"name": "nobody at all"}),
                 ("person", {}), ("search", {"query": "kettle; pottery", "limit": 10 ** 9}), ("search", {"query": ""}), ("search", {"query": "पढ़ाई"}),
                 ("facts", {}), ("open_loops", {}), ("sources", {})]
        msgs += [tool(10 + n, name, args) for n, (name, args) in enumerate(calls)]
        msgs += [tool(40, "nope", {}), req(41, "nope/nope")]
        got = self.talk(home, msgs, raw=b"{broken\n")
        by_id = {g["id"]: g for g in got}
        self.assertEqual(len(got), len(msgs) - 1 + 1)                      # every request answered, the notification not, plus the parse error
        self.assertEqual(sorted(k for k in by_id if k is not None), sorted(m["id"] for m in msgs if "id" in m))
        self.assertEqual(by_id[None]["error"]["code"], -32700)
        self.assertEqual(by_id[40]["error"]["code"], -32602)
        self.assertEqual(by_id[41]["error"]["code"], -32601)
        # an app the owner opened reads with every tool. one nobody opened is handed the short profile, on a full archive and an empty one alike
        self.assertEqual([t["name"] for t in by_id[3]["result"]["tools"]], ["context_" + n for n in TOOLS] if opened else ["context_about_me", "context_profile"])
        self.assertEqual(by_id[0]["result"], by_id[3]["result"])
        for n, (name, args) in enumerate(calls):
            res = by_id[10 + n]["result"]
            self.assertEqual(res["content"][0]["type"], "text")
            self.assertTrue(res["content"][0]["text"], name)
            self.assertLessEqual(len(res["content"][0]["text"]), mcp.MOST + 100)
            self.assertNotIn("Traceback", res["content"][0]["text"])
            self.assertEqual(res["isError"], (name, args) in (("page", {}), ("person", {}), ("search", {"query": ""})) or (not opened and name != "about_me"), (name, args))
        return by_id

    def test_a_full_session_on_an_archive(self):
        made = [os.path.join(fixture.HOME, n) for n in ("api.json", "api.json.lock", "api.log") if not os.path.exists(os.path.join(fixture.HOME, n))]
        self.addCleanup(lambda: [os.remove(p) for p in made if os.path.exists(p)])       # the app's record and its read log: not left for other tests
        closed = self.session(fixture.HOME, opened=False)                    # years of messages in the archive earn an app nothing
        self.assertIn("closed to it", text(closed[16]))
        self.assertNotIn("kettle fund", json.dumps(closed))
        from unittest import mock
        from ctx import api
        with mock.patch.object(api, "CONF", os.path.join(fixture.HOME, "api.json")):
            api.set_key("mcp:unnamed", all_=True)                            # the owner's own word: python3 -m ctx api --set mcp:unnamed --all
        by_id = self.session(fixture.HOME)
        self.assertIn("W1", text(by_id[16]))

    def test_a_full_session_for_a_new_user_with_an_empty_folder(self):
        with tempfile.TemporaryDirectory(prefix="ctx-empty-") as home:
            by_id = self.session(home, opened=False)
            self.assertIn("has not run yet", text(by_id[10]))
            for closed in (13, 16):                                                     # person and search: not for an app nobody opened
                self.assertTrue(by_id[closed]["result"]["isError"])
                self.assertIn("closed to it", text(by_id[closed]))
                self.assertIn("python3 -m ctx api --set mcp:unnamed", text(by_id[closed]))
            # reading wrote nothing but the archive's marker (an empty folder becomes context's own: guard.claim), the app's own record and the count of what it read
            self.assertEqual(sorted(f for f in os.listdir(home) if f != "memory"), [".closed", "api.json", "api.json.lock", "api.log"])
            with open(os.path.join(home, "api.log")) as f:
                log = f.read()
            self.assertIn('"key": "mcp:unnamed"', log)
            for word in ("ada", "kettle", "pottery", "nobody"):                         # what was asked is never in it
                self.assertNotIn(word, log)

    def test_nothing_sent(self):
        self.assertEqual(self.talk(fixture.HOME, []), [])

    def test_an_entry_that_says_it_is_the_apps_own_loop_gets_nothing_for_it(self):
        """What any ai app's config can hold: our command, and any names it likes in the environment."""
        from ctx import guard, tools as agent_tools
        made = [os.path.join(fixture.HOME, n) for n in ("api.json", "api.json.lock", "api.log") if not os.path.exists(os.path.join(fixture.HOME, n))]
        self.addCleanup(lambda: [os.remove(p) for p in made if os.path.exists(p)])
        ended = fixture.own_run()[guard.AGENT_RUN]
        guard.agent_close(ended)
        msgs = [req(1, "tools/list"), tool(2, "search", {"query": "kettle"}), tool(3, "context_about_me", {}), tool(4, "stats", {"what": "people"})]
        with tempfile.TemporaryDirectory(prefix="ctx-stranger-") as t:
            log, cache = os.path.join(t, "rows.jsonl"), os.path.join(t, "kept")
            for n, said in enumerate(({"CTX_AGENT": "1"}, {"CTX_AGENT": "1", guard.AGENT_RUN: "f" * 64}, {"CTX_AGENT": "1", guard.AGENT_RUN: ended},
                                      {"CTX_AGENT": "1", guard.AGENT_RUN: "../../api.json"})):
                got = {g["id"]: g for g in self.talk(fixture.HOME, msgs, CTX_MCP_CLIENT="stranger%d" % n, CTX_AGENT_LOG=log, CTX_AGENT_CACHE=cache,
                                                     CTX_AGENT_SEAL="0123456789abcdef", CTX_AGENT_SCOPE="{}", **said)}
                self.assertEqual([x["name"] for x in got[1]["result"]["tools"]], ["context_about_me", "context_profile"], said)     # the limits of a new app, the names of another program
                for closed in (2, 4):
                    self.assertTrue(got[closed]["result"]["isError"], said)
                    self.assertIn("closed to it", text(got[closed]))
                self.assertNotIn("kettle fund", json.dumps(got))
                raw = got[3]["result"]["content"][0]["text"]
                self.assertTrue(raw.startswith(guard.NOTE) and raw.endswith(guard.FENCE_CLOSE), said)       # marked as data, not handed over inside a seal it chose
                self.assertNotIn("<<material", raw)
                self.assertEqual(os.listdir(t), [], said)                                        # and it had nothing written where it pointed
            own = {g["id"]: g for g in self.talk(fixture.HOME, msgs[:2], CTX_MCP_CLIENT="stranger0", **fixture.own_run())}       # the real thing, for contrast
            self.assertEqual([x["name"] for x in own[1]["result"]["tools"]], [n for n in TOOLS if n in agent_tools.AGENT])
            self.assertIn("W1", text(own[2]))


class NeverList(unittest.TestCase):
    """The never list (ctx/api.py keeps it, ctx/rules.py holds it) binds mcp exactly as it binds the local api."""

    def setUp(self):
        import shutil, tempfile
        from unittest import mock
        from ctx import api, rules
        self.tmp = tempfile.mkdtemp(prefix="ctx-never-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for mod, name in ((api, "NEVER"), (api, "CONF"), (rules, "FILE"), (rules, "GONE")):
            p = mock.patch.object(mod, name, os.path.join(self.tmp, name.lower()))
            p.start()
            self.addCleanup(p.stop)
        rules._mem.clear()
        self.addCleanup(rules._mem.clear)
        self.api = api

    def said(self, name, args, **kw):
        return json.dumps(mcp.handle(tool(1, name, args), **kw)).lower()

    def test_over_stdio(self):
        self.assertIn("kalam", self.said("search", {"query": "kalam"}))
        self.assertIn("admiral", self.said("page", {"name": "people"}))
        self.api.set_never(people=["grace hopper"])
        for name, args in (("search", {"query": "kalam; kettle memo"}), ("read_thread", {"thread": "grace hopper"}), ("read_thread", {"around": "W2"}), ("doc", {"id": "W2"}),
                           ("page", {"name": "people"}), ("person", {"name": "grace"}), ("profile", {"section": "people"}), ("card", {"thread": "grace hopper"}),
                           ("stats", {"what": "people"}), ("about_me", {})):
            text = self.said(name, args)
            for word in ("kalam", "kettle memo", "milte hain", "admiral"):
                self.assertNotIn(word, text, name)
        self.assertIn("kettle fund", self.said("search", {"query": "kettle"}))       # everyone else is still there

    def test_over_http_and_for_the_apps_own_loop(self):
        from unittest import mock
        self.api.set_never(sources=["whatsapp"])
        self.assertNotIn("[w", self.said("search", {"query": "kettle; pottery"}, strict=True, allow=["search"]))      # how remote.py calls it
        with mock.patch.dict(os.environ, fixture.own_run()):
            self.assertNotIn("[w", self.said("search", {"query": "kettle; pottery"}))
        self.api.set_never(sources=[])
        self.assertIn("[w", self.said("search", {"query": "kettle"}))

    def test_dates(self):
        self.api.set_never(ranges=[["2024-01", "2024-12"]])
        text = self.said("search", {"query": "kettle"})
        self.assertNotIn("[w5]", text)
        self.assertIn("[w1]", text)



class Clients(unittest.TestCase):
    """Each ai app that reads over mcp has its own limits, its own count of what it read, and can be closed by itself."""

    def setUp(self):
        import shutil, tempfile
        from unittest import mock
        from ctx import api, rules
        fixture.write()
        self.tmp = tempfile.mkdtemp(prefix="ctx-clients-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for mod, name in ((api, "CONF"), (api, "LOG"), (api, "NEVER"), (rules, "FILE"), (rules, "GONE"), (mcp, "WROTE")):
            p = mock.patch.object(mod, name, os.path.join(self.tmp, name.lower()))
            p.start()
            self.addCleanup(p.stop)
        rules._mem.clear()
        api._mcp_gate.clear()
        self.addCleanup(api._mcp_gate.clear)
        self.api, self.mock = api, mock

    def names(self, client):
        return [t["name"] for t in mcp.handle(req(1, "tools/list"), client=client)["result"]["tools"]]

    def ask(self, client, name, args=None):
        res = mcp.handle(tool(1, name, args or {}), client=client)
        return res["result"]["isError"], res["result"]["content"][0]["text"] if "result" in res else res

    def test_a_new_app_reads_the_short_profile_until_the_owner_opens_it(self):
        self.assertEqual(self.names("cursor"), ["context_about_me", "context_profile"])
        err, text = self.ask("cursor", "context_search", {"query": "kettle"})
        self.assertTrue(err)
        self.assertIn("closed to it", text)
        self.assertNotIn("kettle fund", text)
        self.assertFalse(self.ask("cursor", "context_about_me")[0])
        self.api.set_key("mcp:cursor", scope={"sources": "whatsapp", "people": "ada lovelace"})
        self.assertEqual(self.names("cursor"), ["context_" + n for n in TOOLS if n in self.api.SCOPED_TOOLS])
        err, text = self.ask("cursor", "context_search", {"query": "kettle"})
        self.assertIn("[W1]", text)
        self.assertNotIn("[W2]", text)                                   # the same word in a conversation with someone else
        self.assertTrue(self.ask("cursor", "context_person", {"name": "grace"})[0])
        self.assertEqual(self.names("another-app"), ["context_about_me", "context_profile"])      # what was opened for one app is not open for the next
        self.api.set_key("mcp:cursor", all_=True)
        self.assertEqual(len(self.names("cursor")), len(TOOLS))

    def test_an_archive_with_years_in_it_gives_no_app_everything_named_or_not(self):
        from ctx import paths
        self.assertGreater(os.path.getsize(paths.MESSAGES), 0)               # the archive is in use: that earns an app nothing
        with self.mock.patch.object(mcp, "registered_ids", lambda *a, **k: ["cursor", "claude_desktop"]):     # and nor does being connected already
            for app in ("unnamed", "", "cursor", "claude_desktop", "anything"):
                self.assertEqual(self.names(app), ["context_about_me", "context_profile"], app)
                err, text = self.ask(app, "context_search", {"query": "kettle"})
                self.assertTrue(err, app)
                self.assertNotIn("kettle fund", text)
        self.assertEqual({k["kind"] for k in self.api.keys()}, {"profile"})

    def test_an_update_carries_no_everything_over(self):
        with open(self.api.CONF, "w") as f:                                  # the file an earlier form left: apps and a key that read it all
            json.dump({"v": 2, "mcp_v": 1, "keys": {"mcp:unnamed": {"made": 1, "used": 0, "calls": 0, "expires": 0, "all": True, "client": True},
                                                    "mcp:cursor": {"made": 1, "used": 0, "calls": 0, "expires": 0, "all": True, "client": True},
                                                    "mcp:zed": {"made": 1, "used": 0, "calls": 0, "expires": 0, "scope": {"sources": ["whatsapp"]}, "client": True},
                                                    "mcp:shut": {"made": 1, "used": 0, "calls": 0, "expires": 0, "revoked": True, "client": True}}}, f)
        for app in ("unnamed", "cursor"):
            self.assertEqual(self.names(app), ["context_about_me", "context_profile"], app)
        self.assertEqual(self.names("zed"), ["context_" + n for n in TOOLS if n in self.api.SCOPED_TOOLS])       # what the owner set by hand stays
        self.assertEqual(self.names("shut"), [])
        listed = {k["name"]: k for k in self.api.keys()}
        self.assertEqual([listed[n]["kind"] for n in ("mcp:unnamed", "mcp:cursor", "mcp:zed", "mcp:shut")], ["profile", "profile", "rows", "none"])
        self.assertIn("api --set mcp:cursor --all", listed["mcp:cursor"]["narrowed"])
        self.assertNotIn("narrowed", listed["mcp:zed"])
        self.api.set_key("mcp:cursor", all_=True)                            # the owner opens their own app, by name
        self.assertEqual(len(self.names("cursor")), len(TOOLS))
        self.assertNotIn("narrowed", {k["name"]: k for k in self.api.keys()}["mcp:cursor"])
        self.assertEqual(self.names("unnamed"), ["context_about_me", "context_profile"])

    def test_closing_an_app_and_seeing_what_it_read(self):
        self.api.mcp_client("cursor", all_=True)
        self.ask("cursor", "context_search", {"query": "kettle"})
        self.ask("cursor", "context_person", {"name": "ada"})
        day = self.api.log_for("mcp:cursor", 1)[0]
        self.assertEqual((day["calls"], day["sources"]), (2, ["whatsapp"]))
        self.assertGreaterEqual(day["rows"], 1)
        with open(self.api.LOG) as f:
            log = f.read()
        self.assertNotIn("kettle", log)
        self.assertNotIn("ada", log)
        self.assertTrue(self.api.revoke("mcp:cursor"))
        self.assertEqual(self.names("cursor"), [])
        err, text = self.ask("cursor", "context_search", {"query": "kettle"})
        self.assertTrue(err)
        self.assertNotIn("kettle fund", text)
        row = next(k for k in self.api.keys() if k["name"] == "mcp:cursor")
        self.assertEqual((row["kind"], row["reads"]), ("none", "nothing: closed by the owner"))
        self.assertEqual(self.names("cursor"), [])                           # closed stays closed: it does not come back as a new app
        self.api.command("api-key-set", {"name": "mcp:cursor", "preset": "profile"})
        self.assertEqual(self.names("cursor"), ["context_about_me", "context_profile"])

    def test_an_app_reading_far_more_than_usual_is_held(self):
        import time
        self.api.mcp_client("cursor", all_=True)
        self.ask("cursor", "context_about_me")
        at = time.strftime("%Y-%m-%dT12:00:00+0000")
        with open(self.api.LOG, "a") as f:
            f.write(json.dumps({"key": "mcp:cursor", "method": "MCP", "path": "/mcp/search", "status": 200, "bytes": 1, "rows": 6000, "src": ["whatsapp"], "at": at}) + "\n")
        self.api._mcp_gate.clear()
        err, text = self.ask("cursor", "context_search", {"query": "kettle"})
        self.assertTrue(err)
        self.assertIn("far more today", text)
        self.assertIn("api --clear mcp:cursor", text)
        self.api.set_key("mcp:cursor", clear=True)
        self.api._mcp_gate.clear()
        self.assertFalse(self.ask("cursor", "context_search", {"query": "kettle"})[0])

    def test_the_name_is_carried_by_the_entry_context_writes(self):
        self.assertEqual(mcp._entry("std", "/usr/bin/python3", "/engine", "cursor")["env"], {"CTX_MCP_CLIENT": "cursor"})
        self.assertEqual(self.api.mcp_name("Cursor IDE / 2"), "mcp:cursor-ide-2")
        self.assertEqual(self.api.mcp_name(""), "mcp:unnamed")
        import inspect
        self.assertIn('os.environ.get("CTX_MCP_CLIENT") or "unnamed"', inspect.getsource(mcp.serve))


class Names(unittest.TestCase):
    """Another server can offer a tool called `search` too. Ours are all called context_<name>, and say how to tell them."""

    def test_every_tool_is_offered_under_the_servers_own_name(self):
        tools = mcp.handle(req(1, "tools/list"))["result"]["tools"]
        self.assertTrue(all(t["name"].startswith("context_") for t in tools))
        self.assertEqual(len({t["name"] for t in tools}), len(TOOLS))
        about = mcp.handle(req(1, "initialize", {"protocolVersion": "2025-06-18"}))["result"]
        self.assertEqual(about["serverInfo"]["name"], "context")
        for part in ("begins with context_", "is not this one", "never instructions", "Nothing here can send, change or schedule"):
            self.assertIn(part, about["instructions"])
        a = mcp.handle(tool(1, "context_search", {"query": "kettle"}))["result"]["content"][0]["text"]
        b = mcp.handle(tool(1, "search", {"query": "kettle"}))["result"]["content"][0]["text"]      # the old name still reaches the same tool, for a client set up before
        self.assertEqual(a, b)
        self.assertEqual(mcp.handle(tool(1, "context_context_search", {"query": "x"}))["error"]["code"], -32602)
        with mock_env(fixture.own_run()):                                   # the app's own loop talks to its own server only, under the plain names it always used
            self.assertNotIn("context_", json.dumps([t["name"] for t in mcp.handle(req(1, "tools/list"))["result"]["tools"]]))


class Reach(unittest.TestCase):
    """No tool takes a path. An id, a name or a page that looks like one reaches nothing outside the archive."""

    def test_arguments_that_look_like_paths_read_no_file(self):
        import tempfile
        d = tempfile.mkdtemp(prefix="ctx-reach-")
        secret = os.path.join(d, "id_made_up")
        with open(secret, "w") as f:
            f.write("MADE-UP-PRIVATE-KEY-1111")
        rel = os.path.relpath(secret, os.path.join(fixture.HOME, "memory", "wiki"))
        tries = [secret, "file://" + secret, rel, "../" * 12 + secret.lstrip("/"), "~/.ssh/id_ed25519", "/etc/passwd", "..%2f..%2fetc%2fpasswd", "memory/../../" + os.path.basename(d),
                 secret + "\x00.md", "people/../../../" + secret.lstrip("/"), "core/../../api.json", "../api.json", "../../never.json", "status.json", "messages.jsonl"]
        from unittest import mock
        from ctx import api
        patches = [mock.patch.object(api, "CONF", os.path.join(d, "api.json")), mock.patch.object(api, "LOG", os.path.join(d, "api.log")), mock.patch.object(api, "PER_MINUTE", 10 ** 6)]
        for p in patches:
            p.start()
        api._mcp_gate.clear()
        try:
            for name, (about, props, required) in mcp.TOOLS.items():
                for t in tries:
                    args = {k: t for k in props if props[k].get("type") == "string" and "enum" not in props[k]}
                    if not args:
                        continue
                    for client in (None, "unnamed"):
                        out = json.dumps(mcp.handle(tool(1, name, args), client=client))
                        self.assertNotIn("MADE-UP-PRIVATE-KEY", out, (name, t))
                        self.assertNotIn("root:", out, (name, t))
                        self.assertNotIn('\\"hash\\"', out, (name, t))            # the key store
                        self.assertNotIn(d, out, (name, t))                          # nor is a path echoed back from an error
        finally:
            import shutil
            for p in patches:
                p.stop()
            api._mcp_gate.clear()
            shutil.rmtree(d)

    def test_the_entry_context_writes_fetches_nothing_and_names_no_package(self):
        for shape in ("std", "copilot", "opencode"):
            e = mcp._entry(shape, "/usr/bin/python3", "/Applications/context.app/Contents/Resources/engine", "x")
            flat = json.dumps(e)
            for word in ("npx", "uvx", "pip ", "curl", "http", "@latest", "sh -c", "node", "PYTHONPATH"):
                self.assertNotIn(word, flat, (shape, word))
            cmd = e["command"] if isinstance(e["command"], list) else [e["command"]] + e["args"]
            self.assertEqual((cmd[:4], cmd[5:]), (["/usr/bin/python3", "-I", "-S", "-c"], ["/Applications/context.app/Contents/Resources/engine", "mcp"]))


class Entries(unittest.TestCase):
    """The line context writes into another app's config is a command that app runs. A changed one is noticed."""

    def setUp(self):
        import shutil, tempfile
        from unittest import mock
        from ctx import api
        self.home = tempfile.mkdtemp(prefix="ctx-entries-")
        self.addCleanup(shutil.rmtree, self.home, True)
        os.makedirs(os.path.join(self.home, ".cursor"))
        self.cfg = os.path.join(self.home, ".cursor", "mcp.json")
        for mod, name in ((mcp, "WROTE"), (api, "CONF"), (api, "LOG")):
            p = mock.patch.object(mod, name, os.path.join(self.home, "store-" + name.lower()))
            p.start()
            self.addCleanup(p.stop)
        self.run = lambda *a, **k: __import__("subprocess").CompletedProcess(a, 0, "", "")
        self.api = api

    def cursor(self):
        return next(r for r in mcp.status(home=self.home, claude=None, run=self.run) if r["id"] == "cursor")

    def test_an_entry_another_program_changed_is_flagged(self):
        lines = []
        said = mcp.install(home=self.home, claude=None, run=self.run, say=lines.append, only="cursor")
        self.assertEqual(said["cursor"], "registered")
        self.assertIn("it reads", lines[0])
        self.assertEqual(self.cursor()["state"], "registered")                 # read from the files: the same answer on every mac
        self.assertEqual(self.cursor()["detail"].count("not the one context wrote"), 0)
        with open(self.cfg) as f:
            cfg = json.load(f)
        self.assertEqual(cfg["mcpServers"]["context"]["env"]["CTX_MCP_CLIENT"], "cursor")
        for change in (lambda e: e.update(command="/tmp/evil-python"), lambda e: e["args"].append("--extra"), lambda e: e["env"].update(PYTHONPATH="/tmp/evil"),
                       lambda e: e["env"].update(PYTHONSTARTUP="/tmp/x.py"), lambda e: e["env"].update(CTX_MCP_CLIENT="unnamed"), lambda e: e.update(args=["-c", "import os"])):
            evil = json.loads(json.dumps(cfg))
            change(evil["mcpServers"]["context"])
            with open(self.cfg, "w") as f:
                json.dump(evil, f)
            row = self.cursor()
            self.assertEqual(row["state"], "changed")
            self.assertIn("not the one context wrote", row["detail"])
            self.assertIn("python3 -m ctx mcp --install cursor", row["detail"])
        with open(self.cfg, "w") as f:
            json.dump(cfg, f)
        self.assertNotEqual(self.cursor()["state"], "changed")
        other = dict(cfg, mcpServers=dict(cfg["mcpServers"], another={"command": "x"}))      # another app's own entry beside ours is no change to ours
        with open(self.cfg, "w") as f:
            json.dump(other, f)
        self.assertNotEqual(self.cursor()["state"], "changed")

    def test_a_config_that_is_a_link_is_not_written_through(self):
        target = os.path.join(self.home, "elsewhere.json")
        with open(target, "w") as f:
            f.write('{"mcpServers": {}}')
        os.symlink(target, self.cfg)
        said = mcp.install(home=self.home, claude=None, run=self.run, say=lambda l: None, only="cursor")
        self.assertIn("a link", said["cursor"])
        with open(target) as f:
            self.assertEqual(f.read(), '{"mcpServers": {}}')

    def test_what_an_app_may_read_is_set_when_it_is_registered(self):
        lines = []
        mcp.install(home=self.home, claude=None, run=self.run, say=lines.append, only="cursor")
        self.assertIn("it reads the short profile", lines[-1])
        os.remove(self.cfg)
        mcp.install(home=self.home, claude=None, run=self.run, say=lines.append, only="cursor", reads={"sources": "whatsapp"})
        self.assertIn("it reads only whatsapp", lines[-1])
        mcp.install(home=self.home, claude=None, run=self.run, say=lines.append, only="cursor")
        self.assertIn("it reads only whatsapp", lines[-1])                # registering again does not widen or narrow what the owner set


def mock_env(env):
    from unittest import mock
    return mock.patch.dict(os.environ, env)


if __name__ == "__main__":
    unittest.main()
