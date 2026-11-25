"""Take context off this Mac, cleanly, and show first what is there.

  python3 -m ctx remove                  list everything context has put on this mac, with sizes. changes nothing
  python3 -m ctx remove --all            remove all of it (asks you to type the word remove; --yes skips the question)
  python3 -m ctx remove --keep-archive   remove everything except your data: the app, the entries in ai apps, keys, the browser link
  python3 -m ctx remove --only <id>      one thing from the list (repeat it, or give a comma list; a group name works too)
  add --dry-run to see what a removal would do, --json for a program

What it does and does not do:
  - nothing is deleted. every file and folder is moved to the Trash, so a mistake can be put back
  - in other apps' config files only our own entry is taken out; an entry that is not ours is left alone
  - the archive folder is moved only when it carries the marker context writes in a folder it made or found empty
    (.closed). a folder CTX_HOME was pointed at that holds someone else's files has none: nothing in it is touched
  - a process is stopped only when its number came from our own run file and `ps` says it is still our program
  - some things only you can do (the browser extension, permissions in System Settings, the device inside Telegram):
    they are printed at the end, every time

Every place is an argument (see places()), so the tests run it on a made-up home folder and never on the real one.
"""
import glob, json, os, plistlib, pwd, shutil, signal, subprocess, sys, time
from . import bridge, mcp, paths

APP_ID = "so.context.app"
# the labels a background job of context's would carry. context makes none of its own today; a launch agent is taken for
# ours only when its label is one of these, whole
LAUNCH_LABELS = (APP_ID, "so.context.tick", "so.context.bridge")
WORD = "remove"                              # what the person types to confirm
MARKER = "CTX_REMOVE_TEST_ONLY"              # set by the tests: with it, nothing is ever removed from the real home
SLUGS = {"Dia": "dia", "Google Chrome": "chrome", "Chromium": "chromium", "Arc": "arc", "Brave Browser": "brave", "Microsoft Edge": "edge"}
LOG_NAMES = ("ledger.jsonl",)                # logs that do not end in .log
GROUPS = [("servers", "running now"), ("app", "the mac app"), ("mcp", "entries in ai apps"), ("hosts", "the browser link"),
          ("secrets", "keys and sign-ins"), ("archive", "your data (kept by --keep-archive)")]
# what a removal does first to last: servers stop before their files go, the app quits before its files go, the data goes last
ORDER = ["servers", "mcp", "hosts", "app", "secrets", "archive"]


class Refused(Exception):
    pass


def real_home():
    """This account's home folder as the system has it, whatever $HOME says."""
    return pwd.getpwuid(os.getuid()).pw_dir


def _same(a, b):
    return os.path.realpath(a) == os.path.realpath(b)


def _inside(path, folder):
    p, f = os.path.realpath(path), os.path.realpath(folder)
    return p == f or p.startswith(f.rstrip("/") + "/")


def places(home=None, ctx_home=None, browser_data=None, apps=None, repo=None, tmp=None):
    """Every folder this module looks in, in one dict. With no arguments: this Mac. With home= a made-up home, nothing
    outside that folder is named (no /Applications, no real browser folder) unless it is passed in too."""
    made_up = home is not None
    home = os.path.abspath(home or os.path.expanduser("~"))
    system_apps = [] if made_up or not _same(home, real_home()) else ["/Applications"]      # never when $HOME points somewhere else
    return {"home": home,
            "ctx_home": os.path.abspath(ctx_home or paths.HOME),
            "browser_data": os.path.abspath(browser_data or (os.path.join(home, "Library", "Application Support") if made_up else bridge.APPDATA)),
            "apps": [os.path.abspath(a) for a in (apps if apps is not None else system_apps + [os.path.join(home, "Applications")])],
            "repo": os.path.abspath(repo or bridge.REPO),
            "tmp": os.path.abspath(tmp) if tmp else ""}


def _guard(P):
    """The tests set MARKER. With it set, a removal that could reach the real home, or /Applications, does not run."""
    if not os.environ.get(MARKER):
        return
    real = real_home()
    for p in [P["home"], P["ctx_home"], P["browser_data"]] + P["apps"]:
        if _same(p, "/Applications") or _inside(p, real) or _inside(real, p):
            raise Refused("refused: %s is set and %s is on the real home. nothing was changed" % (MARKER, p))


