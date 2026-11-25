"""Remove secrets from text before it is written to disk or sent to a model.

Every collector writes through scrub(). Rules err toward removing too much: a lost hash costs nothing,
a leaked key costs a wallet. Wallet addresses (0x + 40 hex, base58 under 45 chars) are public and kept.
Phone numbers, emails, IFSC and SWIFT codes are not secrets and are kept too.

The passes run in the order of PASSES. tests/test_scrub_corpus.py measures them on made-up text: what share of each
kind of secret is caught, and how much ordinary chat is changed. Run it after any change here.
"""
import math, re
from . import langpacks

R = "[redacted]"
# every key that starts at a word edge sits under one \b: a place that is no word edge is passed over in one step
NAMED = re.compile(r"""
    \b(?:
      sk-[A-Za-z0-9_\-]{16,}                      # openai, anthropic, openrouter, stripe-like
    | (?:rk|pk|sk)_(?:live|test)_[A-Za-z0-9]{16,}  # stripe
    | gh[pousr]_[A-Za-z0-9]{20,} | github_pat_[A-Za-z0-9_]{20,}
    | xox[abeprs]-[A-Za-z0-9\-]{10,} | xapp-[A-Za-z0-9\-]{10,}
    | A[KS]IA[0-9A-Z]{16}\b | AIza[0-9A-Za-z_\-]{30,}
    | (?:npm|hf|gsk|r8|sbp|ntn|shp(?:at|ss|ca|pa)|dop_v1|lin_api|whsec|pplx|tvly|dckr_pat)_[A-Za-z0-9]{20,}   # npm, huggingface, groq, replicate, supabase, notion, shopify, digitalocean, linear, stripe webhook
    | figd_[A-Za-z0-9_\-]{30,} | secret_[A-Za-z0-9]{40,}\b | glpat-[A-Za-z0-9_\-]{20,} | GOCSPX-[A-Za-z0-9_\-]{20,}
    | SG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,} | pypi-AgE[A-Za-z0-9_\-]{40,} | PMAK-[0-9a-f]{20,}-[0-9a-f]{20,}
    | (?:SK|AC)[0-9a-f]{32}\b | key-[0-9a-f]{32}\b                      # twilio, mailgun
    | [MNO][A-Za-z0-9_\-]{23,25}\.[A-Za-z0-9_\-]{6}\.[A-Za-z0-9_\-]{27,}  # discord bot token
    | eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{6,}   # jwt
    | (?:0x)?[0-9a-fA-F]{64}\b                    # evm private key (also tx hashes)
    | [1-9A-HJ-NP-Za-km-z]{80,90}\b               # solana secret key
    | [xyzt]prv[1-9A-HJ-NP-Za-km-z]{90,} | suiprivkey1[a-z0-9]{50,} | AGE-SECRET-KEY-1[A-Z0-9]{50,}
    | otpauth://\S+                               # an authenticator setup link holds the 2fa secret
    )
  | (?<![0-9])\d{8,10}:[A-Za-z0-9_\-]{35}\b       # telegram bot token, also right after "bot" in an api url
  | \[\s*(?:\d{1,3}\s*,\s*){31,}\d{1,3}\s*\]      # a key exported as a list of 32 or 64 byte values (solana-keygen, phantom)
  | -----BEGIN[A-Z\ ]*PRIVATE\ KEY(?:\ BLOCK)?-----.*?(?:-----END[A-Z\ ]*PRIVATE\ KEY(?:\ BLOCK)?-----|$)
  | (?<=://)[^\s/:@]*:[^\s/@]+(?=@)               # user:pass in a url, also ":pass" with no user (redis)
""", re.X | re.S)
# a link whose path is the secret: the host stays readable, the key goes
URLKEY = re.compile(r"((?:hooks\.slack\.com/(?:services|workflows|triggers)|discord(?:app)?\.com/api/webhooks|alchemy\.com/v2|alchemyapi\.io/v2"
                    r"|infura\.io/(?:ws/)?v3|quiknode\.pro|api\.telegram\.org)/)([A-Za-z0-9/_\-:]{8,})")
# http headers and shell commands that carry a login
COOKIE = re.compile(r"""(?i)(\b(?:set-)?cookies?["']?\s*[:=]\s*["']?)([^\n"'=]{1,80}=[^\n"']{1,4000})""")
AUTH = re.compile(r"""(?i)(\bauthorization["']?\s*[:=]\s*["']?\s*(?:basic|bearer|token|digest|negotiate|apikey)\s+)([^\s"',;]{4,})""")
CLI = re.compile(r"""(\bsshpass\s+-p\s*["']?|\bcurl\b[^\n]{0,300}?\s(?:-u|--user)[\s=]+["']?[^\s:"']{1,80}:|\bmysql(?:dump)?\b[^\n]{0,200}?\s-p(?=[^\s\-])|--password[=\s]+["']?)([^\s"']+)""")
ENVNAME = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|PWD|PASS|PASSPHRASE|PK|PRIVATE_KEY|MNEMONIC|SEED|AUTH|DSN)\b\s*[:=]\s*\S+")
_SHORTCUE = {"pass", "pw", "pwd", "pin", "otp", "totp", "auth", "seed", "cvv"}   # short enough to sit inside another word: "compass", "spin"
# whole words that begin like a cue and are not one
_NOTCUE = set("""author authors authored authority authorities authentic pincode pincodes pink ping pinged pinging pinned pinch pine pint pinterest
    seeded seeding seedling passed passing passenger passengers passion passive passes passage tokenize tokenized tokenizer
    secretary secretly secretive pwa""".split())
_NOTLOGIN = set("password pass passwd pwd otp signup register logout google apple email mail phone mobile number username name code link page".split())
_CODE = re.compile(r"[A-Za-z_][\w.]*[(\[]|(?:process|os|import|req|request|self|this|config|settings|env|secrets|args|params|ctx)\.\w")
# one-time codes: a number of 4 to 8 digits on the same line as a word that says what it is, before or after it.
# the pattern (OTPCUE) is built in _words() below, with the word for "code" from every language pack
_OTP_STRONG = r"""otp|o\.t\.p|one[\s\-]?time\s+(?:password|pass\s?code|pin|code)
    |(?:verification|security|login|log[\s\-]?in|sign[\s\-]?in|auth|authentication|confirmation|access|2fa|two[\s\-]?factor|activation)\s+code|passcode"""
