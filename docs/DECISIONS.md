# decisions and checklist

the rules this product follows, and what is still open. each line is a rule the code follows or a thing not done
yet. a box is ticked only when the work is in the repo and tested.

how answer quality is measured: [EVAL.md](EVAL.md). the permission sequence: [PERMISSIONS.md](PERMISSIONS.md).

## what this is

- [x] one memory on your mac, for every ai you use. the archive is plain files in `~/.context/v2`.
- [x] a chat app over it: claude's frame, with your own life as the knowledge.
- [x] other ais read it through one local mcp server. nothing is hosted.
- [x] the model is the one you already pay for. no api key needed, no account with us.

## decisions on data

- [x] collect lifetime history from every source, not a recent window.
- [x] prefer official exports and apis over reading pages. telegram through its api only.
- [x] nothing is installed from the network but telegram's packages, each at a fixed version and named by its hash, and they are pinned again by hash when first loaded.
- [x] every python the engine starts is isolated: it takes code from the engine folder only.
- [x] the few words of a language the engine needs live in language packs; nothing assumes which languages the owner writes in.
- [x] the language voice notes are read in follows the mac, and is stored with the archive at the first one.
- [x] every row passes the secret scrubber before it is written: keys, tokens, seed phrases, passwords, card numbers.
- [x] a seed phrase inside a sentence, numbered or one word per line is caught.
- [x] the scrubber runs on text only, never on ids or json structure.
- [x] a source that is blocked, missing or broken keeps the rows it had. a read that comes back empty is treated as blocked.
- [x] ids come from content, so re-downloading an export does not duplicate or renumber rows.
- [x] an archive downloaded twice is read once.
- [x] the first export of a service is started only by the owner. after that each comes round on a cadence (monthly by default, weekly or off per service: `python3 -m ctx driver --every x=weekly`) and a driver does every step that needs no secret.
- [x] when a site wants a password, a code or a sign-in the driver stops and says that one step, once: never more than one reminder for a service in a cycle, and nothing for a service the owner declined.
- [x] when an export should be ready the driver opens the service's own downloads page in a background tab. it never reads mail for a link. the zip in downloads is unpacked, collected and indexed, and one line says so.
- [ ] the driver presses "request" through page scripting (a tab in front), not in a background tab: the extension only reads, by decision. it has run against a made-up site only.
- [x] chatgpt conversations that are new or changed since the last export are read daily from the owner's signed-in tab, GET only, and saved in the export's own shape: one conversation is one row whichever way it came. the page's token is used inside the page and never returned.
- [x] instagram saved posts are read daily the same way. instagram refuses its chats and liked posts to a plain GET from a tab, so messages and likes still come only with the export.
- [ ] both sites forbid automated collection in their terms and can change these addresses or ask the owner to prove they are a person. a read is one tab and a few requests, once a day, and stops at the first refusal.
- [x] three refresh tiers: files on disk every 15 minutes, signed-in sources daily, exports monthly unless the owner sets another cadence.
- [x] one read of a source at a time: a second read (the app's schedule and a hand-run collect) steps aside and the rows stay.
- [x] a signed-in source with saved rows that was skipped for the same reason seven days running goes quiet: tried weekly, and it asks for nothing.
- [x] any app can be added: the owner's own model writes a reader, the code is vetted and trial-run before it is kept.
- [ ] raw export folders under `imports/` are kept as they came. `ctx rawscrub` counts the secrets in their text files and `--apply` takes them out; nothing does it by itself.
- [x] a name book, built on this mac from the contacts app, whatsapp's own contacts and a google takeout: a chat known only by a number or an address is called by the person's name, and so is whoever wrote in a whatsapp group. a number is matched by its last ten digits.
- [x] a name a person gave themselves on whatsapp stands in only where the owner saved none, and is written with a "~" in front.
- [x] the name book is one private file (`namebook.json`, readable by the owner only). a process macos keeps out of contacts never replaces a book built with them.
- [x] reminders, calls (the mac's history and whatsapp's) and voice memos (title, date, length) are sources. no call is recorded and no memo is listened to here.
- [x] a complete linkedin export is read for what the owner wrote or did: posts, reposts, comments, articles, invitation notes, recommendations, saved posts, reactions, searches, and one row for their career as they wrote it (no street, birth date or phone).
- [x] from a linkedin export these are never read: ad targeting, ads clicked, inferences, credibility scores, logins, security challenges, receipts, registration, verifications, phone numbers and email addresses.
- [x] every linkedin export in imports is read and a row's id is made from what it is, so three exports do not double. the cells are read as written: the ids of rows already in the archive do not change.
- [ ] not read from linkedin yet: endorsements, follows, events, poll votes, learning, job applications.
- [x] a chatgpt export is known by what is in it, as a zip or as a folder the owner unzipped. its rooms count as the owner's words only when the owner is the one member.
- [ ] contacts, reminders, the mac's call history and voice memos are tested on made-up stores only.
- [x] pictures, screenshots, pdfs, documents, voice notes and videos on this mac are read on this mac, with apple's own frameworks: no network, no model call, no download ([MEDIA.md](MEDIA.md)).
- [x] a file sent in whatsapp or imessage is tied to its conversation and dated by its message, so an answer can name "the screenshot you sent x".
- [x] a picture with real words becomes a row of those words. one with none gets a light row of what is in it (receipt, whiteboard, beach). one with neither gets no row.
- [x] a video is not transcribed: its row holds the date, the length and the conversation.
- [x] text read off a picture passes the scrubber, plus two rules for layout: a seed phrase in a grid, a card number broken across lines.
- [x] every file is remembered by path, size and time of change and saved as it is read: a stopped run goes on, a file is read once.
- [x] the first pass over all files starts only when the owner starts it, after an estimate timed on a sample. after that the 15-minute read takes new files, 30 seconds at most.
- [x] media is read one file at a time at low priority, and stops when the mac is on battery under 30%.
- [x] a file kept in icloud and not on this mac is counted and left alone: opening it would make macos download it. the owner can switch that on.
- [x] the owner can leave any folder out of the media read.
- [x] on macos 26 a command-line tool transcribes audio with the installed models and needs no permission. before macos 26 it needs a permission only the app can ask for: the audio is counted and waits.
- [ ] languages: text in a picture is read only in the scripts the mac's own text recognition supports, which depends on the macos version, and speech is transcribed only where a model for the language is installed. a picture or a voice note outside those gets a row with no words.
- [ ] imessage attachments, voice memos, notes attachments and the photos library need full disk access. their readers are tested on made-up data only.
- [ ] spreadsheets, slides, pages and keynote files are counted, not read. telegram's media cache has no link to a conversation: counted, read only if switched on.

## decisions on answers

- [x] an answer, never a list of word matches. nothing is looked up while you type; return asks the model.
- [x] the model drives: it searches, reads threads, follows leads, then writes. the fixed pipeline is the fallback.
- [x] sources appear as numbered citations under an answer, with the message shown in its thread.
- [x] a request for a link returns the link itself, and only one that is really in the archive.
- [x] analyse, do not just cite: conclusion first, reasoning across sources and years, inference marked "my read:".
- [x] say what is missing. name the sources that are not in the archive yet instead of guessing.
- [x] a message holding an unusual unicode line break keeps the evidence of the tool call it came from.
- [x] a check before every answer: quotes and links no message holds, claims with nothing cited, ids that do not exist.
- [x] an answer links only to addresses in rows the owner wrote or saved. an address that only someone else's message holds is named by its site, in plain words; a setting widens this.
- [x] the app draws no pictures in an answer, opens only http and https, and writes a link's real host after its words.
- [x] everything a model is given travels inside a block sealed with a marker made for that one call, and what the model writes is cleaned before anyone sees it.
- [x] the word "rows" never reaches the owner. steps are described in words, never by id.
- [x] follow-ups build on the evidence of the earlier turn, and keep its citations.
- [x] a source named in the question is searched by itself and its size is stated, so "none matched" is never "none exist".
- [x] whole-archive questions are counted by code: who went quiet, what was shared most, how many, how often.
- [x] introductions, conflicts, ideas, commitments and decisions are pulled once into tables and counted from there.
- [x] spend once, answer lean: most routine questions take one small model call.
- [x] strong, partial or weak is stated on the answer. weak answers lead with that.
- [x] the owner can rate an answer or a related item, and the rating changes the next result.
- [x] a second, wider look before the loop: guessed wordings, conversations ranked first, their best stretches read.
- [ ] hard questions asked from half a memory have their own tier and targets. method in [EVAL.md](EVAL.md).
- [ ] the target for answers that state something false as fact is zero.
- [ ] analysis answers have a rubric and a target: 6.5 of 8 with under 0.5 unsupported claims, in 45 s.
- [x] an analysis starts from the wiki's own paragraphs on the question, chosen by code; the search that follows only fills gaps and stops at its budget.
- [x] a sentence whose mark comes after its full stop keeps its mark.
- [x] a quick answer to a lookup takes 40 seconds at most, the automatic longer look included. one that runs out says so and shows the closest messages.
- [x] the question reaches the model's cli at once, so the cli never gives up waiting for it.
- [x] a question about the present ranks the last 30 days first, then the last 90, and the model is told the newest evidence wins. a question that names a past time is left alone.
- [x] the briefing opens with a "now" block counted by code from the last 30 days, dated, no model call.
- [x] saved posts and likes take turns by source, so a small source is not pushed off the page by a large one.
- [x] the owner's public voice is measured by code per channel, from their own writing (shorthand and units included), and written up on their plan; a request to improve or write a post is answered in it, held to their measured bands, with what it leaned on.
- [ ] writing in the owner's voice has a blind test, and it has not passed. the drafts meet every check a program can run.
- [x] what gave drafts away is held by code on every draft (twelve counted habits) and by rules every writing prompt carries.
- [x] a long piece is outlined, written a section at a time on the owner's own notes, past posts and saves, then read once whole for flow.
- [x] linkedin posts and comments are measured and given a guide once the complete export is in. an engine with no reader for a source keeps that source's rows.
- [x] standing rules in the owner's own words: count this more, leave that out, forget it for good (proposed, backed up 30 days), answer like this, this is a fact, show it like that. held by code at the readers, not by asking the model.
- [x] nothing is saved from a sentence until the owner has seen what it will touch and confirmed; a name that could be two conversations asks back.
- [x] a rule that leaves a conversation out also hides its summary card and every paragraph of about you that cites it, at once; the owner is told how many pages cite it, and those pages are written without it at the next build.
- [x] the owner's weights steer the evidence about you is written from: who is read closely or gets a page, and which months of a long conversation are shown.
- [x] "before 2020" ends on the last day of 2019.
- [x] a new chat opens with the scope and the mode the owner's rules set, unless one was set on that chat.
- [x] after every read of the sources, a forgotten message that came back is taken out of the files again, and the rows of things made here are put back if the read rewrote them.
- [x] a thing made here (a post, a plan, a brief, a comparison) is kept as a document with versions, revised by a follow-up or by the owner's own edit, and becomes a row of the archive.
- [x] about you can be edited paragraph by paragraph: remove, correct, comment, pin. the edits are applied on every read and outlive a rebuild.
- [x] the journal has sections the engine builds by code (worth a glance, waiting on you, you said you would, on your mind, left open, newest notes); a rule switches them, and a line can be removed for good or commented on.
- [ ] recency is not yet measured on questions with no time word.
- [ ] the tables pulled from the cards (introductions, conflicts, ideas) are not exact; a count from them is an "at least".
- [x] a graded test set for whole-archive questions, gold computed by code. it passes on the phrasings it was built on; other phrasings are not measured.

## decisions on the model

- [x] runs on the owner's own claude or chatgpt plan through their signed-in cli. an api key is only a fallback.
- [x] the owner picks the model: three presets (balanced, best, lean) or one model per job.
- [x] recommendations come from speed measured on this mac, each with a one-line reason.
- [x] a retired model or a usage limit never fails an answer: it falls back and says so under the answer.
- [x] big spends show an estimate first and can stop and resume.
- [x] every model call the app or the engine makes on its own has a switch, on one card in settings. nudges worded by the plan are off by default, because they send the window title.
- [x] the model cli runs in an empty folder outside the home, with its settings, rules, commands and other tool servers off, and no tool of its own. a codex build that will not switch its tools off is not used.
- [ ] that isolation is tested by the flags passed. a run with a real model against planted files is written and has not been run.
- [x] a nightly catch-up, off until the first read-through has been run or a number is set, spends at most `nightly_calls` (40; 0 is off) on unread conversations, the recent and the ones the owner wrote most in first, then on wiki pages whose evidence changed. small hours only, on mains or above half battery, never beside an answer or a run the owner started, and it ends at the plan's limit with no smaller model in its place.
- [ ] the nightly catch-up is tested with a stand-in model only. a conversation that alone needs more calls than a night's budget waits for a run started by hand.
- [x] no local model is required. a better embedder can be plugged in, and is optional.
- [ ] the chatgpt plan still uses the fixed pipeline; the model-driven loop is claude only.

## decisions on the app

- [x] the frame people know: sidebar of saved chats, centred conversation, sources panel on the right.
- [x] the home is an empty chat with the composer in the middle.
- [x] a running answer never blocks. chats run side by side; a pill covers jobs outside chats.
- [x] the model's steps show above the answer while it works and stay collapsed after.
- [x] answers render as real markdown and keep their own capitals.
- [x] scope chips: these sources, this date range, this person. quick and deep modes.
- [x] ask from anywhere: a global key opens a floating panel. the key is shown, changeable, never taken silently.
- [x] first run is two screens: what this is plus four switches, then every source filling in live.
- [x] all key permissions are asked up front so sources can read while the owner is away.
- [x] progress is always real. no fake counts, no fake bars.
- [x] setup is skipped when an archive already exists.
- [x] people are objects: a name opens that person's page.
- [x] the home opens on the last 30 days: who is waiting on the owner, what they said they would do, what is on their mind, and the months of the archive, all counted by code (`ctx now`). a thing it is not sure of is left out.
- [x] "what context knows about you" is a place, and any line can be marked wrong.
- [x] a source wears its app's icon when the app is on this mac, and a letter when it is not. fetching an icon from the service's own site is a switch, off by default. no icon is committed here.
- [x] settings: plan and model, connected ais, sync, permissions, read-through, archive, keys by name only.
- [x] text contrast of 4.5:1 in light and dark is enforced by the build.
- [x] every control has a spoken label; focus rings show for keyboard use only.
- [x] the title bar's lights, mark and labels share one centre line, checked to a pixel.
- [x] pings are off unless switched on. things that only wait on the owner never ping.
- [x] ping rebuild: one ping per thing ever, rate limits, four kinds.
- [x] the profile as a deep wiki: a page per person, project, year and theme, every paragraph tied to its evidence.
- [x] answers read the wiki first for people, projects, periods and patterns, and cite the messages its sentences rest on.
- [x] an export's placeholder ("instagram user") is never a person's name: each such account stands alone, unnamed, with no page and no place among the closest.
- [x] the wiki estimate counts the pages it will rewrite and says where its calls go. one new message does not make a whole conversation count as unread.

## decisions on connecting other ais

- [x] one command registers the server with every local ai app it finds, safely, with backups, and can remove it.
- [x] tools are read-only. other people's phone numbers and emails are masked for remote callers.
- [x] the remote endpoint for chatgpt and claude.ai exists, is off by default, never starts by itself, logs every call.
- [x] a local http api for any ai app or agent: one key per app, this mac only, read only, masked, logged without content ([API.md](API.md)).
- [x] a new api key reads nothing until opened, expires, is counted, and is held on an unusual day. a new install picks its own port, and the server is not started beside another listener.
- [x] each ai app over mcp has its own limits, log, hold and way to close it. a new app reads the short profile until opened. tools are named `context_*`.
- [x] `mcp --status` flags an entry another program changed.
- [x] one never list binds every route: the api, mcp and the app's own answers.
- [x] x likes, posts, replies and bookmarks are read through the extension from x's own data address, since x draws nothing in a hidden tab.
- [x] a long x list is read in short runs, stops one short of x's limit, keeps its place, and goes on at the next daily read until its end was reached.
- [ ] x's own list of a profile's posts ends long before the first post. older posts come with the x archive.
- [ ] the remote endpoint has never been run through a real tunnel.
- [x] the browser extension is loaded in a real browser and connects to the helper on this mac.
- [x] the extension's manifest names four sites: slack, google drive, google docs and x. every other site is read only after the owner switches it on in the popup, on that site, and the browser asks. the owner also keeps a "never read" list. the engine can change neither.

## decisions on the repo

- [x] mit license.
- [x] the install path is walked from a fresh clone in an empty home, on python 3.9 and 3.14.
- [x] `doctor` is the preflight: what this mac has and lacks, source by source. it makes no request to any site unless run with `--check-sign-in`.
- [x] tests run on every push, on macos and linux. linux proves the clean "macos only" message.
- [x] nothing personal in the tree: not in code, fixtures, docs or commit messages ([AGENTS.md](../AGENTS.md), for contributors).
- [x] fixtures, tests and screenshots use made-up data only.
- [x] tests never find the mac's model CLIs, its home folder or a key in `.env`.
- [x] the readme states time, number of permissions and cost before anything runs.
- [x] tests do not depend on the mac they run on: not its battery, its wall clock or how busy it is. a scan stops under 30% battery, so the tests stub the battery.
- [x] inside one process, limits, waits and pauses count time awake (`time.monotonic`), not the wall clock, so a mac that sleeps does not end a wait early.
- [x] the answer's deadline stays on the wall clock, on purpose. it is set in the engine and handed to a child process (the model CLI calls the tools, which read `CTX_AGENT_UNTIL`), and time awake is not a number two processes can share: each could only measure from its own start. a wall-clock time is the same in both. what a sleep does to it: if the mac sleeps while an answer is being written, the deadline is past when it wakes, the tools stop answering and the answer is cut short with what was found so far. the owner asks again. an answer is seconds long, so this is rare, and a cut answer says it was cut.
- [x] times that are written to disk and read by a later run stay on the wall clock too, because they are dates: when a plan's limit lifts, when a source was last read, how old a lock is, the daily and weekly schedule.
- [ ] intel macs, macos 14 and 15, most browsers and a mac with no developer tools are untested.

## how the work is checked

- [x] a layout gate renders every screen at three sizes and fails the build on clipping, overlap or misalignment.
- [x] the installed app is driven by hand after each build. renders alone miss real bugs.
- [x] answer quality is measured on a private set of questions with known answers, kept on the mac it was made on.
- [x] installs are built from a clean copy of committed code, never from a folder with half-finished edits.
- [x] refactors are proven by byte-identical output on a made-up archive.
- [x] error handling that turns a missing app or a blocked permission into "skipped: reason" is never traded for brevity.

## still to decide

- whether to offer a better local embedder by default for people who want faster hard-question recall.
- how the remote endpoint should be given a fixed address without an account.
