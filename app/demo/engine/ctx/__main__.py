"""A stand-in for the real engine, for looking at the app without touching anyone's data.

`python3 -m ctx collect` prints the same lines as the real collector and writes made-up rows to a folder of the demo's
own: CTX_HOME when that folder carries the demo's marker (.demo, written only into a folder the demo made or found
empty), else a folder it makes in the temp folder. A folder CTX_HOME names that holds anything else (a real archive,
someone's documents) is never written to. Nothing here reads a real source. Set DEMO_FAST=1 to skip the pauses.
"""
import json, os, random, stat, sys, tempfile, time
from datetime import datetime, timedelta, timezone

MARK = ".demo"
ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))       # the folder that holds this stand-in's ctx/


def _ours(folder, make=False):
    """Is this folder the demo's own: it carries the marker, or (make) it is new or empty, ours, and is marked now."""
    try:
        if stat.S_ISREG(os.lstat(os.path.join(folder, MARK)).st_mode):
            return True
    except OSError:
        pass
    if not make:
        return False
    try:
        os.makedirs(folder, mode=0o700, exist_ok=True)
        st = os.lstat(folder)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or os.listdir(folder):
            return False
        with open(os.path.join(folder, MARK), "w"):
            pass
        return True
    except OSError:
        return False


def _home():
    want = os.environ.get("CTX_HOME")
    if want and _ours(os.path.abspath(os.path.expanduser(want)), make=True):
        return os.path.abspath(os.path.expanduser(want))
    own = os.path.join(tempfile.gettempdir(), "context-demo-%d" % os.getuid())
    if not _ours(own, make=True):
        own = tempfile.mkdtemp(prefix="context-demo-")
        _ours(own, make=True)
    if want:
        print("demo: %s is not a folder of the demo's own, so made-up data goes to %s" % (want, own), file=sys.stderr)
    return own


HOME = _home()
FAST = bool(os.environ.get("DEMO_FAST"))
NOW = datetime.now(timezone.utc)
R = random.Random(7)

PEOPLE = ["maya okafor", "jonas", "priya", "sam (landlord)", "dad", "the print shop", "ines", "tomas", "studio group", "leo"]
LINES = [
    "can you send the revised deck before friday", "running ten minutes late", "the pricing page copy is in the doc",
    "stripe says the webhook signature does not match", "lunch thursday?", "i will look at the invoice tonight",
    "did the print proofs arrive", "let's move the call to 4", "the lease renewal is due on the first",
    "sounds good", "sending it now", "which plan do we show first, monthly or yearly", "ok", "thanks, got it",
    "the landing page hero still says beta", "i can review the checkout flow tomorrow morning", "call me when you land",
    "happy birthday!", "the yearly discount should be two months free", "can you share the figma link again",
]
NOTES = [("pricing page outline", "three plans. yearly toggle on by default. one line under each price. no feature table above the fold."),
         ("books to read", "the timeless way of building. a pattern language. how buildings learn."),
         ("lease questions", "ask sam about the renewal date and whether the deposit carries over."),
         ("checkout bugs", "stripe webhook signature fails when the body is parsed before verification. keep the raw body.")]


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def say(name, status, pause):
    if not FAST:
        time.sleep(pause)
    print(f"{name:12} {status}", flush=True)
    return status


def messages(out, src, prefix, n, years, pause):
    start = NOW - timedelta(days=365 * years)
    step = (NOW - start) / n
    t = time.time()
    for i in range(n):
        who = "me" if R.random() < 0.45 else "them"
        p = R.randrange(len(PEOPLE))
        out.write(json.dumps({"id": f"{prefix}{i}", "src": src, "ts": iso(start + step * i), "thread_id": f"{prefix.lower()}{p}",
                              "thread": PEOPLE[p], "kind": "group" if "group" in PEOPLE[p] else "dm", "who": who,
                              "sender": "" if who == "me" else PEOPLE[p].split()[0], "text": R.choice(LINES)}) + "\n")
        if not FAST and i % 400 == 0:
            out.flush()
            time.sleep(pause * 400 / n)
    out.flush()
    return {"rows": n, "secs": round(time.time() - t, 1)}


