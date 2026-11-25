"""Daily refresh of the sources that are read through the owner's signed-in browser or apps:
Slack, Google Docs/Slides/Sheets, Apple Calendar and X bookmarks.

The browser sources go through the `context` extension when it is loaded (ctx/bridge.py): it reads in background
tabs and never changes what is on screen. Without it they fall back to AppleScript, which in Dia can only open a
tab in front, so that path is off unless CTX_OPEN_TABS=1 or a tab for the site is already open.

Read-only everywhere: these load pages, scroll, and ask each site for the owner's own data with the session the
tab already has. Nothing is posted, clicked or changed, and no token or cookie ever leaves the page.
Each function returns {"rows", "new", "state": "ok"|"needs_you"|"skipped", "detail"} and does not raise for
expected conditions (signed out, browser scripting off, permission refused).
"""
import json, os, re, subprocess, time
from datetime import datetime, timezone
from . import bridge, paths, request
from .collect import BUSY, drop_lock, note, take_lock
from .scrub import scrub

IMPORTS = os.path.join(paths.HOME, "imports")


def _res(rows, new=0, state="ok", detail=""):
    return {"rows": rows, "new": new, "state": state, "detail": detail}


def _lines(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def _write_lines(path, rows):
    os.makedirs(IMPORTS, exist_ok=True)
    with open(path + ".part", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(path + ".part", path)


# ---------------------------------------------------------------- browser tabs

class Skip(Exception):
    pass


class _Tab(request.Tab):
    """request.Tab, but it can adopt a tab that is already open (found by a piece of its URL) instead of opening one."""
    FIND = '''on run argv
      tell application id "%s"
        set hit to ""
        repeat with w in windows
          repeat with t in tabs of w
            if (URL of t) contains (item 1 of argv) then set hit to (id of t) as text
          end repeat
        end repeat
        return hit
      end tell
    end run'''

    def __init__(self, url, reuse=None):
        b = request.browser()
        if not b["scripting"]:
            raise Skip("browser scripting is off: " + (b["how_to_enable"] or "no browser we can drive"))
        name = b["name"]
        bundle = next(x[1] for x in request.BROWSERS if x[0] == name)
        found = request.osa(self.FIND % bundle, reuse) if reuse else ""
        if found:
            focus = "focus t" if name == "Dia" else "set active tab index of w to i\n            set index of w to 1"
            self.browser, self.script, self.id, self.opened = name, request.TAB % (bundle, focus), found, False
        elif not os.environ.get("CTX_OPEN_TABS"):
            # Dia has no way to open a tab in the background: a new tab becomes the one on screen. Off unless asked for.
            # CTX_OPEN_TABS=1 allows it; the owner is told what they can do, not which variable to set
            raise Skip(("keep a %s tab open in %s and it is read on the next look" % (reuse.split("/")[0], name.lower())) if reuse
                       else "needs to open a tab in %s, which takes over the window" % name.lower())
        else:
            super().__init__(name, bundle, url)
            self.opened = True

    def url(self):
        return self._do("url")

    def done(self):
        if self.opened:
            self.close()


CG_FILE_NAME = os.path.join("chatgpt-web", "conversations-000.json")
FILES = {"slack": "slack.jsonl", "gdrive": "gdrive.jsonl", "calendar": "calendar.jsonl", "x_bookmarks": "bookmarks.json", "x_likes": "x_likes.json", "x_posts": "x_posts.json", "x_replies": "x_replies.json",
         "chatgpt": CG_FILE_NAME, "instagram_saved": "instagram_saved_web.json"}


def _count(name):
    p = os.path.join(IMPORTS, FILES[name])
    try:
        return len(paths.read_json(p)) if p.endswith(".json") else sum(1 for _ in paths.read_lines(p))
    except (OSError, ValueError):
        return 0


def _guard(fn):
    """Turn the expected ways a browser read can stop into a result instead of an exception."""
    def run(*a, **k):
        lock = take_lock("signed_in_" + fn.__name__)       # the app's daily read and one started by hand must not write the same file together
        if not lock:
            return _res(_count(fn.__name__), 0, "skipped", BUSY)
        try:
            return fn(*a, **k)
        except Skip as e:
            return _res(_count(fn.__name__), 0, "skipped", str(e))
        except request.Needs as e:
            what = str(e)
            return _res(_count(fn.__name__), 0, "needs_you", "sign in to %s in your browser" % fn.__name__.split("_")[0] if what == "login"
                        else "%s is asking for your %s in the browser" % (fn.__name__.split("_")[0], what))
        except bridge.Offline as e:
            return _res(_count(fn.__name__), 0, "skipped", str(e))
        except (request.Fail, RuntimeError, subprocess.TimeoutExpired) as e:
            if "unknown reader" in str(e) or "does not belong" in str(e):
                return _res(_count(fn.__name__), 0, "skipped", "the context extension in your browser does not have this reader yet: reload it at chrome://extensions")
            return _res(_count(fn.__name__), 0, "skipped", "could not read the page: " + str(e).split(": ")[-1][:120])
        finally:
            drop_lock(lock)
    run.__name__, run.__doc__ = fn.__name__, fn.__doc__
    return run


# ---------------------------------------------------------------- slack

# Runs inside the signed-in app.slack.com tab and calls Slack's own API with that tab's session.
# The token is read and used inside the page only; nothing here returns it. Only read methods are called.
# OLD maps conversation id -> newest ts already saved; history is asked only for what came after.
SLACK_START = r'''
  if (window.__sl && window.__sl.running) return "running";
  var OLD = %s;
  var S = window.__sl = {running:true, done:false, err:"", convs:0, users:{}, msgs:[], at:0, skipped:0};
  var team = location.pathname.split("/")[2];
  var cfg = JSON.parse(localStorage.getItem("localConfig_v2") || "{}");
  var tok = cfg.teams && cfg.teams[team] && cfg.teams[team].token;
  if (!tok) { S.err = "no session"; S.running = false; S.done = true; return "no session"; }
  var W = null; try { W = new Worker(URL.createObjectURL(new Blob(["onmessage=function(e){setTimeout(function(){postMessage(1)},e.data)}"]))) } catch(e){}
  function sleep(ms){ return new Promise(function(r){ if (!W) return r(); W.onmessage = function(){ r() }; W.postMessage(ms) }) }   /* hidden tabs throttle timers; workers are not throttled */
  async function api(m, p){
    for (var k = 0; k < 6; k++){
      var f = new FormData(); f.append("token", tok); for (var x in p) f.append(x, p[x]);
      var r = await fetch("/api/" + m, {method:"POST", body:f, credentials:"include"});
      if (r.status == 429){ await sleep(1000 * (parseInt(r.headers.get("retry-after") || "5") + 1)); continue }
      var j = await r.json(); if (!j.ok && j.error == "ratelimited"){ await sleep(6000); continue }
      return j;
    }
    return {ok:false, error:"gave up"};
  }
  (async function(){
    try {
      var me = await api("auth.test", {}); if (!me.ok) { S.err = "no session"; S.done = true; S.running = false; return }
      S.me = me.user_id;
      var cur = "", convs = [];
      do { var u = await api("users.list", {limit:500, cursor:cur}); (u.members||[]).forEach(function(m){ S.users[m.id] = m.real_name || m.name }); cur = (u.response_metadata||{}).next_cursor || "" } while (cur);
      cur = "";
      do { var c = await api("users.conversations", {types:"im,mpim,public_channel,private_channel", limit:500, cursor:cur, exclude_archived:false});
           if (!c.ok){ S.err = "convs: " + c.error; break }
           (c.channels||[]).forEach(function(ch){ convs.push({id:ch.id, kind: ch.is_im ? "dm" : "group", name: ch.is_im ? (S.users[ch.user] || ch.user) : (ch.name || ch.id)}) });
           cur = (c.response_metadata||{}).next_cursor || "" } while (cur);
      S.convs = convs.length;
      for (var i = 0; i < convs.length; i++){
        var cv = convs[i], cur2 = "", empty = 0; S.at = i + 1;
        do { var p = {channel:cv.id, limit:200, cursor:cur2}; if (OLD[cv.id]) p.oldest = OLD[cv.id];
             var h = await api("conversations.history", p);
             if (!h.ok) break; var before = S.msgs.length;
             (h.messages||[]).forEach(function(m){ if (m.text && !m.subtype) S.msgs.push([cv.id, cv.name, cv.kind, m.ts, m.user == S.me ? "me" : (S.users[m.user] || m.user || ""), m.text.slice(0,4000)]) });
             empty = S.msgs.length == before ? empty + 1 : 0; if (empty >= 3) { S.skipped++; break }   /* bot or log channel */
             cur2 = h.has_more ? (h.response_metadata||{}).next_cursor : ""; await sleep(W ? 300 : 0) } while (cur2);
      }
    } catch(e){ S.err = String(e) }
    S.users = {}; S.done = true; S.running = false;
  })();
  return "started";
'''
SLACK_POLL = 'var S=window.__sl||{};return {done:!!S.done,err:S.err||"",convs:S.convs||0,at:S.at||0,msgs:(S.msgs||[]).length}'


def _slack_save(path, have, msgs, err):
    seen, new = {r["id"] for r in have}, []
    for m in msgs:
        cid, ts, who = m["cid"], m["ts"], m["who"]
        row = {"id": "S" + cid + "_" + ts.replace(".", ""), "src": "slack", "ts": float(ts), "thread_id": "sl" + cid, "thread": m["name"],
               "kind": m["kind"], "who": "me" if who == "me" else "them", "sender": "" if who == "me" else who, "text": scrub(m["text"])}
        if row["id"] not in seen:
            seen.add(row["id"])
            new.append(row)
    if new:
        _write_lines(path, have + sorted(new, key=lambda r: r["ts"]))
    return _res(len(have) + len(new), len(new), "ok", ("slack stopped early: " + err) if err else "")


@_guard
def slack():
    """Messages newer than what is saved, for every conversation the owner is in. Appends to imports/slack.jsonl."""
    path = os.path.join(IMPORTS, "slack.jsonl")
    have = _lines(path)
    newest = {}
    for r in have:
        cid = r["thread_id"][2:]
        if r["ts"] > newest.get(cid, (0, ""))[0]:
            newest[cid] = (r["ts"], r["id"].split("_")[-1])
    # Slack's ts is seconds.micros as text; the saved id keeps the digits exactly, the float may not
    old = {cid: d[:-6] + "." + d[-6:] for cid, (_, d) in newest.items() if d.isdigit() and len(d) > 6}
    if bridge.connected():   # the extension reads in a background tab
        note("slack: reading in the background")
        r = bridge.submit({"type": "page", "url": "https://app.slack.com/client", "reuse": "https://app.slack.com/client/*",
                           "fn": "slack_read", "args": [old], "settle": 8000}, timeout=1800)
        v = r.get("value") or {}
        if r.get("away") or v.get("err") == "no session" or "/client/" not in r.get("url", ""):
            raise request.Needs("login")
        return _slack_save(path, have, v.get("msgs") or [], v.get("err") or "")
    t = _Tab("https://app.slack.com/client", reuse="app.slack.com/client")
    try:
        note("slack: opening your workspace")
        for _ in range(20):   # a fresh tab redirects to /client/<team>/..., or to a sign-in page
            t.check()
            if "/client/T" in t.url() or "/client/E" in t.url():
                break
            if "app.slack.com" not in t.url():
                raise request.Needs("login")
            time.sleep(1)
        else:
            raise request.Needs("login")
        if t.js(SLACK_START % json.dumps(old)) == "no session":
            raise request.Needs("login")
        while True:
            time.sleep(3)
            p = t.js(SLACK_POLL)
            note("slack: conversation %s of %s, %s new messages" % (p["at"], p["convs"], p["msgs"]))
            if p["done"]:
                break
        if p["err"] == "no session":
            raise request.Needs("login")
        msgs = []
        for off in range(0, p["msgs"], 500):
            msgs += [dict(zip(("cid", "name", "kind", "ts", "who", "text"), m)) for m in t.js("return window.__sl.msgs.slice(%d,%d)" % (off, off + 500))]
        t.js("window.__sl.msgs=[];return 1")
        return _slack_save(path, have, msgs, p["err"])
    finally:
        t.done()


# ---------------------------------------------------------------- google docs, slides, sheets

GD_KINDS = [("document", "type:document", "application/vnd.google-apps.document"),
            ("presentation", "type:presentation", "application/vnd.google-apps.presentation"),
            ("spreadsheets", "type:spreadsheet", "application/vnd.google-apps.spreadsheet")]
GD_RECENT = 10   # per kind: re-read this many from the top of the list, since the list shows no modified time
GD_LIST = r'''return [].slice.call(document.querySelectorAll('[data-id]')).filter(function(e){return /^[\w-]{25,}$/.test(e.getAttribute('data-id'))})
  .map(function(e){return [e.getAttribute('data-id'), e.getAttribute('aria-label')||'']})'''
# Same-origin read of the plain view of each file, from a docs.google.com tab. Tags come off with regex: the page blocks DOMParser.
GD_START = r'''
  if (window.__gd && window.__gd.running) return "running";
  var L = %s; var G = window.__gd = {running:true, done:false, rows:[], fail:0, at:0};
  (async function(){ for (var i = 0; i < L.length; i++){ var x = L[i]; G.at = i + 1;
    var u = "https://docs.google.com/" + x[1] + "/d/" + x[0] + (x[1]=="document" ? "/mobilebasic" : x[1]=="presentation" ? "/htmlpresent" : "/gviz/tq?tqx=out:csv");
    try { var r = await fetch(u, {credentials:"include"}); if (!r.ok){ G.fail++; continue } var t = await r.text();
      if (x[1] != "spreadsheets"){ t = t.replace(/<(script|style|head)[\s\S]*?<\/\1>/gi," ").replace(/<\/(p|div|h[1-6]|li|tr|br)>|<br\s*\/?>/gi,"\n").replace(/<[^>]+>/g," ")
        .replace(/&nbsp;/g," ").replace(/&amp;/g,"&").replace(/&lt;/g,"<").replace(/&gt;/g,">").replace(/&#39;/g,"'").replace(/&quot;/g,'"').replace(/[ \t]+/g," ").replace(/\n\s*\n+/g,"\n").trim() }
      if (!t){ G.fail++; continue }
      G.rows.push([x[0], x[1], t.slice(0,20000)]) } catch(e){ G.fail++ } }
    G.done = true; G.running = false })();
  return "started";
'''


GD_PLAIN = {"document": "/mobilebasic", "presentation": "/htmlpresent", "spreadsheets": "/gviz/tq?tqx=out:csv"}


def _gd_list_script(add):
    """AppleScript route: Drive's lists in one tab that this opens."""
    t = _Tab("https://drive.google.com/drive/u/0/search?q=" + GD_KINDS[0][1])
    try:
        for n, (kind, q, mime) in enumerate(GD_KINDS):
            note("drive: listing " + kind)
            if n:
                t.go("https://drive.google.com/drive/u/0/search?q=" + q)
            try:
                found = t.wait(GD_LIST, 15)
            except request.Fail:
                found = []   # none of this kind
            add(kind, mime, found)
    except BaseException:
        t.done()
        raise
    return t


def _gd_read_script(t, todo):
    try:
        t.go("https://docs.google.com/document/u/0/")
        t.check()
        t.js(GD_START % json.dumps(todo))
        while True:
            time.sleep(2)
            p = t.js("var G=window.__gd||{};return {done:!!G.done,at:G.at||0,n:(G.rows||[]).length,fail:G.fail||0}")
            note("drive: reading file %s of %s" % (p["at"], len(todo)))
            if p["done"]:
                break
        got = [t.js("return window.__gd.rows[%d]" % i) for i in range(p["n"])]   # one file per call: each can be 20,000 characters
        t.js("window.__gd.rows=[];return 1")
        return got, p["fail"]
    finally:
        t.done()


def _gd_list_bridge(add):
    for kind, q, mime in GD_KINDS:
        note("drive: listing " + kind)
        r = bridge.submit({"type": "page", "url": "https://drive.google.com/drive/u/0/search?q=" + q, "fn": "drive_list", "settle": 2000}, timeout=90)
        if r.get("away"):
            raise request.Needs("login")
        add(kind, mime, [[f["id"], f["title"]] for f in r.get("value") or []])


def _gd_read_bridge(todo):
    got, fail = [], 0
    for n, (fid, kind) in enumerate(todo):
        note("drive: reading file %s of %s" % (n + 1, len(todo)))
        try:
            r = bridge.submit({"type": "fetch", "url": "https://docs.google.com/%s/d/%s%s" % (kind, fid, GD_PLAIN[kind]),
                               "strip": kind != "spreadsheets", "max": 20000}, timeout=60)
        except RuntimeError:
            r = {}
        if r.get("away"):
            raise request.Needs("login")
        if r.get("status") == 200 and r.get("text"):
            got.append([fid, kind, r["text"]])
        else:
            fail += 1
    return got, fail


@_guard
def gdrive():
    """Docs, Slides and Sheets text. Finds files in Drive's own lists, reads new ones and the most recent ones again.
    A file whose text did not change keeps its row and its date."""
    path, ipath = os.path.join(IMPORTS, "gdrive.jsonl"), os.path.join(IMPORTS, "gdrive_index.jsonl")
    have, index = _lines(path), _lines(ipath)
    by_id, known = {r["id"]: r for r in have}, {r["id"] for r in index}
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    todo, titles = [], {}

    def add(kind, mime, found):
        for k, (fid, title) in enumerate(found):
            titles[fid] = title
            if fid not in known:
                index.append({"id": fid, "title": title, "mimeType": mime, "modifiedTime": now, "createdTime": None})
                known.add(fid)
            if k < GD_RECENT or "G" + fid not in by_id:
                todo.append([fid, kind])

    if bridge.connected():   # the extension lists in background tabs and reads with plain requests
        _gd_list_bridge(add)
        got, fail = _gd_read_bridge(todo) if todo else ([], 0)
    else:
        t = _gd_list_script(add)
        if todo:
            got, fail = _gd_read_script(t, todo)
        else:
            t.done()
            got, fail = [], 0
    new = changed = 0
    for fid, kind, text in got:
        text, old = scrub(text), by_id.get("G" + fid)
        if old and old.get("text") == text:
            continue
        new, changed = new + (not old), changed + bool(old)
        by_id["G" + fid] = {"id": "G" + fid, "src": "gdrive", "ts": now, "title": scrub(titles.get(fid, "")), "kind": kind, "text": text}
    rows = sorted(by_id.values(), key=lambda r: r["ts"], reverse=True)
    if new or changed:
        for r in index:
            if "G" + r["id"] in by_id and by_id["G" + r["id"]]["ts"] == now:
                r["modifiedTime"] = now
        _write_lines(path, rows)
    if len(index) != len(_lines(ipath)) or new or changed:
        _write_lines(ipath, index)
    detail = ", ".join(x for x in ("%d changed" % changed if changed else "", "%d could not be read" % fail if fail else "") if x)
    return _res(len(rows), new, "ok", detail)


# ---------------------------------------------------------------- apple calendar

CAL_BACK, CAL_AHEAD = 30, 365   # days
CAL_JXA = '''var app = Application("Calendar"), a = new Date(Date.now() - %d*864e5), b = new Date(Date.now() + %d*864e5), out = [], bad = 0;
app.calendars().forEach(function(c){ try {
  var ev = c.events.whose({_and: [{startDate: {_greaterThan: a}}, {startDate: {_lessThan: b}}]});
  var u = ev.uid(), s = ev.summary(), d = ev.startDate(), l = ev.location(), n = ev.description(), name = c.name();
  for (var i = 0; i < u.length; i++) out.push([u[i], s[i] || "", d[i].getTime()/1000, name, l[i] || "", n[i] || ""]);
} catch(e) { bad++ } });
JSON.stringify({rows: out, bad: bad})'''


def _z(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def calendar():
    """Events from 30 days back to a year ahead, merged into imports/calendar.jsonl. Rows in that window are replaced
    (so deleted events go, and old K<index> rows become K<uid>); rows outside it are kept as they are."""
    path = os.path.join(IMPORTS, "calendar.jsonl")
    have = _lines(path)
    note("calendar: asking the calendar app")
    try:
        r = subprocess.run(["osascript", "-l", "JavaScript", "-e", CAL_JXA % (CAL_BACK, CAL_AHEAD)], capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return _res(len(have), 0, "skipped", "the calendar app took too long to answer")
    if r.returncode:
        refused = "-1743" in r.stderr or "not authorized" in r.stderr.lower() or "not allowed" in r.stderr.lower()
        return _res(len(have), 0, "needs_you" if refused else "skipped",
                    "allow context to read calendar: system settings > privacy & security > automation" if refused else "the calendar app did not answer")
    got = json.loads(r.stdout)
    now = time.time()
    lo, hi = _z(now - CAL_BACK * 86400), _z(now + CAL_AHEAD * 86400)
    fresh, ids = [], set()
    for uid, title, ts, cal, loc, notes in got["rows"]:
        rid = "K" + uid
        if rid in ids:   # a detached occurrence of a repeating event shares the uid
            rid += "_%d" % ts
        ids.add(rid)
        title = scrub(title)
        fresh.append({"id": rid, "src": "calendar", "ts": _z(ts), "title": title,
                      "text": " | ".join([title, cal, scrub(loc), scrub(notes)[:4000]]).rstrip(" |")})
    if got["bad"] and not fresh:
        return _res(len(have), 0, "skipped", "the calendar app could not list events")
    kept = [x for x in have if not (lo < x["ts"] < hi) and x["id"] not in ids]
    before = {x["id"] for x in have} | {(x["title"], x["ts"]) for x in have}
    new = sum(1 for x in fresh if x["id"] not in before and (x["title"], x["ts"]) not in before)
    rows = sorted(kept + fresh, key=lambda x: x["ts"])
    _write_lines(path, rows)
    return _res(len(rows), new, "ok", "%d calendars could not be read" % got["bad"] if got["bad"] else "")


# ---------------------------------------------------------------- x bookmarks

X_STEP = r'''
  window.__bm = window.__bm || new Map();
  document.querySelectorAll("article").forEach(function(a){
    var t = a.querySelector("time"); var link = t && t.closest("a"); if (!link) return;
    var u = link.href.split("?")[0]; if (window.__bm.has(u)) return;
    var txt = a.querySelector('[data-testid="tweetText"]'); var name = a.querySelector('[data-testid="User-Name"]');
    var links = Array.prototype.slice.call(a.querySelectorAll("a[href]")).map(function(x){return x.innerText}).filter(function(x){return /\.[a-z]{2,}\//i.test(x)}).slice(0,3);
    window.__bm.set(u, {u:u, d:t.getAttribute("datetime"), n:name ? name.innerText.split("\n").slice(0,2).join(" ") : "", t:txt ? txt.innerText : "", l:links,
      m:a.querySelectorAll('[data-testid="tweetPhoto"],video').length});
  });
  window.scrollTo(0, document.documentElement.scrollHeight);
  return {urls: Array.from(window.__bm.keys()), hidden: document.visibilityState == "hidden"};
'''
X_SCREENS = 30   # at most this many scrolls in one run


@_guard
def x_bookmarks():
    """The owner's bookmarks, newest first, in imports/bookmarks.json: a list of {u, d, n, t, l, m}; new ones go in front.
    With the extension it is read like likes and posts (_x_list), from x's own data address, since a hidden tab draws
    nothing to scroll. Without it, a tab on x.com/i/bookmarks is scrolled over AppleScript until a saved bookmark shows;
    that way needs the window in front."""
    path = os.path.join(IMPORTS, "bookmarks.json")
    have = _x_load(path)
    known = {b["u"] for b in have}

    def save(new, reached, hidden):
        new = [{"u": b["u"], "d": b["d"], "n": scrub(b["n"]), "t": scrub(b["t"]), "l": b["l"], "m": b["m"]} for b in new]
        if new:
            os.makedirs(IMPORTS, exist_ok=True)
            with open(path + ".part", "w") as f:
                json.dump(new + have, f, ensure_ascii=False)
            os.replace(path + ".part", path)
        return _res(len(new) + len(have), len(new), "ok",
                    "" if reached else ("x only loads while its window is in front; older new bookmarks may be missing" if hidden
                                        else "did not reach a saved bookmark; older new bookmarks may be missing"))

    if bridge.connected():   # the extension asks x's own data address from a background tab: a hidden tab draws nothing to scroll
        return _x_list("bookmarks.json", "https://x.com/i/bookmarks", "Bookmarks", "bookmarks", ("/i/bookmarks", "/i/history"),
                       vars={"count": 40, "includePromotedContent": False}, part="Bookmarks")
    t = _Tab("https://x.com/i/bookmarks")   # always a fresh tab: it starts at the newest bookmark. X now sends this to /i/history
    try:
        note("x: reading bookmarks")
        time.sleep(3)
        urls, still, hidden = [], 0, False
        for _ in range(X_SCREENS):
            t.check()
            if "/i/bookmarks" not in t.url() and "/i/history" not in t.url():
                raise request.Needs("login")
            if t.js("var s=document.querySelector('main [role=tab][aria-selected=true]');return !!s&&!/Bookmarks/i.test(s.innerText)"):
                raise Skip("x did not open on bookmarks")
            p = t.js(X_STEP)
            hidden = p["hidden"]
            still = still + 1 if len(p["urls"]) == len(urls) else 0
            urls = p["urls"]
            if any(u in known for u in urls) or still >= 4:
                break
            time.sleep(1.5)
        if not urls:
            raise Skip("x only loads while its window is in front" if hidden else "x showed no bookmarks")
        fresh = []
        for u in urls:   # page order is newest bookmark first
            if u in known:
                break
            fresh.append(u)
        new = []
        for off in range(0, len(fresh), 40):
            new += [b for b in t.js("var w=%s;return w.map(function(u){return window.__bm.get(u)})" % json.dumps(fresh[off:off + 40])) if b]
        return save(new, any(u in known for u in urls) or not known, hidden)
    finally:
        t.done()


# ---------------------------------------------------------------- x likes and own posts (through the extension only)

X_FIRST = 300    # pages of 40 on the first read of a list: up to 12,000 posts, about eight minutes. later reads stop at a saved post


def _x_handle():
    """The signed-in account's handle, asked once from x itself and kept in imports/x_me.json."""
    if not bridge.connected():
        raise Skip("needs the context extension in your browser")
    path = os.path.join(IMPORTS, "x_me.json")
    try:
        with open(path) as f:
            got = json.load(f).get("handle") or ""
    except (OSError, ValueError, AttributeError):
        got = ""
    if re.fullmatch(r"[A-Za-z0-9_]{1,15}", got):
        return got
    r = bridge.submit({"type": "page", "url": "https://x.com/home", "fn": "x_me", "args": [], "settle": 3000}, timeout=90)
    if r.get("away"):
        raise request.Needs("login")
    got = str(r.get("value") or "")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", got):
        raise Skip("x did not show which account is signed in")
    os.makedirs(IMPORTS, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"handle": got}, f)
    return got


X_RUN = 8        # pages of 40 in one call to the tab: under a minute, so a tab that goes away costs little


def _pid(u):
    """The number of a post, from its link. A post is known by this: a handle can change its spelling."""
    return u.rstrip("/").rsplit("/", 1)[-1]


def _x_mark(mark):
    """Where a list stands: (cursor to go on from, was the end of the list ever reached). A saved list whose mark
    cannot be read is taken as read to its end: only what is newer is then fetched."""
    try:
        with open(mark) as f:
            m = json.load(f)
        return str(m.get("next") or ""), bool(m.get("end"))
    except (OSError, ValueError, AttributeError):
        return "", True


def _x_load(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def _x_save(path, rows):
    os.makedirs(IMPORTS, exist_ok=True)
    with open(path + ".part", "w") as f:
        json.dump(rows, f, ensure_ascii=False)
    os.replace(path + ".part", path)


def _x_list(file, url, op, what, where, mine="", vars=None, part="", replies=False):
    """One of the owner's own lists on x (likes, posts, bookmarks), newest first, read from x's own data address inside
    a background tab. Read in short runs and saved after each. imports/<file>.at keeps the place: the cursor to go on
    from, and whether the end of the list was ever reached. Until it was, every read goes on down the list: from the
    cursor, or, when a stop lost the cursor, from the top past the posts already saved (those pages cost little).
    Once it was, a read only looks for posts newer than the saved ones and stops at a saved post.
    `where` are pieces of the address the tab must end on; `mine` is the owner's handle when only their own posts count.
    `vars` and `part` are for a list that is not about one account: see x_api in extension/readers.js."""
    path, mark = os.path.join(IMPORTS, file), os.path.join(IMPORTS, file + ".at")
    have = _x_load(path)
    at, ended = _x_mark(mark) if have else ("", False)
    deep = not ended
    passed = bool(at) or not have       # from the top of a half-read list, posts met before a saved one are newer than it
    known = {_pid(b["u"]) for b in have}
    note("x: reading your %s in the background" % what)
    start, why, wait, front = len(have), "", 0, []
    for run in range(X_FIRST // X_RUN if deep else 2):
        r = bridge.submit({"type": "page", "url": url, "fn": "x_api", "settle": 4000,
                           "args": [op, [] if deep else [b["u"] for b in have[:300]], X_RUN, at, vars, part]}, timeout=240)
        landed = r.get("url", "").lower()
        if r.get("away") or not any(w.lower() in landed for w in where):
            raise request.Needs("login")
        got = r.get("value") or {}
        if got.get("why") == "signed out":
            raise request.Needs("login")
        items = got.get("items") or []
        if mine:        # a profile also shows reposts and the posts a reply answers: keep what this account wrote
            items = [b for b in items if ("/%s/status/" % mine).lower() in b["u"].lower() and not b.get("rt")]
        if replies:     # the list of replies also holds the owner's other posts now and then: those are in the posts list
            items = [b for b in items if b.get("r")]
        back = []
        for b in items:
            if _pid(b["u"]) in known:
                passed = True
                continue
            known.add(_pid(b["u"]))
            row = {"u": b["u"], "d": b["d"], "n": scrub(b["n"]), "t": scrub(b["t"]), "l": b["l"], "m": b["m"]}
            if mine and b.get("r"):
                row["r"] = b["r"]       # the handle this post answers, when it is a reply
            (back if deep and passed else front).append(row)
        have = have + back              # going down the list: older ones go at the end
        why, at, wait = got.get("why") or "", got.get("next") or "", int(got.get("wait") or 0)
        _x_save(path, front + have)
        if deep:
            with open(mark, "w") as f:
                json.dump({"next": at, "end": not at and not why}, f)
        note("x: %d %s so far" % (len(front) + len(have), what))
        if not at or why:
            break
        time.sleep(2)
    total = len(front) + len(have)
    added = total - start
    if not total:
        raise Skip("x showed no %s%s" % (what, ": " + why if why else ""))
    if why == "x asked to slow down" and wait:
        why += " for %d minutes" % max(1, round(wait / 60.0))
    more = "more to read: it goes on at the next daily read" if deep and (at or why) else ""
    return _res(total, added, "ok", "; ".join(x for x in (why, more) if x))


@_guard
def x_likes():
    """The posts the owner liked, from x.com/<handle>/likes. Only the owner can see that page."""
    handle = _x_handle()
    return _x_list("x_likes.json", "https://x.com/%s/likes" % handle, "Likes", "likes", ("/" + handle, "/i/history"))     # x now sends /<handle>/likes to /i/history/likes


@_guard
def x_posts():
    """What the owner posted, from the list their profile shows. Replies to other people are not in it: x_replies reads those."""
    handle = _x_handle()
    return _x_list("x_posts.json", "https://x.com/" + handle, "UserTweets", "posts", ("/" + handle,), mine=handle)


@_guard
def x_replies():
    """The owner's replies, from the list behind the "replies" tab of their profile. x refuses the list that tab once
    used (UserTweetsAndReplies answers 404) and a search for them (404 too); UserRepliesTimeline is the one it gives.
    Each row keeps "r", the handle it answers."""
    handle = _x_handle()
    return _x_list("x_replies.json", "https://x.com/%s/with_replies" % handle, "UserRepliesTimeline", "replies", ("/" + handle,), mine=handle, replies=True)


# ---------------------------------------------------------------- chatgpt and instagram (through the extension only)
# Their exports need a code or a password, so between exports they go stale. These read the same things from the owner's
# signed-in tab, from the addresses the site's own page reads, GET only. Both sites forbid automated collection in their
# terms and both watch for it: a read is one tab, a few requests a second apart, once a day, and it stops at the first
# refusal. Neither address is a published api: either site can change it, and then the read says so and keeps its rows.

CG_FILE = os.path.join("chatgpt-web", "conversations-000.json")
CG_MOST, CG_RUNS = 10, 4        # conversations in one call to the tab, calls in one read


def _cg_known():
    """{conversation id: when it last changed} for every conversation already in imports/, from an export or from here."""
    from . import local_apps
    known = {}
    for d, _, names in os.walk(IMPORTS):
        for x in names:
            if re.fullmatch(r"conversations(-\d+)?\.json", x):
                try:
                    for c in local_apps._array(os.path.join(d, x)):
                        if isinstance(c, dict) and (c.get("conversation_id") or c.get("id")):
                            cid, at = c.get("conversation_id") or c.get("id"), c.get("update_time") or 0
                            known[cid] = max(known.get(cid, 0), at if isinstance(at, (int, float)) else 0)
                except (OSError, ValueError):
                    continue
    return known


def _cg_conversation(c):
    """What the tab returned for one conversation, in the shape the export uses, so the export's reader reads it and gives
    the same ids: one row per conversation whichever way it came."""
    mapping, prev = {"root": {"id": "root", "parent": None, "children": [], "message": None}}, "root"
    for k, t in enumerate(c.get("turns") or []):
        node = "n%d" % k
        mapping[prev]["children"] = [node]
        mapping[node] = {"id": node, "parent": prev, "children": [], "message": {
            "author": {"role": t.get("role")}, "create_time": t.get("at") or c.get("changed") or 0, "content": {"content_type": "text", "parts": [str(t.get("text") or "")]}}}
        prev = node
    return {"conversation_id": c["id"], "id": c["id"], "title": str(c.get("title") or ""), "create_time": c.get("made") or 0, "update_time": c.get("changed") or 0,
            "current_node": prev, "mapping": mapping}


@_guard
def chatgpt():
    """Conversations that are new or changed since the last export or the last read, from chatgpt.com in a background
    tab. Saved in the export's own shape under imports/chatgpt-web/, which the chatgpt_export reader already reads."""
    if not bridge.connected():
        raise Skip("needs the context extension in your browser")
    path = os.path.join(IMPORTS, CG_FILE)
    have = {c["id"]: c for c in _x_load(path)}
    known, added, why, more = _cg_known(), 0, "", False
    note("chatgpt: reading what changed, in the background")
    for run in range(CG_RUNS):
        r = bridge.submit({"type": "page", "url": "https://chatgpt.com/", "fn": "chatgpt_api", "settle": 5000, "args": [known, 3, "", CG_MOST]}, timeout=300)
        got = r.get("value") or {}
        if r.get("away") or "chatgpt.com" not in r.get("url", "") or got.get("why") == "signed out":
            raise request.Needs("login")
        for c in got.get("items") or []:
            if not c.get("id"):
                continue
            added += c["id"] not in have and c["id"] not in known
            have[c["id"]] = _cg_conversation(c)
            known[c["id"]] = c.get("changed") or time.time()
        why, more = got.get("why") or "", bool(got.get("next"))
        if got.get("items"):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _x_save(path, sorted(have.values(), key=lambda c: c.get("update_time") or 0, reverse=True))
            with open(os.path.join(os.path.dirname(path), "user.json"), "w") as f:      # marks the folder as chatgpt's for the export reader
                json.dump({"read_from": "chatgpt.com, by the context extension"}, f)
        note("chatgpt: %d conversations read here so far" % len(have))
        if why or not more:
            break
        time.sleep(3)
    total = len(known)
    if not total:
        raise Skip("chatgpt showed no conversations%s" % (": " + why if why else ""))
    return _res(total, added, "ok", "; ".join(x for x in (why, "more to read: it goes on at the next daily read" if more and not why else "") if x))


def _ig_posts(file, kind, what, part, prefix):
    """Posts the owner saved or liked on instagram, newest first, new ones in front of imports/<file>."""
    if not bridge.connected():
        raise Skip("needs the context extension in your browser")
    from . import collect
    path = os.path.join(IMPORTS, file)
    have = _x_load(path)
    # stop at a post saved here before, or at one an export already brought
    known = [b["id"] for b in have[:300]] + [k.decode("ascii", "ignore")[len(prefix):] for k in collect._ids(collect._part(part)) if k.startswith(prefix.encode())][:5000]
    note("instagram: reading your %s posts in the background" % what)
    r = bridge.submit({"type": "page", "url": "https://www.instagram.com/", "fn": "ig_api", "settle": 5000, "args": [kind, known, 3, ""]}, timeout=240)
    got = r.get("value") or {}
    if r.get("away") or "instagram.com" not in r.get("url", "") or "/accounts/login" in r.get("url", "") or got.get("why") == "signed out":
        raise request.Needs("login")
    seen = {b["id"] for b in have}
    fresh = [{"id": str(b["id"]), "at": int(b.get("at") or 0), "user": scrub(b.get("user") or ""), "text": scrub(b.get("text") or ""), "reel": bool(b.get("reel"))}
             for b in got.get("items") or [] if b.get("id") and str(b["id"]) not in seen]
    if fresh:
        _x_save(path, fresh + have)
    why = got.get("why") or ""
    if not (have or fresh) and why:
        raise Skip("instagram showed no %s posts: %s" % (what, why))
    return _res(len(have) + len(fresh), len(fresh), "ok", why)


@_guard
def instagram_saved():
    """Posts and reels the owner saved, read from instagram.com (the export has them only as of the day it was made).
    Messages and liked posts are not read this way: instagram refuses both to a plain GET, so those two
    still come with the export."""
    return _ig_posts("instagram_saved_web.json", "saved", "saved", "instagram_saved", "IS")


ALL = {"slack": slack, "gdrive": gdrive, "calendar": calendar, "x_bookmarks": x_bookmarks, "x_likes": x_likes, "x_posts": x_posts, "x_replies": x_replies,
       "chatgpt": chatgpt, "instagram_saved": instagram_saved}