OTPNUM = re.compile(r"(?<![\w.,:/+\-])(?:\d{3}[\- ]\d{3}|\d{4,8})(?!\w|[.,:/\-]\d)")
GCODE = re.compile(r"\bG-\d{6}\b")
# the bare word for "code" is weak: these words before it mean a postal, promo or error code, and so do the ones after it below
_NOTCODE = re.compile(r"(?i)\b(?:pin|zip|postal|post|plz|cep|area|country|std|isd|dial|promo|coupon|discount|referral|invite|error|status|exit|qr|bar|source|hs|product|item|color|colour)\s*$")
# backup codes for 2fa come as a list after their name: every code-shaped word in the lines that follow goes
_NOTCODE_AFTER = re.compile(r"(?i)\s*(?:postal|pos\b|promo\w*|d[e']\s?(?:descuento|desconto|area|área|erro|error|pays|r[eé]duction)|rabatt)")
RECOVERY = re.compile(r"(?i)\b(?:backup|recovery|2fa|mfa|two[\s\-]?factor)\s+codes?\b")
RCODE = re.compile(r"(?<![A-Za-z0-9\-])(?:[A-Za-z0-9]{4,6}-[A-Za-z0-9]{4,6}|\d{4} \d{4}|\d{6,10}|(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-z])[a-z0-9]{8,12}|(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{8,12})(?![A-Za-z0-9\-])")
# bank and identity numbers. the ones with a fixed shape are told by the shape, each beside the name of the scheme that
# issues it: add another scheme's number as one more pattern here and one more line in _ids()
AADHAAR = re.compile(r"(?<!\d)(?<!\d[ \-])[2-9]\d{3}[ \-]\d{4}[ \-]\d{4}(?![ \-]?\d)")
AADHAAR_CUE = re.compile(r"(?i)(\b(?:aadhaar|aadhar|adhaar|adhar|uid|uidai)\b[^\n\d]{0,20})(\d{4}[ \-]?\d{4}[ \-]?\d{4})(?!\d)")
PAN = re.compile(r"\b[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]\b")
PAN_CUE = re.compile(r"(?i)(\bpan\b[^\n\d]{0,25}?)\b([a-z]{5}\d{4}[a-z])\b")
SSN = re.compile(r"(?<![\d\-])(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?![\d\-])")
SSN_CUE = re.compile(r"(?i)(\b(?:ssn|social\s+security)\b[^\n\d]{0,25})(\d{9})(?!\d)")
CPF_CUE = re.compile(r"(?i)(\bcpf\b[^\n\d]{0,20})(\d{3}\.?\d{3}\.?\d{3}-?\d{2})(?!\d)")
NINO_CUE = re.compile(r"(?i)(\b(?:national\s+insurance|ni\s+(?:number|no\.?)|nino)\b[^\n\d]{0,25}?)\b([a-z]{2} ?\d{2} ?\d{2} ?\d{2} ?[a-d])\b")
NIK_CUE = re.compile(r"(?i)(\b(?:nik|ktp)\b[^\n\d]{0,20})(\d{16})(?!\d)")
CURP_CUE = re.compile(r"(?i)(\bcurp\b[^\n]{0,20}?)\b([a-z]{4}\d{6}[hm][a-z]{5}[a-z0-9]\d)\b")
# Identity numbers by the country that issues them (ISO code), every country read alike and in the order of its code.
# "cue": numbers told by the word before them: (words to look for first, the pattern). "shape": numbers told by their
# own shape or check digit, wherever they stand: (the pattern, what to put in its place). Another country is one more entry.
ID_NUMBERS = {
    "br": {"cue": [(("cpf",), CPF_CUE)]},
    "gb": {"cue": [(("insurance", "nino", "ni n"), NINO_CUE)]},
    "id": {"cue": [(("nik", "ktp"), NIK_CUE)]},
    "in": {"cue": [(("dha", "uid"), AADHAAR_CUE), (("pan",), PAN_CUE)], "shape": [(AADHAAR, lambda m: _aadhaar(m)), (PAN, R)]},
    "mx": {"cue": [(("curp",), CURP_CUE)]},
    "us": {"cue": [(("ssn", "social"), SSN_CUE)], "shape": [(SSN, R)]},
}
# Payment systems people name a PIN for, by country: "<name> pin 1234". Read alike; add a country or a name here.
PAY_PIN = {"id": ["gopay", "ovo", "dana", r"m-?banking"], "in": ["upi", r"net\s?banking"], "ke": [r"m-?pesa"], "ng": ["opay"], "ph": ["gcash"]}
# sites that show a public ledger: an address named after one of them is a public address, not a secret
LEDGER_SITES = ("blockchain.com", "blockchair", "bscscan", "etherscan", "solscan", "tronscan")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")
# a wallet seed phrase: 12 to 24 short words in a row, lower case, Capitalised or CAPS, with or without "1." numbering,
# on one line or one word per line. it is judged by _seed below.
_W = r"(?:\d{1,2}[.):]?[ \t]*)?(?:[A-Z][a-z]{2,7}|[a-z]{3,8}|[A-Z]{3,8})"
SEED = re.compile(r"(?<![A-Za-z])(?:%s[ \t,]+){11,}%s(?![A-Za-z])" % (_W, _W))
SEED_LINES = re.compile(r"(?m)(?:^[ \t]*%s[ \t]*\n){11,23}[ \t]*%s[ \t]*$" % (_W, _W))
# the same words in any other layout: a grid of a few per line, two lines of six, a bulleted list, or joined by hyphens, bars,
# slashes or dots. ordinary writing is full of such runs (lines of a poem, a menu, a sentence after a full stop), so here
# every word must be in the bip39 list at the end of this file. it never starts inside a link or a file name.
_NL = r"(?:\r?\n[ \t]*){1,2}(?:[\-*•][ \t]+)?"                 # a line break, a blank line at most, then maybe a list bullet
_SEP = r"(?:[ \t,;|/.\-]+(?:%s)?|%s)" % (_NL, _NL)
SEED_ANY = re.compile(r"(?<![A-Za-z0-9/._=@\-])(?:%s%s){11,}%s(?![A-Za-z])" % (_W, _SEP, _W))
# common words that ARE in the bip39 list: a real phrase can hold one or two, a sentence holds more
_SOFT = {"you", "that", "this", "can", "have"}
TOKEN = re.compile(r"[A-Za-z0-9_\-+/=.~]{24,}")
CARD = re.compile(r"\b(?:\d[ \-]?){13,19}\b")
# cheap tests that let a pass be skipped: most chat rows hold no long run of key characters and no number
_KEYISH = re.compile(r"[A-Za-z0-9_\-]{15,}|://|\[|-----")
_DIGIT = re.compile(r"\d")
_DIGITS3 = re.compile(r"\d{3}")
_ADDR = re.compile(r"(?:0x)?[0-9a-fA-F]{40}")
_PUBLIC = re.compile(r"\b(ca|address|addr|wallet|mint|contract|token|coin|pool|(?:%s)\S*)\W*$" % "|".join(re.escape(h) for h in LEDGER_SITES))       # the words that say "this is a public address"
_SOL = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
_SHA = re.compile(r"(?i)(?:commits?|tree|blob|compare|address|token|tx|sha|rev|raw)/$")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_PIECE = re.compile(r"[a-z]{1,20}|[A-Z]{1,12}|[a-z]*(?:[A-Z][a-z]+){1,6}|\d{1,10}|[A-Za-z]{1,3}\d{1,6}")


