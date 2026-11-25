"""The tools a model drives to answer from the archive. One set of functions serves the app's own answering agent
(agent.py starts the owner's CLI with these and nothing else) and any outside AI app (mcp.py lists them).

Each tool is read-only, bounded in size, and returns rows as lines a model can cite:
  [id] source date conversation | who: text
The description of each tool is the prompt the model picks by: say what it is for, when to use it, and what comes back.

For the app's agent, four things arrive in the environment (agent.py sets them; none is needed otherwise):
  CTX_AGENT_SCOPE   {"sources": [...], "after": "...", "before": "...", "people": [...]}  what the owner limited the chat to
  CTX_AGENT_CALLS   how many tool calls this answer may make; after that every call says to answer now
  CTX_AGENT_UNTIL   a clock time (seconds) after which the same
  CTX_AGENT_LOG     a file to append one JSON line per call to: the rows shown, so the answer's marks can be checked
  CTX_AGENT_CACHE   a folder to keep results in by call, so a repeated run (an evaluation) reads nothing twice
"""
import collections, hashlib, json, math, os, re, time
from . import paths

MOST = 9000         # characters one call returns
DOC = 24000         # characters of one row the doc tool returns in a call: a note is read whole, not by its opening lines
S = {"type": "string"}
DATES = "`after` and `before` take YYYY, YYYY-MM or YYYY-MM-DD and include that whole year, month or day."
SPECS = {
    "search": (
        "Find rows anywhere in the owner's archive: chat messages (whatsapp, telegram, imessage, slack, instagram, linkedin), mail, "
        "notes, docs, saved posts, browsing, calendar, and what the owner typed to AI agents. THE MAIN TOOL: call it several times, "
        "in one turn, with different wordings.\n"
        "`query`: for mode words, one or more probes separated by ';'; each probe is 1 to 3 words that must ALL sit in the same "
        "short stretch of one conversation or the same doc (a word of 4+ letters also matches longer words that start with it). "
        "Use the words the people would have typed, not the question's: names, products, places, numbers; add synonyms, and "
        "words of any language or script the owner writes in, romanised words in their common spellings ('kettle; ketle; teapot'). For mode meaning, a plain "
        "sentence describing what the row would say. Mode both (default) runs both and merges: probes then act as hints too.\n"
        "`people`: names of people or group chats: search only inside their conversations (every app that person is on). "
        "`sources`: only these (e.g. ['whatsapp','apple_notes']); see the sources tool for names; ['knowledge'] searches the statements and question keys an earlier close read wrote and returns the rows they rest on: good when the question is in other words than the chat. `mine`: true for only what the "
        "owner wrote. " + DATES + " `order`: best (default), newest or oldest: use newest for 'last time', oldest for 'first time'. "
        "`limit` default 20, at most 40.\n"
        "Returns matching rows cut short around the match, plus the conversations whose read-through summary matches. A row is a "
        "lead, not the whole story: use read_thread around a promising id to see what was said before and after.",
        {"query": S, "mode": {"type": "string", "enum": ["both", "words", "meaning"]}, "people": {"type": "array", "items": S},
         "sources": {"type": "array", "items": S}, "mine": {"type": "boolean"}, "after": S, "before": S,
         "order": {"type": "string", "enum": ["best", "newest", "oldest"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 40}}, ["query"]),
    "read_thread": (
        "Read a conversation in order, verbatim, with times and who said each line. Use it after search to see the messages "
        "around a hit (`around`: a row id; gives `limit`/2 messages each side), to see how things stand with someone "
        "(`thread`: a person or group name, or a thread id; with nothing else it gives the LATEST messages), to read a period "
        "(`after`/`before`), or to pull the parts of a long conversation that mention something (`query`: words, any of them). "
        "`limit` default 40 messages, at most 150. A name on several apps lists every conversation and reads the largest: pass a "
        "listed thread id to read another. " + DATES,
        {"thread": S, "around": S, "after": S, "before": S, "query": S, "limit": {"type": "integer", "minimum": 1, "maximum": 150}}, []),
    "person": (
        "Who someone is to the owner: the line about them from the read-through of the whole archive, every conversation with "
        "them across apps (with message counts, first and last date, thread ids), what each conversation is about, and the last "
        "few messages exchanged. Call this first for any question about a person, a relationship, or 'when did i last talk to'. "
        "Give a name or part of one; a nickname works if the read-through knows it.", {"name": S}, ["name"]),
    "card": (
        "The read-through's summary of one whole conversation or project: who they are, what it is about, decisions with dates, "
        "open items, how it changed over time, facts. Fast way to get the arc of a long chat before reading parts of it. "
        "A summary is a pointer, not evidence: confirm what matters with search or read_thread and cite those rows.",
        {"thread": S}, ["thread"]),
    "timeline": (
        "What was going on in a period: the read-through's timeline for those years, then computed from the rows: messages per "
        "month and the conversations and projects that were most active. Use for 'what was i doing in…', 'around when did…', "
        "and to turn a vague time into dates to search in. " + DATES, {"after": S, "before": S}, []),
    "saved": (
        "Search only what the owner SAVED from other people: x bookmarks, instagram saves, instagram likes. Other people's words, "
        "so describe the post ('a thread on pricing saas'), and try the words the post itself would use. `kind`: bookmarks | "
        "instagram | likes (default: all, likes last). Rows carry the post's url. These show what the owner pays attention to, "
        "not what the owner said. " + DATES,
        {"query": S, "kind": {"type": "string", "enum": ["bookmarks", "instagram", "likes"]}, "after": S, "before": S,
         "limit": {"type": "integer", "minimum": 1, "maximum": 40}}, ["query"]),
    "links": (
        "Find a link, file, doc, video or post: rows that carry a url and match the words, plus urls sent within a few messages "
        "of a matching message (a link is often sent bare, next to the talk about it). `query` as in search mode words. "
        "`mine_only`: only links the owner sent or made. `people`, `sources`, " + DATES + " Urls are returned whole: copy them exactly.",
        {"query": S, "mine_only": {"type": "boolean"}, "people": {"type": "array", "items": S}, "sources": {"type": "array", "items": S},
         "after": S, "before": S, "limit": {"type": "integer", "minimum": 1, "maximum": 40}}, ["query"]),
    "doc": ("One row whole, by id: a note, a doc, a saved post, a mail, a prompt, an agent session, or one long message. Use it "
            "whenever a result was clipped and the rest matters: never judge a note or doc by its opening lines. Returns up to "
            "24,000 characters; when it was cut it says so and where, and `from` (a character offset) reads on from there.",
            {"id": S, "from": {"type": "integer", "minimum": 0}, "part": {"type": "integer", "minimum": 1}}, ["id"]),
    "profile": (
        "Pages written from a full read of the archive. `section`: core (who the owner is, what they are building, how they "
        "decide), people (who matters and how), projects, timeline, voice (how they write). Background for understanding and "
        "for analysis questions; a page is not a row and cannot be cited.",
        {"section": {"type": "string", "enum": ["core", "people", "projects", "timeline", "voice"]}}, ["section"]),
    "voice": (
        "How the owner writes in public, for writing AS them: a style guide written from their own posts, the limits a program "
        "measured over them (length, case, punctuation, emoji), counted habits, and a dozen of their own posts word for word. "
        "`channel`: x_posts, x_replies, linkedin_posts, linkedin_comments, blog, or overall (default). Read it before drafting "
        "anything the owner will post, keep inside the limits, and never copy an exemplar. `part`: 'guide' leaves the exemplars out.",
        {"channel": {"type": "string", "enum": ["overall", "x_posts", "x_replies", "linkedin_posts", "linkedin_comments", "blog"]}, "part": {"type": "string"}}, []),
    "wiki": (
        "The long write-up of the owner's life, written from a close read of every conversation: a page per person, project or "
        "idea, year and quarter, and theme, far more detailed than profile. `query`: words; lists the pages that match best. "
        "`page`: an id from that list (people/…, projects/…, years/2024, themes/…, front) or a title; returns the page, "
        "`part` 2, 3… for the rest of a long one. Best first stop for 'tell me about', 'what happened with', 'how did X change' "
        "and other analysis questions. A page is a pointer, not a row: the ids in square brackets after its sentences are the "
        "messages they rest on: cite those ids for what the sentence says, and open one with read_thread (`around`) when you need the exact words or what came next. Never cite the page itself.",
        {"query": S, "page": S, "part": {"type": "integer", "minimum": 1}}, []),
    "stats": (
        "Counts computed by code from every row, never estimated. `what`: 'people' (who the owner talks to most: top conversations "
        "by messages, with the owner's share), 'count' (how many rows contain `query`: total, by year, by source, by "
        "conversation, first and last date), 'person' (messages with `person` by year and app, first and last), 'months' "
        "(messages per month), 'overview' (everything at once: totals by source and year, how many people and conversations, the owner's own messages by hour of the day, busiest days, longest silences). All take `sources`, `people` and " + DATES + " Use for 'how many', 'how often', 'most', 'when did "
        "it start/stop'.",
        {"what": {"type": "string", "enum": ["people", "count", "person", "months", "overview"]}, "query": S, "person": S, "mine": {"type": "boolean"},
         "sources": {"type": "array", "items": S}, "people": {"type": "array", "items": S}, "after": S, "before": S}, ["what"]),
    "lapsed": (
        "People over time, computed by code from every message on every app (a person's conversations on different apps are "
        "merged): `what`: 'lapsed' (default: people the owner USED to talk to a lot and no longer does: a busy stretch once, "
        "next to nothing lately), 'quiet' (went quiet only recently), 'new' (first talked to lately), 'lately' (talked to most "
        "lately), 'least' (still in touch, barely). `months`: how long 'lately' is (default 6). Returns the exact count and a "
        "ranked list with each person's busiest period, last contact and app, and the last message as a row to cite. Use for "
        "'who did i use to talk to', 'who went quiet', 'who am i talking to most these days', 'who is new'.",
        {"what": {"type": "string", "enum": ["lapsed", "quiet", "new", "lately", "least"]}, "months": {"type": "integer", "minimum": 1, "maximum": 60},
         "limit": {"type": "integer", "minimum": 1, "maximum": 40}}, []),
    "shared": (
        "What the owner SENT to the most people, computed by code: every web address in the owner's own messages, the same page "
        "counted once however it was pasted. `by`: 'people' (default: how many different conversations it went to) or 'times'. "
        "`query`: words the address must contain (a site name). `kind`: 'link' (default) or 'image' (says honestly what the "
        "archive holds about pictures and files: most sources keep text only). " + DATES + " Returns totals and the top addresses "
        "with counts, dates, and a row to cite for each.",
        {"by": {"type": "string", "enum": ["people", "times"]}, "kind": {"type": "string", "enum": ["link", "image"]}, "query": S, "after": S, "before": S,
         "limit": {"type": "integer", "minimum": 1, "maximum": 40}}, []),
    "intros": (
        "Introductions: who introduced whom to whom, from a table an earlier reading pulled out of the summaries of every "
        "conversation, each checked against the conversation's own messages. `person`: only those involving this person "
        "(as introducer, introduced, or the one they met). `by_me`: only ones the owner made. Returns counts (how many have "
        "messages behind them, how many only offered) and the list with a row to cite for each. Use for 'how many people have "
        "i introduced X to', 'who introduced me to Y', 'who do i connect people to'. " + DATES,
        {"person": S, "by_me": {"type": "boolean"}, "after": S, "before": S, "limit": {"type": "integer", "minimum": 1, "maximum": 40}}, []),
    "conflicts": (
        "Arguments, fallings-out and tension the owner was part of, from the same table: ranked by what they were about and "
        "with whom, then the list (who, topic, how heated 1 to 3, resolved or not, when) with rows to cite. `person`, `topic` "
        "(words), " + DATES + " Use for 'what do i fight about most', 'who have i fallen out with', 'did X and i ever argue'.",
        {"person": S, "topic": S, "after": S, "before": S, "limit": {"type": "integer", "minimum": 1, "maximum": 40}}, []),
    "ideas": (
        "Ideas, projects and plans the owner floated, from the same table, each with what became of it, decided by code from "
        "later mentions in the owner's own messages: built, in progress, came back to it, dropped, never mentioned again. "
        "`status`: one of those, or 'not followed through' (dropped + never mentioned again). `person`, `topic`, " + DATES +
        " Use for 'how many ideas did i not follow through on', 'what did i want to build in 2024', 'ideas i had with X'.",
        {"status": S, "person": S, "topic": S, "after": S, "before": S, "limit": {"type": "integer", "minimum": 1, "maximum": 40}}, []),
    "sources": ("What the archive holds and what it does NOT: every source with its row count and date range, and the sources that "
                "are missing and why. Check it before saying something is not in the archive, to say where it likely lives instead.", {}, []),
}
AGENT = ("search", "read_thread", "person", "card", "timeline", "saved", "links", "doc", "profile", "wiki", "stats", "sources", "lapsed", "shared", "intros", "conflicts", "ideas")   # what the app's own agent may call
KINDS = {"bookmarks": ["x_bookmarks", "linkedin_saved"], "instagram": ["instagram_saved"], "likes": ["instagram_likes", "x_likes", "linkedin_likes"]}
URL = re.compile(r"https?://[^\s<>\"')\]]+")
KEEP = ("id", "src", "ts", "thread", "who", "text", "url", "sender")        # what a shown row carries to the answer's citations


class Bad(Exception):
    """The caller's mistake, said in one plain sentence."""


# ---------------------------------------------------------------- arguments

def _list(v):
    if isinstance(v, str):
        v = [x for x in re.split(r"[,;]", v)]
    return [str(x).strip() for x in v if str(x).strip()][:8] if isinstance(v, (list, tuple)) else []


def _bool(v):
    return v.strip().lower() in ("true", "1", "yes") if isinstance(v, str) else bool(v)


def _int(v, default, most):
    try:
        return max(1, min(int(v), most))
    except (TypeError, ValueError):
        return default


def _day(s, last=False):
    """"YYYY-MM-DD" bound from a year, a month or a day; "" when it is not a date."""
    s = str(s or "").strip()[:10]
    if re.fullmatch(r"\d{4}", s):
        return s + ("-12-31" if last else "-01-01")
    if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", s):
        return s + ("-31" if last else "-01")
    return s if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])-([0-2]\d|3[01])", s) else ""


