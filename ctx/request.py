"""Ask each service for the owner's official data export, in the browser they are already signed in to.

The only thing this clicks is "request my own export". It never reads, types or stores a password or a code:
when a site asks for one it stops, leaves that tab in front and reports `needs_you`. Page text is only matched
against fixed patterns; none of it is printed or saved.

    python3 -m ctx request --list            every service: its state, what it will ask you for, and which ways into the browser are ready
    python3 -m ctx request <id>              ask that service for your export now (ids: x google instagram linkedin chatgpt notion)
    python3 -m ctx request --check <id>      look only: is an export already pending on the site? presses nothing
    python3 -m ctx request --decline <id>    never ask this service; nothing is driven or said for it
    python3 -m ctx request --reset <id>      forget its state (undoes a decline, or a request that failed)
    python3 -m ctx request --enable-browser  switch page scripting on (a browser that takes it as a launch option is quit and reopened; tabs come back)
    python3 -m ctx request --link-extension chatgpt   copy the chatgpt extension's helper file into this browser
"""
import glob, json, os, plistlib, shutil, subprocess, sys, time
from datetime import datetime, timezone
from . import paths

STATE = os.path.join(paths.HOME, "requests.json")
IMPORTS = os.path.join(paths.HOME, "imports")

# ---------------------------------------------------------------- browser

# The Chromium browsers, by name. All share Chrome's AppleScript dictionary (windows, tabs, URL, `execute <tab> javascript`)
# and all are treated alike: none is preferred, and where two would do, the order here (the alphabet) decides.
BROWSERS = [("Arc", "company.thebrowser.Browser", "Arc/User Data"),
            ("Brave Browser", "com.brave.Browser", "BraveSoftware/Brave-Browser"),
            ("Dia", "company.thebrowser.dia", "Dia/User Data"),
            ("Google Chrome", "com.google.Chrome", "Google/Chrome"),
            ("Microsoft Edge", "com.microsoft.edgemac", "Microsoft Edge")]
# Where one of them differs from the rest, the difference is written here once, by bundle id, and the code below asks this table.
# "launch": page scripting is an option the browser is started with, not a menu item kept in its profile.
# "focus": the AppleScript that brings a tab to the front, where it is not the shared one.
QUIRKS = {"company.thebrowser.dia": {"launch": True, "focus": "focus t"}}
SCRIPT_FLAG = "--enable-applescript-javascript"
AWAKE_FLAGS = ["--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding", "--disable-background-timer-throttling"]   # keep hidden tabs rendering
FOCUS = "set active tab index of w to i\n            set index of w to 1"
APPDATA = os.environ.get("CTX_BROWSER_DATA", os.path.expanduser("~/Library/Application Support"))   # where browsers keep profiles
EXTENSIONS = [("claude_extension", "claude", "fcoeoabgfenejglbffodgkkbkcdhcgfn"),
              ("chatgpt_extension", "chatgpt", "hehggadaopoacecdllhhajmbjkdcmajg")]
CODEX_HOST = "com.openai.codexextension.json"   # tells a browser where the ChatGPT extension's local helper is
HOST_SOURCES = sorted({b[2] for b in BROWSERS} | {"Chromium"})      # any chromium browser's folder may hold it
MENU = "in {0}: view > developer > allow javascript from apple events"


def osa(script, *args, timeout=60):
    r = subprocess.run(["osascript", "-", *args], input=script, capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:200])
    return r.stdout.rstrip("\n")


def _installed(bundle):
    """Spotlight knows every copy of an app. It can be switched off, so the usual folders are checked too."""
    try:
        r = subprocess.run(["mdfind", f"kMDItemCFBundleIdentifier == '{bundle}'"], capture_output=True, text=True, timeout=10)
        if r.stdout.strip():
            return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    name = next((b[0] for b in BROWSERS if b[1] == bundle), "")
    return any(os.path.isdir(os.path.join(root, name + ".app")) for root in ("/Applications", os.path.expanduser("~/Applications")))


