"""Pictures, screenshots, voice notes, videos and files on this Mac, turned into rows. Read here, kept here: no network,
no model call, no download. The reading is done by app/tools/media.swift with Apple's own frameworks (Vision for the
words and the labels of a picture, PDFKit for a pdf, the on-device speech models for audio) and by textutil for documents.

  python3 -m ctx media --estimate [--json]     how many files of each kind, where, what is blocked, and how long the
                                               first pass would take, timed on a few files (read for the timing only: nothing of them is kept)
  python3 -m ctx media --scan [--kind images|audio|files|video] [--limit N] [--minutes M] [--recent DAYS] [--retry]
                                               read what is not read yet, newest first; safe to stop and run again
                                               (--spread with --limit: a sample across the years; --fast: full priority)
  python3 -m ctx media --status [--json]       what is read, what is left, what is blocked
  python3 -m ctx media --leave-out <folder>    never read anything under this folder (--take-in <folder> undoes it)
  python3 -m ctx media --folder <folder>       also read this folder (--drop-folder <folder> undoes it)
  python3 -m ctx media --set key=value         speech_locale, max_chars, ocr_pages, tick_seconds, telegram_cache (on|off),
                                               icloud_files (on|off: may macos download a file kept in icloud so it can be read)

Where it looks: the folders in media.json (Desktop, Documents and Downloads to start), WhatsApp's media, iMessage
attachments, Voice Memos, Apple Notes attachments and the Photos library. A place macOS keeps this process out of is
reported as "blocked: needs full disk access" and the rest goes on.

How it stays cheap: every file is remembered by its path, size and time of change in CTX_HOME/media/done.jsonl, one
line appended as each file is read, so a stopped run loses nothing and a file is read once. One file at a time, at low
priority; it stops by itself when the Mac is on battery under 30%.

The four sources (media_images, media_audio, media_files, media_video) hand the remembered rows to the collector and,
once the owner has started the first pass, take a short turn at files from the last 30 days on every 15-minute read
(tick_seconds between them, 30 by default; 0 switches it off). The first pass over everything only ever starts from
--scan.

A video is not transcribed: its row holds the date, the length and the conversation it was sent in.
"""
import glob, hashlib, json, os, queue, re, shutil, subprocess, sys, tempfile, threading, time
from . import paths
from .scrub import R, scrub

H = os.path.expanduser
DIR = os.path.join(paths.HOME, "media")
DONE = os.path.join(DIR, "done.jsonl")
CONFIG = os.path.join(paths.HOME, "media.json")
BIN = os.path.join(paths.HOME, "bin", "media")
_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "tools")
SOURCES = [os.path.join(_TOOLS, "media.swift"), os.path.join(_TOOLS, "media_speech.swift")]
APPLE = 978307200
BLOCKED = "blocked: needs full disk access"

WA_DIR = H("~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared")
IM_DB = H("~/Library/Messages/chat.db")
VOICE_MEMOS = H("~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings")
NOTES_MEDIA = H("~/Library/Group Containers/group.com.apple.notes/Accounts")
PHOTOS = H("~/Pictures/Photos Library.photoslibrary")
TELEGRAM = H("~/Library/Group Containers/6N38VWS5BX.ru.keepcoder.Telegram/appstore")

IMAGE = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".tiff", ".tif", ".bmp", ".webp"}
VIDEO = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp"}
AUDIO = {".opus", ".m4a", ".mp3", ".wav", ".aac", ".caf", ".ogg", ".oga", ".amr", ".flac", ".aiff", ".aif", ".qta"}
PDF = {".pdf"}
TEXTUTIL = {".doc", ".docx", ".rtf", ".rtfd", ".odt", ".webarchive"}        # what macOS turns to text by itself
PLAIN = {".txt", ".md", ".markdown"}
UNREAD = {".pages", ".key", ".numbers", ".xlsx", ".xls", ".pptx", ".ppt", ".epub", ".csv"}     # counted, not read
KINDS = ("image", "audio", "file", "video")
ASKED = {"images": "image", "image": "image", "audio": "audio", "files": "file", "file": "file", "video": "video", "videos": "video"}
SRC = {"image": "image", "audio": "voice_note", "file": "file", "video": "video"}
PREFIX = {"image": "MI", "audio": "MA", "file": "MF", "video": "MV"}
PART = {"image": "media_images", "audio": "media_audio", "file": "media_files", "video": "media_video"}

# a folder that holds one of these is somebody's code, not the owner's papers (or an obsidian vault, which is a source
# of its own): nothing under it is read
REPO = {".git", ".obsidian", "package.json", "node_modules", "Cargo.toml", "go.mod", "pyproject.toml", "setup.py", "Package.swift", "Gemfile",
        "pom.xml", "build.gradle", "tsconfig.json", "requirements.txt", "composer.json", "CMakeLists.txt", "foundry.toml", "hardhat.config.js"}
SKIP_DIRS = {"node_modules", "__pycache__", "venv", "env", "site-packages", "Pods", "DerivedData", "Caches", "cache", "build", "dist",
             "target", "vendor", "Library", "Applications", "System", "fonts", "Fonts"}
SKIP_ENDS = (".app", ".framework", ".bundle", ".xcodeproj", ".xcworkspace", ".photoslibrary", ".pkg", ".plugin", ".kext", ".lproj",
             ".xcassets", ".iconset", ".imageset", ".musiclibrary", ".tvlibrary", ".sparsebundle", ".dSYM")
MAC_OWN = None          # no fixed language: the one this archive's voice notes were first read in, else the mac's own (config())
DEFAULTS = {"folders": ["~/Desktop", "~/Documents", "~/Downloads"], "leave_out": [], "speech_locale": MAC_OWN, "max_chars": 20000,
            "ocr_pages": 8, "tick_seconds": 30, "telegram_cache": "off", "icloud_files": "off"}
BIG = {"image": 80 << 20, "audio": 400 << 20, "file": 200 << 20, "video": 1 << 62}
TICK_DAYS = 30
DATALESS = 0x40000000       # the file's words are in icloud and only its name is here: opening it makes macos download it
LOW_BATTERY = 30
MIN_SPEECH = 0.5          # below this the recogniser was guessing: a voice note in a language it has no model for


# ---------------------------------------------------------------- settings

USED = os.path.join(DIR, "speech_locale")      # the language this archive's voice notes were first read in, written then


NO_LANGUAGE = "en-US"   # what speech is told when neither the mac nor LANG names a language. never a default for anyone who has one


