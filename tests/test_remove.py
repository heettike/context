import json, os, plistlib, shutil, signal, sys, tempfile, unittest
from unittest import mock
from tests import fixture
from ctx import bridge, mcp, paths, remove

os.environ[remove.MARKER] = "1"      # from here on no removal can run against the real home, whatever a test gets wrong


class Result:
    def __init__(self, code=0):
        self.returncode, self.stdout, self.stderr = code, "", ""


def put(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return path


def build(home):
    """A made-up home with everything context can leave behind, plus things that are not ours. Every name is invented."""
    v2 = os.path.join(home, ".context", "v2")
    j = lambda *a: os.path.join(*a)
    put(j(v2, "messages.jsonl"), '{"id": "m1", "text": "tea at four"}\n' * 40)
    put(j(v2, ".closed"), "")                           # the marker context writes in an archive it has used
    put(j(v2, "sessions.jsonl"), "{}\n" * 10)
    put(j(v2, "status.json"), "{}")
    put(j(v2, "memory", "cards.jsonl"), "{}\n" * 5)
    put(j(v2, "imports", "export.zip"), "z" * 3000)
    put(j(v2, "cache", "semantic", "vectors.bin"), "v" * 5000)
    put(j(v2, "cache", "words", "index.bin"), "w" * 2000)
    put(j(v2, "cache", "icons", "app.png"), "i" * 700)
    for n in ("api.log", "remote.log", "remote.tunnel.log", "bad_replies.log", "ledger.jsonl"):
        put(j(v2, n), "line\n" * 20)
    put(j(v2, "backups", "mcp.json.20260101-000000"), "{}")
    put(j(v2, "custom", "reader.json"), "{}")
    put(j(v2, "chats", "one.json"), "{}")
    put(j(v2, "media", "notes.jsonl"), "{}")
    put(j(v2, "bin", "embed"), "b" * 900)
    put(j(v2, "bridge", "host.sh"), "#!/bin/sh\n")
    put(j(v2, "bridge", "jobs", "1.json"), "{}")
    put(j(v2, "repo"), "/made/up/repo\n")
    put(j(v2, "app.json"), "{}")
    put(j(v2, "api.json"), json.dumps({"keys": {"one": {"hash": "aa"}, "two": {"hash": "bb"}}}))
    put(j(v2, "remote.json"), json.dumps({"secret": "s" * 43}))
    put(j(v2, "api.run.json"), json.dumps({"pid": 111, "port": 1}))
    put(j(v2, "remote.run.json"), json.dumps({"pid": 222, "tunnel": "cloudflared", "tunnel_pid": 333}))
    put(j(v2, "telegram.session"), "t" * 400)
    put(j(home, ".context", "derived", "profile", "core.md"), "core")
    put(j(home, "Applications", "context.app", "Contents", "MacOS", "context"), "a" * 4000)
    put(j(home, "Applications", "context.app", "Contents", "Info.plist"),
        '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict><key>CFBundleIdentifier</key><string>so.context.app</string></dict></plist>\n')
    lib = j(home, "Library")
    put(j(lib, "Preferences", "so.context.app.plist"), "p")
    put(j(lib, "Preferences", "com.other.app.plist"), "p")
    put(j(lib, "Caches", "so.context.app", "c"), "c" * 100)
    put(j(lib, "HTTPStorages", "so.context.app", "h"), "h")
    put(j(lib, "HTTPStorages", "so.context.app.binarycookies"), "h")
    put(j(lib, "Saved Application State", "so.context.app.savedState", "w"), "w")
    with open(put(j(lib, "LaunchAgents", "so.context.tick.plist")), "wb") as f:
        plistlib.dump({"Label": "so.context.tick"}, f)
    with open(put(j(lib, "LaunchAgents", "com.other.job.plist")), "wb") as f:
        plistlib.dump({"Label": "com.other.job"}, f)
    with open(put(j(lib, "LaunchAgents", "com.also.contextmenu.plist")), "wb") as f:      # holds "so.context" inside its name: someone else's
        plistlib.dump({"Label": "com.also.contextmenu"}, f)
    with open(put(j(lib, "LaunchAgents", "so.context.app.helper.plist")), "wb") as f:     # starts like ours, is not one of ours
        plistlib.dump({"Label": "so.context.app.helper.of.someone"}, f)
    ours = mcp._entry("std", sys.executable, fixture.REPO)
    put(j(home, ".cursor", "mcp.json"), json.dumps({"mcpServers": {"context": ours, "other": {"command": "x"}}, "theme": "dark"}))
    put(j(lib, "Application Support", "Claude", "claude_desktop_config.json"), json.dumps({"mcpServers": {"context": {"command": "someone-elses"}}}))
    put(j(home, ".codex", "config.toml"), 'model = "m"\n\n[mcp_servers.context]\ncommand = "/usr/bin/python3"\nargs = ["-m", "ctx", "mcp"]\n\n'
                                           '[mcp_servers.context.env]\nPYTHONPATH = "/made/up/repo"\n')
    put(j(home, ".claude.json"), json.dumps({"mcpServers": {"context": ours}}))
    host = {"name": bridge.NAME, "path": j(v2, "bridge", "host.sh"), "type": "stdio"}
    put(j(lib, "Application Support", "Google", "Chrome", "NativeMessagingHosts", bridge.NAME + ".json"), json.dumps(host))
    put(j(lib, "Application Support", "Arc", "User Data", "NativeMessagingHosts", bridge.NAME + ".json"), json.dumps(dict(host, name="so.someone.else")))
    return v2


def read(path):
    with open(path) as f:
        return f.read()


def load(path):
    return json.loads(read(path))


def tree(root):
    out = {}
    for d, dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            with open(p, "rb") as h:
                out[os.path.relpath(p, root)] = h.read()
    return out


COMMANDS = {111: "/usr/bin/python3 -m ctx api --serve --port 1", 222: "/usr/bin/python3 -m ctx mcp --http --port 2", 333: "cloudflared tunnel --url http://localhost:2"}


class Base(unittest.TestCase):
    def setUp(self):
        self.home = os.path.realpath(tempfile.mkdtemp(prefix="ctx-remove-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.v2 = build(self.home)
        p = mock.patch.object(paths, "HOME", self.v2)      # mcp keeps its backups under paths.HOME
        p.start()
        self.addCleanup(p.stop)
        self.P = remove.places(home=self.home, ctx_home=self.v2)
        self.killed, self.ran, self.said, self.quits, self.commands = [], [], [], [], dict(COMMANDS)
        self.trash = os.path.join(self.home, ".Trash")

    def run_(self, cmd, **kw):
        self.ran.append(cmd)
        if cmd[:3] == ["/fake/claude", "mcp", "remove"]:      # what the real cli does: drop the entry from its own file
            p = os.path.join(self.home, ".claude.json")
            d = load(p)
            d["mcpServers"].pop("context", None)
            put(p, json.dumps(d))
        return Result(0)

    def go(self, mode, only=(), **kw):
        kw.setdefault("claude", "/fake/claude")
        return remove.run(mode, only, P=self.P, say=self.said.append, kill=lambda pid, sig: self.killed.append((pid, sig)), command=lambda pid: self.commands.get(pid, ""),
                          quit_app=lambda: self.quits.append(1) or "quit", run=self.run_, trash_cmd="", sleep=lambda s: None, **kw)

    def by_id(self):
        return {it["id"]: it for it in remove.listing(self.P, lambda pid: self.commands.get(pid, ""))["items"]}

    def has(self, *parts):
        return os.path.lexists(os.path.join(self.home, *parts))

    def in_trash(self):
        return {n for d, dirs, files in os.walk(self.trash) for n in dirs + files}


class Places(Base):
    def test_a_made_up_home_names_nothing_outside_it(self):
        for p in [self.P["home"], self.P["ctx_home"], self.P["browser_data"]] + self.P["apps"]:
            self.assertTrue(p.startswith(self.home), p)

    def test_this_mac_by_default(self):
        P = remove.places()
        self.assertEqual(P["ctx_home"], paths.HOME)
        self.assertEqual(P["browser_data"], os.path.abspath(bridge.APPDATA))
        self.assertNotIn("/Applications", P["apps"])          # "~" is made up in the tests, so the real /Applications is not named
        with mock.patch.object(remove, "real_home", return_value=os.path.expanduser("~")):
            self.assertEqual(remove.places()["apps"], ["/Applications", os.path.join(os.path.expanduser("~"), "Applications")])


class Listing(Base):
    def test_changes_nothing(self):
        before = tree(self.home)
        d = remove.listing(self.P, lambda pid: self.commands.get(pid, ""))
        remove.text(d)
        self.assertEqual(remove.main([], P=self.P, out=self.said.append, command=lambda pid: ""), 0)
        self.assertEqual(remove.main(["--json"], P=self.P, out=self.said.append, command=lambda pid: ""), 0)
        self.assertEqual(tree(self.home), before)
        self.assertFalse(os.path.exists(self.trash))
        self.assertIs(d["changed"], False)
        self.assertEqual(self.killed, [])

    def test_sizes_and_places(self):
        it = self.by_id()
        self.assertEqual((it["imports"]["bytes"], it["imports"]["files"]), (3000, 1))
        self.assertEqual(it["index-meaning"]["bytes"], 5000)
        self.assertEqual(it["index-words"]["bytes"], 2000)
        self.assertEqual(it["caches"]["bytes"], 700)
        self.assertEqual(it["tools"]["bytes"], 900)
        self.assertEqual(it["logs"]["files"], 5)
        self.assertEqual(it["app"]["where"], ["~/Applications/context.app"])
        self.assertEqual(it["app"]["bytes"], 4000 + os.path.getsize(os.path.join(self.home, "Applications", "context.app", "Contents", "Info.plist")))
        self.assertEqual(it["imports"]["where"], ["~/.context/v2/imports"])
        self.assertEqual(len(it["app-caches"]["where"]), 4)
        self.assertEqual(it["launch-agents"]["where"], ["~/Library/LaunchAgents/so.context.tick.plist"])
        self.assertTrue(it["derived"]["exists"] and it["backups"]["exists"])
        self.assertIn("OTHER apps", it["backups"]["note"])
        self.assertIn("devices", it["telegram-session"]["note"])
        data = it["data"]["where"]
        self.assertIn("~/.context/v2/messages.jsonl", data)
        self.assertFalse([w for w in data if "api.json" in w or w.endswith("/repo") or ".log" in w or "telegram" in w])
        total = remove.listing(self.P)["total_bytes"]
        self.assertEqual(total, sum(i["bytes"] for i in it.values()))

    def test_keys_are_counted_never_shown(self):
        d = remove.listing(self.P)
        text = remove.text(d) + json.dumps(d)
        self.assertIn("api keys (2)", text)
        self.assertNotIn("s" * 43, text)
        self.assertNotIn('"aa"', text)

    def test_which_entries_are_ours(self):
        it = self.by_id()
        self.assertTrue(it["mcp-cursor"]["exists"] and it["mcp-codex"]["exists"] and it["mcp-claude-code"]["exists"])
        self.assertFalse(it["mcp-claude-desktop"]["exists"])
        self.assertIn("not ours", it["mcp-claude-desktop"]["note"])
        self.assertTrue(it["host-chrome"]["exists"])
        self.assertFalse(it["host-arc"]["exists"])
        self.assertIn("not ours", it["host-arc"]["note"])
        self.assertFalse(it["host-dia"]["exists"])
        self.assertEqual(self.ran, [])           # looking starts no program

    def test_servers_say_whether_they_run(self):
        it = self.by_id()
        self.assertTrue(it["api-server"]["running"] and it["remote-server"]["running"])
        self.commands.clear()
        self.assertFalse(self.by_id()["api-server"]["running"])

    def test_text_has_every_id_and_the_by_hand_list(self):
        d = remove.listing(self.P)
        text = remove.text(d)
        for it in d["items"]:
            self.assertIn(it["id"], text)
        for word in (bridge.EXTENSION_ID, "tccutil reset All so.context.app", "Login Items", "Devices", ".env", "nothing was changed"):
            self.assertIn(word, text)
        self.assertEqual(text, text.replace(self.home, ""))      # the home folder is written as ~


class All(Base):
    def test_everything_goes_and_lands_in_the_trash(self):
        outside = tempfile.mkdtemp(prefix="ctx-outside-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        put(os.path.join(outside, "keep.txt"), "mine")
        before = tree(self.home)
        res = self.go("all")
        self.assertEqual(res["could_not"], [])
        self.assertEqual(res["left"], [])
        for it in self.by_id().values():
            self.assertFalse(it["exists"], it["id"])
        self.assertFalse(self.has(".context"))
        self.assertFalse(self.has("Applications", "context.app"))
        self.assertFalse(self.has("Library", "Preferences", "so.context.app.plist"))
        # recoverable: every byte that was ours is now under <home>/.Trash, in one folder made for this removal
        self.assertEqual(len(os.listdir(self.trash)), 1)
        self.assertTrue(res["trash"].startswith("~/.Trash/context removed "))
        after = {os.path.basename(k): v for k, v in tree(self.trash).items()}
        for name in ("messages.jsonl", "export.zip", "vectors.bin", "telegram.session", "api.json", "core.md", "so.context.app.plist", "so.context.tick.plist"):
            self.assertIn(name, after)
        self.assertEqual(after["messages.jsonl"], before[os.path.join(".context", "v2", "messages.jsonl")])
        self.assertIn("context.app", self.in_trash())
        self.assertIn("v2", self.in_trash())
        self.assertEqual(tree(outside), {"keep.txt": b"mine"})


    def test_a_folder_ctx_home_names_that_is_not_an_archive_is_never_marked_changed_or_moved(self):
        """What was seen: CTX_HOME at a folder holding two text files; the engine's first start set them to 0600 and
        wrote the marker, and `remove --all --yes` then moved the folder to the Trash. Played here end to end, in a
        process of its own, as the person would run it: a made-up home, the real engine, nothing patched."""
        import stat, subprocess
        from ctx import guard
        self.home = os.path.realpath(tempfile.mkdtemp(prefix="ctx-remove-bare-"))        # a home with nothing of context's in it
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.trash = os.path.join(self.home, ".Trash")
        theirs = os.path.join(self.home, "Documents", "notes")
        for name in ("thesis.txt", "letters.txt"):
            put(os.path.join(theirs, name), "years of work")
            os.chmod(os.path.join(theirs, name), 0o644)
        os.chmod(theirs, 0o755)
        before = tree(theirs)
        modes = lambda: {n: stat.S_IMODE(os.stat(os.path.join(theirs, n)).st_mode) for n in os.listdir(theirs) + ["."]}
        scratch = os.path.join(self.home, "tmp")
        os.makedirs(scratch)
        env = {"HOME": self.home, "CTX_HOME": theirs, "TMPDIR": scratch, "CTX_BROWSER_DATA": os.path.join(self.home, "Library", "Application Support"),
               "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8", "CTX_ANY_OS": "1", remove.MARKER: "1", "CTX_CLI_PATH": fixture.NO_CLI}
        run = lambda *args: subprocess.run(guard.python(list(args)), capture_output=True, text=True, env=env, cwd=scratch, timeout=120, stdin=subprocess.DEVNULL)
        r = run("remove", "--all", "--yes")                  # importing the engine is the first thing this does
        self.assertEqual(r.returncode, 1, r.stdout[-400:] + r.stderr[-400:])            # 1: something was left, and said
        self.assertIn("does not look like a context archive", r.stdout)
        self.assertEqual(tree(theirs), before)                                          # nothing added (no marker), nothing taken
        self.assertEqual(modes(), {"thesis.txt": 0o644, "letters.txt": 0o644, ".": 0o755})
        self.assertFalse(any(n in ("thesis.txt", "letters.txt", "notes") for n in self.in_trash()))
        r = run("remove", "--only", "data", "--yes")         # nor piece by piece
        self.assertEqual(tree(theirs), before)
        self.assertIn("not ours", run("remove").stdout)    # the listing says why it shows nothing in that folder
        # the same engine, started on a folder it makes, marks it and takes it away whole
        mine = os.path.join(self.home, "elsewhere", "archive")
        env["CTX_HOME"] = mine
        r = run("remove", "--all", "--yes")
        self.assertIn("the archive folder ~/elsewhere/archive: moved to the trash", r.stdout, r.stderr[-400:])
        self.assertFalse(os.path.exists(mine))

    def test_an_archive_folder_reached_through_a_link_goes_whole(self):
        """CTX_HOME as a link to the folder that holds the archive: the folder it points to carries the marker, so that
        folder goes to the trash, then the link, and both are said. Moving the link alone left every file in place."""
        real = os.path.join(self.home, "Volumes", "big", "archive")
        os.makedirs(os.path.dirname(real))
        shutil.move(self.v2, real)
        os.symlink(real, self.v2)
        self.assertIn("is a link to ~/Volumes/big/archive", self.by_id()["data"]["note"])
        res = self.go("all")
        self.assertEqual((res["could_not"], res["left"]), ([], []))
        self.assertFalse(os.path.lexists(real))
        self.assertFalse(os.path.lexists(self.v2))
        self.assertTrue(any(l.startswith("the archive folder ~/.context/v2 (a link to ~/Volumes/big/archive): moved to the trash") for l in self.said), self.said)
        self.assertTrue(any(l.startswith("the link ~/.context/v2, which pointed to it: moved to the trash") for l in self.said), self.said)
        self.assertTrue({"messages.jsonl", "telegram.session", "api.json"} <= self.in_trash())          # the files themselves, not only a link to them

    def test_a_link_to_a_folder_that_is_not_an_archive_moves_nothing(self):
        theirs = os.path.join(self.home, "Documents", "notes")
        put(os.path.join(theirs, "thesis.txt"), "years of work")
        shutil.rmtree(self.v2)
        os.symlink(theirs, self.v2)
        res = self.go("all")
        self.assertEqual(read(os.path.join(theirs, "thesis.txt")), "years of work")
        self.assertTrue(os.path.islink(self.v2))
        self.assertIn("~/.context/v2", " ".join(res["left"]))
        self.assertTrue(any("(a link to ~/Documents/notes)" in l and "does not look like a context archive" in l for l in self.said), self.said)

    def test_a_folder_that_is_not_an_archive_is_never_moved_whole(self):
        os.remove(os.path.join(self.v2, ".closed"))         # a folder that never carried the marker
        res = self.go("all")
        self.assertTrue(os.path.isdir(self.v2))
        self.assertTrue(any("does not look like a context archive" in l for l in self.said))
        self.assertIn("~/.context/v2", " ".join(res["left"]))
        self.assertTrue(self.has(".context", "v2", "messages.jsonl") and self.has(".context", "v2", "api.json") and self.has(".context", "v2", "telegram.session"))
        self.assertEqual(self.killed, [])                   # pids read out of a folder that is not ours are not trusted either
        it = self.by_id()
        self.assertFalse(any(it[i]["exists"] for i in ("data", "imports", "api-keys", "telegram-session", "api-server", "bridge")))
        self.assertIn("not ours", it["data"]["note"])

    def test_a_folder_named_derived_beside_an_archive_kept_elsewhere_is_not_taken_for_ours(self):
        docs = os.path.join(self.home, "Documents")                       # CTX_HOME pointed into a folder of the person's own
        arch = os.path.join(docs, "my-archive")
        shutil.copytree(self.v2, arch)
        put(os.path.join(docs, "derived", "thesis.txt"), "years of work")       # theirs: it only shares a name
        self.P = remove.places(home=self.home, ctx_home=arch)
        it = self.by_id()["derived"]
        self.assertEqual((it["exists"], it["where"], it["bytes"]), (False, [], 0))
        self.assertIn("left alone", it["note"])
        self.go("all")
        self.assertEqual(tree(os.path.join(docs, "derived")), {"thesis.txt": b"years of work"})
        self.assertFalse(os.path.exists(arch))                             # the archive itself, which carries the marker, went
        self.assertFalse(any("thesis" in n or n == "derived" for n in self.in_trash()))
        # the same folder is ours when it carries the marker context writes
        shutil.copytree(self.v2, arch)
        put(os.path.join(docs, "derived", ".closed"), "")
        self.assertTrue(self.by_id()["derived"]["exists"])
        # and with no marker in the archive, nothing beside it is ours either
        os.remove(os.path.join(arch, ".closed"))
        self.assertFalse(self.by_id()["derived"]["exists"])

    def test_an_app_of_the_same_name_with_another_bundle_id_is_left(self):
        info = os.path.join(self.home, "Applications", "context.app", "Contents", "Info.plist")
        with open(info) as f:
            text = f.read()
        with open(info, "w") as f:
            f.write(text.replace("so.context.app", "org.example.other"))
        it = self.by_id()["app"]
        self.assertEqual(it["where"], [])
        self.assertIn("bundle id is not ours", json.dumps(it))
        self.go("all")
        self.assertTrue(self.has("Applications", "context.app"))

    def test_what_is_not_ours_stays(self):
        self.go("all")
        desktop = load(os.path.join(self.home, "Library", "Application Support", "Claude", "claude_desktop_config.json"))
        self.assertEqual(desktop["mcpServers"]["context"], {"command": "someone-elses"})
        cursor = load(os.path.join(self.home, ".cursor", "mcp.json"))
        self.assertEqual(cursor, {"mcpServers": {"other": {"command": "x"}}, "theme": "dark"})
        self.assertEqual(read(os.path.join(self.home, ".codex", "config.toml")), 'model = "m"\n')
        arc = os.path.join(self.home, "Library", "Application Support", "Arc", "User Data", "NativeMessagingHosts", bridge.NAME + ".json")
        self.assertEqual(load(arc)["name"], "so.someone.else")
        self.assertTrue(self.has("Library", "Preferences", "com.other.app.plist"))
        self.assertTrue(self.has("Library", "LaunchAgents", "com.other.job.plist"))
        self.assertTrue(self.has("Library", "LaunchAgents", "com.also.contextmenu.plist"))
        self.assertTrue(self.has("Library", "LaunchAgents", "so.context.app.helper.plist"))
        self.assertFalse(self.has("Library", "LaunchAgents", "so.context.tick.plist"))           # ours by its exact label
        self.assertTrue(any("not ours" in s for s in self.said))

    def test_order_and_what_is_started(self):
        res = self.go("all")
        ids = [d["id"] for d in res["done"]]
        self.assertLess(ids.index("mcp-cursor"), ids.index("host-chrome"))
        self.assertLess(ids.index("host-chrome"), ids.index("app-prefs"))
        self.assertLess(ids.index("app-prefs"), ids.index("app"))
        self.assertLess(ids.index("app"), ids.index("data"))
        self.assertEqual(self.quits, [1])
        self.assertEqual(sorted(self.killed), [(111, signal.SIGTERM), (222, signal.SIGTERM), (333, signal.SIGTERM)])
        self.assertTrue(self.said[0].startswith("the app:"))                     # asked to quit before anything moves
        self.assertIn(["/fake/claude", "mcp", "remove", "context", "-s", "user"], self.ran)
        self.assertIn(["defaults", "delete", "so.context.app"], self.ran)
        self.assertFalse([c for c in self.ran if c[0] in ("osascript", "open", "tccutil", "trash", "launchctl")])
        self.assertTrue(any("tccutil reset All so.context.app" in s for s in res["by_hand"]))
        self.assertIn("only you can do these", remove.report(res))

    def test_a_pid_that_is_not_ours_is_not_killed(self):
        self.commands = {111: "vim notes.txt", 222: "/usr/bin/python3 -m ctx mcp --http", 333: "ssh somewhere"}
        self.go("all")
        self.assertEqual(self.killed, [(222, signal.SIGTERM)])
        self.assertTrue(any("111 is not ours" in s for s in self.said))

    def test_a_tunnel_name_we_never_start_is_not_trusted(self):
        put(os.path.join(self.v2, "remote.run.json"), json.dumps({"pid": 0, "tunnel": "vim", "tunnel_pid": 444}))
        self.commands = {444: "vim notes.txt"}
        self.go("only", ["remote-server"])
        self.assertEqual(self.killed, [])
        self.assertFalse(self.has(".context", "v2", "remote.run.json"))

    def test_no_outside_program_without_a_run_on_a_made_up_home(self):
        with mock.patch.object(remove.subprocess, "run", side_effect=AssertionError("started a real program")):
            res = remove.run("all", P=self.P, say=self.said.append, kill=lambda *a: None, command=lambda pid: "", sleep=lambda s: None)
        self.assertFalse(self.has(".context"))
        self.assertEqual([c["id"] for c in res["could_not"]], ["mcp-claude-code"])       # no cli was run, so its entry is for the person
        self.assertIn("claude mcp remove context -s user", res["could_not"][0]["by_hand"])
        self.assertTrue(any("defaults delete so.context.app" in s for s in res["by_hand"]))

    def test_dry_run_changes_nothing(self):
        before = tree(self.home)
        res = self.go("all", dry=True)
        self.assertEqual(tree(self.home), before)
        self.assertFalse(os.path.exists(self.trash))
        self.assertEqual((self.killed, self.ran, self.quits), ([], [], []))
        self.assertTrue(res["dry_run"])
        self.assertTrue(all(d["did"].startswith("would") for d in res["done"]))
        self.assertIn("app", [d["id"] for d in res["done"]])


class KeepArchive(Base):
    def test_data_stays_and_the_rest_goes(self):
        res = self.go("keep-archive")
        for name in ("messages.jsonl", "sessions.jsonl", "imports", "cache", "chats", "custom", "backups", "api.log", "app.json", "memory"):
            self.assertTrue(self.has(".context", "v2", name), name)
        self.assertTrue(self.has(".context", "derived", "profile", "core.md"))
        for name in ("api.json", "remote.json", "api.run.json", "remote.run.json", "bridge", "repo", "telegram.session"):
            self.assertFalse(self.has(".context", "v2", name), name)
        self.assertFalse(self.has("Applications", "context.app"))
        self.assertFalse(self.has("Library", "Preferences", "so.context.app.plist"))
        self.assertFalse(self.has("Library", "Application Support", "Google", "Chrome", "NativeMessagingHosts", bridge.NAME + ".json"))
        it = self.by_id()
        self.assertFalse(it["mcp-cursor"]["exists"] or it["mcp-codex"]["exists"] or it["mcp-claude-code"]["exists"])
        kept = {k["id"] for k in res["kept"]}
        self.assertTrue({"data", "imports", "logs", "backups", "derived"} <= kept)
        self.assertFalse(kept & {"app", "api-keys", "bridge", "repo-pointer"})
        self.assertIn("kept (", remove.report(res))
        self.assertTrue({"api.json", "remote.json", "bridge", "repo", "context.app"} <= self.in_trash())


class Only(Base):
    def test_one_item(self):
        before = tree(self.home)
        res = self.go("only", ["imports"])
        self.assertEqual([d["id"] for d in res["done"]], ["imports"])
        after = tree(self.home)
        gone = {k for k in before if k not in after}
        self.assertEqual(gone, {os.path.join(".context", "v2", "imports", "export.zip")})
        self.assertEqual((self.killed, self.ran, self.quits), ([], [], []))

    def test_a_group_and_a_comma_list(self):
        self.assertEqual(remove.main(["--only", "hosts,api-keys", "--only", "mcp-cursor", "--yes"], P=self.P, out=self.said.append, run=self.run_, trash_cmd="",
                                     kill=lambda *a: self.killed.append(a), command=lambda pid: ""), 0)
        self.assertFalse(self.has(".context", "v2", "bridge") or self.has(".context", "v2", "api.json"))
        self.assertNotIn("context", load(os.path.join(self.home, ".cursor", "mcp.json"))["mcpServers"])
        self.assertTrue(self.has(".context", "v2", "remote.json") and self.has("Applications", "context.app"))
        self.assertEqual(self.killed, [])

    def test_an_unknown_id_changes_nothing(self):
        before = tree(self.home)
        with self.assertRaises(remove.Refused):
            self.go("only", ["imports", "nope"])
        self.assertEqual(remove.main(["--only", "nope", "--yes"], P=self.P, out=self.said.append), 2)
        self.assertEqual(tree(self.home), before)

    def test_the_other_entry_named_context_is_left_alone(self):
        res = self.go("only", ["mcp-claude-desktop", "host-arc"])
        self.assertEqual(res["done"], [])
        self.assertEqual(len([s for s in self.said if "not ours" in s]), 2)


class Asking(Base):
    def main(self, argv, answer):
        self.asked = []
        return remove.main(argv, P=self.P, out=self.said.append, ask=lambda q: self.asked.append(q) or answer, run=self.run_, trash_cmd="",
                           kill=lambda *a: None, command=lambda pid: "", quit_app=lambda: "quit", claude="/fake/claude")

    def test_a_wrong_word_changes_nothing(self):
        before = tree(self.home)
        for answer in ("yes", "y", "", "removed", "remove it"):
            self.assertEqual(self.main(["--all"], answer), 1)
        self.assertEqual(tree(self.home), before)
        self.assertIn("nothing was changed.", self.said)
        self.assertEqual(len(self.asked), 1)

    def test_no_one_to_ask_changes_nothing(self):
        before = tree(self.home)

        def gone(q):
            raise EOFError
        self.assertEqual(remove.main(["--keep-archive"], P=self.P, out=self.said.append, ask=gone), 1)
        self.assertEqual(remove.main(["--all", "--json"], P=self.P, out=self.said.append, ask=gone), 2)
        self.assertEqual(tree(self.home), before)

    def test_the_word_goes_ahead(self):
        self.assertEqual(self.main(["--all"], " Remove "), 0)
        self.assertFalse(self.has(".context"))

    def test_yes_skips_the_question(self):
        self.assertEqual(self.main(["--keep-archive", "--yes", "--json"], "no"), 0)
        self.assertEqual(self.asked, [])
        res = json.loads(self.said[-1])
        self.assertEqual(res["mode"], "keep-archive")
        self.assertFalse(self.has("Applications", "context.app"))

    def test_odd_arguments_change_nothing(self):
        before = tree(self.home)
        for argv in (["--everything"], ["--all", "--keep-archive", "--yes"], ["--only"], ["--only", "--yes"], ["--all", "--only", "imports", "--yes"]):
            self.assertEqual(self.main(argv, "remove"), 2, argv)
        self.assertEqual(tree(self.home), before)

    def test_dry_run_needs_no_word(self):
        before = tree(self.home)
        self.assertEqual(self.main(["--all", "--dry-run"], "no"), 0)
        self.assertEqual(self.asked, [])
        self.assertEqual(tree(self.home), before)


class Guard(Base):
    def test_the_real_home_is_refused(self):
        real = remove.real_home()
        self.assertNotEqual(os.path.realpath(real), os.path.realpath(os.path.expanduser("~")))     # the tests' own "~" is made up
        for P in (remove.places(home=real, ctx_home=self.v2), remove.places(home=self.home, ctx_home=os.path.join(real, ".context", "v2")),
                  remove.places(home=self.home, ctx_home=self.v2, apps=["/Applications"]), remove.places(home=self.home, ctx_home=self.v2, browser_data=os.path.join(real, "Library")),
                  remove.places(home="/", ctx_home=self.v2)):
            with self.assertRaises(remove.Refused):
                remove._guard(P)
        remove._guard(self.P)      # a made-up home passes

    def test_a_removal_stops_before_it_touches_anything(self):
        before = tree(self.home)
        with mock.patch.object(remove, "real_home", return_value=self.home):       # pretend the made-up home is the real one
            for mode, only in (("all", ()), ("keep-archive", ()), ("only", ["imports"])):
                with self.assertRaises(remove.Refused):
                    self.go(mode, only)
            self.assertEqual(remove.main(["--all", "--yes"], P=self.P, out=self.said.append, run=self.run_, trash_cmd=""), 2)
            self.assertEqual(remove.main([], P=self.P, out=self.said.append, command=lambda pid: ""), 0)       # looking is still allowed
        self.assertEqual(tree(self.home), before)
        self.assertEqual((self.killed, self.ran, self.quits), ([], [], []))
        self.assertTrue(any(s.startswith("refused:") for s in self.said if isinstance(s, str)))


class Trash(Base):
    def test_two_things_with_one_name_both_survive(self):
        a, b = put(os.path.join(self.home, "a", "same.txt"), "one"), put(os.path.join(self.home, "b", "same.txt"), "two")
        t = remove._Trash(self.P, "", self.run_, now=0)
        first, second = t.move(a), t.move(b)
        self.assertNotEqual(first, second)
        self.assertEqual(sorted(read(p) for p in (first, second)), ["one", "two"])
        again = remove._Trash(self.P, "", self.run_, now=0)       # a second removal in the same second gets its own folder
        again.move(put(os.path.join(self.home, "c", "same.txt"), "three"))
        self.assertNotEqual(again.folder, t.folder)

    def test_the_trash_program_is_used_when_given_and_checked(self):
        f = put(os.path.join(self.home, "x.txt"))
        t = remove._Trash(self.P, "/fake/trash", self.run_)        # says it worked, moved nothing: we fall back to the folder
        to = t.move(f)
        self.assertEqual(self.ran, [["/fake/trash", f]])
        self.assertTrue(to.startswith(self.trash) and os.path.exists(to))


if __name__ == "__main__":
    unittest.main()
