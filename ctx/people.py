"""The people in the archive, counted. No model call.

  python3 -m ctx people [--json]          the people who matter, most written-to and most recent first
  python3 -m ctx person "<name>" [--json] one person: their conversations, what the read-through says, what is open, the last messages

Built from the thread index (answer.thread_index): every one-to-one conversation is a person, and the same name on
two apps is one person. Kept in CTX_HOME/cache/people.json and rebuilt when messages.jsonl changes.
This is the owner's own app reading its own archive on this mac: nothing here is masked.
"""
import json, os, re, tempfile
from . import paths

CACHE = os.path.join(paths.HOME, "cache", "people.json")
MOST = 500
VERSION = 2     # of the cached list: raised when what a person is changes (2: an export's placeholder is not a name)
CLIP = 160
_mem = {}       # the list, kept while the process lives
_cards = {}     # cards by (name, app), for threads whose card file is named another way
# what an export writes where it withholds an account's name. it is not a name: every such conversation is a different person
PLACEHOLDER = re.compile(r"(?i)^(?:(?:instagram|facebook|messenger|linkedin|telegram|whatsapp|snapchat|twitter|x|tiktok|discord|signal|slack|skype|unknown|deleted|deactivated|anonymous) "
                         r"(?:user|member|account|contact|participant)|deleted account|unknown|user|member|account|participant)(?: \d+)?$")


def placeholder(name):
    """Is this what an export puts in place of a name it withheld ("Instagram User", "LinkedIn Member", "Deleted Account")?"""
    return bool(PLACEHOLDER.match(" ".join(str(name or "").split())))


def _answer():
    from . import answer
    return answer


def key_of(name):
    """(key two spellings of one name share, is it a number with no name). Case, accents, emoji, punctuation and word
    order do not count: "Okafor, Maya", "maya okafor" and "Maya Okafor 🌿" are one key."""
    words = _answer()._norm(name).split()
    if not any(c.isalpha() for w in words for c in w):
        digits = "".join(c for c in str(name) if c.isdigit())
        return ("#" + digits if digits else ""), True
    return " ".join(sorted(words)), False


def _days(day):
    try:
        y, m, d = int(day[:4]), int(day[5:7]), int(day[8:10])
        return y * 365 + m * 30 + d
    except ValueError:
        return 0


def _build(idx):
    by = {}
    for tid, t in idx["threads"].items():
        if t.get("kind") == "group":            # a group is not a person
            continue
        name = " ".join(str(t.get("thread") or "").split())
        key, unnamed = key_of(name)
        held = False
        if placeholder(name):                   # the export withheld this account's name
            real = next((o for o in (" ".join(str(o).split()) for o in t.get("names") or []) if o and not placeholder(o) and key_of(o)[0] and not key_of(o)[1]), "")
            handle = " ".join(str(t.get("handle") or "").split()).lstrip("@")
            if real:                            # the same conversation carried a real name at another time: it is that person
                name, (key, unnamed) = real, key_of(real)
            else:                               # its own entry, never joined with the other withheld accounts, and not among the named
                name, key, unnamed, held = ("@" + handle if handle else "%s account, name not in the export" % t["src"]), "@" + tid, not handle, True
        if not key:
            continue
        p = by.get(key)
        if p is None:
            p = by[key] = {"key": key, "unnamed": unnamed, "names": {}, "apps": {}, "tids": [], "messages": 0, "mine": 0, "first": "", "last": "", "held": held}
        p["tids"].append(tid)
        p["messages"] += t["n"]
        p["mine"] += t["mine"]
        p["apps"][t["src"]] = p["apps"].get(t["src"], 0) + t["n"]
        p["names"][name] = p["names"].get(name, 0) + t["n"] + 1
        for other in t.get("names") or []:      # what the same conversation was called before
            other = " ".join(str(other).split())
            if other and key_of(other)[0] and not placeholder(other):
                p["names"].setdefault(other, 0)
        if t["from"] and (not p["first"] or t["from"] < p["first"]):
            p["first"] = t["from"]
        if t["to"] > p["last"]:
            p["last"] = t["to"]
    newest = max([_days(p["last"]) for p in by.values()] or [0])
    out = []
    for p in by.values():
        # a spelling with only letters and spaces reads best; among those, the one most messages came under
        names = sorted(p["names"], key=lambda n: (not all(c.isalpha() or c in " .'-" for c in n), -p["names"][n], n))
        age = max(0, newest - _days(p["last"])) if p["last"] else 3650
        d = {"name": names[0], "aliases": names[1:8], "apps": sorted(p["apps"], key=lambda a: -p["apps"][a]), "threads": len(p["tids"]),
             "messages": p["messages"], "mine": p["mine"], "first": p["first"], "last": p["last"],
             "_key": p["key"], "_tids": p["tids"], "_score": round(p["mine"] * 0.5 ** (age / 365.0), 3)}     # what the owner wrote, halved for each year of silence
        if p["unnamed"]:
            d["unnamed"] = True
        if p.get("held"):                       # a name the export withheld: by its handle when there is one, never among the closest
            d["withheld"] = True
        out.append(d)
    out.sort(key=lambda d: (d["_score"], d["last"], d["messages"]), reverse=True)
    return out


