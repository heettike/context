"""Which model does which job, on the plans the owner has connected.

  python3 -m ctx models [--json]      the models each connected plan can run, what was measured, and who does what
  python3 -m ctx models --refresh     test each model now with one tiny call (else done once a day, in the background)
  python3 -m ctx models --bench       run the answer eval on a slice per model, if the eval exists. spends plan: only on request

Four jobs, each with its own model:
  routine      everyday answers
  analysis     long-form thinking
  first_parse  the one-time read-through of the whole archive
  tools        the model that drives the search (plans it, reranks, digs)
Three presets set all four at once: balanced (the default), best, lean. `settings --set preset=best`, or one job:
`settings --set model.routine=<id>`. An answer may name a model for itself ({"model": id} in serve, --model on the cli).

What the two CLIs can tell us, checked on their own help and by running them:
  claude   has no command that lists models. `--model` takes an alias (haiku, sonnet, opus, fable) or a full name; the
           first stream event names the model that actually served the call; an id the plan cannot run ends with
           "There's an issue with the selected model". So the list is: try each alias once, keep what answered.
  codex    keeps the list it fetched itself in ~/.codex/models_cache.json (slug, display name, description, whether
           it is shown, an order). We read that file; `exec -m <slug>` runs one.
Nothing here is a benchmark from memory: tiers come from a small table by model family, speed is what one tiny call
took on this Mac, and a recommendation says which of the two it rests on.
"""
import json, os, re, threading, time
from . import paths

FILE = os.path.join(paths.HOME, "models.json")
ROLES = ("routine", "analysis", "first_parse", "tools")
PRESETS = ("balanced", "best", "lean")
DAY = 86400
# The fallback table: a family's tier when nothing better is known. Claude's from its own alias names (haiku is the
# small one, opus the large one); "fable" is the alias its help lists first for the latest model, kept with the strongest.
# Codex models are not in the table: their names say nothing we can rely on, so their tier is read from the one-line
# description the codex cli itself gives each model ("our most capable ...", "fast and affordable ...").
FAMILY = [("haiku", "fast"), ("sonnet", "balanced"), ("opus", "strongest"), ("fable", "strongest"), ("mini", "fast"), ("nano", "fast")]
CLAUDE_ALIASES = ("haiku", "sonnet", "opus", "fable")
USE = {"fast": "uses the least of your plan", "balanced": "", "strongest": "uses more of your plan"}
WORSE = "lean puts the fastest model on every job: hard questions get shallower answers, analysis is brief, and the read-through notices less."
SLOW_ROUTINE = 4.0      # seconds to first words above which a model is not put on everyday answers
_lock = threading.Lock()


def _load():
    try:
        with open(FILE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d):
    with open(FILE + ".new", "w") as f:
        json.dump(d, f, indent=1)
    os.replace(FILE + ".new", FILE)


def tier(model_id, description=""):
    """fast, balanced or strongest, from the family table; "" when the name says nothing we know."""
    low = str(model_id).lower()
    for word, t in FAMILY:
        if re.search(r"(^|[^a-z])" + word + r"([^a-z]|$)", low):
            return t
    d = str(description).lower()
    if re.search(r"\b(most capable|strongest|frontier|hardest|complex)\b", d):
        return "strongest"
    if re.search(r"\b(affordable|easier|small(est)?|cheap|lightweight|efficient)\b", d):
        return "fast"
    if re.search(r"\b(everyday|go-to|general)\b", d):
        return "balanced"
    return ""


def candidates(status=None):
    """[{"plan", "ask", "name", "description"}]: what to try on each connected plan. `ask` is what we pass as the model."""
    from . import llm
    st = status or llm.status()
    out = []
    if st["claude"]["signed_in"]:
        out += [{"plan": "claude", "ask": a, "name": "claude " + a, "description": ""} for a in CLAUDE_ALIASES]
    if st["codex"]["signed_in"]:
        listed = []
        try:
            with open(os.path.join(os.path.expanduser("~"), ".codex", "models_cache.json")) as f:
                ms = json.load(f).get("models") or []
            listed = sorted((m for m in ms if isinstance(m, dict) and m.get("slug") and m.get("visibility") == "list"), key=lambda m: m.get("priority") or 99)[:5]
        except (OSError, ValueError, AttributeError):
            pass
        out += [{"plan": "codex", "ask": m["slug"], "name": str(m.get("display_name") or m["slug"]), "description": str(m.get("description") or "")[:200]} for m in listed] \
            or [{"plan": "codex", "ask": "default", "name": "codex default", "description": "whatever the codex cli picks"}]
    if st.get("api_key"):
        out += [{"plan": "api", "ask": m, "name": m, "description": "billed per token"} for m in llm.PRICE]
    return out