def _running(name):
    return subprocess.run(["pgrep", "-x", name], capture_output=True).returncode == 0


def _default_bundle():
    try:
        p = os.path.expanduser("~/Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist")
        with open(p, "rb") as f:
            handlers = plistlib.load(f).get("LSHandlers", [])
        for h in handlers:
            if h.get("LSHandlerURLScheme") == "https":
                return h.get("LSHandlerRoleAll", "")
    except Exception:
        pass
    return ""


def pick():
    """The default browser if it is one we can drive, else one that is running, else one that is installed."""
    default = _default_bundle().lower()
    have = [b for b in BROWSERS if _installed(b[1])]
    for test in (lambda b: b[1].lower() == default, lambda b: _running(b[0]), lambda b: True):
        for b in have:
            if test(b):
                return b
    return None


def _launch(bundle):
    """Does this browser take page scripting as a launch option (so it can be switched on by reopening it)?"""
    return bool(QUIRKS.get(bundle, {}).get("launch"))


def _scripting(name, bundle, data_dir, ask=False):
    """Can AppleScript run JavaScript in a page? Either a menu item, stored in the profile, or (QUIRKS "launch") an option the browser was started with.
    ask=True also asks a running browser itself, which sends it an Apple event and can raise macos's "wants to control"
    prompt: only when the owner has started something that drives the browser anyway. A listing never does."""
    if _launch(bundle):
        ps = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True).stdout
        return any("%s.app/Contents/MacOS/%s " % (name, name) in l and SCRIPT_FLAG in l for l in ps.splitlines())
    if ask and _running(name):   # ask the browser itself: run `1` in the front tab
        try:
            osa(f'tell application id "{bundle}" to execute (active tab of front window) javascript "1"', timeout=10)
            return True
        except Exception as e:
            if "turned off" in str(e) or "Apple Events" in str(e):
                return False
    try:
        root = os.path.join(APPDATA, data_dir)
        last = paths.read_json(os.path.join(root, "Local State")).get("profile", {}).get("last_used", "Default")
        prefs = paths.read_json(os.path.join(root, last, "Preferences"))
        return bool(prefs.get("browser", {}).get("allow_javascript_apple_events"))
    except Exception:
        return False


def ways(b):
    """Two different things a browser can be ready for, said apart, so nothing shows "on" for the wrong one:
    reading   signed-in sources are read (slack, drive, x, chatgpt): through the extension, or through page scripting
    asking    an export is asked for by pressing the site's own button: page scripting only. the extension only reads
    {"can_read", "reads_through": "extension" | "page scripting" | "", "can_request", "request_needs": what to switch on, or ""}"""
    try:
        from . import bridge
        ext = bool(bridge.connected())
    except Exception:
        ext = False
    script = bool(b.get("scripting"))
    return {"can_read": ext or script, "reads_through": "extension" if ext else "page scripting" if script else "",
            "can_request": script, "request_needs": "" if script else b.get("how_to_enable", "")}


def browser(ask=False):
    """The browser that would be driven, and what it is ready for. ask: see _scripting; listings leave it False."""
    b = pick()
    if not b:
        out = {"name": "", "scripting": False, "how_to_enable": "install a chromium browser (%s) and sign in to your accounts there" % ", ".join(b[0].lower() for b in BROWSERS)}
        return dict(out, **ways(out))
    name, bundle, data_dir = b
    ok = _scripting(name, bundle, data_dir, ask)
    how = "" if ok else ("run: python3 -m ctx request --enable-browser (quits %s and reopens it with page scripting on; your tabs come back)" % name.lower()
                         if _launch(bundle) else MENU.format(name.lower()))
    out = {"name": name, "scripting": ok, "how_to_enable": how, "routes": routes(name, data_dir, ok, bundle)}
    return dict(out, **ways(out))


def _host_source():
    return next((p for p in (os.path.join(APPDATA, d, "NativeMessagingHosts", CODEX_HOST) for d in HOST_SOURCES) if os.path.isfile(p)), None)


