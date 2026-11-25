"""Made-up text for measuring ctx/scrub.py: secrets set in chat-like sentences, and ordinary chat that must pass untouched.

Nothing here is real. Every key, card, phrase and number is drawn from a seeded random source when the module runs, and
provider-shaped strings are put together from parts, so no whole key sits in this file for a scanner to trip on.

    secrets()  -> [{"class", "variant", "text", "secret"}]   "secret" is a string or a list of strings that must not survive
    benign()   -> [{"kind", "text"}]                          a false positive is scrub(text) != text
    leaks(item, out), catch_table(scrub, items), fp_table(scrub, lines), slow_inputs()
"""
import base64, json, random, re, string

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
ALNUM = string.ascii_letters + string.digits
LOWNUM = string.ascii_lowercase + string.digits
UPNUM = string.ascii_uppercase + string.digits
HEX = "0123456789abcdef"
B64 = ALNUM + "+/"
SAFE = ALNUM + "_-"
B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
BECH = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
DIGITS = string.digits

# about 230 words of the real BIP-39 english list (2048 words; it is not in the standard library)
BIP39 = """abandon ability able about above absent absorb abstract absurd abuse access accident account accuse achieve acid
acoustic acquire across act action actor actress actual adapt add addict address adjust admit adult advance advice aerobic
affair afford afraid again age agent agree ahead aim air airport aisle alarm album alcohol alert alien all alley allow
almost alone alpha already also alter always amateur amazing among amount amused analyst anchor ancient anger angle angry
animal ankle announce annual another answer antenna antique anxiety any apart apology appear apple approve april arch
arctic area arena argue arm armed armor army around arrange arrest arrive arrow art artist artwork ask aspect assault
asset assist assume asthma athlete atom attack attend attitude attract auction audit august aunt author auto autumn
average avocado avoid awake aware away awesome awful awkward axis bamboo banana bridge bronze bullet butter cactus candy
castle coral cotton cradle danger desert diamond doctor dragon eagle elephant embrace engine fabric father flame flower
forest galaxy garden guitar harbor hockey horse humble hybrid insect island jacket jungle kingdom kitchen ladder legend
lemon lizard lunar magnet mango market melody mirror monkey museum mystery night noble north number ocean olive orange
orbit panda pencil piano pilot pumpkin puzzle quantum rabbit remember rhythm ribbon river rocket school season
seven shadow silver smile snake soccer solar spider spirit stone story street sugar summer sunset table tent theory
thunder ticket tiger title toast today tomato tooth tower tragic travel tribe trophy trumpet tunnel turtle twist typical
umbrella uncle uniform unique unlock upper urban useful valley vault velvet victory village virus vivid voice volcano
voyage wall water wave wealth whale wild window winter wolf world wrap wrist year yellow young youth zero zone zoo
this that have can you""".split()

# sentences a secret is dropped into. "{}" is the secret. some name it, some do not: a scrubber must not lean on the cue.
# the bare secret, then two plain sentences in each of four languages: no one language and no one way of typing carries the tests
WRAPS = ["{}",
         "here is the key: {} please use it",
         "ok sending it now\n{}\ntell me if it works",
         "ponlo en el archivo de entorno {} y reinicia",
         "este es el de pruebas {} el otro te lo paso luego",
         "yeh raha {} isse kaam ho jayega",
         "abhi ke liye {} use kar lijiye, kal badal denge",
         "pakai yang ini dulu {} besok saya ganti",
         "ini dia - {} - jangan dibagikan di grup"]


class Gen:
    """One seeded random source and the list being built."""

    def __init__(self, seed):
        self.r = random.Random(seed)
        self.out = []
        self.n = 0

    def s(self, alphabet, n):
        return "".join(self.r.choice(alphabet) for _ in range(n))

    def mixed(self, alphabet, n):
        """Like s(), but never all one kind of character: a real key of this length holds letters and digits."""
        while True:
            t = self.s(alphabet, n)
            if re.search(r"\d", t) and re.search(r"[A-Za-z]", t):
                return t

    def num(self, n):
        return self.r.choice("123456789") + self.s(DIGITS, n - 1)

    def add(self, cls, variant, text, secret, words=False):
        self.out.append({"class": cls, "variant": variant, "text": text, "secret": secret, "words": words})

    def wrap(self, cls, variant, make, n=4, lead=""):
        """n samples of one shape, each in a different sentence. `lead` is put right before the secret ("NAME=")."""
        for _ in range(n):
            tok = make()
            self.n += 1
            self.add(cls, variant, WRAPS[self.n % len(WRAPS)].format(lead + tok), tok)


def luhn_digit(body):
    d = [int(c) for c in body][::-1]
    s = sum(sum(divmod(2 * x, 10)) if i % 2 == 0 else x for i, x in enumerate(d))
    return str(-s % 10)