def probe(plan, ask):
    """One tiny call. {"ok", "id" (the model that served it), "first", "total", "at"} or {"ok": False, "error"}."""
    from . import llm
    t, first, usage = time.time(), None, {}
    try:
        fn = {"claude": llm._claude_stream, "codex": llm._codex_stream, "api": llm._api_stream}[plan]
        for piece in fn("Answer in one lowercase word.", "Say ok.", ask, usage):
            first = first if first is not None else time.time() - t
        return {"ok": True, "id": usage.get("model") or ask, "first": round(first if first is not None else time.time() - t, 2),
                "total": round(time.time() - t, 2), "at": int(time.time())}
    except Exception as e:
        return {"ok": False, "error": limit_text(e) or ("this plan cannot run it" if "issue with the selected model" in str(e) else type(e).__name__), "at": int(time.time())}


def refresh(force=False, status=None, probe=probe):
    """Test every candidate that has not been tested in a day (all of them with force). Returns how many calls were made."""
    with _lock:
        d, n = _load(), 0
        seen = d.setdefault("probed", {})
        for c in candidates(status):
            key = c["plan"] + ":" + c["ask"]
            if not force and time.time() - (seen.get(key) or {}).get("at", 0) < DAY:
                continue
            seen[key] = dict(probe(c["plan"], c["ask"]), plan=c["plan"], ask=c["ask"], name=c["name"], description=c["description"])
            n += 1
            _save(d)
        d["refreshed"] = int(time.time())
        _save(d)
        return n


def refresh_in_background():
    """Once a day, off the request path. Costs one tiny call per model, so the owner can switch it off (settings: model_check)."""
    from . import settings
    if not settings.spend("model_check") or time.time() - _load().get("refreshed", 0) < DAY:
        return False

    def work():
        try:
            refresh()
        except Exception:
            pass
    threading.Thread(target=work, daemon=True).start()
    return True


def rows(status=None):
    """One row per model a connected plan can run: measured ones first, then what the table expects but has not tried."""
    d = _load()
    seen, out = d.get("probed", {}), {}
    for c in candidates(status):
        p = seen.get(c["plan"] + ":" + c["ask"]) or {}
        mid = p.get("id") or c["ask"]
        if p and not p.get("ok"):
            out[(c["plan"], c["ask"])] = {"id": c["ask"], "name": c["name"], "plan": c["plan"], "ok": False, "why_not": p.get("error", ""), "tier": tier(c["ask"], c["description"])}
            continue
        t = tier(mid, c["description"]) or tier(c["ask"], c["description"]) or "balanced"
        row = {"id": mid, "ask": c["ask"], "name": c["name"], "plan": c["plan"], "ok": True, "tier": t, "measured": bool(p), "order": len(out),
               "first_secs": p.get("first"), "total_secs": p.get("total"), "measured_at": p.get("at"), "usage": USE[t]}
        b = (d.get("bench") or {}).get(c["plan"] + ":" + mid)
        if b:
            row["bench"] = b
        out.setdefault((c["plan"], mid), row)
    return list(out.values())


def recommend(models):
    """{role: {"id", "plan", "why"}} from the tier table, moved by what was measured here. {} when no model works."""
    ok = [m for m in models if m.get("ok")]
    if not ok:
        return {}
    speed = lambda m: m["first_secs"] if m.get("first_secs") is not None else {"fast": 1.5, "balanced": 2.5, "strongest": 5.0}[m["tier"]]
    said = lambda m: (f'first words in {m["first_secs"]} s on this mac' if m.get("measured") else "from the default table; not measured on this mac yet") + \
        (f', {m["bench"]["accuracy"]}% right on the eval' if m.get("bench", {}).get("accuracy") is not None else "")
    # among the strongest: the order the plan itself lists them in (newest first), unless that one is very slow to start
    # here; then the next. among the others: the quickest.
    by = lambda t: sorted((m for m in ok if m["tier"] == t), key=lambda m: (speed(m) > 30, m.get("order", 0) if t == "strongest" else 0, speed(m)))
    fast, mid, strong = by("fast"), by("balanced"), by("strongest")
    quickest = min(ok, key=speed)
    top = (strong or mid or fast)[0]
    out = {"analysis": dict(top, why="the strongest your plan runs: " + said(top)),
           "first_parse": dict(top, why="read once and kept for good, so worth the strongest. " + (top["usage"] + ". " if top["usage"] else "") + said(top)),
           "tools": dict((fast or [quickest])[0], why="it steers the search, several calls an answer, so the quickest: " + said((fast or [quickest])[0]))}
    quick_enough = [m for m in mid + strong if speed(m) <= SLOW_ROUTINE]
    if quick_enough:
        m = quick_enough[0]
        out["routine"] = dict(m, why="a capable model that still starts quickly: " + said(m))
    else:
        slow = (mid + strong)[:1]
        out["routine"] = dict(quickest, why=(f'{slow[0]["name"]} takes {speed(slow[0])} s to start here, too slow for everyday answers; ' if slow else "") + "the quickest instead: " + said(quickest))
    return {r: {"id": m["id"], "ask": m.get("ask", m["id"]), "plan": m["plan"], "name": m["name"], "why": m["why"]} for r, m in out.items()}


