"""Take secrets out of the raw export files under ~/.context/v2/imports, in place.

The rows made from an export pass the scrubber; the export itself was kept as it came. This goes through the text
files of an export (json, jsonl, the x archive's .js, csv, html, txt, ics, vcf) and applies the same rules to the
text in them, and only to the text: json is read as json and written as json, csv cell by cell, html between its
tags, so no file is left that its reader cannot read.

    python3 -m ctx rawscrub             a dry run: counts only, by kind of file and by rule. nothing is changed
    python3 -m ctx rawscrub --apply     scrub. each file is written beside itself, checked, then swapped in one step.
                                        it asks you to type "scrub" first; --yes skips the question

What is NOT applied here is the rule for long opaque strings: in a raw file those are ids, cursors and links the
readers need, and a string with no space in it gets only the rules for named keys. So a bare unknown token that is a
whole message stays in the raw file (its row in the archive is still scrubbed).

Left alone and listed, by kind: mail boxes (.mbox: their text is encoded in ways a rule cannot see through, and a
rewrite needs as much free disk as the file), zips, databases, pictures and anything else that is not text.
Nothing is ever printed but counts: no text, no name, no path below the kind of export.
"""
import collections, csv, io, json, os, re, shutil, sys
from . import paths
from .scrub import PASSES, R

ROOT = os.path.join(paths.HOME, "imports")
NO_TEXT = {".at": "a place in a list, no text"}        # known files that hold nothing to scrub
TEXT = {".json": "json", ".jsonl": "jsonl", ".js": "js", ".csv": "csv", ".html": "html", ".htm": "html", ".txt": "text", ".ics": "text", ".vcf": "text"}
SKIP_PASS = {"opaque_token"}                    # ids, cursors and links live in raw files: see above
SOLID = {"named_key", "key_in_link"}            # the only rules for a string with no space in it
MAX_FILE = 600 * 1024 * 1024                     # a text file larger than this is listed, not loaded
TAG = re.compile(r"(<[^<>]{0,2000}>)")


def careful(text, fired=None):
    """scrub(), for a string out of a raw file: every rule but the opaque-string one; a string with no space only the
    named-key rules. fired, when given, is a Counter that takes the name of each rule that changed something."""
    if not text or len(text) < 6:
        return text
    solid = not any(c.isspace() for c in text)
    low = text.lower()
    for name, pattern, words, run in PASSES:
        if name in SKIP_PASS or (solid and name not in SOLID):
            continue
        if (pattern is not None and not pattern.search(text)) or (words is not None and not any(w in low for w in words)):
            continue
        new = run(text)
        if new != text:
            if fired is not None:
                fired[name] += 1
            text, low = new, new.lower()
    return text


def _walk(v, fired):
    if isinstance(v, str):
        return careful(v, fired)
    if isinstance(v, list):
        return [_walk(x, fired) for x in v]
    if isinstance(v, dict):
        return {k: _walk(x, fired) for k, x in v.items()}
    return v


def _json(text, fired):
    return json.dumps(_walk(json.loads(text), fired), ensure_ascii=False, indent=1)


JS_DATA = re.compile(r"\s*(?:window|self|globalThis)(?:\.[\w$]{1,80}|\[[\"'][\w$. -]{1,80}[\"']\]){1,6}\s*=\s*(?=[\[{])")


class NotData(ValueError):
    """A .js file that is a program, not an export's data."""


def _js(text, fired):
    """An account archive's data files: `window.YTD.name.part0 = [ ... ]` (x), `window.__THAR_CONFIG = { ... }`. Only a
    file that is one such line of data is touched: the json after the = is scrubbed and the head kept, letter for letter.
    Any other .js (the archive's own viewer, a script) is a program and is left as it is: never parsed, never rewritten."""
    m = JS_DATA.match(text)
    if not m:
        raise NotData()
    head, body = m.group(0), text[m.end():]
    tail = ""
    stripped = body.rstrip()
    if stripped.endswith(";"):
        tail, stripped = ";", stripped[:-1]
    return head + _json(stripped, fired) + tail + "\n"


def _jsonl(text, fired):
    out = []
    for line in text.split("\n"):
        if not line.strip():
            out.append(line)
            continue
        try:
            out.append(json.dumps(_walk(json.loads(line), fired), ensure_ascii=False))
        except ValueError:
            out.append(careful(line, fired))    # a line that is not json is plain text: scrubbed as text, its shape left alone
    return "\n".join(out)


def _csv(text, fired):
    rows = list(csv.reader(io.StringIO(text, newline="")))
    out = io.StringIO(newline="")
    w = csv.writer(out, lineterminator="\n")
    for row in rows:
        w.writerow([careful(c, fired) for c in row])
    return out.getvalue()


