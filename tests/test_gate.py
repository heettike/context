"""One gate for every reader: the never list and the owner's rules hold for every way a row, a count, a card or a page
can leave the archive. A made-up archive is written to a fresh CTX_HOME in a child process (so nothing here shares the
suite's own made-up archive), and one of these holds (MODES): the never list with one source, one person and one
stretch of days, a rule that leaves one conversation out and another that forgets one row ("closed"); the never list
with a source only, with a stretch of days only, or with both and no person (and the search index made again after
it, or not); a leave-out rule with after and before.
Then every reader is called: every mcp tool by name, every api route with an --all key, /v1/ask with a stand-in model,
the tools, facts, the read-through's pages and its prompt pieces, the close read's units, peek, voice, the counts, the
open loops, the day's card, the wider look, the wiki and its build, and readers in one thread while another reads the
archive with no rule applied. Nothing hidden may be in any of it, nor in anything that would be sent to a model. A
never.json, rules.json or forgotten.json that cannot be read closes every reader with one error.

Every name, message and date here is invented. No model is called: the model calls are replaced by ones that keep
what they were sent and answer nothing, and the answering model by a stand-in that cites every id it is shown and
every hidden one besides."""
import json, os, re, shutil, subprocess, sys, tempfile, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY_HIDDEN = "2021-03-"
BROKEN = {"broken": ("never.json", json.dumps({"sources": ["telegram"], "ranges": [["2021-03", "not a day"]]})),        # a range written by hand, half a day
          "broken-rules": ("rules.json", '{"rules": [{"id": "r1", "kind": "leave_out", "target": {"threads": ["whatsapp:Hollis Gr'),  # cut off mid-write
          "broken-gone": ("forgotten.json", json.dumps({"ids": "F1"})),                                                         # not a list of ids
          "null-rules": ("rules.json", "null"), "null-gone": ("forgotten.json", "null")}                                       # json, but no list of anything
TOTALS = ("teacup", "teacup; marzipan", "zircon; marzipan; kumquat; brambling; quokka; lanternfish; nightjar; gazpacho; halyard")

# what no reader may hand out once the never list and the rules hold: words only the hidden rows, cards and pages have
HIDDEN = ("marzipan", "zircon", "ottoline", "kumquat", "pemberton", "brambling", "quokka", "hollis", "lanternfish", "nightjar",
          "gazpacho", "halyard", "telegram", TODAY_HIDDEN, "march 2021")
SHOWN = ("teacup", "orchard", "garden club")         # and what is left, which must still be there
RANGE = ("marzipan", "nightjar", "gazpacho", "halyard", TODAY_HIDDEN, "march 2021")      # only the stretch of days has these
SOURCE = ("zircon", "ottoline", "telegram")                                             # only the source has these
MARCH = [["2021-03-01", "2021-03-31"]]
MODES = {   # mode: (the never list, or None for none; the rules saved; the words no reader may hand out)
    "closed": ({"sources": ["telegram"], "people": ["pemberton quill"], "ranges": MARCH},
               [{"kind": "leave_out", "said": "leave out hollis", "target": {"threads": ["whatsapp:Hollis Grange"], "thread_names": ["Hollis Grange"]}},
                {"kind": "forget", "said": "forget the lanternfish recipe", "target": {"words": ["lanternfish"]}}], HIDDEN),
    "source": ({"sources": ["telegram"], "people": [], "ranges": []}, [], SOURCE),
    "range": ({"sources": [], "people": [], "ranges": MARCH}, [], RANGE),
    "noperson": ({"sources": ["telegram"], "people": [], "ranges": MARCH}, [], SOURCE + RANGE),
    "rebuilt": ({"sources": ["telegram"], "people": [], "ranges": MARCH}, [], SOURCE + RANGE),         # and the index made again after it
    "dates": (None, [{"kind": "leave_out", "said": "leave out march 2021", "target": {"after": "2021-03-01", "before": "2021-04-01"}}], RANGE),
}
# the ids of rows that hold hidden words, by the words: the stand-in model cites them all, and none may come back
HIDDEN_IDS = {"marzipan": ["M3", "M8", "M10", "X9", "B2"], "nightjar": ["N2"], "gazpacho": ["PR2"], "halyard": ["S2"], "zircon": ["T1", "T3"],
              "kumquat": ["P1"], "brambling": ["GP1"], "quokka": ["H1"], "lanternfish": ["F1"]}
ASKS = ("what about the marzipan order and the zircon samples", "the teacup club and the halyard race")
TOTAL_WORDS = ("zircon", "marzipan", "kumquat", "brambling", "quokka", "lanternfish", "nightjar", "gazpacho", "halyard")


def totals(mode):
    """The searches a mode's counts are checked on: a word seen alone, with the words only hidden rows have, and those alone."""
    hid = "; ".join(w for w in TOTAL_WORDS if w in MODES[mode][2])
    return ("teacup", "teacup; " + hid, hid)


ALL_TOTALS = tuple(sorted(set(TOTALS) | {q for m in MODES for q in totals(m)}))
Q1 = "marzipan; zircon; kumquat; brambling; quokka"
Q2 = "lanternfish; nightjar; gazpacho; halyard; teacup; orchard"
NAMES = ("Ada Lovelace", "Pemberton Quill", "Hollis Grange", "Ottoline Brack", "Garden Club")
CALLS = ([("about_me", {}), ("facts", {}), ("open_loops", {}), ("sources", {})]
         + [("page", {"name": p}) for p in ("people", "projects", "timeline", "voice")]
         + [("person", {"name": n}) for n in ("pemberton quill", "pemberton", "hollis grange", "ottoline brack", "ada lovelace", "ivo smart", "garden club")]
         + [("search", {"query": Q1}), ("search", {"query": Q2}), ("search", {"query": Q1, "mode": "words"}), ("search", {"query": "garden; seeds", "people": ["garden club"]}),
            ("search", {"query": "marzipan", "after": "2021-01", "before": "2021-12"})]
         + [("read_thread", {"thread": n}) for n in NAMES]
         + [("read_thread", {"around": i}) for i in ("A5", "A31", "M3", "G3", "GP1", "T1", "F1")]
         + [("read_thread", {"thread": "Ada Lovelace", "after": "2021-01", "before": "2021-12"})]
         + [("card", {"thread": n}) for n in NAMES]
         + [("timeline", {"after": "2021", "before": "2023"}), ("timeline", {"after": "2021-03", "before": "2021-03"})]
         + [("saved", {"query": q}) for q in ("orchard", "zircon", "marzipan")] + [("saved", {})]
         + [("links", {"query": "orchard"}), ("links", {"query": "zircon"})]
         + [("doc", {"id": i}) for i in ("A1", "M3", "T1", "P1", "H1", "GP1", "F1", "N1", "N2", "X1", "X9", "PR2", "S2")]
         + [("profile", {"section": s}) for s in ("core", "people", "projects", "timeline", "voice")]
         + [("voice", {"channel": "x_posts"}), ("voice", {"channel": "overall"})]
         + [("wiki", {"query": q}) for q in ("ada lovelace", "pemberton", "garden", "ottoline", "2021")]
         + [("wiki", {"page": p}) for p in ("people/ada-lovelace", "people/pemberton-quill", "people/ottoline-brack", "years/2021", "topics/garden")]
         + [("stats", {"what": w}) for w in ("people", "months", "overview")]
         + [("stats", {"what": "person", "person": "ada lovelace"}), ("stats", {"what": "person", "person": "pemberton quill"}),
            ("stats", {"what": "count", "query": Q1}), ("stats", {"what": "count", "query": "lanternfish; nightjar; gazpacho; halyard"})]
         + [("lapsed", {"what": w, "months": 24}) for w in ("lapsed", "quiet", "new", "lately", "least")]
         + [("shared", {}), ("intros", {}), ("conflicts", {}), ("ideas", {}), ("ideas", {"status": "dropped"})])


