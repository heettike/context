<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-dark.svg">
  <img src="docs/assets/logo-light.svg" alt="context" width="215">
</picture>

one memory on your mac, for every ai you use.

> **read this first.**
> - this is early. it was built by one person, for their own use.
> - macos only.
> - it reads very private data: your messages, mail, notes and files, and with the app it holds full disk access.
> - read [docs/SECURITY.md](docs/SECURITY.md) before you install it. the open risks are listed at its top.
> - no warranty. see [LICENSE](LICENSE).

context reads your chats, mail, notes, docs, posts, files and coding sessions into one folder of plain files, `~/.context/v2/`.
you ask it questions, and it answers from that folder with the messages it used.
claude code, claude desktop, cursor, codex and eight other ai apps read the same folder through a local, read-only server.

no account. no server of ours. nothing is sent to the author: no telemetry, no update check, no crash report.

what does leave the mac, and where it goes:

- what your own ai plan reads, to the company whose plan it is (anthropic or openai): your question, the messages the search finds, pages about you. this happens for every answer, every read-through, and the automatic calls in the table under "what it costs you".
- what an ai app you connect (claude code, cursor, codex and the rest) reads through the server goes to that app's own company, under that company's terms.
- requests to the sites you are signed in to, from your own browser, to read your own data there: slack, google, x, and any site you switch on.
- requests to telegram's servers, if you set telegram up.
- a plain request to each website, feed or repo you add as a source.
- nothing for icons, unless you switch on "fetch source icons from their sites" in settings: then one request per source to that service's own site.
- nothing else, unless you start the remote endpoint yourself.

```bash
git clone https://github.com/heettike/context && cd context
python3 -m ctx doctor          # what this mac has. reads no message
app/install.sh                 # build the mac app and open it. 10 to 25 minutes, mostly waiting
```

**the only real copy is `https://github.com/heettike/context`.** there is no installer to download, no command to paste from a page, an ad, a message or a call, and no other repo, package or site that is context. nobody from this project will ever send you an installer or a "fix" command by dm: if someone does, it is not us.

macos 14 or later. it needs the command line tools (`xcode-select --install`), and the python 3.9 they bring is enough. no packages, no homebrew. the one thing ever installed from the network is telegram's packages, if you set telegram up, from a file of fixed versions and hashes (`requirements-telegram.txt`).

**the whole install, step by step, is [AGENTS.md](AGENTS.md).** open this folder in claude code or codex and say **"run context"**: the agent follows that file and stops to ask you at every permission, password and spend.

## before you install

- **it acts on your accounts, read only.** every day, in your own signed-in browser, it reads your own data on the sites you allow. it never clicks, types, sends or changes anything there, with one exception you start yourself: pressing "request my export".
- **two sites' terms forbid automated reading.** chatgpt and instagram are off until you switch each on yourself. a read there is one tab and a few requests a day, and it stops at the first refusal. the risk to your account is yours to weigh.
- **exports are asked for again every month**, for the services you asked once yourself. it stops for any password or code and tells you once.
- **it spends your ai plan** in a few places with no click. the table under "what it costs you" lists every one.
- **`mcp --install` rewrites the entry named `context`** in the config files of your other ai apps. it keeps a copy of each old file in `~/.context/v2/backups/configs/`, the newest three per app. those copies hold the other servers and keys in those apps' configs. every connected app reads only a short profile until you open more, whatever it read before an update.
- **`python3 -m ctx remove --all` moves the whole archive to the trash**, with everything else context made. it asks you to type a word first, and it leaves alone a folder that is not a context archive.

## what you get

- **an archive you can grep.** one json object per line, in `messages.jsonl`, `docs.jsonl`, `sessions.jsonl` and `prompts.jsonl`. keys, passwords and seed phrases are removed before a row is written.
- **answers from your own history.** `python3 -m ctx answer "what did i promise dana"` replies with the rows it used.
- **pages about you.** a read-through writes a card per conversation, then a wiki: a page per person, project, year and theme, each paragraph with its evidence.
- **a memory your ais share.** read-only tools over mcp, named `context_*`, with limits per app. a local http api with one key per app.
- **a mac app** on the same folder: a question box, first-run screens that walk you through each permission, about you, sources, settings.
- **your files too.** pictures, pdfs and voice notes are read on the mac, with no model and no network.

