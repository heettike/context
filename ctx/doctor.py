"""`python3 -m ctx doctor`: what this Mac has and lacks, before anything is read.

Run it first on a new computer. It prints one line per thing: ready, needs something (and what), or not on this mac.
It reads no message, note or page. It only checks that files exist and can be opened, asks the model CLIs whether
they are signed in, and looks at browser settings on disk. It makes no request to any site and asks the browser
nothing: whether you are signed in to a site is told from the last read. It sends no Apple events, so macOS shows no
pop-up for it, with one exception: on macOS 14 and later, checking WhatsApp may ask "access data from other apps" once.

Only `doctor --check-sign-in` goes further: through the extension, when it is connected, it asks each signed-in site
for one small page to see whether the session is live. That is a request from your browser to those sites.

    python3 -m ctx doctor          plain text
    python3 -m ctx doctor --check-sign-in      also ask each signed-in site, through the extension, whether the session is live
    python3 -m ctx doctor --json   the same report as one json object
"""
import glob, json, os, platform, plistlib, shutil, subprocess, sys, time
from . import paths

H = os.path.expanduser
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"      # where the mac app looks for python3
MIN_PY, MIN_MACOS = (3, 9), 14                                   # 14: the app's deployment target
FDA_FIX = "system settings > privacy & security > full disk access: switch on the app that runs this, then quit and reopen it"

# (name, app bundle names, data folder under ~/Library/Application Support, can context drive it)
BROWSERS = [("arc", ["Arc"], "Arc/User Data", True), ("brave", ["Brave Browser"], "BraveSoftware/Brave-Browser", True),
            ("chrome", ["Google Chrome"], "Google/Chrome", True), ("chromium", ["Chromium"], "Chromium", False),
            ("dia", ["Dia"], "Dia/User Data", True), ("edge", ["Microsoft Edge"], "Microsoft Edge", True),
            ("opera", ["Opera"], "com.operasoftware.Opera", False), ("vivaldi", ["Vivaldi"], "Vivaldi", False)]       # in the order of the alphabet: none comes first by habit
DRIVEN = ", ".join(n for n, _, _, drive in BROWSERS if drive)        # the ones context can drive, as a list for a sentence
BUNDLES = {"arc": "company.thebrowser.browser", "brave": "com.brave.browser", "chrome": "com.google.chrome", "dia": "company.thebrowser.dia",
           "edge": "com.microsoft.edgemac", "firefox": "org.mozilla.firefox", "safari": "com.apple.safari"}
OTHER = [("firefox", ["Firefox"], "Firefox"), ("zen", ["Zen", "Zen Browser"], "zen"), ("orion", ["Orion"], "Orion")]
PROTECTED = ("Documents", "Desktop", "Downloads", "Library/Mobile Documents")   # macos asks before a terminal reads these


def _state(path):
    """yes | missing | blocked, without reading more than 16 bytes."""
    p = H(path)
    try:
        if os.path.isdir(p):
            os.listdir(p)
        else:
            with open(p, "rb") as f:
                f.read(16)
        return "yes"
    except FileNotFoundError:
        return "missing"
    except (PermissionError, OSError):
        return "blocked"


def _out(args, timeout=20, env=None):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env)
        return (r.stdout or r.stderr).strip()
    except Exception:
        return ""


def _app(names):
    for n in names:
        for root in ("/Applications", H("~/Applications")):
            if os.path.isdir(os.path.join(root, n + ".app")):
                return os.path.join(root, n + ".app")
    return ""


def _full_disk_access():
    """True, False, or None when it cannot be told. The TCC folder is on every Mac and opens only with the grant."""
    for p in ("~/Library/Application Support/com.apple.TCC", "~/Library/Safari", "~/Library/Mail", "~/Library/Messages"):
        s = _state(p)
        if s != "missing":
            return s == "yes"
    return None


