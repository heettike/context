# pictures, voice notes, videos and files

the archive used to hold only text. it now also reads the files on this mac: what a picture says, what a voice note says, what is in a pdf. all of it is read on this mac and stays on this mac.

## what is read

| kind | how | what the row holds |
|---|---|---|
| picture or screenshot with words | vision, accurate level, language found by itself | the words, the date, where it came from, the path |
| picture with no real words | vision's own labels (document, receipt, whiteboard, food, beach) | a light row: "a picture of: receipt, document." |
| picture with neither | | no row |
| pdf | pdfkit's text; a page with no text layer is recognised like a picture, 8 pages at most | the first 20,000 characters and a note of the full length |
| doc, docx, rtf, odt | `textutil` | the same |
| txt, md | read as they are | the same |
| voice note, voice memo, audio | the speech model on this mac | the words, the length; or the length alone when the words could not be made out |
| video | its own header | the date, the length, the conversation. not transcribed |

every row has `src` (`image`, `voice_note`, `file`, `video`), a date, a `url` that is the file's path, and a `title` an answer can cite, such as "screenshot you sent ada lovelace". `who` is `me` when you sent or made it: a screenshot, a voice memo, a file you sent in a chat.

a file sent in whatsapp or imessage is tied to its conversation (`thread_id`, the same one its messages carry) and dated by the message, not by the file.

## where it looks

- the folders in `~/.context/v2/media.json`: desktop, documents and downloads to start
- whatsapp's media folder, each file linked to its conversation through whatsapp's database
- imessage attachments, linked through `chat.db`
- voice memos
- files kept inside apple notes
- the photos library, through its own database. it is never copied

the last four need full disk access. a place this process is kept out of is reported as `blocked: needs full disk access` and the rest goes on. the app's collector and your own terminal have that access.

telegram keeps a cache of what it showed, with no names and no link to a conversation. it is counted, and read only after `--set telegram_cache=on`.

## what is not read

- code: any folder that holds a `.git`, a `package.json` or the like, and everything under it
- app bundles, caches, `node_modules`, hidden folders, anything under `~/Library` except the chat folders above
- an obsidian vault (it is a source already)
- pictures under 12 kb (icons), stickers, installers, fonts
- spreadsheets, slides, pages and keynote files: counted, not read
- a file that is kept in icloud and not on this mac. opening one makes macos download it, so it is counted and left alone. `--set icloud_files=on` reads them too
- text in a picture is read only in the scripts the mac's own text recognition supports; which those are depends on the macos version. a picture in another script gives no words. speech is transcribed only in a language whose model is installed on the mac; a voice note in another language gets a row with its length and no words
- video sound

## privacy

- no network, no model call, no download. the helper is `app/tools/media.swift`, built on first use like the embedder
- recognised text passes the secret scrubber before it touches the disk, with two more rules for text read off a picture: a seed phrase laid out in a grid, and a card number broken across lines
- a picture of a passport or a bank statement is not a special case: the numbers in it meet the scrubber's rules like the numbers in a message, and what no rule covers stays in the row as text. leave such folders out:

```
python3 -m ctx media --leave-out ~/Documents/scans
python3 -m ctx media --take-in ~/Documents/scans      # undo
python3 -m ctx media --folder ~/Pictures/work         # read one more folder
```

- files are only ever read. nothing is moved, renamed or changed

## the first pass

```
python3 -m ctx media --estimate     # how many files, where, what is blocked, how long. reads a dozen of each kind to time it
python3 -m ctx media --scan         # read everything not read yet, newest first
python3 -m ctx media --status       # read, left, blocked
```

`--scan` takes `--kind images|audio|files|video`, `--limit N` and `--minutes M`. it reads one file at a time at low priority and stops by itself when the mac is on battery under 30%. each file is saved as it is read (`~/.context/v2/media/done.jsonl`), keyed by path, size and time of change, so a stopped run goes on where it stopped and a file is read once. `--fast` runs at full priority.

the first pass only starts when you start it. after that the 15-minute read takes files from the last 30 days, 30 seconds at most (`--set tick_seconds=0` switches that off).

`python3 -m ctx media --help` lists every flag.

## speech

on macos 26 a command-line tool can transcribe a file with the models already installed and is asked for no permission (`SpeechAnalyzer`). before macos 26 the only way is `SFSpeechRecognizer`, which needs a permission that only an app can ask for. the helper never asks: it answers "needs permission", the audio is counted and waits. the code is in `app/tools/media_speech.swift`, a file with no top-level code, so the app can compile it too and run the same job.

the locale is the mac's own, stored with the archive when its first voice note is read and kept from then on (`--set speech_locale=en-US` changes it). a transcript the recogniser was not sure of (under 0.5) is not kept: the row says the words could not be made out.

## video

not transcribed in this pass. the row makes a video countable and findable by conversation and date. transcribing would mean pulling the sound out of each file and running it through the same speech model.
