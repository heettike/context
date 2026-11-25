"""What a complete LinkedIn export holds beyond messages and connections (those two are in ctx/exports.py).

Read, because they are the owner's own writing or their own acts:
  linkedin_posts            Shares.csv (their posts, with what the owner shared) and InstantReposts.csv (reposts: a link, no words)
  linkedin_comments         Comments.csv: what the owner wrote under other people's posts, with the post's address
  linkedin_articles         Articles/*.html: articles the owner published, whole
  linkedin_invitations      Invitations.csv: the note written with an invitation (theirs, and the few sent to the owner)
  linkedin_recommendations  Recommendations_Given.csv and _Received.csv
  linkedin_saved            Saved_Items.csv: posts the owner saved (an address and a date; the export has no words for them)
  linkedin_likes            Reactions.csv: what the owner reacted to and how (an address and a date)
  linkedin_searches         SearchQueries.csv: what the owner searched for
  linkedin_profile          one row: their career as the owner wrote it, from Profile, Positions, Education, Skills, Publications

Left out on purpose, because they are not their words or are about their account, not their life: Ad_Targeting, Ads Clicked,
LAN Ads Engagement, Inferences_about_you, Inferred Credibility Scores, Logins, Security Challenges, Receipts,
Registration, Verifications, Email Addresses, PhoneNumbers, Whatsapp Phone Numbers. Also not read yet: endorsements,
follows, events, votes, learning, job applications (they hold a phone number and an email), media captions.

Every LinkedIn export in imports/ is read (a basic one, a complete one, an old one) and a row has its id from what it
is, so the same post in three exports is one row. A csv is read with the csv module (cells span lines) and its header
is found by content: some files open with a block of notes.
"""
import csv, html, io, os, re
from datetime import datetime, timezone
from urllib.parse import unquote
from .collect import put, rid
from .exports import _find, idtext

NONE = "no LinkedIn export with this in imports/: ask for the complete archive at linkedin.com > settings > data privacy > get a copy of your data"
REACTED = {"LIKE": "liked", "EMPATHY": "loved", "PRAISE": "celebrated", "INTEREST": "found insightful", "APPRECIATION": "supported",
           "MAYBE": "was curious about", "ENTERTAINMENT": "found funny"}


