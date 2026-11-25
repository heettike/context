"""Prompt overrides: an archive may carry its own wording for pieces of the prompts that read it and write its pages.

python3 -m ctx prompts                  does this archive override any piece, how many, are they all still in the source
python3 -m ctx prompts --check          also compare what the prompts render to with what the archive's file says they should
python3 -m ctx prompts --drop           what dropping the overrides would write again, counted; changes nothing
python3 -m ctx prompts --drop --yes     drop them: this archive is read with the prompts as the source has them

Who it is for: someone who tunes the wording of a prompt for their own archive (a different word for a kind of page, a
rule stated more firmly) without editing the source. The file is CTX_HOME/prompt-overrides.json:

  {"overrides": {"<sha256 of a piece of prompt as the source has it>": "<the text to use in its place>"},
   "expect": {"<module>.<NAME>": "<sha256 of that prompt as it must render>"}}

Every piece of prompt in the modules below passes through piece(). When the archive overrides that piece, piece() gives
the archive's text; otherwise the source's. A new archive has no such file. Two things to know before tuning:
  - the wiki keeps every page by the text of its prompt, so a prompt that changes by one word writes those pages again,
    on the owner's plan. `--drop` says how many before it does anything.
  - an override is tied to the piece it replaces by that piece's digest. When the source's piece is edited, the override
    no longer applies (`prompts` counts it under "no_longer_in_the_source") until its key is set to the new digest.
"expect" is optional: digests of whole prompts as they should render, so `--check` can say which prompt moved.

The file is read once per process: a running app or server takes a change when it starts again.
"""
import hashlib, json, os, sys

from . import paths

FILE = os.path.join(paths.HOME, "prompt-overrides.json")
MEM = os.path.join(paths.HOME, "memory")
MODULES = ("wiki", "understand", "voice", "whole")          # the modules whose prompts pass through piece()
_seen = {}


def _key(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file():
    if "file" not in _seen:
        try:
            with open(FILE, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        over = d.get("overrides") if isinstance(d, dict) else None
        _seen["file"] = {"overrides": {k: v for k, v in over.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(over, dict) else {},
                         "expect": d.get("expect") if isinstance(d, dict) and isinstance(d.get("expect"), dict) else {}}
    return _seen["file"]


def reset():
    """Forget what this process read (tests, and after --drop)."""
    _seen.clear()


def piece(text):
    """A piece of prompt as this archive is read with it: the archive's override when it has one for this piece, else the text given."""
    if not text:
        return text
    over = _file()["overrides"]
    return over.get(_key(text), text) if over else text


def _pieces():
    """Every piece of prompt in the source that passes through piece(): {module: [text]}. Read from the source, not run."""
    import ast
    out = {}
    for name in MODULES:
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py"), encoding="utf-8") as f:
                tree = ast.parse(f.read())
        except (OSError, SyntaxError):
            continue
        out[name] = [n.args[0].value for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_p"
                     and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)]
    return out


def _built():
    """What a model has already written into this archive, counted."""
    def count(folder, ends, deep=False):
        n = 0
        try:
            if deep:
                for _, _, names in os.walk(folder):
                    n += sum(1 for x in names if x.endswith(ends) and not x.startswith("."))
            else:
                n = sum(1 for x in os.listdir(folder) if x.endswith(ends) and not x.startswith("."))
        except OSError:
            pass
        return n
    return {"cards": count(os.path.join(MEM, "cards"), ".json"), "read_through_pages": count(MEM, ".md"),
            "wiki_pages": count(os.path.join(MEM, "wiki"), ".md", deep=True), "voice_guides": count(os.path.join(MEM, "voice"), ".md")}


def status():
    over = _file()["overrides"]
    have = {_key(t) for ts in _pieces().values() for t in ts}
    return {"overridden": bool(over), "overrides": len(over), "in_use": len(have & set(over)),
            "no_longer_in_the_source": len(set(over) - have), "file": FILE if over else "", "built": _built()}


def check():
    """Do the prompts render, for this archive, to exactly what its file says they should? {"ok", "same", "differ": [names]}."""
    import importlib
    expect = _file()["expect"]
    same, differ = 0, []
    for name, want in sorted(expect.items()):
        mod, _, const = name.partition(".")
        try:
            got = _key(repr(getattr(importlib.import_module("ctx." + mod), const)))
        except Exception:
            got = ""
        if got == want:
            same += 1
        else:
            differ.append(name)
    return dict(status(), ok=not differ, same=same, differ=differ)


def drop(yes=False):
    """Stop using the archive's overrides. Without yes nothing changes: it says what would be written again."""
    if not _file()["overrides"]:
        return {"ok": True, "changed": False, "note": "this archive overrides no prompt"}
    b = _built()
    stale = {"wiki_pages": b["wiki_pages"], "read_through_pages": b["read_through_pages"], "voice_guides": b["voice_guides"], "cards_kept_as_they_are": b["cards"]}
    n = sum(v for k, v in stale.items() if k != "cards_kept_as_they_are")
    if not yes:
        return {"ok": False, "changed": False, "would_write_again": stale,
                "ask": "dropping this archive's prompt overrides makes %d built pages stale: the next wiki, read-through and voice builds write them again, on your plan "
                       "(python3 -m ctx wiki --estimate says what the wiki part costs). to go on: python3 -m ctx prompts --drop --yes" % n}
    os.replace(FILE, FILE + ".dropped")     # kept beside it, so the choice can be taken back by renaming it
    reset()
    return {"ok": True, "changed": True, "would_write_again": stale, "kept_as": FILE + ".dropped",
            "note": "the app and any running server take the change when they start again"}


def main(args):
    if args[:1] == ["--drop"]:
        out = drop(yes="--yes" in args[1:])
        print(json.dumps(out, indent=1))
        return 0
    if args == ["--check"]:
        out = check()
        print(json.dumps(out, indent=1))
        return 0 if out["ok"] else 1
    if args and args != ["--status"]:
        print("usage: python3 -m ctx prompts [--status | --check | --drop [--yes]]", file=sys.stderr)
        return 1
    print(json.dumps(status(), indent=1))
    return 0
