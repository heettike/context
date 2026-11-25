"""A page behind the owner's own sign-in, as a source: a bookmarking app, a read-later list, a notes app.

No password is typed or kept and no sign-in is automated. The page is read only through the browser the owner is
already signed in to, by the `context` extension (ctx/bridge.py), and only on a site the owner allowed in the extension's
own popup. What reads the page is a RECIPE: json, not code.

    {"url": "https://app.example.com/saved", "wait_for": "<css>", "list_selector": "<css>",
     "fields": {"title": "<css>", "link": "<css>@href", "text": "<css>", "date": "<css>@datetime", "tags": "<css>"},
     "next": {"kind": "scroll"} | {"kind": "param", "param": "page"}, "max_items": 200, "id_from": "link"}
    or, when the page loads its list from its own json address:
    {"url": ..., "api": {"url_pattern": "/api/saves?page={page}", "items_path": "data.items", "fields": {"title": "name", "link": "url"}, "max_pages": 5}}

A field is "<css>" (the text of that element inside the item), "<css>@attr", "@attr" (on the item itself) or "" (the
item's own text). The extension runs a recipe with querySelectorAll and nothing else; validate() below refuses anything
that is not a selector, not the same site, or not a GET. There is no "click" step: a click can change things.

`connect webapp:<url>`:
  1. a public way is tried first (the page's feed, or the page itself when it shows its text to anyone) and used if it works
  2. the extension opens the page in a background tab and returns a SURVEY: the tag and class skeleton of the blocks
     that repeat, attribute names, text replaced by its length, links by their host. No content leaves the tab.
  3. the owner's model proposes a recipe from the survey: one small call, the only model use here
  4. the recipe is validated in code and tried once through the extension: rows, since, three examples with text redacted
  5. ready -> `--enable` -> the source canvas_<slug>, read daily, new items added by id; items already read are kept
"""
import json, re, time
from urllib.parse import urljoin, urlsplit
from . import canvas
from .canvas import Stop, _iso, _rid, _rows

FIELDS = ("title", "link", "text", "date", "tags", "author", "id")
SELECTOR = re.compile(r"^[\w\s\-.#>+~*,:\[\]=\"'()^$|]*$")
MAX_ITEMS = 500
EXT_STEP = ("load the context extension in your browser: run python3 -m ctx bridge --install, then open chrome://extensions, switch on developer mode, "
            "choose load unpacked and pick the extension folder of context")

SYSTEM = """You write a small JSON recipe that tells a reader how to find the list of saved items on one web page.
You get a survey of the page: the blocks that repeat, as a skeleton of tags, classes and attribute names. Text is replaced by its length
and links by their host; you never see content. Choose the block that is the owner's list of items (bookmarks, saves, notes, posts),
not a menu, a footer or a list of suggestions.

Answer: {"list_selector": "<css selector matching every item>", "wait_for": "<css selector that exists once the list has loaded>",
 "fields": {"title": "<field>", "link": "<field>", "text": "<field>", "date": "<field>", "tags": "<field>"},
 "next": {"kind": "scroll"} or {"kind": "param", "param": "<the page-number parameter in the address>"} or null, "id_from": "link"}
A field is "<css selector inside one item>" (its text), "<css selector>@<attribute>" (for example "a@href", "time@datetime"),
"@<attribute>" (an attribute of the item itself), or "" (the item's whole text). Leave out a field the page does not have.
Only css selectors: no script, no xpath, no clicks.
If no block in the survey is a list of the owner's items: {"cannot": "<one plain lowercase sentence why>"}."""


def _field_ok(v):
    if not isinstance(v, str) or len(v) > 200 or "javascript" in v.lower():
        return False
    sel, _, attr = v.partition("@")
    return bool(SELECTOR.match(sel)) and (not attr or bool(re.fullmatch(r"[\w:-]{1,40}", attr)))


