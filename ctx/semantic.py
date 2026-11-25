"""Find things by what they mean, not by the words a question happens to use.

Word matching fails when the row that answers a question uses other words than the question. This module indexes
the archive in units that carry meaning and scores each unit against a question three ways at once:

  context   a unit is not one chat line. It is a window of consecutive messages in one conversation, a note or a
            chunk of a document, a saved post, a prompt, or a card the read-through wrote about a whole conversation.
            A question's words may be spread over the window, or stand in the card, and the unit still matches.
  words     every word of the question counts on its own, weighed by how rare it is in this archive, and a word also
            matches its neighbours in meaning (video: clip, footage), taken from the word vectors macOS ships.
  vectors   each unit and the question are turned into a vector by the model macOS ships (NaturalLanguage); units
            close to the question are found even when no word is shared.

Everything runs on this Mac: no download, no network, no python package. The vectors come from a small helper,
app/tools/embed.swift, compiled on first use into CTX_HOME/bin. Without a swift compiler the index is still built
and searched, by context and words only.

  python3 -m ctx index            build or update (only new and changed units are embedded; safe to stop and rerun)
  python3 -m ctx index --status   units per source, vectors, size on disk

Ratings (python3 -m ctx rate) are kept in CTX_HOME/feedback.jsonl and change later searches: see feedback().
"""
import array, hashlib, heapq, json, math, mmap, os, re, shutil, subprocess, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor
from . import paths, understand

DIR = os.path.join(paths.HOME, "cache", "semantic")
BIN = os.path.join(paths.HOME, "bin", "embed")
SOURCE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "tools", "embed.swift")
FEEDBACK = os.path.join(paths.HOME, "feedback.jsonl")
MODELS = ("contextual", "sentence")       # tried in this order; both give 512 numbers per text
DIM = 512
WIN_MSGS, WIN_CHARS, OVERLAP = 10, 600, 2  # a window: up to this many messages or characters, sharing two with the next
CHUNK, CHUNK_OVER, MAX_CHUNKS = 700, 100, 40
THIN = {"browser_history", "linkedin_connections", "calendar", "mail", "linkedin_saved", "linkedin_likes"}   # a title and little else: words only, no vector
SAVED = {"x_bookmarks", "instagram_saved", "instagram_likes", "x_likes", "linkedin_saved", "linkedin_likes"}
OWN = {"apple_notes", "obsidian"}
VECTOR_SHARE = 1.0        # how much a vector alone can carry a unit, 0 to 1
MINE, KEPT, CARD = 1, 2, 4
FOLD, GLOSSED = True, False    # the spelling fold helps a little and is on; the word list did not help when measured and is off
STOP = set("""a about after again all also am an and any are as at be because been before but by can could did do does for
from had has have he her here him his how i if in into is it its just like me more my no not now of on or our out over
she so some than that the their them then there these they this to up us was we were what when where which who whom why
will with would you your anything ever tell know think thought thoughts said say says saved save bookmarked liked find
show give get got link url http https www com""".split())
WORD = re.compile(r"[^\W_]+")


def tokens(text):
    """The words of a text as the index sees them: lowercase runs of letters and digits, 2 to 40 characters."""
    return [w for w in WORD.findall(str(text or "").lower().replace("’", "'")) if 2 <= len(w) <= 40]


_FOLD = [("ph", "f"), ("w", "v"), ("z", "j"), ("q", "k"), ("ck", "k"), ("chh", "ch"), ("aa", "a"), ("ee", "i"), ("ii", "i"), ("oo", "u"),
         ("uu", "u"), ("ai", "e"), ("ei", "e"), ("ey", "e"), ("au", "o"), ("ou", "o")]


def fold(w):
    """One spelling for the many a word is typed in when a language is written in latin letters with no fixed spelling,
    whichever language it is: a long vowel written double or single, a sound two letters share (ph/f, w/v, z/j, q/k), a
    nasal ending written or left off. "habeebi" and "habibi" become one, "arigatou" and "arigato", "nahin" and "nahi";
    two spellings that differ by a whole vowel stay apart (no rule guesses a vowel). The rules are _FOLD above and the
    three lines below, and a rule for another habit of spelling is added there. Used beside the word itself, never
    instead of it; a word in a script of its own is left as it is."""
    if not w.isascii() or not w.isalpha() or len(w) < 3:
        return w
    for a, b in _FOLD:
        w = w.replace(a, b)
    w = re.sub(r"(?<=[^aeiou])y(?=[aeiou])", "i", w)         # a y between a consonant and a vowel is also written i
    w = re.sub(r"(.)\1+", r"\1", w)                           # doubled letters
    if len(w) > 3 and w[-1] == "n" and w[-2] in "aeiou":      # a nasal ending is written or not
        w = w[:-1]
    return w


GLOSS = os.path.join(paths.HOME, "cache", "gloss.json")
_gloss = {}


def gloss():
    """The owner's own bilingual word list, made once by `index --gloss` and kept on this Mac only:
    ({word: [english words]}, {english word: [words]}). Empty when it was never made."""
    try:
        stamp = os.stat(GLOSS).st_mtime_ns
    except OSError:
        return {}, {}
    if _gloss.get("stamp") != stamp:
        try:
            with open(GLOSS) as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}
        fwd = {str(k).lower(): [t for x in (v if isinstance(v, list) else [v]) for t in tokens(x) if t not in STOP][:4] for k, v in raw.items() if isinstance(raw, dict)}
        back = {}
        for k, vs in fwd.items():
            for v in vs:
                back.setdefault(v, []).append(k)
        _gloss.update(stamp=stamp, fwd=fwd, back=back)
    return _gloss["fwd"], _gloss["back"]


GLOSS_ASK = """Below are frequent words from one person's chats, most frequent first. They may be in any language or
script the owner writes in, some of them written in latin letters; the rest are English, names, or noise. For every word
that is NOT English and not a name, give 1 to 3 plain English words that carry its meaning (content words, whatever the
language: "dinero": ["money"], "shaadi": ["wedding", "marriage"], "besok": ["tomorrow"]). Leave out grammar words that
carry no topic (the words for "is", "of", "not", "then" in that language), English words and names.
Return JSON: {"word": ["english", ...], ...}"""


def build_gloss(most=3000):
    """Make the owner's word list: the archive's most frequent words go to the model once, which glosses the ones
    that are not english. Needs an index. Returns how many words were glossed."""
    from . import llm
    ix = index()
    if ix is None:
        return 0
    words = []
    for line in bytes(ix.terms).split(b"\n"):
        parts = line.split(b"\t")
        if len(parts) == 3:
            w = parts[0].decode("utf-8", "replace")
            if w.isascii() and w.isalpha() and 3 <= len(w) <= 14 and w not in STOP and int(parts[2]) >= 25:
                words.append((int(parts[2]), w))
    words = [w for _, w in sorted(words, reverse=True)[:most]]
    out = {}
    def ask(part):
        try:
            got = llm.ask_json(GLOSS_ASK, " ".join(part), llm.CHEAP, tag="index:gloss")
        except Exception:
            return {}
        return {str(k).lower(): v for k, v in got.items() if isinstance(v, list) and str(k).lower() in part} if isinstance(got, dict) else {}
    with ThreadPoolExecutor(4) as pool:
        for got in pool.map(ask, [words[a:a + 300] for a in range(0, len(words), 300)]):
            out.update(got)
    if out:
        os.makedirs(os.path.dirname(GLOSS), exist_ok=True)
        with open(GLOSS + ".new", "w") as f:
            json.dump(out, f, ensure_ascii=False)
        os.replace(GLOSS + ".new", GLOSS)
    return len(out)


def _flat(s, most=0):
    s = " ".join(str(s or "").split())
    return s[:most] if most else s


# ---------------------------------------------------------------- the helper

