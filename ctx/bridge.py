"""The link between the engine and the `context` browser extension (extension/ in this repo).

The browser starts this file as a native-messaging host when the extension connects. The engine never talks to it
directly: it drops a job file in ~/.context/v2/bridge/jobs/ and waits for the answer in results/. The host passes
jobs to the extension, scrubs what comes back and writes it down. Nothing here opens a socket or talks to a server.

    python3 -m ctx bridge --install           write the host file for every Chromium browser on this mac
    python3 -m ctx bridge --status [--deep]   json: where it is installed, whether the extension answered lately. --deep also
                                              asks the extension which version it runs, and says if the folder is newer
    python3 -m ctx bridge --reload            tell the extension to load the folder's code again
    python3 -m ctx.bridge <origin>    what the browser runs (length-prefixed json on stdin/stdout)
"""
import json, os, queue, re, struct, sys, threading, time
from . import guard, paths
from .scrub import scrub

NAME = "so.context.bridge"
EXTENSION_ID = "bcgoemooaoejbcndipjlhjoojelkkdih"   # fixed by the public `key` in extension/manifest.json
ORIGIN = "chrome-extension://%s/" % EXTENSION_ID
ROOT = os.path.join(paths.HOME, "bridge")
JOBS, RESULTS, BEAT = os.path.join(ROOT, "jobs"), os.path.join(ROOT, "results"), os.path.join(ROOT, "heartbeat")
LAUNCHER = os.path.join(ROOT, "host.sh")
KEY = os.path.join(ROOT, "key")      # the secret jobs are signed with (guard.key): made on first use, 0600
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPDATA = os.environ.get("CTX_BROWSER_DATA", os.path.expanduser("~/Library/Application Support"))
BROWSERS = [("Dia", "Dia/User Data"), ("Google Chrome", "Google/Chrome"), ("Chromium", "Chromium"), ("Arc", "Arc/User Data"),
            ("Brave Browser", "BraveSoftware/Brave-Browser"), ("Microsoft Edge", "Microsoft Edge")]
IDLE = 20         # seconds the host stays connected with nothing to do; the extension asks again every minute
FRESH = 150       # a heartbeat younger than this means the extension is loaded and answering
RAW = {"id", "cid", "u", "url", "ts", "d", "next"}   # ids, links, times and a list's cursor: scrub would take them for secrets
OK_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_IN = 64 * 1024 * 1024


def _dirs():
    for d in (ROOT, JOBS, RESULTS):
        os.makedirs(d, exist_ok=True)
        os.chmod(d, 0o700)


def _write(path, obj):
    with open(path + ".part", "w") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.chmod(path + ".part", 0o600)
    os.replace(path + ".part", path)


# ---------------------------------------------------------------- the engine's side

class Offline(Exception):
    """The extension is not loaded, or did not pick the job up."""


def connected():
    try:
        return time.time() - os.path.getmtime(BEAT) < FRESH
    except OSError:
        return False


def submit(job, timeout=120, pickup=90):
    """Hand one job to the extension and wait for its answer. Returns the result; raises Offline or RuntimeError."""
    _dirs()
    jid = "%d_%s" % (time.time() * 1000, os.urandom(4).hex())
    jpath, rpath = os.path.join(JOBS, jid + ".json"), os.path.join(RESULTS, jid + ".json")
    _write(jpath, guard.sign(dict(job, id=jid, timeout=timeout), guard.key(KEY)))
    end = time.monotonic() + pickup + timeout          # waits count time awake: the wall clock leaps when the mac sleeps
    try:
        while time.monotonic() < end:
            if os.path.exists(rpath):
                with open(rpath) as f:
                    out = json.load(f)
                if not out.get("ok"):
                    raise RuntimeError(out.get("error") or "the extension could not do it")
                return out.get("result")
            if os.path.exists(jpath) and time.monotonic() > end - timeout:   # nobody took it
                raise Offline("the context extension did not answer")
            time.sleep(0.3)
        raise Offline("the context extension took too long")
    finally:
        for p in (jpath, rpath):
            try:
                os.remove(p)
            except OSError:
                pass


# ---------------------------------------------------------------- the host the browser starts

def read_msg(stream):
    """One native message: 4 bytes of length in native order, then that much utf-8 json. None at end of stream."""
    head = stream.read(4)
    if len(head) < 4:
        return None
    n = struct.unpack("=I", head)[0]
    if n > MAX_IN:              # the browser never sends more than 64 mb; a length past that is a broken or hostile peer, not a message
        return None
    body = stream.read(n)
    return json.loads(body.decode("utf-8"))


