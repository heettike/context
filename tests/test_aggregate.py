"""Whole-archive questions: counted by code from a made-up archive. No model is called."""
import json, os, tempfile, unittest
from unittest import mock
from tests import fixture          # sets CTX_HOME to a made-up folder before ctx is imported
from ctx import agent, aggregate, paths, tools


def row(i, ts, who, text, thread="maya okafor", src="whatsapp", kind="dm"):
    return {"id": i, "src": src, "ts": ts, "thread_id": src + ":" + thread, "thread": thread, "kind": kind, "who": who, "sender": "" if who == "me" else thread, "text": text}


class Counted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix="ctx-agg-")
        rows, n = [], 0
        for m in range(1, 7):                       # maya: busy in early 2023, then nothing
            for d in range(1, 11):
                n += 1
                rows.append(row(f"A{n}", f"2023-{m:02d}-{d:02d}T10:00:00Z", "me" if d % 2 else "them", "about the kiln"))
        for m in range(1, 7):                       # ravi: steady through 2025
            for d in range(1, 9):
                n += 1
                rows.append(row(f"B{n}", f"2025-{m:02d}-{d:02d}T09:00:00Z", "me" if d % 2 else "them", "about the lease", thread="ravi anand", src="telegram"))
        for k, th in enumerate(("ravi anand", "maya okafor", "pottery club")):
            rows.append(row(f"L{k}", f"2025-06-2{k}T08:00:00Z", "me", "read this https://www.example.org/guide/?utm_source=x", thread=th, kind="group" if "club" in th else "dm",
                            src="telegram" if th == "ravi anand" else "whatsapp"))
        rows.append(row("L9", "2025-06-25T08:00:00Z", "me", "again http://example.org/guide#top and https://youtu.be/abc123?t=4", thread="ravi anand", src="telegram"))
        rows.append(row("M1", "2025-06-26T08:00:00Z", "me", "sent an attachment", thread="ravi anand", src="telegram"))
        cls.files = {"MESSAGES": os.path.join(cls.home, "messages.jsonl")}
        with open(cls.files["MESSAGES"], "w") as f:
            f.write("".join(json.dumps(r) + "\n" for r in rows))
        from ctx import answer, people, peek
        cls.p = [mock.patch.object(paths, "MESSAGES", cls.files["MESSAGES"]), mock.patch.object(paths, "HOME", cls.home), mock.patch.object(aggregate, "CACHE", os.path.join(cls.home, "agg.json")),
                 mock.patch.object(answer, "CACHE", os.path.join(cls.home, "threads.idx")), mock.patch.object(people, "CACHE", os.path.join(cls.home, "people.json")),
                 mock.patch.object(answer, "FILES", [cls.files["MESSAGES"]]), mock.patch.object(peek, "find", lambda i: next(((0, r) for r in rows if r["id"] == i), (0, None)))]
        for p in cls.p:
            p.start()
        for m in (aggregate._mem, answer._idx, people._mem):
            m.clear()

    @classmethod
    def tearDownClass(cls):
        from ctx import answer, people
        for p in cls.p:
            p.stop()
        for m in (aggregate._mem, answer._idx, people._mem):
            m.clear()

    def test_one_page_is_one_address_however_it_was_pasted(self):
        n = aggregate.norm_url
        self.assertEqual(n("https://www.example.org/guide/?utm_source=x"), n("http://example.org/guide#top"))
        self.assertEqual(n("https://youtu.be/abc123?t=4"), n("https://www.youtube.com/watch?v=abc123&feature=share"))
        self.assertEqual(n("https://twitter.com/ada/status/123?s=20"), "x.com/ada/status/123")
        self.assertEqual(n("https://example.org/a?page=2"), "example.org/a?page=2")
        self.assertEqual(n("not a link"), "")

    def test_who_the_owner_used_to_talk_to(self):
        got = aggregate.lapsed(6, least=40)
        self.assertEqual([(p["name"], p["peak"], p["recent"]) for p in got["people"]], [("maya okafor", ["2023-01", "2023-06", 60], 1)])
        self.assertEqual(got["window"], ["2025-01", "2025-06"])
        self.assertEqual([p["name"] for p in aggregate.lately(6)["people"]][:1], ["ravi anand"])
        text, rows = tools.run("lapsed", {})
        self.assertIn("1 people you once talked to a lot", text)
        self.assertIn("maya okafor (whatsapp)", text)
        self.assertTrue(rows and rows[0]["id"])                     # a row to cite comes with the number

    def test_what_was_sent_to_most_people(self):
        got = aggregate.shared()
        top = got["links"][0]
        self.assertEqual((top["key"], top["times"], top["to"], top["people"]), ("example.org/guide", 4, 3, 2))
        self.assertEqual(got["media"], {"telegram": 1})
        text, rows = tools.run("shared", {})
        self.assertIn("sent 4 times to 3 conversations (2 one-to-one, 1 groups)", text)
        self.assertEqual(rows[0]["id"], "L0")
        self.assertIn("cannot be counted", tools.run("shared", {"kind": "image"})[0])

    def test_the_overview_counts_everything(self):
        g = aggregate.overview()
        self.assertEqual((g["messages"], g["conversations"]), (113, 3))
        self.assertEqual(g["gaps"][0][0] > 500, True)               # the long silence between 2023 and 2025
        self.assertIn("113 messages", tools.run("stats", {"what": "overview"})[0])

    def test_such_questions_are_recognised_and_given_their_table(self):
        for q in ("whom did i use to talk to at the allotment but don't anymore", "what's something i've shared with most people on the committee", "how many people have i introduced maya to",
                  "what's something i've argued most about with ines", "how many ideas did i float with sam but didn't follow through on", "who went quiet on me"):
            self.assertEqual(agent.kind_of(q), "count", q)
        self.assertEqual(agent.kind_of("where is the link ravi sent about the lease"), "lookup")
        text, rows = agent.counted("whom did i use to talk to but don't anymore")
        self.assertIn("maya okafor", text)
        self.assertTrue(rows)
        self.assertEqual(agent.counted("what did ravi say about the lease"), ("", []))

    def test_one_small_call_answers_from_the_table(self):
        def stream(system, prompt, model, usage):
            self.assertIn("computed by code", prompt)
            self.assertIn("number or the ranking FIRST", system)
            yield "one person: maya okafor, busiest jan to jun 2023 [L1].\n===\n{\"strength\": \"strong\"}"
        with mock.patch("ctx.llm._claude_stream", stream), mock.patch("ctx.llm._log"), mock.patch.object(agent, "model_for", return_value="made-up"), \
                mock.patch.object(agent, "DIR", os.path.join(self.home, "agent")), mock.patch.object(agent, "run") as loop, mock.patch("ctx.understand.core", return_value=""):
            reply = agent.answer_for("whom did i use to talk to but don't anymore", keep=False)
        loop.assert_not_called()
        self.assertEqual((reply["path"], reply["kind"], reply["usage"]["calls"], [c["id"] for c in reply["cites"]]), ("lean", "count", 1, ["L1"]))


if __name__ == "__main__":
    unittest.main()
