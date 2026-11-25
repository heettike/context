"""Questions about the WHOLE archive that no row answers: who went quiet, what was shared with most people, how much,
how often, the longest silence. Counted by code from every message, never estimated by a model, and every number comes
with rows that can be cited as examples.

One pass over messages.jsonl builds a small table (kept in CTX_HOME/cache/aggregate.json until the file changes):
  months   per conversation, messages per month, both ways
  links    every web address the owner SENT, normalised, with the conversations it went to
  media    how many of the owner's messages only mark an attachment (most sources keep text, not the file)
  days     the owner's own messages per day, and per hour of the day (local time)

  python3 -m ctx aggregate [lapsed|new|lately|quiet|shared|overview]     print one of the tables
"""
import collections, datetime, json, os, re, tempfile, time
from . import paths

CACHE = os.path.join(paths.HOME, "cache", "aggregate.json")
V = 2
URL = re.compile(r"https?://[^\s<>\"')\]|]+")
MEDIA = re.compile(r"(?i)<media omitted>|<attached:|sent an attachment|image omitted|video omitted|^\[(photo|image|video|sticker|gif|file|voice|audio|document)[^\]]{0,30}\]$")
DROP = re.compile(r"(?i)^(utm_\w+|fbclid|gclid|igshid|igsh|si|s|t|ref|ref_src|ref_url|feature|share_id|mibextid|source|src|cxt|context|app|usp|pli)$")
SHORT = {"youtu.be": "youtube.com", "twitter.com": "x.com", "mobile.twitter.com": "x.com", "fxtwitter.com": "x.com", "vxtwitter.com": "x.com", "mobile.x.com": "x.com",
         "m.youtube.com": "youtube.com", "music.youtube.com": "youtube.com", "m.facebook.com": "facebook.com", "instagr.am": "instagram.com"}
_mem = {}


def norm_url(u):
    """One address for the same page however it was pasted: no scheme, www, tracking tags, fragment or trailing slash;
    the short forms of the big sites folded into the long ones. "" for something that is not a page."""
    u = str(u or "").strip().rstrip(".,;:!?*)>]'\"")
    m = re.match(r"(?i)https?://([^/?#\s]+)([^?#\s]*)(\?[^#\s]*)?", u)
    if not m:
        return ""
    host, path, query = m.group(1).lower().split("@")[-1], m.group(2) or "", (m.group(3) or "")[1:]
    host = re.sub(r"^(www|m|mobile)\.", "", host) if host not in SHORT else host
    if host == "youtu.be" and len(path) > 1:
        path, query = "/watch", "v=" + path.strip("/").split("/")[0]
    if host == "youtube.com" and path.startswith("/shorts/"):
        path, query = "/watch", "v=" + path.split("/")[2] if len(path.split("/")) > 2 else ""
    host = SHORT.get(host, host)
    keep = [p for p in query.split("&") if p and not DROP.match(p.split("=")[0])]
    if host in ("x.com", "instagram.com", "linkedin.com", "t.me", "open.spotify.com", "tiktok.com", "reddit.com", "github.com"):
        keep = []                   # on these the page is the path; whatever follows it is tracking
    if host == "x.com":
        path = re.sub(r"(?i)^(/[^/]+/status/\d+).*", r"\1", path)
    if host == "youtube.com":
        keep = [p for p in keep if p.startswith(("v=", "list="))][:1]
    path = path.rstrip("/")
    if host not in ("youtube.com",):
        path = path if re.search(r"[A-Z]", path) and host in ("x.com", "t.me", "github.com", "bit.ly", "tinyurl.com", "docs.google.com", "drive.google.com") or not re.search(r"[A-Z]", path) else path
    return host + path + ("?" + "&".join(sorted(keep)) if keep else "")


def _stamp():
    """What the table was counted from: messages.jsonl, and the owner's rules and never list it was counted under."""
    from . import rules
    try:
        st = os.stat(paths.MESSAGES)
        return [st.st_size, st.st_mtime_ns, rules.stamp()]
    except OSError:
        return [0, 0, rules.stamp()]


