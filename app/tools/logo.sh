#!/bin/sh
# redraws the icon and doc images from tools/logo.swift. only needed when the mark changes; the results are committed.
set -e
cd "$(dirname "$0")/.."
T=$(mktemp -d)
swiftc -O -o "$T/logo" tools/logo.swift
"$T/logo" "$T"
S="$T/context.iconset"; mkdir "$S"
for n in 16 32 128 256 512; do
  sips -z $n $n "$T/icon-1024.png" --out "$S/icon_${n}x${n}.png" >/dev/null
  sips -z $((n*2)) $((n*2)) "$T/icon-1024.png" --out "$S/icon_${n}x${n}@2x.png" >/dev/null
done
iconutil -c icns "$S" -o Resources/context.icns
cp "$T/mark.png" "$T/social.png" ../docs/assets/
sips -z 256 256 "$T/icon-1024.png" --out ../docs/assets/icon.png >/dev/null
echo "wrote Resources/context.icns and docs/assets/"
