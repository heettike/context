"""The owner's side of the profile pages: correcting them, and what the app shows around them. No model call.

  python3 -m ctx correct --page people --line "<text>" --wrong            that line is wrong: take it off the page
  python3 -m ctx correct --page people --line "<text>" --fix "<right>"    that line should say this instead
  python3 -m ctx correct --list | --undo <n>
  python3 -m ctx starters [--json]                                        up to six questions for an empty chat
  python3 -m ctx understand --estimate [N]                                what a read-through would cost, before it runs

The pages (core, people, projects, timeline, voice in CTX_HOME/memory) are written by the read-through. A correction is
kept in CTX_HOME/memory/corrections.jsonl and applied to the page at once; the page as it was is copied to
CTX_HOME/backups first. `corrections()` gives the next rebuild what the owner said, so the same mistake is not written again.
"""
import json, os, re, time, unicodedata
from . import paths

PAGES = ("core", "people", "projects", "timeline", "voice")
MEM = os.path.join(paths.HOME, "memory")
LOG = os.path.join(MEM, "corrections.jsonl")
BACKUPS = os.path.join(paths.HOME, "backups")


def _norm(s):
    """A line as compared when it no longer matches letter for letter: case, accents, markdown marks, punctuation and
    spacing do not count."""
    s = unicodedata.normalize("NFKD", str(s or "")).lower()
    return " ".join("".join(c if c.isalnum() or unicodedata.category(c)[0] == "M" else " " for c in s if not "̀" <= c <= "ͯ").split())


def _page(page):
    return os.path.join(MEM, page + ".md")


