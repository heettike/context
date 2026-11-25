"""Which lines of the archive can match a probe, without reading every line.

answer.search() reads the archive line by line and keeps the lines in which every word of some probe appears
(as a run of bytes anywhere in the lowercased line). That pass is the slow part of a search. This module gives
search() the same lines, in the same order, from an index:

  - every line is cut into tokens (runs of letters, digits and non-ascii bytes, lowercased);
  - for each token the index keeps the numbers of the lines that hold it;
  - a probe word is cut the same way; a line can hold the word only if, for each piece of the word, it holds some
    token that contains that piece. So the lines the index names are always a superset of the lines that match,
    and search() still checks each one exactly as before. The results are the same rows; only the reading is less.

The archive files are joined from per-source parts. An index is made per part and named by the hash of the part's
bytes, so a tick that brings new whatsapp rows indexes whatsapp again and nothing else, and a part written again
with the same rows costs nothing. warm() then checks, by hashing, that each joined file really is those parts end to
end and writes that down with the joined file's size and time. lines() uses the index only for a joined file that
still has that size and time; otherwise it reads the whole file as before.

  python3 -m ctx words [--status]     index what changed (the tick does this) | say what is indexed
CTX_WORD_INDEX=0 turns the index off.
"""
import array, bisect, hashlib, json, mmap, os, re, tempfile, time
from . import paths

DIR = os.path.join(paths.HOME, "cache", "words")
TOKEN = re.compile(rb"[0-9a-z\x80-\xff]+")
LONG = 64               # a line holding a token longer than this is always handed to search (its token is not indexed)
ALL = 0xFFFFFFFF        # in the table: this token is in more than half the lines, so it narrows nothing
V = 3
JOINED = (paths.MESSAGES, paths.PROMPTS, paths.DOCS, paths.SESSIONS)
_open = {}              # hash of a part -> its open index, kept while the process lives
_plans = {}             # joined file -> (manifest file stamp, manifest)


def on():
    return os.environ.get("CTX_WORD_INDEX", "1") != "0"


def _stamp(path):
    try:
        st = os.stat(path)
        return [st.st_size, st.st_mtime_ns]
    except OSError:
        return None


def _file(digest):
    return os.path.join(DIR, digest + ".idx")


def _manifest(path):
    return os.path.join(DIR, os.path.basename(path) + ".json")


def _digest(f, size=None):
    """The hash of a file, or of the next `size` bytes of an open one."""
    h, left = hashlib.blake2b(digest_size=16), size
    own = isinstance(f, str)
    f = open(f, "rb") if own else f
    try:
        while left is None or left > 0:
            block = f.read(1 << 20 if left is None else min(1 << 20, left))
            if not block:
                break
            h.update(block)
            if left is not None:
                left -= len(block)
    finally:
        if own:
            f.close()
    return h.hexdigest()


def parts_of(path):
    """The part files a joined archive file is made of, in the order they are joined. [path] when it has no parts."""
    try:
        from . import collect
        T, part = collect.TABLE, collect._part
        if path == paths.PROMPTS:
            ps = [part(n, "prompts") for n, g, _ in T if g == collect.S] + [part(n) for n, g, _ in T if g == collect.P]
        else:
            ps = [part(n) for n, g, _ in T if g == path]
    except Exception:
        ps = []
    ps = [p for p in ps if os.path.exists(p)]
    return ps or [path]


