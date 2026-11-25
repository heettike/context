"""Three speeds of refresh, so the archive stays current without hammering anything.

  fast    every 15 minutes   sources that are files on this Mac
  daily   once a day         sources read through a signed-in session (mail, slack, drive, calendar, telegram, bookmarks)
  weekly  once a week        account exports that have to be requested (monthly where the site asks for a password)

`python3 -m ctx tick` does whatever is due and nothing else. The app calls it every 15 minutes; `ctx watch` loops it.
"""
import json, os, time
from . import collect, paths

FAST = ["whatsapp", "imessage", "claude_code", "codex", "cursor", "grok_bot", "grok_bot_prompts", "claude_history",
        "browser_history", "safari_history", "journal", "obsidian", "apple_notes", "contacts", "reminders", "calls", "voice_memos", "media_images", "media_audio", "media_files", "media_video"]
DAILY = ["email", "slack", "gdrive", "calendar", "telegram", "x_bookmarks", "x_web_likes", "x_web_posts", "x_web_replies", "instagram_saved_web", "chatgpt_export", "chatgpt_export_prompts"]
FROM_EXPORT = {"x": ["x_dms", "x_archive"], "google": ["gmail_takeout", "google_takeout"], "instagram": ["instagram", "instagram_saved", "instagram_likes"],
               "linkedin": ["linkedin", "linkedin_connections"] + ["linkedin_" + x for x in ("posts", "comments", "articles", "invitations", "recommendations", "saved", "likes", "searches", "profile")], "chatgpt": ["chatgpt_export", "chatgpt_export_prompts"], "notion": ["notion"]}
EVERY = {"fast": 15 * 60, "daily": 24 * 3600, "weekly": 7 * 86400, "monthly": 30 * 86400}
STATE = os.path.join(paths.HOME, "schedule.json")
LOCK = os.path.join(paths.HOME, "tick.lock")


QUIET_AFTER = 7     # daily reads in a row that were skipped for one and the same reason
QUIET_NOTE = "not in use: nothing is needed. it is tried once a week"


def quiet_now(st, name, now, force=()):
    """A signed-in source the owner plainly does not use (it has rows from long ago, and every daily read for a week was
    skipped for the same reason) is tried once a week, not daily. Returns the result to record without trying it, or None
    when it should be tried now."""
    q = (st.get("quiet") or {}).get(name) or {}
    if q.get("n", 0) >= QUIET_AFTER and now - q.get("tried", 0) < EVERY["weekly"] and name not in force:
        return {"rows": q.get("rows", 0), "new": 0, "state": "skipped", "detail": QUIET_NOTE}
    return None


def quiet_note(st, name, result, now):
    """Count this read towards going quiet, and return the result to record. A read that worked, failed, found no saved
    rows or stopped for a new reason starts the count again. Only one read a day counts."""
    quiet = st.setdefault("quiet", {})
    state, detail = result.get("state"), str(result.get("detail") or "")
    if state == "skipped" and detail == collect.BUSY:       # another read had it: says nothing about the source
        return result
    if state not in ("skipped", "needs_you") or not result.get("rows"):
        quiet.pop(name, None)
        return result
    q = quiet.get(name) or {}
    if q.get("why") == [state, detail]:
        n, counted = q.get("n", 1), q.get("counted", 0)
        if now - counted >= 20 * 3600:
            n, counted = n + 1, now
    else:
        n, counted = 1, now
    quiet[name] = {"why": [state, detail], "n": n, "counted": counted, "tried": now, "rows": result["rows"]}
    if n >= QUIET_AFTER:
        return dict(result, state="skipped", detail=QUIET_NOTE)
    return result


def _canvas(tier):
    """The owner's own sources (ctx/canvas.py) that this tier reads: folders, files and notes fast; websites and feeds daily."""
    try:
        from . import canvas
        collect.load_canvas()
        return canvas.due(tier)
    except Exception:
        return []


def _load():
    try:
        return paths.read_json(STATE)
    except (OSError, ValueError):
        return {}


def _save(st):
    with open(STATE + ".new", "w") as f:
        json.dump(st, f, indent=1)
    os.replace(STATE + ".new", STATE)


def _locked():
    """One tick at a time. A lock older than two hours belongs to a run that died."""
    try:
        pid, at = paths.read_text(LOCK).split()
        os.kill(int(pid), 0)
        return time.time() - float(at) < 7200
    except (OSError, ValueError):
        return False