def everyone():
    """Every person, ranked, with the private fields (_key, _tids, _score). Read from the cache when messages.jsonl
    has not changed since it was written."""
    from . import rules
    idx = _answer().thread_index()
    if rules.raw_now():         # a rule being made reads the archive with no rule applied: that table is for this call alone, never kept
        return _build(idx)
    stamp = list(idx["stamp"]) + [len(idx["threads"]), rules.stamp()]      # and the owner's rules and never list: they leave conversations out of the index, or part of one (rules.py)
    got = _mem.get("both")
    if got is not None and got[0] == stamp:
        return got[1]
    try:
        with open(CACHE, encoding="utf-8") as f:
            got = json.load(f)
        if got.get("stamp") == stamp and got.get("v") == VERSION:
            _mem["both"] = (stamp, got["people"])
            return got["people"]
    except (OSError, ValueError, AttributeError):
        pass
    people = _build(idx)
    try:                    # a cache: if it cannot be written the list still serves this run
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CACHE), suffix=".new")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"v": VERSION, "stamp": stamp, "people": people}, f, ensure_ascii=False)
        os.replace(tmp, CACHE)
    except OSError:
        pass
    _mem["both"] = (stamp, people)          # the table and the stamp it was made under, in one assignment
    return people


def _public(p):
    return {k: v for k, v in p.items() if not k.startswith("_")}


def people(most=MOST):
    """The people who matter: [{"name", "aliases", "apps", "threads", "messages", "mine", "first", "last"}], ranked by how much
    the owner wrote to them and how lately, at most 500. A name that is only a phone number carries "unnamed": true."""
    return [_public(p) for p in everyone()[:max(0, int(most))]]


def find(name):
    """The person a name means, or None: the same name first, then a name that holds every word asked for
    (the highest ranked of those)."""
    key, _ = key_of(name)
    if not key:
        return None
    all_ = everyone()
    for p in all_:
        if p["_key"] == key:
            return p
    for p in all_:
        if key in [key_of(a)[0] for a in p["aliases"]]:
            return p
    if key.startswith("#"):
        return next((p for p in all_ if p["_key"].startswith("#") and len(key) > 6 and p["_key"].endswith(key[1:])), None)
    want = key.split()
    for p in all_:          # ranked: the first hit is the one who matters most
        have = p["_key"].split()
        if all(any(h == w or (len(w) > 2 and h.startswith(w)) for h in have) for w in want):
            return p
    return None


