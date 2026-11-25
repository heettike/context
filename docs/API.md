# the api

your archive as a plain http api on your mac, for any ai app or agent that can make a web request.

it is read only. it answers on this mac only. every call needs a key.

## start

```bash
python3 -m ctx api --key my-agent --preset work
```

- this makes one key for one app and prints it once, as json.
- it starts the api as a background process that outlives the command, and prints the address to use. every install picks its port at random once and keeps it; `python3 -m ctx api --status` and the answer to `api --key` show the address. there is no fixed port. the examples below write `<port>`.
- from then on the api starts by itself whenever the context app is open. it never starts before a key exists, and it stops when the last key is revoked.
- a key's name is 1 to 40 characters of `a-z 0-9 - _ .`. name it after the app that will use it.
- **a key made with no preset and no limits reads nothing** but the index. see "what a key can see".

```bash
curl -H "Authorization: Bearer ctx_..." "http://127.0.0.1:<port>/v1/search?q=lease"
```

an agent that has never seen this api can start at `GET /v1`: it lists every endpoint. `GET /v1/openapi.json` is the same as an openapi 3 document.

## commands

```bash
python3 -m ctx api --key <name> [--preset profile|work|writing|people] [--sources a,b] [--people "x,y"] [--after YYYY-MM] [--before YYYY-MM] [--all] [--days N | --never]
python3 -m ctx api --set <name> [the same flags] [--rows-per-day N]   # change what a key reads
python3 -m ctx api --renew <name> [--days N]
python3 -m ctx api --keys             # keys by name: what each reads, expiry, calls. never the key
python3 -m ctx api --log [<name>] [--days N]
python3 -m ctx api --clear <name>     # let a key held as unusual through again
python3 -m ctx api --hold on|off
python3 -m ctx api --never-list [people="a,b"] [sources=a,b] [range=YYYY-MM..YYYY-MM] [--empty]
python3 -m ctx api --revoke <name>    # that key stops working at once
python3 -m ctx api --status | --start | --stop
python3 -m ctx api --serve [--port N] # the server in the foreground
```

## endpoints

| | | |
|---|---|---|
| GET | `/v1` | what this is and every endpoint |
| GET | `/v1/openapi.json` | the same, as an openapi 3 document |
| GET | `/v1/tools` | every tool with its argument schema |
| POST | `/v1/tools/<name>` | run one tool; the json body is its arguments |
| GET | `/v1/search?q=` | messages, notes, saved posts and docs. also `people`, `sources`, `mine`, `after`, `before`, `limit` |
| GET | `/v1/people/<name>` | who someone is to you, and every conversation with them |
| GET | `/v1/wiki?q=` | wiki pages that match |
| GET | `/v1/wiki/<page id>` | one page; `&part=2` for the rest of a long one |
| GET | `/v1/profile/<section>` | core, people, projects, timeline or voice |
| GET | `/v1/briefing` | one page on who you are and what you are in the middle of |
| GET | `/v1/sources` | what the archive holds |
| POST | `/v1/ask` | `{"question": "...", "mode": "quick" | "deep"}`: a written answer with the messages it rests on. runs on your ai plan |

## keys

- one key per app, so one can be cut off without touching the rest.
- a key is shown once. only its hash is kept, in `~/.context/v2/api.json`, readable by you alone. a lost key is revoked and made again.
- a revoke takes hold at once.
- in the app, settings > "what can read" lists ai apps connected over mcp and programs with a key, each with what it opens and what it really pulled, and has the never list.

## what a key can see

**a new key reads nothing.** `api --key my-agent` makes a key that can open `/v1` and `/v1/openapi.json` and no more;
the answer says so and lists the flags that open it. you choose what it reads when you make it, or later with `--set`.

```bash
python3 -m ctx api --key my-agent --preset work
python3 -m ctx api --key my-agent --sources whatsapp,slack --people "dana okafor" --after 2025-01 --before 2025-12
python3 -m ctx api --set my-agent --preset people --people "dana okafor"
python3 -m ctx api --key my-agent --all
```

| preset | what it opens |
|---|---|
| `profile` | the short profile (`/v1/profile`) and the briefing (`/v1/briefing`). no messages, no search, no people, no wiki, no ask |
| `work` | messages and documents from slack, mail (`email`, `gmail_takeout`), google drive, calendar, notion, and linkedin messages, posts, articles and comments |
| `writing` | only what you wrote yourself, in obsidian, apple notes, the journal, notion, google drive, your x posts and your linkedin posts, articles and comments |
| `people` | your conversations: whatsapp, imessage, telegram, slack, x dms, instagram dms, linkedin messages. add `--people "a,b"` to keep it to those people |

`--sources`, `--people`, `--after` and `--before` narrow a preset or stand alone. a name matches as whole words: a key
for "ann" does not read "joanna".

a key with limits (anything but `--all` and `profile`):

