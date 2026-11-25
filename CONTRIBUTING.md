# contributing

context runs on other people's macs with access to their whole private history. a change here is a change to what
runs there, so the bar for what gets merged is about who can run what.

## what gets read by a person, line by line, before it is merged

a pull request that touches any of these is never merged on a summary, a green check or an ai review:

- `AGENTS.md`, `README.md`, `CONTRIBUTING.md`, anything under `docs/` that gives commands: an installing agent does
  what these say.
- any file an ai coding tool reads or runs by itself: `CLAUDE.md`, `.claude/`, `.cursor/`, `.codex/`, `.mcp.json`,
  `.vscode/`, skills, hooks, rules files, `tasks.json`. this repo keeps none of them besides `AGENTS.md`; a pull
  request that adds one is closed unless there is a reason a maintainer can state in a sentence.
- `.github/workflows/`, `app/build.sh`, `app/install.sh`, `app/run.sh`, `requirements-telegram.txt`.
- `ctx/guard.py`, `ctx/sandbox.py`, `ctx/scrub.py`, `ctx/api.py`, `ctx/mcp.py`, `ctx/bridge.py`, `extension/`.

they are read raw, as bytes: not the rendered view. hidden and look-alike characters do not render. a file that
holds a character outside plain text where none belongs is refused.

## what a pull request may not add

- a dependency. the engine uses python's standard library and nothing else. the one exception is
  `requirements-telegram.txt`, where every version is fixed and every file is named by its sha256; a change to it
  says where each new hash was read.
- anything fetched at install or at run time: no `curl`, no package runner, no download in a script.
- a tool that writes, sends, posts or schedules for the model. the tools read.
- a route, a job or a tool that answers without the checks its neighbours have. `tests/test_api_keys.py`,
  `tests/test_guard.py`, `tests/test_mcp.py` and `tests/test_injection.py` hold these; a change that needs one of
  their assertions loosened says why in its first line.
- real data. fixtures, tests, docs and screenshots use made-up people, numbers and text.

## how to check your change

```bash
python3 -m unittest discover -s tests
/usr/bin/python3 -m unittest discover -s tests
```

both must pass on a clean checkout of your commit, not only in a folder that holds other work.

## reporting a security problem

not in a public issue. open a private advisory on the repo's github page (security > report a vulnerability) with what
you found and how to see it. do not send a proof of concept as a repo to open or a file to run: describe it in words,
and paste the few lines that matter.

## for maintainers

the people who can merge here are the way in to everyone who installs. the attacks that work on maintainers are
plain ones.

- never run a command someone sent you: not from a dm, not from a call, not to fix your audio, not from a known
  account (known accounts get taken over).
- never open a repo someone sent you in an editor or a coding agent on the mac that holds an archive. project files
  can run code when a folder is opened. read it in the browser.
- pull requests are read in the browser. they are never checked out into the folder the app is built from, and
  never reviewed by an agent that has tools.
- a "security report" that comes with a repo, an html file or a script to run is treated as an attack until its
  author has described it in words.
- an authorisation screen that asks for access to your x or github account for a "calendar" or a "meeting" is
  refused. sign in only on pages you opened yourself.
- releases are tags made by a maintainer on their own mac. there is no publish token in ci, and the workflow has
  read-only permissions, fixed commit pins for the actions it uses, and no trigger that runs code from a fork with
  the repo's rights.
- the repo's name and owner do not change. if they ever must, the old name is kept registered and pointed here.