def validate(recipe, url):
    """Reasons this recipe may not run, or [] when it may. Selectors only, the same site only, GET only, with caps."""
    why = []
    if not isinstance(recipe, dict):
        return ["the recipe is not an object"]
    u = urlsplit(url)
    r = urlsplit(str(recipe.get("url") or url))
    if r.scheme != "https" or r.netloc.lower() != u.netloc.lower() or r.username or r.password:
        why.append("the recipe's address must be https and on the same site")
    extra = set(recipe) - {"url", "wait_for", "list_selector", "fields", "next", "max_items", "id_from", "api"}
    if extra:
        why.append("the recipe has keys that are not allowed: " + ", ".join(sorted(extra))[:80])
    api = recipe.get("api")
    if api is None:
        if not recipe.get("list_selector") or not _field_ok(recipe.get("list_selector")) or "@" in recipe["list_selector"]:
            why.append("list_selector must be a css selector")
        fields = recipe.get("fields")
        if not isinstance(fields, dict) or not fields or not ({"title", "text", "link"} & set(fields)):
            why.append("fields must name at least a title, a link or a text")
        elif set(fields) - set(FIELDS) or not all(_field_ok(v) for v in fields.values()):
            why.append("a field is not a css selector, or is not one of: " + ", ".join(FIELDS))
    else:
        if not isinstance(api, dict) or set(api) - {"url_pattern", "items_path", "fields", "max_pages"}:
            why.append("api has keys that are not allowed")
        else:
            p = str(api.get("url_pattern") or "")
            if not re.fullmatch(r"/(?!/)[\w\-./~%?=&{}]{0,200}", p) or re.sub(r"\{page\}", "", p).count("{") or ".." in p:
                why.append("api.url_pattern must be a path on the same site, with at most a {page} in it")
            if not re.fullmatch(r"[\w.\-]{0,80}", str(api.get("items_path") or "")):
                why.append("api.items_path must be a dotted path")
            f = api.get("fields")
            if not isinstance(f, dict) or not f or set(f) - set(FIELDS) or not all(isinstance(v, str) and re.fullmatch(r"[\w.\-]{1,80}", v) for v in f.values()):
                why.append("api.fields must map title, link, text, date or tags to dotted paths")
            if not isinstance(api.get("max_pages", 1), int) or not 1 <= api.get("max_pages", 1) <= 20:
                why.append("api.max_pages must be 1 to 20")
    if recipe.get("wait_for") is not None and (not _field_ok(recipe["wait_for"]) or "@" in str(recipe["wait_for"])):
        why.append("wait_for must be a css selector")
    nxt = recipe.get("next")
    if nxt is not None:
        if not isinstance(nxt, dict) or nxt.get("kind") not in ("scroll", "param") or set(nxt) - {"kind", "param"}:
            why.append("next must be scroll or param (a click is not allowed: it could change something)")
        elif nxt["kind"] == "param" and not re.fullmatch(r"\w{1,20}", str(nxt.get("param") or "")):
            why.append("next.param must be the name of a parameter")
    if not isinstance(recipe.get("max_items", 100), int) or not 1 <= recipe.get("max_items", 100) <= MAX_ITEMS:
        why.append("max_items must be 1 to %d" % MAX_ITEMS)
    if recipe.get("id_from") is not None and recipe["id_from"] not in FIELDS:
        why.append("id_from must be one of the fields")
    return why


def _page(url, fn, args, say, timeout=120):
    """One named reader in a background tab of the owner's browser. Every way it can stop comes back as a plain Stop."""
    from . import bridge
    host = urlsplit(url).hostname or url
    if not bridge.connected():
        raise Stop("needs_you", EXT_STEP)
    try:
        r = bridge.submit({"type": "page", "url": url, "fn": fn, "args": args, "settle": 2500}, timeout=timeout)
    except bridge.Offline:
        raise Stop("needs_you", EXT_STEP)
    except RuntimeError as e:
        if "not allowed" in str(e):
            raise Stop("needs_you", "context reads %s only after you say so in the browser: open that site, click the context icon and choose \"let context read this site\", then try again" % host)
        if "unknown reader" in str(e):
            raise Stop("needs_you", "the context extension in your browser is an older one: reload it at chrome://extensions")
        raise Stop("cannot", "the page could not be read in your browser: " + str(e)[:120].lower())
    r = r if isinstance(r, dict) else {}
    v = r.get("value") if isinstance(r.get("value"), dict) else {}
    if r.get("away") or v.get("logged_out"):
        raise Stop("needs_you", "sign in to %s in your browser, then try again (context never types a password)" % host)
    return v