def routes(name, data_dir, scripting, bundle=""):
    """Every way context could drive this browser, best first. Only applescript is used today; the rest are reported, not spoken to."""
    low, root = name.lower(), os.path.join(APPDATA, data_dir)
    bundle = bundle or next((b[1] for b in BROWSERS if b[0] == name), "")
    out = [{"id": "applescript", "ready": scripting, "one_click": _launch(bundle),
            "fix": "" if scripting else ("quit and reopen %s with page scripting on" % low if _launch(bundle) else MENU.format(low))}]
    for rid, label, ext in EXTENSIONS:
        installed = bool(glob.glob(os.path.join(root, "*", "Extensions", ext)))
        fix, one = ("" if installed else f"install the {label} extension in {low}"), False
        if rid == "chatgpt_extension" and installed and not os.path.isfile(os.path.join(root, "NativeMessagingHosts", CODEX_HOST)):
            installed, one = False, bool(_host_source())
            fix = f"copy the codex host file into {low}'s folder" if one else "install the chatgpt desktop app, which brings the helper this extension talks to"
        out.append({"id": rid, "ready": installed, "fix": fix, "one_click": one})
    return out


def link_extension(which):
    """Register the ChatGPT extension's existing local helper with this browser: copy its manifest from another chromium browser on this mac.
    Never replaces a different file that is already there."""
    b = pick()
    if which != "chatgpt" or not b:
        raise SystemExit("usage: python3 -m ctx request --link-extension chatgpt")
    src, dest = _host_source(), os.path.join(APPDATA, b[2], "NativeMessagingHosts", CODEX_HOST)
    if not src:
        print("no codex host file in another chromium browser on this mac to copy", file=sys.stderr)
    elif os.path.exists(dest):
        if paths.read_text(dest, "rb") != paths.read_text(src, "rb"):
            print("a different codex host file is already in %s's folder; left as it is" % b[0].lower(), file=sys.stderr)
    elif paths.read_json(src).get("name") + ".json" == CODEX_HOST:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(src, dest)
    return browser()


def enable_browser():
    """Switch page scripting on in the browser that would be driven, whichever it is. One that takes it as a launch option
    is quit and reopened with it; for the others the owner uses the browser's own menu, and browser() says which item."""
    b = pick()
    if b and _launch(b[1]) and not _scripting(*b):
        if _running(b[0]):
            osa('tell application id "%s" to quit' % b[1])
            for _ in range(40):
                if not _running(b[0]):
                    break
                time.sleep(0.5)
        subprocess.run(["open", "-b", b[1], "--args", SCRIPT_FLAG, *AWAKE_FLAGS])
        for _ in range(40):
            time.sleep(0.5)
            if _scripting(*b):
                break
    return browser()


# One script for every tab operation; the tab is found by the id the browser gave it when we opened it.
TAB = '''on run argv
  set op to item 1 of argv
  tell application id "%s"
    if op is "open" then
      if (count of windows) is 0 then error "no browser window is open"
      set t to make new tab at end of tabs of front window with properties {URL:item 2 of argv}
      return (id of t) as text
    end if
    repeat with w in windows
      repeat with i from 1 to count of tabs of w
        set t to tab i of w
        if ((id of t) as text) is item 2 of argv then
          if op is "js" then return (execute t javascript (item 3 of argv))
          if op is "url" then return URL of t
          if op is "go" then
            set URL of t to item 3 of argv
            return ""
          end if
          if op is "close" then
            close t
            return ""
          end if
          if op is "front" then
            %s
            activate
            return ""
          end if
        end if
      end repeat
    end repeat
    error "tab is gone"
  end tell
end run'''

