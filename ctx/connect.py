"""Connect an app that is not a built-in source.

    python3 -m ctx connect --search "<q>"     json list: apps on this mac and services we know, no model
    python3 -u -m ctx connect <id>            work out how to read it; progress lines, then one json line
    python3 -m ctx connect --enable <id> | --disable <id> | --list

A website, a feed, a folder, a file or a page of the owner's own notes is connected the same way, with no model at all:
ctx/canvas.py. `--search` offers one for whatever was typed, and those ids are handed to it.

How `connect <id>` works for an app:
  1. survey its data folders, read-only: which stores exist, their sizes, sqlite tables and row counts
  2. ask the owner's own model to write one function, read(days, emit). It sees the survey only, and exactly this:
     the app's name; its data folders, with the home folder written as ~; for each store its kind, size in bytes,
     how many files and the month it last changed; for sqlite, table names, row counts, column names with their
     declared types, and two sample rows for up to four tables; for up to three json, plist or jsonl files, their
     shape. In every sample and shape each value is replaced by its type and length, and a number by its type and
     how many digits it has (`<int 10 digits>`): true, false and null stay. Sent as they are: the
     names of files, folders, tables, columns and stored keys, unless a name looks like an account or an id
     (then it is *, or the keys are counted). On a second try it also sees why the first reader was refused, or
     the type and line of the error it stopped at. No value of any row leaves the mac.
  3. vet that code with ast before it ever runs: a short list of imports, no writes, no network, no paths outside
     the surveyed folders
  4. run it once in a child process with a time limit and the same rules enforced again at run time, count the rows,
     and save it to ~/.context/v2/custom/<slug>.py with a sidecar that pins its sha256. It is not enabled yet.
"""
import ast, glob, hashlib, json, os, plistlib, re, shutil, sqlite3, subprocess, sys, tempfile, time
from . import paths

CUSTOM = os.path.join(paths.HOME, "custom")
ENABLED = os.path.join(CUSTOM, "enabled.json")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")
APP_DIRS = ["/Applications", os.path.join(HOME, "Applications"), "/System/Applications"]
FDA = "blocked by macos: grant full disk access to context (system settings > privacy & security), then try again"
# app slug -> the built-in source that already reads it
BUILT_IN = {"whatsapp": "whatsapp", "messages": "imessage", "telegram": "telegram", "slack": "slack", "mail": "email", "notes": "apple_notes",
            "calendar": "calendar", "cursor": "cursor", "claude": "claude_code", "codex": "codex", "obsidian": "obsidian", "dia": "browser_history",
            "safari": "safari_history", "grok_bot": "grok_bot", "chatgpt": "chatgpt_export"}
LIMIT = 60   # seconds a reader may run


def say(phase):
    print("@" + json.dumps({"phase": phase}), flush=True)


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def tilde(p):
    return "~" + p[len(HOME):] if p.startswith(HOME) else p


# ---------------------------------------------------------------- search

def _apps():
    seen = {}
    for root in APP_DIRS:
        for p in glob.glob(os.path.join(root, "*.app")) + glob.glob(os.path.join(root, "*", "*.app")):
            try:
                with open(os.path.join(p, "Contents", "Info.plist"), "rb") as f:
                    info = plistlib.load(f)
            except Exception:
                info = {}
            name = info.get("CFBundleDisplayName") or info.get("CFBundleName") or os.path.basename(p)[:-4]
            sid = slug(os.path.basename(p)[:-4])
            seen.setdefault(sid, {"id": sid, "name": str(name), "kind": "app", "installed": True, "bundle_id": info.get("CFBundleIdentifier", ""),
                                  "app_path": p, "known": sid in BUILT_IN})
    return seen


def _services():
    from . import request
    return {s["id"]: {"id": s["id"], "name": s["name"], "kind": "service", "installed": False, "known": True} for s in request.SERVICES}


def search(q):
    q = q.strip().lower()
    apps, services = _apps(), _services()
    hits = [a for a in apps.values() if q in a["name"].lower() or q in a["id"] or q.replace(" ", "_") in a["id"]]
    hits.sort(key=lambda a: (not a["name"].lower().startswith(q), a["name"].lower()))
    hits += [s for s in services.values() if q in s["name"].lower() and s["id"] not in {h["id"] for h in hits}]
    return hits[:20]


def search_all(q):
    """search(), plus what was typed read as a thing of the owner's own: a website, a feed, a folder, a file, a repo;
    and when nothing matches at all, a blank note. So the panel never ends in nothing. (ctx/canvas.py)"""
    hits = search(q) if q.strip() else []
    try:
        from . import canvas
        return canvas.candidates(q, hits)
    except Exception:
        return hits


# ---------------------------------------------------------------- survey

SKIP_DIRS = {"cache", "caches", "code cache", "gpucache", "dawncache", "dawngraphitecache", "dawnwebgpucache", "blob_storage", "crashpad", "logs",
             "node_modules", "service worker", "shadercache", "grshadercache", "graphitedawncache", "sentry", "webstorage", "shared dictionary",
             "session storage", "network", "component_crx_cache", "extensions", "partitions", "videodecodestats", "safe browsing", "dictionaries"}