def _entropy(s):
    return -sum(s.count(c) / len(s) * math.log2(s.count(c) / len(s)) for c in set(s))


def _named_parts(s, in_path):
    """True for a name built from words and numbers: report_final_v3.pdf, PXL_20260120_515378121.mp4, NEXT_PUBLIC_APP_URL,
    and inside a link or a path top-10-coins-of-2026. Outside one, words joined by hyphens alone may be a passphrase."""
    if not in_path and not re.search(r"[_.=]", s):
        return False
    parts = [p for p in re.split(r"[\-_.~=+]", s) if p]
    return len(parts) >= 2 and all(_PIECE.fullmatch(p) for p in parts)


def _piece(t, before, in_path=False):
    """One run with no slash in it: keep it or redact it. `before` is the text right before it."""
    if _ADDR.fullmatch(t) or t.isdigit() or t.isalpha():
        return t  # wallet address, long number, plain word
    core = t.strip("=._-")
    if _SOL.fullmatch(t):  # looks like a solana address: keep only when the text says so
        if not t.islower() and not t.isupper() and _PUBLIC.search(before[-40:].lower()):
            return t
    if "." in core and re.fullmatch(r"[a-z0-9\-]+(?:\.[a-z0-9\-]+)+", core):
        return t  # domain name
    if _named_parts(core, in_path):
        return t  # a file name or a link's slug
    if re.fullmatch(r"[0-9a-fA-F]{32,}", core) and not core.isdigit():
        return R  # a long hex key: its letters are too few for the entropy test below to be sure
    classes = bool(re.search(r"[a-z]", core)) + bool(re.search(r"[A-Z]", core)) + bool(re.search(r"\d", core))
    return R if classes >= 2 and _entropy(core) >= 3.6 else t


def _token(m):
    t = m.group(0)
    before = m.string[max(0, m.start() - 40):m.start()]
    if "/" not in t:
        return _piece(t, before)
    parts = t.split("/")
    full = [p for p in parts if p]
    if re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", t) and 2 * sum(1 for p in full if _PIECE.fullmatch(p.rstrip("="))) < len(full):
        if _piece(t.replace("/", ""), before) == R:
            return R  # base64 that happens to hold a slash: most of its parts are no word and no number
    # a path or a link: each part is judged alone, so a long folder name or an id in a link does not take the whole link with it
    out, seen = [], before
    for p in parts:
        if _UUID.fullmatch(p) or not re.search(r"[A-Za-z0-9_\-]{28,}", p):
            out.append(p)        # no long opaque run: a folder, a file name, a short id
        elif re.fullmatch(r"[0-9a-fA-F]{40}", p) and not p.isdigit() and not _SHA.search(seen):
            out.append(R)        # 40 hex with no 0x in a link: a commit when the link says so, else it may be the link's key
        else:
            out.append(_piece(p, seen, True))
        seen = (seen + p + "/")[-40:]
    return "/".join(out)


def _luhn(m):
    d = [int(c) for c in m.group(0) if c.isdigit()]
    n = len(d)
    if not 13 <= n <= 19:
        return m.group(0)
    # card numbers start 2 to 6, and each start has its lengths: this keeps tweet ids, timestamps and order numbers
    if not {2: n == 16, 3: 14 <= n <= 16, 4: n in (13, 16, 19), 5: n == 16, 6: n >= 16}.get(d[0]):
        return m.group(0)
    s = sum(d[-1::-2]) + sum(sum(divmod(2 * x, 10)) for x in d[-2::-2])
    return R + m.group(0)[len(m.group(0).rstrip(" -")):] if s % 10 == 0 else m.group(0)   # the space after the number stays


def _cards(text):
    out = CARD.sub(_luhn, text)
    return EXPIRY.sub(lambda m: m.group(1) + R, out) if out != text else out   # an expiry date matters only next to its card


_VD = ("0123456789", "1234067895", "2340178956", "3401289567", "4012395678", "5987604321", "6598710432", "7659821043", "8765932104", "9876543210")
_VP = ("0123456789", "1576283094", "5803796142", "8916043527", "9453126870", "4286573901", "2793806415", "7046913258")


