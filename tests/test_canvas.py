"""Blank-canvas sources: a website, a feed, a folder, a file, the owner's own notes. Every page and file here is made up.

The website is a tiny server on this mac. canvas.py refuses addresses on this mac, so the tests switch on the one flag
that lets loopback through (and one test checks that without it the server is refused).
"""
import io, json, os, shutil, subprocess, sys, tempfile, threading, time, unittest, zipfile
from tests import files as _f
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from tests import fixture
from ctx import canvas, collect, connect, paths, serve

WORDS = "the lantern keeper walked along the harbour wall counting gulls and thinking about clay glaze kiln shelves tide tables and warm bread".split()


def prose(seed, n=120):
    return " ".join(WORDS[(seed * 7 + i * (seed + 3)) % len(WORDS)] for i in range(n)) + " marker%d." % seed


def page(title, body, head="", pre=""):
    return ("<!doctype html><html><head><title>%s | the harbour log</title>%s</head><body><header><a href='/'>the harbour log</a></header>"
            "<nav><a href='/'>home</a> <a href='/blog/'>blog</a> <a href='/tags/clay'>clay</a> menuword</nav>%s"
            "<main><article><h1>%s</h1>%s</article></main><footer>footerword all rights kept</footer>"
            "<script>var x = 'scriptword';</script><style>.a{color:red}</style></body></html>") % (title, head, pre, title, body)


class Site:
    """A made-up personal site. `pages` maps a path to (body, content type). Counts what was asked for."""
    def __init__(self, sitemap=True):
        self.asked, self.heads, self.gone, self.version = [], [], set(), {}
        site = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                site.asked.append(self.path)
                site.heads.append(dict(self.headers))
                body, ctype = site.pages().get(self.path, (None, ""))
                if body is None or self.path in site.gone:
                    self.send_response(404)
                    self.end_headers()
                    return
                if body.startswith("->"):
                    self.send_response(302)
                    self.send_header("Location", body[2:])
                    self.end_headers()
                    return
                tag = '"v%d-%d"' % (site.version.get(self.path, 0), len(body))
                if self.headers.get("If-None-Match") == tag:
                    self.send_response(304)
                    self.end_headers()
                    return
                data = body.encode()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("ETag", tag)
                self.send_header("Set-Cookie", "session=abc")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        self.sitemap = sitemap
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    def pages(self):
        u, v = self.url, self.version
        posts = {
            "/blog/kiln-notes": page("kiln notes", "<p>%s</p>" % prose(1 + v.get("/blog/kiln-notes", 0)), '<meta property="article:published_time" content="2021-03-04T10:00:00+02:00">'),
            "/blog/tide-tables": page("tide tables", "<p>posted <time datetime='2022-07-09'>july 9</time></p><p>%s</p>" % prose(2)),
            "/blog/gull-count": page("gull count", "<p>%s</p>" % prose(3), '<script type="application/ld+json">{"@type":"BlogPosting","datePublished":"2023-01-15T08:00:00Z"}</script>'),
            "/blog/2020/11/30/warm-bread": page("warm bread", "<p>%s</p>" % prose(4)),
            "/blog/harbour-wall": page("harbour wall", "<p>February 3, 2019</p><p>%s</p>" % prose(5)),
            "/blog/glaze": page("glaze", "<p>%s</p>" % prose(6)),
            "/blog/glaze-again": page("glaze", "<p>%s</p>" % prose(6)),                       # the same words as /blog/glaze
            "/blog/stub": page("stub", "<p>only a few words here</p>"),
            "/private/diary": page("diary", "<p>%s</p>" % prose(7)),
        }
        tags = {"/tags/%s" % t: page("tag " + t, "<ul>" + "".join("<li><a href='%s'>%s</a></li>" % (p, p) for p in posts) + "</ul>") for t in ("clay", "sea", "bread", "birds", "walls", "tides")}
        out = {k: (b, "text/html; charset=utf-8") for k, b in list(posts.items()) + list(tags.items())}
        out["/"] = (page("home", "<p>welcome</p>" + "".join("<a href='%s'>x</a> " % p for p in list(posts) + list(tags)) + "<a href='/blog/kiln-notes?share=1'>s</a> <a href='/photo.jpg'>p</a>"
                         " <a href='https://example.org/elsewhere'>out</a>", '<link rel="alternate" type="application/rss+xml" href="/feed.xml">'), "text/html")
        out["/robots.txt"] = ("User-agent: *\nDisallow: /private/\n" + ("Sitemap: %s/sitemap.xml\n" % u if self.sitemap else ""), "text/plain")
        out["/photo.jpg"] = ("not really a photo", "image/jpeg")
        out["/old"] = ("->/blog/glaze", "")
        out["/feed.xml"] = ("<?xml version='1.0'?><rss version='2.0'><channel><title>the harbour log</title><link>%s/</link>" % u + "".join(
            "<item><title>%s</title><link>%s%s</link><pubDate>%s</pubDate><description><![CDATA[<p>a short summary of %s &amp; more</p>]]></description></item>" % (t, u, p, d, t)
            for t, p, d in (("kiln notes", "/blog/kiln-notes", "Thu, 04 Mar 2021 08:00:00 GMT"), ("tide tables", "/blog/tide-tables", "Sat, 09 Jul 2022 12:00:00 GMT"),
                            ("the diary", "/private/diary", "Sun, 01 Jan 2023 12:00:00 GMT"))) + "</channel></rss>", "application/rss+xml")
        if self.sitemap:
            out["/sitemap.xml"] = ("<sitemapindex><sitemap><loc>%s/sitemap-posts.xml</loc></sitemap><sitemap><loc>%s/sitemap-tags.xml</loc></sitemap></sitemapindex>" % (u, u), "application/xml")
            out["/sitemap-posts.xml"] = ("<urlset>" + "".join("<url><loc>%s%s</loc>%s</url>" % (u, p, "<lastmod>2024-02-0%d</lastmod>" % (1 + v.get(p, 0)) if p == "/blog/glaze" else "")
                                                              for p in posts if p not in self.gone or p == "/blog/gull-count") + "</urlset>", "text/xml")
            out["/sitemap-tags.xml"] = ("<urlset>" + "".join("<url><loc>%s%s</loc></url>" % (u, p) for p in tags) + "</urlset>", "text/xml")
        for i in range(200):                        # a chain of pages with no end in sight, for the caps
            out["/chain/%d" % i] = (page("link %d" % i, "<p>%s</p><a href='/chain/%d'>next</a> <a href='/chain/%d?again=1'>loop</a>" % (prose(20 + i), i + 1, i)), "text/html")
        return out