# ---------------------------------------------------------------- the made-up archive

def archive():
    m, d, p, s = [], [], [], []

    def msg(i, text, thread, src="whatsapp", ts="2022-05-01T10:00:00Z", who="them", kind="dm", sender=None):
        m.append({"id": i, "src": src, "ts": ts, "thread_id": src + ":" + thread, "thread": thread, "kind": kind, "mine_total": 40,
                  "who": who, "sender": sender or ("me" if who == "me" else thread), "text": text})
    for n in range(32):                                     # a friend, seen
        msg("A%d" % n, "the teacup club meets on thursday, round %d" % n, "Ada Lovelace", who="me" if n % 2 else "them", ts="2022-%02d-%02dT10:00:00Z" % (n % 12 + 1, n % 27 + 1))
    for n in range(12):                                     # and a stretch of days the never list holds, in the same conversation
        msg("M%d" % n, "the marzipan order, part %d" % n, "Ada Lovelace", who="me" if n % 2 else "them", ts="2021-03-%02dT10:00:00Z" % (n + 2))
    for n in range(12):
        msg("I%d" % n, "teacup photos from the market %d" % n, "Ivo Smart", src="imessage", who="me" if n % 2 else "them", ts="2023-01-%02dT10:00:00Z" % (n + 1))
    for n in range(14):                                     # a source the never list holds
        msg("T%d" % n, "the zircon samples arrived, box %d" % n, "Ottoline Brack", src="telegram", who="me" if n % 2 else "them", ts="2022-06-%02dT10:00:00Z" % (n + 1))
    for n in range(14):                                     # a person the never list holds
        msg("P%d" % n, "kumquat harvest notes %d" % n, "Pemberton Quill", who="me" if n % 2 else "them", ts="2022-07-%02dT10:00:00Z" % (n + 1))
    for n in range(10):                                     # a group, seen, that the listed person writes in too
        msg("G%d" % n, "the garden club meets at dawn %d" % n, "Garden Club", kind="group", who="me" if n % 3 == 0 else "them", sender="me" if n % 3 == 0 else "Ivo Smart", ts="2022-08-%02dT10:00:00Z" % (n + 1))
    for n in range(4):
        msg("GP%d" % n, "brambling seeds for everyone %d" % n, "Garden Club", kind="group", sender="Pemberton Quill", ts="2022-08-%02dT11:00:00Z" % (n + 12))
    for n in range(14):                                     # a conversation the owner leaves out
        msg("H%d" % n, "the quokka feeding rota %d" % n, "Hollis Grange", who="me" if n % 2 else "them", ts="2022-07-%02dT12:00:00Z" % (n + 1))
    msg("F1", "the lanternfish recipe is in the blue drawer", "Ada Lovelace", who="me", ts="2022-09-09T10:00:00Z")      # a row the owner forgets

    def doc(i, text, src, ts, title="", url="", who=None):
        d.append(dict({"id": i, "src": src, "ts": ts, "title": title, "text": text, "url": url}, **({"who": who} if who else {})))
    doc("N1", "my note about the orchard app and its teacup icon", "apple_notes", "2022-04-01T09:00:00Z", title="orchard")
    doc("N2", "nightjar sightings by the river", "apple_notes", "2021-03-10T09:00:00Z", title="birds")
    for n in range(8):
        doc("X%d" % (n + 1), "shipping the orchard app today, build %d" % n, "x_posts", "2022-%02d-02T09:00:00Z" % (n + 2), who="me")
    doc("X9", "marzipan launch day is here", "x_posts", "2021-03-05T09:00:00Z", who="me")
    doc("X10", "marzipan stall is open again", "x_posts", "2021-03-20T09:00:00Z", who="me")
    doc("B1", "a thread about orchards and teacups", "x_bookmarks", "2022-04-03T09:00:00Z", url="https://example.com/b/1")
    doc("B2", "a thread about marzipan moulds", "x_bookmarks", "2021-03-06T09:00:00Z", url="https://example.com/b/2")
    p.append({"id": "PR1", "src": "claude_code", "ts": "2022-05-05T10:00:00Z", "thread": "orchard", "who": "me", "text": "write the orchard sync script"})
    p.append({"id": "PR2", "src": "claude_code", "ts": "2021-03-12T10:00:00Z", "thread": "importer", "who": "me", "text": "write the gazpacho importer"})
    s.append({"id": "S1", "src": "codex", "title": "orchard timer", "project": "orchard", "first_user": "build the orchard timer", "last_user": "ship it",
              "last_user_ts": "2022-05-06T10:00:00Z", "last_agent": "the orchard timer is done", "last_agent_ts": "2022-05-06T11:00:00Z", "user_turns": 3})
    s.append({"id": "S2", "src": "codex", "title": "halyard tracker", "project": "halyard", "first_user": "build the halyard tracker", "last_user": "stop",
              "last_user_ts": "2021-03-15T10:00:00Z", "last_agent": "the halyard tracker is half done", "last_agent_ts": "2021-03-15T11:00:00Z", "user_turns": 2})
    return {"messages.jsonl": m, "docs.jsonl": d, "prompts.jsonl": p, "sessions.jsonl": s}


PAGES = {   # written by the read-through before the never list and the rules: each hidden word sits on a line that names what hides it
    "core": "they build an orchard app and collect teacups.\nin march 2021 they ordered marzipan for everyone.\npemberton quill grows kumquats with them.\n"
            "most evenings they write on telegram about zircon.\nhollis grange keeps the quokka rota.\non 2021-03-14 they watched the nightjar.\nthey write in lowercase.\n",
    "people": "- **ada lovelace**: a close friend from the teacup club.\n- **pemberton quill**: grows kumquat trees, posts brambling seeds.\n"
              "- **hollis grange**: runs the quokka farm.\n- **ottoline brack**: sends zircon samples.\n",
    "projects": "- orchard app (2022): active.\n- gazpacho importer (march 2021): shelved.\n- halyard tracker (2021-03): shelved.\n",
    "timeline": "# 2021\n- 2021-03: the marzipan month, the gazpacho importer.\n# 2022\n- 2022-05: the orchard app.\n",
    "voice": "in chats they write short lines about teacups.\non telegram they write long zircon essays.\n",
}
WIKI = {    # id: (title, kind, summary, body)
    "people/ada-lovelace": ("ada lovelace", "people", "a close friend from the teacup club", "she runs the teacup club. [[r:A1]]\n\nshe ordered marzipan in bulk. [[r:M3]]\n\nshe knows pemberton quill well. [[r:A2]]"),
    "people/pemberton-quill": ("pemberton quill", "people", "grows kumquats", "he grows kumquats. [[r:P1]]"),
    "people/ottoline-brack": ("ottoline brack", "people", "a pen friend", "they swap zircon samples. [[r:T1]]\n\nshe sends a box a week. [[r:T2]]"),
    "years/2021": ("2021", "years", "the year of the teacup club", "in 2021 they started the teacup club. [[r:A3]]\n\nthe marzipan orders peaked. [[r:M1]]\n\nthe quokka rota began. [[r:H1]]"),
    "topics/garden": ("the garden club", "people", "pemberton quill posts brambling seeds there", "the garden club meets at dawn. [[r:G1]]\n\nbrambling seeds go round. [[r:GP1]]\n\nthe lanternfish recipe came up. [[r:F1]]"),
}
CARD = {"_key": "chat:whatsapp:Ada Lovelace", "_title": "Ada Lovelace", "_src": "whatsapp", "_kind": "dm", "_n": 45, "_mine": 22, "_from": "2021-03-02", "_to": "2022-12-27",
        "who": "a close friend from the teacup club", "about": ["the teacup club", "the marzipan orders of march 2021"], "decisions": [{"what": "bought marzipan", "when": "2021-03"}],
        "people": [{"name": "pemberton quill", "role": "a mutual friend"}], "facts": ["keeps teacups"], "open": [], "arc": "steady", "tone": "warm"}
