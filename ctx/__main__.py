"""python3 -m ctx <command>     (python3 -m ctx --help lists every command; python3 -m ctx <command> --help explains one)"""
import json, os, sys
if sys.platform != "darwin" and not os.environ.get("CTX_ANY_OS"):      # before anything is imported: nothing is made on disk
    sys.exit("context reads mac apps and only runs on macos. (CTX_ANY_OS=1 skips this check.)")
from . import paths


VERSION = "0.1.0"
# every command, grouped, one line each: (how to call it, what it does). `--help` prints this; `<command> --help` one entry.
HELP = [
    ("collect: read your own history into ~/.context/v2", [
        ("doctor [--json]", "what this mac has and lacks, source by source. run it first"),
        ("collect", "read every source that is a file on this mac"),
        ("collect-one <source>", "read one source now, with live progress lines"),
        ("ingest", "unpack export zips from ~/Downloads, then collect"),
        ("request --list | <id>", "ask a service for your data export, in your signed-in browser"),
        ("driver --status | --every <id>=weekly|monthly|off | --dry [<id>]", "exports that come round by themselves, with you asked for one step at most"),
        ("media --status | --estimate | --scan", "pictures, voice notes, files and videos on this mac, read on this mac"),
        ("catchup --status | --run [N]", "a little of the read-through and the wiki each night, on your plan"),
        ("telegram-login", "sign in to telegram once by scanning a qr code"),
        ("collect-telegram", "the full telegram history through its api (hours)"),
        ("tick [fast|daily|weekly]", "do whatever refresh is due; a tier name forces that one"),
        ("schedule", "what is due and when each tier runs next"),
        ("watch", "tick every 15 minutes until stopped"),
    ]),
    ("ask: questions over the archive", [
        ("answer \"<question>\" [--history <json>] [--stream] [--deep | --no-dig]", "an answer from your archive with the rows it used. --no-dig: never look longer after an unsure answer"),
        ("thread <id> [--around N] [--json]", "one message in its conversation. no model"),
        ("title \"<question>\" \"<answer>\"", "a 3 to 6 word name for a chat"),
        ("lens --list | <id>", "a ready-made question: intros, tasks, money, saved"),
        ("people [--json]", "the people who matter, most written-to first. no model"),
        ("person \"<name>\" [--json]", "one person: conversations, what is open, the last messages. no model"),
        ("rules [--list] | --add \"<sentence>\" [--yes] | --off <id> | --remove <id>", "your standing rules: what counts more, what is left out, how answers are worded and shown"),
        ("journal [--json]", "the journal's sections: worth a glance, waiting on you, promised, on your mind, left open, newest notes. no model"),
        ("made [--list | --get <id>]", "what was made here from your archive (a post, a plan, a brief), with its versions"),
        ("voice --status | --build | --show <channel>", "how you write in public: measured by code, a guide per channel on your plan, used to write as you"),
        ("now [--json]", "the last 30 days for the home: who is waiting on you, what you promised, what is on your mind. no model"),
        ("starters [--json]", "up to six questions for an empty chat, from your own profile. no model"),
        ("relate \"<paragraph>\"", "things from your past that bear on what you are writing"),
        ("today [--json] [--build] | --done <id> | --dismiss <id>", "one card for this morning, or none"),
        ("coach --now '<json>'", "one nudge for what is on screen now"),
        ("facts | aggregate", "counts from the archive; aggregate: who lapsed, who is new, who went quiet. no model"),
        ("loops | batches | rank | review", "things left hanging: find them, judge them, mark which were real"),
        ("rate --question \"<q>\" --id <row> --yes|--no | --stats", "say a row was right or wrong for a question"),
    ]),
    ("connect: other apps and models", [
        ("model [--test]", "which ai plan model calls run on"),
        ("models [--json] [--refresh] [--bench]", "which model does which job; what each plan can run and how fast here"),
        ("mcp", "the read-only server other ai apps start (stdio)"),
        ("mcp --status | --install [id] [--all | --preset work|writing|people|profile] [--replace] [--json] | --remove <id>",
         "where it is registered, and whether another program changed an entry; register or remove it. tools are named context_<name>. each app has "
         "its own limits: a new one reads the short profile until opened with --all, --preset, or later with: api --set mcp:<app>"),
        ("mcp --http [--port N]", "the same tools over http, on this mac only"),
        ("remote --start | --stop | --status | --url | --rotate", "let chatgpt and claude.ai reach the archive. off by default"),
        ("api --key <name> [--preset work|writing|people|profile | --sources a,b --people \"x,y\" --after .. --before .. | --all] [--days N | --never] | --keys "
         "| --set <name> .. | --renew <name> | --revoke <name> | --log [name] | --clear <name> | --hold on|off | --never-list [..] | --status",
         "a local http api for any ai app or agent, one key per app. a new key reads nothing until a preset, limits or --all opens it, and lasts 30 days. "
         "--keys lists keys and ai apps (mcp:<app>) with what each reads and has read; --never-list is what none is ever given"),
        ("connect | note", "connect --search \"<q>\" | <id> | --enable <id> | --list: add an app, your website, a feed, a folder; note \"<name>\": your own page"),
        ("bridge --install | --status", "the browser extension's local helper"),
        ("serve", "the engine kept warm for the mac app: json lines on stdin and stdout"),
    ]),
    ("maintain: indexes, settings, cost", [
        ("understand [N] | events | wiki", "read every conversation once and remember what it means | tables of introductions, conflicts and ideas pulled "
         "from the cards | the deep profile: a page per person, project, year and theme. each takes an estimate and a status"),
        ("correct [--page <page> --line \"<text>\" --wrong|--fix \"<right>\"] [--list] [--undo <n>]", "say a line of a profile page is wrong; the page changes at once"),
        ("index [--status] [--embedder <name>]", "build or update the search-by-meaning index"),
        ("words [--status]", "the word index searches read through (the tick keeps it current)"),
        ("settings [--fast] | --set key=value", "the settings page as one json object; change a setting"),
        ("cost | rawscrub | namebook | prompts", "model calls and tokens so far | secrets out of the raw export files (counts only without --apply) | whose number is whose, counted | prompt overrides: wording this archive uses in place of a piece of a prompt"),
        ("report [--out <path>] [--json] [--try]", "a tester report: what worked and what broke here, with nothing personal in it"),
        ("remove [--all | --keep-archive | --only <id>] [--dry-run] [--json]", "list everything context has put on this mac; take it off again, into the Trash"),
        ("version", "which version this is"),
    ]),
]


