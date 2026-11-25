"""The nightly catch-up: a little of the understanding layer every night, on the owner's plan, so it never falls far behind.

The read-through (ctx/understand.py) and the wiki (ctx/wiki.py) only ran when the owner started them. Each night this
spends at most `nightly_calls` model calls (settings; 40 by default, 0 switches it off), in this order:

  1. conversations not read yet: the ones touched in the last 90 days first, then by how much the owner wrote in them
  2. wiki pages whose evidence changed, and the short pages, in the wiki's own order (wiki.build with what is left)

It adds no machinery of its own for what is "done": a conversation is current when its card says so and a page when its
evidence hash matches, exactly as a run started by hand decides, so nothing is done twice and a night cut short loses
nothing. It runs in the small hours (`nightly_hour`, 2 by default, for five hours), only on mains power or with the
battery above half, never while an answer is being written, and it stops at once when the plan says its limit is
reached: no second try, no smaller model in its place. Calls and tokens are in the ledger like every other call.

    python3 -m ctx catchup --status [--fresh]   what last night did, what is still behind (--fresh counts it again now), and
                                                whether tonight's run may start
    python3 -m ctx catchup --run [N]            run now with a budget of N calls (default: the setting), whatever the hour
"""
import json, os, subprocess, sys, time
from . import paths

STATE = os.path.join(paths.HOME, "catchup.json")
HOURS = 5               # how long after nightly_hour a run may still start
SLICE = 10              # calls in one tick, so the 15 minute reads are never held up for long
RECENT = 90 * 86400
BUSY_FOR = 180          # seconds after an answer's last model call during which nothing is started


def _load():
    try:
        with open(STATE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d):
    tmp = "%s.part.%d" % (STATE, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, STATE)


def _settings():
    try:
        from . import settings
        s = settings.load()
        return int(s.get("nightly_calls", 40)), int(s.get("nightly_hour", 2))
    except Exception:
        return 40, 2


def night_of(now, hour):
    """The night this moment belongs to, as the date it began on ("" outside the window)."""
    t = time.localtime(now)
    start = time.mktime(t[:3] + (hour, 0, 0, 0, 0, -1))
    if now < start:
        start -= 86400
    return time.strftime("%Y-%m-%d", time.localtime(start)) if now - start < HOURS * 3600 else ""


def power():
    """(may run, why not). On mains power, or on battery above half. A mac that will not say is taken to be plugged in."""
    try:
        out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return True, ""
    if "AC Power" in out or "Battery Power" not in out:
        return True, ""
    import re
    m = re.search(r"(\d{1,3})%", out)
    pct = int(m.group(1)) if m else 100
    return (True, "") if pct > 50 else (False, "on battery at %d%%" % pct)


def _ledger_size():
    try:
        return os.path.getsize(paths.LEDGER)
    except OSError:
        return 0


def _ledger_since(offset):
    """(calls, tokens in, tokens out, errors) of the ledger rows written after this point in the file."""
    calls = tin = tout = errors = 0
    try:
        with open(paths.LEDGER, "rb") as f:
            f.seek(offset)
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                calls += 1
                tin += d.get("in", 0) or 0
                tout += d.get("out", 0) or 0
                errors += 1 if d.get("error") else 0
    except OSError:
        pass
    return calls, tin, tout, errors


def _recent(now, tags=None):
    """Was a model call logged in the last few minutes (one whose tag starts with one of `tags`, when given)?"""
    try:
        with open(paths.LEDGER, "rb") as f:
            f.seek(max(0, os.path.getsize(paths.LEDGER) - 6000))
            tail = f.read().decode("utf-8", "replace").split("\n")[-12:]
    except OSError:
        return False
    for line in reversed(tail):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if tags is None or str(d.get("tag", "")).startswith(tags):
            return now - (d.get("at") or 0) < BUSY_FOR
    return False


def answering(now=None):
    """Is an answer being written right now? Told from the ledger: an answer's own call in the last few minutes."""
    return _recent(now or time.time(), ("answer", "agent", "lens", "relate", "coach"))


def model_in_use(now=None):
    """Is anything using the plan right now: an answer, or a read-through or wiki build the owner started themselves?
    A night's slice never starts beside one (two read-throughs at once would read the same conversations twice)."""
    return _recent(now or time.time())


def _limit(e):
    try:
        from . import models
        return models.limit_text(e)
    except Exception:
        return "limit" in str(e).lower() and str(e)[:120]


def order(todo, now=None):
    """Unread conversations in the order they are read: touched in the last 90 days first, and within each half the
    ones the owner wrote most in."""
    now = now or time.time()
    floor = time.strftime("%Y-%m-%d", time.gmtime(now - RECENT))
    return sorted(todo, key=lambda u: (0 if (u[2][-1][0] or "")[:10] >= floor else 1, -u[1]["mine"]))


def _cost(job):
    from . import understand
    return 1 if job[0] == "many" else understand._size(job[1][2]) // understand.CHUNK + 2


