"""A chatgpt export as chatgpt sends it now: conversations split into numbered files, group chats and codex tasks in
files of their own, arriving as a zip under any name or as a folder the owner unzipped. All made up."""
import io, json, os, shutil, tempfile, unittest, zipfile
from unittest import mock
from tests import fixture  # noqa: F401  (sets CTX_HOME before ctx is imported)
from ctx import exports, local_apps

ME = "user-TeapotTeapotTeapot"


def conv(cid, asked, answered, at=1750000000):
    return {"conversation_id": cid, "id": cid, "title": "about " + asked[:12], "create_time": at, "update_time": at + 60, "current_node": "b",
            "mapping": {"root": {"id": "root", "parent": None, "children": ["a"], "message": None},
                        "a": {"id": "a", "parent": "root", "children": ["b"], "message": {"author": {"role": "user"}, "create_time": at, "content": {"content_type": "text", "parts": [asked]}}},
                        "b": {"id": "b", "parent": "a", "children": [], "message": {"author": {"role": "assistant"}, "create_time": at + 60, "content": {"content_type": "text", "parts": [answered]}}}}}


def files(second_member=False):
    members = [{"id": ME}] + ([{"id": "user-KettleKettleKettle"}] if second_member else [])
    gm = lambda i, role, text: {"id": "t~t~Message~%d" % i, "role": role, "text": text, "attachments": [], "created_at": "2026-03-0%dT10:00:00.000000+00:00" % (i + 1), "updated_at": ""}
    return {
        "export_manifest.json": json.dumps({"logical_files": {"conversations.json": {"sharded": True, "shard_count": 2}}}),
        "user.json": json.dumps({"id": ME, "email": "teapot@example.com"}),
        "conversations-000.json": json.dumps([conv("c-1", "how hot should a kiln be", "about 1200 degrees")]),
        "conversations-001.json": json.dumps([conv("c-2", "my key is sk-abcdefghijklmnopqrstuvwxyz012345", "do not share keys"), conv("c-1", "how hot should a kiln be", "about 1200 degrees")]),
        "group_chats.json": json.dumps({"chats": [
            {"id": "g-1", "name": "kiln club", "members": members, "messages": [gm(1, "assistant", "a glaze needs silica"), gm(0, "user", "what is in a glaze"), gm(2, "user", "thanks")]},
            {"id": "g-2", "name": "notes to self", "members": members, "messages": [gm(0, "user", "remember the clay order")]}]}),
        "codex.json": json.dumps([{"id": "task_e_6a0000000000aaaabbbbccccddddeeee", "title": "add a kiln timer", "archived": False, "turns": [
            {"id": "task_e_6a0000000000aaaabbbbccccddddeeee~turn_1", "role": "user", "input_items": [{"type": "message", "role": "user", "content": [{"content_type": "text", "text": "add a kiln timer to the repo"}]}]},
            {"id": "task_e_6a0000000000aaaabbbbccccddddeeee~turn_2", "role": "assistant", "turn_status": "done", "output_items": [
                {"type": "partial_repo_snapshot"}, {"type": "message", "role": "assistant", "content": [{"content_type": "text", "text": "added timer.py"}, {"content_type": "repo_file_citation", "path": "timer.py"}]}]}]}]),
        "conversation_summaries.json": json.dumps([{"abc": "a summary a model wrote, not the owner"}]),
        "user_settings.json": json.dumps({"theme": "dark"}),
        "file-AbCdEf.dat": "not text: an attachment, left to the media reader",
        "index.html": "<html></html>"}