# where a command's own usage is written: the module that runs it says every flag in the lines of its docstring that
# begin `python3 -m ctx <command>`. `<command> --help` prints those, so the help cannot fall behind the code's own page.
DOCS = {"understand": ("understand", "deep"), "telegram-login": (), "collect-telegram": (), "collect-one": (), "version": ()}
MORE = {"understand": "python3 -m ctx understand [N]                   read only the N conversations you wrote most in\n"
                      "python3 -m ctx understand --estimate [N]        how many conversations are unread and about how many model calls. no model call",
        "cost": "it reads the ledger of model calls on this mac and takes no flags"}


def _from_doc(cmd):
    """The usage lines a command's module gives for it, with the lines that carry on under each. "" when it gives none."""
    import importlib
    out = []
    for name in DOCS.get(cmd, (cmd.replace("-", "_"),)):
        try:
            doc = importlib.import_module("ctx." + name).__doc__ or ""
        except Exception:
            continue
        lines, keep = doc.split("\n"), False
        for line in lines:
            mine = line.strip().startswith(("python3 -m ctx %s " % cmd, "python3 -m ctx.%s " % cmd)) or line.strip() in ("python3 -m ctx " + cmd, "python3 -m ctx." + cmd)
            other = line.strip().startswith("python3 -m ctx") and not mine
            if mine:
                keep = True
            elif other or not line.strip():
                keep = False
            if keep:
                out.append(line.replace("python3 -m ctx." + cmd, "python3 -m ctx " + cmd))
    if not out:
        return ""
    cut = min(len(l) - len(l.lstrip()) for l in out)
    return "\n".join(l[cut:].rstrip() for l in out)