## what it costs you

| | |
|---|---|
| your attention | about 30 minutes in two sittings: permissions first, export downloads later |
| waiting | the app build (10 to 25 minutes), telegram (hours), the media pass (hours), exports (minutes to a day) |
| money | nothing to us. model work runs on the claude or chatgpt plan you already pay for, through its signed-in cli |
| disk | a few hundred megabytes for the build; the archive's text is small; raw exports can be gigabytes |

collecting is free: it is file reads on your mac.

model calls happen when you ask a question or start a job (the read-through, the wiki, the voice guides, a rule, adding a source). the app also makes calls on its own. every one has a switch on one card: settings > general > "what context does on its own".

| what context does on its own | the call | default |
|---|---|---|
| nudges worded by your plan | at most one every 20 minutes, when you drift from what you set out to do or change the kind of app you are in. it sends the app in front, its window title when macos lets context read it, and today's apps | off |
| name a new chat | one small call after the first answer of a chat, sending the question and the start of the answer | on |
| look longer after an unsure answer | when a quick answer is weak, up to three more rounds of searching and reading | on |
| from your past, while you write | one call for each paragraph of twelve words or more you write in the journal, three seconds after you stop, sending that paragraph | on |
| the morning card | one call a day, during the daily read, once the app's setup is done | on |
| measure the models once a day | one tiny call to each model your plan can run, during the daily read, once the app's setup is done | on |
| read again every week | once a week the engine reads again what changed | off |
| catch up at night | at most 40 calls a night, on conversations not yet read and pages gone stale | off until you have run the first read-through |

without the app, the engine's own four are settings: `python3 -m ctx settings --set morning_card=off`, `model_check=off`, `reread_weekly=off`, `nightly_calls=0`. the morning card and the model check wait for the app's setup to be done (the app records it in `app.json`): before that, and with no app at all, neither is made.