def _pages(recipe, say, known=()):
    """Run the recipe: one tab for a list or a scroll, one per page for a page-number parameter. Returns the items."""
    url = recipe["url"]
    cap, nxt = min(int(recipe.get("max_items") or 100), MAX_ITEMS), recipe.get("next") or {}
    if nxt.get("kind") != "param":
        return (_page(url, "recipe", [recipe, list(known)[:2000]], say).get("items") or [])[:cap]
    items, seen = [], set()
    for n in range(1, 11):
        sep = "&" if "?" in url else "?"
        got = _page("%s%s%s=%d" % (url, sep, nxt["param"], n), "recipe", [dict(recipe, next=None), []], say).get("items") or []
        fresh = [i for i in got if json.dumps(i, sort_keys=True) not in seen]
        seen.update(json.dumps(i, sort_keys=True) for i in got)
        items += fresh
        if not fresh or len(items) >= cap or any(_item_id(recipe, i) in known for i in fresh):
            break
    return items[:cap]


def _item_id(recipe, item):
    return str(item.get(recipe.get("id_from") or "link") or item.get("link") or item.get("id") or item.get("title") or item.get("text") or "")[:400]


def _item_rows(d, recipe, items, first_seen):
    for i in items:
        if not isinstance(i, dict):
            continue
        key = _item_id(recipe, i)
        title, text = " ".join(str(i.get("title") or "").split())[:300], str(i.get("text") or "").strip()
        if not key or not (title or text):
            continue
        tags = i.get("tags")
        tags = ", ".join(str(t) for t in tags) if isinstance(tags, list) else str(tags or "")
        body = "\n".join(x for x in (title, text if text != title else "", "by " + str(i["author"]) if i.get("author") else "", "tags: " + tags if tags else "") if x)
        link = canvas.norm(str(i.get("link") or ""), recipe["url"]) if i.get("link") else ""
        yield key, list(_rows(d["slug"], _rid(d["slug"], key), link, title or text[:80], body, canvas.when(i.get("date")) or canvas.when(i.get("date"), loose=True) or first_seen))


def read(d, emit, trial, say, st, prev):
    """A full read: what the page lists now, new items added; what was read before is kept as it was."""
    recipe = (d.get("options") or {}).get("recipe")
    if not recipe or validate(recipe, d["address"]):
        raise Stop("needs_you", "this page has no reading recipe yet: connect it again")
    known = {r[0].get("item") for r in prev.values() if r and r[0].get("item")}
    say("reading %s in your browser" % (urlsplit(d["address"]).hostname or ""))
    items = _pages(recipe, say, known)
    done, new = set(), 0
    for key, rows in _item_rows(d, recipe, items, _iso(time.time())):
        pid = rows[0]["id"]
        if pid in done:
            continue
        done.add(pid)
        if pid in prev:
            continue                                # read before: it keeps its row and the day it was first seen
        for r in rows:
            emit(dict(r, item=key, kept="saved"))
        new += 1
    for pid, rows in prev.items():
        for r in rows:
            emit(r)
    return {"how": d.get("how", ""), "detail": "", "why": "the page listed nothing", "stats": {"found": len(items), "new": new, "route": "browser"}}


