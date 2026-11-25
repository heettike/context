"""Open loops from the last N days, turned into questions the AI asks you first.

Three kinds:
  owe     - someone asked or is waiting, you never answered
  promise - you said you would do something, no sign you did
  agent   - an AI session ended on a question or unfinished work you never came back to
Steps: batches (code, free) -> judge (cheap model, per batch) -> rank (strong model, once).
"""
import collections, glob, json, os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from . import llm, paths

BATCH_DIR = os.path.join(paths.HOME, "batches")
CAND_DIR = os.path.join(paths.HOME, "candidates")
BATCH_CHARS = 60000

JUDGE_PEOPLE = """You find open loops in one person's WhatsApp chats. "me" is the owner. Today is {today}.
Each thread shows its recent messages, oldest first: [ID] date who: text. More than one language may be mixed.
Report only loops still open at the END of the thread:
- owe: the other person asked a question, made a request or is waiting on the owner, and the owner never answered.
- promise: the owner said they would do or send something and nothing later shows it was done.
- waiting: the owner asked something that matters and got no answer.
Skip: anything resolved later in the thread, small talk, greetings, forwards, memes, reactions, spam, sales pitches,
bots, group chatter not aimed at the owner, and things clearly settled by a call or in person.
When unsure, leave it out. Most threads have no open loop.
Return a JSON array. Each item: {{"thread": str, "kind": "owe"|"promise"|"waiting", "what": one plain sentence,
"ids": [message IDs that show it], "date": "YYYY-MM-DD" of the open message, "weight": 1-5 (5 = money, work
commitments, close people), "sure": 1-5}}. Return [] if none."""

JUDGE_AGENT = """You review one person's AI coding-agent sessions. Today is {today}. Each session shows its project,
title, the owner's first and last message, and the agent's final message. Sessions are sorted by project, then time.
Report sessions that ended with something left hanging for the owner: the agent asked a question, offered a next step,
reported a blocker or unverified work, and the owner never replied. If a later session in the same project picks the
matter up, it is not hanging. Skip throwaway sessions and finished work.
Return a JSON array. Each item: {{"thread": project name, "kind": "agent", "what": one plain sentence saying what was
left hanging, "ids": [session IDs], "date": "YYYY-MM-DD", "weight": 1-5 (5 = shipped product at risk, money,
a decision blocking other work), "sure": 1-5}}. Return [] if none."""

JUDGE_NOTES = """You read one person's own notes. Today is {today}. Each note shows its date, title and text.
Report things the owner wrote down to do, decide or follow up that are still open and still matter: unchecked to-dos, plans with
no outcome, questions to self, people the owner meant to contact. Skip reference material, finished lists, journals with no
action in them, and anything older than a year that reads as abandoned.
Return a JSON array. Each item: {{"thread": note title, "kind": "note", "what": one plain sentence, "ids": [note IDs],
"date": "YYYY-MM-DD", "weight": 1-5, "sure": 1-5}}. Return [] if none."""

RANK = """You are the owner's assistant. Today is {today}. Below is what you know about the owner, then candidate open loops
from the owner's last {days} days. Pick the ones worth raising, at most {top}. Merge duplicates. Drop anything stale, trivial or
likely settled elsewhere. Order by how much the owner would regret missing it.
For each write a question you would ask the owner first, addressed as "you", in plain short words, lowercase, no emoji, that can be answered in one
line. Name the person or project and the date. Do not quote other people's private matters; refer to them neutrally.
Return a JSON array: {{"q": the question, "kind": str, "thread": str, "date": str, "ids": [...], "why": one short clause}}."""


def _line(m):
    who = "me" if m["who"] == "me" else ("them" + (":" + m["sender"] if m["kind"] == "group" else ""))
    return f'[{m["id"]}] {m["ts"][:10]} {who}: {m["text"][:320].replace(chr(10), " / ")}'


