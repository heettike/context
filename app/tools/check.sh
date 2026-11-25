#!/bin/sh
# builds, runs the unit and layout checks, and writes renders of every screen (light and dark) plus two contact
# sheets to a folder to look over. nothing appears on screen and no real data is read.
# usage: tools/check.sh [folder]   (default: build/check)
set -e
cd "$(dirname "$0")/.."
OUT="${1:-build/check}"
./build.sh
BIN=build/context.app/Contents/MacOS/context
"$BIN" --selftest | tail -1
"$BIN" --asktest | tail -1      # the chat against a stand-in engine: every outcome ends in an answer or a sentence
mkdir -p "$OUT"
"$BIN" --layouttest "$OUT" 2>/dev/null | grep -v "^search"
echo "renders and contact sheets: $OUT (contact-light.png, contact-dark.png)"