- gets `/v1/search` and the tools `search`, `read_thread`, `saved` and `links`
- is shown a message only if it fits every limit. each message is checked before it is returned, whatever the app asked for
- gets 403 from everything written from the whole archive: `/v1/ask`, the profile, the wiki, people pages, counts and `/v1/sources`

`--all` reads everything through every endpoint, and prints a warning when you make it. no key reads everything
unless you made or set it with `--all`: a key from an older key file that did is narrowed to nothing on update,
and `--keys` lists it as narrowed with the command that opens it.

## ai apps that read over mcp

an app you connected with `mcp --install` is listed beside the keys, as `mcp:<app>`, with the same limits, log and holds.
a new app reads the short profile only. open more, or close it:

```bash
python3 -m ctx api --set mcp:cursor --preset work
python3 -m ctx api --set mcp:claude_desktop --all
python3 -m ctx api --revoke mcp:cursor
```

every app starts at the short profile, on a new archive and on an old one. after an update, a key or an app that read everything under an older form of the key file is narrowed and `--keys` lists it as narrowed, with the command that opens it again.

## how long a key lasts

30 days, unless you say `--days N` or `--never`. an expired key gets 401 with the command that renews it:

```bash
python3 -m ctx api --renew my-agent --days 30
```

keys made before this got 30 days from the day the engine was updated.

## never share

one list above every key, `--all` keys included. a key cannot widen it.

```bash
python3 -m ctx api --never-list people="sam reyes" sources=calendar range=2019-01..2019-12
python3 -m ctx api --never-list            # show it
python3 -m ctx api --never-list --empty
```

a source, a person (every conversation whose name holds that name, and every line they wrote in a group) or a
stretch of dates on this list is returned by no endpoint: not as a message, not in a count, a conversation's size or
its first and last day, not in a conversation summary, not in a wiki paragraph that rests on it. a page written
before the list (the profile pages, the briefing, a card, a wiki page, its title and summary) loses every line that
names a listed person or source, or a date wholly inside a listed stretch. it is held the same way as your own rules
("leave out ..."). the list is kept in `never.json` beside the archive and binds every route alike: this api, mcp
over stdio and over http, and the app's own answers. if `never.json` cannot be read, nothing is passed over: every
endpoint but `/v1` and `/v1/openapi.json` answers 503 with the reason, and mcp tools answer with the same error,
until the file is fixed or replaced with `--never-list --empty`. the same holds when your rules (`rules.json`) or
the list of forgotten rows (`forgotten.json`) cannot be read. a line the pages learned from a listed row without
naming the person, the source or the date stays until the next read-through, which reads only what is left.

## what was read

```bash
python3 -m ctx api --log my-agent --days 14
```

per key and per day: calls, messages returned, bytes, which sources they came from, refusals. `api.log` never holds
what was asked or answered, and no names.

- a key that is handed more than 5 times its usual day (the median of the last 7), and more than 2,000 messages, is
  marked unusual and refused for the rest of the day. look at its log, then `python3 -m ctx api --clear my-agent`.
  `python3 -m ctx api --hold off` switches the holding off; the mark stays.
- a key is handed at most 20,000 messages a day. `python3 -m ctx api --set my-agent --rows-per-day N` changes it.

## what guards it

- it listens on 127.0.0.1 only. nothing outside your mac can reach it.
- no key, no answer. a new key reads nothing until you open it, and every key expires.
- read only: no endpoint writes, deletes or sends.
- other people's phone numbers and email addresses are masked. names are not. masking is a courtesy to the people in your archive, not a wall: a caller with a key reads your messages.
- a web page in a browser cannot use it: requests with an `Origin` or a `Sec-Fetch-Site` header are refused, and the `Host` must be this mac.
- what a tool returns comes with a `note` saying it is data, not instructions. `/v1/ask` returns no web address that a cited message does not hold.
- a web address in what a tool returns stays a link only when a message, note or saved page you wrote or saved, among the rows returned, holds it. any other address becomes the name of its site as plain words, like `example.com (site only)`: no path, no query. a page written from the whole archive (profile, wiki, people) comes with no rows, so every address in it is written that way. the setting `links_from_others` counts addresses other people sent you as yours.
- a request refused before its key is read (from a browser page, under a foreign host name, with a body sent two ways, with no key or a wrong one) is counted by kind and day: `api --log` shows the counts. nothing it sent is kept.
- 120 calls a minute per key; `/v1/ask` is capped at 6 a minute and 200 a day per key, and 400 a day for all keys together, because it spends your plan. the counts live in memory: restarting the api starts them again.
- `api.log` records when, which key, which endpoint and how big. never what was asked or answered, and no names.
- the port is this install's own, picked at random once and kept. there is no fixed port, and no fallback to one: if no port can be taken, the api does not start and says so.

## the honest limit

these controls bound an app that holds a key: what it may read, for how long, how much in a day.
they do not bound a program already running as you on the mac. that program can read the archive files without a key, and can write the counts file too.
the log and the hold are a record for you, not proof against it. [SECURITY.md](SECURITY.md).

reaching it from another machine means putting your history on the internet. nothing here does that.