def system():
    tools = _out(["xcode-select", "-p"])
    have_tools = bool(tools) and os.path.isdir(tools)
    # on a mac with no command line tools, swiftc, git and /usr/bin/python3 are stubs that open an install window.
    # so they are only run when the tools are there.
    swift = (_out(["swiftc", "--version"]).splitlines() or [""])[0][:80] if have_tools else ""
    app_py = shutil.which("python3", path=APP_PATH) or ""
    app_py_ver = ""
    if app_py and (have_tools or not app_py.startswith("/usr/bin/")):
        # isolated (-I: not the folder doctor runs in, no PYTHON* settings, no user site) and no site-packages (-S: no .pth
        # file runs): homebrew's site-packages can be written by any program running as the owner
        app_py_ver = _out([app_py, "-I", "-S", "-c", "import sys; print(sys.version.split()[0])"])
    macos = platform.mac_ver()[0]
    try:
        free = shutil.disk_usage(paths.HOME).free // 2 ** 30
    except OSError:
        free = None
    bad = []
    for f in sorted(glob.glob(os.path.join(REPO, "ctx", "*.py"))):
        try:
            with open(f, encoding="utf-8") as fh:
                compile(fh.read(), f, "exec")
        except SyntaxError as e:
            bad.append("%s line %s" % (os.path.basename(f), e.lineno))
        except OSError:
            pass
    return {"macos": macos, "macos_ok": bool(macos) and int(macos.split(".")[0]) >= MIN_MACOS, "arch": platform.machine(),
            "python": sys.version.split()[0], "python_path": sys.executable, "python_ok": sys.version_info >= MIN_PY and not bad,
            "python_cannot_parse": bad, "app_python": app_py, "app_python_version": app_py_ver,
            "command_line_tools": tools if have_tools else "", "swiftc": swift, "git": bool(have_tools and shutil.which("git")),
            "repo": REPO, "repo_on_external_volume": REPO.startswith("/Volumes/"), "archive": paths.HOME, "disk_free_gb": free,
            "timezone": time.strftime("%Z"), "shell": os.path.basename(os.environ.get("SHELL", "")),
            "terminal": os.environ.get("TERM_PROGRAM", ""), "full_disk_access": _full_disk_access()}


def _default_browser():
    try:
        with open(H("~/Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist"), "rb") as f:
            for h in plistlib.load(f).get("LSHandlers", []):
                if h.get("LSHandlerURLScheme") == "https":
                    return (h.get("LSHandlerRoleAll") or "").lower()
    except Exception:
        pass
    return "com.apple.safari"      # no entry means the default was never changed


def _launch(name):
    from . import request
    return request._launch(BUNDLES.get(name, ""))


def _scripting(name, root):
    """Is 'allow javascript from apple events' on? Read from disk and from the process list; the browser is not asked."""
    if _launch(name):                # a browser that takes page scripting as an option it is started with (request.QUIRKS)
        from . import request
        app = next((apps[0] for n, apps, _, _ in BROWSERS if n == name), name)
        ps = _out(["ps", "-axo", "command"])
        return any("%s.app/Contents/MacOS/%s " % (app, app) in l and request.SCRIPT_FLAG in l for l in ps.splitlines())
    try:
        with open(os.path.join(root, "Local State"), encoding="utf-8") as f:
            last = json.load(f).get("profile", {}).get("last_used", "Default")
        with open(os.path.join(root, last, "Preferences"), encoding="utf-8") as f:
            return bool(json.load(f).get("browser", {}).get("allow_javascript_apple_events"))
    except Exception:
        return False