def _local(ts):
    """(day, hour) of a row's time on this Mac's clock; the row's own digits when it carries no zone."""
    ts = str(ts or "")
    if len(ts) >= 19 and (ts.endswith("Z") or re.search(r"[+-]\d\d:?\d\d$", ts)):
        try:
            d = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")[:19] + ("+00:00" if ts.endswith("Z") else ts[-6:] if ts[-3] == ":" else "+00:00")).astimezone()
            return d.strftime("%Y-%m-%d"), d.hour
        except ValueError:
            pass
    return ts[:10], int(ts[11:13]) if len(ts) >= 13 and ts[11:13].isdigit() else -1


def build():
    """The one pass, over the rows the owner's rules and the never list let through (rules.read): what they leave out is
    in no count. Returns the table (see the module's first lines)."""
    from . import rules
    months, links, media, days, hours, srcs = {}, {}, collections.Counter(), collections.Counter(), collections.Counter(), {}
    n = 0
    for d in rules.read(paths.MESSAGES):
        tid, ts, src = str(d.get("thread_id") or ""), str(d.get("ts") or ""), str(d.get("src") or "")
        if not tid or len(ts) < 7:
            continue
        n += 1
        me = d.get("who") == "me"
        m = months.setdefault(tid, {}).setdefault(ts[:7], [0, 0])
        m[0] += 1
        m[1] += me
        s = srcs.setdefault(src, [ts[:10], ts[:10], 0])
        s[0], s[1], s[2] = min(s[0], ts[:10]), max(s[1], ts[:10]), s[2] + 1
        if not me:
            continue
        day, hour = _local(ts)
        days[day] += 1
        if hour >= 0:
            hours[hour] += 1
        text = str(d.get("text") or "")
        if MEDIA.search(text.strip()):
            media[src] += 1
        if "http" in text:
            for u in set(URL.findall(text)):
                key = norm_url(u)
                if not key or "." not in key.split("/")[0]:
                    continue
                L = links.get(key)
                if L is None:
                    L = links[key] = {"url": u.rstrip(".,;:!?*)>]'\""), "n": 0, "tids": {}, "first": ts[:10], "last": ts[:10], "ids": []}
                L["n"] += 1
                L["tids"][tid] = L["tids"].get(tid, 0) + 1
                L["first"], L["last"] = min(L["first"], ts[:10]), max(L["last"], ts[:10])
                if len(L["ids"]) < 6 and tid not in [x[1] for x in L["ids"]]:
                    L["ids"].append([str(d.get("id") or ""), tid])
    keep = {k: L for k, L in links.items() if L["n"] >= 2 or len(L["tids"]) >= 2}       # an address sent once to one place is found by search, not counted here
    return {"v": V, "stamp": _stamp(), "n": n, "months": months, "links": keep, "links_all": len(links), "links_sent": sum(L["n"] for L in links.values()),
            "media": dict(media), "days": dict(days), "hours": {str(k): v for k, v in hours.items()}, "srcs": srcs}


def table():
    """The table, from memory or the cache when messages.jsonl has not changed, else built now (some seconds)."""
    stamp = _stamp()
    if _mem.get("stamp") == stamp:
        return _mem
    try:
        with open(CACHE, encoding="utf-8") as f:
            got = json.load(f)
        if got.get("stamp") == stamp and got.get("v") == V:
            _mem.clear()
            _mem.update(got)
            return _mem
    except (OSError, ValueError):
        pass
    got = build()
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CACHE), suffix=".new")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(got, f, ensure_ascii=False)
        os.replace(tmp, CACHE)
    except OSError:
        pass
    _mem.clear()
    _mem.update(got)
    return _mem


def _ym(y, m):
    return f"{y:04d}-{m:02d}"