LIB = r'''
var vis=function(e){return e.getClientRects().length>0};
var all=function(root,sel){return [].slice.call((root||document).querySelectorAll(sel)).filter(vis)};
var txt=function(e){return (e.innerText||e.getAttribute('aria-label')||'').trim().replace(/\s*\n\s*/g,' / ')};
var top=function(){var d=all(document,'[role=dialog]');return d[d.length-1]||document.body};
var body=function(){return (document.body&&document.body.innerText)||''};
var press=function(e){['mousedown','mouseup'].forEach(function(t){e.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window}))});e.click()};
var CTL='button,[role=button],[role=listitem],[role=option],[role=menuitem],[role=tab],label';
var find=function(root,want,sel){var m=all(root,sel||CTL).filter(function(e){var t=txt(e);return want instanceof RegExp?want.test(t):t===want});return m[m.length-1]};
var hit=function(root,want,sel){var e=find(root,want,sel);if(!e||e.disabled||e.getAttribute('aria-disabled')==='true')return false;press(e);return true};
var row=function(r){var p=r,t='';for(var i=0;i<8&&p;i++){p=p.parentElement;t=p?txt(p):'';if(t)break}return t};
var radio=function(root,want){var r=all(root,'input[type=radio]').filter(function(r){return row(r).indexOf(want)===0})[0];if(!r)return false;if(!r.checked)r.click();return r.checked};
'''
WALL = '''var u=location.host+location.pathname;
if(all(document,'input[type=password]').length) return 'password';
if(/mfa|two-?factor|2fa|otp|challenge|checkpoint/i.test(u)||all(document,'input[autocomplete=one-time-code]').length) return 'code';
if(/(^|\\/)(login|signin|sign-in|log-in|signup)(\\/|$)|accounts\\.google\\.com|auth\\.openai\\.com|i\\/flow\\/login/i.test(u)) return 'login';
return '';'''


class Needs(Exception):   # the site wants the person: "password", "code" or "login"
    pass


class Fail(Exception):
    pass


class Tab:
    def __init__(self, name, bundle, url):
        self.browser, self.script = name, TAB % (bundle, QUIRKS.get(bundle, {}).get("focus") or FOCUS)
        self.id = osa(self.script, "open", url)
        time.sleep(3)

    def _do(self, op, *a):
        return osa(self.script, op, self.id, *a)

    def js(self, body):
        """Run a function body in the page. Returns whatever it returns (JSON-safe values only)."""
        code = "(function(){%s try{return JSON.stringify({v:(function(){%s})()})}catch(e){return JSON.stringify({err:String(e)})}})()" % (LIB, body)
        out = ""
        for _ in range(10):   # a tab that is still loading answers with nothing
            out = self._do("js", code)
            if out:
                break
            time.sleep(1)
        for _ in range(2):   # some browsers hand the string back JSON-quoted, some hand it back bare
            if isinstance(out, str):
                try:
                    out = json.loads(out)
                except ValueError:
                    break
        if not isinstance(out, dict) or "err" in out:
            raise Fail("the page did not answer a script")
        return out.get("v")

    def check(self):
        w = self.js(WALL)
        if w:
            raise Needs(w)

    def wait(self, body, secs=20, why="the page did not get to the next step"):
        """Re-read the page until the function body returns something truthy. Stops at once if the site asks for the person."""
        end = time.monotonic() + secs          # time awake: a mac that slept has not been waiting on the page
        while True:
            self.check()
            v = self.js(body)
            if v:
                return v
            if time.monotonic() > end:
                raise Fail(why)
            time.sleep(1)

    def said(self, rx):
        return bool(self.js("return /%s/i.test(body())" % rx))

    def go(self, url):
        self._do("go", url)
        time.sleep(3)

    def front(self):
        try:
            self._do("front")
        except Exception:
            pass

    def close(self):
        try:
            self._do("close")
        except Exception:
            pass


# ---------------------------------------------------------------- the six flows
# Each returns when the site itself shows the request as filed, and each looks for "already filed" before clicking.

GOOGLE_PRODUCTS = ["Mail", "Calendar", "Contacts", "Keep", "Tasks", "Chrome", "My Activity", "YouTube and YouTube Music"]   # no Drive, no Photos
YOUTUBE_PARTS = ["comments", "history", "playlists", "subscriptions"]   # no videos
TAKEOUT_BUSY = "Google is creating a copy|Export in progress"


