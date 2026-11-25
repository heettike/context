"""Prompt overrides (ctx/prompts.py): an archive may replace pieces of the prompts with wording of its own. The source
holds one wording; an archive's file swaps in its own for the pieces it names, and nothing else. Every sentence and
every override here is invented."""
import ast, hashlib, json, os, re, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

from tests import fixture
from ctx import profile, prompts

GENDERED = re.compile(r"\b(he|his|him|himself|she|herself)\b", re.I)     # a prompt says "the owner" and "they": it fits whoever the owner is
SOURCE = "the owner keeps bees and says so often."
TUNED = "the keeper of this archive tends bees, and mentions it."


def key(text):
    return hashlib.sha256(text.encode()).hexdigest()


def source(name):
    with open(os.path.join(fixture.REPO, "ctx", name + ".py"), encoding="utf-8") as f:
        return f.read()


class Source(unittest.TestCase):
    def test_no_prompt_piece_assumes_who_the_owner_is(self):
        for name, pieces in prompts._pieces().items():
            self.assertTrue(pieces, name)
            for p in pieces:
                self.assertIsNone(GENDERED.search(p), "%s: %r" % (name, p[:60]))

    def test_no_other_string_in_those_modules_does_either(self):
        for name in prompts.MODULES:
            tree = ast.parse(source(name))
            inside = {id(c) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_p" for c in ast.walk(n)}
            docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                    and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant)}
            loose = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in inside and id(n) not in docs
                     and GENDERED.search(n.value)]
            self.assertEqual([t[:50] for t in loose], [], name + ": a string that assumes who the owner is")

    def test_with_no_file_the_source_is_what_is_said(self):
        with mock.patch.object(prompts, "FILE", os.path.join(fixture.HOME, "no-such-overrides-file.json")):
            prompts.reset()
            self.addCleanup(prompts.reset)
            self.assertIs(prompts.piece(SOURCE), SOURCE)
            self.assertEqual(prompts.status()["overridden"], False)

    def test_a_page_reader_tells_a_heading_from_a_project_however_the_heading_is_worded(self):
        page = ("## kiln timer\nstatus: active\n\n## what the keeper keeps returning to\n- clay\n\n## what the owner keeps returning to\n- glaze\n\n"
                "## what ines keeps returning to\n- slip\n\n## what they keep returning to\n- ash\n\n## gazebo shop\nstatus: shelved\n")
        d = tempfile.mkdtemp(prefix="ctx-prompts-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        p = os.path.join(d, "projects.md")
        with open(p, "w") as f:
            f.write(page)
        with mock.patch.object(profile, "_page", lambda name: p):
            self.assertEqual(profile._projects(), ["kiln timer", "gazebo shop"])


class Overridden(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ctx-prompts-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(prompts.reset)
        for p in (mock.patch.object(prompts, "FILE", os.path.join(self.tmp, "prompt-overrides.json")), mock.patch.object(prompts, "MEM", os.path.join(self.tmp, "memory"))):
            p.start()
            self.addCleanup(p.stop)
        prompts.reset()

    def pin(self, overrides, expect=None):
        with open(prompts.FILE, "w") as f:
            json.dump({"overrides": overrides, "expect": expect or {}}, f)
        prompts.reset()

    def put(self, rel):
        p = os.path.join(self.tmp, "memory", rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("x")

    def test_an_overridden_piece_is_said_in_the_archives_words_and_no_other(self):
        self.pin({key(SOURCE): TUNED})
        self.assertEqual(prompts.piece(SOURCE), TUNED)
        self.assertEqual(prompts.piece(SOURCE + " "), SOURCE + " ")         # one byte off is another piece
        self.assertEqual(prompts.piece("the allotment opens at nine."), "the allotment opens at nine.")
        self.assertEqual(prompts.piece(""), "")

    def test_a_broken_file_is_no_file(self):
        with open(prompts.FILE, "w") as f:
            f.write("{not json")
        prompts.reset()
        self.assertEqual(prompts.piece(SOURCE), SOURCE)
        self.pin({key(SOURCE): 7, 3: "x"})
        self.assertEqual(prompts.piece(SOURCE), SOURCE)

    def test_status_counts_the_overrides_and_what_the_source_still_has(self):
        real = prompts._pieces()["understand"][0]
        self.pin({key(real): "an older way of saying it", key(SOURCE): TUNED})
        st = prompts.status()
        self.assertEqual((st["overridden"], st["overrides"], st["in_use"], st["no_longer_in_the_source"]), (True, 2, 1, 1))

    def test_dropping_says_what_it_costs_and_waits_for_a_yes(self):
        for rel in ("wiki/people/a.md", "wiki/front.md", "core.md", "voice/x_posts.md", "cards/a.json"):
            self.put(rel)
        self.assertEqual(prompts.drop()["changed"], False)                # nothing to drop yet
        self.pin({key(SOURCE): TUNED})
        got = prompts.drop()
        self.assertEqual((got["ok"], got["would_write_again"]), (False, {"wiki_pages": 2, "read_through_pages": 1, "voice_guides": 1, "cards_kept_as_they_are": 1}))
        self.assertIn("4 built pages", got["ask"])
        self.assertEqual(prompts.piece(SOURCE), TUNED)
        got = prompts.drop(yes=True)
        self.assertEqual((got["ok"], got["changed"]), (True, True))
        self.assertEqual(prompts.piece(SOURCE), SOURCE)
        self.assertTrue(os.path.exists(got["kept_as"]))                 # kept beside it, not deleted


class Rendered(unittest.TestCase):
    def run_(self, home, *args, code=None):
        e = dict(os.environ, CTX_HOME=home)
        cmd = [sys.executable, "-c", code] if code else [sys.executable, "-m", "ctx", "prompts", *args]
        return subprocess.run(cmd, cwd=fixture.REPO, env=e, capture_output=True, text=True, timeout=120)

    def test_an_override_reaches_the_prompts_and_the_check_sees_a_change(self):
        home = tempfile.mkdtemp(prefix="ctx-prompts-")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        dump = "import hashlib, json\nfrom ctx import understand\nprint(json.dumps({'read': understand.READ, 'sha': hashlib.sha256(repr(understand.READ).encode()).hexdigest()}))"
        plain = json.loads(self.run_(home, code=dump).stdout)
        piece = next(p for p in prompts._pieces()["understand"] if p == plain["read"])
        mine = piece.replace("the owner", "the beekeeper")
        self.assertNotEqual(mine, piece)
        with open(os.path.join(home, "prompt-overrides.json"), "w") as f:
            json.dump({"overrides": {key(piece): mine}, "expect": {"understand.READ": hashlib.sha256(repr(mine).encode()).hexdigest()}}, f)
        got = json.loads(self.run_(home, code=dump).stdout)
        self.assertEqual(got["read"], mine)                             # byte for byte what the archive's file holds
        r = self.run_(home, "--check")
        self.assertEqual((r.returncode, json.loads(r.stdout)["ok"], json.loads(r.stdout)["same"]), (0, True, 1))
        with open(os.path.join(home, "prompt-overrides.json"), "w") as f:    # the source's piece changed under the override: the check says which prompt
            json.dump({"overrides": {key(piece + "!"): mine}, "expect": {"understand.READ": hashlib.sha256(repr(mine).encode()).hexdigest()}}, f)
        r = self.run_(home, "--check")
        self.assertEqual((r.returncode, json.loads(r.stdout)["differ"]), (1, ["understand.READ"]))

    def test_the_command_shows_and_asks(self):
        home = tempfile.mkdtemp(prefix="ctx-prompts-")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        os.makedirs(os.path.join(home, "memory", "wiki"))
        with open(os.path.join(home, "memory", "wiki", "front.md"), "w") as f:
            f.write("a page")
        self.assertEqual(json.loads(self.run_(home).stdout)["overridden"], False)
        with open(os.path.join(home, "prompt-overrides.json"), "w") as f:
            json.dump({"overrides": {key(SOURCE): TUNED}}, f)
        self.assertEqual(json.loads(self.run_(home).stdout)["overrides"], 1)
        self.assertEqual(json.loads(self.run_(home, "--status").stdout)["overrides"], 1)
        asked = json.loads(self.run_(home, "--drop").stdout)
        self.assertEqual((asked["changed"], asked["would_write_again"]["wiki_pages"]), (False, 1))
        self.assertEqual(json.loads(self.run_(home, "--drop", "--yes").stdout)["changed"], True)
        self.assertEqual(json.loads(self.run_(home).stdout)["overridden"], False)
        self.assertNotEqual(self.run_(home, "--nope").returncode, 0)


if __name__ == "__main__":
    unittest.main()
