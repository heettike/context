# context extension

reads your own slack, google docs and x lists in the background, and sites you switch on, for the context engine on this mac.
it never clicks, types, sends or changes anything in your accounts, and it sends what it reads to nothing but the helper on this mac.

what it does do in your browser:

- it opens background tabs on the sites it reads, and may use a tab you already have open on that site.
- it may scroll a tab it reads.
- slack is read with requests that use the POST method, because that is how slack's own api is called. they ask for your messages; they send none.

version 0.7. manifest v3. for dia, chrome, chromium, arc, brave and edge.

## load it (once, by hand; about 3 minutes)

1. run `python3 -m ctx bridge --install` in the repo. it tells each browser where the local helper is.
2. open `chrome://extensions` (in dia: `dia://extensions`).
3. turn on "developer mode" (top right).
4. click "load unpacked".
5. pick this `extension` folder. if the context app is installed, pick the copy inside it instead: `/Applications/context.app/Contents/Resources/engine/extension`. that copy is read-only, and the app's browser switch shows it in finder.

check it with `python3 -m ctx bridge --status`: within a minute `connected` turns true.
the extension id is always `bcgoemooaoejbcndipjlhjoojelkkdih`.

a browser does not load an extension from a folder by itself. these five steps are yours.

`bridge --install` refuses when the repo folder is not yours, or is writable by anyone else: the browser starts python from that folder every minute.

## the four sites

the manifest gives it four sites and no more. they can be read as soon as the extension is loaded.

| site | what is read |
|---|---|
| `app.slack.com` | your messages, read from a slack tab with slack's own api |
| `drive.google.com` | the list of your docs, slides and sheets |
| `docs.google.com` | a text view of each one |
| `x.com` | your bookmarks, likes, posts and replies, asked from x's own data address (GET only) |

you must be signed in to each in this browser. the extension never types a password.

## every other site: one grant each

every other site is in the manifest's `optional_host_permissions`. the browser asks you, one site at a time.

- `chatgpt.com` and `www.instagram.com` have readers built in. they are **off** until you switch them on.
- any site you added as a source in the app is off until you switch it on.

to switch a site on:

1. open that site.
2. click the context icon.
3. press "let context read this site".
4. the browser then asks you itself whether context may read that one site. allow.

both must hold: your list in the popup, and the browser's grant. the engine can change neither: they live in this browser.

- "stop reading this site" takes the site off your list and gives the grant back.
- "never read this site", on one of the four built-in sites, keeps it out for good. "let context read this site again" undoes it.
- the popup lists every site you added and every site you marked, each with a button to undo it.

what is read once a site is on:

| site | what is read |
|---|---|
| `chatgpt.com` | conversations that are new or changed, with chatgpt's own api from its tab |
| `www.instagram.com` | your saved posts. instagram refuses its chats and likes this way; those come only with the export |
| a site you added | the page you chose, by fixed selectors |

## the reload tick box

the popup has one box: "let this mac reload me (only while you are changing the extension's code)".

- it is **off** by default.
- off, the extension refuses when the engine asks it to load the folder's code again.
- tick it only while you are changing this folder's code. untick it when you are done.
- ticked or not, the browser reads this folder's code each time it starts.

## after an update

if `manifest.json` changed, a plain reload keeps the old permissions. remove the extension and load the folder again.
the popup says so itself when it sees this: "one more step: open the extensions page, remove context, and load the folder again."

`python3 -m ctx bridge --status --deep` shows the version the browser runs beside the version in the folder, and `stale` when they differ.

## what it cannot do

- send a message, click, type or change anything. every job is a read, though one site is read with requests that use the POST method.
- take orders from a web page or another extension. it listens only to the helper on this mac (`so.context.bridge`).
- run code it was sent. it runs only the readers in `readers.js`.
- run a reader anywhere but on its own site, or fetch any address but the few the engine reads (`policy.js`).
- read a site the browser was not asked about, one you did not add, or one you marked "never read".
- reload itself because the mac asked, unless you ticked the box.

its code is read from the folder you loaded each time the browser starts, and the browser does not check who changed it.
this is an open risk. [docs/SECURITY.md](../docs/SECURITY.md), open item 1, says what it means. the fix is the chrome web store, and that is not done.

what it reads is scrubbed for secrets and saved under `~/.context/v2/imports/`.

## how it works

every minute the extension asks the local helper (`ctx/bridge.py`) for work.
the engine leaves signed jobs in `~/.context/v2/bridge/jobs/`.
the helper checks the signature, the job's age (15 minutes at most) and what is asked, and passes it on.
answers land in `~/.context/v2/bridge/results/`.
with no work the helper hangs up after 20 seconds and the extension sleeps.

the reads happen on the engine's daily refresh: the app does it, or `python3 -m ctx tick daily`.

## remove it

1. `chrome://extensions` > context > remove.
2. `python3 -m ctx remove --only hosts` moves the helper's files to the trash. or by hand: delete `so.context.bridge.json` from the browser's `NativeMessagingHosts` folder
   (dia: `~/Library/Application Support/Dia/User Data/NativeMessagingHosts`; chrome: `~/Library/Application Support/Google/Chrome/NativeMessagingHosts`; `python3 -m ctx bridge --status` lists the browsers it was written for), and delete `~/.context/v2/bridge`.

## limits

- x gives each list a number of answers per quarter hour. a long first read stops one short of that, keeps its place in `imports/<file>.at`, and goes on at the next daily read.
- the popup's buttons and the browser's per-site question have been tested by code against a stand-in browser, not by hand in a real one.
- most of the supported browsers are written for and not yet run for real.