def _back(ym, k):
    """The month k months before ym."""
    y, m = int(ym[:4]), int(ym[5:7])
    t = y * 12 + (m - 1) - k
    return _ym(t // 12, t % 12 + 1)


def _between(a, b):
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def now_month(t=None):
    """The newest month the archive holds: "lately" is measured from there, not from today's date."""
    t = t or table()
    return max((s[1][:7] for s in t["srcs"].values()), default=time.strftime("%Y-%m"))


def contacts(months=6, least=40, after="", before=""):
    """Every person with their months, and four readings of them. Returns {"now", "window", "people": [...]}; each person:
    name, apps, total, mine, first, last, recent (messages in the last `months`), before (the same span just before it),
    peak (the busiest run of `months` months: [from, to, messages]), covered (do the apps they are on still have rows
    in the recent window: a source whose collection stopped proves nothing about a person), tids."""
    from . import people
    t = table()
    now = (before or now_month(t))[:7]
    start = _back(now, months - 1)
    prev = _back(start, months)
    ends = {s: v[1][:7] for s, v in t["srcs"].items()}
    out = []
    for p in people.everyone():
        ser, mine = collections.Counter(), 0
        for tid in p["_tids"]:
            for ym, (n, me) in (t["months"].get(tid) or {}).items():
                if (not after or ym >= after[:7]) and ym <= now:
                    ser[ym] += n
                    mine += me
        total = sum(ser.values())
        if not total:
            continue
        keys = sorted(ser)
        recent = sum(n for ym, n in ser.items() if ym >= start)
        was = sum(n for ym, n in ser.items() if prev <= ym < start)
        best = [keys[0], keys[0], 0]
        for ym in keys:                                     # the busiest run of `months` months starting at a month with messages
            end = _back(ym, -(months - 1))
            got = sum(n for k, n in ser.items() if ym <= k <= end)
            if got > best[2]:
                best = [ym, min(end, keys[-1]), got]
        out.append({"name": p["name"], "apps": p["apps"], "total": total, "mine": mine, "first": keys[0], "last": keys[-1], "last_day": p.get("last", ""),
                    "recent": recent, "before": was, "peak": best, "covered": any(ends.get(a, "") >= start for a in p["apps"]),
                    "unnamed": bool(p.get("unnamed")), "tids": p["_tids"]})
    return {"now": now, "window": [start, now], "months": months, "people": out}


def lapsed(months=6, least=40, most=25, **kw):
    """People the owner used to talk to and no longer does: a busy stretch once (at least `least` messages in `months`
    months, some of them the owner's), next to nothing in the last `months`. Busiest first."""
    c = contacts(months, **kw)
    got = [p for p in c["people"] if p["peak"][2] >= least and p["mine"] >= max(5, least // 8) and p["recent"] <= max(2, p["peak"][2] // 50)
           and p["peak"][1] < c["window"][0] and not p["unnamed"]]
    got.sort(key=lambda p: -p["peak"][2])
    return dict(c, people=got[:most], total=len(got), covered=sum(p["covered"] for p in got))


def new(months=6, least=15, most=25, **kw):
    c = contacts(months, **kw)
    got = sorted((p for p in c["people"] if p["first"] >= c["window"][0] and p["recent"] >= least and not p["unnamed"]), key=lambda p: -p["recent"])
    return dict(c, people=got[:most], total=len(got))


def lately(months=6, most=25, least=False, **kw):
    """Who the owner talks to most in the last `months`; with least, people still in touch but barely."""
    c = contacts(months, **kw)
    got = [p for p in c["people"] if p["recent"] > 0 and not p["unnamed"]]
    got.sort(key=lambda p: p["recent"] if least else -p["recent"])
    return dict(c, people=got[:most], total=len(got))


def quiet(months=6, least=30, most=25, **kw):
    """People who went quiet lately: active in the stretch before the last `months`, a tenth of that or less since."""
    c = contacts(months, **kw)
    got = sorted((p for p in c["people"] if p["before"] >= least and p["recent"] <= p["before"] // 10 and not p["unnamed"]), key=lambda p: -p["before"])
    return dict(c, people=got[:most], total=len(got))


def shared(by="people", most=20, after="", before="", query=""):
    """The web addresses the owner sent most: by how many different conversations they went to ("people") or how many
    times ("times"). Each: {"url", "times", "to" (conversations), "people" (one-to-one among them), "first", "last",
    "names" (up to 6 conversation names), "ids" (rows to cite)}."""
    from . import answer
    t, idx = table(), answer.thread_index()
    words = [w for w in re.findall(r"[^\W_]+", str(query or "").lower()) if len(w) > 1]
    out = []
    for key, L in t["links"].items():
        if (after and L["last"] < after[:10]) or (before and L["first"] > before[:10] + "~") or any(w not in key.lower() for w in words):
            continue
        ths = [idx["threads"].get(tid) or {} for tid in L["tids"]]
        out.append({"url": L["url"], "key": key, "times": L["n"], "to": len(L["tids"]), "people": sum(th.get("kind") == "dm" for th in ths), "first": L["first"], "last": L["last"],
                    "names": [str(th.get("thread") or "")[:40] for th in sorted(ths, key=lambda th: -L["tids"].get("", 0))][:6], "ids": [i for i, _ in L["ids"]]})
    out.sort(key=(lambda x: (-x["times"], -x["to"])) if by == "times" else (lambda x: (-x["to"], -x["times"])))
    return {"links": out[:most], "distinct": t["links_all"], "sent": t["links_sent"], "repeated": len(t["links"]), "media": t["media"]}


def overview(after="", before=""):
    """Counts of everything, and the owner's own rhythm: by source and year, by hour, the busiest days, the longest silences."""
    from . import answer, people
    t, idx = table(), answer.thread_index()
    ok = lambda ym: (not after or ym >= after[:7]) and (not before or ym <= before[:7])
    by_src, by_year, threads, n, mine = collections.Counter(), collections.Counter(), set(), 0, 0
    for tid, ms in t["months"].items():
        for ym, (c, me) in ms.items():
            if ok(ym):
                n += c
                mine += me
                by_src[(idx["threads"].get(tid) or {}).get("src", "?")] += c
                by_year[ym[:4]] += c
                threads.add(tid)
    days = sorted(d for d in t["days"] if ok(d[:7]) and len(d) == 10)
    gaps = []
    for a, b in zip(days, days[1:]):
        try:
            gap = (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days - 1
        except ValueError:
            continue
        if gap >= 2:
            gaps.append((gap, a, b))
    return {"messages": n, "mine": mine, "conversations": len(threads), "people": sum(1 for p in people.everyone() if not p.get("unnamed")),
            "by_source": by_src.most_common(), "by_year": sorted(by_year.items()), "hours": [t["hours"].get(str(h), 0) for h in range(24)],
            "busiest_days": sorted(((t["days"][d], d) for d in days), reverse=True)[:5], "gaps": sorted(gaps, reverse=True)[:5],
            "days_written": len(days), "sources": {s: v for s, v in t["srcs"].items()}}


def main(args):
    what = args[0] if args else "overview"
    t0 = time.time()
    if what in ("lapsed", "new", "lately", "quiet"):
        got = {"lapsed": lapsed, "new": new, "lately": lately, "quiet": quiet}[what]()
        print(f'{got["total"]} people, window {got["window"][0]} to {got["window"][1]}' + (f', {got["covered"]} on an app still collected' if "covered" in got else ""))
        for p in got["people"]:
            print(f'- {p["name"]} ({", ".join(p["apps"][:2])}): peak {p["peak"][0]} to {p["peak"][1]} {p["peak"][2]} messages, last {p["last"]}, recent {p["recent"]}')
    elif what == "shared":
        got = shared()
        print(f'{got["sent"]} links sent, {got["distinct"]} different, {got["repeated"]} sent more than once')
        for L in got["links"]:
            print(f'- {L["url"][:90]}: {L["times"]} times, {L["to"]} conversations, {L["first"]} to {L["last"]}')
    else:
        got = overview()
        print(json.dumps({k: v for k, v in got.items() if k != "sources"}, ensure_ascii=False))
    print(f"{time.time() - t0:.1f}s")
    return 0
