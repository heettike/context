import io, json, os, shutil, subprocess, sys, tempfile, unittest
from tests import files as _f
from unittest import mock
from tests import fixture
from ctx import collect, exports, paths, settings


class Ids(unittest.TestCase):
    def test_a_row_id_is_what_the_row_is_not_where_it_sat(self):
        a = collect.rid("LI", "c1", "2024-01-01", "ada", "hello")
        self.assertEqual(a, collect.rid("LI", "c1", "2024-01-01", "ada", "hello"))
        self.assertNotEqual(a, collect.rid("LI", "c1", "2024-01-01", "ada", "hello!"))
        self.assertNotEqual(collect.rid("LI", "ab", "c"), collect.rid("LI", "a", "bc"))          # parts do not run together
        self.assertRegex(a, r"^LI[0-9a-f]{14}$")

    def test_session_ids_keep_sixteen_characters(self):
        self.assertEqual(collect.sid("C", "0f3a9c1e-77aa-4b2e-9d10-aabbccddeeff"), "C0f3a9c1e77aa4b2e")
        self.assertEqual(collect.sid("X", "rollout-2026-01-02T03-04-05-0f3a9c1e-77aa-4b2e-9d10-aabbccddeeff", tail=True), "X9d10aabbccddeeff")
        self.assertNotEqual(collect.sid("C", "0f3a9c1e-1111-4b2e-9d10-aabbccddeeff"), collect.sid("C", "0f3a9c1e-2222-4b2e-9d10-aabbccddeeff"))   # same first 8
        self.assertEqual(collect.sid("U", "short"), "Ushort")