def write_msg(stream, obj):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    if len(body) > 1024 * 1024:
        raise ValueError("a message to the browser must be under 1 mb")
    stream.write(struct.pack("=I", len(body)) + body)
    stream.flush()


def clean(v, key=None):
    """Scrub every string that came back from a page, except ids, links and times."""
    if isinstance(v, str):
        return v if key in RAW else scrub(v)
    if isinstance(v, list):
        return [clean(x, key) for x in v]
    if isinstance(v, dict):
        return {k: clean(x, k) for k, x in v.items()}
    return v


def _take_jobs():
    """Job files that are really ours: plain files, owned by this user, in a folder only this user can write, signed by
    the engine with the secret in bridge/key, and asking only for what guard.job_ok allows (a named reader on its own
    site, a fetch of one of the few addresses the engine reads). Returns (jobs to pass on, [(id, why)] refused)."""
    st = os.lstat(JOBS)
    if st.st_uid != os.getuid() or st.st_mode & 0o022:
        return [], []
    out, refused, k = [], [], guard.key(KEY, make=False)
    for name in sorted(os.listdir(JOBS)):
        p = os.path.join(JOBS, name)
        if not name.endswith(".json") or not OK_ID.match(name[:-5]):
            continue
        try:
            s = os.lstat(p)
            if not (s.st_mode & 0o170000 == 0o100000 and s.st_uid == os.getuid()):   # a regular file, not a link, and ours
                continue
            if time.time() - s.st_mtime > 600:   # nobody is waiting for it any more
                os.remove(p)
                continue
            with open(p) as f:
                job = json.load(f)
            os.remove(p)
        except (OSError, ValueError):
            continue
        if not (isinstance(job, dict) and job.get("id") == name[:-5]):
            continue
        if not guard.verify(job, k):             # not written by the engine: dropped, and nothing is said back
            continue
        why = guard.job_ok(job)
        if why:
            refused.append((job["id"], why))
            continue
        job.pop("mac", None)
        out.append(job)
    return out, refused


def host(inp=None, out=None, idle=IDLE, origin=None):
    """Run until the browser hangs up, or until there has been nothing to do for `idle` seconds."""
    inp, out = inp or sys.stdin.buffer, out or sys.stdout.buffer
    if origin is not None and origin != ORIGIN:
        return 1   # some other extension asked; the browser should already refuse it
    _dirs()
    inbox = queue.Queue()

    def reader():
        try:
            while True:
                m = read_msg(inp)
                inbox.put(m)
                if m is None:
                    return
        except Exception:
            inbox.put(None)
    threading.Thread(target=reader, daemon=True).start()
    waiting, last = {}, time.monotonic()
    while True:
        _write(BEAT, {"at": time.time(), "pid": os.getpid()})
        jobs, refused = _take_jobs()
        for jid, why in refused:
            _write(os.path.join(RESULTS, jid + ".json"), {"ok": False, "error": why})
        for job in jobs:
            waiting[job["id"]] = time.monotonic() + (job.get("timeout") if isinstance(job.get("timeout"), (int, float)) else 60) + 30
            write_msg(out, job)
        try:
            m = inbox.get(timeout=0.5)
        except queue.Empty:
            m = False
        if m is None:
            return 0
        if isinstance(m, dict) and m.get("id") in waiting:
            del waiting[m["id"]]
            _write(os.path.join(RESULTS, m["id"] + ".json"),
                   {"ok": bool(m.get("ok")), "result": clean(m.get("result")), "error": str(m.get("error") or "")[:200]})
        for jid in [j for j, end in waiting.items() if time.monotonic() > end]:
            del waiting[jid]
            _write(os.path.join(RESULTS, jid + ".json"), {"ok": False, "error": "the extension did not finish"})
        if waiting or m:
            last = time.monotonic()
        elif time.monotonic() - last > idle:
            return 0


# ---------------------------------------------------------------- install and status

def _host_file(data_dir):
    return os.path.join(APPDATA, data_dir, "NativeMessagingHosts", NAME + ".json")