def _verhoeff(digits):
    """The check digit of an aadhaar number: one in ten random 12-digit numbers passes, so a phone number rarely does."""
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = int(_VD[c][int(_VP[i % 8][int(ch)])])
    return c == 0


def _aadhaar(m):
    return R if _verhoeff(re.sub(r"\D", "", m.group(0))) else m.group(0)


def _iban(m):
    """Redact when the mod-97 check passes. A trailing group may be the next word, so shorter cuts are tried too."""
    t = m.group(0)
    while len(t.replace(" ", "")) >= 15:
        s = t.replace(" ", "")
        if int("".join(str(int(ch, 36)) for ch in s[4:] + s[:4])) % 97 == 1:
            return R + m.group(0)[len(t):]
        cut = t.rstrip().rfind(" ")
        if cut < 0:
            break
        t = t[:cut]
    return m.group(0)


def _assign(m):
    """The text to put in place of the match, or None when it is no secret."""
    word, val, k, s = m.group(1).lower(), m.group(4), m.group("k").lower(), m.start()
    if val.startswith(R[:5]) or (k + m.group("t").lower()) in _NOTCUE or _CODE.match(val) or "://" in val:
        return None  # done already, "author:", code, or a link (a key inside a link has its own rules)
    if k in _SHORTCUE and s and m.string[s - 1].isalpha() and not (m.string[s - 1].islower() and m.string[s].isupper()):
        return None  # "compass: north": the cue is the tail of another word. "userPass" is still a cue
    bare = val.rstrip(".)!?")
    colon, dash = re.search(r"[:=]", m.group(1)), re.search(r"\s-", m.group(1))
    if _ADDR.fullmatch(bare) or (k == "token" and not colon and _SOL.fullmatch(bare) and not bare.islower() and not bare.isupper()):
        return None  # "token 0x52..": a coin's address, public
    digit = re.search(r"\d", val)
    looks_secret = bool(digit) and bool(re.search(r"[A-Za-z]", val)) or len(val) >= 20
    if k.endswith("key") and k[:3] in ("sec", "set") or k == "totp":
        looks_secret = looks_secret or bool(re.fullmatch(r"[A-Z2-7]{16,}", bare))        # an authenticator key can be all capitals
    if looks_secret and len(val) >= 6:
        return m.group(1) + R
    if not re.match(r"(pass|pwd|pswd|pw|pin|mpin|otp|cvv)", word):
        return None
    if k in ("otp", "pin", "mpin", "cvv"):
        return m.group(1) + R if digit and (colon or dash or _SAID.search(word)) else None    # "otp is sent" is no code
    # a password said outright. the weaker the wording, the more the value must look like one: "pass - Tiger@12" goes,
    # "pass - through" stays; four or five plain letters go only after a colon
    odd = digit or re.search(r"[^A-Za-z0-9]", bare) or not (bare.islower() or bare.isupper() or bare.istitle())
    said = colon or _SAID.search(word) and (len(val) >= 6 or odd) or dash and odd
    if not said or bare.lower() in _NOTPASS or re.fullmatch(r"[*x.•_\-<>]+", bare, re.I):
        return None
    return m.group(1) + R


def _assigns(text):
    """ASSIGN over the text. After a cue that held no secret the search goes on from its value, which may be the real cue:
    in "auth token: x" the first match is "auth" + "token:", and the one that counts starts at "token"."""
    out, pos = [], 0
    while True:
        m = ASSIGN.search(text, pos)
        if not m:
            break
        new = _assign(m)
        if new is None:
            out.append(text[pos:m.start(4)])
            pos = m.start(4)
        else:
            out.append(text[pos:m.start()] + new)
            pos = m.end()
    return "".join(out) + text[pos:]


def _pass_then_is(m):
    v = m.group(2)
    return m.group(0) if v.startswith(R[:5]) or v.lower() in _NOTPASS or v.lower() in _STOP else m.group(1) + R


def _login(m):
    if m.group(5):
        return m.group(0) if m.group(6).startswith(R[:5]) else m.group(5) + R
    user, pw = m.group(2), m.group(4)
    if user.isdigit() or pw.startswith(("/", R[:5])) or "//" in pw or user.lower() in ("http", "https", "page", "link", "screen", "flow"):
        return m.group(0)  # a time, a link, "login / signup"
    if re.match(r"\d{2,5}(?:/|$)", pw) or pw.lower().strip(".,)") in _NOTLOGIN:
        return m.group(0)  # "login: localhost:3000/app", "login: email / password"
    return m.group(1) + user + m.group(3) + R


def _spans(text, spans):
    """text with each (start, end) replaced by R."""
    out, pos = [], 0
    for a, b in sorted(set(spans)):
        if a >= pos:
            out.append(text[pos:a] + R)
            pos = b
    return "".join(out) + text[pos:]


def _otp(text):
    spans = [m.span() for m in GCODE.finditer(text)]
    for m in OTPCUE.finditer(text):
        weak = m.group(0).lower() in _CODE_WORDS
        if weak and (_NOTCODE.search(text, max(0, m.start() - 12), m.start()) or _NOTCODE_AFTER.match(text, m.end())):
            continue
        a = max(0, m.start() - 40)                               # a few words either side of the cue, on its own line
        a = max(a, text.rfind("\n", a, m.start()) + 1)
        b = min(len(text), m.end() + (30 if weak else 80))
        nl = text.find("\n", m.end(), b)
        b = b if nl < 0 else nl
        for c in OTPNUM.finditer(text, a, b):
            if c.end() == b and b < len(text) and text[b].isalnum():
                continue                                         # the window ended inside a longer number
            if weak and len(re.sub(r"\D", "", c.group(0))) != 6:
                continue                                         # "code" alone takes six digits only
            # a number before the cue counts when it leads into it: "123456 is your otp". "order 1234 sent, otp is 5678" keeps the order
            lead = r"\s+is\s+(?:your|ur|the)\b" if weak else _LEAD
            if c.start() > m.start() or re.match(lead, text[c.end():m.start()], re.I):
                spans.append(c.span())
    return _spans(text, spans) if spans else text


