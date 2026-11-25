"""The wiki: layers, refs on every paragraph, rebuilding only what changed, corrections, the cap, carrying on after a
kill, and reading it back. The model is a stub; every name and row is made up."""
import json, os, re, shutil, tempfile, unittest
from unittest import mock
from tests import fixture
from ctx import llm, profile, understand, wiki

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(REPO, "tests", "fixtures", "wiki")
SECRET = "sk-" + "a1B2c3D4e5F6g7H8i9J0"


def model(calls, kill_after=None, line=""):
    """llm.ask by step. A page reply holds one grounded paragraph, one with no ref, a bullet with an invented ref,
    a heading with nothing under it and a secret, so the cleaning can be seen."""
    def page(part):
        cs, rs = wiki._refs(part.split("## evidence", 1)[-1])
        refs = ["[[c:%s]]" % c for c in sorted(cs)[:2]] + ["[[r:%s]]" % r for r in sorted(rs)[:2]]
        return ("summary: what the evidence shows of this subject.\n\n## who they are\n\na grounded paragraph about the gazebo. the key was %s. %s\n\n"
                "an invented paragraph that cites nothing.\n\n%s- a grounded bullet %s\n- a bullet with an invented ref [[r:NOPE]]\n\n## nothing here\n"
                % (SECRET, " ".join(refs), (line + " " + refs[0] + "\n\n") if line and refs else "", refs[0] if refs else ""))

    def ask(system, prompt, model=None, tag=""):
        calls.append({"tag": tag, "system": system, "prompt": prompt})
        if kill_after is not None and len(calls) > kill_after:
            raise KeyboardInterrupt
        step = tag.split(":")[-1]
        if step == "digest":
            return "\n".join("%s | work, beliefs | kettle fund | the owner wrote about the lease [[r:%s]]" % (m, i) for i, m in re.findall(r"(?m)^(\S+)\| (\d{4}-\d{2})", prompt)[:6])
        if step == "survey":
            return "\n".join("C | %s | beliefs, voice | kettle fund" % k for k in re.findall(r"\[\[c:([^\]]+)\]\]", prompt)) + "\nP | kettle fund | the kettle | a fund for kettles | project"
        if step == "catalog":
            return "id | title | names | kind | what\nkettle-fund | Kettle Fund | kettle fund; the kettle | project | a fund for kettles"
        if step == "condense":
            cs, rs = wiki._refs(prompt)
            return "\n".join(["- 2024-01: condensed from a card [[c:%s]]" % c for c in sorted(cs)[:3]] + ["- 2024-02: condensed from a row [[r:%s]]" % r for r in sorted(rs)[:3]])
        if step == "audit":
            n = re.search(r"(?m)^(\d+)\. [^\n]*audit me", prompt)
            m = re.search(r"(?m)^(\d+)\. [^\n]*trim me", prompt)
            return "\n".join(([n.group(1) + " | drop"] if n else []) + ([m.group(1) + " | fix | the owner signed the lease in june."] if m else [])) or "ok"
        if step == "short":
            return "the owner funds kettles and makes pottery.\n"
        parts = re.split(r"(?m)^=== (\S+) ===$", prompt)
        if len(parts) > 1:
            return "\n".join("=== %s ===\n%s" % (parts[i], page(parts[i + 1])) for i in range(1, len(parts), 2))
        return page(prompt)
    return ask


