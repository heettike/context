"""The home's last 30 days: who is waiting, what was promised, what is on their mind, the months. No model; every name is made up."""
import json, os, time, unittest
from unittest import mock
from tests import fixture
from tests.test_serve import Lines
from ctx import now, serve

fixture.index()
NOW = time.mktime(time.strptime("2025-06-20", "%Y-%m-%d"))


def msg(i, who, text, day, tid="t1"):
    return {"id": i, "who": who, "text": text, "ts": day + "T10:00:00Z", "thread_id": tid, "thread": tid, "src": "whatsapp"}


def person(name, rank=1, **more):
    return dict({"name": name, "rank": rank}, **more)


class Rules(unittest.TestCase):
    def setUp(self):
        self.threads = {t: {"kind": "dm", "thread": name, "src": "whatsapp", "mine": 40} for t, name in
                        (("maya", "Maya Okafor"), ("ravi", "Ravi Anand"), ("ada", "Ada Lovelace"), ("grace", "Grace Hopper"), ("kiln", "Kiln Notes Bot"), ("held", "Instagram User"), ("far", "Old Contact"))}
        self.threads["crew"] = {"kind": "group", "thread": "gazebo crew", "src": "whatsapp", "mine": 90}
        self.who = {"maya": person("Maya Okafor", 0), "ravi": person("Ravi Anand", 1), "ada": person("Ada Lovelace", 2), "grace": person("Grace Hopper", 3), "kiln": person("Kiln Notes Bot", 4),
                    "held": person("instagram account, name not in the export", 5, unnamed=True, withheld=True), "far": person("Old Contact", 300)}

    def test_who_is_waiting(self):
        by = {"maya": [msg("m1", "me", "see you then", "2025-06-01", "maya"), msg("m2", "them", "can you send the lease draft before friday? thanks", "2025-06-05", "maya")],
              "ravi": [msg("r1", "them", "when are we meeting?", "2025-06-10", "ravi"), msg("r2", "me", "thursday works", "2025-06-11", "ravi")],            # the owner answered
              "ada": [msg("a1", "me", "ok", "2025-06-01", "ada"), msg("a2", "them", "just launched something big! check it out https://made.up/x?ref=1", "2025-06-02", "ada")],   # sent to many
              "grace": [msg("g1", "me", "ok", "2025-06-01", "grace"), msg("g2", "them", "haha nice", "2025-06-12", "grace")],                              # nothing asked
              "kiln": [msg("k1", "me", "start", "2025-06-01", "kiln"), msg("k2", "them", "what would you like to do next?", "2025-06-03", "kiln")],          # a bot
              "held": [msg("h1", "me", "hey", "2025-06-01", "held"), msg("h2", "them", "are you coming?", "2025-06-03", "held")],                          # a name the export withheld
              "crew": [msg("c1", "me", "hi", "2025-06-01", "crew"), msg("c2", "them", "who is bringing the kettle?", "2025-06-04", "crew")],               # a group
              "far": [msg("f1", "them", "are you free for a call?", "2025-06-06", "far")]}                                                                 # no word from the owner this month, and not close
        got = now._waiting(by, self.threads, self.who, NOW)
        self.assertEqual([(w["who"], w["id"], w["days"]) for w in got], [("Maya Okafor", "m2", 15)])
        self.assertEqual(set(got[0]), {"who", "what", "when", "days", "thread", "id", "src"})
        self.assertLess(len(got[0]["what"]), 60)
        self.assertIn("lease draft", got[0]["what"])

    def test_the_longest_wait_comes_first_and_four_at_most(self):
        by = {}
        for n, t in enumerate(("maya", "ravi", "ada", "grace", "far")):
            self.who[t]["rank"] = n
            by[t] = [msg(t + "1", "me", "ok", "2025-06-01", t), msg(t + "2", "them", "can you call me?", "2025-06-%02d" % (4 + 2 * n), t)]
        got = now._waiting(by, self.threads, self.who, NOW)
        self.assertEqual([w["thread"] for w in got], ["Maya Okafor", "Ravi Anand", "Ada Lovelace", "Grace Hopper"])
        self.assertEqual([w["days"] for w in got], sorted((w["days"] for w in got), reverse=True))
        by["maya"].append(msg("today", "them", "are you there?", "2025-06-20", "maya"))
        self.assertNotIn("today", [w["id"] for w in now._waiting(by, self.threads, self.who, NOW)])        # asked today is not waiting yet

    def test_a_promise_followed_by_its_doing_is_dropped(self):
        by = {"maya": [msg("p1", "me", "i'll send the lease draft tomorrow", "2025-06-05", "maya"), msg("p2", "them", "great", "2025-06-05", "maya")],
              "ravi": [msg("q1", "me", "will share the numbers by friday", "2025-06-06", "ravi"), msg("q2", "me", "sent, have a look", "2025-06-08", "ravi")],
              "ada": [msg("s1", "me", "kal bhej dunga", "2025-06-09", "ada")],
              "grace": [msg("u1", "me", "if you say yes i'll transfer it", "2025-06-09", "grace"), msg("u2", "me", "i'll be there at nine", "2025-06-10", "grace")],
              "kiln": [msg("b1", "me", "i'll check the build", "2025-06-10", "kiln")]}
        with mock.patch("ctx.events.ready", return_value=False):
            got = now._promised(by, self.threads, self.who, NOW, "2025-05-21")
        self.assertEqual(sorted(w["id"] for w in got), ["p1", "s1"])
        self.assertEqual(set(got[0]), {"what", "when", "days", "thread", "id", "src"})
        self.assertTrue(all(len(w["what"]) < 60 for w in got))

    def test_a_question_mark_in_a_link_is_not_a_question(self):
        self.assertTrue(now._asks("can you look at this? https://made.up/doc?id=4"))
        self.assertFalse(now._asks("the new page https://made.up/doc?id=4"))
        self.assertFalse(now._asks("your order has been shipped. track it?"))
        self.assertFalse(now._asks("ok?" * 200))

    def test_the_months_are_in_order_with_the_gaps_filled(self):
        got = now._strip({"1970-01": 2, "2024-11": 5, "2025-02": 7, "": 9, "2025-13": 1})
        self.assertEqual(got, [{"ym": "2024-11", "n": 5}, {"ym": "2024-12", "n": 0}, {"ym": "2025-01", "n": 0}, {"ym": "2025-02", "n": 7}])