def _records():
    out = []
    try:
        with open(LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    out.append(d)
    except OSError:
        pass
    return out


def _append(rec):
    os.makedirs(MEM, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _write(page, lines, tail):
    """Put the page back whole: the old one is copied to backups, the new one written beside it and moved into place."""
    path = _page(page)
    os.makedirs(BACKUPS, exist_ok=True)
    stamp, n = time.strftime("%Y%m%d-%H%M%S"), 0
    while True:
        backup = os.path.join(BACKUPS, f"{page}.md.{stamp}" + (f".{n}" if n else ""))
        if not os.path.exists(backup):
            break
        n += 1
    with open(path, "rb") as src, open(backup, "wb") as dst:
        dst.write(src.read())
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + tail)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return backup


def _read(page):
    with open(_page(page), encoding="utf-8", errors="replace") as f:
        text = f.read()
    return text.split("\n")[:-1] if text.endswith("\n") else text.split("\n"), "\n" if text.endswith("\n") or not text else ""


def _where(lines, want):
    """Index of the line meant, or -1: the same text first, then the same text as _norm compares it."""
    want = str(want or "").strip()
    if not want:
        return -1
    for i, l in enumerate(lines):
        if l.strip() == want:
            return i
    n = _norm(want)
    if n:
        for i, l in enumerate(lines):
            if _norm(l) == n:
                return i
    return -1


def _lead(line):
    return re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?", line).group(0)


def correct(page, line, wrong=False, fix=None):
    """Record what the owner said about one line of a page and change the page now. `wrong` removes the line; `fix` puts
    the right version in its place (its indent and bullet are kept). A line that is not on the page is still recorded,
    with "applied": false, for the next rebuild to honour."""
    page, line, fix = str(page or "").strip().lower(), " ".join(str(line or "").split()), " ".join(str(fix or "").split())
    if page.endswith(".md"):
        page = page[:-3]
    if page not in PAGES:
        return {"ok": False, "error": "no such page. pages: " + ", ".join(PAGES)}
    if not line:
        return {"ok": False, "error": "give the line that is wrong."}
    if not wrong and not fix:
        return {"ok": False, "error": "say one of: the line is wrong, or what it should say instead."}
    rec = {"n": len([r for r in _records() if "undo" not in r]) + 1, "page": page, "line": line, "verdict": "fix" if fix else "wrong", "fix": fix,
           "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "applied": False}
    try:
        lines, tail = _read(page)
    except OSError:
        lines = None
    i = _where(lines, line) if lines is not None else -1
    if i >= 0:
        was = lines[i]
        rec.update(applied=True, was=was, at=i, after=lines[i - 1] if i else "")
        if fix:
            lines[i] = fix if re.match(r"^\s*([-*+#]|\d+[.)])\s", fix) else _lead(was) + fix
            rec["now"] = lines[i]
        else:
            del lines[i]
        rec["backup"] = os.path.basename(_write(page, lines, tail))
    _append(rec)
    out = {"ok": True, "n": rec["n"], "page": page, "verdict": rec["verdict"], "applied": rec["applied"]}
    if not rec["applied"]:
        out["note"] = "not found on the page as it is now. kept, so the next read-through leaves it out." if lines is not None else \
            "that page has not been written yet. kept, so the read-through honours it."
    return out


def listing():
    """Every correction made, oldest first, each with its number and whether it was undone."""
    recs = _records()
    undone = {r["undo"] for r in recs if "undo" in r}
    return [dict({k: r.get(k) for k in ("n", "page", "line", "verdict", "fix", "time", "applied")}, undone=r.get("n") in undone) for r in recs if "undo" not in r]


def corrections(page=None):
    """What the owner has said is wrong on the profile pages, for whoever writes those pages next.

    Returns the corrections still in force (undone ones left out), oldest first, as
    [{"page": "people", "line": "<the line as it was shown>", "verdict": "wrong" | "fix", "fix": "<the right version, or ''>", "time": "..."}].
    `page` limits it to one of core, people, projects, timeline, voice.

    A rebuild must honour them: a "wrong" line states something false about the owner and must not come back in any
    wording; a "fix" line must say what "fix" says. `note(page)` is the same thing as text for a prompt, and
    `honour(page, text)` applies them to a freshly written page (drops lines that match a "wrong" one, rewrites lines
    that match a fixed one), for what the model let through."""
    recs = _records()
    undone = {r["undo"] for r in recs if "undo" in r}
    return [{k: r.get(k, "") for k in ("page", "line", "verdict", "fix", "time")} for r in recs
            if "undo" not in r and r.get("n") not in undone and r.get("verdict") in ("wrong", "fix") and (not page or r.get("page") == page)]


def state(fact, key=""):
    """Record something the owner states as true about their life (a rule of kind "fact", rules.py): kept with their
    corrections, so every page written from now on is told it. key: the rule's id, to take it back with unstate()."""
    fact = " ".join(str(fact or "").split())[:300]
    if fact:
        _append({"n": len([r for r in _records() if "undo" not in r]) + 1, "page": "", "verdict": "fact", "fix": fact, "key": str(key), "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    return bool(fact)


def unstate(key):
    """Take back the facts recorded under a rule's id."""
    for r in _records():
        if r.get("verdict") == "fact" and r.get("key") == str(key) and "undo" not in r:
            _append({"undo": r.get("n"), "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")})


def facts():
    """What the owner has stated as fact, still in force, oldest first."""
    recs = _records()
    undone = {r["undo"] for r in recs if "undo" in r}
    return [str(r.get("fix") or "") for r in recs if r.get("verdict") == "fact" and r.get("n") not in undone and r.get("fix")]


def note(page=None, most=60):
    """corrections() as a block to add to the prompt that writes a page, with what the owner has stated as fact. "" when there are none."""
    cs = corrections(page)[-most:]
    told = facts()[-30:]
    out = ""
    if told:
        out += "\n\nThe owner has stated these as facts about their life. They override anything the cards say:\n" + "\n".join("- " + f for f in told)
    if not cs:
        return out
    lines = [f'- wrong, leave it out: "{c["line"][:300]}"' if c["verdict"] == "wrong" else f'- wrong: "{c["line"][:300]}" the truth: "{c["fix"][:300]}"' for c in cs]
    return (out + "\n\nThe owner has read an earlier version of this page and corrected it. These corrections are facts and override the cards:\n"
            + "\n".join(lines) + "\nNever state what a corrected line stated, in any wording.")


def honour(page, text):
    """A freshly written page with the owner's corrections applied again: a line that still matches a corrected one is
    dropped or replaced."""
    cs = {_norm(c["line"]): c for c in corrections(page)}
    if not cs:
        return text
    out = []
    for l in str(text).split("\n"):
        c = cs.get(_norm(l)) if l.strip() else None
        if c is None:
            out.append(l)
        elif c["verdict"] == "fix":
            out.append(c["fix"] if re.match(r"^\s*([-*+#]|\d+[.)])\s", c["fix"]) else _lead(l) + c["fix"])
    return "\n".join(out)


def undo(n):
    """Take one correction back: the page gets its line back (when the correction had changed the page and the page
    still shows that change), and corrections() stops returning it."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return {"ok": False, "error": "give the number of a correction: correct --list shows them."}
    recs = _records()
    rec = next((r for r in recs if r.get("n") == n and "undo" not in r), None)
    if not rec:
        return {"ok": False, "error": "no correction with that number."}
    if any(r.get("undo") == n for r in recs):
        return {"ok": False, "error": "that one was already undone."}
    restored = False
    if rec.get("applied"):
        try:
            lines, tail = _read(rec["page"])
        except OSError:
            lines = None
        if lines is not None:
            if rec["verdict"] == "fix":
                i = _where(lines, rec.get("now") or rec["fix"])
                if i >= 0:
                    lines[i], restored = rec["was"], True
            elif _where(lines, rec["was"]) < 0:
                i = _where(lines, rec.get("after")) + 1 if rec.get("after", "").strip() else 0
                if i == 0 and rec.get("at"):            # the line it stood under is gone: back to the place it had
                    i = min(int(rec["at"]), len(lines))
                lines.insert(i, rec["was"])
                restored = True
            if restored:
                _write(rec["page"], lines, tail)
    _append({"undo": n, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    return {"ok": True, "n": n, "page": rec["page"], "restored": restored}


def correct_main(argv):
    arg = lambda k: argv[argv.index(k) + 1] if k in argv and argv.index(k) + 1 < len(argv) else ""
    if "--list" in argv:
        print(json.dumps(listing(), ensure_ascii=False))
        return 0
    if "--undo" in argv:
        got = undo(arg("--undo"))
    elif arg("--page") and arg("--line") and ("--wrong" in argv or arg("--fix")):
        got = correct(arg("--page"), arg("--line"), wrong="--wrong" in argv, fix=arg("--fix"))
    else:
        print('usage: python3 -m ctx correct --page <%s> --line "<the line>" --wrong | --fix "<the right version>"\n'
              '       python3 -m ctx correct --list | --undo <n>' % "|".join(PAGES))
        return 2
    print(json.dumps(got, ensure_ascii=False))
    return 0 if got.get("ok") else 1


# ---------------------------------------------------------------- starters

GENERIC = ["what did i promise this week?", "who am i waiting to hear back from?", "what was i working on a year ago?",
           "what have i saved and never opened?"]
WHOLE = ["who did i use to talk to but don't anymore?", "what link have i shared with the most people?", "who went quiet on me this year?",          # counted over the
         "what do i fight about most?", "how many ideas did i float and never follow through?", "who have i introduced to the most people?",     # whole archive
         "who am i talking to most these days?", "who is new in my life in the last six months?", "what time of day do i write the most?",        # (aggregate.py, events.py)
         "what was my longest silence?"]
ABOUT_PERSON = ["what did {x} and i last agree on?", "what do i owe {x}?", "when did {x} and i last talk?"]
ABOUT_PROJECT = ["where did i leave {x}?", "what is still open on {x}?", "what did i decide about {x}?"]
ABOUT_MONTH = ["what was i busy with in {x}?", "who did i talk to most in {x}?"]
MONTHS = "january february march april may june july august september october november december".split()
LONGEST = 59


def _projects(most=5):
    """Project names from projects.md: the ones the page calls active first, then the rest in the page's order."""
    try:
        with open(_page("projects"), encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    blocks = []
    for l in lines:
        s = l.strip()
        m = re.match(r"^#{2,4}\s+(.+)$", s) or re.match(r"^(?:[-*]\s+)?\*\*([^*]+)\*\*(.*)$", s)
        if m and not (blocks and re.match(r"^[-*]\s", s) and blocks[-1]["head"].startswith("#")):     # a bold bullet under a heading is a field, not a project
            blocks.append({"head": s, "name": m.group(1), "text": s})
        elif blocks:
            blocks[-1]["text"] += "\n" + s
    out = []
    for b in blocks:
        name = re.sub(r"\([^)]*\)", " ", b["name"])
        name = re.split(r"\s[-–—|:]\s|:|,", name)[0]
        name = " ".join(re.sub(r"^[\d.)\s]+", "", name.replace("*", " ").replace("`", " ")).split()).lower()
        low = b["text"].lower()
        if 2 <= len(name) <= 28 and not re.match(r"^(bets|themes|projects|what|other|summary|notes)\b", name):
            out.append((not re.search(r"\b(status\W{0,6})?active\b", low) or bool(re.search(r"\b(not|no longer) active\b|\binactive\b", low)), len(out), name))
    return [n for _, _, n in sorted(out)][:most]


def _first_names(most=5):
    from . import people
    out = []
    for p in people.people(40):
        if p.get("unnamed") or not p["mine"]:
            continue
        words = [w for w in re.sub(r"[^\w\s.'-]", " ", p["name"]).split() if any(c.isalpha() for c in w)]
        name = (words[0] if words and len(words[0]) > 2 else " ".join(words[:2])).lower()
        if 2 <= len(name) <= 24 and name not in out:
            out.append(name)
        if len(out) >= most:
            break
    return out


def _months(most=3):
    from . import answer
    last = max([t["to"] for t in answer.thread_index()["threads"].values() if t.get("to")] or [""])
    try:
        y, m = int(last[:4]), int(last[5:7])
    except ValueError:
        return []
    out = []
    for back in range(1, most + 1):
        mm = (m - 1 - back) % 12
        out.append(f"{MONTHS[mm]} {y - (1 if m - 1 - back < 0 else 0)}")
    return out


def starters(turn=None):
    """Up to six short things to ask from an empty chat: [{"q": "...", "lens": "<id>"} for the four lenses, then
    {"q": "...", "about": "person" | "project" | "month" | "anything"}]. The two after the lenses are made from the owner's own
    profile by the templates above (who they write to most, what they are building, a recent month); `turn` picks which
    (it changes daily when left out). No model call."""
    from . import lens
    turn = int(time.time() // 86400) if turn is None else int(turn)
    out = [{"q": L["title"].lower(), "lens": L["id"]} for L in lens.listing()][:4]
    own = []
    for kind, pick, forms in (("person", _first_names, ABOUT_PERSON), ("project", _projects, ABOUT_PROJECT), ("month", _months, ABOUT_MONTH)):
        try:
            names = pick()
        except Exception:
            names = []
        for k in range(len(names)):                 # the first name that fits a line of the right length
            q = forms[turn % len(forms)].format(x=names[(turn + k) % len(names)]).lower()
            if len(q) <= LONGEST:
                own.append({"q": q, "about": kind})
                break
    own = own[:2]
    for g in GENERIC[turn % len(GENERIC):] + GENERIC[:turn % len(GENERIC)]:
        if len(own) >= 2:
            break
        own.append({"q": g, "about": "anything"})
    return [s for s in out + own if len(s["q"]) <= LONGEST][:6]


def whole(turn=None, most=3):
    """Questions only the whole archive can answer (counted by code: aggregate.py, events.py), for a caller that wants
    to show what else can be asked: [{"q": "...", "about": "everything"}], rotating daily. No model call."""
    turn = int(time.time() // 86400) if turn is None else int(turn)
    return [{"q": WHOLE[(turn + k) % len(WHOLE)], "about": "everything"} for k in range(max(0, min(int(most), len(WHOLE))))]


def starters_main(argv):
    got = starters()
    print(json.dumps(got, ensure_ascii=False) if "--json" in argv else "\n".join(s["q"] for s in got))
    return 0


# ---------------------------------------------------------------- the read-through, before it runs

PAGES_CALLS = 5     # after the reading, one call per page


def estimate(limit=None):
    """What `understand` would do now: how many conversations have no current card, and about how many model calls
    reading them takes (the fast model for the reading, then the strong one once per page). Reads the archive; no model call."""
    from . import understand
    us = understand.units()
    todo = [(k, m, rows) for k, m, rows in us if not understand._current(k, m)]
    unread = len(todo)
    if limit:
        todo = todo[:int(limit)]
    js = understand.jobs(todo)
    reading = sum(1 if kind == "many" else understand._size(x[2]) // understand.CHUNK + 2 for kind, x in js)
    out = {"conversations": len(us), "unread": unread, "would_read": len(todo), "sittings": len(js), "reading_calls": reading,
           "page_calls": PAGES_CALLS if todo else 0, "calls": reading + (PAGES_CALLS if todo else 0),
           "chars": sum(understand._size(rows) for _, _, rows in todo)}
    try:
        from . import llm
        out["plan"] = llm.status().get("plan", "")
    except Exception:
        out["plan"] = ""
    return out
