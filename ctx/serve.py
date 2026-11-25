"""The engine kept warm: one long-lived process the app starts once and talks to in JSON lines.

  python3 -u -m ctx serve

Each line on stdin is one request, {"id": <any>, "cmd": "...", ...}; every line written back carries that id.
Requests run side by side. The process ends when stdin closes.
Every request ends with one last line, {"id": <id>, "end": true}: after it nothing more comes for that id, so the app
never has to wait and guess. In a streamed answer, when a deeper search will follow the first {"done"}, the line
{"phase": "dig-pending"} comes right after that done; then {"phase": "dig"} lines and a second {"done", "deep": true}.

  answer      {"q": "...", "history": [...], "stream": true}   event lines as `answer --stream` prints them
                                                                ({"phase"}, {"delta"}, {"cite"}), then {"done"} or {"error"};
                                                                without "stream": one {"result": the reply}
                                                                "deep": true looks deeper (three more rounds at most): in a stream,
                                                                {"phase": "dig"} events and a second {"done", "deep": true}
                                                                "sources", "after", "before", "people", "kind" limit the question
                                                                (passed to the answer as its scope)
                                                                "model": "<id>" answers this one question with that model
  models      {} | {"refresh": true}                           which model does which job, what each plan can run, speeds
  title       {"q": "<question>", "a": "<answer>"}             {"result": {"title": a few words to name the chat}}
  thread      {"msg": "<row id>", "before": 15, "after": 15}   {"result": the message in its conversation}
  today       {} (the card the daily tick made: a read of the cache) | {"build": true} | {"done": "<card id>"} | {"dismiss": "<card id>"}
  settings    {} | {"fast": true} | {"set": "key=value"}
  mcp-status  {}
  rate        {"question": "...", "row": "<row id>", "ok": true, "kind": "answer"} | {"stats": true}
  facts       {}
  doctor      {}                                               what this mac has and lacks, as `doctor --json`
  report      {} | {"try": true}                               the tester report as data: counts and states, nothing personal
  index-status {}                                              the word, meaning, thread and id indexes: current or not
  collect-status {}                                            every source's last read, and whether a read is running now
  collect     {"src": "<source>"} | {"tick": ["fast"]}         run a read; its progress lines come as {"event": "progress", ...},
                                                                then {"result": {"exit": 0, ...}}
  subscribe   {}                                               stays open: {"event": "sync", "src": ..., "new": N, "rows": R} each
                                                                time a read lands rows, until cancelled
  rules-list  {}                                               {"result": [rule, ...]}: the owner's standing rules, each {"id", "said", "kind", "target", "strength"?, "made", "on", "affects"}
  rule-propose {"text": "<their sentence>"}                      {"result": {"rule": rule without id | null, "says": what will change, "ask": a question back | "",
                                                                "affects": {"rows", "threads", "from", "to"}, "destructive": bool}}: one small model call; saves nothing
  rule-save   {"rule": {...}}                                  {"result": rule} (a forget rule moves its rows to a backup here) or {"result": {"error"}}
  rule-set    {"rule_id": "..", "on": false}                   {"result": rule}
  rule-remove {"rule_id": ".."}                                {"result": {"removed": true, "restored"?: n, "says"?: "..."}}: a forget rule's rows come back within 30 days
  prefs       {}                                               {"result": {"answers": {...}, "about_you": {...}, "journal": {...}, "new_chat": {...}}}: how things are shown, from the "show" rules
                                                                an answer's "done" carries "rules": [ids of the rules that shaped it]
  journal     {}                                               {"result": {"date", "sections": [{"id": today|waiting|promised|mind|open|notes, "title", "lines": [{"anchor", "text", "row", "thread", "when", "note"?}]}], "removed": n}}
                                                                by code, no model; which sections show is their "show" rule for the journal (prefs.journal.sections, [] = all)
  journal-edit {"line": anchor, "action": "remove" | "comment" | "restore", "text"?: "..."}      {"result": the journal as it now reads}: a removed line stays out
  wiki-edit   {"page": id, "para": anchor, "action": "remove" | "correct" | "comment" | "pin" | "unpin" | "restore", "text"?: "..."}
                                                               {"result": {"page": id, "text": the page as it now reads, "paras": [{"anchor", "text", "refs", "note"?, "pinned"?}]}}
                                                                anchors come from `wiki --page <id> --json` ("paras"); their edits are applied whenever the page is read
  made-list   {}                                               {"result": [{"id", "title", "kind", "made", "version"}]}: things made here (a post, a plan, a brief), newest first
  made-get    {"doc": id}                                      {"result": {"id", "title", "kind", "text", "made", "from": [row ids], "chat", "version", "history": [...]}}
  made-save   {"doc": id, "text": "...", "title"?: "..."}      {"result": the document}: their own edit, a new version
                                                                an answer that is a made thing carries "made": {"id", "title", "kind", "version"} in its "done"
  now         {}                                               {"result": {"at", "waiting": [{"who", "what", "when", "days", "thread", "id", "src"}],
                                                                "promised": [{"what", "when", "days", "thread", "id", "src"}], "mind": [{"what", "detail", "thread"}],
                                                                "strip": [{"ym", "n"}]}}: the last 30 days for the home, at most 4 a list, kept
                                                                until the archive changes; any list may be empty. no model (now.py)
  people      {} | {"most": N}                                 {"result": [{"name", "aliases", "apps", "threads", "messages", "mine", "first", "last"}]}
                                                                the people who matter, ranked; "unnamed": true on a bare number. no model
  person      {"name": "..."}                                  {"result": that person, "threads" as a list, plus "about", "open", "recent"}
                                                                or {"result": {"error": "nobody by that name in your archive"}}. no model
  correct     {"page": "people", "line": "...", "wrong": true} | {..., "fix": "<the right version>"} | {"list": true} | {"undo": n}
                                                                the owner corrects a profile page: recorded, and the page changed at once
  starters    {}                                               {"result": [{"q": "...", "lens": "<id>"} x4, {"q": "...", "about": ...} x2]}
  understand-estimate {"limit": N?}                            {"result": {"unread", "would_read", "calls", ...}}: the cost, before it runs
  understand  {"limit": N?}                                    the read-through: {"progress": {"read": n, "of": m, "label": ...}} lines, then
                                                                {"result": {"read", "of", "pages", "exit"}}. one at a time; cancel stops it
  understand-status {} | {"fast": true}                        {"result": {"running", "progress", "status": how far along it is}}
  connect-search {"q": "<what was typed>"}                     {"result": [{"id", "name", "kind", "what"?, "installed", ...}]}: apps, services,
                                                                and what was typed read as a website, feed, folder, file or a blank note
  connect     {"source": "<candidate id>", "only": "posts"?}   one bounded trial: {"event": "progress", "phase": ...} lines, then {"result":
                                                                {"id", "name", "kind", "source", "state": ready|needs_you|cannot, "how",
                                                                "sample": {"rows", "since"}, "detail", "ask"?: {"question", "choices"}}}
  connect-enable {"source": "<id>", "on": true, "only"?}       save it and switch it on or off; {"remove": true} forgets it. {"result": the row}
                                                                then `collect {"src": result.source}` reads it now
  connect-list {}                                              {"result": every connected source, on or off}
  exports     {}                                               {"result": {"rows": [{"id", "name", "state": denied|waiting on you|asked|failed|in|idle, "show",
                                                                "detail", "restart", "every", "next_in", "asks_for"}], "reminders": [...], "done": [...]}}
                                                                an export that is in has "show": false; a declined one is "denied" with "restart": true
                                                                "browser": {"name", "can_read", "reads_through": extension|page scripting|"", "can_request",
                                                                "request_needs"}: reading signed-in sources and asking for an export are two abilities; the
                                                                extension gives the first only, so "can_request" may be false while "can_read" is true
  exports-restart {"service": id}                              a declined or failed export is asked for again on the next tick: {"result": {"rows"}}
  exports-every {"service": id, "every": weekly|monthly|off}   how often it comes round: {"result": {"rows"}}
  catchup-status {} | {"fresh": true}                          {"result": {"nightly_calls", "last_night", "tonight", "behind", "nights_to_catch_up", "may_run_now", "why_not"}}
  telegram-login {}                                            {"event": "qr", "qr": "<address to draw as a qr code>", "n", "of"} each time the code renews, then
                                                                {"result": {"state": ok|needs_you|cannot, "detail"}}. nothing is typed: the owner scans it. cancel stops it
  note        {"name": "...", "text"?: "...", "mode"?: "append"|"replace"}   the owner's own page: {"result": {"id", "source", "name", "path", "text", "rows"}}
                                                                without "text" it only returns the page
  cancel      {"target": <id of a running request>}            the target ends with {"id": target, "cancelled": true}
  ping        {}

Why keep it running: the planner and the answer are each a model call, and what the engine does around them should
cost nothing. Here the indexes (threads, row ids, words, meaning) stay mapped in memory and are re-read only when
their files change, the counts page is kept until messages change, and the check for a signed-in CLI is made once.
No model process is kept alive: each call starts one and ends it when its text ends.
The one-shot commands call the same functions.
"""
import time
import json, os, sys, threading
from concurrent.futures import ThreadPoolExecutor
from . import paths
from . import guard


