#!/bin/sh
# checks the add-a-source flow against the real engine, in a throwaway CTX_HOME, on the three paths that need no
# model call: a known service, a built-in app, and something no app here holds. it reads the fields the app's add
# sheet reads (Connect.swift) and fails if one is missing or of the wrong type. nothing is enabled or written to
# the real archive, and no account is touched.
set -e
cd "$(dirname "$0")/../.."
T="$(mktemp -d)"
export CTX_HOME="$T"
python3 - <<'P'
import json, subprocess, sys
def run(*a):
    out = subprocess.run([sys.executable, "-u", "-m", "ctx", "connect", *a], capture_output=True, text=True, timeout=60).stdout
    return [l for l in out.splitlines() if l.strip()]
bad = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: bad.append(name)
rows = json.loads("\n".join(run("--search", "notion")))
check("search gives a list", isinstance(rows, list) and rows)
r = rows[0]
check("a found row has id, name, kind, installed, known", all(k in r for k in ("id", "name", "kind", "installed", "known"))
      and isinstance(r["installed"], bool) and r["kind"] in ("app", "service"))
check("search for nothing known still gives a list", isinstance(json.loads("\n".join(run("--search", "zzqqxx-not-a-thing")) or "[]"), list))
for sid, want in (("notion", "ready"), ("calendar", "ready"), ("zzqqxx-not-a-thing", "cannot")):
    lines = run(sid)
    last = json.loads([l for l in lines if l.startswith("{")][-1])
    check(f"connect {sid}: one final object with id, name, state, how, detail, sample.rows", all(k in last for k in ("id", "name", "state", "how", "detail"))
          and isinstance(last.get("sample", {}).get("rows"), int))
    check(f"connect {sid}: state is {want}", last["state"] == want)
    check(f"connect {sid}: progress lines, if any, are @json with a phase", all(json.loads(l[1:]).get("phase") for l in lines if l.startswith("@")))
sys.exit(1 if bad else 0)
P