def _card(tid, t):
    from . import rules, understand
    if rules.card_hidden(understand._key("chat:" + tid)):
        return None
    try:
        with open(os.path.join(understand.CARDS, understand._key("chat:" + tid) + ".json"), encoding="utf-8") as f:
            c = json.load(f)
        return rules.scrub_card(c) if isinstance(c, dict) else None     # what the owner's rules and the never list leave out is not in it as read
    except (OSError, ValueError):
        pass
    try:
        stamp = os.stat(understand.CARDS).st_mtime_ns
    except OSError:
        return None
    stamp = (stamp, rules._key())
    if _cards.get("stamp") != stamp:
        norm = _answer()._norm
        _cards.update(stamp=stamp, by={(norm(c.get("_title", "")), str(c.get("_src", ""))): c for c in understand.cards() if isinstance(c, dict)})
    return _cards["by"].get((_answer()._norm(t["thread"]), t["src"]))


def _one_line(card, most=CLIP):
    if not isinstance(card, dict):
        return ""
    s = card.get("summary") or card.get("who") or ""
    if isinstance(s, list):
        s = "; ".join(str(x) for x in s)
    return " ".join(str(s).split())[:most]


def page_block(name_keys, page="people"):
    """The paragraph about someone on a profile page: the line that names them and the lines under it, up to the next
    blank line, heading or name. "" when the page does not name them."""
    from . import understand
    lines = understand.page(page).splitlines()          # as it may be handed out now (rules.scrub)
    if not lines:
        return ""
    norm = _answer()._norm

    def head_of(line):          # the part of a line that can be a name: bold text, a heading, or what comes before the colon
        s = line.strip()
        m = re.match(r"^(?:[-*]\s+)?\*\*([^*]+)\*\*", s)
        if m:
            return m.group(1)
        if s.startswith("#"):
            return s.lstrip("# ")
        return s.lstrip("-* ").split(":")[0] if ":" in s[:80] else ""

    def names(line):
        h = norm(re.sub(r"\([^)]*\)", " ", head_of(line)))
        return " ".join(sorted(h.split()))
    starts = lambda l: bool(l.strip()) and (l.lstrip().startswith(("#", "**")) or bool(re.match(r"^[-*]\s+\*\*", l)))
    for i, line in enumerate(lines):
        got = names(line)
        if not got or not any(k == got or (len(k.split()) > 1 and set(k.split()) <= set(got.split())) for k in name_keys):
            continue
        out, plain = [line.strip()], not starts(line) and not line.lstrip().startswith(("-", "*"))
        for nxt in lines[i + 1:]:
            if not nxt.strip():
                if len(out) == 1 and not plain:     # a blank line between a name and its lines
                    continue
                break
            if starts(nxt) or (plain and not nxt.startswith((" ", "\t", "-", "*")) and ":" in nxt[:80]):
                break
            out.append(nxt.strip())
        return "\n".join(out)[:2000]
    return ""


def _open(p, cards):
    out, seen = [], set()
    for title, c in cards:
        for what in (c.get("open") or []) if isinstance(c.get("open"), list) else []:
            what = " ".join(str(what).split())[:240]
            if what and what not in seen:
                seen.add(what)
                out.append({"what": what, "kind": "open", "date": str(c.get("_to") or "")[:10], "thread": title, "ids": [], "from": "read-through"})
    keys = {p["_key"]} | {key_of(a)[0] for a in p["aliases"]}
    from . import loops as _loops
    for l in _loops.kept():         # the loops the owner's rules and the never list still let through
        if isinstance(l, dict) and key_of(l.get("thread", ""))[0] in keys:
            ids = l.get("ids") if isinstance(l.get("ids"), list) else [l.get("ids")] if l.get("ids") else []
            out.append({"what": " ".join(str(l.get("q") or l.get("what") or "").split())[:240], "kind": str(l.get("kind") or "loop"),
                        "date": str(l.get("date") or "")[:10], "thread": str(l.get("thread") or ""), "ids": [str(i) for i in ids], "from": "loops"})
    return out[:20]


