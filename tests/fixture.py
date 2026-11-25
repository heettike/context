"""A made-up archive in a temp folder. Import this before anything from ctx: paths are fixed when ctx is first imported.

Every name, message and number here is invented.
"""
import atexit, json, os, shutil, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = tempfile.mkdtemp(prefix="ctx-test-")
os.environ["CTX_HOME"] = HOME
os.environ["CTX_AGENT"] = "0"       # no test starts a real model loop; the tests of the loop itself hand it a made-up CLI
# no test finds the model CLIs of the mac it runs on, or a key in the repo's .env: a real call would spend the owner's plan.
# child processes get this too. a test that needs a CLI puts a made-up one in a folder and names it in CTX_CLI_PATH.
NO_CLI = os.path.join(HOME, "no-cli")
os.makedirs(NO_CLI, exist_ok=True)
os.environ["CTX_CLI_PATH"] = NO_CLI
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ.pop("CTX_MODEL", None)
# "~" is a made-up, empty home: no test reads this mac's own messages, notes, mail, browsers or apps
USER_HOME = os.path.join(HOME, "user-home")
os.makedirs(USER_HOME, exist_ok=True)
os.environ["HOME"] = USER_HOME
atexit.register(shutil.rmtree, HOME, ignore_errors=True)
if REPO not in sys.path:
    sys.path.insert(0, REPO)


def own_run():
    """The environment of the tool server of one run of the app's own answering loop: a real pass, made the way agent.py
    makes one (guard.agent_open). Use as: mock.patch.dict(os.environ, fixture.own_run())."""
    from ctx import guard
    token = guard.agent_open()
    atexit.register(guard.agent_close, token)
    return {guard.AGENT_RUN: token}


def msg(i, text, who="them", thread="ada lovelace", src="whatsapp", ts="2025-06-01T10:00:00Z", kind="dm", sender=None):
    return {"id": i, "src": src, "ts": ts, "thread_id": src + ":" + thread, "thread": thread, "kind": kind, "mine_total": 9,
            "who": who, "sender": sender or ("me" if who == "me" else thread), "text": text}


def doc(i, text, src, title="", ts="2025-05-01T09:00:00Z", url=""):
    return {"id": i, "src": src, "ts": ts, "title": title, "text": text, "url": url}


