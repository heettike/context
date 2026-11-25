#!/bin/sh
# opens the app on made-up data: a stand-in engine and a throwaway data folder. touches nothing real.
set -e
cd "$(dirname "$0")"
[ -d ../build/context.app ] || ../build.sh
export DEMO_LIVE=1 CONTEXT_REPO="$(pwd)/engine" CTX_HOME="$(pwd)/home"
[ -f home/status.json ] || (cd engine && DEMO_FAST=1 python3 -m ctx collect >/dev/null)
(cd engine && python3 -m ctx seed)
exec ../build/context.app/Contents/MacOS/context