def collect():
    os.makedirs(HOME, exist_ok=True)
    status = {}
    skip_fda = {"skipped": "blocked by macOS: grant Full Disk Access to the app running this (System Settings > Privacy & Security)"}
    locked = bool(os.environ.get("DEMO_LOCKED"))
    with open(os.path.join(HOME, "messages.jsonl"), "w") as out:
        status["whatsapp"] = say("whatsapp", messages(out, "whatsapp", "W", 40000, 4, 3.0), 0)
        status["imessage"] = say("imessage", skip_fda if locked else messages(out, "imessage", "I", 8000, 6, 1.6), 0.4)
        status["telegram"] = say("telegram", {"skipped": "needs setup: python3 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements-telegram.txt"}, 0.3)
        status["slack"] = say("slack", messages(out, "slack", "S", 3000, 1, 1.0), 0)
        status["email"] = say("email", skip_fda if locked else messages(out, "email", "E", 1500, 3, 1.2), 0.3)
    with open(os.path.join(HOME, "sessions.jsonl"), "w") as out, open(os.path.join(HOME, "prompts.jsonl"), "w") as pr:
        for src, pre, n in (("claude_code", "C", 100), ("codex", "X", 40), ("cursor", "U", 60)):
            t = time.time()
            for i in range(n):
                ts = iso(NOW - timedelta(days=4 + i * 2, hours=i))
                out.write(json.dumps({"id": f"{pre}{i:07d}", "src": src, "title": "", "project": "/Users/you/shop", "first_user":
                                      "tidy the " + R.choice(["cart", "footer", "plans table", "signup form"]) + " component",
                                      "last_user": "ok", "last_agent": "done. the tests pass.", "last_agent_ts": ts, "user_turns": 3}) + "\n")
                pr.write(json.dumps({"id": f"{pre}{i:07d}:0", "src": src, "ts": ts, "thread": "shop", "who": "me",
                                     "text": "tidy the component and run the tests"}) + "\n")
            if src == "claude_code":
                old = iso(NOW - timedelta(days=43))
                out.write(json.dumps({"id": "Cwebhook1", "src": src, "title": "fix stripe webhook signature check", "project": "/Users/you/shop",
                                      "first_user": "the stripe webhook signature check fails on every checkout event",
                                      "last_user": "ship it", "last_agent": "fixed: verify the signature against the raw request body, before any json parsing. added a test.",
                                      "last_agent_ts": old, "user_turns": 9}) + "\n")
                pr.write(json.dumps({"id": "Cwebhook1:0", "src": src, "ts": old, "thread": "shop", "who": "me",
                                     "text": "the stripe webhook signature check fails on every checkout event"}) + "\n")
                pr.write(json.dumps({"id": "Ctoday01:0", "src": src, "ts": iso(NOW - timedelta(minutes=50)), "thread": "shop", "who": "me",
                                     "text": "checkout is broken again, stripe says the webhook signature is invalid"}) + "\n")
                n += 1
            out.flush()
            status[src] = say(src, {"rows": n, "secs": round(time.time() - t + 0.3, 1)}, 0.5)
    with open(os.path.join(HOME, "docs.jsonl"), "w") as out:
        status["obsidian"] = say("obsidian", {"skipped": "not installed"}, 0.3)
        t = time.time()
        for i in range(400):
            title, text = NOTES[i % len(NOTES)]
            out.write(json.dumps({"id": f"N{i}", "src": "apple_notes", "ts": iso(NOW - timedelta(days=i * 6)), "title": title, "text": text}) + "\n")
        out.flush()
        status["apple_notes"] = say("apple_notes", skip_fda if locked else {"rows": 400, "secs": 0.2}, 0.6)
        for i in range(900):
            out.write(json.dumps({"id": f"B{i}", "src": "x_bookmarks", "ts": iso(NOW - timedelta(days=i)), "title": "someone",
                                  "text": "a thread about pricing pages and why yearly should be the default", "url": "https://x.com/i/status/1"}) + "\n")
        status["x_bookmarks"] = say("x_bookmarks", {"rows": 900, "secs": 0.0}, 0.5)
        status["x_archive"] = say("x_archive", {"skipped": "needs your X archive: x.com/settings/download_your_data"}, 0.3)
        status["gdrive"] = say("gdrive", {"skipped": "no imports/gdrive.jsonl yet"}, 0.3)
        status["calendar"] = say("calendar", {"skipped": "no imports/calendar.jsonl yet"}, 0.3)
    json.dump(status, open(os.path.join(HOME, "status.json"), "w"), indent=1)
    seed()


