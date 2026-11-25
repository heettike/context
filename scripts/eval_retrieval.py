"""How often does each kind of search put the right row in front of the model?

  python3 scripts/eval_retrieval.py                      made-up rows and questions (scripts/eval_data.py), in a temp folder
  python3 scripts/eval_retrieval.py --questions f.json   your own archive (CTX_HOME) and your own questions:
                                                         [{"kind": "...", "q": "the question", "id": "the row that answers it"}]
      --planner    let the model write the keyword probes, as `answer` does (one fast call per question, on your plan)
      --plans f    keep the planner's replies in this file and reuse them, so a second run asks nothing
      --planner-secs N   with --tiers and replies on file: wait N seconds where the planner call would be, for honest timing
      --tiers      run the whole answer pipeline with the answering call left out, and say where the right row landed:
                   strong, maybe, in a thread read in order, or nowhere
      --rate       then mark each right row "yes" and one wrong strong row "no" in a throwaway ratings file, run again,
                   and say what changed

Three searches are compared on recall@K (the share of questions whose row is in the first K rows):
  keyword    answer.search with probes: whole words that must all be in one row
  semantic   semantic.search on the question alone: units of meaning scored by context, word neighbours and vectors.
             nothing but this Mac is used
  semantic+  the same, also given the planner's probes and its guess at the answer's own words, as `answer` does
  fused      keyword and semantic+, merged by reciprocal rank
It prints numbers only: no question, no row text.
"""
import json, os, statistics, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
K = 20


def made_up():
    """A temp archive from eval_data: each answer row in a conversation or a saved post of its own, plus noise."""
    import eval_data
    home = tempfile.mkdtemp(prefix="ctx-eval-")
    os.environ["CTX_HOME"] = home
    msgs, docs, qs, where = [], [], [], {}
    for n, (kind, q, text) in enumerate(eval_data.PAIRS):
        if text not in where:
            rid = f"E{n}"
            where[text] = rid
            if kind == "saves":
                docs.append({"id": rid, "src": "x_bookmarks" if n % 2 else "instagram_saved", "ts": "2025-03-01T10:00:00Z", "title": "", "text": text, "url": f"https://example.com/p/{n}"})
            else:
                msgs.append({"id": rid, "src": "whatsapp", "ts": f"2025-02-{n % 27 + 1:02d}T10:00:00Z", "thread_id": f"whatsapp:friend {n}", "thread": f"friend {n}",
                             "kind": "dm", "who": "them" if n % 2 else "me", "sender": f"friend {n}", "text": text})
        qs.append({"kind": kind, "q": q, "id": where[text]})
    for n, text in enumerate(eval_data.NOISE * 6):
        msgs.append({"id": f"X{n}", "src": "telegram", "ts": f"2025-01-{n % 27 + 1:02d}T09:{n % 60:02d}:00Z", "thread_id": f"telegram:group {n % 9}", "thread": f"group {n % 9}",
                     "kind": "group", "who": "them", "sender": f"member {n % 5}", "text": text})
    for name, rows in (("messages.jsonl", msgs), ("docs.jsonl", docs), ("prompts.jsonl", []), ("sessions.jsonl", [])):
        with open(os.path.join(home, name), "w") as f:
            f.write("".join(json.dumps(r) + "\n" for r in rows))
    return qs