def browsers():
    from . import bridge
    appdata = os.environ.get("CTX_BROWSER_DATA", H("~/Library/Application Support"))
    default, out = _default_browser(), []
    bundles = BUNDLES
    linked = bridge.connected()
    for name, apps, data, drive in BROWSERS:
        root = os.path.join(appdata, data)
        if not (_app(apps) or os.path.isdir(root)):
            continue
        hist = [_state(p) for p in glob.glob(os.path.join(glob.escape(root), "*", "History"))]
        b = {"name": name, "default": bundles.get(name) == default, "history": "ready" if "yes" in hist else "needs: open it once" if not hist else "needs: " + FDA_FIX,
             "profiles": len(hist), "signed_in_reads": "not supported: history only", "export_requests": "not supported"}
        if drive:
            on = _scripting(name, root)
            script = ("page scripting. python3 -m ctx request --enable-browser switches it on, and THAT COMMAND QUITS %s and reopens it (tabs come back)" % name.upper() if _launch(name)
                      else "page scripting. in %s: view > developer > allow javascript from apple events" % name)
            # the extension first: it reads in the background and quits nothing. page scripting is the other way in
            fix = ("the context extension: python3 -m ctx bridge --install, then load the extension/ folder at chrome://extensions "
                   "(developer mode > load unpacked). it reads in background tabs and quits nothing. or " + script)
            host = os.path.isfile(os.path.join(root, "NativeMessagingHosts", bridge.NAME + ".json"))
            via = "the context extension, in the background" if linked and host else \
                "page scripting (it reads a tab you already have open; CTX_OPEN_TABS=1 lets it open one)" if on else ""
            b["page_scripting"], b["extension_helper"] = on, host
            b["signed_in_reads"] = ("ready, through " + via) if via else "needs: " + fix
            b["export_requests"] = "ready" if on else "needs: " + script + ". the extension only reads; asking a site for an export presses its button"
        out.append(b)
    if _app(["Safari"]):
        s = _state("~/Library/Safari/History.db")
        out.append({"name": "safari", "default": default == "com.apple.safari", "profiles": 1,
                    "history": {"yes": "ready", "blocked": "needs: " + FDA_FIX, "missing": "needs: open it once"}[s],
                    "signed_in_reads": "not supported: safari has no way in yet", "export_requests": "not supported"})
    for name, apps, data in OTHER:
        if _app(apps) or os.path.isdir(os.path.join(appdata, data)):
            out.append({"name": name, "default": bundles.get(name) == default, "profiles": 0, "history": "not supported",
                        "signed_in_reads": "not supported", "export_requests": "not supported"})
    return out


def model():
    from . import llm
    st = llm.status()
    try:
        from . import models
        jobs = models.line(st)
    except Exception:
        jobs = ""
    return {"using": st["using"], "plan": st["plan"], "fix": st["fix"], "api_key": st["api_key"], "jobs": jobs,
            "claude": {k: st["claude"].get(k) for k in ("installed", "signed_in", "path")},
            "codex": {k: st["codex"].get(k) for k in ("installed", "signed_in", "path")}}


def _telegram():
    from . import llm  # loads .env
    try:
        import telethon  # noqa: F401
        have = True
    except ImportError:
        from . import paths as _paths
        have = any(os.path.isdir(os.path.join(p, "telethon")) for p in _paths.venv_sites())
    if not have:
        return "needs: python3 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements-telegram.txt (in the repo folder)"
    if not os.environ.get("TELEGRAM_API_ID") or not os.environ.get("TELEGRAM_API_HASH"):
        return "needs: TELEGRAM_API_ID and TELEGRAM_API_HASH in .env (my.telegram.org > api development tools)"
    if not os.path.exists(os.path.join(paths.HOME, "telegram.session")):
        return "needs: a sign-in: the telegram card on the sources page (from a checkout: python3 -m ctx telegram-login)"
    if not os.path.exists(os.path.join(paths.HOME, "imports", "telegram_full.jsonl")):
        return "needs: the first full read, which takes hours: sync now on the sources page (from a checkout: python3 -m ctx collect-telegram)"
    return "ready"


