"""Apple Mail from disk (~/Library/Mail/V*/**/*.emlx). Needs Full Disk Access. Lifetime, with bodies.

Kept as messages: every email the owner sent, and every email from an address they have ever written to.
Everything else (newsletters, receipts, strangers) is kept as one index line: sender, subject, date.
"""
import email, email.policy, email.utils, glob, html, os, re, unicodedata
from .collect import FDA, iso, note, put, rid

ROOT = os.path.expanduser("~/Library/Mail")
# the folder mail you sent sits in. its name comes from the mail server, in the account's language.
SENT = re.compile(r"/(Sent|Sent Mail|Sent Messages|Sent Items|Drafts|Outbox"
                  r"|Gesendet|Gesendete Objekte|Gesendete Elemente|Entw\u00fcrfe|Envoy\u00e9s|Messages envoy\u00e9s|\u00c9l\u00e9ments envoy\u00e9s|Brouillons"
                  r"|Enviados|Elementos enviados|Mensajes enviados|Borradores|Itens Enviados|Rascunhos|Inviati|Posta inviata|Bozze"
                  r"|Verzonden|Verzonden items|Concepten|Skickat|Sendt|\u041e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043d\u044b\u0435|\u9001\u4fe1\u6e08\u307f|\u5df2\u53d1\u9001|\u5bc4\u4ef6\u5099\u4efd)\.mbox/", re.I)
TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)
QUOTE = re.compile(r"\n(On .{10,90}wrote:|-{2,} ?Original Message ?-{2,}|From: .{3,80}\nSent: ).*", re.S)


def _body(msg):
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        text = part.get_content()
    except Exception:
        return ""
    if part.get_content_type() == "text/html":
        text = html.unescape(TAG.sub(" ", text))
    text = QUOTE.sub("", "\n".join(l for l in text.splitlines() if not l.lstrip().startswith(">")))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()[:6000]


def _read(path):
    with open(path, "rb") as f:
        n = int(f.readline().strip() or 0)
        return email.message_from_bytes(f.read(n), policy=email.policy.default)


def _addr(v):
    return (email.utils.parseaddr(str(v or ""))[1] or "").lower()


def _ts(msg):
    try:
        return email.utils.parsedate_to_datetime(str(msg["Date"])).timestamp()
    except Exception:
        return 0


def mail(days, out, index_out=None):
    try:
        os.listdir(ROOT)
    except FileNotFoundError:
        raise FileNotFoundError("apple mail is not set up on this mac")
    except PermissionError:
        raise PermissionError(FDA)
    files = glob.glob(os.path.join(ROOT, "V*", "**", "*.emlx"), recursive=True)
    if not files:
        raise FileNotFoundError("Apple Mail has no downloaded mail")
    me, peers, seen, n = set(), set(), set(), 0
    try:        # mail the owner flagged (a star in gmail): those rows say "starred": true. ctx/kept.py reads the flags
        from . import kept
        starred = kept.mail_flagged_files()
    except Exception:
        starred = set()
    note(f"found {len(files):,} emails. working out which address is yours")
    # pass 1a: who am I. Gmail keeps sent mail inside All Mail, so use Sent and Drafts folders where they exist.
    # CTX_MY_EMAILS=a@x.com,b@y.com in .env says it outright, for a mailbox whose sent folder has a name not listed above.
    from . import llm  # loads .env
    me.update(a.strip().lower() for a in os.environ.get("CTX_MY_EMAILS", "").split(",") if "@" in a)
    for f in files:
        if SENT.search(unicodedata.normalize("NFC", f)):
            try:
                me.add(_addr(_read(f)["From"]))
            except Exception:
                pass
    me.discard("")
    if not me:
        raise FileNotFoundError("could not tell which address is yours: no sent or drafts folder found on disk. "
                                "put CTX_MY_EMAILS=you@example.com in .env and read mail again")
    note("finding the people you write to")
    for f in files:                    # pass 1b: who do I write to
        try:
            m = _read(f)
        except Exception:
            continue
        if _addr(m["From"]) in me:
            for h in ("To", "Cc"):
                peers.update(a.lower() for _, a in email.utils.getaddresses([str(m[h] or "")]) if a)
    peers -= me
    note(f"reading mail with {len(peers):,} people you write to")
    for f in files:                    # pass 2
        try:
            m = _read(f)
        except Exception:
            continue
        mid = str(m["Message-ID"] or f)
        if mid in seen:
            continue
        seen.add(mid)
        frm, ts, subj = _addr(m["From"]), _ts(m), str(m["Subject"] or "")[:150]
        if days and ts < __import__("time").time() - days * 86400:
            continue
        thread = re.sub(r"^((re|fwd?|fw):\s*)+", "", subj.strip(), flags=re.I).lower()[:70]
        if frm in me or frm in peers:
            text = _body(m)
            if not text:
                continue
            put(out, {"id": rid("E", m["Message-ID"] or (frm, ts, subj, text[:200])), "src": "email", "ts": iso(ts), "thread_id": "em:" + thread, "thread": subj[:80] or "(no subject)",
                      "kind": "dm", "mine_total": 3, "who": "me" if frm in me else "them", "sender": frm.split("@")[0][:12] if frm not in me else "",
                      "to": _addr(m["To"]), "text": text, **({"starred": True} if os.path.basename(f).split(".")[0] in starred else {})})
            n += 1
        elif index_out is not None:
            put(index_out, {"id": rid("M", m["Message-ID"] or (frm, ts, subj)), "src": "email_index", "ts": iso(ts), "title": frm, "text": subj,
                            **({"starred": True} if os.path.basename(f).split(".")[0] in starred else {})})
    return n