def seed():
    """The things the real engine or the app would have written by now: questions, today's timeline, the week's line."""
    day = lambda d: (NOW - timedelta(days=d)).strftime("%Y-%m-%d")
    json.dump([
        {"q": "did you send maya the revised deck you promised for friday?", "kind": "promise", "thread": "maya okafor", "date": day(4), "ids": ["W101"], "why": "you said you would send it. nothing went out after."},
        {"q": "sam asked about the lease renewal twice. have you answered?", "kind": "waiting", "thread": "sam (landlord)", "date": day(9), "ids": ["I220"], "why": "two messages from him, none from you since."},
        {"q": "the agent asked whether to keep the old plans table. you never said.", "kind": "agent", "thread": "shop", "date": day(2), "ids": ["C0000003"], "why": "the session ended on its question."},
    ], open(os.path.join(HOME, "loops.json"), "w"), indent=1)
    now = time.time()
    plan = [("Cursor", "plans.tsx — shop", 34), ("Safari", "pricing page — figma", 22), ("Safari", "home / x", 9), ("Cursor", "plans.tsx — shop", 41),
            ("WhatsApp", "", 6), ("Safari", "home / x", 14), ("Ghostty", "shop — claude", 26), ("Safari", "home / x", 19),
            ("Safari", "youtube — how they built the stadium", 17), ("Safari", "home / x", 12)]
    t = now - sum(m for _, _, m in plan) * 60 - 600
    spans = []
    for app, title, mins in plan:
        spans.append({"app": app, "title": title, "start": t, "secs": mins * 60 - 20})
        t += mins * 60
    spans[-1]["secs"] = now - spans[-1]["start"]
    os.makedirs(os.path.join(HOME, "activity"), exist_ok=True)
    json.dump(spans, open(os.path.join(HOME, "activity", time.strftime("%Y-%m-%d") + ".json"), "w"))
    app = os.path.join(HOME, "app.json")
    if not os.path.exists(app):
        json.dump({"onboarded": False, "hourly": True, "pill": False, "focus": "ship the pricing page", "focusSet": now, "hidden": {}}, open(app, "w"))


SERVICES = [
    ("x", "x", "every post, reply, like and direct message since you joined.", "nothing", "a day", "requested"),
    ("google", "google", "all of gmail, your youtube history and your keep notes, as a google takeout.", "password", "hours", "needs_you"),
    ("instagram", "instagram", "your direct messages and what you posted.", "password", "hours", "requested"),
    ("linkedin", "linkedin", "your messages and who you are connected to.", "nothing", "a day", "failed"),
    ("chatgpt", "chatgpt", "every conversation you have had with chatgpt.", "nothing", "minutes", "requested"),
    ("notion", "notion", "the pages in your workspace, as markdown.", "code", "minutes", "needs_you"),
]
DETAIL = {"google": "google wants your password in the tab that just opened. type it there, then check again.",
          "notion": "notion sent a code to your email. type it in the tab that just opened, then check again.",
          "linkedin": "linkedin showed a page context did not expect. nothing was requested."}


