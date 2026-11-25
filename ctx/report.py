"""`python3 -m ctx report`: what worked and what broke on this Mac, with nothing personal in it.

For someone trying context on their own machine who will not, and should not, send their data. The report holds
counts, states, versions and timings. It holds no message, title, thread or contact name, file name from a user
folder, email, phone number, link, account name, or the name of this Mac or its user. It does not say where the Mac
is or what language it is set to: no locale, no time zone. No secret file is opened for it: not the telegram sign-in
(telegram.session), not the api keys, not the remote secret.

    python3 -m ctx report                  write ~/Desktop/context-report-<date>.txt and print where it is
    python3 -m ctx report --out <path>     write it somewhere else
    python3 -m ctx report --json           the same as one json object on stdout (with --out: into that file)
    python3 -m ctx report --redact <word>  one more word to remove wherever it appears (repeat for more)
    python3 -m ctx report --try [--real]   also run doctor, a read of the file sources into a temp folder, the mcp
                                           self-test and one tiny model call, and time each. --real: when there is no
                                           archive yet, read into the real one instead of a temp folder

How nothing personal gets out (class Redactor):
  1. nothing is copied from a row. sources are counted; their dates are cut to year-month.
  2. text the engine wrote (a skip reason, an error) is kept only when it is one of our own messages: every string
     in ctx/*.py is the allowlist, read from the source when the report runs, plus a short list of standard library
     messages. anything else becomes its length: <42 chars>.
  3. every string that is kept still passes clean(): home becomes ~, the user and host names become <user> and
     <host>, folders under Documents, Desktop, Downloads become …, and emails, links, phone numbers, long digit
     runs and whatever scrub.py catches are removed.
"""
import ast, glob, json, os, platform, plistlib, re, shutil, socket, subprocess, sys, tempfile, threading, time
from . import paths
from . import guard
from .scrub import scrub

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_LINES = 300
ABOUT = ("this is a tester report from context (python3 -m ctx report). it holds counts, states, versions and timings from "
         "this mac: which sources were read, how many rows each gave, which months they span, how long each step took, and "
         "what failed. it does not hold any message, title, thread or contact name, file name from your folders, mail "
         "address, phone number, link, account name, or the name of this mac or its user. home paths are written as ~. "
         "error text that is not one of the tool's own messages is replaced by its length. read it before you send it, "
         "and delete any line you would rather not share.")

# ---------------------------------------------------------------- the redactor

USER, HOST, GONE = "<user>", "<host>", "…"
EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
URL = re.compile(r"(?i)\b(?:[a-z][a-z0-9+.\-]{1,12}://|www\.)[^\s\"'<>)]+")
DOMAIN = re.compile(r"(?i)(?<![\w.\-/~])(?:[a-z0-9\-]+\.)+(?:com|org|net|io|so|ai|dev|co|in|xyz|me|fun|gg|uk|de|fr|us|edu|gov|info|fi|to|tv|ly)\b(?:/[^\s\"'<>)]*)?")
DATE = r"\d{4}-\d{2}(?:-\d{2})?(?:[t ]\d{2}:\d{2}(?::\d{2})?)?"
NUMBERS = re.compile(r"(?i)(?<![\w.])(?P<date>%s)(?![\w])|(?P<phone>\+?\(?\d(?:[ .\-]?[()]{0,2}\d){7,16})" % DATE)
DIGITS = re.compile(r"\d{7,}")
PATHISH = re.compile(r"(?<![\w<])(?:~|/Users/[^/\s\"']+|/Volumes/[^/\s\"']+|/private/var|/var/folders|/tmp)/[^\"'\n<>;,)\]]*")
# folders macos keeps personal files in: nothing below them is ever shown
PROTECTED = {"Documents", "Desktop", "Downloads", "Movies", "Music", "Pictures", "Public", "Mobile Documents", "iCloud Drive", "CloudStorage", "Dropbox"}
# path parts that say something about the setup and nothing about the person
SEGMENTS = {"Library", "Application Support", "Applications", "Logs", "Preferences", ".context", "v2", ".claude", ".codex", ".cursor", ".gemini", ".config",
            ".local", "bin", "lib", "share", "opt", "usr", "homebrew", "local", "Cellar", "Frameworks", "Python.framework", "Python3.framework", "Versions",
            "Current", "Developer", "CommandLineTools", "Xcode.app", "Contents", "MacOS", "Resources", "python", "python3", ".pyenv", "versions", "shims",
            ".venv", "venv", "miniconda3", "anaconda3", "miniforge3", "mambaforge", ".asdf", "installs", ".mise", "mise", ".rye", "uv", "Claude",
            "claude_desktop_config.json", "mcp.json", "settings.json", "config.toml", ".claude.json", "mcp-config.json", "mcp_config.json",
            "cline_mcp_settings.json", "opencode.json", "opencode.jsonc", "Code", "User", ".copilot", ".codeium", "windsurf", "devin", "zed", ".cline",
            "data", "settings", ".lmstudio", "opencode", "context.app", "context", "ctx", "System", "Users", USER, "sbin", "Volumes", "private", "var", "tmp", "folders",
            "claude", "codex", "ChatGPT.app", "Codex.app", "codex-cli", "node", "nodejs", ".nvm", ".npm-global", ".bun", ".volta", "Library", "site-packages"}
SEGMENT = re.compile(r"(?:python|pypy)?3?(?:\.\d{1,2}){0,2}|v?\d{1,3}(?:\.\d{1,3}){1,3}")     # python3.11, 3.11.6, v22.1.0
# what the standard library says when a file, a database or a call fails. matched whole, case ignored.
STDLIB = [re.compile(p, re.I) for p in (
    r"\[errno -?\d{1,3}\] (?:no such file or directory|operation not permitted|permission denied|is a directory|not a directory|file exists|"
    r"resource temporarily unavailable|too many open files|no space left on device|read-only file system|broken pipe|connection refused|"
    r"connection reset by peer|operation timed out|interrupted system call|input/output error|resource busy|directory not empty|invalid argument|"
    r"bad file descriptor|nodename nor servname provided, or not known|network is unreachable|host is down|no route to host|exec format error|"
    r"argument list too long|file name too long|cross-device link|device not configured)", r"unable to open database file", r"database is locked", r"database disk image is malformed",
    r"file is not a database", r"no such (?:table|column)", r"attempt to write a readonly database", r"disk i/o error",
    r"authorization denied", r"operation not permitted", r"permission denied", r"no such file or directory", r"is a directory", r"not a directory",
    r"broken pipe", r"connection refused", r"connection reset by peer", r"timed out", r"the read operation timed out", r"list index out of range",
    r"string indices must be integers(?:, not '[a-z]{3,8}')?", r"'[a-z]{3,12}' object (?:is not (?:subscriptable|iterable|callable)|has no attribute '[a-z_]{1,40}')",
    r"expecting (?:value|property name enclosed in double quotes|',' delimiter|':' delimiter)", r"line \d{1,6} column \d{1,6} \(char \d{1,6}\)",
    r"extra data", r"unterminated string starting at", r"division by zero", r"maximum recursion depth exceeded(?: [a-z ]{0,40})?",
    r"invalid literal for int\(\) with base \d{1,2}", r"'utf-?8' codec can't decode byte 0x[0-9a-f]{2} in position \d{1,6}", r"invalid (?:start|continuation) byte",
    r"file is not a zip file", r"bad magic number for (?:central directory|file header)", r"not enough values to unpack \(expected \d{1,2}, got \d{1,2}\)",
    r"too many values to unpack \(expected \d{1,2}\)", r"nodename nor servname provided, or not known", r"command (?:timed out|returned non-zero exit status \d{1,3})",
    r"no module named '[a-z0-9_.]{1,40}'", r"no reply", r"killed", r"terminated", r"exit (?:code|status) -?\d{1,3}")]
SEPARATORS = re.compile(r"(: |; |\. | \(|\)| - |, )")
LIMIT = re.compile(r"(?i)usage limit|rate.?limit|limit reached|quota|too many requests|overloaded")


def _norm(s):
    return " ".join(str(s).split())


def _exceptions():
    names = set()
    for mod in ("builtins", "sqlite3", "json", "subprocess", "zipfile", "plistlib", "socket", "ssl", "urllib.error", "asyncio", "concurrent.futures", "shutil"):
        try:
            m = __import__(mod, fromlist=["x"])
        except Exception:
            continue
        for k, v in vars(m).items():
            if isinstance(v, type) and issubclass(v, BaseException):
                names.add(k)
    return names