def presets(models):
    """What each preset puts on each job, with a line on what it costs."""
    rec, ok = recommend(models), [m for m in models if m.get("ok")]
    if not rec:
        return {}
    speed = lambda m: m["first_secs"] if m.get("first_secs") is not None else {"fast": 1.5, "balanced": 2.5, "strongest": 5.0}[m["tier"]]
    slim = lambda m, why: {"id": m["id"], "ask": m.get("ask", m["id"]), "plan": m["plan"], "name": m["name"], "why": why}
    quickest = min(ok, key=speed)
    strongest = next((m for m in ok if m["id"] == rec["analysis"]["id"] and m["plan"] == rec["analysis"]["plan"]), quickest)
    mids = sorted((m for m in ok if m["tier"] == "balanced"), key=speed) or [quickest]
    return {
        "balanced": {"about": "recommended: the strongest model reads your archive and does long thinking; quick ones answer everyday questions and steer the search.",
                     "roles": rec},
        "best": {"about": "the strongest model on every answer. slower to start and " + (USE["strongest"]) + ".",
                 "roles": {"routine": slim(strongest, "the strongest, also for everyday answers"), "analysis": rec["analysis"], "first_parse": rec["first_parse"],
                           "tools": slim(mids[0], "a capable model steers the search")}},
        "lean": {"about": WORSE, "roles": {r: slim(quickest, "the quickest your plan runs") for r in ROLES}},
    }


def known_status():
    """Which plans are connected, from what was last measured: no cli is run. For the path every model call takes."""
    seen = _load().get("probed", {})
    on = lambda plan: any(v.get("ok") and v.get("plan") == plan for v in seen.values())
    return {"claude": {"signed_in": on("claude")}, "codex": {"signed_in": on("codex")}, "api_key": on("api")}


def roles(models=None, settings=None, now=None):
    """Who does what right now: {role: {"id", "ask", "plan", "name", "why", "source"}} and notes for anything that was changed
    for the owner (a model that is gone, a plan at its limit)."""
    from . import settings as S
    st = settings or S.load()
    models = rows(known_status()) if models is None else models
    pre = presets(models)
    if not pre:
        return {}, ["no model is signed in on this mac."]
    chosen = st.get("preset") if st.get("preset") in pre else "balanced"
    out, notes = {}, []
    known = {(m["plan"], m["id"]): m for m in models if m.get("ok")}
    known.update({(m["plan"], m.get("ask")): m for m in models if m.get("ok")})
    for r in ROLES:
        want = (st.get("models") or {}).get(r)
        base = dict(pre[chosen]["roles"][r], source="preset " + chosen)
        if want:
            hit = next((m for (plan, mid), m in known.items() if mid == want), None)
            if hit:
                base = {"id": hit["id"], "ask": hit.get("ask", hit["id"]), "plan": hit["plan"], "name": hit["name"], "why": "you chose it", "source": "your choice"}
            else:
                notes.append(f"{want}, set for {r}, is not a model your plans can run now. using {base['name']} from the {chosen} preset.")
        out[r] = base
    limited = _load().get("limited") or {}
    now = now or time.time()
    lean = pre["lean"]["roles"]["routine"]
    plan = out["routine"]["plan"]
    if st.get("fallback_when_limited", "on") == "on" and (limited.get(plan) or {}).get("until", 0) > now and out["routine"]["id"] != lean["id"]:
        notes.append(f'your {plan} plan hit its limit ({limited[plan].get("why", "")}): everyday answers use {lean["name"]} until '
                     + time.strftime("%H:%M", time.localtime(limited[plan]["until"])) + ".")
        out["routine"] = dict(lean, source="plan limit")
    return out, notes


