import json, os, tempfile, threading, unittest, urllib.error, urllib.request
from tests import files as _f
from unittest import mock
from tests import fixture  # noqa: F401  (points CTX_HOME at the made-up archive)
from ctx import api


class Api(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ctx-api-")
        for name in ("CONF", "RUN", "LOG"):
            p = mock.patch.object(api, name, os.path.join(self.tmp, name.lower()))
            p.start()
            self.addCleanup(p.stop)
        self.key = api.make_key("made-up-app", all_=True)
        self.srv = api.make_server(0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def call(self, path, key="", method="GET", body=None, headers=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), method=method, data=json.dumps(body).encode() if body is not None else None)
        if key:
            req.add_header("Authorization", "Bearer " + key)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_no_key_no_answer(self):
        self.assertEqual(self.call("/v1")[0], 401)
        self.assertEqual(self.call("/v1", "ctx_not-a-key")[0], 401)

    def test_a_browser_page_is_refused(self):
        self.assertEqual(self.call("/v1", self.key, headers={"Origin": "https://made.up"})[0], 403)
        self.assertEqual(self.call("/v1", self.key, headers={"Host": "made.up"})[0], 403)

    def test_index_and_tools(self):
        status, d = self.call("/v1", self.key)
        self.assertEqual(status, 200)
        self.assertTrue(any(e["path"] == "/v1/ask" for e in d["endpoints"]))
        status, d = self.call("/v1/tools", self.key)
        self.assertIn("search", [t["name"] for t in d["tools"]])
        status, d = self.call("/v1/openapi.json", self.key)
        self.assertEqual(d["openapi"][:1], "3")

    def test_search_and_a_tool_by_name(self):
        status, d = self.call("/v1/search?q=harbour%20lease", self.key)
        self.assertEqual(status, 200)
        self.assertIn("text", d)
        status, d = self.call("/v1/tools/sources", self.key, "POST", {})
        self.assertEqual(status, 200)
        self.assertEqual(self.call("/v1/tools/no-such-tool", self.key, "POST", {})[0], 400)
        self.assertEqual(self.call("/v1/search", self.key)[0], 400)
        self.assertEqual(self.call("/v1/elsewhere", self.key)[0], 404)

    def test_revoke_is_immediate_and_the_key_is_never_kept(self):
        self.assertNotIn(self.key, _f.read(api.CONF))
        self.assertEqual(oct(os.stat(api.CONF).st_mode & 0o777), "0o600")
        self.assertTrue(api.revoke("made-up-app"))
        self.assertEqual(self.call("/v1", self.key)[0], 401)
        self.assertEqual(api.keys(), [])

    def test_the_log_holds_no_names(self):
        self.call("/v1/people/Maya%20Okafor", self.key)
        self.call("/v1/wiki/people/maya-okafor", self.key)
        log = _f.read(api.LOG).lower()
        self.assertNotIn("maya", log)
        self.assertIn("/v1/people", log)

    def test_caps(self):
        with mock.patch.object(api, "PER_MINUTE", 2):
            codes = [self.call("/v1", self.key)[0] for _ in range(4)]
        self.assertEqual(codes.count(429), 2)

    def test_key_names(self):
        for bad in ("", "Has Space", "x" * 41, "made-up-app"):
            with self.assertRaises(api.Bad):
                api.make_key(bad)


if __name__ == "__main__":
    unittest.main()