class Cancelled(Exception):
    pass


def framed(emit, dig="auto"):
    """Wrap an answer's emit so the reader is told what follows the first answer: when a deeper search will run,
    {"phase": "dig-pending"} goes out right after the first {"done"}. (The search itself is answer.py's; whether it
    will run is answer.needs_dig's call, the same test answer_stream makes.) Used by serve and by `answer --stream`."""
    from . import answer

    def out(event):
        emit(event)
        if "done" in event and not event.get("deep") and (dig is True or (dig == "auto" and answer.needs_dig(event["done"]))):
            emit({"phase": "dig-pending"})
    return out


class Server:
    def __init__(self, out=None, workers=8):
        self.out = out or sys.stdout
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(workers)
        self.running = {}           # request id (as json text) -> {"thread": ident, "stop": Event}
        self._facts = (None, None)
        self._reading = {"id": None, "progress": None}      # the read-through, when one is running here

    def write(self, obj):
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        with self.lock:
            try:
                self.out.write(line)
                self.out.flush()
            except (BrokenPipeError, ValueError):
                pass

    def warm(self):
        """Map what is slow to open, off the request path. Each piece re-reads itself later when its file changes."""
        for load in (lambda: __import__("ctx.answer", fromlist=["x"]).thread_index(), lambda: __import__("ctx.wordindex", fromlist=["x"]).status(),
                     lambda: __import__("ctx.semantic", fromlist=["x"]).index(), lambda: __import__("ctx.llm", fromlist=["x"])._claude_bin(),
                     lambda: __import__("ctx.understand", fromlist=["x"]).core(),
                     lambda: __import__("ctx.models", fromlist=["x"]).refresh_in_background()):
            try:
                load()
            except Exception:
                pass

    def facts(self):
        from . import facts, rules
        try:
            st = os.stat(paths.MESSAGES)
            stamp = (st.st_size, st.st_mtime_ns, rules.stamp())     # counted again when the owner's rules or the never list change
        except OSError:
            stamp = None
        if self._facts[0] != stamp or self._facts[1] is None:
            self._facts = (stamp, facts.facts())
        return self._facts[1]

    def index_status(self):
        from . import answer, peek, wordindex
        out = {"words": wordindex.status(), "threads": os.path.exists(answer.CACHE), "ids": os.path.exists(peek.CACHE)}
        try:
            from . import semantic
            out["meaning"] = semantic.status()
        except Exception as e:
            out["meaning"] = {"error": type(e).__name__}
        return out

    def _sources(self):
        try:
            with open(os.path.join(paths.HOME, "status.json")) as f:
                st = json.load(f)
            return st if isinstance(st, dict) else {}
        except (OSError, ValueError):
            return {}

    def collect_status(self):
        from . import schedule
        try:
            running = schedule._locked()
        except Exception:
            running = False
        return {"running": running, "sources": self._sources()}

    def collect(self, req, emit, stop):
        """Run one source's read, or a tick, as a child process and pass its progress lines on as events."""
        import subprocess
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if req.get("src"):
            args = ["collect-one", str(req["src"])]
        else:
            args = ["tick"] + [str(t) for t in (req.get("tick") if isinstance(req.get("tick"), list) else []) if t in ("fast", "daily", "weekly")]
        p = subprocess.Popen(guard.python(args), cwd=repo, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, env=dict(os.environ, PYTHONPATH=repo))
        last = ""
        try:
            for line in p.stdout:
                if stop.is_set():
                    break
                line = line.strip()
                if line.startswith("@"):
                    try:
                        emit(dict(json.loads(line[1:]), event="progress"))
                    except ValueError:
                        pass
                elif line:
                    last = line[:400]
        finally:
            if p.poll() is None and stop.is_set():
                p.terminate()
            p.stdout.close()
            code = p.wait()
        return {"exit": code, "last": last, "sources": self._sources() if not req.get("src") else {req["src"]: self._sources().get(req["src"])}}

    def connect(self, req, emit, stop):
        """One trial of a source, as a child process: its phase lines are passed on as events, its last line is the result."""
        import subprocess
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = str(req.get("source") or "")
        if not src or src.startswith("-"):
            return {"state": "cannot", "detail": "say which source: {\"source\": \"<id from connect-search>\"}"}
        args = ["connect", src] + (["--only", str(req["only"])] if req.get("only") else [])
        p = subprocess.Popen(guard.python(args), cwd=repo, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, env=dict(os.environ, PYTHONPATH=repo))
        last = ""
        try:
            for line in p.stdout:
                if stop.is_set():
                    break
                line = line.strip()
                if line.startswith("@"):
                    try:
                        emit(dict(json.loads(line[1:]), event="progress"))
                    except ValueError:
                        pass
                elif line:
                    last = line
        finally:
            if p.poll() is None and stop.is_set():
                p.terminate()
            p.stdout.close()
            p.wait()
        try:
            out = json.loads(last)
            if isinstance(out, dict):
                return out
        except ValueError:
            pass
        return {"id": src, "state": "cannot", "how": "", "sample": {"rows": 0, "since": ""}, "detail": "the trial stopped before it finished"}

    def connect_enable(self, req):
        from . import canvas, connect
        src = str(req.get("source") or "")
        if req.get("remove"):
            return canvas.remove(src)
        on = req.get("on") is not False
        if connect._canvas_id(src):
            return canvas.enable(canvas.resolve(src) or src, on, req.get("only") or None)
        return connect.enable(connect.slug(src), on)

    def understand(self, req, emit, stop, rid=None):
        """The read-through as a child process, its progress passed on as events. One at a time. A cancel ends the child
        and the model calls it started."""
        import signal, subprocess
        with self.lock:
            if self._reading["id"] is not None:
                return {"error": "the read-through is already running."}
            self._reading.update(id=json.dumps(rid), progress=None)
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        limit = req.get("limit")
        args = ["understand"] + ([str(int(limit))] if isinstance(limit, (int, float)) and not isinstance(limit, bool) and limit > 0 else [])
        last, result, seen = "", None, {"read": 0, "of": 0}
        try:
            p = subprocess.Popen(guard.python(args), cwd=repo, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, env=dict(os.environ, PYTHONPATH=repo), start_new_session=True)

            def watch():            # a sitting can take minutes with no line: do not wait for one to notice a cancel
                while p.poll() is None:
                    if stop.wait(0.2):
                        try:
                            os.killpg(p.pid, signal.SIGTERM)
                        except (OSError, AttributeError, TypeError):
                            try:
                                p.terminate()
                            except Exception:
                                pass
                        return
            threading.Thread(target=watch, daemon=True).start()
            try:
                for line in p.stdout:
                    if stop.is_set():
                        break
                    line = line.strip()
                    if line.startswith("@"):
                        try:
                            d = json.loads(line[1:])
                        except ValueError:
                            continue
                        if "rows" in d:
                            seen = {"read": d.get("rows", 0), "of": d.get("of", 0)}
                        prog = dict(seen, label=str(d.get("label") or d.get("phase") or "")[:120])
                        self._reading["progress"] = prog
                        emit({"progress": prog})
                    elif line:
                        last = line[:400]
                        try:
                            got = json.loads(line)
                            if isinstance(got, dict) and isinstance(got.get("understand"), dict):
                                result = got["understand"]
                        except ValueError:
                            pass
            finally:
                p.stdout.close()
                code = p.wait()
        finally:
            self._reading.update(id=None)
        if result is None:
            return {"error": "the read-through stopped before it finished." + (" " + last if last and not last.startswith("{") else ""), "exit": code}
        return dict(result, exit=code)

    def understand_status(self, fast=False):
        out = {"running": self._reading["id"] is not None, "progress": self._reading["progress"]}
        if not fast:
            from . import understand
            out["status"] = understand.status()
        return out

    def subscribe(self, emit, stop, every=1.0):
        """Say when a read lands rows, so the app does not have to ask. Watches the collector's own record."""
        path = os.path.join(paths.HOME, "status.json")
        seen, stamp = self._sources(), None
        emit({"event": "subscribed"})
        while not stop.wait(max(0.05, every)):
            try:
                now = os.stat(path).st_mtime_ns
            except OSError:
                continue
            if now == stamp:
                continue
            stamp, cur = now, self._sources()
            for src, st in cur.items():
                if st != seen.get(src) and isinstance(st, dict) and st.get("new"):
                    emit({"event": "sync", "src": src, "new": st["new"], "rows": st.get("rows", 0)})
            seen = cur

    def run(self, req):
        """One request, start to finish, on a worker thread."""
        rid, cmd = req.get("id"), str(req.get("cmd") or "")
        key = json.dumps(rid)
        me = {"thread": threading.get_ident(), "stop": threading.Event()}
        self.running[key] = me

        def emit(event):
            if me["stop"].is_set():
                raise Cancelled()
            if isinstance(event.get("done"), dict) and cmd == "answer":
                try:        # say so under the answer when another model than the one asked for wrote it
                    from . import models
                    late = [n["text"] for n in models._load().get("notes", []) if n.get("at", 0) >= asked_at - 1]
                    if late:
                        event = dict(event, done=dict(event["done"], fallback=late[-1]))
                except Exception:
                    pass
            self.write(dict(event, id=rid))
        asked_at = int(time.time())
        try:
            if cmd == "answer":
                from . import answer
                # what the owner limited the question to in the app; answer.py reads it. any event it emits (phase, delta,
                # cite, step, done ...) goes out as it is, with the request's id
                box = req.get("scope") if isinstance(req.get("scope"), dict) else {}     # the app may send them in a "scope" object
                scope = {k: (req[k] if k in req else box[k]) for k in ("sources", "after", "before", "people", "kind")
                         if (k in req or k in box) and (req.get(k) if k in req else box.get(k)) not in (None, [], "")}
                fresh_chat = not [h for h in (req.get("history") if isinstance(req.get("history"), list) else []) if isinstance(h, dict)]
                deep = req.get("deep")
                try:                        # a new chat opens the way their rules say (rules.py, "show" for a new chat): its scope when the owner set none, its mode when they chose none
                    from . import rules
                    if fresh_chat and not any(k in scope for k in ("sources", "after", "before", "people")):
                        scope = rules.new_chat(scope)
                    if fresh_chat and not isinstance(deep, bool) and rules.prefs()["new_chat"].get("mode") == "deep":
                        deep = True
                except Exception:
                    pass
                asked_at = int(time.time())
                from . import llm
                llm._tl.override = str(req["model"]) if req.get("model") else None       # the composer's picker: this answer only
                if req.get("stream"):       # "deep": true digs whatever the first answer; false never; left out: only when it is unsure
                    dig = deep if isinstance(deep, bool) else "auto"
                    answer.answer_stream(req.get("q", ""), req.get("history"), framed(emit, dig), dig=dig, scope=scope)
                else:
                    emit({"result": answer.answer(req.get("q", ""), req.get("history"), dig=bool(deep), scope=scope)})
            elif cmd == "models":           # which model does which job; {"refresh": true} tests each model now
                from . import models
                if req.get("refresh"):
                    models.refresh(force=True)
                emit({"result": models.report()})
            elif cmd == "title":
                from . import answer
                emit({"result": {"title": answer.title(str(req.get("q") or ""), str(req.get("a") or ""))}})
            elif cmd == "thread":
                from . import peek
                emit({"result": peek.thread(str(req.get("msg") or ""), req.get("before", req.get("around", 15)), req.get("after", req.get("around", 15)))})
            elif cmd == "today":
                from . import today
                emit({"result": today.mark(str(req["done"]), "done") if req.get("done") else today.mark(str(req["dismiss"]), "dismissed") if req.get("dismiss")
                      else today.get(cached=not req.get("build"))})
            elif cmd == "settings":
                from . import settings
                emit({"result": settings.set_(req["set"]) if req.get("set") else settings.report(fast=bool(req.get("fast")))})
            elif cmd in ("api-keys", "api-log", "api-key-make", "api-key-revoke", "api-key-set", "api-never"):     # keys for other programs: what each reads, its log, the never list (api.command)
                from . import api
                emit({"result": api.command(cmd, req)})
            elif cmd == "mcp-status":
                from . import mcp
                emit({"result": mcp.status()})
            elif cmd == "rate":
                from . import semantic
                emit({"result": semantic.rate_stats() if req.get("stats") else
                      semantic.rate(str(req.get("question") or ""), str(req.get("row") or ""), bool(req.get("ok")), str(req.get("kind") or "answer"))})
            elif cmd == "facts":
                emit({"result": self.facts()})
            elif cmd == "doctor":
                from . import doctor
                emit({"result": doctor.report()})
            elif cmd == "report":       # the tester report as data, already redacted: what `python3 -m ctx report --json` prints
                from . import report
                emit({"result": report.build(try_=bool(req.get("try")))})
            elif cmd == "index-status":
                emit({"result": self.index_status()})
            elif cmd == "collect-status":
                emit({"result": self.collect_status()})
            elif cmd == "collect":
                emit({"result": self.collect(req, emit, me["stop"])})
            elif cmd == "subscribe":
                self.subscribe(emit, me["stop"], float(req.get("every") or 1.0))
            elif cmd in ("rules-list", "rule-propose", "rule-save", "rule-set", "rule-remove", "prefs"):      # the owner's standing rules (rules.py)
                from . import rules
                emit({"result": rules.listing() if cmd == "rules-list" else rules.propose(req.get("text")) if cmd == "rule-propose" else rules.save(req.get("rule")) if cmd == "rule-save"
                      else rules.turn(str(req.get("rule_id") or ""), bool(req.get("on"))) if cmd == "rule-set" else rules.remove(str(req.get("rule_id") or "")) if cmd == "rule-remove" else rules.prefs()})
            elif cmd in ("journal", "journal-edit"):     # the journal's sections, switched by their rules; a line can be removed or commented on (journal.py)
                from . import journal
                emit({"result": journal.get() if cmd == "journal" else journal.edit(req.get("line"), str(req.get("action") or ""), req.get("text") or "")})
            elif cmd == "wiki-edit":    # their own edit to one paragraph of about you: remove | correct | comment | pin | unpin | restore; it outlives a rebuild
                from . import wiki
                emit({"result": wiki.edit(req.get("page"), str(req.get("para") or ""), str(req.get("action") or ""), req.get("text") or "")})
            elif cmd in ("made-list", "made-get", "made-save"):      # things made here from the archive, kept as documents with versions (made.py)
                from . import made
                emit({"result": made.listing() if cmd == "made-list" else (made.get(req.get("doc")) or {"error": "no such document"}) if cmd == "made-get" else made.save(req.get("doc"), req.get("text"), req.get("title"))})
            elif cmd == "now":          # the home's last 30 days: who waits on the owner, what they promised, what is on their mind, the months. no model
                from . import now
                emit({"result": now.get()})
            elif cmd == "people":
                from . import people
                emit({"result": people.people(int(req["most"])) if isinstance(req.get("most"), int) else people.people()})
            elif cmd == "person":
                from . import people
                emit({"result": people.person(req.get("name"))})
            elif cmd == "correct":
                from . import profile
                emit({"result": profile.listing() if req.get("list") else profile.undo(req["undo"]) if req.get("undo") is not None
                      else profile.correct(req.get("page"), req.get("line"), wrong=bool(req.get("wrong")), fix=req.get("fix"))})
            elif cmd == "starters":
                from . import profile
                emit({"result": profile.starters()})
            elif cmd == "understand-estimate":
                from . import profile
                emit({"result": profile.estimate(req.get("limit") if isinstance(req.get("limit"), int) else None)})
            elif cmd == "understand":
                emit({"result": self.understand(req, emit, me["stop"], rid)})
            elif cmd == "understand-status":
                emit({"result": self.understand_status(fast=bool(req.get("fast")))})
            elif cmd == "connect-search":
                from . import connect
                emit({"result": connect.search_all(str(req.get("q") or ""))})
            elif cmd == "connect":
                emit({"result": self.connect(req, emit, me["stop"])})
            elif cmd in ("connect-enable", "connect-list", "note"):
                from . import canvas, connect
                try:
                    emit({"result": self.connect_enable(req) if cmd == "connect-enable" else connect.listing() + canvas.listing() if cmd == "connect-list"
                          else canvas.note(str(req.get("name") or ""), req.get("text"), "replace" if req.get("mode") == "replace" else "append")})
                except (ValueError, SystemExit, PermissionError) as e:
                    emit({"result": {"error": str(e)}})
            elif cmd == "exports":
                from . import driver
                from . import request
                b = request.browser()
                emit({"result": {"rows": driver.rows(), "reminders": driver.status()["reminders"], "done": driver.status()["done"],
                                 "browser": {k: b.get(k) for k in ("name", "can_read", "reads_through", "can_request", "request_needs")}}})
            elif cmd == "exports-restart":
                from . import driver
                try:
                    emit({"result": {"rows": driver.restart(str(req.get("service") or ""))}})
                except ValueError as e:
                    emit({"result": {"error": str(e)}})
            elif cmd == "exports-every":
                from . import driver
                try:
                    driver.every(str(req.get("service") or ""), str(req.get("every") or ""))
                    emit({"result": {"rows": driver.rows()}})
                except ValueError as e:
                    emit({"result": {"error": str(e)}})
            elif cmd == "catchup-status":
                from . import catchup
                emit({"result": catchup.status(fresh=bool(req.get("fresh")))})
            elif cmd == "telegram-login":
                from . import telegram_login
                emit({"result": telegram_login.login(lambda e: emit(dict({"event": "qr"}, **e)), me["stop"])})
            elif cmd == "ping":
                emit({"result": "ok"})
            else:
                emit({"error": "no such command. commands: " + ", ".join(commands())})
        except Cancelled:
            pass
        except Exception as e:
            if not me["stop"].is_set():
                self.write({"id": rid, "error": f"that did not work ({type(e).__name__}). try again."})
        finally:
            try:
                from . import llm
                llm._tl.override = None     # a worker thread is reused: the next request must not inherit this one's model
            except Exception:
                pass
            self.running.pop(key, None)
            if me["stop"].is_set():
                self.write({"id": rid, "cancelled": True})
            self.write({"id": rid, "end": True})        # the last line for this id, whatever happened

    def cancel(self, target):
        """Stop a running request: its events stop, and the model call it is waiting on is ended."""
        from . import llm
        me = self.running.get(json.dumps(target))
        if not me:
            return False
        me["stop"].set()
        llm.cancel(me["thread"])
        return True

    def handle(self, line):
        line = line.strip()
        if not line:
            return
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError
        except ValueError:
            self.write({"id": None, "error": "each line must be one json object with an id and a cmd."})
            return
        if req.get("cmd") == "cancel":
            self.write({"id": req.get("id"), "result": {"cancelled": self.cancel(req.get("target"))}})
            self.write({"id": req.get("id"), "end": True})
            return
        self.pool.submit(self.run, req)

    def serve(self, stdin=None):
        stdin = stdin or sys.stdin
        threading.Thread(target=self.warm, daemon=True).start()
        self.write({"id": None, "ready": True, "pid": os.getpid()})
        try:
            for line in stdin:
                self.handle(line)
        except KeyboardInterrupt:
            pass
        for key in list(self.running):      # stdin closed: the app is gone. end what is running, model calls included
            self.cancel(json.loads(key))
        self.pool.shutdown(wait=True, cancel_futures=True)


def commands():
    """Every command the server answers, in the order run() tests for them: read from run() itself, so the list said
    to a caller who sent an unknown one is the list that is handled. "cancel" is answered by handle()."""
    import inspect, re
    try:
        src = inspect.getsource(Server.run)
    except (OSError, TypeError):
        return []
    out = []
    for one, many in re.findall(r'(?m)^\s+(?:if|elif) cmd (?:== "([^"]+)"|in \(([^)]*)\))', src):
        out += [one] if one else re.findall(r'"([^"]+)"', many)
    return list(dict.fromkeys(out + ["cancel"]))


def main(args):
    real, sys.stdout = sys.stdout, sys.stderr       # a stray print in any module must not break the line protocol
    try:
        if not os.environ.get("CTX_NO_API"):
            from . import api
            api.ensure()            # the local api runs alongside the app once the owner has made a key, and never before
        Server(real).serve()
    finally:
        sys.stdout = real
    return 0