class Vocabulary:
    """Our own messages, read from the source: every string constant in ctx/*.py, and every f-string and %-format as
    a pattern with holes. Built once, when the first message that is not obviously ours has to be judged."""

    def __init__(self, folder=None):
        self.fixed, self.patterns, self.classes = set(), [], set()
        for f in sorted(glob.glob(os.path.join(folder or os.path.dirname(os.path.abspath(__file__)), "*.py"))):
            try:
                with open(f, encoding="utf-8") as fh:
                    tree = ast.parse(fh.read())
            except (OSError, SyntaxError, ValueError):
                continue
            for n in ast.walk(tree):
                if isinstance(n, ast.ClassDef):
                    self.classes.add(n.name)
                elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                    self._constant(n.value)
                elif isinstance(n, ast.JoinedStr):
                    self._pattern([v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else None for v in n.values])
        self.sorted = sorted(self.fixed)
        self.by_head = {}                       # long constants by their first three letters, longest first: for finding one inside a longer message
        for k in sorted((k for k in self.fixed if len(k) >= 12 and " " in k), key=len, reverse=True):
            self.by_head.setdefault(k[:3], []).append(k)

    def _constant(self, s):
        if re.search(r"%[-\d.]*[sdrif]", s):
            self._pattern([x if i % 2 == 0 else None for i, x in enumerate(re.split(r"(%[-\d.]*[sdrif])", s))])
            return
        k = _norm(s).lower()
        if 2 <= len(k) <= 400 and "\n" not in s.strip():
            self.fixed.add(k)

    def _pattern(self, parts):
        """parts: text, or None for a hole. Kept only when enough of it is our own words to mean something."""
        text = [_norm(p).lower() if p.strip() else (" " if p else "") for p in parts if p is not None]
        holes = sum(1 for p in parts if p is None)
        if not 1 <= holes <= 3 or sum(c.isalpha() for c in "".join(text)) < 8:
            return
        rx, lead = "", ""
        for p in parts:
            if p is None:
                rx += "(.{0,120}?)"
            else:
                rx += r"\s+".join(re.escape(w) for w in re.split(r"\s+", p.lower()))
                lead = max(lead, _norm(p).lower(), key=len)
        try:
            self.patterns.append((lead, re.compile(rx, re.S), sum(c.isalpha() for c in "".join(text))))
        except re.error:
            pass

    def whole(self, k):
        """Is this text (lowercased, spaces collapsed) one of our constants, or the start of one that was cut short?"""
        if k in self.fixed or k + ":" in self.fixed or k.rstrip(".:") in self.fixed:
            return True
        if len(k) >= 20:
            import bisect
            i = bisect.bisect_left(self.sorted, k)
            return i < len(self.sorted) and self.sorted[i].startswith(k)
        return False

    def inside(self, k, i):
        """The longest of our constants (two words or more) that starts at k[i] and ends at a word's end. "" when none does."""
        if i and k[i - 1].isalnum():
            return ""
        for c in self.by_head.get(k[i:i + 3], ()):
            if k.startswith(c, i) and not k[i + len(c):i + len(c) + 1].isalnum():
                return c
        return ""


class Redactor:
    def __init__(self, extra=(), home=None, users=None, hosts=None):
        self.home = (home or os.path.expanduser("~")).rstrip("/") or "/"
        self.users = set(users) if users is not None else self._users()
        self.hosts = set(hosts) if hosts is not None else self._hosts()
        self.extra = {w for w in extra if w and len(w) >= 2}
        self._vocab, self._exc, self.removed = None, _exceptions(), 0
        self._names = [(self._word(self.users, loose=True), USER), (self._word(self.hosts, loose=True), HOST), (self._word(self.extra), "<removed>")]

    def _users(self):
        names = {os.path.basename(self.home), os.environ.get("USER", ""), os.environ.get("LOGNAME", "")}
        try:
            import pwd
            me = pwd.getpwuid(os.getuid())
            names.add(me.pw_name)
            full = me.pw_gecos.split(",")[0].strip()
            names.update([full] + [w for w in re.split(r"[\s.]+", full) if len(w) >= 3])
        except Exception:
            pass
        return {n for n in names if n and len(n) >= 2 and n.lower() not in ("root", "users", "user", "shared")}

    def _hosts(self):
        names = set()
        for get in (socket.gethostname, platform.node):
            try:
                names.add(get())
            except Exception:
                pass
        for key in ("ComputerName", "LocalHostName", "HostName"):
            names.add(_out(["scutil", "--get", key], timeout=5))
        out = set()
        for n in names:
            n = (n or "").strip()
            if not n or "not set" in n.lower():
                continue
            out.update([n, n.split(".")[0], re.sub(r"(?i)\.(local|lan|home|localdomain)$", "", n)])
        return {n for n in out if len(n) >= 2 and n.lower() not in ("localhost", "local", "mac")}

    @staticmethod
    def _word(names, loose=False):
        """One pattern for a set of names. loose: a name is also caught with -, _ or . where it has a space."""
        alts = []
        for n in sorted(names, key=len, reverse=True):
            alts.append(re.sub(r"(?:\\?[\s\-_.])+", lambda m: "[\\s\\-_.’']*", re.escape(n)) if loose else re.escape(n))
        return re.compile(r"(?i)(?<![a-z0-9])(?:%s)(?![a-z0-9])" % "|".join(alts)) if alts else None

    # ---- paths

    def path(self, p):
        """A path with only the parts that describe a setup: ~/Library/Application Support/Claude/…, never a folder
        or file the person named."""
        p = str(p or "")
        if not p:
            return ""
        if p == self.home or p.startswith(self.home + "/"):
            p = "~" + p[len(self.home):]
        p = re.sub(r"^/Users/[^/]+", "/Users/" + USER, p)
        segs, out = p.split("/"), []
        for i, s in enumerate(segs):
            if i == 0 and s in ("", "~"):
                out.append(s)
            elif s in PROTECTED:
                out.append(s)
                if i < len(segs) - 1:
                    out.append(GONE)
                break
            elif s in SEGMENTS or SEGMENT.fullmatch(s):
                out.append(s)
            elif not out or out[-1] != GONE:
                out.append(GONE)
        return "/".join(out)

    def _in_text(self, m):
        """A path found inside a sentence. It ends at the first space, unless more path follows the space or part of it
        had to be hidden: then everything up to the next quote or comma goes with it."""
        full = m.group(0)
        head, sep, rest = full.partition(" ")
        if rest.startswith("Support/") or "/" in rest:
            return self.path(full.rstrip()) + full[len(full.rstrip()):]
        got = self.path(head)
        return got + ("" if got.endswith(GONE) else sep + rest)

    # ---- every string that leaves

    def clean(self, s):
        """The last pass over anything printed. It only removes; what it finds should already be gone."""
        s = str(s)
        before = s
        s = PATHISH.sub(self._in_text, s.replace(self.home, "~") if len(self.home) > 1 else s)
        s = re.sub(r"/Users/(?!<user>)[^/\s\"']+", "/Users/" + USER, s)
        s = EMAIL.sub("<mail>", s)
        s = URL.sub("<link>", s)
        s = DOMAIN.sub("<link>", s)
        for rx, put in self._names:
            if rx:
                s = rx.sub(put, s)
        s = scrub(s).replace("[redacted]", "<secret>")
        s = NUMBERS.sub(lambda m: m.group(0) if m.group("date") else "<number>", s)
        s = DIGITS.sub("<number>", s)
        s = re.sub(r"(?i)https?", "web", s.replace("@", ""))
        if s != before.replace(self.home, "~"):
            self.removed += 1
        return s

    def seal(self, x):
        """clean() over every string in a structure, keys too."""
        if isinstance(x, str):
            return self.clean(x)
        if isinstance(x, dict):
            return {self.clean(str(k)): self.seal(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [self.seal(v) for v in x]
        return x if isinstance(x, (int, float, bool)) or x is None else self.clean(str(x))

    # ---- text the engine wrote

    def _piece(self, part, deep=True):
        """One piece of a message: itself when it is ours, a number, an exception name, a standard library message or
        a path (redacted); None when it is none of those."""
        v = self._vocab
        raw = part.strip()
        k = _norm(raw).lower()
        if not k:
            return part
        if re.fullmatch(r"-?\d{1,6}(?:[.,:]\d{1,6}){0,2}\s?(?:s|secs?|seconds|ms|gb|mb|kb|%|rows?|x)?", k):
            return part
        if raw.strip("'\"") in self._exc or raw in v.classes:
            return part
        if any(rx.fullmatch(k) for rx in STDLIB) or v.whole(k):
            return part
        bare = raw.strip("'\"`")
        quoted = len(raw) > 2 and raw[0] in "'\"`" and raw[-1] == raw[0]
        if bare[:1] in ("~", "/") and "/" in bare and "//" not in bare and (quoted or not re.search(r"\s", bare)):
            return part.replace(bare, self.path(bare))
        if deep:
            got = self._format(k, strict=True)
            if got:
                return got[0]
        return None

    def _format(self, k, strict):
        """k read as one of our format strings: our words, with each filling kept when it is safe. strict: every filling
        must be safe, or it is no match. Otherwise an unsafe filling becomes its length, and the reading that hides
        least is returned as (text, 1, characters hidden); None when no format of ours fits."""
        best = None
        for lead, rx, letters in self._vocab.patterns:
            if (lead and lead not in k) or (not strict and letters < 10):
                continue
            m = rx.fullmatch(k)
            if not m:
                continue
            out, at, hidden = "", 0, 0
            for g in range(1, (m.lastindex or 0) + 1):
                got = self._piece(m.group(g), deep=False) if m.group(g).strip() else m.group(g)
                if got is None and len(m.group(g)) > 3:
                    got = self.phrase(m.group(g), _nested=True)
                if got is None:
                    if strict:
                        break
                    got, hidden = "<%d chars>" % len(m.group(g)), hidden + len(m.group(g))
                out, at = out + k[at:m.start(g)] + got, m.end(g)
            else:
                if strict:
                    return out + k[at:], 1, 0
                if best is None or hidden < best[2]:
                    best = (out + k[at:], 1, hidden)
        return best

    def phrase(self, msg, _nested=False):
        """A reason or an error as the engine wrote it, kept only where it is one of our own messages. The rest is
        replaced by its length."""
        if self._vocab is None:
            self._vocab = Vocabulary()
        msg = _norm(msg)[:400]
        if not msg:
            return ""
        got = self._piece(msg)
        if got is not None:
            return got if _nested else self.clean(got)
        k = msg.lower()
        if len(k) != len(msg):
            msg = k
        runs, i, loose = [], 0, ""             # (ours, text): our own constants found inside the message, and what lies between
        while i < len(k):
            c = self._vocab.inside(k, i)
            if c:
                if loose:
                    runs.append((False, loose))
                runs.append((True, msg[i:i + len(c)]))
                i, loose = i + len(c), ""
            else:
                loose, i = loose + msg[i], i + 1
        if loose:
            runs.append((False, loose))
        # read it three ways (cut at punctuation; cut around our constants; as one of our format strings) and keep the way that hides least
        ways = [self._pieces([(False, msg)]), self._pieces(runs)] + ([] if _nested else [w for w in [self._format(k, strict=False)] if w])
        out, kept, hidden = min(ways, key=lambda x: x[2])
        if not kept or len(re.findall(r"<\d+ chars>", out)) > 3:       # mostly not ours: its length says as much as its shape would
            return None if _nested else "<%d chars>" % len(msg)
        return out if _nested else self.clean(out)

    def _pieces(self, runs):
        """(text, pieces kept, characters hidden) for a message cut into runs: ours as they are, the rest cut at
        punctuation and each piece judged on its own."""
        out, kept, hidden = [], 0, 0
        for ours, text in runs:
            if ours:
                out.append(text)
                kept += 1
                continue
            for j, p in enumerate(SEPARATORS.split(text)):
                if j % 2 or not p.strip(" :;,.()-"):
                    out.append(p)
                    continue
                lead, core, trail = re.match(r"(\s*)(.*?)(\s*)$", p, re.S).groups()
                got = self._piece(core)
                kept += got is not None
                hidden += 0 if got is not None else len(core)
                out.append(lead + (got if got is not None else "<%d chars>" % len(core)) + trail)
        return "".join(out), kept, hidden

    def word(self, s, allowed, other="other"):
        """A value that must come from a fixed list (a source name, an app id)."""
        return s if s in allowed else other


# ---------------------------------------------------------------- small helpers

def _out(args, timeout=10, env=None):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env)
        return (r.stdout or r.stderr or "").strip()
    except Exception:
        return ""


def _json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {} if default is None else default


def _day(ts):
    try:
        return time.strftime("%Y-%m-%d", time.localtime(float(ts))) if ts else ""
    except (ValueError, OverflowError, OSError, TypeError):
        return ""


def _num(x, digits=1):
    return round(x, digits) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _median(xs):
    xs = sorted(xs)
    return round(xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2, 1) if xs else None


def _counts(d, keys=None, depth=1):
    """The numbers in a status object, and nothing else: keys that are plain identifiers (or in `keys`), values that
    are numbers or true/false. One level of nesting."""
    out = {}
    for k, v in (d.items() if isinstance(d, dict) else ()):
        k = str(k)
        if not (k in keys if keys is not None else re.fullmatch(r"[a-z][a-z0-9_.]{0,31}", k)):
            continue
        if isinstance(v, (int, float, bool)):
            out[k] = round(v, 2) if isinstance(v, float) else v
        elif isinstance(v, dict) and depth:
            sub = _counts(v, keys, depth - 1)
            if sub:
                out[k] = sub
    return out


MODEL_WORDS = {"claude", "gpt", "codex", "haiku", "sonnet", "opus", "fable", "gemini", "mini", "nano", "max", "pro", "high", "low", "medium", "latest", "preview",
               "turbo", "default", "fast", "thinking", "flash", "plus", "ultra", "lite", "o", "chatgpt"}


def _model_id(s):
    """A model's id or name, a part at a time: a part is kept when it is a known model word, a version or a date."""
    out = []
    for part in re.split(r"[\s\-_:/]+", str(s or "").lower())[:8]:
        if part in MODEL_WORDS or re.fullmatch(r"[a-z]?\d{1,2}(?:\.\d{1,2})?[a-z]?", part):
            out.append(part)
        elif re.fullmatch(r"20\d{6}", part):
            out.append("%s-%s-%s" % (part[:4], part[4:6], part[6:]))
        elif part:
            out.append(GONE)
    return "-".join(out)


def _timed(fn, timeout, default):
    """fn() on a thread, given up on after `timeout` seconds: a status that reads the whole archive must not hang the report."""
    box = {}

    def work():
        try:
            box["v"] = fn()
        except Exception as e:
            box["v"] = {"error": type(e).__name__}
    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout)
    return box.get("v", default)


