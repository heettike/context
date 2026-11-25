#!/bin/sh
# builds and opens the app. CONTEXT_REPO and CTX_HOME are passed through if set.
set -e
cd "$(dirname "$0")"
./build.sh
set --
[ -n "$CONTEXT_REPO" ] && set -- "$@" --env "CONTEXT_REPO=$CONTEXT_REPO"
[ -n "$CTX_HOME" ] && set -- "$@" --env "CTX_HOME=$CTX_HOME"
open "$@" build/context.app
