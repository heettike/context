"""Blank-canvas sources: the owner points at anything of their own and it becomes a source.

    python3 -m ctx connect --search "<what was typed>"     a candidate row for a website, a feed, a folder, a file, a repo,
                                                           a youtube channel; a blank note when nothing else matches
    python3 -u -m ctx connect <id> [--only posts|all|/path]   one real, bounded trial; progress lines, then one json line
    python3 -m ctx connect --enable <id> | --disable <id> | --remove <id> | --list
    python3 -m ctx note "<name>" [--append "<text>" | --file <path> | stdin] [--replace]

An id is "<kind>:<address>": site:https://example.com/blog, feed:https://example.com/feed.xml, folder:/path,
file:/path, repo:user/repo, youtube:https://www.youtube.com/@name, note:<name>. Once saved, "canvas_<slug>" works too.

A saved source lives in CTX_HOME/custom/canvas.json and is read by collect.py as the source canvas_<slug> (docs).
What each read remembers (etags, sitemap dates, file times) is in CTX_HOME/custom/canvas_state/<slug>.json.

Network rules, all enforced in fetch(): GET only; http and https only; no cookies and no credentials are ever sent;
every address is resolved first and refused unless every answer is a public address (nothing on this mac, nothing on
the local network), and the connection is made to the address that was checked; redirects are followed by hand, each
hop checked the same way; only text is read, up to a size cap. robots.txt is read and obeyed for pages. No model is
used anywhere in this file.
"""
import gzip, hashlib, html, http.client, ipaddress, json, os, re, socket, ssl, subprocess, sys, threading, time, zipfile, zlib
from collections import deque
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib import robotparser
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from . import paths

CUSTOM = os.path.join(paths.HOME, "custom")
DEFS = os.path.join(CUSTOM, "canvas.json")
STATE = os.path.join(CUSTOM, "canvas_state")
NOTES = os.path.join(CUSTOM, "notes")
PARTS = os.path.join(paths.HOME, "parts")
HOME = os.path.expanduser("~")

AGENT = "context-reader"
UA = AGENT + "/1.0 (a personal archive tool; reads public pages for their owner, one at a time)"
TRIAL_PAGES, FULL_PAGES = 40, 2000      # pages fetched in a trial and in a full read
TRIAL_SECS, FULL_SECS = 90, 3600
_clock = time.monotonic               # limits and pauses count time awake: the wall clock jumps when the mac sleeps, and a read that slept is not a read that ran out of time
DELAY = 0.5                             # seconds between two requests to one site
TIMEOUT = 15
MAX_BYTES = 2_000_000                   # of one page
MAX_REDIRECTS = 5
MIN_WORDS = 80                          # a page with fewer words is an index or a stub, not a text
ROW_CHARS = 20000
FILE_BYTES = 5_000_000
def _test_loopback(env, home):
    """The tests' own server is on this mac, so they may reach it. The switch works only on an archive in the system's
    temporary folder, which a test's is and nobody's real one is: set anywhere else it does nothing."""
    import tempfile
    tmp, home = os.path.realpath(tempfile.gettempdir()), os.path.realpath(home)
    return env.get("CTX_CANVAS_TEST_LOOPBACK") == "1" and (home + os.sep).startswith(tmp + os.sep)


ALLOW_LOOPBACK = _test_loopback(os.environ, paths.HOME)
KINDS = ("site", "feed", "folder", "file", "repo", "youtube", "note", "builtin", "webapp")
TIER = {"site": "daily", "feed": "daily", "youtube": "daily", "folder": "fast", "file": "fast", "note": "fast", "repo": "weekly", "builtin": "fast", "webapp": "daily"}
LOCAL = "that address is on this mac or your local network; only public pages are read"
_lock = threading.RLock()


class Stop(Exception):
    """A read that cannot go on. state is "cannot" or "needs_you"; detail says why in plain words."""
    def __init__(self, state, detail, ask=None):
        Exception.__init__(self, detail)
        self.state, self.detail, self.ask = state, detail, ask


class Refused(Exception):
    """An address this tool will not fetch."""


class Blocked(Exception):
    """robots.txt asks tools not to read this address."""


class Unreachable(Exception):
    """The request was made and failed."""


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")[:60].strip("_")
    return s or "n" + hashlib.sha1(str(name).encode("utf-8", "replace")).hexdigest()[:8]


def tilde(p):
    return "~" + p[len(HOME):] if p.startswith(HOME + os.sep) or p == HOME else p


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rid(*parts):
    return "K" + hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8", "surrogateescape")).hexdigest()[:14]


def _sha(text):
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]


# ---------------------------------------------------------------- dates

ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d\d)(?::(\d\d))?(?:\.\d+)?\s*(Z|[+-]\d\d:?\d\d)?)?")
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
WORDY = re.compile(r"(?i)\b(?:(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?,?\s+(\d{4})|([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4}))\b")
IN_URL = re.compile(r"/((?:19|20)\d\d)[/-](0[1-9]|1[0-2])(?:[/-](0[1-9]|[12]\d|3[01]))?(?=[/-]|$)")


def when(s, loose=False):
    """Any date a page or a feed writes, as 2024-05-17T09:30:00Z; "" when it is not a date. loose: find one inside a sentence."""
    s = str(s or "").strip()
    if not s:
        return ""
    try:
        m = ISO.search(s) if loose else ISO.match(s)
        dt = None
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if m.group(4) is None:
                dt = datetime(y, mo, d, 12, tzinfo=timezone.utc)
            else:
                dt = datetime(y, mo, d, int(m.group(4)), int(m.group(5)), int(m.group(6) or 0), tzinfo=timezone.utc)
                z = m.group(7)
                if z and z != "Z":
                    z = z.replace(":", "")
                    dt -= timedelta(hours=int(z[1:3]), minutes=int(z[3:5])) * (1 if z[0] == "+" else -1)
        if dt is None and not loose:
            try:
                dt = parsedate_to_datetime(s)
                dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
            except (TypeError, ValueError, IndexError):
                dt = None
        if dt is None:
            w = WORDY.search(s)
            if not w:
                return ""
            day, mon, year = (w.group(1), w.group(2), w.group(3)) if w.group(1) else (w.group(5), w.group(4), w.group(6))
            if mon[:3].lower() not in MONTHS:
                return ""
            dt = datetime(int(year), MONTHS[mon[:3].lower()], int(day), 12, tzinfo=timezone.utc)
        if not 1990 <= dt.year <= time.gmtime().tm_year + 1:
            return ""
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError):
        return ""


# ---------------------------------------------------------------- the network: one guarded GET

PAGE_TYPES = ("text/", "application/xhtml+xml", "application/xml", "application/rss+xml", "application/atom+xml", "application/rdf+xml",
              "application/json", "application/feed+json", "application/vnd.github")
GZ_TYPES = ("application/gzip", "application/x-gzip", "application/octet-stream")
_tls = []