def main():
    args = sys.argv[1:]
    own = args[args.index("--questions") + 1] if "--questions" in args else ""
    if own:
        with open(own) as f:
            qs = json.load(f)
    else:
        qs = made_up()
    from ctx import answer, llm, semantic            # after CTX_HOME is set
    if not own:
        meta = semantic.build(say=lambda **kw: None)
        print(f'made-up archive: {meta["units"]} units, {meta["vectors"]} vectors, model "{meta["model"] or "none (words only)"}"')
    elif not semantic.ready():
        sys.exit("no index yet: run python3 -m ctx index")
    if "--rate" in args:                             # ratings made here never touch the real file
        semantic.FEEDBACK = os.path.join(tempfile.mkdtemp(prefix="ctx-eval-"), "feedback.jsonl")
    plans, plan_file = {}, args[args.index("--plans") + 1] if "--plans" in args else ""
    if plan_file and os.path.exists(plan_file):
        with open(plan_file) as f:
            plans = json.load(f)

    def plan_for(q):
        """The planner's reply for a question, asked once: {"probes": [...], "words": [...]}. Without --planner, the question's own words."""
        if q not in plans:
            plans[q] = {}
            if "--planner" in args:
                try:
                    out = llm.ask_json(answer.PLAN + answer.WORDS, q, llm.FAST, tag="eval:plan")
                    plans[q] = out if isinstance(out, dict) else {}
                except Exception:
                    pass
            plans[q]["probes"] = answer.clean_probes(plans[q].get("probes")) or answer.fallback_probes(q)
            if plan_file:
                with open(plan_file, "w") as f:
                    json.dump(plans, f)
        return plans[q]

    def rank(rows, rid):
        ids = [r["id"] for r in rows]
        return ids.index(rid) + 1 if rid in ids else 0

    names = ("keyword", "semantic", "semantic+", "fused")
    got, secs = {n: [] for n in names}, {n: [] for n in names}
    for item in qs:
        q, rid = item["q"], item["id"]
        probes = plan_for(q)["probes"]
        t = time.time()
        kw, _ = answer.search(probes, limit=70)
        t1 = time.time()
        sem = semantic.find(q, 40)["rows"]
        t2 = time.time()
        sem2 = semantic.find(q, 40, probes=probes + answer._plan_words(plan_for(q)))["rows"]
        fused = semantic.fuse([kw, sem2])
        t3 = time.time()
        for name, rows, dt in (("keyword", kw, t1 - t), ("semantic", sem, t2 - t1), ("semantic+", sem2, t3 - t2), ("fused", fused, (t1 - t) + (t3 - t2))):
            got[name].append((item["kind"], rank(rows, rid)))
            secs[name].append(dt)
    kinds = list(dict.fromkeys(i["kind"] for i in qs))
    print(f"\n{len(qs)} questions. recall@{K} (and recall@5), by kind of question")
    print(f'{"":10}' + "".join(f"{k:>16}" for k in kinds + ["all"]) + f'{"median secs":>14}')
    for name in got:
        cells = []
        for k in kinds + ["all"]:
            rs = [r for kk, r in got[name] if k in (kk, "all")]
            cells.append(f"{sum(0 < r <= K for r in rs) / len(rs):.2f} ({sum(0 < r <= 5 for r in rs) / len(rs):.2f})")
        print(f"{name:10}" + "".join(f"{c:>16}" for c in cells) + f"{statistics.median(secs[name]):>14.2f}")
    if "--tiers" in args or "--rate" in args:
        def place():
            """Where each right row lands in the prompt the answering model would get."""
            out, strong_wrong, took, reads, order = [], {}, [], [], []
            for item in qs:
                seen = {}

                def call(prompt, seen=seen):
                    seen["p"] = prompt
                    return {"answer": "x", "cites": []}
                keep_plan, keep_call = llm.ask_json, answer._answer_call
                def ask_json(system, prompt, model=None, tag="", q=item["q"]):
                    if not tag.endswith("plan"):                 # the pick among candidates is a real call
                        return keep_plan(system, prompt, model, tag) if "--planner" in args else {}
                    time.sleep(wait)                             # the planner's reply is on file: wait as long as it took
                    return plan_for(q)
                llm.ask_json = ask_json
                answer._answer_call = call
                t = time.time()
                try:
                    answer.answer(item["q"])
                finally:
                    llm.ask_json, answer._answer_call = keep_plan, keep_call
                took.append(time.time() - t)
                p = seen.get("p", "")
                head, _, weak = p.partition("## maybe rows")
                cut = max(head.find("## rows ("), head.find("## other rows ("))
                thread, rows = (head[:cut], head[cut:]) if cut >= 0 else (head, "")
                reads.append("## threads read in order" in thread)
                mark = f'[{item["id"]}]'
                out.append("strong" if mark in rows else "maybe" if mark in weak else "thread" if mark in thread else "nowhere")
                ids = [l[1:l.index("]")] for l in rows.split("\n") if l.startswith("[") and "]" in l]
                order.append(ids.index(item["id"]) + 1 if item["id"] in ids else 0)
                strong_wrong[item["q"]] = next((i for i in ids if i != item["id"]), "")
            print(f"right row among the first {K} strong rows of the prompt: {sum(0 < r <= K for r in order) / len(qs):.2f}   among the first 5: {sum(0 < r <= 5 for r in order) / len(qs):.2f}")
            return out, strong_wrong, statistics.median(took), sum(reads)
        wait = float(args[args.index("--planner-secs") + 1]) if "--planner-secs" in args else 0.0
        where, wrong, med, reads = place()
        count = lambda w: {k: w.count(k) for k in ("strong", "maybe", "thread", "nowhere")}
        print(f"\nwhere the right row landed in the answer prompt, of {len(qs)}: {count(where)}   conversations read in order for {reads} questions   median secs to build the prompt: {med:.2f}")
        if "--rate" in args:
            for item in qs:
                semantic.rate(item["q"], item["id"], True, kind="maybe")
                if wrong[item["q"]]:
                    semantic.rate(item["q"], wrong[item["q"]], False)
            after, wrong2, _, _ = place()
            still = sum(1 for item in qs if wrong[item["q"]] and wrong2[item["q"]] == wrong[item["q"]])
            print(f"after one yes on each right row and one no on a wrong strong row: {count(after)}   rows marked no that are still first: {still}")
            print("ratings file used: a throwaway one. stats:", {k: v for k, v in semantic.rate_stats().items() if k != "per_source"})


if __name__ == "__main__":
    main()