def rows():
    m, d = [], []
    m.append(msg("W1", "the kettle fund closes on friday", who="me"))
    m.append(msg("W2", "did you read the kettle memo", thread="grace hopper"))
    m.append(msg("W3", "kalam wrote about rockets", thread="grace hopper"))                    # holds "kal" only inside a longer word
    m.append(msg("W4", "milte hain kal subah", who="me", thread="grace hopper"))
    m.append(msg("W5", "investing in a kettle maker", who="me", ts="2024-03-05T08:00:00Z"))
    m.append(msg("W6", "we should invest slowly", ts="2023-11-20T08:00:00Z"))
    m.append(msg("W7", "nothing to see here", thread="whatsapp fans"))                         # the word is in the thread name only
    m.append(msg("W8", "x" * 900 + " the zeppelin landed safely " + "y" * 900, who="me"))
    m.append(msg("W9", "call me on +1 415 555 0100 or mail teapot@example.com about the samovar"))
    m.append(msg("W10", "samovar prices are in the sheet", thread="+1 415 555 0199"))
    m.append(msg("W11", "पढ़ाई ज़रूरी है", who="me"))
    m.append(msg("W12", "i’ll send the samovar deck tonight", who="me"))
    m.append(msg("DUP", "the quorum vote passed with a clear margin today", who="me"))
    m.append(msg("DUP", "the quorum vote passed with a clear margin today", who="me"))          # same id twice
    m.append(msg("W13", "The quorum vote passed, with a clear margin today!", who="me", thread="grace hopper"))   # same words again
    for n in range(40):                                                                        # one loud thread
        m.append(msg(f"L{n}", f"lantern festival plan number {n}", thread="loud group", kind="group", ts=f"2025-07-{n % 28 + 1:02d}T10:00:00Z"))
    for n in range(20):
        m.append(msg(f"Q{n}", f"lantern for the porch {n}", thread=f"quiet {n}", ts="2025-01-02T10:00:00Z"))
    for n in range(120):                                                                       # chat volume on one topic
        m.append(msg(f"C{n}", f"pottery class notes {n}", who="me" if n % 2 else "them", thread=f"friend {n % 30}"))
    m.append(msg("R1", "pottery glaze with celadon finish", thread="rare one"))
    # one person on three apps, under three spellings of the name
    for n in range(12):
        m.append(msg(f"MW{n}", f"gazebo permit step {n}", who="me" if n % 2 else "them", thread="Maya Okafor", ts=f"2025-03-{n + 1:02d}T09:00:00Z"))
    for n in range(6):
        m.append(msg(f"MT{n}", f"gazebo paint colour {n}", who="me" if n % 2 else "them", thread="maya okafor 🌿", src="telegram", ts=f"2025-04-{n + 1:02d}T09:00:00Z"))
    for n in range(4):
        m.append(msg(f"MI{n}", f"gazebo photo {n}", thread="Okafor, Maya", src="instagram", ts=f"2025-05-{n + 1:02d}T09:00:00Z"))
    m.append(msg("MX0", "hello from another maya", thread="Maya Stone", ts="2025-02-01T09:00:00Z"))
    m.append(msg("GZ0", "the gazebo crew meets sunday", thread="gazebo crew", kind="group", sender="Tomas", ts="2025-05-09T09:00:00Z"))
    # a conversation far too long to send whole: 3,000 messages over 2023 and 2024, with one topic raised twice
    for n in range(3000):
        text = f"harbour lease clause {n}" if n in (700, 2200) else f"day {n} small talk about the weather and the tide tables again"
        m.append(msg(f"V{n}", text, who="me" if n % 3 == 0 else "them", thread="Ravi Anand",
                     ts=f"{2023 + n // 1500}-{n % 1500 // 125 + 1:02d}-{n % 125 // 5 + 1:02d}T{n % 5 + 8:02d}:00:00Z"))
    for n in range(30):
        d.append(doc(f"IL{n}", f"a liked post about pottery wheels {n}", "instagram_likes", url=f"https://example.com/p/{n}"))
    for n in range(3):
        d.append(doc(f"B{n}", f"a thread on pottery kilns {n}", "x_bookmarks", url=f"https://example.com/b/{n}"))
        d.append(doc(f"IS{n}", f"a saved reel on pottery glazing {n}", "instagram_saved"))
    d.append(doc("N1", "my note: pottery is how i rest", "apple_notes", title="rest"))
    d.append(doc("O1", "pottery studio shortlist", "obsidian", title="studios"))
    d.append(doc("G1", "pottery budget spreadsheet", "gdrive", title="budget"))
    for n in range(30):
        d.append(doc(f"H{n}", "", "browser_history", title=f"pottery shop page {n}", url=f"https://example.com/shop/{n}"))
    p = [{"id": "P1", "src": "claude_code", "ts": "2025-08-01T10:00:00Z", "thread": "demo", "who": "me", "text": "write a pottery inventory script"}]
    s = [{"id": "S1", "src": "codex", "title": "kiln timer", "project": "demo", "first_user": "build a kiln timer", "last_user": "ship it",
          "last_user_ts": "2025-08-02T10:00:00Z", "last_agent": "the kiln timer is done", "last_agent_ts": "2025-08-02T11:00:00Z", "user_turns": 3}]
    return {"messages.jsonl": m, "docs.jsonl": d, "prompts.jsonl": p, "sessions.jsonl": s}


def write(home=HOME):
    for name, rs in rows().items():
        with open(os.path.join(home, name), "w") as f:
            for r in rs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            if name == "messages.jsonl":
                f.write("this line is not json but says kettle\n")
    os.makedirs(os.path.join(home, "memory", "cards"), exist_ok=True)
    with open(os.path.join(home, "memory", "core.md"), "w") as f:
        f.write("they make pottery and fund kettles.\n")
    with open(os.path.join(home, "memory", "people.md"), "w") as f:
        f.write("ada lovelace: friend.\n- **grace hopper** (the admiral): old colleague.\n")
    with open(os.path.join(home, "memory", "cards", "chat_whatsapp_Ravi_Anand.json"), "w") as f:
        json.dump({"_title": "Ravi Anand", "_src": "whatsapp", "_mine": 1000, "who": "the landlord of the harbour unit",
                   "about": ["the lease"], "decisions": [{"what": "renewed for two years", "when": "2024-06"}], "arc": "formal, then friendly"}, f)
    card = {"_title": "ada lovelace", "_src": "whatsapp", "_mine": 12, "_from": "2024-01-01", "_to": "2025-06-01", "_key": "k", "_at": 1700000000,
            "who": "a close friend", "about": ["kettles"], "people": [{"name": "charles babbage", "role": "her collaborator, reach him on +1 415 555 0123"}],
            "facts": ["writes to bab@example.com"], "open": [], "arc": "steady", "tone": "warm"}
    with open(os.path.join(home, "memory", "cards", "k.json"), "w") as f:
        json.dump(card, f)
    with open(os.path.join(home, "status.json"), "w") as f:
        json.dump({"whatsapp": {"rows": 200}}, f)


write()


def index():
    """The word index for the made-up archive, so the whole suite runs through it (a test that changes a file makes
    its index stale, and search then reads the file whole, as it should)."""
    from ctx import wordindex
    wordindex.warm()


index()