class Base(unittest.TestCase):
    def setUp(self):
        self.was = (canvas.ALLOW_LOOPBACK, canvas.DELAY)
        canvas.ALLOW_LOOPBACK, canvas.DELAY = True, 0
        self.said = []
        self.addCleanup(lambda: setattr(canvas, "ALLOW_LOOPBACK", self.was[0]) or setattr(canvas, "DELAY", self.was[1]))
        self.addCleanup(self.wipe)

    def wipe(self):
        for d in list(canvas._defs().values()):
            canvas.remove(d["id"])

    def site(self, **kw):
        s = Site(**kw)
        self.addCleanup(s.close)
        return s

    def trial(self, cid, only=None):
        return canvas.connect(cid, only, say=self.said.append)

    def read(self, d):
        """A full read of a definition into a list, with the state and rows a second read would be handed."""
        rows, st = [], {}
        info = canvas.READ[d["kind"]](d, rows.append, False, self.said.append, st, {})
        return rows, st, info


class Recognise(Base):
    def kinds(self, q):
        return [(c["kind"], c["id"]) for c in connect.search_all(q)]

    def test_each_kind_is_recognised_from_what_was_typed(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        os.mkdir(os.path.join(tmp, "my writing"))
        _f.write("x", os.path.join(tmp, "one.md"), "w")
        self.assertEqual(self.kinds("example.com")[0], ("site", "site:https://example.com/"))
        self.assertEqual(self.kinds("https://example.com/blog")[0], ("site", "site:https://example.com/blog"))
        self.assertEqual(self.kinds("https://example.com/feed.xml")[0][0], "feed")
        self.assertEqual(self.kinds("example.com/blog/rss")[0][0], "feed")
        self.assertEqual(self.kinds(os.path.join(tmp, "my writing"))[0], ("folder", "folder:" + os.path.join(tmp, "my writing")))
        self.assertEqual(self.kinds(os.path.join(tmp, "my\\ writing"))[0][0], "folder")             # dragged in, spaces escaped
        self.assertEqual(self.kinds("'%s'" % os.path.join(tmp, "one.md"))[0][0], "file")
        self.assertEqual(self.kinds("github.com/ada/engine")[0], ("repo", "repo:ada/engine"))
        self.assertEqual(self.kinds("ada/engine")[0][0], "repo")
        self.assertEqual(self.kinds("https://www.youtube.com/@adalovelace")[0][0], "youtube")
        self.assertEqual(self.kinds("a thing with no home zzqx"), [("note", "note:a thing with no home zzqx")])
        for c in connect.search_all("example.com") + connect.search_all("zzqx nothing"):
            self.assertTrue(all(k in c for k in ("id", "name", "kind", "what", "installed")), c)
            self.assertIs(c["installed"], True)
        self.assertIn("add your own notes about 'zzqx nothing'", connect.search_all("zzqx nothing")[0]["what"])

    def test_not_an_address(self):
        self.assertEqual(canvas.identify("notes.md"), [])                   # a file name, not a domain
        self.assertEqual(canvas.identify("localhost:8000"), [])             # this mac, and no scheme
        self.assertEqual(canvas.identify("two words.com here"), [])
        self.assertEqual(canvas.identify("/no/such/path/anywhere"), [])
        self.assertTrue(canvas.is_id("site:https://example.com/") and canvas.is_id("canvas_x") and not canvas.is_id("whatsapp"))


class Pages(Base):
    def test_a_page_is_read_without_its_frame(self):
        p = canvas.read_html(page("kiln notes", "<p>first para &amp; more</p><ul><li>one</li><li>two</li></ul><pre>a\n  b</pre><aside>asideword</aside>"), "http://example.com/x")
        self.assertEqual(p["title"], "kiln notes")
        self.assertIn("first para & more", p["text"])
        self.assertIn("- one\n- two", p["text"])
        for junk in ("menuword", "footerword", "scriptword", "color:red", "asideword", "the harbour log"):
            self.assertNotIn(junk, p["text"])
        self.assertIn("http://example.com/tags/clay", p["links"])           # a menu's links still count as links

    def test_dates(self):
        d = lambda body, head="", url="http://example.com/a", **kw: canvas._date(canvas.read_html(page("t", body, head), url), url, **kw)
        self.assertEqual(d("x", '<meta property="article:published_time" content="2021-03-04T10:00:00+02:00">'), "2021-03-04T08:00:00Z")
        self.assertEqual(d("<time datetime='2022-07-09'>x</time>"), "2022-07-09T12:00:00Z")
        self.assertEqual(d("x", '<script type="application/ld+json">{"datePublished": "2023-01-15T08:00:00Z"}</script>'), "2023-01-15T08:00:00Z")
        self.assertEqual(d("x", url="http://example.com/2020/11/30/warm-bread"), "2020-11-30T12:00:00Z")
        self.assertEqual(d("<p>February 3, 2019</p>"), "2019-02-03T12:00:00Z")
        self.assertEqual(d("<p>3rd Feb 2019</p>"), "2019-02-03T12:00:00Z")
        self.assertEqual(d("x", lastmod="2024-02-01"), "2024-02-01T12:00:00Z")
        self.assertEqual(d("x", known="Thu, 04 Mar 2021 08:00:00 GMT"), "2021-03-04T08:00:00Z")
        self.assertEqual(d("x"), "")
        self.assertEqual(canvas.when("1066-10-14"), "")
        self.assertEqual(canvas.when("not a date"), "")

    def test_long_text_is_cut_into_parts(self):
        rows = list(canvas._rows("s", "Kabc", "u", "long one", ("word " * 30 + "\n\n") * 400, "2024-01-01T12:00:00Z"))
        self.assertGreater(len(rows), 2)
        self.assertEqual([r["id"] for r in rows[:2]], ["Kabc", "Kabc:2"])
        self.assertIn("(part 2 of %d)" % len(rows), rows[1]["title"])
        self.assertTrue(all(len(r["text"]) <= canvas.ROW_CHARS for r in rows))


class Safety(Base):
    def test_the_switch_that_lets_tests_reach_this_mac_works_only_in_a_test_archive(self):
        on = {"CTX_CANVAS_TEST_LOOPBACK": "1"}
        self.assertTrue(canvas._test_loopback(on, os.path.join(tempfile.gettempdir(), "ctx-made-up")))
        self.assertFalse(canvas._test_loopback(on, "/Users/someone/.context/v2"))
        self.assertFalse(canvas._test_loopback(on, "/"))
        self.assertFalse(canvas._test_loopback({}, tempfile.gettempdir() + "/x"))

    def test_this_mac_and_the_local_network_are_refused(self):
        s = self.site()
        canvas.ALLOW_LOOPBACK = False
        with self.assertRaises(canvas.Refused):
            canvas.fetch(s.url + "/")
        for bad in ("http://10.0.0.1/", "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data", "http://[::1]/", "http://0.0.0.0/",
                    "http://[::ffff:127.0.0.1]/", "http://100.64.0.1/", "ftp://example.com/", "file:///etc/hosts", "http://user:pw@example.com/"):
            with self.assertRaises(canvas.Refused, msg=bad):
                canvas.fetch(bad)
        self.assertEqual(s.asked, [])
        r = self.trial("site:" + s.url + "/")
        self.assertEqual(r["state"], "cannot")
        self.assertIn("local network", r["detail"])
        self.assertEqual(s.asked, [])

    def test_loopback_flag_lets_only_loopback_through(self):
        with self.assertRaises(canvas.Refused):
            canvas.fetch("http://192.168.1.1/")

    def test_no_cookie_is_ever_sent_and_only_text_is_read(self):
        s = self.site()
        canvas.fetch(s.url + "/")
        canvas.fetch(s.url + "/blog/glaze")                                 # the first answer set a cookie
        self.assertTrue(all("Cookie" not in h and "Authorization" not in h for h in s.heads))
        self.assertTrue(all(h["User-Agent"].startswith("context-reader/") for h in s.heads))
        got = canvas.fetch(s.url + "/photo.jpg")
        self.assertEqual((got.status, got.text), (200, ""))
        self.assertEqual(canvas.fetch(s.url + "/old").url, s.url + "/blog/glaze")      # a redirect is followed by hand


class Website(Base):
    def test_the_one_question_then_only_the_posts(self):
        s = self.site()
        r = self.trial("site:" + s.url + "/")
        self.assertEqual(r["state"], "needs_you")
        self.assertIn("found 15 pages", r["detail"])
        self.assertIn("9 look like posts under /blog", r["detail"])
        self.assertEqual([c["only"] for c in r["ask"]["choices"]], ["posts", "all"])
        self.assertFalse(any(a.startswith("/blog/") for a in s.asked))      # nothing was read to ask the question
        r = self.trial("site:" + s.url + "/", "posts")
        self.assertEqual(r["state"], "ready", r)
        self.assertEqual(r["sample"]["rows"], 6)                            # nine posts: one blocked, one a stub, one a copy
        self.assertEqual(r["sample"]["since"], "2019-02")
        self.assertIn("from its sitemap", r["how"])
        self.assertIn("robots.txt keeps 1 page out", r["detail"])
        self.assertIn("1 had too little text", r["detail"])
        self.assertIn("1 were copies", r["detail"])
        self.assertNotIn("/private/diary", s.asked)
        self.assertFalse(any(a.startswith("/tags/") for a in s.asked))
        self.assertTrue(any("reading page" in x for x in self.said))
        self.assertEqual(r["source"], "canvas_" + canvas._resolve(r["id"])["slug"])

    def test_a_mac_that_slept_mid_read_has_not_run_out_of_time(self):
        s = self.site()
        real, jumps = time.time, [0]

        def wall():                         # the wall clock leaps ten minutes whenever it is looked at, as it does across a sleep
            jumps[0] += 600
            return real() + jumps[0]
        with mock.patch.object(canvas.time, "time", wall):
            r = self.trial("site:" + s.url + "/", "posts")
        self.assertEqual((r["state"], r["sample"]["rows"]), ("ready", 6), r)
        self.assertLess(r["stats"]["secs"], 90)

    def test_every_page_and_a_path(self):
        s = self.site()
        self.assertEqual(self.trial("site:" + s.url + "/", "all")["stats"]["read"], 14)        # all but the one robots keeps out
        r = self.trial("site:" + s.url + "/", "/blog/2020")
        self.assertEqual((r["state"], r["sample"]["rows"], r["sample"]["since"]), ("ready", 1, "2020-11"))

    def test_rows_and_dates(self):
        s = self.site()
        d = canvas._make("site", s.url + "/")
        d["options"] = {"only": "posts"}
        rows, st, info = self.read(d)
        by = {r["url"].rsplit("/", 1)[-1]: r for r in rows}
        self.assertEqual(sorted(by), ["glaze", "gull-count", "harbour-wall", "kiln-notes", "tide-tables", "warm-bread"])
        self.assertEqual(by["kiln-notes"]["ts"], "2021-03-04T08:00:00Z")    # the feed's date and the meta tag agree
        self.assertEqual(by["tide-tables"]["ts"], "2022-07-09T12:00:00Z")
        self.assertEqual(by["gull-count"]["ts"], "2023-01-15T08:00:00Z")
        self.assertEqual(by["warm-bread"]["ts"], "2020-11-30T12:00:00Z")
        self.assertEqual(by["harbour-wall"]["ts"], "2019-02-03T12:00:00Z")
        self.assertEqual(by["glaze"]["ts"], "2024-02-01T12:00:00Z")         # only the sitemap knows
        r = by["glaze"]
        self.assertEqual((r["title"], r["src"], r["id"][0]), ("glaze", "canvas_" + d["slug"], "K"))
        self.assertIn("marker6", r["text"])
        self.assertNotIn("menuword", r["text"])
        self.assertTrue(120 <= info["stats"]["median_words"] <= 125)

    def test_without_a_sitemap_the_links_are_followed_and_the_trial_stops_at_its_cap(self):
        s = self.site(sitemap=False)
        r = self.trial("site:" + s.url + "/chain/0")
        self.assertEqual(r["state"], "ready", r)
        self.assertIn("following its links", r["how"])
        chain = [a for a in s.asked if a.startswith("/chain/")]
        self.assertEqual(len(chain), canvas.TRIAL_PAGES + 1)                # the first page, then the cap
        self.assertEqual(len(chain), len(set(chain)))                       # no page twice
        self.assertFalse(any("?" in a for a in s.asked))                    # no address with a query is followed
        self.assertFalse(any(a.startswith("/blog") for a in s.asked))       # it stays under the path it was given

    def test_a_crawl_from_the_home_page(self):
        s = self.site(sitemap=False)
        canvas.TRIAL_PAGES, was = 25, canvas.TRIAL_PAGES
        self.addCleanup(setattr, canvas, "TRIAL_PAGES", was)
        r = self.trial("site:" + s.url + "/")
        self.assertEqual(r["state"], "ready", r)
        self.assertEqual(r["sample"]["rows"], 6)
        self.assertNotIn("/private/diary", s.asked)
        self.assertNotIn("/photo.jpg", s.asked)
        self.assertEqual(r["stats"]["blocked"], 1)

    def test_a_second_read_asks_only_for_what_changed_and_keeps_what_is_gone(self):
        s = self.site()
        d = canvas._make("site", s.url + "/")
        d["options"] = {"only": "posts"}
        rows, st, _ = self.read(d)
        prev = {}
        for r in rows:
            prev.setdefault(r["id"].split(":")[0], []).append(r)
        del s.asked[:], s.heads[:]
        s.version["/blog/kiln-notes"] = 1                                   # rewritten
        s.gone.add("/blog/tide-tables")                                     # taken down, and out of the sitemap
        s.gone.add("/blog/gull-count")                                      # taken down, still in the sitemap
        again = []
        info = canvas.read_site(d, again.append, False, self.said.append, st, prev)
        by = {r["url"].rsplit("/", 1)[-1]: r for r in again}
        self.assertEqual(len(by), 6)
        self.assertNotIn("/blog/glaze", s.asked)                            # its sitemap date did not move: not asked for at all
        asked = dict(zip(s.asked, s.heads))
        self.assertIn("If-None-Match", asked["/blog/2020/11/30/warm-bread"])           # asked for only if changed
        self.assertEqual(by["warm-bread"], prev[again[[r["url"] for r in again].index(by["warm-bread"]["url"])]["id"]][0])
        self.assertIn("marker2.", by["kiln-notes"]["text"])                 # the new words
        self.assertTrue(by["tide-tables"].get("gone") and by["gull-count"].get("gone"))
        self.assertIn("marker2", by["tide-tables"]["text"])                 # gone from the site, kept here
        self.assertFalse(by["glaze"].get("gone"))
        self.assertEqual(info["stats"]["gone"], 2)

    def test_a_site_that_is_down_keeps_nothing_new_and_says_so(self):
        s = self.site()
        d = canvas._make("site", s.url + "/")
        s.close()
        with self.assertRaises(canvas.Stop) as e:
            self.read(d)
        self.assertEqual(e.exception.state, "cannot")
        self.assertIn("could not read 127.0.0.1", e.exception.detail)


class Feed(Base):
    def test_summaries_are_followed_to_the_page(self):
        s = self.site()
        r = self.trial("feed:" + s.url + "/feed.xml")
        self.assertEqual((r["state"], r["sample"]["rows"], r["sample"]["since"]), ("ready", 3, "2021-03"), r)
        self.assertIn("2 entries were only summaries", r["detail"])
        self.assertIn("robots.txt keeps 1", r["detail"])
        d = canvas._resolve("feed:" + s.url + "/feed.xml")
        rows, st, _ = self.read(d)
        by = {r["title"]: r for r in rows}
        self.assertIn("marker1", by["kiln notes"]["text"])                  # the page's text, not the summary
        self.assertEqual(by["kiln notes"]["ts"], "2021-03-04T08:00:00Z")
        self.assertEqual(by["the diary"]["text"], "a short summary of the diary & more")       # robots keeps its page out: the summary stays
        self.assertNotIn("/private/diary", s.asked)
        del s.asked[:]
        prev = {r["id"]: [r] for r in rows}
        again = []
        canvas.read_feed(d, again.append, False, self.said.append, st, prev)
        self.assertEqual(len(again), 3)
        self.assertEqual([a for a in s.asked if a.startswith("/blog")], [])                    # nothing new in the feed: no page is read again

    def test_a_feed_typed_as_a_site_and_atom(self):
        s = self.site()
        r = self.trial("site:" + s.url + "/feed.xml")
        self.assertEqual((r["state"], r["stats"]["route"]), ("ready", "feed"))
        f = canvas.parse_feed("""<feed xmlns="http://www.w3.org/2005/Atom"><title>log</title><link href="http://example.com/"/>
            <link rel="next" href="/feed?page=2"/><entry><title type="html">A &amp;amp; B</title><link rel="alternate" type="text/html" href="/a"/>
            <updated>2024-05-06T07:08:09Z</updated><content type="html">&lt;p&gt;hello &lt;b&gt;there&lt;/b&gt;&lt;/p&gt;</content></entry></feed>""", "http://example.com/feed")
        self.assertEqual(f["next"], "http://example.com/feed?page=2")
        self.assertEqual(f["entries"], [{"title": "A & B", "url": "http://example.com/a", "date": "2024-05-06T07:08:09Z", "text": "hello there", "full": False}])


class Folder(Base):
    def make(self):
        root = tempfile.mkdtemp(prefix="ctx-canvas-")
        self.addCleanup(shutil.rmtree, root, True)
        outside = tempfile.mkdtemp(prefix="ctx-outside-")
        self.addCleanup(shutil.rmtree, outside, True)
        w = lambda rel, text, mode="w": (os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True), _f.write(text, os.path.join(root, rel), mode))
        w("essay.md", "# on kilns\n\n" + prose(1))
        w("deep/er/list.txt", "bread, clay, gulls")
        w("page.html", page("a saved page", "<p>%s</p>" % prose(2)))
        w("table.csv", "day,gulls\nmon,4\n")
        w("small.json", '{"kiln": "warm"}')
        w("big.json", '{"x": "%s"}' % ("y" * 300_000))
        w("node_modules/pkg/readme.md", "not mine")
        w(".git/config.txt", "not mine either")
        w(".hidden.md", "hidden")
        w("photo.png", b"\x89PNG\x00\x00".decode("latin-1"))
        w("binary.txt", "\x00\x01\x02 nulls")
        w("scan.pdf", "%PDF-1.4\n1 0 obj\n<< /Filter /FlateDecode >>\nstream\n" + "q8#x " * 400 + "\nendstream\nendobj\n")
        with zipfile.ZipFile(os.path.join(root, "letter.docx"), "w") as z:
            z.writestr("word/document.xml", '<w:document><w:body><w:p><w:r><w:t>dear harbour master,</w:t></w:r></w:p><w:p><w:r><w:t>the kiln &amp; the gulls</w:t>'
                                            '<w:tab/><w:t>are fine</w:t></w:r></w:p></w:body></w:document>')
        _f.write("outside the folder", os.path.join(outside, "secret.md"), "w")
        os.symlink(os.path.join(outside, "secret.md"), os.path.join(root, "link.md"))
        os.symlink(outside, os.path.join(root, "linkdir"))
        w("long.txt", ("a line of words about the tide\n\n") * 2000)
        return root

    def test_a_folder(self):
        root = self.make()
        r = self.trial("folder:" + root)
        self.assertEqual(r["state"], "ready", r)
        self.assertIn("pdf text could not be read without extra tools: 1 pdf skipped", r["detail"])
        self.assertIn("1 file over the size limit skipped", r["detail"])
        d = canvas._resolve("folder:" + root)
        rows, st, info = self.read(d)
        by = {}
        for x in rows:
            by.setdefault(os.path.basename(x["url"]), []).append(x)
        self.assertEqual(sorted(by), ["essay.md", "letter.docx", "list.txt", "long.txt", "page.html", "small.json", "table.csv"])
        self.assertEqual(by["letter.docx"][0]["text"], "dear harbour master,\nthe kiln & the gulls\tare fine")
        self.assertEqual(by["list.txt"][0]["title"], os.path.join("deep", "er", "list"))
        self.assertEqual(by["page.html"][0]["title"], "a saved page")
        self.assertNotIn("menuword", by["page.html"][0]["text"])
        self.assertEqual(len(by["long.txt"]), 4)
        self.assertIn("(part 2 of 4)", by["long.txt"][1]["title"])
        self.assertTrue(by["essay.md"][0]["ts"].startswith(time.strftime("%Y-", time.gmtime())))
        self.assertFalse(any("outside the folder" in x["text"] or "not mine" in x["text"] or "hidden" == x["text"] for x in rows))
        # a second read: only the file that changed is opened again
        prev = {}
        for x in rows:
            prev.setdefault(x["id"].split(":")[0], []).append(x)
        time.sleep(0.01)
        with open(os.path.join(root, "essay.md"), "a") as f:
            f.write("\nand a new line")
        os.remove(os.path.join(root, "table.csv"))
        again = []
        info = canvas.read_folder(d, again.append, False, self.said.append, st, prev)
        self.assertEqual(info["stats"]["same"], 5)
        self.assertEqual(len(again), len(rows) - 1)
        self.assertIn("and a new line", [x for x in again if x["url"].endswith("essay.md")][0]["text"])

    def test_one_file_and_what_cannot_be_read(self):
        root = self.make()
        r = self.trial("file:" + os.path.join(root, "essay.md"))
        self.assertEqual((r["state"], r["sample"]["rows"], r["kind"]), ("ready", 1, "file"))
        r = self.trial("file:" + os.path.join(root, "scan.pdf"))
        self.assertEqual(r["state"], "cannot")
        self.assertIn("pdf text could not be read without extra tools", r["detail"])
        self.assertEqual(self.trial("file:" + os.path.join(root, "photo.png"))["state"], "cannot")
        self.assertEqual(self.trial("folder:" + os.path.join(root, "nope"))["state"], "cannot")
        self.assertEqual(self.trial("folder:" + paths.HOME)["state"], "cannot")                 # the archive is not a source for itself

    def test_a_folder_macos_blocks_names_the_permission(self):
        self.assertIn("files and folders > context > documents folder", canvas._permission(os.path.join(canvas.HOME, "Documents", "writing")))
        self.assertIn("removable volumes", canvas._permission("/Volumes/stick/notes"))
        self.assertIn("full disk access", canvas._permission("/somewhere/else"))
        root = self.make()
        os.chmod(root, 0)
        self.addCleanup(os.chmod, root, 0o700)
        if os.access(root, os.R_OK):
            self.skipTest("this user can read anything")
        r = self.trial("folder:" + root)
        self.assertEqual(r["state"], "needs_you")
        self.assertIn("system settings > privacy & security", r["detail"])


