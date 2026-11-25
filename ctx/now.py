"""The last 30 days, for the app's home: who is waiting on the owner, what they said they would do, what they keep coming
back to, and how much the archive holds month by month. All by code, no model call.

  python3 -m ctx now [--json]

  {"at": iso time it was computed,
   "waiting":  [{"who", "what", "when", "days", "thread", "id", "src"}]   people waiting on the owner, longest first, at most 4
   "promised": [{"what", "when", "days", "thread", "id", "src"}]          things the owner said they would do, at most 4
   "mind":     [{"what", "detail", "thread"}]                             what the owner wrote most about, at most 4
   "strip":    [{"ym", "n"}]}                                             messages and docs per month, oldest first

Computed once and kept in CTX_HOME/cache/home.json until the archive or the day changes. A home that guesses wrong is
worse than an empty one, so the rules lean towards leaving a thing out: any list may be empty, and a failure gives the
keys with empty lists, never an error.
"""
import collections, json, os, re, time
from . import langpacks, paths

CACHE = os.path.join(paths.HOME, "cache", "home.json")
DAYS, MOST = 30, 4
OWN = ("apple_notes", "obsidian", "google_keep")
# what is not a person: senders of receipts, codes and news; lists and bots
NOT_A_PERSON = re.compile(r"(?i)\b(bot|no.?reply|do.?not.?reply|notifications?|alerts?|support|team|info|news(letter)?|updates?|billing|receipts?|orders?|verify|verification|otp|bank|payments?|"
                          r"security|admin|service|customer|care|help(desk)?|digest|offers?|deals?|store|shop|official|broadcast|channel|mailer|marketing|hello|welcome|jobs?|careers?)\b|bot$|@|\.com\b|^\+?\d[\d\s-]{5,}$")
BLAST = re.compile(r"(?i)\b(just launched|we('re| are) (live|launching|hiring|excited)|launching|check (it|us) out|excited to (share|announce)|happy to (share|announce)|use code|sign up|register (now|here)|"
                   r"join (us|the)|limited (seats|slots)|price point|dm (me|us) (for|to)|link in bio|forwarded|hello everyone|hi (all|everyone)|dear (all|customer|sir))\b")

@langpacks.on_change
def _words():
    """The patterns that hold words of a language, built from every pack there is (ctx/langpacks.py) and built again when
    one is added: nothing here names a language.
    ASKS            a line that wants an answer: a question mark, or a request in any pack's words
    PROMISE         the owner's own words that commit to something
    NOT_A_PROMISE   what reads like one and is not
    DONE            a later line of the owner's that looks like the thing done, or a link
    NOISE           a message a machine sent (a code, a receipt, a delivery or bank notice, an offer): nobody is waiting"""
    global ASKS, PROMISE, NOT_A_PROMISE, DONE, NOISE
    NOISE = re.compile(r"(?i)(?<![^\W_])(?:%s)(?![^\W_])" % langpacks.alt("automated"))
    ASKS = re.compile(r"(?i)\?|\b(?:%s)\b" % langpacks.alt("asks"))
    PROMISE = re.compile(r"(?i)\b(?:%s)\b" % langpacks.alt("promises"))
    NOT_A_PROMISE = re.compile(r"(?i)\b(?:%s)\b|\bif\b[^.!?\n]{0,80}\b(?:i'?ll|i will)\b" % langpacks.alt("not_promises"))
    DONE = re.compile(r"(?i)\b(?:%s)\b|https?://" % langpacks.alt("done"))


def _empty(at=""):
    return {"at": at, "waiting": [], "promised": [], "mind": [], "strip": []}


def _stamp(day):
    from . import rules
    return [day, 2, str(rules._key())] + [os.path.getsize(p) if os.path.exists(p) else 0 for p in (paths.MESSAGES, paths.DOCS, paths.PROMPTS)]


def _phrase(text, most=58):
    """A short plain phrase cut from a message: the sentence that asks or commits, scrubbed, never more than `most` characters."""
    from . import scrub
    text = " ".join(str(scrub.scrub(str(text or ""))).split())
    text = re.sub(r"https?://\S+", "", text).strip()
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\s*\n\s*", text) if p.strip()]
    best = next((p for p in parts if ASKS.search(p) or PROMISE.search(p)), parts[0] if parts else "")
    if len(best) > most:
        best = best[:most].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
    return best