def _section(fn, *a):
    try:
        return fn(*a)
    except Exception as e:          # one broken section never costs the report; its type is itself a finding
        tb = e.__traceback__
        while tb and tb.tb_next:
            tb = tb.tb_next
        return {"error": type(e).__name__, "at": "%s:%s" % (os.path.basename(tb.tb_frame.f_code.co_filename), tb.tb_lineno) if tb else ""}


# ---------------------------------------------------------------- what is read

def tool():
    version = ""
    try:
        with open(os.path.join(REPO, "ctx", "__main__.py"), encoding="utf-8") as f:
            m = re.search(r'(?m)^VERSION\s*=\s*"([\w.\-]{1,20})"', f.read())
            version = m.group(1) if m else ""
    except OSError:
        pass
    tools = _out(["xcode-select", "-p"])        # without the command line tools /usr/bin/git is a stub that opens an install window
    git = os.path.isdir(os.path.join(REPO, ".git")) and bool(shutil.which("git", path="/opt/homebrew/bin:/usr/local/bin") or (tools and os.path.isdir(tools)))
    rev = _out(["git", "-C", REPO, "rev-parse", "HEAD"])[:6] if git else ""       # six: never a run of digits longer than that
    changed = len([l for l in _out(["git", "-C", REPO, "status", "--porcelain", "--untracked-files=no"]).splitlines() if l.strip()]) if git else None
    return {"version": version, "commit": rev if re.fullmatch(r"[0-9a-f]{6}", rev) else "", "files_changed_locally": changed,
            "when": time.strftime("%Y-%m-%d %H:%M")}


def _pythons(have_tools):
    seen, out = set(), []
    dirs = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"] + os.environ.get("PATH", "").split(os.pathsep)
    for d in dict.fromkeys(dirs):
        for p in sorted(glob.glob(os.path.join(glob.escape(d), "python3*")) if d else []):
            if not re.fullmatch(r"python3(\.\d{1,2})?", os.path.basename(p)) or not os.access(p, os.X_OK):
                continue
            if p.startswith("/usr/bin/") and not have_tools:      # a stub that opens an install window
                out.append({"path": p, "version": "stub (no command line tools)"})
                continue
            real = os.path.realpath(p)
            if real in seen:
                continue
            seen.add(real)
            v = re.search(r"\d{1,2}\.\d{1,2}(?:\.\d{1,3})?", _out([p, "-V"], timeout=5))
            out.append({"path": p, "version": v.group(0) if v else "did not answer"})
    return out[:12]