class Notes(Base):
    def setUp(self):
        Base.setUp(self)
        status = os.path.join(paths.HOME, "status.json")
        keep = _f.read(status) if os.path.exists(status) else None
        docs = _f.read(paths.DOCS, "rb") if os.path.exists(paths.DOCS) else None

        def back():
            self.wipe()
            for p, was, mode in ((status, keep, "w"), (paths.DOCS, docs, "wb")):
                if was is not None:
                    _f.write(was, p, mode)
        self.addCleanup(back)

    def docs(self, src):
        return [json.loads(l) for l in _f.lines(paths.DOCS) if '"src": "%s"' % src in l]

    def test_a_note_is_a_blank_page_that_becomes_rows(self):
        r = self.trial("note:kiln ideas")
        self.assertEqual((r["state"], r["kind"], r["sample"]["rows"], r["source"]), ("ready", "note", 0, "canvas_note_kiln_ideas"))
        self.assertIn('python3 -m ctx note "kiln ideas" --append', r["how"])
        self.assertTrue(os.path.exists(os.path.join(canvas.NOTES, "kiln_ideas.md")))
        before = sum(1 for _ in _f.lines(paths.DOCS)) if os.path.exists(paths.DOCS) else 0
        n = canvas.note("kiln ideas", "try a celadon glaze at cone six")
        self.assertEqual((n["rows"], n["text"]), (1, "try a celadon glaze at cone six\n"))
        n = canvas.note("kiln ideas", "ask the harbour master about the shed")
        self.assertEqual(n["rows"], 2)
        got = self.docs("canvas_note_kiln_ideas")
        self.assertEqual([g["text"] for g in got], ["try a celadon glaze at cone six", "ask the harbour master about the shed"])
        self.assertTrue(all(g["title"] == "kiln ideas" and g["ts"].startswith(time.strftime("%Y-", time.gmtime())) for g in got))
        self.assertEqual(sum(1 for _ in _f.lines(paths.DOCS)), before + 2)      # the other sources' rows were not touched
        first = got[0]
        n = canvas.note("kiln ideas", "# glazes\ncone six celadon\n\nand a shino\n# 2023-04-05 shed\nasked, waiting", "replace")
        got = self.docs("canvas_note_kiln_ideas")
        self.assertEqual([(g["title"], g["text"]) for g in got], [("kiln ideas: glazes", "cone six celadon\n\nand a shino"), ("kiln ideas: 2023-04-05 shed", "asked, waiting")])
        self.assertEqual(got[1]["ts"], "2023-04-05T12:00:00Z")              # a heading with a date dates its block
        self.assertNotEqual(got[0]["id"], first["id"])
        self.assertEqual(canvas.note("kiln ideas")["text"], n["text"])      # no text: only read it back
        self.assertEqual(canvas.note("kiln ideas", "sk-abcdefghijklmnopqrstuvwxyz012345 is my key")["rows"], 2)       # it lands under the last heading
        self.assertNotIn("sk-abcdefghijklmnop", _f.read(paths.DOCS))    # rows are scrubbed on the way in
        self.assertIn("canvas_note_kiln_ideas", canvas.due("fast"))
        out = canvas.remove("note:kiln ideas")
        self.assertEqual(self.docs("canvas_note_kiln_ideas"), [])
        self.assertTrue(os.path.exists(os.path.join(canvas.NOTES, "kiln_ideas.md")) and out["kept"].endswith("kiln_ideas.md"))      # the owner's words stay

    def test_cli_and_serve(self):
        env = dict(os.environ, PYTHONPATH=fixture.REPO)
        r = subprocess.run([sys.executable, "-m", "ctx", "note", "gull log", "--append", "four gulls on the wall"], cwd=fixture.REPO, env=env, capture_output=True, text=True, timeout=60)
        out = json.loads(r.stdout)
        self.assertEqual((out["rows"], out["source"]), (1, "canvas_note_gull_log"), r.stderr)
        r = subprocess.run([sys.executable, "-m", "ctx", "note", "gull log"], cwd=fixture.REPO, env=env, input="six the next day", capture_output=True, text=True, timeout=60)
        self.assertEqual(json.loads(r.stdout)["rows"], 2)
        box = io.StringIO()
        srv = serve.Server(box)
        self.addCleanup(lambda: srv.pool.shutdown(wait=True))
        srv.run({"id": 1, "cmd": "note", "name": "gull log", "text": "none today", "mode": "replace"})
        srv.run({"id": 2, "cmd": "note", "name": "gull log"})
        srv.run({"id": 3, "cmd": "connect-list"})
        lines = [json.loads(l) for l in box.getvalue().splitlines()]
        self.assertEqual([l["result"]["text"] for l in lines if l["id"] in (1, 2) and "result" in l], ["none today\n", "none today\n"])
        self.assertIn("canvas_note_gull_log", [x.get("source") for x in [l for l in lines if l["id"] == 3][0]["result"]])
        self.assertEqual([l for l in lines if l.get("end")], [{"id": 1, "end": True}, {"id": 2, "end": True}, {"id": 3, "end": True}])