def system_locale():
    """The language this mac is set to, as speech wants it (a tag such as "pt-BR"). The mac's own setting, then LANG;
    NO_LANGUAGE only when the mac names none at all, since the speech framework must be given some tag."""
    seen = ""
    try:
        seen = subprocess.run(["defaults", "read", "-g", "AppleLocale"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    for raw in (seen, os.environ.get("LANG", "")):
        m = re.match(r"([A-Za-z]{2,3})[_-]([A-Za-z]{2})\b", raw.split("@")[0].split(".")[0])
        if m:
            return "%s-%s" % (m.group(1).lower(), m.group(2).upper())
    return NO_LANGUAGE


def _used():
    try:
        with open(USED) as f:
            v = f.read().strip()
        return v if re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", v) else ""
    except OSError:
        return ""


def _keep_locale(locale):
    """Write down, once, the language the first voice note was read in."""
    if locale and not os.path.exists(USED):
        try:
            os.makedirs(os.path.dirname(USED), exist_ok=True)
            with open(USED, "w") as f:
                f.write(str(locale) + "\n")
        except OSError:
            pass


def config():
    """The media settings in force: the defaults, then whatever valid values media.json holds. Never raises.
    speech_locale, when the owner has not set one, is the language this archive's voice notes were first read in
    (kept with the archive, so a mac whose language changes does not split them), else the mac's own language."""
    out = json.loads(json.dumps(DEFAULTS))
    out["speech_locale"] = _used() or system_locale()
    try:
        with open(CONFIG) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return out
    for k, v in saved.items() if isinstance(saved, dict) else []:
        if k in ("folders", "leave_out") and isinstance(v, list) and all(isinstance(x, str) for x in v):
            out[k] = v
        elif k in ("max_chars", "ocr_pages", "tick_seconds") and isinstance(v, int) and 0 <= v <= 1000000:
            out[k] = v
        elif k == "speech_locale" and isinstance(v, str) and re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", v):
            out[k] = v
        elif k in ("telegram_cache", "icloud_files") and v in ("on", "off"):
            out[k] = v
    return out


def save_config(cfg):
    tmp = "%s.new.%d" % (CONFIG, os.getpid())
    with open(tmp, "w") as f:
        json.dump({k: cfg[k] for k in DEFAULTS}, f, indent=1)
    os.replace(tmp, CONFIG)


def _full(p):
    return os.path.abspath(H(p))


def _short(p):
    """A path as the owner would write it: ~/Desktop, not /Users/name/Desktop."""
    home = H("~")
    return "~" + p[len(home):] if p == home or p.startswith(home + os.sep) else p


def left_out(path, cfg):
    return any(path == d or path.startswith(d + os.sep) for d in (_full(x) for x in cfg["leave_out"]))


# ---------------------------------------------------------------- the helper

def helper():
    """Path of the compiled media helper, or "" when it cannot be built on this Mac (no swift compiler). Compiled once
    into CTX_HOME/bin, and again when a source is newer; if that fails, the copy already there serves."""
    have = BIN if os.path.exists(BIN) else ""
    try:
        if not all(os.path.exists(s) for s in SOURCES):
            return have
        if have and os.path.getmtime(BIN) >= max(os.path.getmtime(s) for s in SOURCES):
            return BIN
        if not shutil.which("swiftc"):
            return have
        if subprocess.run(["xcode-select", "-p"], capture_output=True).returncode != 0:    # swiftc is a stub that opens an install window
            return have
        os.makedirs(os.path.dirname(BIN), exist_ok=True)
        tmp = "%s.%d.%d.new" % (BIN, os.getpid(), threading.get_ident())
        r = subprocess.run(["swiftc", "-O", "-parse-as-library"] + SOURCES + ["-o", tmp], capture_output=True, timeout=900)
        if r.returncode != 0 or not os.path.exists(tmp):
            return have
        os.replace(tmp, BIN)
        return BIN
    except (OSError, subprocess.SubprocessError):
        return have


def info():
    """What the helper can do here: the languages text recognition knows and what speech can do. {} with no helper."""
    h = helper()
    if not h:
        return {}
    try:
        r = subprocess.run([h, "info"], capture_output=True, timeout=120)
        return json.loads(r.stdout.decode("utf-8", "replace").strip().splitlines()[-1]) if r.returncode == 0 else {}
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return {}


def speech(cfg=None, about=None):
    """(can audio be transcribed by this process, the locale to use, a plain reason when it cannot)."""
    cfg, about = cfg or config(), info() if about is None else about
    sp = about.get("speech") or {}
    want = cfg.get("speech_locale") or system_locale()
    if not about:
        return False, want, "no swift compiler on this mac, so the reader could not be built"
    if sp.get("modern"):
        have = sp.get("installed") or []
        if want in have:
            return True, want, ""
        same = [x for x in have if x.split("-")[0] == want.split("-")[0]]
        if same:
            return True, same[0], ""
        return False, want, "the speech model for %s is not installed on this mac (system settings > keyboard > dictation adds a language)" % want
    if sp.get("permission") == "granted" and (sp.get("on_device") or {}).get(want):
        return True, want, ""
    return False, want, "before macos 26 speech recognition needs a permission only the app can ask for"


class Tool:
    """The helper, kept running: one file in, one json line out. A file that takes too long is given up on and the
    helper started again, so one bad file never stops a run."""

    def __init__(self, cfg=None, gentle=True):
        self.cfg, self.gentle, self.p, self.q = cfg or config(), gentle, None, None

    def _start(self):
        h = helper()
        if not h:
            raise FileNotFoundError("no swift compiler on this mac, so the media reader could not be built (xcode-select --install)")
        args = [h, "read", "--max-chars", str(self.cfg["max_chars"]), "--ocr-pages", str(self.cfg["ocr_pages"]), "--locale", self.cfg.get("speech_locale") or system_locale()]
        if self.gentle and os.path.exists("/usr/sbin/taskpolicy"):
            args = ["/usr/sbin/taskpolicy", "-c", "utility"] + args        # below anything the owner is doing
        self.p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.q = queue.Queue()

        def pump(p, q):
            for line in p.stdout:
                q.put(line)
            q.put(None)
        threading.Thread(target=pump, args=(self.p, self.q), daemon=True).start()

    def ask(self, kind, path, timeout=180, **more):
        if self.p is None or self.p.poll() is not None:
            self._start()
        try:
            self.p.stdin.write((json.dumps(dict(more, kind=kind, path=path)) + "\n").encode("utf-8", "surrogateescape"))
            self.p.stdin.flush()
            line = self.q.get(timeout=timeout)
        except queue.Empty:
            self.close()
            return {"ok": False, "why": "took too long"}
        except (OSError, ValueError):
            self.close()
            return {"ok": False, "why": "the reader stopped"}
        if line is None:
            self.close()
            return {"ok": False, "why": "the reader stopped on this file"}
        try:
            d = json.loads(line)
            return d if isinstance(d, dict) else {"ok": False, "why": "unreadable answer"}
        except ValueError:
            return {"ok": False, "why": "unreadable answer"}

    def close(self):
        if self.p is not None:
            try:
                self.p.kill()
                self.p.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass
            for pipe in (self.p.stdin, self.p.stdout):
                try:
                    pipe.close()
                except (OSError, ValueError):
                    pass
        self.p = None


# ---------------------------------------------------------------- where the files are

def kind_of(path):
    """(kind, what it is called) for a file name, or (None, a reason word) for one that is not read."""
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE:
        return "image", "picture"
    if ext in VIDEO:
        return "video", "video"
    if ext in AUDIO:
        return "audio", "audio"
    if ext in PDF:
        return "file", "pdf"
    if ext in TEXTUTIL or ext in PLAIN:
        return "file", "document"
    if ext in UNREAD:
        return None, "unread"
    return None, ""


def _sniff(path):
    """The kind of a file with no extension (telegram's cache), from its first bytes."""
    try:
        with open(path, "rb") as f:
            b = f.read(16)
    except OSError:
        return None, ""
    if b[:3] == b"\xff\xd8\xff" or b[:8] == b"\x89PNG\r\n\x1a\n" or b[:4] == b"GIF8" or (b[:4] == b"RIFF" and b[8:12] == b"WEBP"):
        return "image", "picture"
    if b[4:8] == b"ftyp":
        return ("audio", "audio") if b[8:11] == b"M4A" else ("video", "video")
    if b[:4] == b"OggS" or b[:3] == b"ID3":
        return "audio", "audio"
    if b[:4] == b"%PDF":
        return "file", "pdf"
    return None, ""


class Blocked(Exception):
    pass


def here(items, cfg):
    """The files whose contents are on this Mac. One kept in iCloud (Desktop and Documents with "optimise storage" on)
    is left alone unless icloud_files is on: reading it would make macOS fetch it over the network and keep a copy."""
    return items if cfg.get("icloud_files") == "on" else [it for it in items if not it.get("cloud")]


def _item(path, kind, what, place, st, **more):
    d = {"path": path, "kind": kind, "what": what, "place": place, "size": st.st_size, "mtime": int(st.st_mtime), "ts": st.st_mtime}
    if getattr(st, "st_flags", 0) & DATALESS:
        d["cloud"] = 1
    d.update({k: v for k, v in more.items() if v not in ("", None)})
    return d


def _listdir(path):
    try:
        return os.listdir(path)
    except FileNotFoundError:
        return None
    except (PermissionError, OSError):
        raise Blocked(BLOCKED)


def _walk(root, place, cfg, counts=None, shots=()):
    """Every file under root the rules let through. Code, app bundles, caches and hidden folders are not entered."""
    root = _full(root)
    if _listdir(root) is None:
        return
    for folder, dirs, files in os.walk(root):
        if folder != root and (REPO & set(files) or REPO & set(dirs)):
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS and not d.endswith(SKIP_ENDS)
                         and not left_out(os.path.join(folder, d), cfg))
        if left_out(folder, cfg):
            dirs[:] = []
            continue
        for name in files:
            if name.startswith("."):
                continue
            kind, what = kind_of(name)
            if kind is None:
                if what and counts is not None:
                    counts[what] = counts.get(what, 0) + 1
                continue
            p = os.path.join(folder, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if kind == "image" and st.st_size < 12000:          # icons and thumbnails
                continue
            shot = p in shots or bool(re.match(r"(?i)(screenshot|screen shot|screen recording|cleanshot|simulator screenshot)", name))
            yield _item(p, kind, "screenshot" if shot and kind == "image" else "screen recording" if shot and kind == "video" else what,
                        place, st, who="me" if shot else "", name=name)


def folders(cfg, counts=None):
    shots = screenshots()
    for f in cfg["folders"]:
        full = _full(f)
        lib = H("~/Library")
        if full == lib or full.startswith(lib + os.sep) or left_out(full, cfg):
            continue
        for it in _walk(full, os.path.basename(full).lower() or full, cfg, counts, shots):
            yield it


_shots = None


def screenshots():
    """Paths Spotlight marks as screen captures. Empty when Spotlight does not answer."""
    global _shots
    if _shots is None:
        try:
            r = subprocess.run(["mdfind", "kMDItemIsScreenCapture == 1"], capture_output=True, timeout=30)
            _shots = set(r.stdout.decode("utf-8", "surrogateescape").splitlines()) if r.returncode == 0 else set()
        except (OSError, subprocess.SubprocessError):
            _shots = set()
    return _shots


def _ro(path):
    """A read-only connection, or Blocked. A database that is not there is None."""
    import sqlite3
    try:
        os.stat(path)
    except FileNotFoundError:
        return None
    except (PermissionError, OSError):
        raise Blocked(BLOCKED)
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path.replace("?", "%3f").replace("#", "%23"), uri=True)
    except sqlite3.Error:
        raise Blocked(BLOCKED)
    try:
        con.execute("select 1 from sqlite_master limit 1").fetchall()
        return con
    except sqlite3.Error:
        con.close()
        raise Blocked(BLOCKED)


def whatsapp(cfg, counts=None):
    """What was sent and received in WhatsApp, each file tied to the conversation it was sent in."""
    import sqlite3
    con = _ro(os.path.join(WA_DIR, "ChatStorage.sqlite"))
    if con is None:
        return
    try:
        chats = {pk: (name, stype) for pk, name, stype in con.execute("select Z_PK, ZPARTNERNAME, ZSESSIONTYPE from ZWACHATSESSION")}
        rows = con.execute("""select i.ZMEDIALOCALPATH, m.ZMESSAGEDATE, m.ZISFROMME, m.ZCHATSESSION from ZWAMEDIAITEM i
                              join ZWAMESSAGE m on m.Z_PK = i.ZMESSAGE where i.ZMEDIALOCALPATH is not null""").fetchall()
    except sqlite3.Error:
        raise Blocked("whatsapp's database is in a form this version does not read")
    finally:
        con.close()
    for rel, ts, me, spk in rows:
        name, stype = chats.get(spk, ("?", 0))
        if stype not in (0, 1):             # status updates and broadcasts are not conversations
            continue
        ext = os.path.splitext(rel)[1].lower()
        if ext == ".webp":                  # stickers
            continue
        kind, what = kind_of(rel)
        if kind is None:
            if what and counts is not None:
                counts[what] = counts.get(what, 0) + 1
            continue
        p = os.path.join(WA_DIR, "Message", rel)
        try:
            st = os.stat(p)
        except OSError:
            continue
        it = _item(p, kind, "voice note" if ext == ".opus" else what, "whatsapp", st, who="me" if me else "them", thread_id="wa%s" % spk,
                   thread=name or "?", chat="group" if stype == 1 else "dm", name=os.path.basename(rel) if kind == "file" else "")
        if ts:
            it["ts"] = ts + APPLE
        yield it


def imessage(cfg, counts=None):
    """iMessage attachments, each tied to its conversation."""
    import sqlite3
    con = _ro(IM_DB)
    if con is None:
        return
    try:
        rows = con.execute("""select a.filename, a.transfer_name, m.date, m.is_from_me, c.ROWID, coalesce(nullif(c.display_name,''), c.chat_identifier), c.style
                              from attachment a join message_attachment_join x on x.attachment_id = a.ROWID
                              join message m on m.ROWID = x.message_id join chat_message_join j on j.message_id = m.ROWID
                              join chat c on c.ROWID = j.chat_id where a.filename is not null""").fetchall()
    except sqlite3.Error:
        raise Blocked("imessage's database is in a form this version does not read")
    finally:
        con.close()
    denied = seen = 0
    for filename, shown, ts, me, cid, name, style in rows:
        kind, what = kind_of(filename)
        if kind is None:
            if what and counts is not None:
                counts[what] = counts.get(what, 0) + 1
            continue
        p = _full(filename)
        seen += 1
        try:
            st = os.stat(p)
        except PermissionError:
            denied += 1
            continue
        except OSError:
            continue                        # in icloud, not on this mac
        ext = os.path.splitext(p)[1].lower()
        it = _item(p, kind, "voice note" if ext in (".caf", ".amr") else what, "imessage", st, who="me" if me else "them", thread_id="im%s" % cid,
                   thread=name or "?", chat="group" if style == 43 else "dm", name=(shown or "") if kind == "file" else "")
        if ts:
            it["ts"] = ts / 1e9 + APPLE
        yield it
    if denied and denied == seen:
        raise Blocked(BLOCKED)


def voice_memos(cfg, counts=None):
    names = _listdir(VOICE_MEMOS)
    for name in sorted(names or []):
        p = os.path.join(VOICE_MEMOS, name)
        if kind_of(name)[0] != "audio":
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        yield _item(p, "audio", "voice memo", "voice memos", st, who="me", name=os.path.splitext(name)[0])


def notes(cfg, counts=None):
    """Files kept inside Apple Notes."""
    if _listdir(NOTES_MEDIA) is None:
        return
    for acc in sorted(glob.glob(os.path.join(glob.escape(NOTES_MEDIA), "*", "Media"))):
        for folder, dirs, files in os.walk(acc):
            for name in files:
                kind, what = kind_of(name)
                if kind is None:
                    continue
                p = os.path.join(folder, name)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                yield _item(p, kind, what, "apple notes", st, who="me", name=name if kind == "file" else "")


def photos(cfg, counts=None):
    """The Photos library, read through its own database: the originals that are on this Mac. Never copied."""
    import sqlite3
    if left_out(PHOTOS, cfg):
        return
    con = _ro(os.path.join(PHOTOS, "database", "Photos.sqlite"))
    if con is None:
        return
    try:
        cols = {r[1] for r in con.execute("pragma table_info(ZASSET)")}
        if not {"ZDIRECTORY", "ZFILENAME", "ZKIND"} <= cols:
            raise Blocked("the photos library is in a form this version does not read")
        shot = "ZISDETECTEDSCREENSHOT" if "ZISDETECTEDSCREENSHOT" in cols else "0"
        when = "ZDATECREATED" if "ZDATECREATED" in cols else "null"
        live = " where coalesce(ZTRASHEDSTATE, 0) = 0" if "ZTRASHEDSTATE" in cols else ""
        rows = con.execute("select ZDIRECTORY, ZFILENAME, ZKIND, %s, %s from ZASSET%s" % (when, shot, live)).fetchall()
    except sqlite3.Error:
        raise Blocked(BLOCKED)
    finally:
        con.close()
    away = 0
    for folder, name, zkind, ts, is_shot in rows:
        if not folder or not name:
            continue
        kind, what = kind_of(name)
        if kind not in ("image", "video"):
            continue
        p = os.path.join(PHOTOS, "originals", folder, name)
        try:
            st = os.stat(p)
        except PermissionError:
            raise Blocked(BLOCKED)
        except OSError:
            away += 1                       # kept in icloud, not on this mac
            continue
        it = _item(p, kind, "screenshot" if is_shot and kind == "image" else "photo" if kind == "image" else what, "photos", st,
                   who="me" if is_shot else "")
        if ts is not None:
            it["ts"] = ts + APPLE
        yield it
    if counts is not None and away:
        counts["in icloud, not on this mac"] = counts.get("in icloud, not on this mac", 0) + away


def telegram_cache(cfg, counts=None):
    """Telegram keeps what it showed in a cache with no names and no link to a conversation. Counted always; read only
    when telegram_cache is on, because most of it is other people's channels, stickers and profile pictures."""
    if _listdir(TELEGRAM) is None:
        return
    for d in sorted(glob.glob(os.path.join(glob.escape(TELEGRAM), "account-*", "postbox", "media"))):
        for name in _listdir(d) or []:
            if name.endswith(".meta"):
                continue
            p = os.path.join(d, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if st.st_size < 12000 or not os.path.isfile(p):
                continue
            kind, what = kind_of(name)
            if kind is None:
                kind, what = _sniff(p)
            if kind:
                yield _item(p, kind, what, "telegram cache", st)


PLACES = [("folders", folders), ("whatsapp", whatsapp), ("imessage", imessage), ("voice memos", voice_memos), ("apple notes", notes),
          ("photos", photos), ("telegram cache", telegram_cache)]


def listing(cfg=None, kinds=None, every=False):
    """(files that can be read, {place: why it is blocked}, {what is counted but not read: n}). A place that is blocked
    is named and the rest goes on. `every` also lists telegram's cache when it is switched off (for the count)."""
    cfg = cfg or config()
    items, blocked, counts, seen = [], {}, {}, set()
    for place, fn in PLACES:
        if place == "telegram cache" and cfg["telegram_cache"] != "on" and not every:
            continue
        got = []
        try:
            for it in fn(cfg, counts):
                got.append(it)
        except Blocked as e:
            blocked[place] = str(e)
        except Exception as e:              # a place in a shape nobody expected must not stop the others
            blocked[place] = "could not be listed (%s)" % type(e).__name__
        for it in got:
            if it["path"] in seen or left_out(it["path"], cfg) or (kinds and it["kind"] not in kinds):
                continue
            seen.add(it["path"])
            items.append(it)
    return items, blocked, counts


# ---------------------------------------------------------------- what is already read

def key(it):
    return hashlib.sha1(("%s\x1f%s\x1f%s" % (it["path"], it["size"], it["mtime"])).encode("utf-8", "surrogateescape")).hexdigest()[:16]


def done():
    """{key: the line saved for that file}. A half-written last line (a stopped run) is passed over."""
    out = {}
    try:
        with open(DONE, "rb") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    out[d["k"]] = d
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        pass
    return out


def _remember(f, rec):
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    f.flush()


def content_id(path, size):
    """A number for what the file holds, so the same picture in two folders is one row and a re-download changes nothing."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        if size <= 64 << 20:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        else:                               # a long video: its two ends and its size say enough
            h.update(f.read(4 << 20))
            f.seek(max(0, size - (4 << 20)))
            h.update(f.read(4 << 20))
            h.update(str(size).encode())
    return h.hexdigest()[:14]


# ---------------------------------------------------------------- secrets in text read off a picture or a page
# the same secrets as in a message, laid out in a grid or broken across lines. scrub() judges a line; these join the lines first.
_GROUPS = re.compile(r"\d+(?:(?:[ \t\-•·]{1,3}|[ \t]*\n[ \t]*)\d+)+")
_CELL = r"(?:\d{1,2}[.):]?[ \t]*)?(?:[A-Z][a-z]{2,7}|[a-z]{3,8}|[A-Z]{3,8})"       # one word of a phrase, numbered or not
_GRID_LINE = re.compile(r"[ \t]*(?:(?:%s|\d{1,2}[.):]?)[ \t,|]*){1,8}" % _CELL)


def _cards(m):
    """A card number broken into groups over spaces, dots or lines: any stretch of whole groups of four or more digits
    that adds up to 13 to 19 digits, starts like a card and passes the check digit goes. The digits around it stay."""
    run = m.group(0)
    groups = [(g.start(), g.end()) for g in re.finditer(r"\d+", run)][:60]
    out, last, i = [], 0, 0
    while i < len(groups):
        hit = None
        for j in range(i + 1, len(groups)):         # two groups or more: a number in one piece is scrub()'s own rule
            d = [int(c) for c in run[groups[i][0]:groups[j][1]] if c.isdigit()]
            if len(d) > 19 or groups[j - 1][1] - groups[j - 1][0] < 4:      # a card is printed in fours (the last group may be three):
                break                                                       # line numbers and columns of small sums are not one
            if groups[j][1] - groups[j][0] < 3:
                continue
            if len(d) >= 13 and d[0] in (2, 3, 4, 5, 6, 8) and (sum(d[-1::-2]) + sum(sum(divmod(2 * x, 10)) for x in d[-2::-2])) % 10 == 0:
                hit = j
        if hit is None:
            i += 1
            continue
        out.append(run[last:groups[i][0]] + R)
        last, i = groups[hit][1], hit + 1
    return "".join(out) + run[last:]


def _grids(text):
    """A seed phrase as a wallet shows it: a few words to a line, numbered or not, the numbers sometimes on lines of their
    own. Lines of that shape are joined into one run of words and given to scrub(), which judges a phrase on one line."""
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        j = i
        while j < len(lines) and j - i < 80 and (_GRID_LINE.fullmatch(lines[j]) or (j > i and not lines[j].strip())):
            j += 1
        if j - i >= 2:
            flat = " ".join(re.findall(r"[A-Za-z]+", " ".join(lines[i:j])))
            if len(flat.split()) >= 12:
                judged = scrub(flat)
                if R in judged:
                    out.append(judged)
                    i = j
                    continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def scrub_layout(text):
    """scrub() for text that came off a picture, a pdf page or a recording, where a line break or a wide gap can fall
    inside a secret. A picture of a passport or a bank statement is not a special case: the numbers in it meet the
    same rules as the numbers in a message."""
    if not text:
        return text
    return scrub(_GROUPS.sub(_cards, _grids(text)))


# ---------------------------------------------------------------- one file into one row

def useful(text):
    """Is this enough real text to be worth a row? A logo, a clock or two stray words are not."""
    words = re.findall(r"[^\W\d_]{2,}", text or "", re.UNICODE)
    return len(words) >= 4 and sum(len(w) for w in words) >= 16


def _length(secs):
    secs = int(round(secs or 0))
    return "%d:%02d" % (secs // 60, secs % 60) if secs < 3600 else "%d:%02d:%02d" % (secs // 3600, secs % 3600 // 60, secs % 60)


def title(it, what=None, tail=""):
    """How an answer can name this file: "screenshot you sent <conversation>", or the file's own name and where it lies."""
    what, name = what or it["what"], it.get("name") or ""
    if it.get("thread_id"):
        if it.get("who") == "me":
            where = "you sent %s" % it["thread"]
        elif it.get("chat") == "group":
            where = "sent in %s" % it["thread"]
        else:
            where = "%s sent you" % it["thread"]
    else:
        place = it["place"]
        where = {"desktop": "on the desktop", "photos": "in the photos library", "voice memos": "in voice memos",
                 "apple notes": "in apple notes", "telegram cache": "from telegram"}.get(place, "in %s" % place)
    tail = (", " + tail) if tail else ""
    return ("%s (%s %s%s)" % (name, what, where, tail)) if name else "%s %s%s" % (what, where, tail)


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _row(it, kind, text, **more):
    row = {"id": "", "src": SRC[kind], "ts": _iso(it["ts"]), "title": scrub(title(it, more.pop("what", None), more.pop("tail", ""))), "text": scrub_layout(text),
           "url": "file://" + it["path"], "place": it["place"]}
    for k in ("who", "thread_id", "thread"):
        if it.get(k):
            row[k] = it[k]
    if it.get("chat"):
        row["kind"] = it["chat"]
    row.update({k: v for k, v in more.items() if v not in ("", None, [], 0)})
    return row


def _textutil(path, most):
    r = subprocess.run(["textutil", "-convert", "txt", "-stdout", "--", path], capture_output=True, timeout=120)
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace")


def _capped(text, most, full=None):
    """The first `most` characters, and a last line saying how long the whole thing is."""
    text = (text or "").strip()
    full = max(full or 0, len(text))
    if full <= most:
        return text
    return text[:most].rstrip() + "\n[the first %s of %s characters]" % (format(most, ","), format(full, ","))


def mp4_seconds(path):
    """How long an mp4 or mov runs, from its own header (the mvhd box). 0 when it is not one or says nothing."""
    try:
        with open(path, "rb") as f:
            end = os.fstat(f.fileno()).st_size

            def boxes(start, stop):
                at = start
                while at + 8 <= stop:
                    f.seek(at)
                    head = f.read(16)
                    size, name = int.from_bytes(head[:4], "big"), head[4:8]
                    hdr = 8
                    if size == 1:
                        size, hdr = int.from_bytes(head[8:16], "big"), 16
                    elif size == 0:
                        size = stop - at
                    if size < hdr:
                        return
                    yield name, at + hdr, min(at + size, stop)
                    at += size
            for name, a, b in boxes(0, end):
                if name != b"moov":
                    continue
                for inner, c, d in boxes(a, b):
                    if inner == b"mvhd":
                        f.seek(c)
                        body = f.read(32)
                        scale, ticks = (int.from_bytes(body[20:24], "big"), int.from_bytes(body[24:32], "big")) if body[:1] == b"\x01" else \
                            (int.from_bytes(body[12:16], "big"), int.from_bytes(body[16:20], "big"))
                        return round(ticks / scale, 1) if scale and ticks < 1 << 40 else 0
    except (OSError, ValueError):
        pass
    return 0


def read_one(it, tool, cfg, can_speak=None):
    """Read one file. Returns the line to remember: {"row": {...}} when it made a row, else {"why": reason}."""
    kind, path, t0 = it["kind"], it["path"], time.time()
    rec = {"k": key(it), "p": path, "kind": kind, "at": int(t0)}

    def no(why):
        rec.update(why=why, secs=round(time.time() - t0, 3))
        return rec
    if it["size"] > BIG[kind]:
        return no("too large")
    if it["size"] == 0:
        return no("empty")
    row = None
    if kind == "image":
        d = tool.ask("image", path, timeout=180)
        if not d.get("ok"):
            return no(d.get("why") or "could not be read")
        text = (d.get("text") or "").strip()
        labels = [str(x[0]) for x in d.get("labels") or [] if isinstance(x, list) and x]
        what = "screenshot" if it["what"] == "picture" and "screenshot" in labels else it["what"]
        if useful(text):
            row = _row(it, kind, _capped(text, cfg["max_chars"]), what=what, labels=labels, media=what)
        elif labels and not d.get("tiny"):
            said = (" the words on it: %s." % " ".join(text.split())) if text else ""
            row = _row(it, kind, "a %s of: %s.%s" % ("screenshot" if what == "screenshot" else "picture", ", ".join(labels), said),
                       what=what, labels=labels, media=what, light=1)
        else:
            return no("no text and nothing recognised in it")
    elif kind == "file":
        ext = os.path.splitext(path)[1].lower()
        if ext in PDF:
            d = tool.ask("pdf", path, timeout=600)
            if not d.get("ok"):
                return no(d.get("why") or "could not be read")
            text = (d.get("text") or "").strip()
            if not useful(text):
                return no("no text in it")
            row = _row(it, kind, _capped(text, cfg["max_chars"], d.get("chars")), media="pdf", pages=d.get("pages"), chars=d.get("chars"),
                       ocr_pages=d.get("ocr_pages"))
        else:
            try:
                if ext in PLAIN:
                    with open(path, encoding="utf-8", errors="ignore") as f:
                        text = f.read(cfg["max_chars"] * 4 + 1)
                    full = it["size"] if len(text) > cfg["max_chars"] * 4 else len(text)
                else:
                    text = _textutil(path, cfg["max_chars"])
                    full = len(text or "")
            except (OSError, subprocess.SubprocessError):
                return no("could not be read")
            if text is None:
                return no("macos could not turn it to text")
            if not useful(text):
                return no("no text in it")
            row = _row(it, kind, _capped(text, cfg["max_chars"], full), media="document", chars=full)
    elif kind == "audio":
        locale = (can_speak[1] if can_speak else "") or cfg.get("speech_locale") or system_locale()
        d = tool.ask("audio", path, timeout=max(300, it["size"] // 20000), locale=locale)
        if d.get("ok") and (d.get("text") or "").strip():
            _keep_locale(locale)
        secs, text, what = d.get("secs") or 0, (d.get("text") or "").strip() if d.get("ok") else "", it["what"]
        if not d.get("ok") and not secs:
            return no(d.get("why") or "could not be read")
        if useful(text) and (d.get("conf") or 0) >= MIN_SPEECH:
            row = _row(it, kind, _capped(text, cfg["max_chars"]), what=what, tail=_length(secs), media=what, secs=round(secs, 1),
                       conf=round(d.get("conf") or 0, 2), locale=d.get("locale"))
        elif d.get("why") in ("needs permission", "not installed"):
            # not a verdict on the file: it is counted now and transcribed when this mac can
            row = _row(it, kind, "%s, %s long. not transcribed yet." % (what, _length(secs)), what=what, tail=_length(secs), media=what,
                       secs=round(secs, 1), light=1)
            rec["wait"] = 1
        else:               # silence, music, or a language this mac has no model for: still a row, so it can be counted and found
            row = _row(it, kind, "%s, %s long. its words could not be made out on this mac." % (what, _length(secs)), what=what,
                       tail=_length(secs), media=what, secs=round(secs, 1), light=1)
    elif kind == "video":
        secs = mp4_seconds(path)            # the file's own header says how long it is: no decoder is started for it
        if not secs:
            d = tool.ask("video", path, timeout=120)
            if not d.get("ok"):
                return no(d.get("why") or "could not be read")
            secs = d.get("secs") or 0
        row = _row(it, kind, "%s, %s long. videos are not transcribed." % (it["what"], _length(secs)), tail=_length(secs),
                   media=it["what"], secs=secs, light=1)
    try:
        row["id"] = PREFIX[kind] + content_id(path, it["size"])
    except OSError:
        return no("could not be read")
    rec.update(row=row, secs=round(time.time() - t0, 3))
    return rec


# ---------------------------------------------------------------- the run

def battery():
    """(running on battery, percent). A Mac with no battery is (False, 100)."""
    try:
        out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, timeout=10).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return False, 100
    m = re.search(r"(\d+)%", out)
    return "Battery Power" in out, int(m.group(1)) if m else 100


def todo(items, known, retry=False):
    """The files not read yet, newest first. A file that failed is not tried again unless asked; one that only waited
    (audio with no speech model) is."""
    out = []
    for it in items:
        d = known.get(key(it))
        if d is None or d.get("wait") or (retry and "row" not in d):
            out.append(it)
    out.sort(key=lambda it: -it["ts"])
    return out


def scan(kinds=None, limit=None, seconds=None, recent=None, retry=False, say=None, tool=None, cfg=None, gentle=True, lock=True, items=None,
         can_speak=None, spread=False):
    """Read files that are not read yet. Stops at `limit` files, after `seconds`, or when the Mac is on battery under
    30%. Every file is saved as it is read. Returns what happened."""
    from . import collect
    cfg = cfg or config()
    held = collect.take_lock("media_scan") if lock else "none"
    if not held:
        return {"read": 0, "rows": 0, "left": None, "stopped": "another media read is running"}
    t0, n, rows, stopped, own = time.time(), 0, 0, "", tool is None
    began = time.monotonic()            # the limit in seconds counts time awake
    try:
        os.makedirs(DIR, exist_ok=True)
        blocked = {}
        if items is None:
            items, blocked, _ = listing(cfg, kinds)
        elif kinds:
            items = [it for it in items if it["kind"] in kinds]
        if recent:
            items = [it for it in items if it["ts"] >= time.time() - recent * 86400]
        away = len(items)
        items = here(items, cfg)
        away -= len(items)
        known = done()
        work = todo(items, known, retry)
        if spread and limit and len(work) > limit:      # a sample across the years and the places, not just this week's files
            work = [work[int(i * len(work) / limit)] for i in range(limit)]
        if can_speak is None:
            can_speak = speech(cfg) if any(it["kind"] == "audio" for it in work) else (True, "", "")
        if not can_speak[0]:                # audio that is already counted waits for a mac that can transcribe it
            work = [it for it in work if it["kind"] != "audio" or key(it) not in known]
        if work and own:
            if not helper():
                return {"read": 0, "rows": 0, "left": len(work), "stopped": "no swift compiler on this mac, so the media reader could not be built "
                        "(xcode-select --install)", "blocked": blocked, "audio": ""}
            tool = Tool(cfg, gentle)
        with open(DONE, "a") as f:
            try:
                os.chmod(DONE, 0o600)
                with open(DONE, "rb") as end:           # a run that was killed mid-line: start on a line of our own
                    end.seek(max(0, os.path.getsize(DONE) - 1))
                    if end.read(1) not in (b"", b"\n"):
                        f.write("\n")
            except OSError:
                pass
            for it in work:
                if limit is not None and n >= limit:
                    stopped = "limit"
                    break
                if seconds is not None and time.monotonic() - began >= seconds:
                    stopped = "time"
                    break
                if n % 20 == 0:
                    on, pct = battery()
                    if on and pct < LOW_BATTERY:
                        stopped = "on battery under %d%%" % LOW_BATTERY
                        break
                rec = read_one(it, tool, cfg, can_speak)
                _remember(f, rec)
                n += 1
                rows += "row" in rec
                if say:
                    say({"read": n, "of": len(work), "rows": rows, "kind": it["kind"], "secs": round(time.time() - t0, 1)})
        return {"read": n, "rows": rows, "left": len(work) - n, "stopped": stopped, "secs": round(time.time() - t0, 1), "blocked": blocked,
                "audio": "" if can_speak[0] else can_speak[2], "in_icloud": away}
    finally:
        if own and tool is not None:
            tool.close()
        if lock:
            collect.drop_lock(held)


def rows(kind, known=None):
    """The rows to hand the collector for one kind: the newest reading of each file, and one row per content."""
    known = done() if known is None else known
    by_path = {}
    for d in known.values():                # later lines win: a file that changed has a newer reading
        if d.get("kind") == kind:
            by_path[d.get("p")] = d
    out = {}
    for d in by_path.values():
        row = d.get("row")
        if not isinstance(row, dict) or not row.get("id"):
            continue
        had = out.get(row["id"])
        if had is None or (row.get("thread_id") and not had.get("thread_id")) or (bool(row.get("thread_id")) == bool(had.get("thread_id")) and row["ts"] < had["ts"]):
            out[row["id"]] = row            # the copy tied to a conversation is kept; else the earliest
    return sorted(out.values(), key=lambda r: r["ts"])


_memo = [0.0, None]


def _listed(cfg):
    """One listing shared by the four sources when they are read one after another."""
    if _memo[1] is None or time.monotonic() - _memo[0] > 120:
        _memo[0], _memo[1] = time.monotonic(), listing(cfg)[0]
    return _memo[1]


STARTED = os.path.join(DIR, "started")
_turn = [float("-inf"), 0.0]          # when this tick's turn began, and the seconds of it already used


def _budget(cfg):
    """Seconds the four sources may still spend on new files in this 15-minute read: tick_seconds between them."""
    if time.monotonic() - _turn[0] > 600:
        _turn[0], _turn[1] = time.monotonic(), 0.0
    return max(0.0, cfg["tick_seconds"] - _turn[1])


def source(kind):
    """The collector's reader for one kind: a short turn at files from the last 30 days, then every remembered row.
    The turn is only taken once the owner has started the first pass themselves (--scan with no --limit)."""
    def read(days, out):
        from . import collect
        cfg = config()
        left = _budget(cfg) if os.path.exists(STARTED) else 0
        if left > 0:
            t0 = time.monotonic()
            try:
                scan(kinds=[kind], seconds=left, recent=TICK_DAYS, cfg=cfg, items=_listed(cfg))
            except OSError:
                pass
            _turn[1] += time.monotonic() - t0
        got = rows(kind)
        if not got and not os.path.exists(DONE):
            raise FileNotFoundError("not read yet: python3 -m ctx media --estimate says how many files and how long")
        for r in got:
            collect.put(out, dict(r))
        return len(got)
    return read


images, audio, files, video = source("image"), source("audio"), source("file"), source("video")


# ---------------------------------------------------------------- counts, status, estimate

def inventory(cfg=None):
    """How many files of each kind there are, by place, with their size. Counts only."""
    cfg = cfg or config()
    wide = dict(cfg, folders=list(dict.fromkeys(cfg["folders"] + ["~/Pictures", "~/Movies"])))
    items, blocked, counts = listing(wide, every=True)
    table = {}
    for it in items:
        what = "screenshot" if it["what"] == "screenshot" else "voice note" if it["what"] in ("voice note", "voice memo") else \
            "pdf" if it["what"] == "pdf" else "document" if it["kind"] == "file" else it["kind"]
        c = table.setdefault(it["place"], {}).setdefault(what, [0, 0])
        c[0] += 1
        c[1] += it["size"]
    lib = _photos_count()
    cloud = {}
    for it in items:
        if it.get("cloud"):
            c = cloud.setdefault(it["place"], [0, 0])
            c[0] += 1
            c[1] += it["size"]
    return {"places": table, "in_icloud": cloud, "blocked": blocked, "not_read": counts, "photos_library": lib, "spotlight_screenshots": len(screenshots()),
            "folders": [_short(_full(f)) for f in cfg["folders"]], "left_out": [_short(_full(f)) for f in cfg["leave_out"]]}


def _photos_count():
    """Photos and videos in the Photos library, from its database: {"photos": n, "videos": n, "screenshots": n} or the reason."""
    import sqlite3
    try:
        con = _ro(os.path.join(PHOTOS, "database", "Photos.sqlite"))
    except Blocked as e:
        return str(e)
    if con is None:
        return "no photos library on this mac"
    try:
        cols = {r[1] for r in con.execute("pragma table_info(ZASSET)")}
        live = " where coalesce(ZTRASHEDSTATE, 0) = 0" if "ZTRASHEDSTATE" in cols else ""
        by = dict(con.execute("select ZKIND, count(*) from ZASSET%s group by 1" % live).fetchall())
        shots = con.execute("select count(*) from ZASSET%s%s ZISDETECTEDSCREENSHOT = 1" % (live, " and" if live else " where")).fetchone()[0] \
            if "ZISDETECTEDSCREENSHOT" in cols else 0
        return {"photos": by.get(0, 0), "videos": by.get(1, 0), "screenshots": shots}
    except sqlite3.Error:
        return BLOCKED
    finally:
        con.close()


def status(cfg=None):
    cfg = cfg or config()
    items, blocked, _ = listing(cfg)
    known = done()
    out = {"kinds": {}, "blocked": blocked, "folders": [_short(_full(f)) for f in cfg["folders"]], "left_out": [_short(_full(f)) for f in cfg["leave_out"]],
           "tool": bool(helper())}
    ok, locale, why = speech(cfg)
    out["speech"] = {"works_here": ok, "locale": locale, "why": why}
    for kind in KINDS:
        every = [it for it in items if it["kind"] == kind]
        mine = here(every, cfg)
        seen = [known[key(it)] for it in mine if key(it) in known and not known[key(it)].get("wait")]
        out["kinds"][kind] = {"files": len(mine), "read": len(seen), "left": len(mine) - len(seen), "rows": len(rows(kind, known)),
                              "no_row": sum(1 for d in seen if "row" not in d), "in_icloud": len(every) - len(mine)}
    return out


def _rate(known, kind):
    """(seconds per file, share that made a row, share with real words, files measured) from what has been read."""
    seen = [d for d in known.values() if d.get("kind") == kind and not d.get("wait") and d.get("why") not in ("too large", "empty")]
    if not seen:
        return None
    made = [d for d in seen if "row" in d]
    full = [d for d in made if not d["row"].get("light")]
    return sum(d.get("secs") or 0 for d in seen) / len(seen), len(made) / len(seen), len(full) / len(seen), len(seen)


BYTES_A_SECOND = {".opus": 2500, ".ogg": 6000, ".oga": 6000, ".amr": 1600, ".wav": 176000, ".aiff": 176000, ".aif": 176000, ".caf": 3000, ".flac": 90000}


def _audio_hours(left, known):
    """Hours to transcribe these files: their length guessed from their size, at the speed measured on the ones already read."""
    heard = [(d["row"].get("secs") or 0, d.get("secs") or 0) for d in known.values() if d.get("kind") == "audio" and "row" in d and not d.get("wait")]
    length, took = sum(h[0] for h in heard), sum(h[1] for h in heard)
    if not length or not took:
        return None
    guess = sum(it["size"] / BYTES_A_SECOND.get(os.path.splitext(it["path"])[1].lower(), 16000) for it in left)
    return guess * took / length / 3600, guess / 3600


def _sample(kinds_wanted, items, say, cfg):
    """Read a few files only to time them, and keep nothing: what they said is written to a throwaway file that is
    deleted here, never to the archive's own record. An estimate must not be a way for files to come in before a yes."""
    global DONE
    real, tmp = DONE, tempfile.mkdtemp(prefix="ctx-media-sample-")
    DONE = os.path.join(tmp, "sample.jsonl")
    try:
        for kind, n in kinds_wanted:
            scan(kinds=[kind], limit=n, seconds=240, say=say, cfg=cfg, items=items, spread=True)
        return done()
    finally:
        DONE = real
        shutil.rmtree(tmp, ignore_errors=True)


def estimate(sample=12, say=None, cfg=None):
    """Counts by kind and place, and the time the first pass would take, from the speed of files already read. When
    fewer than `sample` files of a kind have been read, that many are read now to time them and nothing of them is
    kept (sample=0 reads none: then the hours are only given for kinds already read)."""
    cfg = cfg or config()
    inv = inventory(cfg)
    items, blocked, _ = listing(cfg)
    items = here(items, cfg)
    known = done()
    want = []
    for kind in KINDS:
        have = _rate(known, kind)
        if sample and (have is None or have[3] < sample) and any(it["kind"] == kind for it in items):
            want.append((kind, sample - (have[3] if have else 0)))
    timed = dict(_sample(want, items, say, cfg), **known) if want else known       # for the speed only; `known` stays what is really read
    known, real = timed, known
    out = {"inventory": inv, "kinds": {}, "blocked": blocked}
    total = total_rows = 0
    for kind in KINDS:
        mine = [it for it in items if it["kind"] == kind]
        left = [it for it in mine if key(it) not in real or real[key(it)].get("wait")]
        r = _rate(known, kind)
        e = {"files": len(mine), "left": len(left), "bytes": sum(it["size"] for it in mine)}
        if r:
            hours = len(left) * r[0] / 3600
            by_length = _audio_hours(left, known) if kind == "audio" else None
            if by_length:                   # a two-hour recording is not a ten-second voice note: count audio by its length
                hours, e["hours_of_audio"] = by_length[0], round(by_length[1], 1)
            e.update(secs_per_file=round(r[0], 2), share_with_row=round(r[1], 2), share_with_words=round(r[2], 2), measured_on=r[3],
                     hours=round(hours, 2), rows=int(round(len(mine) * r[1])))
            total += hours * 3600
            total_rows += len(mine) * r[1]
        out["kinds"][kind] = e
    ok, locale, why = speech(cfg)
    out["speech"] = {"works_here": ok, "locale": locale, "why": why}
    out["hours"], out["rows"] = round(total / 3600, 2), int(round(total_rows))
    return out


# ---------------------------------------------------------------- the command

def _mb(n):
    return "%.1f GB" % (n / 1e9) if n >= 1e9 else "%d MB" % round(n / 1e6)


def _print_inventory(inv):
    print("where the files are (counts and sizes only; code, app bundles and caches are left out)")
    for place in sorted(inv["places"]):
        parts = ["%s %s (%s)" % (format(c[0], ","), ("audio file" if what == "audio" else what) + ("s" if c[0] != 1 else ""), _mb(c[1]))
                 for what, c in sorted(inv["places"][place].items())]
        print("  %-15s %s" % (place, ", ".join(parts)))
    lib = inv["photos_library"]
    if not isinstance(lib, str):
        print("  %-15s %s photos, %s videos, %s screenshots in the library's own count" % (("photos library",) + tuple(format(lib[k], ",") for k in ("photos", "videos", "screenshots"))))
    for place, why in sorted(inv["blocked"].items()):
        print("  %-15s %s" % ("photos library" if place == "photos" else place, why))
    if inv["in_icloud"]:
        n, size = sum(c[0] for c in inv["in_icloud"].values()), sum(c[1] for c in inv["in_icloud"].values())
        print("  kept in icloud, not on this mac: %s of the files above (%s; %s). they are not read: opening one makes macos download it." %
              (format(n, ","), ", ".join("%s %s" % (format(c[0], ","), p) for p, c in sorted(inv["in_icloud"].items())), _mb(size)))
        print("    to read them too: python3 -m ctx media --set icloud_files=on")
    if inv["not_read"]:
        print("  counted but not read: " + ", ".join("%s %s" % (format(n, ","), "spreadsheets, slides, pages and keynote files" if k == "unread" else k)
                                                     for k, n in sorted(inv["not_read"].items())))
    print("  screen captures spotlight knows of: %s" % format(inv["spotlight_screenshots"], ","))
    if inv["left_out"]:
        print("  left out by you: " + ", ".join(inv["left_out"]))


def main(argv):
    as_json = "--json" in argv

    def value(flag):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None
    cfg = config()
    for flag, field, add in (("--leave-out", "leave_out", True), ("--take-in", "leave_out", False), ("--folder", "folders", True), ("--drop-folder", "folders", False)):
        v = value(flag)
        if v:
            full, have = _short(_full(v)), [_short(_full(x)) for x in cfg[field]]
            cfg[field] = list(dict.fromkeys(have + [full])) if add else [x for x in have if x != full]
            save_config(cfg)
            print("%s: %s" % (field.replace("_", " "), ", ".join(cfg[field]) or "nothing"))
            return 0
    if "--set" in argv:
        k, _, v = (value("--set") or "").partition("=")
        if k not in DEFAULTS or k in ("folders", "leave_out"):
            print("settings: speech_locale, max_chars, ocr_pages, tick_seconds, telegram_cache (on|off), icloud_files (on|off)")
            return 1
        try:
            with open(CONFIG) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        saved[k] = int(v) if v.isdigit() else v
        tmp = CONFIG + ".try"
        with open(tmp, "w") as f:
            json.dump(saved, f)
        os.replace(tmp, CONFIG)
        now = config()
        save_config(now)
        print("%s = %s" % (k, now[k]))
        return 0 if str(now[k]) == v else 1
    if "--status" in argv:
        st = status(cfg)
        if as_json:
            print(json.dumps(st, ensure_ascii=False))
            return 0
        for kind in KINDS:
            k = st["kinds"][kind]
            print("%-6s %7s files, %7s read, %7s left, %7s rows" % (kind, format(k["files"], ","), format(k["read"], ","), format(k["left"], ","), format(k["rows"], ",")))
        for place, why in sorted(st["blocked"].items()):
            print("%s: %s" % (place, why))
        print("audio: " + ("transcribed on this mac (%s)" % st["speech"]["locale"] if st["speech"]["works_here"] else st["speech"]["why"]))
        return 0
    if "--estimate" in argv:
        if not as_json:
            print("counting files, then reading a small sample of each kind to time it ...", flush=True)
        est = estimate(sample=int(value("--sample") or 12), cfg=cfg)
        if as_json:
            print(json.dumps(est, ensure_ascii=False))
            return 0
        _print_inventory(est["inventory"])
        print("\nthe first pass, one file at a time at low priority")
        for kind in KINDS:
            e = est["kinds"][kind]
            if "hours" in e:
                print("  %-6s %7s files, %7s left: about %s h at %.2f s a file (measured on %d); about %s rows, %d%% with real words" %
                      (kind, format(e["files"], ","), format(e["left"], ","), e["hours"], e["secs_per_file"], e["measured_on"], format(e["rows"], ","),
                       round(100 * e["share_with_words"])))
            else:
                print("  %-6s %7s files: not timed yet" % (kind, format(e["files"], ",")))
        print("  total: about %s hours, about %s rows" % (est["hours"], format(est["rows"], ",")))
        if not est["speech"]["works_here"]:
            print("  audio is not transcribed here: " + est["speech"]["why"])
        print("start it with: python3 -m ctx media --scan     (safe to stop; it goes on where it stopped)")
        return 0
    if "--scan" in argv:
        kind = value("--kind")
        if kind and kind not in ASKED:
            print("--kind is one of: images, audio, files, video")
            return 1
        limit, minutes, recent = value("--limit"), value("--minutes"), value("--recent")
        items, blocked, _ = listing(cfg, [ASKED[kind]] if kind else None)
        left = todo(here(items, cfg), done(), "--retry" in argv)
        if limit and limit.isdigit():
            left_n = min(len(left), int(limit))
        else:
            left_n = len(left)
        known = done()
        secs = sum((_rate(known, k) or (1.0,))[0] * sum(1 for it in left[:left_n] if it["kind"] == k) for k in KINDS)
        if not as_json:
            print("%s files to read, about %s. one at a time, at low priority. stop any time; it goes on where it stopped." %
                  (format(left_n, ","), "%.1f hours" % (secs / 3600) if secs >= 3600 else "%d minutes" % max(1, round(secs / 60))), flush=True)
            for place, why in sorted(blocked.items()):
                print("%s: %s" % (place, why))
            if len(here(items, cfg)) < len(items):
                print("%s files are kept in icloud, not on this mac, and are left alone (media --set icloud_files=on reads them too)" %
                      format(len(items) - len(here(items, cfg)), ","))
        last = [0.0]

        def say(d):
            if not as_json and time.monotonic() - last[0] > 5:
                last[0] = time.monotonic()
                print("  %s of %s read, %s rows" % (format(d["read"], ","), format(d["of"], ","), format(d["rows"], ",")), flush=True)
        if not (limit and limit.isdigit()):      # the first pass, started by the owner: from now on the 15-minute read keeps up with new files
            os.makedirs(DIR, exist_ok=True)
            with open(STARTED, "a"):
                pass
        r = scan(kinds=[ASKED[kind]] if kind else None, limit=int(limit) if limit and limit.isdigit() else None,
                 seconds=float(minutes) * 60 if minutes else None, recent=int(recent) if recent and recent.isdigit() else None,
                 retry="--retry" in argv, say=say, cfg=cfg, gentle="--fast" not in argv, items=items, spread="--spread" in argv)
        if as_json:
            print(json.dumps(r, ensure_ascii=False))
        else:
            print("%s files read in %s s, %s rows, %s left%s" % (format(r["read"], ","), r.get("secs", 0), format(r["rows"], ","), format(r["left"] or 0, ","),
                                                                (" (stopped: %s)" % r["stopped"]) if r["stopped"] else ""))
            if r.get("audio"):
                print("audio was not transcribed: " + r["audio"])
        return 0
    print(__doc__.split("\n\n")[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
