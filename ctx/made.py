"""Things made here from the archive: a post, a blog draft, a plan, a brief, a comparison, a list.

  python3 -m ctx made [--list | --get <id>]

An answer that IS a made thing (a text written for the owner to post or send, or an artefact such as a plan or a table) is
kept as a document of its own in CTX_HOME/made/<id>.json:
  {"id", "title", "kind", "text", "made": iso, "from": [row ids it rests on], "chat", "version", "history": [{"version", "text", "made", "by", "said"}]}
A follow-up in the same chat that changes it ("tighter", "add the numbers from the march thread"), or their own edit,
makes a new version; the earlier ones stay in "history". Each document is also one row of the archive (src "made",
their own), rewritten at every version, so later answers and the wiki can draw on what the owner built here.
"""
import hashlib, json, os, re, time
from . import paths

DIR = os.path.join(paths.HOME, "made")
KINDS = ("post", "reply", "blog", "plan", "brief", "comparison", "table", "list", "outline", "note")
MAKES = re.compile(r"(?i)\b(make|build|create|put together|draw up|prepare|write up|give me|draft|compile)\b.{0,40}\b(plan|brief|briefing|comparison|table|list|checklist|outline|agenda|proposal|memo|one.?pager|roadmap|timeline|summary doc|pitch|faq)\b")
ASKING = re.compile(r"(?i)\s*(what|when|who|whom|whose|which|where|why|did|does|do i|have i|has|is|are|was|were|find|show me the|search|how (did|do|does|many|much|often|long))\b")
REVISE = re.compile(r"(?i)^\s*(tighter|shorter|longer|punchier|simpler|again|more \w+|less \w+|make it|make this|add|remove|cut|drop|change|replace|swap|rewrite|rework|redo|fix|use|keep|turn it|now |but |and (add|make|cut)|"
                    r"version \d|try (again|another)|another (one|version))\b")


def wants(question):
    """Is the owner asking for a thing to be made from their archive (a plan, a brief, a comparison, a list), not for a fact?"""
    q = str(question or "")
    return bool(MAKES.search(q)) and not (ASKING.match(q) and "?" in q)


def kind_of(question, reply=None):
    q = str(question or "").lower()
    v = (reply or {}).get("voice") or {}
    if v.get("channel") == "blog" or re.search(r"\b(blog|essay|article)\b", q):
        return "blog"
    for k, rx in (("plan", r"\b(plan|roadmap|timeline|agenda)\b"), ("brief", r"\b(brief|briefing|memo|one.?pager|pitch|proposal)\b"), ("comparison", r"\b(comparison|compare|versus|vs)\b"), ("table", r"\btable\b"),
                  ("list", r"\b(list|checklist|faq)\b"), ("outline", r"\boutline\b"), ("reply", r"\b(reply|respond)\b"), ("post", r"\b(tweet|post|thread|caption|linkedin)\b")):
        if re.search(rx, q):
            return k
    return "post" if v else "note"


def _path(doc_id):
    return os.path.join(DIR, re.sub(r"[^\w-]", "", str(doc_id)) + ".json")


def get(doc_id):
    """The document with its history, or None."""
    try:
        with open(_path(doc_id), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("id") else None
    except (OSError, ValueError):
        return None


def listing():
    """Every made thing, newest first: [{"id", "title", "kind", "made", "version"}]."""
    out = []
    for name in os.listdir(DIR) if os.path.isdir(DIR) else []:
        d = get(name[:-5]) if name.endswith(".json") else None
        if d:
            out.append({k: d.get(k) for k in ("id", "title", "kind", "made", "version")})
    return sorted(out, key=lambda d: str(d.get("made")), reverse=True)


def _title(question, text):
    line = next((l.strip(" #*_") for l in str(text or "").split("\n") if l.strip(" #*_-")), "")
    if re.match(r"(?i)^(outline|\d+|version)\b", line) or len(line) > 70 or len(line) < 4:
        line = re.sub(r"(?i)^\s*(please\s+)?(can you\s+)?", "", " ".join(str(question or "").split()))
    return line[:70].strip() or "untitled"


def _plain(answer):
    """An answer's text as a document: the numbered marks and the "leans on" lines are how it was shown, not part of the thing."""
    text = re.sub(r"(?m)^_(leans on|outside your usual range):.*$", "", str(answer or ""))
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]*\[\d+\]", "", text)).strip()