def _recovery(text):
    spans = []
    for m in RECOVERY.finditer(text):
        spans += [c.span() for c in RCODE.finditer(text, m.end(), min(len(text), m.end() + 400))]
    return _spans(text, spans) if spans else text


def _pin(m):
    k, n = m.group("k").lower(), len(m.group(3))
    ok = n in (3, 4) if k.startswith("cv") else n == 4 if k == "pin" else n in (4, 6)
    return m.group(1) + R if ok else m.group(0)


def _ids(text):
    """Bank and identity numbers. A rule that needs a cue word runs only when the word is there."""
    low = text.lower()
    if _ACCOUNT_CUE.search(low):
        text = ACCOUNT.sub(lambda m: m.group(1) + R, text)
    for country in sorted(ID_NUMBERS):
        for words, pattern in ID_NUMBERS[country].get("cue", ()):
            if any(w in low for w in words):
                text = pattern.sub(lambda m: m.group(1) + R, text)
        for pattern, put in ID_NUMBERS[country].get("shape", ()):
            text = pattern.sub(put, text)
    text = IBAN.sub(_iban, text)
    return PASSPORT.sub(lambda m: m.group(1) + R, text) if "passport" in low else text


def _seed(m, listed=False):
    """Redact each stretch of 12 or more words that holds no everyday stop word and few repeats. The words around it stay:
    'and the words abandon ability ...' loses the phrase, not the sentence. With `listed`, a stretch is 12 or more words
    of the bip39 list and any other word ends it."""
    parts = re.split(r"((?:\d{1,2}[.):]?[ \t]*)?[A-Za-z]+)", m.group(0))      # separators at even places, words at odd ones
    out, run = [], []

    def close():
        words = [re.sub(r"^[\d.): \t]+", "", w).lower() for w in run[::2]]
        if len(words) >= 12 and len(set(words)) >= 0.7 * len(words) and (listed or sum(w in _SOFT for w in words) <= 2):
            out.append(R)
        else:
            out.extend(run)
        del run[:]
    for i in range(1, len(parts), 2):
        word, sep = parts[i], parts[i + 1]
        w = re.sub(r"^[\d.): \t]+", "", word).lower()
        if w not in _BIP39 if listed else w in _STOP:
            if run:
                tail = run.pop()         # the separator before the stop word stays outside the phrase
                close()
                out.append(tail)
            out.extend([word, sep])
        else:
            run.extend([word, sep])
    if run:
        tail = run.pop()
        close()
        out.append(tail)
    return parts[0] + "".join(out)


def _seeds(text):
    if len(text) < 47:                   # twelve three-letter words are 47 characters
        return text
    text = SEED_ANY.sub(lambda m: _seed(m, True), text)
    return SEED.sub(_seed, SEED_LINES.sub(_seed, text))


# (name, gate pattern, gate words, pass). a pass runs only when the pattern finds something and one of the words is in the
# lower-cased text: most chat rows hold no number, no long run of key characters and no cue word, and skip most passes.
# the names are what why() reports.
PASSES = (
    ("named_key", _KEYISH, None, lambda t: NAMED.sub(R, t)),
    ("key_in_link", None, ("slack.com", "discord", "alchemy", "infura", "quiknode", "telegram.org"), lambda t: URLKEY.sub(lambda m: m.group(1) + R, t)),
    ("cookie", None, ("cookie",), lambda t: COOKIE.sub(lambda m: m.group(1) + re.sub(r"=\s*[^;\s]+", "=" + R, m.group(2)), t)),
    ("auth_header", None, ("authorization",), lambda t: AUTH.sub(lambda m: m.group(0) if m.group(2).startswith(R[:5]) else m.group(1) + R, t)),
    ("shell_login", None, ("sshpass", "curl", "mysql", "--password"), lambda t: CLI.sub(lambda m: m.group(1) + R, t)),
    ("login_pair", None, ("login", "log in", "cred", "pass", "pw", "p:", "p=", "p :", "p ="), lambda t: LOGIN.sub(_login, t)),
    ("env_name", None, ("_key", "_secret", "_token", "_pass", "_pwd", "_pk", "_mnemonic", "_seed", "_auth", "_dsn"),
     lambda t: ENVNAME.sub(lambda m: m.group(0).split("=")[0].split(":")[0] + "=" + R, t)),
    ("totp_key", _DIGIT, ("key", "totp", "2fa"), lambda t: TOTP.sub(lambda m: m.group(1) + R, t)),
    ("assignment", None, ("pass", "pw", "pswd", "secret", "key", "token", "auth", "bearer", "seed", "mnemonic", "otp", "pin", "cvv", "credential"), _assigns),
    ("password_then_is", None, ("pass",), lambda t: PASS_THEN_IS.sub(_pass_then_is, t)),
    ("one_time_code", _DIGITS3, None, _otp),      # no cue words to look for first: the word for "code" comes from the language packs
    ("recovery_codes", _DIGIT, ("code",), _recovery),
    ("pin_cvv", _DIGITS3, ("pin", "cvv", "cvc", "cvn"), lambda t: PIN.sub(_pin, t)),
    ("seed_phrase", None, None, _seeds),
    ("opaque_token", None, None, lambda t: TOKEN.sub(_token, t)),
    ("card", _DIGIT, None, _cards),
    ("bank_identity", _DIGITS3, None, _ids),
)


def _passes(text):
    """The passes whose gates let this text in, as (name, pass)."""
    low = text.lower()
    return [(name, run) for name, pattern, words, run in PASSES
            if (pattern is None or pattern.search(text)) and (words is None or any(w in low for w in words))]


def scrub(text):
    if not text:
        return text
    for _, run in _passes(text):
        text = run(text)
    return text