HIDDEN_CARDS = {"whatsapp:Pemberton Quill": "kumquat", "whatsapp:Hollis Grange": "quokka", "telegram:Ottoline Brack": "zircon"}
EVENTS = [{"t": "conflict", "with": "pemberton quill", "area": "money", "topic": "kumquat crates", "heat": 2, "resolved": False, "thread": "Pemberton Quill", "src": "whatsapp", "tid": "whatsapp:Pemberton Quill", "rows": ["P2"], "when": "2022-07"},
          {"t": "intro", "by": "me", "a": "ottoline brack", "b": "the zircon guild", "done": True, "thread": "Ottoline Brack", "src": "telegram", "tid": "telegram:Ottoline Brack", "rows": ["T3"], "when": "2022-06"},
          {"t": "idea", "what": "a quokka cafe", "with": "hollis grange", "status": "dropped", "fate": "dropped", "thread": "Hollis Grange", "src": "whatsapp", "tid": "whatsapp:Hollis Grange", "rows": ["H3"], "when": "2022-07"},
          {"t": "idea", "what": "a marzipan stall", "with": "", "status": "dropped", "fate": "dropped", "thread": "Ada Lovelace", "src": "whatsapp", "tid": "whatsapp:Ada Lovelace", "rows": ["M5"], "when": "2021-03"},
          {"t": "idea", "what": "a teacup museum", "with": "ivo smart", "status": "built", "fate": "built", "thread": "Ivo Smart", "src": "imessage", "tid": "imessage:Ivo Smart", "rows": ["I2"], "when": "2023-01"},
          {"t": "commitment", "by": "me", "to": "pemberton quill", "what": "return the kumquat crates", "done": False, "thread": "Pemberton Quill", "src": "whatsapp", "tid": "whatsapp:Pemberton Quill", "rows": ["P4"], "when": "2022-07"}]
FACTS = [   # the knowledge layer (deep.py), written before the list and the rules: each statement with the rows it rests on
    {"s": "ottoline brack", "p": "sends", "o": "zircon samples every week", "ids": ["T3"], "thread": "Ottoline Brack", "src": "telegram", "when": "2022-06-04"},
    {"s": "ada lovelace", "p": "ordered", "o": "marzipan in bulk", "ids": ["M3"], "thread": "Ada Lovelace", "src": "whatsapp", "when": "2021-03-05"},
    {"s": "the teacup club", "p": "plans", "o": "a halyard race on the lake", "ids": ["X3", "M4"], "thread": "Ada Lovelace", "src": "whatsapp", "when": "2022-04-02"},   # one row seen, one in the stretch
    {"s": "the teacup club", "p": "meets", "o": "on thursday evenings", "ids": ["A1"], "thread": "Ada Lovelace", "src": "whatsapp", "when": "2022-02-02"}]
LOOPS = [{"q": "did you send ada the teacup photos?", "kind": "owe", "thread": "Ada Lovelace", "date": "2022-12-01", "ids": ["A5"]},
         {"q": "reply about the kumquat crates", "kind": "owe", "thread": "Pemberton Quill", "date": "2022-07-10", "ids": ["P3"]},
         {"q": "the quokka rota for next week", "kind": "promise", "thread": "Hollis Grange", "date": "2022-07-01", "ids": ["H2"]},
         {"q": "send the zircon samples back", "kind": "owe", "thread": "Ottoline Brack", "date": "2022-06-03", "ids": ["T2"]},
         {"q": "pay the invoice for the order", "kind": "owe", "thread": "Ada Lovelace", "date": "2021-03-09", "ids": ["M4"]}]