class Served(Base):
    def test_search_trial_enable_list_over_the_line_protocol(self):
        os.environ["CTX_CANVAS_TEST_LOOPBACK"] = "1"
        self.addCleanup(os.environ.pop, "CTX_CANVAS_TEST_LOOPBACK", None)
        s = self.site()
        box = io.StringIO()
        srv = serve.Server(box)
        self.addCleanup(lambda: srv.pool.shutdown(wait=True))
        got = lambda rid: [json.loads(l) for l in box.getvalue().splitlines() if json.loads(l).get("id") == rid]
        srv.run({"id": 1, "cmd": "connect-search", "q": s.url + "/"})
        cand = got(1)[0]["result"][0]
        self.assertEqual((cand["kind"], cand["id"]), ("site", "site:" + s.url + "/"))
        srv.run({"id": 2, "cmd": "connect", "source": cand["id"]})
        self.assertEqual(got(2)[-2]["result"]["state"], "needs_you", got(2)[-2]["result"])
        srv.run({"id": 3, "cmd": "connect", "source": cand["id"], "only": "posts"})
        lines = got(3)
        self.assertTrue(any(l.get("event") == "progress" and "robots.txt" in l.get("phase", "") for l in lines))
        self.assertEqual((lines[-2]["result"]["state"], lines[-2]["result"]["sample"]["rows"]), ("ready", 6), lines[-2]["result"])
        self.assertEqual(lines[-1], {"id": 3, "end": True})
        srv.run({"id": 4, "cmd": "connect-enable", "source": cand["id"], "only": "posts"})
        row = got(4)[0]["result"]
        self.assertEqual((row["enabled"], row["tier"], row["options"], row["kind"]), (True, "daily", {"only": "posts"}, "site"))
        self.assertIn(row["source"], collect.BY_NAME)
        self.assertIn(row["source"], canvas.due("daily"))
        srv.run({"id": 5, "cmd": "connect-enable", "source": row["source"], "on": False})
        self.assertIs(got(5)[0]["result"]["enabled"], False)
        self.assertNotIn(row["source"], collect.BY_NAME)
        srv.run({"id": 6, "cmd": "connect-enable", "source": row["source"], "remove": True})
        self.assertTrue(got(6)[0]["result"]["removed"])
        srv.run({"id": 7, "cmd": "connect-list"})
        self.assertNotIn(row["source"], [x.get("source") for x in got(7)[0]["result"]])
        srv.run({"id": 8, "cmd": "connect-enable", "source": "nothing at all like this"})
        self.assertIn("error", got(8)[0]["result"])