def request(args):
    """Stand-in for `ctx request`: no browser is touched. States live in CTX_HOME/requests.json."""
    path = os.path.join(HOME, "requests.json")
    saved = json.load(open(path)) if os.path.exists(path) else {}

    def row(sid):
        _, name, what, asks, arrives, _ = next(x for x in SERVICES if x[0] == sid)
        st = saved.get(sid, {})
        return {"id": sid, "name": name, "what": what, "state": st.get("state", "idle"), "detail": st.get("detail", ""),
                "asks_for": asks, "arrives": arrives, "requested_at": st.get("requested_at", 0)}

    if args[:1] == ["--list"]:
        print(json.dumps({"browser": {"name": "Dia", "scripting": not os.environ.get("DEMO_NO_SCRIPTING") and saved.get("_scripting", True),
                                      "how_to_enable": "view > developer > allow javascript from apple events"},
                          "services": [row(s[0]) for s in SERVICES]}))
        return
    if args[:1] == ["--enable-browser"]:
        saved["_scripting"] = True
        print(json.dumps({"ok": True}))
    elif args[:1] in (["--decline"], ["--reset"]):
        saved[args[1]] = {"state": "declined"} if args[0] == "--decline" else {}
        print(json.dumps(row(args[1])))
    else:
        if not FAST:
            time.sleep(2)
        result = next(x for x in SERVICES if x[0] == args[0])[5]
        saved[args[0]] = {"state": result, "detail": DETAIL.get(args[0], "") if result != "requested" else "", "requested_at": time.time()}
        print(json.dumps(row(args[0])))
    json.dump(saved, open(path, "w"))


# ---- live reading, as the real collector prints it: "@{json}" progress lines, then one final line per source

THREADS = ["maya okafor", "jonas", "priya", "sam (landlord)", "dad", "the print shop", "ines", "tomas", "studio group", "leo",
           "book club", "flat 4b", "anja", "weekend football", "kofi", "the allotment"]
TITLES = ["pricing page outline", "books to read", "lease questions", "checkout bugs", "talk notes, march", "recipes", "gift ideas",
          "questions for the accountant", "trip packing list", "what the plans table should say"]
SESSIONS = ["fix stripe webhook signature check", "tidy the cart component", "plans table copy", "signup form validation",
            "yearly toggle default", "footer links", "checkout flow tests"]
PAGES = ["stripe docs: webhooks", "figma: pricing page", "a pattern language", "how buildings learn", "train times", "weather, saturday"]
LOCKED = "blocked by macOS: grant Full Disk Access to the app running this (System Settings > Privacy & Security)"
# name, lane, rows, seconds, years back, labels, outcome (None = read; or a status dict)
TABLE = [
    ("whatsapp", 0, 40000, 5.0, 4, THREADS, None),
    ("imessage", 0, 8000, 1.5, 6, THREADS, {"rows": 8000, "stale": True, "why": LOCKED}),
    ("telegram", 0, 0, 0.3, 0, [], {"skipped": "needs setup: python3 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements-telegram.txt"}),
    ("slack", 0, 3000, 1.2, 1, ["#launch", "#design", "ines", "#general"], None),
    ("email", 0, 1500, 4.0, 3, ["re: lease renewal", "invoice 204", "print proofs", "pricing page copy"], None),
    ("claude_code", 1, 100, 1.6, 1, SESSIONS, None),
    ("codex", 1, 40, 0.4, 1, SESSIONS, None),
    ("cursor", 1, 60, 2.4, 1, SESSIONS, None),
    ("grok_bot", 1, 0, 0.2, 0, [], {"skipped": "not installed or no data"}),
    ("browser_history", 2, 2000, 2.6, 1, PAGES, None),
    ("safari_history", 2, 0, 0.3, 0, [], {"skipped": LOCKED}),
    ("obsidian", 2, 0, 0.2, 0, [], {"skipped": "not installed"}),
    ("apple_notes", 2, 400, 0.8, 6, TITLES, None),
    ("x_bookmarks", 2, 900, 0.6, 2, ["on pricing pages", "why yearly should be the default", "a thread on onboarding"], None),
    ("gdrive", 2, 0, 0.3, 0, [], {"skipped": "no imports/gdrive.jsonl yet"}),
    ("calendar", 2, 500, 0.5, 3, ["dentist", "lunch with maya", "print shop pickup", "lease call"], None),
]
import threading
_lock = threading.Lock()


def out(line):
    with _lock:
        print(line, flush=True)


