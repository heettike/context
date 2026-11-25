"""Whole-archive questions: how many, who most, who no longer, what was never followed through, what was shared most.

No single message answers these, so they are graded differently from lookups: the gold is COMPUTED, not written.

  python3 scripts/eval_whole.py --gold            compute the gold for your archive (CTX_HOME) and say how it was made
  python3 scripts/eval_whole.py [--only ids] [--tag NAME] [--workers N]
                                                  answer the 30 questions by the route and grade them by code
  python3 scripts/eval_whole.py --table [--why]   print the table from what is stored, run nothing

Three kinds of gold:
  counted    by a pass over every message made HERE, apart from the code the answer uses (totals, by year, by app, by
             conversation, busiest month and day): a wrong table in ctx/aggregate.py shows up as a wrong answer.
  defined    by ctx/aggregate.py itself, where the answer depends on a definition only that code holds ("used to
             talk to a lot": 40+ messages in six months once, next to none in the last six). These check that the
             answer reports the table faithfully, not that the definition is the right one.
  extracted  from the tables an earlier reading pulled out of the cards (introductions, conflicts, ideas). The gold
             is the table; how far the table can be trusted is a separate, hand-read sample (docs/EVAL.md).

Grading, by code, no model: a "number" question passes when the answer states the gold number within its tolerance;
a "top" question is scored by overlap, the share of the gold's first k names the answer gives (pass at 60%); a "one"
question passes when the answer names the gold item. A wrong number stated flat counts as "wrong number".
Questions and gold with real names in them stay under CTX_HOME/eval; this file holds only the templates.
"""
import json, os, re, statistics, sys, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

MONTHS = "january february march april may june july august september october november december".split()
#   id, kind of gold, how graded, the question ({} filled from the archive at gold time), what the gold is
QUESTIONS = (
    ("w01", "counted", "number", "how many messages are in my archive in total", "messages"),
    ("w02", "counted", "number", "how many messages have i written myself, across every app", "mine"),
    ("w03", "counted", "number", "how many conversations do i have in my archive", "conversations"),
    ("w04", "counted", "number", "how many messages did i send and get in {year}", "year_n"),
    ("w05", "counted", "number", "how many messages do i have on {app}", "app_n"),
    ("w06", "counted", "number", "how many messages have {person} and i exchanged", "person_n"),
    ("w07", "counted", "one", "which year was my busiest for messages", "year"),
    ("w08", "counted", "one", "which month was my busiest ever for messages", "month"),
    ("w09", "defined", "one", "what was my single busiest day for messages", "day"),
    ("w10", "counted", "top", "which apps do i chat on the most", "apps"),
    ("w11", "counted", "top", "who do i talk to the most, one to one", "people"),
    ("w12", "counted", "top", "which group chats are my busiest", "groups"),
    ("w13", "defined", "number", "how many people did i use to talk to a lot and no longer do", "lapsed_n"),
    ("w14", "defined", "top", "who did i use to talk to a lot that i don't talk to anymore", "lapsed"),
    ("w15", "defined", "number", "how many people have gone quiet on me in the last six months", "quiet_n"),
    ("w16", "defined", "top", "who went quiet recently", "quiet"),
    ("w17", "defined", "number", "how many new people did i start talking to in the last six months", "new_n"),
    ("w18", "defined", "top", "who is new in my life lately", "new"),
    ("w19", "defined", "top", "who am i talking to the most these days", "lately"),
    ("w20", "defined", "number", "how many links have i sent to people", "links_n"),
    ("w21", "defined", "number", "how many different links have i shared", "links_distinct"),
    ("w22", "defined", "one", "what link did i share with the most people", "link_top"),
    ("w23", "defined", "top", "what did i share the most: which links went to the most conversations", "links"),
    ("w24", "defined", "one", "what hour of the day do i write the most messages", "hour"),
    ("w25", "extracted", "number", "how many introductions have i made between people", "intros_n"),
    ("w26", "extracted", "number", "how many ideas did i float and never follow through on", "ideas_n"),
    ("w27", "extracted", "top", "which ideas did i never follow through on", "ideas"),
    ("w28", "extracted", "number", "how many arguments or fallings-out does my archive show", "conflicts_n"),
    ("w29", "extracted", "top", "who have i had the most conflicts with", "conflict_people"),
    ("w30", "extracted", "top", "who do i introduce to other people most often", "intro_people"),
)
TOL = {"counted": 0.02, "defined": 0.02, "extracted": 0.05}       # how far a stated number may be from the gold


