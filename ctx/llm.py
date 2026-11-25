"""Model calls run on the plan the user already pays for. No keys, no extra accounts.

The engine looks for a signed-in coding CLI on this Mac and uses it:
  claude   the Claude Code CLI          (sign in once: claude auth login)
  codex    the Codex CLI, ChatGPT plan  (sign in once: codex login)
An ANTHROPIC_API_KEY in the environment or .env is used only when neither CLI is signed in, by the engine's own call to
the messages api (_api_stream, standard library only). It is never handed to a CLI: guard.CLI_DROP keeps every provider
key and address out of the environment a CLI starts with, so `claude -p` bills the plan, not the key.
CTX_MODEL=claude|codex|api forces one. Every call is logged to ledger.jsonl.
"""
import json, os, re, shutil, subprocess, tempfile, threading, time
from . import guard, paths

for _env in paths.env_files():
    if not os.path.exists(_env):
        continue
    try:
        _lines = paths.read_text(_env, encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        _lines = []
    for _l in _lines:
        if "=" in _l and not _l.lstrip().startswith("#"):
            _k, _v = _l.strip().split("=", 1)
            _k, _v = _k.strip(), _v.strip().strip('"\'')
            if _k.startswith("export "):
                _k = _k[7:].strip()
            if _v:                      # an empty line in .env (TELEGRAM_API_ID=) is not a setting
                os.environ.setdefault(_k, _v)

FAST = os.environ.get("CTX_FAST_MODEL", "claude-haiku-5-5")      # one nudge, a few thousand tokens
CHEAP = os.environ.get("CTX_CHEAP_MODEL", "claude-sonnet-5-5")   # reads every thread
STRONG = os.environ.get("CTX_STRONG_MODEL", "claude-opus-5-5")   # one ranking pass
PRICE = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00)}  # $/1M, api only
_lock = threading.Lock()
# CTX_CLI_PATH: look for the model CLIs in these folders and nowhere else. The tests set it, so that no test ever finds
# (and spends) the plan that is signed in on the mac it runs on; a made-up CLI is put in a folder it names.
_ONLY = os.environ.get("CTX_CLI_PATH")
_PATH = _ONLY if _ONLY is not None else os.pathsep.join(["/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/.local/bin"), os.environ.get("PATH", "")])
_ENV = guard.cli_env(dict(os.environ, PATH=_PATH))        # what a model cli is started with: no variable that redirects it or loads code into it


def _find(name, extra=()):
    found = shutil.which(name, path=_PATH) or next((p for p in (() if _ONLY is not None else extra) if os.access(p, os.X_OK)), None)
    return found if found and not guard.cli_ok(found) else None       # a cli another account could have put there, or can change, is not run


_claude_path = None


def _claude_cands():
    if _ONLY is not None:
        return [shutil.which("claude", path=_PATH) or ""]
    return list(dict.fromkeys([os.path.expanduser("~/.local/bin/claude"), os.path.expanduser("~/.claude/local/claude"),
                               "/opt/homebrew/bin/claude", "/usr/local/bin/claude", shutil.which("claude", path=_PATH) or ""]))


def claude_found():
    """The first program named claude where Claude Code is installed, by its files alone: nothing is started. For pages
    that only look (mcp --status); _claude_bin() is the one that is run."""
    return next((c for c in _claude_cands() if c and os.path.isfile(c) and os.access(c, os.X_OK) and not guard.cli_ok(c)), None)


def _claude_bin():
    """The real Claude Code CLI. Other programs named `claude` can sit earlier on PATH, so check that it answers `auth status`."""
    global _claude_path
    if _claude_path:
        return _claude_path
    for c in _claude_cands():
        if c and os.access(c, os.X_OK) and not guard.cli_ok(c):
            # an old build has no `auth` command and would take the words "auth status" as a prompt for the model.
            # asking for help first is safe on every build: it only prints.
            h = _run([c, "auth", "--help"], timeout=15)
            if not h or "status" not in h.stdout:
                continue
            r = _run([c, "auth", "status"])
            if r and '"loggedIn"' in r.stdout:
                _claude_path = c
                return c
    return None


def _codex_bin():
    return _find("codex", ["/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
                           "/Applications/Codex.app/Contents/Resources/codex-cli/bin/codex"])


