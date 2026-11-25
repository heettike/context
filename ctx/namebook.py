"""The name book: whose number or address is this. No model, nothing leaves this mac.

Chats come with a name when the app that holds them knows one. Where it does not, the thread is a bare phone number or
an email address. The names are on this mac all the same, in four places, best first:

  apple contacts       ~/Library/Application Support/AddressBook (every account's store). needs full disk access
  whatsapp's contacts  the phone's address book as whatsapp keeps it beside its chats, with whatsapp's own ids
  google contacts      the .vcf files of a google takeout in imports/
  whatsapp push names  the name a person gave themselves on whatsapp: used only where nothing better is known
  x archive            accounts the owner's own posts name (a mention carries the account's number, handle and name):
                       kept as "x:<number>", for x chats, which come with numbers only

build() reads what it can and writes one small private file, CTX_HOME/namebook.json (only the owner can read it):
{"phones": {last ten digits: name}, "emails": {address: name}, "ids": {whatsapp id: name}, "weak": {...}, "sources"}.
The chat readers (collect.whatsapp, collect.imessage), the call reader and anything else ask name_for() or
thread_name(). A number is matched by its last ten digits, so a number is one number however it is written and whichever
country it is from: "+55 11 91234 5678" and "011 91234 5678", "+1 (415) 555-0100" and "4155550100", "+62 812 3456 7890" and
"0812-3456-7890".

    python3 -m ctx namebook            how many numbers, addresses and ids the book holds, and from which places. counts only
    python3 -m ctx namebook --build    read every place again and write the book now
"""
import glob, json, os, re, time
from . import paths

PATH = os.path.join(paths.HOME, "namebook.json")
H = os.path.expanduser
APPLE_ROOT = "~/Library/Application Support/AddressBook"
WA_ROOT = "~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared"
STALE = 6 * 3600        # seconds after which a reader that wants the book builds it again
_mem = {}


def digits(number):
    return "".join(c for c in str(number or "") if c.isdigit())


def key(number):
    """What two spellings of one phone number share: its last ten digits (the whole of it when it is shorter, as some
    countries' numbers are). "" for something too short to be a phone number."""
    d = digits(number)
    if d.startswith("00"):
        d = d[2:]
    d = d.lstrip("0")
    return d[-10:] if len(d) >= 7 else ""


def _name(*parts):
    return " ".join(" ".join(str(p or "").split()) for p in parts if str(p or "").strip()).strip()


def _cols(con, table):
    return {r[1].upper() for r in con.execute('pragma table_info("%s")' % table)}


def _open(path):
    from . import connect
    return connect._open_ro(path)


def _close(con, tmp):
    import shutil
    con.close()
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)


def apple_contacts():
    """[{name, phones, emails, note, uid, at}] from every store of the contacts app. PermissionError when macos keeps
    this process out, FileNotFoundError when there is no contacts store."""
    root = H(APPLE_ROOT)
    try:
        os.listdir(root)
    except FileNotFoundError:
        raise FileNotFoundError("not installed or no data")
    stores = sorted(glob.glob(os.path.join(glob.escape(root), "AddressBook-v22.abcddb")) + glob.glob(os.path.join(glob.escape(root), "Sources", "*", "AddressBook-v22.abcddb")))
    out, seen = [], set()
    for path in stores:
        try:
            con, tmp = _open(path)
        except Exception:
            continue
        try:
            rc = _cols(con, "ZABCDRECORD")
            if not rc:
                continue
            pick = lambda c: ("r." + c) if c in rc else "''"
            people = {r[0]: r[1:] for r in con.execute("select r.Z_PK, %s, %s, %s, %s, %s, %s from ZABCDRECORD r" % tuple(
                pick(c) for c in ("ZFIRSTNAME", "ZLASTNAME", "ZNICKNAME", "ZORGANIZATION", "ZUNIQUEID", "ZMODIFICATIONDATE")))}
            phones, emails, notes = {}, {}, {}
            if "ZFULLNUMBER" in _cols(con, "ZABCDPHONENUMBER"):
                for owner, number in con.execute("select ZOWNER, ZFULLNUMBER from ZABCDPHONENUMBER"):
                    phones.setdefault(owner, []).append(str(number or ""))
            if "ZADDRESS" in _cols(con, "ZABCDEMAILADDRESS"):
                for owner, addr in con.execute("select ZOWNER, ZADDRESS from ZABCDEMAILADDRESS"):
                    emails.setdefault(owner, []).append(str(addr or "").strip().lower())
            nc = _cols(con, "ZABCDNOTE")
            if "ZTEXT" in nc and "ZCONTACT" in nc:
                for owner, text in con.execute("select ZCONTACT, ZTEXT from ZABCDNOTE"):
                    if text:
                        notes[owner] = str(text)
            for pk, (first, last, nick, org, uid, at) in people.items():
                name = _name(first, last) or _name(nick) or _name(org)
                if not name:
                    continue
                uid = str(uid or "%s:%s" % (os.path.basename(os.path.dirname(path)), pk))
                if uid in seen:             # the same card in two accounts' stores
                    continue
                seen.add(uid)
                out.append({"name": name, "phones": phones.get(pk, []), "emails": emails.get(pk, []), "note": notes.get(pk, ""), "uid": uid,
                            "at": float(at or 0)})
        except Exception:
            continue
        finally:
            _close(con, tmp)
    return out