def scan():
    """One pass over every message, made here and nowhere else: the counted gold."""
    from ctx import paths
    out = {"n": 0, "mine": 0, "year": {}, "month": {}, "day": {}, "src": {}, "thread": {}}
    with open(paths.MESSAGES, errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            out["n"] += 1
            out["mine"] += d.get("who") == "me"
            ts, src, tid = str(d.get("ts") or ""), str(d.get("src") or ""), str(d.get("thread_id") or "")
            for key, val in (("year", ts[:4]), ("month", ts[:7]), ("day", ts[:10]), ("src", src)):
                if val:
                    out[key][val] = out[key].get(val, 0) + 1
            if tid:
                t = out["thread"].setdefault(tid, {"n": 0, "name": "", "kind": str(d.get("kind") or ""), "src": src})
                t["n"] += 1
                t["name"] = str(d.get("thread") or "") or t["name"]
    return out


def _top(d, k=1):
    return [x for x, _ in sorted(d.items(), key=lambda kv: -kv[1])[:k]]


def gold():
    """{question id: {"q", "kind", "grade", "gold", "k"}} for this archive. Names appear here, so the caller keeps it private."""
    from ctx import aggregate
    s = scan()
    year, month, day = _top(s["year"])[0], _top(s["month"])[0], _top(s["day"])[0]
    app = _top(s["src"])[0]
    dms = sorted((t for t in s["thread"].values() if t["kind"] == "dm" and t["name"] and not re.fullmatch(r"[+\d\s()-]+", t["name"])), key=lambda t: -t["n"])
    groups = sorted((t for t in s["thread"].values() if t["kind"] != "dm" and t["name"]), key=lambda t: -t["n"])
    person = dms[2] if len(dms) > 2 else dms[0]          # not the first: a name the answer cannot get by default
    ov = aggregate.overview()
    hours = ov["hours"]
    day = ov["busiest_days"][0][1] if ov.get("busiest_days") else day        # a day is a day on the owner's clock, which only that table keeps
    hour = max(range(24), key=lambda h: hours[h])
    names = lambda got: [str(p.get("name") or "") for p in got.get("people") or [] if p.get("name")]
    lap, qui, new, lat = aggregate.lapsed(most=10), aggregate.quiet(most=10), aggregate.new(most=10), aggregate.lately(most=10)
    sh = aggregate.shared(most=5)
    link_of = lambda r: re.sub(r"^https?://(www\.)?", "", str(r.get("url") or r.get("key") or "")).rstrip("/")
    g = {"messages": s["n"], "mine": s["mine"], "conversations": len(s["thread"]), "year_n": s["year"][year], "app_n": s["src"][app], "person_n": person["n"],
         "year": year, "month": month, "day": day, "apps": _top(s["src"], 3), "people": [t["name"] for t in dms[:5]], "groups": [t["name"] for t in groups[:5]],
         "lapsed_n": lap["total"], "lapsed": names(lap), "quiet_n": qui["total"], "quiet": names(qui), "new_n": new["total"], "new": names(new), "lately": names(lat)[:5],
         "links_n": sh["sent"], "links_distinct": sh["distinct"], "link_top": link_of(sh["links"][0]) if sh["links"] else "", "links": [link_of(r) for r in sh["links"][:5]], "hour": int(hour)}
    try:                                                 # the extracted tables, by the same reading of them the tools give
        from ctx import events
        ev = events.table() if events.ready() else []
        me = lambda e: str(e.get("by", "")).lower() in ("me", "the owner", "owner")
        intro = [e for e in ev if e["t"] == "intro" and e.get("done") is not False and me(e)]
        idea = [e for e in ev if e["t"] == "idea" and e.get("fate") in ("dropped", "never mentioned again")]
        conf = [e for e in ev if e["t"] == "conflict"]
        if ev:                                           # a count may be given whole or as "with messages behind them": either is the table's number
            g["intros_n"] = [len(intro), sum(bool(e.get("rows")) for e in intro)]
            g["ideas_n"] = [len(idea), sum(bool(e.get("rows")) for e in idea)]
            g["conflicts_n"] = [len(conf), sum(bool(e.get("rows")) for e in conf)]
            g["ideas"] = [str(e.get("what") or "")[:80] for e in idea]
            who = {}
            for e in conf:
                if e.get("with"):
                    who[str(e["with"])] = who.get(str(e["with"]), 0) + 1
            g["conflict_people"] = _top(who, 5)
            who = {}
            for e in intro:
                if e.get("a"):
                    who[str(e["a"])] = who.get(str(e["a"]), 0) + 1
            g["intro_people"] = _top(who, 5)
    except Exception:
        pass
    fill = {"year": year, "app": app.replace("_", " "), "person": person["name"]}
    out = {}
    for qid, kind, how, q, key in QUESTIONS:
        val = g.get(key)
        if val in (None, "", []):
            continue                                     # this archive cannot ask it (no such table)
        out[qid] = {"id": qid, "q": q.format(**fill), "kind": kind, "grade": how, "gold": val, "key": key}
    return out


def numbers(text):
    """Every number an answer states: 1,234 and 1234 and 12.3k and 120k."""
    out = []
    for m in re.finditer(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(\s?[kK])?(?![\w]*\])", str(text)):
        v = float(m.group(1).replace(",", ""))
        out.append(v * 1000 if m.group(2) else v)
    return out


def _flat(s):
    return " ".join(re.findall(r"[^\W_]+", str(s).lower()))


def named(name, text):
    """Is this name (or page) in the answer? A person by full name or by first name of 4+ letters; a link by its host and path."""
    flat, n = _flat(text), _flat(name)
    if not n:
        return False
    if n in flat:
        return True
    first = n.split()[0]
    return len(first) >= 4 and re.search(r"\b" + re.escape(first) + r"\b", flat) is not None and len(n.split()) <= 3


def grade(item, answer):
    """{"pass": bool, "score": 0..1, "why": ...} for one answer, by code."""
    text = re.sub(r"\[\d+\]", "", str(answer or ""))
    how, want = item["grade"], item["gold"]
    if not text.strip():
        return {"pass": False, "score": 0.0, "why": "no answer"}
    if how == "number":
        tol = TOL[item["kind"]]
        got = numbers(text[:1200])
        near = [x for x in got for w in (want if isinstance(want, list) else [want])
                if abs(x - w) <= max(tol * w, 0.5) or (w >= 10000 and abs(x - w) <= 0.006 * w + 500 and x % 100 == 0)]   # a rounded figure for an exact one ("120k" for 120,405)
        if near:
            return {"pass": True, "score": 1.0, "why": "number within tolerance"}
        lead = [x for x in numbers(text[:260]) if not 1990 <= x <= 2035 and x > 3]
        return {"pass": False, "score": 0.0, "why": "wrong number" if lead else "no number"}
    if how == "one":
        forms = [str(want)]
        if item["key"] == "month":
            y, m = str(want).split("-")
            forms += [f"{MONTHS[int(m) - 1]} {y}", f"{MONTHS[int(m) - 1][:3]} {y}"]
        elif item["key"] == "day":
            y, m, d = str(want).split("-")
            forms += [f"{int(d)} {MONTHS[int(m) - 1][:3]}", f"{MONTHS[int(m) - 1][:3]} {int(d)}", f"{MONTHS[int(m) - 1]} {int(d)}", f"{int(d)} {MONTHS[int(m) - 1]}"]
        elif item["key"] == "hour":
            h = int(want)
            forms = [f"{h}h", f"{h}:00", f"{h:02d}:00", f"{(h - 1) % 12 + 1} {'am' if h < 12 else 'pm'}", f"{(h - 1) % 12 + 1}{'am' if h < 12 else 'pm'}", f"{h} to {h + 1}", f"{h}-{h + 1}"]
        low = _flat(text[:900])
        ok = any(_flat(f) in low for f in forms) if item["key"] != "link_top" else _flat(want) in _flat(text)
        return {"pass": ok, "score": 1.0 if ok else 0.0, "why": "named" if ok else "not named"}
    k = min(5, len(want)) if item["key"] not in ("ideas",) else 3
    pool = want[:k] if item["key"] not in ("ideas", "lapsed", "quiet", "new") else want       # a list question may name any of the gold's first ten
    if item["key"] == "ideas":                           # an idea is a phrase: it is named when most of its longer words are there
        flat = set(_flat(text).split())
        words = lambda x: [w for w in _flat(x).split() if len(w) > 3]
        hits = sum(1 for x in pool if words(x) and sum(w in flat for w in words(x)) >= max(2, (len(words(x)) + 1) // 2))
    elif item["key"] in ("links", "link_top"):
        hits = sum(_flat(x) in _flat(text) for x in pool)
    else:
        hits = sum(named(x, text) for x in pool)
    score = min(1.0, hits / float(k)) if k else 0.0
    return {"pass": score >= 0.6, "score": round(score, 2), "why": f"{hits} of the gold's first {k if pool is not want else len(pool)} named"}


def table(items, got, why=False):
    done = [(items[i], got[i]) for i in items if i in got and got[i].get("grade")]
    if not done:
        print("nothing stored yet")
        return
    print(f"\nwhole-archive questions: {len(done)} answered of {len(items)}")
    print(f'{"gold":10} {"graded":7} {"n":>3} {"pass":>5} {"score":>6}')
    for kind in ("counted", "defined", "extracted"):
        for how in ("number", "one", "top"):
            part = [g for it, g in done if it["kind"] == kind and it["grade"] == how]
            if part:
                print(f'{kind:10} {how:7} {len(part):>3} {sum(g["grade"]["pass"] for g in part):>5} {statistics.mean(g["grade"]["score"] for g in part):>6.2f}')
    n = len(done)
    nums = [g for it, g in done if it["grade"] == "number"]
    tops = [g for it, g in done if it["grade"] == "top"]
    use = [g["reply"].get("usage") or {} for _, g in done]
    print(f'all: pass {sum(g["grade"]["pass"] for _, g in done)} of {n}; numbers within tolerance {sum(g["grade"]["pass"] for g in nums)} of {len(nums)}, wrong number stated {sum(g["grade"]["why"] == "wrong number" for g in nums)}; '
          f'top-k overlap {statistics.mean(g["grade"]["score"] for g in tops) if tops else 0:.2f} over {len(tops)}; '
          f'med {statistics.median(g["reply"].get("secs", 0) for _, g in done):.1f}s, calls {statistics.median(u.get("calls", 0) for u in use):.0f}, tok in {statistics.mean(u.get("in", 0) for u in use):.0f}')
    paths_ = sorted({g["reply"].get("path") or "-" for _, g in done})
    print("   by path: " + "  ".join(f'{p} {sum((g["reply"].get("path") or "-") == p for _, g in done)}' for p in paths_))
    if why:
        print("   not passed: " + " ".join(f'{it["id"]}({g["grade"]["why"]})' for it, g in done if not g["grade"]["pass"]))


def main():
    a = sys.argv[1:]
    opt = lambda flag, default=None: a[a.index(flag) + 1] if flag in a and a.index(flag) + 1 < len(a) else default
    from ctx import paths
    base = os.path.join(paths.HOME, "eval")
    os.makedirs(base, exist_ok=True)
    gp = os.path.join(base, "whole.jsonl")
    if "--gold" in a or not os.path.exists(gp):
        items = gold()
        with open(gp, "w") as f:
            for it in items.values():
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        kinds = [it["kind"] for it in items.values()]
        print(f"gold for {len(items)} of {len(QUESTIONS)} questions: counted {kinds.count('counted')}, defined {kinds.count('defined')}, extracted {kinds.count('extracted')}. kept in CTX_HOME/eval/whole.jsonl")
        if "--gold" in a:
            return
    with open(gp) as f:
        items = {d["id"]: d for d in map(json.loads, f)}
    if opt("--only"):
        items = {i: d for i, d in items.items() if i in opt("--only").split(",")}
    folder = os.path.join(base, "runs", f"whole@{opt('--tag', 'base')}")
    os.makedirs(folder, exist_ok=True)
    got = {}
    for i in items:
        try:
            with open(os.path.join(folder, i + ".json")) as f:
                got[i] = json.load(f)
        except (OSError, ValueError):
            pass
    if "--table" not in a:
        from ctx import agent

        def one(i):
            cur = got.get(i) or {}
            if not cur.get("reply") or cur["reply"].get("error"):
                try:
                    reply = agent.answer_for(items[i]["q"], mode="quick", cache=os.path.join(base, "toolcache"), keep=False) or {"answer": "", "error": "the loop did not start", "usage": {}}
                except Exception as e:
                    reply = {"answer": "", "error": type(e).__name__, "usage": {}}
                cur = {"id": i, "reply": {k: reply.get(k) for k in ("answer", "strength", "secs", "error", "usage", "kind", "path")}, "at": int(time.time())}
            cur["grade"] = grade(items[i], cur["reply"].get("answer"))
            with open(os.path.join(folder, i + ".json"), "w") as f:
                json.dump(cur, f, ensure_ascii=False)
            got[i] = cur
        with ThreadPoolExecutor(int(opt("--workers", 3))) as ex:
            list(ex.map(one, list(items)))
    else:
        for i in got:                                    # the grader is code: regrade what is stored, free
            got[i]["grade"] = grade(items[i], got[i]["reply"].get("answer")) if i in items else got[i].get("grade")
    table(items, got, "--why" in a)


if __name__ == "__main__":
    main()