SKIP_FILES = {"dips", "trust tokens", "sharedstorage", "declarative_performance_observer.db", "cookies", "web data", "history", "favicons",
              "login data", "top sites", "network persistent state", "preferences", "local state", "transportsecurity", "quotamanager",
              "emoji-index-en.json", "package.json"}   # browser-engine housekeeping that every electron app carries
TYPES = {".sqlite": "sqlite", ".sqlite3": "sqlite", ".db": "sqlite", ".store": "sqlite", ".json": "json", ".jsonl": "jsonl", ".ndjson": "jsonl",
         ".plist": "plist", ".md": "text", ".txt": "text"}


def _folders(name, bundle_id):
    lib, out = os.path.join(HOME, "Library"), []
    wants = {name.lower(), name.lower().replace(" ", ""), bundle_id.lower()} - {""}
    try:
        out += [os.path.join(lib, "Application Support", d) for d in os.listdir(os.path.join(lib, "Application Support")) if d.lower() in wants]
    except OSError:
        pass
    if bundle_id:
        out.append(os.path.join(lib, "Containers", bundle_id, "Data"))
        out += [p for p in glob.glob(os.path.join(lib, "Group Containers", "*")) if bundle_id.lower() in p.lower()]
    out.append(os.path.join(HOME, "." + slug(name)))
    return [p for p in dict.fromkeys(out) if os.path.isdir(p)]


def _mask(part):
    """A folder or file name that looks like an account, an id or a title is not sent: it becomes *."""
    stem = os.path.splitext(part)[0]
    if "@" in part or re.fullmatch(r"[0-9a-fA-F-]{16,}|\d{6,}", stem) or len(stem) > 40:
        return "*" + os.path.splitext(part)[1]
    return part


def _open_ro(path):
    """A read-only connection. If the app holds a lock, read a copy instead. Returns (connection, temp dir or None)."""
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path.replace("?", "%3f").replace("#", "%23"), uri=True, timeout=2)
        con.execute("select name from sqlite_master limit 1").fetchall()
        return con, None
    except sqlite3.DatabaseError as e:
        if "not a database" in str(e) or "encrypted" in str(e):
            raise
    tmp = tempfile.mkdtemp(prefix="ctx_survey_")
    for ext in ("", "-wal", "-shm"):
        if os.path.exists(path + ext):
            shutil.copy2(path + ext, os.path.join(tmp, "copy.db" + ext))
    con = sqlite3.connect(os.path.join(tmp, "copy.db"), timeout=2)
    con.execute("select name from sqlite_master limit 1").fetchall()
    return con, tmp