def size(path):
    """(bytes, files) under a path, links not followed. (0, 0) when it is not there or cannot be read."""
    try:
        st = os.lstat(path)
    except OSError:
        return 0, 0
    if not os.path.isdir(path) or os.path.islink(path):
        return st.st_size, 1
    total, n = 0, 0
    for root, dirs, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
                n += 1
            except OSError:
                pass
    return total, n


def human(b):
    for unit in ("bytes", "kb", "mb", "gb"):
        if b < 1024 or unit == "gb":
            return ("%d %s" % (b, unit)) if unit == "bytes" else ("%.1f %s" % (b, unit))
        b /= 1024.0


def _our_app(path):
    """Is the bundle at this path context's own, by its bundle id?"""
    import plistlib
    try:
        with open(os.path.join(path, "Contents", "Info.plist"), "rb") as f:
            return plistlib.load(f).get("CFBundleIdentifier") == APP_ID
    except Exception:
        return False


def _is_archive(folder, names=None):
    """An archive folder carries the marker (.closed, a plain file) that context writes only into a folder it made or
    found empty (guard.claim). Any other folder CTX_HOME was pointed at is someone else's, whatever it holds."""
    from . import guard
    return guard.marked(folder)


def _derived_ours(v2, derived, names):
    """The folder beside the archive that holds pages worked out from it (<parent>/derived) is context's own when the
    archive is (the same marker rule) and either the parent is the folder context makes for itself (.context), or the
    derived folder carries the marker too. Anywhere else a folder of that name is someone else's until shown otherwise."""
    from . import guard
    if not os.path.isdir(derived) or os.path.islink(derived) or not names or not _is_archive(v2, names):
        return False
    return os.path.basename(os.path.dirname(v2)) == ".context" or guard.marked(derived)


def _shown(path, P):
    return "~" + path[len(P["home"]):] if path == P["home"] or path.startswith(P["home"] + "/") else path


