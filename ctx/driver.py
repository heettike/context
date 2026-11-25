"""Exports with the owner in the passenger seat.

Some of the archive has one complete copy only: the export a service makes when asked (x chats and old posts, google
takeout, the complete linkedin archive, instagram messages and likes, notion). An export goes stale from the day it is
made. This keeps each one fresh on a cadence, doing every step that needs no secret and asking the owner for exactly
one thing when a site wants a password or a code.

One service, one cycle:
  due        its cadence has passed since the last cycle began (weekly or monthly; `off` stops it). only services the
             owner has asked for at least once are ever driven, and never one the owner declined
  ask        the export page is opened and "request" pressed (ctx/request.py, which also stops at any prompt)
  waiting    the site wants a password, a code or a sign-in: ONE reminder says that one step, with the tab ready
  asked      the request is in. after the time the service usually takes, its own downloads page is opened in a
             background tab (the engine never reads mail for a link); if the download needs the owner and no reminder
             was used this cycle, one says so
  in         the zip reached Downloads: ingest unpacked it, its sources were collected, the index refreshed, and one
             line says so. the cycle is over

Never more than one reminder for a service in a cycle. State is CTX_HOME/driver.json; a reminder is also written as
that service's `needs_you` state in requests.json, which the app's list of things waiting on the owner already shows.

    python3 -m ctx driver --status            every service: cadence, where it stands, when it is next due, open reminders
    python3 -m ctx driver --every x=weekly    change a cadence: weekly | monthly | off
    python3 -m ctx driver --dry [x]           look at each real export page as far as the request button and press
                                              nothing: is the owner signed in, is one pending, is the button there. it opens
                                              a tab, so it is for when the owner is at the mac
"""
import json, os, subprocess, sys, time
from datetime import datetime, timezone
from . import paths

STATE = os.path.join(paths.HOME, "driver.json")
EVERY = {"weekly": 7 * 86400, "monthly": 30 * 86400}
# how often, and why: how fast it goes stale against how heavy the export is and how much the owner must do
CADENCE = {"x": "monthly",          # chats and old posts only come this way; likes, posts, replies, bookmarks are read daily. password each time, a day's wait
           "google": "monthly",     # youtube, keep and mail in bulk: gigabytes, hours to build
           "instagram": "monthly",  # messages and likes only come this way (the site refuses them to the extension). password each time
           "linkedin": "monthly",   # the complete archive takes a day; little changes in a week
           "chatgpt": "monthly",    # conversations are read daily through the extension; the export is the full copy. a code each time
           "notion": "monthly"}
WAIT = {"minutes": 20 * 60, "hours": 4 * 3600, "a day": 22 * 3600}     # how long after asking before the downloads page is worth opening
DOWNLOADS = {"x": "https://x.com/settings/download_your_data", "google": "https://takeout.google.com/manage",
             "instagram": "https://accountscenter.instagram.com/info_and_permissions/dyi/", "linkedin": "https://www.linkedin.com/mypreferences/d/download-my-data",
             "chatgpt": "", "notion": ""}          # "": the site mails a link and has no page of its own for it
SECRET = {"password": "your password", "code": "the code it sent you", "login": "you to sign in"}
RETRY, TRIES, REOPEN = 86400, 3, 12 * 3600


class Site:
    """The real services, through ctx/request.py. Tests hand tick() a made-up one with the same five functions."""

    def known(self):
        from . import request
        return [(s["id"], s["name"], s.get("arrives", "hours"), s.get("asks_for", "nothing")) for s in request.SERVICES]

    def state(self, sid):
        from . import request
        return request.service(sid)

    def ask(self, sid):
        from . import request
        request.request(sid, again=True)        # a new request, whatever archive is already here
        return request._load().get(sid) or {}   # as saved: the listing would call an older archive "arrived"

    def remind(self, sid, text):
        from . import request
        request._save(sid, "needs_you", text)

    def arrived(self, sid, since):
        from . import request
        return bool(request._arrived(sid, datetime.fromtimestamp(since, timezone.utc).isoformat(timespec="seconds")))

    def open_page(self, url):
        """Open a page in the owner's browser without bringing it to the front."""
        from . import request
        b = request.browser()
        if not b.get("name"):
            return False
        try:
            return subprocess.run(["open", "-g", "-a", b["name"], url], capture_output=True, timeout=20).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False


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


