"""people, person, correct, starters, and the read-through through serve. Every name here is made up."""
import io, json, os, subprocess, sys, time, unittest
from unittest import mock
from tests import fixture
from tests.test_serve import Lines
from ctx import paths, people, profile, serve

MEM = os.path.join(paths.HOME, "memory")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def keep(test, *files):
    """Put these files back as they were when the test ends (the made-up archive is shared by every test)."""
    for path in files:
        try:
            with open(path, "rb") as f:
                was = f.read()
        except OSError:
            was = None

        def back(path=path, was=was):
            if was is None:
                if os.path.exists(path):
                    os.remove(path)
            else:
                with open(path, "wb") as f:
                    f.write(was)
        test.addCleanup(back)


class People(unittest.TestCase):
    def test_one_person_on_three_apps_is_one_entry(self):
        got = people.people()
        by = {p["name"]: p for p in got}
        maya = by["Maya Okafor"]
        self.assertEqual((maya["apps"], maya["threads"], maya["messages"], maya["mine"], maya["first"], maya["last"]),
                         (["whatsapp", "telegram", "instagram"], 3, 22, 9, "2025-03-01", "2025-05-04"))
        self.assertEqual(sorted(maya["aliases"]), ["Okafor, Maya", "maya okafor 🌿"])
        self.assertIn("Maya Stone", by)                                     # another person with the same first name stays apart
        self.assertEqual(set(maya), {"name", "aliases", "apps", "threads", "messages", "mine", "first", "last"})

    def test_groups_are_left_out_and_bare_numbers_are_flagged(self):
        got = people.people()
        names = [p["name"] for p in got]
        self.assertNotIn("loud group", names)
        self.assertNotIn("gazebo crew", names)
        self.assertEqual([p.get("unnamed") for p in got if p["name"] == "+1 415 555 0199"], [True])
        self.assertFalse(any(p.get("unnamed") for p in got if p["name"] != "+1 415 555 0199"))

    def test_an_exports_placeholder_is_not_a_name(self):
        t = lambda name, n, **more: dict({"src": "instagram", "kind": "dm", "thread": name, "names": [name], "n": n, "mine": n // 2, "from": "2024-01-01", "to": "2024-06-01"}, **more)
        idx = {"threads": {"iguser_1": t("Instagram User", 400), "iguser_2": t("Instagram User", 30), "li_9": t("LinkedIn Member", 12, src="linkedin"),
                           "ig_maya": t("Instagram User", 50, names=["Instagram User", "Maya Okafor"]), "wa_maya": t("Maya Okafor", 10, src="whatsapp"),
                           "tg_h": t("Deleted Account", 9, src="telegram", handle="@kiln_notes")}}
        got = people._build(idx)
        by = {p["name"]: p for p in got}
        self.assertEqual((by["Maya Okafor"]["threads"], by["Maya Okafor"]["messages"]), (2, 60))     # the same conversation had her name once: it is hers
        held = [p for p in got if p.get("withheld")]
        self.assertEqual(sorted(p["threads"] for p in held), [1, 1, 1, 1])                           # each withheld account by itself, never one "person"
        self.assertFalse([p for p in got if people.placeholder(p["name"]) or any(people.placeholder(a) for a in p["aliases"])])
        self.assertEqual([(p["name"], p.get("unnamed")) for p in held if p["apps"] == ["telegram"]], [("@kiln_notes", None)])     # by its handle when there is one
        self.assertTrue(all(p.get("unnamed") for p in held if p["apps"] != ["telegram"]))            # so it is in no list of named people
        for name, want in (("Instagram User", True), ("linkedin member", True), ("Deleted Account", True), ("Facebook user 12", True), ("Maya Okafor", False), ("User Experience Guild", False), ("Mr Unknown", False)):
            self.assertEqual(people.placeholder(name), want, name)

    def test_ranked_by_what_the_owner_wrote_and_how_lately(self):
        got = people.people()
        order = [p["name"] for p in got]
        self.assertEqual(order[0], "Ravi Anand")                             # a thousand of the owner's messages, half a year quiet
        self.assertLess(order.index("Maya Okafor"), order.index("Maya Stone"))
        t = lambda name, mine, to: {"src": "whatsapp", "kind": "dm", "thread": name, "names": [name], "n": mine * 2, "mine": mine, "from": "2020-01-01", "to": to, "at": [0, 0]}
        built = people._build({"threads": {"a": t("Old Friend", 100, "2022-06-01"), "b": t("New Friend", 30, "2025-06-01"), "c": t("Never Answered", 0, "2025-06-01")}})
        self.assertEqual([p["name"] for p in built], ["New Friend", "Old Friend", "Never Answered"])       # halved for each year of silence
        self.assertLessEqual(len(people.people(most=3)), 3)
        self.assertLessEqual(len(got), 500)

    def test_the_cache_is_kept_and_follows_the_archive(self):
        people.people()
        self.assertTrue(os.path.exists(people.CACHE))
        with mock.patch("ctx.people._build", side_effect=AssertionError("built again")):
            people._mem.clear()
            self.assertTrue(people.people())                                # read from the file, not rebuilt
        keep(self, paths.MESSAGES)
        with open(paths.MESSAGES, "a") as f:
            f.write(json.dumps(fixture.msg("NEW1", "a new hello", who="me", thread="Nadia Brandt", ts="2025-08-01T10:00:00Z")) + "\n")
        self.assertIn("Nadia Brandt", [p["name"] for p in people.people()])

    def test_key_of(self):
        self.assertEqual(people.key_of("Okafor, Maya")[0], people.key_of("  maya OKAFOR 🌿 ")[0])
        self.assertEqual(people.key_of("José Díaz")[0], people.key_of("jose diaz")[0])
        self.assertNotEqual(people.key_of("maya")[0], people.key_of("maya okafor")[0])
        self.assertEqual(people.key_of("+1 (415) 555-0199"), ("#14155550199", True))
        self.assertEqual(people.key_of(" 🌿 "), ("", True))


class Person(unittest.TestCase):
    def test_one_person(self):
        got = people.person("maya okafor")
        self.assertEqual((got["name"], got["messages"], got["mine"]), ("Maya Okafor", 22, 9))
        self.assertEqual([(t["app"], t["messages"], t["last"]) for t in got["threads"]],
                         [("instagram", 4, "2025-05-04"), ("telegram", 6, "2025-04-06"), ("whatsapp", 12, "2025-03-12")])
        self.assertEqual(set(got["threads"][0]), {"id", "app", "title", "messages", "last", "summary"})
        self.assertEqual([r["id"] for r in got["recent"]], ["MT5", "MI0", "MI1", "MI2", "MI3"])        # the last five, across apps
        self.assertEqual(got["recent"][-1], {"id": "MI3", "ts": "2025-05-04T09:00:00Z", "who": "them", "app": "instagram", "text": "gazebo photo 3"})
        self.assertEqual((got["about"], got["open"]), ("", []))

    def test_about_comes_from_the_people_page_then_from_the_cards(self):
        self.assertEqual(people.person("Grace Hopper")["about"], "- **grace hopper** (the admiral): old colleague.")
        self.assertEqual(people.person("ada lovelace")["about"], "ada lovelace: friend.")
        ravi = people.person("ravi anand")
        self.assertEqual(ravi["about"], "the landlord of the harbour unit")
        self.assertEqual(ravi["threads"][0]["summary"], "the landlord of the harbour unit")
        self.assertEqual(people.person("ada lovelace")["threads"][0]["summary"], "a close friend")     # a card found by its title

    def test_a_block_under_a_name(self):
        keep(self, os.path.join(MEM, "people.md"))
        with open(os.path.join(MEM, "people.md"), "w") as f:
            f.write("# people\n\n## friends\n\n**Maya Okafor**\n- who: builds gazebos\n- now: waiting on the permit\n\n**Maya Stone**\n- who: someone else\n")
        self.assertEqual(people.person("okafor maya")["about"], "**Maya Okafor**\n- who: builds gazebos\n- now: waiting on the permit")

    def test_open_things_come_from_cards_and_loops(self):
        card = os.path.join(MEM, "cards", "chat_whatsapp_Maya_Okafor.json")
        keep(self, card, paths.LOOPS)
        with open(card, "w") as f:
            json.dump({"_title": "Maya Okafor", "_src": "whatsapp", "_to": "2025-03-12", "who": "the gazebo builder", "summary": "builds the gazebo",
                       "open": ["send her the permit"]}, f)
        with open(paths.LOOPS, "w") as f:
            json.dump([{"q": "did you pay maya for the paint?", "kind": "owe", "thread": "maya okafor 🌿", "date": "2025-04-06", "ids": ["MT5"], "why": "x"},
                       {"q": "something else", "kind": "owe", "thread": "Maya Stone", "date": "2025-02-01", "ids": ["MX0"]}], f)
        got = people.person("Maya Okafor")
        self.assertEqual([(o["what"], o["from"], o["ids"]) for o in got["open"]],
                         [("send her the permit", "read-through", []), ("did you pay maya for the paint?", "loops", ["MT5"])])
        self.assertEqual(got["about"], "builds the gazebo")                 # a card's "summary" wins over its "who"

    def test_part_of_a_name_and_nobody(self):
        self.assertEqual(people.person("okafor")["name"], "Maya Okafor")
        self.assertEqual(people.person("maya")["name"], "Maya Okafor")      # two mayas: the one written to most
        self.assertEqual(people.person("nobody at all"), {"error": "nobody by that name in your archive"})
        self.assertEqual(people.person(""), {"error": "nobody by that name in your archive"})
        self.assertEqual(people.person("loud group"), {"error": "nobody by that name in your archive"})
        self.assertTrue(people.person("+1 415 555 0199")["unnamed"])

    def test_a_long_message_is_clipped_and_nothing_is_masked(self):
        got = people.person("ada lovelace")
        self.assertTrue(all(len(r["text"]) <= 160 for r in got["recent"]))
        self.assertEqual(len(got["recent"]), 5)

    def test_no_model_is_called(self):
        with mock.patch("ctx.llm.ask", side_effect=AssertionError("model")), mock.patch("ctx.llm.ask_json", side_effect=AssertionError("model")):
            people._mem.clear()
            people.people()
            people.person("grace hopper")
            profile.starters()


class Correct(unittest.TestCase):
    def setUp(self):
        self.page = os.path.join(MEM, "people.md")
        keep(self, self.page, profile.LOG)
        if os.path.exists(profile.LOG):
            os.remove(profile.LOG)
        with open(self.page, "w") as f:
            f.write("# people\n\n**Ada Lovelace**\n- who: a close friend\n- owes her: the kettle memo\n\n  - **Grace Hopper** (the admiral): old colleague.\n")

    def text(self):
        with open(self.page) as f:
            return f.read()

    def test_wrong_removes_the_line_and_keeps_a_backup(self):
        before = self.text()
        got = profile.correct("people", "- owes her: the kettle memo", wrong=True)
        self.assertEqual((got["ok"], got["applied"], got["verdict"], got["n"]), (True, True, "wrong", 1))
        self.assertEqual(self.text(), before.replace("- owes her: the kettle memo\n", ""))
        backups = [f for f in os.listdir(profile.BACKUPS) if f.startswith("people.md.")]
        self.assertTrue(any(read(os.path.join(profile.BACKUPS, f)) == before for f in backups))
        self.assertFalse(os.path.exists(self.page + ".new"))
        rec = json.loads(read(profile.LOG).splitlines()[0])
        self.assertEqual((rec["page"], rec["line"], rec["verdict"], rec["fix"], bool(rec["time"])), ("people", "- owes her: the kettle memo", "wrong", "", True))

    def test_fix_replaces_the_line_and_keeps_its_bullet(self):
        got = profile.correct("people", "who: a close friend", fix="who: her cousin")
        self.assertEqual((got["applied"], got["verdict"]), (True, "fix"))
        self.assertIn("\n- who: her cousin\n", self.text())
        self.assertNotIn("close friend", self.text())

    def test_a_line_that_changed_shape_is_matched_by_its_words(self):
        got = profile.correct("people.md", "Grace Hopper (the admiral) - old colleague", fix="**Grace Hopper**: a mentor")
        self.assertTrue(got["applied"])
        self.assertTrue(self.text().endswith("  - **Grace Hopper**: a mentor\n"))

    def test_a_line_that_is_not_there_is_reported_and_the_page_is_untouched(self):
        before = self.text()
        got = profile.correct("people", "the owner lives on the moon", wrong=True)
        self.assertEqual((got["ok"], got["applied"]), (True, False))
        self.assertIn("not found", got["note"])
        self.assertEqual(self.text(), before)
        self.assertEqual(profile.corrections("people")[0]["line"], "the owner lives on the moon")      # still said, for the next rebuild

    def test_bad_requests_change_nothing(self):
        for args in (("nope", "x", True, None), ("people", "", True, None), ("people", "- who: a close friend", False, None)):
            self.assertFalse(profile.correct(args[0], args[1], wrong=args[2], fix=args[3])["ok"])
        self.assertFalse(os.path.exists(profile.LOG))

    def test_corrections_note_and_honour_for_the_next_rebuild(self):
        profile.correct("people", "- owes her: the kettle memo", wrong=True)
        profile.correct("people", "- who: a close friend", fix="- who: her cousin")
        profile.correct("core", "something about the owner", wrong=True)
        cs = profile.corrections("people")
        self.assertEqual([(c["verdict"], c["line"], c["fix"]) for c in cs],
                         [("wrong", "- owes her: the kettle memo", ""), ("fix", "- who: a close friend", "- who: her cousin")])
        self.assertEqual(len(profile.corrections()), 3)
        note = profile.note("people")
        self.assertIn("the kettle memo", note)
        self.assertIn("her cousin", note)
        self.assertEqual(profile.note("voice"), "")
        fresh = "**Ada Lovelace**\n* Who: a close friend.\n- owes her: the kettle memo\n- likes tea\n"
        self.assertEqual(profile.honour("people", fresh), "**Ada Lovelace**\n- who: her cousin\n- likes tea\n")

    def test_list_and_undo(self):
        before = self.text()
        profile.correct("people", "- owes her: the kettle memo", wrong=True)
        profile.correct("people", "- who: a close friend", fix="who: her cousin")
        self.assertEqual([(c["n"], c["verdict"], c["undone"]) for c in profile.listing()], [(1, "wrong", False), (2, "fix", False)])
        self.assertEqual(profile.undo(1), {"ok": True, "n": 1, "page": "people", "restored": True})
        self.assertEqual(profile.undo(2)["restored"], True)
        self.assertEqual(self.text(), before)
        self.assertEqual(profile.corrections(), [])
        self.assertEqual([c["undone"] for c in profile.listing()], [True, True])
        self.assertFalse(profile.undo(1)["ok"])
        self.assertFalse(profile.undo(9)["ok"])
        self.assertFalse(profile.undo("x")["ok"])
        self.assertEqual(profile.correct("people", "- who: a close friend", wrong=True)["n"], 3)

    def test_a_page_not_written_yet(self):
        path = os.path.join(MEM, "voice.md")
        keep(self, path)
        if os.path.exists(path):
            os.remove(path)
        got = profile.correct("voice", "the owner writes in capitals", wrong=True)
        self.assertEqual((got["ok"], got["applied"]), (True, False))
        self.assertFalse(os.path.exists(path))


class Starters(unittest.TestCase):
    def test_four_lenses_then_two_of_the_owners_own(self):
        keep(self, os.path.join(MEM, "projects.md"))
        with open(os.path.join(MEM, "projects.md"), "w") as f:
            f.write("# projects\n\n### Old Kiln (2021)\n- **status**: dead\n\n### Kettle Fund — the seed vehicle\n- **status**: active\n- **role**: founder\n")
        got = profile.starters(turn=0)
        self.assertEqual([s.get("lens") for s in got[:4]], ["intros", "tasks", "money", "saved"])
        self.assertEqual(got[4:], [{"q": "what did ravi and i last agree on?", "about": "person"}, {"q": "where did i leave kettle fund?", "about": "project"}])
        for turn in range(12):
            for s in profile.starters(turn=turn):
                self.assertLess(len(s["q"]), 60)
                self.assertEqual(s["q"], s["q"].lower())
        self.assertNotEqual(profile.starters(turn=1)[4], got[4])               # another day, another question

    def test_generic_ones_when_there_is_no_profile(self):
        with mock.patch("ctx.profile._first_names", lambda: []), mock.patch("ctx.profile._projects", lambda: []), mock.patch("ctx.profile._months", lambda: []):
            got = profile.starters(turn=0)
        self.assertEqual(len(got), 6)
        self.assertEqual([s["about"] for s in got[4:]], ["anything", "anything"])
        self.assertEqual(got[4]["q"], profile.GENERIC[0])

    def test_a_month_fills_in_when_there_is_no_project(self):
        with mock.patch("ctx.profile._projects", lambda: []):
            got = profile.starters(turn=0)
        self.assertEqual(got[5], {"q": "what was i busy with in june 2025?", "about": "month"})


class Estimate(unittest.TestCase):
    def test_counts_unread_conversations_and_calls_without_a_model(self):
        with mock.patch("ctx.llm.ask", side_effect=AssertionError("model")), mock.patch("ctx.llm.ask_json", side_effect=AssertionError("model")), \
                mock.patch("ctx.llm.status", lambda: {"plan": "made up"}):
            got = profile.estimate()
            one = profile.estimate(limit=1)
        self.assertGreater(got["unread"], 1)
        self.assertEqual((got["would_read"], got["calls"], got["plan"]), (got["unread"], got["reading_calls"] + 5, "made up"))
        self.assertGreaterEqual(got["reading_calls"], got["sittings"])
        self.assertEqual((one["unread"], one["would_read"], one["sittings"], one["page_calls"]), (got["unread"], 1, 1, 5))


class Served(unittest.TestCase):
    def setUp(self):
        self.out = Lines()
        self.srv = serve.Server(self.out)
        self.addCleanup(lambda: self.srv.pool.shutdown(wait=True))

    def send(self, **req):
        self.srv.handle(json.dumps(req))

    def result(self, rid, timeout=30):
        return self.out.wait(lambda e: e.get("id") == rid and ("result" in e or "error" in e or "cancelled" in e), timeout)

    def ended(self, rid):
        self.out.wait(lambda e: e.get("id") == rid and e.get("end"))
        return self.out.of(rid)

    def test_people_person_starters(self):
        self.send(id=1, cmd="people")
        self.assertEqual(self.result(1)["result"], people.people())
        self.send(id=2, cmd="people", most=2)
        self.assertEqual(len(self.result(2)["result"]), 2)
        self.send(id=3, cmd="person", name="Okafor, Maya")
        self.assertEqual(self.result(3)["result"]["messages"], 22)
        self.send(id=4, cmd="person", name="nobody at all")
        self.assertEqual(self.result(4)["result"], {"error": "nobody by that name in your archive"})
        self.send(id=5, cmd="starters")
        got = self.result(5)["result"]
        self.assertEqual((len(got), got[0]["lens"]), (6, "intros"))
        for rid in (1, 2, 3, 4, 5):
            self.assertEqual(self.ended(rid)[-1], {"id": rid, "end": True})

    def test_correct(self):
        page = os.path.join(MEM, "people.md")
        keep(self, page, profile.LOG)
        self.send(id=10, cmd="correct", page="people", line="ada lovelace: friend.", fix="ada lovelace: a cousin.")
        self.assertEqual(self.result(10)["result"]["applied"], True)
        self.assertTrue(read(page).startswith("ada lovelace: a cousin.\n"))
        self.send(id=11, cmd="correct", page="people", line="- **grace hopper** (the admiral): old colleague.", wrong=True)
        self.assertEqual(self.result(11)["result"]["verdict"], "wrong")
        self.assertEqual(read(page), "ada lovelace: a cousin.\n")
        self.send(id=12, cmd="correct", list=True)
        self.assertEqual([c["verdict"] for c in self.result(12)["result"]][-2:], ["fix", "wrong"])
        n = self.out.of(11)[0]["result"]["n"]
        self.send(id=13, cmd="correct", undo=n)
        self.assertEqual(self.result(13)["result"]["restored"], True)
        self.assertIn("grace hopper", read(page))
        self.send(id=14, cmd="correct", page="people", line="x")
        self.assertFalse(self.result(14)["result"]["ok"])

    def child(self, text, wait=None):
        class Child:
            pid = 0

            def __init__(self, cmd, **kw):
                Child.cmd, Child.kw = cmd, kw
                self.stdout = wait or io.StringIO(text)

            def poll(self):
                return 0

            def terminate(self):
                pass

            def wait(self):
                return 0
        return Child

    def test_understand_passes_progress_on_then_the_result(self):
        Child = self.child('@{"src": "understand", "phase": "3 conversations and projects to read, in 2 sittings"}\n'
                           '@{"src": "understand", "rows": 1, "of": 3, "label": "a long one"}\n@{"src": "understand", "rows": 3, "of": 3, "label": "2 short conversations"}\n'
                           '@{"src": "understand", "phase": "wrote core"}\n{"understand": {"read": 3, "of": 3, "pages": ["core"]}}\n')
        with mock.patch.object(subprocess, "Popen", Child):
            self.send(id=20, cmd="understand", limit=3)
            res = self.result(20)["result"]
        self.assertEqual(Child.cmd[-2:], ["understand", "3"])
        self.assertEqual(res, {"read": 3, "of": 3, "pages": ["core"], "exit": 0})
        lines = self.ended(20)
        self.assertEqual([e["progress"] for e in lines if "progress" in e],
                         [{"read": 0, "of": 0, "label": "3 conversations and projects to read, in 2 sittings"}, {"read": 1, "of": 3, "label": "a long one"},
                          {"read": 3, "of": 3, "label": "2 short conversations"}, {"read": 3, "of": 3, "label": "wrote core"}])
        self.assertEqual(lines[-1], {"id": 20, "end": True})
        self.send(id=21, cmd="understand-status", fast=True)
        self.assertEqual(self.result(21)["result"], {"running": False, "progress": {"read": 3, "of": 3, "label": "wrote core"}})
        with mock.patch.object(subprocess, "Popen", Child):
            self.send(id=22, cmd="understand")
            self.result(22)
        self.assertEqual(Child.cmd[-1], "understand")                       # no limit: everything unread

    def test_a_read_through_that_dies_says_so(self):
        with mock.patch.object(subprocess, "Popen", self.child("no model is signed in on this mac.\n")):
            self.send(id=25, cmd="understand")
            res = self.result(25)["result"]
        self.assertIn("stopped before it finished", res["error"])
        self.assertEqual(self.ended(25)[-1], {"id": 25, "end": True})

    def test_understand_runs_one_at_a_time_and_can_be_cancelled(self):
        r, w = os.pipe()
        reader, writer = os.fdopen(r), os.fdopen(w, "w")
        self.addCleanup(writer.close)
        killed = []
        with mock.patch.object(subprocess, "Popen", self.child("", wait=reader)), mock.patch("os.killpg", lambda pid, sig: (killed.append(sig), writer.close())):
            Child = subprocess.Popen
            Child.poll = lambda self: None if not killed else -15
            self.send(id=30, cmd="understand")
            writer.write('@{"src": "understand", "rows": 1, "of": 9, "label": "one"}\n')
            writer.flush()
            self.out.wait(lambda e: e.get("id") == 30 and "progress" in e)
            self.send(id=31, cmd="understand-status", fast=True)
            self.assertEqual(self.result(31)["result"], {"running": True, "progress": {"read": 1, "of": 9, "label": "one"}})
            self.send(id=32, cmd="understand")
            self.assertEqual(self.result(32)["result"], {"error": "the read-through is already running."})
            self.send(id=33, cmd="cancel", target=30)
            lines = self.ended(30)
        self.assertEqual(lines[-2:], [{"id": 30, "cancelled": True}, {"id": 30, "end": True}])
        self.assertTrue(killed)
        self.assertFalse(any("result" in e for e in lines))
        self.send(id=34, cmd="understand-status", fast=True)
        self.assertFalse(self.result(34)["result"]["running"])

    def test_estimate_and_status(self):
        with mock.patch("ctx.llm.status", lambda: {"plan": "made up", "using": "none"}):
            self.send(id=40, cmd="understand-estimate", limit=2)
            got = self.result(40)["result"]
            self.send(id=41, cmd="understand-status")
            st = self.result(41)["result"]
        self.assertEqual((got["would_read"], got["page_calls"]), (2, 5))
        self.assertEqual((st["running"], st["status"]["left"]), (False, got["unread"]))

    def test_the_command_list_names_them(self):
        self.send(id=50, cmd="nope")
        for name in ("people", "person", "correct", "starters", "understand-estimate", "understand-status"):
            self.assertIn(name, self.result(50)["error"])
        for name in ("people ", "person ", "correct ", "starters ", "understand ", "understand-estimate", "understand-status"):
            self.assertIn("\n  " + name, serve.__doc__)


class Cli(unittest.TestCase):
    def ctx(self, *args):
        env = dict(os.environ, CTX_HOME=paths.HOME, CTX_ANY_OS="1")
        return subprocess.run([sys.executable, "-m", "ctx", *args], cwd=fixture.REPO, env=env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)

    def test_commands(self):
        keep(self, os.path.join(MEM, "people.md"), profile.LOG)
        got = json.loads(self.ctx("people", "--json").stdout)
        self.assertEqual(got, people.people())
        self.assertIn("Maya Okafor", self.ctx("people").stdout)
        self.assertEqual(json.loads(self.ctx("person", "maya okafor", "--json").stdout)["threads"][0]["app"], "instagram")
        r = self.ctx("person", "nobody at all")
        self.assertEqual((r.returncode, json.loads(r.stdout)), (1, {"error": "nobody by that name in your archive"}))
        self.assertEqual(len(json.loads(self.ctx("starters", "--json").stdout)), 6)
        self.assertEqual(len(self.ctx("starters").stdout.splitlines()), 6)
        r = self.ctx("correct", "--page", "people", "--line", "ada lovelace: friend.", "--fix", "ada lovelace: a cousin.")
        self.assertEqual((r.returncode, json.loads(r.stdout)["applied"]), (0, True))
        n = json.loads(self.ctx("correct", "--list").stdout)[-1]["n"]
        self.assertEqual(json.loads(self.ctx("correct", "--undo", str(n)).stdout)["restored"], True)
        self.assertIn("ada lovelace: friend.", read(os.path.join(MEM, "people.md")))
        self.assertEqual(self.ctx("correct").returncode, 2)
        self.assertGreater(json.loads(self.ctx("understand", "--estimate").stdout)["unread"], 0)

    def test_help(self):
        text = self.ctx("--help").stdout
        for cmd in ("people", "person", "starters", "correct"):
            self.assertRegex(text, r"(?m)^  " + cmd + r"\b")
        for cmd, want in (("people", "--json"), ("person", "<name>"), ("correct", "--undo"), ("starters", "empty chat"), ("understand", "--estimate")):
            self.assertIn(want, self.ctx(cmd, "--help").stdout)


if __name__ == "__main__":
    unittest.main()