_tl = threading.local()
_has = {}
_FLAGS = os.path.join(paths.HOME, "cli_flags.json")     # which of the flags below each installed cli knows: learned when the plan is checked, never while an answer waits


def _cli_key(path, sub=()):
    try:
        st = os.stat(path)
        return "%s|%d|%d|%s" % (path, st.st_mtime_ns, st.st_size, " ".join(sub))       # a new build of the cli is asked again
    except (OSError, TypeError):
        return ""


def learn_flags(path, wanted, sub=()):
    """Ask a cli's own --help which of `wanted` it knows, and remember the answer for that build. Called where the plan is
    checked (status()), so no answer ever waits on it."""
    key = _cli_key(path, sub)
    if not key or key in _known():
        return
    r = _run([path] + list(sub) + ["--help"], timeout=10)
    text = (r.stdout + r.stderr) if r else ""
    if not text:
        return
    _has[key] = [f for f in wanted if re.search(r"(?m)(^|[\s,])" + re.escape(f) + r"(?![\w-])", text)]
    try:
        with open(_FLAGS, "w") as f:
            json.dump(_has, f)
    except OSError:
        pass


def _known():
    if not _has:
        try:
            with open(_FLAGS) as f:
                got = json.load(f)
            _has.update({k: [x for x in v if isinstance(x, str)] for k, v in got.items() if isinstance(v, list)} if isinstance(got, dict) else {})
        except (OSError, ValueError):
            pass
    return _has


def cli_flags(path, wanted, sub=()):
    """Those of `wanted` that this build of a cli is known to take (learn_flags). A build that was never asked, or an
    older one that lacks a flag, is not handed it: a call never fails over a flag."""
    return [f for f in wanted if f in _known().get(_cli_key(path, sub), ())]


# claude: no skills or slash commands, no browser integration, on top of --tools "", --strict-mcp-config and --setting-sources ""
CLAUDE_ALONE = ("--disable-slash-commands", "--no-chrome")
# codex: not the user's config.toml (its tool servers, hooks and profiles; the sign-in is kept elsewhere) and no .rules files
CODEX_ALONE = ("--ignore-user-config", "--ignore-rules")
# codex keeps its own tools on, inside a sandbox that can write nothing. the ones that run commands, drive a browser or
# the screen, reach other apps, load plugins, skills or hooks, or remember across runs are switched off by name, where
# the installed build has a feature of that name (`codex features list`). what it is left with is the text it is given.
CODEX_OFF = ("shell_tool", "unified_exec", "unified_exec_tty", "apps", "browser_use", "browser_use_external", "browser_use_full_cdp_access", "computer_use",
             "in_app_browser", "in_app_local_automation", "plugins", "remote_plugin", "plugin_sharing", "plugin_discovery_prefetch", "hooks", "memories",
             "multi_agent", "image_generation", "view_image", "skill_search", "skill_mcp_dependency_install", "tool_suggest", "goals", "worktrees", "web_search", "web_search_request")


# what must hold before codex is handed a word of the archive, every one of them: both of the features that run
# commands are in this build's list and are switched off, and both flags that keep the user's own config and rules out
# are flags this build takes. one missing is a build whose state is not known, and it is not used.
CODEX_NEEDS = ("shell_tool", "unified_exec")
CODEX_UNSAFE = ("codex on this mac cannot be used safely to read your archive: this build will not switch off its own tools (running commands, "
                "browsing) or will not leave your own codex config out. update codex, or use claude: python3 -m ctx settings --set backend=claude")


def codex_ready(path):
    """(flags, why). The flags codex is started with when every one of CODEX_NEEDS and CODEX_ALONE is there; else [] and
    what is missing, in a few words (for the log: the owner is told CODEX_UNSAFE)."""
    off, alone = codex_off(path), cli_flags(path, CODEX_ALONE, ("exec",))
    missing = [f for f in CODEX_NEEDS if f not in off[1::2]] + [f for f in CODEX_ALONE if f not in alone]
    return ([], "missing: " + ", ".join(missing)) if missing else (alone + off, "")


