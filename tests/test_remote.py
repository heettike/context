import time
from tests import files as _f
import http.client, json, os, re, stat, subprocess, sys, threading, time, unittest
from unittest import mock
from tests import fixture
from ctx import mcp, paths, remote, settings

DEFAULT = ["about_me", "search", "person", "facts", "open_loops", "sources"]


def clean():
    for f in (remote.CONF, remote.RUN, remote.LOG, remote.TUNNEL_LOG, settings.FILE):
        if os.path.exists(f):
            os.remove(f)


class Server(unittest.TestCase):
    """The real HTTP server on a free port of 127.0.0.1, over the made-up archive."""

    def setUp(self):
        clean()
        self.addCleanup(clean)
        self.gate = remote.Gate()
        self.srv = remote.make_server(0, self.gate)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.secret = remote.secret()

    def send(self, method="POST", path=None, body=None, headers=None, raw=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        h.update(headers or {})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        c.request(method, path if path is not None else "/mcp/" + self.secret, body=data, headers=h)
        r = c.getresponse()
        text = r.read().decode()
        c.close()
        return r.status, dict((k.lower(), v) for k, v in r.getheaders()), (json.loads(text) if text else None)

    def rpc(self, i, method, params=None, **kw):
        return self.send(body={"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}, **kw)

    def tool(self, name, args=None, **kw):
        return self.rpc(7, "tools/call", {"name": name, "arguments": args or {}}, **kw)

    def log(self, want=0):
        """The call log. A call is logged just after its reply is sent, so wait a moment for the lines that are due."""
        rows = []
        for _ in range(100):
            rows = [json.loads(l) for l in _f.lines(remote.LOG)] if os.path.exists(remote.LOG) else []
            if len(rows) >= want:
                break
            time.sleep(0.05)
        return rows


class Protocol(Server):
    def test_bound_to_this_mac_only(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")
        src = _f.read(os.path.join(fixture.REPO, "ctx", "remote.py"))
        self.assertNotIn("0.0.0.0", src)
        self.assertEqual(src.count("ThreadingHTTPServer(("), 1)
        self.assertIn('ThreadingHTTPServer(("127.0.0.1"', src)

    def test_initialize_then_list_then_call(self):
        code, head, out = self.rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "Some Client", "version": "1"}})
        self.assertEqual((code, head["content-type"], out["id"]), (200, "application/json", 1))
        self.assertEqual(out["result"]["protocolVersion"], "2025-06-18")
        session = head["mcp-session-id"]
        self.assertRegex(session, r"^[\x21-\x7e]{20,}$")
        code, _, out = self.send(body={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers={"Mcp-Session-Id": session})
        self.assertEqual((code, out), (202, None))
        code, _, out = self.rpc(2, "tools/list", headers={"Mcp-Session-Id": session, "MCP-Protocol-Version": "2025-06-18"})
        self.assertEqual(sorted(t["name"] for t in out["result"]["tools"]), sorted("context_" + n for n in DEFAULT))
        self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in out["result"]["tools"]))
        code, _, out = self.tool("search", {"query": "kettle fund"}, headers={"Mcp-Session-Id": session})
        self.assertEqual(code, 200)
        self.assertIn("W1", out["result"]["content"][0]["text"])
        self.assertEqual(self.log()[-1]["client"], "Some Client")

    def test_every_allowed_tool_answers(self):
        for name, args in (("about_me", {}), ("search", {"query": "pottery"}), ("person", {"name": "ada"}), ("facts", {}), ("open_loops", {}), ("sources", {})):
            code, _, out = self.tool(name, args)
            self.assertEqual(code, 200, name)
            res = out["result"]
            self.assertEqual((res["isError"], res["content"][0]["type"]), (False, "text"), name)
            self.assertLessEqual(len(res["content"][0]["text"]), remote.MAX_OUT + 100)

    def test_a_tool_off_the_allowlist_does_not_exist(self):
        code, _, out = self.tool("page", {"name": "people"})
        self.assertEqual((code, out["error"]["code"]), (200, -32602))
        settings.set_("remote_tools=search,page")
        code, _, out = self.rpc(2, "tools/list")
        self.assertEqual([t["name"] for t in out["result"]["tools"]], ["context_page", "context_search"])
        self.assertIn("ada", self.tool("page", {"name": "people"})[2]["result"]["content"][0]["text"])
        self.assertTrue(self.tool("page", {"name": "core"})[2]["result"]["isError"])          # still only the distilled pages
        self.assertEqual(self.tool("facts")[2]["error"]["code"], -32602)

    def test_numbers_and_addresses_are_masked_even_when_asked_for(self):
        for args in ({"query": "samovar"}, {"query": "samovar; 415 555 0199"}, {"query": "teapot@example.com; samovar"}):
            text = self.tool("search", args)[2]["result"]["content"][0]["text"]
            self.assertNotIn("555", text, args)
            self.assertNotIn("example.com", text)
        card = self.tool("person", {"name": "ada"})[2]["result"]["content"][0]["text"]
        self.assertNotIn("555", card)
        self.assertNotIn("bab@", card)

    def test_replies_are_capped(self):
        with mock.patch.object(remote, "MAX_OUT", 500):
            text = self.tool("search", {"query": "pottery", "limit": 50})[2]["result"]["content"][0]["text"]
        self.assertLessEqual(len(text), 600)
        self.assertIn("cut here", text)

    def test_ping_unknown_method_and_notifications(self):
        self.assertEqual(self.rpc(3, "ping")[2], {"jsonrpc": "2.0", "id": 3, "result": {}})
        self.assertEqual(self.rpc(4, "resources/list")[2]["error"]["code"], -32601)
        self.assertEqual(self.send(body={"jsonrpc": "2.0", "id": 1, "result": {}})[0], 202)

    def test_bad_bodies(self):
        self.assertEqual(self.send(raw=b"{not json")[0::2], (400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}))
        self.assertEqual(self.send(raw=b"\xff\xfe")[0], 400)
        self.assertEqual(self.send(body=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}])[0], 400)
        self.assertEqual(self.send(body="text")[0], 400)
        self.assertEqual(self.rpc(1, "ping", headers={"MCP-Protocol-Version": "1999-01-01"})[0], 400)

    def test_oversized_body_is_refused_unread(self):
        code, _, out = self.send(raw=b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":"' + b"a" * (remote.MAX_BODY + 10) + b'"}}')
        self.assertEqual(code, 413)
        self.assertEqual(self.rpc(1, "ping")[0], 200)                    # and the server is still there

    def test_only_post(self):
        for method in ("GET", "DELETE", "PUT", "PATCH", "OPTIONS"):
            code, head, _ = self.send(method)
            self.assertEqual((code, head.get("allow")), (405, "POST"), method)
        self.assertEqual(self.send("HEAD")[0], 405)

    def test_a_browser_page_elsewhere_is_refused(self):
        self.assertEqual(self.rpc(1, "ping", headers={"Origin": "https://evil.example"})[0], 403)
        for ok in ("https://claude.ai", "https://chatgpt.com", "http://127.0.0.1:5000"):
            self.assertEqual(self.rpc(1, "ping", headers={"Origin": ok})[0], 200, ok)


class Secret(Server):
    def test_the_secret_is_long_private_and_in_the_path(self):
        self.assertRegex(self.secret, r"^[A-Za-z0-9_-]{43,}$")
        self.assertEqual(stat.S_IMODE(os.stat(remote.CONF).st_mode), 0o600)
        self.assertEqual(remote.secret(), self.secret)                   # stable until rotated

    def test_wrong_or_missing_secret_is_a_bare_404(self):
        for method in ("POST", "GET", "DELETE"):
            for path in ("/", "/mcp", "/mcp/", "/mcp/" + "x" * 43, "/mcp/" + self.secret[:-1], "/mcp/" + self.secret + "x", "/mcp/" + self.secret + "/more",
                         "/" + self.secret, "/.well-known/oauth-protected-resource", "/.well-known/oauth-authorization-server", "/register", "/favicon.ico"):
                code, head, out = self.send(method, path, body={"jsonrpc": "2.0", "id": 1, "method": "ping"} if method == "POST" else None)
                self.assertEqual((code, out), (404, None), (method, path))
                self.assertNotIn("www-authenticate", head)
        self.assertEqual(self.log(), [])

    def test_bearer_header_on_the_bare_path(self):
        self.assertEqual(self.rpc(1, "ping", path="/mcp", headers={"Authorization": "Bearer " + self.secret})[0], 200)
        for bad in ("Bearer " + self.secret[:-1], "bearer " + self.secret, self.secret, "Basic " + self.secret, "Bearer "):
            self.assertEqual(self.rpc(1, "ping", path="/mcp", headers={"Authorization": bad})[0], 404, bad[:8])

    def test_compared_in_constant_time(self):
        with mock.patch.object(remote.hmac, "compare_digest", wraps=remote.hmac.compare_digest) as cmp:
            self.rpc(1, "ping", path="/mcp/" + "y" * 43)
        self.assertTrue(cmp.called)

    def test_rotate_kills_the_old_url_at_once(self):
        old = self.secret
        time.sleep(0.01)
        new = remote.rotate()
        self.assertNotEqual(new, old)
        self.assertEqual(self.rpc(1, "ping", path="/mcp/" + old)[0], 404)
        self.assertEqual(self.rpc(1, "ping", path="/mcp/" + new)[0], 200)
        self.assertEqual(stat.S_IMODE(os.stat(remote.CONF).st_mode), 0o600)

    def test_the_secret_is_in_no_log_error_or_status(self):
        import io
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            self.tool("search", {"query": "kettle"})
            self.send(raw=b"{bad")
            self.rpc(1, "ping", path="/mcp/" + self.secret + "?x=1&y=" + "z" * 10)
            self.send("GET")
            self.tool("nope")
        blob = err.getvalue() + _f.read(remote.LOG) + json.dumps(remote.status()) + json.dumps(mcp.status(home=fixture.HOME, claude=None, run=lambda *a, **k: None))
        self.assertNotIn(self.secret, blob)
        self.assertNotIn(self.secret[:12], blob)
        self.assertEqual(err.getvalue(), "")


class Limits(Server):
    def test_per_minute_cap(self):
        self.gate.per_minute = 3
        codes = [self.tool("sources")[0] for _ in range(5)]
        self.assertEqual(codes, [200, 200, 200, 429, 429])
        code, head, out = self.tool("sources")
        self.assertEqual((code, head["retry-after"], out["error"]["code"]), (429, "60", -32000))
        self.assertEqual(self.rpc(1, "ping")[0], 200)                    # only tool calls are counted
        self.assertEqual(self.rpc(1, "tools/list")[0], 200)

    def test_per_day_cap(self):
        self.gate.per_day = 2
        self.assertEqual([self.tool("sources")[0] for _ in range(3)], [200, 200, 429])
        self.assertEqual(self.tool("sources")[1]["retry-after"], "3600")

    def test_the_day_count_survives_a_restart(self):
        for _ in range(3):
            self.tool("sources")
        for _ in range(40):         # the call is logged just after its reply is sent: give a slow machine a moment
            if remote.Gate().today == 3:
                break
            time.sleep(0.05)
        self.assertEqual(remote.Gate().today, 3)

    def test_concurrent_calls(self):
        got, lock = [], threading.Lock()

        def one(n):
            code, _, out = self.tool("search", {"query": "pottery" if n % 2 else "kettle"})
            with lock:
                got.append((code, out))
        ts = [threading.Thread(target=one, args=(n,)) for n in range(12)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len(got), 12)
        self.assertTrue({c for c, _ in got} <= {200, 429})
        ok = [o for c, o in got if c == 200]
        self.assertGreaterEqual(len(ok), 4)
        self.assertTrue(all(o["id"] == 7 and "matched" in o["result"]["content"][0]["text"] for o in ok))
        self.assertEqual(len(self.log(12)), 12)

    def test_the_log_holds_sizes_never_content(self):
        self.tool("search", {"query": "kettle fund secretword", "limit": 5})
        self.tool("person", {"name": "ada lovelace"})
        rows = self.log(2)
        self.assertEqual([(r["tool"], r["status"]) for r in rows], [("search", 200), ("person", 200)])
        self.assertEqual(rows[0]["args"], {"query": 22, "limit": 1})
        self.assertGreater(rows[0]["bytes_out"], 50)
        blob = _f.read(remote.LOG)
        for word in ("kettle", "secretword", "ada", "lovelace"):
            self.assertNotIn(word, blob)
        self.assertEqual(set(rows[0]), {"tool", "args", "bytes_out", "client", "status", "at"})


class Running(unittest.TestCase):
    """Start, stop and status with the server process and the tunnel program both made up. Nothing is exposed."""

    def setUp(self):
        clean()
        self.addCleanup(clean)
        self.started = []

    def popen(self, tunnel_says=""):
        test = self

        class P:
            def __init__(self, cmd, **kw):
                test.started.append((cmd, kw))
                self.pid = 40000 + len(test.started)
                if "stdout" in kw and hasattr(kw["stdout"], "write") and tunnel_says:
                    kw["stdout"].write(tunnel_says)
                    kw["stdout"].flush()

            def poll(self):
                return None

            def terminate(self):
                test.started.append(("terminated", self.pid))
        return P

    def test_no_tunnel_program_gives_the_install_line_and_leaves_nothing_running(self):
        out = remote.start(which=lambda n: None, popen=self.popen(), sleep=lambda s: None, busy=lambda p: False)
        self.assertEqual(out, {"error": remote.INSTALL})
        self.assertIn("cloudflared", out["error"])
        self.assertNotIn("ngrok", out["error"])                          # it names only the programs it can drive
        self.assertNotIn("brew", out["error"])                           # it names what is missing, and tells nobody how to install anything
        self.assertIn(("terminated", 40001), self.started)
        self.assertFalse(os.path.exists(remote.RUN))
        self.assertFalse(remote.status()["running"])

    def test_cloudflared_is_preferred_and_the_url_carries_the_secret(self):
        says = "2026 INF |  https://quiet-river-demo.trycloudflare.com  |\n"
        with mock.patch.object(remote, "_alive", lambda pid: True):
            out = remote.start(port=47999, which=lambda n: "/fake/" + n, popen=self.popen(says), sleep=lambda s: None, busy=lambda p: False)
            self.assertEqual(out, {"url": "https://quiet-river-demo.trycloudflare.com/mcp/" + remote.secret(), "tunnel": "cloudflared", "pid": 40001})
            server, tunnel = self.started[0][0], self.started[1][0]
            self.assertEqual((server[1:3], server[-4:]), (["-I", "-c"], ["mcp", "--http", "--port", "47999"]))       # isolated python, then the command
            self.assertEqual(tunnel, ["/fake/cloudflared", "tunnel", "--url", "http://127.0.0.1:47999"])
            st = remote.status()
            self.assertEqual((st["running"], st["tunnel"], st["host"]), (True, "cloudflared", "quiet-river-demo.trycloudflare.com"))
            self.assertNotIn(remote.secret(), json.dumps(st) + _f.read(remote.RUN) + _f.read(remote.TUNNEL_LOG))
            self.assertEqual(stat.S_IMODE(os.stat(remote.RUN).st_mode), 0o600)
            self.assertEqual(remote.url()["url"], out["url"])
            rows = {r["id"]: r for r in mcp.status(home=fixture.HOME, claude=None, run=lambda *a, **k: None)}
            self.assertEqual((rows["chatgpt"]["state"], rows["claude_ai"]["state"]), ("remote on", "remote on"))
            self.assertIn("quiet-river-demo.trycloudflare.com", rows["claude_ai"]["detail"])
            self.assertIn("No sign in", rows["claude_ai"]["detail"])
            self.assertIn("No authentication", rows["chatgpt"]["detail"])
            self.assertNotIn(remote.secret(), json.dumps(rows))
            self.assertIn("already running", remote.start(which=lambda n: "/fake/" + n, popen=self.popen(says), busy=lambda p: False)["error"])

    def test_tailscale_when_there_is_no_cloudflared_and_never_in_the_background(self):
        with mock.patch.object(remote, "_alive", lambda pid: True):
            out = remote.start(port=47998, which=lambda n: "/fake/tailscale" if n == "tailscale" else None,
                               popen=self.popen("Available on the internet:\nhttps://mac.tail1234.ts.net\n"), sleep=lambda s: None, busy=lambda p: False)
        self.assertEqual((out["tunnel"], out["url"].split("/mcp/")[0]), ("tailscale", "https://mac.tail1234.ts.net"))
        self.assertEqual(self.started[1][0], ["/fake/tailscale", "funnel", "--https=443", "47998"])
        self.assertNotIn("--bg", self.started[1][0])

    def test_a_tunnel_that_gives_no_address_is_stopped(self):
        out = remote.start(which=lambda n: "/fake/" + n, popen=self.popen("starting...\n"), sleep=lambda s: None, wait=2, busy=lambda p: False)
        self.assertIn("gave no public address", out["error"])
        self.assertEqual([s for s in self.started if s[0] == "terminated"], [("terminated", 40002), ("terminated", 40001)])
        self.assertFalse(os.path.exists(remote.RUN))

    def test_the_port_is_this_installs_own_picked_at_random_and_kept(self):
        self.assertFalse(hasattr(remote, "PORT"))                        # no fixed number to go looking at
        self.assertNotIn("47613", _f.read(remote.__file__))
        p = remote.stored_port()
        self.assertTrue(49152 <= p < 65536)
        self.assertEqual(remote.stored_port(), p)
        s = remote.secret()
        remote.rotate()                                                  # a new secret keeps the port
        self.assertEqual((remote.stored_port(), remote.secret() != s), (p, True))
        self.assertEqual(stat.S_IMODE(os.stat(remote.CONF).st_mode), 0o600)
        remote.start(which=lambda n: None, popen=self.popen(), sleep=lambda s: None, busy=lambda q: False)
        self.assertEqual(self.started[0][0][-4:], ["mcp", "--http", "--port", str(p)])

    def test_nothing_starts_beside_another_program_listening_on_its_port(self):
        import socket
        other = socket.socket()
        other.bind(("127.0.0.1", 0))
        other.listen(1)
        self.addCleanup(other.close)
        port = other.getsockname()[1]
        self.assertTrue(remote.taken(port))
        for local in (False, True):
            out = remote.start(port=port, local=local, which=lambda n: "/fake/" + n, popen=self.popen("https://x.trycloudflare.com\n"), sleep=lambda s: None)
            self.assertEqual(out, {"error": remote.TAKEN % (port, port)})
        self.assertEqual(self.started, [])                               # no server, no tunnel, and the secret went nowhere
        self.assertFalse(os.path.exists(remote.RUN))
        other.close()
        self.assertFalse(remote.taken(port))

    def test_stop_kills_only_what_we_started(self):
        remote._write_private(remote.RUN, {"pid": 111, "tunnel_pid": 222, "tunnel": "cloudflared", "port": 1, "host": "h"})
        killed = []
        with mock.patch.object(remote, "_alive", lambda pid: True), mock.patch.object(remote, "_is", lambda pid, word: pid == 222):
            out = remote.stop(kill=lambda pid, sig: killed.append(pid))
        self.assertEqual(killed, [222])                                  # pid 111 is some other program now: left alone
        self.assertEqual(out, {"stopped": True, "was_running": True})
        self.assertFalse(os.path.exists(remote.RUN))
        self.assertEqual(remote.stop(), {"stopped": False, "was_running": False})

    def test_status_when_off(self):
        st = remote.status()
        self.assertEqual((st["running"], st["tunnel"], st["host"], st["calls_today"], st["autostart"], st["has_secret"]), (False, "", "", 0, False, False))
        self.assertEqual(st["tools"], DEFAULT)
        self.assertFalse(os.path.exists(remote.CONF))                    # looking does not make a secret
        self.assertIn("error", remote.url())

    def test_nothing_starts_it_by_itself(self):
        for name in ("schedule.py", "settings.py", "mcp.py", "collect.py", "__init__.py"):
            src = _f.read(os.path.join(fixture.REPO, "ctx", name))
            self.assertNotRegex(src, r"remote\.(start|serve|open_tunnel)\(", name)

    def test_the_command_serves_on_loopback(self):
        env = dict(os.environ, CTX_HOME=fixture.HOME, PYTHONPATH=fixture.REPO)
        p = subprocess.Popen([sys.executable, "-m", "ctx", "mcp", "--http", "--port", "0"], cwd=fixture.REPO, env=env, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            line = p.stderr.readline()
            port = int(re.search(r"127\.0\.0\.1:(\d+)", line).group(1))
            self.assertNotIn(remote.secret(), line)
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request("POST", "/mcp/" + remote.secret(), body=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}), headers={"Content-Type": "application/json"})
            self.assertEqual(c.getresponse().status, 200)
        finally:
            p.terminate()
            p.wait(10)
            p.stderr.close()
            p.stdout.close()


if __name__ == "__main__":
    unittest.main()