def read_conversations(budget, now=None, busy=answering, pause_after=None, whole=None):
    """Read unread conversations until the budget is spent, or, with pause_after, until that many calls have gone in
    this sitting (the rest of the budget is for a later one). A conversation that alone needs more than a whole night
    (`whole`) is passed over: it waits for a run started by hand. Returns {"calls", "read", "stopped", "left",
    "too_big"}: calls is what the work was sized at; the ledger has what was really sent. stopped is "" (nothing left
    to read), "budget", "paused", or the reason."""
    from . import llm, understand
    os.makedirs(understand.CARDS, exist_ok=True)
    todo = order([(k, m, rows) for k, m, rows in understand.units() if not understand._current(k, m)], now)
    spent = read = big = 0
    stopped = ""
    for job in understand.jobs(todo):
        cost = _cost(job)
        if cost > (whole or budget):
            big += 1
            continue
        if spent + cost > budget:
            stopped = "budget"
            break
        if pause_after and spent >= pause_after:
            stopped = "paused"
            break
        if busy():
            stopped = "an answer is being written"
            break
        llm._tl.no_fallback = True          # a plan at its limit ends the night: no smaller model is tried in its place
        try:
            if job[0] == "one":
                read += 1 if understand._read_unit(*job[1]) else 0
            else:
                read += understand._read_many(job[1])
            spent += cost
        except Exception as e:
            spent += 1
            why = _limit(e)
            stopped = why or ("no model is signed in" if "signed in" in str(e) else "a call failed: " + str(e)[:80])
            break
        finally:
            llm._tl.no_fallback = False
    return {"calls": spent, "read": read, "stopped": stopped, "left": max(0, len(todo) - read), "too_big": big}


def write_pages(budget):
    """Wiki pages whose evidence changed, with what is left of the budget. The wiki decides what is stale and in what order."""
    from . import llm, wiki
    llm._tl.no_fallback = True
    try:
        got = wiki.build(max_calls=budget, say=lambda **kw: None) or {}
    except Exception as e:
        return {"calls": 0, "written": 0, "stopped": _limit(e) or "a call failed: " + str(e)[:80]}
    finally:
        llm._tl.no_fallback = False
    return {"calls": int(got.get("calls") or 0), "written": int(got.get("written") or 0), "stopped": str(got.get("stopped") or got.get("error") or "")}


def run(budget=None, now=None, busy=answering, night="", pause_after=None, whole=None):
    """Spend up to `budget` calls now. Adds to tonight's record and returns it."""
    now = now or time.time()
    budget = _settings()[0] if budget is None else budget
    d, at = _load(), _ledger_size()
    rec = d.get("tonight") if (d.get("tonight") or {}).get("night") == night and night else None
    if rec is None:
        if d.get("tonight"):
            d["last_night"] = d["tonight"]
        rec = {"night": night or time.strftime("%Y-%m-%d", time.localtime(now)), "calls": 0, "in": 0, "out": 0, "conversations": 0, "pages": 0, "stopped": "", "runs": 0}
    if budget <= 0:
        return rec
    a = read_conversations(budget, now, busy, pause_after, whole)
    left = budget - a["calls"]
    b = {"calls": 0, "written": 0, "stopped": ""}
    if left > 0 and a["stopped"] in ("", "budget") and not busy():      # nothing left to read, or nothing that fits: the pages
        b = write_pages(left if not pause_after else min(left, max(pause_after - a["calls"], 1)))
    calls, tin, tout, errors = _ledger_since(at)
    rec.update(calls=rec["calls"] + max(calls, 0), runs=rec["runs"] + 1, conversations=rec["conversations"] + a["read"], pages=rec["pages"] + b["written"],
               stopped=a["stopped"] if a["stopped"] not in ("", "budget", "paused") else b["stopped"], at=now, too_big=a["too_big"])
    rec["in"], rec["out"] = rec["in"] + tin, rec["out"] + tout
    rec["sized"] = rec.get("sized", 0) + a["calls"] + b["calls"]
    d["tonight"] = rec
    _save(d)
    return rec


def _allowed_quick():
    """allowed(), without asking which model is signed in (that starts a program): for every tick outside the window."""
    with _no_model_check():
        return allowed()


class _no_model_check:
    def __enter__(self):
        _skip_model[0] = True

    def __exit__(self, *a):
        _skip_model[0] = False


_skip_model = [False]


