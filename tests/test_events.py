"""Events pulled from the cards and counted by code, on made-up data. No model is called."""
import json, os, tempfile, unittest
from unittest import mock
from tests import fixture          # sets CTX_HOME to a made-up folder before ctx is imported
from ctx import events, tools

CARDS = [{"_key": "chat_whatsapp_maya", "_title": "maya okafor", "_src": "whatsapp", "_kind": "dm", "_mine": 9, "_n": 30, "_from": "2024-01-02", "_to": "2024-06-01", "_at": "x",
          "who": "a potter", "about": ["the kiln", "an intro to ravi"], "people": [{"name": "ravi anand", "role": "landlord"}], "decisions": [], "open": [], "arc": "warm, then a row about rent", "facts": [], "tone": "warm"}]
ROWS = [{"id": "E1", "ts": "2024-03-02T10:00:00Z", "who": "me", "text": "maya, let me introduce you to ravi, he has a studio to let"},
        {"id": "E2", "ts": "2024-03-02T10:01:00Z", "who": "them", "text": "thanks!"},
        {"id": "E3", "ts": "2024-05-05T10:00:00Z", "who": "them", "text": "you never paid the kiln rent and i am tired of asking"},
        {"id": "E4", "ts": "2024-05-06T10:00:00Z", "who": "me", "text": "what if we open a pottery cafe by the harbour"}]
MADE = [{"t": "intro", "card": 1, "by": "me", "a": "maya okafor", "b": "ravi anand", "done": True, "when": "2024-03"},
        {"t": "intro", "card": 1, "by": "me", "a": "maya okafor", "b": "the gallery owner", "done": False, "when": "2024-04"},
        {"t": "conflict", "card": 1, "with": "maya okafor", "area": "money", "topic": "kiln rent never paid", "heat": 2, "resolved": None, "when": "2024-05"},
        {"t": "idea", "card": 1, "what": "a pottery cafe by the harbour", "with": "maya okafor", "status": "unknown", "when": "2024-05"},
        {"t": "idea", "card": 9, "what": "points at no card"}, {"t": "nonsense", "card": 1}, "not a record"]


class Events(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="ctx-events-")
        self.p = [mock.patch.object(events, "DIR", self.home), mock.patch.object(events, "UNITS", os.path.join(self.home, "units")), mock.patch.object(events, "TABLE", os.path.join(self.home, "events.jsonl")),
                  mock.patch("ctx.understand.cards", return_value=CARDS), mock.patch.object(events, "_tids", return_value={"chat_whatsapp_maya": "whatsapp:maya"}),
                  mock.patch("ctx.answer.thread_rows", return_value=ROWS), mock.patch("ctx.answer.search", return_value=([], 0)),
                  mock.patch("ctx.peek.find", lambda i: next(((0, dict(r, src="whatsapp", thread="maya okafor", thread_id="whatsapp:maya", kind="dm")) for r in ROWS if r["id"] == i), (0, None)))]
        for p in self.p:
            p.start()
        events._mem.clear()

    def tearDown(self):
        for p in self.p:
            p.stop()
        events._mem.clear()

    def test_a_pass_reads_each_batch_once_and_points_at_messages(self):
        self.assertEqual(events.estimate()["calls"], 1)
        with mock.patch("ctx.llm.ask_json", return_value=MADE) as ask:
            got = events.run()
            events.run()
        ask.assert_called_once()                                    # a batch already read is never paid for again
        self.assertIn("[1] maya okafor (whatsapp, dm, 2024-01 to 2024-06, 30 messages)", ask.call_args[0][1])
        self.assertEqual((got["events"], got["with_messages"]["intro"], got["calls"]), ({"intro": 2, "conflict": 1, "idea": 1}, 1, 1))
        by = {(e["t"], e.get("b") or e.get("topic") or e.get("what")): e for e in events.table()}
        self.assertEqual(by[("intro", "ravi anand")]["rows"], ["E1"])
        self.assertEqual(by[("intro", "the gallery owner")]["rows"], [])        # nothing in the conversation shows it: summary only
        self.assertEqual(by[("conflict", "kiln rent never paid")]["rows"], ["E3"])
        self.assertEqual((by[("idea", "a pottery cafe by the harbour")]["rows"], by[("idea", "a pottery cafe by the harbour")]["fate"]), (["E4"], "never mentioned again"))

    def test_an_ideas_fate_is_decided_by_later_mentions(self):
        e = {"t": "idea", "what": "a pottery cafe by the harbour", "status": "unknown", "when": "2024-05"}
        asked = []

        def search(probes, **kw):
            asked.append((probes, kw["after"], kw["who"]))
            return [{"ts": "2025-01-03"}] * 5, 5
        self.assertEqual(events.fate(e, search), ("came back to it", 5, "2025-01"))
        self.assertEqual(asked[0][1:], ("2024-07", "me_only"))                  # only the owner's words, from two months on
        self.assertEqual(events.fate(dict(e, status="built"), search)[0], "built")
        self.assertEqual(events.fate(e, lambda p, **kw: ([], 0))[0], "never mentioned again")
        self.assertEqual(events.fate(dict(e, when=""), search), ("unknown", None, ""))

    def test_the_tools_count_and_say_what_is_only_from_a_summary(self):
        self.assertIn("has not been built", tools.run("intros", {})[0])
        with mock.patch("ctx.llm.ask_json", return_value=MADE):
            events.run()
        text, rows = tools.run("intros", {"person": "maya"})
        self.assertIn("1 introductions made (1 with messages behind them, 0 from a summary only), 1 of them by the owner; 1 more only offered", text)
        self.assertIn("(summary only)", text)
        self.assertEqual([r["id"] for r in rows], ["E1"])
        self.assertIn("0 introductions made", tools.run("intros", {"person": "nobody"})[0])
        text, rows = tools.run("conflicts", {})
        self.assertIn("by what they were about: money: 1", text)
        self.assertEqual([r["id"] for r in rows], ["E3"])
        text, rows = tools.run("ideas", {"status": "not followed through"})
        self.assertIn("not followed through (dropped or never mentioned again): 1.", text)
        self.assertIn("at least N", text)


if __name__ == "__main__":
    unittest.main()