def google_pending(t):
    t.wait("return /status of the requests|Create new request|Export in progress/i.test(body())", why="takeout's list of exports did not load")
    return t.said(TAKEOUT_BUSY)


def google(t):
    t.go("https://takeout.google.com/settings/takeout")
    boxes = "all(document,'input[type=checkbox]').filter(function(c){return /^Select /.test(c.getAttribute('aria-label')||'')})"
    t.wait(f"return {boxes}.length>20", why="takeout's product list did not load")
    if t.said("Google is creating a copy"):
        return
    if not t.js("return hit(document,'Deselect all','button,[role=button]')"):
        raise Fail("takeout has no 'deselect all' button any more")
    t.wait(f"return {boxes}.filter(function(c){{return c.checked}}).length===0", why="takeout did not clear the selection")
    want = json.dumps(["Select " + p for p in GOOGLE_PRODUCTS])
    t.js(f"var w={want};{boxes}.forEach(function(c){{if(w.indexOf(c.getAttribute('aria-label'))>=0&&!c.checked)c.click()}});return 1")
    time.sleep(1)
    on = t.js(f"return {boxes}.filter(function(c){{return c.checked}}).map(function(c){{return c.getAttribute('aria-label')}})")
    if sorted(on) != sorted(json.loads(want)):
        raise Fail("takeout's product list changed; could not select exactly mail, calendar, contacts, keep, tasks, chrome, my activity, youtube")
    # YouTube: history, subscriptions, playlists and comments only. If the options button is missing, the default stays.
    if t.js("return hit(document,/All YouTube data included/i,'button,[role=button]')"):
        dlg = "all(document,'[role=dialog]').filter(function(d){return /YouTube and YouTube Music content options/.test(d.innerText)})[0]"
        t.wait(f"var d={dlg};return d&&all(d,'input[type=checkbox]').length>5")
        parts = json.dumps(YOUTUBE_PARTS)
        t.js(f"var w={parts};all({dlg},'input[type=checkbox]').forEach(function(c){{var s=w.indexOf(row(c).split(' / ')[0])>=0;if(c.checked!==s)c.click()}});return 1")
        time.sleep(1)
        got = t.js(f"return all({dlg},'input[type=checkbox]').filter(function(c){{return c.checked}}).map(function(c){{return row(c).split(' / ')[0]}})")
        if sorted(got) != YOUTUBE_PARTS:
            raise Fail("takeout's youtube options changed; nothing was requested")
        t.js(f"return hit({dlg},'OK','button,[role=button]')")
        t.wait("return all(document,'[role=dialog]').length===0")
    if not t.js("return hit(document,/Next step/i,'button,[role=button]')"):
        raise Fail("takeout has no 'next step' button any more")
    size = "document.querySelector('[role=combobox][aria-label=\"File size select\"]')"
    t.wait(f"return !!{size}", why="takeout's delivery step did not load")
    ok = t.js("""var once=all(document,'input[type=radio]').filter(function(r){return row(r).indexOf('Export once')===0})[0];
        var c=all(document,'[role=combobox]').map(txt);
        return !!(once&&once.checked)&&c.indexOf('Send download link via email')>=0&&c.indexOf('.zip')>=0""")
    if not ok:
        raise Fail("takeout's defaults are not 'export once, .zip, link by email'; nothing was requested")
    t.js(f"press({size});return 1")
    t.wait("return all(document,'[role=option]').filter(function(o){return /^\\d+ GB$/.test(txt(o))}).length>1")
    t.js("""var o=all(document,'[role=option]').filter(function(o){return /^\\d+ GB$/.test(txt(o))});
        o.sort(function(a,b){return parseInt(txt(a))-parseInt(txt(b))});press(o[o.length-1]);return 1""")   # biggest parts, so fewer files
    time.sleep(2)
    if not t.js("return hit(document,'Create export','button,[role=button]')"):
        raise Fail("takeout has no 'create export' button any more")
    t.wait("return /Google is creating a copy/i.test(body())", 30, "takeout did not confirm the export")