def extension_ok(folder):
    """"" when the extension folder is safe for a browser to load code from, else why not: the folder and every file
    the browser reads from it belong to this account, are writable by no one else, and none is a link."""
    try:
        names = [""] + sorted(n for n in os.listdir(folder) if n.endswith((".js", ".json", ".html")))
        for n in names:
            p = os.path.join(folder, n) if n else folder
            st = os.lstat(p)
            what = "extension/" + n if n else "the extension folder"
            if (st.st_mode & 0o170000) == 0o120000:
                return "%s is a link" % what
            if st.st_uid != os.getuid():
                return "%s belongs to another account" % what
            if st.st_mode & 0o022:
                return "%s can be changed by other accounts" % what
    except OSError:
        return "the extension folder is not there"
    return ""


def launcher(exe, repo):
    """The text of the small script a browser starts. Python in isolated mode with no site-packages, the engine named by
    its path: the browser's environment and folder add no code. Every word is quoted for the shell, so a folder with a
    space, a quote, a $ or a backtick in its name is one argument and nothing else."""
    import shlex
    code = 'import sys, runpy; sys.path.insert(0, sys.argv.pop(1)); runpy.run_module("ctx.bridge", run_name="__main__", alter_sys=True)'
    return '#!/bin/sh\nexec %s -I -S -c %s %s "$@"\n' % (shlex.quote(exe), shlex.quote(code), shlex.quote(repo))


def install():
    why = guard.engine_ok(REPO) or extension_ok(os.path.join(REPO, "extension"))
    if why:         # the browser would start python from this folder every minute, and load the extension's code from the
        # folder beside it: both must be the owner's alone
        raise SystemExit("the helper was not installed: %s. the folder context runs from, and its extension/ folder, must belong to you and be writable by no one else" % why)
    _dirs()
    with open(LAUNCHER, "w") as f:   # browsers start hosts with an almost empty environment, so everything is spelled out
        f.write(launcher(sys.executable, REPO))
    os.chmod(LAUNCHER, 0o700)
    for name, data_dir in BROWSERS:
        if os.path.isdir(os.path.join(APPDATA, data_dir)):
            p = _host_file(data_dir)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                json.dump({"name": NAME, "description": "context: local bridge to the engine", "path": LAUNCHER, "type": "stdio",
                           "allowed_origins": [ORIGIN]}, f, indent=1)
    return status()


def folder_version():
    try:
        with open(os.path.join(REPO, "extension", "manifest.json")) as f:
            return str(json.load(f).get("version") or "")
    except (OSError, ValueError):
        return ""


def running(timeout=20):
    """The version of the extension code the browser has loaded, "" when it is too old to say, None when it is not there."""
    if not connected():
        return None
    try:
        return str(submit({"type": "about"}, timeout=timeout, pickup=75).get("version") or "")
    except Offline:
        return None
    except RuntimeError:
        return ""


def reload():
    """Ask the extension to load the folder's code again. True when it said it would."""
    try:
        return bool(submit({"type": "reload"}, timeout=20, pickup=75).get("reloading"))
    except (Offline, RuntimeError):
        return False


def status(deep=False):
    seen = os.path.getmtime(BEAT) if os.path.exists(BEAT) else None
    more = {}
    if deep:
        have, want = running(), folder_version()
        more = {"running": have, "folder_version": want, "stale": have is not None and have != want}
    return dict({"extension_id": EXTENSION_ID, "folder": os.path.join(REPO, "extension"),
            "connected": connected(), "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(seen)) if seen else None,
            "browsers": [{"name": n, "installed": os.path.isdir(os.path.join(APPDATA, d)), "host_file": os.path.isfile(_host_file(d))} for n, d in BROWSERS]}, **more)


def main(argv):
    if argv[:1] == ["--install"]:
        print(json.dumps(install()))
    elif argv[:1] == ["--status"]:
        print(json.dumps(status(deep="--deep" in argv)))
    elif argv[:1] == ["--reload"]:
        print(json.dumps({"reloading": reload()}))
    else:
        raise SystemExit("usage: python3 -m ctx bridge --install | --status [--deep] | --reload")


if __name__ == "__main__":   # started by the browser: argv[1] is the calling extension's origin
    pipe, sys.stdout = sys.stdout.buffer, sys.stderr   # nothing but messages may reach the browser's pipe
    code = host(out=pipe, origin=sys.argv[1] if len(sys.argv) > 1 else "")
    pipe.flush()
    os._exit(code)   # the reader thread is still blocked on stdin; a normal exit would wait on it