def role_of(tag, model, defaults):
    """Which job a call is, from the tag it logs under and the size of model it asked for. None: leave the call as it is."""
    tag = str(tag or "")
    fast, cheap, strong = defaults
    if model not in defaults or tag.startswith(("test", "models")):
        return None                         # the caller named a model of its own
    if tag.startswith("understand"):        # the bulk reading (millions of tokens, on the fast model) is its own case: see route()
        return "first_read" if model == fast else "first_parse"
    if tag == "answer":
        return "analysis" if model == strong else "routine"
    if model == fast or tag.startswith(("answer:", "tools", "title", "coach", "today")):
        return "tools"
    return "analysis" if model == strong else "routine"


_memo = {"at": float("-inf"), "roles": {}, "stamp": None}


def route(tag, model, defaults, override=None):
    """(plan or None, model to pass, role) for one call. plan None means "the engine's usual plan"."""
    role = role_of(tag, model, defaults)
    if override and role in ("routine", "analysis"):       # the composer's picker: this answer only
        hit = next((m for m in rows(known_status()) if m.get("ok") and override in (m["id"], m.get("ask"))), None)
        if hit:
            return hit["plan"], hit.get("ask", hit["id"]), role
        note(f"{override} is not a model your plans can run now. this answer used the {role} model instead.")
    if role is None:
        return None, model, None
    if role == "first_read":
        # reading every thread is millions of tokens. it moves to the first_parse model only when the owner chose that
        # model or the best preset; under balanced the strongest model does the merging and the pages, not the bulk read
        from . import settings as S
        st = S.load()
        role = "first_parse" if (st.get("models") or {}).get("first_parse") or st.get("preset") == "best" else "tools"
    stamp = tuple((os.path.getmtime(p) if os.path.exists(p) else 0) for p in (FILE, os.path.join(paths.HOME, "settings.json")))
    if _memo["stamp"] != stamp or time.monotonic() - _memo["at"] > 60:
        got, _ = roles()
        _memo.update(at=time.monotonic(), roles=got, stamp=stamp)
    r = _memo["roles"].get(role)
    return (r["plan"], r["ask"], role) if r else (None, model, role)


def note(text):
    """Something the owner should see once: kept, newest last, at most twenty."""
    with _lock:
        d = _load()
        notes = [n for n in d.get("notes", []) if n.get("text") != text][-19:] + [{"text": text, "at": int(time.time())}]
        d["notes"] = notes
        _save(d)


LIMIT = re.compile(r"(?i)usage limit|rate.?limit|limit reached|quota|too many requests|overloaded")


def limit_text(e):
    """"" unless this error is a plan at its limit; then one plain sentence, with when it lifts if the cli said so."""
    s = str(e)
    if not LIMIT.search(s):
        return ""
    m = re.search(r"(?i)resets?\s+(?:at|in|on)?\s*([^.\n|]{2,40})", s)
    return "your plan's limit was reached" + (f"; it resets {m.group(0).split(None, 1)[1].strip()}" if m else "") + "."


def limited(plan, e, now=None):
    """Remember that a plan is at its limit, until the time its message names or for an hour."""
    now = now or time.time()
    until = now + 3600
    m = re.search(r"(?i)resets?\s+(?:at\s+)?(\d{1,2})(?::(\d\d))?\s*(am|pm)?", str(e))
    if m:
        h = int(m.group(1)) % 12 + (12 if (m.group(3) or "").lower() == "pm" else 0) if m.group(3) else int(m.group(1))
        t = time.localtime(now)
        at = time.mktime(t[:3] + (h % 24, int(m.group(2) or 0), 0, 0, 0, -1))
        until = at if at > now else at + DAY
    with _lock:
        d = _load()
        d.setdefault("limited", {})[plan] = {"until": int(until), "why": limit_text(e)}
        _save(d)
    _memo["at"] = float("-inf")
    return until


def lean_for(plan=None):
    """The model to drop to when a plan is at its limit: the lean preset's, on another plan when there is one."""
    ms = rows(known_status())
    pre = presets(ms)
    if not pre:
        return None
    others = [m for m in ms if m.get("ok") and m["plan"] != plan]
    if others and plan:
        m = min(others, key=lambda m: m["first_secs"] if m.get("first_secs") is not None else 9)
        return {"plan": m["plan"], "ask": m.get("ask", m["id"]), "name": m["name"]}
    r = pre["lean"]["roles"]["routine"]
    return {"plan": r["plan"], "ask": r["ask"], "name": r["name"]}


