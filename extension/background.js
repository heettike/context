// context: reads the owner's own pages in the background for the context app on this mac.
// It takes jobs only from the local native host (so.context.bridge) and answers only to it.
// There is no listener for web pages or other extensions (no onMessage, no onMessageExternal, no onConnectExternal),
// and nothing here talks to a server.
importScripts("policy.js", "readers.js");

const HOST = "so.context.bridge";
// What may be read is decided here, not by the job (policy.js): the built-in readers run only on their own sites, a
// fetch only gets the few addresses the engine reads, and any other site is read only after the owner allowed it in
// the popup. He also keeps a list of sites never to read. The engine can change neither list: both live in this
// browser's own storage, which only the popup writes.
let BLOCKED = [], ALLOWED = [], DEV_RELOAD = false;
// chrome.storage is missing until the browser has taken up a manifest that asks for it (an extension reloaded half-way):
// then nothing is blocked, nothing extra is allowed, and the worker still runs.
const STORE = (typeof chrome != "undefined" && chrome.storage && chrome.storage.local) || null;
const hosts = (v) => (Array.isArray(v) ? v.filter((h) => typeof h == "string" && /^[a-z0-9.-]{1,253}$/.test(h)) : []);
function reblock(done) {
  if (!STORE) { BLOCKED = []; ALLOWED = []; DEV_RELOAD = false; if (typeof done == "function") done(); return; }
  STORE.get({ blocked: [], allowed: [], dev_reload: false }, (v) => {
    BLOCKED = hosts(v && v.blocked);
    ALLOWED = hosts(v && v.allowed);
    DEV_RELOAD = !!(v && v.dev_reload === true);
    if (typeof done == "function") done();
  });
}
const ready = new Promise((r) => reblock(r));
if (STORE && chrome.storage.onChanged) chrome.storage.onChanged.addListener(() => reblock());
const hostOf = POLICY.hostOf;
// a tab that has moved (a sign-in page, a redirect) is read only if the reader still belongs where it landed
const pageOk = (fn, u) => POLICY.page(fn, u, BLOCKED, ALLOWED) == "";
// The manifest names only the built-in sites. Any other site (and the built-in ones that start switched off) must also
// have been granted to this extension by the browser, which asks the owner himself when he adds it in the popup.
function granted(u) {
  const host = hostOf(u);
  if (!host) return Promise.resolve(false);
  return new Promise((r) => { try { chrome.permissions.contains({ origins: [POLICY.origin(host)] }, (ok) => { void chrome.runtime.lastError; r(!!ok); }); } catch (e) { r(false); } });
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let port = null;

// The host stays connected only while there is work, and an open port keeps this worker awake.
// When it has nothing to do it hangs up, the worker sleeps, and the alarm asks again a minute later.
function connect() {
  if (port) return;
  try { port = chrome.runtime.connectNative(HOST); } catch (e) { port = null; return; }
  port.onMessage.addListener(onJob);
  port.onDisconnect.addListener(() => { void chrome.runtime.lastError; port = null; });
}
function wake() {
  chrome.alarms.get("wake", (a) => { if (!a) chrome.alarms.create("wake", { periodInMinutes: 1 }); });
  connect();
}
chrome.runtime.onInstalled.addListener(wake);
chrome.runtime.onStartup.addListener(wake);
chrome.alarms.onAlarm.addListener(connect);

async function onJob(job) {
  if (!job || typeof job.id != "string") return;
  let out;
  try {
    await ready;
    const run = JOBS[job.type];
    if (!run) throw new Error("unknown job");
    const limit = Math.min(Math.max(job.timeout || 60, 5), 3600) * 1000;
    const result = await Promise.race([run(job), sleep(limit).then(() => { throw new Error("took too long"); })]);
    out = { id: job.id, ok: true, result: result };
  } catch (e) {
    out = { id: job.id, ok: false, error: String((e && e.message) || e).slice(0, 200) };
  }
  try { if (port) port.postMessage(out); } catch (e) {}
}

// html to text with regex, the same way the engine always did it
function strip(t) {
  return t.replace(/<(script|style|head)[\s\S]*?<\/\1>/gi, " ").replace(/<\/(p|div|h[1-6]|li|tr|br)>|<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&#39;/g, "'").replace(/&quot;/g, '"')
    .replace(/[ \t]+/g, " ").replace(/\n\s*\n+/g, "\n").trim();
}

async function loaded(tabId, ms) {
  for (const end = Date.now() + ms; Date.now() < end; await sleep(500)) {
    const t = await chrome.tabs.get(tabId);
    if (t.status == "complete") return t;
  }
  return chrome.tabs.get(tabId);
}

// Use a tab that is already open on that site, or open one in the background and close it afterwards.
// Never focuses a window and never changes which tab is on screen.
async function withTab(job, run) {
  if (!pageOk(job.fn, job.url) || !(await granted(job.url))) throw new Error("site not allowed");
  let tab = null, opened = false;
  if (typeof job.reuse == "string" && hostOf(job.reuse.replace("*", "")) == hostOf(job.url)) {
    tab = (await chrome.tabs.query({ url: job.reuse })).find((t) => !t.discarded && t.status == "complete") || null;
  }
  if (!tab) {
    tab = await chrome.tabs.create({ url: job.url, active: false });
    opened = true;
    await loaded(tab.id, 30000);
    await sleep(Math.min(job.settle || 3000, 15000));
  }
  try {
    tab = await chrome.tabs.get(tab.id);
    if (!pageOk(job.fn, tab.url) || !(await granted(tab.url))) return { url: (tab.url || "").split("?")[0].split("#")[0], away: true };   // sent to a sign-in page or another site
    return await run(tab);
  } finally {
    if (opened) { try { await chrome.tabs.remove(tab.id); } catch (e) {} }
  }
}

async function exec(tabId, fn, args) {
  if (!Object.prototype.hasOwnProperty.call(READERS, fn)) throw new Error("unknown reader");
  const r = await chrome.scripting.executeScript({ target: { tabId: tabId }, func: READERS[fn], args: args || [] });
  return r && r[0] ? r[0].result : null;
}

const JOBS = {
  // Which code is running: the folder on disk can be newer than what the browser loaded.
  about: async function () {
    return { version: chrome.runtime.getManifest().version, readers: Object.keys(READERS) };
  },

  // Load the folder's code again. The folder is read from disk, so this is how changed code takes hold at once: it is
  // refused unless the owner switched "let this mac reload me" on in the popup, which he does only while working on it.
  reload: async function () {
    if (!DEV_RELOAD) throw new Error("reload is switched off: reload at the extensions page, or switch it on in the popup");
    setTimeout(() => chrome.runtime.reload(), 500);
    return { reloading: true };
  },

  // GET one of the few addresses the engine reads (policy.js) with the owner's cookies, and return its text.
  // Any other address is refused here, whoever asked: this must never be a way to read an arbitrary signed-in page.
  fetch: async function (job) {
    if (POLICY.fetchOk(job.url, BLOCKED)) throw new Error("site not allowed");
    let r;
    try { r = await fetch(job.url, { method: "GET", credentials: "include", redirect: "follow" }); }
    catch (e) { return { status: 0, url: "", away: true, text: "" }; }     // sent on to a site this extension has no grant for (a sign-in page)
    const landed = hostOf(r.url);
    if (POLICY.fetchHosts.indexOf(landed) < 0 || POLICY.listed(landed, BLOCKED)) return { status: r.status, url: r.url.split("?")[0], away: true, text: "" };   // sent to a sign-in page: return nothing from it
    let text = await r.text();
    if (job.strip) text = strip(text);
    return { status: r.status, url: r.url.split("?")[0], text: text.slice(0, Math.min(job.max || 20000, 2000000)) };
  },

  // Run one named reader in a background tab.
  page: function (job) {
    return withTab(job, async (tab) => ({ url: tab.url.split("?")[0].split("#")[0], value: await exec(tab.id, job.fn, Array.isArray(job.args) ? job.args : []) }));
  },
};

wake();