def every(sid, value=None):
    """A service's cadence. With a value (weekly, monthly, off) it is set."""
    d = _load()
    if value is not None:
        if value not in ("weekly", "monthly", "off"):
            raise ValueError("a cadence is weekly, monthly or off")
        d.setdefault("services", {}).setdefault(sid, {})["every"] = value
        _save(d)
    return (d.get("services", {}).get(sid) or {}).get("every") or CADENCE.get(sid, "monthly")


def cycles():
    """{service: when its current cycle began} for the services the driver has begun to drive."""
    return {sid: st["cycle"] for sid, st in (_load().get("services") or {}).items() if isinstance(st, dict) and st.get("cycle")}


def _remind(d, st, sid, name, text, url, now, site):
    """The one reminder of this cycle. False when one was already given."""
    if st.get("reminded") == st.get("cycle"):
        return False
    st["reminded"] = st["cycle"]
    row = {"id": "driver:%s:%d" % (sid, int(st["cycle"])), "service": sid, "name": name, "text": text, "url": url, "at": now, "open": True}
    d["reminders"] = ([r for r in d.get("reminders", []) if r.get("service") != sid] + [row])[-30:]
    site.remind(sid, text)
    return True


def tick(now=None, arrived=(), site=None):
    """Move every service one step. `arrived` are the kinds ingest unpacked on this tick. Returns what happened:
    {"asked": [...], "reminded": [...], "opened": [...], "in": [...]}; empty when nothing did."""
    now, site, d = now or time.time(), site or Site(), _load()
    did = {"asked": [], "reminded": [], "opened": [], "in": []}
    sv = d.setdefault("services", {})
    for sid, name, arrives, asks in site.known():
        st = sv.setdefault(sid, {})
        cadence = st.get("every") or CADENCE.get(sid, "monthly")
        seen = site.state(sid)
        low = name.lower()
        if seen.get("state") == "declined":         # the owner said no: nothing is asked, opened or said
            st.update(stage="idle", reminded=st.get("reminded"))
            continue
        stage = st.get("stage", "idle")
        if stage != "idle" and (sid in arrived or site.arrived(sid, st.get("cycle", now))):
            st.update(stage="idle", last_done=now, line="your %s export is in" % low)
            for r in d.get("reminders", []):
                if r.get("service") == sid:
                    r["open"] = False
            d["done"] = (d.get("done", []) + [{"service": sid, "text": st["line"], "at": now}])[-30:]
            did["in"].append(sid)
            continue
        if cadence == "off":
            continue
        if stage == "idle":
            if "cycle" not in st:                   # first sight: the clock starts at the last export the owner asked for themselves
                asked_before = seen.get("state") in ("requested", "arrived", "needs_you")
                if not asked_before:
                    continue                        # never asked for: only the owner starts a service's first export
                st["cycle"] = _when(seen.get("requested_at")) or _first_asked(sid) or now
                if seen.get("state") == "requested":
                    st.update(stage="asked", asked_at=st["cycle"])
                continue
            if now - st["cycle"] < EVERY[cadence]:
                continue
            st.update(cycle=now, stage="start", tries=0, opened=0, opens=0, tried_at=0)
            stage = "start"
        if stage == "start":
            if now - st.get("tried_at", 0) < RETRY and st.get("tries", 0):
                continue
            st["tried_at"], st["tries"] = now, st.get("tries", 0) + 1
            try:
                got = site.ask(sid) or {}
            except Exception as e:
                got = {"state": "failed", "detail": str(e)[:120]}
            if got.get("state") in ("requested", "arrived"):
                st.update(stage="asked", asked_at=now)
                did["asked"].append(sid)
            elif got.get("state") == "needs_you":
                what = next((v for k, v in SECRET.items() if k in str(got.get("detail", "")).lower() or (k == "login" and "sign in" in str(got.get("detail", "")).lower())), SECRET.get(asks, "you"))
                text = "%s wants %s to make your export: open the %s tab that is waiting, do that one step, and context does the rest" % (low, what, low)
                st.update(stage="waiting", waiting_since=now)
                if _remind(d, st, sid, name, text, seen.get("url") or DOWNLOADS.get(sid, ""), now, site):
                    did["reminded"].append(sid)
            elif st["tries"] >= TRIES:              # the page changed, or the browser cannot be driven: say so once and wait
                text = "context could not press the button on %s's export page: open it, ask for your export, and context does the rest" % low
                st.update(stage="waiting", waiting_since=now)
                if _remind(d, st, sid, name, text, DOWNLOADS.get(sid, ""), now, site):
                    did["reminded"].append(sid)
            continue
        # asked, or waiting on the owner: when the export should be ready, open the service's own downloads page
        since = st.get("asked_at") or st.get("waiting_since") or st.get("cycle", now)
        url = DOWNLOADS.get(sid, "")
        if url and now - since >= WAIT.get(arrives, WAIT["hours"]) and st.get("opens", 0) < 3 and now - st.get("opened", 0) >= REOPEN:
            if site.open_page(url):
                st["opened"], st["opens"] = now, st.get("opens", 0) + 1
                did["opened"].append(sid)
                text = "your %s export should be ready: the %s tab context opened has the download. press it%s and context does the rest" % (
                    low, low, " (it asks for %s first)" % SECRET[asks] if asks in SECRET else "")
                if _remind(d, st, sid, name, text, url, now, site):
                    did["reminded"].append(sid)
    _save(d)
    return {k: v for k, v in did.items() if v}