def why(text):
    """The names of the passes that change this text, in order. For counting what a rule catches, never for showing it."""
    fired = []
    for name, run in _passes(text or ""):
        new = run(text)
        if new != text:
            fired.append(name)
        text = new
    return fired


# the 2048 words of the bip39 english list (bitcoin/bips, MIT). it is long, so it sits here, out of the way of the rules
_BIP39 = frozenset("""
abandon ability able about above absent absorb abstract absurd abuse access accident account accuse achieve acid acoustic acquire across act action
actor actress actual adapt add addict address adjust admit adult advance advice aerobic affair afford afraid again age agent agree ahead aim air
airport aisle alarm album alcohol alert alien all alley allow almost alone alpha already also alter always amateur amazing among amount amused analyst
anchor ancient anger angle angry animal ankle announce annual another answer antenna antique anxiety any apart apology appear apple approve april arch
arctic area arena argue arm armed armor army around arrange arrest arrive arrow art artefact artist artwork ask aspect assault asset assist assume
asthma athlete atom attack attend attitude attract auction audit august aunt author auto autumn average avocado avoid awake aware away awesome awful
awkward axis baby bachelor bacon badge bag balance balcony ball bamboo banana banner bar barely bargain barrel base basic basket battle beach bean
beauty because become beef before begin behave behind believe below belt bench benefit best betray better between beyond bicycle bid bike bind biology
bird birth bitter black blade blame blanket blast bleak bless blind blood blossom blouse blue blur blush board boat body boil bomb bone bonus book
boost border boring borrow boss bottom bounce box boy bracket brain brand brass brave bread breeze brick bridge brief bright bring brisk broccoli
broken bronze broom brother brown brush bubble buddy budget buffalo build bulb bulk bullet bundle bunker burden burger burst bus business busy butter
buyer buzz cabbage cabin cable cactus cage cake call calm camera camp can canal cancel candy cannon canoe canvas canyon capable capital captain car
carbon card cargo carpet carry cart case cash casino castle casual cat catalog catch category cattle caught cause caution cave ceiling celery cement
census century cereal certain chair chalk champion change chaos chapter charge chase chat cheap check cheese chef cherry chest chicken chief child
chimney choice choose chronic chuckle chunk churn cigar cinnamon circle citizen city civil claim clap clarify claw clay clean clerk clever click
client cliff climb clinic clip clock clog close cloth cloud clown club clump cluster clutch coach coast coconut code coffee coil coin collect color
column combine come comfort comic common company concert conduct confirm congress connect consider control convince cook cool copper copy coral core
corn correct cost cotton couch country couple course cousin cover coyote crack cradle craft cram crane crash crater crawl crazy cream credit creek
crew cricket crime crisp critic crop cross crouch crowd crucial cruel cruise crumble crunch crush cry crystal cube culture cup cupboard curious
current curtain curve cushion custom cute cycle dad damage damp dance danger daring dash daughter dawn day deal debate debris decade december decide
decline decorate decrease deer defense define defy degree delay deliver demand demise denial dentist deny depart depend deposit depth deputy derive
describe desert design desk despair destroy detail detect develop device devote diagram dial diamond diary dice diesel diet differ digital dignity
dilemma dinner dinosaur direct dirt disagree discover disease dish dismiss disorder display distance divert divide divorce dizzy doctor document dog
doll dolphin domain donate donkey donor door dose double dove draft dragon drama drastic draw dream dress drift drill drink drip drive drop drum dry
duck dumb dune during dust dutch duty dwarf dynamic eager eagle early earn earth easily east easy echo ecology economy edge edit educate effort egg
eight either elbow elder electric elegant element elephant elevator elite else embark embody embrace emerge emotion employ empower empty enable enact
end endless endorse enemy energy enforce engage engine enhance enjoy enlist enough enrich enroll ensure enter entire entry envelope episode equal
equip era erase erode erosion error erupt escape essay essence estate eternal ethics evidence evil evoke evolve exact example excess exchange excite
exclude excuse execute exercise exhaust exhibit exile exist exit exotic expand expect expire explain expose express extend extra eye eyebrow fabric
face faculty fade faint faith fall false fame family famous fan fancy fantasy farm fashion fat fatal father fatigue fault favorite feature february
federal fee feed feel female fence festival fetch fever few fiber fiction field figure file film filter final find fine finger finish fire firm first
fiscal fish fit fitness fix flag flame flash flat flavor flee flight flip float flock floor flower fluid flush fly foam focus fog foil fold follow
food foot force forest forget fork fortune forum forward fossil foster found fox fragile frame frequent fresh friend fringe frog front frost frown
frozen fruit fuel fun funny furnace fury future gadget gain galaxy gallery game gap garage garbage garden garlic garment gas gasp gate gather gauge
gaze general genius genre gentle genuine gesture ghost giant gift giggle ginger giraffe girl give glad glance glare glass glide glimpse globe gloom
glory glove glow glue goat goddess gold good goose gorilla gospel gossip govern gown grab grace grain grant grape grass gravity great green grid grief
grit grocery group grow grunt guard guess guide guilt guitar gun gym habit hair half hammer hamster hand happy harbor hard harsh harvest hat have hawk
hazard head health heart heavy hedgehog height hello helmet help hen hero hidden high hill hint hip hire history hobby hockey hold hole holiday hollow
home honey hood hope horn horror horse hospital host hotel hour hover hub huge human humble humor hundred hungry hunt hurdle hurry hurt husband hybrid
ice icon idea identify idle ignore ill illegal illness image imitate immense immune impact impose improve impulse inch include income increase index
indicate indoor industry infant inflict inform inhale inherit initial inject injury inmate inner innocent input inquiry insane insect inside inspire
install intact interest into invest invite involve iron island isolate issue item ivory jacket jaguar jar jazz jealous jeans jelly jewel job join joke
journey joy judge juice jump jungle junior junk just kangaroo keen keep ketchup key kick kid kidney kind kingdom kiss kit kitchen kite kitten kiwi
knee knife knock know lab label labor ladder lady lake lamp language laptop large later latin laugh laundry lava law lawn lawsuit layer lazy leader
leaf learn leave lecture left leg legal legend leisure lemon lend length lens leopard lesson letter level liar liberty library license life lift light
like limb limit link lion liquid list little live lizard load loan lobster local lock logic lonely long loop lottery loud lounge love loyal lucky
luggage lumber lunar lunch luxury lyrics machine mad magic magnet maid mail main major make mammal man manage mandate mango mansion manual maple
marble march margin marine market marriage mask mass master match material math matrix matter maximum maze meadow mean measure meat mechanic medal
media melody melt member memory mention menu mercy merge merit merry mesh message metal method middle midnight milk million mimic mind minimum minor
minute miracle mirror misery miss mistake mix mixed mixture mobile model modify mom moment monitor monkey monster month moon moral more morning
mosquito mother motion motor mountain mouse move movie much muffin mule multiply muscle museum mushroom music must mutual myself mystery myth naive
name napkin narrow nasty nation nature near neck need negative neglect neither nephew nerve nest net network neutral never news next nice night noble
noise nominee noodle normal north nose notable note nothing notice novel now nuclear number nurse nut oak obey object oblige obscure observe obtain
obvious occur ocean october odor off offer office often oil okay old olive olympic omit once one onion online only open opera opinion oppose option
orange orbit orchard order ordinary organ orient original orphan ostrich other outdoor outer output outside oval oven over own owner oxygen oyster
ozone pact paddle page pair palace palm panda panel panic panther paper parade parent park parrot party pass patch path patient patrol pattern pause
pave payment peace peanut pear peasant pelican pen penalty pencil people pepper perfect permit person pet phone photo phrase physical piano picnic
picture piece pig pigeon pill pilot pink pioneer pipe pistol pitch pizza place planet plastic plate play please pledge pluck plug plunge poem poet
point polar pole police pond pony pool popular portion position possible post potato pottery poverty powder power practice praise predict prefer
prepare present pretty prevent price pride primary print priority prison private prize problem process produce profit program project promote proof
property prosper protect proud provide public pudding pull pulp pulse pumpkin punch pupil puppy purchase purity purpose purse push put puzzle pyramid
quality quantum quarter question quick quit quiz quote rabbit raccoon race rack radar radio rail rain raise rally ramp ranch random range rapid rare
rate rather raven raw razor ready real reason rebel rebuild recall receive recipe record recycle reduce reflect reform refuse region regret regular
reject relax release relief rely remain remember remind remove render renew rent reopen repair repeat replace report require rescue resemble resist
resource response result retire retreat return reunion reveal review reward rhythm rib ribbon rice rich ride ridge rifle right rigid ring riot ripple
risk ritual rival river road roast robot robust rocket romance roof rookie room rose rotate rough round route royal rubber rude rug rule run runway
rural sad saddle sadness safe sail salad salmon salon salt salute same sample sand satisfy satoshi sauce sausage save say scale scan scare scatter
scene scheme school science scissors scorpion scout scrap screen script scrub sea search season seat second secret section security seed seek segment
select sell seminar senior sense sentence series service session settle setup seven shadow shaft shallow share shed shell sheriff shield shift shine
ship shiver shock shoe shoot shop short shoulder shove shrimp shrug shuffle shy sibling sick side siege sight sign silent silk silly silver similar
simple since sing siren sister situate six size skate sketch ski skill skin skirt skull slab slam sleep slender slice slide slight slim slogan slot
slow slush small smart smile smoke smooth snack snake snap sniff snow soap soccer social sock soda soft solar soldier solid solution solve someone
song soon sorry sort soul sound soup source south space spare spatial spawn speak special speed spell spend sphere spice spider spike spin spirit
split spoil sponsor spoon sport spot spray spread spring spy square squeeze squirrel stable stadium staff stage stairs stamp stand start state stay
steak steel stem step stereo stick still sting stock stomach stone stool story stove strategy street strike strong struggle student stuff stumble
style subject submit subway success such sudden suffer sugar suggest suit summer sun sunny sunset super supply supreme sure surface surge surprise
surround survey suspect sustain swallow swamp swap swarm swear sweet swift swim swing switch sword symbol symptom syrup system table tackle tag tail
talent talk tank tape target task taste tattoo taxi teach team tell ten tenant tennis tent term test text thank that theme then theory there they
thing this thought three thrive throw thumb thunder ticket tide tiger tilt timber time tiny tip tired tissue title toast tobacco today toddler toe
together toilet token tomato tomorrow tone tongue tonight tool tooth top topic topple torch tornado tortoise toss total tourist toward tower town toy
track trade traffic tragic train transfer trap trash travel tray treat tree trend trial tribe trick trigger trim trip trophy trouble truck true truly
trumpet trust truth try tube tuition tumble tuna tunnel turkey turn turtle twelve twenty twice twin twist two type typical ugly umbrella unable
unaware uncle uncover under undo unfair unfold unhappy uniform unique unit universe unknown unlock until unusual unveil update upgrade uphold upon
upper upset urban urge usage use used useful useless usual utility vacant vacuum vague valid valley valve van vanish vapor various vast vault vehicle
velvet vendor venture venue verb verify version very vessel veteran viable vibrant vicious victory video view village vintage violin virtual virus
visa visit visual vital vivid vocal voice void volcano volume vote voyage wage wagon wait walk wall walnut want warfare warm warrior wash wasp waste
water wave way wealth weapon wear weasel weather web wedding weekend weird welcome west wet whale what wheat wheel when where whip whisper wide width
wife wild will win window wine wing wink winner winter wire wisdom wise wish witness wolf woman wonder wood wool word work world worry worth wrap
wreck wrestle wrist write wrong yard year yellow you young youth zebra zero zone zoo
""".split())