def _whatsapp():
    """(strong, weak): [(name, phone, whatsapp id)] from whatsapp's copy of the address book, and from the names people
    gave themselves. Empty when whatsapp is not on this mac or cannot be read."""
    strong, weak = [], []
    try:
        con, tmp = _open(os.path.join(H(WA_ROOT), "ContactsV2.sqlite"))
        try:
            c = _cols(con, "ZWAADDRESSBOOKCONTACT")
            if "ZFULLNAME" in c:
                q = "select ZFULLNAME, %s, %s, %s from ZWAADDRESSBOOKCONTACT" % tuple(x if x in c else "''" for x in ("ZPHONENUMBER", "ZWHATSAPPID", "ZLID"))
                for name, phone, wid, lid in con.execute(q):
                    if _name(name):
                        strong.append((_name(name), str(phone or "") or str(wid or "").split("@")[0], str(lid or "").split("@")[0]))
        finally:
            _close(con, tmp)
    except Exception:
        pass
    try:
        con, tmp = _open(os.path.join(H(WA_ROOT), "ChatStorage.sqlite"))
        try:
            if "ZPUSHNAME" in _cols(con, "ZWAPROFILEPUSHNAME"):
                for jid, name in con.execute("select ZJID, ZPUSHNAME from ZWAPROFILEPUSHNAME"):
                    name, jid = _name(name), str(jid or "")
                    if any(ch.isalpha() for ch in name) and "@" in jid:
                        who, kind = jid.split("@", 1)
                        weak.append((name, who if kind.startswith("s.whatsapp") else "", who if kind == "lid" else ""))
        finally:
            _close(con, tmp)
    except Exception:
        pass
    return strong, weak


def _vcards():
    """[(name, phones, emails)] from every .vcf under imports/ (a google takeout's contacts)."""
    out = []
    for path in sorted(glob.glob(os.path.join(glob.escape(os.path.join(paths.HOME, "imports")), "**", "*.vcf"), recursive=True)):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = re.sub(r"\r?\n[ \t]", "", f.read())          # a long line is folded onto the next with a leading space
        except OSError:
            continue
        name, n, phones, emails = "", "", [], []
        for line in text.splitlines():
            head, _, value = line.partition(":")
            tag = head.split(";")[0].split(".")[-1].upper()
            if tag == "BEGIN":
                name, n, phones, emails = "", "", [], []
            elif tag == "FN":
                name = _name(value.replace("\\,", ","))
            elif tag == "N":
                last, first = (value.split(";") + ["", ""])[:2]
                n = _name(first, last)
            elif tag == "TEL":
                phones.append(value)
            elif tag == "EMAIL":
                emails.append(value.strip().lower())
            elif tag == "END" and (name or n) and (phones or emails):
                out.append((name or n, phones, emails))
    return out