def _first_asked(sid):
    """When the scheduler noted this service's last request (schedule.json), for a request that left no time of its own."""
    try:
        with open(os.path.join(paths.HOME, "schedule.json"), encoding="utf-8") as f:
            return float((json.load(f).get("exports") or {}).get(sid) or 0)
    except (OSError, ValueError, TypeError):
        return 0


def _when(iso):
    try:
        return datetime.fromisoformat(str(iso)).timestamp() if iso else 0
    except ValueError:
        return 0


def status(now=None, site=None):
    """What the app shows: each service's cadence and stage, when it is next due, the reminders still open (at most one a
    service) and the last lines said."""
    now, site, d = now or time.time(), site or Site(), _load()
    rows = []
    for sid, name, arrives, asks in site.known():
        st = (d.get("services") or {}).get(sid) or {}
        cadence = st.get("every") or CADENCE.get(sid, "monthly")
        declined = site.state(sid).get("state") == "declined"
        nxt = None if declined or cadence == "off" or "cycle" not in st else max(0, int(st["cycle"] + EVERY[cadence] - now))
        rows.append({"id": sid, "name": name, "every": cadence, "stage": "declined" if declined else st.get("stage", "idle"), "next_in": nxt,
                     "asks_for": asks, "last_done": st.get("last_done"), "line": st.get("line", "")})
    return {"services": rows, "reminders": [r for r in d.get("reminders", []) if r.get("open")], "done": d.get("done", [])[-5:]}


def rows(now=None, site=None):
    """One row per service for the app's sources page. An export that is in shows no row (`show` false); one the owner
    declined shows as "denied" and can be started again; one waiting on the owner carries the reminder's words."""
    st = status(now, site)
    site = site or Site()
    open_ = {r["service"]: r for r in st["reminders"]}
    out = []
    for s in st["services"]:
        seen = site.state(s["id"])
        state = {"declined": "denied", "needs_you": "waiting on you", "requested": "asked", "failed": "failed", "arrived": "in"}.get(seen.get("state"), "idle")
        if s["stage"] in ("asked", "waiting", "start") and state in ("in", "idle"):     # a new cycle is under way though an older archive is here
            state = "asked" if s["stage"] == "asked" else "waiting on you" if s["id"] in open_ else "asked"
        out.append({"id": s["id"], "name": s["name"], "state": state, "show": state in ("denied", "waiting on you", "asked", "failed"),
                    "detail": (open_.get(s["id"]) or {}).get("text") or (seen.get("detail") if state in ("failed", "waiting on you") else "") or "",
                    "restart": state in ("denied", "failed"), "every": s["every"], "next_in": s["next_in"], "asks_for": s["asks_for"]})
    return out


def restart(sid, site=None):
    """The owner takes back a "no", or wants a failed one tried again: the service is asked anew on the next tick."""
    from . import request
    if sid not in request.BY_ID:
        raise ValueError("no such service")
    request._save(sid, "idle")
    d = _load()
    st = d.setdefault("services", {}).setdefault(sid, {})
    st.update(stage="start", cycle=time.time(), tries=0, tried_at=0, opened=0, opens=0)
    d["reminders"] = [r for r in d.get("reminders", []) if r.get("service") != sid]
    _save(d)
    return rows(site=site)


# ---------------------------------------------------------------- a dry run: look, never press