def _html(text, fired):
    parts = TAG.split(text)
    return "".join(p if i % 2 else careful(p, fired) for i, p in enumerate(parts))       # tags at odd places stay as they are


def _text(text, fired):
    return "\n".join(careful(l, fired) for l in text.split("\n"))


HOW = {"json": _json, "jsonl": _jsonl, "js": _js, "csv": _csv, "html": _html, "text": _text}


def _still_reads(kind, new):
    """Can the reader of this kind still read what was written? A file that fails this is not swapped in."""
    try:
        if kind == "json":
            json.loads(new)
        elif kind == "js":
            m = JS_DATA.match(new)
            json.loads(new[m.end():].rstrip().rstrip(";"))
        elif kind == "csv":
            list(csv.reader(io.StringIO(new, newline="")))
        return True
    except (ValueError, csv.Error):
        return False


def export_kind(path, root):
    """The kind of export a file belongs to, from the first folder name: `x-2026-01` is x. Never the name itself."""
    first = os.path.relpath(path, root).split(os.sep)[0]
    return re.split(r"[-_. ]", first)[0].lower()[:20] or "other"


def one(path, apply=False, fired=None):
    """Scrub one file. Returns "clean", "changed", "would change", "left: why". With apply, the new text is written
    beside the file, read back, and swapped in with one rename: a crash leaves the old file or the new one, never half."""
    kind = TEXT.get(os.path.splitext(path)[1].lower())
    if not kind:
        return "left: " + NO_TEXT.get(os.path.splitext(path)[1].lower(), "not a text file")
    try:
        st = os.lstat(path)
        if not os.path.isfile(path) or os.path.islink(path):
            return "left: not a plain file"
        if st.st_size > MAX_FILE:
            return "left: too large to load"
        with open(path, encoding="utf-8", newline="") as f:
            old = f.read()
    except UnicodeDecodeError:
        return "left: not utf-8 text"
    except OSError:
        return "left: could not be read"
    mine = collections.Counter()
    try:
        new = HOW[kind](old, mine)
    except NotData:
        return "left: a program, not data"
    except (ValueError, csv.Error, RecursionError):
        return "left: does not parse as " + kind
    if not mine:
        return "clean"                          # nothing fired: the file is left byte for byte, whatever re-writing would do to its spacing
    if fired is not None:
        fired.update(mine)
    if not apply:
        return "would change"
    if not _still_reads(kind, new):
        return "left: the scrubbed text would not parse"
    if shutil.disk_usage(os.path.dirname(path)).free < len(new.encode("utf-8")) + 512 * 1024 * 1024:
        return "left: not enough free disk"
    tmp = path + ".scrubbing"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(new)
            f.flush()
            os.fsync(f.fileno())
        with open(tmp, encoding="utf-8", newline="") as f:
            if f.read() != new:
                raise OSError("read back differs")
        os.utime(tmp, (st.st_atime, st.st_mtime))       # the readers know a file by its time and size: keep the time
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return "left: could not be written"
    return "changed"


def run(root=None, apply=False, say=None):
    """Go through every file under root. Returns counts only:
    {"files", "bytes", "free_bytes", "by_kind": {ext: {"files", "bytes", state: n}}, "rules": {rule: hits}, "by_export": {kind: {state: n}}, "left": {why: {ext: n}}}."""
    root = root or ROOT
    out = {"files": 0, "bytes": 0, "free_bytes": shutil.disk_usage(root).free if os.path.isdir(root) else 0, "by_kind": {}, "rules": collections.Counter(),
           "by_export": {}, "left": {}, "applied": bool(apply)}
    for d, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(files):
            p = os.path.join(d, name)
            if name.endswith(".scrubbing"):
                continue
            ext = os.path.splitext(name)[1].lower() or "(none)"
            try:
                size = os.lstat(p).st_size
            except OSError:
                continue
            state = one(p, apply, out["rules"])
            k = out["by_kind"].setdefault(ext, collections.Counter())
            k["files"] += 1
            k["bytes"] += size
            k[state.split(":")[0]] += 1
            out["files"] += 1
            out["bytes"] += size
            out["by_export"].setdefault(export_kind(p, root), collections.Counter())[state.split(":")[0]] += 1
            if state.startswith("left"):
                out["left"].setdefault(state[6:], collections.Counter())[ext] += 1
            if say and out["files"] % 200 == 0:
                say("%d files" % out["files"])
    out["rules"] = dict(out["rules"])
    for key in ("by_kind", "by_export", "left"):
        out[key] = {k: dict(v) for k, v in out[key].items()}
    return out


def main(argv):
    apply = "--apply" in argv
    if apply and "--yes" not in argv:
        if not sys.stdin.isatty() or input("this rewrites the raw export files in place. type scrub to go on: ").strip() != "scrub":
            raise SystemExit("nothing was changed")
    print(json.dumps(run(apply=apply), indent=1, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1:])