def build():
    """Read every place that knows names and write the book. Returns it. A process macos keeps out of the contacts
    app never replaces a book that was built with them: it returns that book as it is."""
    try:
        with open(PATH, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = {}
    book = {"v": 1, "phones": {}, "emails": {}, "ids": {}, "weak": {}, "sources": {}}
    try:
        cards = apple_contacts()
        book["sources"]["apple contacts"] = len(cards)
    except PermissionError:
        if (old.get("sources") or {}).get("apple contacts"):
            _mem.clear()
            return old
        cards = []
        book["sources"]["apple contacts"] = "blocked by macos"
    except (FileNotFoundError, OSError):
        cards = []
    for c in cards:
        for p in c["phones"]:
            if key(p):
                book["phones"].setdefault(key(p), c["name"])
        for e in c["emails"]:
            if "@" in e:
                book["emails"].setdefault(e, c["name"])
    strong, weak = _whatsapp()
    for name, phone, lid in strong:
        if key(phone):
            book["phones"].setdefault(key(phone), name)
        if lid:
            book["ids"].setdefault(lid, name)
    book["sources"]["whatsapp contacts"] = len(strong)
    cards = _vcards()
    for name, phones, emails in cards:
        for p in phones:
            if key(p):
                book["phones"].setdefault(key(p), name)
        for e in emails:
            if "@" in e:
                book["emails"].setdefault(e, name)
    book["sources"]["google contacts"] = len(cards)
    for name, phone, lid in weak:
        if key(phone) and key(phone) not in book["phones"]:
            book["weak"].setdefault(key(phone), name)
        if lid and lid not in book["ids"]:
            book["weak"].setdefault("id:" + lid, name)
    book["sources"]["whatsapp push names"] = len(weak)
    try:                    # x accounts the owner's own posts name: "x:<account number>" -> "Name (@handle)"
        from . import exports
        named = exports.x_names()
    except Exception:
        named = {}
    for num, name in named.items():
        book["ids"].setdefault("x:" + num, name)
    book["sources"]["x archive"] = len(named)
    book["at"] = time.time()
    os.makedirs(paths.HOME, exist_ok=True)
    tmp = "%s.part.%d" % (PATH, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(book, f, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    os.replace(tmp, PATH)
    _mem.clear()
    return book


def load():
    """The book as last written ({} parts when there is none). Read again only when the file changes."""
    try:
        stamp = os.stat(PATH).st_mtime_ns
    except OSError:
        return {"phones": {}, "emails": {}, "ids": {}, "weak": {}, "sources": {}}
    if _mem.get("stamp") != stamp:
        try:
            with open(PATH, encoding="utf-8") as f:
                book = json.load(f)
        except (OSError, ValueError):
            book = {}
        for k in ("phones", "emails", "ids", "weak", "sources"):
            if not isinstance(book.get(k), dict):
                book[k] = {}
        _mem.update(stamp=stamp, book=book)
    return _mem["book"]


def fresh():
    """The book, built now if there is none or it is hours old. Never raises: a reader must not fail for want of names."""
    try:
        if time.time() - os.path.getmtime(PATH) < STALE:
            return load()
    except OSError:
        pass
    try:
        build()
    except Exception:
        pass
    return load()


def _weak(book, k, wanted):
    got = book["weak"].get(k, "") if wanted else ""
    return "~" + got if got else ""


def name_for(who, book=None, weak=True):
    """The name behind a phone number, an email address or a whatsapp id ("5511...@s.whatsapp.net", "123@lid"). "" when
    the book has none. `weak` lets a name someone gave themselves stand in when the owner saved none: it comes back
    with a "~" in front, as whatsapp shows it, so it is never taken for a name the owner chose."""
    book, who = book or load(), str(who or "").strip()
    if not who:
        return ""
    if who.startswith("x:"):
        return book["ids"].get(who, "")
    if who.endswith("@lid") or who.endswith("@lid.status"):
        lid = who.split("@")[0]
        return book["ids"].get(lid) or _weak(book, "id:" + lid, weak)
    if "@s.whatsapp.net" in who or "@c.us" in who:
        who = who.split("@")[0]
    elif "@" in who:
        return book["emails"].get(who.lower(), "")
    if any(c.isalpha() for c in who):
        return ""
    k = key(who)
    return (book["phones"].get(k) or _weak(book, k, weak)) if k else ""


def thread_name(name, address="", book=None):
    """What to call a one-to-one thread: the name the app gave it, unless that is only a number or an address and the
    book knows whose it is. `address` is the app's own id for the other side, when it has one."""
    name = str(name or "")
    if any(c.isalpha() for c in name) and "@" not in name:
        return name
    return name_for(address, book) or name_for(name, book) or name


def main(argv):
    if argv[:1] == ["--build"]:
        book = build()
    else:
        book = load()
    print(json.dumps({"file": PATH if os.path.exists(PATH) else "", "numbers": len(book["phones"]), "addresses": len(book["emails"]),
                      "whatsapp ids": len(book["ids"]), "self-given names": len(book["weak"]), "sources": book["sources"]}))


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
