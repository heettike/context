"""Things made from the archive are kept as documents with versions, and as rows of the archive. No model; made-up data."""
import json, os, shutil, tempfile, unittest
from unittest import mock
from tests import fixture
from tests.test_serve import Lines
from ctx import agent, answer, made, paths, peek, serve

fixture.index()


class Made(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ctx-made-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        docs = os.path.join(self.tmp, "docs.jsonl")
        shutil.copy(paths.DOCS, docs)
        for p in (mock.patch.object(made, "DIR", os.path.join(self.tmp, "made")), mock.patch.object(paths, "DOCS", docs),
                  mock.patch.object(peek, "FILES", (paths.MESSAGES, docs, paths.PROMPTS, paths.SESSIONS))):
            p.start()
            self.addCleanup(p.stop)

    def reply(self, text, **more):
        return dict({"answer": text, "cites": [{"id": "V700"}, {"id": "V701"}], "error": "", "draft": True}, **more)

    def rows(self):
        with open(paths.DOCS) as f:
            return [json.loads(l) for l in f if '"src": "made"' in l]

    def test_what_is_a_request_to_make_something(self):
        for q in ("make me a plan for the gazebo rebuild from my chats with ravi", "put together a brief for my meeting with maya", "draw up a comparison of the two kiln quotes", "give me a checklist for the harbour lease"):
            self.assertEqual(agent.kind_of(q), "make", q)
        for q in ("what was the plan for the gazebo?", "where is the harbour lease", "did ravi send the list?", "who made the brief", "what did i plan last year"):
            self.assertNotEqual(agent.kind_of(q), "make", q)

    def test_a_made_thing_is_a_document_a_row_and_keeps_its_versions(self):
        r = self.reply("the gazebo plan\n\n1. order the timber by friday [1]\n2. ravi signs the lease [2]\n\n_leans on: your chat with ravi_ [1]")
        got = made.keep("make me a plan for the gazebo rebuild", r)
        self.assertEqual((got["kind"], got["version"], got["title"]), ("plan", 1, "the gazebo plan"))
        self.assertEqual(r["made"], got)
        d = made.get(got["id"])
        self.assertEqual((d["from"], d["history"], "[1]" in d["text"], "leans on" in d["text"]), (["V700", "V701"], [], False, False))       # the thing itself, without how it was shown
        self.assertEqual(oct(os.stat(made._path(got["id"])).st_mode & 0o777), "0o600")
        row = self.rows()
        self.assertEqual((len(row), row[0]["id"], row[0]["who"]), (1, "made:" + got["id"], "me"))                        # a row of the archive, their own
        self.assertIn("made", answer.OWN)
        # a follow-up in the same chat changes it: a new version, the old one kept
        again = self.reply("the gazebo plan\n\n1. order the timber by thursday [1]\n2. ravi signs [2]")
        got2 = made.keep("tighter, and move it a day earlier", again, history=[{"q": "make me a plan", "a": r["answer"]}])
        self.assertEqual((got2["id"], got2["version"]), (got["id"], 2))
        d = made.get(got["id"])
        self.assertEqual(([h["version"] for h in d["history"]], "thursday" in d["text"], "friday" in d["history"][0]["text"], d["said"]), ([1], True, True, "tighter, and move it a day earlier"))
        self.assertEqual(len(self.rows()), 1)                                                                            # still one row, the newest version
        self.assertIn("version 2", self.rows()[0]["title"])
        # their own edit: a third version, by the owner
        d = made.save(got["id"], "the gazebo plan\n\n1. timber on thursday", title="gazebo, final")
        self.assertEqual((d["version"], d["by"], d["title"], len(d["history"])), (3, "me", "gazebo, final", 2))
        self.assertIn("error", made.save("nope", "x"))
        self.assertEqual([(e["id"], e["version"]) for e in made.listing()], [(got["id"], 3)])
        # a new question in another chat is another document
        other = made.keep("put together a brief for my meeting with maya", self.reply("brief: maya\n\nwhat is open: the kettle fund [1]"))
        self.assertNotEqual(other["id"], got["id"])
        self.assertEqual((other["kind"], len(made.listing())), ("brief", 2))
        # a rebuild of the docs that drops the rows: they are put back
        with open(paths.DOCS, "w") as f:
            f.write("")
        self.assertEqual((made.resync(), len(self.rows())), (2, 2))

    def test_the_route_keeps_what_it_makes_and_a_follow_up_revises_it(self):
        first = self.reply("the gazebo plan\n\n1. order the timber [1]", strength="strong", usage={"calls": 2}, path="loop")
        with mock.patch.object(agent, "run", return_value=first) as loop:
            reply = agent.answer_for("make me a plan for the gazebo rebuild", keep=False)
        self.assertTrue(loop.call_args[1]["make"])
        self.assertEqual((reply["made"]["version"], reply["made"]["kind"]), (1, "plan"))
        second = self.reply("the gazebo plan\n\n1. order the timber today [1]", strength="strong", usage={"calls": 2}, path="loop")
        with mock.patch.object(agent, "run", return_value=second) as loop, mock.patch.object(agent, "lean") as small:
            again = agent.answer_for("tighter", history=[{"q": "make me a plan for the gazebo rebuild", "a": first["answer"]}], keep=False)
        small.assert_not_called()                                                                                        # a change to the made thing is not a lookup
        self.assertTrue(loop.call_args[1]["make"])
        self.assertEqual((again["made"]["id"], again["made"]["version"]), (reply["made"]["id"], 2))
        plain = {"answer": "clause 700 covers it[1].", "cites": [{"id": "V700"}], "error": "", "strength": "strong", "usage": {"calls": 1}}
        with mock.patch.object(agent, "lean", return_value=plain):
            self.assertNotIn("made", agent.answer_for("harbour lease clause", keep=False))                               # a lookup makes nothing

    def test_the_protocol(self):
        got = made.keep("make me a plan for the gazebo rebuild", self.reply("the gazebo plan\n\n1. order the timber [1]"))
        out = Lines()
        srv = serve.Server(out)
        self.addCleanup(lambda: srv.pool.shutdown(wait=True))
        ask = lambda n, **req: (srv.handle(json.dumps(dict(req, id=n))), out.wait(lambda e: e.get("id") == n and "result" in e)["result"], out.wait(lambda e: e.get("id") == n and e.get("end")))[1]
        self.assertEqual([e["id"] for e in ask(1, cmd="made-list")], [got["id"]])
        self.assertEqual(ask(2, cmd="made-get", doc=got["id"])["version"], 1)
        self.assertEqual(ask(3, cmd="made-save", doc=got["id"], text="the gazebo plan, by me")["version"], 2)
        self.assertIn("error", ask(4, cmd="made-get", doc="nope"))