def read_one(row, status):
    name, _, rows, secs, years, labels, outcome = row
    speed = float(os.environ.get("DEMO_SPEED", "1"))
    out("@" + json.dumps({"src": name, "phase": "starting", "rows": 0}))
    t0 = time.time()
    if outcome is None or outcome.get("stale"):
        steps = max(1, int(secs / speed / 0.12))
        start = NOW - timedelta(days=365 * years)
        if name == "email":
            for phase in ("finding the people you write to", "reading what you sent"):
                out("@" + json.dumps({"src": name, "phase": phase, "rows": 0}))
                time.sleep(0.6 / speed)
        if outcome is None:
            for i in range(1, steps + 1):
                at = (start + (NOW - start) * i / steps).strftime("%Y-%m")
                out("@" + json.dumps({"src": name, "rows": rows * i // steps, "at": at, "label": labels[(i * 7) % len(labels)] if labels else ""}))
                time.sleep(0.12)
    else:
        time.sleep(secs / speed)
    st = outcome or {"rows": rows, "secs": round(time.time() - t0, 1)}
    status[name] = st
    out(f"{name:12} {st}")


def live_collect(only=None):
    status = {}
    if only:
        read_one(next(r for r in TABLE if r[0] == only), status)
    else:
        def lane(k):
            for r in TABLE:
                if r[1] == k:
                    read_one(r, status)
        ts = [threading.Thread(target=lane, args=(k,)) for k in range(3)]
        [t.start() for t in ts]
        [t.join() for t in ts]
    path = os.path.join(HOME, "status.json")
    saved = json.load(open(path)) if os.path.exists(path) else {}
    saved.update(status)
    os.makedirs(HOME, exist_ok=True)
    json.dump(saved, open(path, "w"), indent=1)


FACTS = {"total": 56500, "sources": 11, "since": "2019-06-01", "lines": [
    "your record starts in june 2019.",
    "you typed 400,000 words here. about 4 novels.",
    "you write to maya most: 6,000 messages.",
    "2 people are waiting on a reply from you.",
    "you and tomas last spoke 4 months ago.",
    "you write most around 11pm. a tenth of it after midnight.",
    "you gave agents 1,200 instructions. most on shop: 800.",
], "waiting": [{"name": "sam (landlord)", "since": "9 days ago"}, {"name": "ines", "since": "3 days ago"}]}

if len(sys.argv) > 1 and sys.argv[1] == "collect-one":
    live_collect(sys.argv[2])
elif len(sys.argv) > 1 and sys.argv[1] == "collect" and os.environ.get("DEMO_LIVE"):
    live_collect()
elif len(sys.argv) > 1 and sys.argv[1] == "tick":
    if os.environ.get("DEMO_LIVE"):
        live_collect()
    print(json.dumps({"tick": {"fast": 10}}))
elif len(sys.argv) > 1 and sys.argv[1] == "schedule":
    now = time.time()
    print(json.dumps({
        "fast": {"last": now - 360, "due": False, "next_in": 540, "sources": ["whatsapp", "imessage", "claude_code", "codex", "cursor",
                 "grok_bot", "browser_history", "safari_history", "obsidian", "apple_notes"], "results": {}},
        "daily": {"last": now - 36000, "due": False, "next_in": 50400, "sources": ["email", "slack", "gdrive", "calendar", "telegram", "x_bookmarks"],
                  "results": {"slack": {"state": "ok", "detail": ""}, "x_bookmarks": {"state": "needs_you", "detail": "x only loads while its window is in front"}}},
        "weekly": {"x": {"state": "requested", "every": "monthly", "last": now - 7200, "due": False, "next_in": 2584800}}}))
elif len(sys.argv) > 1 and sys.argv[1] == "answer":
    if not FAST:
        time.sleep(float(os.environ.get("DEMO_ANSWER_SECS", "6")))
    reply = {"answer": "not yet. sam asked about the lease renewal twice, nine and six days ago, and your last message to him is from before both. "
                          "you did write a note with the two questions you wanted to ask him: the renewal date, and whether the deposit carries over.",
                          "cites": [{"id": "I220", "src": "imessage", "ts": iso(NOW - timedelta(days=9)), "thread": "sam (landlord)", "who": "them", "text": "the lease renewal is due on the first"},
                                    {"id": "I231", "src": "imessage", "ts": iso(NOW - timedelta(days=6)), "thread": "sam (landlord)", "who": "them", "text": "did you see my message about the renewal?"},
                                    {"id": "N2", "src": "apple_notes", "ts": iso(NOW - timedelta(days=12)), "thread": "lease questions", "who": "me", "text": "ask sam about the renewal date and whether the deposit carries over."}],
                          "searched": ["sam", "lease", "renewal", "deposit"], "found": 38, "confidence": 4, "secs": 17.2, "error": ""}
    if os.environ.get("DEMO_ANSWER_ERROR"):
        reply = {"answer": "", "cites": [], "searched": [], "error": "no plan is signed in, so context cannot read for an answer."}
    if "--stream" in sys.argv:
        # the same line protocol as the real engine: phase, delta, cite, then done or error
        say = lambda d: print(json.dumps(d), flush=True)
        nap = lambda s: None if FAST else time.sleep(s)
        say({"phase": "plan"})
        nap(1.2)
        if reply["error"]:
            say({"error": reply["error"]})
            sys.exit(0)
        say({"phase": "read", "rows": 38, "sources": ["imessage", "apple_notes"], "threads": [{"thread": "sam (landlord)", "src": "imessage", "rows": 24}]})
        nap(1.5)
        marked = reply["answer"].replace("six days ago,", "six days ago [1][2],").replace("deposit carries over.", "deposit carries over [3].")
        reply["answer"] = marked
        told = 0
        words = marked.split(" ")
        for k, w in enumerate(words):
            for n in (1, 2, 3):
                if f"[{n}]" in w and n > told:
                    told = n
                    say({"cite": dict(reply["cites"][n - 1], n=n)})
            say({"delta": w + (" " if k < len(words) - 1 else "")})
            nap(0.06)
        deep = bool(os.environ.get("DEMO_DEEP"))
        reply["strength"] = "partial" if deep else "strong"
        reply["maybe"] = []
        say({"done": reply})
        if deep:
            # the deeper search, as the engine tells it: what it is doing, then a second whole reply
            for n, doing in enumerate(["reading your whole thread with sam", "looking for the note about the deposit"], 1):
                say({"phase": "dig", "round": n, "doing": doing})
                nap(2)
            say({"done": dict(reply, answer="yes. you told sam on the ninth that you are staying [1], and asked whether the deposit carries over [3].",
                              strength="strong", deep=True, dug=[{"how": "thread", "threads": 1}, {"how": "notes"}])})
    else:
        print(json.dumps(reply))
elif len(sys.argv) > 1 and sys.argv[1] == "serve":
    # the warm engine, stood in for: each request is answered by running this same file once, and every line that
    # comes back carries the request's id. made-up data only.
    import subprocess, threading
    lock = threading.Lock()
    def write(d):
        with lock:
            print(json.dumps(d), flush=True)
    def argv(r):
        c = r.get("cmd")
        if c == "answer": return ["answer", r.get("q", ""), "--stream"]
        if c == "thread": return ["thread", str(r.get("msg", "")), "--json"]
        if c == "today": return ["today", "--done", r["done"]] if r.get("done") else ["today", "--dismiss", r["dismiss"]] if r.get("dismiss") else ["today", "--json"]
        if c == "settings": return ["settings"]
        if c == "mcp-status": return ["mcp", "--status"]
        if c == "facts": return ["facts"]
        return None
    def run(r):
        a = argv(r)
        if a is None:
            write({"id": r.get("id"), "result": "ok" if r.get("cmd") in ("ping", "rate") else None})
            return
        # isolated (-I): nothing from PYTHONPATH, the user's site-packages or the folder it starts in; the stand-in named by
        # its path, and the child told the folder this process chose
        boot = "import sys, runpy; sys.path.insert(0, sys.argv.pop(1)); runpy.run_module('ctx', run_name='__main__', alter_sys=True)"
        p = subprocess.Popen([sys.executable, "-I", "-u", "-c", boot, ENGINE] + a, stdout=subprocess.PIPE, text=True, env=dict(os.environ, CTX_HOME=HOME))
        last = None
        for line in p.stdout:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if r.get("cmd") == "answer": write(dict(d, id=r.get("id")))
            else: last = d
        if r.get("cmd") != "answer": write({"id": r.get("id"), "result": last})
    write({"ready": True, "pid": os.getpid()})
    for line in sys.stdin:
        try:
            req = json.loads(line)
        except ValueError:
            continue
        if req.get("cmd") != "cancel": threading.Thread(target=run, args=(req,), daemon=True).start()
elif len(sys.argv) > 1 and sys.argv[1] == "thread":
    said = ["morning. quick one about the flat.", "Morning, Sam. Go on.", "the lease renewal is due on the first. can you let me know by then whether you are staying?",
            "I will check with the others and come back to you.", "thanks. no rush before the weekend.", "did you see my message about the renewal?"]
    print(json.dumps({"thread": "sam (landlord)", "title": "sam (landlord)", "src": "imessage", "focus": sys.argv[2] if len(sys.argv) > 2 else "", "open": None,
                      "rows_total": 1700, "from": "2022-05-01", "to": NOW.strftime("%Y-%m-%d"),
                      "rows": [{"id": f"I{k}", "ts": iso(NOW - timedelta(days=9, minutes=-k * 3)), "at": 0, "who": "me" if k in (1, 3) else "them", "me": k in (1, 3),
                                "sender": "" if k in (1, 3) else "sam", "text": t, "here": k == 2} for k, t in enumerate(said)]}))
elif len(sys.argv) > 1 and sys.argv[1] == "today":
    if "--dismiss" in sys.argv:
        print(json.dumps({"card": None}))
    else:
        print(json.dumps({"card": {"id": NOW.strftime("%Y-%m-%d") + "-promised-1", "kind": "promised", "state": "done" if "--done" in sys.argv else "unread",
                                   "line": "you told sam you would come back to him about the lease after checking with the others. that was nine days ago, and the renewal is due on the first.",
                                   "cite": {"id": "I3", "src": "imessage", "who": "me", "thread": "sam (landlord)", "ts": (NOW - timedelta(days=9)).strftime("%Y-%m-%d"), "at": 0,
                                            "quote": "I will check with the others and come back to you."},
                                   "action": {"label": "reply", "open": None, "thread": "I3"}}}))
elif len(sys.argv) > 1 and sys.argv[1] == "mcp" and "--status" in sys.argv:
    print(json.dumps([{"id": "claude_desktop", "name": "claude desktop", "installed": True, "registered": True, "config": "~/Library/Application Support/Claude/claude_desktop_config.json"},
                      {"id": "claude_code", "name": "claude code", "installed": True, "registered": True, "config": "~/.claude.json"},
                      {"id": "cursor", "name": "cursor", "installed": True, "registered": False, "config": "~/.cursor/mcp.json"},
                      {"id": "codex", "name": "codex", "installed": False, "registered": False, "config": "~/.codex/config.toml"}]))
elif len(sys.argv) > 1 and sys.argv[1] == "settings":
    calls = {"calls": 12, "tokens_in": 1, "tokens_out": 1}
    print(json.dumps({"usage": {"today": {"answer": calls}, "week": {"answer": calls, "coach": calls}, "cost": "$0 extra: calls run on the plan you already pay for"},
                      "archive": {"folder": "~/.context/v2", "bytes": 3e9, "rows": {"messages": 1000000, "docs": 80000}},
                      "read_through": {"reread_weekly": True, "read": 170, "units": 1600},
                      "keys": {"file": ".env in the engine folder", "present": [], "not_set": ["TELEGRAM_API_ID", "TELEGRAM_API_HASH"]},
                      "sync": {"settings": {"fast_minutes": 15, "daily_hour": 4, "weekly_day": "sun"}}}))
elif len(sys.argv) > 1 and sys.argv[1] == "lens":
    if "--list" in sys.argv or len(sys.argv) < 3:
        print(json.dumps([{"id": "intros", "title": "intros i promised", "about": "people you said you would introduce, and whether you did"},
                          {"id": "tasks", "title": "tasks i owe", "about": "things you told someone you would do"},
                          {"id": "money", "title": "money i agreed to", "about": "money you owe, are owed, or said you would pay or put in"},
                          {"id": "saved", "title": "things i saved", "about": "things you saved to come back to, and what you could do with each"}]))
    else:
        if not FAST:
            time.sleep(3)
        row = lambda i, who, text: {"id": f"W{i}", "src": "whatsapp", "ts": iso(NOW - timedelta(days=i)), "thread": who, "who": "me", "text": text}
        print(json.dumps({"title": "intros i promised", "summary": "you offered three introductions this month. one went out.", "items": [
            {"what": "introduce maya to jonas about the pricing page", "who": "maya okafor", "when": (NOW - timedelta(days=4)).strftime("%Y-%m-%d"), "status": "open", "cite": row(4, "maya okafor", "i'll intro you two this week")},
            {"what": "connect priya with the print shop", "who": "priya", "when": (NOW - timedelta(days=9)).strftime("%Y-%m-%d"), "status": "done", "cite": row(9, "priya", "sending the intro now")},
            {"what": "put tomas in touch with ines", "who": "tomas", "when": (NOW - timedelta(days=15)).strftime("%Y-%m-%d"), "status": "unclear", "cite": row(15, "tomas", "happy to put you in touch")}],
            "searched": ["intro", "introduce"], "error": ""}))
elif len(sys.argv) > 1 and sys.argv[1] == "connect":
    a = sys.argv[2:]
    if a[:1] == ["--search"]:
        q = (a[1] if len(a) > 1 else "").lower()
        known = [("granola", "Granola", "app", True), ("linear", "Linear", "service", False), ("spotify", "Spotify", "app", True)]
        print(json.dumps([{"id": i, "name": n, "kind": k, "installed": inst, "icon_path": "", "known": False} for i, n, k, inst in known if q in i]))
    elif a[:1] == ["--enable"]:
        print(json.dumps({"ok": True}))
    else:
        for phase in ("looking at where granola keeps its data", "reading how its notes are stored", "trying it on the newest ten"):
            print("@" + json.dumps({"phase": phase}), flush=True)
            if not FAST:
                time.sleep(1.2)
        print(json.dumps({"id": a[0], "name": a[0], "state": "ready", "how": "found granola's notes in its app folder", "sample": {"rows": 300, "since": "2024-05"}, "detail": ""}))
elif len(sys.argv) > 1 and sys.argv[1] == "relate":
    print(json.dumps({"notes": [{"line": "you already decided this in march: yearly on by default.",
                                 "cite": {"id": "N1", "src": "apple_notes", "ts": iso(NOW - timedelta(days=240)), "thread": "pricing page outline", "who": "me", "text": "three plans. yearly toggle on by default."}}], "error": ""}))
elif len(sys.argv) > 1 and sys.argv[1] == "bridge":
    print(json.dumps({"connected": True}))
elif len(sys.argv) > 1 and sys.argv[1] == "facts":
    print(json.dumps(FACTS))
elif len(sys.argv) > 1 and sys.argv[1] == "model":
    none = bool(os.environ.get("DEMO_NO_PLAN"))
    print(json.dumps({"claude": {"installed": True, "signed_in": not none, "fix": "run once in a terminal: claude auth login"},
                      "codex": {"installed": False, "signed_in": False, "fix": ""}, "api_key": False,
                      "using": "none" if none else "claude", "plan": "" if none else "your claude plan",
                      "fix": "run once in a terminal: claude auth login" if none else ""}))
elif len(sys.argv) > 1 and sys.argv[1] == "coach":
    print(json.dumps({"say": "you opened x eleven times since lunch. the pricing page has not moved since tuesday.",
                      "why": "three of the last four afternoons went the same way.", "kind": "drift", "confidence": 4}))
elif len(sys.argv) > 1 and sys.argv[1] == "request":
    request(sys.argv[2:])
elif len(sys.argv) > 1 and sys.argv[1] == "collect":
    collect()
elif len(sys.argv) > 1 and sys.argv[1] == "seed":
    seed()
else:
    print(__doc__)