def linkedin_pending(t):
    t.wait("return /Select archive you want to download/i.test(body())", why="linkedin's download page did not load")
    return t.said("Request pending|is now available for download")   # the first part is ready within minutes, the rest within a day


def linkedin(t):
    t.js("var l=document.querySelector('label[for=\"fast-file-only-plus-other-data\"]');if(l)l.click();return !!l")
    t.wait("""var r=document.getElementById('fast-file-only-plus-other-data');var b=find(document,'Request archive','button');
        return !!(r&&r.checked&&b&&!b.disabled)""", why="linkedin's larger-archive option could not be selected")
    t.js("return hit(document,'Request archive','button')")
    t.wait("return /Request pending/i.test(body())", 30, "linkedin did not confirm the request")


X_PENDING = "We received your request|Request pending|Requesting archive|we.ll (email|notify|send)|being (generated|prepared)|Download archive"


def x_pending(t):
    t.wait("return /Download an archive of your data|X data/i.test(body())", why="x's download page did not load")
    time.sleep(2)
    t.check()
    return t.said(X_PENDING)


def x(t):
    if not t.js("return hit(document,'Request archive','button,[role=button]')"):
        raise Fail("x shows neither a pending request nor a 'request archive' button")
    t.wait("return /%s/i.test(body())" % X_PENDING, 30, "x did not confirm the request")


def chatgpt(t):   # ChatGPT and Notion show no "pending" marker; the state file is what stops a second request
    ctx = "all(document,'button').filter(function(b){return txt(b)==='Export'&&/Export data/i.test(b.parentElement.parentElement.innerText||'')})"
    t.wait(f"return {ctx}.length===1", why="chatgpt's data controls did not load")
    t.js(f"{ctx}[0].click();return 1")
    dlg = "all(document,'[role=dialog]').filter(function(d){return /Request data export/i.test(d.innerText)})[0]"
    t.wait(f"return !!{dlg}", why="chatgpt did not ask to confirm the export")
    t.js(f"return hit({dlg},'Confirm export','button')")
    for _ in range(8):   # it either closes the dialog or sends the tab to a code prompt
        time.sleep(1)
        if "chatgpt.com" not in t._do("url"):
            raise Needs("code")
        t.check()
    if t.js(f"return !!{dlg}"):
        raise Fail("chatgpt did not take the confirmation")


IG_PENDING = "being prepared for export|Requested on \\d|In progress"


def instagram_pending(t):
    t.wait("return !!find(top(),'Create export','[role=button],button')", why="instagram's export page did not load")
    return t.said(IG_PENDING)


def instagram(t):
    step = lambda want, then, why: (t.js("return hit(top(),%s)" % want), t.wait("return %s" % then, why=why))
    step("'Create export','[role=button],button'", "!!find(top(),/ \\/ Instagram$/)", "instagram did not list your profiles")
    step("/ \\/ Instagram$/", "!!find(top(),'Export to device')", "instagram did not ask where to export")
    step("'Export to device'", "!!find(top(),'Start export')", "instagram did not show the export summary")
    for label, choice in (("Date range", "All time"), ("Format", "JSON"), ("Media quality", "Lower quality")):
        if t.js("return !!find(top(),'%s / %s')" % (label, choice)):
            continue
        step("/^%s \\/ /" % label, "all(top(),'input[type=radio]').length>1&&!!find(top(),'Save')", f"instagram did not open {label.lower()}")
        if not t.js("return radio(top(),'%s')" % choice):
            raise Fail(f"instagram has no '{choice.lower()}' choice any more")
        step("'Save'", "!!find(top(),'%s / %s')" % (label, choice), f"instagram did not keep {label.lower()}")
    if not t.js("return !!find(top(),/^Customize information \\/ All available information/)"):
        raise Fail("instagram's summary does not say 'all available information'; nothing was requested")
    t.js("return hit(top(),'Start export')")
    t.wait("return /%s/i.test(body())" % IG_PENDING, 30, "instagram did not confirm the export")   # usually stops here for the password