def _json(path):
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _command(pid):
    """What `ps` says that process is, "" when there is no such process."""
    try:
        return subprocess.run(["ps", "-p", str(int(pid)), "-o", "command="], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return ""


class _Ok:
    returncode, stdout, stderr = 0, "", ""


def _no_run(cmd, **kw):
    """Stands in for subprocess.run while listing: nothing is started (mcp.status starts nothing of its own either)."""
    return _Ok()


def _ours_host(path):
    d = _json(path)
    return d.get("name") == bridge.NAME


def _procs(P):
    """The servers our run files name: [(item id, run file, [(key, pid, the words ps must show)])]."""
    v2 = P["ctx_home"]
    api_run, remote_run = os.path.join(v2, "api.run.json"), os.path.join(v2, "remote.run.json")
    a, r = _json(api_run), _json(remote_run)
    tunnel = r.get("tunnel") if r.get("tunnel") in ("cloudflared", "tailscale") else ""
    return [("api-server", api_run, [("pid", a.get("pid"), "ctx api")]),
            ("remote-server", remote_run, [("tunnel_pid", r.get("tunnel_pid"), tunnel), ("pid", r.get("pid"), "ctx mcp --http")])]


def items(P, command=_command):
    """Everything context has put on this Mac, found by looking. Read-only. One dict per thing:
    {"id", "group", "what", "where": [...], "exists", "bytes", "files", "note", "keep"}; keep means --keep-archive leaves it."""
    home, v2, out = P["home"], P["ctx_home"], []
    lib = os.path.join(home, "Library")
    # CTX_HOME can name any folder. one that does not carry the archive's marker is someone else's: nothing inside it is
    # listed, so nothing inside it is moved, stopped or counted, whatever names its files have
    foreign = os.path.isdir(v2) and not _is_archive(v2)

    def add(i, group, what, found, note="", keep=False, kind="path", **more):
        found = [p for p in found if os.path.lexists(p) and not (foreign and _inside(p, v2))]
        b = n = 0
        for p in found:
            x, y = size(p)
            b, n = b + x, n + y
        out.append(dict({"id": i, "group": group, "what": what, "where": [_shown(p, P) for p in found], "exists": bool(found), "bytes": b, "files": n,
                         "note": note, "keep": keep, "_kind": kind, "_paths": found}, **more))
        return out[-1]

    # servers
    for i, run_file, pids in _procs(P):
        live = [pid for _, pid, word in pids if pid and word and not foreign and word in command(pid)]
        what = "the local api server" if i == "api-server" else "the remote endpoint and its tunnel"
        it = add(i, "servers", what, [run_file], "" if live else ("not running: only its run file is left" if os.path.exists(run_file) else ""), kind="process")
        it["running"] = bool(live)
    # entries in ai apps
    try:
        rows = [r for r in mcp.status(home=home, claude=None, run=_no_run) if r["id"] in mcp.ORDER]
    except Exception as e:
        rows = [{"id": i, "registered": False, "config": "", "detail": "could not read its config (%s)" % type(e).__name__} for i in mcp.ORDER]
    for r in rows:
        ours, other = bool(r.get("ours")), "another server" in (r.get("detail") or "")
        out.append({"id": "mcp-" + r["id"].replace("_", "-"), "group": "mcp", "what": "our entry in " + mcp.NAMES[r["id"]], "where": [r["config"]] if ours and r.get("config") else [],
                    "exists": ours, "bytes": 0, "files": 0, "keep": False, "_kind": "mcp", "_paths": [], "_target": r["id"],
                    "note": "an entry named context is there but it is not ours: left alone" if other else "only our entry is taken out; the rest of the file stays"})
    # the browser link
    for name, data_dir in bridge.BROWSERS:
        p = os.path.join(P["browser_data"], data_dir, "NativeMessagingHosts", bridge.NAME + ".json")
        mine = os.path.isfile(p) and _ours_host(p)
        it = add("host-" + SLUGS.get(name, name.lower().replace(" ", "-")), "hosts", "the link file in " + name.lower(), [p] if mine else [],
                 "a file with our name is there but it is not ours: left alone" if os.path.isfile(p) and not mine else "", kind="host")
        it["_host"] = p
    add("bridge", "hosts", "the helper the browser starts, and its job folder", [os.path.join(v2, "bridge")])
    # the app
    found = [os.path.join(a, "context.app") for a in P["apps"]]
    ours = [p for p in found if not os.path.exists(p) or _our_app(p)]          # an app of the same name from someone else is not ours to move
    add("app", "app", "context.app", ours, "an app named context.app is there but its bundle id is not ours: left alone" if len(ours) < len(found) else "")
    add("app-prefs", "app", "the app's saved settings", [os.path.join(lib, "Preferences", APP_ID + ".plist")])
    add("app-caches", "app", "the app's caches and saved window state",
        [os.path.join(lib, "Caches", APP_ID), os.path.join(lib, "Saved Application State", APP_ID + ".savedState"), os.path.join(lib, "WebKit", APP_ID),
         os.path.join(lib, "Application Support", APP_ID)] + sorted(glob.glob(os.path.join(lib, "HTTPStorages", APP_ID + "*"))))
    agents = []
    for p in sorted(glob.glob(os.path.join(lib, "LaunchAgents", "*.plist"))):
        label = None
        try:
            with open(p, "rb") as f:
                label = plistlib.load(f).get("Label")
        except Exception:
            pass
        # by its exact label, never a part of a name: com.also.contextmenu.plist holds "so.context" and is someone else's.
        # a file whose label cannot be read counts only when its name is one of ours whole
        if label in LAUNCH_LABELS or (label is None and os.path.basename(p)[:-len(".plist")] in LAUNCH_LABELS):
            agents.append(p)
    add("launch-agents", "app", "background jobs started at login", agents, "context makes none of its own; any found here carry its name. it stays loaded until you log out")
    if P["tmp"]:
        add("debug-home", "app", "scratch folders of a debug build", sorted(glob.glob(os.path.join(P["tmp"], "context-debug"))))
    # keys and sign-ins
    keys = _json(os.path.join(v2, "api.json")).get("keys")
    add("api-keys", "secrets", "api keys (%d)" % (len(keys) if isinstance(keys, dict) else 0), [os.path.join(v2, "api.json")],
        "apps you gave a key to stop working once this is gone")
    add("remote-secret", "secrets", "the secret in the remote url", [os.path.join(v2, "remote.json")], "the url pasted into chatgpt or claude.ai stops working once this is gone")
    add("telegram-session", "secrets", "the telegram sign-in", sorted(glob.glob(os.path.join(v2, "telegram.session*"))),
        "moving the file does not sign the device out: also remove it in telegram > settings > devices")
    add("repo-pointer", "secrets", "the note telling the app where the engine is", [os.path.join(v2, "repo")])
    # the data
    claimed = {"bridge", "api.json", "remote.json", "api.run.json", "remote.run.json", "repo", "imports", "cache", "backups", "custom", "chats", "bin", "media", "app.json"}
    try:
        names = sorted(os.listdir(v2))
    except OSError:
        names = []
    logs = [n for n in names if n.endswith(".log") or n in LOG_NAMES]
    rest = [n for n in names if n not in claimed and n not in logs and not n.startswith("telegram.session")]
    cache = os.path.join(v2, "cache")
    try:
        other_cache = [os.path.join(cache, n) for n in sorted(os.listdir(cache)) if n not in ("semantic", "words")]
    except OSError:
        other_cache = []
    arch = lambda i, what, found, note="": add(i, "archive", what, found, note, keep=True)
    arch("data", "everything collected: messages, sessions, notes, what was learned from them", [os.path.join(v2, n) for n in rest],
         "the folder %s does not carry the marker context writes in an archive it made (.closed), so it is not ours: nothing in it is listed or moved" % _shown(v2, P) if foreign
         else "%s is a link to %s: a full removal moves that folder, then the link" % (_shown(v2, P), _shown(os.path.realpath(v2), P)) if os.path.islink(v2) else "")
    arch("imports", "raw imports and unpacked exports", [os.path.join(v2, "imports")])
    arch("media", "what was read out of photos, voice notes and files", [os.path.join(v2, "media")])
    arch("chats", "your chats with the app", [os.path.join(v2, "chats")])
    arch("custom", "readers for apps you added yourself", [os.path.join(v2, "custom")])
    arch("index-meaning", "the search-by-meaning index", [os.path.join(cache, "semantic")], "can be built again: python3 -m ctx index")
    arch("index-words", "the word index", [os.path.join(cache, "words")], "can be built again: python3 -m ctx words")
    arch("caches", "other caches (icons, fetched pages)", other_cache)
    arch("tools", "small helper programs built on this mac", [os.path.join(v2, "bin")], "built again when needed")
    arch("logs", "logs", [os.path.join(v2, n) for n in logs], "sizes and times of calls, never what was asked")
    arch("backups", "backups of other apps' config files", [os.path.join(v2, "backups")],
         "copies of OTHER apps' config files, made each time `mcp --install` or `--remove` changed one. keep them if you may want an old config back")
    arch("app-state", "what the app remembers between runs", [os.path.join(v2, "app.json")])
    up = os.path.dirname(v2)
    derived = os.path.join(up, "derived")
    if _derived_ours(v2, derived, names):
        arch("derived", "pages worked out from the archive", [derived])
    else:               # CTX_HOME can be pointed anywhere: a folder that merely sits beside it and is called derived is not taken for ours
        add("derived", "archive", "pages worked out from the archive", [], "a folder named derived beside the archive is left alone unless it is context's own" if os.path.isdir(derived) else "", keep=True)
    return out


def by_hand(P):
    """What no program should do for the person. Printed with the list and after every removal."""
    return [
        "the browser extension: open chrome://extensions (or your browser's extensions page), find context, click remove. its id is " + bridge.EXTENSION_ID,
        "permissions: System Settings > Privacy & Security > Full Disk Access, Accessibility and Automation: switch context off or remove it. "
        "or in Terminal: tccutil reset All " + APP_ID,
        "open at login: System Settings > General > Login Items: remove context if it is listed. the app sets this itself and only macos can clear it",
        "telegram: on your phone open Telegram > Settings > Devices and end the session context made. the file alone going does not sign it out",
        "the remote url: if you pasted one into chatgpt (plugins) or claude.ai (connectors), delete that connector there",
        "api keys: any app you gave a key to must be told to stop using it; the keys stop working once the key file is gone",
        "the code: the folder %s is yours and is left alone. delete it yourself when you are done. inside it, .env may hold your telegram api id and hash, "
        "and .venv holds the telegram packages" % _shown(P["repo"], P),
    ]


def listing(P=None, command=_command):
    P = P or places()
    its = items(P, command)
    return {"items": [{k: v for k, v in it.items() if not k.startswith("_")} for it in its], "total_bytes": sum(it["bytes"] for it in its),
            "by_hand": by_hand(P), "changed": False}


def _lines(rows, show_absent=True):
    out = []
    width = max([len(r["id"]) for r in rows if r["exists"] or "not ours" in r["note"]] + [4])
    for g, title in GROUPS:
        here = [r for r in rows if r["group"] == g and r["exists"]]
        gone = [r for r in rows if r["group"] == g and not r["exists"]]
        out.append("")
        out.append("%s  (--only %s)" % (title, g))
        for r in here:
            sz = "running" if r.get("running") else human(r["bytes"]) if r["bytes"] or r["files"] else "-"
            out.append("  %-*s  %10s  %s" % (width, r["id"], sz, r["what"]))
            for w in r["where"]:
                out.append("  %-*s  %10s    %s" % (width, "", "", w))
            if r["note"]:
                out.append("  %-*s  %10s    note: %s" % (width, "", "", r["note"]))
        if not here:
            out.append("  nothing here")
        for r in gone:
            if r["note"] and "not ours" in r["note"]:
                out.append("  %-*s  %10s  %s" % (width, r["id"], "-", r["note"]))
        if show_absent and any("not ours" not in r["note"] for r in gone):
            out.append("  not on this mac: " + ", ".join(r["id"] for r in gone if "not ours" not in r["note"]))
    return out


def text(d):
    out = ["what context has put on this mac. nothing was changed."]
    out += _lines(d["items"])
    out += ["", "total: " + human(d["total_bytes"]), "", "only you can do these:"]
    out += ["  - " + s for s in d["by_hand"]]
    out += ["", "to remove:  python3 -m ctx remove --all | --keep-archive | --only <id>      add --dry-run to look first. everything goes to the Trash."]
    return "\n".join(out)


# ---------------------------------------------------------------- removing

def _new_trash_folder(P, now=None):
    base = os.path.join(P["home"], ".Trash", "context removed " + time.strftime("%Y-%m-%d %H.%M.%S", time.localtime(now)))
    to, n = base, 1
    while True:
        try:
            os.makedirs(to)
            return to
        except FileExistsError:
            n += 1
            to = "%s (%d)" % (base, n)


class _Trash:
    """Moves things to the Trash. With the `trash` program: one by one, so Finder's Put Back works. Without it: into one
    new folder inside <home>/.Trash named for this removal, so nothing there is ever written over."""

    def __init__(self, P, cmd, run, now=None):
        self.P, self.cmd, self.run, self.now, self.folder = P, cmd, run, now, None

    def move(self, path):
        """Where it went ("the Trash" or a path). Raises OSError when it could not be moved."""
        if self.cmd:
            try:
                r = self.run([self.cmd, path], capture_output=True, text=True, timeout=300)
                if r.returncode == 0 and not os.path.lexists(path):
                    return "the Trash"
            except (OSError, subprocess.SubprocessError):
                pass
        if self.folder is None:
            self.folder = _new_trash_folder(self.P, self.now)
        name = os.path.basename(path.rstrip("/"))
        to, n = os.path.join(self.folder, name), 1
        while os.path.lexists(to):
            n += 1
            to = os.path.join(self.folder, "%s (%d)" % (name, n))
        try:
            os.rename(path, to)
        except OSError:
            shutil.move(path, to)       # another disk
        return to


def _app_running(run):
    try:
        return run(["pgrep", "-f", "context.app/Contents/MacOS/context"], capture_output=True, text=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _quit_app(run, sleep=time.sleep):
    """Ask the app to quit, only when it is running (asking an app that is not running could start it)."""
    if not _app_running(run):
        return "not running"
    try:
        run(["osascript", "-e", 'tell application id "%s" to quit' % APP_ID], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass
    for _ in range(10):
        if not _app_running(run):
            return "quit"
        sleep(0.5)
    return "still running"


def pick(its, mode, only=()):
    """The items a mode means, in the order they are done. Raises Refused for an id nobody has."""
    if mode == "all":
        chosen = list(its)
    elif mode == "keep-archive":
        chosen = [it for it in its if not it["keep"]]
    else:
        groups, ids = {g for g, _ in GROUPS}, {it["id"] for it in its}
        bad = [o for o in only if o not in groups and o not in ids]
        if bad or not only:
            raise Refused("no such thing to remove: %s. run `python3 -m ctx remove` to see the ids" % (", ".join(bad) or "(nothing named)"))
        chosen = [it for it in its if it["id"] in only or it["group"] in only]
    rank = {"app": 2}      # inside the app group the bundle goes after its settings and caches
    return sorted(chosen, key=lambda it: (ORDER.index(it["group"]), rank.get(it["id"], 1)))


def run(mode, only=(), P=None, dry=False, say=print, kill=os.kill, command=_command, quit_app=None, run=None, claude="", trash_cmd=None,
        sleep=time.sleep, now=None, its=None):
    """Remove what a mode names: "all", "keep-archive" or "only" (with ids). Everything is moved to the Trash.

    Returns {"mode", "dry_run", "done": [{"id", "did", "to"}], "kept": [...], "could_not": [...], "by_hand": [...]}.
    kill, command, quit_app, run, claude, trash_cmd and now exist so tests can stand in for the system: with a made-up
    home and no run given, no outside program is started at all (no claude, no defaults, no osascript, no trash)."""
    P = P or places()
    if not dry:
        _guard(P)
    real = _same(P["home"], real_home()) and _same(os.path.expanduser("~"), real_home())
    outside = run is not None or real             # may we start other programs (claude, defaults, osascript)?
    run = run or subprocess.run
    if trash_cmd is None:                         # the real Trash only for the real home
        trash_cmd = (shutil.which("trash") or "") if real else ""
    its = its if its is not None else items(P, command)
    chosen = pick(its, mode, only)
    chosen_ids = {it["id"] for it in chosen}
    with_folder = []          # in a full removal, what lives in the archive folder goes with it in one move, not piece by piece
    trash = _Trash(P, trash_cmd, run, now)
    done, could_not, extra = [], [], []
    procs = {i: (run_file, pids) for i, run_file, pids in _procs(P)}

    def note(it, did, to=""):
        done.append({"id": it["id"], "did": did, "to": _shown(to, P) if to and to != "the Trash" else to})
        say("%s: %s%s" % (it["id"], did, (" -> " + done[-1]["to"]) if to else ""))

    def fail(it, why, hand):
        could_not.append({"id": it["id"], "why": why, "by_hand": hand})
        say("%s: could not: %s" % (it["id"], why))

    def move(it, found):
        """Move every path of an item to the Trash. True when all went."""
        went, ok = "", True
        if mode == "all" and not dry and found and all(_inside(p, P["ctx_home"]) for p in found):
            with_folder.append(it)
            return True
        for p in found:
            if not os.path.lexists(p):
                continue
            try:
                went = trash.move(p)
            except OSError as e:
                ok = False
                fail(it, "%s would not move (%s)" % (_shown(p, P), e.strerror or type(e).__name__), "move %s to the Trash yourself" % _shown(p, P))
        if ok:
            note(it, "moved to the trash", went)
        return ok

    if not dry and any(it["id"] == "app" for it in chosen) and (quit_app or outside):
        try:
            say("the app: " + str(quit_app() if quit_app else _quit_app(run, sleep)))
        except Exception as e:
            say("the app: could not ask it to quit (%s)" % type(e).__name__)
    for it in chosen:
        kind = it["_kind"]
        if kind == "process":
            run_file, pids = procs[it["id"]]
            if not it["exists"]:
                continue
            for key, pid, word in pids:
                if not pid:
                    continue
                if not word or word not in command(pid):
                    say("%s: process %s is not ours (or is gone): left alone" % (it["id"], pid))
                    continue
                if dry:
                    say("%s: would stop process %s" % (it["id"], pid))
                    continue
                try:
                    kill(int(pid), signal.SIGTERM)
                    say("%s: stopped process %s" % (it["id"], pid))
                except (OSError, ValueError) as e:
                    fail(it, "process %s would not stop (%s)" % (pid, type(e).__name__), "stop it yourself: kill %s" % pid)
            if dry:
                note(it, "would stop it and move its run file to the trash")
            else:
                move(it, it["_paths"])
        elif kind == "mcp":
            if not it["exists"]:
                if "not ours" in it["note"]:
                    say("%s: %s" % (it["id"], it["note"]))
                continue
            if dry:
                note(it, "would take our entry out of " + (it["where"] or ["its config"])[0])
                continue
            got = list(mcp.remove(it["_target"], home=P["home"], claude=claude if outside else None, run=run, say=lambda line: None).values())[0]
            if got == "removed":
                note(it, "our entry taken out (a copy of the file as it was is in backups)")
            else:
                hand = "claude mcp remove context -s user" if it["_target"] == "claude_code" else "take the entry named context out of %s yourself" % (it["where"] or ["its config"])[0]
                fail(it, got, hand)
        elif kind == "host":
            if not it["exists"]:
                if it["note"]:
                    say("%s: %s" % (it["id"], it["note"]))
                continue
            if not _ours_host(it["_host"]):       # looked at again just before it moves
                say("%s: not ours any more: left alone" % it["id"])
                continue
            note(it, "would move to the trash") if dry else move(it, [it["_host"]])
        else:
            if not it["exists"]:
                continue
            if dry:
                note(it, "would move to the trash (%s)" % human(it["bytes"]))
                continue
            ok = move(it, it["_paths"])
            if ok and it["id"] == "app-prefs":
                if outside:      # macos keeps settings in memory too; this clears that copy
                    try:
                        run(["defaults", "delete", APP_ID], capture_output=True, text=True, timeout=30)
                    except (OSError, subprocess.SubprocessError):
                        extra.append("the app's settings may still be remembered until you log out. to clear them now: defaults delete " + APP_ID)
                else:
                    extra.append("the app's settings may still be remembered until you log out. to clear them now: defaults delete " + APP_ID)
            if ok and it["id"] == "launch-agents":
                extra.append("a background job that was already loaded keeps running until you log out")
    # the folders themselves, once everything in them went
    left = []
    if not dry and mode == "all":
        v2, up = P["ctx_home"], os.path.dirname(P["ctx_home"])
        # CTX_HOME may be a link to the folder that holds the archive. moving the link alone would leave every file where it
        # is, so the folder it points to is the one checked for the marker and moved, and then the link, and both are said
        link = os.path.islink(v2)
        real = os.path.realpath(v2) if link else v2
        shown = _shown(v2, P) + (" (a link to %s)" % _shown(real, P) if link else "")
        try:
            rest = os.listdir(real)
        except OSError:
            rest = None
        if rest is not None and not _is_archive(real, rest):
            # CTX_HOME can be pointed anywhere. a folder that does not carry the archive's own marker is never moved whole
            left.append(_shown(v2, P))
            say("the folder %s does not look like a context archive (no .closed marker in it): left where it is" % shown)
        elif rest is not None:
            try:
                where = trash.move(real)
                for it in with_folder:
                    note(it, "moved to the trash, inside the archive folder")
                say("the archive folder %s: moved to the trash -> %s" % (shown, where if where == "the Trash" else _shown(where, P)))
                if link and os.path.lexists(v2):
                    where = trash.move(v2)
                    say("the link %s, which pointed to it: moved to the trash -> %s" % (_shown(v2, P), where if where == "the Trash" else _shown(where, P)))
            except OSError:
                left.append(_shown(v2, P))
        if os.path.basename(up) == ".context" and os.path.isdir(up):
            try:
                for n in os.listdir(up):
                    if n == ".DS_Store":
                        os.remove(os.path.join(up, n))
                os.rmdir(up)
            except OSError:
                left.append("%s (it still holds something that is not ours)" % _shown(up, P))
    if not dry and any(d["id"] in ("api-keys", "remote-secret", "telegram-session") for d in done):
        extra.append("the key file, the remote secret and the telegram sign-in are in the Trash until you empty it. empty the Trash to be rid of them for good")
    kept = [{"id": it["id"], "where": it["where"], "bytes": it["bytes"]} for it in its if it["exists"] and it["id"] not in chosen_ids] if mode == "keep-archive" else []
    hand = by_hand(P) + extra
    return {"mode": mode, "dry_run": dry, "done": done, "kept": kept, "could_not": could_not, "left": left, "by_hand": hand,
            "trash": _shown(trash.folder, P) if trash.folder else ("the Trash" if trash_cmd else "")}


def report(res):
    """The end of a removal, for a person: what was kept, what could not be removed, what only they can do."""
    out = [""]
    if res["dry_run"]:
        out.append("that was a dry run: nothing was changed.")
    elif res["trash"]:
        out.append("everything removed is in %s. to put something back, drag it out again." % ("the Trash" if res["trash"] == "the Trash" else res["trash"]))
    if res["kept"]:
        out.append("")
        out.append("kept (%s):" % human(sum(k["bytes"] for k in res["kept"])))
        out += ["  %s  %s" % (k["id"], ", ".join(k["where"])) for k in res["kept"]]
    if res["could_not"] or res["left"]:
        out.append("")
        out.append("could not remove:")
        out += ["  %s: %s. by hand: %s" % (c["id"], c["why"], c["by_hand"]) for c in res["could_not"]]
        out += ["  still there: " + l for l in res["left"]]
    out += ["", "only you can do these:"] + ["  - " + s for s in res["by_hand"]]
    return "\n".join(out)


def main(argv, P=None, ask=input, out=print, **inject):
    """python3 -m ctx remove [--all | --keep-archive | --only <id>...] [--yes] [--dry-run] [--json]. Returns the exit code."""
    flags = {"--all", "--keep-archive", "--only", "--yes", "--dry-run", "--json"}
    only, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--only":
            if i + 1 >= len(argv) or argv[i + 1].startswith("--"):
                out("--only needs an id. run `python3 -m ctx remove` to see them")
                return 2
            only += [x.strip() for x in argv[i + 1].split(",") if x.strip()]
            i += 1
        elif a not in flags:
            out("remove does not know %s. it takes: --all | --keep-archive | --only <id>, and --yes --dry-run --json" % a)
            return 2
        i += 1
    modes = [m for m, on in (("all", "--all" in argv), ("keep-archive", "--keep-archive" in argv), ("only", bool(only))) if on]
    as_json, dry = "--json" in argv, "--dry-run" in argv
    if len(modes) > 1:
        out("pick one of --all, --keep-archive, --only")
        return 2
    if P is None:
        import tempfile
        P = places(tmp=tempfile.gettempdir())
    if not modes:       # the list. nothing is changed
        d = listing(P, inject.get("command", _command))
        out(json.dumps(d) if as_json else text(d))
        return 0
    mode = modes[0]
    try:
        if not dry:
            _guard(P)
        its = items(P, inject.get("command", _command))
        chosen = pick(its, mode, only)
        if not dry and "--yes" not in argv:
            if as_json:
                out(json.dumps({"error": "add --yes: with --json nobody is there to answer the question"}))
                return 2
            here = [it for it in chosen if it["exists"]]
            out("this will move to the Trash, or take out of other apps' config:")
            out("\n".join("  %-16s %10s  %s" % (it["id"], human(it["bytes"]) if it["bytes"] else "-", it["what"]) for it in here) or "  nothing: none of it is here")
            if mode == "keep-archive":
                out("your data stays where it is.")
            try:
                got = ask("type the word %s to go ahead: " % WORD)
            except EOFError:
                got = ""
            if got.strip().lower() != WORD:
                out("nothing was changed.")
                return 1
        res = run(mode, only, P=P, dry=dry, say=(lambda line: None) if as_json else out, its=its, **inject)
    except Refused as e:
        out(json.dumps({"error": str(e)}) if as_json else str(e))
        return 2
    out(json.dumps(res) if as_json else report(res))
    return 1 if res["could_not"] or res["left"] else 0