class Linkedin(unittest.TestCase):
    """An export downloaded again with rows added keeps every old row's id."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ctx-imports-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        p = mock.patch.object(exports, "IMPORTS", self.dir)
        p.start()
        self.addCleanup(p.stop)

    def dms(self, rows):
        with open(os.path.join(self.dir, "messages.csv"), "w") as f:
            f.write("CONVERSATION ID,CONVERSATION TITLE,FROM,TO,DATE,CONTENT\n" + "".join(f"{c},,{frm},me,{d},{text}\n" for c, frm, d, text in rows))
        out = io.StringIO()
        exports.linkedin_dms(None, out)
        return {json.loads(l)["text"]: json.loads(l)["id"] for l in out.getvalue().splitlines()}

    def test_messages(self):
        first = self.dms([("c1", "Ada", "2024-01-01 10:00:00 UTC", "hello"), ("c1", "Ada", "2024-01-02 10:00:00 UTC", "second")])
        again = self.dms([("c0", "Bo", "2023-12-01 10:00:00 UTC", "an older one now included"), ("c1", "Ada", "2024-01-01 10:00:00 UTC", "hello"),
                          ("c1", "Ada", "2024-01-01 12:00:00 UTC", "one in between"), ("c1", "Ada", "2024-01-02 10:00:00 UTC", "second")])
        self.assertEqual({t: again[t] for t in first}, first)
        self.assertEqual(len(set(again.values())), 4)
        self.assertTrue(all(i.startswith("LI") and not i[2:].isdigit() for i in again.values()))

    def connections(self, rows):
        with open(os.path.join(self.dir, "Connections.csv"), "w") as f:
            f.write("Notes:\n\nFirst Name,Last Name,URL,Company,Position,Connected On\n" + "".join(",".join(r) + "\n" for r in rows))
        out = io.StringIO()
        exports.linkedin_connections(None, out)
        return {json.loads(l)["title"]: json.loads(l)["id"] for l in out.getvalue().splitlines()}

    def test_connections(self):
        first = self.connections([("Ada", "Lovelace", "https://example.com/in/ada", "Engines", "Analyst", "01 Jan 2024")])
        again = self.connections([("New", "Person", "https://example.com/in/new", "X", "Y", "05 Feb 2024"), ("Ada", "Lovelace", "https://example.com/in/ada", "Engines", "Analyst", "01 Jan 2024")])
        self.assertEqual(again["Ada Lovelace"], first["Ada Lovelace"])
        self.assertNotEqual(again["New Person"], again["Ada Lovelace"])


class Wording(unittest.TestCase):
    def test_install_prints_json_alone_on_stdout(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, ".cursor"))
            env = dict(os.environ, CTX_HOME=fixture.HOME, PYTHONPATH=fixture.REPO, HOME=home)
            p = subprocess.run([sys.executable, "-m", "ctx", "mcp", "--install", "cursor"], capture_output=True, text=True, env=env, cwd=fixture.REPO, timeout=120)
            self.assertEqual(json.loads(p.stdout), {"cursor": "registered"})                    # the whole of stdout parses
            self.assertIn("cursor: registered", p.stderr)
            q = subprocess.run([sys.executable, "-m", "ctx", "mcp", "--install", "cursor", "--json"], capture_output=True, text=True, env=env, cwd=fixture.REPO, timeout=120)
            self.assertEqual((json.loads(q.stdout), q.stderr), ({"cursor": "already there"}, ""))

    def test_usage_says_since_when_days_are_counted(self):
        import time
        keep = _f.read(paths.LEDGER) if os.path.exists(paths.LEDGER) else None
        try:
            with open(paths.LEDGER, "w") as f:
                f.write(json.dumps({"tag": "old", "in": 1, "out": 1, "usd": 0.0}) + "\n" + json.dumps({"tag": "a", "in": 1, "out": 1, "usd": 0.0, "at": 1790000000}) + "\n")
            self.assertEqual(settings.usage()["since"], time.strftime("%Y-%m-%d", time.localtime(1790000000)))
            _f.write(json.dumps({"tag": "old", "in": 1, "out": 1, "usd": 0.0}) + "\n", paths.LEDGER, "w")
            self.assertIsNone(settings.usage()["since"])
        finally:
            if keep is None:
                os.remove(paths.LEDGER)
            else:
                _f.write(keep, paths.LEDGER, "w")

    def test_doctor_does_not_call_a_site_ready_without_knowing(self):
        from ctx import doctor
        browsers = [{"name": "dia", "signed_in_reads": "ready"}]
        sys_ = {"full_disk_access": True}
        with mock.patch("ctx.bridge.connected", lambda: False), mock.patch.object(doctor, "_last_reads", lambda: {}):
            s = doctor.sources(sys_, browsers)["slack"]
            self.assertIn("if you are signed in to slack", s)
            self.assertTrue(s.startswith("ready, in dia"))
        with mock.patch("ctx.bridge.connected", lambda: False), mock.patch.object(doctor, "_last_reads", lambda: {"slack": {"state": "needs_you"}, "gdrive": {"state": "ok"}}):
            got = doctor.sources(sys_, browsers)
            self.assertEqual(got["slack"], "needs: sign in to slack in dia (the last read found no session)")
            self.assertIn("when it was last read", got["gdrive"])
        for reply, want in (({"status": 200, "away": False}, "checked now"), ({"away": True}, "needs: sign in to slack in dia")):
            with mock.patch("ctx.bridge.connected", lambda: True), mock.patch("ctx.bridge.submit", lambda job, **k: reply), mock.patch.object(doctor, "_last_reads", lambda: {}):
                self.assertIn(want, doctor.sources(sys_, browsers, ask=True)["slack"])
        asked = []
        with mock.patch("ctx.bridge.connected", lambda: True), mock.patch("ctx.bridge.submit", lambda job, **k: asked.append(job) or {"status": 200}), mock.patch.object(doctor, "_last_reads", lambda: {}):
            self.assertNotIn("checked now", doctor.sources(sys_, browsers)["slack"])        # not asked for: no request leaves the browser
        self.assertEqual(asked, [])
        with mock.patch("ctx.bridge.connected", lambda: True), mock.patch("ctx.bridge.submit", side_effect=RuntimeError("x")), mock.patch.object(doctor, "_last_reads", lambda: {}):
            self.assertIn("if you are signed in to slack", doctor.sources(sys_, browsers, ask=True)["slack"])


if __name__ == "__main__":
    unittest.main()
