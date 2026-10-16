#!/usr/bin/env bash
# Smoke-test a frozen engine folder end to end: version, bundled ffmpeg, and a real silence cut.
# usage: smoke_engine.sh <engine-dir> [expected-version]
set -euo pipefail
dir=$1
want=${2:-}

bin() { if [ -f "$dir/$1.exe" ]; then echo "$dir/$1.exe"; else echo "$dir/$1"; fi; }
engine=$(bin claudebolt-engine)
ffmpeg=$(bin ffmpeg)
ffprobe=$(bin ffprobe)
for f in "$engine" "$ffmpeg" "$ffprobe"; do
  [ -x "$f" ] || { echo "missing or not executable: $f"; exit 1; }
done

got=$("$engine" --version | tr -d '\r')
echo "$got"
if [ -n "$want" ] && [ "$got" != "claudebolt $want" ]; then
  echo "expected claudebolt $want"; exit 1
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
# 1 s tone | 3 s silence | 1 s tone: the cut must drop most of the silence
"$ffmpeg" -v error -nostdin -y \
  -f lavfi -i sine=frequency=440:duration=1 \
  -f lavfi -i anullsrc=r=44100:cl=mono:d=3 \
  -f lavfi -i sine=frequency=440:duration=1 \
  -filter_complex "[0:a][1:a][2:a]concat=n=3:v=0:a=1" "$work/in.wav"
# no ffmpeg on PATH for the engine: it has to find the bundled copy
PATH="/usr/bin:/bin" CLAUDEBOLT_CACHE="$work/cache" "$engine" cut "$work/in.wav" -o "$work/out.wav"
dur=$("$ffprobe" -v error -show_entries format=duration -of csv=p=0 "$work/out.wav" | tr -d '\r')
echo "cut 5.0 s -> $dur s"
awk -v d="$dur" 'BEGIN { exit !(d > 1.5 && d < 4.0) }' || { echo "unexpected output duration"; exit 1; }

"$engine" mcp install --list > /dev/null
echo "engine OK"
