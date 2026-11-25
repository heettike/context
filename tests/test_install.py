import json, os, shutil, sys, tempfile, unittest
from tests import files as _f
from tests import fixture
from ctx import mcp

REPO = fixture.REPO


class Result:
    def __init__(self, code=0):
        self.returncode, self.stdout, self.stderr = code, "", ""


class Base(unittest.TestCase):
    """Everything here happens in a made-up home folder with a made-up claude CLI. Nothing real is touched."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="ctx-home-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.backups = os.path.join(fixture.HOME, "backups", "configs")
        shutil.rmtree(os.path.dirname(self.backups), ignore_errors=True)
        self.ran, self.lines, self.importable, self.claude_code = [], [], True, 0
        self.desktop = os.path.join(self.home, "Library", "Application Support", "Claude", "claude_desktop_config.json")
        self.cursor = os.path.join(self.home, ".cursor", "mcp.json")
        self.codex = os.path.join(self.home, ".codex", "config.toml")

    def run_(self, cmd, **kw):
        self.ran.append(cmd)
        if "-c" in cmd[1:4]:
            self.check_kw = kw
            return Result(0 if self.importable else 1)
        return Result(self.claude_code)

    def install(self, claude=None):
        self.lines = []
        return mcp.install(home=self.home, claude=claude, run=self.run_, say=self.lines.append)

    def put(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def read(self, path):
        with open(path) as f:
            return f.read()

    def n_backups(self):
        return len(os.listdir(self.backups)) if os.path.isdir(self.backups) else 0



class Install(Base):
    def test_nothing_installed(self):
        done = self.install()
        self.assertTrue({"claude desktop", "cursor", "claude code", "codex", "gemini cli", "vs code (copilot)", "windsurf", "zed", "opencode"} <= set(done))
        self.assertTrue(all(v == "skipped: not installed" for v in done.values()), done)
        self.assertEqual(os.listdir(self.home), [])
        self.assertEqual(self.n_backups(), 0)

    def test_one_line_per_target(self):
        done = self.install()
        self.assertEqual(self.lines, [f"{k}: {v}" for k, v in done.items()])
        self.assertEqual(len(self.lines), len(mcp.ORDER))

    def test_registers_everything_and_records_this_python(self):
        for p in (self.desktop, self.cursor):
            os.makedirs(os.path.dirname(p))
        os.makedirs(os.path.dirname(self.codex))
        done = self.install(claude="/fake/claude")
        self.assertEqual({done[k] for k in ("claude desktop", "cursor", "claude code", "codex")}, {"registered"})
        for p, app in ((self.desktop, "claude_desktop"), (self.cursor, "cursor")):      # each entry carries the app's own name, so each app has its own limits
            entry = json.loads(self.read(p))["mcpServers"]["context"]
            self.assertEqual(entry, {"command": sys.executable, "args": mcp._args(REPO), "env": {"CTX_MCP_CLIENT": app}})
            self.assertEqual((entry["args"][:3], entry["args"][4:]), (["-I", "-S", "-c"], [REPO, "mcp"]))       # isolated python, the engine named by its path
        toml = self.read(self.codex)
        self.assertIn("[mcp_servers.context]\ncommand = " + json.dumps(sys.executable), toml)
        self.assertIn("args = " + json.dumps(mcp._args(REPO)), toml)
        add = [c for c in self.ran if c[:3] == ["/fake/claude", "mcp", "add-json"]][0]
        self.assertEqual(json.loads(add[4])["command"], sys.executable)
        self.assertEqual(self.n_backups(), 0)                           # nothing existed, so nothing to back up
        self.assertEqual([f for f in os.listdir(os.path.dirname(self.codex))], ["config.toml"])      # no temp file left behind

    def test_checks_that_the_recorded_python_can_import_ctx(self):
        self.install()
        check = self.ran[0]
        self.assertEqual((check[0], check[1:4], check[-1]), (sys.executable, ["-I", "-S", "-c"], REPO))     # as the entry starts it: isolated, the engine by its path
        self.assertIn("import ctx.mcp", check[4])
        self.assertNotEqual(os.path.realpath(self.check_kw["cwd"]), os.path.realpath(self.home))            # never in the home folder
        self.assertEqual(os.listdir(self.check_kw["cwd"]), [])
        os.makedirs(os.path.dirname(self.cursor))
        self.importable = False
        done = self.install(claude="/fake/claude")
        self.assertTrue(all(v.startswith("skipped: this python cannot import ctx") for v in done.values()), done)
        self.assertFalse(os.path.exists(self.cursor))
        self.assertEqual(len(self.ran), 2)                              # the claude CLI was never called

    def test_the_real_python_really_can_import_ctx(self):
        import subprocess
        os.makedirs(os.path.dirname(self.cursor))
        done = mcp.install(home=self.home, claude=None, run=subprocess.run, say=self.lines.append)
        self.assertEqual(done["cursor"], "registered")

    def test_the_check_runs_no_ctx_planted_in_the_home_folder_or_on_pythonpath(self):
        """A program that can write the home folder plants ~/ctx/__init__.py and sets PYTHONPATH to it. The check runs
        with the app's permissions, so it must import the engine it was given and nothing else."""
        import subprocess
        pwned = os.path.join(self.home, "pwned")
        self.put(os.path.join(self.home, "ctx", "__init__.py"), "open(%r, 'w').write('ran')\nraise SystemExit(0)\n" % pwned)
        self.put(os.path.join(self.home, "ctx", "mcp.py"), "")
        os.makedirs(os.path.dirname(self.cursor))
        from unittest import mock
        with mock.patch.dict(os.environ, {"PYTHONPATH": self.home, "PYTHONSTARTUP": os.path.join(self.home, "ctx", "__init__.py")}):
            done = mcp.install(home=self.home, claude=None, run=subprocess.run, say=self.lines.append, only="cursor")
        self.assertEqual(done["cursor"], "registered")
        self.assertFalse(os.path.exists(pwned))

    def test_second_run_changes_nothing_and_backs_up_nothing(self):
        self.put(self.cursor, json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
        self.put(self.codex, 'model = "x"\n\n[mcp_servers.other]\ncommand = "y"\n')
        self.put(self.desktop, "{}")
        first = self.install()
        self.assertEqual((first["cursor"], first["codex"], first["claude desktop"]), ("registered",) * 3)
        self.assertEqual(self.n_backups(), 3)
        before = {p: (self.read(p), os.stat(p).st_mtime_ns) for p in (self.cursor, self.codex, self.desktop)}
        second = self.install()
        self.assertEqual((second["cursor"], second["codex"], second["claude desktop"]), ("already there",) * 3)
        self.assertEqual(self.n_backups(), 3)
        self.assertEqual(before, {p: (self.read(p), os.stat(p).st_mtime_ns) for p in before})

    def test_other_settings_and_servers_are_kept(self):
        self.put(self.cursor, json.dumps({"mcpServers": {"other": {"command": "x"}, "context": {"command": "/old/python3", "args": ["-m", "ctx", "mcp"], "env": {"PYTHONPATH": "/old"}}}, "theme": "dark"}))
        self.put(self.codex, 'model = "x"\n\n[mcp_servers.context]\ncommand = "old"\n\n[mcp_servers.context.env]\nPYTHONPATH = "/old"\n\n[mcp_servers.other]\ncommand = "y"\n')
        self.install()
        cfg = json.loads(self.read(self.cursor))
        self.assertEqual((cfg["theme"], cfg["mcpServers"]["other"]), ("dark", {"command": "x"}))
        self.assertEqual(cfg["mcpServers"]["context"]["command"], sys.executable)
        toml = self.read(self.codex)
        self.assertIn('model = "x"', toml)
        self.assertIn('[mcp_servers.other]\ncommand = "y"', toml)
        self.assertNotIn("old", toml)
        self.assertEqual(toml.count("[mcp_servers.context]"), 1)

    def test_mcpservers_null_is_treated_as_empty(self):
        self.put(self.cursor, json.dumps({"mcpServers": None, "x": 1}))
        self.assertEqual(self.install()["cursor"], "registered")
        self.assertEqual(json.loads(self.read(self.cursor))["x"], 1)

    def test_a_config_we_cannot_read_is_left_alone_and_the_rest_still_run(self):
        for bad in ('{"mcpServers": [1, 2]}', '{"mcpServers": "nope"}', "[1, 2]", "{not json", '"text"'):
            self.put(self.desktop, bad)
            self.put(self.cursor, bad)
            self.put(self.codex, "")
            done = self.install(claude="/fake/claude")
            self.assertTrue(done["claude desktop"].startswith("skipped: its "), (bad, done))
            self.assertTrue(done["cursor"].startswith("skipped: its "), (bad, done))
            self.assertEqual(self.read(self.desktop), bad)
            self.assertEqual((done["claude code"], done["codex"]), ("registered", "registered"), bad)   # codex was reached
            os.remove(self.codex)
        self.assertEqual(self.n_backups() <= 5, True)

    def test_an_empty_config_file_is_fine(self):
        self.put(self.cursor, "")
        self.assertEqual(self.install()["cursor"], "registered")

    def test_one_target_blowing_up_does_not_stop_the_others(self):
        self.put(self.cursor, "{}")
        os.makedirs(os.path.dirname(self.codex))
        os.chmod(os.path.dirname(self.cursor), 0o500)                   # cannot write there
        self.addCleanup(os.chmod, os.path.dirname(self.cursor), 0o700)

        def run(cmd, **kw):
            if cmd[1] == "mcp":
                raise OSError("cannot start")
            return Result(0)
        done = mcp.install(home=self.home, claude="/fake/claude", run=run, say=self.lines.append)
        self.assertEqual(done["cursor"], "skipped: could not write its config")
        self.assertTrue(done["claude code"].startswith("skipped:"))
        self.assertEqual(done["codex"], "registered")
        self.assertNotIn(self.home, " ".join(self.lines))
        self.assertEqual(self.read(self.cursor), "{}")

    def test_claude_code_already_there_and_refused(self):
        entry = {"command": sys.executable, "args": mcp._args(REPO), "env": {"CTX_MCP_CLIENT": "claude_code"}, "type": "stdio"}
        self.put(os.path.join(self.home, ".claude.json"), json.dumps({"mcpServers": {"context": entry}}))
        self.assertEqual(self.install(claude="/fake/claude")["claude code"], "already there")
        self.assertEqual(len(self.ran), 1)                              # only the import check
        self.put(os.path.join(self.home, ".claude.json"), json.dumps({"mcpServers": None}))
        self.claude_code = 3
        self.assertEqual(self.install(claude="/fake/claude")["claude code"], "skipped: claude refused it (exit 3)")
        self.assertEqual(self.read(os.path.join(self.home, ".claude.json")), '{"mcpServers": null}')     # we never write that file

    def test_claude_codes_entry_is_changed_only_when_it_is_ours(self):
        """claude code's file is written by claude's own cli. context reads it first: an entry named context that another
        program put there is left alone (as in every other app) unless --replace, and the file is backed up before claude
        changes it."""
        cfg = os.path.join(self.home, ".claude.json")
        theirs = {"mcpServers": {"context": {"command": "node", "args": ["their-server.js"], "env": {"THEIR_KEY": "made-up"}}}, "projects": {}}
        self.put(cfg, json.dumps(theirs))
        done = mcp.install(home=self.home, claude="/fake/claude", run=self.run_, say=self.lines.append, only="claude_code")
        self.assertEqual(done, {"claude code": "skipped: another server is already named context there, left alone (--replace to overwrite it)"})
        self.assertFalse([c for c in self.ran if c[:2] == ["/fake/claude", "mcp"]])          # claude's cli was not asked to change anything
        self.assertEqual(mcp.remove("claude_code", home=self.home, claude="/fake/claude", run=self.run_, say=self.lines.append),
                         {"claude code": "skipped: the entry named context there is not ours, left alone"})
        self.assertFalse([c for c in self.ran if c[:2] == ["/fake/claude", "mcp"]])
        self.assertEqual(self.n_backups(), 0)
        done = mcp.install(home=self.home, claude="/fake/claude", run=self.run_, say=self.lines.append, only="claude_code", replace=True)
        self.assertEqual(done, {"claude code": "registered"})
        self.assertEqual([c[:3] for c in self.ran if c[:2] == ["/fake/claude", "mcp"]], [["/fake/claude", "mcp", "remove"], ["/fake/claude", "mcp", "add-json"]])
        self.assertEqual(self.n_backups(), 1)                                   # a copy of claude's file as it was, before its cli changed it
        kept = os.path.join(self.backups, os.listdir(self.backups)[0])
        self.assertEqual(json.loads(self.read(kept)), theirs)
        self.assertEqual(oct(os.stat(kept).st_mode & 0o777), oct(0o600))
        self.assertTrue(os.listdir(self.backups)[0].startswith("claude_code..claude.json."))
        self.put(cfg, json.dumps({"mcpServers": {}}))                          # nothing named context: nothing to take out, nothing run
        self.ran = []
        self.assertEqual(mcp.remove("claude_code", home=self.home, claude="/fake/claude", run=self.run_, say=self.lines.append), {"claude code": "not registered"})
        self.assertEqual(self.ran, [])
        self.put(cfg, "{not json")
        self.assertEqual(mcp.install(home=self.home, claude="/fake/claude", run=self.run_, say=self.lines.append, only="claude_code"),
                         {"claude code": "skipped: its config is not plain json, left alone"})

    def test_backups_keep_the_newest_three_per_app_in_their_own_folder(self):
        old = os.path.dirname(self.backups)
        os.makedirs(old)
        for n in range(5):                                                      # copies an older build left straight in backups/
            self.put(os.path.join(old, "mcp.json.2026010%d-000000" % n), "{}")
        self.put(os.path.join(old, "people.md.20260101-000000"), "not a config")
        self.put(self.cursor, json.dumps({"mcpServers": {"other": {"command": "x", "env": {"KEY": "made-up"}}}}))
        for n in range(5):
            cfg = json.loads(self.read(self.cursor))
            cfg["n"] = n
            self.put(self.cursor, json.dumps(cfg))
            mcp.install(home=self.home, claude=None, run=self.run_, say=self.lines.append, only="cursor", replace=True)
            mcp.remove("cursor", home=self.home, claude=None, run=self.run_, say=self.lines.append)
        kept = os.listdir(self.backups)
        when = lambda k: (mcp._STAMP.match(k).group("at"), int(mcp._STAMP.match(k).group("n") or 1))
        cursor = sorted((k for k in kept if k.startswith("cursor.mcp.json.")), key=when)
        self.assertEqual([json.loads(self.read(os.path.join(self.backups, k))).get("n") for k in cursor], [3, 4, 4])     # the newest three: two copies a round
        self.assertEqual(len([k for k in kept if k.startswith("old.mcp.json.")]), 3)          # the older build's copies moved in, three kept
        self.assertEqual(sorted(os.listdir(old)), ["configs", "people.md.20260101-000000"])     # nothing that is not a config copy is touched
        self.assertEqual(oct(os.stat(self.backups).st_mode & 0o777), oct(0o700))
        for k in kept:
            self.assertEqual(oct(os.stat(os.path.join(self.backups, k)).st_mode & 0o777), oct(0o600), k)

    def test_codex_table_with_a_trailing_comment_is_replaced_once(self):
        self.put(self.codex, '[mcp_servers.context] # mine\ncommand = "old"\n')
        self.install()
        self.assertEqual(self.read(self.codex).count("[mcp_servers.context]"), 1)
        self.assertNotIn("old", self.read(self.codex))


if __name__ == "__main__":
    unittest.main()


class Targets(Base):
    """The apps added from their own docs: each writes the shape that app reads, and nothing else in its file changes."""

    def test_every_target_names_the_doc_it_was_read_from(self):
        src = _f.read(os.path.join(REPO, "ctx", "mcp.py"))
        table = src[src.index("JSON_TARGETS = ["):src.index("REMOTE = [")]
        for t in mcp.JSON_TARGETS:
            before = table[:table.index('"id": "%s"' % t["id"])]
            self.assertIn("https://", before.rsplit("{", 1)[0].rsplit("},", 1)[-1], t["id"])
        self.assertEqual(len({t["id"] for t in mcp.JSON_TARGETS}), len(mcp.JSON_TARGETS))

    def paths(self):
        return {t["id"]: os.path.join(self.home, *t["dir"].split("/"), t["file"]) for t in mcp.JSON_TARGETS}

    def test_each_app_gets_its_own_shape(self):
        P = self.paths()
        for p in P.values():
            os.makedirs(os.path.dirname(p), exist_ok=True)
        done = self.install()
        std = lambda app: {"command": sys.executable, "args": mcp._args(REPO), "env": {"CTX_MCP_CLIENT": app}}
        for i in ("gemini", "windsurf", "devin", "cline", "lmstudio", "cursor", "claude_desktop"):
            self.assertEqual(json.loads(self.read(P[i]))["mcpServers"]["context"], std(i), i)
        self.assertEqual(json.loads(self.read(P["zed"]))["context_servers"]["context"], std("zed"))
        self.assertEqual(json.loads(self.read(P["vscode"]))["mcpServers"]["context"], dict(std("vscode"), type="stdio", tools=["*"]))
        self.assertEqual(json.loads(self.read(P["opencode"]))["mcp"]["servers"]["context"],
                         {"type": "local", "command": [sys.executable] + mcp._args(REPO), "environment": {"CTX_MCP_CLIENT": "opencode"}})
        self.assertEqual({done[mcp.NAMES[i]] for i in P}, {"registered"})
        again = self.install()
        self.assertEqual({again[mcp.NAMES[i]] for i in P}, {"already there"})

    def test_vs_code_is_found_by_its_own_folder_too(self):
        os.makedirs(os.path.join(self.home, "Library", "Application Support", "Code", "User"))
        self.assertEqual(self.install()["vs code (copilot)"], "registered")
        self.assertTrue(os.path.exists(os.path.join(self.home, ".copilot", "mcp-config.json")))

    def test_the_rest_of_a_settings_file_is_kept(self):
        P = self.paths()
        self.put(P["zed"], json.dumps({"theme": "one", "context_servers": {"other": {"command": "x"}}, "vim_mode": True}))
        self.put(P["opencode"], json.dumps({"$schema": "s", "mcp": {"timeout": 5, "servers": {"other": {"type": "local", "command": ["x"]}}}}))
        self.put(P["gemini"], json.dumps({"ui": {"theme": "dark"}}))
        self.install()
        zed = json.loads(self.read(P["zed"]))
        self.assertEqual((zed["theme"], zed["vim_mode"], zed["context_servers"]["other"]), ("one", True, {"command": "x"}))
        oc = json.loads(self.read(P["opencode"]))
        self.assertEqual((oc["$schema"], oc["mcp"]["timeout"], oc["mcp"]["servers"]["other"]["command"]), ("s", 5, ["x"]))
        self.assertIn("context", oc["mcp"]["servers"])
        self.assertEqual(json.loads(self.read(P["gemini"]))["ui"], {"theme": "dark"})

    def test_a_settings_file_with_comments_is_left_alone(self):
        P = self.paths()
        text = '// my zed settings\n{\n  "theme": "one", // nice\n}\n'
        self.put(P["zed"], text)
        self.assertTrue(self.install()["zed"].startswith("skipped: its config is not plain json"))
        self.assertEqual(self.read(P["zed"]), text)
        self.assertEqual(self.n_backups(), 0)

    def test_opencode_jsonc_is_used_when_that_is_the_file(self):
        d = os.path.join(self.home, ".config", "opencode")
        self.put(os.path.join(d, "opencode.jsonc"), "{}")
        self.assertEqual(self.install()["opencode"], "registered")
        self.assertFalse(os.path.exists(os.path.join(d, "opencode.json")))
        self.assertIn("context", json.loads(self.read(os.path.join(d, "opencode.jsonc")))["mcp"]["servers"])

    def test_another_programs_entry_named_context_is_not_overwritten(self):
        other = {"mcpServers": {"context": {"command": "python3", "args": ["-m", "something", "else"], "env": {"A_KEY": "x"}}}}
        self.put(self.cursor, json.dumps(other))
        self.assertTrue(self.install()["cursor"].startswith("skipped: another server is already named context"))
        self.assertEqual(json.loads(self.read(self.cursor)), other)
        row = next(r for r in mcp.status(home=self.home, claude=None, run=self.run_) if r["id"] == "cursor")
        self.assertEqual((row["registered"], row["state"]), (False, "not registered"))
        self.assertIn("another server", row["detail"])
        self.assertEqual(mcp.remove("cursor", home=self.home, claude=None, run=self.run_, say=self.lines.append)["cursor"],
                         "skipped: the entry named context there is not ours, left alone")
        done = mcp.install(home=self.home, claude=None, run=self.run_, say=self.lines.append, only="cursor", replace=True)
        self.assertEqual(done, {"cursor": "registered"})
        self.assertEqual(self.n_backups(), 1)

    def test_install_one_target_only(self):
        for p in (self.cursor, self.desktop):
            os.makedirs(os.path.dirname(p))
        done = mcp.install(home=self.home, claude=None, run=self.run_, say=self.lines.append, only="cursor")
        self.assertEqual(done, {"cursor": "registered"})
        self.assertFalse(os.path.exists(self.desktop))
        self.assertEqual(mcp.install(home=self.home, claude=None, run=self.run_, say=self.lines.append, only="nope"), {"nope": "skipped: no such target"})

    def test_remove_takes_out_only_our_entry_with_a_backup(self):
        self.put(self.cursor, json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
        self.put(self.codex, 'model = "x"\n\n[mcp_servers.other]\ncommand = "y"\n')
        self.install()
        n = self.n_backups()
        rm = lambda i: mcp.remove(i, home=self.home, claude="/fake/claude", run=self.run_, say=self.lines.append)
        self.assertEqual(rm("cursor"), {"cursor": "removed"})
        self.assertEqual(json.loads(self.read(self.cursor)), {"mcpServers": {"other": {"command": "x"}}, "theme": "dark"})
        self.assertEqual(rm("codex"), {"codex": "removed"})
        self.assertEqual(self.read(self.codex), 'model = "x"\n\n[mcp_servers.other]\ncommand = "y"\n')
        self.assertEqual(self.n_backups(), n + 2)
        self.assertEqual(rm("cursor"), {"cursor": "not registered"})
        self.assertEqual(rm("codex"), {"codex": "not registered"})
        self.assertEqual(self.n_backups(), n + 2)
        self.assertEqual(rm("gemini"), {"gemini cli": "not registered"})
        self.assertEqual(rm("claude_code"), {"claude code": "not registered"})       # claude's file holds no entry named context
        self.assertNotIn(["/fake/claude", "mcp", "remove", "context", "-s", "user"], self.ran)
        self.put(os.path.join(self.home, ".claude.json"), json.dumps({"mcpServers": {"context": dict(mcp._entry("std", sys.executable, REPO, "claude_code"), type="stdio")}}))
        self.assertEqual(rm("claude_code"), {"claude code": "removed"})                # ours: claude's own cli takes it out, after a backup
        self.assertIn(["/fake/claude", "mcp", "remove", "context", "-s", "user"], self.ran)
        self.assertEqual(self.n_backups(), n + 3)
        self.assertEqual(rm("nope"), {"nope": "skipped: no such target"})
        self.assertEqual(rm(None), {"None": "skipped: no such target"})


class Status(Base):
    KEYS = {"id", "name", "installed", "registered", "config", "state", "detail"}

    def status(self, claude=None):
        return {r["id"]: r for r in mcp.status(home=self.home, claude=claude, run=self.run_)}

    def run_(self, cmd, **kw):
        self.ran.append(cmd)
        if cmd[1:] == ["mcp", "list"]:
            r = Result(0)
            r.stdout = self.listing
            return r
        return super().run_(cmd, **kw)

    listing = ""

    def test_shape_on_a_mac_with_nothing(self):
        rows = mcp.status(home=self.home, claude=None, run=self.run_)
        self.assertEqual([r["id"] for r in rows], mcp.ORDER + ["chatgpt", "claude_ai"])
        for r in rows:
            self.assertTrue(self.KEYS <= set(r), r)
            self.assertNotIn(self.home, json.dumps(r))
        local = [r for r in rows if not r["state"].startswith("remote")]
        self.assertEqual({r["state"] for r in local}, {"app not found"})
        self.assertTrue(all(r["config"].startswith("~/") for r in local))
        remote = [r for r in rows if r["state"].startswith("remote")]
        self.assertEqual([r["state"] for r in remote], ["remote off", "remote off"])
        self.assertIn("remote --start", remote[0]["detail"])
        self.assertIn("Add custom MCP server", remote[0]["how"])
        self.assertIn("Add custom connector", remote[1]["how"])
        self.assertEqual(os.listdir(self.home), [])                     # status writes nothing
        self.assertEqual(self.n_backups(), 0)

    def test_states(self):
        os.makedirs(os.path.dirname(self.cursor))
        os.makedirs(os.path.dirname(self.codex))
        os.makedirs(os.path.join(self.home, ".gemini"))
        self.assertEqual(self.status()["cursor"]["state"], "not registered")
        self.install()
        st = self.status()
        self.assertEqual([(st[i]["installed"], st[i]["registered"], st[i]["state"]) for i in ("cursor", "codex", "gemini", "zed")],
                         [(True, True, "registered")] * 3 + [(False, False, "app not found")])
        self.assertEqual(st["cursor"]["config"], "~/.cursor/mcp.json")

    def test_an_entry_naming_files_that_are_not_there_is_not_registered(self):
        os.makedirs(os.path.dirname(self.cursor))
        for entry in ({"command": "/no/such/python3", "args": mcp._args(REPO), "env": {"CTX_MCP_CLIENT": "cursor"}},
                      {"command": sys.executable, "args": mcp._args(self.home), "env": {"CTX_MCP_CLIENT": "cursor"}}):      # a folder with no engine in it
            self.put(self.cursor, json.dumps({"mcpServers": {"context": entry}}))
            row = self.status()["cursor"]
            self.assertEqual((row["registered"], row["ours"], row["state"]), (False, True, "not registered"))
            self.assertIn("--install cursor", row["detail"])
        self.assertEqual(self.ran, [])

    def test_status_starts_no_program_any_config_names(self):
        """Any program that can write an app's config can put its own command in an entry shaped like ours. Status used
        to run that command to see whether it imports ctx; now it only reads files, and an entry that is not the one
        context wrote there says so."""
        ran = os.path.join(self.home, "ran")
        fake = os.path.join(self.home, "bin", "python3")
        self.put(fake, "#!/bin/sh\necho started > %s\n" % ran)
        os.chmod(fake, 0o755)
        os.makedirs(os.path.dirname(self.cursor))
        os.makedirs(os.path.dirname(self.codex))
        self.install(claude="/fake/claude")
        self.put(os.path.join(self.home, ".claude.json"), json.dumps({"mcpServers": {"context": dict(mcp._entry("std", sys.executable, REPO, "claude_code"), type="stdio")}}))
        self.ran = []

        def run(cmd, **kw):
            raise AssertionError("status started a program: %s" % cmd)
        st = {r["id"]: r for r in mcp.status(home=self.home, claude="/fake/claude", run=run)}
        self.assertEqual([st[i]["state"] for i in ("cursor", "codex", "claude_code")], ["registered"] * 3)      # read from the files: claude code's own "type" is no change
        cfg = json.loads(self.read(self.cursor))
        cfg["mcpServers"]["context"]["command"] = fake                       # another program points our entry at its own code
        self.put(self.cursor, json.dumps(cfg))
        self.put(self.codex, self.read(self.codex).replace(json.dumps(sys.executable), json.dumps(fake)))
        self.put(os.path.join(self.home, ".claude.json"), json.dumps({"mcpServers": {"context": dict(mcp._entry("std", fake, REPO, "claude_code"), type="stdio")}}))
        st = {r["id"]: r for r in mcp.status(home=self.home, claude="/fake/claude", run=run)}
        for i in ("cursor", "codex", "claude_code"):
            self.assertEqual((st[i]["state"], st[i]["registered"]), ("changed", False), i)
            self.assertIn("not the one context wrote", st[i]["detail"])
        self.assertFalse(os.path.exists(ran))
        self.assertEqual(self.ran, [])
        from unittest import mock
        from ctx import llm
        with mock.patch.object(llm, "_run", side_effect=AssertionError("status ran the claude cli")):      # not even `claude auth`
            row = {r["id"]: r for r in mcp.status(home=self.home, run=run)}["claude_code"]
        self.assertIn(row["state"], ("registered", "changed", "app not found"))
        src = _f.read(os.path.join(REPO, "ctx", "mcp.py"))
        body = src[src.index("def status("):src.index("    rows = [out[i] for i in ORDER]")]
        self.assertNotIn("run(", body.replace("def status(home=None, claude=\"\", run=None):", ""))     # and nothing in it calls a program
        self.assertNotIn('"list"', body)

    def test_a_broken_config_is_said_not_raised(self):
        self.put(self.cursor, "{nope")
        row = self.status()["cursor"]
        self.assertEqual(row["state"], "not registered")
        self.assertIn("not plain json", row["detail"])
