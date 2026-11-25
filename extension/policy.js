// What a job may touch. One table, used by the worker (background.js) and the popup, and mirrored in ctx/guard.py
// so the helper refuses the same things before they reach the browser. Nothing here can be changed by a job.
const POLICY = {
  // reader -> the hosts it belongs on. null: a page the owner added as a source, on a site he allowed in the popup.
  readers: { slack_read: ["app.slack.com"], drive_list: ["drive.google.com"], x_me: ["x.com"], x_api: ["x.com"], x_ops: ["x.com"], chatgpt_api: ["chatgpt.com"], ig_api: ["www.instagram.com"], survey: null, recipe: null },
  // the only addresses a fetch job may GET with the owner's cookies
  fetch: /^https:\/\/(docs\.google\.com\/(document\/d\/[\w-]{10,120}\/mobilebasic|presentation\/d\/[\w-]{10,120}\/htmlpresent|spreadsheets\/d\/[\w-]{10,120}\/gviz\/tq\?tqx=out:csv)|app\.slack\.com\/client)$/,
  // built-in sites that are off until the owner switches them on in the popup, on that site: the browser asks him once
  // for that site, and from then on its reader may run there
  optional: ["chatgpt.com", "www.instagram.com"],
  // where a fetch may end up after redirects and still hand its text back
  fetchHosts: ["docs.google.com", "app.slack.com"],
  hostOf: function (u) { try { const x = new URL(u); return x.protocol == "https:" && !x.username && !x.password ? x.hostname.toLowerCase() : ""; } catch (e) { return ""; } },
  builtin: function (host) { return POLICY.optional.indexOf(host) < 0 && (Object.keys(POLICY.readers).some((r) => POLICY.readers[r] && POLICY.readers[r].indexOf(host) >= 0) || POLICY.fetchHosts.indexOf(host) >= 0); },
  // the address pattern the browser is asked to grant for one site the owner adds
  origin: function (host) { return "https://" + host + "/*"; },
  listed: function (host, list) { return (list || []).some((b) => typeof b == "string" && b && (host == b || host.endsWith("." + b))); },
  // "" when this reader may run on this address, else why not. blocked and allowed are the owner's two lists.
  page: function (fn, url, blocked, allowed) {
    if (typeof fn != "string" || !Object.prototype.hasOwnProperty.call(POLICY.readers, fn)) return "unknown reader";
    const host = POLICY.hostOf(typeof url == "string" ? url : "");
    if (!host) return "site not allowed";
    if (POLICY.listed(host, blocked)) return "site not allowed";
    const hosts = POLICY.readers[fn];
    if (hosts) return hosts.indexOf(host) >= 0 && (POLICY.optional.indexOf(host) < 0 || POLICY.listed(host, allowed)) ? "" : "site not allowed";
    return POLICY.listed(host, allowed) ? "" : "site not allowed";
  },
  fetchOk: function (url, blocked) {
    if (typeof url != "string" || !POLICY.fetch.test(url)) return "site not allowed";
    return POLICY.listed(POLICY.hostOf(url), blocked) ? "site not allowed" : "";
  },
};
if (typeof module != "undefined") module.exports = POLICY;