_VD = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
       [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1], [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
       [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_VP = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
       [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1], [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]
_VINV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_digit(body):
    c = 0
    for i, ch in enumerate(reversed(body)):
        c = _VD[c][_VP[(i + 1) % 8][int(ch)]]
    return str(_VINV[c])


def verhoeff_ok(number):
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _VD[c][_VP[i % 8][int(ch)]]
    return c == 0


def iban(country, bban):
    n = int("".join(str(int(ch, 36)) for ch in bban + country + "00"))
    return country + "%02d" % (98 - n % 97) + bban


def b64url(obj):
    return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode().rstrip("=")


def _providers(g):
    P, s, r = "provider_key", g.s, g.r
    w = lambda variant, make, n=4, lead="": g.wrap(P, variant, make, n, lead)
    w("openai_sk", lambda: "sk" + "-" + s(ALNUM, 48))
    w("openai_legacy", lambda: "sk" + "-" + s(ALNUM, 20) + "T3Blbk" + "FJ" + s(ALNUM, 20))
    w("openai_proj", lambda: "sk" + "-proj-" + s(SAFE, 64))
    w("anthropic", lambda: "sk" + "-ant-" + "api03-" + s(SAFE, 93) + "AA")
    w("aws_access_key_id_akia", lambda: "AK" + "IA" + s("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567", 16))
    w("aws_access_key_id_asia", lambda: "AS" + "IA" + s("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567", 16))
    for lead in ("aws_secret_access_key = ", "aws_secret_access_key=", "AWS_SECRET_ACCESS_KEY=", "aws secret: "):
        tok = g.mixed(B64, 40)
        g.add(P, "aws_secret_access_key", "aws config for the new server:\n" + lead + tok + "\nregion ap-south-1", tok)
    for pre in ("ghp", "gho", "ghu", "ghs", "ghr"):
        w("github_" + pre, lambda pre=pre: pre + "_" + s(ALNUM, 36), 2)
    w("github_pat", lambda: "github" + "_pat_" + s(ALNUM, 22) + "_" + s(ALNUM, 59))
    w("gitlab_pat", lambda: "gl" + "pat-" + s(SAFE, 20))
    w("slack_bot", lambda: "xo" + "xb-" + g.num(12) + "-" + g.num(13) + "-" + s(ALNUM, 24))
    w("slack_user", lambda: "xo" + "xp-" + g.num(12) + "-" + g.num(12) + "-" + g.num(12) + "-" + s(HEX, 32))
    w("slack_app", lambda: "xa" + "pp-1-A" + s(UPNUM, 10) + "-" + g.num(13) + "-" + s(HEX, 64))
    for _ in range(4):
        tail = "T" + s(UPNUM, 9) + "/B" + s(UPNUM, 10) + "/" + s(ALNUM, 24)
        g.add(P, "slack_webhook", "the alerts webhook is https://hooks.slack" + ".com/services/" + tail + " post there", tail.split("/")[-1])
    w("stripe_secret", lambda: "sk" + "_live_" + s(ALNUM, 24))
    w("stripe_restricted", lambda: "rk" + "_live_" + s(ALNUM, 24))
    w("stripe_webhook", lambda: "wh" + "sec_" + s(ALNUM, 32))
    w("google_api_key", lambda: "AI" + "za" + s(SAFE, 35))
    w("google_oauth_secret", lambda: "GOC" + "SPX-" + s(SAFE, 28))
    w("twilio_api_key", lambda: "SK" + s(HEX, 32))
    for _ in range(4):
        sid, tok = "AC" + s(HEX, 32), s(HEX, 32)
        g.add(P, "twilio_sid_auth_token", "twilio sid " + sid + " and auth token " + tok + " para los sms", [sid, tok])
    w("sendgrid", lambda: "SG" + "." + s(SAFE, 22) + "." + s(SAFE, 43))
    w("telegram_bot", lambda: g.num(r.choice((9, 10))) + ":AA" + s(SAFE, 33))
    for _ in range(2):
        tok = g.num(10) + ":AA" + s(SAFE, 33)
        g.add(P, "telegram_bot_in_url", "curl https://api.telegram.org/bot" + tok + "/getMe", tok.split(":")[1])
    w("discord_bot", lambda: r.choice("MN") + s(ALNUM, 23) + "." + s(SAFE, 6) + "." + s(SAFE, 27))
    for _ in range(4):
        tok = s(SAFE, 68)
        g.add(P, "discord_webhook", "post alerts to https://discord" + ".com/api/webhooks/" + g.num(18) + "/" + tok, tok)
    w("npm", lambda: "npm" + "_" + s(ALNUM, 36))
    w("pypi", lambda: "pypi-" + "AgEIcHlwaS5vcmc" + s(SAFE, 70))
    w("huggingface", lambda: "hf" + "_" + s(string.ascii_letters, 34))
    w("groq", lambda: "gsk" + "_" + s(ALNUM, 52))
    w("replicate", lambda: "r8" + "_" + s(ALNUM, 37))
    w("supabase_service_jwt", lambda: b64url({"alg": "HS256", "typ": "JWT"}) + "." + b64url(
        {"iss": "supabase", "ref": s(string.ascii_lowercase, 20), "role": "service_role", "iat": 1700000000 + r.randrange(10 ** 7)}) + "." + s(SAFE, 43))
    w("supabase_pat", lambda: "sbp" + "_" + s(HEX, 40))
    for lead in ("vercel token ", "VERCEL_TOKEN=", "vercel token: ", "--token "):
        tok = g.mixed(ALNUM, 24)
        g.add(P, "vercel_token", "untuk deploy perlu " + lead + tok, tok)
    for lead in ("CF_API_TOKEN=", "CF_API_TOKEN: ", "CLOUDFLARE_API_TOKEN=", "export CF_API_TOKEN="):
        tok = g.mixed(SAFE, 40)
        g.add(P, "cloudflare_api_token", "for the deploy tool\n" + lead + tok, tok)
    w("digitalocean", lambda: "dop" + "_v1_" + s(HEX, 64))
    w("shopify", lambda: "shp" + "at_" + s(HEX, 32))
    w("mailgun", lambda: "key" + "-" + s(HEX, 32))
    w("postman", lambda: "PM" + "AK-" + s(HEX, 24) + "-" + s(HEX, 34))
    w("linear", lambda: "lin" + "_api_" + s(ALNUM, 40))
    w("notion_secret", lambda: "sec" + "ret_" + s(ALNUM, 43))
    w("notion_ntn", lambda: "nt" + "n_" + s(ALNUM, 46))
    w("figma", lambda: "fi" + "gd_" + s(SAFE, 40))
    for _ in range(3):
        k = g.mixed(SAFE, 32)
        g.add(P, "rpc_alchemy", "rpc: https://eth-mainnet.g.alchemy.com/v2/" + k + " rate limit lag raha", k)
        k = s(HEX, 32)
        g.add(P, "rpc_infura", "use https://mainnet.infura.io/v3/" + k + " for now", k)
        k = "-".join(s(HEX, n) for n in (8, 4, 4, 4, 12))
        g.add(P, "rpc_helius", "the rpc is https://mainnet.helius-rpc.com/?api-key=" + k + " use that one", k)
        k = s(HEX, 40)
        g.add(P, "rpc_quicknode", "wss://fabled-quiet-sun.solana-mainnet.quiknode.pro/" + k + "/", k)
    for lead in ("privy app secret: ", "PRIVY_APP_SECRET=", "privy app secret ", "privy secret is "):
        tok = g.mixed(B58, 88)
        g.add(P, "privy_app_secret", "copied from the dashboard " + lead + tok, tok)
    for _ in range(3):
        pw = g.mixed(ALNUM, 14)
        g.add(P, "database_url_postgres", "DATABASE_URL=postgres://postgres:" + pw + "@db.example.internal:5432/app", pw)
        pw = g.mixed(ALNUM, 16)
        g.add(P, "database_url_postgres_prose", "the db url is postgresql://admin:" + pw + "@10.0.0.12:5432/main?sslmode=require try it", pw)
        pw = g.mixed(ALNUM, 12)
        g.add(P, "database_url_mongodb", "mongodb+srv://appuser:" + pw + "@cluster0.ab1cd.mongodb.net/prod", pw)
        pw = g.mixed(ALNUM, 20)
        g.add(P, "database_url_redis", "redis://default:" + pw + "@redis-12345.example.cloud:6379", pw)
        pw = g.mixed(ALNUM, 20)
        g.add(P, "database_url_redis_no_user", "cache is at redis://:" + pw + "@10.0.0.9:6379/0", pw)


def _pem(g):
    def block(kind, lines, block_word=""):
        body = [g.s(B64, 64) for _ in range(lines)]
        head = "-----BEGIN " + kind + "PRIVATE" + " KEY" + block_word + "-----"
        foot = "-----END " + kind + "PRIVATE" + " KEY" + block_word + "-----"
        return head, body, foot
    for kind in ("RSA ", "EC ", "OPENSSH ", ""):
        head, body, foot = block(kind, 6)
        g.add("pem", (kind.strip().lower() or "pkcs8") + "_multiline", "the server key\n" + "\n".join([head] + body + [foot]) + "\nsave it", body)
        head, body, foot = block(kind, 6)
        g.add("pem", (kind.strip().lower() or "pkcs8") + "_one_line", "key: " + " ".join([head] + body + [foot]) + " ok", body)
        head, body, foot = block(kind, 6)
        g.add("pem", (kind.strip().lower() or "pkcs8") + "_escaped_newlines", '"private_key": "' + "\\n".join([head] + body + [foot]) + '\\n"', body)
        head, body, foot = block(kind, 6)
        g.add("pem", (kind.strip().lower() or "pkcs8") + "_no_end_line", "ye dekh\n" + "\n".join([head] + body), body)
    for _ in range(2):
        head, body, foot = block("PGP ", 8, " BLOCK")
        g.add("pem", "pgp_block", "my gpg key\n" + head + "\n\n" + "\n".join(body) + "\n=" + g.s(B64, 4) + "\n" + foot + "\nthanks", body)
    for _ in range(2):
        head, body, foot = block("RSA ", 6)
        g.add("pem", "body_only_no_header", "pasting the key body\n" + "\n".join(body), body)


def _jwt(g):
    def make():
        return b64url({"alg": "HS256", "typ": "JWT"}) + "." + b64url({"sub": g.num(10), "name": "sam", "iat": 1700000000 + g.r.randrange(10 ** 7)}) + "." + g.s(SAFE, 43)
    g.wrap("jwt", "alone", make, 4)
    for lead in ("Bearer ", "Authorization: Bearer ", "bearer ", "token: "):
        tok = make()
        g.add("jwt", "after_bearer", "put it in the header: " + lead + tok, tok)


def _seeds(g):
    def phrase(n):
        return g.r.sample(BIP39, n)
    forms = {
        "in_sentence": lambda w: "here take these " + " ".join(w) + " and show nobody",
        "in_sentence_es": lambda w: "toma apunta " + " ".join(w) + " no se lo des a nadie",
        "in_sentence_hi": lambda w: "yeh lo " + " ".join(w) + " kisi ko mat dena",
        "in_sentence_id": lambda w: "ini ya " + " ".join(w) + " jangan kasih siapa siapa",
        "after_seed_phrase_cue": lambda w: "seed phrase: " + " ".join(w),
        "after_recovery_cue_hi": lambda w: "mera recovery phrase hai " + " ".join(w) + " ok",
        "after_recovery_cue_es": lambda w: "mi recovery phrase es " + " ".join(w) + " listo",
        "numbered_inline": lambda w: " ".join("%d. %s" % (i + 1, x) for i, x in enumerate(w)),
        "one_per_line": lambda w: "my words:\n" + "\n".join(w),
        "one_per_line_numbered": lambda w: "\n".join("%d) %s" % (i + 1, x) for i, x in enumerate(w)),
        "one_per_line_bulleted": lambda w: "words\n" + "\n".join("- " + x for x in w),
        "blank_line_between_halves": lambda w: " ".join(w[:len(w) // 2]) + "\n\n" + " ".join(w[len(w) // 2:]),
        "grid_spaces": lambda w: "\n".join("   ".join(w[i:i + (3 if len(w) == 12 else 4)]) for i in range(0, len(w), 3 if len(w) == 12 else 4)),
        "grid_tabs": lambda w: "\n".join("\t".join(w[i:i + 4]) for i in range(0, len(w), 4)),
        "grid_numbered": lambda w: "\n".join("  ".join("%2d. %s" % (i + j + 1, x) for j, x in enumerate(w[i:i + 3])) for i in range(0, len(w), 3)),
        "comma_separated": lambda w: "words are " + ", ".join(w),
        "capitalised": lambda w: " ".join(x.capitalize() for x in w),
        "all_caps": lambda w: "PHRASE " + " ".join(x.upper() for x in w),
        "two_lines_of_half": lambda w: " ".join(w[:len(w) // 2]) + "\n" + " ".join(w[len(w) // 2:]),
        "hyphen_joined": lambda w: "phrase " + "-".join(w),
        "crlf_lines": lambda w: "\r\n".join(w),
    }
    for name in forms:
        for n in (12, 12, 24):
            w = phrase(n)
            g.add("seed_phrase", name + ("_24" if n == 24 else "_12"), forms[name](w), w, words=True)
    for sep, name in ((" | ", "pipe_separated"), (" / ", "slash_separated"), (". ", "period_separated")):
        w = phrase(12)
        g.add("seed_phrase", name + "_12", "phrase: " + sep.join(w), w, words=True)
    for _ in range(3):                      # two messages glued by a caller is one text; two separate rows cannot be seen here
        w = phrase(12)
        g.add("seed_phrase", "first_six_then_note_then_six", " ".join(w[:6]) + "\n(baaki neeche)\n" + " ".join(w[6:]), w, words=True)


def _private_keys(g):
    K, s = "private_key", g.s
    g.wrap(K, "evm_hex_0x", lambda: "0x" + s(HEX, 64))
    g.wrap(K, "evm_hex_bare", lambda: s(HEX, 64))
    g.wrap(K, "evm_hex_upper", lambda: s(HEX, 64).upper())
    g.wrap(K, "solana_base58_88", lambda: s(B58, g.r.choice((87, 88))))
    for _ in range(4):
        nums = [g.r.randrange(256) for _ in range(64)]
        for name, text in (("solana_byte_array", "[" + ",".join(map(str, nums)) + "]"),
                           ("solana_byte_array_spaced", "[" + ", ".join(map(str, nums)) + "]"),
                           ("solana_byte_array_multiline", "[\n  " + ",\n  ".join(",".join(map(str, nums[i:i + 16])) for i in range(0, 64, 16)) + "\n]")):
            g.n += 1
            # the secret is the run of numbers: any 12 characters of it left behind is a leak
            g.add(K, name, WRAPS[g.n % len(WRAPS)].format(text), text.strip("[]\n "))
    g.wrap(K, "bitcoin_wif", lambda: g.r.choice("5KL") + s(B58, g.r.choice((50, 51))))
    g.wrap(K, "xprv", lambda: "xp" + "rv" + s(B58, 107))
    g.wrap(K, "sui_bech32", lambda: "suipriv" + "key1" + s(BECH, 58))
    g.wrap(K, "age_secret_key", lambda: "AGE-SECRET" + "-KEY-1" + s(BECH, 58).upper())
    for lead in ("pk: ", "pk - ", "private key ", "tron pk: ", "PRIVATE_KEY=", "priv key is "):
        tok = s(HEX, 64)
        g.add(K, "hex_after_pk_cue", "the wallet " + lead + tok + " keep it safe", tok)


def _card(g, prefix, n):
    body = prefix + g.s(DIGITS, n - 1 - len(prefix))
    return body + luhn_digit(body)


def _cards(g):
    C = "card"
    for _ in range(4):
        v, m, a = _card(g, "4", 16), _card(g, "5" + g.r.choice("12345"), 16), _card(g, g.r.choice(("34", "37")), 15)
        g.add(C, "plain_16", "card number " + v + " here", v)
        g.add(C, "plain_16_no_cue", "use " + m + " for the booking", m)
        sp = " ".join(v[i:i + 4] for i in range(0, 16, 4))
        g.add(C, "groups_of_4_spaces", "charge it to my card " + sp, sp)
        da = "-".join(m[i:i + 4] for i in range(0, 16, 4))
        g.add(C, "groups_of_4_dashes", "card: " + da, da)
        am = a[:4] + " " + a[4:10] + " " + a[10:]
        g.add(C, "amex_15_grouped", "use the amex " + am, am)
        g.add(C, "amex_15_plain", "amex " + a, a)
        cvv = g.num(3)
        while cvv in v:
            cvv = g.num(3)
        g.add(C, "with_cvv", sp + " cvv " + cvv + " name sam carter", [sp, cvv])
        g.add(C, "with_cvv_colon", "card " + v + "\ncvv: " + cvv + "\n", [v, cvv])
        exp = "%02d/%d" % (g.r.randrange(1, 13), g.r.randrange(27, 32))
        g.add(C, "with_expiry", sp + " exp " + exp, [sp, exp])
        g.add(C, "with_expiry_and_cvv", "card " + da + " expiry " + exp + " cvv " + cvv, [da, exp, cvv])
        v19 = _card(g, "62", 19)
        g.add(C, "plain_19_unionpay", "card " + v19, v19)


def _passwords(g):
    P = "password"
    lower = lambda n: g.s(string.ascii_lowercase, n)
    kinds = {"short_lower": lambda: lower(g.r.choice((6, 7, 8))),
             "long_mixed": lambda: g.mixed(ALNUM, 18),
             "with_symbols": lambda: g.mixed(ALNUM, 5) + g.r.choice("@#$%!&*?") + g.mixed(ALNUM, 4) + g.r.choice("@#$%!&*?"),
             "word_and_digits": lambda: g.r.choice(("tiger", "mango", "sunset", "rocket")).capitalize() + "@" + g.num(4)}
    phr = {"password_colon": "password: {}",
           "pass_dash": "pass - {}",
           "pwd_equals": "pwd={}",
           "the_password_is": "the password is {}",
           "wifi_password_no_sep": "wifi password {}",
           "pw_colon": "pw: {}",
           "login_user_slash_pass": "login: sam.carter / {}",
           "hi_password_hai": "password hai {}",
           "hi_ka_password": "netflix ka password {} hai",
           "es_password_es": "el password es {}",
           "id_password_adalah": "password adalah {}",
           "pt_password_e": "o password é {}",
           "passcode_is": "passcode is {}",
           "id_and_password_lines": "id: sam@example.com\npassword: {}",
           "email_then_pass_colon": "sam@example.com pass: {}",
           "passphrase": "passphrase: {}",
           "creds_colon_pair": "creds admin:{}",
           "u_p_short": "u: admin p: {}"}
    for name, form in phr.items():
        for kind, make in kinds.items():
            pw = make()
            g.add(P, name + "/" + kind, form.format(pw), pw)
    for _ in range(4):
        pw = lower(4)
        g.add(P, "four_char_after_colon", "password: " + pw, pw)
        pw = lower(7)
        g.add(P, "bare_no_cue", "try " + pw + " it should work", pw)


def _otp(g):
    O = "otp_2fa"
    six = lambda: g.num(6)
    forms = {"your_otp_is": "your otp is {}", "otp_colon": "OTP: {}", "is_your_verification_code": "{} is your verification code",
             "is_your_otp_for": "{} is your OTP for login to example. do not share it with anyone", "use_code": "use code {} to sign in",
             "verification_code_colon": "Your verification code: {}", "hi_otp": "otp bhej {} aaya hai", "hi_otp_hai": "otp {} hai jaldi daaliye", "es_codigo": "tu codigo es {}", "id_kode": "kode verifikasi {} jangan dibagikan", "fr_code": "votre code de vérification est {}",
             "security_code_is": "your security code is {}", "is_your_code": "{} is your example code", "login_code": "login code {}",
             "one_time_password": "{} is the one time password for your transaction", "otp_for_txn": "OTP for txn of INR 4,500.00 is {}. valid for 10 mins",
             "code_colon": "code: {}"}
    for name, form in forms.items():
        for _ in range(3):
            c = six()
            g.add(O, name, form.format(c), c)
    for _ in range(3):
        c = six()
        g.add(O, "use_code_3_3", "use code " + c[:3] + "-" + c[3:] + " to verify", c[:3] + "-" + c[3:])
        g.add(O, "g_prefix", "G-" + c + " is your Google verification code", c)
        c4 = g.num(4)
        g.add(O, "four_digit_otp", "otp " + c4, c4)
        g.add(O, "bare_six_digits_no_cue", c, c)                 # a bare number has no cue to go by
    for n in (16, 32):
        for _ in range(2):
            k = g.s(B32, n)
            g.add(O, "totp_secret_key_%d" % n, "secret key " + k + " goes in the authenticator", k)
            k = g.s(B32, n)
            g.add(O, "totp_setup_key_colon_%d" % n, "setup key: " + k, k)
            k = g.s(B32, n)
            g.add(O, "totp_otpauth_uri_%d" % n, "otpauth://totp/Example:sam@example.com?secret=" + k + "&issuer=Example", k)
    for _ in range(3):
        k = g.s(B32, 16).lower()
        grouped = " ".join(k[i:i + 4] for i in range(0, 16, 4))
        g.add(O, "totp_grouped_lower", "2fa setup key: " + grouped, grouped)
    for _ in range(3):
        codes = [g.s(LOWNUM, 4) + "-" + g.s(LOWNUM, 4) for _ in range(10)]
        g.add(O, "recovery_codes_abcd_efgh", "github recovery codes:\n" + "\n".join(codes), codes)
        codes = [g.num(4) + " " + g.num(4) for _ in range(10)]
        g.add(O, "backup_codes_1234_5678", "google backup codes\n" + "\n".join("%d. %s" % (i + 1, c) for i, c in enumerate(codes)), codes)
        codes = [g.num(8) for _ in range(8)]
        g.add(O, "backup_codes_8_digit", "backup codes: " + ", ".join(codes), codes)
        codes = [g.mixed(LOWNUM, 10) for _ in range(8)]
        g.add(O, "recovery_codes_10_alnum", "2fa recovery codes\n" + "\n".join(codes), codes)


def _bank(g):
    B = "bank_identity"
    ifsc = lambda: g.s(string.ascii_uppercase, 4) + "0" + g.s(UPNUM, 6)
    for _ in range(3):
        acct = g.num(g.r.choice((11, 12, 14, 16)))
        g.add(B, "account_with_ifsc", "account number " + acct + " ifsc " + ifsc() + " name sam carter", acct)
        acct = g.num(g.r.choice((11, 14, 15)))
        g.add(B, "ac_no_colon", "a/c no: " + acct + "\nIFSC: " + ifsc(), acct)
        acct = g.num(12)
        g.add(B, "hi_account", "mera account no " + acct + " hai isme bhej de", acct)
        g.add(B, "es_cuenta", "mi cuenta es " + acct + " mandalo ahi", acct)
        g.add(B, "id_rekening", "rekening " + acct + " ya kirim ke situ", acct)
        acct = g.num(13)
        g.add(B, "bank_details_block", "Bank: Example Bank\nAccount: " + acct + "\nIFSC: " + ifsc() + "\nBranch: Harbour Road", acct)
        pin = g.num(4)
        g.add(B, "in_upi_pin", "upi pin " + pin + " hai", pin)
        g.add(B, "ke_mpesa_pin", "m-pesa pin " + pin, pin)
        g.add(B, "id_gopay_pin", "gopay pin " + pin + " ya", pin)
        g.add(B, "ph_gcash_pin", "gcash pin is " + pin, pin)
        cpf = "%s.%s.%s-%s" % (g.num(3), g.s(DIGITS, 3), g.s(DIGITS, 3), g.s(DIGITS, 2))
        g.add(B, "br_cpf", "meu cpf: " + cpf, cpf)
        nik = g.num(16)
        g.add(B, "id_nik", "nik saya " + nik, nik)
        nino = "QQ" + g.s(DIGITS, 6) + "C"
        g.add(B, "gb_national_insurance", "my national insurance number is " + nino, nino)
        curp = g.s(string.ascii_uppercase, 4) + g.s(DIGITS, 6) + "M" + g.s(string.ascii_uppercase, 5) + g.s(UPNUM, 1) + g.s(DIGITS, 1)
        g.add(B, "mx_curp", "mi curp es " + curp, curp)
        pin = g.num(6)
        g.add(B, "in_upi_pin_is_6", "my upi pin is " + pin, pin)
        pin = g.num(4)
        g.add(B, "atm_pin_colon", "atm pin: " + pin, pin)
        pin = g.num(4)
        g.add(B, "pin_bare_4", "pin " + pin, pin)
        body = g.r.choice("23456789") + g.s(DIGITS, 10)
        aad = body + verhoeff_digit(body)
        sp = " ".join(aad[i:i + 4] for i in range(0, 12, 4))
        g.add(B, "aadhaar_grouped", "aadhaar " + sp, sp)
        g.add(B, "aadhaar_grouped_no_cue", "take this " + sp + " for the form", sp)
        g.add(B, "aadhaar_plain_with_cue", "aadhar no " + aad, aad)
        g.add(B, "aadhaar_dashes", "uid: " + sp.replace(" ", "-"), sp.replace(" ", "-"))
        g.add(B, "aadhaar_plain_no_cue", "take this " + aad, aad)
        pan = g.s(string.ascii_uppercase, 3) + "P" + g.s(string.ascii_uppercase, 1) + g.num(4) + g.s(string.ascii_uppercase, 1)
        g.add(B, "pan_upper", "pan " + pan, pan)
        g.add(B, "pan_upper_no_cue", "take this " + pan + " for the form", pan)
        g.add(B, "pan_lower_with_cue", "pan card number " + pan.lower(), pan.lower())
        ssn = "%03d-%02d-%04d" % (g.r.randrange(100, 660), g.r.randrange(10, 99), g.r.randrange(1000, 9999))
        g.add(B, "ssn_dashed", "my ssn is " + ssn, ssn)
        g.add(B, "ssn_dashed_no_cue", "its " + ssn + " for the w9", ssn)
        g.add(B, "ssn_plain_with_cue", "ssn " + ssn.replace("-", ""), ssn.replace("-", ""))
        ib = iban("GB", g.s(string.ascii_uppercase, 4) + g.s(DIGITS, 14))
        g.add(B, "iban_plain", "iban " + ib, ib)
        de = iban("DE", g.s(DIGITS, 18))
        sp = " ".join(de[i:i + 4] for i in range(0, len(de), 4))
        g.add(B, "iban_grouped", "IBAN: " + sp + " BIC DEUTDEFF", sp)
        acct = g.num(10)
        g.add(B, "swift_with_account", "swift EXAMGB2L account " + acct, acct)
        pp = g.s(string.ascii_uppercase, 1) + g.num(7)
        g.add(B, "passport_no", "passport no " + pp, pp)
        pp = g.s(string.ascii_uppercase, 1) + g.num(7)
        g.add(B, "passport_number_colon", "Passport Number: " + pp + " expiry 2031", pp)
        rt, acct = g.num(9), g.num(11)
        g.add(B, "us_routing_and_account", "routing " + rt + " account " + acct, [rt, acct])
        rt, acct = g.num(9), g.num(10)
        g.add(B, "us_routing_and_account_labels", "Routing number: " + rt + "\nAccount number: " + acct, [rt, acct])


def _session(g):
    S, s = "session", g.s
    for _ in range(3):
        sid, csrf = s(LOWNUM, 32), s(ALNUM, 32)
        g.add(S, "cookie_header", "cookie: sessionid=" + sid + "; csrftoken=" + csrf, [sid, csrf])
        sid = s(ALNUM, 16)
        g.add(S, "cookie_header_short_value", "Cookie: sid=" + sid + "; theme=dark", sid)
        sid = s(HEX, 24)
        g.add(S, "set_cookie", "Set-Cookie: connect.sid=" + sid + "; Path=/; HttpOnly", sid)
        pw = g.mixed(ALNUM, 10)
        b = base64.b64encode(("sam:" + pw).encode()).decode()
        g.add(S, "authorization_basic", "Authorization: Basic " + b, b)
        g.add(S, "curl_basic_header", "curl -H 'Authorization: Basic " + b + "' https://api.example.com/v1/me", b)
        k = g.mixed(ALNUM, 32)
        g.add(S, "x_api_key_header", "x-api-key: " + k, k)
        k = g.mixed(ALNUM, 20)
        g.add(S, "x_api_key_short", "X-API-Key: " + k, k)
        k = g.mixed(SAFE, 40)
        g.add(S, "curl_bearer", 'curl -s -H "Authorization: Bearer ' + k + '" https://api.example.com/v1/items', k)
        k = g.mixed(ALNUM, 16)
        g.add(S, "curl_bearer_short", 'curl -H "Authorization: Bearer ' + k + '" https://api.example.com', k)
        pw = g.mixed(ALNUM, 10)
        g.add(S, "curl_u_user_pass", "curl -u admin:" + pw + " https://api.example.com/health", pw)
        pw = s(string.ascii_lowercase, 8)
        g.add(S, "curl_user_long_flag", "curl --user deploy:" + pw + " https://api.example.com/health", pw)
        pw = g.mixed(ALNUM, 9)
        g.add(S, "sshpass", "sshpass -p " + pw + " ssh root@10.0.0.4", pw)
        pw = g.mixed(ALNUM, 9)
        g.add(S, "sshpass_quoted", "sshpass -p '" + pw + "' scp a.txt root@10.0.0.4:/tmp", pw)
        pw = g.mixed(ALNUM, 12)
        g.add(S, "mysql_dash_p", "mysql -u root -p" + pw + " -h 10.0.0.5 app", pw)
        a, b2, c, d = g.mixed(ALNUM, 32), g.mixed(ALNUM, 12), g.mixed(SAFE, 40), g.mixed(ALNUM, 10)
        env = "\n".join(["NODE_ENV=production", "PORT=3000", "API_KEY=" + a, "DB_PASSWORD=" + b2, 'JWT_SECRET="' + c + '"', "ADMIN_PASS=" + d])
        g.add(S, "env_paste", "env file:\n" + env, [a, b2, c, d])
        a, b2 = g.mixed(ALNUM, 12), g.mixed(ALNUM, 8)
        g.add(S, "env_paste_odd_names", "SESSION_SECRET_KEY: " + a + "\nSMTP_PASS = " + b2 + "\nNEXTAUTH_SECRET=" + a[::-1], [a, b2, a[::-1]])
        a = g.mixed(ALNUM, 12)
        g.add(S, "env_lowercase_names", "db_password=" + a + "\napi_secret: " + a[::-1], [a, a[::-1]])
        pw = g.mixed(ALNUM, 14)
        g.add(S, "connection_string_kv", "Server=db.example.internal;Database=app;User Id=sa;Password=" + pw + ";", pw)
        pw = g.mixed(ALNUM, 12)
        g.add(S, "connection_string_amqp", "amqps://svc:" + pw + "@b-1234.mq.example.com:5671", pw)
        tok = s(ALNUM, 40)
        g.add(S, "url_token_query", "open https://app.example.com/reset?token=" + tok + "&email=sam@example.com", tok)
        tok = s(HEX, 32)
        g.add(S, "url_access_token_query", "https://graph.example.com/me?access_token=" + tok, tok)
        tok = s(ALNUM, 22)
        g.add(S, "json_token_field", '{"user": "sam", "refresh_token": "' + tok + '"}', tok)
        tok = s(ALNUM, 24)
        g.add(S, "json_client_secret", '{"client_id": "abc", "clientSecret": "' + tok + '"}', tok)


def secrets(seed=7):
    g = Gen(seed)
    for part in (_providers, _pem, _jwt, _seeds, _private_keys, _cards, _passwords, _otp, _bank, _session):
        part(g)
    return g.out


# ---------------------------------------------------------------------------------------------------------------------
# ordinary chat: none of it is a secret

EN = """can you cover my night shift on thursday, i have to take my mother to her appointment
the ward was quiet until four and then three admissions came in at once
remember to hand the cabinet over to the day nurse before you leave
my exam is on monday and i have not opened the second chapter yet
did you take notes in the lecture today, i missed the last twenty minutes
the library closes at nine so let us meet at the study room by six
i opened the shop late today because the delivery van was stuck on the bridge
we are out of the small paper bags again, please order two boxes
a customer left an umbrella by the till, i put it behind the counter
can you pick the kids up from school, my meeting is running over
she has a fever again so i am keeping her home tomorrow
the parents evening is next wednesday at half past five
are we still on for dinner tomorrow
running late, be there in ten
ok
sounds good, let us do it
no worries take your time
what is the plan for the weekend
happy birthday, hope you have a lovely day
who is picking up the cake
need to buy milk and bread on the way home
this song has been stuck in my head all day
the bus was full so i walked the last two stops
good morning, did you sleep well
wait what, when did that happen
remind me to pay the electricity bill before the tenth
did you get home safe
we lost the game but it was close until the last five minutes
going to sleep early today, long day tomorrow
nice
what time does the pharmacy close
i tried the new bakery near the station and the bread was really good
if it rains we can move the picnic indoors and start an hour later
send me the photos from yesterday when you get time
grandma asked if you are coming home for the holidays this year
i can do tuesday or wednesday after four
the taxi is here, coming down now
just saw your message, sorry i was driving all afternoon
the tomatoes are finally ripe, come and take some before the birds do
the vet says the dog needs to rest for a week and no stairs
choir practice moved to the church hall because the school is being painted
i fixed the tap in the kitchen but the one in the bathroom still drips
my train is at six in the morning so i need to leave by five
the neighbours are having a party on saturday and we are all invited
thanks for the lift yesterday, i would have missed the ferry
the roof leaked again last night, i put a bucket under it
can you check the oven, i think i left it on
he got his driving licence on the second try
the rent goes up next month so we should talk about the budget
turn left after the post office and it is the third house with a blue gate
my knee hurts when i climb the stairs so no football for me this week
we planted the beans too early and the frost got them
the washing machine is making that noise again
lunch is in the fridge, just warm it for two minutes
see you at the market on sunday
i left my glasses at your place, can you bring them tomorrow
call me when you are free
the baby finally slept through the night
she got the job at the clinic and starts in march
the food was lovely, we should go back with everyone next month""".split("\n")

HI = """kal subah school ki meeting hai aap aa jaiyega
dawai kha li aapne ya phir bhool gaye
dukaan aaj jaldi band karni padegi bijli nahi hai
bachon ko school se main le aaunga tum aaram karo
aaj khana kya banau koi batao
barish ho rahi hai chhata le kar jana
papa ki tabiyat ab pehle se behtar hai
kal shaam ko mandir chalenge sab log
sabzi wale se tamatar aur pyaaz le aana
meri pariksha agle hafte hai dua karna
train do ghante late hai station par baitha hun
doodh wala aaj nahi aaya kya
ghar pahunch kar phone kar dena
didi ki shaadi ki taiyari chal rahi hai
aaj khet mein paani dena hai subah jaldi uthna
chai bana di hai aa jao sab
bijli ka bill is mahine zyada aaya hai
nani ne tumhare liye laddu bheje hain
kal chutti hai to subah der tak soenge
darzi ne kaha kapde shaniwar tak tayyar ho jayenge
bus stand par milte hain paanch baje
aaj clinic mein bahut bheed thi
kitab wapas kar dena library band hone se pehle
mummy pooch rahi hain khana khaya ya nahi
gaadi ka tyre puncture ho gaya thoda late ho jaunga
aap kaise hain bahut din ho gaye baat kiye
mausam achha hai chalo park chalte hain
kiraya kal de dunga makaan malik ko bol dena
match dekha kal raat ka kya khel tha
theek hai phir kal milte hain""".split("\n")

ES = """puedes cubrir mi turno del jueves tengo que llevar a mi madre al medico
la tienda abre tarde hoy porque el reparto se retraso
recoge a los ninos del colegio que yo no llego
manana tengo examen y no he abierto el libro
hoy hace mucho calor mejor no salgas
la abuela pregunta si vienes a comer el domingo
se nos acabo el pan compra dos barras al volver
el autobus venia lleno asi que vine andando
ya regue las plantas del balcon
el medico dice que repose una semana
quedamos en la plaza a las seis
la lavadora hace otra vez ese ruido
gracias por llevarme ayer casi pierdo el tren
el nino ya duerme toda la noche
manana no hay clase es fiesta
me dejas los apuntes de hoy que falte
la farmacia de la esquina cierra a las nueve
hay que pagar la luz antes del dia diez
los tomates del huerto ya estan maduros
el ensayo del coro es en el salon de la iglesia
llego en diez minutos guardame sitio
que tal el partido de anoche
feliz cumpleanos que tengas un buen dia
la comida esta en la nevera calientala dos minutos
escribeme cuando llegues a casa
vale nos vemos el sabado en el mercado
el perro no puede subir escaleras esta semana
se me olvidaron las gafas en tu casa
aprobo el carnet de conducir a la segunda
buenos dias que tal has dormido""".split("\n")

ID = """bisa gantikan jaga malam saya hari kamis saya harus antar ibu ke dokter
warung buka agak siang hari ini karena kiriman telat
tolong jemput anak anak dari sekolah ya
besok saya ujian dan belum baca bab dua
hari ini panas sekali jangan keluar dulu
nenek tanya kamu pulang lebaran tahun ini atau tidak
beras di rumah habis beli dua kilo ya
busnya penuh jadi saya jalan kaki
tanaman di teras sudah saya siram
kata dokter harus istirahat seminggu
kita ketemu di alun alun jam enam
mesin cucinya bunyi lagi
terima kasih tumpangannya kemarin hampir ketinggalan kereta
si kecil akhirnya tidur nyenyak semalaman
besok sekolah libur
pinjam catatan kuliah hari ini dong saya tadi tidak masuk
apotek di pojok tutup jam sembilan
listrik harus dibayar sebelum tanggal sepuluh
tomat di kebun sudah matang ambil saja
latihan paduan suara pindah ke aula
sepuluh menit lagi sampai tolong jagain tempat
gimana pertandingan semalam
selamat ulang tahun semoga sehat selalu
makanan ada di kulkas panaskan dua menit
kabari kalau sudah sampai rumah
oke sampai ketemu hari sabtu di pasar
anjingnya belum boleh naik tangga minggu ini
kacamata saya ketinggalan di rumahmu
dia lulus ujian sim di percobaan kedua
selamat pagi tidurnya nyenyak""".split("\n")

FR = """tu peux prendre ma garde de jeudi je dois emmener ma mere chez le medecin
la boutique ouvre plus tard aujourd'hui la livraison a du retard
tu peux recuperer les enfants a l'ecole
j'ai un examen demain et je n'ai pas ouvert le livre
il fait tres chaud aujourd'hui ne sors pas
mamie demande si tu viens manger dimanche
il n'y a plus de pain prends deux baguettes en rentrant
le bus etait plein alors je suis venue a pied
j'ai arrose les plantes du balcon
le medecin dit de se reposer une semaine
on se retrouve sur la place a dix-huit heures
la machine a laver refait ce bruit
merci de m'avoir deposee hier j'ai failli rater le train
le petit fait enfin ses nuits
demain il n'y a pas ecole c'est ferie
tu me pretes tes notes du cours j'etais absent
la pharmacie du coin ferme a vingt et une heures
il faut payer l'electricite avant le dix
les tomates du jardin sont mures
la repetition de la chorale est dans la salle paroissiale
j'arrive dans dix minutes garde moi une place
alors le match d'hier soir
joyeux anniversaire je te souhaite une belle journee
le repas est au frigo rechauffe le deux minutes
ecris moi quand tu es rentree
d'accord on se voit samedi au marche
le chien ne doit pas monter les escaliers cette semaine
j'ai oublie mes lunettes chez toi
il a eu son permis au deuxieme essai
bonjour tu as bien dormi""".split("\n")

DE = """kannst du meinen dienst am donnerstag uebernehmen ich muss meine mutter zum arzt bringen
der laden macht heute spaeter auf die lieferung kommt nicht durch
holst du die kinder von der schule ab
ich habe morgen pruefung und das buch noch nicht aufgeschlagen
heute ist es sehr heiss bleib lieber drinnen
oma fragt ob du am sonntag zum essen kommst
das brot ist alle bring zwei mit wenn du kommst
der bus war voll also bin ich gelaufen
die blumen auf dem balkon habe ich gegossen
der arzt sagt eine woche ruhe
wir treffen uns um sechs am marktplatz
die waschmaschine macht wieder dieses geraeusch
danke fuers mitnehmen gestern ich haette den zug verpasst
die kleine schlaeft endlich durch
morgen ist schulfrei
gibst du mir deine mitschrift von heute ich war nicht da
die apotheke an der ecke schliesst um neun
der strom muss vor dem zehnten bezahlt werden
die tomaten im garten sind reif
die chorprobe ist im gemeindesaal
bin in zehn minuten da halt mir einen platz frei
wie war das spiel gestern abend
alles gute zum geburtstag hab einen schoenen tag
das essen steht im kuehlschrank zwei minuten warm machen
schreib mir wenn du zu hause bist
gut dann sehen wir uns am samstag auf dem markt
der hund darf diese woche keine treppen steigen
ich habe meine brille bei dir vergessen
er hat den fuehrerschein beim zweiten mal bestanden
guten morgen hast du gut geschlafen""".split("\n")

PT = """voce pode cobrir meu plantao de quinta preciso levar minha mae ao medico
a loja abre mais tarde hoje a entrega atrasou
pega as criancas na escola por favor
tenho prova amanha e ainda nao abri o livro
hoje esta muito quente melhor nao sair
a vovo perguntou se voce vem almocar no domingo
acabou o pao traz dois quando voltar
o onibus estava cheio entao vim a pe
ja reguei as plantas da varanda
o medico disse para descansar uma semana
a gente se encontra na praca as seis
a maquina de lavar esta fazendo aquele barulho de novo
obrigada pela carona ontem quase perdi o trem
o bebe finalmente dormiu a noite toda
amanha nao tem aula e feriado
me empresta as anotacoes de hoje eu faltei
a farmacia da esquina fecha as nove
tem que pagar a luz antes do dia dez
os tomates da horta ja estao maduros
o ensaio do coral e no salao da igreja
chego em dez minutos guarda um lugar
como foi o jogo de ontem
feliz aniversario tenha um otimo dia
a comida esta na geladeira esquenta dois minutos
me avisa quando chegar em casa
combinado a gente se ve sabado na feira
o cachorro nao pode subir escada essa semana
esqueci meus oculos na sua casa
ele tirou a carteira de motorista na segunda tentativa
bom dia dormiu bem""".split("\n")

LONG = """please bring your laptop charger phone wallet keys water bottle jacket umbrella snacks tickets and the camera for the trip
we spent the whole evening walking around the old town looking at small shops eating street food and taking photos of everything
my week looks like this monday gym tuesday office wednesday dentist thursday client call friday dinner with family saturday rest
the guide talked about rivers bridges mills churches markets castles gardens orchards harbours and the old wall for two whole hours
the kids played outside all afternoon then came home tired hungry muddy and happy and fell asleep right after dinner
bhai sun kal subah jaldi uth jana phir gym phir office phir shaam ko doctor ke paas jana hai mat bhoolna
every morning she wakes early makes coffee reads the news waters the plants walks the dog and then starts work
this spring we fixed the fence painted the shed cleared the gutters trimmed the hedge and planted beans peas and carrots along the wall
i need to remember passport tickets hotel booking cash cards charger adapter medicines and the gift for your sister
last night we watched three episodes ordered pizza argued about the ending and then fell asleep on the couch again
everyone please bring your own plate cup spoon and blanket on saturday and tell me today if you need a lift there
when you reach the station take the east exit cross the road walk past the bakery and wait near the yellow gate""".split("\n")

# everyday chat from varied lives (a nurse, a student, a shopkeeper, a parent, a neighbour), thirty lines in each language,
# typed the way people type (mostly without accents). each must come through the scrubber untouched, and none is the main one
CHAT = {"de": DE, "es": ES, "fr": FR, "hi": HI, "id": ID, "pt": PT}

# twelve or more short lower-case words with no everyday joining word: a seed phrase looks exactly like this
TELEGRAPHIC = """send money today via bank transfer then call mom about dinner plans tonight okay
need eggs milk bread rice sugar salt butter cheese onion tomato potato garlic ginger
monday gym tuesday office wednesday dentist thursday client friday dinner saturday rest sunday family
bring laptop charger phone wallet keys water bottle jacket umbrella snacks tickets camera
chores sweep kitchen then hallway then stairs then porch then yard then shed then garage
tags garden recipes cycling pottery travel books music photos hiking baking chess""".split("\n")

LYRICS = """la la la la la la la la la la la la la la
tum tum tum ta ra ra tum tum ta ra ra again
row row row the kettle down the garden lane
hum hum hum along the allotment wall tonight
tick tock tick tock goes the kitchen clock at nine
dum dum dum goes the rain on the tin roof
hey ho hey ho the bread is in the oven now
round and round and round the pond we go
clap clap clap for the cat upon the mat
zoom zoom zoom said the bee to the broom""".split("\n")

GROCERY = "milk eggs bread rice sugar salt butter cheese onion tomato potato garlic ginger lemon apple banana mango grapes carrot spinach paneer curd flour oil tea coffee".split()
# first names from six regions, twelve each. NAMES takes them turn and turn about, so a name drawn at random is as likely
# to come from one region as from another and no place is the one the tests know
NAMES_BY_REGION = {
    "east africa": "amina baraka wanjiru otieno zawadi juma neema kamau achieng mwangi fatuma kiprop".split(),
    "east asia": "haruto yui ren sakura mei jun hana kenji aiko taro nao rin".split(),
    "iberia and latin america": "lucia mateo sofia diego valentina javier camila andres elena pablo carmen luis".split(),
    "south asia": "ravi priya arjun meera kabir ananya rohan sneha vikram pooja aditya nisha".split(),
    "southeast asia": "budi siti agus dewi rizky putri andi wulan joko rina fajar ayu".split(),
    "western europe": "lukas emma noah lea felix clara jonas marie paul nina theo anna".split()}
NAMES = [n for turn in zip(*(NAMES_BY_REGION[k] for k in sorted(NAMES_BY_REGION))) for n in turn]
TAGS = "garden recipes cycling pottery travel books music photos hiking baking chess weather school ferry builders".split()


def benign(seed=11):
    r = random.Random(seed)
    out = []
    s = lambda a, n: "".join(r.choice(a) for _ in range(n))
    num = lambda n: r.choice("123456789") + s(DIGITS, n - 1)
    add = lambda kind, text: out.append({"kind": kind, "text": text})
    uuid = lambda: "-".join(s(HEX, n) for n in (8, 4, 4, 4, 12))
    slug = lambda: "-".join(r.sample(TAGS + GROCERY, r.randrange(2, 5)))

    for i in range(220):
        add("prose_english", EN[i % len(EN)] if i < len(EN) else r.choice(EN) + ". " + r.choice(EN))
    for code in sorted(CHAT):                   # every language's chat in the same measure, kinds named by language code
        for i in range(120):
            add("prose_" + code, CHAT[code][i % len(CHAT[code])] if i < len(CHAT[code]) else r.choice(CHAT[code]) + " " + r.choice(CHAT[code]))
    for i in range(80):
        add("prose_long_12plus_words", LONG[i % len(LONG)] if i < len(LONG) else r.choice(LONG) + " " + r.choice(EN))
    for i in range(18):
        add("telegraphic_12plus_no_joining_words", TELEGRAPHIC[i % len(TELEGRAPHIC)])
    for i in range(40):
        add("lyrics", LYRICS[i % len(LYRICS)] if i < len(LYRICS) else r.choice(LYRICS) + "\n" + r.choice(LYRICS))
    for _ in range(100):                        # money the way ten places write it, one way each
        add("price", r.choice(["its {} rupees", "paid ${} for it", "son {} euros", "rp {} saja", "R$ {} por mes", "£{} all in", "{} yen desu", "{} pesos y ya", "KSh {} tu", "total {} francs"]).format(
            r.choice(["%d" % r.randrange(10, 99999), "{:,}".format(r.randrange(1000, 9999999)), "%d.%02d" % (r.randrange(1, 9999), r.randrange(100)), "%dk" % r.randrange(1, 900)])))
    for _ in range(80):
        y, mo, d = r.randrange(2019, 2028), r.randrange(1, 13), r.randrange(1, 29)
        add("date", r.choice(["%04d-%02d-%02d" % (y, mo, d), "%02d/%02d/%04d" % (d, mo, y), "%02d-%02d-%04d" % (d, mo, y), "on %d %s %d" % (d, r.choice(["jan", "feb", "march", "nov"]), y),
                              "%04d-%02d-%02dT%02d:%02d:%02dZ" % (y, mo, d, r.randrange(24), r.randrange(60), r.randrange(60)), "due %02d.%02d.%02d" % (d, mo, y % 100),
                              "%02d/%02d/%04d %02d:%02d UTC" % (d, mo, y, r.randrange(24), r.randrange(60)), "from %02d/%02d to %02d/%02d" % (d, mo, d, mo % 12 + 1)]))
    d = lambda n: s(DIGITS, n)
    phones = [lambda: "+1 (415) 555-01" + d(2), lambda: "+44 20 7946 0" + d(3), lambda: "+49 30 " + d(7), lambda: "+52 55 %s %s" % (d(4), d(4)), lambda: "+55 11 9%s-%s" % (d(4), d(4)),
              lambda: "+62 812-%s-%s" % (d(4), d(4)), lambda: "+81 90-%s-%s" % (d(4), d(4)), lambda: "+91 9%s %s" % (d(4), d(5)), lambda: "+254 7%s %s" % (d(2), d(6))]
    says = ["call me on {}", "{}", "whatsapp {}", "mi numero es {}", "nomor saya {}", "mera number {} hai", "mon numero c'est {}", "meine nummer ist {}", "meu numero e {}"]
    for i in range(90):                         # nine countries' numbers, each as often as the next, said in as many ways
        add("phone", says[(i // len(phones)) % len(says)].format(phones[i % len(phones)]()))
    def ref(n):                                 # a long reference number that is not, by chance, a valid card number
        while True:
            v = num(n)
            if n < 13 or luhn_digit(v[:-1]) != v[-1]:
                return v
    for _ in range(60):
        add("order_id", r.choice(["order #{}".format(num(r.choice((8, 10, 12)))), "shop order 40%s-%s-%s" % (s(DIGITS, 1), s(DIGITS, 7), s(DIGITS, 7)), "order id ORD" + ref(18), "food order " + num(12),
                                  "ticket INC" + num(7), "invoice INV-2026-" + num(5), "ref no " + ref(16), "payment id " + ref(13), "booking id BKG" + ref(14), "ts " + "17" + s(DIGITS, 11)]))
    for _ in range(40):
        add("tracking_number", r.choice(["tracking 1Z" + s(UPNUM, 6) + num(10), "awb " + num(11), "post RR" + num(9) + r.choice(("BR", "DE", "GB", "IN", "JP", "KE")), "courier " + ref(14), "parcel " + num(12),
                                         "parcel " + ref(15), "shipment D" + num(8)]))
    for _ in range(30):
        add("flight_pnr", r.choice(["pnr " + s(UPNUM, 6), "PNR: " + s(string.ascii_uppercase, 6) + " indigo 6E " + num(4), "irctc pnr " + num(10), "booking ref " + s(UPNUM, 6) + " seat 14C"]))
    for _ in range(30):
        add("tx_hash_redacted_on_purpose", r.choice(["tx 0x" + s(HEX, 64), "https://etherscan.io/tx/0x" + s(HEX, 64), "hash: " + s(HEX, 64)]))
    for _ in range(60):
        a = "0x" + s(HEX + "ABCDEF", 40)
        add("evm_address", r.choice(["send to {}", "{}", "ca: {}", "my wallet {}", "https://etherscan.io/address/{}", "the address is {} fyi", "token {}"]).format(a))
    for _ in range(40):
        a = s(B58, r.choice((43, 44)))
        add("solana_address_after_cue", r.choice(["ca: {}", "ca {}", "mint address {}", "wallet: {}", "contract {}", "https://solscan.io/token/{}", "token {}"]).format(a))
    for _ in range(100):
        add("url", r.choice(["https://example.com/{}/{}".format(slug(), slug()), "https://www.example.org/blog/2026/11/{}".format(slug()), "check https://docs.example.com/guides/{}#setup".format(slug()),
                             "https://example.com/search?q={}&page={}&sort=new".format(r.choice(TAGS), r.randrange(1, 40)), "https://github.com/example/{}/pull/{}".format(slug(), r.randrange(1, 4000)),
                             "https://github.com/example/{}/blob/main/src/{}.ts#L{}".format(slug(), r.choice(TAGS), r.randrange(1, 900)), "https://shop.example.com/dp/B0{}".format(s(UPNUM, 8)),
                             "https://maps.example.com/place/{}/@{}.{:04d},{}.{:04d},17z".format(slug(), r.randrange(-60, 60), r.randrange(10000), r.randrange(-170, 170), r.randrange(10000)), "https://news.example.com/2026/11/21/{}-{}.html".format(slug(), slug()),
                             "https://en.wikipedia.org/wiki/{}_{}".format(r.choice(NAMES).capitalize(), r.choice(TAGS)), "https://t.me/{}/{}".format(r.choice(TAGS) + "chat", r.randrange(1, 99999)),
                             "https://example.vercel.app/{}?utm_source=twitter&utm_medium=social&utm_campaign={}".format(slug(), slug()), "https://etherscan.io/address/0x{}".format(s(HEX, 40)),
                             "https://www.linkedin.com/in/{}-{}-{}/".format(r.choice(NAMES), r.choice(NAMES), s(LOWNUM, 8)), "https://example.substack.com/p/{}".format(slug())]))
    for _ in range(30):
        vid = s(SAFE, 11)
        add("youtube_link", r.choice(["https://www.youtube.com/watch?v={}", "https://youtu.be/{}", "https://youtu.be/{}?t=120", "https://www.youtube.com/watch?v={}&list=PL" + s(SAFE, 16)]).format(vid))
    for _ in range(20):
        add("google_docs_link", r.choice(["https://docs.google.com/document/d/{}/edit", "https://docs.google.com/spreadsheets/d/{}/edit#gid=0", "https://drive.google.com/file/d/{}/view"]).format(s(SAFE, r.choice((33, 44)))))
    for _ in range(40):
        add("git_commit_hash", r.choice(["fixed in {}".format(s(HEX, 7)), "commit {}".format(s(HEX, 40)), "revert {} pls".format(s(HEX, 8)), "git checkout {}".format(s(HEX, 40)), "{} chore: bump deps".format(s(HEX, 7))]))
    for _ in range(30):
        add("uuid_bare", r.choice(["user id {}", "{}", "request {} failed", "session {} timed out"]).format(uuid()))
    for _ in range(40):
        add("uuid_in_url", r.choice(["https://app.example.com/orders/{}", "https://example.com/u/{}/settings", "see https://app.example.com/runs/{}?tab=logs", "https://claude.ai/chat/{}"]).format(uuid()))
    for _ in range(50):
        add("file_path", r.choice(["/Users/sam/Sites/{}/src/{}.py".format(slug(), r.choice(TAGS)), "~/Downloads/{}_final_v{}.pdf".format(slug(), r.randrange(1, 9)), "src/components/{}/{}.tsx".format(r.choice(TAGS).capitalize(), r.choice(TAGS).capitalize()),
                                   "C:\\Users\\sam\\Documents\\{}.docx".format(slug()), "./node_modules/.bin/{}".format(r.choice(TAGS)), "/var/log/nginx/access.log.{}".format(r.randrange(1, 30)),
                                   "open ~/Library/Application Support/{}/config.json".format(r.choice(TAGS).capitalize()), "tests/test_{}.py::Test{}::test_{}_{}".format(r.choice(TAGS), r.choice(TAGS).capitalize(), r.choice(TAGS), r.choice(TAGS))]))
    code = ["const res = await fetch(url, { headers })", "git checkout -b fix/login-redirect", "npm install @tanstack/react-query", "def scrub(text): return text",
            "SELECT id, name FROM users WHERE created_at > now() - interval '7 days'", "docker run -p 3000:3000 app:latest", "export NODE_ENV=production", "const apiKey = process.env.API_KEY",
            "const token = await getToken()", "password_hash = bcrypt.hashpw(password, salt)", "if (!user.password) throw new Error('missing')", "for i in range(len(items)): print(items[i])",
            "pip install requests==2.31.0", "kubectl get pods -n production", "console.log(JSON.stringify(data, null, 2))", "import { useState, useEffect } from 'react'",
            "git rebase -i HEAD~3", "chmod +x scripts/deploy.sh && ./scripts/deploy.sh", "const { data, error } = await supabase.from('users').select('*')", "token = os.environ['API_TOKEN']",
            "auth: { persistSession: false }", "max_tokens=1024, temperature=0.2", "tokens_used: 15234, cost: 0.42", "border-radius: 12px; padding: 16px 24px;", "x = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]",
            "ssh -i ~/.ssh/id_ed25519 deploy@10.0.0.4", "author: sam carter", "secret santa list is ready", "passport renewal appointment is on monday", "pincode 123456", "pin code: 000001", "postcode 00000", "postal code 000-0000", "zip 99999-0000",
            "keyboard shortcut is cmd+shift+p", "the stall opened with 90 jars", "seed round closed at 2m", "git log --oneline | head -20", "curl -s https://api.example.com/v1/health | jq .status"]
    for i in range(72):
        add("code_snippet", code[i % len(code)])
    for _ in range(30):
        add("version_string", r.choice(["v%d.%d.%d" % (r.randrange(9), r.randrange(30), r.randrange(99)), "node v20.%d.%d" % (r.randrange(20), r.randrange(9)), "python 3.%d.%d" % (r.randrange(8, 15), r.randrange(12)),
                                        "react@18.3.1", "macOS 15.%d (24A%d)" % (r.randrange(6), r.randrange(100, 999)), "build 2026.11.%d-rc%d" % (r.randrange(1, 30), r.randrange(1, 5)), "Chrome/131.0.%d.%d" % (r.randrange(9999), r.randrange(200))]))
    for _ in range(30):
        add("image_name", r.choice(["IMG_2026%02d%02d_%06d.jpg" % (r.randrange(1, 13), r.randrange(1, 29), r.randrange(240000)), "WhatsApp Image 2026-11-%02d at %02d.%02d.%02d.jpeg" % (r.randrange(1, 29), r.randrange(24), r.randrange(60), r.randrange(60)),
                                    "DSC0%04d.JPG" % r.randrange(9999), "Screenshot 2026-11-%02d at %d.%02d.%02d PM.png" % (r.randrange(1, 29), r.randrange(1, 12), r.randrange(60), r.randrange(60)),
                                    "photo_%s_y.jpg" % num(19), "%s.png" % s(ALNUM, 24), "PXL_2026%02d%02d_%09d.mp4" % (r.randrange(1, 13), r.randrange(1, 29), r.randrange(10 ** 9))]))
    for _ in range(50):
        add("tweet_url", r.choice(["https://x.com/{}/status/{}", "https://twitter.com/{}/status/{}?s=20", "https://x.com/{}/status/{}/photo/1", "lol https://x.com/{}/status/{}"]).format(r.choice(NAMES) + r.choice(["", "_writes", "_01", "99"]), r.choice("12") + s(DIGITS, 18)))
    for _ in range(50):
        add("email", r.choice(["{}@example.com", "mail me at {}@example.org", "{}.{}@example.net", "cc {}@example.com and {}@example.com", "from: {} <{}@example.com>"]).format(r.choice(NAMES), r.choice(NAMES)))
    for _ in range(50):                         # everyday counting: weights, distances, scores, shares of a bill
        add("amounts", r.choice(["3 lots at 125 each, 2 held back, the rest on friday", "bought %d kg at %d a kilo" % (r.randrange(1, 50), r.randrange(2, 300)), "%.1f km in %d minutes" % (r.random() * 20, r.randrange(5, 120)),
                                 "%d%% off until sunday" % r.randrange(5, 70), "booking fee 7: 4 to the hall, 3 to the band", "score %d to %d at half time" % (r.randrange(0, 5), r.randrange(0, 5)),
                                 "%d ml of milk and %d g of flour" % (r.randrange(50, 900), r.randrange(50, 900)), "room %d, floor %d" % (r.randrange(1, 400), r.randrange(1, 30)),
                                 "%d steps today, %d yesterday" % (r.randrange(500, 20000), r.randrange(500, 20000)), "class of %d, %d passed" % (r.randrange(20, 40), r.randrange(5, 20))]))
    zones = ("AEST", "BRT", "CET", "EAT", "IST", "JST", "PST", "UTC", "WIB")
    for i in range(54):                         # nine time zones, each as often as the next
        z, z2 = zones[i % len(zones)], zones[(i + 4) % len(zones)]
        add("time", r.choice(["at %d:%02d pm" % (r.randrange(1, 13), r.randrange(60)), "%02d:%02d %s" % (r.randrange(24), r.randrange(60), z), "call at %d tomorrow" % r.randrange(1, 12), "%d-%d pm works" % (r.randrange(1, 6), r.randrange(6, 12)),
                              "in %d mins" % r.randrange(1, 60), "eta %02d:%02d:%02d" % (r.randrange(24), r.randrange(60), r.randrange(60)), "%dam %s / %d:30pm %s" % (r.randrange(1, 12), z.lower(), r.randrange(1, 12), z2.lower())]))
    for _ in range(60):
        pool, n = r.choice([GROCERY, NAMES, TAGS]), r.choice((4, 6, 8, 13, 15))
        items = r.sample(pool, min(n, len(pool)))
        add("comma_list_short" if len(items) < 12 else "comma_list_12plus_words", r.choice(["{}", "list: {}", "invite {}"]).format(", ".join(items)))
    return out


MUST_SURVIVE = ("prose_english",) + tuple("prose_" + code for code in sorted(CHAT)) + ("evm_address", "url", "phone", "date", "price", "uuid_in_url", "solana_address_after_cue", "email", "time", "amounts")


def leaks(item, out):
    """True when part of the secret can still be read in `out`: the whole of a short one, any 12 characters in a row of a
    long one, or any 4 phrase words in a row of a seed phrase."""
    parts = item["secret"] if isinstance(item["secret"], list) else [item["secret"]]
    if item.get("words"):
        seen = re.findall(r"[a-z]+", out.lower())
        want = [w.lower() for w in parts]
        runs = set(tuple(want[i:i + 4]) for i in range(len(want) - 3))
        return any(tuple(seen[i:i + 4]) in runs for i in range(len(seen) - 3))
    for p in parts:
        if len(p) <= 12:
            if p in out:
                return True
        elif any(p[i:i + 12] in out for i in range(len(p) - 11)):
            return True
    return False


def catch_table(scrub, items):
    """{class: {variant: [caught, total]}}"""
    table = {}
    for it in items:
        cell = table.setdefault(it["class"], {}).setdefault(it["variant"], [0, 0])
        cell[1] += 1
        cell[0] += not leaks(it, scrub(it["text"]))
    return table


def rates(table):
    """{class: (caught, total)}"""
    return dict((c, (sum(v[0] for v in vs.values()), sum(v[1] for v in vs.values()))) for c, vs in table.items())


def fp_table(scrub, lines):
    """{kind: [changed, total]}"""
    table = {}
    for ln in lines:
        cell = table.setdefault(ln["kind"], [0, 0])
        cell[1] += 1
        cell[0] += scrub(ln["text"]) != ln["text"]
    return table


def slow_inputs(seed=3):
    """Text that could make a careless pattern crawl. Each must scrub in well under a second."""
    r = random.Random(seed)
    lines = [b["text"] for b in benign()]
    big = "\n".join(lines)
    while len(big) < 200000:
        big += "\n" + big
    words = " ".join(r.choice(BIP39) for _ in range(50000))
    return {"benign_200kb": big[:200000],
            "50000_short_words": words,
            "50000_short_words_one_per_line": words.replace(" ", "\n"),
            "100kb_digits": "".join(r.choice(DIGITS) for _ in range(100000)),
            "100kb_digit_groups": " ".join("".join(r.choice(DIGITS) for _ in range(4)) for _ in range(20000)),
            "100kb_a_space": "a " * 50000,
            "100kb_one_letter": "a" * 100000,
            "100kb_hex": "".join(r.choice(HEX) for _ in range(100000)),
            "100kb_dashes": "-" * 100000,
            "100kb_begin_lines": "-----BEGIN " * 9000,
            "100kb_commas_numbers": "[" + ",".join(str(r.randrange(256)) for _ in range(30000)),
            "100kb_cookie_pairs": "cookie: " + "; ".join("k%d=v%d" % (i, i) for i in range(9000)),
            "100kb_password_words": "password " * 11000,
            "100kb_otp_words": "otp code " * 11000,
            "100kb_base64_line": "".join(r.choice(B64) for _ in range(100000)),
            "100kb_key_equals": "A_KEY=" * 16000,
            "100kb_colons": "a:b@" * 25000,
            "100kb_slashes": "ab/" * 33000,
            "100kb_password_no_spaces": "password" * 12500,
            "100kb_env_name_parts": "A_" * 50000 + "KEY",
            "100kb_curl_words": "curl " * 20000,
            "100kb_cookie_cues": "cookie: " * 12500,
            "100kb_login_cues": "login: ab " * 10000,
            "100kb_account_cues": "account no 1234 " * 6000,
            "100kb_otp_numbers": "otp 1234 " * 11000,
            "100kb_backup_codes_cues": "backup codes abcd-1234 " * 4300,
            "100kb_pan_cues": "pan " * 25000,
            "100kb_url_creds": "://a:" * 20000,
            "100kb_eleven_words_then_stop": ("apple banana cactus danger eagle fabric galaxy harbor island jacket ladder it " * 1400),
            "100kb_hyphen_words": "-".join(r.choice(BIP39) for _ in range(16000)),
            "100kb_words_wide_gaps": ("apple" + " " * 200) * 490,
            "100kb_blank_indented_lines": ("apple\n   \n   \n   ") * 6000,
            "100kb_dotted_words": "abc.def." * 12500,
            "100kb_brackets": "[1," * 33000,
            "100kb_uppercase": "ABCPE1234F GB82WEST " * 5000}