def redact(v, depth=0):
    """Keep the shape, drop the content: every value becomes its type and length. A number becomes its type and how many
    digits it has before the point (enough to tell seconds from milliseconds, a flag from an id; the number itself, which
    can be a phone number, an account or an amount, is not sent). True, False and nothing stay: they hold no content.
    Names of keys stay unless most of them look like ids."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        try:
            whole = abs(int(v))
        except (ValueError, OverflowError):        # nan, inf
            return "<%s>" % type(v).__name__
        return "<%s %d digit%s%s>" % (type(v).__name__, len(str(whole)), "" if len(str(whole)) == 1 else "s", " negative" if v < 0 else "")
    if isinstance(v, bytes):
        return "<bytes %d>" % len(v)
    if isinstance(v, str):
        s = v.strip()
        if depth < 5 and len(s) < 2_000_000 and s[:1] in "[{" and s[-1:] in "]}":
            try:
                return {"<str %d holding json>" % len(v): redact(json.loads(s), depth + 1)}
            except ValueError:
                pass
        hint = (" iso-date" if re.match(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d", s) else " uuid" if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}", s)
                else " html" if re.search(r"</\w+>", s) else " path" if s.startswith(("/", "~/")) else "")
        return "<str %d%s>" % (len(v), hint)
    if depth > 6:
        return "<%s>" % type(v).__name__
    if isinstance(v, (list, tuple)):
        return [redact(x, depth + 1) for x in v[:2]] + (["<%d more>" % (len(v) - 2)] if len(v) > 2 else [])
    if isinstance(v, dict):
        keys = list(v)
        odd = sum(1 for k in keys if "@" in str(k) or re.fullmatch(r"[0-9a-fA-F-]{12,}|\d{5,}", str(k)) or len(str(k)) > 40 or " " in str(k))
        if keys and (odd > len(keys) / 2 or len(keys) > 60):   # a map keyed by ids or names: the keys are content too
            return {"<%d keys like ids>" % len(keys): redact(v[keys[0]], depth + 1)}
        return {str(k): redact(x, depth + 1) for k, x in v.items()}
    return "<%s>" % type(v).__name__


def _sqlite_info(path):
    con, tmp = _open_ro(path)
    try:
        tables = []
        for (t,) in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'").fetchall()[:60]:
            q = '"%s"' % t.replace('"', '""')
            try:
                n = con.execute("select count(*) from %s" % q).fetchone()[0]
                cols = [(c[1], c[2]) for c in con.execute("pragma table_info(%s)" % q).fetchall()]
            except sqlite3.Error:
                continue
            tables.append({"table": t, "rows": n, "columns": ["%s %s" % c for c in cols][:40]})
        tables.sort(key=lambda t: -t["rows"])
        for t in [t for t in tables if t["rows"] and any("TEXT" in c.upper() or "CHAR" in c.upper() or "BLOB" in c.upper() or c.endswith(" ") for c in t["columns"])][:4]:
            cur = con.execute('select * from "%s" order by rowid desc limit 2' % t["table"].replace('"', '""'))
            names = [d[0] for d in cur.description]
            t["sample_rows"] = [{k: redact(v, 1) for k, v in zip(names, r) if v is not None} for r in cur.fetchall()]
        return tables
    finally:
        con.close()
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def survey(name, bundle_id):
    """What is on disk for this app. Raises PermissionError when macOS will not let us look."""
    roots = _folders(name, bundle_id)
    stores, groups, level = [], {}, []
    for root in roots:
        try:
            os.listdir(root)
        except PermissionError:
            raise PermissionError(FDA)
        for d, dirs, files in os.walk(root):
            rel = os.path.relpath(d, root)
            if rel.count(os.sep) >= 6:
                dirs[:] = []
            dirs[:] = [x for x in dirs if x.lower() not in SKIP_DIRS and not x.endswith((".app", ".framework"))]
            if "CURRENT" in files and any(f.endswith((".ldb", ".log")) for f in files):
                level.append(os.sep.join(_mask(x) for x in tilde(d).split(os.sep)))
                dirs[:] = []
                continue
            for f in files:
                if f.lower() in SKIP_FILES or f.endswith(("-wal", "-shm", "-journal")):
                    continue
                p = os.path.join(d, f)
                kind = TYPES.get(os.path.splitext(f)[1].lower())
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if not kind and st.st_size >= 100:
                    try:
                        with open(p, "rb") as fh:
                            kind = "sqlite" if fh.read(16) == b"SQLite format 3\x00" else None
                    except OSError:
                        kind = None
                if kind and st.st_size >= 100:
                    groups.setdefault((d, kind, os.path.splitext(f)[1].lower()), []).append((p, st.st_size, st.st_mtime))
    for (d, kind, ext), files in groups.items():
        shown = os.sep.join(_mask(x) for x in tilde(d).split(os.sep))
        if len(files) > 3 or kind == "text":   # many alike: give the pattern, not the names
            stores.append({"path": "%s/*%s" % (shown, ext), "type": kind, "files": len(files), "bytes": sum(f[1] for f in files),
                           "newest": time.strftime("%Y-%m", time.localtime(max(f[2] for f in files))), "_real": max(files, key=lambda f: f[1])[0]})
        else:
            for p, size, mt in files:
                stores.append({"path": "%s/%s" % (shown, _mask(os.path.basename(p))), "type": kind, "bytes": size,
                               "newest": time.strftime("%Y-%m", time.localtime(mt)), "_real": p})
    weight = {"sqlite": 4, "jsonl": 3, "json": 2, "text": 2, "plist": 1}
    stores.sort(key=lambda s: -(weight[s["type"]] * (s["bytes"] ** 0.5)))
    stores = stores[:40]
    looked = 0
    for s in stores:
        real = s.pop("_real")
        try:
            if s["type"] == "sqlite":
                try:
                    s["tables"] = _sqlite_info(real)
                except sqlite3.DatabaseError:
                    s["encrypted"] = True
            elif looked < 3 and s["type"] in ("json", "plist") and s["bytes"] < 40_000_000:
                with open(real, "rb") as f:
                    s["shape"] = redact(json.load(f) if s["type"] == "json" else plistlib.load(f))
                looked += 1
            elif looked < 3 and s["type"] == "jsonl":
                with open(real, errors="replace") as f:
                    s["shape"] = [redact(json.loads(l)) for l in [f.readline() for _ in range(2)] if l.strip()]
                looked += 1
        except Exception:
            s["unreadable"] = True
    return {"folders": [tilde(r) for r in roots], "stores": stores, "leveldb_folders": level[:10]}, roots


# ---------------------------------------------------------------- vetting

IMPORTS = {"json", "sqlite3", "os", "os.path", "glob", "re", "datetime", "time", "plistlib", "gzip", "zlib", "base64", "struct", "html", "shutil", "tempfile"}
OS_PATH = {"join", "exists", "isfile", "isdir", "islink", "expanduser", "basename", "dirname", "splitext", "split", "getmtime", "getsize", "getctime",
           "abspath", "realpath", "normpath", "relpath", "sep"}
# what may be taken from each module. a module holds other modules (re.enum.sys, os.path.os, sqlite3.dbapi2) and through
# them everything: so a name not listed here is refused, and a module may only be used as `module.name`, never handed on.
ONLY = {"os": {"path", "listdir", "walk", "scandir", "stat", "sep", "fspath"}, "os.path": OS_PATH,
        "shutil": {"copy", "copy2", "copyfile"}, "tempfile": {"mkdtemp", "gettempdir"},
        "json": {"loads", "load", "dumps", "JSONDecodeError"}, "sqlite3": {"connect", "Row", "Error", "DatabaseError", "OperationalError"},
        "glob": {"glob", "iglob", "escape"},
        "re": {"compile", "search", "match", "fullmatch", "sub", "subn", "split", "findall", "finditer", "escape", "error",
               "I", "M", "S", "X", "U", "A", "IGNORECASE", "MULTILINE", "DOTALL", "VERBOSE", "UNICODE", "ASCII"},
        "datetime": {"datetime", "date", "time", "timedelta", "timezone", "UTC"},
        "time": {"time", "mktime", "strftime", "strptime", "gmtime", "localtime", "timezone", "struct_time"},
        "plistlib": {"load", "loads", "InvalidFileException", "UID"}, "gzip": {"open", "decompress", "GzipFile", "BadGzipFile"},
        "zlib": {"decompress", "decompressobj", "error", "MAX_WBITS"},
        "base64": {"b64decode", "urlsafe_b64decode", "standard_b64decode", "b32decode", "b16decode", "b85decode", "a85decode"},
        "struct": {"unpack", "unpack_from", "iter_unpack", "calcsize", "error", "Struct"}, "html": {"unescape", "escape"}}
BANNED = {"eval", "exec", "compile", "__import__", "importlib", "ctypes", "pickle", "marshal", "subprocess", "socket", "urllib", "http", "requests",
          "getattr", "setattr", "delattr", "globals", "locals", "vars", "breakpoint", "input", "system", "popen", "remove", "unlink", "rename",
          "renames", "rmdir", "removedirs", "rmtree", "move", "chmod", "chown", "truncate", "kill", "fork", "write", "writelines", "write_text",
          "write_bytes", "dump", "executescript", "enable_load_extension", "load_extension", "symlink", "link", "mkfifo", "startfile", "putenv",
          # the ways from an object to the interpreter's own frames and from there to anything (a generator's frame holds its caller's globals)
          "gi_frame", "gi_code", "gi_yieldfrom", "cr_frame", "cr_code", "ag_frame", "ag_code", "f_back", "f_globals", "f_locals", "f_builtins", "f_code",
          "tb_frame", "tb_next", "co_code", "co_consts", "func_globals", "modules", "builtins", "sys", "posix", "pwrite", "pread", "sendfile",
          "execv", "execve", "execvp", "execl", "spawnv", "spawnl", "posix_spawn", "Popen", "FileIO", "dbapi2", "memoryview", "open_code",
          "help", "exit", "quit", "type", "object", "super", "classmethod", "staticmethod", "property"}
SQL_WRITE = re.compile(r"(?i)\b(insert\s+(or\s+\w+\s+)?into|update\s+\S+\s+set|delete\s+from|drop\s+(table|index|view)|alter\s+table|create\s+(table|index|view|trigger)"
                       r"|attach\s+database|vacuum|pragma\s+\w+\s*=)")
PATHY = re.compile(r"^(~|/(Users|Library|Applications|System|private|var|tmp|etc|Volumes|usr|bin|sbin|opt|home|dev|cores)(/|$))")


def vet(code, roots):
    """Reasons this code may not run, or [] when it may. Static only; the child process enforces the same rules again."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return ["does not parse: line %s" % e.lineno]
    why, alias = [], {}
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "read"]
    if len(fns) != 1 or len(fns[0].args.args) != 2:
        why.append("must define exactly one read(days, emit)")
    for n in tree.body:
        if not isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Assign, ast.Expr)) or (isinstance(n, ast.Expr) and not isinstance(n.value, ast.Constant)):
            why.append("line %d: only imports, constants and functions at the top level" % n.lineno)
    allowed = [os.path.realpath(r) for r in roots]
    for n in ast.walk(tree):            # first the imports, so a name is known as a module wherever it is used
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name in IMPORTS:
                    alias[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
    based = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Attribute)}        # names used as `name.something`
    for n in ast.walk(tree):
        line = getattr(n, "lineno", 0)
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name not in IMPORTS:
                    why.append("line %d: import %s is not allowed" % (line, a.name))
        elif isinstance(n, ast.ImportFrom):
            if n.level or n.module not in IMPORTS:
                why.append("line %d: from %s import is not allowed" % (line, n.module))
            for a in n.names:
                if a.name == "*" or a.name in BANNED or a.name not in ONLY.get(n.module, ()) or a.name.startswith("_"):
                    why.append("line %d: %s.%s is not allowed" % (line, n.module, a.name))
                elif n.module == "os" and a.name == "path":
                    alias[a.asname or "path"] = "os.path"
        elif isinstance(n, (ast.AsyncFunctionDef, ast.Global, ast.Nonlocal, ast.ClassDef)):
            why.append("line %d: %s is not allowed" % (line, type(n).__name__.lower()))
        elif isinstance(n, ast.Name):
            if n.id in BANNED or n.id.startswith("__"):
                why.append("line %d: %s is not allowed" % (line, n.id))
            elif n.id in alias and (id(n) not in based or not isinstance(n.ctx, ast.Load)):     # a module is only ever `module.name`: never stored, passed or returned
                why.append("line %d: the module %s may only be used as %s.<name>" % (line, n.id, n.id))
        elif isinstance(n, ast.Attribute):
            if (n.attr in BANNED and not (n.attr == "compile" and isinstance(n.value, ast.Name) and alias.get(n.value.id) == "re")) or n.attr.startswith("_"):
                why.append("line %d: .%s is not allowed" % (line, n.attr))     # re.compile is fine; the builtin compile is a name
            mod = alias.get(n.value.id) if isinstance(n.value, ast.Name) else None
            if mod is None and isinstance(n.value, ast.Attribute) and isinstance(n.value.value, ast.Name) and alias.get(n.value.value.id) == "os" and n.value.attr == "path":
                mod = "os.path"
            if mod and n.attr not in ONLY[mod]:
                why.append("line %d: %s.%s is not allowed" % (line, mod, n.attr))
        elif isinstance(n, (ast.JoinedStr, ast.Constant)) and isinstance(getattr(n, "value", None), str) and re.search(r"\{[^{}]*[.\[]", n.value) and ".format" in code:
            why.append("line %d: a format string that reaches into an object is not allowed" % line)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open":
            mode = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "mode"), None)
            if mode is not None and not (isinstance(mode, ast.Constant) and mode.value in ("r", "rb", "rt")):
                why.append("line %d: open() may only read" % line)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            s = n.value
            if SQL_WRITE.search(s):
                why.append("line %d: sql that writes is not allowed" % line)
            if PATHY.match(s) or "/../" in s or s.startswith(".."):
                real = os.path.realpath(os.path.expanduser(s.split("*")[0].rstrip("/") or "/"))
                if ".." in s or not any(real == r or real.startswith(r + os.sep) for r in allowed):
                    why.append("line %d: a path outside the app's own folders" % line)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and re.search(r"(?i)\b_?(posix)?subprocess\b|\b_?socket\b|\bbuiltins\b|\bctypes\b|real_open|/\.ssh\b|\.aws/|keychain", n.value):
            why.append("line %d: a name that has no place in a reader" % line)
    return list(dict.fromkeys(why))[:8]


