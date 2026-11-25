#!/bin/sh
# builds app/build/context.app with swift package manager. needs only the command line tools.
set -e
cd "$(dirname "$0")"
# on a mac with no command line tools, swift is a stub that opens an install window. say so instead.
if ! xcode-select -p >/dev/null 2>&1; then
  echo "the command line tools are not installed. run: xcode-select --install   then run this again."
  exit 1
fi
mkdir -p build
APP=build/context.app
# nothing changed since the last build: leave the app, and its signature, exactly as they are
if [ -x "$APP/Contents/MacOS/context" ] && [ -z "$(find Sources Resources Package.swift build.sh ../ctx tools ../extension -newer "$APP/Contents/MacOS/context" 2>/dev/null | head -1)" ]; then
  echo "up to date $(pwd)/$APP"
  exit 0
fi
BIN=""
echo "building context.app: about 2 minutes to compile, then a few more to check every screen. nothing opens on screen."
# swift package manager first. some command line tools installs ship a broken swift-package
# (missing SWBBuildService), so fall back to the compiler itself with the same sources.
echo "1/4 compiling (a few minutes)"
if swift build -c release >build/spm.log 2>&1; then
  BIN="$(swift build -c release --show-bin-path)/context"
else
  echo "swift build did not run here (see build/spm.log). compiling with swiftc."
  # the compiler's warnings go to a file: a page of them reads like a failure to someone who only wants the app
  rm -f build/context-bin
  swiftc -suppress-warnings -O -swift-version 5 -parse-as-library -module-name context \
    -target "$(uname -m)-apple-macos14.0" -o build/context-bin Sources/context/*.swift >build/swiftc.log 2>&1 || true
  BIN=build/context-bin
fi
[ -x "$BIN" ] || { grep -A6 "error:" build/swiftc.log 2>/dev/null | head -40; echo "build failed: the compiler's first errors are above; all of it is in app/build/swiftc.log (and app/build/spm.log)"; exit 1; }
echo "2/4 putting the app together"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
# copy beside, then rename: a copy of the app that is running keeps its old file instead of having it rewritten under it
cp "$BIN" "$APP/Contents/MacOS/context.new" && mv -f "$APP/Contents/MacOS/context.new" "$APP/Contents/MacOS/context"
cp Resources/context.icns "$APP/Contents/Resources/context.icns"
cat > "$APP/Contents/Info.plist" <<'P'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>context</string>
  <key>CFBundleDisplayName</key><string>context</string>
  <key>CFBundleIdentifier</key><string>so.context.app</string>
  <key>CFBundleExecutable</key><string>context</string>
  <key>CFBundleIconFile</key><string>context</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><false/>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>NSAppleEventsUsageDescription</key><string>context reads your notes and mail through their apps when full disk access is off. it only reads.</string>
  <key>NSHumanReadableCopyright</key><string>runs on your mac. the archive stays on it.</string>
</dict>
</plist>
P
# the engine goes inside the app, under its signature: the installed app runs this copy and no other, so no folder
# a stray program can write decides what runs with the app's permissions. built beside, then renamed.
ENGINE="$APP/Contents/Resources/engine"
[ -d "$ENGINE" ] && chmod -R u+w "$ENGINE"
rm -rf "$ENGINE.new" "$ENGINE"
mkdir -p "$ENGINE.new/ctx" "$ENGINE.new/app/tools" "$ENGINE.new/extension"
cp ../ctx/*.py "$ENGINE.new/ctx/"
cp tools/*.swift "$ENGINE.new/app/tools/"          # the helpers ctx compiles on first use, into the archive folder
cp -R ../extension/. "$ENGINE.new/extension/"
git -C .. rev-parse --short HEAD > "$ENGINE.new/COMMIT" 2>/dev/null || true
find "$ENGINE.new" -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
mv "$ENGINE.new" "$ENGINE"
# macos ties full disk access and accessibility to the signature. signed with the same local identity every time,
# a rebuilt app keeps its grants; signed ad hoc, each build is a new app to macos and the grants are dropped.
# the identity is found at build time and never written down here: CONTEXT_SIGN_ID if set, else the first
# "Apple Development" identity in the keychain, else ad hoc.
# signing with a keychain identity makes macos ask for the login password, so it happens only on a deliberate
# install (install.sh signs the copy it installs). a build is always ad-hoc unless CONTEXT_SIGN=1, and never touches the keychain.
ID=""
if [ "$CONTEXT_SIGN" = "1" ]; then
  ID="$CONTEXT_SIGN_ID"
  [ -n "$ID" ] || ID="$(security find-identity -v -p codesigning 2>/dev/null | awk '/"Apple Development/ { print $2; exit }')"
fi
if [ -n "$ID" ] && codesign --force --sign "$ID" --identifier so.context.app "$APP" 2>/dev/null; then
  :
else
  codesign --force --sign - --identifier so.context.app "$APP" 2>/dev/null || true
  [ "$CONTEXT_INSTALL" = "1" ] || echo "signed ad hoc: macos will ask for full disk access and accessibility again after each rebuild. install.sh signs with your own identity if you have one."
fi
codesign -d -r- "$APP" 2>&1 | tail -1
touch "$APP/Contents/MacOS/context"
# a build is not done until every screen lays out: no clipped text, no overlap, nothing outside the window.
# the check draws nothing on screen and reads no real data.
# it also draws each screen light and dark into build/check, and fails when a dark one comes out on a light ground.
# the check runs from a copy outside the app, under another name: a process with the app's bundle id would be
# taken for the installed app by anything that looks it up while the check runs.
echo "3/4 checking every screen lays out (several minutes; it draws nothing on screen)"
cp "$APP/Contents/MacOS/context" build/context-check
if build/context-check --layouttest build/check >build/layout.log 2>/dev/null; then
  tail -1 build/layout.log
else
  grep -v "^search" build/layout.log
  echo "layout check failed: see the lines above. the build is not finished."
  rm -f "$APP/Contents/MacOS/context"
  exit 1
fi
# and every question must end: an answer or a plain sentence, never a turn left waiting. the check talks to a stand-in
# engine in a temporary folder: no real data, no model, nothing drawn. about half a minute.
if build/context-check --asktest >build/ask.log 2>&1; then
  tail -1 build/ask.log
else
  grep -E "^FAIL|timed out" build/ask.log
  echo "ask check failed: see the lines above (all of it: build/ask.log). the build is not finished."
  rm -f "$APP/Contents/MacOS/context"
  exit 1
fi
echo "4/4 built $(pwd)/$APP"