def learn_codex_features(path):
    """Which of CODEX_OFF this build of codex has, asked once per build where the plan is checked."""
    key = _cli_key(path, ("features",))
    if not key or key in _known():
        return
    r = _run([path, "features", "list"], timeout=10)
    have = {l.split()[0] for l in (r.stdout if r else "").splitlines() if l.split()}
    if not have:
        return
    _has[key] = [f for f in CODEX_OFF if f in have]
    try:
        with open(_FLAGS, "w") as f:
            json.dump(_has, f)
    except OSError:
        pass


def codex_off(path):
    """["--disable", name, ...] for the features this build is known to have."""
    return [x for f in _known().get(_cli_key(path, ("features",)), ()) for x in ("--disable", f)]


def _run(cmd, timeout=25, **kw):
    # stdin is closed: a cli that is not set up yet may stop to ask a question, and nobody is there to answer
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_ENV, stdin=subprocess.DEVNULL, **kw)
    except (OSError, subprocess.TimeoutExpired):
        return None


def status():
    """Which plan the engine will use, and what to do if none is ready. Shown in the app's setup."""
    out = {"claude": {"installed": False, "signed_in": False, "path": "", "fix": "install claude code (claude.com/claude-code), then run once in a terminal: claude auth login"},
           "codex": {"installed": False, "signed_in": False, "path": "", "fix": "install codex (the chatgpt desktop app brings it), then run once in a terminal: codex login"},
           "api_key": bool(os.environ.get("ANTHROPIC_API_KEY"))}
    c = _claude_bin()
    if c:
        r = _run([c, "auth", "status"])
        ok = bool(r and re.search(r'"loggedIn"\s*:\s*true', r.stdout))
        out["claude"] = {"installed": True, "signed_in": ok, "path": c, "fix": "" if ok else "run once in a terminal: claude auth login"}
        learn_flags(c, CLAUDE_ALONE)
    x = _codex_bin()
    if x:
        r = _run([x, "login", "status"])
        ok = bool(r and "logged in" in (r.stdout + r.stderr).lower() and "not logged in" not in (r.stdout + r.stderr).lower())
        out["codex"] = {"installed": True, "signed_in": ok, "path": x, "fix": "" if ok else "run once in a terminal: " + ("codex" if shutil.which("codex", path=_PATH) else '"%s"' % x) + " login"}
        learn_flags(x, CODEX_ALONE, ("exec",))
        learn_codex_features(x)
    want = os.environ.get("CTX_MODEL", "")
    why = "CTX_MODEL=%s is set" % want
    if not want:                # the settings page's choice; the environment wins when both are set
        try:
            from . import settings
            want = {"auto": ""}.get(settings.load()["backend"], settings.load()["backend"])
        except Exception:
            want = ""
        why = "settings choose %s for model calls" % want
    order = [want] if want else ["claude", "codex", "api"]
    use = next((b for b in order if (b == "api" and out["api_key"]) or (b in ("claude", "codex") and out[b]["signed_in"])), "none")
    out["using"] = use
    out["plan"] = {"claude": "your claude plan", "codex": "your chatgpt plan", "api": "an api key, billed per token", "none": ""}[use]
    if use != "none":
        out["fix"] = ""
    elif want in ("claude", "codex"):
        out["fix"] = "%s. %s" % (why, out[want]["fix"])
    elif want:
        out["fix"] = "CTX_MODEL=%s is set but %s. unset it, or use claude, codex or api" % (want, "ANTHROPIC_API_KEY is empty" if want == "api" else "that is not a model")
    elif out["claude"]["installed"] or out["codex"]["installed"]:
        out["fix"] = out["claude"]["fix"] if out["claude"]["installed"] else out["codex"]["fix"]
    else:
        out["fix"] = "no claude code or codex cli on this mac. install either one and sign in once: claude auth login, or codex login"
    return out


_using = None


def _backend():
    """The plan in use. Remembered for ten minutes so each call does not pay for two sign-in checks."""
    global _using
    memo = os.path.join(paths.HOME, "model.json")
    if _using is None:
        try:
            m = paths.read_json(memo)
            if time.time() - m["at"] < 600 and m["using"] != "none":
                _using = m["using"]
        except (OSError, ValueError, KeyError):
            pass
    if _using is None:
        st = status()
        if st["using"] == "none":      # not remembered: the next call looks again, in case the owner just signed in
            raise RuntimeError("no model is signed in on this mac. " + st["fix"])
        _using = st["using"]
        try:
            json.dump({"using": _using, "at": time.time()}, open(memo, "w"))
        except OSError:
            pass
    return _using


