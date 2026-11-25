"""Notes and Mail through Apple Events. Slower than reading their databases, but needs only the one-click
"allow Claude to control Notes / Mail" prompt instead of Full Disk Access."""
import json, subprocess
from .collect import iso, put

def jxa(script, timeout=600):
    r = subprocess.run(["osascript", "-l", "JavaScript", "-e", script], capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise PermissionError("not allowed or app not answering: " + r.stderr.strip()[:160])
    return json.loads(r.stdout)


def notes(days, out):
    rows = jxa('''var n=Application("Notes").notes; var a=n.name(), b=n.plaintext(), c=n.modificationDate(), p=n.passwordProtected(), i=n.id();
        JSON.stringify(a.map(function(x,k){return p[k]?null:[i[k],x,b[k],c[k].getTime()/1000]}).filter(Boolean))''')
    for nid, title, text, ts in rows:
        if (text or "").strip():
            put(out, {"id": "N" + nid.split("/")[-1], "src": "apple_notes", "ts": iso(ts), "title": title or "", "text": text[:20000]})
    return len(rows)


def mail_sent(days, out, chunk=25):
    """Every email the owner sent. Bodies come one at a time (about a second each)."""
    n = jxa('Application("Mail").sentMailbox.messages.length')
    done = 0
    for start in range(0, n, chunk):
        rows = jxa('''var s=Application("Mail").sentMailbox.messages, o=[];
            for (var i=%d;i<Math.min(%d,s.length);i++){ try { var m=s[i];
              o.push([m.id(), m.subject(), m.dateSent().getTime()/1000, m.toRecipients.address().join(", "), m.content().slice(0,6000)]) } catch(e){} }
            JSON.stringify(o)''' % (start, start + chunk))
        for mid, subj, ts, to, body in rows:
            put(out, {"id": f"E{mid}", "src": "email", "ts": iso(ts), "thread_id": "em:" + (subj or "").lower().lstrip("re: ").strip()[:60],
                      "thread": (subj or "")[:80], "kind": "dm", "mine_total": 3, "who": "me", "sender": "", "to": to, "text": body})
        done += len(rows)
        out.flush()
    return done


def mail_inbox_index(days, out):
    """Subject, sender and date of every inbox email. No bodies: enough to know who writes and about what."""
    rows = jxa('''var s=Application("Mail").inbox.messages; var a=s.subject(), b=s.sender(), c=s.dateReceived(), r=s.readStatus();
        JSON.stringify(a.map(function(x,k){return [x,b[k],c[k].getTime()/1000,r[k]]}))''', timeout=1200)
    for k, (subj, sender, ts, read) in enumerate(rows):
        put(out, {"id": f"M{k}", "src": "email_inbox", "ts": iso(ts), "title": sender or "", "text": subj or "", "read": read})
    return len(rows)