def batches(days=90, note_days=365):
    """Writes people-*.txt, agent-*.txt and notes-*.txt for the window. Returns their paths.
    The archive is lifetime; only the questions are limited to recent days."""
    from datetime import datetime, timedelta, timezone
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    note_cut = (datetime.now(timezone.utc) - timedelta(days=note_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(BATCH_DIR, exist_ok=True)
    for f in glob.glob(BATCH_DIR + "/*.txt"):
        os.remove(f)
    from . import rules             # every file is read through the owner's rules and the never list: what they leave out is never sent
    threads = collections.defaultdict(list)
    for m in rules.read(paths.MESSAGES):
        if str(m.get("ts") or "") >= cut and m.get("thread_id"):
            threads[m["thread_id"]].append(m)
    blocks = []
    for ms in threads.values():
        mine = sum(m["who"] == "me" for m in ms)
        if ms[0]["kind"] == "dm" and ms[0].get("mine_total", 0) < 3:
            continue  # the owner has never really talked to this number: spam, bots, vendors
        if ms[0]["kind"] == "group" and mine < 5:
            continue  # groups the owner only reads
        ms.sort(key=lambda m: m["ts"])
        blocks.append(f'### THREAD: {ms[0]["thread"]} ({ms[0]["kind"]}, {ms[0]["src"]})\n' + "\n".join(_line(m) for m in ms[-60:]))
    out = _pack(blocks, "people")
    sess = sorted((s for s in rules.read(paths.SESSIONS) if str(s.get("last_agent_ts") or "") >= cut), key=lambda s: (str(s.get("project") or ""), s["last_agent_ts"]))
    blocks = [f'### SESSION {s["id"]} | {s["src"]} | project: {os.path.basename(s["project"]) or "?"} | '
              f'{s["last_agent_ts"][:10]} | title: {s["title"]}\nFIRST ASK: {s["first_user"][:400]}\n'
              f'LAST FROM OWNER: {s["last_user"][:400]}\nAGENT\'S FINAL MESSAGE: {s["last_agent"][-1400:]}' for s in sess]
    out += _pack(blocks, "agent")
    if os.path.exists(paths.DOCS):  # notes: unfinished to-dos and plans the owner wrote to themselves
        docs = [d for d in rules.read(paths.DOCS) if d.get("src") and d.get("ts")]
        blocks = [f'### NOTE {d["id"]} | {d["src"]} | {d["ts"][:10]} | {d.get("title", "")}\n{d["text"][:6000]}'
                  for d in docs if d["src"] in ("obsidian", "apple_notes") and d["ts"] >= note_cut]
        out += _pack(blocks, "notes") if blocks else []
    return out


def _pack(blocks, name):
    files, cur, size = [], [], 0
    for b in blocks + [None]:
        if b is None or (cur and size + len(b) > BATCH_CHARS):
            p = os.path.join(BATCH_DIR, f"{name}-{len(files):02d}.txt")
            paths.write_text(p, "\n\n".join(cur))
            files.append(p)
            cur, size = [], 0
        if b:
            cur.append(b)
            size += len(b)
    return files


def judge(files, workers=4):
    os.makedirs(CAND_DIR, exist_ok=True)
    today = date.today().isoformat()

    def one(p):
        kind = os.path.basename(p).split("-")[0]
        sysmsg = {"agent": JUDGE_AGENT, "notes": JUDGE_NOTES}.get(kind, JUDGE_PEOPLE).format(today=today)
        res = llm.ask_json(sysmsg, paths.read_text(p), llm.CHEAP, tag="judge:" + os.path.basename(p))
        with open(os.path.join(CAND_DIR, os.path.basename(p)[:-4] + ".json"), "w") as f:
            json.dump(res, f, ensure_ascii=False)
        return len(res)
    with ThreadPoolExecutor(workers) as ex:
        return sum(ex.map(one, files))


def candidates():
    out = []
    for f in sorted(glob.glob(CAND_DIR + "/*.json")):
        out += [c for c in paths.read_json(f) if isinstance(c, dict) and c.get("sure", 0) >= 3]
    return [c for c in out if _ok(c)]          # judged before a rule was made: what it leaves out is not ranked


def profile_notes(limit=12000):
    from . import rules
    notes = ""
    for name in ("projects.md", "people_taste.md"):
        p = os.path.join(paths.PROFILE_DIR, name)
        if os.path.exists(p):
            notes += rules.scrub(paths.read_text(p))[:limit // 2] + "\n"
    return notes or "(no profile yet)"


def _ok(l):
    """May this loop (written by an earlier pass) be shown now: no message it rests on is left out by the owner's rules
    or the never list, nor its conversation or its day, and no word of it names what they leave out."""
    from . import rules
    if not isinstance(l, dict) or rules.broken():
        return False
    ids = l.get("ids") if isinstance(l.get("ids"), list) else [l.get("ids")] if l.get("ids") else []
    if any(rules.ref_hidden("r", str(i)) for i in ids):
        return False
    if rules.hidden({"thread": l.get("thread"), "ts": str(l.get("date") or "")}):
        return False
    said = " | ".join(str(l.get(k) or "") for k in ("q", "what", "thread", "date", "why"))
    return rules.scrub(said, blocks=False) == said


def kept():
    """The open loops of the last pass (loops.json) that may be shown now (_ok): what every reader of them uses."""
    try:
        with open(paths.LOOPS, encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        return []
    return [l for l in got if _ok(l)] if isinstance(got, list) else []


def text():
    """The open loops as loops.md has them, of those that may be shown now. "" when there are none."""
    return "".join(f'{i}. {r.get("q") or r.get("what") or ""}\n   {r.get("kind")} | {r.get("thread")} | {r.get("date")} | {", ".join(map(str, r.get("ids") or []))}\n'
                   for i, r in enumerate(kept(), 1))


def rank(days=90, top=30):
    cands = candidates()
    prompt = "## WHAT YOU KNOW\n" + profile_notes() + "\n## CANDIDATES\n" + json.dumps(cands, ensure_ascii=False)
    res = llm.ask_json(RANK.format(today=date.today().isoformat(), days=days, top=top), prompt, llm.STRONG, tag="rank")
    write(res)
    return res


def write(res):
    with open(paths.LOOPS, "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    with open(paths.LOOPS_MD, "w") as f:
        for i, r in enumerate(res, 1):
            f.write(f'{i}. {r["q"]}\n   {r.get("kind")} | {r.get("thread")} | {r.get("date")} | {", ".join(r.get("ids", []))}\n')