class Home(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(now, "CACHE", os.path.join(fixture.HOME, "cache", "home-test.json"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(lambda: os.path.exists(now.CACHE) and os.remove(now.CACHE))

    def test_shape_caps_cache_and_no_model(self):
        at = time.mktime(time.strptime("2024-05-20", "%Y-%m-%d"))
        with mock.patch("ctx.llm.ask") as model:
            got = now.get(at)
            t0 = time.monotonic()
            again = now.get(at)
            warm = time.monotonic() - t0
        model.assert_not_called()
        self.assertEqual(sorted(got), ["at", "mind", "promised", "strip", "waiting"])
        self.assertEqual(got, again)
        self.assertLess(warm, 5)                                                # kept until the archive or the day changes; room for a loaded mac
        self.assertTrue(all(len(got[k]) <= 4 for k in ("waiting", "promised", "mind")))
        self.assertTrue(got["strip"] and all(set(m) == {"ym", "n"} for m in got["strip"]))
        self.assertEqual([m["ym"] for m in got["strip"]], sorted(m["ym"] for m in got["strip"]))
        self.assertLessEqual(got["strip"][-1]["ym"], "2024-05")
        self.assertNotIn("gazebo crew", [w["thread"] for w in got["waiting"]])
        self.assertTrue(json.dumps(got))

    def test_a_failure_gives_empty_lists_not_an_error(self):
        with mock.patch.object(now, "_waiting", side_effect=RuntimeError("made up")), mock.patch.object(now, "_mind", side_effect=KeyError("made up")):
            got = now.get(time.mktime(time.strptime("2024-05-21", "%Y-%m-%d")), fresh=True)
        self.assertEqual((got["waiting"], got["mind"]), ([], []))
        self.assertTrue(got["strip"])
        with mock.patch.object(now, "build", side_effect=RuntimeError("made up")):
            self.assertEqual(now.get(fresh=True), {"at": "", "waiting": [], "promised": [], "mind": [], "strip": []})

    def test_served(self):
        out = Lines()
        srv = serve.Server(out)
        self.addCleanup(lambda: srv.pool.shutdown(wait=True))
        srv.handle(json.dumps({"id": 7, "cmd": "now"}))
        got = out.wait(lambda e: e.get("id") == 7 and "result" in e)["result"]
        self.assertEqual(sorted(got), ["at", "mind", "promised", "strip", "waiting"])
        out.wait(lambda e: e.get("id") == 7 and e.get("end"))