# ---------------------------------------------------------------- running a reader

# Runs inside `python3 -I`, inside the macos sandbox (ctx/sandbox.py). argv: reader file, rows file, slug, days, private
# temp dir, json list of folders. The kernel is what keeps it in: it can read python, the app's folders and its own work
# folder, write only the work folder, start nothing and reach no network. The patches below repeat those rules inside
# python so a reader that strays gets a plain error at the line that strayed; they are not what the safety rests on.
# Nothing of ctx is imported here: the child cannot read the engine or the archive at all. Rows are scrubbed by the
# parent when it takes them over.
RUNNER = r"""
import builtins, io, json, os, sys, sqlite3, tempfile, time
reader, out_path, slug, days, tmp, roots = sys.argv[1:7]
roots = [os.path.realpath(r) for r in json.loads(roots)]; tmp = os.path.realpath(tmp)
tempfile.tempdir = tmp
code = compile(open(reader).read(), "reader", "exec")
out = open(out_path, "w")
inside = lambda p, where: any(p == w or p.startswith(w + os.sep) for w in where)
real_open, real_connect = builtins.open, sqlite3.connect
def guarded_open(file, mode="r", *a, **k):
    if isinstance(file, int): raise PermissionError("no file descriptors")
    p = os.path.realpath(os.fspath(file))
    if any(c in mode for c in "wax+"):
        if not inside(p, [tmp]): raise PermissionError("write outside the temp folder")
    elif not inside(p, roots + [tmp]): raise PermissionError("read outside the app's folders")
    return real_open(file, mode, *a, **k)
def guarded_connect(database, *a, **k):
    s = os.fspath(database); s = s[5:].split("?")[0] if s.startswith("file:") else s
    p = os.path.realpath(s)
    if inside(p, [tmp]): return real_connect(p, timeout=5)
    if not inside(p, roots): raise PermissionError("database outside the app's folders")
    return real_connect("file:" + p.replace("?", "%3f").replace("#", "%23") + "?mode=ro", uri=True, timeout=5)
def no(*a, **k): raise PermissionError("not allowed in a reader")
builtins.open = io.open = guarded_open; sqlite3.connect = sqlite3.dbapi2.connect = guarded_connect
for name in ("remove", "unlink", "rename", "renames", "replace", "rmdir", "removedirs", "system", "popen", "chown", "truncate", "kill",
             "symlink", "link", "fork", "execv", "execve", "execvp", "posix_spawn", "posix_spawnp", "_exit", "putenv"):
    if hasattr(os, name): setattr(os, name, no)
real_chmod = os.chmod
def guarded_chmod(path, *a, **k):
    if not inside(os.path.realpath(os.fspath(path)), [tmp]): raise PermissionError("chmod outside the temp folder")
    return real_chmod(path, *a, **k)
os.chmod = guarded_chmod
import socket; socket.socket = no; socket.create_connection = no
n, first = 0, ""
KEYS = {"messages": ("id", "ts", "thread_id", "thread", "kind", "who", "sender", "text"), "docs": ("id", "ts", "title", "text")}
def emit(row):
    global n, first
    if not isinstance(row, dict) or n >= 500000: return
    shape = "messages" if "thread_id" in row else "docs"
    r = {k: row[k] for k in KEYS[shape] if row.get(k) is not None}
    text = r.get("text")
    if not isinstance(text, str) or not text.strip(): return
    r["text"] = text[:20000]
    for k in ("title", "thread", "sender"):
        if k in r: r[k] = str(r[k])[:300]
    rid = str(r.get("id") or n); pre = "X" + slug + ":"
    r["id"] = rid if rid.startswith(pre) else pre + rid
    if "thread_id" in r and not str(r["thread_id"]).startswith(pre): r["thread_id"] = pre + str(r["thread_id"])
    ts = r.get("ts")
    if isinstance(ts, (int, float)) and ts > 0:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts / 1000 if ts > 1e11 else ts))
    r["ts"] = ts if isinstance(ts, str) else ""
    r["src"] = "custom_" + slug
    if shape == "messages":
        r["who"] = "me" if r.get("who") == "me" else "them"; r["kind"] = r.get("kind") if r.get("kind") in ("dm", "group") else "dm"
    out.write(json.dumps(r, ensure_ascii=False) + "\n"); n += 1
    if len(r["ts"]) >= 7 and r["ts"][:4].isdigit() and (not first or r["ts"][:7] < first): first = r["ts"][:7]
env = {"__name__": "reader"}
err = ""
try:
    exec(code, env)
    env["read"](int(days) or None, emit)
except BaseException as e:
    tb = e.__traceback__
    while tb and tb.tb_next: tb = tb.tb_next
    err = "%s at line %s" % (type(e).__name__, tb.tb_lineno if tb else "?")   # the type and place only: a message could hold content
out.close()
sys.stdout.write(json.dumps({"rows": n, "since": first, "error": err}))
"""