def _public(host, port):
    """The address to connect to, after every address the name resolves to was checked. Raises Refused for anything not public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        raise Unreachable("no such address")
    ips = []
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            raise Refused(LOCAL)
        inner = ip
        if ip.version == 6:
            inner = ip.ipv4_mapped or ip.sixtofour or (ipaddress.ip_address(int(ip) & 0xFFFFFFFF) if ip in ipaddress.ip_network("64:ff9b::/96") else ip)
        for a in {ip, inner}:
            if a.is_loopback and ALLOW_LOOPBACK:
                continue
            if not a.is_global or a.is_multicast or a.is_loopback or a.is_private or a.is_link_local or a.is_reserved or a.is_unspecified:
                raise Refused(LOCAL)
        ips.append(ip)
    if not ips:
        raise Unreachable("no such address")
    ips.sort(key=lambda i: i.version)       # ipv4 first: it is the one that always routes
    return str(ips[0])


class _Conn(http.client.HTTPConnection):
    """Connects to the address that was checked, not to whatever the name resolves to a moment later."""
    def __init__(self, host, port, ip):
        http.client.HTTPConnection.__init__(self, host, port, timeout=TIMEOUT)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _Tls(_Conn):
    default_port = 443

    def connect(self):
        _Conn.connect(self)
        if not _tls:
            _tls.append(ssl.create_default_context())
        self.sock = _tls[0].wrap_socket(self.sock, server_hostname=self.host)


class Got:
    def __init__(self, status, url, ctype="", text="", headers=None, cut=False):
        self.status, self.url, self.type, self.text, self.headers, self.cut = status, url, ctype, text, headers or {}, cut


def fetch(url, etag="", modified="", cap=MAX_BYTES, gz=False, check=None, accept=""):
    """GET one public address and return its text. No cookies, no credentials, no body. check(url) is called for every hop
    and may raise Blocked. A page that is not text comes back with empty text."""
    hops = 0
    while True:
        try:
            u = urlsplit(url)
            port = u.port
        except ValueError:
            raise Refused("that is not an address")
        if u.scheme not in ("http", "https"):
            raise Refused("only http and https addresses are read")
        if u.username or u.password or not u.hostname:
            raise Refused("an address with a name or a password in it is not read")
        try:
            host = u.hostname.encode("idna").decode("ascii")
        except UnicodeError:
            raise Refused("that is not an address")
        if check:
            check(url)
        port = port or (443 if u.scheme == "https" else 80)
        ip = _public(host, port)
        target = quote(u.path or "/", safe="/%:@!$&'()*+,;=~-._") + ("?" + quote(u.query, safe="=&%:@!$'()*+,;/?~-._") if u.query else "")
        head = {"User-Agent": UA, "Accept": accept or "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.1",
                "Accept-Encoding": "gzip", "Connection": "close"}
        if etag:
            head["If-None-Match"] = etag
        if modified:
            head["If-Modified-Since"] = modified
        conn = (_Tls if u.scheme == "https" else _Conn)(host, port, ip)
        try:
            conn.request("GET", target, headers=head)
            r = conn.getresponse()
            heads = {k.lower(): v for k, v in r.getheaders()}
            if r.status in (301, 302, 303, 307, 308) and heads.get("location"):
                hops += 1
                if hops > MAX_REDIRECTS:
                    raise Unreachable("it redirects too many times")
                url = urljoin(url, heads["location"])
                continue
            ctype = heads.get("content-type", "").split(";")[0].strip().lower()
            zipped = gz and u.path.lower().endswith(".gz") and ctype in GZ_TYPES
            if r.status != 200 or not (not ctype or ctype.startswith(PAGE_TYPES) or zipped):
                return Got(r.status, url, ctype, "", heads)
            raw = r.read(cap + 1)
            cut = len(raw) > cap
            if zipped or "gzip" in heads.get("content-encoding", "").lower():
                try:
                    raw = zlib.decompressobj(47).decompress(raw, cap)
                except zlib.error:
                    if not zipped and raw[:2] != b"\x1f\x8b":
                        pass                    # it said gzip and sent plain text
                    else:
                        return Got(r.status, url, ctype, "", heads)
            m = re.search(r"charset=[\"']?([\w.:-]+)", heads.get("content-type", ""), re.I) or re.search(rb"<meta[^>]+charset=[\"']?([\w.:-]+)", raw[:2048], re.I)
            enc = m.group(1) if m else "utf-8"
            enc = enc.decode("ascii", "replace") if isinstance(enc, bytes) else enc
            try:
                text = raw[:cap].decode(enc, "replace")
            except LookupError:
                text = raw[:cap].decode("utf-8", "replace")
            return Got(r.status, url, ctype, text, heads, cut)
        except ssl.SSLCertVerificationError:
            raise Unreachable("its certificate could not be checked")
        except (OSError, http.client.HTTPException) as e:
            raise Unreachable("it did not answer" if isinstance(e, (socket.timeout, TimeoutError)) else "the connection failed (%s)" % type(e).__name__)
        finally:
            conn.close()


class Web:
    """One polite reader: robots.txt per site, one request at a time, a pause between two."""
    def __init__(self):
        self.rules, self.last, self.requests = {}, 0.0, 0

    def robots(self, url):
        u = urlsplit(url)
        origin = "%s://%s" % (u.scheme, u.netloc)
        if origin not in self.rules:
            rp = robotparser.RobotFileParser()
            try:
                self._pause(0)
                got = fetch(origin + "/robots.txt", cap=500_000)
                if got.status == 200 and got.text and "<html" not in got.text[:500].lower():
                    rp.parse(got.text.splitlines())
                elif got.status in (401, 403):
                    rp.disallow_all = True
                else:
                    rp.allow_all = True
            except Unreachable:
                rp.allow_all = True
            self.rules[origin] = rp
        return self.rules[origin]

    def allowed(self, url):
        try:
            return self.robots(url).can_fetch(AGENT, url)
        except Refused:
            raise
        except Exception:
            return True

    def _check(self, url):
        if not self.allowed(url):
            raise Blocked(url)

    def _pause(self, extra):
        wait = self.last + max(DELAY, extra) - _clock() if DELAY or extra else 0
        if wait > 0:
            time.sleep(wait)
        self.last = _clock()

    def get(self, url, **kw):
        self._check(url)
        try:
            asked = self.robots(url).crawl_delay(AGENT) or 0
        except Exception:
            asked = 0
        self._pause(min(float(asked), 10.0) if DELAY else 0)
        self.requests += 1
        return fetch(url, check=self._check, **kw)


# ---------------------------------------------------------------- addresses

SKIP_EXT = re.compile(r"(?i)\.(png|jpe?g|gif|webp|avif|svg|ico|bmp|tiff?|pdf|zip|gz|tar|tgz|rar|7z|dmg|exe|pkg|mp3|mp4|m4a|m4v|mov|avi|wav|ogg|webm|css|js|mjs|"
                      r"json|xml|rss|atom|woff2?|ttf|eot|otf|epub|mobi|docx?|xlsx?|pptx?|csv|txt|ics|vcf)$")
TRACK = re.compile(r"(?i)^(utm_\w+|fbclid|gclid|mc_[ce]id|ref|ref_src|source)=")
LISTING = {"tag", "tags", "category", "categories", "cat", "author", "authors", "page", "archive", "archives", "search", "topics", "label", "labels"}


def norm(url, base=""):
    """One spelling of an address: no fragment, no tracking parameters. "" when it is not http or https."""
    try:
        u = urlsplit(urljoin(base, url.strip()) if base else url.strip())
        if u.scheme not in ("http", "https") or not u.hostname:
            return ""
        port = u.port
    except ValueError:
        return ""
    net = u.hostname.lower() + (":%d" % port if port and port != (443 if u.scheme == "https" else 80) else "")
    path = re.sub(r"/index\.(html?|php)$", "/", re.sub(r"/{2,}", "/", u.path or "/"))
    query = "&".join(p for p in u.query.split("&") if p and not TRACK.match(p))
    return urlunsplit((u.scheme, net, path, query, ""))


def key(url):
    """What makes two addresses the same page: http or https, www or not, a closing slash or not."""
    u = urlsplit(url)
    host = (u.netloc or "").lower()
    return (host[4:] if host.startswith("www.") else host) + (u.path.rstrip("/") or "/") + ("?" + u.query if u.query else "")


def _host(url):
    h = (urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _listing(url, scope=""):
    """An address that looks like a list of pages (a tag, a category, page 2, a month), not a page of its own."""
    path = urlsplit(url).path
    if scope and path.rstrip("/") == scope:
        return True
    segs = [s.lower() for s in path.split("/") if s]
    return not segs or any(s in LISTING for s in segs) or all(s.isdigit() for s in segs)


# ---------------------------------------------------------------- reading a page of html

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
DROP = {"script", "style", "noscript", "template", "svg", "nav", "footer", "aside", "iframe", "button", "select", "textarea", "dialog", "canvas",
        "video", "audio", "object"}
PARA = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "ul", "ol", "table", "article", "section", "main", "figure", "hr"}
BLOCK = PARA | {"div", "li", "tr", "dt", "dd", "figcaption", "header", "br", "td", "th"}
ROLES = {"navigation", "banner", "contentinfo", "complementary", "search", "dialog", "alert"}
CHROME = {"nav", "navbar", "navigation", "menu", "sidebar", "footer", "site-footer", "site-header", "comments", "comment-list", "share", "sharing",
          "social", "related", "related-posts", "breadcrumb", "breadcrumbs", "cookie-banner", "cookie-notice", "newsletter", "skip-link", "pagination"}
META_DATES = ("article:published_time", "og:article:published_time", "datepublished", "date", "pubdate", "publishdate", "publish-date",
              "publication_date", "dc.date", "dc.date.issued", "dcterms.created", "dcterms.date", "citation_publication_date", "parsely-pub-date",
              "sailthru.date")


class Reader(HTMLParser):
    """The words of a page: its title, the text of its article or main part, without menus, footers, scripts and styles."""
    def __init__(self, base=""):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.base, self.skip, self.zone = base, None, {"article": 0, "main": 0}
        self.out = {"article": [], "main": [], "body": []}
        self.title, self.in_title, self.h1, self.pre = [], False, None, 0
        self.meta, self.times, self.links, self.feeds, self.canonical, self.ld, self.in_ld = {}, [], [], [], "", [], False

    def _text(self, s):
        self.out["body"].append(s)
        for z in ("article", "main"):
            if self.zone[z]:
                self.out[z].append(s)

    def _chrome(self, tag, a):
        if tag in ("html", "body", "main", "article"):
            return False
        if a.get("role", "").lower() in ROLES or "hidden" in a or a.get("aria-hidden") == "true" or re.search(r"display\s*:\s*none", a.get("style", "")):
            return True
        return bool(set((a.get("class", "") + " " + a.get("id", "")).lower().split()) & CHROME)

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])            # a menu's links still say which pages exist
        if self.skip:
            if tag == self.skip[0]:
                self.skip[1] += 1
            return
        if tag == "meta":
            k = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if k and a.get("content"):
                self.meta.setdefault(k, a["content"].strip())
            return
        if tag == "link":
            rel = a.get("rel", "").lower().split()
            if "canonical" in rel and a.get("href"):
                self.canonical = a["href"]
            elif "alternate" in rel and a.get("href") and re.search(r"(rss|atom)\+xml", a.get("type", ""), re.I):
                self.feeds.append(a["href"])
            return
        if tag == "base":
            self.base = urljoin(self.base, a.get("href", "")) if a.get("href") else self.base
            return
        if tag == "title":
            self.in_title = True
            return
        if tag == "script":
            self.in_ld = "ld+json" in a.get("type", "").lower()
            self.skip = ["script", 1]
            return
        if tag == "time" and a.get("datetime"):
            self.times.append((not (self.zone["article"] or self.zone["main"]), a["datetime"]))
        if tag in VOID:
            if tag in ("br", "hr"):
                self._text("\n")
            return
        if tag in DROP or (tag == "header" and not (self.zone["article"] or self.zone["main"])) or self._chrome(tag, a):
            self.skip = [tag, 1]
            return
        if tag in ("article", "main"):
            self.zone[tag] += 1
        if tag == "h1" and self.h1 is None:
            self.h1 = []
        if tag == "pre":
            self.pre += 1
        if tag in BLOCK:
            self._text("\n\n" if tag in PARA else "\n")
        if tag == "li":
            self._text("- ")

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[0]:
                self.skip[1] -= 1
                if not self.skip[1]:
                    self.skip, self.in_ld = None, False
            return
        if tag == "title":
            self.in_title = False
            return
        if tag == "h1" and isinstance(self.h1, list):
            self.h1 = " ".join("".join(self.h1).split())
        if tag == "pre" and self.pre:
            self.pre -= 1
        if tag in BLOCK and tag not in ("li", "td", "th", "dt", "dd"):
            self._text("\n\n" if tag in PARA else "\n")
        if tag in ("article", "main") and self.zone[tag]:
            self.zone[tag] -= 1

    def handle_data(self, data):
        if self.in_ld:
            self.ld.append(data)
            return
        if self.skip:
            return
        if self.in_title:
            self.title.append(data)
            return
        if isinstance(self.h1, list):
            self.h1.append(data)
        self._text(data if self.pre else re.sub(r"\s+", " ", data))

    def text(self, zone):
        lines, out = [re.sub(r"[ \t\r\f\v\u00a0]+", " ", l).strip() for l in "".join(self.out[zone]).split("\n")], []
        for l in lines:
            if l in ("", "-") and (not out or out[-1] == ""):
                continue
            out.append("" if l == "-" else l)
        return "\n".join(out).strip()


def read_html(text, url=""):
    """{"title", "text", "words", "links", "feeds", "canonical", "meta", "ld", "times"} of one page."""
    r = Reader(url)
    try:
        r.feed(text)
        r.close()
    except Exception:
        pass
    art, main, body = r.text("article"), r.text("main"), r.text("body")
    whole = main if len(main) >= 200 else body
    body_text = art if len(art) >= 200 and len(art) * 2 >= len(whole) else whole
    h1 = r.h1 if isinstance(r.h1, str) else ""
    title = " ".join((r.meta.get("og:title") or "".join(r.title)).split())
    if h1 and (not title or h1.lower() in title.lower()):
        title = h1                                      # the heading without the site's name after it
    base = r.base or url
    return {"title": title[:300], "text": body_text, "words": len(body_text.split()), "links": [n for n in (norm(l, base) for l in r.links) if n],
            "feeds": [n for n in (norm(f, base) for f in r.feeds) if n], "canonical": norm(r.canonical, base) if r.canonical else "",
            "meta": r.meta, "ld": "".join(r.ld), "times": r.times}


def _date(p, url, known="", lastmod=""):
    """When a page was written: what a feed said, its own meta tags, its JSON-LD, a <time>, its address, a date at the
    top of its text, and last the sitemap's date (which is often only the day the site was rebuilt)."""
    if when(known):
        return when(known)
    for k in META_DATES:
        if when(p["meta"].get(k)):
            return when(p["meta"][k])
    m = re.search(r'"date(?:Published|Created)"\s*:\s*"([^"]+)"', p["ld"])
    if m and when(m.group(1)):
        return when(m.group(1))
    for _, t in sorted(p["times"], key=lambda t: t[0]):     # one inside the article before one in the page's frame
        if when(t):
            return when(t)
    m = IN_URL.search(urlsplit(url).path)
    if m:
        return when("%s-%s-%s" % (m.group(1), m.group(2), m.group(3) or "01"))
    return when(p["text"][:400], loose=True) or when(lastmod)