def _write(d):
    os.makedirs(DIR, exist_ok=True)
    with open(os.open(_path(d["id"]) + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(_path(d["id"]) + ".new", _path(d["id"]))
    try:
        _row(d)
    except Exception:
        pass
    return d


def _row(d):
    """The document as one row of the archive (docs.jsonl, src "made"): the row of its earlier version is replaced."""
    from . import rules
    rid = "made:" + d["id"]
    if os.path.exists(paths.DOCS):
        rules._strip(paths.DOCS, lambda x: str(x.get("id")) == rid)
    with open(paths.DOCS, "a", encoding="utf-8") as f:
        f.write(json.dumps({"id": rid, "src": "made", "ts": d["made"], "title": "%s (%s, made here, version %d)" % (d["title"], d["kind"], d["version"]), "text": d["text"], "who": "me", "url": ""}, ensure_ascii=False) + "\n")


def resync():
    """Put back the archive row of any made thing that a rebuild of the docs dropped. Returns how many were put back."""
    have = set()
    try:
        with open(paths.DOCS, "rb") as f:
            for line in f:
                if b'"src": "made"' in line:
                    try:
                        have.add(json.loads(line).get("id"))
                    except ValueError:
                        pass
    except OSError:
        pass
    n = 0
    for e in listing():
        if "made:" + e["id"] not in have:
            _row(get(e["id"]))
            n += 1
    return n


def keep(question, reply, history=None, chat=""):
    """Keep an answer that is a made thing: a new document, or a new version of the one the last turn of this chat
    made when this turn changes it. Returns {"id", "title", "kind", "version"} (also set as reply["made"]), or None."""
    text = _plain(reply.get("answer"))
    if not text or reply.get("error"):
        return None
    turns = [h for h in (history if isinstance(history, list) else []) if isinstance(h, dict)]
    last = by_answer(turns[-1].get("a")) if turns else None
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    ids = [str(c.get("id")) for c in reply.get("cites") or [] if isinstance(c, dict) and c.get("id")]
    if last and (REVISE.search(str(question or "")) or len(str(question or "").split()) <= 12):
        d = last
        if text == d["text"]:
            return None
        d["history"].append({"version": d["version"], "text": d["text"], "made": d["made"], "by": d.get("by", "context"), "said": d.get("said", "")})
        d.update(version=d["version"] + 1, text=text, made=now, by="context", said=" ".join(str(question or "").split())[:300])
        d["from"] = list(dict.fromkeys(d.get("from", []) + ids))
    else:
        doc_id = time.strftime("%Y%m%d-") + hashlib.sha1((now + text).encode("utf-8", "replace")).hexdigest()[:8]
        d = {"id": doc_id, "title": _title(question, text), "kind": kind_of(question, reply), "text": text, "made": now, "from": ids, "chat": str(chat or ""), "version": 1,
             "by": "context", "said": " ".join(str(question or "").split())[:300], "history": []}
    d["shown"] = hashlib.sha1(re.sub(r"\s+", " ", str(reply.get("answer") or "")).encode("utf-8", "replace")).hexdigest()[:16]       # to find it again from the chat's last answer
    _write(d)
    reply["made"] = {k: d[k] for k in ("id", "title", "kind", "version")}
    return reply["made"]


def by_answer(answer):
    """The made thing an answer of a chat was, or None: so a follow-up revises it rather than starting another."""
    want = hashlib.sha1(re.sub(r"\s+", " ", str(answer or "")).encode("utf-8", "replace")).hexdigest()[:16]
    plain = _plain(answer)
    for e in listing()[:200]:
        d = get(e["id"])
        if d and (d.get("shown") == want or d.get("text") == plain):
            return d
    return None


def save(doc_id, text, title=None):
    """Their own edit: a new version. Returns the document, or {"error"}."""
    d = get(doc_id)
    text = str(text or "").strip()
    if not d:
        return {"error": "no such document"}
    if not text:
        return {"error": "nothing to save"}
    if text != d["text"]:
        d["history"].append({"version": d["version"], "text": d["text"], "made": d["made"], "by": d.get("by", "context"), "said": d.get("said", "")})
        d.update(version=d["version"] + 1, text=text, made=time.strftime("%Y-%m-%dT%H:%M:%S"), by="me", said="")
    if title:
        d["title"] = " ".join(str(title).split())[:70]
    return _write(d)


def main(argv):
    if "--get" in argv and argv.index("--get") + 1 < len(argv):
        got = get(argv[argv.index("--get") + 1])
        print(json.dumps(got or {"error": "no such document. python3 -m ctx made --list shows what there is"}, ensure_ascii=False, indent=1))
        return 0 if got else 1
    else:
        for e in listing():
            print("%-18s v%-2s %-10s %s  %s" % (e["id"], e["version"], e["kind"], str(e["made"])[:10], e["title"]))
        if not listing():
            print("nothing made yet: ask for a post, a plan, a brief or a comparison and it is kept here.")
    return 0
