"""The settings page, as data. `python3 -m ctx settings` prints one JSON object the app draws; nothing here calls a model.

  python3 -m ctx settings                     everything the page shows
  python3 -m ctx settings --fast              the same without the slow read-through count
  python3 -m ctx settings --set key=value     change one of the few real settings (kept in CTX_HOME/settings.json)

Settings: fast_minutes (5-240), daily_hour (0-23 or any), weekly_day (mon..sun or any), read_through (on|off),
reread_weekly (on|off), backend (claude|codex|auto), remote_tools (comma list), remote_autostart (on|off),
morning_card (on|off), model_check (on|off).
schedule.py, llm.py and remote.py read them through load(); the two background model calls ask spend().
"""
import json, os, time
from . import paths

FILE = os.path.join(paths.HOME, "settings.json")
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
REMOTE_TOOLS = ["about_me", "page", "person", "search", "facts", "open_loops", "sources"]       # every tool there is; the default leaves page out
DEFAULTS = {"fast_minutes": 15, "daily_hour": "any", "weekly_day": "any", "read_through": "on", "reread_weekly": "off", "backend": "auto",
            "remote_tools": ["about_me", "search", "person", "facts", "open_loops", "sources"], "remote_autostart": "off", "embedder": "apple",
            "preset": "balanced", "models": {}, "fallback_when_limited": "on", "links_from_others": "off", "nightly_calls": 40, "nightly_hour": 2,
            "morning_card": "on", "model_check": "on"}
APP = os.path.join(paths.HOME, "app.json")          # what the app remembers between runs; its switches for the same two calls are read too
APP_NAMES = {"morning_card": "morningCard", "model_check": "modelCheck"}
ABOUT = {"fast_minutes": "minutes between reads of the sources that are files on this mac (5 to 240)",
         "daily_hour": "hour of the day (0 to 23) for the daily read of signed-in sources, or any",
         "weekly_day": "day of the week (mon..sun) for export requests and the weekly re-read, or any",
         "read_through": "whether the engine may run the read-through on its own (on, off)",
         "reread_weekly": "re-read what changed once a week, on your plan (on, off)",
         "backend": "which signed-in cli model calls use (claude, codex, auto)",
         "remote_tools": "the tools chatgpt and claude.ai may call when the remote endpoint is on, comma separated",
         "preset": "which model does which job: balanced (recommended), best, or lean. see: python3 -m ctx models",
         "models": "a model of your own for one job, set with model.routine=<id> (jobs: routine, analysis, first_parse, tools)",
         "links_from_others": "whether an answer may link to an address that only someone else's message holds; off shows its site name as plain words (on, off)",
         "fallback_when_limited": "when your plan hits its limit, let everyday answers use the lean model until it lifts (on, off)",
         "embedder": "what turns text into vectors for search by meaning: apple, ollama:<model already pulled>, or file:<program>. then run: python3 -m ctx index",
         "remote_autostart": "whether the app may start the remote endpoint again after a restart (on, off). the engine never does",
         "nightly_calls": "model calls the nightly catch-up may spend on unread conversations and stale wiki pages (0 to 400; 0 switches it off)",
         "nightly_hour": "hour of the night (0 to 23) from which the catch-up may run, for five hours",
         "morning_card": "whether the daily read may make the morning card, one small model call a day (on, off)",
         "model_check": "whether each model your plans can run is tried once a day with a tiny call, to know which work and how fast (on, off)"}
OPTIONAL_KEYS = ["TELEGRAM_API_ID", "TELEGRAM_API_HASH", "ANTHROPIC_API_KEY", "CTX_MY_EMAILS", "CTX_X_HANDLE", "CTX_MODEL",
                 "CTX_FAST_MODEL", "CTX_CHEAP_MODEL", "CTX_STRONG_MODEL", "CTX_CODEX_MODEL", "CTX_MODEL_TIMEOUT"]