def _obsidian():
    try:
        with open(H("~/Library/Application Support/obsidian/obsidian.json"), encoding="utf-8") as f:
            vaults = [v.get("path", "") for v in (json.load(f).get("vaults") or {}).values() if isinstance(v, dict)]
    except FileNotFoundError:
        return "not on this mac"
    except (OSError, ValueError, AttributeError):
        return "needs: obsidian's list of vaults could not be read"
    if not vaults:
        return "needs: a vault (obsidian is installed but has none)"
    home = H("~") + "/"
    asks = sorted({d.split("/")[-1].lower() for v in vaults for d in PROTECTED if v.startswith(home + d + "/") or v == home + d})
    return "ready" + (" (macos will ask once to read your %s folder)" % " and ".join("icloud drive" if a == "mobile documents" else a for a in asks) if asks else "")


def _last_reads():
    """How each signed-in source did on the last daily read, from the scheduler's own record."""
    try:
        with open(os.path.join(paths.HOME, "schedule.json")) as f:
            got = json.load(f).get("daily_results")
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def sources(sys_, browsers_, ask=False):
    """One line per source in collect.TABLE order: ready | needs: <what> | not on this mac."""
    from . import collect, local_apps
    fda = sys_["full_disk_access"]

    def local(path, absent="not on this mac", blocked=FDA_FIX):
        s = _state(path)
        return "ready" if s == "yes" else ("needs: " + blocked) if s == "blocked" else absent

    def guarded(path, absent):
        """Inside a folder macOS hides without full disk access: a missing file cannot be told from a hidden one."""
        s = _state(path)
        if s == "yes":
            return "ready"
        return "needs: " + FDA_FIX if s == "blocked" or fda is False else absent

    def imported(*names):
        return any(os.path.exists(os.path.join(paths.HOME, "imports", n)) for n in names)

    def export(kind, what):
        return "ready" if glob.glob(os.path.join(paths.HOME, "imports", kind + "-*")) else \
            "needs: %s. ask for it: python3 -m ctx request %s. when the zip is in downloads: python3 -m ctx ingest" % (what, kind)

    drive = [b for b in browsers_ if b.get("signed_in_reads", "").startswith("ready")]

    def signed(name, site, probe=None):
        """A source read through a signed-in browser. The browser being ready says nothing about being signed in to the
        site, so say only what is known: the extension's own check when it is connected, else how the last read went."""
        if not drive:
            return web
        where = drive[0]["name"]
        last = (_last_reads().get(name) or {}).get("state")
        if probe and ask:           # only when asked: this is a request from the browser to the site
            try:
                from . import bridge
                if bridge.connected():
                    r = bridge.submit({"type": "fetch", "url": probe, "max": 200}, timeout=15, pickup=5)
                    ok = not r.get("away") and r.get("status") == 200
                    return "ready, in %s (signed in to %s: checked now)" % (where, site) if ok else "needs: sign in to %s in %s" % (site, where)
            except Exception:
                pass                            # the check could not be made: fall back to what the last read showed
        if last == "ok":
            return "ready, in %s (signed in to %s when it was last read)" % (where, site)
        if last == "needs_you":
            return "needs: sign in to %s in %s (the last read found no session)" % (site, where)
        return "ready, in %s if you are signed in to %s there (not checked yet: python3 -m ctx tick daily reads it)" % (where, site)
    can = [b for b in browsers_ if "page_scripting" in b]
    if drive:
        web = "ready, in " + drive[0]["name"]
    elif can:
        web = can[0]["signed_in_reads"]
    else:
        web = "needs: one of %s, signed in to the site (safari and firefox cannot be read yet)" % DRIVEN
    chromium = [n for n, _ in local_apps.chromium_profiles()]
    out = {
        "whatsapp": local("~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite",
                          "needs: open whatsapp once and let it sync" if _app(["WhatsApp"]) else "not on this mac",
                          "allow 'access data from other apps' when macos asks, or switch on full disk access"),
        "imessage": guarded("~/Library/Messages/chat.db", "not on this mac (messages was never used here)"),
        "telegram": _telegram(),
        "slack": "ready (saved read)" if imported("slack.jsonl") and not drive else signed("slack", "slack", "https://app.slack.com/client"),
        "email": guarded("~/Library/Mail", "not on this mac (apple mail is not set up; gmail can come from google takeout)"),
        "claude_code": local("~/.claude/projects"), "codex": local("~/.codex/sessions"),
        "cursor": local("~/Library/Application Support/Cursor/User/globalStorage/state.vscdb"),
        "grok_bot": local("~/Library/Application Support/Grok Bot/sand-client-persistence"),
        "claude_history": local("~/.claude/history.jsonl"),
        "contacts": guarded("~/Library/Application Support/AddressBook", "not on this mac"),
        "reminders": guarded("~/Library/Group Containers/group.com.apple.reminders", "not on this mac"),
        "calls": guarded("~/Library/Application Support/CallHistoryDB/CallHistory.storedata", "not on this mac"),
        "voice_memos": guarded("~/Library/Group Containers/group.com.apple.VoiceMemos.shared", "not on this mac"),
        "browser_history": ("ready: " + ", ".join(dict.fromkeys(chromium))) if chromium else "not on this mac (no chromium browser: arc, brave, chrome, dia, edge, vivaldi)",
        "safari_history": guarded("~/Library/Safari/History.db", "not on this mac"),
        "journal": "ready" if glob.glob(os.path.join(paths.HOME, "journal", "*.md")) else "needs: something written in the app's plan tab",
        "obsidian": _obsidian(),
        "apple_notes": guarded("~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite", "not on this mac (notes was never opened)"),
        "x_bookmarks": "ready (saved read)" if imported("bookmarks.json") and not drive else signed("x_bookmarks", "x"),
        "gdrive": "ready (saved read)" if imported("gdrive.jsonl") and not drive else signed("gdrive", "google drive"),
        "calendar": "ready (saved read)" if imported("calendar.jsonl") else "needs: allow 'control calendar' when macos asks (first read takes about ten minutes)",
        "x_dms": export("x", "your x archive"), "x_archive": export("x", "your x archive"),
        "instagram": export("instagram", "your instagram export"), "instagram_saved": export("instagram", "your instagram export"),
        "instagram_likes": export("instagram", "your instagram export"),
        "linkedin": export("linkedin", "your linkedin export"), "linkedin_connections": export("linkedin", "your linkedin export"),
        **{"linkedin_" + x: export("linkedin", "your complete linkedin export") for x in ("posts", "comments", "articles", "invitations", "recommendations", "saved", "likes", "searches", "profile")},
        "gmail_takeout": export("google", "a google takeout with mail"), "google_takeout": export("google", "a google takeout"),
        "chatgpt_export": export("chatgpt", "your chatgpt export"), "notion": export("notion", "your notion export"),
    }
    if out["apple_notes"].startswith("needs") and fda is False:
        out["apple_notes"] = "needs: full disk access, or allow 'control notes' when macos asks"
    order = [n for n, _, _ in collect.TABLE if n in out]
    return {n: out[n] for n in order + [k for k in out if k not in order]}