def helper():
    """Path of the compiled embedding helper, or "" when it cannot be built on this Mac (no swift compiler).
    Compiled once into CTX_HOME/bin, and again when its source is newer; if that fails, the copy already there serves."""
    have = BIN if os.path.exists(BIN) else ""
    try:
        if have and (not os.path.exists(SOURCE) or os.path.getmtime(BIN) >= os.path.getmtime(SOURCE)):
            return BIN
        if not os.path.exists(SOURCE) or not shutil.which("swiftc"):
            return have
        if subprocess.run(["xcode-select", "-p"], capture_output=True).returncode != 0:    # swiftc is a stub that opens an install window
            return have
        os.makedirs(os.path.dirname(BIN), exist_ok=True)
        tmp = f"{BIN}.{os.getpid()}.{threading.get_ident()}.new"       # two callers may compile at once: each to its own file
        r = subprocess.run(["swiftc", "-O", SOURCE, "-o", tmp], capture_output=True, timeout=600)
        if r.returncode != 0 or not os.path.exists(tmp):
            return have
        os.replace(tmp, BIN)
        return BIN
    except (OSError, subprocess.SubprocessError):
        return have


def model():
    """Which built-in model this Mac can run: "contextual", "sentence" or "" for none."""
    h = helper()
    for m in MODELS if h else ():
        try:
            r = subprocess.run([h, "info", "--model", m], capture_output=True, timeout=60)
            if r.returncode == 0 and json.loads(r.stdout).get("dim") == DIM:
                return m
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return ""


def embed(texts, name):
    """Vectors for texts, as bytes: len(texts) * DIM float32, unit length, in order. Raises when the helper fails."""
    if not texts:
        return b""
    data = ("\n".join(_flat(t, 1200) or "." for t in texts) + "\n").encode("utf-8", "replace")
    r = subprocess.run([helper() or "embed", "vectors", "--model", name], input=data, capture_output=True, timeout=3600)
    if r.returncode != 0 or len(r.stdout) != len(texts) * DIM * 4:
        raise RuntimeError("the embedding helper failed")
    return r.stdout


def ask_helper(question, words, name, vectors, emb="apple", dim=DIM):
    """One helper run for a question: ({word: [(neighbour, similarity)]}, array of one cosine per stored vector or None).
    question may be a list of texts (the question and guesses at what the answer looks like): a vector's cosine is
    then its best against any of them. With an embedder other than apple's, the question is embedded by that
    embedder first and the helper only compares."""
    h = helper()
    if not h:
        return {}, None
    use = vectors if name and vectors and os.path.exists(vectors) and os.path.getsize(vectors) else "-"
    texts = [_flat(t, 600) for t in ([question] if isinstance(question, str) else list(question)) if _flat(t)]
    args, tmp = [h, "ask", use, "--model", name if name in MODELS else MODELS[-1]], ""
    try:
        if emb not in ("apple", "test") and use != "-":
            try:
                qv = embed_with(texts, emb)
                fd, tmp = tempfile.mkstemp(dir=DIR, suffix=".q")
                with os.fdopen(fd, "wb") as f:
                    f.write(qv)
                args += ["--dim", str(dim), "--queries", tmp]
            except Exception:
                args[2] = "-"               # the embedder is not answering: words only for this question
        r = subprocess.run(args, capture_output=True, timeout=60, input=("\t".join(texts) + "\n" + " ".join(words) + "\n").encode("utf-8", "replace"))
        if r.returncode != 0:
            return {}, None
        cut = r.stdout.index(b"\n")
        head = json.loads(r.stdout[:cut])
        scores = array.array("f")
        scores.frombytes(r.stdout[cut + 1:cut + 1 + 4 * int(head.get("rows") or 0)])
        near = {w: [(str(x[0]), float(x[1])) for x in v] for w, v in (head.get("near") or {}).items()}
        return near, (scores if len(scores) else None)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}, None
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


# ---------------------------------------------------------------- which embedder

TIERS = {"apple": "basic (the model macos ships: fair on english notes and posts, poor on chat and on romanised text)",
         "ollama:bge-m3": "good, multilingual", "ollama:embeddinggemma": "good, multilingual", "ollama:nomic-embed-text": "good, english",
         "ollama:mxbai-embed-large": "good, english"}
BETTER = ("with ollama installed: ollama pull bge-m3   then: python3 -m ctx index --embedder ollama:bge-m3  "
          "(about 1.2 gb; runs on this mac only; nothing is installed until you run it)")


def check_embedder(name):
    """(clean name, "") or (None, why not). apple | ollama:<model> | file:<path to a program>."""
    name = str(name or "").strip()
    if name.lower() == "apple":
        return "apple", ""
    if re.fullmatch(r"ollama:[A-Za-z0-9._/:-]{1,80}", name):
        return name, ""
    if name.startswith("file:") and os.path.isabs(name[5:]) and os.access(name[5:], os.X_OK):
        return name, ""
    return None, "embedder must be apple, ollama:<model already pulled>, or file:<full path of a program that reads one text per line and writes float32 vectors>"


def embedder():
    """The embedder in force: CTX_EMBEDDER, else the "embedder" setting, else apple."""
    name = os.environ.get("CTX_EMBEDDER", "")
    if not name:
        try:
            with open(os.path.join(paths.HOME, "settings.json")) as f:
                name = json.load(f).get("embedder", "")
        except (OSError, ValueError, AttributeError):
            name = ""
    return check_embedder(name)[0] or "apple"