def _public(d, say):
    """A public way to the same thing, if there is one: the page's feed, or the page itself when anyone can read it."""
    try:
        web = canvas.Web()
        got = web.get(d["address"])
        if got.status != 200 or not got.text or canvas._host(got.url) != canvas._host(d["address"]):
            return None
        p = canvas.read_html(got.text, got.url)
        if re.search(r"<input[^>]+type=[\"']?password", got.text, re.I):
            return None
        for kind, addr in ([("feed", f) for f in p["feeds"][:1]] + ([("site", d["address"])] if p["words"] >= canvas.MIN_WORDS else [])):
            say("this is public: reading its %s instead of asking your browser" % ("feed" if kind == "feed" else "page"))
            out = canvas.connect("%s:%s" % (kind, addr), say=say)
            if out.get("state") == "ready" and out["sample"]["rows"]:
                out["detail"] = "; ".join(x for x in ("read by the public route (its %s), so no sign-in is used" % ("feed" if kind == "feed" else "pages"), out.get("detail")) if x)
                return out
    except (canvas.Refused, canvas.Blocked, canvas.Unreachable, Stop):
        pass
    return None


def _shape(item):
    from . import connect
    return connect.redact({k: v for k, v in item.items() if v not in (None, "", [])})


def connect(d, say, res):
    """The trial for a page behind a sign-in. `res` builds canvas.py's result object."""
    url = d["address"]
    if urlsplit(url).scheme != "https":
        return res("cannot", detail="a signed-in page is only read over https")
    out = _public(d, say)
    if out:
        return out
    recipe = (d.get("options") or {}).get("recipe")
    if not recipe:
        say("looking at the shape of the page in your browser (no text leaves the tab)")
        survey = _page(url, "survey", [], say)
        if not survey.get("repeated"):
            return res("cannot", detail="the page showed no list of items to a reader: nothing on it repeats")
        from . import llm
        if llm.status().get("using") == "none":
            return res("needs_you", detail="no model is signed in to work out which list on the page is yours (one small call): sign in to claude code or codex, then try again")
        say("asking your model which list on the page is yours: one small call, about 3,000 tokens of your plan")
        try:
            ans = llm.ask_json(SYSTEM, "Page: %s\n\nSurvey:\n%s" % (urlsplit(url).netloc, json.dumps(survey, ensure_ascii=False)[:24000]), model=llm.FAST, tag="connect")
        except Exception as e:
            return res("needs_you", detail="your model did not answer: " + str(e)[:120].lower())
        if not isinstance(ans, dict) or ans.get("cannot"):
            return res("cannot", detail=str((ans or {}).get("cannot") or "your model could not find your list on that page")[:200].lower() if isinstance(ans, dict) else "your model's answer could not be read")
        recipe = dict({k: v for k, v in ans.items() if v is not None}, url=url)
        recipe.setdefault("max_items", 200)
    say("checking the recipe before it runs")
    why = validate(recipe, url)
    if why:
        return res("cannot", detail="the recipe was refused: " + why[0])
    say("trying it once in your browser")
    items = _pages(dict(recipe, max_items=min(recipe.get("max_items", 200), 60), next=None if (recipe.get("next") or {}).get("kind") == "param" else recipe.get("next")), say)
    rows = [r for _, rs in _item_rows(d, recipe, items, "") for r in rs]
    if not rows:
        return res("cannot", detail="the recipe ran and found no items on the page")
    dated = sorted(r["ts"][:7] for r in rows if r["ts"])
    how = "reads your list at %s in the browser you are signed in to: %d items on the first screen%s. your password is never typed or kept" % (
        urlsplit(url).netloc + urlsplit(url).path, len(rows), ", then it scrolls for more" if (recipe.get("next") or {}).get("kind") == "scroll" else "")
    d.setdefault("options", {})["recipe"] = recipe
    d.update(how=how, rows=len(rows), since=dated[0] if dated else "")
    canvas._put_def(d)
    canvas._table()
    return res("ready", how, len(rows), dated[0] if dated else "", "read through your browser by a recipe your model proposed and code checked; nothing is clicked or changed",
               examples=[_shape(i) for i in items[:3] if isinstance(i, dict)], stats={"found": len(items), "route": "browser"})