class Export(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ctx-cg-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.down, self.home = os.path.join(self.dir, "Downloads"), os.path.join(self.dir, "home")
        os.makedirs(self.down)
        for p in (mock.patch.object(exports, "IMPORTS", os.path.join(self.home, "imports")), mock.patch.object(local_apps.paths, "HOME", self.home)):
            p.start()
            self.addCleanup(p.stop)

    def folder(self, name="0a1b2c-2025-09-03-not-a-name-anyone-chose", **kw):
        d = os.path.join(self.down, name)
        os.makedirs(d)
        for n, text in files(**kw).items():
            with open(os.path.join(d, n), "w") as f:
                f.write(text)
        return d

    def read(self):
        s, p = io.StringIO(), io.StringIO()
        ns, np = local_apps.chatgpt_export(None, s), local_apps.chatgpt_export_prompts(None, p)
        sessions, prompts = [json.loads(l) for l in s.getvalue().split("\n") if l], [json.loads(l) for l in p.getvalue().split("\n") if l]
        self.assertEqual((ns, np), (len(sessions), len(prompts)))
        return sessions, prompts

    def check(self):
        sessions, prompts = self.read()
        by = {s["title"]: s for s in sessions}
        self.assertEqual(sorted(by), ["about how hot shou", "about my key is sk", "add a kiln timer", "kiln club"])       # c-1 once; the room nobody answered in is no session
        self.assertEqual((by["add a kiln timer"]["src"], by["add a kiln timer"]["first_user"], by["add a kiln timer"]["last_agent"], by["add a kiln timer"]["last_user_ts"][:4]),
                         ("codex", "add a kiln timer to the repo", "added timer.py", "2026"))
        self.assertEqual((by["kiln club"]["src"], by["kiln club"]["first_user"], by["kiln club"]["user_turns"]), ("chatgpt", "what is in a glaze", 2))     # in the order they were said
        texts = sorted(p["text"] for p in prompts)
        self.assertEqual(len(prompts), 6)
        self.assertEqual(len({p["id"] for p in prompts}), 6)
        self.assertIn("remember the clay order", texts)                               # typed in a room of their own: their words, session or not
        self.assertFalse([t for t in texts if "sk-abcdefghijklmnop" in t])
        self.assertTrue(all(p["who"] == "me" for p in prompts))
        self.assertFalse([t for t in texts if "summary a model wrote" in t])
        return sessions, prompts

    def test_a_folder_the_owner_unzipped_is_known_by_what_is_in_it(self):
        d = self.folder()
        os.makedirs(os.path.join(self.down, "holiday photos"))
        with open(os.path.join(self.down, "holiday photos", "user.json"), "w") as f:
            f.write("{}")                                                             # a folder that is not an export
        self.assertEqual([k for k, _ in exports.ingest(downloads=self.down)], ["chatgpt"])
        got = [f for _, _, fs in os.walk(exports.IMPORTS) for f in fs]
        self.assertIn("conversations-001.json", got)
        self.assertNotIn("file-AbCdEf.dat", got)
        self.assertTrue(os.path.exists(os.path.join(d, "file-AbCdEf.dat")))            # the folder is left as it was
        first = self.check()
        self.assertEqual(exports.ingest(downloads=self.down), [])                      # not taken twice
        os.rename(d, d + " copy")
        self.assertEqual(exports.ingest(downloads=self.down), [])                      # nor under another name
        self.assertEqual(self.check(), first)                                          # the same ids on every read

    def test_a_zip_under_any_name_split_or_not(self):
        with zipfile.ZipFile(os.path.join(self.down, "my data from openai.zip"), "w") as z:
            for n, text in files().items():
                z.writestr(n, text)
        with zipfile.ZipFile(os.path.join(self.down, "holiday.zip"), "w") as z:
            z.writestr("conversations.json", "[]")                                     # the name alone does not make it an export
        with zipfile.ZipFile(os.path.join(self.down, "0123456789abcdef0123456789abcdef-old.zip"), "w") as z:
            z.writestr("conversations.json", json.dumps([conv("c-9", "an older export in one file", "yes")]))
            z.writestr("user.json", json.dumps({"id": ME}))
        self.assertEqual(sorted(k for k, _ in exports.ingest(downloads=self.down)), ["chatgpt", "chatgpt"])
        self.assertEqual(exports.ingest(downloads=self.down), [])
        sessions, _ = self.read()
        self.assertEqual(len(sessions), 5)
        self.assertIn("about an older exp", [s["title"] for s in sessions])
        self.folder()                                                                  # the same export again, unzipped
        self.assertEqual(exports.ingest(downloads=self.down), [])

    def test_a_room_with_other_people_is_read_but_its_words_are_not_called_the_owners(self):
        self.folder(second_member=True)
        exports.ingest(downloads=self.down)
        sessions, prompts = self.read()
        self.assertIn("kiln club", [s["title"] for s in sessions])
        self.assertEqual(sorted(p["text"][:8] for p in prompts), ["add a ki", "how hot ", "my key i"])


if __name__ == "__main__":
    unittest.main()