def bench(limit=20, run=None):
    """How many answers each model gets right, from the answer eval (scripts/eval_answers.py --live: its made-up set
    through the real model, the fixed pipeline, a slice of `limit` questions). Spends plan, so only ever on request.
    The model under test answers; the search is steered as usual."""
    import subprocess, sys
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "eval_answers.py")
    if not os.path.exists(script):
        return {"error": "there is no answer eval yet (scripts/eval_answers.py), so there is nothing to measure accuracy with."}
    run, out = run or subprocess.run, {}
    for m in [m for m in rows(known_status()) if m.get("ok")]:
        ask = m.get("ask", m["id"])
        from . import guard
        r = run(guard.python_script(script, ["--live", "--slice", str(limit), "--configs", "fixed", "--tag", "bench_" + re.sub(r"[^A-Za-z0-9]", "_", ask)]),
                capture_output=True, text=True, timeout=7200, env=dict(os.environ, CTX_ANSWER_MODEL=ask))
        # its table: <config> <n> <right%> <partly%> <missed%> <wrong%> <bluffed%> <cites ok%> <median secs> ...
        row = next((l.split() for l in (r.stdout or "").splitlines() if l.startswith("fixed") and len(l.split()) >= 9 and l.split()[2].endswith("%")), None)
        try:
            out[m["plan"] + ":" + m["id"]] = {"accuracy": round(float(row[2].rstrip("%"))), "bluffed": round(float(row[6].rstrip("%"))), "secs": float(row[8]),
                                              "questions": int(row[1]), "at": int(time.time())}
        except (TypeError, ValueError, IndexError):
            out[m["plan"] + ":" + m["id"]] = {"error": "the eval gave no result for this model"}
    with _lock:
        d = _load()
        d["bench"] = dict(d.get("bench") or {}, **{k: v for k, v in out.items() if "error" not in v})
        _save(d)
    return out


def report(status=None):
    """Everything the settings page shows about models."""
    from . import settings as S
    st, ms = S.load(), rows(status)
    who, notes = roles(ms, st)
    rec, pre = recommend(ms), presets(ms)
    for m in ms:
        m["recommended_for"] = [r for r in ROLES if rec.get(r, {}).get("id") == m["id"] and rec[r]["plan"] == m["plan"]]
    d = _load()
    return {"models": ms, "roles": who, "preset": st.get("preset", "balanced"), "presets": pre, "recommended": rec,
            "notes": notes + [n["text"] for n in d.get("notes", [])][-5:], "fallback_when_limited": st.get("fallback_when_limited", "on") == "on",
            "limited": {p: v for p, v in (d.get("limited") or {}).items() if v.get("until", 0) > time.time()},
            "measured_at": d.get("refreshed"), "lean_costs": WORSE}


def line(status=None):
    """One line for doctor."""
    who, notes = roles(rows(status))
    if not who:
        return "no model signed in"
    from . import settings as S
    return f'{S.load().get("preset", "balanced")} preset: ' + ", ".join(f'{r} {who[r]["name"]}' for r in ROLES) + (" (" + notes[0] + ")" if notes else "")


def main(args):
    if "--bench" in args:
        print(json.dumps(bench(), ensure_ascii=False))
        return 0
    if "--refresh" in args:
        refresh(force=True)
    else:
        refresh_in_background()
    rep = report()
    if "--json" in args:
        print(json.dumps(rep, ensure_ascii=False))
        return 0
    for m in rep["models"]:
        if not m.get("ok"):
            print(f'  {m["name"]:<22} {m["plan"]:<7} cannot run: {m.get("why_not", "")}')
            continue
        speed = f'{m["first_secs"]} s to first words' if m.get("measured") else "not measured yet"
        print(f'  {m["name"]:<22} {m["plan"]:<7} {m["tier"]:<10} {speed:<26} {m["usage"]:<28} ' + (", ".join(m["recommended_for"]) or "-"))
    print(f'\n{rep["preset"]} preset:')
    for r in ROLES:
        if r in rep["roles"]:
            print(f'  {r:<12} {rep["roles"][r]["name"]:<22} {rep["roles"][r]["why"]}')
    for n in rep["notes"]:
        print("note: " + n)
    return 0