def _log(row):
    if row.get("error"):        # an error is a cli's own words and can quote a header or a token: it passes the scrubber before it is kept
        from .scrub import scrub
        row = dict(row, error=scrub(str(row["error"])))
    with _lock, open(paths.LEDGER, "a") as f:
        f.write(json.dumps(dict(row, at=int(time.time()))) + "\n")      # when, so usage can be shown by day


def _claude(system, prompt, model):
    """One whole reply. Read as a stream so the call ends when the text does, not when the CLI has finished tidying up."""
    usage = {}
    text = "".join(_claude_stream(system, prompt, model, usage))
    return text, usage.get("in", 0), usage.get("out", 0), 0.0


def _codex(system, prompt, model):
    # an empty folder and a read-only sandbox: the model answers from the text it is given and can change nothing
    with tempfile.TemporaryDirectory() as box:
        last = os.path.join(box, "last.txt")
        learn_codex_features(_codex_bin())      # asked once per build; a build that cannot say which tools it has is not used
        learn_flags(_codex_bin(), CODEX_ALONE, ("exec",))      # the same for its flags: a new build is asked here, not refused until the plan is checked again
        flags, why = codex_ready(_codex_bin())       # CODEX_ALONE and codex_off(), all or nothing
        if not flags:
            raise RuntimeError("%s (this build: %s)" % (CODEX_UNSAFE, why))
        cmd = [_codex_bin(), "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-o", last] + flags
        named = model if model and not str(model).startswith("claude") and model not in ("default", "haiku", "sonnet", "opus", "fable") else ""
        if named or os.environ.get("CTX_CODEX_MODEL"):     # a model chosen for this job, else the one pinned in .env, else codex's own default
            cmd += ["-m", named or os.environ["CTX_CODEX_MODEL"]]
        system, prompt = guard.sealed(system, prompt)
        text = system + "\n\nAnswer from the material below only. Do not run commands, read files, browse or call any tool.\n\n" + prompt
        r = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=_wait(), cwd=box, env=_ENV)
        if not os.path.exists(last) and re.search(r"(?i)unknown feature|unrecognized|unexpected argument|invalid value", r.stderr or ""):
            raise RuntimeError(CODEX_UNSAFE)        # this build refused a switch: it is not run with its tools on
        if not os.path.exists(last):
            raise RuntimeError(f"codex: {(r.stderr or r.stdout)[-300:]}")
        return paths.read_text(last), 0, 0, 0.0


def _api(system, prompt, model):
    """One whole reply from the messages api: _api_stream read to its end (it seals the call)."""
    usage = {}
    text = "".join(_api_stream(system, prompt, model, usage))
    return text, usage.get("in", 0), usage.get("out", 0), usage.get("usd", 0.0)


def _wait():
    """Seconds to wait for one model reply. Someone is watching an answer, so it gets less than a background read."""
    return int(os.environ.get("CTX_MODEL_TIMEOUT") or (90 if _tl.__dict__.get("live") else 240))


class use_model:
    """For the answer being made on this thread, use this model for the answer itself (the composer's picker)."""
    def __init__(self, model_id):
        self.id = model_id

    def __enter__(self):
        _tl.override = self.id or None

    def __exit__(self, *a):
        _tl.override = None


def _route(model, tag):
    """(plan, model to pass, job) for a call: the owner's choice of model for that job when the caller asked for one of
    the three default sizes. A size pinned in .env stays as pinned. Any trouble here and the call goes as it always did."""
    try:
        from . import models
        sizes = tuple(m if not os.environ.get(k) else None for m, k in ((FAST, "CTX_FAST_MODEL"), (CHEAP, "CTX_CHEAP_MODEL"), (STRONG, "CTX_STRONG_MODEL")))
        # one answer's own model (the composer's picker), or CTX_ANSWER_MODEL for a whole run (the eval, per model)
        plan, ask_as, job = models.route(tag, model, sizes, getattr(_tl, "override", None) or os.environ.get("CTX_ANSWER_MODEL"))
        return (plan or _backend()), ask_as, job
    except RuntimeError:
        raise
    except Exception:
        return _backend(), model, None