def report(ask=False):
    sys_ = system()
    br = browsers()
    try:
        from . import semantic
        search = semantic.embedder_report()
        if not str(search.get("better") or "").startswith("python3 -m ctx"):     # the check-up tells nobody to install another program; `index --help` is where that lives
            search["better"] = ""
    except Exception:
        search = {}
    return {"system": sys_, "model": model(), "browsers": br, "sources": sources(sys_, br, ask), "search": search,
            # the keys the first doctor printed, kept for anything that reads them
            "macos": sys_["macos"], "arch": sys_["arch"], "python": sys_["python"], "python_ok": sys_["python_ok"],
            "full_disk_access": bool(sys_["full_disk_access"]), "repo": REPO, "archive": paths.HOME}


def render(r):
    s, m, L = r["system"], r["model"], []
    def row(k, v):
        L.append("  %-18s %s" % (k, v))
    L.append("this mac")
    row("macos", "%s on %s%s" % (s["macos"] or "unknown", s["arch"], "" if s["macos_ok"] else "  (the app needs macos %d or later; the engine may still run)" % MIN_MACOS))
    if s["python_cannot_parse"]:
        row("python", "%s at %s: too old, it cannot read %s. install python 3.9 or later" % (s["python"], s["python_path"], ", ".join(s["python_cannot_parse"][:3])))
    else:
        row("python", "%s at %s%s" % (s["python"], s["python_path"], "" if s["python_ok"] else ": too old, needs %d.%d or later" % MIN_PY))
    if s["app_python"] and os.path.realpath(s["app_python"]) != os.path.realpath(s["python_path"]):
        row("python for the app", "%s %s (the app runs the first python3 in %s)" % (s["app_python"], s["app_python_version"] or "", APP_PATH))
    elif not s["app_python_version"] and not s["command_line_tools"]:
        row("python for the app", "missing: the app runs python3 from %s. install the command line tools" % APP_PATH)
    row("build tools", ("ready: " + s["swiftc"]) if s["swiftc"] else "needs: xcode-select --install (for app/build.sh; the engine runs without it)")
    fda = s["full_disk_access"]
    who = (" for " + s["terminal"].lower()) if s["terminal"] else ""
    row("full disk access", "on" + who if fda else ("off%s. %s" % (who, FDA_FIX)) if fda is False else "cannot tell on this mac")
    row("repo", s["repo"] + ("  (on an external volume: the app and other tools lose the engine when it is unplugged)" if s["repo_on_external_volume"] else ""))
    row("archive", "%s%s" % (s["archive"], "" if s["disk_free_gb"] is None else "  (%d gb free)" % s["disk_free_gb"]))
    row("timezone", s["timezone"] + "  (hours and days in facts are counted in this zone)")
    L.append("")
    L.append("model (the ai plan the reading runs on)")
    for name in ("claude", "codex"):
        c = m[name]
        row(name, "signed in" if c["signed_in"] else "installed, not signed in" if c["installed"] else "not on this mac")
    row("using", "%s: %s" % (m["using"], m["plan"]) if m["using"] != "none" else "nothing yet. collecting works without it; answers and the read-through do not")
    if m.get("jobs") and m["using"] != "none":
        row("models", m["jobs"])
    if m["fix"]:
        row("to fix", m["fix"])
    e = r.get("search") or {}
    if e:
        L.append("")
        L.append("search by meaning")
        row("embedder", "%s: %s" % (e.get("embedder"), e.get("quality")))
        row("index", ("%s units, %s with vectors%s" % (e.get("units"), e.get("vectors"), "  (built with %s: run python3 -m ctx index)" % e["indexed_with"] if e.get("needs_index") else ""))
            if e.get("units") else "none yet: python3 -m ctx index")
    L.append("")
    L.append("browsers")
    if not r["browsers"]:
        row("none found", "history, slack, drive, x bookmarks and export requests need one of: " + DRIVEN)
    for b in r["browsers"]:
        L.append("  %s%s" % (b["name"], "  (default)" if b.get("default") else ""))
        row("  history", b["history"])
        row("  signed-in reads", b["signed_in_reads"])
        row("  export requests", b["export_requests"])
    L.append("")
    L.append("sources")
    for k, v in r["sources"].items():
        row(k, v)
    n = sum(1 for v in r["sources"].values() if v.startswith("ready"))
    L.append("")
    L.append("%d of %d sources ready. next: python3 -m ctx collect" % (n, len(r["sources"])))
    web = [k for k in ("slack", "gdrive", "x_bookmarks", "calendar") if r["sources"].get(k, "").startswith(("ready, in", "needs: allow"))]
    if web:      # collect reads files only; these come through the browser or an app, on the daily read
        L.append("%s: python3 -m ctx tick daily  (it talks to your browser and the calendar app; macos may ask to allow it)" % ", ".join(web))
    return "\n".join(L)


def main(argv):
    r = report(ask="--check-sign-in" in argv)
    print(json.dumps(r, indent=1) if "--json" in argv else render(r))
    if not r["system"]["python_ok"]:
        sys.exit(1)