def machine(R):
    from . import doctor
    s = doctor.system()
    mem = _out(["sysctl", "-n", "hw.memsize"])
    chip = re.sub(r"[^A-Za-z0-9 ()\-]", "", _out(["sysctl", "-n", "machdep.cpu.brand_string"]))[:48]
    model = re.sub(r"[^A-Za-z0-9,]", "", _out(["sysctl", "-n", "hw.model"]))[:24]
    swift = re.search(r"swift version [\d.]{1,12}", s.get("swiftc") or "", re.I)
    try:
        disk = shutil.disk_usage(R.home)
        free, total = disk.free // 2 ** 30, disk.total // 2 ** 30
    except OSError:
        free = total = None
    size = 0
    for n in ("messages.jsonl", "sessions.jsonl", "prompts.jsonl", "docs.jsonl", "mail_index.jsonl"):
        try:
            size += os.path.getsize(os.path.join(paths.HOME, n))
        except OSError:
            pass
    return {"macos": re.sub(r"[^\d.]", "", s.get("macos") or "")[:12], "macos_ok": s.get("macos_ok"), "arch": R.word(s.get("arch"), ("arm64", "x86_64")),
            "chip": chip, "model": model, "ram_gb": int(mem) // 2 ** 30 if mem.isdigit() else None, "disk_free_gb": free, "disk_total_gb": total,
            "python": s.get("python"), "python_path": R.path(s.get("python_path")), "python_ok": s.get("python_ok"),
            "python_cannot_parse": len(s.get("python_cannot_parse") or []), "pythons": [{"path": R.path(p["path"]), "version": p["version"]} for p in _pythons(bool(s.get("command_line_tools")))],
            "python_for_the_app": R.path(s.get("app_python")), "python_for_the_app_version": re.sub(r"[^\d.]", "", s.get("app_python_version") or "")[:10],
            "command_line_tools": bool(s.get("command_line_tools")), "swiftc": swift.group(0).lower() if swift else "", "git": bool(s.get("git")),
            "repo": R.path(s.get("repo")), "repo_on_external_volume": bool(s.get("repo_on_external_volume")), "archive": R.path(paths.HOME),
            "archive_mb": round(size / 1e6, 1), "shell": R.word(s.get("shell"), ("zsh", "bash", "fish", "sh", "")), "terminal": re.sub(r"[^A-Za-z_.]", "", s.get("terminal") or "")[:24],
            "full_disk_access": {True: "yes", False: "no"}.get(s.get("full_disk_access"), "unknown")}


# apps the collector reads from (collect.TABLE), and where each lives. names only.
APPS = [("whatsapp", ["WhatsApp"]), ("telegram", ["Telegram", "Telegram Desktop"]), ("slack", ["Slack"]), ("cursor", ["Cursor"]), ("obsidian", ["Obsidian"]),
        ("notion", ["Notion"]), ("chatgpt", ["ChatGPT"]), ("claude", ["Claude"]), ("codex", ["Codex"]), ("grok", ["Grok", "Grok Bot"])]
FOLDERS = [("claude code sessions", "~/.claude/projects"), ("codex sessions", "~/.codex/sessions")]     # dot folders: reading them asks macos nothing


def _verdict(s):
    """doctor's line for one thing, cut to its first word or two: the rest is advice, not a finding."""
    s = str(s or "")
    return next((v for v in ("ready", "needs", "not supported", "not on this mac") if s.startswith(v)), "other").replace("needs", "needs something")


def apps(R):
    from . import doctor
    br = doctor.browsers()
    known = {n for n, _, _, _ in doctor.BROWSERS} | {n for n, _, _ in doctor.OTHER} | {"safari"}
    out = {"browsers": [], "default_browser": "", "apps": [n for n, bundle in APPS if doctor._app(bundle)],
           "folders": [n for n, p in FOLDERS if os.path.isdir(os.path.expanduser(p))]}
    for b in br:
        name = R.word(b.get("name"), known)
        out["browsers"].append({"name": name, "profiles": b.get("profiles") if isinstance(b.get("profiles"), int) else None, "history": _verdict(b.get("history")),
                                "page_scripting": b.get("page_scripting"), "extension_helper": b.get("extension_helper"),
                                "signed_in_reads": _verdict(b.get("signed_in_reads"))})
        if b.get("default"):
            out["default_browser"] = name
    return out


def _span(path):
    """Earliest and latest year-month in one jsonl file, read as bytes: the dates are found by their key, no row is parsed."""
    rx, lo, hi, tail = re.compile(rb'"[a-z_]*ts": "(\d{4}-\d{2})'), None, None, b""
    top = time.strftime("%Y-%m", time.localtime(time.time() + 40 * 86400)).encode()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1 << 22)
                if not chunk:
                    break
                for m in rx.findall(tail + chunk):
                    if b"1990-01" <= m <= top and m[5:] <= b"12":
                        lo = m if lo is None or m < lo else lo
                        hi = m if hi is None or m > hi else hi
                tail = chunk[-64:]
    except OSError:
        pass
    return (lo.decode(), hi.decode()) if lo else ("", "")


def sources(R):
    from . import collect, schedule
    st = _json(os.path.join(paths.HOME, "status.json"))
    daily = (_json(os.path.join(paths.HOME, "schedule.json")).get("daily_results") or {})
    rows, custom = [], 0
    for name, _, _ in collect.TABLE:
        shown = name
        if name.startswith("custom_"):          # an app the owner added: its name is theirs, so it is numbered
            custom += 1
            shown = "custom_%d" % custom
        s = st.get(name)
        row = {"source": shown, "tier": "fast" if name in schedule.FAST else "daily" if name in schedule.DAILY else "export" if not name.startswith("custom_") else "custom"}
        if not isinstance(s, dict):
            row["state"] = "not tried"
        else:
            why = str(s.get("skipped") or s.get("why") or "")
            row["state"] = "failed" if why.startswith("error:") else "stale" if s.get("stale") else "skipped" if "skipped" in s else "ok"
            row["rows"], row["new"], row["secs"] = s.get("rows") if isinstance(s.get("rows"), int) else 0, s.get("new") if isinstance(s.get("new"), int) else None, _num(s.get("secs"))
            if why:
                row["reason"] = R.phrase(why)
            lo, hi = _span(os.path.join(collect.PARTS, name + ".jsonl")) if row["rows"] else ("", "")
            row["earliest"], row["latest"] = lo, hi
        d = daily.get(name)
        if isinstance(d, dict):                 # how the last signed-in read went
            row["last_daily_read"] = R.word(d.get("state"), ("ok", "needs_you", "skipped", "failed"))
            if d.get("detail") and "reason" not in row:
                row["reason"] = R.phrase(str(d["detail"]))
        rows.append(row)
    sched = _json(os.path.join(paths.HOME, "schedule.json"))
    return {"rows": rows, "collect_secs": round(sum(r.get("secs") or 0 for r in rows), 1), "total_rows": sum(r.get("rows") or 0 for r in rows),
            "by_state": _tally(r["state"] for r in rows), "last_fast_read": _day(sched.get("fast")), "last_daily_read": _day(sched.get("daily")),
            "exports_requested": len(sched.get("exports") or {}), "imports": len(glob.glob(os.path.join(paths.HOME, "imports", "*")))}


def _tally(xs):
    out = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


def permissions(R, mach, src, app_):
    blocked = [r["source"] for r in src.get("rows", []) if "full disk access" in (r.get("reason") or "").lower() or "blocked by macos" in (r.get("reason") or "").lower()]
    auto = {r["source"]: r["last_daily_read"] for r in src.get("rows", []) if r.get("last_daily_read")}
    try:
        from . import bridge
        linked = bool(bridge.connected())
    except Exception:
        linked = None
    return {"full_disk_access": mach.get("full_disk_access", "unknown"), "sources_blocked_by_macos": blocked, "signed_in_reads_last_seen": auto,
            "browser_extension_connected": linked, "page_scripting_on": [b["name"] for b in app_.get("browsers", []) if b.get("page_scripting")]}


def _error_class(s):
    s = str(s).lower()
    if LIMIT.search(s):
        return "limit"
    if re.search(r"not (?:logged|signed) in|no model is signed in|auth login|unauthori[sz]ed|login required|invalid api key|please (?:log|sign) in", s):
        return "not signed in"
    if re.search(r"timed out|timeout|took too long", s):
        return "timeout"
    if re.search(r"no reply|nothing usable|empty reply", s):
        return "no reply"
    if re.search(r"issue with the selected model|cannot run|model not found|does not exist", s):
        return "model unavailable"
    return "other"


TAG_HEADS = ("answer", "understand", "wiki", "index", "lens", "relate", "coach", "title", "test", "today", "connect", "eval", "selftest", "loops", "bench", "events")
TAG_PARTS = {"plan", "rerank", "check", "lean", "write", "dig", "agent", "quick", "deep", "read", "merge", "events", "core", "people", "projects", "timeline", "voice",
             "page", "digest", "survey", "condense", "catalog", "gloss", "probes", "intros", "tasks", "money", "saved", "judge", "rank"}


def _tag(t):
    """The tag a model call was logged under, a part at a time: only parts that are our own job names."""
    parts = str(t or "").split(":")
    head = next((h for h in TAG_HEADS if parts[0] == h or parts[0].startswith(h + "_")), "")
    return ":".join([head] + [p for p in parts[1:3] if p in TAG_PARTS]) if head else "other"