def notion(t):
    # Written from Notion's labels, never run against a signed-in workspace.
    time.sleep(5)
    if "notion.com/" in t._do("url") and not t.js("return !!document.querySelector('.notion-sidebar')"):
        t.check()
        raise Needs("login")
    t.wait("return !!document.querySelector('.notion-sidebar')", why="notion's sidebar did not load")
    if not t.js("return hit(document.querySelector('.notion-sidebar'),'Settings','[role=button],[role=link],a')"):
        raise Fail("notion's sidebar has no 'settings' item")
    t.wait("return top()!==document.body")
    export = "'Export all workspace content','[role=button],button'"
    if not t.js(f"return !!find(top(),{export})"):
        for tab in ("Settings", "General"):
            t.js(f"return hit(top(),'{tab}','[role=button],[role=tab]')")
            time.sleep(2)
            if t.js(f"return !!find(top(),{export})"):
                break
        else:
            raise Fail("notion shows no 'export all workspace content'; that needs a workspace owner")
    t.js(f"return hit(top(),{export})")
    t.wait("return /Export format/i.test(top().innerText)&&!!find(top(),'Export','[role=button],button')", why="notion did not open the export dialog")
    if not t.js("return /Markdown & CSV/.test(top().innerText)"):
        raise Fail("notion's export format is not 'markdown & csv' by default; nothing was requested")
    t.js("""var s=all(top(),'[role=switch],input[type=checkbox]').filter(function(s){return /Include subpages/i.test(row(s))})[0];
        if(s&&s.getAttribute('aria-checked')==='false')s.click();return 1""")
    t.js("return hit(top(),'Export','[role=button],button')")
    time.sleep(3)


SERVICES = [
    {"id": "x", "name": "X", "what": "every tweet, reply, like, bookmark and dm you have on x", "asks_for": "password", "arrives": "a day",
     "url": "https://x.com/settings/download_your_data", "pending": x_pending, "run": x},
    {"id": "google", "name": "Google", "what": "your gmail, calendar, contacts, keep notes, tasks, chrome history, search activity and youtube history", "asks_for": "nothing", "arrives": "hours",
     "url": "https://takeout.google.com/manage", "pending": google_pending, "run": google},
    {"id": "instagram", "name": "Instagram", "what": "your instagram dms, posts, comments, likes and follows, as json", "asks_for": "password", "arrives": "hours",
     "url": "https://accountscenter.instagram.com/info_and_permissions/dyi/", "pending": instagram_pending, "run": instagram},
    {"id": "linkedin", "name": "LinkedIn", "what": "your linkedin messages, connections, profile and account history", "asks_for": "nothing", "arrives": "a day",
     "url": "https://www.linkedin.com/mypreferences/d/download-my-data", "pending": linkedin_pending, "run": linkedin},
    {"id": "chatgpt", "name": "ChatGPT", "what": "every conversation you have had with chatgpt", "asks_for": "code", "arrives": "minutes",
     "url": "https://chatgpt.com/#settings/DataControls", "run": chatgpt},
    {"id": "notion", "name": "Notion", "what": "every page in your notion workspace, as markdown and csv", "asks_for": "nothing", "arrives": "minutes",
     "url": "https://www.notion.so", "run": notion},
]
BY_ID = {s["id"]: s for s in SERVICES}


# ---------------------------------------------------------------- state

def _load():
    try:
        return paths.read_json(STATE)
    except (OSError, ValueError):
        return {}


def _save(sid, state, detail="", requested_at=None):
    d = _load()
    d[sid] = {"state": state, "detail": detail, "requested_at": requested_at or d.get(sid, {}).get("requested_at")}
    if state in ("idle", "declined"):
        d[sid]["requested_at"] = None
    with open(STATE + ".part", "w") as f:
        json.dump(d, f, indent=1)
    os.replace(STATE + ".part", STATE)