def run_code(code, sid, roots, days, out_path, limit=LIMIT, vetted=True):
    """Run reader code in a child process inside the macos sandbox. Returns {"rows", "since", "error"}. Rows land in
    out_path, scrubbed. The code is vetted first; if the sandbox cannot be started the code is not run at all.
    vetted=False skips the vetting: only the tests use it, to show that the sandbox holds without it."""
    from . import sandbox
    from .collect import put
    why = vet(code, roots) if vetted else []
    if why:
        return {"rows": 0, "since": "", "error": "refused: " + why[0]}
    if not re.fullmatch(r"[a-z0-9_]{1,80}", str(sid)):
        return {"rows": 0, "since": "", "error": "refused: not a source id"}
    work = tempfile.mkdtemp(prefix="ctx_reader_")
    try:
        os.mkdir(os.path.join(work, "tmp"))
        with open(os.path.join(work, "reader.py"), "w") as f:
            f.write(code)
        rows = os.path.join(work, "rows.jsonl")
        try:
            r = sandbox.run(["-c", RUNNER, os.path.join(work, "reader.py"), rows, sid, str(days or 0), os.path.join(work, "tmp"), json.dumps(roots)],
                            read=roots, write=[work], timeout=limit, cwd=work, tmp=os.path.join(work, "tmp"))
        except subprocess.TimeoutExpired:
            return {"rows": 0, "since": "", "error": "took longer than %d seconds" % limit}
        except sandbox.Unavailable as e:
            return {"rows": 0, "since": "", "error": str(e)}
        try:
            res = json.loads(r.stdout[r.stdout.rindex('{"rows"'):])
        except ValueError:
            return {"rows": 0, "since": "", "error": "the reader stopped without an answer"}
        n = 0
        with open(out_path, "w") as out:        # the child's rows are taken over here, each one through the scrubber
            try:
                with open(rows, errors="replace") as f:
                    for line in f:
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(row, dict) and str(row.get("src")) == "custom_" + sid and str(row.get("id", "")).startswith("X" + sid + ":"):
                            put(out, row)
                            n += 1
            except OSError:
                pass
        return {"rows": n, "since": str(res.get("since") or "")[:7], "error": str(res.get("error") or "")[:120]}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _sidecar(sid):
    with open(os.path.join(CUSTOM, sid + ".json")) as f:
        return json.load(f)