def ledger():
    """Model calls, read from the ledger: counts by tag today, error classes, and how long each step of an answer took."""
    midnight = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    today, classes, classes_today, secs, errors = {}, {}, {}, {}, []
    calls = failed = 0
    try:
        with open(paths.LEDGER, encoding="utf-8", errors="replace") as f:
            for l in f:
                try:
                    d = json.loads(l)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                calls += 1
                tag, at = _tag(d.get("tag")), d.get("at") if isinstance(d.get("at"), (int, float)) else 0
                if at >= midnight:
                    today[tag] = today.get(tag, 0) + 1
                if d.get("error"):
                    failed += 1
                    c = _error_class(d["error"])
                    classes[c] = classes.get(c, 0) + 1
                    if at >= midnight:
                        classes_today[c] = classes_today.get(c, 0) + 1
                    errors.append({"when": at, "where": "ledger", "type": c, "at": tag, "message": str(d["error"])})
                    del errors[:-40]
                elif isinstance(d.get("secs"), (int, float)) and tag.startswith("answer"):
                    secs.setdefault(tag, []).append(d["secs"])
    except OSError:
        pass
    steps = {"plan": "answer:plan", "search (rerank)": "answer:rerank", "check": "answer:check", "write, fixed path": "answer", "write, lean path": "answer:lean",
             "agent, quick": "answer:agent:quick", "agent, deep": "answer:agent:deep", "dig": "answer:dig"}
    timing = {k: {"median_secs": _median(secs[t][-200:]), "calls": len(secs[t])} for k, t in steps.items() if secs.get(t)}
    return {"calls": calls, "failed": failed, "today_by_tag": dict(sorted(today.items())), "error_classes": classes, "error_classes_today": classes_today,
            "answer_steps": timing, "_errors": errors}


def model(R):
    from . import doctor, models
    m = doctor.model()
    out = {"using": R.word(m.get("using"), ("claude", "codex", "api", "none")), "api_key_set": bool(m.get("api_key")),
           "clis": {n: ("signed in" if m[n].get("signed_in") else "installed, not signed in" if m[n].get("installed") else "not installed") for n in ("claude", "codex")}}
    st = _json(os.path.join(paths.HOME, "settings.json"))
    out["preset"] = R.word(st.get("preset", "balanced"), models.PRESETS, "balanced")
    out["own_choices"] = len(st.get("models") or {}) if isinstance(st.get("models"), dict) else 0
    try:
        who, notes = models.roles()
        out["roles"] = {r: {"model": _model_id(v.get("name") or v.get("id")), "plan": R.word(v.get("plan"), ("claude", "codex", "api")),
                            "source": v.get("source") if v.get("source") in ["preset " + p for p in models.PRESETS] + ["your choice", "plan limit"] else "other"}
                        for r, v in who.items() if r in models.ROLES}
        out["notes"] = len(notes)
    except Exception as e:
        out["roles"] = {"error": type(e).__name__}
    d = _json(os.path.join(paths.HOME, "models.json"))
    out["measured"] = []
    for v in (d.get("probed") or {}).values() if isinstance(d.get("probed"), dict) else ():
        if not isinstance(v, dict):
            continue
        row = {"model": _model_id(v.get("id") or v.get("ask")), "plan": R.word(v.get("plan"), ("claude", "codex", "api")), "ok": bool(v.get("ok")), "when": _day(v.get("at"))}
        if v.get("ok"):
            row["first_secs"], row["total_secs"] = _num(v.get("first"), 2), _num(v.get("total"), 2)
        else:
            row["error"] = _error_class(v.get("error", "")) if _error_class(v.get("error", "")) != "other" else R.phrase(str(v.get("error", "")))
        out["measured"].append(row)
    out["measured_on"] = _day(d.get("refreshed"))
    out["plans_at_limit"] = [R.word(p, ("claude", "codex", "api")) for p, v in (d.get("limited") or {}).items() if isinstance(v, dict) and v.get("until", 0) > time.time()]
    return out


def indexes(R):
    known = _known() | {"browser_history", "prompts", "sessions", "messages", "docs", "mail"}
    out = {}
    try:
        from . import semantic
        s = semantic.status()
        emb = str(s.get("embedder") or "")
        out["meaning"] = dict(_counts({k: s.get(k) for k in ("units", "vectors", "pending", "terms", "secs", "dim", "mb", "stale", "helper")}),
                              built=_day(s["built"]) if isinstance(s.get("built"), (int, float)) else str(s.get("built") or "")[:10] if re.match(r"\d{4}-\d{2}-\d{2}", str(s.get("built") or "")) else "",
                              embedder=emb.split(":")[0] if emb.split(":")[0] in ("apple", "ollama", "file") else "other" if emb else "",
                              per_source=dict(_counts(s.get("per_source") or {}, known, 0),
                                              **{"other": sum(v for k, v in (s.get("per_source") or {}).items() if k not in known and isinstance(v, int))}))
    except Exception as e:
        out["meaning"] = {"error": type(e).__name__}
    try:
        from . import wordindex
        w = wordindex.status()
        out["words"] = {"on": bool(w.get("on")), "whole": bool(w.get("whole")), "mb": round((w.get("bytes") or 0) / 1e6, 1),
                        "files": {k: _counts(v) for k, v in (w.get("files") or {}).items() if k in ("messages.jsonl", "sessions.jsonl", "prompts.jsonl", "docs.jsonl", "mail_index.jsonl")}}
    except Exception as e:
        out["words"] = {"error": type(e).__name__}

    def read_through():
        from . import understand
        s = understand.status()
        return _counts({k: s.get(k) for k in ("units", "read", "left", "chars", "calls_left_about", "core")})
    out["read_through"] = _timed(read_through, 90, {"error": "took longer than 90 seconds"})
    try:
        from . import events
        e = events.status()
        out["events"] = {"cards_read": e.get("cards_read") if isinstance(e.get("cards_read"), int) else 0, "events": sum(v for v in (e.get("events") or {}).values() if isinstance(v, int)),
                         "kinds": len(e.get("events") or {}), "with_messages": sum(v for v in (e.get("with_messages") or {}).values() if isinstance(v, int))}
    except Exception as e:
        out["events"] = {"error": type(e).__name__}
    try:
        from . import wiki
        w = wiki.status()
        out["wiki"] = {"built": bool(w.get("built")), "pages": sum(v for v in (w.get("pages") or {}).values() if isinstance(v, int)), "kinds": len(w.get("pages") or {}),
                       "words": w.get("words") if isinstance(w.get("words"), int) else 0, "dropped_paragraphs": w.get("dropped_paragraphs") if isinstance(w.get("dropped_paragraphs"), int) else 0,
                       "spent": _counts({k: (w.get("spent") or {}).get(k) for k in ("calls", "errors", "secs")})}
    except Exception as e:
        out["wiki"] = {"error": type(e).__name__}
    return out


def mcp_status(R):
    from . import mcp
    ids = set(mcp.ORDER) | {r["id"] for r in mcp.REMOTE}
    states = ("connected", "registered", "changed", "not registered", "app not found", "needs remote", "remote on", "remote off")
    out = []
    for r in _timed(mcp.status, 60, []) or []:
        if not isinstance(r, dict):
            continue
        out.append({"id": R.word(r.get("id"), ids), "installed": r.get("installed"), "registered": bool(r.get("registered")), "state": R.word(r.get("state"), states),
                    "config": R.path(r.get("config")), "note": "" if r.get("state") in ("remote on", "remote off") else R.phrase(r.get("detail") or "")})
    return out


LOGS = ("collect.log", "telegram.log", "maildbg.log", "bad_replies.log", "remote.log", "remote.tunnel.log", "app.log", "tick.log", "watch.log", "serve.log", "engine.log")
FIELDS = ("src", "rows", "phase", "at", "new", "state", "secs", "exit", "error", "tag", "chars", "tick", "event", "of", "read", "stale", "skipped", "why", "detail", "level", "msg")
STAMP = re.compile(r"\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?|\d{2}:\d{2}(?::\d{2})?)(?:[.,]\d{1,6})?Z?\]?[ \t]*")


def _tail(path, most=256 * 1024):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - most))
            lines = f.read().decode("utf-8", "replace").splitlines()
        return lines[1:] if size > most else lines
    except OSError:
        return []