def _scope():
    try:
        s = json.loads(os.environ.get("CTX_AGENT_SCOPE") or "{}")
    except ValueError:
        s = {}
    return s if isinstance(s, dict) else {}


class Args:
    """One call's arguments read once, with what the owner pinned for the chat applied on top."""

    def __init__(self, a, scope=None):
        sc = _scope() if scope is None else scope
        self.raw = a
        self.query = " ".join(str(a.get("query") or "").split())[:400]
        self.sources = _list(a.get("sources") or a.get("source"))
        only = _list(sc.get("sources"))
        if only:
            self.sources = [s for s in self.sources if s in only] or only
        self.only = set(only)
        self.people = _list(a.get("people")) or _list(sc.get("people"))
        self.after, self.before = _day(a.get("after")), _day(a.get("before"), True)
        lo, hi = _day(sc.get("after")), _day(sc.get("before"), True)
        self.after = max(self.after, lo) if lo else self.after
        self.before = (min(self.before, hi) if self.before else hi) if hi else self.before
        self.mine = _bool(a.get("mine") or a.get("only_mine") or a.get("mine_only"))
        self.fresh = _bool(a.get("recent")) or bool(sc.get("fresh"))        # a question about the present: the last weeks rank first (fresh())

    def ok(self, r):
        """Is this row inside the sources and dates asked for?"""
        day = str(r.get("ts") or "")[:10]
        if self.sources and r.get("src") not in self.sources:
            return False
        if (self.after or self.before) and (not day or (self.after and day < self.after) or (self.before and day > self.before)):
            return False
        return True


def _age(ts, now=None):
    """Days between a row's date and today; None when it has no date."""
    try:
        t = time.mktime(time.strptime(str(ts or "")[:10], "%Y-%m-%d"))
    except (ValueError, OverflowError):
        return None
    return ((now or time.time()) - t) / 86400.0


def fresh(items, when=lambda r: r.get("ts"), now=None):
    """The same items with the recent ones lifted, for a question about the present. An item keeps the weight of its
    place (1 / (8 + place)), times 1.8 when it is from the last 30 days and 1.3 from the last 90: a recent item among
    the first seven goes to the top, an older one keeps its order among the older. Nothing is dropped."""
    def lift(x):
        age = _age(when(x), now)
        return 1.8 if age is not None and -2 <= age <= 30 else 1.3 if age is not None and -2 <= age <= 90 else 1.0
    scored = sorted(((-lift(x) / (8.0 + n), n) for n, x in enumerate(items)))
    return [items[n] for _, n in scored]


def _probes(query):
    from . import answer
    return answer.clean_probes([p for p in re.split(r"[;\n]", query) if p.strip()], most=10)


# ---------------------------------------------------------------- rows

def _row(n, d):
    """A row of the archive (file number, parsed line) in the shape tools show."""
    from . import answer
    src = str(d.get("src") or "")
    if n == 0:
        who = "me" if d.get("who") == "me" else (" ".join(str(d.get("sender") or "").split())[:30] or "them")
        return {"id": str(d.get("id", "")), "src": src, "ts": str(d.get("ts") or "")[:16].replace("T", " "), "thread": str(d.get("thread") or "")[:50],
                "who": who, "text": str(d.get("text") or ""), "url": "", "tid": str(d.get("thread_id") or ""),
                "sender": "" if who == "me" else (" ".join(str(d.get("sender") or "").split())[:60] or (str(d.get("thread") or "")[:60] if d.get("kind") == "dm" else ""))}
    mine = n == 2 or src in answer.OWN
    text = str(d.get("text") or " … ".join(str(d.get(k) or "") for k in ("first_user", "last_user", "last_agent") if d.get(k)))
    return {"id": str(d.get("id", "")), "src": src, "ts": str(d.get("ts") or d.get("last_agent_ts") or "")[:10],
            "thread": str(d.get("title") or d.get("thread") or d.get("project") or "")[:70],
            "who": "me" if mine else "saved" if src in answer.SAVED else "doc", "text": text, "url": str(d.get("url") or ""), "tid": ""}