def _checked(sid):
    """The saved reader's code and sidecar, only if the code is still the code that was vetted."""
    side = _sidecar(sid)
    with open(os.path.join(CUSTOM, sid + ".py")) as f:
        code = f.read()
    if hashlib.sha256(code.encode()).hexdigest() != side.get("sha256"):
        raise PermissionError("the saved reader for %s was changed after it was checked; connect it again" % sid)
    return code, side


def enabled():
    """[(slug, kind)] of readers that are switched on. For collect.py."""
    try:
        with open(ENABLED) as f:
            on = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for sid in on:
        try:
            out.append((sid, _sidecar(sid)["kind"]))
        except (OSError, ValueError, KeyError):
            pass
    return out


def reader(sid):
    """A collect-style source: fn(days, out) -> row count. Runs the saved reader in a child process, after the sha256 check."""
    def fn(days, out):
        from .collect import put
        code, side = _checked(sid)
        fd, tmp = tempfile.mkstemp(prefix="ctx_rows_", suffix=".jsonl")
        os.close(fd)
        try:
            res = run_code(code, sid, side["folders"], days, tmp)
            if res["error"] and not res["rows"]:
                raise FileNotFoundError(res["error"])
            n = 0
            with open(tmp) as f:
                for line in f:
                    put(out, json.loads(line))
                    n += 1
            return n
        finally:
            os.remove(tmp)
    return fn