two settings change what a call costs, not whether it is made. when your plan hits its limit, everyday answers carry on with a quicker model, on another signed-in plan if there is one (settings > "carry on with a quicker model at a limit"). and with an `ANTHROPIC_API_KEY` in `.env`, the api counts as a plan billed per token: its models are measured daily too, and a plan at its limit can fall back to it. the engine uses that key only in its own request to the api (python's standard library, nothing to install, `claude-opus-5-5` unless a call names another api model). it never hands the key to the claude or codex cli, so they keep billing your plan.

| job you start | size |
|---|---|
| one answer | a few thousand tokens |
| the read-through of everything | the whole archive once, in pieces; `understand --estimate` gives the calls for yours before anything runs, and it picks up where it stopped |

## what it reads

every source is read back to its first row.

| source | how | you grant |
|---|---|---|
| whatsapp | mac app database | nothing (app installed and synced) |
| imessage | `chat.db` | full disk access |
| apple mail | mail files on disk | full disk access |
| apple notes | notes database | full disk access, or the "control notes" prompt |
| contacts | the contacts app's stores: builds the name book (whose number is this), and a row per contact you wrote a note on | full disk access |
| reminders | title, notes, list, due, done | full disk access |
| calls | the mac's call history and whatsapp's own: who, when, how long, which way. nothing said is kept | full disk access for the mac's history; none for whatsapp's |
| voice memos | title, date and length; the words through the media pass | full disk access |
| pictures, pdfs, documents, voice notes, videos | read on the mac by apple's own frameworks. [docs/MEDIA.md](docs/MEDIA.md) | full disk access for photos, attachments and voice memos; you start the first pass |
| calendar | calendar app | the "control calendar" prompt |
| obsidian | vault files | nothing |
| claude code, codex | session files | nothing |
| cursor, grok bot | app's local files | nothing |
| browser history (dia, chrome, arc, brave, edge, vivaldi, opera) | browser database | nothing |
| safari history | browser database | full disk access |
| slack | slack's api, called inside your signed-in tab | the extension, or browser scripting |
| google drive | docs, slides, sheets read inside your signed-in tab | the extension, or browser scripting |
| x bookmarks, likes, posts, replies | x's own lists, asked from a background tab | the extension |
| chatgpt conversations | chatgpt's own api, from its tab | the extension, with chatgpt.com switched on by you |
| instagram saved posts | instagram's own api, from its tab | the extension, with www.instagram.com switched on by you |
| telegram | telegram's api | api id, qr login, two-step password |
| x chats and old posts | account archive | archive request |
| instagram dms, saved, likes | account export | export request |
| linkedin: connections, messages, posts, reposts, comments, articles, invitation notes, recommendations, saved posts, reactions, searches, one profile row | the complete account export. not read: ad targeting, inferences, logins, security, receipts | export request (ask for the complete archive) |
| chatgpt, the full copy | account export | export request |
| gmail, youtube, keep | google takeout | takeout request |
| notion | workspace export | export request |

readers are tested on made-up data: files written in the shape the app or service writes, read in a clean home folder. some have also run on a real archive.

signed-in reads need dia, chrome, arc, brave or edge. safari gives history only. firefox is not read.
add an app, a website, a feed or a folder that is not on this list with `python3 -m ctx connect --search "<name>"`.

how each one gets in, the export driver and its monthly reminder, and what needs a password: [AGENTS.md, section 7](AGENTS.md#7-every-source-and-how-it-gets-in).
every prompt you will see: [docs/PERMISSIONS.md](docs/PERMISSIONS.md).

## the extension

`extension/` reads signed-in sites in background tabs. you load it by hand, once.

- its manifest names four sites: `app.slack.com`, `drive.google.com`, `docs.google.com`, `x.com`.
- every other site, chatgpt and instagram included, is off until you switch it on in the popup, on that site. the browser then asks you itself.
- "let this mac reload me" is off. tick it only while you change the extension's code.

steps: [extension/README.md](extension/README.md).

## commands

`python3 -m ctx --help` prints every command. `python3 -m ctx <command> --help` explains one. the ones you will use:

```
doctor                      what this mac has and lacks. --json for the raw report
model [--test]              which ai plan model calls run on
collect | collect-one <s>   read every source that is a file on this mac, or one
tick [fast|daily|weekly]    do whatever refresh is due. watch does this every 15 minutes
ingest                      unpack export zips from ~/Downloads, then collect
request --list | <id>       ask a service for your data export, in your browser
driver --status             exports that come round by themselves; --every <id>=weekly|monthly|off
media --estimate | --scan   pictures, voice notes, files, videos, read on this mac
answer "<question>"         an answer from the archive, with the rows it used
understand [--estimate]     read everything once and write pages about you
wiki --estimate | --build   a page per person, project, year and theme
catchup --status            the nightly catch-up: what it did, what is behind
rules --add "<sentence>"    a standing rule: count this more, leave that out, answer like this
made | voice | correct      things made here; how you write; fix a line about you
mcp --install [id] [--preset <p> | --all] | --status | --remove <id>
api --key <name> | --keys | --set <name> | --revoke <name>
settings [--set key=value]
rawscrub [--apply]          take secrets out of the raw export files
remove [--all | --keep-archive | --only <id>]
report                      a tester report with nothing personal in it
```

`collect` reads files and nothing else. `tick daily` (and so `watch` and the app) also talks to your browser and the calendar app, and makes a few small model calls.

## how your ais connect

### on this mac: mcp

```bash
python3 -m ctx mcp --install                        # every ai app found; each reads a short profile only until you open more
python3 -m ctx mcp --install cursor --preset work   # open one app further: profile | work | writing | people, or --all
python3 -m ctx mcp --status                         # where it is registered, and any entry another program changed
```

this adds a server named `context` to each of these it finds: claude desktop, cursor, claude code, codex, gemini cli, vs code (copilot), windsurf, devin, zed, cline, lm studio, opencode.
it writes into each app's own config file and keeps a copy of the old file in `~/.context/v2/backups/configs/` first (the newest three per app).
for claude code it changes the entry with claude's own cli, and only when the entry named `context` there is its own (`--replace` takes another program's).
an app counts as found when its config folder exists, so open a new app once before you run this.

- the server is a child process each app starts on your mac. it speaks over stdin and stdout, opens no port, and only reads.
- every tool is named `context_<name>`. a tool without that prefix is not this server's.
- each app has its own limits, read log, hold and way to close it, like an api key. `python3 -m ctx api --keys` lists apps and keys together.
- every app starts at the short profile, named or not, on a new archive or one with years in it. nothing is opened for you: `python3 -m ctx api --set mcp:<app> --preset work` (or `--all`) is how an app reads more. after an update, an app or a key that read everything under an older key file is narrowed, and `api --keys` says so with the command that opens it.
- context's own answering loop is told apart from other apps by a pass made for each run, never by a name an app's config could set.
- in what a tool returns, a web address stays a link only when a message or page you wrote or saved holds it. any other is written as its site, as plain words.

### anything else: the api

```bash
python3 -m ctx api --key my-agent --preset work    # mail, slack, drive, calendar
python3 -m ctx api --key my-agent --sources whatsapp --people "dana okafor" --after 2025-01
python3 -m ctx api --revoke my-agent
```

- it answers on this mac only and is read only. every install picks its own port at random once and keeps it; `api --status` prints it. there is no fixed port.
- a new key reads nothing until you open it: with a preset (`profile`, `work`, `writing`, `people`), with limits, or with `--all`, which warns you.
- a key lasts 30 days unless you say otherwise.
- what each key read is logged per day, a key far past its usual day is held, and one never list sits above every key, every ai app and the app's own answers.
- these bound an app that holds a key. they do not bound a program already running as you.

[docs/API.md](docs/API.md).

### chatgpt and claude.ai on the web (optional, off, untested)

these take only https connectors, so they cannot reach a server on your mac. `python3 -m ctx remote --start` opens a tunnel and prints a url to paste into them. it needs `cloudflared` or `tailscale`, which you install yourself.

know what this does before you start it:

- your history is then reachable from the internet by anyone who has the url. the only lock is a secret in its path. `remote --rotate` replaces it.
- whatever those apps read goes to openai's or anthropic's servers.
- it serves six tools, masks phone numbers and email addresses, caps calls at 30 a minute and 1,000 a day, and logs the size of each call, never its content.
- nothing starts it but you. `remote --stop` ends it.
- it has never been run through a real tunnel. do not start it for a second person yet.

## privacy and security

everything context collects stays in `~/.context/v2/`, closed to other accounts on the mac. there is no telemetry and no update check.

read [docs/SECURITY.md](docs/SECURITY.md) before you give this to anyone. open today:

1. **any program you run can read the archive.** it is a folder in your home; nothing on a mac stops your own programs from reading it.
2. **the extension is unpacked code.** the browser reads it from a folder and does not check who changed it. the copy inside the installed app is read-only.
3. **without your own signing identity the seal can be remade.** the app is then signed ad hoc, and macos asks for full disk access again after every install.
4. **raw exports are unscrubbed until you run the scrubber.** `python3 -m ctx rawscrub` counts the secrets in `~/.context/v2/imports/`; `--apply` takes them out.
5. **the model cli's isolation is shown by its flags, pending a live check.** the check exists (`scripts/verify_cli_isolation.py`) and has not been run, because it spends a plan.

also know:

- an address that only someone else's message holds is shown as plain words, not a link. it is still shown.
- `~/.context/v2/telegram.session`, if you set telegram up, is a full sign-in to your telegram account, kept as a file: a full account credential. it is held to 0600 each time the engine starts, and `report` never opens it.
- a site you switch on in the extension stays readable until you switch it off there: the grant is per site, and it is yours to take back.
- the app's and the helper's ids (`so.context.app`, `so.context.bridge`) are reverse-domain style names. they imply no website.

what holds: the installed app runs only the engine sealed inside it, on the system python started isolated. the model reads your archive in an empty folder with no tools of its own. an answer draws no pictures, and links only to addresses you wrote or saved.

after a `git pull`, run `app/install.sh` again, then `python3 -m ctx mcp --install` and `python3 -m ctx bridge --install`, and reload the extension from the app's copy. [AGENTS.md, section 22](AGENTS.md#22-updating).

### secrets

keys turn up in chats. every row passes through `ctx/scrub.py` before it is written, so the files, the mcp tools and the model see `[redacted]`.

it removes:

- api keys with a known prefix, telegram bot tokens, jwts, cookies and connection strings
- private keys, pem and pgp blocks
- `password is ...`, `token: ...`, `NAME_KEY=...`, and `user:pass@` in a url
- seed phrases of 12 or more words: in a sentence, numbered, capitalised, one per line, or in a grid
- one-time codes, card numbers that pass the check digit, bank and identity numbers with a cue
- from browser history: the query string of every url, and sign-in and localhost pages

it keeps wallet and contract addresses, which are public.

it misses:

- a short all-lowercase password with no word near it that says so
- six bare digits with no cue
- a seed phrase cut in two by other words
- what no rule covers inside a photo or a pdf

it also changes some lines that hold no secret: about 5 in 100 ordinary lines in its own test set.

### to remove it all

```bash
python3 -m ctx remove          # lists everything it put on this mac. changes nothing
python3 -m ctx remove --all    # moves it all to the trash, after you type the word remove
```

it takes everything context created, and ends with what only you can do: remove the extension, switch off full disk access, remove the telegram device. the export zips you downloaded to `~/Downloads` are yours; delete those yourself.

## not tested

- macos 14: no runner builds it.
- intel macs and macos 15 by hand: the workflow in `.github/` builds the app and runs the tests on both, and nobody has used the app on either.
- most of the supported browsers, for signed-in reads and export requests
- the extension popup's buttons and the browser's per-site question, by hand in a real browser
- apple mail across account kinds and languages
- a mac with no command line tools
- `app/install.sh` on an account that is not an admin
- the remote endpoint through a real tunnel
- notion and google takeout exports
- writing in your voice: it has not passed its blind test. [docs/EVAL.md](docs/EVAL.md)
- linux and windows are not supported. it says so in one line and stops.

## when something goes wrong

the table is in [AGENTS.md, section 23](AGENTS.md#23-troubleshooting). the three most common:

| you see | what it means |
|---|---|
| `blocked by macOS` | full disk access is off for the app running the command. a coding agent's shell often lacks it even after you grant it: use the app, or a terminal tab |
| `no model is signed in on this mac` | run the command printed after it. collecting does not need a model |
| slack, drive or x never arrive | `collect` does not read them. the daily read does, with the extension loaded and your browser signed in |

`python3 -m ctx report` writes the thing to send with a bug. it holds no message text. [docs/TESTING.md](docs/TESTING.md).

## layout

```
ctx/collect.py      sources that are files on this mac, one function each
ctx/apple.py        contacts, reminders, calls, voice memos
ctx/namebook.py     whose number or address is this
ctx/media.py        pictures, pdfs, voice notes and videos, read on this mac
ctx/mail.py         apple mail from disk
ctx/exports.py      account archives: x, google, instagram, linkedin, notion
ctx/signed_in.py    slack, drive, calendar, x, chatgpt, instagram through your browser
ctx/bridge.py       the extension's local helper
ctx/request.py      asks services for your exports, in your signed-in browser
ctx/driver.py       asks again on a cadence, with one reminder at most
ctx/schedule.py     what is read every 15 minutes, daily, weekly
ctx/scrub.py        secret removal; ctx/rawscrub.py for the raw export files
ctx/llm.py          model calls through your own claude or chatgpt plan
ctx/understand.py   the read-through; ctx/wiki.py the pages; ctx/catchup.py a little each night
ctx/answer.py       questions answered from the archive
ctx/rules.py        your standing rules; ctx/made.py things made here; ctx/voice.py how you write
ctx/mcp.py          the read-only server for other ai apps
ctx/api.py          the local http api, with keys
ctx/remote.py       the same tools over https, off by default
ctx/remove.py       take it all off again
app/                the mac app (swift)
extension/          browser extension for background reads
tests/              python3 -m unittest discover tests
AGENTS.md           the runbook
```

## what was decided, and what is left

[docs/DECISIONS.md](docs/DECISIONS.md) is the checklist: every rule this follows and every open item. to change something here, read [CONTRIBUTING.md](CONTRIBUTING.md) first. answer quality is measured in [docs/EVAL.md](docs/EVAL.md). what this release holds: [CHANGELOG.md](CHANGELOG.md).

## license

mit. see [LICENSE](LICENSE).