def _asks(text):
    """Does this line of theirs want an answer from the owner? A question or a request in a short message written to the owner: not
    a notice, not a forwarded blurb, not something sent to many (a link with an announcement), and a "?" inside a web
    address does not count."""
    text = str(text or "")
    bare = re.sub(r"https?://\S+", " ", text)
    if NOISE.search(text) or len(bare.split()) < 2 or len(bare) > 280:
        return False
    if bare != text and "?" not in bare:        # a link with no question beside it is something shared, not something asked
        return False
    return bool(ASKS.search(bare)) and not BLAST.search(bare)


def _days(ts, now):
    try:
        return max(0, int((now - time.mktime(time.strptime(str(ts)[:10], "%Y-%m-%d"))) // 86400))
    except (ValueError, OverflowError):
        return 0


def _dated(path, since, today, months=None):
    """The rows of a file dated inside the window, parsed; every dated line is counted into months on the way. Only the
    rows the owner's rules and the never list let through, in both."""
    from . import rules
    act = rules.active()
    if act.broken:
        return
    try:
        with open(path, "rb") as f:
            for line in f:
                i = line.find(b'"ts": "')
                if i < 0:
                    continue
                day = line[i + 7:i + 17].decode("ascii", "replace")
                inside, count = since <= day <= today, months is not None and day[:7] <= today[:7]
                if not (inside or count):
                    continue
                d = None
                if inside or act.binds:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(d, dict) or (act.binds and act.hides(d)):
                        continue
                if count:
                    months[day[:7]] += 1
                if inside:
                    yield d
    except OSError:
        return


def _strip(months):
    """Counts per month, oldest first, with the empty months between filled in. A stray date long before the rest
    (a file dated 1970) is left out: the strip starts where the months begin to follow each other."""
    good = sorted(m for m in months if re.match(r"^(19|20)\d\d-(0[1-9]|1[0-2])$", m))
    num = lambda m: int(m[:4]) * 12 + int(m[5:7])
    while len(good) > 1 and num(good[1]) - num(good[0]) > 24:
        good.pop(0)
    out = []
    if good:
        n, last = num(good[0]), num(good[-1])
        while n <= last:
            ym = "%04d-%02d" % ((n - 1) // 12, (n - 1) % 12 + 1)
            out.append({"ym": ym, "n": months.get(ym, 0)})
            n += 1
    return out


def _waiting(by_thread, threads, who_of, now):
    out = []
    for tid, rows in by_thread.items():
        t, p = threads.get(tid), who_of.get(tid)
        if not t or t.get("kind") != "dm" or p is None or t.get("mine", 0) < 3:      # a person the owner has written to, one to one
            continue
        if p.get("unnamed") or p.get("withheld") or NOT_A_PERSON.search(p["name"]) or p["rank"] >= 400:
            continue
        last = rows[-1]
        if last.get("who") == "me":
            continue
        theirs = []
        for d in reversed(rows):                # what they wrote since their last word
            if d.get("who") == "me":
                break
            theirs.append(d)
        # the owner wrote to them this month, or they are among the people they write to most: an old contact's announcement is not someone waiting
        if p["rank"] >= 80 and not any(d.get("who") == "me" for d in rows):
            continue
        asks = [d for d in theirs if _asks(d.get("text"))]
        if not asks:
            continue
        d = asks[0]                             # the latest line of theirs that asks
        days = _days(d.get("ts"), now)
        what = _phrase(d.get("text"))
        if days < 1 or len(what) < 6:
            continue
        out.append({"who": p["name"], "what": what, "when": str(d.get("ts") or ""), "days": days, "thread": str(t.get("thread") or ""), "id": str(d.get("id") or ""), "src": str(t.get("src") or ""),
                    "_rank": p["rank"]})
    close = [w for w in out if w["_rank"] < 150] or out         # the people the owner actually talks to, when any of them wait
    close.sort(key=lambda w: (-w["days"], w["_rank"]))
    return [{k: v for k, v in w.items() if not k.startswith("_")} for w in close[:MOST]]


def _promised(by_thread, threads, who_of, now, since):
    out, seen = [], set()
    try:                                        # what an earlier reading already judged open, dated by the message behind it
        from . import events, peek
        for e in events.table() if events.ready() else []:
            if e.get("t") != "commitment" or e.get("done") is True or str(e.get("by") or "").lower() not in ("me", "the owner", "owner") or str(e.get("when") or "9")[:7] < since[:7]:
                continue
            rid = next((str(i) for i in e.get("rows") or [] if isinstance(i, (str, int))), "")
            d = peek.find(rid)[1] if rid else None
            if not isinstance(d, dict) or not since <= str(d.get("ts") or "")[:10] or d.get("who") != "me":
                continue
            tid = str(d.get("thread_id") or "")
            later = [x for x in by_thread.get(tid, []) if x.get("who") == "me" and str(x.get("ts")) > str(d.get("ts"))]
            if tid in seen or any(DONE.search(str(x.get("text") or "")) for x in later):
                continue
            seen.add(tid)
            out.append({"what": _phrase(e.get("what")), "when": str(d.get("ts") or ""), "days": _days(d.get("ts"), now), "thread": str(d.get("thread") or ""), "id": rid, "src": str(d.get("src") or ""), "_sure": 1})
    except Exception:
        pass
    for tid, rows in by_thread.items():
        t, p = threads.get(tid), who_of.get(tid)
        if not t or tid in seen or (t.get("kind") == "dm" and (p is None or p.get("unnamed") or NOT_A_PERSON.search(p["name"]))):
            continue
        for n in range(len(rows) - 1, -1, -1):  # their latest promise in this conversation
            d = rows[n]
            text = str(d.get("text") or "")
            if d.get("who") != "me" or not PROMISE.search(text) or NOT_A_PROMISE.search(text) or "?" in text or len(text) > 400:
                continue
            if any(x.get("who") == "me" and DONE.search(str(x.get("text") or "")) for x in rows[n + 1:]):
                break                           # the owner did it, or something like it, afterwards
            what = _phrase(text)
            if len(what) >= 8:
                seen.add(tid)
                out.append({"what": what, "when": str(d.get("ts") or ""), "days": _days(d.get("ts"), now), "thread": str(t.get("thread") or ""), "id": str(d.get("id") or ""), "src": str(t.get("src") or ""),
                            "_sure": 0 if t.get("kind") != "dm" else 0.5})
            break
    out.sort(key=lambda w: (-w["_sure"], w["days"]))            # the judged ones first, then one-to-one, each newest first
    for w in out:                               # a conversation known only by a number is not named on the home
        if not any(c.isalpha() for c in w["thread"]):
            w["thread"] = ""
    return [{k: v for k, v in w.items() if not k.startswith("_")} for w in out[:MOST]]


def _projects():
    """[(title, names)] from the wiki's catalog of projects, the longest names first; [] when there is no wiki."""
    try:
        from . import people, wiki
        with open(wiki._work("catalog.json"), encoding="utf-8") as f:
            got = json.load(f)
    except Exception:
        return []
    out = []
    for e in got if isinstance(got, list) else []:
        names = [" ".join(re.findall(r"[^\W_]+", str(n).lower())) for n in (e.get("names") or []) + [e.get("title") or ""]]
        names = sorted({n for n in names if len(n) >= 4 and not people.placeholder(n)}, key=len, reverse=True)
        if names and e.get("title"):
            out.append((str(e["title"]), names))
    return out


def _mind(by_thread, threads, who_of, notes, prompts):
    """What the owner wrote most about: their own messages, notes and prompts that name a project the wiki knows, counted by
    project; with no wiki, the projects the owner typed to AI agents about and the groups they wrote most in."""
    from . import people
    projects = _projects()
    word = {n: title for title, names in projects for n in names}
    rx = re.compile(r"(?<![^\W_])(" + "|".join(re.escape(n) for n in sorted(word, key=len, reverse=True)) + r")(?![^\W_])") if word else None
    count = collections.defaultdict(lambda: collections.Counter())
    where = collections.defaultdict(collections.Counter)

    def note(kind, text, thread=""):
        if rx is None:
            return
        flat = " ".join(re.findall(r"[^\W_]+", str(text or "").lower()))
        for title in {word[m] for m in rx.findall(flat)}:
            count[title][kind] += 1
            if thread:
                where[title][thread] += 1
    for tid, rows in by_thread.items():
        t, p = threads.get(tid), who_of.get(tid)
        if not t or (t.get("kind") == "dm" and (p is None or p.get("unnamed"))):
            continue
        for d in rows:
            if d.get("who") == "me":
                note("messages", d.get("text"), str(t.get("thread") or ""))
    for d in notes:
        note("notes", str(d.get("title") or "") + " " + str(d.get("text") or "")[:4000])
    typed = collections.Counter()
    for d in prompts:
        name = " ".join(str(d.get("thread") or "").split())
        typed[name] += 1
        flat = " ".join(re.findall(r"[^\W_]+", name.lower()))
        title = word.get(flat) or next((word[m] for m in (rx.findall(flat) if rx else [])), None)
        if title:
            count[title]["prompts"] += 1
        elif rx is not None:
            note("prompts", d.get("text"))
    out = []
    plural = lambda n, w: "%d %s" % (n, w if n != 1 else w[:-1])
    for title, c in sorted(count.items(), key=lambda x: -(x[1]["messages"] + 3 * x[1]["notes"] + min(x[1]["prompts"], 80) * 0.5)):
        if c["messages"] + c["notes"] + c["prompts"] < 5 or people.placeholder(title):
            continue
        detail = ", ".join(plural(c[k], k) + (" to ai agents" if k == "prompts" else "") for k in ("messages", "notes", "prompts") if c[k])
        out.append({"what": title, "detail": detail, "thread": where[title].most_common(1)[0][0] if where[title] else ""})
    if not out:                                 # no wiki yet: the projects typed about, then the groups the owner wrote most in
        for name, n in typed.most_common(MOST):
            if name and n >= 5:
                out.append({"what": name, "detail": plural(n, "prompts") + " to ai agents", "thread": ""})
        groups = sorted(((sum(d.get("who") == "me" for d in rows), threads[tid]) for tid, rows in by_thread.items() if tid in threads and threads[tid].get("kind") == "group"), key=lambda x: -x[0])
        for mine, t in groups:
            if mine >= 5 and not people.placeholder(t.get("thread")):
                out.append({"what": str(t.get("thread") or ""), "detail": plural(mine, "messages"), "thread": str(t.get("thread") or "")})
    return out[:MOST]


def build(now=None):
    """Compute it. Each list is made apart, so one that fails leaves the others standing."""
    from . import answer, people, rules
    now = now or time.time()
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    since = time.strftime("%Y-%m-%d", time.localtime(now - DAYS * 86400))
    out = _empty(time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)))
    months, by_thread, notes, prompts, threads, who_of = collections.Counter(), collections.defaultdict(list), [], [], {}, {}
    try:
        for d in _dated(paths.MESSAGES, since, today, months):
            if str(d.get("text") or "").strip() and not d.get("last_only") and not rules.hidden(d):
                by_thread[str(d.get("thread_id") or "")].append(d)
        for rows in by_thread.values():
            rows.sort(key=lambda d: str(d.get("ts") or ""))
        notes = [d for d in _dated(paths.DOCS, since, today, months) if d.get("src") in OWN and not rules.hidden(d)]
        prompts = [d for d in _dated(paths.PROMPTS, since, today) if not rules.hidden(d)]
        threads = answer.thread_index()["threads"]
        for rank, p in enumerate(people.everyone()):
            for tid in p["_tids"]:
                who_of[tid] = dict(p, rank=rank)
    except Exception:
        pass
    for key, make in (("strip", lambda: _strip(months)), ("waiting", lambda: _waiting(by_thread, threads, who_of, now)),
                      ("promised", lambda: _promised(by_thread, threads, who_of, now, since)), ("mind", lambda: _mind(by_thread, threads, who_of, notes, prompts))):
        try:
            out[key] = make()
        except Exception:
            out[key] = []
    return out


def get(now=None, fresh=False):
    """The home's data, from the cache when the archive and the day are the same as when it was made. Never raises."""
    try:
        stamp = _stamp(time.strftime("%Y-%m-%d", time.localtime(now or time.time())))
        if not fresh:
            try:
                with open(CACHE, encoding="utf-8") as f:
                    got = json.load(f)
                if got.get("stamp") == stamp and isinstance(got.get("home"), dict):
                    return got["home"]
            except (OSError, ValueError):
                pass
        home = build(now)
        try:
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            with open(CACHE + ".new", "w", encoding="utf-8") as f:
                json.dump({"stamp": stamp, "home": home}, f, ensure_ascii=False)
            os.replace(CACHE + ".new", CACHE)
        except OSError:
            pass
        return home
    except Exception:
        return _empty()


def main(argv):
    got = get(fresh="--fresh" in argv)
    if "--json" in argv:
        print(json.dumps(got, ensure_ascii=False))
        return 0
    print("computed %s" % got["at"])
    for w in got["waiting"]:
        print("waiting   %3dd  %s (%s): %s" % (w["days"], w["who"], w["src"], w["what"]))
    for w in got["promised"]:
        print("promised  %3dd  %s (%s): %s" % (w["days"], w["thread"], w["src"], w["what"]))
    for w in got["mind"]:
        print("mind            %s: %s" % (w["what"], w["detail"]))
    print("strip           %d months, %d things" % (len(got["strip"]), sum(m["n"] for m in got["strip"])))
    return 0