def _arrived(sid, since):
    """Newest unpacked archive of this kind in imports/, if it landed after the request (or there was no request)."""
    dirs = [p for p in glob.glob(os.path.join(IMPORTS, sid + "-*")) if os.path.isdir(p)]
    if not dirs:
        return None
    at = datetime.fromtimestamp(max(os.path.getmtime(p) for p in dirs), timezone.utc)
    return at if not since or at > datetime.fromisoformat(since) else None


def service(sid):
    s, saved = BY_ID[sid], _load().get(sid, {})
    out = {"id": sid, "name": s["name"], "what": s["what"], "state": saved.get("state", "idle"), "detail": saved.get("detail", ""),
           "asks_for": s["asks_for"], "arrives": s["arrives"], "requested_at": saved.get("requested_at")}
    at = _arrived(sid, out["requested_at"]) if out["state"] != "declined" else None
    if at:
        out["state"], out["detail"] = "arrived", "archive from %s is on this mac" % at.astimezone().strftime("%Y-%m-%d")
    return out


def listing():
    return {"browser": browser(), "services": [service(s["id"]) for s in SERVICES]}


def request(sid, click=True, again=False):
    """click=False only looks: it records `requested` if the site already shows a pending export and clicks nothing.
    again=True asks for a new export though an earlier one was filed or is already on this mac (ctx/driver.py, when a
    service's cadence comes round): without it an archive in imports/ would stop every later request."""
    s, now = BY_ID[sid], datetime.now(timezone.utc).isoformat(timespec="seconds")
    if again:
        _save(sid, "idle")
    elif service(sid)["state"] in ("requested", "arrived"):   # already filed: do not open the browser, do not click again
        return service(sid)
    b = browser(ask=True)       # the owner asked for an export: the browser is about to be driven, so it may be asked
    if not b["scripting"]:
        _save(sid, "failed", b["how_to_enable"])
        return service(sid)
    low, app = s["name"].lower(), b["name"].lower()
    t = None
    try:
        t = Tab(b["name"], next(x[1] for x in BROWSERS if x[0] == b["name"]), s["url"])
        filed = bool(s.get("pending") and s["pending"](t))
        if click and not filed:
            s["run"](t)
            filed = True
        if filed:
            _save(sid, "requested", "", now)
            try:        # start the clock for the next one: schedule.plan() shows when it comes due
                from . import schedule
                schedule.note_request(sid)
            except Exception:
                pass
        t.close()
    except Needs as e:
        what = str(e)
        _save(sid, "needs_you", f"sign in to {low} in the {app} tab that just opened, then ask again" if what == "login"
              else f"{low} is asking for your {what} in the {app} tab that just opened")
        t.front()
    except Fail as e:
        _save(sid, "failed", str(e))
    except Exception as e:   # osascript errors: browser quit, tab closed by hand, automation not allowed
        _save(sid, "failed", "could not drive %s: %s" % (app, str(e).split(": ")[-1][:120]))
    return service(sid)


def main(argv):
    usage = "usage: python3 -m ctx request --list | <id> | --check <id> | --decline <id> | --reset <id> | --enable-browser | --link-extension chatgpt\nids: " + " ".join(BY_ID)
    a = argv[0] if argv else ""
    sid = argv[1] if len(argv) > 1 else a
    if a == "--list":
        print(json.dumps(listing()))
    elif a == "--link-extension":
        print(json.dumps(link_extension(argv[1] if len(argv) > 1 else "")))
    elif a == "--enable-browser":
        print(json.dumps(enable_browser()))
    elif sid not in BY_ID:
        raise SystemExit(usage)
    elif a == "--decline":
        _save(sid, "declined")
        print(json.dumps(service(sid)))
    elif a == "--check":   # look only: is an export already pending on the site?
        print(json.dumps(request(sid, click=False)))
    elif a == "--reset":
        _save(sid, "idle")
        print(json.dumps(service(sid)))
    else:
        print(json.dumps(request(sid)))
