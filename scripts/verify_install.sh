#!/usr/bin/env bash
# Install a built release package on a clean machine, smoke-test the installed engine, then launch
# the installed desktop app and check that it starts its bundled engine and that engine answers.
# usage: verify_install.sh <nsis|msi|zip|deb|rpm|dmg> <dir-with-package> <expected-version>
set -euo pipefail
kind=$1
pkgdir=$(cd "$2" && pwd)
version=$3
here=$(cd "$(dirname "$0")" && pwd)
tmp=${RUNNER_TEMP:-${TMPDIR:-/tmp}}
one() { # exactly one file matching the glob
  # shellcheck disable=SC2206 # $1 is a glob on purpose
  local m=("$pkgdir"/$1)
  [ ${#m[@]} -eq 1 ] && [ -f "${m[0]}" ] || { echo "expected one $1 in $pkgdir, got: ${m[*]}"; exit 1; }
  echo "${m[0]}"
}
win() { cygpath -w "$1"; }

case $kind in
  nsis)
    dest="$tmp/cb-nsis"
    # NSIS: /S silent, /D=<dir> must be last and unquoted
    powershell -NoProfile -Command "\$p = Start-Process -Wait -PassThru -FilePath '$(win "$(one '*-setup.exe')")' -ArgumentList '/S','/D=$(win "$dest")'; exit \$p.ExitCode"
    root=$dest ;;
  msi)
    log=$(win "$tmp/msi.log")
    powershell -NoProfile -Command "\$p = Start-Process -Wait -PassThru msiexec -ArgumentList '/i','\"$(win "$(one '*.msi')")\"','/qn','/l*v','\"$log\"'; exit \$p.ExitCode" \
      || { tail -n 50 "$tmp/msi.log"; exit 1; }
    root="/c/Program Files/claudebolt" ;;
  zip)
    rm -rf "$tmp/cb-zip" && mkdir -p "$tmp/cb-zip"
    (cd "$tmp/cb-zip" && unzip -q "$(one '*-portable.zip')")
    root="$tmp/cb-zip/claudebolt" ;;
  deb)
    sudo apt-get update -q
    sudo apt-get install -y -q "$(one '*.deb')" xvfb
    engine=$(dpkg -L claudebolt | grep '/claudebolt-engine$') ;;
  rpm)
    # no GUI check here; the .deb run covers the app itself, this proves the rpm installs and runs
    docker run --rm -v "$pkgdir:/pkg:ro" -v "$here:/scripts:ro" fedora:latest bash -euc '
      dnf install -y -q /pkg/*.rpm
      bash /scripts/smoke_engine.sh "$(dirname "$(rpm -ql claudebolt | grep "/claudebolt-engine$")")" '"$version"
    exit 0 ;;
  dmg)
    mnt="$tmp/cb-dmg"
    hdiutil attach -nobrowse -readonly -mountpoint "$mnt" "$(one '*.dmg')"
    cp -R "$mnt"/*.app /Applications/
    hdiutil detach "$mnt"
    codesign --verify --deep --verbose=2 /Applications/claudebolt.app
    root=/Applications/claudebolt.app ;;
  *) echo "unknown package kind: $kind"; exit 1 ;;
esac

[ -n "${engine:-}" ] || engine=$(find "$root" -type f \( -name claudebolt-engine -o -name claudebolt-engine.exe \) -path '*engine/claudebolt-engine*' | head -n1)
[ -n "$engine" ] || { echo "no bundled engine under $root"; exit 1; }
echo "installed engine: $engine"
bash "$here/smoke_engine.sh" "$(dirname "$engine")" "$version"

# ---- launch the installed app --------------------------------------------------------------
case $kind in
  nsis|msi|zip) app="$root/claudebolt.exe" ;;
  deb) app=/usr/bin/claudebolt ;;
  dmg) app=/Applications/claudebolt.app/Contents/MacOS/claudebolt ;;
esac
[ -f "$app" ] || { echo "app binary not found: $app"; exit 1; }
cache="$tmp/cb-launch-cache"
rm -rf "$cache" && mkdir -p "$cache"
export CLAUDEBOLT_CACHE="$cache" # inherited by the engine the app spawns; it writes daemon.json here
if [ "$kind" = deb ]; then
  xvfb-run -a "$app" > "$tmp/app.log" 2>&1 &
else
  "$app" > "$tmp/app.log" 2>&1 &
fi
app_pid=$!
app_winpid=$(cat "/proc/$app_pid/winpid" 2>/dev/null || true)
cleanup() { # only what we launched: the app and the engine it spawned
  if [ -n "$app_winpid" ]; then
    taskkill //F //T //PID "$app_winpid" > /dev/null 2>&1 || true
  fi
  kill "$app_pid" 2>/dev/null || true
  pkill -f "$engine" 2>/dev/null || true
}
trap cleanup EXIT

for _ in $(seq 90); do
  [ -s "$cache/daemon.json" ] && break
  sleep 1
done
if [ ! -s "$cache/daemon.json" ]; then
  echo "the app did not start its engine within 90 s"; cat "$tmp/app.log" || true; exit 1
fi
port=$(sed -E 's/.*"port": *([0-9]+).*/\1/' "$cache/daemon.json")
token=$(sed -E 's/.*"token": *"([^"]+)".*/\1/' "$cache/daemon.json")
health=""
for _ in $(seq 20); do
  health=$(curl -fsS -H "Authorization: Bearer $token" "http://127.0.0.1:$port/api/health" || true)
  [ -n "$health" ] && break
  sleep 1
done
echo "engine started by the app: $health"
case $health in
  *"\"version\":\"$version\""*) echo "app OK" ;;
  *) echo "engine started by the app did not report version $version"; exit 1 ;;
esac