def _tail(tid, idx, n=5):
    """The last n messages of one conversation, read at their places in the file (the whole conversation is not read)."""
    from . import rules
    t = idx["threads"].get(tid)
    if not t:
        return []
    start, count = t["at"]
    out, act = [], rules.active()
    try:
        with open(paths.MESSAGES, "rb") as f:
            for off in reversed(idx["offs"][start:start + count]):      # from the newest back, past any the owner's rules or the never list leave out
                if len(out) >= n:
                    break
                f.seek(off)
                try:
                    d = json.loads(f.readline())
                except ValueError:
                    continue
                if isinstance(d, dict) and str(d.get("thread_id") or "") == tid and not act.hides(d):
                    out.append(d)
    except OSError:
        pass
    return out[::-1]


def person(name):
    """One person: the list's fields, with "threads" as the conversations themselves, plus "about", "open" and "recent".
    {"error": ...} when nobody has that name."""
    name = " ".join(str(name or "").split())
    p = find(name) if name else None
    if not p:
        return {"error": "nobody by that name in your archive"}
    idx = _answer().thread_index()
    out, threads, cards, recent = _public(p), [], [], []
    for tid in p["_tids"]:
        t = idx["threads"].get(tid)
        if not t:
            continue
        c = _card(tid, t)
        if isinstance(c, dict):
            cards.append((t["thread"], c))
        threads.append({"id": tid, "app": t["src"], "title": t["thread"], "messages": t["n"], "last": t["to"], "summary": _one_line(c)})
        recent += _tail(tid, idx)
    threads.sort(key=lambda t: (t["last"], t["messages"]), reverse=True)
    recent.sort(key=lambda d: str(d.get("ts") or ""))
    about = page_block({p["_key"]} | {key_of(a)[0] for a in p["aliases"]})
    if not about:
        about = "\n".join(s for s in (_one_line(c, 600) for _, c in cards) if s)[:2000]
    out.update(threads=threads, about=about, open=_open(p, cards),
               recent=[{"id": str(d.get("id") or ""), "ts": str(d.get("ts") or ""), "who": "me" if d.get("who") == "me" else "them", "app": str(d.get("src") or ""),
                        "text": " ".join(str(d.get("text") or "").split())[:CLIP]} for d in recent[-5:]])
    return out


def main(argv, one=False):
    as_json = "--json" in argv
    args = [a for a in argv if a != "--json"]
    if one:
        got = person(" ".join(args))
        if as_json or "error" in got:
            print(json.dumps(got, ensure_ascii=False))
            return 1 if "error" in got else 0
        print(f'{got["name"]}  ({", ".join(got["apps"])})  {got["messages"]} messages, {got["mine"]} yours, {got["first"]} to {got["last"]}')
        if got["about"]:
            print("\n" + got["about"])
        if got["threads"]:
            print("\nconversations:")
            for t in got["threads"]:
                print(f'  {t["app"]:<12} {t["messages"]:>6}  {t["last"]}  {t["title"]}' + (f'  ({t["summary"]})' if t["summary"] else ""))
        if got["open"]:
            print("\nopen:")
            for o in got["open"]:
                print(f'  {o["date"]}  {o["what"]}')
        if got["recent"]:
            print("\nlast messages:")
            for r in got["recent"]:
                print(f'  {r["ts"][:10]} {r["who"]}: {r["text"]}')
        return 0
    got = people()
    if as_json:
        print(json.dumps(got, ensure_ascii=False))
        return 0
    for p in got:
        print(f'{p["mine"]:>7} of {p["messages"]:<7} {p["last"]}  {p["name"]}  ({", ".join(p["apps"])})' + ("  [name withheld]" if p.get("withheld") else "  [number only]" if p.get("unnamed") else ""))
    if not got:
        print("nobody yet: python3 -m ctx collect reads your conversations first.")
    return 0
