#!/bin/sh
# builds context and puts a signed copy in /Applications (or ~/Applications when that is not writable). run it when you want the app you use every day to update.
# macos may ask for your login password once for the signature: choose "always allow" and it will not ask again.
# the signature is the same every time, so permissions you granted (full disk access, accessibility) stay.
set -e
cd "$(dirname "$0")"
REPO="$(cd .. && pwd)"
CONTEXT_INSTALL=1 ./build.sh
mkdir -p "$HOME/.context/v2"
# quit the old copy only when one is running: asking an app that is not running to quit starts it first
if pgrep -f "context.app/Contents/MacOS/context" >/dev/null 2>&1; then
  osascript -e 'tell application id "so.context.app" to quit' 2>/dev/null || true
  sleep 1
  pkill -f "context.app/Contents/MacOS/context" 2>/dev/null || true      # the polite quit can be refused; the old copy must not keep running
  sleep 1
fi
# an account that is not an admin cannot write to /Applications: use the one in the home folder
DEST=/Applications
[ -w "$DEST" ] || { DEST="$HOME/Applications"; mkdir -p "$DEST"; }
# the old copy goes to the trash, never deleted outright: it can be put back if the new one is wrong
if [ -e "$DEST/context.app" ]; then
  if command -v trash >/dev/null 2>&1; then
    trash "$DEST/context.app"
  else
    mkdir -p "$HOME/.Trash"
    mv "$DEST/context.app" "$HOME/.Trash/context $(date +%Y-%m-%d-%H%M%S).app"
  fi
fi
[ ! -e "$DEST/context.app" ] || { echo "could not move the old $DEST/context.app out of the way: nothing was installed" >&2; exit 1; }
cp -R build/context.app "$DEST/context.app"
ID="$CONTEXT_SIGN_ID"
[ -n "$ID" ] || ID="$(security find-identity -v -p codesigning 2>/dev/null | awk '/"Apple Development/ { print $2; exit }')"
if [ -n "$ID" ] && codesign --force --sign "$ID" --identifier so.context.app "$DEST/context.app"; then
  echo "signed with your own identity: permissions will survive updates"
else
  codesign --force --sign - --identifier so.context.app "$DEST/context.app" 2>/dev/null || true
  echo "no signing identity found: signed ad-hoc. the app works; macos will ask for full disk access and accessibility again after each install"
fi
# nothing may be added to the engine folder after it is signed: a file written there would break the seal the app checks
chmod -R a-w "$DEST/context.app/Contents/Resources/engine" 2>/dev/null || true
open "$DEST/context.app"
echo "installed $DEST/context.app. it runs the engine inside the app. run this again to update it."
