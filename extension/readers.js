// Functions the extension can run inside a page. Each one is self-contained (it is copied into the tab),
// only reads, and returns plain data. The engine picks one by name; it cannot send code of its own.
const READERS = {

  // Slack: ask Slack's own API, from inside the signed-in tab, for messages newer than what is saved.
  // The session token is read and used here, inside the page, and is never returned.
  // old = { conversation id: newest saved ts }
  slack_read: async function (old) {
    const S = { err: "", convs: 0, skipped: 0, msgs: [] };
    const team = location.pathname.split("/")[2];
    let tok = "";
    try { const cfg = JSON.parse(localStorage.getItem("localConfig_v2") || "{}"); tok = (cfg.teams && cfg.teams[team] && cfg.teams[team].token) || ""; } catch (e) {}
    if (!tok) { S.err = "no session"; return S; }
    let W = null;   // hidden tabs throttle timers; a worker's timers are not throttled
    try { W = new Worker(URL.createObjectURL(new Blob(["onmessage=function(e){setTimeout(function(){postMessage(1)},e.data)}"]))); } catch (e) {}
    const sleep = (ms) => new Promise((r) => { if (!W) return setTimeout(r, ms); W.onmessage = () => r(); W.postMessage(ms); });
    async function api(m, p) {
      for (let k = 0; k < 6; k++) {
        const f = new FormData(); f.append("token", tok); for (const x in p) f.append(x, p[x]);
        const r = await fetch("/api/" + m, { method: "POST", body: f, credentials: "include" });
        if (r.status == 429) { await sleep(1000 * (parseInt(r.headers.get("retry-after") || "5") + 1)); continue; }
        const j = await r.json(); if (!j.ok && j.error == "ratelimited") { await sleep(6000); continue; }
        return j;
      }
      return { ok: false, error: "gave up" };
    }
    try {
      const me = await api("auth.test", {}); if (!me.ok) { S.err = "no session"; return S; }
      const users = {}, convs = []; let cur = "";
      do { const u = await api("users.list", { limit: 500, cursor: cur }); (u.members || []).forEach((m) => { users[m.id] = m.real_name || m.name; }); cur = (u.response_metadata || {}).next_cursor || ""; } while (cur);
      cur = "";
      do { const c = await api("users.conversations", { types: "im,mpim,public_channel,private_channel", limit: 500, cursor: cur, exclude_archived: false });
        if (!c.ok) { S.err = "convs: " + c.error; break; }
        (c.channels || []).forEach((ch) => { convs.push({ id: ch.id, kind: ch.is_im ? "dm" : "group", name: ch.is_im ? (users[ch.user] || ch.user) : (ch.name || ch.id) }); });
        cur = (c.response_metadata || {}).next_cursor || ""; } while (cur);
      S.convs = convs.length;
      for (const cv of convs) {
        let cur2 = "", empty = 0;
        do { const p = { channel: cv.id, limit: 200, cursor: cur2 }; if (old && old[cv.id]) p.oldest = old[cv.id];
          const h = await api("conversations.history", p); if (!h.ok) break;
          const before = S.msgs.length;
          (h.messages || []).forEach((m) => { if (m.text && !m.subtype) S.msgs.push({ cid: cv.id, name: cv.name, kind: cv.kind, ts: m.ts, who: m.user == me.user_id ? "me" : (users[m.user] || m.user || ""), text: m.text.slice(0, 4000) }); });
          empty = S.msgs.length == before ? empty + 1 : 0; if (empty >= 3) { S.skipped++; break; }   // bot or log channel
          cur2 = h.has_more ? (h.response_metadata || {}).next_cursor : ""; await sleep(300); } while (cur2);
      }
    } catch (e) { S.err = String(e); }
    return S;
  },

  // Drive: the files in the list that is on screen, as [{id, title}]. Waits for the list to draw.
  drive_list: async function () {
    const rows = () => Array.prototype.slice.call(document.querySelectorAll("[data-id]"))
      .filter((e) => /^[\w-]{25,}$/.test(e.getAttribute("data-id")))
      .map((e) => ({ id: e.getAttribute("data-id"), title: e.getAttribute("aria-label") || "" }));
    for (let i = 0; i < 15 && !rows().length; i++) await new Promise((r) => setTimeout(r, 1000));
    return rows();
  },

  // X: the handle of the signed-in account, from the profile link in the side bar. "" when signed out.
  x_me: async function () {
    const find = () => { const a = document.querySelector('a[data-testid="AppTabBar_Profile_Link"]'); return a ? (a.getAttribute("href") || "").replace(/^\//, "").split("/")[0] : ""; };
    for (let i = 0; i < 12 && !find(); i++) await new Promise((r) => setTimeout(r, 1000));
    return find();
  },

  // X, without drawing anything: x does not render a timeline in a tab that is not on screen, so a hidden tab shows no
  // posts to scroll through. This asks x's own data address for the list instead, the same call the page makes, with
  // the session the tab already has. GET only. `op` is the page's own name for the list: Likes, UserTweets, Bookmarks.
  // `vars` replaces the request's variables for a list that is not about one account (bookmarks, a search).
  // `part` is a pattern for the name of the code part that holds the request, when x loads it only on that list's page.
  // Returns {items: [{u, d, n, t, l, m}], pages, why, next, wait}: why says where it stopped when it could not go on,
  // wait is the seconds x asked for when it said to slow down.
  x_api: async function (op, known, pages, from, vars, part) {
    const idOf = (u) => String(u).split("/").pop();   // a post is known by its number: a handle can change its spelling
    const seen = new Set((known || []).map(idOf)), out = [], sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const given = vars && typeof vars == "object" ? vars : null;
    const find = () => performance.getEntriesByType("resource").map((e) => e.name).filter((n) => n.indexOf("/graphql/") > 0 && n.indexOf("/" + op + "?") > 0).pop();
    let first = find();
    for (let i = 0; i < 4 && !first; i++) { await sleep(1000); first = find(); }
    const ct0 = (document.cookie.match(/(?:^|; )ct0=([^;]+)/) || [])[1];
    if (!ct0) return { items: [], pages: 0, why: "signed out" };
    let url;
    if (first) {
      url = new URL(first);
      try { vars = given || JSON.parse(url.searchParams.get("variables")); } catch (e) { return { items: [], pages: 0, why: "the page's request could not be read" }; }
    } else {
      // A tab that is not on screen asks for nothing, so there is no request to copy. The shape of the request (its id and
      // the switches it must name) is written in x's own script files: read it from there.
      const uid = (decodeURIComponent((document.cookie.match(/(?:^|; )twid=([^;]+)/) || [])[1] || "").match(/u=(\d+)/) || [])[1];
      if (!uid) return { items: [], pages: 0, why: "signed out" };
      const srcs = Array.from(new Set(Array.from(document.querySelectorAll("script[src], link[as=script][href]")).map((e) => e.src || e.href).filter((u) => /twimg\.com\/.*\.js/.test(u))));
      const rx = new RegExp('queryId:"([^"]+)",operationName:"' + op + '",operationType:"query",metadata:\\{featureSwitches:\\[([^\\]]*)\\](?:,fieldToggles:\\[([^\\]]*)\\])?');
      // x loads part of its code only when a page needs it. The page's own loader lists those parts as number: "name" and
      // number: "file mark"; the file is <name>.<mark>a.js next to the main script.
      const partUrls = (want) => {
        const main = srcs.find((u) => /\/main\.[0-9a-f]+\.js/.test(u));
        if (!main || !want) return [];
        const inl = Array.from(document.scripts).filter((e) => !e.src).map((e) => e.textContent || "").join("\n");
        const prx = new RegExp(String(want), "i"), urls = [];
        for (const m of inl.matchAll(/[{,](\d+):"((?:bundle|loader|ondemand|shared~)[A-Za-z0-9_.~-]{1,160})"/g)) {
          if (!prx.test(m[2])) continue;
          const h = inl.match(new RegExp("[{,]" + m[1] + ':"([0-9a-f]{12,20})"'));
          if (h) urls.push(main.replace(/main\.[0-9a-f]+\.js.*$/, m[2] + "." + h[1] + "a.js"));
          if (urls.length >= 8) break;
        }
        return urls;
      };
      let def = null;
      for (const src of srcs.sort((x, y) => (/\/main\./.test(y) ? 1 : 0) - (/\/main\./.test(x) ? 1 : 0)).concat(partUrls(part))) {
        try { const m = (await (await fetch(src, { credentials: "omit" })).text()).match(rx); if (m) { def = m; break; } } catch (e) {}
      }
      if (!def) return { items: [], pages: 0, why: "x's scripts do not name this list", scripts: srcs.length, path: location.pathname };
      const names = (t) => (t || "").split(",").map((x) => x.replace(/"/g, "").trim()).filter(Boolean);
      const feats = {}, toggles = {};
      names(def[2]).forEach((n) => { feats[n] = true; });
      names(def[3]).forEach((n) => { toggles[n] = false; });
      vars = given || { userId: uid, count: 40, includePromotedContent: false, withClientEventToken: false, withBirdwatchNotes: false, withVoice: true, withCommunity: true };
      url = new URL("https://x.com/i/api/graphql/" + def[1] + "/" + op);
      url.searchParams.set("features", JSON.stringify(feats));
      if (names(def[3]).length) url.searchParams.set("fieldToggles", JSON.stringify(toggles));
    }
    const headers = { "authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA",
                      "x-csrf-token": ct0, "x-twitter-active-user": "yes", "x-twitter-auth-type": "OAuth2Session", "content-type": "application/json" };
    // a post that is quoted or reposted inside another is not itself in the list: do not go into it
    const INNER = { quoted_status_result: 1, retweeted_status_result: 1, quoted_status: 1, retweeted_status: 1 };
    const walk = (o, f) => { if (o && typeof o == "object") { f(o); for (const k in o) if (!INNER[k]) walk(o[k], f); } };
    let cursor = from || null, n = 0, why = "", done = false, wait = 0, low = false;
    for (; n < Math.min(pages || 20, 400); n++) {
      const v = Object.assign({}, vars, { count: 40 });
      if (cursor) v.cursor = cursor; else delete v.cursor;
      url.searchParams.set("variables", JSON.stringify(v));
      let data = null;
      try {
        const r = await fetch(url.toString(), { method: "GET", credentials: "include", headers: headers });
        if (r.status == 429) {
          why = "x asked to slow down";
          const reset = parseInt(r.headers.get("x-rate-limit-reset") || "0");
          wait = reset ? Math.max(0, Math.round(reset - Date.now() / 1000)) : 0;
          break;
        }
        if (!r.ok) { why = "x answered " + r.status; break; }
        data = await r.json();
        // x says in each answer how many more it will give before a pause: stop one short of that, not at a refusal
        const left = r.headers.get("x-rate-limit-remaining"), reset = parseInt(r.headers.get("x-rate-limit-reset") || "0");
        if (left !== null && parseInt(left) <= 1) { low = true; wait = reset ? Math.max(0, Math.round(reset - Date.now() / 1000)) : 0; }
      } catch (e) { why = "the request failed"; break; }
      let next = null, got = 0, hit = false;
      walk(data, (o) => {
        if (o.cursorType == "Bottom" && typeof o.value == "string") next = o.value;
        const l = o.legacy;
        if (!(o.__typename == "Tweet" || o.core) || !o.rest_id || !l || typeof l.full_text != "string") return;   // a post with limited replies comes wrapped, with no type name
        const who = (((o.core || {}).user_results || {}).result || {}), wl = who.legacy || {}, wc = who.core || {};
        const handle = wc.screen_name || wl.screen_name || "", name = wc.name || wl.name || "";
        const u = "https://x.com/" + (handle || "i") + "/status/" + o.rest_id;
        got++;
        if (seen.has(o.rest_id)) { hit = true; return; }
        seen.add(o.rest_id);
        const note = ((((o.note_tweet || {}).note_tweet_results || {}).result || {}).text) || "";
        const urls = ((l.entities || {}).urls || []).map((x) => x.expanded_url).filter(Boolean).slice(0, 3);
        const d = new Date(l.created_at);
        out.push({ u: u, d: isNaN(d) ? "" : d.toISOString(), n: (name + " @" + handle).trim(), t: note || l.full_text, l: urls,
                   m: (((l.extended_entities || {}).media) || []).length, r: l.in_reply_to_screen_name || "", rt: !!l.retweeted_status_result });
      });
      if (hit && (known || []).length) { done = true; break; }
      if (!next || next == cursor || !got) { done = true; break; }
      cursor = next;
      if (low) { why = "x asked to slow down"; n++; break; }
      await sleep(1200);
    }
    // next: where a later call goes on from (the caller reads in short runs and saves between them). "" when the list ended; kept when x asked to slow down, so the read goes on later.
    return { items: out, pages: n, why: why, next: done ? "" : (cursor || ""), wait: why ? wait : 0 };
  },

  // X: the names of the lists x's own scripts know how to ask for, that match a pattern. Names only, nothing of the owner's.
  // `parts` is a pattern for the names of the code parts x loads later, to look in those too.
  x_ops: async function (pattern, parts) {
    const rx = new RegExp(String(pattern || "."), "i"), found = new Set();
    const srcs = Array.from(new Set(Array.from(document.querySelectorAll("script[src], link[as=script][href]")).map((e) => e.src || e.href).filter((u) => /twimg\.com\/.*\.js/.test(u))));
    // x loads part of its code only when a page needs it. The page's own loader lists those parts as number: "name" and
    // number: "file mark"; the file is <name>.<mark>a.js next to the main script.
    const partUrls = (want) => {
      const main = srcs.find((u) => /\/main\.[0-9a-f]+\.js/.test(u));
      if (!main || !want) return [];
      const inl = Array.from(document.scripts).filter((e) => !e.src).map((e) => e.textContent || "").join("\n");
      const prx = new RegExp(String(want), "i"), urls = [];
      for (const m of inl.matchAll(/[{,](\d+):"((?:bundle|loader|ondemand|shared~)[A-Za-z0-9_.~-]{1,160})"/g)) {
        if (!prx.test(m[2])) continue;
        const h = inl.match(new RegExp("[{,]" + m[1] + ':"([0-9a-f]{12,20})"'));
        if (h) urls.push(main.replace(/main\.[0-9a-f]+\.js.*$/, m[2] + "." + h[1] + "a.js"));
        if (urls.length >= 8) break;
      }
      return urls;
    };
    const more = partUrls(parts);
    for (const src of srcs.concat(more)) {
      try {
        const t = await (await fetch(src, { credentials: "omit" })).text();
        for (const m of t.matchAll(/operationName:"([A-Za-z0-9_]+)",operationType:"query"/g)) if (rx.test(m[1])) found.add(m[1]);
      } catch (e) {}
    }
    return { ops: Array.from(found).sort().slice(0, 200), scripts: srcs.length, parts: more.length };
  },

  // The shape of a page, with no content: the blocks that repeat, as tags, classes and attribute names.
  // Text is replaced by its length and a link by its host. The engine's model reads this to find the owner's list.
  survey: function () {
    const sig = (e) => e.tagName.toLowerCase() + (e.classList.length ? "." + Array.from(e.classList).slice(0, 3).map((c) => CSS.escape(c)).join(".") : "");
    const shape = (e, depth) => {
      const o = { tag: sig(e) };
      const attrs = Array.from(e.attributes).map((a) => a.name).filter((n) => n != "class" && n != "style");
      if (attrs.length) o.attrs = attrs.slice(0, 8);
      if (e.tagName == "A" && e.href) { try { o.link_host = new URL(e.href).host; } catch (x) {} }
      const own = Array.from(e.childNodes).filter((n) => n.nodeType == 3).map((n) => n.textContent.trim()).join(" ").trim();
      if (own) o.text = "<str " + own.length + ">";
      if (depth < 4) { const kids = Array.from(e.children).slice(0, 8).map((c) => shape(c, depth + 1)); if (kids.length) o.children = kids; }
      return o;
    };
    const path = (e) => {
      const parts = [sig(e)];
      for (let n = e.parentElement; n && n != document.body && parts.length < 4; n = n.parentElement) parts.unshift(n.id && /^[A-Za-z][\w-]*$/.test(n.id) ? "#" + n.id : sig(n));
      return parts.join(" > ");
    };
    const groups = [];
    for (const parent of document.querySelectorAll("body *")) {
      if (parent.children.length < 4) continue;
      const by = {};
      for (const c of parent.children) { const s = sig(c); (by[s] = by[s] || []).push(c); }
      for (const s in by) if (by[s].length >= 4 && (by[s][0].innerText || "").trim().length > 20) groups.push([by[s][0], by[s].length]);
    }
    groups.sort((a, b) => b[1] - a[1]);
    return { logged_out: !!document.querySelector('input[type="password"]'), scrolls: document.documentElement.scrollHeight > 2 * innerHeight,
             repeated: groups.slice(0, 8).map((g) => ({ selector: path(g[0]), count: g[1], item: shape(g[0], 0) })) };
  },

  // Run a recipe: json the engine checked (selectors only, this site only, GET only). Reads; never clicks, types or posts.
  // known = ids already saved: scrolling stops when one shows up.
  recipe: async function (recipe, known) {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const cap = Math.min(recipe.max_items || 100, 500), seen = new Set(known || []);
    const clip = (s) => String(s == null ? "" : s).replace(/\s+/g, " ").trim().slice(0, 1500);
    const out = { logged_out: !!document.querySelector('input[type="password"]'), items: [] };
    if (recipe.api) {
      const walk = (o, p) => String(p || "").split(".").filter(Boolean).reduce((v, k) => (v == null ? v : v[k]), o);
      const paged = String(recipe.api.url_pattern).indexOf("{page}") >= 0;
      for (let n = 1; n <= Math.min(recipe.api.max_pages || 1, 20) && out.items.length < cap; n++) {
        const u = new URL(String(recipe.api.url_pattern).replace("{page}", n), location.origin);
        if (u.origin != location.origin) break;
        const r = await fetch(u.href, { method: "GET", credentials: "same-origin", headers: { Accept: "application/json" } });
        if (!r.ok) break;
        let list = null;
        try { list = walk(await r.json(), recipe.api.items_path); } catch (e) {}
        if (!Array.isArray(list) || !list.length) break;
        for (const it of list) {
          const row = {};
          for (const f in recipe.api.fields) { const v = walk(it, recipe.api.fields[f]); row[f] = Array.isArray(v) ? v.slice(0, 20).map(clip) : clip(v); }
          out.items.push(row);
        }
        if (!paged) break;
        await sleep(800);
      }
      out.items = out.items.slice(0, cap);
      return out;
    }
    const pick = (el, spec, field) => {
      const at = String(spec).indexOf("@"), sel = at < 0 ? String(spec) : String(spec).slice(0, at), attr = at < 0 ? "" : String(spec).slice(at + 1);
      let nodes;
      try { nodes = sel.trim() ? Array.from(el.querySelectorAll(sel)) : [el]; } catch (e) { return ""; }
      const val = (n) => clip(!attr ? n.innerText || n.textContent : (attr == "href" || attr == "src") && n[attr] ? n[attr] : n.getAttribute(attr));
      if (field == "tags") return nodes.slice(0, 20).map(val).filter(Boolean);
      return nodes.length ? val(nodes[0]) : "";
    };
    const take = () => {
      let els;
      try { els = Array.from(document.querySelectorAll(recipe.list_selector)); } catch (e) { return []; }
      return els.slice(0, cap).map((el) => { const row = {}; for (const f in recipe.fields) row[f] = pick(el, recipe.fields[f], f); return row; });
    };
    if (recipe.wait_for) {
      for (let i = 0; i < 20; i++) { let ok = false; try { ok = !!document.querySelector(recipe.wait_for); } catch (e) {} if (ok) break; await sleep(500); }
    }
    let items = take(), still = 0;
    if (recipe.next && recipe.next.kind == "scroll") {
      const key = recipe.id_from || "link";
      for (let i = 0; i < 25 && items.length < cap && still < 3; i++) {
        if (items.some((r) => seen.has(r[key]))) break;
        window.scrollTo(0, document.documentElement.scrollHeight);
        await sleep(1500);
        const now = take();
        still = now.length == items.length ? still + 1 : 0;
        items = now;
      }
    }
    out.items = items;
    return out;
  },

  // Instagram: the posts the owner saved, newest first, from the address instagram's own page reads them from, with the
  // session the tab already has. GET only: nothing is sent, liked, saved or marked seen. `known` = ids already saved:
  // reading stops at the first of them. `from` is where an earlier call stopped.
  // Returns {items, next, why, me}: why says where it stopped when it could not go on; next is "" at the end.
  // Measured 2026-11-22 from a background tab: saved posts are answered. The list of chats (direct_v2/inbox) answers 404
  // and liked posts (feed/liked) 400: instagram's page gets both another way that is not a plain GET, so they are not read.
  ig_api: async function (kind, known, pages, from) {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const csrf = (document.cookie.match(/(?:^|; )csrftoken=([^;]+)/) || [])[1] || "";
    const uid = (document.cookie.match(/(?:^|; )ds_user_id=([^;]+)/) || [])[1] || "";
    if (!uid) return { items: [], next: "", why: "signed out", me: "" };
    if (kind != "saved") return { items: [], next: "", why: "unknown list", me: uid };
    // the id of instagram's own web app, which its pages send with every request of this kind
    const headers = { "X-IG-App-ID": "936619743392459", "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrf, "Accept": "application/json" };
    const clip = (t, n) => String(t == null ? "" : t).slice(0, n || 4000);
    const seen = new Set((Array.isArray(known) ? known : []).map(String)), out = [];
    let cursor = from || "", why = "", done = false;
    for (let n = 0; n < Math.min(pages || 3, 20); n++) {
      let d = null;
      try {
        const r = await fetch("/api/v1/feed/saved/posts/" + (cursor ? "?max_id=" + encodeURIComponent(cursor) : ""), { method: "GET", credentials: "include", headers: headers });
        if (r.status == 429) { why = "instagram asked to slow down"; break; }
        if (r.status == 401 || r.status == 403) { why = r.status == 401 ? "signed out" : "instagram refused"; break; }
        if (!r.ok) { why = "instagram answered " + r.status; break; }
        if ((r.headers.get("content-type") || "").indexOf("json") < 0) { why = "instagram sent a page, not data (it may be asking you to confirm it is you)"; break; }
        d = await r.json();
      } catch (e) { why = "the request failed"; break; }
      if (!d || d.status == "fail" || d.require_login) { why = d && d.message == "checkpoint_required" ? "instagram is asking you to confirm it is you" : "instagram refused"; break; }
      let hit = false, got = 0;
      for (const it of d.items || []) {
        const m = it.media || it;
        if (!m || !m.pk) continue;
        got++;
        const id = String(m.code || m.pk);
        if (seen.has(id)) { hit = true; continue; }
        seen.add(id);
        out.push({ id: id, at: m.taken_at || 0, user: clip((m.user || {}).username, 60), text: clip((m.caption || {}).text, 2200), reel: m.product_type == "clips" });
      }
      const next = d.more_available ? String(d.next_max_id || "") : "";
      if (hit || !next || next == cursor || !got) { done = true; break; }
      cursor = next;
      await sleep(1500);
    }
    return { items: out, next: done ? "" : cursor, why: why, me: uid };
  },

  // ChatGPT, from the addresses its own page reads. GET only. The page's access token is asked for here, used here and
  // never returned or kept: it lives in this function's own variable until the function ends.
  // `known` = {conversation id: when it last changed, as saved}. The list is read newest-changed first, `from` on;
  // a conversation that is new or changed since is read whole, as its visible turns: [{role, text, at}].
  // Reading stops at a page of the list on which nothing has changed, or after `most` conversations (the next call
  // goes over the list again and takes up the ones still unread).
  chatgpt_api: async function (known, pages, from, most) {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    known = known && typeof known == "object" ? known : {};
    let token = "";
    try {
      const s = await fetch("/api/auth/session", { method: "GET", credentials: "include", headers: { "Accept": "application/json" } });
      if (s.ok) token = ((await s.json()) || {}).accessToken || "";
    } catch (e) {}
    if (!token) return { items: [], next: "", why: "signed out" };
    const headers = { "Authorization": "Bearer " + token, "Accept": "application/json" };
    const secs = (t) => (typeof t == "number" ? t : (t ? Date.parse(t) / 1000 : 0)) || 0;
    const get = async (url) => {
      const r = await fetch(url, { method: "GET", credentials: "include", headers: headers });
      if (r.status == 429) return { why: "chatgpt asked to slow down" };
      if (r.status == 401) return { why: "signed out" };
      if (r.status == 403) return { why: "chatgpt refused (it may be checking that you are a person)" };
      if (!r.ok) return { why: "chatgpt answered " + r.status };
      if ((r.headers.get("content-type") || "").indexOf("json") < 0) return { why: "chatgpt sent a page, not data" };
      return { data: await r.json() };
    };
    const out = [];
    let offset = parseInt(from || "0") || 0, why = "", done = false;
    const cap = Math.min(most || 10, 40);
    try {
      for (let n = 0; n < Math.min(pages || 2, 10) && !done && !why; n++) {
        const page = await get("/backend-api/conversations?offset=" + offset + "&limit=28&order=updated");
        if (page.why) { why = page.why; break; }
        const items = (page.data && page.data.items) || [];
        if (!items.length) { done = true; break; }
        let fresh = 0, full = false;
        for (const it of items) {
          const changed = secs(it.update_time);
          if (known[it.id] && secs(known[it.id]) >= changed - 1) continue;      // as saved
          fresh++;
          if (out.length >= cap) { full = true; break; }
          await sleep(900);
          const c = await get("/backend-api/conversation/" + encodeURIComponent(it.id));
          if (c.why) { why = c.why; break; }
          const map = (c.data && c.data.mapping) || {}, turns = [], walked = new Set();
          let node = c.data.current_node;
          while (node && map[node] && !walked.has(node)) {
            walked.add(node);
            const m = map[node].message;
            if (m && m.author && (m.author.role == "user" || m.author.role == "assistant") && m.content &&
                (m.content.content_type == "text" || m.content.content_type == "multimodal_text") && !(m.metadata || {}).is_visually_hidden_from_conversation) {
              const text = (m.content.parts || []).filter((p) => typeof p == "string").join("\n").trim();
              if (text) turns.unshift({ role: m.author.role, text: text.slice(0, 60000), at: m.create_time || 0 });
            }
            node = map[node].parent;
          }
          out.push({ id: String(it.id), title: String(c.data.title || it.title || "").slice(0, 200), made: secs(c.data.create_time || it.create_time), changed: changed, turns: turns });
        }
        if (why || full) break;
        if (!fresh || items.length < 28) { done = true; break; }       // newest-changed first: a page with nothing new means the rest is as saved
        offset += items.length;
      }
    } catch (e) { why = why || "the request failed"; }
    token = "";
    return { items: out, next: done ? "" : String(offset), why: why };
  },
};