class Collected(Base):
    """Enable, then read through collect.py in its own archive: rows land in docs.jsonl; a second read keeps and marks;
    switched off, the rows leave; removed, nothing is left."""
    def test_enable_collect_disable_remove(self):
        s = self.site()
        home = tempfile.mkdtemp(prefix="ctx-canvas-home-")
        self.addCleanup(shutil.rmtree, home, True)
        with open(os.path.join(home, "status.json"), "w") as f:            # every built-in source counts as tried: none of this mac's own data is read
            json.dump({n: {"skipped": "not in this test"} for n, _, _ in collect.TABLE}, f)
        env = dict(os.environ, CTX_HOME=home, PYTHONPATH=fixture.REPO, CTX_CANVAS_TEST_LOOPBACK="1")

        def ctx(*args):
            r = subprocess.run([sys.executable, "-u", "-m", "ctx"] + list(args), cwd=fixture.REPO, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr[-600:])
            return r.stdout.strip().splitlines()
        docs = lambda: [json.loads(l) for l in _f.lines(os.path.join(home, "docs.jsonl"))]
        cid = "site:" + s.url + "/"
        first = json.loads(ctx("connect", s.url + "/")[-1])
        self.assertEqual(first["state"], "needs_you", first)
        trial = ctx("connect", cid, "--only", "posts")
        self.assertTrue(trial[0].startswith('@{"phase"'))
        self.assertEqual(json.loads(trial[-1])["state"], "ready")
        row = json.loads(ctx("connect", "--enable", cid, "--only", "posts")[-1])
        src = row["source"]
        self.assertEqual(row["next"], "python3 -m ctx collect-one " + src)
        self.assertIn(src, [x["source"] for x in json.loads(ctx("connect", "--list")[-1])])
        out = ctx("collect-one", src)
        self.assertTrue(any(l.startswith("@") and '"phase"' in l for l in out))
        got = docs()
        self.assertEqual(len(got), 6)
        self.assertEqual({g["src"] for g in got}, {src})
        self.assertTrue(all(set(g) >= {"id", "src", "ts", "title", "text", "url"} for g in got))
        self.assertEqual(_f.load(os.path.join(home, "status.json"))[src]["rows"], 6)
        self.assertIn(src, json.loads(ctx("schedule")[-1])["daily"]["sources"])
        del s.asked[:]
        s.gone.add("/blog/tide-tables")
        ctx("collect-one", src)
        got = docs()
        self.assertEqual(len(got), 6)
        self.assertEqual([g["url"].rsplit("/", 1)[-1] for g in got if g.get("gone")], ["tide-tables"])
        self.assertNotIn("/blog/glaze", s.asked)
        s.close()                                                           # the site goes down: the rows from last time are kept
        ctx("collect-one", src)
        self.assertEqual(len(docs()), 6)
        st = _f.load(os.path.join(home, "status.json"))[src]
        self.assertTrue(st["stale"] and "could not read" in st["why"], st)
        self.assertIs(json.loads(ctx("connect", "--disable", src)[-1])["enabled"], False)
        self.assertEqual(docs(), [])
        self.assertIs(json.loads(ctx("connect", "--enable", src)[-1])["enabled"], True)
        self.assertEqual(len(docs()), 6)                                    # switched back on: its rows return without a read
        self.assertTrue(json.loads(ctx("connect", "--remove", src)[-1])["removed"])
        self.assertEqual(docs(), [])
        self.assertEqual(json.loads(ctx("connect", "--list")[-1]), [])
        self.assertFalse(os.path.exists(os.path.join(home, "parts", src + ".jsonl")))

    def test_a_folder_through_collect(self):
        root = tempfile.mkdtemp(prefix="ctx-canvas-")
        self.addCleanup(shutil.rmtree, root, True)
        _f.write("the kiln log, day one. my api_key = sk-abcdefghijklmnopqrstuvwxyz012345", os.path.join(root, "a.md"), "w")
        home = tempfile.mkdtemp(prefix="ctx-canvas-home-")
        self.addCleanup(shutil.rmtree, home, True)
        with open(os.path.join(home, "status.json"), "w") as f:
            json.dump({n: {"skipped": "not in this test"} for n, _, _ in collect.TABLE}, f)
        env = dict(os.environ, CTX_HOME=home, PYTHONPATH=fixture.REPO)
        run = lambda *a: subprocess.run([sys.executable, "-m", "ctx"] + list(a), cwd=fixture.REPO, env=env, capture_output=True, text=True, timeout=120).stdout
        row = json.loads(run("connect", "--enable", root).strip().splitlines()[-1])
        self.assertEqual((row["kind"], row["tier"]), ("folder", "fast"))
        run("collect-one", row["source"])
        got = [json.loads(l) for l in _f.lines(os.path.join(home, "docs.jsonl"))]
        self.assertEqual(len(got), 1)
        self.assertIn("the kiln log, day one", got[0]["text"])
        self.assertNotIn("sk-abcdefghijklmnop", got[0]["text"])             # through put(): scrubbed
        self.assertIn(row["source"], json.loads(run("schedule"))["fast"]["sources"])