def _settings():
    try:
        from . import settings
        return settings.load()
    except Exception:
        return {"fast_minutes": 15, "daily_hour": "any", "weekly_day": "any", "read_through": "on", "reread_weekly": "off"}


def due_in(tier, now, last, cfg):
    """(is this tier due, seconds until it next is) under the owner's settings: minutes between fast reads, and an
    hour of the day for the daily one (the read happens at the first tick after that hour, once a day)."""
    if tier == "fast":
        every = cfg["fast_minutes"] * 60
    elif cfg["daily_hour"] == "any":
        every = EVERY["daily"]
    else:
        t = time.localtime(now)
        slot = time.mktime(t[:3] + (cfg["daily_hour"], 0, 0, 0, 0, -1))
        if now < slot:
            slot -= 86400                       # today's hour has not come: the slot in force is yesterday's
        return last < slot, 0 if last < slot else int(slot + 86400 - now)
    return now - last >= every, max(0, int(every - (now - last)))


def day_ok(now, cfg):
    return cfg["weekly_day"] == "any" or ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][time.localtime(now).tm_wday] == cfg["weekly_day"]


def _when(iso):
    """Seconds since 1970 for the time a request was filed (as request.py writes it), 0 when there is none."""
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(iso)).timestamp() if iso else 0
    except ValueError:
        return 0


def plan(now=None):
    """What is due, and when each tier next runs. Shown in the app."""
    now, st, cfg = now or time.time(), _load(), _settings()
    out = {}
    for tier in ("fast", "daily"):
        last = st.get(tier, 0)
        due, wait = due_in(tier, now, last, cfg)
        out[tier] = {"last": last, "due": due, "next_in": wait,
                     "sources": (FAST if tier == "fast" else DAILY) + _canvas(tier), "results": st.get(tier + "_results", {})}
    weekly = {}
    try:
        from . import request
        from . import driver
        cycles = driver.cycles()
        for s in request.listing()["services"]:
            # one clock: how often an export comes round is the driver's (ctx/driver.py), set by the owner with
            # `driver --every <id>=weekly|monthly|off` or the app's exports-every. this only shows it.
            every = driver.every(s["id"])
            last = cycles.get(s["id"]) or st.get("exports", {}).get(s["id"]) or _when(s.get("requested_at"))    # a request made before the clock was kept still counts
            want = s["state"] in ("requested", "arrived") and every != "off"          # only what the owner said yes to
            span = EVERY.get(every, EVERY["monthly"])
            weekly[s["id"]] = {"state": s["state"], "every": every, "last": last, "due": bool(want and last > 0 and now - last >= span),
                               "next_in": max(0, int(span - (now - last))) if want and last else None}
    except Exception as e:
        weekly = {"error": str(e)[:120]}
    out["weekly"] = weekly
    last = st.get("read_through", 0)
    out["read_through"] = {"last": last, "enabled": cfg["read_through"] == "on" and cfg["reread_weekly"] == "on",
                           "due": cfg["read_through"] == "on" and cfg["reread_weekly"] == "on" and now - last >= EVERY["weekly"] and day_ok(now, cfg)}
    return out