def write(home):
    for name, rows in archive().items():
        with open(os.path.join(home, name), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    mem = os.path.join(home, "memory")
    for sub in ("cards", "wiki", "voice", os.path.join("deep", "events")):
        os.makedirs(os.path.join(mem, sub), exist_ok=True)
    for name, text in PAGES.items():
        with open(os.path.join(mem, name + ".md"), "w", encoding="utf-8") as f:
            f.write(text)
    key = lambda k: "".join(c if c.isalnum() or c in "_.-" else "_" for c in k)[:80]
    with open(os.path.join(mem, "cards", key("chat:whatsapp:Ada Lovelace") + ".json"), "w", encoding="utf-8") as f:
        json.dump(CARD, f)
    for tid, word in HIDDEN_CARDS.items():
        src, title = tid.split(":", 1)
        with open(os.path.join(mem, "cards", key("chat:" + tid) + ".json"), "w", encoding="utf-8") as f:
            json.dump({"_key": "chat:" + tid, "_title": title, "_src": src, "_kind": "dm", "_n": 14, "_mine": 7, "_from": "2022-06-01", "_to": "2022-07-14",
                       "who": "someone who talks about " + word, "about": [word], "facts": [word + " every week"], "arc": word}, f)
    pages = []
    for pid, (title, kind, summary, body) in WIKI.items():
        os.makedirs(os.path.join(mem, "wiki", os.path.dirname(pid)), exist_ok=True)
        with open(os.path.join(mem, "wiki", pid + ".md"), "w", encoding="utf-8") as f:
            f.write("# %s\n\n> %s\n\n%s\n" % (title, summary, body))
        pages.append({"id": pid, "title": title, "kind": kind, "path": pid + ".md", "words": 20, "summary": summary})
    with open(os.path.join(mem, "wiki", "index.json"), "w", encoding="utf-8") as f:
        json.dump({"pages": pages}, f)
    with open(os.path.join(mem, "voice", "x_posts.md"), "w", encoding="utf-8") as f:
        f.write("## what the owner does\n- short posts about the orchard app\n- in march 2021 they posted about marzipan every day\n")
    with open(os.path.join(mem, "voice", "x_posts.json"), "w", encoding="utf-8") as f:
        json.dump([{"id": "X1", "ts": "2022-02-02", "text": "shipping the orchard app today, build 0", "likes": 3},
                   {"id": "X9", "ts": "2021-03-05", "text": "marzipan launch day is here", "likes": 9}], f)
    with open(os.path.join(mem, "deep", "events", "events.jsonl"), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(e) + "\n" for e in EVENTS)
    with open(os.path.join(mem, "deep", "facts.jsonl"), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(e) + "\n" for e in FACTS)
    with open(os.path.join(home, "loops.json"), "w", encoding="utf-8") as f:
        json.dump(LOOPS, f)
    with open(os.path.join(home, "loops.md"), "w", encoding="utf-8") as f:
        f.writelines('%d. %s\n   %s | %s | %s | %s\n' % (i, l["q"], l["kind"], l["thread"], l["date"], ", ".join(l["ids"])) for i, l in enumerate(LOOPS, 1))
    with open(os.path.join(home, "status.json"), "w", encoding="utf-8") as f:
        json.dump({"whatsapp": {"rows": 118}, "telegram": {"rows": 14}, "imessage": {"rows": 12}, "apple_notes": {"rows": 2}, "x_posts": {"rows": 10}}, f)


# ---------------------------------------------------------------- the child: one archive, every reader

def child(mode):
    """Run in a fresh process whose CTX_HOME is a new empty folder (see Gate.run). Prints one JSON object:
    {"out": {reader: what it returned, as text}, "sent": [what would have gone to a model], "errors": [...], ...}."""
    import array, hashlib, math, threading, time, urllib.parse, urllib.request
    from unittest import mock
    home = os.environ["CTX_HOME"]
    assert os.path.basename(home).startswith("ctx-gate-") and not os.listdir(home), home        # never anyone's real archive
    write(home)
    sys.path.insert(0, REPO)
    from ctx import llm
    sent = []

    def keep(system, prompt, *a, **k):
        sent.append("%s\n%s" % (system, prompt))
    patches = [mock.patch.object(llm, "ask", lambda *a, **k: keep(*a, **k) or "nothing to add."), mock.patch.object(llm, "ask_json", lambda *a, **k: keep(*a, **k) or {}),
               mock.patch.object(llm, "stream", lambda *a, **k: keep(*a, **k) or "")]
    for p in patches:
        p.start()
    from ctx import (agent, aggregate, answer, api, coach, deep, facts, loops, mcp, now, peek, people, recall, rules, semantic, today, tools,
                     understand, voice, wiki)
    api.PER_MINUTE = 10_000
    # the app's own answering loop: what its model would be told is kept, and no model is started
    mock.patch.object(agent, "command", lambda model, system, config: (keep(system, ""), [os.path.join(home, "no-such-model")])[1]).start()
    # the answering model of a quick answer (agent.lean): a stand-in that keeps what it was handed and answers with every
    # id it was shown and every hidden one besides, and two links (one a hidden row holds)
    model = []

    def stand_in(system, prompt, name, usage=None, *a, **k):
        model.append({"system": system, "prompt": prompt})
        ids = list(dict.fromkeys(re.findall(r"\[([A-Z]+\d+)\]", prompt) + [i for v in HIDDEN_IDS.values() for i in v]))
        yield "the teacup club meets on thursday %s, see https://example.com/b/1 and https://example.com/b/2.\n===\n{\"strength\": \"strong\"}" % " ".join("[%s]" % i for i in ids)
    for p in (mock.patch.object(llm, "_claude_stream", stand_in), mock.patch.object(agent, "model_for", lambda *a, **k: "made-up")):
        p.start()

    def embed(texts):           # a made-up embedder: each word adds to one place, so texts that share words are close
        out = array.array("f")
        for t in texts:
            v = [0.0] * semantic.DIM
            for w in semantic.tokens(t):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % semantic.DIM] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.extend(x / n for x in v)
        return out.tobytes()

    def ask_helper(question, words, name, vectors, emb="test", dim=512):
        q = array.array("f")
        q.frombytes(embed([question if isinstance(question, str) else " ".join(question)]))
        cos = array.array("f")
        if vectors and os.path.exists(vectors):
            got = array.array("f")
            with open(vectors, "rb") as f:
                got.frombytes(f.read())
            for i in range(len(got) // semantic.DIM):
                cos.append(sum(a * b for a, b in zip(q, got[i * semantic.DIM:(i + 1) * semantic.DIM])))
        return {}, (cos if len(cos) else None)
    for p in (mock.patch.object(semantic, "ask_helper", ask_helper), mock.patch.object(semantic, "helper", lambda: "")):
        p.start()
    report = {"stamps": [rules.stamp()], "errors": []}
    try:                        # built before any rule, as an index and a measure of the voice are on a real archive
        semantic.build(embedder=embed, say=lambda **kw: None, workers=1)
        voice.build(model=False)
    except Exception as e:
        report["errors"].append("build: %s: %s" % (type(e).__name__, e))
    if mode in MODES:
        never, saved, _ = MODES[mode]
        if never is not None:
            api.set_never(**never)
            report["stamps"].append(rules.stamp())
        for rule in saved:
            got = rules.save(dict(rule))
            assert "error" not in got, got
        if mode == "closed":
            with open(os.path.join(home, "messages.jsonl"), "a", encoding="utf-8") as f:       # a later read of the source writes it again
                f.write(json.dumps([r for r in archive()["messages.jsonl"] if r["id"] == "F1"][0]) + "\n")
            report["stamps"].append(rules.stamp())
        if mode in ("closed", "rebuilt"):
            try:                    # a forget drops the search index; the next build makes it again from every row, the hidden ones too
                semantic.build(embedder=embed, say=lambda **kw: None, workers=1)
            except Exception as e:
                report["errors"].append("rebuild: %s: %s" % (type(e).__name__, e))
        # in every other mode the index is the one made before the list and the rules: its stretches of a conversation
        # are dated by their last message, and its statements of the knowledge layer by the row they land on
    elif mode in BROKEN:                    # one of the three files the gate reads, there but not readable
        with open(os.path.join(home, BROKEN[mode][0]), "w", encoding="utf-8") as f:
            f.write(BROKEN[mode][1])
        rules._mem.clear()
        report["broken"] = rules.broken()
    with open(os.path.join(home, "today.json"), "w", encoding="utf-8") as f:     # the day's card, made this morning from a row the list holds now
        json.dump({"day": today._day(), "shown": {}, "made": int(time.time()),
                   "card": {"id": "c1", "kind": "years_ago", "line": "two years ago you wrote about the order for the stall", "state": "unread", "action": {"label": "open"},
                            "cite": {"id": "M2", "src": "whatsapp", "who": "me", "thread": "Ada Lovelace", "ts": "2021-03-04", "quote": "the marzipan order, part 2"}}}, f)
    out = {}

    def take(name, fn):
        try:
            got = fn()
        except (tools.Bad, mcp.Bad, api.Bad) as e:
            got = "BAD: %s" % e
        except Exception as e:
            got = "EXC: %s: %s" % (type(e).__name__, e)
        out[name] = got if isinstance(got, str) else json.dumps(got, ensure_ascii=False, default=str)

    for name, args in CALLS:
        if name in tools.RUN:
            take("tools.%s %s" % (name, json.dumps(args)), lambda: tools.run(name, args))
        take("mcp.%s %s" % (name, json.dumps(args)), lambda: mcp.call(name, args))
        take("mcp-strict.%s %s" % (name, json.dumps(args)), lambda: mcp.call(name, args, strict=True))
    take("handle about_me", lambda: mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "context_about_me", "arguments": {}}}))
    # the local api, as a program with an --all key reads it
    with mock.patch.object(api, "start", lambda *a, **k: {"url": "http://127.0.0.1:1/v1"}):
        key = api.make_key("everything", all_=True, days=1)
    srv = api.make_server(0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def call(method, path, body=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": "Bearer " + key})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return {"status": r.status, "body": json.loads(r.read())}
        except urllib.error.HTTPError as e:
            with e:
                return {"status": e.code, "body": json.loads(e.read() or b"{}")}
    q = urllib.parse.quote
    routes = [("GET", "/v1/search?q=" + q(Q1), None), ("GET", "/v1/search?q=" + q(Q2), None), ("GET", "/v1/search?q=" + q("garden; seeds") + "&people=" + q("garden club"), None),
              ("GET", "/v1/search?q=marzipan&after=2021-01&before=2021-12", None), ("GET", "/v1/search?q=zircon&sources=telegram", None)]
    routes += [("GET", "/v1/people/" + q(n.lower()), None) for n in NAMES + ("pemberton",)]
    routes += [("GET", "/v1/wiki?q=" + q(w), None) for w in ("ada", "pemberton", "garden", "2021")] + [("GET", "/v1/wiki/" + pid, None) for pid in WIKI]
    routes += [("GET", "/v1/profile", None)] + [("GET", "/v1/profile/" + s, None) for s in ("core", "people", "projects", "timeline", "voice")]
    routes += [("GET", "/v1/briefing", None), ("GET", "/v1/sources", None)] + [("POST", "/v1/ask", {"question": a}) for a in ASKS]
    routes += [("POST", p, {"question": ASKS[0]}) for p in ("//v1/ask", "/v1//ask", "/v1/%61sk")]          # the same route, spelled otherwise
    routes += [("POST", "/v1/tools/" + name, args) for name, args in CALLS]
    for method, path, body in routes:
        take("api %s %s %s" % (method, path, json.dumps(body)), lambda: call(method, path, body))
    report["static"] = {p: json.dumps(call("GET", p), ensure_ascii=False) for p in ("/v1", "/v1/openapi.json", "/v1/tools")}
    srv.shutdown()
    srv.server_close()
    # the readers themselves, and the prompt pieces the app's own answers and the nightly passes are made of
    take("facts.facts", facts.facts)
    take("understand.units", understand.units)
    take("understand.about", understand.about)
    take("understand.now", lambda: understand.now(days=4000, today="2023-02-01"))
    take("understand.core", understand.core)
    for p in PAGES:
        take("understand.page " + p, lambda: understand.page(p))
    take("understand.cards", understand.cards)
    take("understand.run", lambda: understand.run(workers=1))
    take("answer.pages", answer._pages)
    take("answer.period", lambda: answer._period("2021-01", "2021-12"))
    take("answer.thread_index", lambda: {k: v for k, v in answer.thread_index().items() if k != "offs"})
    take("answer.search", lambda: answer.search(answer.clean_probes([x for x in (Q1 + ";" + Q2).split(";")], most=12), limit=60))
    for i in ("A5", "A31", "M3", "G3", "GP1", "T1", "P1", "H1", "F1", "N2", "X9", "PR2", "S2"):
        take("peek.thread " + i, lambda: peek.thread(i, 20, 20))
        take("peek.find " + i, lambda: peek.find(i))
    take("peek.thread A0 5 5", lambda: peek.thread("A0", 5, 5))
    take("voice.posts", voice.posts)
    for ch in ("x_posts", "overall"):
        take("voice.tool " + ch, lambda: voice.tool(ch))
        take("voice.guide " + ch, lambda: voice.guide(ch))
    take("aggregate.overview", aggregate.overview)
    take("aggregate.shared", aggregate.shared)
    for fn in ("lapsed", "quiet", "new", "lately"):
        take("aggregate." + fn, lambda: getattr(aggregate, fn)(24))
    take("people.people", people.people)
    for n in NAMES:
        take("people.person " + n, lambda: people.person(n))
    take("loops.batches", lambda: "\n".join(open(f, encoding="utf-8").read() for f in loops.batches(days=4000, note_days=4000)))
    take("loops.kept", loops.kept)
    take("loops.text", loops.text)
    take("today.candidates", lambda: today.candidates(now=time.mktime(time.strptime("2023-03-06", "%Y-%m-%d"))))
    take("today.get", today.get)
    take("today.build", lambda: today.build(now=time.mktime(time.strptime("2023-03-06", "%Y-%m-%d")), force=True))
    take("now.build", lambda: now.build(now=time.mktime(time.strptime("2022-08-20", "%Y-%m-%d"))))
    take("coach.context", lambda: coach.context({"app": "notes", "title": "x", "minutes": 3, "focus": "", "today": []}))
    take("deep.links", deep.links)
    for question in ("what about the marzipan order and the zircon samples", "kumquat harvest and the quokka rota", "the teacup club and the orchard app"):
        take("recall.wide " + question, lambda: recall.wide(question, ex={}))
        take("recall.titles " + question, lambda: recall.titles(question, ex={}))
        take("recall.leads " + question, lambda: recall.leads(question))
    take("wiki.index", wiki.index)
    for w in ("ada lovelace", "pemberton", "garden", "ottoline", "2021", "marzipan zircon kumquat quokka"):
        take("wiki.find " + w, lambda: wiki.find(w, most=8))
        take("wiki.excerpt " + w, lambda: wiki.excerpt(w))
    for pid in WIKI:
        take("wiki.page " + pid, lambda: wiki.page(pid))
    for ref in ("c:" + "chat_whatsapp_Pemberton_Quill", "c:chat_telegram_Ottoline_Brack", "r:M3", "r:T1", "r:F1"):
        take("wiki.source " + ref, lambda: wiki.source(ref))
    take("wiki.short", lambda: wiki.short(run=wiki.Run(max_calls=10)))
    take("agent.answer_for", lambda: agent.answer_for("what about the marzipan order and the zircon samples", keep=False))
    # what the quick answer is built from, read directly: the first look (the lean prompt's rows), the evidence around
    # it, and a search by meaning with its pool of whole stretches. The index was made before the rules: a stretch of
    # ada's conversation that runs from the stretch of days into the next year is dated by its last message
    for question in ASKS + ("the marzipan order, part 9 and 10", "the teacup club meets on thursday round 0"):
        take("agent.first_look " + question, lambda: agent.first_look(question))
        take("agent.evidence " + question, lambda: agent.evidence(question))
        take("semantic.find " + question, lambda: {k: v for k, v in semantic.find(question, 20, pool=20).items() if k != "q"})
        take("tools.search meaning " + question, lambda: tools.run("search", {"query": question, "mode": "meaning"})[0])
    for q in ALL_TOTALS:                    # how many matched, as each search says it: of the rows a reader may see
        probes = answer.clean_probes(q.split(";"))
        take("total answer.search " + q, lambda: answer.search(probes, limit=5)[1])
        take("total semantic.keyword " + q, lambda: semantic.keyword(probes, limit=5)[1])
        take("total search tool " + q, lambda: tools.run("search", {"query": q, "mode": "words"})[0].split("\n")[0])
        for how in ("meaning", "both"):
            take("total search tool %s %s" % (how, q), lambda: tools.run("search", {"query": q, "mode": how})[0].split("\n")[0])
    if mode in MODES:
        report["threaded"] = threaded(take, mode)
    if mode not in BROKEN:
        # the wiki's evidence, as a build would gather it: the events and the knowledge layer it reads, a project's
        # evidence (agent sessions among it), and what the second reading that checks a page is handed of its sources
        base = wiki.Base()
        take("wiki.events", lambda: [line for _, line in base.events()])
        take("wiki.deep", lambda: base.deep("facts"))
        catalog = [{"id": "projects/" + n, "title": n + " tracker", "names": {n, n + " tracker"}, "kind": "project", "line": "a made-up project"} for n in ("halyard", "orchard", "marzipan", "zircon")]
        take("wiki.project_specs", lambda: [[t for _, t in s["items"]] for s in wiki._project_specs(base, catalog, ({}, []), [])])
        before = len(sent)
        try:
            wiki._audit(wiki.Run(max_calls=5), {"title": "a page", "kind": "people"},
                        "she runs the club. [[r:A1]] [[c:chat_telegram_Ottoline_Brack]] [[c:chat_whatsapp_Pemberton_Quill]] [[r:M3]] [[r:T1]] [[r:P1]] [[r:H1]]\n")
        except Exception as e:
            report["errors"].append("audit: %s: %s" % (type(e).__name__, e))
        out["wiki.audit sent"] = "\n".join(sent[before:])
        del sent[before:]               # held in the line above; the refs it was given name what is hidden, as a page written earlier would
    take("wiki.build", lambda: wiki.build(max_calls=40, workers=1))
    report.update(out=out, sent=sent, model=model, asks=list(ASKS))
    print("\n@@" + json.dumps(report, ensure_ascii=False))


def threaded(take, mode):
    """Readers in this thread while other threads read the archive with no rule applied (rules._raw, as counting what a
    new rule would touch does): one, then two whose blocks overlap. Each reader's output goes into the report; returns
    whether the rules held for this thread at each point. A slow read of the conversation list inside the raw blocks
    holds them open."""
    import threading, time
    from ctx import answer, mcp, peek, rules, tools
    real, slow = answer._thread_index, {}

    def index():
        time.sleep(slow.get(threading.current_thread().name, 0))
        return real()
    answer._thread_index = index
    held = {}

    def read(label):
        held[label] = rules.active().binds
        take("threaded %s peek" % label, lambda: peek.find("T1") + peek.find("M3"))
        take("threaded %s search" % label, lambda: tools.run("search", {"query": Q1})[0])
        take("threaded %s mcp" % label, lambda: mcp.call("search", {"query": "zircon samples; marzipan order"}))
        take("threaded %s index" % label, lambda: sorted(answer.thread_index()["threads"]))
    count = lambda: rules._count({"sources": ["whatsapp"], "words": ["teacup"]})
    try:
        rules._mem.clear()
        slow["raw-a"] = 0.8
        a = threading.Thread(target=count, name="raw-a")
        a.start()
        time.sleep(0.3)
        read("while one thread reads raw")
        a.join()
        read("after it")
        rules._mem.clear()
        slow.update({"raw-b": 0.6, "raw-c": 1.0})
        b, c = threading.Thread(target=count, name="raw-b"), threading.Thread(target=count, name="raw-c")
        b.start()
        time.sleep(0.2)
        c.start()
        b.join()
        c.join()
        read("after two overlapping")
    finally:
        answer._thread_index = real
    return held


# ---------------------------------------------------------------- the tests

class Gate(unittest.TestCase):
    got = {}

    @classmethod
    def run_child(cls, mode):
        if mode in cls.got:
            return cls.got[mode]
        tmp = tempfile.mkdtemp(prefix="ctx-gate-run-")
        try:
            home, user = os.path.join(tmp, "ctx-gate-" + mode), os.path.join(tmp, "user-home")
            for d in (home, user, os.path.join(tmp, "no-cli")):
                os.makedirs(d)
            env = {k: v for k, v in os.environ.items() if not k.startswith(("CTX_", "ANTHROPIC_", "OPENAI_", "PYTHON"))}
            env.update(CTX_HOME=home, HOME=user, CTX_AGENT="0", CTX_CLI_PATH=os.path.join(tmp, "no-cli"), ANTHROPIC_API_KEY="", PYTHONDONTWRITEBYTECODE="1")
            run = subprocess.run([sys.executable, "-m", "tests.test_gate", "--child", mode], cwd=REPO, env=env, capture_output=True, text=True, timeout=900)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        line = [l for l in run.stdout.split("\n") if l.startswith("@@")]
        if run.returncode or not line:
            raise AssertionError("the child for %s failed:\n%s\n%s" % (mode, run.stdout[-3000:], run.stderr[-6000:]))
        cls.got[mode] = json.loads(line[-1][2:])
        return cls.got[mode]

    @staticmethod
    def handed(report, m):
        """What the answering model was handed, but for the questions asked: those are the caller's own words."""
        text = m["system"] + "\n" + m["prompt"]
        for q in report.get("asks") or []:
            text = text.replace(q, "")
        return text

    def where(self, report, words):
        """{word: [the readers whose output holds it]}, for every word found anywhere: what the child returned, what it
        would have sent to a model, and what the answering model was handed."""
        found = {}
        texts = list(report["out"].items()) + [("sent to a model #%d" % n, t) for n, t in enumerate(report["sent"])]
        texts += [("handed to the answering model #%d" % n, self.handed(report, m)) for n, m in enumerate(report.get("model") or [])]
        for name, text in texts:
            low = text.lower()
            for q in re.findall(r'"query": "([^"]+)"', name):         # a count says the words it was asked for back: the caller's own
                low = low.replace(" or ".join(p.strip() for p in q.lower().split(";")), "")
            for w in words:
                if w in low:
                    found.setdefault(w, []).append(name)
        return found

    def test_without_the_list_and_the_rules_every_reader_reaches_the_made_up_archive(self):
        got = self.run_child("open")
        self.assertEqual(got["errors"], [])
        crashed = {k: v for k, v in got["out"].items() if v.startswith("EXC:")}
        self.assertEqual(crashed, {})
        found = self.where(got, HIDDEN + SHOWN)
        self.assertEqual(sorted(set(HIDDEN + SHOWN) - set(found)), [])         # the test would see a leak: every hidden word is there to be found
        handed = "\n".join(self.handed(got, m) for m in got["model"]).lower()
        self.assertEqual([w for w in ("marzipan", "zircon", "halyard") if w not in handed], [])      # and the answering model is handed them
        for word in ("marzipan", "zircon"):     # through the stretch that runs on past the days, and the statement that rests on a row
            self.assertIn(word, got["out"]["agent.first_look " + ASKS[0]].lower())
        self.assertIn("[X3]", got["out"]["agent.first_look " + ASKS[1]])      # found only by the statement that rests on X3 and on M4

    def test_no_reader_hands_out_what_the_never_list_or_a_rule_leaves_out(self):
        for mode, (_, _, hidden) in MODES.items():
            with self.subTest(mode=mode):
                got = self.run_child(mode)
                self.assertEqual(got["errors"], [])
                crashed = {k: v[:300] for k, v in got["out"].items() if v.startswith("EXC:")}
                self.assertEqual(crashed, {})
                leaks = self.where(got, hidden)
                self.assertEqual(leaks, {}, json.dumps({w: names[:8] for w, names in leaks.items()}, indent=1))
                for path, text in got["static"].items():       # the index and the tool list describe the api, not the archive
                    self.assertEqual([w for w in hidden if w != "telegram" and w in text.lower()], [], path)
                self.assertEqual([w for w in SHOWN if not self.where(got, (w,))], [])          # and what is left is still there

    def test_an_answer_rests_only_on_what_a_reader_may_see(self):
        """/v1/ask with a stand-in model that cites every id it is shown and every hidden one besides: the cites, the links
        and what the model was handed hold nothing hidden, and the model was handed something to answer from."""
        ask = lambda got, a, path="/v1/ask": json.loads(got["out"]["api POST %s %s" % (path, json.dumps({"question": a}))])
        open_ = self.run_child("open")
        self.assertIn("marzipan", json.dumps(ask(open_, ASKS[0])["body"]["cites"]).lower())            # the stand-in cites what it is shown
        for mode, (_, _, hidden) in MODES.items():
            with self.subTest(mode=mode):
                got = self.run_child(mode)
                self.assertTrue(got["model"])
                replies = [ask(got, a) for a in ASKS] + [ask(got, ASKS[0], p) for p in ("//v1/ask", "/v1//ask", "/v1/%61sk")]
                for r in replies:
                    self.assertEqual(r["status"], 200)
                    self.assertEqual([w for w in hidden if w in json.dumps(r["body"]).lower()], [])
                    if "marzipan" in hidden:            # a link only a hidden row holds (B2, saved in the stretch of days)
                        self.assertEqual([l["url"] for l in r["body"]["links"] if "b/2" in l["url"]], [])
                self.assertTrue(ask(got, ASKS[1])["body"]["cites"])                                         # it answered, from what is left
                if "halyard" in hidden:         # a statement of the knowledge layer that rests on a row seen and one hidden is not a way in
                    self.assertNotIn("[X3]", got["out"]["agent.first_look " + ASKS[1]])
                    self.assertEqual([m for m in got["model"] if "[X3]" in m["prompt"]], [])
                ids = ["[%s]" % i for w in hidden for i in HIDDEN_IDS.get(w, [])]
                for m in got["model"]:
                    self.assertEqual([w for w in hidden if w in self.handed(got, m).lower()], [])
                    self.assertEqual([i for i in ids if i in m["prompt"]], [])

    def test_readers_hold_the_rules_while_another_thread_reads_the_archive_raw(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                held = self.run_child(mode)["threaded"]
                self.assertEqual(held, {k: True for k in ("while one thread reads raw", "after it", "after two overlapping")})

    def test_the_wiki_gathers_only_what_a_reader_may_see(self):
        open_ = self.run_child("open")
        self.assertIn("halyard", open_["out"]["wiki.project_specs"])                     # an agent session is evidence for its project
        self.assertIn("marzipan stall", open_["out"]["wiki.project_specs"])              # and so is an event
        self.assertIn("zircon", open_["out"]["wiki.audit sent"])                         # the second reading is handed its sources
        for mode in MODES:
            with self.subTest(mode=mode):
                out = self.run_child(mode)["out"]
                self.assertIn("orchard timer", out["wiki.project_specs"])               # what is left is still evidence
                self.assertIn("she runs the club", out["wiki.audit sent"])
        for mode, (name, _) in BROKEN.items():
            self.assertIn(name, json.loads(self.run_child(mode)["out"]["wiki.build"])["error"], mode)

    def test_what_is_left_is_still_there(self):
        got = self.run_child("closed")
        out = got["out"]
        for name in ("mcp.search %s" % json.dumps({"query": Q2}), "tools.read_thread %s" % json.dumps({"thread": "Ada Lovelace"}), "facts.facts", "understand.core",
                     "mcp.profile %s" % json.dumps({"section": "people"}), "api GET /v1/search?q=%s null" % __import__("urllib.parse").parse.quote(Q2)):
            self.assertTrue(any(w in out[name].lower() for w in SHOWN), (name, out[name][:500]))
        self.assertIn("garden club meets at dawn", out["tools.read_thread %s" % json.dumps({"thread": "Garden Club"})])      # the group is there, without the listed person's lines
        thread = json.loads(out["peek.thread A0 5 5"])          # the first row after the stretch of days the list holds: none of it is a neighbour
        self.assertEqual(([r["id"] for r in thread["rows"]][:1], len(thread["rows"]), thread["rows_total"], thread["from"]), (["A0"], 6, 32, "2022-01-01"))
        self.assertEqual(len(json.loads(out["peek.thread GP1"]).get("rows") or []), 0)        # a listed person's line in a group is not there to read around
        self.assertTrue(json.loads(out["wiki.page people/ada-lovelace"])["text"].strip())

    def test_facts_and_counts_are_of_what_is_left(self):
        got = self.run_child("closed")
        f = json.loads(got["out"]["facts.facts"])
        self.assertNotIn("telegram", f["by_source"])
        self.assertEqual(f["by_source"].get("whatsapp"), 32 + 10)                   # ada's 32 outside the stretch, the group's 10 without the listed person
        self.assertGreaterEqual(f["since"], "2022-")
        self.assertEqual((f["prompts"], f["sessions"]), (1, 1))
        idx = json.loads(got["out"]["answer.thread_index"])["threads"]
        self.assertEqual(sorted(idx), ["imessage:Ivo Smart", "whatsapp:Ada Lovelace", "whatsapp:Garden Club"])
        self.assertEqual((idx["whatsapp:Ada Lovelace"]["n"], idx["whatsapp:Ada Lovelace"]["from"]), (32, "2022-01-01"))      # counted again from what is left
        self.assertEqual(idx["whatsapp:Garden Club"]["n"], 10)
        units = {k: m["n"] for k, m, rows in json.loads(got["out"]["understand.units"])}
        self.assertEqual(units.get("chat:whatsapp:Ada Lovelace"), 32)

    def test_the_stamp_kept_answers_are_filed_under_changes_with_the_never_list(self):
        stamps = self.run_child("closed")["stamps"]
        self.assertEqual(len(set(stamps)), 3)

    def test_a_never_list_rules_or_forgotten_ids_that_cannot_be_read_close_every_reader_and_say_why(self):
        for mode, (name, _) in sorted(BROKEN.items()):
            got = self.run_child(mode)
            self.assertIn(name, got["broken"], mode)
            self.assertIn("nothing from the archive is handed out", got["broken"], mode)
            self.assertEqual(self.where(got, HIDDEN + SHOWN + ("ada lovelace", "ivo smart")), {}, mode)       # not one row, name or count of the archive
            out = got["out"]
            for key, text in out.items():
                if key.startswith(("mcp.", "mcp-strict.", "tools.", "total search tool")):
                    self.assertTrue(text.startswith("BAD: ") and name in text, (mode, key, text[:200]))
                if key.startswith("api "):
                    self.assertEqual(json.loads(text)["status"], 503, (mode, key))
                    self.assertIn(name, json.loads(text)["body"]["error"])
                if key.startswith(("total answer", "total semantic")):
                    self.assertEqual(text, "0", (mode, key))
            self.assertIn(name, json.loads(out["facts.facts"])["error"])
            self.assertIn(name, json.loads(out["agent.answer_for"])["error"])
            self.assertIn(name, out["handle about_me"])
            self.assertEqual(json.loads(out["understand.units"]), [], mode)
            self.assertEqual(json.loads(out["answer.thread_index"])["threads"], {}, mode)
        self.assertIn("range 1", self.run_child("broken")["broken"])

    def test_how_many_matched_counts_only_what_a_reader_may_see(self):
        tot = lambda got, how, q: got["out"]["total %s %s" % (how, q)]
        shut, open_ = self.run_child("closed"), self.run_child("open")
        teacup, both, hidden = TOTALS
        for how in ("answer.search", "semantic.keyword"):
            self.assertGreater(int(tot(open_, how, both)), int(tot(open_, how, teacup)), how)            # the hidden rows are there to be counted
            self.assertEqual(int(tot(shut, how, both)), int(tot(shut, how, teacup)), how)               # and once they are hidden, no count holds them
            self.assertEqual(int(tot(shut, how, hidden)), 0, how)
            self.assertGreater(int(tot(shut, how, teacup)), 0, how)
        self.assertEqual(int(tot(shut, "answer.search", teacup)), int(tot(open_, "answer.search", teacup)))
        self.assertEqual(tot(shut, "search tool", both).split(" matched")[0], tot(shut, "search tool", teacup).split(" matched")[0])
        self.assertNotEqual(tot(open_, "search tool", both).split(" matched")[0], tot(open_, "search tool", teacup).split(" matched")[0])
        self.assertTrue(tot(shut, "search tool", hidden).startswith("no match"), tot(shut, "search tool", hidden))

    def test_in_every_mode_a_search_for_only_what_is_hidden_finds_what_a_search_for_nothing_finds(self):
        tot = lambda got, how, q: got["out"]["total %s %s" % (how, q)]
        open_ = self.run_child("open")
        for mode in MODES:
            with self.subTest(mode=mode):
                shut = self.run_child(mode)
                teacup, both, hidden = totals(mode)
                for how in ("answer.search", "semantic.keyword"):
                    self.assertGreater(int(tot(open_, how, both)), int(tot(open_, how, teacup)), how)
                    self.assertEqual(int(tot(shut, how, both)), int(tot(shut, how, teacup)), how)
                    self.assertEqual(int(tot(shut, how, hidden)), 0, how)
                self.assertEqual(tot(shut, "search tool", both).split(" matched")[0], tot(shut, "search tool", teacup).split(" matched")[0])
                for how in ("search tool", "search tool meaning", "search tool both"):        # by words, by meaning, and the two together
                    self.assertFalse(tot(open_, how, hidden).startswith("no match"), (how, tot(open_, how, hidden)))
                    self.assertTrue(tot(shut, how, hidden).startswith("no match"), (how, tot(shut, how, hidden)))


class NeverFile(unittest.TestCase):
    """What never.json, rules.json and forgotten.json may hold, read in this process against files in a folder of its own."""

    def setUp(self):
        from tests import fixture   # noqa: F401  (the suite's made-up archive: imported before anything from ctx)
        from unittest import mock
        from ctx import api, rules
        self.api, self.rules = api, rules
        self.tmp = tempfile.mkdtemp(prefix="ctx-never-file-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for mod, name in ((api, "NEVER"), (api, "CONF"), (rules, "FILE"), (rules, "GONE")):
            p = mock.patch.object(mod, name, os.path.join(self.tmp, name.lower() + ".json"))
            p.start()
            self.addCleanup(p.stop)
        rules._mem.clear()
        self.addCleanup(rules._mem.clear)

    def put(self, raw):
        with open(self.api.NEVER, "w", encoding="utf-8") as f:
            f.write(raw if isinstance(raw, str) else json.dumps(raw))
        self.rules._mem.clear()

    def test_every_way_of_being_wrong_closes_the_readers(self):
        for raw in ("", "{", "[]", "null", {"sources": "telegram", "ranges": [["2021-03-01", "2021-02-01"]]}, {"ranges": [["2021-03", ""]]},
                    {"ranges": [["2021-02-30", ""]]}, {"ranges": [["", ""]]}, {"ranges": [["2021-03-01"]]}, {"ranges": "2021"}, {"people": [7]}, {"people": ["x"]},
                    {"source": ["telegram"]}, {"sources": ["telegram"], "ranges": [[None, "2021-03-01"]]}):
            self.put(raw)
            self.assertTrue(self.api.never().get("error"), raw)
            self.assertIn("never.json", self.rules.broken(), raw)
            self.assertTrue(self.rules.hidden({"id": "x", "src": "whatsapp", "ts": "2025-01-01", "text": "hello"}), raw)
            self.assertEqual(self.rules.keep([{"id": "x"}]), [], raw)
            self.assertEqual(self.rules.scrub("a page"), "", raw)
            self.assertTrue(self.api.never_hides({"src": "whatsapp", "ts": "2025-01-01"}), raw)
            with self.assertRaises(ValueError):
                self.api.never_targets()

    def test_a_good_list_and_no_list_close_nothing(self):
        for raw in (None, {}, {"sources": ["telegram"], "people": ["pemberton quill"], "ranges": [["2021-03-01", "2021-03-31"], ["", "2001-01-01"], ["2019-01-01", "2019-02-31"]]}):
            if raw is None:
                if os.path.exists(self.api.NEVER):
                    os.remove(self.api.NEVER)
                self.rules._mem.clear()
            else:
                self.put(raw)
            self.assertEqual((self.api.never().get("error"), self.rules.broken()), (None, ""), raw)
        self.assertEqual(self.api.never()["ranges"][-1], ["2019-01-01", "2019-02-28"])        # what an older version wrote for "to february" ends on its last day
        self.assertEqual(self.api.set_never(ranges=[["2019-01", "2019-02"]])["ranges"], [["2019-01-01", "2019-02-28"]])
        self.assertEqual(self.rules.broken(), "")

    def test_a_list_that_cannot_be_read_is_replaced_only_whole(self):
        self.put("{")
        with self.assertRaises(self.api.Bad):
            self.api.set_never(sources=["telegram"])
        self.assertEqual(self.api.set_never(sources=[], people=[], ranges=[]), {"sources": [], "people": [], "ranges": []})
        self.assertEqual(self.rules.broken(), "")

    def test_rules_or_forgotten_ids_that_cannot_be_read_close_the_readers_and_refuse_a_change(self):
        rule = {"kind": "leave_out", "said": "made up", "target": {"sources": ["whatsapp"]}}
        for path, name, raw in ((self.rules.FILE, "rules.json", "{"), (self.rules.FILE, "rules.json", {"rules": "all"}), (self.rules.FILE, "rules.json", {"rules": [{"kind": "leave_out"}]}),
                                (self.rules.FILE, "rules.json", {"rules": [{"id": "r1", "kind": "leave_out"}]}), (self.rules.FILE, "rules.json", []),
                                (self.rules.FILE, "rules.json", "null"), (self.rules.FILE, "rules.json", "7"), (self.rules.FILE, "rules.json", '"rules"'),
                                (self.rules.FILE, "rules.json", {"rules": None}), (self.rules.GONE, "forgotten.json", "null"), (self.rules.GONE, "forgotten.json", "[]"),
                                (self.rules.GONE, "forgotten.json", {"ids": None}), (self.rules.GONE, "forgotten.json", {"ids": [], "by": None}),
                                (self.rules.GONE, "forgotten.json", "[1,"), (self.rules.GONE, "forgotten.json", {"ids": [1]}), (self.rules.GONE, "forgotten.json", {"ids": "F1"})):
            with open(path, "w", encoding="utf-8") as f:
                f.write(raw if isinstance(raw, str) else json.dumps(raw))
            self.rules._mem.clear()
            self.assertIn(name, self.rules.broken(), raw)
            self.assertTrue(self.rules.hidden({"id": "x", "src": "whatsapp", "ts": "2025-01-01", "text": "hello"}), raw)
            self.assertEqual((self.rules.keep([{"id": "x"}]), self.rules.scrub("a page")), ([], ""), raw)
            for change in (lambda: self.rules.save(rule), lambda: self.rules.turn("r1", False), lambda: self.rules.remove("r1")):
                self.assertIn(name, change().get("error", ""), raw)          # a change would write over what the file still holds
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), raw if isinstance(raw, str) else json.dumps(raw))
            os.remove(path)
            self.rules._mem.clear()
            self.assertEqual(self.rules.broken(), "")
        self.assertNotIn("error", self.rules.save(rule))                    # with the files mended, or gone, rules are made again

    def test_a_page_loses_the_lines_that_name_what_the_list_holds(self):
        self.api.set_never(sources=["telegram"], people=["pemberton quill"], ranges=[["2021-03-01", "2021-03-31"]])
        page = ("they collect teacups.\nin march 2021 they ordered marzipan.\non 2021-03-14 they signed.\nthe 5th of march, 2021 was cold.\nq1 2021 was busy.\n"
                "in 2021 they started.\npemberton quill grows kumquats.\nmost evenings they write on telegram.\nby 2021-04-02 it was done.\n")
        self.assertEqual(self.rules.scrub(page), "they collect teacups.\nq1 2021 was busy.\nin 2021 they started.\nby 2021-04-02 it was done.\n")
        self.assertTrue(self.rules.listed("pemberton quill"))
        self.assertTrue(self.rules.listed("march 2021"))
        self.assertFalse(self.rules.listed("2021"))


if __name__ == "__main__" and sys.argv[1:2] == ["--child"]:
    child(sys.argv[2])