def usage(cmd=""):
    """The whole list on one screen, or everything about one command: its line from the list, then every way to call
    it as its own module writes them. Returns the text, "" when the command is not known."""
    if cmd:
        hits = [(u, d) for _, rows in HELP for u, d in rows if cmd in [w.strip("|") for w in u.split(" | ")[0].split()[:1]] or
                cmd in [x.split()[0] for x in u.split(" | ") if x and not x.startswith(("-", "<", "["))]]
        if not hits:
            return ""
        shared = [u for u, d in hits if len([a for a in u.split(" | ") if a[:1].isalpha()]) > 1]       # "cost | rawscrub | namebook | owner": say only this one's part
        head = []
        for u, d in hits:
            alts, parts = u.split(" | "), d.split(" | ")
            if u in shared and len(alts) == len(parts):
                k = next(i for i, a in enumerate(alts) if a.split()[0] == cmd)
                head.append(f"python3 -m ctx {alts[k]}\n    {parts[k]}")
            else:
                head.append(f"python3 -m ctx {u}\n    {d}")
        more = "\n".join(x for x in (MORE.get(cmd, ""), _from_doc(cmd)) if x)
        return "\n".join(head) + ("\n\n" + more if more else "")
    out = ["python3 -m ctx <command>        (python3 -m ctx <command> --help explains one)", ""]
    for title, rows in HELP:
        out.append(title)
        for u, d in rows:
            alts = u.split(" | ")
            names = alts if all(a[:1].isalpha() for a in alts) else alts[:1]       # "loops | batches" are four commands; "--start | --stop" are flags of one
            out.append(f"  {' | '.join(n.split(' [')[0] for n in names):<34} {d}")
    return "\n".join(out)


def version():
    import subprocess
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
                             cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        rev = ""
    if not rev:          # inside the app there is no checkout: the build wrote the commit down beside ctx/
        try:
            with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "COMMIT")) as f:
                rev = f.read().strip()[:12]
        except OSError:
            rev = ""
    return "context " + VERSION + (f" ({rev})" if rev else "")


def cost():
    rows = [json.loads(l) for l in paths.read_lines(paths.LEDGER)] if os.path.exists(paths.LEDGER) else []
    ok = [r for r in rows if "usd" in r]
    print(f'{len(ok)} calls, {sum(r["in"] for r in ok):,} tokens in, {sum(r["out"] for r in ok):,} out, '
          f'${sum(r["usd"] for r in ok):.2f}, {len(rows) - len(ok)} failed')


def review():
    """You mark each question: y = real and I want it raised, n = wrong or noise, s = skip."""
    if not os.path.exists(paths.LOOPS):
        sys.exit("nothing to review yet: run python3 -m ctx loops first")
    loops = paths.read_json(paths.LOOPS)
    y = n = 0
    with open(paths.SCORES, "a") as f:
        for i, r in enumerate(loops, 1):
            print(f'\n{i}/{len(loops)}  {r["q"]}\n      {r.get("thread")} | {r.get("date")} | {r.get("why", "")}')
            a = input("      real and useful? [y/n/s] ").strip().lower()[:1]
            if a in ("y", "n"):
                f.write(json.dumps({"q": r["q"], "ids": r.get("ids"), "ok": a == "y"}) + "\n")
                y, n = y + (a == "y"), n + (a == "n")
    if y + n:
        print(f"\nprecision: {y}/{y + n} = {100 * y // (y + n)}%")