def check(key, value):
    """(clean value, "") or (None, why not). Values arrive as text from the command line."""
    v = str(value).strip().lower()
    if key == "fast_minutes":
        return (int(v), "") if v.isdigit() and 5 <= int(v) <= 240 else (None, "fast_minutes must be a whole number from 5 to 240")
    if key == "daily_hour":
        return (v if v == "any" else int(v), "") if v == "any" or (v.isdigit() and int(v) <= 23) else (None, "daily_hour must be 0 to 23, or any")
    if key == "weekly_day":
        full = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        return (v[:3], "") if v == "any" or v in DAYS or v in full else (None, "weekly_day must be one of mon tue wed thu fri sat sun, or any")
    if key == "remote_tools":
        names = [x.strip().lower() for x in (value if isinstance(value, list) else str(value).split(",")) if str(x).strip()]
        bad = [n for n in names if n not in REMOTE_TOOLS]
        return (None, "remote_tools must be some of: " + ", ".join(REMOTE_TOOLS)) if bad or not names else (list(dict.fromkeys(names)), "")
    if key == "preset":
        return (v, "") if v in ("balanced", "best", "lean") else (None, "preset must be balanced, best or lean")
    if key == "models":                 # as stored: {job: model id}. set one with model.<job>=<id>
        ok = isinstance(value, dict) and all(k in ("routine", "analysis", "first_parse", "tools") and isinstance(x, str) and x for k, x in value.items())
        return (dict(value), "") if ok else (None, "models must be set one at a time: model.routine=<id>")
    if key in ("read_through", "reread_weekly", "remote_autostart", "fallback_when_limited", "links_from_others", "morning_card", "model_check"):
        return ("on" if v in ("on", "true", "yes", "1") else "off", "") if v in ("on", "off", "true", "false", "yes", "no", "1", "0") else (None, key + " must be on or off")
    if key == "embedder":
        from . import semantic
        return semantic.check_embedder(value)
    if key == "backend":
        return (v, "") if v in ("claude", "codex", "auto") else (None, "backend must be claude, codex or auto")
    if key == "nightly_calls":
        return (int(v), "") if v.isdigit() and int(v) <= 400 else (None, "nightly_calls must be a whole number from 0 to 400 (0 switches the catch-up off)")
    if key == "nightly_hour":
        return (int(v), "") if v.isdigit() and int(v) <= 23 else (None, "nightly_hour must be 0 to 23")
    return None, "no such setting. settings: " + ", ".join(DEFAULTS)


def load():
    """The settings in force: the defaults, then whatever valid values the file holds. Never raises."""
    out = dict(DEFAULTS)
    try:
        with open(FILE) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return out
    for k, v in saved.items() if isinstance(saved, dict) else []:
        if k in DEFAULTS:
            clean, why = check(k, v)
            if not why:
                out[k] = clean
    return out


def spend(name):
    """May the engine make this background model call on its own: "morning_card" or "model_check"? Only once the owner
    has finished setting up the app (app.json: onboarded is true): before that nothing is spent unasked, at launch or on
    the daily read, whatever the switches say. A missing or unreadable app.json is setup not done. After it, off when
    the setting is off, or when the app's own switch for it (app.json: morningCard, modelCheck) is false; said nowhere,
    it is on. A call the owner asks for by hand is not asked about here."""
    if load().get(name) == "off":
        return False
    try:
        with open(APP) as f:
            app = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(app, dict) or app.get("onboarded") is not True:
        return False
    return app.get(APP_NAMES.get(name, name)) is not False


def set_(pair):
    """`key=value` from the command line. Returns {"ok", "error", "settings"}."""
    key, sep, value = str(pair).partition("=")
    key = key.strip().lower()
    now = load()
    if sep and key.startswith("model."):        # one job's model: model.routine=<id>; an empty value or "preset" hands it back to the preset
        job, want = key[6:], value.strip()
        if job not in ("routine", "analysis", "first_parse", "tools"):
            return {"ok": False, "error": "jobs are routine, analysis, first_parse and tools: model.routine=<id>", "settings": now}
        from . import models
        can = [m for m in models.rows(models.known_status()) if m.get("ok")]
        if want and want != "preset" and can and want not in [m["id"] for m in can] + [m.get("ask") for m in can]:
            return {"ok": False, "error": "that is not a model your plans can run. see: python3 -m ctx models", "settings": now}
        key, clean, why = "models", {k: v for k, v in dict(now.get("models") or {}, **{job: want}).items() if v and v != "preset"}, ""
    else:
        clean, why = check(key, value) if sep else (None, "write it as key=value")
    if why:
        return {"ok": False, "error": why, "settings": now}
    now[key] = clean
    tmp = FILE + ".new"
    with open(tmp, "w") as f:
        json.dump(now, f, indent=1)
    os.replace(tmp, FILE)
    if key == "backend":            # the remembered choice of plan would otherwise hold for ten more minutes
        try:
            os.remove(os.path.join(paths.HOME, "model.json"))
        except OSError:
            pass
    return {"ok": True, "error": "", "settings": now}


def _lines(path):
    n = 0
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                n += block.count(b"\n")
    except OSError:
        return None
    return n


def archive():
    """The folder, its size on disk, rows per file and when anything was last collected."""
    home = os.path.expanduser("~")
    size = 0
    for root, _, files in os.walk(paths.HOME):
        for f in files:
            try:
                size += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    files = {"messages": paths.MESSAGES, "docs": paths.DOCS, "prompts": paths.PROMPTS, "sessions": paths.SESSIONS, "mail_index": paths.MAIL_INDEX}
    rows = {k: _lines(p) for k, p in files.items()}
    last = max([os.path.getmtime(p) for p in files.values() if os.path.exists(p)] or [0])
    return {"folder": "~" + paths.HOME[len(home):] if paths.HOME.startswith(home) else paths.HOME, "bytes": size,
            "rows": {k: v for k, v in rows.items() if v is not None}, "last_collect": int(last)}