# ---------------------------------------------------------------- the model writes the reader

SYSTEM = """You write one small Python reader for a Mac app's local data, for a personal archive tool that runs on the owner's own Mac.
You get a survey of the app's data folders: stores, sqlite schemas with row counts, and sample rows in which every value was replaced
by its type and length (for example "<str 212>", "<int 10 digits>", "<str 24 iso-date>"). You never see content, and never a number itself:
a time stored as a number shows as its digit count (10 digits: seconds since 1970; 13: milliseconds; 9: seconds since 2001, the mac's own clock; 16 or more: micro or nanoseconds).

Write: def read(days, emit)
- days is None (everything) or a number: then emit only rows from the last `days` days.
- call emit(row) once per row. Pick ONE shape for the whole app:
  messages (people writing to each other): {"id", "ts", "thread_id", "thread", "kind": "dm" or "group", "who": "me" or "them", "sender", "text"}
  docs (notes, transcripts, dictations, documents, anything else): {"id", "ts", "title", "text"}
- ts: seconds since 1970 as a number, or an ISO 8601 UTC string. id: stable and unique per row.
- Read what the owner wrote, said or was told. Skip settings, caches, analytics, logs and empty rows.

Rules, checked by a program before the code runs; code that breaks one is thrown away:
- only these imports: json, sqlite3, os, os.path, glob, re, datetime, time, plistlib, gzip, zlib, base64, struct, html, shutil, tempfile
- read-only. open() only with mode "r" or "rb". No write, dump, remove, rename, subprocess, network, eval, exec, getattr, classes with dunders.
- from os use only os.path.*, os.listdir, os.walk, os.scandir, os.stat. from shutil only copy, copy2, copyfile. from tempfile only mkdtemp.
- paths: build them from os.path.expanduser("~/...") literals that sit inside the surveyed folders. No other paths.
- sqlite: sqlite3.connect(path) is opened read-only for you. If a database may be locked by the running app, copy it (and its -wal and -shm
  files if present) into tempfile.mkdtemp() and read the copy. Only SELECT statements.
- top level may hold only imports, constants and functions. Be defensive: missing files, missing keys, bad rows must not raise.

Answer {"kind": "messages" or "docs", "how": "<one plain lowercase sentence: what is read and from which file>", "code": "<the python source>"}
or, when there is nothing readable (encrypted store, only LevelDB/IndexedDB, nothing textual): {"cannot": "<one plain lowercase sentence why>"}."""


def _ask(name, found, again=""):
    from . import llm
    prompt = "App: %s\n\nSurvey:\n%s" % (name, json.dumps(found, ensure_ascii=False, indent=1)[:60000])
    if again:
        prompt += "\n\nYour last reader was not accepted: %s\nWrite it again and fix that." % again
    r = llm.ask_json(SYSTEM, prompt, model=llm.STRONG, tag="connect")
    return r if isinstance(r, dict) else {}


