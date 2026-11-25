# context, the mac app

a native macos app over the python engine in `../ctx`. one question box over the archive in `~/.context/v2`, a
first run for the permissions, and pages for the journal, the things it made, about you, sources, teach and
settings. it also sees what you are on now (the app in front and, with accessibility on, its window title) and can
nudge you about it, briefly.

no analytics. what goes out, and nothing else:

- what your own ai plan reads to answer you and to write your pages: model calls go through the engine, on your plan
- requests to the sites and services you add or sign in to, to read your own things from them (the engine makes
  these; telegram is one, if you sign in to it)
- a request to a service's own site for its icon, only if you switch on "fetch source icons from their sites"
  (settings, general; off by default)

what context spends on your plan without a click is listed, each with its switch, under settings, general,
"what context does on its own". a nudge worded by the plan is off until you switch it on.

## build

```sh
./build.sh        # makes build/context.app. opens nothing. 10 to 25 minutes: a few to compile, the rest checking every screen
./install.sh      # builds, copies it to /Applications (or ~/Applications), quits a running copy, opens it
./run.sh          # builds and opens build/context.app in place, for development
./demo/run.sh     # opens it on made-up data with a stand-in engine. touches nothing real
build/context.app/Contents/MacOS/context --selftest   # checks with no window: parsing, dates, search timing
tools/check.sh [folder]   # build, unit checks, layout checks, and renders + contact sheets of every screen
```

needs the command line tools only (swift 5.9+, macos 14+). `build.sh` tries `swift build` and, where swift-package
is broken (some command line tools installs miss SWBBuildService), compiles the same sources with `swiftc`.
`build.sh` does nothing when no source changed. it signs ad hoc and never touches the keychain, so macos asks for
full disk access and accessibility again after a rebuild. `install.sh` signs with `CONTEXT_SIGN_ID`, or the first
apple development identity in the keychain, so the grants survive; with neither it signs ad hoc too. a development run (`CONTEXT_DEBUG`) keeps its state in memory and, without
`CTX_HOME`, uses a throwaway folder: it cannot change the real app's saved state.

the app finds the engine in this order: the folder named by `CONTEXT_DEV_ENGINE` or `CONTEXT_REPO`, for a
development run; else the engine inside its own bundle, which `build.sh` copies in; else by walking up from its
bundle to the folder that holds `ctx/`. `CTX_HOME` moves the data folder, as it does for the engine.
`python3 -m ctx doctor` shows which python runs it.

## screens

- **first run.** two screens. the first says what context is and carries four switches, each with a live state
  that is polled: full disk access, your browser (page scripting or the extension, whichever the engine says that
  browser needs), your ai plan (`ctx model`), and connect your ais (`ctx mcp --install`, one result per app).
  nothing is mandatory. "start reading" runs one `python3 -u -m ctx collect` and opens the second screen: every
  source in one list, all reading at once, with a ticking count and the thing being read, from the engine's `@`
  lines. a locked source waits with its button and starts by itself when the switch comes on; an export asks yes
  or no. a row opens that source's own live view. "open context" works at any moment. with an archive already on
  disk first run is skipped; "run setup again" under sources opens the list and reads everything once more.
- **home.** the desk: what waits on you, what you said you would do and what is on your mind from the last thirty
  days, a strip of the whole archive by month, and the question box. typing looks nothing up; return sends the
  question to the warm engine (`ctx serve`, `answer`) as a chat turn. the answer is a page: prose in serif, each
  claim's evidence as a note in the margin, a ribbon of when the evidence is from.
- **journal.** the engine's page for today (`journal`): its sections and lines, each of which can be removed,
  commented on or put back (`journal-edit`).
- **made.** what context wrote for you from the archive (`made-list`, `made-get`, `made-save`), with its history.
- **about you.** the wiki the engine writes, and the short pages; a paragraph can be pinned, corrected or removed
  in place (`wiki-edit`).
- **sources.** every source read, as its app's icon or a letter, with a short count; then "waiting on you" with the
  one action each item needs; then "add". exports are asked for, restarted and scheduled from here and from
  settings.
- **teach.** standing rules in plain sentences (`rule-propose`, `rule-save`): what to weigh, leave out, forget, and
  how things are shown.
- **settings** (⌘,). general, models, connected ais, what can read (ai apps over mcp and programs with a key: what each
  reads and pulled, and what none may read), sources & sync, permissions, your data, notifications, about.
- **the panel.** control-option (changeable in settings) opens a floating field over any app without bringing
  context forward. return asks and the answer lands there; command-return carries on in the window.
- **menu bar.** what waits on you, source health, sync now.

## the ping

when the app needs you, the dot in the menu-bar mark turns persimmon and a small panel drops from under it, over
whatever is in front, without taking the keyboard. one sentence, one action that does the whole thing, and
"not now". it leaves after 8 seconds; the dot stays lit until you open the popover, where the same item waits.

- a nudge: got it
- an export that needs you: open the tab (brings the browser forward; the engine left that tab in front)
- full disk access or accessibility switched off after it was on: open settings
- browser scripting off while an export is waiting: turn it on
- an export arrived: see it

one at a time, newest first; the rest wait in the popover with a count. nudges ping at most once in 20 minutes,
and only the pointed kinds (a promise in the chat you are in, drift, done before, again and again). the popover
has "quiet for an hour". a ping is held back, dot lit, while something keeps the display awake (a video, a call):
that is the cheap stand-in for full-screen video and screen sharing, which the app does not detect directly.
`Ping.swift` holds all of it.

## nudges

`Coach.swift` holds the rules. all local:

- a promise or an unanswered person, while you are in that chat (open loops from `loops.json`, matched to the
  window title, or to the chat app when titles are off)
- drift: under a quarter of the last active hour matched the words in this week's line
- done before: the words in the window title or your latest agent prompt also appear in a session, prompt or note
  more than three days old. "show me" opens it in ask
- the same off-topic place, twelve or more visits today
- otherwise, the top open loop

answers go to `nudges.jsonl`; loop answers also go to `scores.jsonl` in the engine's format.
a nudge worded by the model is off by default (settings, general, "nudges worded by your plan"), because it sends
the app in front and its window title to the model. switched on, the line comes from
`python3 -m ctx coach --now <json>`, on your own plan. it is asked at most once in 20 minutes, only when the
local drift rule has just fired or the app in front changed kind, never twice at once, never on a battery under
20 percent, never when no plan is signed in. its sentence takes the place of the local line of the same kind.

## what the app writes

all inside the data folder: `app.json` (setup done, switches, the week's line, hidden nudges),
`activity/<day>.json` (the day's apps and window titles, written only while "nudges worded by your plan" is on;
files older than 14 days go when the app starts), `nudges.jsonl`, `scores.jsonl`. no screenshots, no keystrokes.
open at login registers nothing until you flip the toggle.

## files

`Sources/context/`: `App` (window, menu bar, pill), `AppModel` (state, keys), `Engine` (collector, tailing),
`Search` (streaming jsonl search), `Activity` (frontmost app, timeline), `Coach` (nudges), `Sources` (copy, colour
and shape per source), `Theme`, and one file per screen. `DESIGN.md` describes the design system and `MOTION.md` every animation. `tools/check.sh` draws every screen, light and dark, into `build/check`: look there for what
the app looks like today. `demo/` is a stand-in engine with made-up data; it answers only some of the engine's
commands, so the parts of the app it does not answer for stay empty under it.
