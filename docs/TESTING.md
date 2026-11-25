# trying context on your own mac

## who this is for

you are a friend who said yes to trying context. you have a mac you actually use: real apps, real browser, years of messages. that is the only real test of this, and we cannot run it for you.

you will not send us your data, and we do not want it. at the end you run one command. it writes a short text file that says what worked and what broke on your machine, with nothing personal in it. you read it, then send it.

## before you say yes

- it takes about 30 minutes of your attention, plus a build of 10 to 25 minutes that needs no one.
- you need macos 14 or later and the command line tools (`xcode-select --install`). the repo is public.
- for answers you need claude code or codex signed in on this mac. collecting works without either.
- the mac app asks for full disk access. it runs only the engine sealed inside it. the open risks are at the top of [SECURITY.md](SECURITY.md). read them first.
- a nightly catch-up can spend up to 40 model calls a night on your own ai plan. it is off until you run the first read-through yourself. step 4 shows how to keep it off.

the full install, with every command, is [AGENTS.md](../AGENTS.md). you can open the folder in claude code or codex and say "run context"; it follows that file and stops to ask you at each permission, password and spend. the steps below are the short form.

## the six steps

1. clone it.

   ```bash
   git clone https://github.com/heettike/context && cd context
   ```

2. see what your mac has. this reads no message; it only checks that files exist. macos may ask once to let your terminal "access data from other apps": that is the whatsapp check.

   ```bash
   python3 -m ctx doctor
   ```

3. read your history. either install the app and follow its first-run screens:

   ```bash
   app/install.sh
   ```

   or do it by hand:

   ```bash
   python3 -m ctx collect
   ```

   macos will ask before some sources are read. each prompt is listed in [PERMISSIONS.md](PERMISSIONS.md). say no to any you do not like: that source is skipped and the report says so.

4. decide about the nightly catch-up. it starts once you have run the read-through. to keep it off for good:

   ```bash
   python3 -m ctx settings --set nightly_calls=0
   ```

5. use it for ten minutes.
   - ask three questions you know the answer to. in the app, or: `python3 -m ctx answer "what did i promise dana"`
   - add one source you expected and did not get: grant full disk access, load the extension ([extension/README.md](../extension/README.md)), or ask a service for an export with `python3 -m ctx request --list`.
   - note anything that felt slow, wrong or confusing.

6. make the report.

   ```bash
   python3 -m ctx report
   ```

   it prints where the file is: `~/Desktop/context-report-<date>.txt`. open it and read it before you send it. it is plain text. delete any line you would rather not share.

   if you have five more minutes, `python3 -m ctx report --try` also runs the real steps and times each one: doctor, a read of the file sources into a temp folder (removed after; your archive is not touched), a self-test of the server other ai apps use, and one tiny model call. it asks nothing in the terminal; macos may show the same prompts as in step 3.

## what the report holds

counts, states, versions and timings.

- the tool's version and commit
- macos version, chip, memory, free disk, which pythons you have
- whether the command line tools are there
- which browsers and which of the apps we read are installed, by name
- permission states: full disk access yes or no, how the last signed-in reads went
- each source: ok, stale, skipped or failed; how many rows; first and last month; seconds taken; the reason if it was skipped
- the ai plan: which cli is installed and signed in, which model does which job, measured speeds, calls today, error kinds
- index, read-through, events and wiki, as counts
- which ai apps the server is registered with
- the mac app: installed or not, version, how it was signed, the end of its log
- the last 30 errors: the error's type, our own file and line, and a redacted message
- how long collecting and each step of an answer took

## what it does not hold

- no message, title, thread name or contact name
- no file name from your folders. `~/Documents/taxes/2024.pdf` is written `~/Documents/…`
- no email address, phone number or link
- no account name. it says "signed in", never who
- not the name of your mac or your user. they are written `<host>` and `<user>`
- no keys or passwords. the telegram sign-in (`telegram.session`), the api keys and the remote secret are never opened for it
- not where you are or what language your mac is set to: no locale, no time zone
- no text of an error unless it is one of our own messages. anything else is replaced by its length, like `<42 chars>`

if you want one more word gone, add `--redact <word>`. you can repeat it.

`python3 -m ctx report --json` prints the same report as data.

## where to send it

open an issue with the tester report template and attach the file:

https://github.com/heettike/context/issues/new?template=tester-report.md

the repo is public, so the issue is public too. if you would rather not post there, send the file to whoever asked you to try it.

## how to remove everything

1. see what is there. this changes nothing:

   ```bash
   python3 -m ctx remove
   ```

2. take it off. it asks you to type the word `remove`, then moves every file to the trash. nothing is deleted outright.

   ```bash
   python3 -m ctx remove --all
   ```

   it stops the local servers, takes context's own entry out of each ai app's config, removes the browser link, the app, the keys and the archive. `--keep-archive` leaves your data in place.

3. do what only you can do. the command prints this list at the end:
   - the extension: your browser's extensions page > context > remove.
   - permissions: system settings > privacy & security. switch off `context` and your terminal under full disk access, accessibility and automation, if you switched them on for this.
   - telegram, if you linked it: telegram > settings > devices > remove the session.
   - a connector you pasted into chatgpt or claude.ai, if you ever started `remote`.
4. empty the trash when you are sure.
5. `remove` takes everything context created. delete what is yours: the export zips in `~/Downloads` (they hold your raw data), the report on your desktop, and the cloned folder (it holds `.venv` and `.env` if you set up telegram).

what context leaves running once the app is quit: the local api server, if you ever made a key (`python3 -m ctx api --stop` ends it; `remove` stops it too), and the remote endpoint, if you started it. nothing else. the app has a switch, "open context when you log in", which is off until you turn it on. if you turned it on, switch it off in the app's settings before you remove the app.

## running the tests

```bash
python3 -m unittest discover tests
```

- the tests use made-up data in a made-up home folder. they never read your archive, your `.env` or your signed-in model cli.
- it takes a few minutes. the tests are meant to pass on the system python (3.9) and on newer ones.
- the app's own checks run inside `app/build.sh`: it draws every screen off-screen and fails the build on a clipped or overlapping one.