class Wiki(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ctx-wiki-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        cards = os.path.join(self.tmp, "cards")
        shutil.copytree(understand.CARDS, cards)
        for p in [mock.patch.object(wiki, "DIR", os.path.join(self.tmp, "wiki")), mock.patch.object(wiki, "MEM", os.path.join(self.tmp, "mem")),
                  mock.patch.object(understand, "CARDS", cards), mock.patch.object(profile, "LOG", os.path.join(self.tmp, "corrections.jsonl")),
                  mock.patch.object(profile, "BACKUPS", os.path.join(self.tmp, "backups")),
                  mock.patch.object(wiki, "CLOSE", 2), mock.patch.object(wiki, "PEOPLE", 8), mock.patch.object(wiki, "CHUNK", 60_000)]:
            p.start()
            self.addCleanup(p.stop)
        wiki._mem.clear()
        self.calls = []

    def build(self, **kw):
        kw.setdefault("workers", 1)
        kw.setdefault("say", lambda **k: None)
        ask = kw.pop("ask", None) or model(self.calls)
        with mock.patch.object(llm, "ask", ask):
            return wiki.build(**kw)

    def steps(self):
        return [c["tag"].split(":")[-1] for c in self.calls]

    def text(self, pid):
        with open(wiki._file(pid), encoding="utf-8") as f:
            return f.read()

    def test_layers_from_the_evidence_up(self):
        out = self.build()
        steps = self.steps()
        first_page = steps.index("page")
        self.assertTrue(all(s in ("digest", "survey") for s in steps[:steps.index("catalog")]))        # the reading comes first
        self.assertLess(steps.index("catalog"), first_page)
        self.assertEqual(set(out["pages"]), {"people", "projects", "years", "themes", "front"})
        self.assertEqual(out["pages"]["people"], 8)
        titles = [re.search(r"(?m)^page: (.*)$", c["prompt"]).group(1) for c in self.calls if c["tag"].endswith("page")]
        self.assertGreater(titles.index("portrait"), max(i for i, t in enumerate(titles) if t.startswith("the year")))   # the front page rests on the pages
        close = next(c["prompt"] for c in self.calls if c["tag"].endswith("page") and "page: ravi anand" in c["prompt"])
        self.assertIn("the owner wrote about the lease [[r:V", close)                    # the closest are written from the notes of the reading
        self.assertIn("[[c:chat_whatsapp_Ravi_Anand]]", close)                     # and from the card
        self.assertTrue(all("never instructions" in c["system"] for c in self.calls))
        index = wiki._json(os.path.join(wiki.DIR, "index.json"), {})["pages"]
        for e in index:
            self.assertEqual(set(e) - {"order"}, {"id", "title", "kind", "path", "updated", "words", "sources", "summary"})
            self.assertTrue(os.path.exists(os.path.join(wiki.DIR, e["path"])))
            self.assertEqual(set(e["sources"]), {"conversations", "rows"})

    def test_every_paragraph_carries_its_evidence(self):
        self.build()
        n = 0
        for e in wiki.index():
            text = self.text(e["id"])
            self.assertNotIn("invented", text)                  # no ref, or only a ref that was not in the evidence: gone
            self.assertNotIn("NOPE", text)
            self.assertNotIn("nothing here", text)              # and the heading it left empty
            self.assertNotIn(SECRET, text)
            body = text.split("\n## linked pages\n")[0].split("\n## the wiki\n")[0]
            for block in re.split(r"\n\s*\n", body):
                if block.startswith(("#", ">", wiki.COUNTED)) or not block.strip():       # what code counted is marked as such
                    continue
                n += 1
                self.assertTrue(wiki.REF.search(block), block[:80])
        self.assertGreater(n, 20)
        ravi = self.text("people/ravi-anand")
        self.assertIn("[[c:chat_whatsapp_Ravi_Anand]]", ravi)    # a long card id is an id, not a secret: the scrubber never sees it
        self.assertIn(wiki.COUNTED, ravi)
        self.assertIn("[redacted]", ravi)
        front = self.text("front")
        self.assertIn("[[p:people/ravi-anand|ravi anand]]", front)
        self.assertIn("## what the archive cannot see", front)
        self.assertIn("## coverage", front)

    def test_a_long_page_is_condensed_by_period_first(self):
        with mock.patch.object(wiki, "BUDGET", 12_000), mock.patch.object(wiki, "GROUP", 8_000):
            self.build(only="people", pick=["people/maya-okafor", "people/ravi-anand"])
        steps = self.steps()
        self.assertIn("condense", steps)
        self.assertLess(steps.index("condense"), steps.index("page"))
        self.assertTrue(wiki.REF.search(self.text("people/ravi-anand")))

    def test_only_what_changed_is_rewritten(self):
        self.build()
        full = len(self.calls)
        del self.calls[:]
        again = self.build()
        self.assertEqual((again["calls"], len(self.calls), again["written"]), (0, 0, 0))
        path = os.path.join(understand.CARDS, "k.json")
        card = wiki._json(path, {})
        card["about"] = ["kettles", "a new samovar"]
        wiki._put(path, json.dumps(card))
        self.build()
        pages = [c["prompt"] for c in self.calls if c["tag"].endswith("page")]
        self.assertTrue(any("page: ada lovelace" in p for p in pages))
        self.assertFalse(any("page: ravi anand" in p or "page: grace hopper" in p for p in pages))     # their evidence did not change
        self.assertLess(len(self.calls), full)

    def test_corrections_are_told_and_applied(self):
        with open(profile.LOG, "w") as f:
            f.write(json.dumps({"n": 1, "page": "people", "line": "the owner once sold the gazebo to a rival", "verdict": "wrong", "time": "t"}) + "\n")
            f.write(json.dumps({"n": 2, "page": "core", "line": "the owner lives on a houseboat in the harbour", "verdict": "fix", "fix": "the owner lives above the pottery studio.", "time": "t"}) + "\n")
        self.build(only="people", limit=1, ask=model(self.calls, line="the owner once sold the gazebo to a rival. the owner lives on a houseboat in the harbour."))
        page = next(c for c in self.calls if c["tag"].endswith("page"))
        self.assertIn("the owner once sold the gazebo to a rival", page["prompt"])         # told, in the material: it quotes a line written from the archive
        self.assertNotIn("the owner once sold the gazebo to a rival", page["system"])
        self.assertIn("# from the owner", page["system"])                                  # and the instructions say what that part of the material is
        text = self.text("people/ravi-anand")
        self.assertNotIn("sold the gazebo", text)                                    # and taken out of what came back
        self.assertNotIn("houseboat", text)
        self.assertRegex(text, r"the owner lives above the pottery studio\. \[\[c:")        # the owner's wording, with the evidence kept

    def test_a_line_that_says_nothing_cannot_be_cited(self):
        lines = ("A1| 2025-01-01 instagram them: Reacted \u2764 to your message \nA2| 2025-01-01 instagram me: You sent an attachment.\n"
                 "A3| 2025-01-01 whatsapp them: ok\nA4| 2025-01-01 whatsapp me: the lease is signed\n[[c:k]] a card")
        self.assertEqual(wiki._citable(lines), ({"k"}, {"A4"}))
        summary, body, dropped = wiki._clean("summary: s.\n\nthe ikea trip is open. [[r:A1]]\n\nthe lease is signed. [[r:A4]] [r:A2]", {"k"}, {"A4"})
        self.assertEqual((body, dropped), ("the lease is signed. [[r:A4]]", 1))

    def test_typed_events_are_evidence_with_their_rows(self):
        path = os.path.join(self.tmp, "events.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"t": "commitment", "by": "me", "to": "Maya Okafor", "what": "file the permit", "done": False, "when": "2025-03", "tid": "whatsapp:Maya Okafor", "key": "x", "thread": "Maya Okafor", "rows": ["MW7"]}) + "\n")
            f.write(json.dumps({"t": "idea", "what": "a kettle fund for makers", "fate": "dropped", "when": "2024-03", "tid": "whatsapp:ada lovelace", "key": "k", "thread": "ada lovelace", "rows": []}) + "\n")
        with mock.patch.object(wiki, "EVENTS", path):
            self.build()
        maya = next(c["prompt"] for c in self.calls if c["tag"].endswith("page") and "page: maya okafor" in c["prompt"])
        self.assertIn("me promised Maya Okafor: file the permit (not done) [[r:MW7]]", maya)
        undone = next(c["prompt"] for c in self.calls if c["tag"].endswith("page") and "page: what they said they would do" in c["prompt"])
        self.assertIn("[[r:MW7]]", undone)
        self.assertIn("from the conversation's summary only, not found in the messages) [[c:k]]", undone)     # no message behind it: the card, and said so

    def test_a_second_reading_checks_each_statement_against_its_sources(self):
        self.build(only="people", limit=1, ask=model(self.calls, line="audit me: the owner sold the harbour. [[r:V1]] trim me: the owner signed the lease in june for a million. [[r:V2]]"))
        audit = next(c for c in self.calls if c["tag"].endswith("audit"))
        self.assertIn("-> 20", audit["prompt"])                       # the cited message, marked, among the lines around it
        self.assertIn("-> 2023-01-01 them: day 1 small talk", audit["prompt"])
        self.assertNotIn("[[r:", audit["prompt"])
        text = self.text("people/ravi-anand")
        self.assertNotIn("sold the harbour", text)                    # what its source does not show is gone
        self.assertIn("the owner signed the lease in june. [[r:V2]]", text)       # or cut back to what it shows, refs kept
        self.assertNotIn("million", text)

    def test_the_cap_is_hard(self):
        out = self.build(max_calls=3)
        self.assertEqual((out["calls"], len(self.calls)), (3, 3))
        self.assertIn("cap", out["stopped"])

    def test_a_killed_build_carries_on(self):
        clean = []
        with mock.patch.object(wiki, "DIR", os.path.join(self.tmp, "clean")):
            self.build(ask=model(clean))
        wiki._mem.clear()
        first = []
        with self.assertRaises(KeyboardInterrupt):
            self.build(ask=model(first, kill_after=len(clean) - 6))
        self.assertTrue(os.path.exists(os.path.join(wiki.DIR, "index.json")))        # what was written before the kill is whole
        self.build()
        asked = [(c["system"], c["prompt"]) for c in first[:-1] + self.calls]
        self.assertEqual(len(asked), len(set(asked)))                                # nothing was paid for twice
        self.assertEqual(len(asked), len(clean))
        self.assertEqual(len(wiki.index()), len(wiki._json(os.path.join(self.tmp, "clean", "index.json"), {})["pages"]))

    def test_estimate_calls_nothing(self):
        est = self.build(dry=True)
        self.assertEqual(self.calls, [])
        self.assertFalse(os.path.exists(os.path.join(wiki.DIR, "index.json")))
        self.assertGreater(est["calls"]["digest"], 1)
        self.assertGreater(est["calls_total"], est["calls"]["digest"])
        self.assertTrue(est["rough"])                                # projects and themes cannot be counted before the reading
        self.assertGreater(est["input_tokens"], 0)
        self.build()
        del self.calls[:]
        est = self.build(dry=True)
        self.assertEqual((self.calls, est["rough"], sum(est["pages_to_write"].values())), ([], [], 0))
        self.assertEqual(est["calls"], {"short": 5})

    def test_a_new_message_costs_one_reading_not_the_whole_conversation(self):
        lines = [("2024-%02d" % m, "R%d%d| 2024-%02d-01 whatsapp me: %s" % (m, i, m, "kettle " * 400)) for m in (1, 2, 3) for i in range(12)]
        one = ("people/maya-okafor", "their conversation with Maya Okafor (whatsapp), 36 messages", lines)
        two = ("people/maya-okafor", "their conversation with Maya Okafor (whatsapp), 37 messages", lines + [("2024-03", "R99| 2024-03-09 whatsapp them: one more")])
        a, b = wiki._digest_prompts(one), wiki._digest_prompts(two)
        self.assertGreater(len(a), 1)
        self.assertEqual([x[3] for x in a[:-1]], [x[3] for x in b[:-1]])          # the earlier stretches are kept under the same name
        self.assertNotEqual(a[-1][3], b[-1][3])                                    # only the stretch with the new message is read again
        self.assertNotEqual(a[0][1], b[0][1])                                      # though the heading the model sees counts one more
        wiki._put(wiki._work("calls", wiki._sha(wiki.VERSION, a[0][0], a[0][3]) + ".txt"), "kept from the first reading")
        dry = wiki.Run(dry=True)
        self.assertEqual(wiki._ask(dry, "digest", b[0][0], b[0][1], key=b[0][3]), "kept from the first reading")
        self.assertIsNone(wiki._ask(dry, "digest", b[-1][0], b[-1][1], key=b[-1][3]))
        self.assertEqual(dry.pending["digest"], 1)

    def test_an_estimate_with_reading_still_to_come_counts_what_it_can_and_says_why(self):
        self.build()
        base = wiki.Base()
        unit = next(wiki._units(base, [p for p in base.people if p["rank"] < wiki.CLOSE]))
        system, _, _, key = wiki._digest_prompts(unit)[0]
        os.remove(wiki._work("calls", wiki._sha(wiki.VERSION, system, key) + ".txt"))          # one stretch must be read again
        del self.calls[:]
        est = self.build(dry=True)
        self.assertEqual((self.calls, est["calls"]["digest"]), ([], 1))
        self.assertIsInstance(est["pages_to_write"].get("themes"), int)            # counted from the notes held, not a first build's worth
        self.assertFalse([r for r in est["rough"] if "counted only after" in r])
        self.assertTrue(any("still to come" in r for r in est["rough"]))
        self.assertIn("1 calls read again", " ".join(est["why"]))
        self.assertEqual(est["calls_total"], sum(est["calls"].values()))

    def test_a_page_titled_with_an_exports_placeholder_is_not_shown(self):
        self.build()
        path = os.path.join(wiki.DIR, "index.json")
        d = wiki._json(path, {})
        n = len(d["pages"])
        d["pages"].append(dict(d["pages"][0], id="people/instagram-user", title="instagram user"))
        wiki._put(path, json.dumps(d))
        wiki._mem.clear()
        self.assertEqual(len(wiki.index()), n)
        self.assertIsNone(wiki.page("instagram user"))
        self.assertFalse([h for h in wiki.find("instagram user") if h["title"] == "instagram user"])

    def test_the_paragraphs_that_bear_on_a_question(self):
        self.build()
        got = wiki.excerpt("maya okafor gazebo", size=600)
        self.assertEqual(got[0][0]["id"], "people/maya-okafor")
        self.assertTrue(all(wiki.REF.search(text) for _, text in got))             # every paragraph handed over carries its evidence
        self.assertLessEqual(sum(len(text) for _, text in got), 700)
        self.assertNotIn("#", got[0][1][:2])
        self.assertEqual(wiki.excerpt("zzzz"), [])

    def test_their_own_edits_to_a_paragraph_outlive_a_rebuild(self):
        self.build()
        got = wiki.page("people/maya-okafor")
        paras = got["paras"]
        self.assertTrue(paras and all(set(p) >= {"anchor", "text", "refs"} for p in paras))
        first, second = paras[0], paras[1]
        self.assertIn("error", wiki.edit("people/maya-okafor", "nope", "remove"))
        self.assertIn("error", wiki.edit("people/nobody", first["anchor"], "remove"))
        self.assertIn("error", wiki.edit("people/maya-okafor", first["anchor"], "comment"))
        out = wiki.edit("people/maya-okafor", first["anchor"], "comment", "she is my oldest friend, not a client")
        self.assertIn("> your note: she is my oldest friend, not a client", out["text"])
        self.assertEqual(out["paras"][0]["note"], "she is my oldest friend, not a client")
        out = wiki.edit("people/maya-okafor", second["anchor"], "remove")
        self.assertNotIn(second["text"][:40], out["text"])
        self.assertEqual(len(out["paras"]), len(paras) - 1)
        self.assertNotIn(second["text"][:40], wiki.page("people/maya-okafor")["text"])          # every reader gets the edited page
        self.assertNotIn(second["text"][:40], self.tools_page("people/maya-okafor"))
        note = wiki.edit_note("people/maya-okafor")
        self.assertIn("removed these statements", note)
        self.assertIn("oldest friend", note)
        # the page is written again from scratch: the edits are still there, and the writer was told
        os.remove(wiki._file("people/maya-okafor"))
        del self.calls[:]
        self.build(only="people", pick=["people/maya-okafor"])
        asked = "\n".join(c["prompt"] for c in self.calls if c["tag"].endswith("page"))
        self.assertIn("The owner removed these statements", asked)
        again = wiki.page("people/maya-okafor")
        self.assertIn("> your note: she is my oldest friend", again["text"])
        self.assertNotIn(second["text"][:40], again["text"])
        # a correction stands in for the paragraph on the same evidence; a pin keeps a paragraph; restore takes an edit back
        out = wiki.edit("people/maya-okafor", first["anchor"], "correct", "she ran the gazebo build with the owner.")
        self.assertIn("she ran the gazebo build with the owner.", out["text"])
        self.assertTrue(wiki.REF.search(next(p["text"] for p in out["paras"] if p["anchor"] == first["anchor"])))
        self.assertTrue(next(p for p in wiki.edit("people/maya-okafor", first["anchor"], "pin")["paras"] if p["anchor"] == first["anchor"])["pinned"])
        out = wiki.edit("people/maya-okafor", second["anchor"], "restore")
        self.assertIn(second["text"][:40], out["text"])

    def tools_page(self, pid):
        from ctx import tools
        return tools.run("wiki", {"page": pid})[0]

    def test_reading_it_back(self):
        self.build()
        self.assertTrue(wiki.ready())
        got = wiki.page("people/maya-okafor")
        self.assertEqual((got["title"], got["kind"]), ("maya okafor", "people"))
        self.assertIn("gazebo", got["text"])
        self.assertEqual(wiki.page("Maya Okafor")["id"], "people/maya-okafor")
        self.assertEqual(wiki.page("maya-okafor.md")["id"], "people/maya-okafor")
        self.assertIsNone(wiki.page("nobody at all"))
        hits = wiki.find("maya gazebo")
        self.assertEqual(hits[0]["id"], "people/maya-okafor")
        self.assertIn("gazebo", hits[0]["snippet"])
        self.assertEqual(wiki.find("zzzz"), [])
        self.assertEqual([h["kind"] for h in wiki.find("kettle fund", kind="projects")], ["projects"])
        self.assertEqual(wiki.source("c:k")["who"], "a close friend")
        self.assertEqual(wiki.source("[[r:W1]]")["text"], "the kettle fund closes on friday")
        st = wiki.status()
        self.assertEqual(st["pages"]["people"], 8)
        self.assertGreater(st["dropped_paragraphs"], 0)

    def test_short_pages_come_from_the_wiki(self):
        self.build()
        os.makedirs(wiki.MEM)
        with open(os.path.join(wiki.MEM, "core.md"), "w") as f:
            f.write("old\n")
        del self.calls[:]
        with mock.patch.object(llm, "ask", model(self.calls)):
            done = wiki.short(install=True)
        self.assertEqual(sorted(done), ["core", "people", "projects", "timeline", "voice"])
        self.assertEqual(wiki._work_text(os.path.join(wiki.MEM, "core.md")), "the owner funds kettles and makes pottery.\n")
        self.assertEqual(len(os.listdir(profile.BACKUPS)), 1)                        # the page it replaced is kept
        self.assertNotIn("[[", "".join(c["prompt"] for c in self.calls))            # a prompt header carries no refs


class Sample(unittest.TestCase):
    """The made-up wiki the app's fixtures use: it must read as a real one does."""
    def test_the_sample_reads_like_a_built_wiki(self):
        with mock.patch.object(wiki, "DIR", SAMPLE):
            wiki._mem.clear()
            pages = wiki.index()
            self.assertEqual({e["kind"] for e in pages}, {"people", "projects", "years", "themes", "front"})
            for e in pages:
                text = wiki.page(e["id"])["text"]
                self.assertTrue(text.startswith("# "))
                self.assertEqual(e["words"], wiki._words(text))
                for block in re.split(r"\n\s*\n", text.split("\n## linked pages\n")[0].split("\n## the wiki\n")[0]):
                    if block.strip() and not block.startswith(("#", ">", wiki.COUNTED)):
                        self.assertTrue(wiki.REF.search(block), block[:60])
                for pid, _ in wiki.LINK.findall(text):
                    self.assertTrue(any(p["id"] == pid for p in pages), pid)
            self.assertEqual(wiki.find("gazebo")[0]["id"], "projects/gazebo")
            self.assertEqual(wiki.find("maya")[0]["id"], "people/maya-okafor")
        wiki._mem.clear()


class WikiTool(unittest.TestCase):
    """The answering engine's way in: find pages by words, read one in parts, refs turned into plain ids."""

    def setUp(self):
        from ctx import tools
        self.tools = tools
        p = mock.patch.object(wiki, "DIR", os.path.join(os.path.dirname(__file__), "fixtures", "wiki"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(wiki._mem.clear)
        wiki._mem.clear()

    def test_find_then_read(self):
        first = wiki.index()[0]
        text, _ = self.tools.run("wiki", {"query": first["title"]})
        self.assertIn(first["id"], text)
        text, _ = self.tools.run("wiki", {"page": first["id"]})
        self.assertIn("part 1 of", text.splitlines()[0])
        self.assertNotIn("[[", text)

    def test_mistakes(self):
        with self.assertRaises(self.tools.Bad):
            self.tools.run("wiki", {})
        with self.assertRaises(self.tools.Bad):
            self.tools.run("wiki", {"page": "no-such-page-anywhere"})

    def test_not_built(self):
        with mock.patch.object(wiki, "DIR", os.path.join(tempfile.gettempdir(), "ctx-no-wiki-here")):
            wiki._mem.clear()
            text, _ = self.tools.run("wiki", {"query": "anything"})
        self.assertIn("not written yet", text)


if __name__ == "__main__":
    unittest.main()