def usage(now=None):
    """Model calls and tokens from the ledger, today and over seven days, by what they were for. Rows written before
    the ledger kept the time of each call are counted under "undated"."""
    now = now or time.time()
    day = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
    spans = {"today": {}, "week": {}, "undated": {}}
    usd, failed, first = 0.0, 0, None
    try:
        with open(paths.LEDGER) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if "error" in r:
                    failed += 1
                    continue
                at, tag = r.get("at"), str(r.get("tag") or "other").split(":")[0]
                first = at if at and (first is None or at < first) else first
                where = ["undated"] if not at else (["today"] if at >= day else []) + (["week"] if at >= now - 7 * 86400 else [])
                for w in where:
                    t = spans[w].setdefault(tag, {"calls": 0, "tokens_in": 0, "tokens_out": 0})
                    t["calls"] += 1
                    t["tokens_in"] += int(r.get("in") or 0)
                    t["tokens_out"] += int(r.get("out") or 0)
                usd += float(r.get("usd") or 0)
    except OSError:
        pass
    # calls made before the ledger kept times cannot be placed on a day: say from when the per-day counts are whole
    return dict(spans, failed=failed, usd=round(usd, 2), since=time.strftime("%Y-%m-%d", time.localtime(first)) if first else None,
                cost="$0 extra: calls run on the plan you already pay for" if usd == 0 else "some calls used an api key, billed per token")


def keys(env=None):
    """Which optional keys are set in .env, by name only. Never a value, never a length."""
    from . import paths
    have = set()
    for one in ([env] if env else paths.env_files()):
        try:
            with open(one, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        k = k.replace("export ", "").strip()
                        if v.strip().strip("\"'") and k.replace("_", "").isalnum():
                            have.add(k)
        except OSError:
            pass
    return {"file": ".env in the engine folder, or in the archive folder", "present": sorted(have), "not_set": [k for k in OPTIONAL_KEYS if k not in have]}


def _search():
    """Search by meaning: which embedder is in use, how good it is, and how to get a better one."""
    from . import semantic
    return semantic.embedder_report()


def report(fast=False):
    """Everything the settings page shows. Each part is gathered on its own: one that fails says so and the rest still come."""
    from concurrent.futures import ThreadPoolExecutor
    from . import llm, schedule, understand, mcp, models
    st = load()

    def plan():
        s = llm.status()
        return {"using": s["using"], "plan": s["plan"], "signed_in": s["using"] != "none", "fix": s["fix"],
                "claude": {k: s["claude"][k] for k in ("installed", "signed_in")}, "codex": {k: s["codex"][k] for k in ("installed", "signed_in")},
                "api_key": s["api_key"], "backend_setting": st["backend"], "models": {"fast": llm.FAST, "cheap": llm.CHEAP, "strong": llm.STRONG}}

    def sync():
        p = schedule.plan()
        last = p.get("fast", {}).get("last", 0)
        p["watching"] = bool(last) and time.time() - last < 2.5 * st["fast_minutes"] * 60      # something is ticking: the app or `ctx watch`
        p["settings"] = {k: st[k] for k in ("fast_minutes", "daily_hour", "weekly_day")}
        return p

    def read():
        cards = os.path.join(understand.MEM, "cards")
        light = {"cards": len(os.listdir(cards)) if os.path.isdir(cards) else 0, "core": os.path.exists(os.path.join(understand.MEM, "core.md")),
                 "enabled": st["read_through"] == "on", "reread_weekly": st["reread_weekly"] == "on"}
        return light if fast else dict(understand.status(), **light)
    from . import remote
    parts = {"plan": plan, "sync": sync, "mcp": mcp.status, "archive": archive, "read_through": read, "usage": usage, "keys": keys, "remote": remote.status, "search": _search,
             "models": models.report}
    out = {}
    with ThreadPoolExecutor(len(parts)) as ex:
        futs = {k: ex.submit(fn) for k, fn in parts.items()}
        for k, f in futs.items():
            try:
                out[k] = f.result()
            except Exception as e:
                out[k] = {"error": "could not read this part (%s)" % type(e).__name__}
    out["settings"] = {"values": st, "about": ABOUT, "file": "settings.json in the archive folder"}
    out["permissions"] = {"note": "shown by the app: the engine cannot see what macos has granted the app"}
    return out


def main(args):
    if "--set" in args:
        pairs = args[args.index("--set") + 1:]
        res = {"ok": False, "error": "write it as: settings --set key=value", "settings": load()}
        for p in pairs:
            res = set_(p)
            if not res["ok"]:
                break
        print(json.dumps(res))
        return 0 if res["ok"] else 1
    print(json.dumps(report(fast="--fast" in args), ensure_ascii=False))
    return 0
