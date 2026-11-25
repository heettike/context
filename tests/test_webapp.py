"""A page behind a sign-in, read by a recipe through the browser extension. The extension here is a stub: these tests
check the engine's side (the recipe rules, the order of steps, what is said when a step is missing). Nothing opens a browser."""
import json, unittest
from unittest import mock
from tests import fixture
from ctx import bridge, canvas, collect, connect, llm, webapp

URL = "https://saves.example.com/me"
SURVEY = {"logged_out": False, "scrolls": True, "repeated": [{"selector": "main > ul.saves > li.save", "count": 30, "item": {
    "tag": "li.save", "children": [{"tag": "a.title", "attrs": ["href"], "link_host": "example.org", "text": "<str 34>"}, {"tag": "p.note", "text": "<str 120>"},
                                   {"tag": "time", "attrs": ["datetime"]}, {"tag": "span.tag", "text": "<str 5>"}]}}]}
RECIPE = {"list_selector": "ul.saves > li.save", "wait_for": "ul.saves", "fields": {"title": "a.title", "link": "a.title@href", "text": "p.note", "date": "time@datetime", "tags": "span.tag"},
          "next": {"kind": "scroll"}, "id_from": "link"}
REAL_PUBLIC = webapp._public
ITEMS = [{"title": "tide tables explained", "link": "https://example.org/tides", "text": "why the tide turns twice a day", "date": "2024-03-02T10:00:00Z", "tags": ["sea", "moon"]},
         {"title": "a kiln you can build", "link": "https://example.org/kiln", "text": "bricks and a lid", "date": "2023-12-25", "tags": []}]


class Stub:
    """What the extension would answer."""
    def __init__(self, items=ITEMS, error=None, away=False):
        self.jobs, self.items, self.error, self.away = [], list(items), error, away

    def __call__(self, job, timeout=120, pickup=90):
        self.jobs.append(job)
        if self.error:
            raise self.error
        if self.away:
            return {"url": "https://login.example.com/", "away": True}
        return {"url": job["url"], "value": SURVEY if job["fn"] == "survey" else {"logged_out": False, "items": self.items}}