def tick(force=()):
    """Run what is due. `force` may name tiers to run now: "fast", "daily", "weekly"."""
    if _locked():
        return {"skipped": "another refresh is running"}
    paths.write_text(LOCK, f"{os.getpid()} {time.time()}")
    done, st, now = {}, _load(), time.time()
    try:
        # archives that landed in Downloads are picked up on every tick
        from . import exports
        new = exports.ingest()
        if new:
            names = {n for kind, _ in new for n in FROM_EXPORT.get(kind, [])}
            collect.run(only=names)
            done["ingested"] = [k for k, _ in new]
        try:                        # exports on a cadence, with the owner asked for one step at most: ctx/driver.py
            from . import driver
            moved = driver.tick(now, arrived=[k for k, _ in new])
            if moved:
                done["exports"] = moved
            if new:                 # a new archive is findable at once, not at the next daily read
                from . import semantic
                semantic.build(say=lambda **kw: None)
        except Exception as e:
            done["exports"] = "failed: " + str(e)[:80]
        p = plan(now)
        fresh = {}

        def read(names):                # collect, and keep how many rows each source gained
            after = collect.run(only=set(names)) or {}
            for n in names:
                if isinstance(after.get(n), dict) and after[n].get("new"):
                    fresh[n] = after[n]["new"]
        if p["fast"]["due"] or "fast" in force:
            fast = FAST + _canvas("fast")
            read(fast)
            st["fast"] = time.time()
            done["fast"] = len(fast)
        if p["daily"]["due"] or "daily" in force:
            results = {}
            try:
                from . import signed_in
            except ImportError:
                signed_in = None
            for name in ("slack", "gdrive", "calendar", "x_bookmarks", "x_likes", "x_posts", "x_replies", "instagram_saved", "chatgpt"):
                fn = getattr(signed_in, name, None) if signed_in else None
                if name == "calendar" and time.time() - st.get("calendar", 0) < EVERY["weekly"] and "calendar" not in force:
                    results[name] = {"state": "skipped", "detail": "read weekly: the calendar app takes ten minutes to answer"}
                    continue
                if name == "calendar":
                    st["calendar"] = time.time()
                if not fn:
                    results[name] = {"state": "skipped", "detail": "no refresher for this source yet"}
                    continue
                resting = quiet_now(st, name, time.time(), force)
                if resting:
                    results[name] = resting
                    continue
                try:
                    results[name] = fn()
                except Exception as e:
                    results[name] = {"state": "failed", "detail": f"{type(e).__name__}: {e}"[:160]}
                results[name] = quiet_note(st, name, results[name], time.time())
            try:
                results["telegram"] = collect.telegram_new()
            except Exception as e:
                results["telegram"] = {"state": "failed", "detail": f"{type(e).__name__}: {e}"[:160]}
            read(DAILY + _canvas("daily"))
            st["daily"], st["daily_results"] = time.time(), results
            from . import settings
            try:                        # which models the plans can run, and how fast, is measured once a day: a tiny call each. the owner can switch it off
                if settings.spend("model_check"):
                    from . import models
                    models.refresh()
                else:
                    done["models"] = "switched off"
            except Exception:
                pass
            try:                        # the morning card is made here, once a day, so the app reads it at once. the owner can switch it off
                if settings.spend("morning_card"):
                    from . import today
                    done["today"] = bool(today.build().get("card"))
                else:
                    done["today"] = "switched off"
            except Exception as e:
                done["today"] = f"failed: {type(e).__name__}"
            done["daily"] = {k: v.get("state") for k, v in results.items()}
            try:        # keep the meaning index in step with what was just read; a failure here never fails the sync
                from . import semantic
                done["index"] = semantic.build(say=lambda **kw: None).get("pending")
            except Exception as e:
                done["index"] = "failed: " + str(e)[:80]
        due = []        # exports that come due are the driver's (above); forcing the weekly tier still asks for every one by hand
        if "weekly" in force:
            due = [sid for sid, w in p["weekly"].items() if isinstance(w, dict) and w.get("state") in ("requested", "arrived")]
        if due:
            from . import request
            asked = {}
            quiet = {s["id"] for s in request.listing()["services"] if s.get("asks_for") in ("nothing", "", None)}
            for sid in due:
                if sid not in quiet:        # it would open a browser tab and wait for a password or a code: only the owner starts those
                    asked[sid] = "waits for you"
                    continue
                try:
                    request._save(sid, "idle")                      # a new request, not the old one
                    asked[sid] = request.request(sid).get("state")
                except Exception as e:
                    asked[sid] = f"failed: {type(e).__name__}"
                st.setdefault("exports", {})[sid] = time.time()
            done["weekly"] = asked
        if p["read_through"]["due"] or ("read_through" in force and _settings()["read_through"] == "on"):
            st["read_through"] = time.time()                        # the weekly re-read the owner switched on: only what changed, on their plan
            _save(st)
            try:
                from . import understand
                done["read_through"] = understand.run()
            except Exception as e:
                done["read_through"] = f"failed: {type(e).__name__}"
        try:                        # a little of the read-through and the wiki each night, on the owner's plan: ctx/catchup.py
            from . import catchup
            night = catchup.tick(time.time())
            if night.get("ran"):
                done["catchup"] = night
        except Exception as e:
            done["catchup"] = "failed: " + str(e)[:80]
        _save(st)
        if done:
            done["new"], done["new_by_source"] = sum(fresh.values()), fresh
            try:                        # the archive changed: bring the lookup indexes up to date so a peek stays instant
                from . import peek, wordindex
                peek.warm()
                wordindex.warm()
            except Exception:
                pass
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass
    return done or {"nothing_due": True}


def note_request(sid, at=None):
    """Remember when an export was asked for, so the weekly clock starts. Called by request.request when a request is filed."""
    st = _load()
    st.setdefault("exports", {})[sid] = at or time.time()
    _save(st)