def _ollama(path, body=None, timeout=600):
    """One call to ollama on this Mac. Only ever 127.0.0.1 or localhost: text never leaves the machine."""
    import urllib.parse, urllib.request
    base = os.environ.get("CTX_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    if urllib.parse.urlsplit(base).hostname not in ("127.0.0.1", "localhost", "::1") or not base.startswith("http://"):
        raise RuntimeError("ollama is only ever called on this mac")
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as r:
        return json.loads(r.read())


def _unit_bytes(vectors):
    out = array.array("f")
    for v in vectors:
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.extend(x / n for x in v)
    return out.tobytes()


def embed_with(texts, name):
    """Vectors for texts from the named embedder, as bytes of float32, unit length, in order. The size per text is
    the embedder's own. Raises when it cannot be reached or answers wrongly."""
    if not texts:
        return b""
    clean = [_flat(t, 1200) or "." for t in texts]
    if name.startswith("ollama:"):
        out = []
        for a in range(0, len(clean), 32):
            got = _ollama("/api/embed", {"model": name[7:], "input": clean[a:a + 32]}).get("embeddings")
            if not isinstance(got, list) or len(got) != len(clean[a:a + 32]):
                raise RuntimeError("ollama returned no vectors: is the model pulled?")
            out += got
        return _unit_bytes(out)
    if name.startswith("file:"):
        r = subprocess.run([name[5:]], input=("\n".join(clean) + "\n").encode("utf-8", "replace"), capture_output=True, timeout=3600)
        if r.returncode != 0 or not r.stdout or len(r.stdout) % (4 * len(clean)):
            raise RuntimeError("the embedder program failed")
        a = array.array("f")
        a.frombytes(r.stdout)
        d = len(a) // len(clean)
        return _unit_bytes([a[i * d:(i + 1) * d] for i in range(len(clean))])
    return embed(texts, model())


def _files(name):
    """Where an embedder's vectors live: each has its own pair of files, so switching back costs nothing."""
    slug = "" if name in ("apple", "test", "", "contextual", "sentence") else "." + re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")[:60]
    return f"vectors{slug}.f32", f"hashes{slug}.txt"


def embedder_report():
    """For doctor and the settings page: which embedder is in use, how good it is, and the one line that gets a better one."""
    name = embedder()
    try:
        with open(_p("meta.json")) as f:
            meta = json.load(f)
    except (OSError, ValueError):
        meta = {}
    here = []
    try:
        here = sorted(str(m.get("name", "")) for m in _ollama("/api/tags", timeout=0.4).get("models", []) if "embed" in str(m.get("name", "")) or "bge" in str(m.get("name", "")))
    except Exception:
        pass
    built = meta.get("embedder") or ("apple" if meta.get("model") else "")
    return {"embedder": name, "indexed_with": built, "dims": meta.get("dim"), "vectors": meta.get("vectors", 0), "units": meta.get("units", 0),
            "quality": TIERS.get(name.split(":latest")[0], "not measured"), "needs_index": bool(meta) and built != name,
            "ollama_models_here": here, "better": "" if name != "apple" else (f"python3 -m ctx index --embedder ollama:{here[0]}" if here else BETTER)}


# ---------------------------------------------------------------- units

def chunks(text, size=CHUNK, over=CHUNK_OVER, most=MAX_CHUNKS):
    """A long text as overlapping pieces, cut at a paragraph, sentence or word end where one is near."""
    text = str(text or "").strip()
    out, at = [], 0
    while at < len(text) and len(out) < most:
        end = min(len(text), at + size)
        if end < len(text):
            for sep in ("\n\n", "\n", ". ", " "):
                cut = text.rfind(sep, at + size // 2, end)
                if cut > 0:
                    end = cut + len(sep)
                    break
        piece = text[at:end].strip()
        if piece:
            out.append(piece)
        if end >= len(text):
            break
        at = max(end - over, at + 1)
    return out


def windows(msgs):
    """One conversation's messages, oldest first, as overlapping windows: [(first index, last index + 1)].
    Cut from the start, so new messages at the end change only the last window."""
    out, i, n = [], 0, len(msgs)
    while i < n:
        j, size = i, 0
        while j < n and j - i < WIN_MSGS and (j == i or size + len(msgs[j]) <= WIN_CHARS):
            size += len(msgs[j])
            j += 1
        out.append((i, j))
        if j >= n:
            break
        i = j - OVERLAP if j - OVERLAP > i else j
    return out


def _unit(kind, src, ref, text, **more):
    u = {"h": hashlib.sha1(f"{kind}|{src}|{ref}|{text}".encode("utf-8", "replace")).hexdigest()[:20], "k": kind, "src": src, "text": text}
    u.update({k: v for k, v in more.items() if v not in ("", None, [], 0)})
    return u


def _rows(path):
    try:
        with open(path, "rb") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    yield d
    except OSError:
        return


def chat_units():
    by = {}
    for n, d in enumerate(_rows(paths.MESSAGES)):
        tid = str(d.get("thread_id") or "")
        text = _flat(d.get("text"), 400)
        if not tid or not text:
            continue
        t = by.get(tid)
        if t is None:
            t = by[tid] = {"src": str(d.get("src") or ""), "thread": "", "kind": str(d.get("kind") or ""), "rows": []}
        t["thread"] = str(d.get("thread") or "") or t["thread"]
        who = "me" if d.get("who") == "me" else (_flat(d.get("sender"), 30) or "them")
        t["rows"].append((str(d.get("ts") or ""), n, str(d.get("id", "")), who.replace(":", " "), text))
    for tid, t in by.items():
        rows = sorted(t["rows"])
        for a, b in windows([r[4] for r in rows]):
            part = rows[a:b]
            if sum(len(r[4]) for r in part) < 20:       # "ok", "haha": nothing to find
                continue
            text = "\n".join(f"{r[3]}: {r[4]}" for r in part)
            yield _unit("win", t["src"], tid, text, tid=tid, thread=t["thread"][:60], ts=part[-1][0][:10], ids=[r[2] for r in part],
                        mine=sum(r[3] == "me" for r in part), dm=1 if t["kind"] == "dm" else 0)


def doc_units():
    for path, default in ((paths.DOCS, ""), (paths.MAIL_INDEX, "mail"), (paths.PROMPTS, "prompt")):
        for d in _rows(path):
            src = str(d.get("src") or default)
            thin = src in THIN or path == paths.MAIL_INDEX
            title = _flat(d.get("title") or d.get("thread"), 120)
            body = str(d.get("text") or "").strip()
            parts = [_flat(title + " " + body, 300)] if thin else chunks(body, most=3 if path == paths.PROMPTS else MAX_CHUNKS) or ([title] if title else [])
            for n, part in enumerate(parts):
                if len(part) < 3:
                    continue
                yield _unit("doc", src, f'{d.get("id", "")}#{n}', part, id=str(d.get("id", "")), thread=title[:60], ts=str(d.get("ts") or "")[:10],
                            url=str(d.get("url") or ""), thin=1 if thin else 0, mine=1 if (path == paths.PROMPTS or src in OWN) else 0)
    for d in _rows(paths.SESSIONS):
        text = "\n".join(_flat(d.get(k), 700) for k in ("title", "first_user", "last_user", "last_agent") if d.get(k))
        for n, part in enumerate(chunks(text, most=3)):
            yield _unit("doc", str(d.get("src") or "session"), f'{d.get("id", "")}#{n}', part, id=str(d.get("id", "")),
                        thread=_flat(d.get("title") or d.get("project"), 60), ts=str(d.get("last_agent_ts") or d.get("last_user_ts") or "")[:10], mine=1)


def _say(v):
    if isinstance(v, list):
        return "; ".join(json.dumps(x, ensure_ascii=False) if isinstance(x, dict) else str(x) for x in v)
    return str(v or "")


def memory_units():
    """What the read-through wrote: one unit per card (a whole conversation or project in a few lines), and the pages in pieces."""
    try:
        names = sorted(os.listdir(understand.CARDS))
    except OSError:
        names = []
    for name in names:
        try:
            with open(os.path.join(understand.CARDS, name)) as f:
                c = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(c, dict):
            continue
        key = str(c.get("_key") or "")
        if not re.match(r"[a-z]+:.", key):      # not a unit key ("chat:<thread id>", "work:<project>"): go by the file's name
            key = name[:-5]
        text = "\n".join(f"{k}: {_say(c.get(k))}" for k in ("who", "about", "decisions", "open", "arc", "facts", "people") if c.get(k))
        if len(text) < 20:
            continue
        yield _unit("card", "card", key, _flat(c.get("_title"), 60) + "\n" + text[:1500], key=key, tid=key[5:] if key.startswith("chat:") else "",
                    thread=_flat(c.get("_title"), 60), ts=str(c.get("_to") or "")[:10], of=str(c.get("_src") or ""))
    try:
        pages = sorted(p for p in os.listdir(understand.MEM) if p.endswith(".md"))
    except OSError:
        pages = []
    for p in pages:
        try:
            with open(os.path.join(understand.MEM, p), errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        for n, part in enumerate(chunks(text)):
            yield _unit("page", "read_through", f"{p}#{n}", part, id=f"page.{p[:-3]}.{n}", thread=p[:-3])
    try:        # the knowledge layer's question keys and facts (deep.py): each is found by its own words and lands on the row it rests on
        from . import deep
        for k in deep.key_units():
            yield _unit("doc", "knowledge", k["id"] + "|" + k["text"][:80], k["text"], id=k["id"], thread=k["thread"], ts=k["ts"], of=k["of"],
                        ids=[str(i) for i in k.get("ids") or [] if i not in (None, "")])       # every row it rests on, for the owner's rules to test
    except Exception:
        pass


def all_units():
    for gen in (memory_units, chat_units, doc_units):
        yield from gen()


def embed_text(u):
    """What is embedded for a unit: its conversation or title, then its words, on one line."""
    return _flat(((u.get("thread") or "") + ": " if u["k"] in ("win", "doc") and u.get("thread") else "") + u["text"].replace("\n", " / "), 1200)


# ---------------------------------------------------------------- the index on disk

def _p(name):
    return os.path.join(DIR, name)


def _write(name, data):
    tmp = _p(name) + ".new"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, _p(name))


def _known(name="apple", dim=DIM):
    """Which vectors are on disk for an embedder: {unit hash: row in its vector file}. A half-written tail (a stopped run) is cut off."""
    vf, hf = _files(name)
    try:
        with open(_p(hf)) as f:
            hs = [l.strip() for l in f if l.strip()]
    except OSError:
        hs = []
    size = os.path.getsize(_p(vf)) if os.path.exists(_p(vf)) else 0
    n = min(len(hs), size // (dim * 4))
    if n != len(hs) or size != n * dim * 4:
        os.makedirs(DIR, exist_ok=True)
        with open(_p(vf), "ab") as f:
            f.truncate(n * dim * 4)
        with open(_p(hf), "w") as f:
            f.write("".join(h + "\n" for h in hs[:n]))
    return {h: i for i, h in enumerate(hs[:n])}


def _flags(u):
    return (MINE if u.get("mine") else 0) | (KEPT if u["src"] in SAVED else 0) | (CARD if u["k"] == "card" else 0)


def _month(ts):
    """A date as one small number, 0 when there is none."""
    m = re.match(r"(\d{4})-(\d\d)", str(ts or ""))
    return (int(m.group(1)) - 1970) * 12 + int(m.group(2)) if m and 1970 <= int(m.group(1)) < 2400 else 0


MONTHS = "january february march april may june july august september october november december".split()


def _when(ts):
    """"2025-03-14" as words a question might use: "2025 march"."""
    m = re.match(r"(\d{4})-(\d\d)", str(ts or ""))
    return f"{m.group(1)} {MONTHS[int(m.group(2)) - 1]}" if m and 1 <= int(m.group(2)) <= 12 else ""


def _write_units(units, known, name, t0, pending, emb="apple", dim=DIM):
    """Everything a search needs except the vectors: the units, where each sits, its source, month and flags, and the word lists."""
    srcs, post = [], {}
    offs, vrow, code, month, flag = array.array("Q"), array.array("i"), bytearray(), array.array("H"), bytearray()
    per = {}
    tmp = _p("units.jsonl") + ".new"
    with open(tmp, "wb") as f:
        for i, u in enumerate(units):
            offs.append(f.tell())
            f.write(json.dumps(u, ensure_ascii=False).encode("utf-8", "replace") + b"\n")
            vrow.append(known.get(u["h"], -1))
            if u["src"] not in srcs:
                srcs.append(u["src"])
            code.append(min(srcs.index(u["src"]), 255))
            month.append(_month(u.get("ts")))
            flag.append(_flags(u))
            s = per.setdefault(u["src"], {"units": 0, "vectors": 0})
            s["units"] += 1
            s["vectors"] += vrow[-1] >= 0
            # found by more than its own words: its conversation or title, its link, its source and its date in words
            for w in set(tokens((u.get("thread") or "") + " " + u["text"] + " " + (u.get("url") or "") + " " + u["src"].replace("_", " ") + " " + _when(u.get("ts")))):
                fw = fold(w)
                for t in ((w, "~" + fw) if fw != w else (w,)):    # "~word": the folded spelling, a term of its own
                    a = post.get(t)
                    if a is None:
                        a = post[t] = array.array("I")
                    a.append(i)
    os.replace(tmp, _p("units.jsonl"))
    terms, at = [], 0
    with open(_p("postings.u32") + ".new", "wb") as f:
        for w in sorted(post, key=lambda w: w.encode()):
            a = post[w]
            f.write(a.tobytes())
            terms.append(f"{w}\t{at}\t{len(a)}\n")
            at += len(a)
    os.replace(_p("postings.u32") + ".new", _p("postings.u32"))
    _write("terms.txt", "".join(terms).encode())
    for nm, arr in (("units.off", offs), ("units.vec", vrow), ("units.month", month)):
        _write(nm, arr.tobytes())
    _write("units.src", bytes(code))
    _write("units.flag", bytes(flag))
    meta = {"v": 1, "model": name, "embedder": emb, "dim": dim, "units": len(units), "vectors": sum(1 for v in vrow if v >= 0), "pending": pending,
            "terms": len(terms), "srcs": srcs, "per_source": per, "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "secs": round(time.time() - t0, 1), "archive": _stamp()}
    _write("meta.json", json.dumps(meta, ensure_ascii=False, indent=1).encode())
    _open.clear()
    return meta


def _stamp():
    out = []
    for p in (paths.MESSAGES, paths.DOCS, paths.PROMPTS, paths.SESSIONS, paths.MAIL_INDEX):
        try:
            st = os.stat(p)
            out.append([st.st_size, st.st_mtime_ns])
        except OSError:
            out.append([0, 0])
    return out


def build(workers=None, batch=2000, limit=None, say=None, embedder=None):
    """Build or update the index. Only units with no vector yet are embedded, a batch at a time, each batch saved
    before the next starts: a stopped run loses at most one batch. Runs at low priority.
    embedder(texts) -> bytes replaces the helper (tests). limit: embed at most this many units now."""
    t0 = time.time()
    say = say or (lambda **kw: print("@" + json.dumps(dict(kw, src="index")), flush=True))
    try:
        os.nice(10)
    except OSError:
        pass
    os.makedirs(DIR, exist_ok=True)
    emb = "test" if embedder else globals()["embedder"]()
    name, dim, why = ("test", DIM, "") if embedder else (model(), DIM, "") if emb == "apple" else (emb, 0, "")
    if emb not in ("apple", "test"):        # another embedder: ask it for one vector to learn its size, and that it answers
        try:
            dim = len(embed_with(["hello"], emb)) // 4
        except Exception as e:
            name, why = "", f"{emb} did not answer ({type(e).__name__}: {str(e)[:80]})"
    vf, hf = _files(emb)
    known = _known(emb, dim) if name and dim else {}
    say(phase="reading the archive")
    units, seen = [], set()
    for u in all_units():
        if u["h"] not in seen:
            seen.add(u["h"])
            units.append(u)
    todo = [u for u in units if not u.get("thin") and u["h"] not in known] if name else []
    todo.sort(key=_first)       # stable: what the owner wrote and kept is embedded before the chatter around the owner
    if limit is not None:
        todo = todo[:max(0, int(limit))]
    live = sum(1 for u in units if u["h"] in known)
    if len(known) > 2000 and live < 0.6 * len(known):      # mostly vectors of units that are gone: keep the live ones only
        known = _compact(known, seen, emb, dim)
    meta = _write_units(units, known, name, t0, len(todo), emb, dim or DIM)
    if not name:
        say(phase=(why or "no swift compiler on this mac") + ": indexed by context and words, without vectors")
        return meta
    workers = workers or max(1, min(8, (os.cpu_count() or 4) - 2))
    run = embedder or (lambda texts: embed_with(texts, emb))
    if emb.startswith("ollama:"):
        workers = 2                         # the server does its own batching
    done = 0
    with ThreadPoolExecutor(workers) as pool:
        for a in range(0, len(todo), batch):
            part = todo[a:a + batch]
            texts = [embed_text(u) for u in part]
            step = max(1, -(-len(texts) // workers))
            vecs = b"".join(pool.map(run, [texts[i:i + step] for i in range(0, len(texts), step)]))
            if len(vecs) != len(part) * dim * 4:
                raise RuntimeError("the embedder returned the wrong amount")
            with open(_p(vf), "ab") as f:
                f.write(vecs)
                f.flush()
                os.fsync(f.fileno())
            with open(_p(hf), "a") as f:
                f.write("".join(u["h"] + "\n" for u in part))
            for u in part:
                known[u["h"]] = len(known)
            done += len(part)
            _write("units.vec", array.array("i", (known.get(u["h"], -1) for u in units)).tobytes())     # a search may use them at once
            say(rows=done, of=len(todo), label="embedding")
    if todo:
        left = sum(1 for u in units if not u.get("thin") and u["h"] not in known)
        vrow = array.array("i", (known.get(u["h"], -1) for u in units))
        _write("units.vec", vrow.tobytes())
        for u in units:
            meta["per_source"][u["src"]]["vectors"] = 0
        for u, v in zip(units, vrow):
            meta["per_source"][u["src"]]["vectors"] += v >= 0
        meta.update(vectors=sum(1 for v in vrow if v >= 0), pending=left, secs=round(time.time() - t0, 1))
        _write("meta.json", json.dumps(meta, ensure_ascii=False, indent=1).encode())
        _open.clear()
    return meta


def _first(u):
    """Embedding takes a while on a large archive, and every unit is searchable by its words meanwhile. So the order
    is by how much a vector is likely to matter: the read-through, the owner's own notes, docs and prompts, what they
    saved, the conversations the owner wrote in (one-to-one first), then groups they only read, then the posts they liked."""
    if u["k"] in ("card", "page"):
        return 0
    if u["k"] == "doc":
        return 5 if u["src"].endswith("_likes") else 1
    return (2 if u.get("dm") else 3) if u.get("mine") else 4


def _compact(known, live, name="apple", dim=DIM):
    vf, hf = _files(name)
    keep = sorted((v, h) for h, v in known.items() if h in live)
    with open(_p(vf), "rb") as src, open(_p(vf) + ".new", "wb") as dst:
        for v, _ in keep:
            src.seek(v * dim * 4)
            dst.write(src.read(dim * 4))
    os.replace(_p(vf) + ".new", _p(vf))
    _write(hf, "".join(h + "\n" for _, h in keep).encode())
    return {h: i for i, (_, h) in enumerate(keep)}


def status():
    """Where the index stands: units and vectors per source, size on disk, and whether the archive changed since."""
    try:
        with open(_p("meta.json")) as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return {"built": "", "units": 0, "vectors": 0, "note": "no index yet: run python3 -m ctx index"}
    size = 0
    for n in os.listdir(DIR):
        try:
            size += os.path.getsize(_p(n))
        except OSError:
            pass
    out = {k: meta.get(k) for k in ("built", "model", "embedder", "dim", "units", "vectors", "pending", "terms", "secs", "per_source")}
    out.update(mb=round(size / 1e6, 1), stale=meta.get("archive") != _stamp(), helper=bool(helper()))
    return out


# ---------------------------------------------------------------- reading the index

_open = {}


class Index:
    def __init__(self):
        with open(_p("meta.json")) as f:
            self.meta = json.load(f)
        self.n = self.meta["units"]
        self.off, self.vec, self.month = array.array("Q"), array.array("i"), array.array("H")
        for arr, nm in ((self.off, "units.off"), (self.vec, "units.vec"), (self.month, "units.month")):
            with open(_p(nm), "rb") as f:
                arr.frombytes(f.read())
        with open(_p("units.src"), "rb") as f:
            self.src = f.read()
        with open(_p("units.flag"), "rb") as f:
            self.flag = f.read()
        if not (len(self.off) == len(self.vec) == len(self.month) == len(self.src) == len(self.flag) == self.n):
            raise ValueError("index files do not agree")
        self.units = self._map("units.jsonl")       # maps, not file positions: two threads may read at once
        self.post = self._map("postings.u32")
        self.terms = self._map("terms.txt")
        self.srcs = self.meta["srcs"]

    @staticmethod
    def _map(name):
        if not os.path.getsize(_p(name)):
            return b""
        with open(_p(name), "rb") as f:
            return mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)

    def unit(self, i):
        at = self.off[i]
        return json.loads(self.units[at:self.units.find(b"\n", at)])

    def _line(self, pos):
        """The term line starting at or after byte pos: (start, term, offset, count) or None."""
        t = self.terms
        if pos > 0:
            pos = t.find(b"\n", pos - 1) + 1
            if pos <= 0:
                return None
        end = t.find(b"\n", pos)
        if end < 0:
            return None
        w, at, n = t[pos:end].split(b"\t")
        return pos, w, int(at), int(n), end + 1

    def lookup(self, word, prefix=False, most=40):
        """[(term, postings offset, count)] for a word, or with prefix for every indexed word that starts with it."""
        t, key = self.terms, word.encode()
        if not len(t):
            return []
        lo, hi = 0, len(t)
        while lo < hi:                      # the first line whose term is >= key
            mid = (lo + hi) // 2
            got = self._line(mid)
            if got is None or got[1] >= key:
                hi = mid
            else:
                lo = got[4]
        out, got = [], self._line(lo)
        while got and len(out) < most and (got[1].startswith(key) if prefix else got[1] == key):
            out.append((got[1].decode(), got[2], got[3]))
            got = self._line(got[4]) if got[4] < len(t) else None
        return out

    def postings(self, at, n):
        a = array.array("I")
        a.frombytes(self.post[at * 4:(at + n) * 4])
        return a


def index():
    """The index, opened once and reopened when it is rebuilt. None when there is none."""
    try:
        stamp = os.stat(_p("meta.json")).st_mtime_ns
    except OSError:
        return None
    if _open.get("stamp") != stamp:
        try:
            _open.update(stamp=stamp, ix=Index())
        except (OSError, ValueError, KeyError):
            return None
    return _open.get("ix")


def ready():
    return index() is not None


# ---------------------------------------------------------------- a question

class Query:
    """A question, read once: its words and their neighbours in meaning, how rare each is here, and how close every
    stored vector is to it. Then it can rank units (rows) and say how much of itself any text covers (cover)."""

    def __init__(self, question, probes=(), ix=None, vectors=True, passages=(), light=False):
        self.ix = ix if ix is not None else index()
        self.question = str(question or "")
        own = list(dict.fromkeys(w for w in tokens(self.question) if w not in STOP))
        passages = [_flat(p, 300) for p in passages or () if isinstance(p, str) and p.strip()][:4]
        extra = list(dict.fromkeys(w for p in list(probes or ()) + passages for w in tokens(" ".join(p) if isinstance(p, (list, tuple)) else p)
                                   if w not in STOP and w not in own))[:40]
        near, self.cos = {}, None
        if self.ix is not None and (own or extra) and not light:      # light: words only, no helper run
            emb = self.ix.meta.get("embedder") or "apple"
            near, self.cos = ask_helper([self.question] + passages, [w for w in own if w.isascii()][:24], self.ix.meta.get("model") or "",
                                        _p(_files(emb)[0]) if vectors else "", emb, int(self.ix.meta.get("dim") or DIM))
        if self.cos is not None and self.ix and len(self.cos) <= max(self.ix.vec, default=-1):
            self.cos = None                  # the vector file is shorter than the index says: ignore it
        fwd, back = gloss() if GLOSSED else ({}, {})
        self.groups = []                     # one per idea: (weight, idf, {variant: how well it stands for the word})
        n = self.ix.n if self.ix else 0
        for w, weight in [(w, 1.0) for w in own] + [(w, 0.5) for w in extra]:
            variants = {w: 1.0}
            for x, sim in near.get(w, ()):
                for t in tokens(x):
                    if t not in STOP and t not in variants:
                        variants[t] = round(0.3 + 0.6 * sim, 3)      # a neighbour never counts as much as the word itself
            if FOLD and w not in near and fold(w) != "" and w.isascii():   # not a word english vectors know: its other spellings
                f = fold(w)
                variants.setdefault(f, 0.85)
                variants.setdefault("~" + f, 0.85)
            for t in (fwd.get(w, []) + back.get(w, []))[:6]:        # and the same thing in the owner's other language
                variants.setdefault(t, 0.6)
                if FOLD and t in fwd:
                    variants.setdefault("~" + fold(t), 0.5)
            df = sum(c for _, _, c in self.ix.lookup(w, len(w) > 3)) if self.ix else 0
            idf = math.log(1 + (n + 1) / (df + 1)) if n else 1.0
            self.groups.append((weight, idf, variants))
        self.total = sum(g[1] for g in self.groups if g[0] == 1.0) or sum(g[1] * g[0] for g in self.groups) or 1.0
        if self.cos is not None and len(self.cos) > 1:
            m = sum(self.cos) / len(self.cos)
            sd = math.sqrt(max(1e-9, sum((x - m) * (x - m) for x in self.cos) / len(self.cos)))
            self.mean, self.sd = m, sd
        else:
            self.mean, self.sd = 0.0, 1.0

    def cover(self, text):
        """How much of the question a text covers, 0 to 1: each word of the question that the text holds (or a word
        that starts with it, or a neighbour in meaning) counts by how rare it is in the archive."""
        ws = set(tokens(text))
        if not ws:
            return 0.0
        ws |= {"~" + fold(x) for x in ws}
        got = 0.0
        for weight, idf, variants in self.groups:
            best = 0.0
            for v, s in variants.items():
                if s > best and (v in ws or (len(v) > 3 and v[0] != "~" and any(x.startswith(v) for x in ws))):
                    best = s
            got += weight * idf * best
        return min(1.0, got / self.total)

    def close(self, i):
        """How close unit i's vector is to the question, 0 to 1: 0 at the archive's average, 1 at five deviations above."""
        if self.cos is None:
            return 0.0
        v = self.ix.vec[i]
        return min(1.0, max(0.0, (self.cos[v] - self.mean) / self.sd / 5)) if v >= 0 else 0.0

    def ranked(self, most=400, keep=None):
        """[(score 0..1, unit index)], best first. keep(i) -> bool filters units before ranking."""
        ix = self.ix
        if ix is None:
            return []
        lex = {}
        for weight, idf, variants in self.groups:
            best = {}
            for v, s in variants.items():
                for term, at, n in ix.lookup(v, len(v) > 3 and v[0] != "~"):
                    if n > 0.2 * ix.n and len(self.groups) > 1:     # a word in a fifth of everything tells nothing
                        continue
                    for u in ix.postings(at, n):
                        if best.get(u, 0.0) < s:
                            best[u] = s
            k = weight * idf / self.total
            for u, s in best.items():
                lex[u] = lex.get(u, 0.0) + k * s
        cand = set(lex)
        if self.cos is not None:
            vec = ix.vec
            cut = self.mean + 1.5 * self.sd
            top = heapq.nlargest(300, (i for i in range(ix.n) if vec[i] >= 0 and self.cos[vec[i]] > cut), key=lambda i: self.cos[vec[i]])
            cand.update(top)
        out = []
        for u in cand:
            if keep and not keep(u):
                continue
            s = blend(min(1.0, lex.get(u, 0.0)), self.close(u))
            out.append((s, u))
        return heapq.nlargest(most, out)


def blend(words, vector):
    """One score from the two signals, 0 to 1. Either alone can carry a unit (a saved post close in meaning with no
    word in common; a message with the exact words), and agreement between them counts for more than a weighted sum
    or the larger of the two would give it."""
    return 1 - (1 - words) * (1 - VECTOR_SHARE * vector)


def _who(u):
    return "me" if u.get("mine") and u["k"] == "doc" else "saved" if u["src"] in SAVED else "them"


def _unit_rows(u, score, q, link=False):
    """A unit as rows in the shape answer.search returns. A window gives its best messages, the best first."""
    if u["k"] == "win":
        lines = u["text"].split("\n")
        ids = u.get("ids") or []
        if len(lines) != len(ids):
            return []
        parts = [(l.partition(": ")[0], l.partition(": ")[2], i) for l, i in zip(lines, ids)]
        order = sorted(range(len(parts)), key=lambda n: (q.cover(parts[n][1]) + (0.3 if link and "http" in parts[n][1] else 0), len(parts[n][1])), reverse=True)
        # the best message carries the window's score; the two next best ride a little below it, so that one window
        # does not take three places ahead of the next window's best message
        return [{"id": parts[n][2], "src": u["src"], "ts": u.get("ts", ""), "thread": u.get("thread", ""), "who": "me" if parts[n][0] == "me" else "them",
                 "text": parts[n][1], "url": "", "tid": u.get("tid", ""), "score": round(score * (1.0 if at == 0 else 0.85), 3)} for at, n in enumerate(order[:3])]
    if u["k"] in ("doc", "page"):
        return [dict({"id": u.get("id", ""), "src": u["src"], "ts": u.get("ts", ""), "thread": u.get("thread", ""), "who": _who(u),
                      "text": u["text"][:600], "url": u.get("url", ""), "tid": "", "score": round(score, 3)}, **({"rests": list(u["ids"])} if u.get("ids") else {}))]
    return []


def find(question, k=40, after="", before="", who="", src="", probes=(), link=False, q=None, fb=None, passages=(), pool=0, skip=None):
    """Search by meaning. Returns {"rows": rows best first (each with "score" 0..1 and "tid"), "threads": {thread id: score}
    for the conversations whose card (the read-through's summary of all of it) matches, "windows": the same for the
    conversations a matching window sits in, "q": the Query, for a caller that wants cover()}.
    pool: also return "units", the best `pool` units whole, for a reader that will pick among them: [{"line": the
    unit on one line, "rows": its rows}].
    who: "me" the owner's words and what they saved, "me_only", "saved", or "" for everyone. after/before: "YYYY-MM".
    skip(unit) -> True: that unit is passed over as if it were not in the index: no row, no score, no place taken."""
    ix = index()
    if ix is None:
        return {"rows": [], "threads": {}, "windows": {}, "q": None, "units": []}
    q = q or Query(question, probes, ix, passages=passages)
    lo, hi = _month(after), _month(before)
    code = ix.srcs.index(src) if src in ix.srcs else (-1 if src else None)

    def keep(i):
        if code is not None and ix.src[i] != code:
            return False
        f = ix.flag[i]
        if (lo or hi) and not f & CARD:
            m = ix.month[i]
            if not m or (lo and m < lo) or (hi and m > hi):
                return False
        if who == "me" and not f & (MINE | KEPT | CARD):
            return False
        if who == "me_only" and not f & MINE:
            return False
        if who == "saved" and not f & KEPT:
            return False
        return True
    rows, threads, wins, seen, per, units = [], {}, {}, set(), {}, []
    no = fb.no if fb else ()
    for score, i in q.ranked(most=max(120, 6 * k, 2 * pool) * (2 if skip else 1), keep=keep):
        if len(rows) >= 3 * k and len(units) >= pool:
            break
        u = ix.unit(i)
        if skip is not None and skip(u):
            continue
        if u["k"] != "card" and len(units) < pool:
            got = [r for r in _unit_rows(u, score, q, link) if r["id"] and r["id"] not in no]
            if got:
                units.append({"line": f'{u["src"]} {u.get("ts", "")} {u.get("thread", "")[:30]} | ' + _flat(u["text"].replace("\n", " / "), 320), "rows": got})
        if len(rows) >= 3 * k:
            continue
        if fb:
            score = max(0.0, min(1.0, score + fb.prior(u["src"], u.get("tid", ""))))
        tid = u.get("tid", "")
        if tid and u["k"] in ("card", "win"):
            d = threads if u["k"] == "card" else wins
            d[tid] = max(d.get(tid, 0.0), score)
        if u["k"] == "card":
            continue
        key = tid or u["src"]
        if per.get(key, 0) >= (6 if tid else max(8, k // 3)):       # one conversation or one source does not take every place
            continue
        for r in _unit_rows(u, score, q, link):
            if r["id"] and r["id"] not in seen and r["id"] not in no:
                seen.add(r["id"])
                per[key] = per.get(key, 0) + 1
                rows.append(r)
    rows.sort(key=lambda r: r["score"], reverse=True)
    return {"rows": rows[:k], "threads": threads, "windows": wins, "q": q, "units": units}


def keyword(probes, after="", who="", limit=70, before="", src="", threads=None, link=False, counts=None):
    """What answer.search does, from the index instead of a pass over every file: about a hundred times faster.
    A unit matches when all words of at least one probe are in it (a word of four letters or more also matches words
    that start with it), so the words may sit in neighbouring messages of one conversation, not only in one row.
    Returns (rows best first, how many units matched). threads: a dict to fill with {thread_id: matching units}.
    counts: {probe: units it matched}. link: only units that hold a url."""
    ix = index()
    probes = [[w for w in tokens(" ".join(p) if isinstance(p, (list, tuple)) else p)] for p in probes or ()]
    probes = [p for p in probes if p][:16]
    if ix is None or not probes:
        return [], 0
    memo = {}

    def units(w):
        if w not in memo:
            got = set()
            for _, at, n in ix.lookup(w, len(w) > 3):
                got.update(ix.postings(at, n))
            memo[w] = got
        return memo[w]
    sets = []
    for p in probes:
        got = None
        for w in sorted(p, key=lambda w: len(units(w))):
            got = set(units(w)) if got is None else got & units(w)
            if not got:
                break
        sets.append(got or set())
    if counts is not None:
        counts.update({" ".join(p): len(g) for p, g in zip(probes, sets)})
    top = max((len(g) for g in sets), default=0)
    if not top:
        return [], 0
    score = {}
    for g in sets:
        if g:
            w = min(3.0, 1 + math.log(top / len(g))) / 3      # a rare probe counts more than one found everywhere
            for u in g:
                score[u] = score.get(u, 0.0) + w
    if link:
        urls = units("http") | units("https")
        score = {u: x for u, x in score.items() if u in urls}
    lo, hi = _month(after), _month(before)
    code = ix.srcs.index(src) if src in ix.srcs else (-1 if src else None)
    recent = _month(time.strftime("%Y-%m", time.gmtime(time.time() - 365 * 86400)))
    ranked = []
    for u, x in score.items():
        f, m = ix.flag[u], ix.month[u]
        if f & CARD or (code is not None and ix.src[u] != code):
            continue
        if (lo or hi) and (not m or (lo and m < lo) or (hi and m > hi)):
            continue
        if (who == "me" and not f & (MINE | KEPT)) or (who == "me_only" and not f & MINE) or (who == "saved" and not f & KEPT):
            continue
        ranked.append((x + (0.2 if f & MINE else 0) + (0.2 if f & KEPT else 0) + (0.1 if m >= recent else 0), m, u))
    total = len(ranked)
    q = Query(" ".join(w for p in probes for w in p), ix=ix, light=True)
    rows, seen, per = [], set(), {}
    for x, m, u in heapq.nlargest(4 * limit, ranked):
        un = ix.unit(u)
        tid = un.get("tid", "")
        if threads is not None and tid:
            threads[tid] = threads.get(tid, 0) + 1
        key = tid or un["src"]
        if len(rows) >= limit or per.get(key, 0) >= (10 if tid else max(8, limit // 5)):
            continue
        for r in _unit_rows(un, min(1.0, x / len(probes) + 0.0), q, link)[:2]:
            if r["id"] and r["id"] not in seen:
                seen.add(r["id"])
                per[key] = per.get(key, 0) + 1
                r.pop("score", None)
                rows.append(r)
    return rows[:limit], total


def search(question, k=40, after="", before="", who="", src=""):
    """Rows by meaning, best first, in the row shape answer.search returns: id, src, ts, thread, who, text, url (and "score")."""
    return [{x: v for x, v in r.items() if x != "tid"} for r in find(question, k, after, before, who, src)["rows"]]


def fuse(lists, c=60):
    """Reciprocal-rank fusion: rows that several searches rank high come first. lists: lists of rows, each best first.
    Returns the rows once each, with "rrf" set, best first; a row keeps the fields of its first appearance plus any
    "score" a later list gave it."""
    by, score = {}, {}
    for rows in lists:
        for n, r in enumerate(rows):
            i = r["id"]
            score[i] = score.get(i, 0.0) + 1.0 / (c + n + 1)
            if i not in by:
                by[i] = dict(r)
            elif "score" in r and "score" not in by[i]:
                by[i]["score"] = r["score"]
    out = sorted(by.values(), key=lambda r: score[r["id"]], reverse=True)
    for r in out:
        r["rrf"] = round(score[r["id"]], 5)
    return out


STRONG, MAYBE, FLOOR = 0.6, 0.3, 0.12     # shares of the best row's relevance; and the least a strong row may have


def tiers(rows, rel, strong=40, maybe=15, exempt=()):
    """Sort evidence into what an answer can rest on and what is only related. rel: {id: relevance 0..1}.
    Returns (strong rows, maybe rows, how many were dropped as weak). A row is strong when its relevance is near the
    best row's, maybe when it is some way below, and dropped when far below. Rows in `exempt` (ids) are never
    dropped: they are kept as maybe at least. Order inside a tier is the order given."""
    best = max((rel.get(r["id"], 0.0) for r in rows), default=0.0)
    a, b, dropped = [], [], 0
    for r in rows:
        x = rel.get(r["id"], 0.0)
        if best > 0 and x >= max(STRONG * best, FLOOR) and len(a) < strong:
            a.append(r)
        elif (best > 0 and x >= MAYBE * best and x > 0) or r["id"] in exempt:
            b.append(r)
        else:
            dropped += 1
    dropped += max(0, len(b) - maybe)
    return a, b[:maybe], dropped


# ---------------------------------------------------------------- ratings

PRIOR_SRC, PRIOR_THREAD, STEP = 0.05, 0.15, 0.03       # the most a source or a conversation can move, and one rating's push


def _qkey(question):
    ws = sorted(set(w for w in tokens(question) if w not in STOP))
    return hashlib.sha1(" ".join(ws).encode()).hexdigest()[:16], ws


def row_by_id(rid):
    """One row of the archive by its id, in the shape a search returns, with "tid". None when it is not there, or when
    the owner's rules leave it out (rules.hidden): a row reached by its id is held to the same rules as one found by a search."""
    needle = json.dumps(str(rid), ensure_ascii=False).encode()
    for path in (paths.MESSAGES, paths.DOCS, paths.PROMPTS, paths.SESSIONS):
        try:
            with open(path, "rb") as f:
                for line in f:
                    if needle not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(d, dict) and str(d.get("id", "")) == str(rid):
                        from . import rules
                        if rules.hidden(d):         # left out by a rule, on the never list, or forgotten: not there, for this reader as for every other
                            return None
                        s = str(d.get("src") or "")
                        mine = d.get("who") == "me" or path == paths.PROMPTS or s in OWN
                        text = str(d.get("text") or f'{d.get("first_user", "")} … {d.get("last_agent", "")}')
                        return {"id": str(rid), "src": s, "ts": str(d.get("ts") or d.get("last_agent_ts") or "")[:10],
                                "thread": str(d.get("thread") or d.get("title") or d.get("project") or "")[:60],
                                "who": "me" if mine else "saved" if s in SAVED else "them", "text": text[:600], "url": str(d.get("url") or ""),
                                "tid": str(d.get("thread_id") or "")}
        except OSError:
            continue
    return None


def rate(question, rid, ok, kind="answer"):
    """Record that a row was right (ok) or wrong for a question. Appends one line to CTX_HOME/feedback.jsonl; nothing
    leaves this Mac. Returns the line written."""
    key, _ = _qkey(question)
    row = row_by_id(rid) or {}
    line = {"q": _flat(question, 400), "qh": key, "id": str(rid), "ok": bool(ok), "kind": kind if kind in ("answer", "maybe") else "answer",
            "src": row.get("src", ""), "tid": row.get("tid", ""), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with open(FEEDBACK, "a") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return line


def ratings():
    return list(_rows(FEEDBACK))


def rate_stats():
    rs = ratings()
    by = {}
    for r in rs:
        s = by.setdefault(r.get("src") or "?", {"yes": 0, "no": 0})
        s["yes" if r.get("ok") else "no"] += 1
    return {"ratings": len(rs), "yes": sum(1 for r in rs if r.get("ok")), "no": sum(1 for r in rs if not r.get("ok")),
            "maybe_rated": sum(1 for r in rs if r.get("kind") == "maybe"), "questions": len({r.get("qh") for r in rs}), "per_source": by}


class Feedback:
    """What the owner's ratings say about one question.
    no: ids marked wrong for this question or one worded almost the same: never shown again for it.
    yes: ids marked right for it: shown as strong. near: ids marked right for a question on the same topic: brought in
    as candidates. prior(src, tid): a small push for a source or conversation the owner keeps confirming, a small sink
    for one the owner keeps rejecting; bounded, so a few clicks cannot wreck the ranking."""

    def __init__(self, question, q=None, rows=None):
        key, ws = _qkey(question)
        mine = set(ws)
        self.no, self.yes, self.near = set(), [], []
        src, thread = {}, {}
        for r in (ratings() if rows is None else rows):
            rid, ok = str(r.get("id", "")), bool(r.get("ok"))
            if r.get("src"):
                src[r["src"]] = src.get(r["src"], 0) + (1 if ok else -1)
            if r.get("tid"):
                thread[r["tid"]] = thread.get(r["tid"], 0) + (1 if ok else -1)
            theirs = set(_qkey(r.get("q", ""))[1])
            same = r.get("qh") == key or (len(mine | theirs) and len(mine & theirs) / len(mine | theirs) >= 0.8)
            if same:
                if ok:
                    self.no.discard(rid)
                    if rid not in self.yes:
                        self.yes.append(rid)
                else:                       # the latest rating of a row wins
                    self.no.add(rid)
                    if rid in self.yes:
                        self.yes.remove(rid)
            elif ok and rid not in self.near and (q.cover(r.get("q", "")) if q else (len(mine & theirs) / max(1, len(mine)))) >= 0.5:
                self.near.append(rid)
        self.near = [i for i in self.near if i not in self.yes and i not in self.no]
        self._src = {k: max(-PRIOR_SRC, min(PRIOR_SRC, STEP * v)) for k, v in src.items()}
        self._thread = {k: max(-PRIOR_THREAD, min(PRIOR_THREAD, STEP * v)) for k, v in thread.items()}

    def prior(self, src, tid=""):
        return self._src.get(src, 0.0) + self._thread.get(tid, 0.0)


def feedback(question, q=None):
    """The ratings that bear on a question, or None when nothing was ever rated."""
    return Feedback(question, q) if os.path.exists(FEEDBACK) else None


# ---------------------------------------------------------------- the owner's rules (rules.py)
# Search by meaning and by the word index return nothing a rule leaves out (see the same block in answer.py).

_find, _keyword = find, keyword


def _written(r):
    """A row from a page of the read-through, as it may be handed out now (rules.scrub): None when nothing of it is left."""
    from . import rules
    if not isinstance(r, dict) or r.get("src") != "read_through" or not rules.active().binds:
        return r
    text = rules.scrub(str(r.get("text") or ""), blocks=False)
    return dict(r, text=text) if text.strip() else None


def _unit_hidden(u):
    """Does a unit of the index rest on anything no reader may return now? The index was made before the rule, and a
    unit's score holds every word in it. A stretch of a conversation is passed over when its conversation is left out or
    any one of its messages is (each is read back by its id: the stretch is dated by its last message only); a card
    when its conversation is left out whole or it names what is left out; a page of the read-through when nothing of it
    may be shown; a note, saved post, prompt or session by its own row; a statement of the knowledge layer by every row
    it rests on, and by what it names."""
    from . import rules
    act = rules.active()
    if act.broken:
        return True
    if not act.binds:
        return False
    k, src, text = u.get("k"), str(u.get("src") or ""), str(u.get("text") or "")
    if k == "win":
        head = {"src": src, "thread_id": str(u.get("tid") or ""), "thread": str(u.get("thread") or "")}
        if act.hides(head):
            return True
        ids = [str(i) for i in u.get("ids") or []]
        if act.gone and any(i in act.gone for i in ids):
            return True
        return act.part_touches(head) and act.ids_out(ids)
    if k == "card":
        from . import understand
        key = str(u.get("key") or "")
        card = {"_src": u.get("of", ""), "_title": u.get("thread", "")}
        return rules.card_hidden(understand._key(key) if re.match(r"[a-z]+:.", key) else key, card) or rules.scrub(text, blocks=False) != text
    if k == "page":
        return not rules.scrub(text, blocks=False).strip()
    ids = [str(i) for i in u.get("ids") or []] or ([str(u["id"])] if u.get("id") else [])
    if src == "knowledge":
        if not u.get("ids"):            # a unit of an index made before units named every row they rest on
            from . import deep
            ids = sorted(set(ids) | deep.rests(u.get("id")))
        if rules.scrub(text, blocks=False) != text:
            return True
    return act.hides({"src": src, "ts": u.get("ts", ""), "thread": u.get("thread", ""), "title": u.get("thread", ""), "text": text}) or act.ids_out(ids)


def find(*a, **kw):
    from . import rules
    act = rules.active()
    if act.broken:
        return {"rows": [], "threads": {}, "windows": {}, "q": None, "units": []}
    if not act.binds:
        return _find(*a, **kw)
    got = _find(*a, skip=_unit_hidden, **kw)       # what the rules leave out is not ranked, scored, counted or shown
    if isinstance(got, dict) and got.get("rows"):
        got["rows"] = [r for r in (_written(r) for r in rules.keep(got["rows"])) if r]
    if isinstance(got, dict) and got.get("units"):
        got["units"] = [u for u in got["units"] if len(rules.keep(u.get("rows") or [])) == len(u.get("rows") or []) and all(_written(r) for r in u.get("rows") or [])
                        and rules.scrub(str(u.get("line") or ""), blocks=False) == str(u.get("line") or "")]
    return got


def keyword(probes, after="", who="", limit=70, before="", src="", threads=None, link=False, counts=None):
    from . import rules
    act = rules.active()
    if act.broken:
        return [], 0
    if not act.binds:
        return _keyword(probes, after, who, limit, before, src, threads, link, counts)
    # the index holds stretches as they were before the rules, so what it counts holds what they leave out: the total,
    # the matches per conversation and per probe are counted again from the rows a reader may see. A row is shown only
    # when its own words match, not because a left-out neighbour in its stretch did, and it carries its own day, not the
    # day its stretch ends on
    rows, n = _keyword(probes, after, who, limit, before, src, None, link, None)
    if not n:
        return [], 0
    from . import answer, peek
    per_thread, per_probe = {}, {}
    n = answer.search(probes, after, who, 1, before, src, link=link, counts=per_probe, threads=per_thread)[1]
    if threads is not None:
        threads.update(per_thread)
    if counts is not None:
        counts.update(per_probe)
    words = [answer._rx(w) for p in answer.clean_probes(probes) for w in p]
    rows = [r for r in rows if n and any(x.search(answer._low(str(r.get("text") or "") + " " + str(r.get("thread") or ""))) for x in words)]
    out = []
    for r in rules.keep(rows):
        d = peek._find(r["id"])[1] if r.get("tid") else None
        out.append(dict(r, ts=str(d.get("ts") or "")[:10]) if isinstance(d, dict) else r)
    return out, n


find.__doc__, keyword.__doc__ = _find.__doc__, _keyword.__doc__