class Webapp(unittest.TestCase):
    def setUp(self):
        self.said, self.asked = [], []
        self.addCleanup(lambda: [canvas.remove(d["id"]) for d in list(canvas._defs().values())])
        self.stub = Stub()
        for obj, name, fn in ((bridge, "connected", lambda: True), (bridge, "submit", self.stub), (webapp, "_public", lambda d, say: None),
                              (llm, "status", lambda: {"using": "claude"}), (llm, "ask_json", self.model)):
            p = mock.patch.object(obj, name, fn)
            p.start()
            self.addCleanup(p.stop)
        self.answer = dict(RECIPE)

    def model(self, system, prompt, model=None, tag=""):
        self.asked.append((prompt, model))
        return self.answer

    def trial(self):
        return canvas.connect("webapp:" + URL, say=self.said.append)

    def test_the_rules_a_recipe_must_keep(self):
        ok = dict(RECIPE, url=URL)
        self.assertEqual(webapp.validate(ok, URL), [])
        self.assertEqual(webapp.validate({"url": URL, "api": {"url_pattern": "/api/saves?page={page}", "items_path": "data.items", "fields": {"title": "name", "link": "url"}, "max_pages": 3}}, URL), [])
        bad = [dict(ok, url="https://evil.example.net/x"), dict(ok, url="http://saves.example.com/me"), dict(ok, list_selector="<script>alert(1)</script>"),
               dict(ok, list_selector="li{}"), dict(ok, fields={"title": "a@href;fetch('x')"}), dict(ok, fields={"title": "javascript:alert(1)"}), dict(ok, fields={"password": "input"}),
               dict(ok, next={"kind": "button", "selector": "button.more"}), dict(ok, next={"kind": "param", "param": "p=1&x"}), dict(ok, max_items=100000), dict(ok, script="x"),
               dict(ok, id_from="cookie"), dict(ok, fields={}), "not a recipe",
               {"url": URL, "api": {"url_pattern": "https://evil.example.net/api", "fields": {"title": "name"}}}, {"url": URL, "api": {"url_pattern": "//evil.example.net/api", "fields": {"title": "name"}}},
               {"url": URL, "api": {"url_pattern": "/api/{user}", "fields": {"title": "name"}}}, {"url": URL, "api": {"url_pattern": "/api", "fields": {"title": "name"}, "method": "POST"}}]
        for r in bad:
            self.assertTrue(webapp.validate(r, URL), r)

    def test_survey_model_recipe_trial(self):
        r = self.trial()
        self.assertEqual((r["state"], r["kind"], r["sample"]["rows"], r["sample"]["since"], r["source"]), ("ready", "webapp", 2, "2023-12", "canvas_web_saves_example_com_me"), r)
        self.assertEqual([j["fn"] for j in self.stub.jobs], ["survey", "recipe"])
        self.assertTrue(all(j["type"] == "page" and j["url"] == URL for j in self.stub.jobs))
        self.assertEqual(len(self.asked), 1)                                # one model call, on the small model
        self.assertEqual(self.asked[0][1], llm.FAST)
        self.assertIn("<str 34>", self.asked[0][0])                         # the model saw shapes
        self.assertNotIn("tide", self.asked[0][0])                          # and no content
        self.assertTrue(any("one small call" in s for s in self.said))
        self.assertEqual(r["examples"][0]["title"], "<str 21>")             # examples are shapes too
        self.assertNotIn("tide", json.dumps(r["examples"]))
        self.assertIn("password is never typed", r["how"])
        # switched on: a daily docs source; a second read adds only what is new and keeps what it had
        on = canvas.enable(r["id"])
        self.assertEqual((on["tier"], on["enabled"]), ("daily", True))
        self.assertIn(on["source"], collect.BY_NAME)
        d = canvas._resolve(r["id"])
        rows = []
        webapp.read(d, rows.append, False, self.said.append, {}, {})
        self.assertEqual([(x["title"], x["url"], x["ts"], x["kept"]) for x in rows],
                         [("tide tables explained", "https://example.org/tides", "2024-03-02T10:00:00Z", "saved"), ("a kiln you can build", "https://example.org/kiln", "2023-12-25T12:00:00Z", "saved")])
        self.assertIn("tags: sea, moon", rows[0]["text"])
        self.assertEqual(self.stub.jobs[-1]["args"][1], [])
        self.stub.items = [{"title": "gulls of the harbour", "link": "https://example.org/gulls", "text": "nine kinds"}] + ITEMS[:1]      # one new, one dropped from the page
        again = []
        info = webapp.read(d, again.append, False, self.said.append, {}, {x["id"]: [x] for x in rows})
        self.assertEqual(sorted(x["title"] for x in again), ["a kiln you can build", "gulls of the harbour", "tide tables explained"])
        self.assertEqual(info["stats"]["new"], 1)
        self.assertEqual(sorted(self.stub.jobs[-1]["args"][1]), ["https://example.org/kiln", "https://example.org/tides"])       # the reader is told what is already saved
        self.assertEqual(len(self.asked), 1)                                # no model after the first time

    def test_each_missing_step_is_named(self):
        with mock.patch.object(bridge, "connected", lambda: False):
            r = self.trial()
            self.assertEqual(r["state"], "needs_you")
            self.assertIn("load the context extension", r["detail"])
        self.stub.error = RuntimeError("site not allowed")
        r = self.trial()
        self.assertEqual(r["state"], "needs_you")
        self.assertIn('let context read this site', r["detail"])
        self.stub.error, self.stub.away = None, True
        r = self.trial()
        self.assertEqual(r["state"], "needs_you")
        self.assertIn("sign in to saves.example.com in your browser", r["detail"])
        self.stub.away = False
        with mock.patch.object(llm, "status", lambda: {"using": "none"}):
            r = self.trial()
            self.assertEqual(r["state"], "needs_you")
            self.assertIn("no model is signed in", r["detail"])
        self.assertEqual(self.asked, [])
        self.answer = dict(RECIPE, next={"kind": "button", "selector": "button.delete"})
        r = self.trial()
        self.assertEqual(r["state"], "cannot")
        self.assertIn("a click is not allowed", r["detail"])
        self.assertEqual([j["fn"] for j in self.stub.jobs if j["fn"] == "recipe"], [])     # a refused recipe never reaches the browser
        self.answer = {"cannot": "the page is a settings form"}
        self.assertEqual(self.trial()["detail"], "the page is a settings form")
        self.assertEqual(canvas.connect("webapp:http://saves.example.com/me", say=self.said.append)["state"], "cannot")

    def test_a_public_way_is_used_first(self):
        feed = {"id": "feed:https://saves.example.com/me.rss", "state": "ready", "sample": {"rows": 12, "since": "2022-01"}, "detail": ""}
        web = mock.Mock()
        web.get.return_value = canvas.Got(200, URL, "text/html", '<html><head><link rel="alternate" type="application/rss+xml" href="/me.rss"></head><body>hi</body></html>')
        with mock.patch.object(webapp, "_public", REAL_PUBLIC), \
                mock.patch.object(canvas, "Web", lambda: web), mock.patch.object(canvas, "connect", lambda cid, only=None, say=None: dict(feed, asked=cid)):
            d = canvas._make("webapp", URL)
            out = webapp.connect(d, self.said.append, lambda *a, **k: {"state": a[0]})
        self.assertEqual((out["state"], out["asked"]), ("ready", "feed:https://saves.example.com/me.rss"))
        self.assertIn("public route (its feed)", out["detail"])
        self.assertEqual(self.stub.jobs, [])                                # the browser was never asked

    def test_search_offers_the_signed_in_route_after_the_public_one(self):
        got = [(c["kind"], c["id"]) for c in connect.search_all("saves.example.com/me")]
        self.assertEqual(got[:2], [("site", "site:" + URL), ("webapp", "webapp:" + URL)])
        self.assertIn("no password is typed or kept", connect.search_all(URL)[1]["what"])


if __name__ == "__main__":
    unittest.main()