def _recover(e, name, model, asked, job, tried):
    """What to try instead when a call fails for a reason about the model, not the question: (plan, model) or None.
    A model that is gone: the size the caller asked for. A plan at its limit: the lean model, for everyday answers,
    when the owner allows it. Each is tried once and leaves a note the settings page shows."""
    from . import models
    text = str(e)
    if "issue with the selected model" in text and "gone" not in tried and model != asked:
        tried.add("gone")
        models.note(f"{model} could not be run on your {name} plan (retired, or not part of the plan). used {asked} instead.")
        return _backend(), asked
    if models.limit_text(e) and "limit" not in tried:
        tried.add("limit")
        models.limited(name, e)
        if getattr(_tl, "no_fallback", False):      # work nobody is waiting for (the nightly catch-up) ends at the limit: no other model in its place
            return None
        try:
            from . import settings
            allowed = settings.load().get("fallback_when_limited", "on") == "on"
        except Exception:
            allowed = True
        lean = models.lean_for(name) if allowed and job == "routine" else None
        if lean and (lean["plan"], lean["ask"]) != (name, model):
            models.note(f"your {name} plan hit its limit. everyday answers use {lean['name']} for now.")
            return lean["plan"], lean["ask"]
    return None


def ask(system, prompt, model=CHEAP, tag=""):
    _tl.live = tag.startswith(("answer", "lens", "relate", "coach"))
    asked = model
    name, model, job = _route(model, tag)
    t, tried = time.time(), set()
    for attempt in (1, 2, 3, 4):
        try:
            text, i, o, usd = {"claude": _claude, "codex": _codex, "api": _api}[name](system, prompt, model)
            break
        except Exception as e:
            other = None
            try:
                other = _recover(e, name, model, asked, job, tried)
            except Exception:
                pass
            if other:
                name, model = other
                continue
            if attempt >= 2 or isinstance(e, subprocess.TimeoutExpired) or tried:      # a timeout already used its whole wait: do not wait again
                _log({"tag": tag, "model": model, "backend": name, "error": str(e)[:300]})
                raise
            time.sleep(3)
    _log({"tag": tag, "model": model if name != "codex" or model != asked else os.environ.get("CTX_CODEX_MODEL", "codex default"), "backend": name,
          "in": i, "out": o, "usd": round(usd, 5), "secs": round(time.time() - t, 1), "prompt_chars": len(prompt), **({"job": job} if job else {})})
    return text