def _after_read():
    """After any read of the sources: rows the owner had forgotten and a source wrote back are taken out again, and
    the archive rows of things made here are put back if the read rewrote the docs (rules.py, made.py)."""
    try:
        from . import rules
        rules.after_read()
    except Exception:
        pass


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd in ("version", "--version", "-V"):
        print(version())
        return
    if cmd and cmd not in ("help", "-h", "--help") and ("--help" in sys.argv[2:] or "-h" in sys.argv[2:]):
        print(usage(cmd) or usage())        # one command's entry; an unknown one gets the list
        return
    days = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 90   # window for questions, not for collecting
    if cmd == "collect":
        from . import collect
        st = collect.run(int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else None)
        _after_read()
        if sys.stdout.isatty():      # a person is reading, not the app: close with what happened and what to do next
            got = {k: v["rows"] for k, v in st.items() if v.get("rows")}
            print("\n%s rows from %d of %d sources, in %s" % (format(sum(got.values()), ","), len(got), len(st), paths.HOME))
            print("the rest were skipped, each with its reason above. python3 -m ctx doctor says what each one needs."
                  if len(got) < len(st) else "every source was read.")
            print("next: python3 -m ctx mcp --install  (lets your ai apps read this)   or   app/install.sh  (the mac app)")
    elif cmd == "loops":
        from . import llm, loops
        if not os.path.exists(paths.MESSAGES) or not os.path.exists(paths.SESSIONS):
            sys.exit("nothing collected yet: run python3 -m ctx collect first")
        st = llm.status()
        if st["using"] == "none":
            sys.exit("no model is signed in on this mac. " + st["fix"])
        files = loops.batches(days)
        print(len(files), "batches")
        try:
            print(loops.judge(files), "candidates")
            print(len(loops.rank(days)), "questions ->", paths.LOOPS_MD)
        except RuntimeError as e:      # the model call failed: say why, without a traceback
            sys.exit("stopped: " + str(e)[:300])
        cost()
    elif cmd == "model":     # which plan model calls run on. `model --test` makes one tiny call
        from . import llm
        st = llm.status()
        if "--test" in sys.argv and st["using"] != "none":
            try:
                st["test"] = llm.ask("Answer in one lowercase word.", "Say ok.", llm.FAST, tag="test").strip()[:40]
            except Exception as e:
                st["test_error"] = str(e)[:200]
        print(json.dumps(st))
    elif cmd == "connect":   # add an app that is not built in: connect --search "<q>" | <id> | --enable <id> | --disable <id> | --list
        from . import connect
        connect.main(sys.argv[2:])
    elif cmd == "note":      # the owner's own page about something: note "<name>" [--append "<text>" | --file <path> | stdin] [--replace]
        from . import canvas
        canvas.note_main(sys.argv[2:])
    elif cmd == "bridge":    # the browser extension's native host: bridge --install | --status
        from . import bridge
        bridge.main(sys.argv[2:])
    elif cmd == "understand":   # read everything once and remember what it means. --status | [N] to read only N
        from . import understand
        if "--deep" in sys.argv:    # the close read that builds the knowledge layer (deep.py). --estimate | --merge | [N]
            from . import deep
            sys.exit(deep.main(sys.argv[2:]))
        if "--estimate" in sys.argv:     # how many conversations are unread and about how many model calls that is. no model call
            from . import profile
            print(json.dumps(profile.estimate(next((int(a) for a in sys.argv[2:] if a.isdigit()), None))))
        elif "--status" in sys.argv:
            print(json.dumps(understand.status()))
        else:
            n = next((int(a) for a in sys.argv[2:] if a.isdigit()), None)
            print(json.dumps({"understand": understand.run(limit=n)}))
    elif cmd == "wiki":      # the deep profile: wiki --estimate | --build | --status | --list | --page <id> | --search "<q>" | --short
        from . import wiki
        sys.exit(wiki.main(sys.argv[2:]))
    elif cmd == "index":     # search by meaning: build or update the index. --status for units per source and size
        from . import semantic
        if "--embedder" in sys.argv:    # apple | ollama:<model already pulled> | file:<program>. saved as a setting; vectors are rebuilt, units and words kept
            from . import settings
            got = settings.set_("embedder=" + (sys.argv[sys.argv.index("--embedder") + 1] if sys.argv.index("--embedder") + 1 < len(sys.argv) else ""))
            if not got.get("ok"):
                sys.exit(got.get("error") or "could not set the embedder")
        if "--gloss" in sys.argv:       # the owner's own bilingual word list, made once by the model, kept on this mac
            print(json.dumps({"glossed": semantic.build_gloss()}))
        else:
            print(json.dumps(semantic.status() if "--status" in sys.argv else {"index": semantic.build()}))
    elif cmd == "rate":      # a row was right or wrong for a question; later searches use it. kept on this mac only
        from . import semantic
        arg = lambda k: sys.argv[sys.argv.index(k) + 1] if k in sys.argv and sys.argv.index(k) + 1 < len(sys.argv) else ""
        if "--stats" in sys.argv:
            print(json.dumps(semantic.rate_stats()))
        elif arg("--question") and arg("--id") and ("--yes" in sys.argv) != ("--no" in sys.argv):
            print(json.dumps(semantic.rate(arg("--question"), arg("--id"), "--yes" in sys.argv, arg("--kind") or "answer")))
        else:
            sys.exit('usage: python3 -m ctx rate --question "<q>" --id <row id> --yes|--no [--kind answer|maybe]   or   rate --stats')
    elif cmd == "lens":      # a ready-made question: lens --list | lens intros|tasks|money|saved
        from . import lens
        print(json.dumps(lens.listing() if "--list" in sys.argv or len(sys.argv) < 3 else lens.run(sys.argv[2]), ensure_ascii=False))
    elif cmd == "journal":   # the journal's sections as the engine builds them: journal [--json]. no model
        from . import journal
        sys.exit(journal.main(sys.argv[2:]))
    elif cmd == "made":      # things made here from the archive, with their versions: made [--list | --get <id>]
        from . import made
        sys.exit(made.main(sys.argv[2:]))
    elif cmd == "rules":     # the owner's standing rules: rules [--list] | --add "<sentence>" [--yes] | --off <id> | --on <id> | --remove <id>
        from . import rules
        sys.exit(rules.main(sys.argv[2:]))
    elif cmd == "voice":     # how the owner writes in public, measured and written up: voice --status | --build [--no-model] [--force] | --show <channel> | --check <channel> "<draft>"
        from . import voice
        sys.exit(voice.main(sys.argv[2:]))
    elif cmd == "now":       # the home's last 30 days: waiting, promised, on their mind, the months: now [--json] [--fresh]. no model
        from . import now
        sys.exit(now.main(sys.argv[2:]))
    elif cmd == "people":    # the people who matter, from conversation counts: people [--json]. no model
        from . import people
        sys.exit(people.main(sys.argv[2:]))
    elif cmd == "person":    # one person: person "<name>" [--json]. no model
        from . import people
        sys.exit(people.main(sys.argv[2:], one=True))
    elif cmd == "correct":   # the owner corrects a profile page: correct --page people --line "<text>" --wrong | --fix "<right>" | --list | --undo <n>
        from . import profile
        sys.exit(profile.correct_main(sys.argv[2:]))
    elif cmd == "aggregate":  # whole-archive counts by code: aggregate [lapsed|new|lately|quiet|shared|overview]. no model
        from . import aggregate
        sys.exit(aggregate.main(sys.argv[2:]))
    elif cmd == "events":  # introductions, conflicts, ideas pulled from the cards into tables: events [estimate|run|status] [N]
        from . import events
        sys.exit(events.main(sys.argv[2:]))
    elif cmd == "starters":  # questions for an empty chat, from the lenses and the owner's own profile: starters [--json]. no model
        from . import profile
        sys.exit(profile.starters_main(sys.argv[2:]))
    elif cmd == "relate":    # things from your past that bear on a paragraph you are writing
        from . import lens
        print(json.dumps(lens.relate(" ".join(sys.argv[2:])), ensure_ascii=False))
    elif cmd == "answer":    # a question about your history, answered from the archive with the rows it used
        from . import answer
        args, hist = sys.argv[2:], None
        if "--history" in args:      # earlier turns of this chat: --history '[{"q": "...", "a": "..."}]'
            i = args.index("--history")
            hist, args = json.loads(args[i + 1]), args[:i] + args[i + 2:]
        if "--model" in args:        # answer this one question with that model (python3 -m ctx models lists them)
            i = args.index("--model")
            from . import llm
            llm._tl.override, args = (args[i + 1] if i + 1 < len(args) else None), args[:i] + args[i + 2:]
        if "--stream" in args:       # one json line per event: phase, delta, cite, then done or error. run with python3 -u
            import signal
            signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))       # stop mid-answer: the model process ends with us, no half line

            def emit(event):
                try:
                    sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
                except BrokenPipeError:
                    sys.exit(0)
            from .serve import framed
            # after an unsure first answer a longer look follows by itself. --deep: always look longer. --no-dig: never (the one
            # answer is the last line before the end; the warm server's "deep": false). --no-deep is the same flag's older name
            dig = True if "--deep" in args else False if "--no-dig" in args or "--no-deep" in args else "auto"
            try:
                answer.answer_stream(" ".join(a for a in args if a not in ("--stream", "--deep", "--no-dig", "--no-deep")), hist, framed(emit, dig), dig=dig)
            finally:
                emit({"end": True})     # the last line: nothing follows it
            sys.exit(0)
        # --deep: when the first answer is unsure, dig (up to three rounds of the fast model directing the search) and give the surer answer
        print(json.dumps(answer.answer(" ".join(a for a in args if a not in ("--deep", "--no-dig", "--no-deep")), hist, dig="--deep" in args), ensure_ascii=False))
    elif cmd == "title":     # a 3 to 6 word lowercase name for a chat: title "<question>" "<answer>"
        from . import answer
        print(json.dumps({"title": answer.title(sys.argv[2] if len(sys.argv) > 2 else "", sys.argv[3] if len(sys.argv) > 3 else "")}, ensure_ascii=False))
    elif cmd == "coach":     # one model-written nudge for what is on screen now: coach --now '<json>'
        from . import coach
        now = json.loads(sys.argv[sys.argv.index("--now") + 1]) if "--now" in sys.argv else {}
        try:
            print(json.dumps(coach.nudge(now), ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"say": "", "kind": "none", "confidence": 1, "error": str(e)[:200]}))
    elif cmd == "facts":     # counted on this mac, no model
        from . import facts
        print(json.dumps(facts.facts(), ensure_ascii=False))
    elif cmd == "doctor":    # what this mac has and lacks
        from . import doctor
        doctor.main(sys.argv[2:])
    elif cmd == "ingest":    # unpack export zips that landed in ~/Downloads, then collect if anything was new
        from . import exports
        new = exports.ingest()
        print("new archives:", new or "none")
        if new:
            from . import collect
            collect.run()
    elif cmd == "tick":      # do whatever refresh is due. tick fast|daily|weekly forces a tier
        from . import schedule
        print(json.dumps({"tick": schedule.tick(force=set(sys.argv[2:]))}))
        _after_read()
    elif cmd == "schedule":  # what is due and when each tier runs next
        from . import schedule
        print(json.dumps(schedule.plan()))
    elif cmd == "watch":     # tick every 15 minutes until stopped
        import time
        from . import schedule
        while True:
            print(time.strftime("%H:%M"), json.dumps(schedule.tick()), flush=True)
            _after_read()
            time.sleep(15 * 60)
    elif cmd == "collect-one":       # read one source now, with live progress lines
        from . import collect
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        if name not in collect.BY_NAME:
            sys.exit("sources: " + " ".join(collect.BY_NAME))
        collect.collect_one(name)
        _after_read()
    elif cmd == "collect-telegram":   # full Telegram export through the API (hours). saved, then reused by every collect
        from . import collect
        full = os.path.join(paths.HOME, "imports", "telegram_full.jsonl")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        try:
            with open(full + ".part", "w") as out:
                n = collect.telegram(None, out)
        except (FileNotFoundError, PermissionError) as e:      # not set up, or not logged in: one line, and the saved export stays
            os.remove(full + ".part")
            sys.exit("telegram: " + str(e))
        os.replace(full + ".part", full)
        collect.collect_one("telegram")
        print("telegram", n)
    elif cmd == "batches":   # for a host agent (Claude Code, Codex) that will judge the batches itself
        from . import loops
        if not os.path.exists(paths.MESSAGES) or not os.path.exists(paths.SESSIONS):
            sys.exit("nothing collected yet: run python3 -m ctx collect first")
        for f in loops.batches(days):
            print(f)
    elif cmd == "rank":      # after a host agent wrote candidates/*.json
        from . import loops
        print(json.dumps(loops.candidates(), ensure_ascii=False, indent=1))
    elif cmd == "api":       # the archive as a local http api for any ai app or agent: --key <name> | --keys | --revoke <name> | --start | --stop | --status
        from . import api
        api.main(sys.argv[2:])
    elif cmd == "remote":    # the archive for chatgpt and claude.ai, off until started: --start | --stop | --status | --url | --rotate
        from . import remote
        sys.exit(remote.main(sys.argv[2:]))
    elif cmd == "models":    # which model does which job, on the plans connected: models [--json] [--refresh] [--bench]
        from . import models
        sys.exit(models.main(sys.argv[2:]))
    elif cmd == "serve":     # the engine kept warm for the app: json lines in, json lines out, until stdin closes. run with python3 -u
        from . import serve
        sys.exit(serve.main(sys.argv[2:]))
    elif cmd == "words":     # the word index search reads through: build what changed | --status
        from . import wordindex
        sys.exit(wordindex.main(sys.argv[2:]))
    elif cmd == "thread":    # one message in its conversation, for the app's peek: thread <id> [--around N] [--json]. no model
        from . import peek
        sys.exit(peek.main(sys.argv[2:]))
    elif cmd == "today":     # one card for this morning, or none: today [--json] [--cached] | --done <id> | --dismiss <id>
        from . import today
        sys.exit(today.main(sys.argv[2:]))
    elif cmd == "settings":  # the settings page as one json object, no model call. --fast | --set key=value
        from . import settings
        sys.exit(settings.main(sys.argv[2:]))
    elif cmd == "mcp":
        from . import mcp
        arg = lambda flag: next((a for a in sys.argv[sys.argv.index(flag) + 1:] if not a.startswith("-")), None)
        if "--http" in sys.argv:      # the same tools over http on this mac only (127.0.0.1); a tunnel is `remote --start`
            from . import remote
            remote.serve(int(arg("--port")) if "--port" in sys.argv else None)        # no --port: this install's own (remote.stored_port)
        elif "--status" in sys.argv:    # where the server stands with every ai app: a json list, read-only
            print(json.dumps(mcp.status()))
        elif "--install" in sys.argv:   # register with every ai app found on this mac, or one: --install <id>
            # one line per app goes to stderr, for a person; stdout is the json alone, for a program
            say = (lambda line: None) if "--json" in sys.argv else (lambda line: print(line, file=sys.stderr))
            # what the apps registered now may read: --all, or --preset work|writing|people|profile. left out: what each had, or the short profile
            reads = "all" if "--all" in sys.argv else None
            if "--preset" in sys.argv:
                from . import api
                try:
                    reads = api.preset(arg("--preset") or "")
                except api.Bad as e:
                    sys.exit(str(e))
            only = next((a for a in sys.argv[sys.argv.index("--install") + 1:sys.argv.index("--install") + 2] if not a.startswith("-")), None)
            print(json.dumps(mcp.install(only=only, replace="--replace" in sys.argv, say=say, reads=reads)))
        elif "--remove" in sys.argv:    # take our entry out of one app: --remove <id>
            print(json.dumps(mcp.remove(arg("--remove"), say=lambda line: print(line, file=sys.stderr))))
        else:
            mcp.serve()
    elif cmd == "telegram-login":
        # No phone number or code to type: scan a QR from the Telegram app you are already signed in to.
        from . import llm
        import asyncio, getpass
        from .collect import telegram_packages
        why = telegram_packages()       # only from a folder that is ours alone and holds the code first installed there
        try:
            from telethon import TelegramClient, errors
            import qrcode
        except ImportError:
            sys.exit(why or "telegram needs two packages, kept inside this repo. run this in the repo folder, then try again:\n"
                     "  python3 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements-telegram.txt")
        if not os.environ.get("TELEGRAM_API_ID", "").strip().isdigit() or not os.environ.get("TELEGRAM_API_HASH"):
            sys.exit("put TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first (my.telegram.org > API development tools)")

        async def login():
            tg = TelegramClient(os.path.join(paths.HOME, "telegram"), int(os.environ["TELEGRAM_API_ID"]), os.environ["TELEGRAM_API_HASH"])
            await tg.connect()
            if not await tg.is_user_authorized():
                qr = await tg.qr_login()
                for _ in range(8):
                    code = qrcode.QRCode(border=1)
                    code.add_data(qr.url)
                    print("\033[2J\033[H")
                    code.print_ascii(invert=True)
                    print("\non your phone: telegram > settings > devices > link desktop device, then scan this.\n")
                    try:
                        await qr.wait(25)
                        break
                    except asyncio.TimeoutError:
                        await qr.recreate()
                    except errors.SessionPasswordNeededError:
                        await tg.sign_in(password=getpass.getpass("your telegram two-step password: "))
                        break
            me = await tg.get_me()
            print("logged in" if me else "not logged in: run it again")
            await tg.disconnect()
            return bool(me)
        if not asyncio.run(login()):
            sys.exit(1)
    elif cmd == "request":   # ask a service for your official data export, in your signed-in browser
        from . import request
        request.main(sys.argv[2:])
    elif cmd == "driver":    # exports on a cadence, the owner asked for one step at most: driver --status | --every <service>=weekly|monthly|off | --dry [<service>]
        from . import driver
        driver.main(sys.argv[2:])
    elif cmd == "catchup":   # a little of the read-through and the wiki each night: catchup --status [--fresh] | --run [N]
        from . import catchup
        catchup.main(sys.argv[2:])
    elif cmd == "media":     # pictures, voice notes, files and videos on this mac, read on this mac: media --status | --estimate | --scan ...
        from . import media
        sys.exit(media.main(sys.argv[2:]))
    elif cmd == "rawscrub":  # take secrets out of the raw export files under imports/, in place: rawscrub (a dry run, counts only) | --apply [--yes]
        from . import rawscrub
        rawscrub.main(sys.argv[2:])
    elif cmd == "namebook":  # whose number or address is this: namebook (counts) | --build
        from . import namebook
        namebook.main(sys.argv[2:])
    elif cmd == "prompts":   # prompt overrides, for someone who tunes the wording: prompts [--status] | --check | --drop [--yes]
        from . import prompts
        sys.exit(prompts.main(sys.argv[2:]))
    elif cmd == "report":    # what worked and what broke on this mac, counts and states only: report [--out <path>] [--json] [--try [--real]] [--redact <word>]
        from . import report
        sys.exit(report.main(sys.argv[2:]))
    elif cmd == "remove":    # what context has put on this mac, and taking it off: remove [--all | --keep-archive | --only <id>] [--yes] [--dry-run] [--json]
        from . import remove
        sys.exit(remove.main(sys.argv[2:]))
    elif cmd == "review":
        review()
    elif cmd == "cost":
        cost()
    else:
        print(usage())
        if cmd not in ("", "help", "-h", "--help"):
            sys.exit("no such command: " + cmd)


try:
    main()
except KeyboardInterrupt:
    sys.exit(130)
except BrokenPipeError:      # output piped to head, or the app closed the pipe
    os._exit(0)
