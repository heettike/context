"""What leaves the machine when the engine works: nothing. A session (collect, a tick, counts, the tools another app
calls, an answer with a made-up model CLI) is run inside the macos sandbox with every kind of network denied, and with
a hook that writes down each socket the engine itself tries to open and each program it starts. The session must
finish as usual, and the list of sockets must be empty. Made-up data only."""
import json, os, shutil, subprocess, sys, tempfile, time, unittest
from tests import fixture
from tests.test_answer_stream import FAKE

DENY = "(version 1)(allow default)(deny network*)"
HOOK = r'''
import json, os, runpy, sys
log = os.environ["CTX_AUDIT_LOG"]
def hook(event, args):
    if event in ("socket.connect", "socket.bind", "socket.getaddrinfo", "socket.gethostbyname", "socket.sendto", "urllib.Request"):
        what = repr(args[1:])[:200]
    elif event == "subprocess.Popen":
        what = os.path.basename(str(args[0]))
    else:
        return
    with open(log, "a") as f:
        f.write(json.dumps([event, what]) + "\n")
sys.addaudithook(hook)
sys.argv = ["ctx"] + sys.argv[1:]
runpy.run_module("ctx", run_name="__main__")
'''


@unittest.skipUnless(sys.platform == "darwin" and os.access("/usr/bin/sandbox-exec", os.X_OK), "the sandbox is a macos thing")
class Session(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ctx-nonet-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.home = os.path.join(self.dir, "home")
        shutil.copytree(fixture.HOME, self.home, ignore=shutil.ignore_patterns("cache", "*.log", "user-home", "bridge"))       # and never another test's browser helper
        with open(os.path.join(self.home, "model.json"), "w") as f:
            json.dump({"using": "claude", "at": time.time()}, f)
        user = os.path.join(self.dir, "user")
        os.makedirs(os.path.join(user, ".local", "bin"))
        cli = os.path.join(user, ".local", "bin", "claude")
        with open(cli, "w") as f:
            f.write(FAKE % sys.executable)
        os.chmod(cli, 0o755)
        self.log = os.path.join(self.dir, "audit.log")
        self.env = dict(os.environ, CTX_HOME=self.home, PYTHONPATH=fixture.REPO, HOME=user, FAKE_PID=os.path.join(self.dir, "pid"), CTX_MODEL="claude",
                        CTX_CLI_PATH=os.path.dirname(cli), CTX_AUDIT_LOG=self.log)

    def ctx(self, *args, stdin=""):
        return subprocess.run(["/usr/bin/sandbox-exec", "-p", DENY, sys.executable, "-c", HOOK] + list(args), cwd=fixture.REPO, env=self.env,
                              input=stdin, capture_output=True, text=True, timeout=170)

    def seen(self):
        try:
            with open(self.log) as f:
                return [json.loads(l) for l in f]
        except OSError:
            return []

    def test_the_sandbox_really_denies(self):
        r = subprocess.run(["/usr/bin/sandbox-exec", "-p", DENY, sys.executable, "-c", "import socket; socket.create_connection(('127.0.0.1', 9), 2)"],
                           capture_output=True, text=True, timeout=30)
        self.assertIn("PermissionError", r.stderr)

    def test_a_working_session_opens_no_socket(self):
        calls = "".join(json.dumps(m) + "\n" for m in (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search", "arguments": {"query": "pottery"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "about_me", "arguments": {}}}))
        ran = {}
        for name, args, stdin in (("collect", ["collect"], ""), ("tick", ["tick", "fast"], ""), ("facts", ["facts"], ""), ("people", ["people", "--json"], ""),
                                  ("schedule", ["schedule"], ""), ("mcp", ["mcp"], calls),
                                  ("answer", ["answer", "what", "is", "the", "kettle", "fund", "--stream"], "")):
            r = self.ctx(*args, stdin=stdin)
            ran[name] = r
            self.assertEqual(r.returncode, 0, (name, r.stderr[-400:]))
        self.assertEqual(len(ran["mcp"].stdout.strip().splitlines()), 4)
        events = [json.loads(l) for l in ran["answer"].stdout.splitlines()]
        if not (events and "error" in events[-1] and "signed in" in str(events[-1]["error"])):      # the made-up cli was found: it answered, with no network
            self.assertTrue(any("done" in e for e in events), ran["answer"].stdout[-300:])
        seen = self.seen()
        sockets = [e for e in seen if e[0] != "subprocess.Popen"]
        self.assertEqual(sockets, [], sockets[:5])                       # the engine itself asked for no socket, no name lookup, nothing
        started = sorted({e[1] for e in seen if e[0] == "subprocess.Popen"})
        for prog in started:                                            # and it started only these: itself, the model cli, macos's own tools
            self.assertIn(prog.split(".")[0], ("python", "python3", "claude", "osascript", "git", "ps", "mdfind", "pgrep", "sandbox-exec", "xcode-select",
                                               "swiftc", "embed", "media", "textutil", "pmset", "sqlite3", "defaults", "plutil", "codex"), started)


if __name__ == "__main__":
    unittest.main()