def logline(R, line, known=()):
    """One line of a log, redacted: its time, the fields we know by name, and any text only where it is our own."""
    line = line.rstrip()
    m = STAMP.match(line)
    head, rest = (m.group(1) + " ", line[m.end():]) if m else ("", line)
    body = rest[1:] if rest.startswith("@") else rest
    d = None
    if body.startswith("{"):
        try:
            d = json.loads(body)
        except ValueError:
            try:
                d = ast.literal_eval(body)
            except Exception:
                d = None
    else:
        m2 = re.fullmatch(r"([a-z_]{2,30})\s+(\{.*\})", body)
        if m2:
            try:
                d = dict(ast.literal_eval(m2.group(2)), src=m2.group(1))
            except Exception:
                d = None
    if isinstance(d, dict):
        out, dropped = [], 0
        for k, v in d.items():
            if k not in FIELDS:
                dropped += 1
            elif isinstance(v, bool) or v is None:
                out.append("%s=%s" % (k, str(v).lower()))
            elif isinstance(v, (int, float)):
                out.append("%s=%s" % (k, _fmt(v)))
            elif k == "src":
                out.append("src=" + (v if v in known else "other"))
            elif k == "at":
                out.append("at=" + (v if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}", v) else "?"))
            elif isinstance(v, str):
                out.append("%s=%s" % (k, R.phrase(v) or "''"))
            else:
                out.append("%s=<%s>" % (k, type(v).__name__))
        return R.clean(head + " ".join(out) + (" (+%d fields not shown)" % dropped if dropped else ""))
    return R.clean(head + (R.phrase(rest) if rest.strip() else ""))


def _fold(lines):
    """Runs of lines that hold nothing of ours (only lengths) said once, with how many there were."""
    out, run = [], 0
    for l in lines + [None]:
        if l is not None and re.fullmatch(r"(?:[\d\-: ]{5,19} )?<\d+ chars>", l):
            run += 1
            continue
        if run:
            out.append("(%d line%s that held none of our own messages: not shown)" % (run, "" if run == 1 else "s"))
            run = 0
        if l is not None:
            out.append(l)
    return out


def _log_errors(R, path, name):
    """Errors in one log: tracebacks (exception type, our own file and line, a redacted message) and lines that say error."""
    lines, out, when = _tail(path), [], 0
    try:
        when = os.path.getmtime(path)
    except OSError:
        pass
    frame, in_tb = "", False
    for l in lines:
        if l.startswith("Traceback (most recent call last)"):
            frame, in_tb = "", True
            continue
        m = re.match(r'\s+File "([^"]+)", line (\d+)', l)
        if m and in_tb:
            base = os.path.basename(m.group(1))       # only a file of ours: one that is in this ctx folder
            if os.sep + "ctx" + os.sep in m.group(1) and re.fullmatch(r"[a-z_]{1,24}\.py", base) and os.path.exists(os.path.join(REPO, "ctx", base)):
                frame = "%s:%s" % (base, m.group(2)[:6])
            continue
        m = re.match(r"((?:[A-Za-z_]\w*\.)*[A-Z]\w*(?:Error|Exception|Expired|Exit|Interrupt|Warning))(?:: (.*))?$", l)
        if m and (in_tb or m.group(1).split(".")[-1] in R._exc):
            out.append({"when": when, "where": name, "type": m.group(1).split(".")[-1] if m.group(1).split(".")[-1] in R._exc else "error (own type)",
                        "at": frame, "message": m.group(2) or ""})
            frame, in_tb = "", False
            continue
        if in_tb and l[:1] in (" ", "\t"):
            continue
        in_tb = False
        m = re.search(r"\b(?:error|failed)\b[\"']?\s*[:=]\s*[\"']?(?:([A-Z]\w*(?:Error|Exception|Expired)): )?([^\"'}]{1,300})", l)
        if m:
            out.append({"when": when, "where": name, "type": m.group(1) if m.group(1) in R._exc else "error line", "at": "", "message": m.group(2)})
    return out[-30:]


def _known():
    """The sources that are ours by name. One the owner added carries a name of theirs, so it is not in this list."""
    from . import collect
    return {n for n, _, _ in collect.TABLE if not n.startswith("custom_")}


def app(R):
    known = _known()
    out = {"installed": False}
    for root in ("/Applications", os.path.join(R.home, "Applications")):
        p = os.path.join(root, "context.app")
        if os.path.isdir(p):
            out.update(installed=True, where="applications" if root == "/Applications" else "applications in the home folder")
            try:
                with open(os.path.join(p, "Contents", "Info.plist"), "rb") as f:
                    info = plistlib.load(f)
                out["version"] = "%s (%s)" % tuple(re.sub(r"[^\w.]", "", str(info.get(k, "")))[:10] for k in ("CFBundleShortVersionString", "CFBundleVersion"))
            except Exception:
                out["version"] = ""
            sig = _out(["/usr/bin/codesign", "-dv", "--verbose=2", p], timeout=15)
            out["signature"] = ("ad hoc" if "Signature=adhoc" in sig else "developer id" if "Authority=Developer ID" in sig else
                                "developer (apple development)" if "Authority=Apple Development" in sig else
                                "not signed" if "not signed" in sig else "signed, kind unknown" if "Authority=" in sig else "unknown")
            try:
                out["installed_on"] = _day(os.path.getmtime(p))
            except OSError:
                pass
            break
    out["built_here"] = os.path.isdir(os.path.join(REPO, "app", "build", "context.app"))
    saved = _json(os.path.join(paths.HOME, "app.json"))
    try:
        out["last_active"] = _day(os.path.getmtime(os.path.join(paths.HOME, "app.json")))       # the app saves this file as it is used
    except OSError:
        out["last_active"] = ""
    out["state"] = _counts({k: saved.get(k) for k in ("onboarded", "hadDisk", "hadTitles", "pingsOff", "soundOff", "hidden")}, ("onboarded", "hadDisk", "hadTitles", "pingsOff", "soundOff", "hidden"))
    out["python"] = R.path(saved.get("python")) if isinstance(saved.get("python"), str) else ""
    try:
        with open(os.path.join(paths.HOME, "repo"), encoding="utf-8") as f:
            out["finds_engine"] = os.path.realpath(f.read().strip()) == os.path.realpath(REPO)
    except OSError:
        out["finds_engine"] = None
    out["chats_saved"] = len(glob.glob(os.path.join(paths.HOME, "chats", "*.json")))
    cands = [os.path.join(paths.HOME, "app.log"), os.path.join(R.home, "Library", "Logs", "context.log")] + \
        sorted(glob.glob(os.path.join(glob.escape(os.path.join(R.home, "Library", "Logs", "context")), "*.log")))
    out["log"] = []
    for c in cands:
        if os.path.isfile(c):
            out["log_lines"] = len([l for l in _tail(c)[-50:] if l.strip()])
            out["log"] = _fold([logline(R, l, known) for l in _tail(c)[-50:] if l.strip()])
            break
    return out


def errors(R, led):
    """The last 30 errors the engine left behind: from every log in the archive folder and from the ledger."""
    found, logs = list(led.pop("_errors", [])), []
    for p in sorted(glob.glob(os.path.join(glob.escape(paths.HOME), "*.log")) + glob.glob(os.path.join(glob.escape(paths.HOME), "logs", "*.log"))):
        name = os.path.basename(p) if os.path.basename(p) in LOGS else "other.log"
        got = _log_errors(R, p, name)
        try:
            with open(p, "rb") as f:
                n = sum(1 for _ in f)
            logs.append({"log": name, "lines": n, "kb": round(os.path.getsize(p) / 1024, 1), "changed": _day(os.path.getmtime(p)), "errors": len(got)})
        except OSError:
            continue
        found += got
    found.sort(key=lambda e: e.get("when") or 0)
    out = [{"when": _day(e.get("when")), "where": e["where"], "type": e["type"], "at": e.get("at") or "", "message": R.phrase(e.get("message") or "")} for e in found[-30:]]
    return {"logs": logs, "last": out}


# ---------------------------------------------------------------- --try: run the real steps, time them

def has_archive():
    return any(os.path.exists(os.path.join(paths.HOME, n)) for n in ("status.json", "messages.jsonl", "parts"))


def tries(R, real=False, say=lambda s: None):
    """Doctor, a read of the file sources into a temp folder, the mcp self-test, one tiny model call. Read-only: the
    archive this Mac already has is never written to. Nothing any step prints is kept: only pass, fail and seconds."""
    from . import schedule
    known = _known()
    steps, tmp = [], tempfile.mkdtemp(prefix="ctx-report-")
    env = dict(os.environ, PYTHONPATH=REPO)
    had = has_archive()

    def step(name, fn):
        say(name)
        t, row = time.time(), {"step": name}
        try:
            row.update(fn() or {})
            row.setdefault("ok", True)
        except subprocess.TimeoutExpired:
            row.update(ok=False, note="took too long")
        except Exception as e:
            row.update(ok=False, note=type(e).__name__)
        row["secs"] = round(time.time() - t, 1)
        steps.append(row)
        return row

    def doctor():
        r = subprocess.run(guard.python(["doctor", "--json"]), cwd=REPO, env=env, capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
        d = json.loads(r.stdout)
        verdicts = {k: ("ready" if v.startswith("ready") else "needs something" if v.startswith("needs") else "not on this mac") for k, v in d.get("sources", {}).items() if k in known}
        return {"ok": r.returncode == 0, "sources": _tally(verdicts.values()), "by_source": verdicts}

    def read():
        into = paths.HOME if (real and not had) else tmp
        code = "from ctx import collect, schedule; collect.run(only=set(schedule.FAST))"
        r = subprocess.run(guard.python_code(code), cwd=REPO, env=dict(env, CTX_HOME=into), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                           timeout=1200, stdin=subprocess.DEVNULL)
        st = _json(os.path.join(into, "status.json"))
        by = {}
        for n in schedule.FAST:
            s = st.get(n)
            if isinstance(s, dict):
                why = str(s.get("skipped") or s.get("why") or "")
                by[n] = {"state": "failed" if why.startswith("error:") else "skipped" if "skipped" in s else "stale" if s.get("stale") else "ok",
                         "rows": s.get("rows") if isinstance(s.get("rows"), int) else 0, "secs": _num(s.get("secs")), "reason": R.phrase(why) if why else ""}
        last = [l for l in (r.stderr or "").splitlines() if l.strip()][-1:] if r.returncode else []
        m = re.match(r"((?:\w+\.)*\w+(?:Error|Exception))", last[0]) if last else None
        return {"ok": r.returncode == 0 and not any(v["state"] == "failed" for v in by.values()), "into": "the real archive (there was none)" if into == paths.HOME else "a temp folder, removed after",
                "rows": sum(v["rows"] for v in by.values()), "by_source": by, "note": (m.group(1).split(".")[-1] if m else "exit %d" % r.returncode) if r.returncode else ""}

    def selftest():
        home = paths.HOME if has_archive() else tmp
        ask = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "report", "version": "1"}}},
               {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
               {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "context_about_me", "arguments": {}}}]
        # it comes in as any new app does, under a name of its own: the short profile is all a new app may call, so that is the call made
        r = subprocess.run(guard.python(["mcp"]), cwd=REPO, env=dict(env, CTX_HOME=home, CTX_MCP_CLIENT="self-test"), input="".join(json.dumps(m) + "\n" for m in ask),
                           capture_output=True, text=True, timeout=120)
        got = {}
        for l in r.stdout.splitlines():
            try:
                d = json.loads(l)
                got[d.get("id")] = d
            except ValueError:
                return {"ok": False, "note": "a line on stdout was not json"}
        init, tools, call = (got.get(i, {}).get("result") or {} for i in (1, 2, 3))
        checks = {"initialize": bool(init.get("serverInfo")), "tools_list": bool(tools.get("tools")), "one_call": bool(call.get("content")) and not call.get("isError")}
        return {"ok": all(checks.values()), "checks": checks, "tools": len(tools.get("tools") or []), "reply_chars": len(((call.get("content") or [{}])[0]).get("text") or "")}

    def tiny():
        from . import llm
        if llm.status()["using"] == "none":
            return {"ok": None, "note": "no plan signed in: not run"}
        code = ("import time; from ctx import llm; t = time.time(); r = llm.ask('Answer in one lowercase word.', 'Say ok.', llm.FAST, tag='test'); "
                "print(len(r.strip()), round(time.time() - t, 2))")
        r = subprocess.run(guard.python_code(code), cwd=REPO, env=dict(env, CTX_HOME=tmp), capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
        m = re.fullmatch(r"(\d{1,6}) (\d{1,4}(?:\.\d{1,2})?)", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "")
        if r.returncode or not m:
            return {"ok": False, "note": _error_class(r.stderr)}
        return {"ok": int(m.group(1)) > 0, "reply_chars": int(m.group(1)), "call_secs": float(m.group(2))}
    try:
        step("doctor", doctor)
        step("read the file sources", read)
        step("mcp self-test", selftest)
        step("one tiny model call", tiny)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)      # it held a copy of what was read
    return {"steps": steps, "archive_before": had}