# what each export page shows before anything is pressed: the first control of the request. read with the page's own text
# and buttons; nothing here clicks
LOOK = {"x": "return !!find(document,'Request archive','button,[role=button]')",
        "google": "return /Create new request|status of the requests|Export in progress/i.test(body())",
        "linkedin": "return !!find(document,'Request archive','button')",
        "instagram": "return !!find(top(),'Create export','[role=button],button')",
        "chatgpt": "return all(document,'button').filter(function(b){return txt(b)==='Export'}).length>0",
        "notion": "return !!document.querySelector('.notion-sidebar')"}
PRESSES = ("hit(", "press(", "radio(", ".click(", ".submit(", ".value=", "dispatchEvent(")


class _Look:
    """A tab that can only be read: any script that would press, pick or type is refused before it reaches the page."""
    def __init__(self, tab):
        self._t = tab

    def js(self, body):
        if any(p in body.replace(" ", "") for p in PRESSES):
            raise PermissionError("a dry run does not press anything")
        return self._t.js(body)

    def check(self):
        return self._t.check()

    def said(self, rx):
        return self._t.said(rx)

    def wait(self, body, secs=20, why="the page did not get to the next step"):
        if any(p in body.replace(" ", "") for p in PRESSES):
            raise PermissionError("a dry run does not press anything")
        return self._t.wait(body, secs, why)

    def go(self, url):
        raise PermissionError("a dry run stays on the page it opened")


def dry(only=None, open_tab=None):
    """Open each service's export page and look, read only, as far as the button that would ask for the export: is the
    owner signed in, is an export already pending, is the button there. Never presses it, never types, saves no state,
    and closes the tab. Stops at a sign-in, a password or a code and says which. Returns one row per service:
    {"id", "reached": "the request button" | "an export already pending" | "sign-in" | "password" | "code" | "not found" | "declined" | "no browser", "detail"}.
    It opens a tab in the owner's browser (in front): run it when they are at the mac."""
    from . import request
    out = []
    if open_tab is None:
        b = request.browser(ask=True)
        if not b.get("scripting"):
            return [{"id": s["id"], "reached": "no browser", "detail": b.get("how_to_enable", "")} for s in request.SERVICES if not only or s["id"] == only]
        bundle = next(x[1] for x in request.BROWSERS if x[0] == b["name"])
        open_tab = lambda url: request.Tab(b["name"], bundle, url)
    for s in request.SERVICES:
        sid = s["id"]
        if only and sid != only:
            continue
        if request.service(sid)["state"] == "declined":
            out.append({"id": sid, "reached": "declined", "detail": ""})
            continue
        row, tab = {"id": sid, "reached": "not found", "detail": ""}, None
        try:
            tab = open_tab(s["url"])
            t = _Look(tab)
            t.check()
            pending = False
            if s.get("pending"):
                try:
                    pending = bool(s["pending"](t))
                except request.Fail as e:
                    row["detail"] = str(e)
            if pending:
                row["reached"] = "an export already pending"
            else:
                t.wait(LOOK[sid], 15, "the button that asks for the export was not on the page")
                row.update(reached="the request button", detail="")
        except request.Needs as e:
            what = str(e)
            row.update(reached="sign-in" if what == "login" else what, detail="%s asks for %s before it shows the export page" % (s["name"].lower(), SECRET.get(what, what)))
        except request.Fail as e:
            row["detail"] = str(e)
        except PermissionError as e:
            row["detail"] = str(e)
        except Exception as e:
            row["detail"] = "could not look: " + str(e).split(": ")[-1][:100]
        finally:
            if tab is not None:
                tab.close()
        out.append(row)
    return out


def main(argv):
    if argv[:1] == ["--dry"]:
        print(json.dumps(dry(argv[1] if len(argv) > 1 else None)))
        return
    if argv[:1] == ["--every"] and len(argv) > 1 and "=" in argv[1]:
        sid, value = argv[1].split("=", 1)
        if sid not in CADENCE:
            raise SystemExit("services: " + " ".join(CADENCE))
        try:
            every(sid, value)
        except ValueError as e:
            raise SystemExit(str(e))
        print(json.dumps(status()))
    elif argv[:1] == ["--status"]:
        print(json.dumps(status()))
    else:
        raise SystemExit("usage: python3 -m ctx driver --status | --every <service>=weekly|monthly|off | --dry [<service>]")


if __name__ == "__main__":
    main(sys.argv[1:])
