"""ChatGPT and Instagram read from the owner's signed-in tab: the engine's side against a made-up extension, the
readers themselves (extension/readers.js) run in node against a made-up site, and the rows: one message, one row,
whether it came by an export or from the site. All made up."""
import io, json, os, shutil, subprocess, tempfile, unittest
from unittest import mock
from tests import fixture
from ctx import bridge, collect, local_apps, signed_in

NODE = shutil.which("node")


def conv(cid, asked, answered, at):
    return {"conversation_id": cid, "id": cid, "title": "t " + cid, "create_time": at, "update_time": at, "current_node": "b",
            "mapping": {"r": {"id": "r", "parent": None, "children": ["a"], "message": None},
                        "a": {"id": "a", "parent": "r", "children": ["b"], "message": {"author": {"role": "user"}, "create_time": at, "content": {"content_type": "text", "parts": [asked]}}},
                        "b": {"id": "b", "parent": "a", "children": [], "message": {"author": {"role": "assistant"}, "create_time": at, "content": {"content_type": "text", "parts": [answered]}}}}}


class Engine(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ctx-sites-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.imports = os.path.join(self.dir, "imports")
        os.makedirs(os.path.join(self.dir, "parts"))
        for p in (mock.patch.object(signed_in, "IMPORTS", self.imports), mock.patch.object(bridge, "connected", lambda: True), mock.patch.object(signed_in.time, "sleep", lambda s: None),
                  mock.patch.object(signed_in, "note", lambda *a: None), mock.patch.object(local_apps.paths, "HOME", self.dir), mock.patch.object(collect, "PARTS", os.path.join(self.dir, "parts"))):
            p.start()
            self.addCleanup(p.stop)
        self.jobs = []

    def answers(self, *values, url="https://chatgpt.com/"):
        left = list(values)

        def submit(job, timeout=0, pickup=0):
            self.jobs.append(json.loads(json.dumps(job)))
            return {"url": url, "value": left.pop(0) if left else {"items": [], "next": "", "why": ""}}
        return mock.patch.object(bridge, "submit", submit)

    def sessions(self):
        s, p = io.StringIO(), io.StringIO()
        local_apps.chatgpt_export(None, s)
        local_apps.chatgpt_export_prompts(None, p)
        return [json.loads(l) for l in s.getvalue().split("\n") if l], [json.loads(l) for l in p.getvalue().split("\n") if l]

    def test_chatgpt_changed_conversations_replace_the_exports_copy_under_the_same_ids(self):
        os.makedirs(os.path.join(self.imports, "chatgpt-export"))
        with open(os.path.join(self.imports, "chatgpt-export", "conversations.json"), "w") as f:
            json.dump([conv("c-1", "how hot should a kiln be", "about 1200", 1000), conv("c-2", "what is slip", "wet clay", 2000)], f)
        with open(os.path.join(self.imports, "chatgpt-export", "user.json"), "w") as f:
            f.write("{}")
        before, _ = self.sessions()
        turn = lambda role, text, at: {"role": role, "text": text, "at": at}
        with self.answers({"items": [{"id": "c-3", "title": "new since the export", "made": 5000, "changed": 5000, "turns": [turn("user", "a brand new question", 5000), turn("assistant", "an answer", 5001)]},
                                     {"id": "c-1", "title": "t c-1", "made": 1000, "changed": 4000, "turns": [turn("user", "how hot should a kiln be", 1000), turn("assistant", "about 1200", 1000),
                                                                                                           turn("user", "and for porcelain", 4000), turn("assistant", "hotter", 4000)]}], "next": "28", "why": ""},
                          {"items": [], "next": "", "why": ""}):
            r = signed_in.chatgpt()
        self.assertEqual((r["state"], r["rows"], r["new"], r["detail"]), ("ok", 3, 1, ""))
        self.assertEqual(self.jobs[0]["args"][0], {"c-1": 1000, "c-2": 2000})          # what an export already brought is not asked for again
        self.assertEqual(self.jobs[1]["args"][0]["c-1"], 4000)
        self.assertEqual((self.jobs[0]["fn"], self.jobs[0]["url"]), ("chatgpt_api", "https://chatgpt.com/"))
        after, prompts = self.sessions()
        by = {s["id"]: s for s in after}
        self.assertEqual(len(after), 3)
        self.assertEqual({s["id"] for s in before} - set(by), set())                   # the same ids as the export gave
        c1 = by[collect.sid("O", "c-1")]
        self.assertEqual((c1["user_turns"], c1["last_user"], c1["last_agent"]), (2, "and for porcelain", "hotter"))      # the copy changed last
        self.assertEqual(sorted(p["text"] for p in prompts), ["a brand new question", "and for porcelain", "how hot should a kiln be", "what is slip"])
        self.assertEqual(len({p["id"] for p in prompts}), 4)

    def test_chatgpt_slow_down_keeps_what_was_read_and_signed_out_asks_for_the_owner(self):
        with self.answers({"items": [{"id": "c-9", "title": "x", "made": 1, "changed": 9, "turns": [{"role": "user", "text": "q", "at": 9}, {"role": "assistant", "text": "a", "at": 9}]}],
                           "next": "0", "why": "chatgpt asked to slow down"}):
            r = signed_in.chatgpt()
        self.assertEqual((r["state"], r["rows"], r["detail"], len(self.jobs)), ("ok", 1, "chatgpt asked to slow down", 1))
        with self.answers({"items": [], "next": "", "why": "signed out"}):
            r = signed_in.chatgpt()
        self.assertEqual((r["state"], r["rows"]), ("needs_you", 1))
        with mock.patch.object(bridge, "submit", side_effect=RuntimeError("unknown reader")):
            r = signed_in.chatgpt()
        self.assertEqual(r["state"], "skipped")
        self.assertIn("reload it", r["detail"])

    def test_instagram_saved_posts_stop_at_what_the_export_brought_and_share_its_ids(self):
        with open(collect._part("instagram_saved"), "w") as f:
            f.write(json.dumps({"id": "ISCabc123", "src": "instagram_saved", "title": "kiln.daily", "text": "from the export", "url": "https://www.instagram.com/p/Cabc123/"}) + "\n")
        with self.answers({"items": [{"id": "Cnew999", "at": 1700300000, "user": "glaze.lab", "text": "a new saved reel", "reel": True}], "next": "", "why": "", "me": "99"}, url="https://www.instagram.com/"):
            r = signed_in.instagram_saved()
        self.assertEqual((r["rows"], r["new"], self.jobs[0]["args"][:2]), (1, 1, ["saved", ["Cabc123"]]))
        with self.answers({"items": [], "next": "", "why": "", "me": "99"}, url="https://www.instagram.com/"):
            signed_in.instagram_saved()
        self.assertEqual(self.jobs[-1]["args"][1], ["Cnew999", "Cabc123"])              # a later read still stops at what the export brought
        with mock.patch.object(collect.paths, "HOME", self.dir):
            out = io.StringIO()
            fn = [f for n, _, f in collect.TABLE if n == "instagram_saved_web"][0]
            self.assertEqual(fn(None, out), 1)
        row = json.loads(out.getvalue())
        self.assertEqual((row["id"], row["src"], row["title"], row["url"], row["ts"]), ("ISCnew999", "instagram_saved", "glaze.lab", "https://www.instagram.com/reel/Cnew999/", "2023-11-18T09:33:20Z"))

    def test_they_are_read_daily(self):
        from ctx import schedule
        for n in ("instagram_saved_web", "chatgpt_export", "chatgpt_export_prompts"):
            self.assertIn(n, schedule.DAILY)
        for n in ("chatgpt", "instagram_saved"):
            self.assertIn(n, signed_in.ALL)


HARNESS = r'''
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const site = JSON.parse(process.argv[3]);
const calls = [];
global.document = { cookie: site.cookie || "" };
global.location = { origin: "https://made.up" };
global.fetch = async (url, opt) => {
  calls.push({ url: url, method: (opt || {}).method, auth: !!(((opt || {}).headers || {}).Authorization), app: (((opt || {}).headers || {})["X-IG-App-ID"]) || "" });
  const hit = site.pages[url];
  const status = hit === undefined ? 404 : (hit.status || 200);
  return { ok: status >= 200 && status < 300, status: status, headers: { get: (h) => (h.toLowerCase() == "content-type" ? (hit && hit.html ? "text/html" : "application/json") : null) }, json: async () => (hit || {}).body };
};
const realTimeout = setTimeout;
global.setTimeout = (f, ms) => realTimeout(f, 0);
const READERS = new Function(src + "; return READERS;")();
READERS[site.fn].apply(null, site.args).then((v) => { console.log(JSON.stringify({ value: v, calls: calls })); });
'''


@unittest.skipUnless(NODE, "node is not on this machine: the readers are javascript")
class Readers(unittest.TestCase):
    def run_reader(self, fn, args, pages, cookie=""):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(HARNESS)
        self.addCleanup(os.remove, f.name)
        r = subprocess.run([NODE, f.name, os.path.join(fixture.REPO, "extension", "readers.js"), json.dumps({"fn": fn, "args": args, "pages": pages, "cookie": cookie})],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-600:])
        out = json.loads(r.stdout)
        return out["value"], out["calls"]

    def cg_conv(self, cid):
        m = lambda role, text, parent, extra=None: {"parent": parent, "message": dict({"author": {"role": role}, "create_time": 5, "content": {"content_type": "text", "parts": [text]}}, **(extra or {}))}
        return {"body": {"title": "about " + cid, "create_time": 1, "current_node": "d", "mapping": {
            "r": {"parent": None, "message": None}, "s": m("system", "rules", "r"), "a": m("user", "asked in " + cid, "s"),
            "h": m("assistant", "hidden", "a", {"metadata": {"is_visually_hidden_from_conversation": True}}), "d": m("assistant", "answered", "h"), "x": m("user", "an abandoned branch", "s")}}}

    def test_chatgpt_reads_what_changed_never_returns_the_token_and_only_gets(self):
        listing = lambda ids: {"body": {"items": [{"id": i, "title": i, "update_time": t} for i, t in ids]}}
        pages = {"/api/auth/session": {"body": {"accessToken": "made-up-token-zzz", "user": {"id": "u"}}},
                 "/backend-api/conversations?offset=0&limit=28&order=updated": listing([("c-new", "2026-03-02T10:00:00Z"), ("c-changed", 4000), ("c-same", 2000)]),
                 "/backend-api/conversation/c-new": self.cg_conv("c-new"), "/backend-api/conversation/c-changed": self.cg_conv("c-changed")}
        v, calls = self.run_reader("chatgpt_api", [{"c-changed": 1000, "c-same": 2000}, 3, "", 10], pages)
        self.assertEqual((v["why"], v["next"], [c["id"] for c in v["items"]]), ("", "", ["c-new", "c-changed"]))
        self.assertEqual(v["items"][0]["turns"], [{"role": "user", "text": "asked in c-new", "at": 5}, {"role": "assistant", "text": "answered", "at": 5}])      # the shown turns of the current branch
        self.assertEqual(v["items"][0]["changed"], 1772445600)
        self.assertNotIn("made-up-token", json.dumps(v))
        self.assertEqual({c["method"] for c in calls}, {"GET"})
        self.assertEqual([c["auth"] for c in calls], [False, True, True, True])
        v, calls = self.run_reader("chatgpt_api", [{"c-changed": 4000, "c-same": 2000, "c-new": 1772445600}, 3, "", 10], pages)
        self.assertEqual((v["items"], v["next"], len(calls)), ([], "", 2))                # nothing changed: the list is read once and that is all

    def test_chatgpt_stops_at_its_cap_at_a_refusal_and_when_signed_out(self):
        many = [("c-%d" % n, 9000 - n) for n in range(28)]
        pages = {"/api/auth/session": {"body": {"accessToken": "t"}}, "/backend-api/conversations?offset=0&limit=28&order=updated": {"body": {"items": [{"id": i, "update_time": t} for i, t in many]}}}
        pages.update({"/backend-api/conversation/c-%d" % n: self.cg_conv("c-%d" % n) for n in range(28)})
        v, _ = self.run_reader("chatgpt_api", [{}, 3, "", 3], pages)
        self.assertEqual((len(v["items"]), v["next"], v["why"]), (3, "0", ""))             # more to read: the next call takes up the rest
        pages["/backend-api/conversation/c-1"] = {"status": 429}
        v, calls = self.run_reader("chatgpt_api", [{}, 3, "", 10], pages)
        self.assertEqual(([c["id"] for c in v["items"]], v["why"]), (["c-0"], "chatgpt asked to slow down"))
        self.assertEqual(len(calls), 4)                                                    # it did not try again
        v, calls = self.run_reader("chatgpt_api", [{}, 3, "", 10], {"/api/auth/session": {"body": {}}})
        self.assertEqual((v["why"], len(calls)), ("signed out", 1))

    def test_instagram_saved_posts_stop_at_a_saved_one(self):
        media = lambda code, at: {"media": {"pk": 1, "code": code, "taken_at": at, "caption": {"text": "caption of " + code}, "user": {"username": "glaze.lab"}, "product_type": "clips" if code == "C3" else "feed"}}
        pages = {"/api/v1/feed/saved/posts/": {"body": {"status": "ok", "items": [media("C3", 30), media("C2", 20)], "more_available": True, "next_max_id": "p2"}},
                 "/api/v1/feed/saved/posts/?max_id=p2": {"body": {"status": "ok", "items": [media("C1", 10), media("C0", 5)], "more_available": True, "next_max_id": "p3"}}}
        v, calls = self.run_reader("ig_api", ["saved", ["C1"], 5, ""], pages, cookie="ds_user_id=99")
        self.assertEqual(([p["id"] for p in v["items"]], v["next"], v["why"], len(calls)), (["C3", "C2", "C0"], "", "", 2))
        self.assertEqual((v["items"][0]["reel"], v["items"][0]["user"], v["items"][0]["text"]), (True, "glaze.lab", "caption of C3"))
        self.assertEqual(({c["method"] for c in calls}, all(c["app"] for c in calls)), ({"GET"}, True))

    def test_instagram_refusals_are_said_and_end_the_read(self):
        for page, want in (({"status": 429}, "instagram asked to slow down"), ({"html": True}, "instagram sent a page, not data (it may be asking you to confirm it is you)"),
                           ({"body": {"status": "fail", "message": "checkpoint_required"}}, "instagram is asking you to confirm it is you"), ({"status": 403}, "instagram refused")):
            v, calls = self.run_reader("ig_api", ["saved", [], 3, ""], {"/api/v1/feed/saved/posts/": page}, cookie="ds_user_id=99")
            self.assertEqual((v["why"], v["items"], len(calls)), (want, [], 1))
        v, calls = self.run_reader("ig_api", ["saved", [], 3, ""], {}, cookie="")
        self.assertEqual((v["why"], calls), ("signed out", []))
        v, calls = self.run_reader("ig_api", ["chats", {}, 3, ""], {}, cookie="ds_user_id=99")
        self.assertEqual((v["why"], calls), ("unknown list", []))                         # chats and likes are refused by instagram: nothing asks for them


if __name__ == "__main__":
    unittest.main()