def _claude_stream(system, prompt, model, usage):
    """Text as the Claude CLI writes it. Flags and event shapes as `claude -p --help` and a live run show them:
    --output-format stream-json needs --verbose with -p, and --include-partial-messages adds lines of
    {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": ...}}};
    the last line is {"type": "result", "usage": {...}, "is_error": bool, "result": whole text}.
    The reply is complete at the "message_stop" event; the CLI then spends about three more seconds on its own
    bookkeeping before "result" and exit. Nothing in that tail is ours, so we stop reading there and end the process."""
    import signal
    if not _claude_bin():
        raise RuntimeError("no model is signed in on this mac. run once in a terminal: claude auth login")
    system, prompt = guard.sealed(system, prompt)       # what is read from the archive goes in as marked material, never as bare text
    hand, files = guard.hand_over({"system.txt": system})       # by path, in a file of the owner's alone: a command line is anyone's to read (ps)
    cmd = [_claude_bin(), "-p", "--model", model, "--output-format", "stream-json", "--include-partial-messages", "--verbose",
           "--system-prompt-file", files["system.txt"], "--tools", "", "--strict-mcp-config", "--no-session-persistence", "--setting-sources", ""] + cli_flags(_claude_bin(), CLAUDE_ALONE)
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=guard.empty_dir(), env=_ENV,
                             start_new_session=True)       # its own group, so stopping it stops whatever it started too
    except BaseException:
        guard.hand_back(hand)
        raise
    late = []

    def end():
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                p.kill()
    clock = threading.Timer(_wait(), lambda: (late.append(1), end()))
    clock.daemon = True
    clock.start()
    sent, done, tail, stop, early = False, None, "", None, False
    _live[threading.get_ident()] = p            # so a caller on another thread can stop this call (llm.cancel)
    try:
        try:
            p.stdin.write(prompt)
            p.stdin.close()
        except OSError:
            pass
        for line in p.stdout:
            try:
                d = json.loads(line)
            except ValueError:
                tail = line.strip()[:300] or tail
                continue
            if not isinstance(d, dict):
                continue
            if d.get("type") == "stream_event":
                ev = d.get("event") or {}
                delta = ev.get("delta") or {}
                if ev.get("type") == "content_block_delta" and delta.get("type") == "text_delta" and delta.get("text"):
                    sent = True
                    yield delta["text"]
                elif ev.get("type") == "message_start":
                    usage["model"] = (ev.get("message") or {}).get("model") or ""       # the model that really serves this call
                    u = (ev.get("message") or {}).get("usage") or {}
                    usage["in"] = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                elif ev.get("type") == "message_delta":
                    u = ev.get("usage") or {}
                    usage["out"] = u.get("output_tokens", usage.get("out", 0))
                    if u.get("input_tokens") is not None:
                        usage["in"] = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                    stop = delta.get("stop_reason")
                elif ev.get("type") == "message_stop" and sent and stop in (None, "end_turn", "stop_sequence", "max_tokens"):
                    early = True
                    break
            elif d.get("type") == "result":
                done = d
        if late:
            raise subprocess.TimeoutExpired(cmd[:2], _wait())
        if early:
            return
        if done is None:
            raise RuntimeError(f"claude: {tail or 'ended without a reply'}")
        if done.get("is_error"):
            raise RuntimeError(f"claude: {str(done.get('result'))[:300]}")
        u = done.get("usage") or {}
        usage.update({"in": u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0), "out": u.get("output_tokens", 0)})
        if not sent and done.get("result"):         # a CLI that sent no partial lines still gets its reply through, in one piece
            yield str(done["result"])
    finally:                                        # reached when the reply ends, when it fails, and when the reader walks away
        _live.pop(threading.get_ident(), None)
        clock.cancel()
        end()
        try:
            p.stdout.close()
            p.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass
        guard.hand_back(hand)


_live = {}      # thread id -> the model process that thread is waiting on


def cancel(thread_id):
    """Stop the model call a thread is waiting on, if any. The call then fails in that thread like any broken call."""
    import signal
    p = _live.get(thread_id)
    if p is not None and p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            p.kill()
        return True
    return False


def _codex_stream(system, prompt, model, usage):
    yield _codex(system, prompt, model)[0]      # `codex exec --json` prints events, but their shape is not documented: the whole reply, once


API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2026-10-21"
API_MODEL = os.environ.get("CTX_API_MODEL", "claude-opus-5-5")        # when a call names no api model of its own (a cli alias, a codex name)
API_FALLBACK = ("claude-opus-5-5", "claude-sonnet-5-5")                # these take the api's own fallback when its safety check declines a call


def _api_error(code, body):
    """The api's own words for a failed request, short. The key is in the request header only: no reply repeats it."""
    try:
        d = json.loads(body.decode("utf-8", "replace") if isinstance(body, bytes) else body)
        e = d.get("error") or {}
        return "%s %s: %s" % (code, e.get("type", ""), str(e.get("message", ""))[:200])
    except (ValueError, AttributeError):
        return "%s" % code