def table(path, must):
    """The rows of one csv as dicts. The header is the first row that holds every name in `must`; rows before it (a block
    of notes) are passed over. [] when the file has no such header or cannot be read."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:      # line ends as python reads them: the ids of rows already in the archive were made that way
            rows = list(csv.reader(io.StringIO(f.read().replace("\x00", ""))))
    except (OSError, csv.Error):
        return []
    for i, r in enumerate(rows[:40]):
        head = [c.strip() for c in r]
        if all(m in head for m in must):
            return [dict(zip(head, row)) for row in rows[i + 1:] if any(c.strip() for c in row)]      # cells as written: ids are made from them
    return []


def _all(name, must):
    """Rows of this file from every export, the newest export first (so where two exports differ, the later one wins)."""
    out = []
    for path in sorted(_find(name), key=lambda p: os.path.getmtime(p), reverse=True):
        out += table(path, must)
    return out


def when(text):
    """The time LinkedIn wrote, in any of the shapes its files use, as the archive writes it. "" when it is not a time."""
    text = " ".join(str(text or "").replace("UTC", "").split())
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%m/%d/%y, %I:%M %p", "%Y-%m-%d", "%d %b %Y", "%b %Y", "%Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return ""


def _link(u):
    return unquote(str(u or "").strip())


def _reader(src, rows_fn):
    def read(days, out):
        seen, n, any_file = set(), 0, False
        for row in rows_fn():
            if row is None:
                any_file = True
                continue
            any_file = True
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            put(out, dict(row, src=src))
            n += 1
        if not any_file:
            raise FileNotFoundError(NONE)
        return n
    read.__name__ = src
    return read


def _found(name):
    """Yield None once when any export has this file: an empty file is "nothing there", no file is "not exported"."""
    if _find(name):
        yield None


def _posts():
    yield from _found("Shares.csv")
    for r in _all("Shares.csv", ("Date", "ShareLink")):
        words = r.get("ShareCommentary", "").replace('""', '"').strip()
        shared = [x for x in (_link(r.get("SharedUrl")), _link(r.get("MediaUrl"))) if x]
        if not (words or shared) or not r.get("ShareLink"):
            continue
        yield {"id": rid("LS", _link(r["ShareLink"])), "ts": when(r.get("Date")), "title": "", "text": "\n".join([words] + shared).strip()[:8000],
               "url": _link(r["ShareLink"]), "who": "me"}
    yield from _found("InstantReposts.csv")
    for r in _all("InstantReposts.csv", ("Date", "Link")):
        if r.get("Link"):
            yield {"id": rid("LT", _link(r["Link"])), "ts": when(r.get("Date")), "title": "repost", "text": "reposted " + _link(r["Link"]), "url": _link(r["Link"]), "who": ""}


def _comments():
    yield from _found("Comments.csv")
    for r in _all("Comments.csv", ("Date", "Link", "Message")):
        words = r.get("Message", "").replace('""', '"').strip()
        if words and when(r.get("Date")):          # a row cut in two by a stray line break has no date: it is not a comment
            yield {"id": rid("LM", _link(r.get("Link")), r.get("Date"), idtext(words)[:120]), "ts": when(r["Date"]), "title": "comment", "text": words[:8000],
                   "url": _link(r.get("Link")), "who": "me"}


def _text(page):
    page = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", page)
    page = re.sub(r"(?i)</(p|div|h[1-6]|li|blockquote|tr)>|<br\s*/?>|<hr\s*/?>", "\n", page)
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))).strip()


def _articles():
    files = [p for p in _find("*.html") if os.sep + "Articles" + os.sep in p]
    if files:
        yield None
    for path in sorted(files, key=os.path.getmtime, reverse=True):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                page = f.read()
        except OSError:
            continue
        m = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", page) or re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
        title = " ".join(_text(m.group(1)).split()) if m else os.path.basename(path)[:-5]
        made = re.search(r'(?is)class="published"[^>]*>(.*?)<', page) or re.search(r'(?is)class="created"[^>]*>(.*?)<', page)
        at = when((re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", made.group(1) if made else os.path.basename(path)) or [""])[0]) \
            or when((re.search(r"\d{4}-\d{2}-\d{2}", os.path.basename(path)) or [""])[0])
        body = _text(page)
        if body:
            yield {"id": rid("LA", title, at[:10]), "ts": at, "title": title, "text": body[:60000], "who": "me"}


def _invitations():
    yield from _found("Invitations.csv")
    for r in _all("Invitations.csv", ("From", "To", "Sent At", "Message")):
        words, mine = r.get("Message", "").strip(), r.get("Direction", "").upper() != "INCOMING"
        if words:
            other = r.get("To") if mine else r.get("From")
            yield {"id": rid("LN", r.get("From"), r.get("To"), r.get("Sent At")), "ts": when(r.get("Sent At")),
                   "title": ("invitation to " if mine else "invitation from ") + (other or "?"), "text": words[:4000],
                   "url": _link(r.get("inviteeProfileUrl") if mine else r.get("inviterProfileUrl")), "who": "me" if mine else "them"}


def _recommendations():
    for name, mine in (("Recommendations_Given.csv", True), ("Recommendations_Received.csv", False)):
        yield from _found(name)
        for r in _all(name, ("First Name", "Last Name", "Text")):
            words, person = r.get("Text", "").strip(), ("%s %s" % (r.get("First Name", ""), r.get("Last Name", ""))).strip()
            if words:
                role = ", ".join(x for x in (r.get("Job Title"), r.get("Company")) if x)
                yield {"id": rid("LE", mine, person, idtext(words)[:120]), "ts": when(r.get("Creation Date")),
                       "title": ("recommendation for " if mine else "recommendation from ") + person + (" (%s)" % role if role else ""),
                       "text": words[:8000], "who": "me" if mine else "them"}


def _saved():
    yield from _found("Saved_Items.csv")
    for r in _all("Saved_Items.csv", ("savedItem",)):
        if r.get("savedItem"):
            yield {"id": rid("LV", _link(r["savedItem"])), "ts": when(r.get("CreatedTime")), "title": "saved on linkedin", "text": "saved " + _link(r["savedItem"]),
                   "url": _link(r["savedItem"]), "who": ""}


def _likes():
    yield from _found("Reactions.csv")
    for r in _all("Reactions.csv", ("Date", "Type", "Link")):
        if r.get("Link"):
            how = REACTED.get(r.get("Type", "").upper(), "reacted to")
            yield {"id": rid("LR", _link(r["Link"])), "ts": when(r.get("Date")), "title": how, "text": "%s %s" % (how, _link(r["Link"])), "url": _link(r["Link"]), "who": ""}


def _searches():
    yield from _found("SearchQueries.csv")
    for r in _all("SearchQueries.csv", ("Time", "Search Query")):
        words = r.get("Search Query", "").strip()
        if words:
            yield {"id": rid("LQ", r.get("Time"), idtext(words)), "ts": when(r.get("Time")), "title": "searched linkedin for", "text": words[:500], "who": "me"}


def _newest(name, must):
    files = sorted(_find(name), key=os.path.getmtime, reverse=True)
    for path in files:
        rows = table(path, must)
        if rows:
            return rows
    return []


def _profile():
    """One row: who the owner says they are and what they have done, in their own words. Where the owner lives to the street, their birth date
    and their phone are in the same files and are left out."""
    yield from _found("Profile.csv")
    p = (_newest("Profile.csv", ("First Name", "Last Name")) or [{}])[0]
    name = ("%s %s" % (p.get("First Name", ""), p.get("Last Name", ""))).strip()
    lines = [x for x in (name, p.get("Headline"), p.get("Summary"), "industry: " + p["Industry"] if p.get("Industry") else "",
                         "based in: " + p["Geo Location"] if p.get("Geo Location") else "", "sites: " + p["Websites"] if p.get("Websites") else "") if x]
    span = lambda a, b: " (%s)" % " to ".join(x for x in (a, b or "now") if x) if a or b else ""
    jobs = _newest("Positions.csv", ("Company Name", "Title"))
    if jobs:
        lines.append("\nwork:")
        for j in jobs:
            lines.append("- %s at %s%s%s" % (j.get("Title", ""), j.get("Company Name", ""), span(j.get("Started On"), j.get("Finished On")),
                                             (", " + j["Location"]) if j.get("Location") else ""))
            if j.get("Description"):
                lines.append("  " + j["Description"])
    schools = _newest("Education.csv", ("School Name",))
    if schools:
        lines.append("\neducation:")
        for e in schools:
            lines.append("- " + ", ".join(x for x in (e.get("School Name"), e.get("Degree Name")) if x) + span(e.get("Start Date"), e.get("End Date") or " "))
            for extra in (e.get("Notes"), e.get("Activities")):
                if extra:
                    lines.append("  " + extra)
    skills = [s.get("Name") for s in _newest("Skills.csv", ("Name",)) if s.get("Name")]
    if skills:
        lines.append("\nskills: " + ", ".join(skills))
    pubs = _newest("Publications.csv", ("Name",))
    if pubs:
        lines.append("\npublications:")
        for b in pubs:
            lines.append("- " + ", ".join(x for x in (b.get("Name"), b.get("Publisher"), b.get("Published On"), b.get("Url")) if x))
            if b.get("Description"):
                lines.append("  " + b["Description"])
    text = "\n".join(lines).strip()
    if text:
        try:
            at = datetime.fromtimestamp(max(os.path.getmtime(f) for f in _find("Profile.csv")), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            at = ""
        yield {"id": rid("LP", "profile"), "ts": at, "title": "linkedin profile" + (": " + name if name else ""), "text": text[:20000], "who": "me"}


SOURCES = {"linkedin_posts": _posts, "linkedin_comments": _comments, "linkedin_articles": _articles, "linkedin_invitations": _invitations,
           "linkedin_recommendations": _recommendations, "linkedin_saved": _saved, "linkedin_likes": _likes, "linkedin_searches": _searches,
           "linkedin_profile": _profile}
READERS = {name: _reader(name, fn) for name, fn in SOURCES.items()}