class Hub:
    """A stand-in for github's api and raw hosts, and for youtube's feed."""
    def __init__(self):
        self.asked, self.limited = [], False
        hub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                hub.asked.append(self.path)
                body = hub.pages().get(self.path.split("&page=")[0])
                if hub.limited and self.path.startswith("/api"):
                    self.send_response(403)
                    self.send_header("X-RateLimit-Remaining", "0")
                    self.send_header("X-RateLimit-Reset", str(int(time.time()) + 600))
                    self.end_headers()
                    return
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = (body if isinstance(body, str) else json.dumps(body)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json" if self.path.startswith("/api") else "text/xml" if "videos.xml" in self.path else "text/plain")
                self.end_headers()
                self.wfile.write(data)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    def pages(self):
        meta = {"full_name": "ada/engine", "description": "an engine of gears", "topics": ["gears"], "language": "Python", "default_branch": "main", "owner": {"login": "ada"},
                "created_at": "2020-01-02T03:04:05Z", "pushed_at": "2024-06-07T08:09:10Z", "html_url": "https://github.com/ada/engine", "fork": False}
        return {
            "/api/repos/ada/engine": meta,
            "/api/repos/ada/engine/git/trees/main?recursive=1": {"tree": [
                {"path": "README.md", "type": "blob", "size": 40, "sha": "r1"}, {"path": "docs/gears.md", "type": "blob", "size": 40, "sha": "g1"},
                {"path": "engine.py", "type": "blob", "size": 40, "sha": "c1"}, {"path": "LICENSE.txt", "type": "blob", "size": 40, "sha": "l1"},
                {"path": "node_modules/x/readme.md", "type": "blob", "size": 40, "sha": "n1"}, {"path": "docs", "type": "tree"}]},
            "/api/repos/ada/engine/issues?state=all&creator=ada&per_page=100": [
                {"number": 7, "title": "teeth slip at speed", "body": "the third gear slips", "created_at": "2021-02-03T04:05:06Z", "html_url": "https://github.com/ada/engine/issues/7"},
                {"number": 9, "title": "add a brake", "body": None, "pull_request": {}, "created_at": "2022-02-03T04:05:06Z", "html_url": "https://github.com/ada/engine/pull/9"}],
            "/raw/ada/engine/main/README.md": "# engine\nan engine of gears, and how to wind it",
            "/raw/ada/engine/main/docs/gears.md": "gears come in pairs",
            "/api/users/ada/repos?type=owner&sort=pushed&per_page=100": [meta, dict(meta, full_name="ada/loom", description="a loom", fork=False), dict(meta, full_name="ada/copy", fork=True)],
            "/raw/ada/engine/HEAD/README.md": "# engine\nan engine of gears, and how to wind it",
            "/robots.txt": "User-agent: *\nDisallow: /nothing\n",
            "/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv": """<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
                <title>ada winds engines</title><entry><yt:videoId>v1</yt:videoId><title>winding the engine</title><link rel="alternate" href="https://www.youtube.com/watch?v=v1"/>
                <published>2023-03-04T05:06:07+00:00</published><media:group><media:title>winding the engine</media:title>
                <media:description>how i wind it each morning</media:description></media:group></entry></feed>""",
        }


class Repo(Base):
    def setUp(self):
        Base.setUp(self)
        self.hub = Hub()
        self.addCleanup(self.hub.close)
        was = (canvas.GH_API, canvas.GH_RAW, canvas.YT_FEED)
        canvas.GH_API, canvas.GH_RAW, canvas.YT_FEED = self.hub.url + "/api", self.hub.url + "/raw", self.hub.url + "/feeds/videos.xml"
        self.addCleanup(lambda: (setattr(canvas, "GH_API", was[0]), setattr(canvas, "GH_RAW", was[1]), setattr(canvas, "YT_FEED", was[2])))

    def test_a_repo_without_a_sign_in(self):
        r = self.trial("repo:ada/engine")
        self.assertEqual((r["state"], r["sample"]["rows"], r["sample"]["since"]), ("ready", 5, "2020-01"), r)
        self.assertIn("no code", r["how"])
        rows, st, _ = self.read(canvas._resolve("repo:ada/engine"))
        by = {x["title"]: x for x in rows}
        self.assertEqual(sorted(by), ["ada/engine", "ada/engine issue #7: teeth slip at speed", "ada/engine pull request #9: add a brake", "ada/engine: README.md", "ada/engine: docs/gears.md"])
        self.assertIn("how to wind it", by["ada/engine: README.md"]["text"])
        self.assertEqual(by["ada/engine issue #7: teeth slip at speed"]["ts"], "2021-02-03T04:05:06Z")
        self.assertFalse(any("engine.py" in a or "LICENSE" in a or "node_modules" in a for a in self.hub.asked if a.startswith("/raw")))      # no code, no licence
        del self.hub.asked[:]
        again = []
        canvas.read_repo(canvas._resolve("repo:ada/engine"), again.append, False, self.said.append, st, {x["id"]: [x] for x in rows})
        self.assertEqual(len(again), 5)
        self.assertEqual([a for a in self.hub.asked if a.startswith("/raw")], [])       # no file changed: none is fetched again

    def test_the_limit_is_said_plainly_and_a_read_keeps_what_it_had(self):
        rows, st, _ = self.read(canvas._resolve("repo:ada/engine"))
        self.hub.limited = True
        r = self.trial("repo:ada/engine")
        self.assertEqual(r["state"], "needs_you")
        self.assertIn("limit for requests without a sign-in", r["detail"])
        again = []
        info = canvas.read_repo(canvas._resolve("repo:ada/engine"), again.append, False, self.said.append, st, {x["id"]: [x] for x in rows})
        self.assertEqual(len(again), 5)
        self.assertIn("limit", info["detail"])

    def test_a_user_and_a_repo_that_is_not_there(self):
        r = self.trial("repo:ada")
        self.assertEqual((r["state"], r["sample"]["rows"]), ("ready", 3), r)             # two repos of her own, one readme; the fork is left out
        r = self.trial("repo:ada/nothing")
        self.assertEqual(r["state"], "cannot")
        self.assertIn("give its folder instead", r["detail"])

    def test_youtube_titles_and_descriptions(self):
        r = self.trial("youtube:https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv")
        self.assertEqual((r["state"], r["sample"]["rows"], r["sample"]["since"]), ("ready", 1, "2023-03"), r)
        self.assertIn("transcripts are not read", r["detail"])
        rows, _, _ = self.read(canvas._resolve(r["id"]))
        self.assertEqual((rows[0]["title"], rows[0]["text"], rows[0]["url"]), ("winding the engine", "how i wind it each morning", "https://www.youtube.com/watch?v=v1"))
        self.assertEqual(self.trial("youtube:https://www.youtube.com/watch?v=abc")["state"], "cannot")


if __name__ == "__main__":
    unittest.main()
