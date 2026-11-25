"""The journal's engine side: what the day's page is made of, in sections the owner can switch, with lines they can
remove or comment on.

  python3 -m ctx journal [--json]

  {"date": "YYYY-MM-DD",
   "sections": [{"id": "today" | "waiting" | "promised" | "mind" | "open" | "notes", "title": "...",
                 "lines": [{"anchor", "text", "row": a row id or "", "thread", "when", "note"?}]}],
   "removed": how many lines the owner took out}

All by code from what the engine already computes (the morning card, the home's last 30 days, the open loops, their
newest notes): no model call here. Which sections are shown is their "show" rule for the journal (rules.py, setting
"sections"); none set means all. A line the owner removes stays out for good (it is known by its section and the row it
rests on, so the same thing does not come back tomorrow); a line the owner comments on carries their note. Their edits are kept in
CTX_HOME/journal_edits.json. What their rules leave out never reaches a line: every source here reads through them.
"""
import hashlib, json, os, time
from . import paths

EDITS = os.path.join(paths.HOME, "journal_edits.json")
TITLES = {"today": "worth a glance today", "waiting": "waiting on you", "promised": "you said you would", "mind": "on your mind", "open": "left open", "notes": "your newest notes"}
ORDER = ("today", "waiting", "promised", "mind", "open", "notes")


def _edits():
    try:
        with open(EDITS, encoding="utf-8") as f:
            got = json.load(f)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def anchor(section, row, text):
    """A line's address: its section and the row it rests on (its words when it rests on none)."""
    return hashlib.sha1(("%s|%s" % (section, row or " ".join(str(text).lower().split())[:80])).encode("utf-8", "replace")).hexdigest()[:10]


def _line(section, text, row="", thread="", when=""):
    text = " ".join(str(text or "").split())
    return {"anchor": anchor(section, row, text), "text": text, "row": str(row or ""), "thread": str(thread or ""), "when": str(when or "")[:10]} if text else None


def _today():
    from . import today
    card = today.get(cached=True)
    card = card.get("card") if isinstance(card, dict) and isinstance(card.get("card"), dict) else card
    if not isinstance(card, dict) or not card.get("line"):
        return []
    return [_line("today", card["line"], card.get("id") or card.get("row") or "", card.get("thread", ""), card.get("ts", ""))]


def _home():
    from . import now
    got = now.get()
    return {"waiting": [_line("waiting", "%s: %s" % (w["who"], w["what"]), w["id"], w["thread"], w["when"]) for w in got.get("waiting", [])],
            "promised": [_line("promised", w["what"], w["id"], w["thread"], w["when"]) for w in got.get("promised", [])],
            "mind": [_line("mind", "%s (%s)" % (w["what"], w["detail"]), "", w.get("thread", "")) for w in got.get("mind", [])]}


def _open(days=30, most=6):
    from . import peek
    since = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    from . import loops as _loops
    loops = _loops.kept()           # the loops the owner's rules and the never list still let through
    out = []
    for l in sorted((l for l in loops if isinstance(l, dict) and str(l.get("date") or "")[:10] >= since), key=lambda l: str(l.get("date")), reverse=True):
        ids = l.get("ids") if isinstance(l.get("ids"), list) else [l.get("ids")] if l.get("ids") else []
        rid = str(ids[0]) if ids else ""
        if rid and peek.find(rid)[1] is None:       # the row is gone, or their rules leave it out
            continue
        out.append(_line("open", l.get("q") or l.get("what"), rid, l.get("thread", ""), l.get("date", "")))
    return [x for x in out if x][:most]


def _notes(days=14, most=5):
    from . import rules
    since = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    got = []
    try:
        with open(paths.DOCS, "rb") as f:
            for line in f:
                if b'"apple_notes"' not in line and b'"obsidian"' not in line and b'"made"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("src") in ("apple_notes", "obsidian", "made") and str(d.get("ts") or "")[:10] >= since and not rules.hidden(d):
                    got.append(d)
    except OSError:
        pass
    got.sort(key=lambda d: str(d.get("ts")), reverse=True)
    return [x for x in (_line("notes", d.get("title") or str(d.get("text") or "")[:80], d.get("id"), "", d.get("ts")) for d in got[:most]) if x]


def get():
    """The journal's sections as they stand now, with their switches and their edits applied. Never raises."""
    try:
        from . import rules
        want = rules.prefs().get("journal", {}).get("sections") or []
    except Exception:
        want = []
    made = {}
    for name, fn in (("today", _today), ("open", _open), ("notes", _notes)):
        try:
            made[name] = fn()
        except Exception:
            made[name] = []
    try:
        made.update(_home())
    except Exception:
        pass
    edits, removed, out = _edits(), 0, []
    for sid in ORDER:
        if want and sid not in want:
            continue
        lines = []
        for l in made.get(sid) or []:
            if not l:
                continue
            e = edits.get(l["anchor"]) or {}
            if e.get("removed"):
                removed += 1
                continue
            if e.get("note"):
                l["note"] = e["note"]
            lines.append(l)
        out.append({"id": sid, "title": TITLES[sid], "lines": lines})
    return {"date": time.strftime("%Y-%m-%d"), "sections": out, "removed": removed}


def edit(line, action, text=""):
    """Their edit to one line: remove | comment (text: their note) | restore. Returns the journal as it now reads, or {"error"}."""
    from . import scrub
    line = str(line or "").strip()
    if action not in ("remove", "comment", "restore") or not line:
        return {"error": "give the line's anchor and one of: remove, comment, restore"}
    text = " ".join(str(text or "").split())[:600]
    if action == "comment" and not text:
        return {"error": "say the note."}
    edits = _edits()
    if action == "restore":
        edits.pop(line, None)
    else:
        e = edits.setdefault(line, {})
        e["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if action == "remove":
            e["removed"] = True
        else:
            e["note"] = scrub.scrub(text)
    with open(os.open(EDITS + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        json.dump(edits, f, ensure_ascii=False, indent=1)
    os.replace(EDITS + ".new", EDITS)
    return get()


def main(argv):
    got = get()
    if "--json" in argv:
        print(json.dumps(got, ensure_ascii=False))
        return 0
    for s in got["sections"]:
        print("%s (%d)" % (s["title"], len(s["lines"])))
        for l in s["lines"]:
            print("  %s  %s%s" % (l["anchor"], l["text"][:100], ("   [your note: %s]" % l["note"][:60]) if l.get("note") else ""))
    return 0