def allowed():
    """(may the nightly job run at all on this archive, why not). It spends the owner's plan with nobody watching, so it
    waits for a yes: it is on once the read-through has been run here at least once (the owner started that themselves and saw
    its cost), or once the owner set nightly_calls themselves. It never runs with nothing to read or no model signed in."""
    try:
        if not os.path.exists(paths.MESSAGES) or os.path.getsize(paths.MESSAGES) == 0:
            return False, "there is nothing in the archive to read yet"
    except OSError:
        return False, "there is nothing in the archive to read yet"
    try:
        from . import settings, understand
        with open(settings.FILE, encoding="utf-8") as f:
            chosen = "nightly_calls" in (json.load(f) or {})
    except (OSError, ValueError, TypeError):
        chosen = False
    try:
        from . import understand
        read = any(n.endswith(".json") for n in os.listdir(understand.CARDS))
    except OSError:
        read = False
    if not (read or chosen):
        return False, ("it starts after the first read-through, which only you start (python3 -m ctx understand --estimate, then understand). "
                       "to switch it on without that: python3 -m ctx settings --set nightly_calls=40")
    if _skip_model[0]:
        return True, ""
    try:
        from . import llm
        if llm.status().get("using") in ("none", "", None):
            return False, "no model is signed in on this mac"
    except Exception:
        return False, "no model is signed in on this mac"
    return True, ""


def due(now=None):
    """(calls that may be spent on this tick, why none). The owner's yes, the window, the budget, the power and the
    answers are all asked, the cheap ones first."""
    now = now or time.time()
    budget, hour = _settings()
    if budget <= 0:
        return 0, "switched off (nightly_calls is 0)"
    ok, why = _allowed_quick()
    if not ok:
        return 0, why
    night = night_of(now, hour)
    if not night:
        return 0, "it runs from %02d:00 for %d hours" % (hour, HOURS)
    rec = (_load().get("tonight") or {})
    used = rec.get("sized", 0) if rec.get("night") == night else 0
    if rec.get("night") == night and rec.get("stopped") and "answer" not in rec["stopped"]:
        return 0, "stopped for tonight: " + rec["stopped"]
    if used >= budget:
        return 0, "tonight's %d calls are spent" % budget
    ok, why = power()
    if not ok:
        return 0, why
    if model_in_use(now):
        return 0, "an answer is being written, or a read-through is already running"
    ok, why = allowed()
    if not ok:
        return 0, why
    return budget - used, ""


def tick(now=None):
    """Called by the scheduler on every tick: spend a slice of tonight's budget when everything allows it."""
    now = now or time.time()
    n, why = due(now)
    if not n:
        return {"ran": False, "why": why}
    rec = run(n, now, night=night_of(now, _settings()[1]), pause_after=SLICE, whole=_settings()[0])
    return {"ran": True, "calls": rec.get("calls"), "conversations": rec.get("conversations"), "pages": rec.get("pages"), "stopped": rec.get("stopped", "")}


def behind():
    """What is still to do, counted without a model call: {"conversations", "reading_calls", "wiki_pages", "wiki_calls"}."""
    out = {}
    try:                    # the same count `understand --estimate` and the app's read-through card show: one number everywhere
        from . import profile
        s = profile.estimate()
        out.update(conversations=s.get("unread", 0), reading_calls=s.get("reading_calls", 0))
    except Exception as e:
        out["conversations_error"] = str(e)[:80]
    try:
        from . import wiki
        e = wiki.build(dry=True, say=lambda **kw: None) or {}
        e = e.get("estimate", e)
        out.update(wiki_pages=sum((e.get("pages_to_write") or {}).values()), wiki_calls=e.get("calls_total", 0))
    except Exception as e:
        out["wiki_error"] = str(e)[:80]
    return out


def status(now=None, fresh=False):
    """For the app: what last night did, what tonight has done so far, what is still behind (as counted at the end of the
    last run, or now with fresh=True), and whether a run may start now."""
    now = now or time.time()
    d = _load()
    budget, hour = _settings()
    if fresh or "behind" not in d:
        d["behind"] = dict(behind(), at=now)
        if fresh or any(v for k, v in d["behind"].items() if k != "at"):      # a look at an empty archive writes nothing down
            _save(d)
    b = d["behind"]
    per = max(budget, 1)
    nights = None
    if budget > 0 and "reading_calls" in b:
        nights = -(-(int(b.get("reading_calls", 0)) + int(b.get("wiki_calls", 0))) // per)
    n, why = due(now)
    on, why_off = allowed()
    if not on:                  # the rule comes before the hour: "not tonight" must not hide "not until you say so"
        n, why = 0, why_off
    return {"nightly_calls": budget, "nightly_hour": hour, "on": on, "last_night": d.get("last_night") or {}, "tonight": d.get("tonight") or {}, "behind": b,
            "nights_to_catch_up": nights, "may_run_now": bool(n), "why_not": why}


def main(argv):
    if argv[:1] == ["--status"]:
        print(json.dumps(status(fresh="--fresh" in argv)))
    elif argv[:1] == ["--run"]:
        n = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else None
        rec = run(n)
        d = _load()
        d["behind"] = dict(behind(), at=time.time())
        _save(d)
        print(json.dumps(rec))
    else:
        raise SystemExit("usage: python3 -m ctx catchup --status [--fresh] | --run [N]")


if __name__ == "__main__":
    main(sys.argv[1:])