def _api_stream(system, prompt, model, usage):
    """The reply as the messages api streams it (server-sent events), read with the standard library: nothing to install.
    The key goes in this one request's header and nowhere else; it never reaches a cli's environment (guard.CLI_DROP)."""
    import urllib.request, urllib.error
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("no ANTHROPIC_API_KEY is set, in the environment or .env")
    model = model if isinstance(model, str) and model.startswith("claude-") else API_MODEL
    system, prompt = guard.sealed(system, prompt)
    body = {"model": model, "max_tokens": 32000, "stream": True, "system": system, "messages": [{"role": "user", "content": prompt}]}
    head = {"content-type": "application/json", "x-api-key": key, "anthropic-version": API_VERSION}
    if model in API_FALLBACK:
        body["fallbacks"] = "default"
        head["anthropic-beta"] = "server-side-fallback-2026-07-01"
    req = urllib.request.Request(API_URL, data=json.dumps(body).encode("utf-8"), headers=head, method="POST")
    try:
        r = urllib.request.urlopen(req, timeout=_wait())
    except urllib.error.HTTPError as e:
        raise RuntimeError("api: " + _api_error(e.code, e.read()))
    stop, served = None, model
    with r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                d = json.loads(line[5:].strip())
            except ValueError:
                continue
            kind = d.get("type") if isinstance(d, dict) else None
            if kind == "message_start":
                m = d.get("message") or {}
                served = usage["model"] = m.get("model") or model       # the model that really serves this call
                u = m.get("usage") or {}
                usage["in"] = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
            elif kind == "content_block_delta":
                delta = d.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield delta["text"]
            elif kind == "message_delta":
                stop = (d.get("delta") or {}).get("stop_reason") or stop
                usage["out"] = (d.get("usage") or {}).get("output_tokens", usage.get("out", 0))
            elif kind == "error":
                raise RuntimeError("api: " + _api_error("stream", json.dumps(d)))
            elif kind == "message_stop":
                break
    if stop == "refusal":
        raise RuntimeError("model refused")
    pi, po = PRICE.get(served, PRICE.get(model, (0, 0)))
    usage["usd"] = (usage.get("in", 0) * pi + usage.get("out", 0) * po) / 1e6


def stream(system, prompt, model=CHEAP, tag=""):
    """The reply as it is written: a generator of pieces of text, on the same plan, timeout and ledger as ask().
    Stop reading (close the generator, or let it go) and the model process is stopped with it. No second try:
    half an answer cannot be taken back."""
    _tl.live = tag.startswith(("answer", "lens", "relate", "coach"))
    asked = model
    name, model, job = _route(model, tag)
    t, usage, chars, tried = time.time(), {}, 0, set()
    row = {"tag": tag, "model": model if name != "codex" or model != asked else os.environ.get("CTX_CODEX_MODEL", "codex default"), "backend": name, "stream": True}
    try:
        while True:
            try:
                for piece in {"claude": _claude_stream, "codex": _codex_stream, "api": _api_stream}[name](system, prompt, model, usage):
                    chars += len(piece)
                    yield piece
                break
            except Exception as e:          # nothing written yet and the trouble is the model, not the question: one other model
                try:
                    other = _recover(e, name, model, asked, job, tried) if not chars else None
                except Exception:
                    other = None
                if not other:
                    raise
                name, model = other
                row.update(model=model, backend=name)
    except GeneratorExit:
        _log(dict(row, stopped=True, secs=round(time.time() - t, 1), prompt_chars=len(prompt), out_chars=chars))
        raise
    except Exception as e:
        _log(dict(row, error=str(e)[:300]))
        raise
    _log(dict(row, **{"in": usage.get("in", 0), "out": usage.get("out", 0), "usd": round(usage.get("usd", 0.0), 5), "secs": round(time.time() - t, 1),
                      "prompt_chars": len(prompt)}))


def parse_json(text):
    """The first JSON object or array in a model reply, forgiving the usual slips: a code fence, prose around it,
    raw newlines inside strings, text after the closing brace. None when there is none."""
    text = re.sub(r"^```[a-z]*\s*|\s*```\s*$", "", (text or "").strip())
    dec = json.JSONDecoder(strict=False)
    for m in re.finditer(r"[\[{]", text):
        try:
            return dec.raw_decode(text[m.start():])[0]
        except json.JSONDecodeError:
            continue
    return None


def ask_json(system, prompt, model=CHEAP, tag=""):
    """Returns the first JSON array or object in the reply. Asks once more if the reply cannot be read."""
    for attempt in (0, 1):
        text = ask(system + "\nReply with JSON only. No prose, no code fence." +
                   (" Your last reply was not valid JSON: escape quotes and newlines inside strings." if attempt else ""), prompt, model, tag)
        out = parse_json(text)
        if out is not None:
            return out
        try:        # keep the unreadable reply's shape (not its text) so the cause can be found later
            with open(os.path.join(paths.HOME, "bad_replies.log"), "a") as f:
                f.write(json.dumps({"tag": tag, "chars": len(text or ""), "head": re.sub(r"[A-Za-z0-9]", "x", (text or "")[:80])}) + "\n")
        except OSError:
            pass
    return []