# ---------------------------------------------------------------- the whole report

def build(try_=False, real=False, extra=(), say=lambda s: None):
    """The report as one object, already redacted: every string in it has been through Redactor.clean."""
    R = Redactor(extra)
    t0 = time.time()
    out = {"about": ABOUT}
    say("this mac")
    out["tool"] = _section(tool)
    out["machine"] = mach = _section(machine, R)
    out["apps"] = apps_ = _section(apps, R)
    say("sources")
    out["sources"] = src = _section(sources, R)
    out["permissions"] = _section(permissions, R, mach, src, apps_)
    say("model")
    led = _section(ledger)
    out["model"] = _section(model, R)
    say("indexes")
    out["indexes"] = _section(indexes, R)
    say("other ai apps")
    out["mcp"] = _section(mcp_status, R)
    out["app"] = _section(app, R)
    out["errors"] = _section(errors, R, led)
    led.pop("_errors", None)
    out["calls"] = {k: led.get(k) for k in ("calls", "failed", "today_by_tag", "error_classes", "error_classes_today")} if "error" not in led else led
    out["timings"] = {"collect_secs": src.get("collect_secs"), "answer_steps": led.get("answer_steps", {}),
                      "first_token_secs": _median([m["first_secs"] for m in (out["model"].get("measured") or []) if isinstance(m, dict) and m.get("first_secs") is not None])}
    if try_:
        out["try"] = _section(tries, R, real, say)
    out["report"] = {"secs": round(time.time() - t0, 1), "strings_changed_by_the_last_pass": R.removed}
    return dict(R.seal(out), about=ABOUT)       # the paragraph is ours and fixed; everything else went through clean()


def _fmt(v):
    if v is None or v == "":
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return format(v, ",")
    if isinstance(v, float):
        return format(v, ",.1f") if abs(v) >= 100 else ("%.2f" % v).rstrip("0").rstrip(".")
    return str(v)


def _table(rows, cols, indent="  "):
    """Aligned columns, two spaces apart, numbers to the right. cols: (key, heading)."""
    if not rows:
        return [indent + "(none)"]
    cells = [[_fmt(r.get(k)) for k, _ in cols] for r in rows]
    width = [max([len(h)] + [len(c[i]) for c in cells]) for i, (_, h) in enumerate(cols)]
    right = [bool(rows) and all(isinstance(r.get(k), (int, float)) or r.get(k) in (None, "") for r in rows) for k, _ in cols]
    line = lambda xs: (indent + "  ".join(x.rjust(w) if rt else x.ljust(w) for x, w, rt in zip(xs, width, right))).rstrip()
    return [line([h for _, h in cols])] + [line(c) for c in cells]


def _pairs(d):
    return ", ".join("%s %s" % (k, _fmt(v)) for k, v in d.items()) if isinstance(d, dict) and d else "-"


