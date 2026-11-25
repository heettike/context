// The owner's two lists, kept in this browser and written only here: sites context may read as a source he added,
// and sites it must never read. The built-in sources (policy.js) need no adding.
const host = POLICY.hostOf;
const STORE = (chrome.storage && chrome.storage.local) || null;
function show(here) {
  if (!STORE) {       // the browser is still running the older manifest: say how to finish the update instead of failing silently
    document.getElementById("site").textContent = "one more step: open the extensions page, remove context, and load the folder again. a plain reload keeps the old permissions.";
    document.getElementById("toggle").hidden = true;
    return;
  }
  STORE.get({ blocked: [], allowed: [], dev_reload: false }, (v) => {
    const blocked = Array.isArray(v.blocked) ? v.blocked : [], allowed = Array.isArray(v.allowed) ? v.allowed : [];
    const site = document.getElementById("site"), btn = document.getElementById("toggle"), list = document.getElementById("list");
    const off = here && blocked.indexOf(here) >= 0, built = here && POLICY.builtin(here), on = here && allowed.indexOf(here) >= 0;
    const drop = (l, h) => l.filter((b) => b != h);
    let say = "context reads slack, google drive and x in the background. chatgpt, instagram and any other site are read only after you add them here, on that site.", label = "", next = null;
    if (off) { say = here + ": never read"; label = "let context read this site again"; next = { blocked: drop(blocked, here) }; }
    else if (built) { say = here + ": can be read"; label = "never read this site"; next = { blocked: blocked.concat([here]) }; }
    else if (on) { say = here + ": can be read, because you added it"; label = "stop reading this site"; next = { allowed: drop(allowed, here) }; }
    else if (here) { say = here + ": not read"; label = "let context read this site"; next = { allowed: allowed.concat([here]) }; }
    site.textContent = say;
    btn.hidden = !next;
    btn.textContent = label;
    // adding a site: the list is written first, then the browser asks the owner for that one site (the popup may close
    // on that question; the worker needs both the list and the grant). taking a site off gives the grant back.
    btn.onclick = () => {
      const adding = next.allowed && next.allowed.length > allowed.length, dropping = next.allowed && next.allowed.length < allowed.length;
      STORE.set(next, () => {
        if (adding) chrome.permissions.request({ origins: [POLICY.origin(here)] }, () => { void chrome.runtime.lastError; show(here); });
        else if (dropping) chrome.permissions.remove({ origins: [POLICY.origin(here)] }, () => { void chrome.runtime.lastError; show(here); });
        else show(here);
      });
    };
    list.textContent = "";
    const row = (text, word, change) => {
      const li = document.createElement("li"), name = document.createElement("span"), undo = document.createElement("button");
      name.textContent = text;
      undo.textContent = word;
      undo.onclick = () => STORE.set(change, () => {
        if (change.allowed) chrome.permissions.remove({ origins: [POLICY.origin(text.split(":")[0])] }, () => { void chrome.runtime.lastError; show(here); });
        else show(here);
      });
      li.appendChild(name);
      li.appendChild(undo);
      list.appendChild(li);
    };
    allowed.filter((b) => b != here).forEach((b) => row(b + ": added", "remove", { allowed: drop(allowed, b) }));
    const dev = document.getElementById("dev");
    if (dev) { dev.checked = v.dev_reload === true; dev.onchange = () => STORE.set({ dev_reload: dev.checked === true }); }
    blocked.filter((b) => b != here).forEach((b) => row(b + ": never read", "allow", { blocked: drop(blocked, b) }));
  });
}
chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => show(host((tabs[0] || {}).url || "")));
