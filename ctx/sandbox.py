"""Run code we did not write (a reader the owner's model wrote) inside the macOS sandbox, where the kernel says no.

Checking code before it runs (connect.vet) and patching python while it runs (connect.RUNNER) can both be talked
around: python has too many ways to reach a file or a socket. So the child process is started by /usr/bin/sandbox-exec
with a profile that denies everything and then allows exactly this (profile() below is the whole of it):
  - reading python itself and what it loads: the folders of this python (its prefix, and for a packaged python the
    package folders its libraries live in), the system's libraries and frameworks (/usr/lib, /System/Library,
    /Library/Apple, the dyld cache), the time zone and text tables, and the machine-wide preferences file
  - reading the folders named (the app's own data folders)
  - reading and writing one work folder (the reader's code, its temp files, its rows)
  - looking at (not opening, not listing) the folders that lie above any of those, which opening a path needs
  - the names directly in the root folder (the loader opens it), /dev/null, /dev/zero and the random devices
  - becoming python: the process sandbox-exec starts may turn into this python (by the path given, its real path, and
    the framework's own copy), and into nothing else
There is no network of any kind and no switch that allows one. No new process can be made at all (not a shell, not
curl, not another python). Nothing else on the disk can be read, written, listed or looked at: not the archive, not
~/.ssh, not the browser's profile, not whether a file outside exists. Kernel settings (sysctl: the machine's name
among them) cannot be read. The rules are enforced by the kernel. tests/test_reader_sandbox.py tries each denial for real.

sandbox-exec is marked deprecated by Apple and has been for years; it is what Chromium, Bazel, the Codex CLI and
Claude Code's sandbox still use on macOS. If it is missing or will not start, nothing is run: see run().
"""
import os, subprocess, sys

TOOL = "/usr/bin/sandbox-exec"
_works = {}


class Unavailable(Exception):
    """The sandbox could not be started, so the code was not run."""


def _q(p):
    return '"' + str(p).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _python_paths(python):
    """Where this python and what it loads live. Read-only in the sandbox."""
    out = ["/usr/lib", "/System/Library", "/Library/Apple", "/private/var/db/dyld", "/private/var/db/timezone", "/usr/share/zoneinfo", "/usr/share/icu",
           "/private/etc/localtime", "/Library/Preferences/.GlobalPreferences.plist"]
    real = os.path.realpath(python)
    for p in {os.path.dirname(python), os.path.dirname(real), sys.base_prefix, sys.prefix, sys.exec_prefix, os.path.realpath(sys.base_prefix)}:
        if p and p != "/":
            out.append(p)
    under = lambda root: real.startswith(root + "/") or python.startswith(root + "/")
    for root in ("/opt/homebrew", "/usr/local"):
        if under(root):            # the libraries a packaged python links against (sqlite, openssl, readline): the package folders, not etc, var or what other programs keep there
            out += [os.path.join(root, d) for d in ("Cellar", "opt", "lib", "Frameworks")]
    for root in ("/Library/Developer/CommandLineTools", "/Applications/Xcode.app", "/Library/Frameworks/Python.framework"):
        if under(root):
            out.append(root)
    return list(dict.fromkeys(out))


def _python_programs(python):
    """The only files the sandboxed process may turn into: this python, by the name given and by its real path, and the copy
    of itself a framework build becomes (Python.app). Each a single file."""
    out = [python, os.path.realpath(python)]
    for prefix in dict.fromkeys((sys.base_prefix, sys.exec_prefix, os.path.realpath(sys.base_prefix))):
        if prefix and prefix != "/":
            out.append(os.path.join(os.path.realpath(prefix), "Resources", "Python.app", "Contents", "MacOS", "Python"))
    return list(dict.fromkeys(out))


def _above(paths):
    """Every folder on the way down to these paths, each as one name: a path can only be opened when the folders above it can be looked at."""
    out = []
    for p in paths:
        while True:
            p = os.path.dirname(p)
            if not p or p == "/":
                break
            out.append(p)
    return list(dict.fromkeys(out))


def profile(read=(), write=(), python=None):
    """The rules, in the sandbox's own language. read and write are folders (or files); each is resolved first, since the
    kernel compares real paths. Everything not named is denied, and there is no way to ask for the network."""
    python = python or sys.executable
    real = lambda p: os.path.realpath(os.path.expanduser(str(p)))
    reads = list(dict.fromkeys(_python_paths(python) + [real(p) for p in read] + [real(p) for p in write]))
    lines = ["(version 1)", "(deny default)",
             # the one start there is: sandbox-exec becoming python (a framework build then becomes its Python.app). making a new process is not allowed at all
             "(allow process-exec %s)" % " ".join("(literal %s)" % _q(p) for p in _python_programs(python)),
             # a look (does it exist, how big, a link's target) at the folders above what may be read, and at nothing else: never content, never a listing
             "(allow file-read-metadata (literal \"/\") (literal \"/private\") (literal \"/var\") (literal \"/tmp\") (literal \"/etc\") %s)" % " ".join("(literal %s)" % _q(p) for p in _above(reads + [python])),
             # the loader opens the root folder itself, so the names directly in it can be listed; nothing below them can
             "(allow file-read* (literal \"/\") (literal \"/dev/null\") (literal \"/dev/urandom\") (literal \"/dev/random\") (literal \"/dev/zero\") (literal \"/dev/dtracehelper\"))",
             "(allow file-write-data (literal \"/dev/null\") (literal \"/dev/dtracehelper\"))",
             "(allow file-read* %s)" % " ".join("(subpath %s)" % _q(p) for p in reads),
             "(allow file-write* %s)" % " ".join("(subpath %s)" % _q(real(p)) for p in write) if write else "",
             "(deny network*)"]
    return "\n".join(l for l in lines if l)


def available(python=None):
    """Can a python be started inside the sandbox on this mac? Asked once per python."""
    python = python or sys.executable
    if python not in _works:
        ok = False
        if sys.platform == "darwin" and os.access(TOOL, os.X_OK):
            try:
                r = subprocess.run([TOOL, "-p", profile(python=python), python, "-I", "-c", "print(40 + 2)"], capture_output=True, text=True, timeout=30,
                                   stdin=subprocess.DEVNULL, env=_env(None))
                ok = r.returncode == 0 and r.stdout.strip() == "42"
            except (OSError, subprocess.SubprocessError):
                ok = False
        _works[python] = ok
    return _works[python]


def _env(tmp):
    """Nothing of the owner's environment goes in: no tokens, no PYTHONPATH, no proxy settings. HOME stays so a reader can
    spell its paths with ~."""
    env = {"PATH": "/usr/bin:/bin", "HOME": os.path.expanduser("~"), "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    if tmp:
        env["TMPDIR"] = tmp
    return env


def run(args, read=(), write=(), timeout=60, cwd=None, tmp=None, python=None):
    """Run `python -I <args>` inside the sandbox. Returns the finished process (stdout, stderr, returncode). Raises
    Unavailable when the sandbox cannot be started on this mac: the code is then not run at all, never run in the open.
    subprocess.TimeoutExpired passes through; the child and whatever it started are killed with it."""
    python = python or sys.executable
    if not available(python):
        raise Unavailable("the macos sandbox could not be started, so the reader was not run")
    cmd = [TOOL, "-p", profile(read=read, write=write, python=python), python, "-I"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, stdin=subprocess.DEVNULL, env=_env(tmp), start_new_session=True)