def render(r):
    """The report as plain lowercase text, a section at a time."""
    import textwrap
    L = ["context tester report", ""] + textwrap.wrap(r["about"], 100) + [""]
    log_at = [0, 0]

    def head(title):
        L.extend(["", title, "-" * len(title)])

    def row(k, v):
        L.append("  %-26s %s" % (k, _fmt(v)))

    def broken(name, sec):
        if isinstance(sec, dict) and set(sec) <= {"error", "at"} and "error" in sec:
            row(name, "this section could not be made: %s at %s" % (sec.get("error"), sec.get("at") or "?"))
            return True
        return False
    t, m = r.get("tool") or {}, r.get("machine") or {}
    head("tool")
    if not broken("tool", t):
        row("version", "%s, commit %s%s" % (t.get("version") or "?", t.get("commit") or "unknown", "" if not t.get("files_changed_locally") else " (+%s files changed here)" % t["files_changed_locally"]))
        row("made", "%s, in %s seconds" % (t.get("when"), _fmt((r.get("report") or {}).get("secs"))))
    head("this mac")
    if not broken("this mac", m):
        row("macos", "%s on %s%s" % (m.get("macos") or "?", m.get("arch"), "" if m.get("macos_ok") else "  (older than the app needs)"))
        row("chip, model", "%s, %s" % (m.get("chip") or "?", m.get("model") or "?"))
        row("memory, disk", "%s gb ram, %s gb free of %s" % (_fmt(m.get("ram_gb")), _fmt(m.get("disk_free_gb")), _fmt(m.get("disk_total_gb"))))
        row("python that ran this", "%s at %s%s" % (m.get("python"), m.get("python_path"), "" if m.get("python_ok") else "  (too old, or cannot parse %s files)" % m.get("python_cannot_parse")))
        row("python for the app", "%s %s" % (m.get("python_for_the_app") or "none found", m.get("python_for_the_app_version") or ""))
        for i, py in enumerate(m.get("pythons") or []):
            row("pythons found" if not i else "", "%s  %s" % (py["version"], py["path"]))
        row("command line tools", "%s%s%s" % ("present" if m.get("command_line_tools") else "missing", ", " + m["swiftc"] if m.get("swiftc") else ", no swiftc", ", git" if m.get("git") else ", no git"))
        row("shell, terminal", "%s, %s" % (m.get("shell") or "?", m.get("terminal") or "?"))
        row("repo", "%s%s" % (m.get("repo"), "  (on an external volume)" if m.get("repo_on_external_volume") else ""))
        row("archive", "%s, %s mb" % (m.get("archive"), _fmt(m.get("archive_mb"))))
    a = r.get("apps") or {}
    head("browsers and apps")
    if not broken("apps", a):
        row("default browser", a.get("default_browser") or "not one we know")
        L.extend(_table(a.get("browsers") or [], [("name", "browser"), ("profiles", "profiles"), ("history", "history"), ("page_scripting", "scripting"),
                                                    ("extension_helper", "extension"), ("signed_in_reads", "signed-in reads")]))
        row("apps installed", ", ".join(a.get("apps") or []) or "none of the ones we read")
        row("folders present", ", ".join(a.get("folders") or []) or "none")
    p = r.get("permissions") or {}
    head("permissions, as the engine saw them")
    if not broken("permissions", p):
        row("full disk access", p.get("full_disk_access"))
        row("blocked by macos", ", ".join(p.get("sources_blocked_by_macos") or []) or "none")
        row("signed-in reads, last", _pairs(p.get("signed_in_reads_last_seen")))
        row("browser extension", "connected" if p.get("browser_extension_connected") else "not connected")
        row("page scripting on", ", ".join(p.get("page_scripting_on") or []) or "none")
    s = r.get("sources") or {}
    head("sources")
    if not broken("sources", s):
        row("totals", "%s rows, %s seconds to read, %s" % (_fmt(s.get("total_rows")), _fmt(s.get("collect_secs")), _pairs(s.get("by_state"))))
        row("last reads", "fast %s, daily %s, %s exports asked for, %s import files" % (s.get("last_fast_read") or "never", s.get("last_daily_read") or "never",
                                                                                      _fmt(s.get("exports_requested")), _fmt(s.get("imports"))))
        rows = s.get("rows") or []
        quiet = [x for x in rows if x.get("state") == "not tried"]
        L.extend(_table([x for x in rows if x.get("state") != "not tried"], [("source", "source"), ("state", "state"), ("rows", "rows"), ("earliest", "from"), ("latest", "to"), ("secs", "secs"),
                                                                             ("last_daily_read", "daily"), ("reason", "reason, as the engine wrote it")]))
        if quiet:
            L.extend(textwrap.wrap("not tried yet: " + ", ".join(x["source"] for x in quiet), 110, initial_indent="  ", subsequent_indent="    "))
    mo, c = r.get("model") or {}, r.get("calls") or {}
    head("model plan")
    if not broken("model", mo):
        row("using", mo.get("using"))
        row("clis", _pairs(mo.get("clis")) + (", an api key is set" if mo.get("api_key_set") else ""))
        row("preset", "%s, %s roles chosen by hand" % (mo.get("preset"), _fmt(mo.get("own_choices"))))
        roles = mo.get("roles") or {}
        if "error" in roles:
            row("roles", "could not be read: %s" % roles["error"])
        else:
            L.extend(_table([dict(v, role=k) for k, v in roles.items()], [("role", "role"), ("model", "model"), ("plan", "plan"), ("source", "from")]))
        if mo.get("measured"):
            L.extend(_table(mo["measured"], [("model", "measured model"), ("plan", "plan"), ("ok", "ok"), ("first_secs", "first words"), ("total_secs", "total"), ("when", "on"), ("error", "error")]))
        else:
            row("measured speeds", "none yet")
        row("plans at their limit", ", ".join(mo.get("plans_at_limit") or []) or "none")
    if not broken("calls", c):
        row("calls, all time", "%s, %s failed" % (_fmt(c.get("calls")), _fmt(c.get("failed"))))
        row("calls today by tag", _pairs(c.get("today_by_tag")))
        row("error classes", _pairs(c.get("error_classes")))
        row("error classes today", _pairs(c.get("error_classes_today")))
    ix = r.get("indexes") or {}
    head("index, read-through, events, wiki")
    if not broken("indexes", ix):
        me = dict(ix.get("meaning") or {})
        per = me.pop("per_source", None)
        row("search by meaning", _pairs(me))
        if per:
            L.extend(textwrap.wrap("units by source: " + _pairs(per), 110, initial_indent="    ", subsequent_indent="      "))
        w = dict(ix.get("words") or {})
        files = w.pop("files", None) or {}
        row("word index", _pairs(w))
        for k, v in files.items():
            row("  " + k, _pairs(v))
        row("read-through", _pairs(ix.get("read_through")))
        row("events", _pairs(ix.get("events")))
        wk = dict(ix.get("wiki") or {})
        spent = wk.pop("spent", None)
        row("wiki", _pairs(wk) + ("; spent: " + _pairs(spent) if spent else ""))
    head("other ai apps (mcp)")
    mc = r.get("mcp")
    if not broken("mcp", mc):
        L.extend(_table(mc or [], [("id", "app"), ("installed", "installed"), ("state", "state"), ("config", "config")]))
        L.extend("  %s: %s" % (x.get("id"), x["note"]) for x in mc or [] if x.get("note"))
    ap = r.get("app") or {}
    head("the mac app")
    if not broken("app", ap):
        row("installed", ("yes, in %s, version %s, signed: %s, on %s" % (ap.get("where"), ap.get("version") or "?", ap.get("signature"), ap.get("installed_on") or "?")) if ap.get("installed")
            else "no" + (" (a build is in the repo)" if ap.get("built_here") else ""))
        row("last active", ap.get("last_active") or "never")
        row("finds the engine", {True: "yes", False: "no: it points at another folder", None: "no record"}[ap.get("finds_engine")])
        row("python it uses", ap.get("python") or "-")
        row("state", _pairs(ap.get("state")) + ", %s chats saved" % _fmt(ap.get("chats_saved")))
        if ap.get("log"):
            row("its log, last lines", ap.get("log_lines"))
            log_at[0] = len(L)
            L.extend("    " + l[:150] for l in ap["log"])
            log_at[1] = len(L)
        else:
            row("its log", "none on this mac")
    er = r.get("errors") or {}
    head("engine errors (the last 30)")
    if not broken("errors", er):
        if er.get("logs"):
            L.extend(_table(er["logs"], [("log", "log"), ("lines", "lines"), ("kb", "kb"), ("changed", "changed"), ("errors", "errors")]))
        if er.get("last"):
            L.extend(_table(er["last"], [("when", "when"), ("where", "where"), ("type", "type"), ("at", "at"), ("message", "message, redacted")]))
        else:
            row("errors", "none recorded")
    ti = r.get("timings") or {}
    head("timings")
    row("collect, all sources", "%s seconds" % _fmt(ti.get("collect_secs")))
    row("first words, measured", "%s seconds (median of the plan's models)" % _fmt(ti.get("first_token_secs")))
    steps = ti.get("answer_steps") or {}
    if steps:
        L.extend(_table([dict(v, step=k) for k, v in steps.items()], [("step", "answer step"), ("median_secs", "median secs"), ("calls", "calls")]))
    else:
        row("answers", "none asked yet")
    if "try" in r:
        tr = r["try"] or {}
        head("--try: the real steps, run now")
        if not broken("try", tr):
            for st in tr.get("steps") or []:
                rest = {k: v for k, v in st.items() if k not in ("step", "ok", "secs", "by_source", "checks", "sources") and v not in ("", None)}
                row(st.get("step"), "%s in %s s%s" % ({True: "pass", False: "fail", None: "skipped"}[st.get("ok")], _fmt(st.get("secs")), ("  " + _pairs(rest)) if rest else ""))
                if st.get("sources"):
                    row("  doctor says", _pairs(st["sources"]))
                if st.get("checks"):
                    row("  checks", _pairs(st["checks"]))
                by = st.get("by_source") or {}
                if by and isinstance(next(iter(by.values())), dict):
                    L.extend(_table([dict(v, source=k) for k, v in by.items()], [("source", "source"), ("state", "state"), ("rows", "rows"), ("secs", "secs"), ("reason", "reason")], "    "))
    L.extend(["", "end of report. %s strings were changed by the last redaction pass." % _fmt((r.get("report") or {}).get("strings_changed_by_the_last_pass"))])
    over = len(L) - MAX_LINES
    if over > 0 and log_at[1] > log_at[0]:      # the app's log is the part that can run long: its oldest lines give way first
        cut = min(over + 1, log_at[1] - log_at[0])
        L[log_at[0]:log_at[0] + cut] = ["    (%d older lines left out to keep this short)" % cut]
    if len(L) > MAX_LINES:
        L = L[:MAX_LINES - 1] + ["(%d more lines left out to keep this short)" % (len(L) - MAX_LINES + 1)]
    return "\n".join(l.rstrip()[:240] for l in L).lower() + "\n"


def default_path():
    return os.path.join(os.path.expanduser("~"), "Desktop", "context-report-%s.txt" % time.strftime("%Y-%m-%d"))


def main(args):
    def after(flag):
        return [args[i + 1] for i, a in enumerate(args) if a == flag and i + 1 < len(args) and not args[i + 1].startswith("--")]
    as_json, out = "--json" in args, (after("--out") or [""])[0]
    say = (lambda s: None) if as_json and not out else (lambda s: print("  checking: " + s, file=sys.stderr, flush=True))
    r = build(try_="--try" in args, real="--real" in args, extra=after("--redact"), say=say)
    text = json.dumps(r, indent=1, ensure_ascii=False) + "\n" if as_json else render(r)
    if as_json and not out:
        sys.stdout.write(text)
        return 0
    wrote = ""
    for p in [os.path.abspath(os.path.expanduser(out))] if out else [default_path(), os.path.join(os.path.expanduser("~"), os.path.basename(default_path())),
                                                                    os.path.join(paths.HOME, os.path.basename(default_path()))]:
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
            wrote = p
            break
        except OSError:
            continue
    if not wrote:
        print("could not write the report. try: python3 -m ctx report --out <a folder you can write to>/report.txt", file=sys.stderr)
        return 1
    print(wrote)
    print("read it before you send it. it is plain text: delete any line you would rather not share.")
    return 0
