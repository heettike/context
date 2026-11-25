# permissions, in the order you meet them

context asks for a lot. this page lists every grant, what it unlocks, what the prompt looks like, and what goes wrong.
nothing here is granted silently: you click or type each one.

there are eight kinds.

| kind | how you grant it | prompt? |
|---|---|---|
| 1. full disk access | a switch in system settings | no prompt; you open the pane |
| 2. automation | "x wants access to control y" | system pop-up, once per app pair |
| 3. files and folders, and "data from other apps" | allow on the pop-up | system pop-up, once each |
| 4. accessibility (optional) | a switch in system settings | only from a button in the app's settings |
| 5. the browser | load the extension by hand, or turn on page scripting | from the browser, not from macos |
| 6. per-site grants in the extension | one click per site, then the browser's own question | from the browser |
| 7. account sign-ins | codes and passwords you type yourself (telegram, your ai plan) | in the terminal or on the site |
| 8. export requests | a button on each service, then an email | on the site |

the panes, exactly:

| permission | pane | opens with |
|---|---|---|
| full disk access | system settings > privacy & security > full disk access | `open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"` |
| automation | system settings > privacy & security > automation | `open "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"` |
| accessibility | system settings > privacy & security > accessibility | `open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"` |
| files and folders | system settings > privacy & security > files and folders | `open "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders"` (macos's usual address; not run here) |
| open at login | system settings > general > login items | `open "x-apple.systempreferences:com.apple.LoginItems-Settings.extension"` (the same) |

## the sequence

### step 0: nothing to grant

these work the moment the repo is cloned. `python3 -m ctx collect` reads them.

run `python3 -m ctx doctor` first. it shows which of these your mac has, reads no message, and makes no request to any site. it can raise the whatsapp pop-up below.

- whatsapp (mac app database), messages and calls. on macos 14 and later you may see **"would like to access data from other apps"**: allow.
- claude code, codex, cursor, grok bot session files
- obsidian vault. if the vault is in documents, desktop or icloud drive, macos asks once: **"would like to access files in your documents folder"**: allow.
- browser history from dia, chrome, arc, brave, edge, vivaldi or opera, whichever you use
- files in desktop, documents and downloads, once you start the media pass. macos asks once per folder.

a source whose app is not on your mac is skipped with one line saying so. that is not an error.

### step 0.5: your ai plan

context does its thinking on the plan you already pay for, through the claude code or codex cli on your mac.

- already signed in to either one: nothing to do.
- neither: run `claude auth login` or `codex login` once. it opens your browser; you approve there.
- context never sees a password or a key. it calls the cli; the cli holds the sign-in.
- `python3 -m ctx model` shows which one it found.

### step 1: full disk access

unlocks **imessage, apple mail, apple notes, safari history, contacts (the name book), reminders, the mac's call history, voice memos, the photos library, and attachments in imessage and notes**.

- system settings > privacy & security > full disk access. switch on the app that runs the collector, then quit and reopen it.
- there is no pop-up for this. the app opens the pane for you and waits until `~/Library/Messages/chat.db` becomes readable.
- which app to switch on: `context.app` if you use the mac app; your terminal if you run `python3 -m ctx collect` there.
- an app signed ad hoc (no apple development identity in your keychain) loses this grant at every install. switch it on again.
- to test it from a shell: `ls ~/Library/Application\ Support/com.apple.TCC >/dev/null && echo ok`.
- trap: coding agents often run commands under a helper identity that does not inherit the grant. if the agent's shell still says "blocked by macos" after you granted it, run the collector in a real terminal tab instead.
- know what you are granting. the installed app runs only the engine sealed inside it, so the grant goes to that code and no other folder. what is still open is at the top of [SECURITY.md](SECURITY.md).

### step 2: automation pop-ups

each appears once. click **allow**.

| pop-up | unlocks |
|---|---|
| "… wants access to control **notes**" | apple notes, without full disk access |
| "… wants access to control **calendar**" | calendar events. reading them starts the calendar app if it is closed |
| "… wants access to control **mail**" | account list, message counts |
| "… wants access to control **dia** / chrome" | page scripting: opening tabs and reading pages you are signed in to, and pressing "request my export" |

if you click don't allow: system settings > privacy & security > automation, switch it back on.

### step 3: accessibility (mac app only, optional)

unlocks **the title of the window you are in**, which the app uses for nudges and pings about what is on screen.

- it is not one of the four switches on the first-run screen. the button is in the app's settings, under "window titles".
- system settings > privacy & security > accessibility, switch on `context.app`.
- without it the app still reads, searches and answers. it sees which app is in front, not which document or chat.
- it reads titles. it does not read keystrokes or take screenshots.
- nudges come from plain rules on the mac and call no model. a switch in settings, off by default, lets your plan word them: that sends the app in front and its window title.

### step 4: the browser

unlocks **slack, google drive, x bookmarks, likes, posts and replies**, and with one more click each **chatgpt conversations and instagram saved posts**: sources that live behind a sign-in and have no file on disk.

there are two ways in. `python3 -m ctx doctor` shows which one your browser has.

**the extension**, in `extension/`. load it once by hand (steps in [extension/README.md](../extension/README.md)).

- it reads in background tabs. it never clicks, types or sends anything; it may scroll a tab it reads.
- its manifest names four sites: `app.slack.com`, `drive.google.com`, `docs.google.com`, `x.com`. it can read these as soon as it is loaded.
- a browser does not load an extension from a folder by itself. you do the five clicks.

**page scripting**, with nothing to load.

- dia: quit it and reopen with `--enable-applescript-javascript`. `python3 -m ctx request --enable-browser` does this, or the agent does after asking. your tabs come back. the flag is gone the next time you open dia normally.
- chrome, arc, brave, edge: view > developer > allow javascript from apple events.
- it reads a tab you already have open on the site. it opens one itself only if you set `CTX_OPEN_TABS=1`.
- export requests (step 7) always go this way, extension or not. `python3 -m ctx request --list` says which you have: `can_read` and `can_request`. the app's first run and its settings show the two apart: reading in the browser, and "ask sites for exports".

for both:

- safari and firefox: not supported for this step. you still get safari history (step 1) and every export in step 7, which you can request by hand on each site.
- you must already be signed in to the site in that browser. context never types a password.
- what it does there is read only: slack's own api from inside your slack tab, a text export of each google doc from inside your google tab, x's own lists with GET only.
- the read happens on the daily refresh: `python3 -m ctx tick daily`, or the app. `python3 -m ctx collect` reads files only and does not touch the browser.
- trap: a tab that is not visible on screen does not load new content. anything that needs scrolling (x bookmarks without the extension) only works while the browser window is in front. with the extension, x is asked for the list itself and nothing is scrolled.

### step 5: per-site grants in the extension

every site outside the four needs you, once, on that site.

- `chatgpt.com` and `www.instagram.com` have readers built in. they are **off** until you switch them on.
- a site you added as a source in the app is off until you switch it on.
- to switch one on: open the site, click the context icon, press **"let context read this site"**. the browser then asks you itself whether context may read that one site. allow.
- both must hold: your list in the popup, and the browser's grant. the engine and the helper can write neither.
- **"stop reading this site"** gives the grant back.
- **"never read this site"**, on one of the four built-in sites, keeps it out for good.
- the box **"let this mac reload me"** is off. leave it off unless you are changing the extension's code.

### step 6: telegram

telegram has no file to read and its web app only shows the last screen of each chat. the api gives everything.

1. `python3 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements-telegram.txt` in the repo folder. for the installed app, also in the repo folder: `/usr/bin/python3 -m venv ~/.context/v2/venv && ~/.context/v2/venv/bin/pip install --require-hashes -r requirements-telegram.txt`. this is the one place context installs anything; every version is fixed and every file is checked against its sha256.
2. my.telegram.org > api development tools. if you have no app there, create one. the id and hash go in `.env` (copy `.env.example`): in the repo folder, or `~/.context/v2/.env` for the installed app.
3. `python3 -m ctx telegram-login`. it shows a **qr code**; scan it from telegram on your phone (settings > devices > link desktop device), then type your **2-step password** if you have one. the agent cannot do these for you.
4. `python3 -m ctx collect-telegram`. hours, unattended.
5. a session file is saved as `~/.context/v2/telegram.session`. you will see a new device in telegram > settings > devices. remove it there to revoke access.

it exports every person and small group back to the first message. in groups over 300 members it keeps only what you wrote.

### step 7: export requests

for sources where the only complete copy is the one the service gives you. the agent can click "request" for you; it stops when a site asks for a password or a code.

| service | where | asks you for | arrives |
|---|---|---|---|
| x | settings > your account > download an archive | password, sometimes a code | about a day, in-app and email |
| google takeout | takeout.google.com (mail, calendar, contacts, keep, tasks, chrome, my activity, youtube) | sometimes your password | hours, by email |
| instagram | accounts center > your information and permissions > download | password | hours, by email |
| linkedin | settings > data privacy > get a copy of your data (larger archive) | nothing | up to a day, by email |
| chatgpt | settings > data controls > export | login code | minutes, by email |
| notion | settings > workspace > export all content | workspace admin | minutes, by email |

when the email comes, download the zip to `~/Downloads`. `python3 -m ctx ingest` does the rest, and so does the app within 15 minutes. the first time, macos may ask **"would like to access files in your downloads folder"**: allow.

the export pages are matched by their english labels. with an account in another language the request may stop with "the page did not get to the next step", and you click the button yourself.

**it asks again.** an export is stale from the day it is made, so each service you said yes to comes round again: monthly unless you change it.

- `python3 -m ctx request --list` and `schedule` only read the browser's preference file. no pop-up comes from looking. the "control dia / chrome" pop-up comes when you start a request.
- `python3 -m ctx driver --status` shows each one. `python3 -m ctx driver --every x=weekly` (or `monthly`, or `off`) changes one.
- it never starts a service you have not asked for once yourself, and never one you declined.
- when a site wants your password or a code, you get one reminder for that service in that round, with the tab ready. never more than one.
- when an export should be ready, context opens that service's own downloads page in a background tab. it never reads your mail to find a link.

### step 8: your ai apps

`python3 -m ctx mcp --install` writes one entry named `context` into the config file of each ai app it finds (claude desktop, cursor, claude code, codex and others), after saving a copy of the old file in `~/.context/v2/backups/`. no macos prompt. each app then starts the read-only server itself, on this mac. a newly connected app reads only a short profile until you open more for it (`python3 -m ctx api --set mcp:<app> --preset work`). `python3 -m ctx mcp --remove <id>` undoes it.

`python3 -m ctx api --key <name>` makes a key for one app or agent to read the archive over http, on this mac only. no macos prompt. [API.md](API.md).

chatgpt and claude.ai cannot reach a server on your mac. `python3 -m ctx remote --start` gives them a url through a tunnel. it is off until you run it, and it puts your history behind a secret url on the internet: read "how your ais connect" in the readme first.

### what spends your plan with no prompt

not a macos permission, and you should know it all the same.

- a nightly catch-up spends up to 40 model calls a night on your plan, with the app open (or `python3 -m ctx watch` running). on a new archive it is off: it starts after you have run the first read-through yourself, or set `nightly_calls` to a number. `python3 -m ctx catchup --status` says `on` and `why_not`. `python3 -m ctx settings --set nightly_calls=0` switches it off.
- one call a day writes the morning card, and one tiny call a day per model measures which models your plan can run. neither is made before the app's setup is done (`onboarded` in `app.json`), at launch or on the daily read. each has a switch: `settings --set morning_card=off`, `model_check=off`.
- the app adds three of its own, each with a switch: naming a new chat, looking longer after an unsure answer, and notes from your past while you write in the journal.
- all of them are on one card in the app: settings > general > "what context does on its own".

## what context never does

- type or store a password, a login code or a card number
- send, post, like, delete or change a setting on any account. the one thing it presses is "request my own export"
- read keystrokes or take screenshots
- upload the archive anywhere, or open it to the internet unless you start `remote` yourself
- read your mail to find a download link

## revoking

- full disk access, automation, accessibility: switch them off in system settings > privacy & security.
- a site in the extension: open it, click the context icon, "stop reading this site". all of it: remove the extension on the extensions page.
- telegram: settings > devices > remove the session; delete `~/.context/v2/telegram.session`.
- your ai apps: `python3 -m ctx mcp --remove <id>` for each, `python3 -m ctx api --revoke <name>` for each key, and `python3 -m ctx remote --stop`.
- everything: `python3 -m ctx remove` lists what context put on this mac, and `python3 -m ctx remove --all` moves it to the trash.