def connect(sid):
    """Work out how to read one app or service. Returns the final object; prints progress on the way."""
    apps, services = _apps(), _services()
    app = apps.get(sid)
    name = (app or services.get(sid) or {}).get("name", sid)
    res = lambda state, how="", rows=0, since="", detail="": {"id": sid, "name": name, "state": state, "how": how,
                                                                "sample": {"rows": rows, "since": since}, "detail": detail}
    if sid in services and not (app and sid not in BUILT_IN and _folders(app["name"], app["bundle_id"])):
        from . import request
        s = request.BY_ID[sid]
        return res("ready", "asks %s for your official export in your signed-in browser; the archive arrives in %s and holds %s"
                   % (s["name"].lower(), s["arrives"], s["what"]))
    if not app:
        return res("cannot", detail="no app on this mac holds its data; it needs an export or the browser extension")
    if sid in BUILT_IN:
        return res("ready", "already built in: context reads %s as the source '%s'" % (name.lower(), BUILT_IN[sid]))
    low = name.lower()
    say("looking at where %s keeps its data" % low)
    try:
        found, roots = survey(app["name"], app["bundle_id"])
    except PermissionError as e:
        return res("needs_you", detail=str(e))
    if not roots or not found["stores"]:
        why = ("%s keeps its data in a browser-style store (leveldb) that cannot be read from outside" % low if found.get("leveldb_folders")
               else "found no data that %s keeps on this mac" % low)
        return res("cannot", detail=why)
    dbs = [s for s in found["stores"] if s["type"] == "sqlite"]
    if dbs and max(dbs, key=lambda s: s["bytes"]).get("encrypted") and not any(t["rows"] for s in dbs for t in s.get("tables", [])):
        return res("cannot", detail="%s encrypts its database on disk; only the app itself can read it" % low)
    say("found %d stores; asking your model to write a reader" % len(found["stores"]))
    again, last = "", ""
    for attempt in (1, 2):
        try:
            ans = _ask(name, found, again)
        except Exception as e:
            return res("needs_you", detail="your model did not answer: " + str(e)[:120].lower())
        if ans.get("cannot"):
            return res("cannot", detail=str(ans["cannot"])[:200].lower())
        code, kind, how = ans.get("code") or "", ans.get("kind"), str(ans.get("how") or "")[:240].lower()
        if not code or kind not in ("messages", "docs"):
            again = last = "the answer had no code or no kind"
            continue
        say("checking the reader before it runs")
        why = vet(code, roots)
        if why:
            again = "; ".join(why)
            last = "the reader your model wrote broke the safety rules (%s)" % why[0]
            say("the reader was refused: " + why[0])
            continue
        say("trying it once on %s" % low)
        fd, tmp = tempfile.mkstemp(prefix="ctx_trial_", suffix=".jsonl")
        os.close(fd)
        try:
            out = run_code(code, sid, roots, None, tmp)
        finally:
            os.remove(tmp)
        if not out["rows"]:
            again = "it ran and read 0 rows" + (" (%s)" % out["error"] if out["error"] else "")
            last = "the reader read nothing" + (": " + out["error"] if out["error"] else "")
            say("it read nothing; asking once more" if attempt == 1 else "it read nothing")
            continue
        os.makedirs(CUSTOM, exist_ok=True)
        with open(os.path.join(CUSTOM, sid + ".py"), "w") as f:
            f.write(code)
        with open(os.path.join(CUSTOM, sid + ".json"), "w") as f:
            json.dump({"id": sid, "name": name, "kind": kind, "how": how, "bundle_id": app["bundle_id"], "folders": roots,
                       "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "sha256": hashlib.sha256(code.encode()).hexdigest(),
                       "rows": out["rows"], "since": out["since"]}, f, indent=1)
        return res("ready", how, out["rows"], out["since"], out["error"] and "stopped early: " + out["error"])
    return res("cannot", detail=last)


# ---------------------------------------------------------------- enable, disable, list

def _set(sid, on):
    try:
        with open(ENABLED) as f:
            cur = json.load(f)
    except (OSError, ValueError):
        cur = []
    cur = [x for x in cur if x != sid] + ([sid] if on else [])
    os.makedirs(CUSTOM, exist_ok=True)
    with open(ENABLED + ".part", "w") as f:
        json.dump(cur, f)
    os.replace(ENABLED + ".part", ENABLED)


def enable(sid, on=True):
    if os.path.exists(os.path.join(CUSTOM, sid + ".json")):
        if on:
            _checked(sid)
        _set(sid, on)
        return dict(_listed(sid), enabled=on)
    if sid in _services():
        from . import request
        if on:
            return request.request(sid)
        request._save(sid, "declined")
        return request.service(sid)
    raise SystemExit("nothing connected under '%s': run python3 -m ctx connect %s first" % (sid, sid))


def _listed(sid):
    s = _sidecar(sid)
    return {"id": sid, "name": s["name"], "kind": s["kind"], "how": s["how"], "rows": s.get("rows", 0), "since": s.get("since", ""),
            "created": s["created"], "enabled": sid in [e[0] for e in enabled()]}


def listing():
    out = []
    for p in sorted(glob.glob(os.path.join(CUSTOM, "*.json"))):
        sid = os.path.basename(p)[:-5]
        if sid != "enabled" and os.path.exists(p[:-5] + ".py"):
            try:
                out.append(_listed(sid))
            except (ValueError, KeyError):
                pass
    return out


def _canvas_id(a):
    """Is this id one of canvas.py's (site:, folder:, note: ..., canvas_<slug>), or something typed that is no app and
    no service but is an address or a path?"""
    from . import canvas
    if not a:
        return False
    if canvas.is_id(a):
        return True
    return slug(a) not in _apps() and slug(a) not in _services() and not os.path.exists(os.path.join(CUSTOM, slug(a) + ".json")) and bool(canvas.resolve(a))


def main(argv):
    a = argv[0] if argv else ""
    arg = argv[1] if len(argv) > 1 else ""
    from . import canvas
    if a == "--search":
        print(json.dumps(search_all(arg)))
    elif a == "--list":
        print(json.dumps(listing() + canvas.listing()))
    elif a == "--remove" or _canvas_id(arg if a in ("--enable", "--disable") else a if not a.startswith("-") else ""):
        canvas.main(argv)       # a website, a feed, a folder, a file, a note: the owner's own things
    elif a in ("--enable", "--disable") and arg:
        print(json.dumps(enable(slug(arg), a == "--enable")))
    elif a and not a.startswith("-"):
        print(json.dumps(connect(slug(a))), flush=True)
    else:
        raise SystemExit('usage: python3 -m ctx connect --search "<q>" | <id> [--only posts|all|/path] | --enable <id> | --disable <id> | --remove <id> | --list')
