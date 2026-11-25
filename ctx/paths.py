import os
HOME = os.path.abspath(os.path.expanduser(os.environ.get("CTX_HOME") or "~/.context/v2"))   # a "~" in CTX_HOME is expanded
DEFAULT = os.path.abspath(os.path.expanduser("~/.context/v2"))      # context's own place, when CTX_HOME names no other
_MADE = [d for d in (os.path.dirname(HOME), HOME) if not os.path.isdir(d)]      # folders that were not there before this process
os.makedirs(HOME, exist_ok=True)
ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # the folder that holds ctx/: a checkout, or inside the app


def env_files():
    """Where settings and keys may be written down: `.env` beside ctx/ in a checkout, and `.env` in the archive folder.
    The installed app's engine sits inside its signed bundle, where nothing may be added, so it has only the second."""
    return [os.path.join(ENGINE, ".env"), os.path.join(HOME, ".env")]


def venv_sites():
    """Folders of extra python packages (telegram's): `.venv` beside ctx/ in a checkout, `venv` in the archive folder."""
    import glob
    return (glob.glob(os.path.join(ENGINE, ".venv", "lib", "python*", "site-packages"))
            + glob.glob(os.path.join(HOME, "venv", "lib", "python*", "site-packages")))


def _leave_nothing():
    """A command that only looked (a listing, --help, a status) must leave no folder behind: when this process made the
    archive folder and put nothing in it but its own marker, the folder goes again as the process ends."""
    for d in reversed(_MADE):
        try:
            inside = os.listdir(d)
            cache = os.path.join(d, "cache")       # counts worked out again whenever they are wanted: not something written
            if d == HOME and not any(n != ".closed" for top, _, names in os.walk(d) for n in names if not (top + os.sep).startswith(cache + os.sep)):       # its marker, its cache and empty folders only
                for top, dirs, names in os.walk(d, topdown=False):
                    for n in names:
                        os.remove(os.path.join(top, n))
                    if top != d:
                        os.rmdir(top)
                inside = []
            if not inside:
                os.rmdir(d)
        except OSError:
            return


def read_text(path, *mode, **how):
    """All of a file, closed again."""
    with open(path, *mode, **how) as f:
        return f.read()


def read_json(path, **how):
    import json
    with open(path, **how) as f:
        return json.load(f)


def read_lines(path, **how):
    """A file's lines as a list, closed again."""
    with open(path, **how) as f:
        return f.readlines()


def write_text(path, text):
    with open(path, "w") as f:
        f.write(text)


import atexit
atexit.register(_leave_nothing)
from . import guard
guard.system_first()  # osascript, ps, git and the like are macos's own, never a same-named file in a folder anyone can write
# what this process writes is for the owner only. the archive marker goes only into a folder made here, found empty, or
# the default place; a folder CTX_HOME names that holds someone else's files is not ours: no mode in it changes (guard.claim)
OURS = guard.lock(HOME, made=HOME in _MADE, default=HOME == DEFAULT)
MESSAGES = os.path.join(HOME, "messages.jsonl")   # one line per human-typed chat message
SESSIONS = os.path.join(HOME, "sessions.jsonl")   # one line per AI agent session
PROMPTS = os.path.join(HOME, "prompts.jsonl")     # everything the owner typed to an AI agent
MAIL_INDEX = os.path.join(HOME, "mail_index.jsonl") # sender + subject of mail from strangers and lists
DOCS = os.path.join(HOME, "docs.jsonl")           # notes, bookmarks
LOOPS = os.path.join(HOME, "loops.json")
LOOPS_MD = os.path.join(HOME, "loops.md")
SCORES = os.path.join(HOME, "scores.jsonl")
LEDGER = os.path.join(HOME, "ledger.jsonl")
PROFILE_DIR = os.path.join(os.path.dirname(HOME), "derived", "profile")