def _full(r):
    """A search hit read back whole from disk (the sender's name, the time, the uncut text). The hit itself when the row
    cannot be found (a page of the read-through), held to the owner's rules like any row. None when the owner's rules or
    the never list leave the row out, or it was forgotten: a hit is never shown in place of a row that is hidden."""
    from . import peek, rules
    try:
        n, d = peek._find(r["id"])
    except Exception:
        n, d = None, None
    if d is None:
        got = rules.keep([dict(r, ts=str(r.get("ts") or "")[:10])])
        return got[0] if got else None
    if rules.hidden(d) or (r.get("rests") and rules.ids_hidden(r["rests"])):
        return None
    return _row(n, d)


def _clip(text, rxs, size):
    text = " ".join(str(text).split())
    if len(text) <= size:
        return text
    low, at = text.lower(), -1
    for r in rxs:
        m = r.search(low)
        if m and (at < 0 or m.start() < at):
            at = m.start()
    start = max(0, at - size // 3) if at > size * 2 // 3 else 0
    start = min(start, len(text) - size)
    end = start + size
    for m in URL.finditer(text):            # never half a link
        if m.start() < end < m.end():
            end = min(m.end(), end + 500)
        if m.start() < start < m.end():
            start = m.start()
    return ("… " if start else "") + text[start:end].strip() + (" …" if end < len(text) else "")


def _line(r, rxs=(), size=300):
    text = _clip(r["text"], rxs, size)
    cut = " (clipped: call doc with this id for all of it)" if r.get("who") in ("doc", "saved") or not r.get("tid", "x") and len(str(r["text"])) > size + 200 else ""
    cut = cut if len(" ".join(str(r["text"]).split())) > size else ""
    return f'[{r["id"]}] {r["src"]} {r["ts"]} {r["thread"]} | {r["who"]}: {text}' + (f' <{r["url"]}>' if r.get("url") and r["url"] not in text else "") + cut


def _rxs(probes):
    from . import answer
    return [answer._rx(w) for p in probes for w in p]


def shown(rows):
    """The rows a tool may show: those no rule or the never list leaves out (rules.keep), whose line, whole, names
    nothing they leave out either (every tool's text loses such a line on the way out: rules.scrub). Counted from this,
    a total says nothing about what is hidden."""
    from . import rules
    rows = rules.keep(rows)
    if not rules.active().binds or not rows:
        return rows
    return [r for r in rows if rules.scrub(_line(r, (), 1 << 30), blocks=False) == _line(r, (), 1 << 30)]


class Out:
    """What one call returns: lines of text, and the rows shown (kept for the answer's marks)."""

    def __init__(self):
        self.lines, self.rows = [], []

    def say(self, *lines):
        self.lines += [l for l in lines if l is not None]

    def show(self, rows, rxs=(), size=300):
        for r in shown(rows):           # the last gate: whatever a tool gathered, a row the owner's rules leave out is not shown
            self.lines.append(_line(r, rxs, size))
            self.rows.append({k: r.get(k, "") for k in KEEP})

    def text(self):
        return "\n".join(self.lines)


# ---------------------------------------------------------------- threads and people

def _threads(names, most=6, others=False):
    """Thread ids for names: an exact thread id is itself; a name is resolved the way the answering code does."""
    from . import answer
    idx = answer.thread_index()
    out = []
    for n in names:
        if n in idx["threads"]:
            out.append(n)
            continue
        got, p = [], None
        try:                    # one person across apps and spellings (people.py), then group chats and looser matches by name
            from . import people
            p = people.find(n) if idx["threads"] else None       # an empty archive is read, never written to
            got = [t for t in (p or {}).get("_tids", []) if t in idx["threads"]][:most]
        except Exception:
            got = []
        got += [t for t in answer.resolve_threads([n], idx, most=most) if t not in got]
        got = got[:most + 2]
        if others and len(str(n).split()) == 1 and idx["threads"]:      # a first name alone may be several people: the busiest conversations of the others too
            try:
                key = people.key_of(n)[0]
                for q in people.everyone()[:1500]:
                    if len(got) >= most + 8:
                        break
                    if key and key in q["_key"].split() and q is not p and q.get("messages", 0) >= 20:
                        got += [t for t in sorted((t for t in q.get("_tids") or [] if t in idx["threads"]), key=lambda t: -idx["threads"][t]["n"])[:1] if t not in got]
            except Exception:
                pass
        out += [t for t in got if t not in out]
    return out, idx


def _tline(d):
    who = "me" if d.get("who") == "me" else (" ".join(str(d.get("sender") or "").split())[:30] or "them")
    return f'[{d.get("id", "")}] {str(d.get("ts") or "")[:16].replace("T", " ")} {who}: ' + " ".join(str(d.get("text") or "").split())[:500]


def _head(tid, t):
    return f'{t["thread"]} ({t["src"]}, {t["kind"] or "chat"}, {t["n"]} messages, {t["mine"]} by the owner, {t["from"]} to {t["to"]}) thread id: {tid}'


def _in_threads(tids, idx, probes, a, limit, order):
    """Search inside given conversations by reading them: (rows, how many matched)."""
    from . import answer
    rx = [[answer._rx(w) for w in p] for p in probes]
    hits = []
    for tid in tids:
        msgs = answer.thread_rows(tid, idx)
        low = [answer._low(d.get("text")) for d in msgs]
        for i, d in enumerate(msgs):
            r = _row(0, d)
            if not a.ok(r) or (a.mine and d.get("who") != "me"):
                continue
            near = " \n ".join(low[max(0, i - 2):i + 3])        # words may be split over neighbouring messages
            sc = sum(2 if all(x.search(low[i]) for x in p) else 1 if any(x.search(low[i]) for x in p) and all(x.search(near) for x in p) else 0 for p in rx)
            if sc:
                hits.append((sc, r["ts"], r))
    if hits:                    # counted from what a reader may be shown (shown())
        ok = {r["id"] for r in shown([h[2] for h in hits])}
        hits = [h for h in hits if h[2]["id"] in ok]
    if order == "oldest":
        hits.sort(key=lambda h: h[1])
    elif order == "newest":
        hits.sort(key=lambda h: h[1], reverse=True)
    else:
        hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
    return [h[2] for h in hits[:limit]], len(hits)


# ---------------------------------------------------------------- the tools

def _search_rows(a, probes, mode, limit, link=False, who=""):
    """Rows from the whole archive by words, by meaning, or both merged: (rows read back whole, matched, {thread id: card score})."""
    from . import answer
    try:
        from . import semantic
        indexed = semantic.ready()
    except Exception:
        indexed = False
    who = "me_only" if a.mine else who
    lo, hi = a.after[:7], a.before[:7]
    srcs = a.sources or [""]
    lists, total, cards = [], 0, {}
    if mode in ("both", "words") and probes:
        for s in srcs[:8]:
            if indexed:
                rows, n = semantic.keyword(probes, lo, who, limit * 2, hi, s, link=link)
                if not rows:        # the index holds stretches of chat; a row the index has not caught up with is still found by a pass
                    rows, n = answer.search(probes, lo, who, limit * 2, hi, s, link=link, tid=True)
            else:
                rows, n = answer.search(probes, lo, who, limit * 2, hi, s, link=link, tid=True)
            lists.append(rows)
            total += n
    if mode in ("both", "meaning") and indexed and a.query:
        for s in srcs[:8]:
            got = semantic.find(a.query.replace(";", " "), limit * 2, lo, hi, who, s, probes=probes, link=link)
            lists.append(got["rows"])
            total = max(total, len(got["rows"]))
            for t, sc in got["threads"].items():
                cards[t] = max(cards.get(t, 0), sc)
    if len(lists) > 1:
        from . import semantic
        rows = semantic.fuse(lists)
    else:
        rows = lists[0] if lists else []
    out, seen = [], set()
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        f = _full(r)
        if f is None or f["src"] in ("read_through", "card"):      # hidden; or a page of the read-through, which is background, not a row to cite: profile and card serve those
            continue
        if a.ok(f) and not (link and not (URL.search(f["text"]) or f.get("url"))):
            out.append(f)
    if a.fresh and not (a.after or a.before):       # dates asked for outright say which time is meant
        out = fresh(out)
    from . import rules
    out = rules.rank(rules.keep(out))               # the owner's own weights, on top: what they said counts more comes first
    if rules.active().binds:
        # what matched is counted from what a reader may be shown: by words the rows a reader may see were counted
        # (answer.search), by meaning it is the rows found that are left. Nothing shown: nothing matched
        out = shown(out)
        total = (len(out) if mode == "meaning" else max(total, len(out))) if out else 0
    return out, total, cards


def _ordered(rows, order, limit):
    if order in ("newest", "oldest"):
        rows = sorted(rows, key=lambda r: r["ts"] or ("0" if order == "newest" else "9"), reverse=order == "newest")
    return rows[:limit]


def search(a, o):
    probes = _probes(a.query)
    if not probes:
        raise Bad("give a query: for words, probes separated by ';', each 1 to 3 words; for meaning, a sentence.")
    mode = a.raw.get("mode") if a.raw.get("mode") in ("both", "words", "meaning") else "both"
    order = a.raw.get("order") if a.raw.get("order") in ("best", "newest", "oldest") else "best"
    limit = _int(a.raw.get("limit"), 20, 40)
    from . import answer
    rxs = _rxs(probes)
    if a.people:
        tids, idx = _threads(a.people, others=True)       # a search may look in every conversation the name could mean; reading one does not guess
        if not tids:
            # the names are not said back: a name the never list holds would make this line go (rules.scrub), and so
            # answer differently from a name nobody has
            o.say("no conversation matches %s. try person, or search without `people`." % ("that name" if len(a.people) == 1 else "those names"))
            return
        rows, n = _in_threads(tids, idx, probes, a, limit, order)
        o.say(f"{n} messages match inside: " + "; ".join(_head(t, idx["threads"][t]) for t in tids[:6]))
        if not rows:
            o.say("nothing there has those words. try other words or spellings, or read_thread to read it in order.")
        o.show(rows, rxs)
        return
    rows, total, cards = _search_rows(a, probes, mode, limit * 2)
    rows = _ordered(rows, order, limit)
    if not rows:
        o.say("no match. try other words (synonyms, the other language, a name), mode meaning, or fewer words per probe.")
    else:
        o.say(f"{total} matched; showing {len(rows)}" + (f" ({order} first)" if order != "best" else "") + ":")
        o.show(rows, rxs)
    idx = answer.thread_index()
    best = [(s, t) for t, s in sorted(cards.items(), key=lambda x: -x[1]) if t in idx["threads"] and s >= 0.45][:4]
    if best:
        o.say("conversations whose summary matches (see card or read_thread):", *["- " + _head(t, idx["threads"][t]) for s, t in best])


def read_thread(a, o):
    from . import answer, peek
    limit = _int(a.raw.get("limit"), 40, 150)
    around, name = str(a.raw.get("around") or "").strip().strip("[]"), str(a.raw.get("thread") or "").strip()
    idx = answer.thread_index()
    if not around and not name:
        raise Bad("give `around` (a row id) or `thread` (a name or thread id).")
    if not around and name not in idx["threads"]:
        n, d = peek.find(name.strip("[]"))          # a row id given as the thread: read around it
        if d is not None:
            around = name.strip("[]")
    if around:
        n, d = peek.find(around)
        if d is None:
            raise Bad("no row with that id. copy an id from a search result.")
        if n != 0:
            return doc(Args({"id": around}), o)
        tid = str(d.get("thread_id") or "")
        msgs = answer.thread_rows(tid, idx)
        at = next((i for i, m in enumerate(msgs) if str(m.get("id")) == around), 0)
        lo, hi = max(0, at - limit // 2), min(len(msgs), at + limit // 2 + 1)
        t = idx["threads"].get(tid) or {"thread": d.get("thread", ""), "src": d.get("src", ""), "kind": "", "n": len(msgs), "mine": 0, "from": "", "to": ""}
        o.say(_head(tid, t), f"messages {lo + 1} to {hi} of {len(msgs)}, around [{around}]:")
        picked = list(range(lo, hi))
    else:
        tids, idx = _threads([name])
        if not tids:
            o.say(f"no conversation named like '{name}'. try person, or search for a message and read around its id.")
            return
        if len(tids) > 1:
            o.say("conversations with that name:", *["- " + _head(t, idx["threads"][t]) for t in tids])
            tids.sort(key=lambda t: -idx["threads"][t]["n"])
        tid = tids[0]
        msgs = answer.thread_rows(tid, idx)
        keep = [i for i, m in enumerate(msgs) if a.ok({"src": idx["threads"][tid]["src"], "ts": m.get("ts")})]
        words = [w for p in _probes(a.query) for w in p]
        if words:
            rx = [answer._rx(w) for w in words]
            hit = [i for i in keep if any(r.search(answer._low(msgs[i].get("text"))) for r in rx)]
            span = max(1, min(6, limit // max(1, 2 * len(hit))))
            pos, most, best = set(), limit // (2 * span + 1) or 1, False
            if len(hit) > most and len(rx) > 1:         # more places than fit: the ones where most of the words sit together, not just the latest
                low = {i: answer._low(msgs[i].get("text")) for h in hit for i in range(max(0, h - 2), min(len(msgs), h + 3))}
                df = [sum(bool(r.search(low[h])) for h in hit) for r in rx]
                rare = [math.log(1 + len(hit) / (d + 1.0)) for d in df]
                score = {h: sum(w * (1.0 if r.search(low[h]) else 0.6 if any(r.search(low[i]) for i in range(max(0, h - 2), min(len(msgs), h + 3))) else 0.0) for r, w in zip(rx, rare)) for h in hit}
                top = sorted(hit, key=lambda h: (score[h], h), reverse=True)
                chosen = []
                for h in top:
                    if len(chosen) >= most:
                        break
                    if all(abs(h - c) > span for c in chosen):
                        chosen.append(h)
                best = len({round(score[h], 3) for h in hit}) > 1
                use = chosen if best else hit[-most:]
            else:
                use = hit[-most:]
            for i in use:
                pos.update(range(max(0, i - span), min(len(msgs), i + span + 1)))
            picked = sorted(pos)[:limit + 20]
            o.say(_head(tid, idx["threads"][tid]), f'{len(hit)} messages mention {", ".join(words)}' + (f"; the {'best' if best else 'latest'} {len(picked)} lines around them" + (" (where most of the words sit together; add dates to read another period)" if best else "") + ":" if hit else ". try other words, or read by date."))
        else:
            picked = keep[:limit] if a.after and not a.before else keep[-limit:]
            o.say(_head(tid, idx["threads"][tid]), f"{len(picked)} of {len(keep)} messages" + (f" from {a.after}" if a.after else "") + (f" to {a.before}" if a.before else "")
                  + (" (the earliest of them)" if a.after and not a.before and len(keep) > limit else " (the latest)" if len(keep) > limit else "") + ":")
    src = idx["threads"].get(tid, {}).get("src", "")
    if a.only and src not in a.only:
        o.lines[:] = ["that conversation is outside the sources this chat is limited to."]
        return
    prev, room = None, MOST - 600
    for i in picked:
        if prev is not None and i != prev + 1:
            o.say(f"… {i - prev - 1} messages not shown …")
        line = _tline(msgs[i])
        room -= len(line) + 1
        if room < 0:
            o.say("… cut here: ask for fewer messages or a narrower period.")
            break
        o.lines.append(line)
        r = _row(0, msgs[i])
        o.rows.append({k: r[k] for k in KEEP})
        prev = i
    if picked and picked[-1] < len(msgs) - 1:
        o.say(f"… {len(msgs) - 1 - picked[-1]} later messages, to {str(msgs[-1].get('ts') or '')[:10]} …")


_cards = {}


def _card_of(tid):
    """The read-through's card for a conversation: by its key, else by the conversation's name and source."""
    from . import answer, rules, understand
    if rules.card_hidden(understand._key("chat:" + tid)):       # the summary of a conversation the owner's rules leave out
        return None
    try:
        with open(os.path.join(understand.CARDS, understand._key("chat:" + tid) + ".json")) as f:
            return rules.scrub_card(json.load(f))       # what the rules leave out is not in it as read
    except (OSError, ValueError):
        pass
    try:
        stamp = os.stat(understand.CARDS).st_mtime_ns
    except OSError:
        return None
    stamp = (stamp, rules._key())
    if _cards.get("stamp") != stamp:
        _cards.update(stamp=stamp, by={(answer._norm(c.get("_title", "")), str(c.get("_src", ""))): c for c in understand.cards() if isinstance(c, dict)})
    t = answer.thread_index()["threads"].get(tid)
    return _cards["by"].get((answer._norm(t["thread"]), t["src"])) if t else None


def _say(v):
    return "; ".join(json.dumps(x, ensure_ascii=False) if isinstance(x, dict) else str(x) for x in v) if isinstance(v, list) else str(v)


def _card_text(tid, most=2600):
    c = _card_of(tid)
    if not isinstance(c, dict):
        return ""
    return "\n".join(f"{k}: {_say(c[k])}" for k in ("who", "about", "decisions", "open", "arc", "facts", "people", "tone") if c.get(k))[:most]


def _people_lines(name, most=6):
    from . import answer, understand
    q = answer._norm(name)
    return [l.strip()[:600] for l in understand.page("people").split("\n") if q and q in answer._norm(l)][:most]


def person(a, o):
    from . import answer, understand
    name = " ".join(str(a.raw.get("name") or "").split())
    if len(name) < 2:
        raise Bad("give a name, or part of one, of at least two letters.")
    lines = _people_lines(name)
    if lines:
        o.say("from the read-through's people page:", *lines)
    tids, idx = _threads([name], most=8)
    tids = [t for t in tids if not a.only or idx["threads"][t]["src"] in a.only]
    if tids:
        tids.sort(key=lambda t: (idx["threads"][t]["kind"] != "dm", -idx["threads"][t]["n"]))
        o.say(f"conversations ({len(tids)}):")
        for t in tids:
            card = _card_text(t, 500).replace("\n", " | ")
            o.say("- " + _head(t, idx["threads"][t]) + (f"\n  summary: {card}" if card else ""))
        dms = [t for t in tids if idx["threads"][t]["kind"] == "dm"] or tids
        last = max(dms, key=lambda t: idx["threads"][t]["to"])
        msgs = answer.thread_rows(last, idx)[-5:]
        o.say(f'last contact: {idx["threads"][last]["to"]} on {idx["threads"][last]["src"]}. the last messages there:')
        for m in msgs:
            o.lines.append(_tline(m))
            r = _row(0, m)
            o.rows.append({k: r[k] for k in KEEP})
    want, seen = answer._norm(name), []
    for c in understand.cards():                    # where other conversations' summaries mention them
        for p in c.get("people") or []:
            if isinstance(p, dict) and want in answer._norm(p.get("name", "")):
                line = f'- {p.get("name")}: {str(p.get("role", ""))[:200]} (from the summary of: {c.get("_title", "")})'
                if line not in seen:
                    seen.append(line)
    if seen:
        o.say("mentioned in other conversations' summaries:", *seen[:8])
    if not o.lines:
        o.say("nobody by that name in conversation names or the read-through. try search with the name as a word: they may only be mentioned.")


def card(a, o):
    name = str(a.raw.get("thread") or a.raw.get("name") or "").strip()
    if len(name) < 2:
        raise Bad("give a conversation: a person or group name, or a thread id.")
    tids, idx = _threads([name], most=4)
    shown = 0
    for t in tids:
        text = _card_text(t)
        if text and shown < 2:
            o.say("## " + _head(t, idx["threads"][t]), text, "")
            shown += 1
    if not shown:
        from . import answer, understand
        want = answer._norm(name)
        for c in understand.cards():                # a project card, or a chat the index does not hold
            if want in answer._norm(c.get("_title", "")) and shown < 2:
                say = lambda v: "; ".join(json.dumps(x, ensure_ascii=False) if isinstance(x, dict) else str(x) for x in v) if isinstance(v, list) else str(v)
                o.say(f'## {c.get("_title", "")} ({c.get("_src", "")}, {str(c.get("_from", ""))[:10]} to {str(c.get("_to", ""))[:10]})',
                      "\n".join(f"{k}: {say(c[k])}" for k in ("who", "about", "decisions", "open", "arc", "facts", "people") if c.get(k))[:2600], "")
                shown += 1
    if not shown:
        o.say("no summary for that" + (": the read-through skipped it (few messages by the owner). use read_thread." if tids else ". try person or search."))


def _scan(a, tids=None):
    """Every message inside the dates, sources and conversations asked for, as (day, src, thread id, mine). Read from the
    bytes of each line, not parsed, so a pass over a large archive takes about a second."""
    ts_k, tid_k, src_k, who_k = b'"ts": "', b'"thread_id": "', b'"src": "', b'"who": "me"'
    lo, hi = a.after.encode(), a.before.encode()
    srcs = {s.encode() for s in a.sources}
    want = {json.dumps(t, ensure_ascii=False)[1:-1].encode() for t in tids} if tids is not None else None
    from . import rules
    act = rules.active()            # the owner's rules and the never list: a line they leave out is not counted
    try:
        with open(paths.MESSAGES, "rb") as f:
            for line in f:
                i = line.find(ts_k)
                day = line[i + 7:i + 17] if i >= 0 else b""
                if (lo and day < lo) or (hi and (not day or day > hi)):
                    continue
                j = line.find(tid_k)
                tid = line[j + 14:line.find(b'"', j + 14)] if j >= 0 else b""
                if want is not None and tid not in want:
                    continue
                k = line.find(src_k)
                src = line[k + 8:line.find(b'"', k + 8)] if k >= 0 else b""
                if srcs and src not in srcs:
                    continue
                if not act.line_ok(line):
                    continue
                yield day.decode("ascii", "replace"), src.decode(), tid, who_k in line
    except OSError:
        return


def timeline(a, o):
    from . import answer
    if not a.after and not a.before:
        raise Bad("give `after` and/or `before`: a year, a month or a day.")
    text = answer._period(a.after[:7], a.before[:7])
    if text:
        o.say("from the read-through's timeline (background, not a row):", text.split("\n", 2)[-1][:3000], "")
    months, per = collections.Counter(), collections.Counter()
    for day, src, tid, mine in _scan(a):
        months[day[:7]] += 1
        per[tid] += 1
    if not months:
        o.say("no messages in that period.")
        return
    keys = sorted(months)
    if len(keys) > 36:
        years = collections.Counter()
        for k, n in months.items():
            years[k[:4]] += n
        o.say("messages per year: " + ", ".join(f"{k}: {years[k]}" for k in sorted(years)))
    else:
        o.say("messages per month: " + ", ".join(f"{k}: {months[k]}" for k in keys))
    idx = answer.thread_index()
    o.say("most active conversations in that period:")
    for tid, n in per.most_common(12):
        t = idx["threads"].get(tid.decode("utf-8", "replace"))
        if t:
            o.say(f'- {t["thread"]} ({t["src"]}, {t["kind"] or "chat"}): {n} messages; thread id: {tid.decode("utf-8", "replace")}')
    docs = collections.Counter()
    from . import rules
    act = rules.active()
    try:
        with open(paths.DOCS, "rb") as f:
            for line in f:
                i = line.find(b'"ts": "')
                day = line[i + 7:i + 17].decode("ascii", "replace") if i >= 0 else ""
                if day and not (a.after and day < a.after) and not (a.before and day > a.before) and act.line_ok(line):
                    k = line.find(b'"src": "')
                    docs[line[k + 8:line.find(b'"', k + 8)].decode()] += 1
    except OSError:
        pass
    if docs:
        o.say("docs, saves and browsing dated in that period: " + ", ".join(f"{s}: {n}" for s, n in docs.most_common()))


def saved(a, o):
    from . import answer
    kind = a.raw.get("kind")
    a.sources = [s for s in (KINDS.get(kind) or ["x_bookmarks", "instagram_saved", "instagram_likes", "x_likes"]) if not a.only or s in a.only]
    if not a.sources:
        o.say("saved posts are outside the sources this chat is limited to.")
        return
    probes = _probes(a.query)
    limit = _int(a.raw.get("limit"), 20, 40)
    newest = a.raw.get("order") == "newest" or not probes
    per, total = [], 0
    if not probes:                      # no words: the latest of each kind, so "what have i liked lately" needs no guess at a word
        for s, rows in _latest(a.sources, limit, a).items():
            per.append(rows)
            total += len(rows)
    for s in a.sources if probes else []:
        one = Args(dict(a.raw, sources=[s]))
        one.sources = [s]
        rows, n, _ = _search_rows(one, probes, "both", limit)
        # within one source: the newest first when asked, else the best match with the last weeks lifted (a like or a save is a sign of what the owner is into now)
        per.append((sorted(rows, key=lambda r: r["ts"] or "0", reverse=True) if newest else rows if one.fresh and not (one.after or one.before) else fresh(rows))[:limit])
        total += n
    rows = _interleave(per, limit)      # a turn for each source: a source with a hundred times the rows does not push the others off the page
    if not rows:
        o.say("no saved post matches. try other words: these are other people's posts, in their words." if probes else "nothing saved or liked in the sources and dates asked for.")
        return
    o.say(f"{total} matched; showing {len(rows)}, a turn for each source ({', '.join(a.sources)}):" if probes else f"the latest of each source ({', '.join(a.sources)}), newest first within each:")
    o.show(rows, _rxs(probes), 420)


def _interleave(groups, limit):
    """One from each group in turn, in each group's own order, until `limit`."""
    out, seen, n = [], set(), 0
    while len(out) < limit and any(n < len(g) for g in groups):
        for g in groups:
            if n < len(g) and len(out) < limit and g[n]["id"] not in seen:
                seen.add(g[n]["id"])
                out.append(g[n])
        n += 1
    return out


def _latest(sources, limit, a):
    """The newest `limit` docs of each of these sources, within the dates asked for: {source: rows, newest first}. One pass over the docs."""
    import heapq
    from . import rules
    act = rules.active()
    want, heaps = {s.encode() for s in sources}, {s: [] for s in sources}
    try:
        with open(paths.DOCS, "rb") as f:
            for n, line in enumerate(f):
                k = line.find(b'"src": "')
                if k < 0 or line[k + 8:line.find(b'"', k + 8)] not in want:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict) or act.hides(d):
                    continue
                r = _row(1, d)
                if r["src"] in heaps and r["ts"] and a.ok(r):
                    h = heaps[r["src"]]
                    (heapq.heappush if len(h) < limit else heapq.heappushpop)(h, (r["ts"], n, r))
    except OSError:
        pass
    return {s: [r for _, _, r in sorted(h, reverse=True)] for s, h in heaps.items() if h}


def links(a, o):
    from . import answer
    probes = _probes(a.query)
    if not probes:
        raise Bad("give a query: words near the link, or in its title.")
    limit = _int(a.raw.get("limit"), 20, 40)
    rxs = [URL] + _rxs(probes)
    if a.people:
        tids, idx = _threads(a.people)
        hits, _ = _in_threads(tids, idx, probes, a, 60, "best")
    else:
        hits, _, _ = _search_rows(a, probes, "words", 30)
    with_url = [r for r in hits if URL.search(r["text"]) or r.get("url")]
    if not a.people:
        with_url += [r for r in _search_rows(a, probes, "words", limit, link=True)[0] if r["id"] not in {x["id"] for x in with_url}]
    near = []
    for r in answer.near_links([dict(r, tid=r.get("tid", "")) for r in hits if r.get("tid")], most=14):
        f = _full(r)
        if f is not None and a.ok(f) and f["id"] not in {x["id"] for x in with_url}:
            near.append(f)
    if a.mine:
        with_url, near = [r for r in with_url if r["who"] == "me"], [r for r in near if r["who"] == "me"]
    if not with_url and not near:
        o.say("no row with a url matches. try other words, the name of the site or app (docs.google, loom, youtube, figma), or search for the "
              "talk about it and read_thread around that message.")
        return
    if with_url:
        o.say(f"rows that match and carry a url ({len(with_url[:limit])}):")
        o.show(with_url[:limit], rxs, 420)
    if near:
        o.say("urls sent within a few messages of a match:")
        o.show(near[:limit], rxs, 420)


def doc(a, o):
    from . import peek
    rid = str(a.raw.get("id") or "").strip().strip("[]")
    if not rid:
        raise Bad("give the row's id.")
    n, d = peek.find(rid)
    if d is None:
        raise Bad("no row with that id. copy an id from a search result.")
    r = _row(n, d)
    if a.only and r["src"] not in a.only:
        o.say("that row is outside the sources this chat is limited to.")
        return
    text = r["text"]
    start = _int(a.raw.get("from"), 0, max(0, len(text))) if a.raw.get("from") is not None else (_int(a.raw.get("part"), 1, 50) - 1) * DOC
    piece, end = text[start:start + DOC], min(len(text), start + DOC)
    o.say(f'[{r["id"]}] {r["src"]} {r["ts"]} {r["thread"]} | {r["who"]}' + (f' <{r["url"]}>' if r["url"] else "")
          + (f" (characters {start} to {end} of {len(text)})" if start or end < len(text) else " (whole)") + ":", piece or "(nothing there)")
    if end < len(text):
        o.say(f'… cut here at character {end} of {len(text)}: call doc with id {r["id"]} and from {end} for the rest.')
    o.rows.append({k: r.get(k, "") for k in KEEP})
    if n == 0:
        o.say("(one message: read_thread with around set to this id shows the conversation around it)")


def profile(a, o):
    from . import understand
    name = a.raw.get("section") or a.raw.get("name") or "core"
    if name not in ("core", "people", "projects", "timeline", "voice"):
        raise Bad("section must be one of: core, people, projects, timeline, voice")
    if not os.path.exists(os.path.join(understand.MEM, name + ".md")):
        o.say("not written yet: the read-through has not run (python3 -m ctx understand).")
        return
    o.say(understand.page(name).strip()[:MOST - 200] or "that page is empty.")


def voice(a, o):
    from . import voice as v
    o.say(v.tool(str(a.raw.get("channel") or "overall").strip().lower(), str(a.raw.get("part") or "")))


def wiki_plain(text):
    """A wiki page's text as the answering model reads it: a link as its words, card refs gone, a message ref as [id]."""
    text = re.sub(r"\[\[p:[^\]|]*\|([^\]]*)\]\]", r"\1", str(text or ""))
    text = re.sub(r"\s*\[\[c:[^\]]*\]\]", "", text)
    return re.sub(r"\[\[r:([^\]]*)\]\]", r"[\1]", text).strip()


def wiki_rows(text, a=None, most=240):
    """The messages the [id] marks in wiki text point at, as rows, each once, within the scope of `a` when given."""
    from . import wiki as w
    out, seen = [], set()
    for rid in re.findall(r"\[([^\[\]\s]+)\]", text):
        if rid in seen or len(seen) >= most:
            continue
        seen.add(rid)
        r = w.source("r:" + rid)
        try:
            if isinstance(r, dict) and r.get("id") and (a is None or a.ok(r)):
                out.append({k: r.get(k, "") for k in KEEP})
        except Exception:
            pass
    return out


def wiki(a, o):
    from . import wiki as w
    if not w.index():
        o.say("not written yet: the wiki has not been built (python3 -m ctx wiki --build).")
        return
    pid, query = str(a.raw.get("page") or "").strip(), str(a.raw.get("query") or "").strip()
    if not pid:
        if not query:
            raise Bad("give `query` (words) to find pages, or `page` (an id or a title) to read one")
        got = w.find(query, most=8)
        if not got:
            o.say("no page matches those words. try a name, a project or a year, or use search.")
        for g in got:
            o.say(f"{g['id']}: {g['title']} ({g['kind']}). {str(g.get('summary') or '')[:220]}")
        if got:
            o.say("read one with `page` set to its id.")
        return
    e = w.page(pid)
    if not e:
        near = w.find(pid, most=5)
        raise Bad("no page with that id or title." + (" close: " + ", ".join(g["id"] for g in near) if near else " find one with `query`."))
    text = wiki_plain(e.get("text") or "")
    size = MOST - 400
    parts = max(1, -(-len(text) // size))
    n = min(_int(a.raw.get("part"), 1, parts), parts)
    cut = text[(n - 1) * size:n * size]
    o.say(f"{e['title']} ({e['id']}), part {n} of {parts}", cut)
    o.rows += wiki_rows(cut, a)         # the messages its sentences rest on count as shown: each was checked against its sentence when the page was written
    if n < parts:
        o.say(f"… more: `part` {n + 1}.")


def _mon(ym):
    return "jan feb mar apr may jun jul aug sep oct nov dec".split()[int(ym[5:7]) - 1] + " " + ym[:4] if re.match(r"\d{4}-(0[1-9]|1[0-2])", str(ym)) else str(ym)


def lapsed(a, o):
    from . import aggregate, answer
    what = a.raw.get("what") if a.raw.get("what") in ("lapsed", "quiet", "new", "lately", "least") else "lapsed"
    months, limit = _int(a.raw.get("months"), 6, 60), _int(a.raw.get("limit"), 15, 40)
    kw = {"after": a.after, "before": a.before}
    got = {"lapsed": aggregate.lapsed, "quiet": aggregate.quiet, "new": aggregate.new}[what](months, most=limit, **kw) if what in ("lapsed", "quiet", "new") \
        else aggregate.lately(months, most=limit, least=what == "least", **kw)
    w = f'{_mon(got["window"][0])} to {_mon(got["window"][1])}'
    head = {"lapsed": f'{got["total"]} people you once talked to a lot (40+ messages within {months} months) and have barely or not at all in the last {months} months ({w})',
            "quiet": f'{got["total"]} people who went quiet in the last {months} months ({w}) after an active {months} months before',
            "new": f'{got["total"]} people you first talked to in the last {months} months ({w}), 15+ messages each',
            "lately": f'{got["total"]} people you exchanged messages with in the last {months} months ({w}); the most active',
            "least": f'{got["total"]} people you exchanged messages with in the last {months} months ({w}); the least active'}[what]
    o.say(head + f'. counted from every one-to-one conversation on every app, a person on several apps counted once. showing {len(got["people"])}, ranked:')
    idx = answer.thread_index()
    for n, p in enumerate(got["people"], 1):
        o.say(f'{n}. {p["name"]} ({", ".join(p["apps"][:3])}): {p["total"]} messages in all, {p["mine"]} yours; busiest {_mon(p["peak"][0])} to {_mon(p["peak"][1])} ({p["peak"][2]}); '
              f'first {_mon(p["first"])}, last {p["last_day"] or _mon(p["last"])}; last {months} months: {p["recent"]}, the {months} before: {p["before"]}')
        if n <= 12:
            tid = max(p["tids"], key=lambda t: (idx["threads"].get(t) or {}).get("to", ""))
            tail = [m for m in answer.thread_rows(tid, idx)[-3:] if str(m.get("text") or "").strip()]
            if tail:
                o.say("   their last message, to cite:")
                o.show([_row(0, tail[-1])], (), 90)
    o.say("how it was counted: messages in one-to-one chats only (groups are not people). what it cannot see: calls, meetings, and apps that are not in the archive (see sources).")


def shared(a, o):
    from . import aggregate, peek
    limit = _int(a.raw.get("limit"), 12, 40)
    got = aggregate.shared("times" if a.raw.get("by") == "times" else "people", limit, a.after, a.before, a.query)
    marks = sum(got["media"].values())
    if a.raw.get("kind") == "image":
        o.say("pictures and files: the archive keeps the TEXT of messages. " + (f"{marks} of your messages only mark that an attachment was sent ("
              + ", ".join(f"{s}: {n}" for s, n in sorted(got["media"].items(), key=lambda x: -x[1])) + "), with no file name or content, so which image went to most people cannot be counted. " if marks else
              "no message carries a file name or a mark for a picture, so which image went to most people cannot be counted. ")
              + "what CAN be counted is links: call shared with kind link.")
        return
    o.say(f'you sent {got["sent"]} links in your own messages, {got["distinct"]} different pages; {got["repeated"]} of them more than once or to more than one conversation. '
          f'the top {len(got["links"])} by {"times sent" if a.raw.get("by") == "times" else "how many conversations they went to"}:')
    for n, L in enumerate(got["links"], 1):
        o.say(f'{n}. {L["url"]} : sent {L["times"]} times to {L["to"]} conversations ({L["people"]} one-to-one, {L["to"] - L["people"]} groups), {L["first"]} to {L["last"]}')
        for i in L["ids"][:1]:
            k, d = peek.find(i)
            if d is not None:
                o.say("   one of them, to cite:")
                o.show([_row(k, d)], (), 120)
    o.say("how it was counted: web addresses in messages YOU wrote, the same page counted once (tracking tags, www and short forms removed). "
          "what it cannot see: links sent as a preview card with no address in the text, posts on apps not in the archive, and pictures or files (text only).")


def _events(kind, a, o, **more):
    """The events of one kind that fit the call, and the line every such answer must carry: where the table comes from."""
    from . import events
    if not events.ready():
        o.say("that table has not been built on this archive yet (`ctx events run`). use search and read_thread instead, and say the count is only what you could find.")
        return None, ""
    st = events.status()
    got = [e for e in events.find(kind, str(a.raw.get("person") or ""), str(a.raw.get("topic") or ""), a.after, a.before, **more) if _event_ok(e)]
    note = (f'where this comes from: an earlier reading\'s summaries of the {st["cards_read"]} busiest conversations, each item then looked up in that conversation\'s own messages. '
            "an item with a row under it has messages behind it; one marked (summary only) does not and must not be counted as certain: say \"at least N\". "
            "what it cannot see: calls, meetings, apps not in the archive, and conversations too small to have a summary.")
    return got, note


def _event_ok(e):
    """May this event be shown: its conversation is one a reader may list, no row it rests on is left out, and its
    conversation and date are not left out by the owner's rules or the never list."""
    from . import answer, rules
    if not isinstance(e, dict) or rules.broken():
        return False
    if not rules.active().binds:
        return True
    if e.get("tid") and e["tid"] not in answer.thread_index()["threads"] and e["tid"] in answer._thread_index()["threads"]:
        return False
    if any(rules.ref_hidden("r", str(i)) for i in e.get("rows") or []):
        return False
    return not rules.hidden({"src": e.get("src"), "thread": e.get("thread"), "thread_id": e.get("tid") or "", "ts": str(e.get("when") or "")})


def _event_rows(o, e, size=110):
    from . import peek
    for i in (e.get("rows") or [])[:1]:
        k, d = peek.find(i)
        if d is not None:
            o.show([_row(k, d)], (), size)
            return True
    return False


def intros(a, o):
    got, note = _events("intro", a, o)
    if got is None:
        return
    if _bool(a.raw.get("by_me")):
        got = [e for e in got if str(e.get("by", "")).lower() in ("me", "the owner", "owner")]
    limit = _int(a.raw.get("limit"), 20, 40)
    done = [e for e in got if e.get("done") is not False]
    sure = [e for e in done if e.get("rows")]
    mine = [e for e in done if str(e.get("by", "")).lower() in ("me", "the owner", "owner")]
    o.say(f'{len(done)} introductions made ({len(sure)} with messages behind them, {len(done) - len(sure)} from a summary only), {len(mine)} of them by the owner; '
          f'{len(got) - len(done)} more only offered or asked for. different people introduced: {len({str(e.get("a", "")).lower() for e in done})}; '
          f'different people or groups they were introduced to: {len({str(e.get("b", "")).lower() for e in done})}.')
    often = collections.Counter(str(e.get("a") or "") for e in (mine or done) if e.get("a"))
    if often:
        o.say(("introduced most often by the owner: " if mine else "introduced most often: ") + ", ".join(f"{k}: {n}" for k, n in often.most_common(8)))
    for n, e in enumerate(got[:limit], 1):
        o.say(f'{n}. {e.get("by", "?")} introduced {e.get("a", "?")} to {e.get("b", "?")}' + ("" if e.get("done") is not False else " (offered, not shown as done)")
              + (f', {e["when"]}' if e.get("when") else "") + f', in {e.get("thread", "")} ({e.get("src", "")})' + ("" if e.get("rows") else " (summary only)"))
        _event_rows(o, e)
    o.say(note)


def conflicts(a, o):
    got, note = _events("conflict", a, o)
    if got is None:
        return
    limit = _int(a.raw.get("limit"), 20, 40)
    sure = [e for e in got if e.get("rows")]
    areas, people = collections.Counter(str(e.get("area") or "other") for e in got), collections.Counter(str(e.get("with") or "?") for e in got)
    o.say(f'{len(got)} conflicts or tensions ({len(sure)} with messages behind them, {len(got) - len(sure)} from a summary only).',
          "by what they were about: " + ", ".join(f"{k}: {n}" for k, n in areas.most_common()),
          "by person (most first): " + ", ".join(f"{k}: {n}" for k, n in people.most_common(10)),
          "heat: " + ", ".join(f'{h} ({w}): {sum(1 for e in got if e.get("heat") == h)}' for h, w in ((3, "falling-out"), (2, "argument"), (1, "friction"))),
          "the list, most heated first:")
    for n, e in enumerate(sorted(got, key=lambda e: (-(e.get("heat") or 0), not e.get("rows")))[:limit], 1):
        o.say(f'{n}. with {e.get("with", "?")}: {e.get("area", "")}: {e.get("topic", "")}; heat {e.get("heat", "?")}; '
              + {True: "resolved", False: "not resolved"}.get(e.get("resolved"), "unclear how it ended") + (f', {e["when"]}' if e.get("when") else "")
              + f', in {e.get("thread", "")} ({e.get("src", "")})' + ("" if e.get("rows") else " (summary only)"))
        _event_rows(o, e)
    o.say(note)


def ideas(a, o):
    got, note = _events("idea", a, o)
    if got is None:
        return
    limit, want = _int(a.raw.get("limit"), 20, 40), str(a.raw.get("status") or "").lower().strip()
    fates = collections.Counter(str(e.get("fate") or e.get("status") or "unknown") for e in got)
    gone = ("dropped", "never mentioned again")
    o.say(f'{len(got)} ideas, projects or plans floated ({sum(1 for e in got if e.get("rows"))} with messages behind them).',
          "what became of them (decided by code from later mentions in the owner's own messages): " + ", ".join(f"{k}: {n}" for k, n in fates.most_common()),
          f'not followed through (dropped or never mentioned again): {sum(fates[k] for k in gone)}.')
    if want:
        got = [e for e in got if (str(e.get("fate") or e.get("status") or "unknown") in gone if "follow" in want or want == "not" else want in str(e.get("fate") or e.get("status") or "").lower())]
        o.say(f'{len(got)} match status "{want}":')
    for n, e in enumerate(got[:limit], 1):
        o.say(f'{n}. {e.get("what", "?")}' + (f' (with {e["with"]})' if e.get("with") else "") + (f', {e["when"]}' if e.get("when") else "")
              + f': {e.get("fate") or e.get("status") or "unknown"}' + (f', {e["later"]} later mentions' + (f', last {e["last"]}' if e.get("last") else "") if e.get("later") is not None else "")
              + f', in {e.get("thread", "")} ({e.get("src", "")})' + ("" if e.get("rows") else " (summary only)"))
        _event_rows(o, e)
    o.say(note)


def _overview(a, o):
    from . import aggregate
    g = aggregate.overview(a.after, a.before)
    span = (f" from {a.after}" if a.after else "") + (f" to {a.before}" if a.before else "")
    o.say(f'{g["messages"]} messages{span}, {g["mine"]} written by you, in {g["conversations"]} conversations; {g["people"]} named people in one-to-one chats.',
          "by source: " + ", ".join(f"{s}: {n}" for s, n in g["by_source"]),
          "by year: " + ", ".join(f"{y}: {n}" for y, n in g["by_year"]),
          "your own messages by hour of the day (this Mac's clock, 0 to 23): " + ", ".join(f"{h}h: {n}" for h, n in enumerate(g["hours"])),
          f'you wrote on {g["days_written"]} different days. busiest days: ' + ", ".join(f"{d} ({n})" for n, d in g["busiest_days"]),
          "longest silences (days with no message from you on any app): " + ", ".join(f"{n} days after {x} until {y}" for n, x, y in g["gaps"]),
          "each source holds: " + ", ".join(f'{s} {v[0]} to {v[1]}' for s, v in sorted(g["sources"].items())))


def stats(a, o):
    from . import answer, wordindex
    what = a.raw.get("what")
    if what == "overview":
        return _overview(a, o)
    idx = answer.thread_index()
    if what == "person" or (what in ("people", "months", "count") and a.people) or what in ("people", "months"):
        tids = None
        who = str(a.raw.get("person") or "").strip()
        if what == "person" or a.people:
            names = [who] if who else a.people
            if not names:
                raise Bad("give `person`: a name.")
            tids, idx = _threads(names, most=8)
            if not tids:
                o.say("no conversation by that name. try the person tool.")
                return
        if what != "count":
            per, mine, months, first, last = collections.Counter(), collections.Counter(), collections.Counter(), {}, {}
            for day, src, tid, me in _scan(a, tids):
                per[tid] += 1
                mine[tid] += me
                months[(day[:4] if what == "person" else day[:7], src if what == "person" else "")] += 1
                if day:
                    first[tid] = min(first.get(tid, day), day)
                    last[tid] = max(last.get(tid, day), day)
            total = sum(per.values())
            span = (f" from {a.after}" if a.after else "") + (f" to {a.before}" if a.before else "")
            if not total:
                o.say("no messages" + span + ".")
                return
            if what == "people":
                o.say(f"{total} messages in {len(per)} conversations{span}. the most active:")
                dms = [(n, t) for t, n in per.most_common(400) if (idx["threads"].get(t.decode("utf-8", "replace")) or {}).get("kind") == "dm"][:15]
                groups = [(n, t) for t, n in per.most_common(400) if (idx["threads"].get(t.decode("utf-8", "replace")) or {}).get("kind") != "dm"][:8]
                for label, part in (("one-to-one", dms), ("groups", groups)):
                    o.say(label + ":")
                    for n, t in part:
                        th = idx["threads"].get(t.decode("utf-8", "replace")) or {"thread": "?", "src": "?"}
                        o.say(f'- {th["thread"]} ({th["src"]}): {n} messages, {mine[t]} by the owner, {first.get(t, "")} to {last.get(t, "")}')
            elif what == "months":
                keys = sorted(k for k, _ in months)
                o.say(f"{total} messages{span}. per month: " + ", ".join(f"{k}: {months[(k, '')]}" for k in keys[-60:]))
            else:
                o.say(f"{total} messages with {who or ', '.join(a.people)}{span}, {sum(mine.values())} by the owner.")
                for t, n in per.most_common(8):
                    th = idx["threads"].get(t.decode("utf-8", "replace")) or {"thread": "?", "src": "?"}
                    o.say(f'- {th["thread"]} ({th["src"]}): {n} messages, {mine[t]} by the owner, first {first.get(t, "")}, last {last.get(t, "")}')
                o.say("by year and app: " + ", ".join(f"{y} {s}: {n}" for (y, s), n in sorted(months.items())))
            return
    if what != "count":
        raise Bad("what must be one of: people, count, person, months, overview")
    probes = _probes(a.query)
    if not probes:
        raise Bad("count needs `query`: probes separated by ';', each 1 to 3 words that must all be in one row.")
    rx = [[answer._rx(w) for w in p] for p in probes]
    raw = [[w.encode() for w in p] for p in probes]
    only = set(_threads(a.people)[0]) if a.people else None
    from . import rules
    act = rules.active()
    n, years, srcs, threads, mine, first, last = 0, collections.Counter(), collections.Counter(), collections.Counter(), 0, None, None
    for path in answer.FILES:
        if not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            for here, line in wordindex.lines(f, path, raw):
                low = line.lower()
                if not any(all(w in low for w in p) for p in raw):
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict) or act.hides(d):
                    continue
                body = answer._low(" \n ".join(str(d.get(k) or "") for k in answer.FIELDS + ("title",)))
                if not any(all(r.search(body) for r in p) for p in rx):
                    continue
                r = {"src": str(d.get("src") or ""), "ts": str(d.get("ts") or d.get("last_agent_ts") or "")}
                me = d.get("who") == "me" or path == paths.PROMPTS or r["src"] in answer.OWN
                if not a.ok(r) or (a.mine and not me) or (only is not None and str(d.get("thread_id") or "") not in only):
                    continue
                n += 1
                mine += me
                years[r["ts"][:4] or "undated"] += 1
                srcs[r["src"]] += 1
                threads[(str(d.get("thread") or d.get("title") or "")[:40], r["src"])] += 1
                day = r["ts"][:10]
                if day:
                    first, last = min(first or day, day), max(last or day, day)
    if not n:
        o.say("0 rows contain that. counting is by exact words: try other spellings, each as its own probe.")
        return
    o.say(f"{n} rows contain {' or '.join(' + '.join(p) for p in probes)} ({mine} written by the owner), first {first}, last {last}.",
          "by year: " + ", ".join(f"{y}: {c}" for y, c in sorted(years.items())),
          "by source: " + ", ".join(f"{s}: {c}" for s, c in srcs.most_common(10)),
          "by conversation: " + "; ".join(f"{t} ({s}): {c}" for (t, s), c in threads.most_common(10)))


_span = {}


def _spans(counts=None):
    """First and last date of every source, from the thread index and one pass over the docs, of what the owner's rules
    and the never list let through. Kept while the process lives. counts: a dict filled with the rows of each source."""
    from . import answer, rules
    try:
        key = (os.stat(paths.MESSAGES).st_size, os.stat(paths.DOCS).st_size if os.path.exists(paths.DOCS) else 0, rules._key())
    except OSError:
        return {}
    if _span.get("key") != key:
        by, n = {}, collections.Counter()

        def add(src, lo, hi):
            if lo and hi:
                cur = by.get(src)
                by[src] = (min(cur[0], lo), max(cur[1], hi)) if cur else (lo, hi)
        for t in answer.thread_index()["threads"].values():
            add(t["src"], t["from"], t["to"])
            n[t["src"]] += t["n"]
        act = rules.active()
        for path in (paths.DOCS, paths.PROMPTS):
            try:
                with open(path, "rb") as f:
                    for line in f:
                        i, k = line.find(b'"ts": "'), line.find(b'"src": "')
                        if k < 0 or not act.line_ok(line):
                            continue
                        src, day = line[k + 8:line.find(b'"', k + 8)].decode(), line[i + 7:i + 17].decode("ascii", "replace") if i >= 0 else ""
                        n[src] += 1
                        if re.fullmatch(r"\d{4}-\d\d-\d\d", day):
                            add(src, day, day)
            except OSError:
                pass
        _span.update(key=key, by=by, n=dict(n))
    if counts is not None:
        counts.update(_span["n"])
    return _span["by"]


def sources(a, o):
    try:
        with open(os.path.join(paths.HOME, "status.json")) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    from . import rules
    counts = {}
    spans = _spans(counts)
    binds = rules.active().binds            # what the rules let through is counted here, not what was collected
    have, gone = [], []
    for name, v in st.items() if isinstance(st, dict) else []:
        if not isinstance(v, dict):
            continue
        if v.get("rows") and binds and not counts.get(name):
            continue
        if v.get("rows"):
            sp = spans.get(name)
            have.append(f'- {name}: {counts.get(name, 0) if binds else v["rows"]} rows' + (f", {sp[0]} to {sp[1]}" if sp else ""))
        elif v.get("skipped"):
            gone.append(f"- {name}: {str(v['skipped'])[:120]}")
    known = {l.split(":")[0][2:] for l in have}
    have += [f"- {s}: {lo} to {hi}" for s, (lo, hi) in sorted(spans.items()) if s not in known]
    o.say("in the archive:", *(have or ["- nothing yet"]))
    if gone:
        o.say("NOT in the archive (so a question about these cannot be answered from it):", *gone)
    o.say("never in the archive: phone calls, voice notes' audio, photos and videos themselves, anything said in person, "
          "apps not listed above.")


RUN = {"search": search, "read_thread": read_thread, "person": person, "card": card, "timeline": timeline, "saved": saved, "links": links,
       "doc": doc, "profile": profile, "wiki": wiki, "voice": voice, "stats": stats, "sources": sources, "lapsed": lapsed, "shared": shared, "intros": intros, "conflicts": conflicts, "ideas": ideas}
_calls = [0]
OVER = "the search budget for this answer is used up. write the answer now from what you have found, and say what is still unsure."


def run(name, args):
    """One tool call: (text, rows shown). Raises Bad for a mistake in the arguments, and with the one error every reader
    gives while the never list cannot be read. What a tool says passes the owner's rules and the never list once more on
    the way out (rules.scrub): a line naming a person, a source or a stretch of days left out, or citing a row left out,
    is not handed on, whatever the tool read it from (a card, a page, a table built earlier)."""
    from . import rules
    why = rules.broken()
    if why:
        raise Bad(why)
    o = Out()
    RUN[name](Args(args if isinstance(args, dict) else {}), o)
    text = o.text()
    shown = rules.scrub(text, blocks=False)
    if shown != text:
        o.rows = [r for r in o.rows if "[%s]" % r.get("id", "") in shown]
        text = shown or "nothing to show."
    o.rows = rules.keep(o.rows)
    if len(text) > MOST and name != "doc":
        text = text[:MOST].rsplit("\n", 1)[0] + "\n… cut here: ask for something narrower."
    return text, o.rows


def call(name, args):
    """run(), with what the app's agent adds through the environment: a budget of calls and time, a cache, a log of rows shown."""
    env = os.environ
    _calls[0] += 1
    budget, until = env.get("CTX_AGENT_CALLS"), env.get("CTX_AGENT_UNTIL")
    try:
        over = (budget and _calls[0] > int(budget)) or (until and time.time() > float(until))
    except ValueError:
        over = False
    if over:
        return OVER
    t0, key, hit = time.time(), None, None
    if env.get("CTX_AGENT_CACHE"):
        key = os.path.join(env["CTX_AGENT_CACHE"], hashlib.sha1(json.dumps([name, args, env.get("CTX_AGENT_SCOPE", "")], sort_keys=True).encode()).hexdigest()[:20] + ".json")
        try:
            with open(key) as f:
                hit = json.load(f)
        except (OSError, ValueError):
            hit = None
    if hit:
        text, rows = hit["text"], hit["rows"]
    else:
        try:
            text, rows = run(name, args)
        except Bad as e:
            _log(name, args, [], time.time() - t0, str(e))
            raise
        if key:
            try:
                os.makedirs(os.path.dirname(key), exist_ok=True)
                with open(key, "w") as f:
                    json.dump({"text": text, "rows": rows}, f, ensure_ascii=False)
            except OSError:
                pass
    _log(name, args, rows, time.time() - t0)
    return text


def _log(name, args, rows, secs, error=""):
    path = os.environ.get("CTX_AGENT_LOG")
    if path:
        try:
            with open(path, "a") as f:
                from . import rules
                f.write(json.dumps({"tool": name, "args": args, "rows": rows, "secs": round(secs, 2), "error": error, "rules": rules.touched()}, ensure_ascii=False) + "\n")
        except OSError:
            pass
