"""Two copies of the engine can run on one archive (the app's, and a newer checkout). The older one has no reader for
a source the newer one read. It must leave that source's rows and its status line where they are."""
import io, json, os, shutil, tempfile, unittest
from unittest import mock
from tests import fixture  # noqa: F401  (sets CTX_HOME before ctx is imported)
from ctx import collect, paths


class Strangers(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ctx-strangers-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.docs, self.msgs, self.prompts = (os.path.join(self.dir, n) for n in ("docs.jsonl", "messages.jsonl", "prompts.jsonl"))
        self.older = [("teapots", self.docs, None), ("chats", self.msgs, None), ("agent", collect.S, None)]
        for p in (mock.patch.object(collect, "PARTS", os.path.join(self.dir, "parts")), mock.patch.object(collect, "D", self.docs), mock.patch.object(collect, "M", self.msgs),
                  mock.patch.object(collect.paths, "PROMPTS", self.prompts), mock.patch.object(collect, "P", self.prompts), mock.patch.object(collect.paths, "HOME", self.dir), mock.patch.object(collect, "TABLE", list(self.older))):
            p.start()
            self.addCleanup(p.stop)
        os.makedirs(collect.PARTS)

    def part(self, name, rows):
        with open(os.path.join(collect.PARTS, name + ".jsonl"), "w") as f:
            f.write("".join(json.dumps(r) + "\n" for r in rows))

    def ids(self, path):
        collect.assemble(path)
        with open(path) as f:
            return [json.loads(l)["id"] for l in f]

    def test_an_engine_keeps_the_rows_of_a_source_it_has_no_reader_for(self):
        self.part("teapots", [{"id": "T1", "src": "teapots", "title": "a", "text": "known"}])
        self.part("chats", [{"id": "C1", "src": "chats", "thread_id": "c", "who": "me", "text": "known"}])
        # read by a newer engine: one with its file noted, three told from their first row
        self.part("kettles", [{"id": "K1", "src": "kettles", "title": "b", "text": "from a newer engine"}])
        self.part("letters", [{"id": "L1", "src": "letters", "thread_id": "l", "thread": "x", "who": "them", "text": "a message"}])
        self.part("typed", [{"id": "P1", "src": "agent", "thread": "x", "who": "me", "text": "a prompt", "ts": ""}])
        self.part("newagent.prompts", [{"id": "N1:0", "src": "newagent", "thread": "x", "who": "me", "text": "typed to a new agent"}])
        with open(os.path.join(collect.PARTS, "groups.json"), "w") as f:
            json.dump({"kettles": "docs"}, f)
        self.assertEqual(self.ids(self.docs), ["T1", "K1"])
        self.assertEqual(self.ids(self.msgs), ["C1", "L1"])
        self.assertEqual(sorted(self.ids(self.prompts)), ["N1:0", "P1"])

    def test_a_source_the_owner_switched_off_or_removed_stays_out(self):
        self.part("teapots", [{"id": "T1", "src": "teapots", "title": "a", "text": "known"}])
        self.part("canvas_old_site", [{"id": "X1", "src": "canvas_old_site", "title": "t", "text": "switched off"}])
        self.part("custom_old_app", [{"id": "X2", "src": "custom_old_app", "title": "t", "text": "switched off"}])
        self.assertEqual(self.ids(self.docs), ["T1"])

    def test_a_row_in_a_known_and_an_unknown_part_is_still_one_row(self):
        self.part("teapots", [{"id": "T1", "src": "teapots", "title": "a", "text": "known"}])
        self.part("kettles", [{"id": "T1", "src": "teapots", "title": "a", "text": "known", "url": "https://made.up/1"}, {"id": "K2", "src": "kettles", "title": "", "text": "x"}])
        self.assertEqual(self.ids(self.docs), ["T1", "K2"])

    def test_its_status_line_is_kept_too_and_a_read_notes_where_the_rows_belong(self):
        with open(os.path.join(self.dir, "status.json"), "w") as f:
            json.dump({"kettles": {"rows": 7}, "canvas_gone": {"rows": 1}, "teapots": {"rows": 1}}, f)
        collect._save_status("chats", {"rows": 3})
        with open(os.path.join(self.dir, "status.json")) as f:
            got = json.load(f)
        self.assertEqual(got, {"teapots": {"rows": 1}, "chats": {"rows": 3}, "kettles": {"rows": 7}})      # the stranger stays; a source the owner removed goes

        def reader(days, out):
            out.write(json.dumps({"id": "T9", "src": "teapots", "title": "", "text": "read now"}) + "\n")
            return 1
        with mock.patch.dict(collect.BY_NAME, {"teapots": (self.docs, reader)}), mock.patch("builtins.print", lambda *a, **k: None):
            collect.collect_one("teapots", join=False)
        with open(os.path.join(collect.PARTS, "groups.json")) as f:
            self.assertEqual(json.load(f), {"teapots": "docs"})


if __name__ == "__main__":
    unittest.main()