def build(seg):
    """Index one part; returns the hash of its bytes, which names the index file. Layout: 8 bytes of header length, a JSON header naming each section, then the sections:
    line offsets (Q), the vocabulary (tokens in order, one per line), where each token starts in it (I), a table of
    (first posting, how many) per token (I, I), the postings (line numbers, I), and the always-check lines (I)."""
    if not os.path.exists(seg):
        return ""
    offs, post, always = array.array("Q"), {}, array.array("I")
    find = TOKEN.findall
    digest = hashlib.blake2b(digest_size=16)
    with open(seg, "rb") as f:
        off = n = 0
        for line in f:
            digest.update(line)
            offs.append(off)
            off += len(line)
            long = False
            for t in set(find(line.lower())):
                if len(t) > LONG:
                    long = True
                    continue
                got = post.get(t)
                if got is None:
                    post[t] = [n]
                else:
                    got.append(n)
            if long:
                always.append(n)
            n += 1
    half = max(1, n // 2)
    toks = sorted(post)
    vocab = b"\n" + b"\n".join(toks) + b"\n"
    starts, table, flat = array.array("I"), array.array("I"), array.array("I")
    at = 1
    for t in toks:
        starts.append(at)
        at += len(t) + 1
        lines = post[t]
        if len(lines) > half:
            table.extend((0, ALL))
        else:
            table.extend((len(flat), len(lines)))
            flat.extend(lines)
    secs, body, pos = {}, [], 0
    for name, data in (("offs", offs.tobytes()), ("vocab", vocab), ("starts", starts.tobytes()), ("table", table.tobytes()),
                       ("post", flat.tobytes()), ("always", always.tobytes())):
        secs[name] = [pos, len(data)]
        body.append(data)
        pos += len(data)
    name = digest.hexdigest()
    head = json.dumps({"v": V, "hash": name, "bytes": off, "lines": n, "tokens": len(toks), "secs": secs}).encode()
    os.makedirs(DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=DIR, suffix=".new")
    with os.fdopen(fd, "wb") as f:
        f.write(len(head).to_bytes(8, "little") + head)
        for data in body:
            f.write(data)
    os.replace(tmp, _file(name))
    return name


class Index:
    def __init__(self, m, head, base):
        self.m, self.head, self.base, self.lines = m, head, base, head["lines"]
        s = head["secs"]
        self.at = {k: (base + v[0], v[1]) for k, v in s.items()}
        self.starts = memoryview(m)[self.at["starts"][0]:self.at["starts"][0] + self.at["starts"][1]].cast("I")
        self.table = memoryview(m)[self.at["table"][0]:self.at["table"][0] + self.at["table"][1]].cast("I")
        self.post = memoryview(m)[self.at["post"][0]:self.at["post"][0] + self.at["post"][1]].cast("I")
        self.offs = memoryview(m)[self.at["offs"][0]:self.at["offs"][0] + self.at["offs"][1]].cast("Q")
        self.always = memoryview(m)[self.at["always"][0]:self.at["always"][0] + self.at["always"][1]].cast("I")

    def piece(self, piece):
        """Line numbers that hold a token containing these bytes, as a set; None when that is most lines."""
        lo, n = self.at["vocab"]
        hi, m, starts, table, post = lo + n, self.m, self.starts, self.table, self.post
        got, total, limit, pos = [], 0, self.lines // 2, lo
        while True:
            pos = m.find(piece, pos, hi)
            if pos < 0:
                break
            k = bisect.bisect_right(starts, pos - lo) - 1
            first, count = table[2 * k], table[2 * k + 1]
            if count == ALL:
                return None
            total += count
            if total > limit:
                return None
            got.append((first, count))
            pos = lo + starts[k + 1] if k + 1 < len(starts) else hi         # on to the next token: one hit per token is enough
        out = set()
        for first, count in got:
            out.update(post[first:first + count])
        return out

    def candidates(self, raw):
        """Line numbers worth checking for these probes (each a list of lowercase byte words), sorted; None for all."""
        memo, union = {}, set()
        for probe in raw:
            narrow = None
            for word in probe:
                for p in TOKEN.findall(word):
                    if p not in memo:
                        memo[p] = self.piece(p)
                    got = memo[p]
                    if got is not None:
                        narrow = got if narrow is None else narrow & got
                        if not narrow:
                            break
                if narrow is not None and not narrow:
                    break
            if narrow is None:          # nothing in this probe narrows the search: every line is a candidate
                return None
            union |= narrow
        union.update(self.always)
        return sorted(union)


def load(digest):
    """The index for the part with these bytes, or None."""
    if digest in _open:
        return _open[digest]
    try:
        with open(_file(digest), "rb") as f:
            n = int.from_bytes(f.read(8), "little")
            head = json.loads(f.read(n))
            if head.get("v") != V or head.get("hash") != digest:
                return None
            m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    except (OSError, ValueError):
        return None
    if len(_open) > 200:
        _open.clear()
    _open[digest] = Index(m, head, 8 + n)
    return _open[digest]


def plan_for(path, size, mtime):
    """[(start, size, index)] for a joined file that warm() has checked and that has not changed since; else None."""
    mf = _manifest(path)
    st = _stamp(mf)
    if st is None:
        return None
    have = _plans.get(path)
    if not have or have[0] != st:
        try:
            with open(mf) as f:
                have = (st, json.load(f))
        except (OSError, ValueError):
            return None
        _plans[path] = have
    man = have[1]
    if not isinstance(man, dict) or man.get("v") != V or man.get("stamp") != [size, mtime] or not isinstance(man.get("segs"), list):
        return None
    out = []
    for digest, start, n in man["segs"]:
        ix = load(digest)
        if ix is None:
            return None
        out.append((start, n, ix))
    return out


def lines(f, path, raw):
    """(offset, line) for every line of the open archive file that search() needs to look at for these probes: the
    lines the index names when it is whole and current, else every line. Same order either way."""
    plan = None
    if on() and raw:
        try:
            st = os.fstat(f.fileno())
            segs = plan_for(path, st.st_size, st.st_mtime_ns)
            if segs:
                plan = [(start, size, ix, ix.candidates(raw)) for start, size, ix in segs]
        except Exception:       # whatever is wrong with the index, the file itself is still there to read
            plan = None
    if plan is None:
        off = 0
        f.seek(0)
        for line in f:
            yield off, line
            off += len(line)
        return
    for start, size, ix, cand in plan:
        if cand is None:
            f.seek(start)
            off, end = start, start + size
            while off < end:
                line = f.readline()
                if not line:
                    break
                yield off, line
                off += len(line)
        else:
            offs = ix.offs
            for n in cand:
                off = start + offs[n]
                f.seek(off)
                yield off, f.readline()


def warm(say=None):
    """Bring the index up to date: index each part whose bytes are new, then check that each joined file is its parts
    end to end and note that down. Returns the names of the parts indexed. The tick calls this after collecting."""
    os.makedirs(DIR, exist_ok=True)
    done, keep = [], set()
    for path in JOINED:
        if not os.path.exists(path):
            continue
        try:
            with open(_manifest(path)) as f:
                old = json.load(f)
        except (OSError, ValueError):
            old = {}
        known = old.get("parts", {}) if isinstance(old, dict) and old.get("v") == V and isinstance(old.get("parts"), dict) else {}
        parts, segs, at = {}, [], 0
        for seg in parts_of(path):
            st = _stamp(seg)
            if st is None:
                continue
            was = known.get(seg)
            digest = was[1] if was and was[0] == st else _digest(seg)        # an untouched part is not read again
            if load(digest) is None:
                t = time.time()
                digest = build(seg)
                done.append(os.path.basename(seg))
                if say:
                    say({"indexed": os.path.basename(seg), "secs": round(time.time() - t, 1)})
            parts[seg] = [st, digest]
            segs.append([digest, at, st[0]])
            at += st[0]
            keep.add(digest)
        try:                    # is the joined file these parts, in this order, byte for byte? only then may lines() trust the index
            with open(path, "rb") as f:
                st = os.fstat(f.fileno())
                same = st.st_size == at and all(_digest(f, n) == digest for digest, _, n in segs)
                stamp = [st.st_size, st.st_mtime_ns]
        except OSError:
            same, stamp = False, None
        man = {"v": V, "stamp": stamp if same else None, "segs": segs if same else [], "parts": parts}
        with open(_manifest(path) + ".new", "w") as f:
            json.dump(man, f)
        os.replace(_manifest(path) + ".new", _manifest(path))
    for name in os.listdir(DIR):       # indexes of bytes that are no longer in the archive
        if name.endswith(".idx") and name[:-4] not in keep and time.time() - os.path.getmtime(os.path.join(DIR, name)) > 3600:
            try:
                os.remove(os.path.join(DIR, name))
            except OSError:
                pass
    return done


def status():
    out, size = {}, 0
    for path in JOINED:
        try:
            with open(path, "rb") as f:
                st = os.fstat(f.fileno())
            plan = plan_for(path, st.st_size, st.st_mtime_ns)
        except OSError:
            plan = None
        out[os.path.basename(path)] = {"current": plan is not None, "parts": len(plan) if plan else 0,
                                       "lines": sum(ix.lines for _, _, ix in plan) if plan else None}
    try:
        size = sum(os.path.getsize(os.path.join(DIR, n)) for n in os.listdir(DIR) if n.endswith(".idx"))
    except OSError:
        pass
    return {"on": on(), "files": out, "bytes": size, "whole": all(v["current"] for v in out.values())}


def main(args):
    print(json.dumps(status() if "--status" in args else {"indexed": warm()}))
    return 0