# ---------------------------------------------------------------- the patterns that hold a word of some language

@langpacks.on_change
def _words():
    """Every pattern that needs a word of a language, built from every pack there is (ctx/langpacks.py): the word for "is"
    between a name and its secret, what follows "password is" when no password is given, the word for a bank account,
    and the everyday words that tell a sentence from a seed phrase. Runs when this module loads and again whenever a
    pack is added, so nothing in this file names a language and a new pack needs no edit here."""
    global OTPCUE, _CODE_WORDS
    _CODE_WORDS = set(w.lower() for w in langpacks.words("code_word")) | {"code"}
    OTPCUE = re.compile(r"(?ix)(?<![^\W_])(?:%s|%s)(?![^\W_])" % (_OTP_STRONG, "|".join(sorted((re.escape(w).replace("\\ ", r"\s+") for w in _CODE_WORDS), key=lambda w: (-len(w), w)))))
    global LOGIN, ASSIGN, _NOTPASS, PASS_THEN_IS, TOTP, PIN, EXPIRY, ACCOUNT, _ACCOUNT_CUE, PASSPORT, _STOP, _SAID, _LEAD
    plain = lambda key: "|".join(sorted((re.escape(w) for w in langpacks.words(key)), key=lambda w: (-len(w), w))) or "(?!)"
    IS = r"(?:%s)(?!\w)" % plain("is")             # the word alone: "is", never the start of "issue"
    # "login: sam / hunter2", "creds admin:hunter2", "u: admin p: hunter2"
    LOGIN = re.compile(r"""(?i)(\b(?:log\s?in|creds?|credentials?|(?:id|user(?:name)?)\s*/\s*pass(?:word)?)\b\s*(?:%s|[:=\-])?\s*)([\w.@+\-]{2,60})(\s+/\s*|\s*/\s+|:)(\S{4,})
        | (\bu(?:ser(?:name)?|id)?\s*[:=]\s*\S{2,60}[\s,;/|]+p(?:w|wd|ass)?\s*[:=]\s*)(\S{4,})""" % IS, re.X)
    # name = value, "password is x" with the word for "is" in any pack, "pass - x", "Bearer x". k is the cue word, t the rest of that word.
    ASSIGN = re.compile(r"""(?i)((?P<k>pass(?:word|wd|code|phrase)?|pwd|pswd|pw|secret[\s_\-]key|setup[\s_\-]key|client[\s_\-]?secret|secret|token|api[\s_\-]?key|apikey
        |access[\s_\-]?key|auth|bearer|private[\s_\-]?key|priv[\s_\-]?key|seed|mnemonic|otp|totp|mpin|pin|cvv|credential)(?P<t>s?[\w\-]{0,40})["']?\s*(?:%s|[:=]|(?<=\s)-+>?(?=\s)|\s)\s*["'`]?)
        ([^\s"'`,;]{4,})""" % IS, re.X)
    _SAID = re.compile(r"\s(?:%s)\s" % plain("is"))
    _LEAD = r"\s*(?:(?:%s|as)(?!\w)|[:\-]|$)" % plain("is")       # a number before its cue counts when it leads into it: "123456 <is> your code"
    # what follows "password is" when nobody is giving a password away
    _NOTPASS = set(w.lower() for w in langpacks.words("not_a_password"))
    # a language that puts "is" after the value: "<the site's> password tiger <is>"
    last = "|".join(sorted((re.escape(w) for w in langpacks.verb_last()), key=lambda w: (-len(w), w))) or "(?!)"
    PASS_THEN_IS = re.compile(r"(?i)(\bpass(?:word|code)?\s+)([^\s\"'`,;]{4,})(?=\s+(?:%s)(?!\w))" % last)
    # the key an authenticator app is set up with, read out in groups of four: "setup key: abcd efgh ijk2 mnop".
    # it must hold a digit: four four-letter words in a row after "secret key" are a sentence
    TOTP = re.compile(r"""(?i)(\b(?:secret[\s_\-]key|setup[\s_\-]key|totp(?:\s+(?:secret|key))?|2fa\s+(?:setup\s+)?(?:key|secret)|authenticator\s+key|manual\s+entry\s+key)
        \s*(?:%s|[:=\-])?\s*)(?=[a-z \-]{0,80}[2-7])((?:[a-z2-7]{4}[ \-]){3,15}[a-z2-7]{4})\b""" % IS, re.X)
    # pins and card check numbers. a bare "pin" takes four digits only: "pin 123456" is a postal code
    PIN = re.compile(r"""(?i)(\b(?P<k>(?:%s|atm|card|debit|credit|sim|phone|lock|bank|security|transaction|txn)\s+pin|m-?pin|t-?pin|cvv2?|cvc2?|cvn|pin)
        \s*(?:number|no\.?)?\s*(?:%s|was|[:=\-])?\s*)(\d{3,6})(?!\d)""" % ("|".join(n for c in sorted(PAY_PIN) for n in PAY_PIN[c]), IS), re.X)
    EXPIRY = re.compile(r"(?i)(\b(?:exp(?:iry|ires|iration|\.)?(?:\s*date)?|valid\s*(?:thru|through|till|upto|until)|good\s*thru)\s*(?:%s|[:=\-])?\s*)(\d{1,2}\s?/\s?\d{2,4})(?!\d)" % IS)
    # a bank account: the word for one in any pack, then its number
    account = langpacks.alt("account")
    ACCOUNT = re.compile(r"(?i)(\b(?:%s)\s*(?:number|num|no\.?|\#|id)?\s*(?:%s|[:=\-])?\s*)(\d(?: ?\d){8,17})(?!\d)" % (account, IS))
    _ACCOUNT_CUE = re.compile(r"(?i)(?:%s)" % account)
    PASSPORT = re.compile(r"(?i)(\bpassport\s*(?:number|num|no\.?|\#)?\s*(?:%s|[:=\-])?\s*)([A-Z]{1,2}\d{6,8}|\d{8,9})\b" % IS)
    # words that end a run: no seed phrase holds them (one that is in the bip39 list is left out here), and nearly every sentence does
    _STOP = set(w.lower() for w in langpacks.words("everyday") if w.isascii() and w.isalpha() and 3 <= len(w) <= 8 and w.lower() not in _BIP39)