def _chunks(text, size=ROW_CHARS, most=50):
    """A long text in pieces of at most `size`, cut at a paragraph or a line where one is near."""
    out = []
    while len(text) > size and len(out) < most - 1:
        cut = text.rfind("\n\n", size // 2, size)
        cut = cut if cut > 0 else text.rfind("\n", size // 2, size)
        cut = cut if cut > 0 else text.rfind(" ", size // 2, size)
        cut = cut if cut > 0 else size
        out.append(text[:cut].strip())
        text = text[cut:].strip()
    return [c for c in out + [text[:size]] if c]


def _rows(sl, pid, url, title, text, ts):
    parts = _chunks(text)
    for i, c in enumerate(parts):
        yield {"id": pid + (":%d" % (i + 1) if i else ""), "src": "canvas_" + sl, "ts": ts,
               "title": title if len(parts) == 1 else "%s (part %d of %d)" % (title, i + 1, len(parts)), "text": c, "url": url}


# ---------------------------------------------------------------- feeds and sitemaps (read with patterns: no xml parser, so no entity tricks)

def is_feed(text):
    return bool(re.search(r"<(rss|feed|rdf:RDF)[\s>]", text[:3000]))


def _unwrap(s):
    s = s.strip()
    cd = re.findall(r"<!\[CDATA\[(.*?)\]\]>", s, re.S)
    return "".join(cd) if cd else html.unescape(s)


def _tag(block, names):
    for n in names:
        m = re.search(r"<%s(?:\s[^>]*)?>(.*?)</%s\s*>" % (re.escape(n), re.escape(n)), block, re.S | re.I)
        if m and m.group(1).strip():
            return _unwrap(m.group(1))
    return ""


def _plain(markup):
    r = Reader()
    try:
        r.feed(markup)
        r.close()
    except Exception:
        pass
    return r.text("body")


def _atom_link(block, rel="alternate"):
    best = ""
    for m in re.finditer(r"<link\b([^>]*)>", block, re.I):
        a = dict((k.lower(), html.unescape(v)) for k, _, v in re.findall(r"([\w:-]+)\s*=\s*([\"'])(.*?)\2", m.group(1), re.S))
        if a.get("href") and a.get("rel", "alternate") == rel:
            if rel != "alternate" or "html" in a.get("type", "html"):
                return a["href"]
            best = best or a["href"]
    return best


def parse_feed(text, base=""):
    """{"title", "site", "next", "entries": [{"title", "url", "date", "text", "full"}]} of an RSS or Atom feed."""
    first = re.search(r"<(item|entry)[\s>]", text, re.I)
    top = text[:first.start()] if first else text
    out = {"title": " ".join(_plain(_tag(top, ["title"])).split())[:200], "site": norm(_tag(top, ["link"]) or _atom_link(top), base),
           "next": norm(_atom_link(top, "next"), base) if _atom_link(top, "next") else "", "entries": []}
    for m in re.finditer(r"<(item|entry)(?:\s[^>]*)?>(.*?)</\1\s*>", text, re.S | re.I):
        b = m.group(2)
        link = _tag(b, ["link"]) or _atom_link(b)
        if not link:
            guid = _tag(b, ["guid", "id"])
            link = guid if guid.startswith(("http://", "https://")) else ""
        full = _tag(b, ["content:encoded", "content"])
        body = full or _tag(b, ["description", "summary", "media:description"])
        words = _plain(body) if "<" in body else " ".join(body.split())
        out["entries"].append({"title": " ".join(_plain(_tag(b, ["title", "media:title"])).split())[:300], "url": norm(link.strip(), base) if link else "",
                               "date": when(_tag(b, ["pubDate", "published", "dc:date", "updated", "date"])), "text": words,
                               "full": bool(full) and len(words.split()) >= 50})
    return out


def _sitemaps(web, origin, inside, deadline, limit=20000):
    """{address: lastmod} from the site's sitemaps (those robots.txt names, else /sitemap.xml), sitemap indexes followed."""
    try:
        todo = list(web.robots(origin + "/").site_maps() or [])
    except Exception:
        todo = []
    todo = deque(todo or [origin + "/sitemap.xml"])
    seen, found = set(), {}
    while todo and len(seen) < 30 and len(found) < limit and _clock() < deadline:
        sm = todo.popleft()
        if sm in seen or _host(sm) != _host(origin):
            continue
        seen.add(sm)
        try:
            got = web.get(sm, cap=10_000_000, gz=True)
        except (Refused, Blocked, Unreachable):
            continue
        if got.status != 200 or "<html" in got.text[:300].lower():
            continue
        for m in re.finditer(r"<(url|sitemap)(?:\s[^>]*)?>(.*?)</\1\s*>", got.text, re.S | re.I):
            loc = norm(_tag(m.group(2), ["loc"]), got.url)
            if not loc:
                continue
            if m.group(1).lower() == "sitemap":
                todo.append(loc)
            elif inside(loc) and len(found) < limit:
                found.setdefault(loc, _tag(m.group(2), ["lastmod"]).strip())
    return found


# ---------------------------------------------------------------- site

def _open(web, url, say):
    """The first page of a site or a feed, with the plain reason when it cannot be had."""
    host = urlsplit(url).hostname or url
    say("asking %s what it lets tools read (robots.txt)" % host)
    try:
        if not web.allowed(url):
            raise Blocked(url)
        say("reading %s" % (host + (urlsplit(url).path if urlsplit(url).path.strip("/") else "")))
        got = web.get(url)
    except Refused as e:
        raise Stop("cannot", str(e))
    except Blocked:
        raise Stop("cannot", "robots.txt on %s asks tools not to read that address, so it was not read" % host)
    except Unreachable as e:
        raise Stop("cannot", "could not read %s: %s" % (host, e))
    if got.status != 200:
        raise Stop("cannot", "%s answered %d for that address" % (host, got.status))
    if not got.text.strip():
        raise Stop("cannot", "that address is not a page of text (%s)" % (got.type or "no type given"))
    return got


def read_site(d, emit, trial, say, st, prev, first=None, web=None):
    t0, sl = _clock(), d["slug"]
    only = str((d.get("options") or {}).get("only") or "")
    cap, deadline = (TRIAL_PAGES, t0 + TRIAL_SECS) if trial else (FULL_PAGES, t0 + FULL_SECS)
    web = web or Web()
    home = first or _open(web, d["address"], say)
    if is_feed(home.text):
        return read_feed(d, emit, trial, say, st, prev, first=home, web=web)
    start = norm(home.url)
    u = urlsplit(start)
    host, origin = _host(start), "%s://%s" % (u.scheme, u.netloc)
    scope = "/" + u.path.strip("/")
    scope = os.path.dirname(scope) if "." in scope.rsplit("/", 1)[-1] else scope
    scope = "" if scope == "/" else scope

    def inside(x):
        p = urlsplit(x).path
        return _host(x) == host and (not scope or p.rstrip("/") == scope or p.startswith(scope + "/"))
    hp = read_html(home.text, start)
    if scope and not any(inside(l) and urlsplit(l).path.rstrip("/") != scope for l in hp["links"]):
        scope = os.path.dirname(scope)              # the address is one page, not a section: its neighbours are the section
        scope = "" if scope == "/" else scope
    say("looking for a sitemap")
    listed = _sitemaps(web, origin, inside, deadline)
    dates, seeds = {}, []
    for f in hp["feeds"][:2]:                       # a feed the page names: its entries are pages, each with a date
        try:
            got = web.get(f)
        except (Refused, Blocked, Unreachable):
            continue
        if got.status == 200 and is_feed(got.text):
            say("reading the feed the page names")
            for e in parse_feed(got.text, got.url)["entries"]:
                if e["url"] and inside(e["url"]):
                    dates[key(e["url"])] = e["date"]
                    seeds.append(e["url"])
    crawl = not listed
    lastmods = {key(x): lm for x, lm in listed.items()}
    prefix = only if only.startswith("/") else ""

    def wanted(x):
        if only == "all":
            return True
        return not _listing(x, scope) and (not prefix or urlsplit(x).path.startswith(prefix))
    if crawl:
        say("no sitemap: following the links from the first page")
        queue = deque(dict.fromkeys([start] + seeds))
        found = len(queue)
    else:
        urls = list(listed)
        posts = [x for x in urls if not _listing(x, scope)]
        rest = len(urls) - len(posts)
        say("the sitemap lists %d pages" % len(urls))
        if trial and not only and posts and rest >= 5 and rest * 100 >= 15 * len(urls):
            tops = {}
            for x in posts:
                segs = [s for s in urlsplit(x).path.split("/") if s]
                if len(segs) > 1:
                    tops[segs[0]] = tops.get(segs[0], 0) + 1
            top = max(tops, key=tops.get) if tops else ""
            under = " under /%s" % top if top and tops[top] * 2 >= len(posts) else ""
            q = "found %d pages on %s: %d look like posts%s, the rest are tag and index pages. read only the posts?" % (len(urls), host, len(posts), under)
            raise Stop("needs_you", q + " answer by running it again with --only posts, --only all, or --only /a/path",
                       ask={"question": q, "choices": [{"label": "only the posts", "only": "posts", "pages": len(posts)},
                                                       {"label": "every page", "only": "all", "pages": len(urls)}]})
        queue = deque(x for x in urls if wanted(x))
        found = len(urls)
    queued = {key(x) for x in queue}
    if not prev:
        st.pop("pages", None)                       # nothing kept from last time: read every page again
    pages = st.setdefault("pages", {})
    if not trial:                                   # a page read before and no longer listed: look once more; if it is gone it is kept and marked
        for pid, rows in prev.items():
            x = rows[0].get("url") or ""
            if x and key(x) not in queued and not rows[0].get("gone"):
                queued.add(key(x))
                queue.append(x)
    c = {"read": 0, "kept": 0, "same": 0, "thin": 0, "dup": 0, "blocked": 0, "failed": 0, "gone": 0, "left": 0}
    done, handled, texts, words = set(), set(), set(), []

    def reuse(pid, mark=False):
        handled.add(pid)
        for r in prev.get(pid, []):
            emit(dict(r, gone=True) if mark else r)
    while queue:
        url = queue.popleft()
        k = key(url)
        if k in done:
            continue
        if c["read"] >= cap or _clock() > deadline:
            c["left"] = 1 + len(queue)
            break
        done.add(k)
        pid, old, lastmod = _rid(sl, k), pages.get(k) or {}, lastmods.get(k, "")
        have = pid in prev
        outs = None
        if not trial and old and lastmod and old.get("lastmod") == lastmod and not crawl:
            reuse(pid)                              # the sitemap says it has not changed since it was read
            c["same"] += have
            continue
        try:
            if k == key(start):
                got = home
            else:
                if not web.allowed(url):
                    raise Blocked(url)
                say("reading page %d%s: %s" % (c["read"] + 1, "" if crawl else " of %d" % min(len(queued), cap), urlsplit(url).path[:80]))
                got = web.get(url, etag=old.get("etag", "") if not trial else "", modified=old.get("modified", "") if not trial else "")
                c["read"] += 1
        except Blocked:
            c["blocked"] += 1
            continue
        except (Refused, Unreachable):
            c["failed"] += 1
            continue
        if got.status == 304:
            reuse(pid)
            c["same"] += have
            outs = old.get("links") or []
        elif got.status in (404, 410):
            if have:
                reuse(pid, mark=True)
                c["gone"] += 1
            pages.pop(k, None)
            continue
        elif got.status != 200 or not got.text:
            c["failed"] += got.status != 200
            continue
        elif _host(got.url) != host:
            handled.add(pid)                        # it now redirects to another site
            continue
        else:
            p = read_html(got.text, got.url)
            handled.add(pid)
            outs = [l for l in dict.fromkeys(p["links"]) if inside(l) and not urlsplit(l).query and not SKIP_EXT.search(urlsplit(l).path) and len(l) < 300][:300]
            canon = key(p["canonical"]) if p["canonical"] else k
            sig = _sha(" ".join(p["text"].lower().split()))
            if not wanted(url):
                pass
            elif canon != k and canon in queued and _host(p["canonical"]) == host:
                c["dup"] += 1                       # the page says it is a copy of another one that is read too
            elif p["words"] < MIN_WORDS:
                c["thin"] += 1
            elif sig in texts:
                c["dup"] += 1
            else:
                texts.add(sig)
                for row in _rows(sl, pid, url, p["title"] or urlsplit(url).path, p["text"], _date(p, url, dates.get(k), lastmod)):
                    emit(row)
                c["kept"] += 1
                words.append(p["words"])
            pages[k] = {"etag": got.headers.get("etag", ""), "modified": got.headers.get("last-modified", ""), "lastmod": lastmod}
            if crawl:
                pages[k]["links"] = outs
        if crawl:
            for l in outs or []:
                if key(l) not in queued:
                    queued.add(key(l))
                    queue.append(l)
                    found += 1
    for pid in prev:                                # anything not looked at this time (the cap, a failure, robots) keeps what it had
        if pid not in handled:
            reuse(pid)
    notes = []
    if c["blocked"]:
        notes.append("robots.txt keeps %d page%s out, so %s not read" % (c["blocked"], "s" * (c["blocked"] > 1), "they were" if c["blocked"] > 1 else "it was"))
    if c["thin"]:
        notes.append("%d had too little text to keep" % c["thin"])
    if c["dup"]:
        notes.append("%d were copies of another page" % c["dup"])
    if c["failed"]:
        notes.append("%d did not answer" % c["failed"])
    if c["gone"]:
        notes.append("%d are gone from the site and were kept, marked gone" % c["gone"])
    if c["left"] and not trial:
        notes.append("stopped at the limit of %d pages or %d minutes; %d were not reached" % (cap, FULL_SECS // 60, c["left"]))
    if not crawl and not only and trial:
        notes.append("tag and index pages are skipped (--only all reads them too)")
    total = len(queued)
    how = "reads %s %s: %d page%s%s. tried %d, %d had enough text" % (
        host + scope, "by following its links" if crawl else "from its sitemap", total, "s" * (total != 1),
        " so far" if crawl and c["left"] else "", c["read"] + (1 if key(start) in done else 0), c["kept"])
    if trial and total > c["read"]:
        how += "; a full read of %d pages takes about %d minutes, one page at a time" % (min(total, FULL_PAGES), max(1, int(min(total, FULL_PAGES) * (DELAY + 0.6) / 60)))
    return {"how": how, "detail": "; ".join(notes), "why": "no page on %s had enough text to keep" % host,
            "stats": dict(c, found=found if crawl else len(listed), pages=total, route="links" if crawl else "sitemap",
                          median_words=sorted(words)[len(words) // 2] if words else 0, secs=round(_clock() - t0, 1), requests=web.requests)}


# ---------------------------------------------------------------- feed

def read_feed(d, emit, trial, say, st, prev, first=None, web=None, follow=True):
    t0, sl = _clock(), d["slug"]
    cap, deadline = (TRIAL_PAGES, t0 + TRIAL_SECS) if trial else (FULL_PAGES, t0 + FULL_SECS)
    web = web or Web()
    got = first or _open(web, d["address"], say)
    if not is_feed(got.text):
        if "<html" in got.text[:2000].lower() or "<body" in got.text[:4000].lower():
            return read_site(d, emit, trial, say, st, prev, first=got, web=web)     # it is a page, not a feed
        raise Stop("cannot", "that address is neither a feed nor a page")
    feed = parse_feed(got.text, got.url)
    entries, hops, nxt = list(feed["entries"]), 0, feed["next"]
    while nxt and hops < 9 and len(entries) < cap and _clock() < deadline:      # a feed in pages
        hops += 1
        try:
            more = web.get(nxt)
        except (Refused, Blocked, Unreachable):
            break
        if more.status != 200 or not is_feed(more.text):
            break
        f = parse_feed(more.text, more.url)
        entries += f["entries"]
        nxt = f["next"]
    hosts = {_host(got.url), _host(feed["site"])} - {""}
    if not prev:
        st.pop("pages", None)
    pages = st.setdefault("pages", {})
    c = {"read": 0, "kept": 0, "same": 0, "followed": 0, "blocked": 0, "failed": 0, "left": max(0, len(entries) - cap)}
    handled, words = set(), []
    say("the feed holds %d entries" % len(entries))
    for e in entries[:cap]:
        k = key(e["url"]) if e["url"] else "entry:" + _sha(e["title"] + e["date"])
        pid = _rid(sl, k)
        if pid in handled:
            continue
        sig = _sha("%s\x1f%s\x1f%s" % (e["title"], e["date"], e["text"]))
        if not trial and pid in prev and (pages.get(k) or {}).get("sig") == sig:
            handled.add(pid)
            c["same"] += 1
            for r in prev[pid]:
                emit(r)
            continue
        text, n = e["text"], len(e["text"].split())
        if follow and e["url"] and _host(e["url"]) in hosts and _clock() < deadline and (n < 50 or (not e["full"] and n < 300)):
            say("the feed has only a summary of entry %d: reading its page" % (c["kept"] + 1))
            try:                                    # only a summary in the feed: the page has the text
                pg = web.get(e["url"])
                c["read"] += 1
                if pg.status == 200 and pg.text:
                    p = read_html(pg.text, pg.url)
                    if p["words"] > n:
                        text, n = p["text"], p["words"]
                        c["followed"] += 1
            except Blocked:
                c["blocked"] += 1
            except (Refused, Unreachable):
                c["failed"] += 1
        if not (text.strip() or e["title"]):
            continue
        handled.add(pid)
        for row in _rows(sl, pid, e["url"], e["title"] or feed["title"], text or e["title"], e["date"]):
            emit(row)
        pages[k] = {"sig": sig}
        c["kept"] += 1
        words.append(n)
    for pid in prev:                                # a feed is a window: what has scrolled out of it is kept
        if pid not in handled:
            for r in prev[pid]:
                emit(r)
    notes = []
    if c["followed"]:
        notes.append("%d entries were only summaries in the feed, so their pages were read for the full text" % c["followed"])
    if c["blocked"]:
        notes.append("robots.txt keeps %d of the pages out; those entries keep the feed's summary" % c["blocked"])
    if c["left"]:
        notes.append("%d more entries than the %s reads" % (c["left"], "trial" if trial else "limit"))
    how = "reads every entry of the feed %s: %d entr%s, title, date, link and text" % (feed["title"] or _host(got.url), len(entries), "y" if len(entries) == 1 else "ies")
    return {"how": how, "detail": "; ".join(notes), "why": "the feed has no entries",
            "stats": dict(c, found=len(entries), route="feed", median_words=sorted(words)[len(words) // 2] if words else 0, secs=round(_clock() - t0, 1),
                          requests=web.requests)}


# ---------------------------------------------------------------- folder and file

TEXT_EXT = {".md", ".markdown", ".mdx", ".txt", ".text", ".rst", ".org", ".adoc", ".tex", ".csv", ".tsv"}
HTML_EXT = {".html", ".htm", ".xhtml"}
UTIL_EXT = {".rtf", ".doc", ".odt", ".webarchive"}          # macos reads these itself: /usr/bin/textutil
READ_EXT = TEXT_EXT | HTML_EXT | UTIL_EXT | {".json", ".docx", ".pdf", ".opml"}
SKIP_DIRS = {"node_modules", "__pycache__", "venv", "site-packages", "pods", "deriveddata", "bower_components"}
BUNDLES = (".app", ".framework", ".photoslibrary", ".xcodeproj", ".xcworkspace", ".musiclibrary", ".tvlibrary", ".bundle", ".lproj")
TEXTUTIL, MDLS, STRINGS = "/usr/bin/textutil", "/usr/bin/mdls", "/usr/bin/strings"
FDA = "macos is keeping context out of this folder: grant full disk access to context (system settings > privacy & security > full disk access), then try again"


def _permission(p):
    for name in ("Documents", "Desktop", "Downloads"):
        if (p + os.sep).startswith(os.path.join(HOME, name) + os.sep):
            return ("macos is keeping context out of your %s folder: allow it in system settings > privacy & security > files and folders > context > %s folder, "
                    "then try again" % (name.lower(), name.lower()))
    if "/Library/Mobile Documents" in p or "/Library/CloudStorage" in p:
        return "macos is keeping context out of your cloud drive: allow it in system settings > privacy & security > files and folders > context, then try again"
    if p.startswith("/Volumes/"):
        return "macos is keeping context off that disk: allow it in system settings > privacy & security > files and folders > context > removable volumes, then try again"
    return FDA


def _clean(t):
    """Is this the words of a document, or the insides of a file?"""
    toks = t.split()
    if len(toks) < 40 or re.search(r"\b(endobj|endstream|FlateDecode|xref)\b", t):
        return False
    good = sum(1 for w in toks if re.fullmatch(r"[\"'(\[]*[^\W\d_]{1,24}[.,;:!?'\")\]]*", w))
    return good * 10 >= len(toks) * 7


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, timeout=30, stdin=subprocess.DEVNULL).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _pdf(p):
    """A pdf's text, only when a tool already on this mac gives clean text: spotlight's copy, then the plain strings in the file."""
    for cmd in ([MDLS, "-raw", "-name", "kMDItemTextContent", p], [STRINGS, "-n", "6", p]):
        if os.path.exists(cmd[0]):
            out = _run(cmd)
            if out.strip() not in ("", "(null)") and _clean(out):
                return out
    return ""


def _docx(p):
    with zipfile.ZipFile(p) as z:
        with z.open("word/document.xml") as f:
            x = f.read(30_000_001).decode("utf-8", "replace")
    x = re.sub(r"<w:tab\b[^>]*/>", "\t", x)
    x = re.sub(r"<w:br\b[^>]*/>|</w:p>", "\n", x)
    return html.unescape(re.sub(r"<[^>]+>", "", x))


def _decode(raw):
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    if b"\x00" in raw[:8192]:
        return ""                                   # not text
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def file_text(p, ext, size):
    """(title or "", text, why not) of one file."""
    if ext == ".pdf":
        t = _pdf(p) if size <= 60_000_000 else ""
        return "", t, "" if t else "pdf"
    if ext == ".docx":
        try:
            return "", _docx(p), ""
        except (OSError, KeyError, zipfile.BadZipFile, zlib.error):
            return "", "", "unreadable"
    if ext in UTIL_EXT:
        if not os.path.exists(TEXTUTIL):
            return "", "", "no textutil"
        return "", _run([TEXTUTIL, "-convert", "txt", "-stdout", p]), ""
    if size > (200_000 if ext == ".json" else FILE_BYTES):
        return "", "", "big"
    with open(p, "rb") as f:
        text = _decode(f.read())
    if ext in HTML_EXT:
        page = read_html(text)
        return page["title"], page["text"], ""
    if ext == ".opml":                              # an export of feeds or bookmarks: one line per entry
        rows = [dict((k.lower(), html.unescape(v)) for k, _, v in re.findall(r"([\w:-]+)\s*=\s*([\"'])(.*?)\2", m, re.S)) for m in re.findall(r"<outline\b([^>]*)>", text)]
        return "", "\n".join(" ".join(x for x in (r.get("text") or r.get("title") or "", r.get("htmlurl") or r.get("url") or "", r.get("xmlurl") or "") if x) for r in rows), ""
    return "", text, ""


def _walk(root, limit=20000):
    """Readable files under root. Never leaves root: links to folders are not followed, links to files only when they stay inside."""
    real = os.path.realpath(root)
    n = 0
    for d, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x.lower() not in SKIP_DIRS and not x.lower().endswith(BUNDLES)
                         and not os.path.islink(os.path.join(d, x)))
        for f in sorted(files):
            if f.startswith(".") or os.path.splitext(f)[1].lower() not in READ_EXT:
                continue
            p = os.path.join(d, f)
            if os.path.islink(p) and not (os.path.realpath(p) + os.sep).startswith(real + os.sep):
                continue
            n += 1
            if n > limit:
                return
            yield p


def read_folder(d, emit, trial, say, st, prev):
    t0, sl, root = _clock(), d["slug"], d["address"]
    one = d["kind"] == "file"
    if not os.path.exists(root):
        raise Stop("cannot", "nothing is at %s now" % tilde(root))
    if (os.path.realpath(root) + os.sep).startswith(os.path.realpath(paths.HOME) + os.sep) or os.path.realpath(root) in ("/", os.path.realpath(HOME)):
        raise Stop("cannot", "that is context's own archive" if os.path.realpath(root) not in ("/", os.path.realpath(HOME))
                   else "that is the whole disk: point at one folder inside it")
    try:
        if one:
            with open(root, "rb") as f:
                f.read(1)
        else:
            os.listdir(root)
    except PermissionError:
        raise Stop("needs_you", _permission(root))
    except OSError as e:
        raise Stop("cannot", "could not open %s (%s)" % (tilde(root), type(e).__name__))
    if one and os.path.splitext(root)[1].lower() not in READ_EXT:
        raise Stop("cannot", "that kind of file is not text: context reads md, txt, rtf, html, csv, json, docx and pdf")
    say("listing the files in %s" % tilde(root))
    if not prev:
        st.pop("files", None)
    seen, files = st.get("files") or {}, {}
    c = {"found": 0, "kept": 0, "same": 0, "pdf": 0, "big": 0, "denied": 0, "empty": 0, "left": 0}
    kinds, words = {}, []
    deadline = t0 + (20 if trial else 1800)
    for p in ([root] if one else _walk(root)):
        c["found"] += 1
        if (trial and c["kept"] >= 300) or _clock() > deadline:
            c["left"] += 1
            continue
        rel = os.path.basename(p) if one else os.path.relpath(p, root)
        ext = os.path.splitext(p)[1].lower()
        pid = _rid(sl, rel)
        try:
            s = os.stat(p)
            stamp = [s.st_mtime_ns, s.st_size]
            if not trial and seen.get(rel) == stamp and pid in prev:
                for r in prev[pid]:
                    emit(r)                         # not touched since it was read
                files[rel] = stamp
                c["same"] += 1
                c["kept"] += 1
                continue
            title, text, why = file_text(p, ext, s.st_size)
        except PermissionError:
            c["denied"] += 1
            continue
        except OSError:
            continue
        if why in ("pdf", "big"):
            c[why] += 1
            continue
        text = text.strip()
        if not text:
            c["empty"] += 1
            continue
        if c["kept"] % 25 == 0:
            say("reading %s" % rel[:80])
        for row in _rows(sl, pid, "file://" + quote(p), title or os.path.splitext(rel)[0], text[:ROW_CHARS * 50], _iso(s.st_mtime)):
            emit(row)
        files[rel] = stamp
        kinds[ext[1:]] = kinds.get(ext[1:], 0) + 1
        c["kept"] += 1
        words.append(len(text.split()))
    if c["denied"] and not c["kept"]:
        raise Stop("needs_you", _permission(root))
    st["files"] = files
    notes = []
    if c["pdf"]:
        notes.append("pdf text could not be read without extra tools: %d pdf%s skipped" % (c["pdf"], "s" * (c["pdf"] > 1)))
    if c["big"]:
        notes.append("%d file%s over the size limit skipped" % (c["big"], "s" * (c["big"] > 1)))
    if c["denied"]:
        notes.append("macos would not open %d file%s" % (c["denied"], "s" * (c["denied"] > 1)))
    if c["left"]:
        notes.append("%d more files than the %s reads" % (c["left"], "trial" if trial else "time limit"))
    sorts = ", ".join("%d %s" % (n, k) for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])[:5])
    how = ("reads the file %s as text" % tilde(root)) if one else "reads the text files under %s, one row per file: %s" % (tilde(root), sorts or "none it can read")
    return {"how": how, "detail": "; ".join(notes), "why": notes[0] if notes else "no text file was found there",
            "stats": dict(c, route="disk", median_words=sorted(words)[len(words) // 2] if words else 0, secs=round(_clock() - t0, 1))}


# ---------------------------------------------------------------- note

def _note_blocks(text, name):
    """[(title, body)]: one per heading when the page has headings, else one per block between blank lines."""
    lines = text.replace("\r\n", "\n").split("\n")
    out = []
    if any(re.match(r"#{1,6}\s+\S", l) for l in lines):
        title, body = name, []
        for l in lines + ["# "]:
            m = re.match(r"#{1,6}\s+(.*)", l) if l.startswith("#") else None
            if m is not None:
                if "\n".join(body).strip():
                    out.append((title, "\n".join(body).strip()))
                title, body = m.group(1).strip() or name, []
            else:
                body.append(l)
    else:
        out = [(name, b.strip()) for b in re.split(r"\n\s*\n", text) if b.strip()]
    return out


def read_note(d, emit, trial, say, st, prev):
    sl, p, name = d["slug"], d["address"], d["name"]
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            text = f.read()
        mtime = os.path.getmtime(p)
    except OSError:
        raise Stop("cannot", "the page for this note is missing")
    born, now, kept, seen = st.get("born") or {}, _iso(time.time()), {}, {}
    n = 0
    for title, body in _note_blocks(text, name):
        h = _sha(title + "\x1f" + body)
        seen[h] = seen.get(h, 0) + 1
        ts = when(title, loose=True) or born.get(h) or (now if born else _iso(mtime))
        kept[h] = born.get(h) or ts                 # a block keeps the day it was first seen, however the page is edited around it
        for row in _rows(sl, _rid(sl, h, seen[h]), "file://" + quote(p), name if title == name else "%s: %s" % (name, title), body, ts):
            emit(row)
        n += 1
    st["born"] = kept
    return {"how": "your own notes about %s: a page you write or paste into, one row per heading or paragraph. add to it in the app, or with: "
                   "python3 -m ctx note \"%s\" --append \"<text>\"" % (name, name),
            "detail": "" if n else "the page is blank until you write on it", "why": "nothing is written in this note yet",
            "stats": {"found": n, "kept": n, "route": "note"}}


# ---------------------------------------------------------------- github repo or user (public rest api, no sign-in)

GH_API, GH_RAW, GH_WEB = "https://api.github.com", "https://raw.githubusercontent.com", "https://github.com"
DOC_EXT = (".md", ".mdx", ".markdown", ".rst", ".txt", ".adoc", ".org")
GH_SKIP = re.compile(r"(?i)(^|/)(node_modules|vendor|third_party|dist|build|\.github)/|(^|/)(license|licence|copying|code_of_conduct|contributing|security|requirements)[^/]*$")


def _gh(web, url, etag=""):
    """One call to github's public api. These are api hosts, not pages: robots.txt does not apply; the api's own limit does."""
    web._pause(0)
    web.requests += 1
    got = fetch(url, etag=etag, cap=8_000_000, accept="application/vnd.github+json")
    if got.status in (403, 429) and (got.headers.get("x-ratelimit-remaining") == "0" or got.headers.get("retry-after")):
        reset = got.headers.get("x-ratelimit-reset", "")
        at = time.strftime("%H:%M", time.localtime(int(reset))) if reset.isdigit() else "within the hour"
        raise Stop("needs_you", "github's limit for requests without a sign-in (60 an hour) is used up; it starts again at %s. try again then" % at)
    return got


def _json(got, kind):
    try:
        v = json.loads(got.text) if got.status == 200 else None
    except ValueError:
        v = None
    return v if isinstance(v, kind) else kind()


def read_repo(d, emit, trial, say, st, prev):
    t0, sl, web = _clock(), d["slug"], Web()
    who, _, repo = d["address"].partition("/")
    handled, words = set(), []
    c = {"found": 0, "kept": 0, "same": 0, "files": 0, "issues": 0, "repos": 0}
    if not prev:
        st.pop("pages", None)
    shas, stopped = st.setdefault("pages", {}), ""

    def keep(k, url, title, text, ts):
        pid = _rid(sl, k)
        if pid in handled or not text.strip():
            return
        handled.add(pid)
        for row in _rows(sl, pid, url, title, text.strip(), when(ts)):
            emit(row)
        c["kept"] += 1
        words.append(len(text.split()))

    def summary(m):
        bits = [m.get("description") or "", "topics: " + ", ".join(m["topics"]) if m.get("topics") else "", "language: " + m["language"] if m.get("language") else "",
                "stars: %s" % m["stargazers_count"] if m.get("stargazers_count") else "", "a fork" if m.get("fork") else ""]
        keep("repo:" + m["full_name"], m.get("html_url") or "%s/%s" % (GH_WEB, m["full_name"]), m["full_name"], "\n".join(b for b in bits if b) or m["full_name"], m.get("created_at"))

    def one(full):
        say("asking github about %s" % full)
        got = _gh(web, "%s/repos/%s" % (GH_API, full))
        if got.status == 404:
            raise Stop("cannot", "github has no public repo %s. a private repo cannot be read without a sign-in; if it is cloned on this mac, give its folder instead" % full)
        m = _json(got, dict)
        if not m.get("full_name"):
            raise Stop("cannot", "github answered %d for %s" % (got.status, full))
        summary(m)
        branch, pushed = m.get("default_branch") or "HEAD", m.get("pushed_at") or m.get("created_at")
        tree = _json(_gh(web, "%s/repos/%s/git/trees/%s?recursive=1" % (GH_API, full, quote(branch, safe=""))), dict).get("tree") or []
        docs = [t for t in tree if t.get("type") == "blob" and str(t.get("path", "")).lower().endswith(DOC_EXT) and (t.get("size") or 0) <= 500_000
                and not GH_SKIP.search(t["path"])]
        docs.sort(key=lambda t: (not t["path"].lower().startswith("readme"), t["path"].count("/"), t["path"].lower()))
        c["found"] += len(docs)
        for t in docs[:10 if trial else 200]:
            k = "file:%s:%s" % (full, t["path"])
            pid = _rid(sl, k)
            if not trial and pid in prev and shas.get(k) == t.get("sha"):
                handled.add(pid)
                c["same"] += 1
                for r in prev[pid]:
                    emit(r)
                continue
            say("reading %s" % t["path"][:80])
            web._pause(0)
            raw = fetch("%s/%s/%s/%s" % (GH_RAW, full, quote(branch), quote(t["path"])))
            if raw.status == 200 and raw.text.strip():
                keep(k, "%s/%s/blob/%s/%s" % (GH_WEB, full, quote(branch), quote(t["path"])), "%s: %s" % (full, t["path"]), raw.text, pushed)
                shas[k] = t.get("sha")
                c["files"] += 1
        owner = (m.get("owner") or {}).get("login") or full.split("/")[0]
        say("looking for the issues and pull requests %s wrote" % owner)
        for n in range(1, 2 if trial else 4):
            items = _json(_gh(web, "%s/repos/%s/issues?state=all&creator=%s&per_page=100&page=%d" % (GH_API, full, quote(owner), n)), list)
            for i in items:
                if isinstance(i, dict) and i.get("number"):
                    keep("issue:%s:%s" % (full, i["number"]), i.get("html_url") or "", "%s %s #%s: %s" % (full, "pull request" if "pull_request" in i else "issue", i["number"], i.get("title") or ""),
                         "%s\n\n%s" % (i.get("title") or "", i.get("body") or ""), i.get("created_at"))
                    c["issues"] += 1
            c["found"] += len(items)
            if len(items) < 100:
                break
    try:
        if repo:
            one(who + "/" + repo)
        else:
            say("asking github for %s's public repos" % who)
            got = _gh(web, "%s/users/%s/repos?type=owner&sort=pushed&per_page=100" % (GH_API, quote(who)))
            if got.status == 404:
                raise Stop("cannot", "github has no user or organisation named %s" % who)
            mine = [m for m in _json(got, list) if isinstance(m, dict) and m.get("full_name") and not m.get("fork")]
            c["found"] += len(mine)
            for m in mine[:8 if trial else 60]:
                summary(m)
                c["repos"] += 1
                k = "file:%s:README.md" % m["full_name"]
                web._pause(0)
                raw = fetch("%s/%s/HEAD/README.md" % (GH_RAW, m["full_name"]))
                if raw.status == 200 and raw.text.strip():
                    keep(k, "%s/%s#readme" % (GH_WEB, m["full_name"]), "%s: README.md" % m["full_name"], raw.text, m.get("pushed_at"))
                    c["files"] += 1
    except Stop as s:
        if trial or not prev:
            raise
        stopped = s.detail                          # a full read keeps what it had and says why it stopped
    except Refused as e:
        raise Stop("cannot", str(e))
    except Unreachable as e:
        if trial or not prev:
            raise Stop("cannot", "could not reach github: %s" % e)
        stopped = "could not reach github: %s" % e
    for pid in prev:
        if pid not in handled:
            for r in prev[pid]:
                emit(r)
    how = ("reads %s on github without a sign-in: its description, %d markdown and text files (readme and docs, no code) and %d issues or pull requests its owner wrote"
           % (d["address"], c["files"] + c["same"], c["issues"])) if repo else (
           "reads %s's %d public repos on github without a sign-in: each one's description and readme" % (who, c["repos"]))
    return {"how": how, "detail": stopped, "why": "nothing readable was found there",
            "stats": dict(c, route="github api", median_words=sorted(words)[len(words) // 2] if words else 0, secs=round(_clock() - t0, 1), requests=web.requests)}


# ---------------------------------------------------------------- youtube channel or playlist (its public feed; no key, no transcripts)

YT_FEED = "https://www.youtube.com/feeds/videos.xml"
YT_NOTE = "youtube's feed lists only the newest 15 videos (older ones are kept once read); transcripts are not read: youtube gives them only to its own player"


YT_VIDEO = re.compile(r'"videoId":"([\w-]{11})"(?:(?!"videoId").){0,1500}?"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"'
                      r'|"contentId":"([\w-]{11})"(?:(?!"contentId").){0,3000}?"title":\{"content":"((?:[^"\\]|\\.)*)"', re.S)


def _yt_page(d, emit, trial, say, st, prev, web, page):
    """The channel's or playlist's own page, when the feed is closed to tools: the titles it lists, and nothing more."""
    sl, t0, handled, n = d["slug"], _clock(), set(), 0
    for m in YT_VIDEO.finditer(page.text):
        vid, raw = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        try:
            title = json.loads('"%s"' % raw)
        except ValueError:
            title = raw
        pid = _rid(sl, "youtube.com/watch?v=" + vid)
        if pid in handled or not title.strip():
            continue
        handled.add(pid)
        if pid in prev:
            rows = prev[pid]                        # seen before: it keeps the day it was first seen
        else:
            rows = list(_rows(sl, pid, "https://www.youtube.com/watch?v=" + vid, title.strip(), title.strip(), "" if trial else _iso(time.time())))
        for r in rows:
            emit(r)
        n += 1
    for pid in prev:
        if pid not in handled:
            for r in prev[pid]:
                emit(r)
    if not n:
        raise Stop("cannot", "youtube's robots.txt keeps tools off its video feed, and its page for %s listed no videos a tool could read" % d["name"])
    return {"how": "reads the titles of the videos on youtube's page for %s: the newest %d" % (d["name"], n),
            "detail": "youtube's robots.txt keeps tools off its video feed, so only what its page lists is read: titles, no descriptions, no upload dates "
                      "(each video is dated the day it was first seen here), no transcripts", "why": "",
            "stats": {"found": n, "kept": n, "route": "youtube page", "secs": round(_clock() - t0, 1), "requests": web.requests}}


def read_youtube(d, emit, trial, say, st, prev):
    web = Web()
    u = urlsplit(d["address"])
    lst = re.search(r"(?:^|&)list=([\w-]+)", u.query)
    chan = re.match(r"/channel/(UC[\w-]{20,})", u.path)
    page, feed = None, ""
    if u.path.startswith(("/shorts/", "/embed/")) or (not lst and (u.path.startswith("/watch") or (u.hostname or "").endswith("youtu.be"))):
        raise Stop("cannot", "that is one video: give the address of the channel or of a playlist")
    if lst:
        feed, shown = YT_FEED + "?playlist_id=" + lst.group(1), "https://www.youtube.com/playlist?list=" + lst.group(1)
    else:
        feed, shown = (YT_FEED + "?channel_id=" + chan.group(1)) if chan else "", "%s://%s%s/videos" % (u.scheme, u.netloc, re.sub(r"/(videos|featured|streams|about)?/?$", "", u.path))
    try:
        if not feed or not web.allowed(feed):       # a handle has to be looked up on the page; a closed feed leaves only the page
            page = _open(web, shown, say)
            m = re.search(r"feeds/videos\.xml\?channel_id=(UC[\w-]{20,})", page.text) or re.search(r'"(?:channelId|externalId)"\s*:\s*"(UC[\w-]{20,})"', page.text)
            feed = feed or (YT_FEED + "?channel_id=" + m.group(1) if m else "")
            if not feed or not web.allowed(feed):
                return _yt_page(d, emit, trial, say, st, prev, web, page)
    except Refused as e:
        raise Stop("cannot", str(e))
    info = read_feed(dict(d, address=feed), emit, trial, say, st, prev, web=web, follow=False)
    info["how"] = "reads the titles and descriptions of the videos in %s from youtube's public feed" % d["name"]
    info["detail"] = "; ".join(x for x in (YT_NOTE, info.get("detail")) if x)
    return info


def read_builtin(d, emit, trial, say, st, prev):
    from . import kept                              # things already on this mac that the owner marked to keep: ctx/kept.py
    return kept.read(d, emit, trial, say, st, prev)


def read_webapp(d, emit, trial, say, st, prev):
    from . import webapp                            # a page behind the owner's sign-in, read through their own browser: ctx/webapp.py
    return webapp.read(d, emit, trial, say, st, prev)


READ = {"builtin": read_builtin, "webapp": read_webapp, "site": read_site, "feed": read_feed, "folder": read_folder, "file": read_folder, "note": read_note, "repo": read_repo, "youtube": read_youtube}


# ---------------------------------------------------------------- what was typed -> candidates (no network, no model)

FEEDISH = re.compile(r"(?i)(/(feed|rss|atom)/?$|\.(rss|atom)$|(feed|rss|atom|index)\.xml$|/feeds?/|[?&](feed|format|alt)=(rss|atom))")
NOT_TLD = {"md", "txt", "pdf", "doc", "docx", "rtf", "csv", "tsv", "json", "html", "htm", "py", "js", "ts", "zip", "png", "jpg", "jpeg", "gif", "mov", "mp4",
           "app", "xml", "yml", "yaml", "log", "plist", "sqlite", "db"}
ADDRESS = re.compile(r"(?i)^(https?://)?((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z][a-z0-9-]{1,23}|localhost|\d{1,3}(?:\.\d{1,3}){3}|\[[0-9a-f:]+\])(:\d{1,5})?([/?#]\S*)?$")
GH = re.compile(r"(?i)^(?:https?://)?(?:www\.)?github\.com/([\w.-]+)(?:/([\w.-]+))?(?:[/?#].*)?$|^git@github\.com:([\w.-]+)/([\w.-]+)$")
GH_BARE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9-]{0,38})/([\w.-]{1,100})$")
GH_NOT = {"about", "features", "topics", "marketplace", "settings", "orgs", "sponsors", "explore", "pricing", "login", "join", "notifications", "search"}
YT = re.compile(r"(?i)^(?:https?://)?(?:www\.|m\.)?(?:youtube\.com|youtu\.be)(/.*)?$")
WHAT = {"site": "the public pages of %s, read one at a time; the text of each page is kept with its date and address",
        "feed": "every entry of this feed (title, date, link, text), with the full page where the feed only has a summary",
        "folder": "the text files in %s: notes, documents and the pdfs that can be read, one row per file",
        "file": "the file %s, as text",
        "repo": "the readme, docs and markdown of %s on github, and the issues its owner wrote; no code, no sign-in",
        "youtube": "the titles and descriptions of this channel's or playlist's videos; no transcripts, youtube gives those only to its own player",
        "note": "add your own notes about '%s': a blank page you write or paste into",
        "webapp": "%s as you see it when signed in (your saves, your list), read through your own browser; no password is typed or kept"}


def _as_path(q):
    q = q.strip().strip("'\"")
    if q.startswith("file://"):
        q = unquote(q[7:])
    if not q.startswith(("/", "~")):
        return ""
    for cand in (q, q.replace("\\ ", " ").replace("\\", "")):       # a dragged path comes with its spaces escaped
        p = os.path.abspath(os.path.expanduser(cand))
        if os.path.exists(p):
            return p
    return ""


def _as_url(q):
    q = q.strip()
    m = ADDRESS.match(q)
    if not m or " " in q:
        return ""
    host = m.group(2).lower()
    if not m.group(1) and (host == "localhost" or host[0] in "[0123456789" and host.replace(".", "").isdigit() or host.rsplit(".", 1)[-1] in NOT_TLD):
        return ""
    return norm(q if m.group(1) else "https://" + q)


def _make(kind, address, name=""):
    """A source definition from a kind and an address. Not saved. Raises ValueError when the address is not of that kind."""
    if kind in ("site", "feed", "youtube", "webapp"):
        url = _as_url(address)
        if not url:
            raise ValueError("that is not a web address")
        u = urlsplit(url)
        shown = _host(url) + (u.path.rstrip("/") if u.path.strip("/") else "")
        if kind == "youtube":
            address, sl, name = url, "youtube_" + slug(re.sub(r"^/(channel/|c/|user/|playlist)?", "", u.path) + u.query.replace("list=", "")), name or shown
        elif kind == "webapp":
            address, sl, name = url, "web_" + slug(shown), name or shown
        else:
            address, sl, name = url, slug(shown), name or shown
    elif kind in ("folder", "file"):
        p = _as_path(address) or os.path.abspath(os.path.expanduser(address))
        address, sl, name = p, slug(os.path.splitext(os.path.basename(p.rstrip("/")))[0] if kind == "file" else os.path.basename(p.rstrip("/"))), name or tilde(p)
    elif kind == "repo":
        m = re.fullmatch(r"([\w.-]+)(?:/([\w.-]+))?", address.strip().strip("/"))
        if not m:
            raise ValueError("that is not a github repo or user")
        address = m.group(1) + ("/" + re.sub(r"\.git$", "", m.group(2)) if m.group(2) else "")
        sl, name = "github_" + slug(address), name or address
    elif kind == "builtin":
        from . import kept
        if address not in kept.KEPT:
            raise ValueError("no such built-in source")
        sl, name = address, kept.KEPT[address][0]
    elif kind == "note":
        name = " ".join(address.split())[:80]
        if not name:
            raise ValueError("a note needs a name")
        sl = "note_" + slug(name)
        address = os.path.join(NOTES, sl[5:] + ".md")
        return {"id": "note:" + name, "slug": sl, "kind": kind, "address": address, "name": name, "options": {}, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "enabled": True}
    else:
        raise ValueError("no such kind")
    cid = kind + ":" + address
    defs = _defs()
    if sl in defs and defs[sl].get("id") != cid:
        sl = (sl[:55] + "_" + hashlib.sha1(cid.encode("utf-8", "replace")).hexdigest()[:4])
    return {"id": cid, "slug": sl, "kind": kind, "address": address, "name": name, "options": {}, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "enabled": False}


def _row(d):
    saved = _defs().get(d["slug"]) or {}
    shown = d["name"]
    if d["kind"] == "builtin":
        from . import kept
        what = kept.KEPT[d["address"]][1]
    else:
        what = WHAT[d["kind"]] % shown if "%s" in WHAT[d["kind"]] else WHAT[d["kind"]]
    return {"id": d["id"], "name": shown, "kind": d["kind"], "what": what,
            "installed": True, "source": "canvas_" + d["slug"], "enabled": bool(saved.get("enabled")) and saved.get("id") == d["id"]}


def identify(q):
    """Candidate rows for what was typed: a path, a youtube or github address, a web address. [] when it is none of them."""
    q = " ".join(str(q).split()) if not str(q).strip().startswith(("/", "~", "file://", "'", '"')) else str(q).strip()
    out = []
    try:
        p = _as_path(q)
        if p:
            return [_row(_make("folder" if os.path.isdir(p) else "file", p))]
        if YT.match(q) and _as_url(q):
            return [_row(_make("youtube", q))]
        m = GH.match(q)
        if m and (m.group(1) or m.group(3)).lower() not in GH_NOT:
            user, repo = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
            return [_row(_make("repo", user + ("/" + repo if repo else "")))]
        url = _as_url(q)
        if url:
            out.append(_row(_make("feed" if FEEDISH.search(url) else "site", url)))
            if url.startswith("https://") and not FEEDISH.search(url):
                out.append(_row(_make("webapp", url)))          # the same address as the owner sees it signed in
        elif GH_BARE.match(q) and not os.path.exists(os.path.expanduser(q)):
            out.append(_row(_make("repo", q)))
    except ValueError:
        pass
    return out


def candidates(q, hits):
    """What `connect --search` returns: what was typed, recognised, ahead of the apps and services that match; when nothing
    matches at all, one blank note, so the panel never ends in nothing."""
    q = str(q or "").strip()
    if not q:
        return hits
    mine = identify(q)
    try:
        from . import kept                          # "starred", "bookmarks", "reading list": kept things this mac already holds
        mine += [_row(_make("builtin", k)) for k in kept.match(q)]
    except Exception:
        pass
    if not mine and not hits:
        try:
            mine = [_row(_make("note", q.strip("'\"")))]
        except ValueError:
            mine = []
    return mine + hits


# ---------------------------------------------------------------- saved sources

def _defs():
    try:
        with open(DEFS) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".part", "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(path + ".part", path)


def _put_def(d):
    with _lock:
        defs = _defs()
        defs[d["slug"]] = d
        _write(DEFS, defs)


def _state(sl):
    try:
        with open(os.path.join(STATE, sl + ".json")) as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def _part(sl):
    return os.path.join(PARTS, "canvas_%s.jsonl" % sl)


def _previous(sl):
    """{row id without its part number: [rows]} of what the last read kept."""
    out = {}
    try:
        with open(_part(sl)) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    out.setdefault(str(r["id"]).split(":")[0], []).append(r)
                except (ValueError, KeyError):
                    pass
    except OSError:
        pass
    return out


def is_id(s):
    s = str(s or "")
    return s.startswith("canvas_") or (s.partition(":")[0] in KINDS and ":" in s)


def _resolve(cid):
    """The definition an id names: a saved one, or a new one made from "<kind>:<address>" or from what was typed."""
    cid = str(cid or "").strip()
    defs = _defs()
    s = cid[7:] if cid.startswith("canvas_") else cid
    if s in defs:
        return dict(defs[s])
    for d in defs.values():
        if d.get("id") == cid:
            return dict(d)
    kind, _, addr = cid.partition(":")
    if kind in KINDS and addr:
        d = _make(kind, addr)
        return dict(defs[d["slug"]]) if defs.get(d["slug"], {}).get("id") == d["id"] else d
    for c in identify(cid):
        return _resolve(c["id"])
    raise ValueError("nothing by that name: give a web address, a path, or note:<name>")


def resolve(a):
    """The canvas id for what was typed after `connect`, or "" when it is not for this file."""
    if is_id(a):
        return a
    got = identify(a)
    return got[0]["id"] if got else ""


def enabled():
    return [sl for sl, d in _defs().items() if d.get("enabled") and d.get("kind") in READ]


def due(tier, now=None):
    """The canvas sources a tier reads: files and notes every fast tick, sites and feeds once a day, repos once a week
    (they ride the daily tick on the day they fall due)."""
    now, out = now or time.time(), []
    for sl, d in _defs().items():
        if not d.get("enabled") or d.get("kind") not in READ:
            continue
        t = TIER.get(d["kind"], "daily")
        if t == tier or (tier == "daily" and t == "weekly" and now - (_state(sl).get("read_at") or 0) >= 7 * 86400):
            out.append("canvas_" + sl)
    return out


def reader(sl):
    """A collect-style source: fn(days, out) -> rows. Keeps what the last read had for anything it could not look at again."""
    def fn(days, out):
        from .collect import put, note as tell
        d = _defs().get(sl)
        if not d or d.get("kind") not in READ:
            raise FileNotFoundError("this source was removed")
        st, prev, n = _state(sl), _previous(sl), [0]

        def emit(row):
            put(out, row)
            n[0] += 1
        try:
            info = READ[d["kind"]](d, emit, False, tell, st, prev)
        except Stop as s:
            raise (PermissionError if s.state == "needs_you" else FileNotFoundError)(s.detail)
        if not n[0]:
            raise FileNotFoundError(info.get("why") or "read nothing")
        st["read_at"] = time.time()
        _write(os.path.join(STATE, sl + ".json"), st)
        with _lock:
            defs = _defs()
            if sl in defs:
                defs[sl]["last"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "rows": n[0], "note": info.get("detail", ""), "stats": info.get("stats", {})}
                _write(DEFS, defs)
        return n[0]
    return fn


def _splice(sl, keep=True):
    """Take this source's rows out of docs.jsonl and, when keep, put its current part back in. The other sources' rows are
    not touched and nothing else is read."""
    needle = ('"src": "canvas_%s"' % sl).encode()
    try:
        with open(paths.DOCS + ".canvas", "wb") as out:
            try:
                with open(paths.DOCS, "rb") as f:
                    for line in f:
                        if needle not in line:
                            out.write(line if line.endswith(b"\n") else line + b"\n")
            except OSError:
                pass
            if keep and os.path.exists(_part(sl)):
                with open(_part(sl), "rb") as f:
                    out.write(f.read())
        os.replace(paths.DOCS + ".canvas", paths.DOCS)
    except OSError:
        pass


def _table():
    if "ctx.collect" in sys.modules:
        try:
            sys.modules["ctx.collect"].load_canvas()
        except Exception:
            pass


def _listed(d):
    last = d.get("last") or {}
    return {"id": d["id"], "source": "canvas_" + d["slug"], "name": d["name"], "kind": d["kind"], "how": d.get("how", ""),
            "address": tilde(d["address"]), "options": d.get("options") or {},
            "rows": last.get("rows", d.get("rows", 0)), "since": d.get("since", ""), "created": d["created"], "enabled": bool(d.get("enabled")),
            "tier": TIER.get(d["kind"], "daily"), "last": last}


def listing():
    return [_listed(d) for d in _defs().values()]


def enable(cid, on=True, only=None):
    """Save the source and switch it on (or off). It is read at its tier from then on; `collect-one canvas_<slug>` reads it now."""
    d = _resolve(cid)
    if d["kind"] == "note":
        _note_file(d)
    if only:
        d.setdefault("options", {})["only"] = only
    d["enabled"] = bool(on)
    _put_def(d)
    _table()
    _splice(d["slug"], keep=bool(on))
    return dict(_listed(d), next="python3 -m ctx collect-one canvas_%s" % d["slug"] if on else "")


def remove(cid):
    """Forget the source: its definition, what its reads remembered and its rows. A note's own page is kept."""
    d = _resolve(cid)
    with _lock:
        defs = _defs()
        defs.pop(d["slug"], None)
        _write(DEFS, defs)
    for p in (os.path.join(STATE, d["slug"] + ".json"), _part(d["slug"])):
        try:
            os.remove(p)
        except OSError:
            pass
    _table()
    _splice(d["slug"], keep=False)
    out = {"id": d["id"], "source": "canvas_" + d["slug"], "removed": True}
    if d["kind"] == "note" and os.path.exists(d["address"]):
        out["kept"] = tilde(d["address"])
    return out


# ---------------------------------------------------------------- connect: one bounded trial

def connect(cid, only=None, say=None):
    """Try the source once, within the trial's limits, and say honestly what came of it. Nothing is written to the archive."""
    say = say or (lambda phase: print("@" + json.dumps({"phase": phase}), flush=True))
    try:
        d = _resolve(cid)
    except ValueError as e:
        return {"id": str(cid), "name": str(cid), "kind": "", "state": "cannot", "how": "", "sample": {"rows": 0, "since": ""}, "detail": str(e)}
    if only:
        d.setdefault("options", {})["only"] = only

    def res(state, how="", rows=0, since="", detail="", **more):
        return dict({"id": d["id"], "name": d["name"], "kind": d["kind"], "source": "canvas_" + d["slug"], "state": state, "how": how,
                     "sample": {"rows": rows, "since": since}, "detail": detail}, **more)
    if d["kind"] not in READ:
        return res("cannot", detail="that kind of source is not built yet")
    if d["kind"] == "note":
        _note_file(d)
    got = []
    try:
        if d["kind"] == "webapp":
            from . import webapp
            return webapp.connect(d, say, res)
        info = READ[d["kind"]](d, got.append, True, say, {}, {})
    except Stop as s:
        more = {"ask": s.ask} if s.ask else {}
        if d["kind"] == "site" and s.state == "cannot" and d["address"].startswith("https://") and re.search(r"answered (401|403)", s.detail):
            more["alt"] = "webapp:" + d["address"]  # it wants a sign-in: the same page can be tried through their browser
            return res(s.state, detail=s.detail + ". if it needs your sign-in, it can be read through your own browser instead", **more)
        return res(s.state, detail=s.detail, **more)
    dated = sorted(r["ts"][:7] for r in got if len(r.get("ts") or "") >= 7)
    since = dated[0] if dated else ""
    if not got and d["kind"] == "builtin":          # it can be read and is empty today: it may be switched on and fills when something is kept
        return res("ready", info["how"], 0, "", info.get("detail", ""), stats=info.get("stats", {}))
    if not got and d["kind"] != "note":
        return res("cannot", detail="; ".join(x for x in (info.get("why"), info.get("detail")) if x), stats=info.get("stats", {}))
    d.update(how=info["how"], rows=len(got), since=since)
    if d["kind"] in ("site", "feed") and info.get("stats", {}).get("route") == "feed":
        d["kind"] = "feed"                         # what was typed as a site turned out to be a feed: remember it as one
    now = _defs().get(d["slug"]) or {}             # a trial takes a while: if it was switched on meanwhile, the trial must not switch it off again
    if "enabled" in now:
        d["enabled"] = now["enabled"]
    if now.get("options") and not d.get("options"):
        d["options"] = now["options"]
    _put_def(d)
    _table()
    return res("ready", info["how"], len(got), since, info.get("detail", ""), stats=info.get("stats", {}))


# ---------------------------------------------------------------- notes: write, paste, read back

def _note_file(d):
    if not os.path.exists(d["address"]):
        os.makedirs(NOTES, exist_ok=True)
        with open(d["address"], "w", encoding="utf-8") as f:
            f.write("")


def note(name, text=None, mode="append"):
    """The owner's own page about something. With text: add it to the page (or replace the page), then read the page into
    the archive at once. Returns the page as it now is."""
    import contextlib, io
    d = _resolve(name if str(name).startswith(("note:", "canvas_note_")) else "note:" + str(name))
    if d["kind"] != "note":
        raise ValueError("that is not a note")
    _note_file(d)
    d["enabled"] = True
    _put_def(d)
    if text is not None and (str(text).strip() or mode == "replace"):
        with open(d["address"], encoding="utf-8", errors="replace") as f:
            cur = f.read()
        new = str(text).strip() + "\n" if mode == "replace" else (cur.rstrip() + "\n\n" if cur.strip() else "") + str(text).strip() + "\n"
        with open(d["address"] + ".part", "w", encoding="utf-8") as f:
            f.write(new)
        os.replace(d["address"] + ".part", d["address"])
    _table()
    rows = 0
    try:
        from . import collect
        collect.load_canvas()
        with contextlib.redirect_stdout(io.StringIO()):
            st = collect.collect_one("canvas_" + d["slug"], join=False)
        rows = 0 if st.get("skipped") else st.get("rows", 0)
        with open(d["address"], encoding="utf-8", errors="replace") as f:
            blank = not f.read().strip()
        if blank:                                   # the page was emptied: its old rows go
            rows = 0
            try:
                os.remove(_part(d["slug"]))
            except OSError:
                pass
        _splice(d["slug"])
    except Exception:
        pass
    with open(d["address"], encoding="utf-8", errors="replace") as f:
        body = f.read()
    return {"id": d["id"], "source": "canvas_" + d["slug"], "name": d["name"], "path": tilde(d["address"]), "text": body, "rows": rows}


def note_main(argv):
    if not argv or argv[0].startswith("-"):
        raise SystemExit('usage: python3 -m ctx note "<name>" [--append "<text>" | --file <path> | text on stdin] [--replace]')
    name, rest, text = argv[0], argv[1:], None
    if "--append" in rest and rest.index("--append") + 1 < len(rest):
        text = rest[rest.index("--append") + 1]
    elif "--file" in rest and rest.index("--file") + 1 < len(rest):
        with open(os.path.expanduser(rest[rest.index("--file") + 1]), encoding="utf-8", errors="replace") as f:
            text = f.read()
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    print(json.dumps(note(name, text, "replace" if "--replace" in rest else "append"), ensure_ascii=False))


def main(argv):
    """The canvas half of `ctx connect`. connect.py hands over when the id is one of ours."""
    a = argv[0] if argv else ""
    only = argv[argv.index("--only") + 1] if "--only" in argv and argv.index("--only") + 1 < len(argv) else None
    arg = argv[1] if len(argv) > 1 else ""
    try:
        if a in ("--enable", "--disable"):
            out = enable(resolve(arg) or arg, a == "--enable", only)
        elif a == "--remove":
            out = remove(resolve(arg) or arg)
        else:
            out = connect(resolve(a) or a, only)
    except ValueError as e:
        raise SystemExit(str(e))
    print(json.dumps(out, ensure_ascii=False), flush=True)
