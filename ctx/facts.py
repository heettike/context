"""Plain facts about the owner, counted from the archive on this Mac. No model, nothing leaves the machine.

`python3 -m ctx facts` prints one JSON object the app shows right after the first read:
the proof that it read you, and the first things worth acting on.
`python3 -m ctx doctor` (doctor.py) prints what this Mac has and lacks, for testing on a new computer.
"""
import collections, json, os
from datetime import datetime, timedelta, timezone
from . import paths


def _rows(path):
    """The rows of one archive file a reader may use: through the owner's rules and the never list (rules.read), so every
    count below is of what may be handed out, never of what they leave out."""
    from . import rules
    return rules.read(path)


def _local(ts):
    try:
        return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).astimezone()
    except (ValueError, TypeError):
        return None


def _ago(dt, now):
    d = (now - dt).days
    return "today" if d == 0 else "yesterday" if d == 1 else f"{d} days ago" if d < 60 else f"{d // 30} months ago"


def facts():
    now = datetime.now().astimezone()
    mine = collections.Counter()          # (src, thread) -> messages I sent, dms only
    theirs = collections.Counter()
    last = {}                             # (src, thread) -> (ts, who, text)
    hours, days, per_src, first = collections.Counter(), set(), collections.Counter(), {}
    my_words = my_msgs = total = 0
    for d in _rows(paths.MESSAGES):
        if not d.get("src") or not d.get("who"):
            continue
        total += 1
        per_src[d["src"]] += 1
        ts = d.get("ts") or ""
        if ts and (d["src"] not in first or ts < first[d["src"]]):
            first[d["src"]] = ts
        if d.get("kind") == "dm" and not d.get("last_only"):
            k = (d["src"], d.get("thread") or "?")
            (mine if d["who"] == "me" else theirs)[k] += 1
            if k not in last or ts > last[k][0]:
                last[k] = (ts, d["who"], d.get("text") or "")
        if d["who"] == "me":
            my_msgs += 1
            my_words += len((d.get("text") or "").split())
            t = _local(ts)
            if t:
                hours[t.hour] += 1
                days.add(t.date())
    prompts, projects = 0, collections.Counter()
    for d in _rows(paths.PROMPTS):
        total += 1
        prompts += 1
        my_words += len((d.get("text") or "").split())
        if d.get("thread"):
            projects[d["thread"]] += 1
        t = _local(d.get("ts") or "")
        if t:
            days.add(t.date())
    docs = collections.Counter()
    for d in _rows(paths.DOCS):
        total += 1
        docs[str(d.get("src") or "")] += 1
    per_src.update(docs)
    sessions = sum(1 for _ in _rows(paths.SESSIONS))

    def person(k):
        return {"name": k[1], "where": k[0], "you": mine[k], "them": theirs[k]}

    real = [k for k in mine if mine[k] >= 20 and theirs[k] >= 20 and not k[1].lstrip("+").replace(" ", "").isdigit()]
    closest = [person(k) for k in sorted(real, key=lambda k: -mine[k])[:5]]
    # people waiting: they wrote last, within two weeks, in a thread you normally answer
    waiting = []
    for k in real:
        ts, who, text = last[k]
        t = _local(ts)
        if who != "me" and t and timedelta(hours=6) < now - t < timedelta(days=14) and "?" in text[-200:]:
            waiting.append({**person(k), "since": _ago(t, now), "days": (now - t).days})
    waiting.sort(key=lambda p: -p["you"])
    # gone quiet: you used to talk a lot, nothing for two months
    quiet = []
    for k in sorted(real, key=lambda k: -(mine[k] + theirs[k]))[:60]:
        t = _local(last[k][0])
        if t and timedelta(days=60) < now - t < timedelta(days=720) and mine[k] >= 150:
            quiet.append({**person(k), "since": _ago(t, now), "days": (now - t).days})
    quiet = quiet[:5]
    earliest = min(first.values()) if first else ""
    peak = hours.most_common(1)[0][0] if hours else None
    late = sum(v for h, v in hours.items() if h < 5) / max(1, sum(hours.values()))
    lines = []
    if earliest:
        lines.append(f"your record starts in {_local(earliest).strftime('%B %Y').lower()}.")
    if my_words:
        novels = my_words // 90000          # a novel is about 90,000 words; under one, the count stands alone
        lines.append(f"you typed {my_words:,} words here." + (f" about {novels} novel{'s' if novels > 1 else ''}." if novels else ""))
    if closest:
        lines.append(f"you write to {closest[0]['name'].split()[0].lower()} most: {closest[0]['you']:,} messages.")
    if waiting:
        lines.append(f"{len(waiting)} {'person is' if len(waiting) == 1 else 'people are'} waiting on a reply from you.")
    if quiet:
        lines.append(f"you and {quiet[0]['name'].split()[0].lower()} last spoke {quiet[0]['since']}.")
    if peak is not None:
        lines.append(f"you write most around {peak % 12 or 12}{'am' if peak < 12 else 'pm'}." + (f" {round(late * 100)}% of it after midnight." if late > 0.08 else ""))
    if projects:
        p, n = projects.most_common(1)[0]
        lines.append(f"you gave agents {prompts:,} instructions. most on {p.lower()}: {n:,}.")
    from . import rules
    why = rules.broken()            # the never list cannot be read: nothing was counted, and this says why
    return dict({"total": total, "sources": sum(1 for v in per_src.values() if v), "since": earliest[:10], "my_messages": my_msgs,
                 "my_words": my_words, "active_days": len(days), "peak_hour": peak, "late_share": round(late, 3), "sessions": sessions,
                 "prompts": prompts, "top_projects": projects.most_common(5), "closest": closest, "waiting": waiting[:8],
                 "quiet": quiet, "by_source": dict(per_src.most_common()), "lines": [why] if why else lines}, **({"error": why} if why else {}))


def doctor():
    """The preflight report. It lives in doctor.py now; kept here for anything that still calls facts.doctor()."""
    from . import doctor as d
    return d.report()
