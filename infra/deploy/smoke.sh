#!/usr/bin/env bash
# The smoke test that follows a production deploy (ADR 0011). It proves the deploy took effect,
# then that the live site is sane.
#
#   1. Poll /version.txt until it is the commit the deploy was built from. The build job writes
#      that file into the site, so the old version cannot pass for the new one.
#   2. / answers 200 and carries the not-affiliated notice, and an unknown path answers 404.
#
# EXPECTED_SHA is required. SMOKE_BASE_URL, SMOKE_ATTEMPTS and SMOKE_SLEEP exist so the tests can
# point it at a local server and wait less; the workflow sets none of them, so it asks production
# for up to 12 tries ten seconds apart, about two minutes.
set -euo pipefail

base="${SMOKE_BASE_URL:-https://m3-tool.broken-wood-97a9.workers.dev}"
expected="${EXPECTED_SHA:?EXPECTED_SHA is the commit the deployed site was built from}"
attempts="${SMOKE_ATTEMPTS:-12}"
pause="${SMOKE_SLEEP:-10}"
notice='Not affiliated with, endorsed by, or sponsored by BMW AG'

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

fetch() { # fetch <url> <body file>: prints the HTTP status, or 000 when there was none
  curl -sS --max-time 20 -H 'Cache-Control: no-cache' -o "$2" -w '%{http_code}' "$1" 2>/dev/null || true
}

found=no
for ((attempt = 1; attempt <= attempts; attempt++)); do
  : > "$tmp/version"
  status="$(fetch "$base/version.txt?attempt=$attempt" "$tmp/version")"
  live="$(tr -d '[:space:]' < "$tmp/version" | head -c 100 || true)"
  if [ "$status" = 200 ] && [ "$live" = "$expected" ]; then
    found=yes
    break
  fi
  echo "Attempt $attempt of $attempts: /version.txt gave '$status' and '${live:0:60}', waiting for $expected."
  sleep "$pause"
done
if [ "$found" != yes ]; then
  echo "::error::The live site never served /version.txt = $expected, so the deploy did not take effect, or the site is down."
  exit 1
fi
echo "The live site is serving $expected."

for ((attempt = 1; attempt <= 3; attempt++)); do
  : > "$tmp/home"
  home="$(fetch "$base/" "$tmp/home")"
  nope="$(fetch "$base/__nope" /dev/null)"
  text="$(tr -s '[:space:]' ' ' < "$tmp/home")"
  has_notice=no
  case "$text" in *"$notice"*) has_notice=yes ;; esac
  if [ "$home" = 200 ] && [ "$nope" = 404 ] && [ "$has_notice" = yes ]; then
    echo "Smoke test passed: / is 200 with the notice, /__nope is 404."
    exit 0
  fi
  echo "Attempt $attempt of 3: / gave '$home' (want 200), /__nope gave '$nope' (want 404), notice present: $has_notice."
  sleep "$pause"
done
echo "::error::The live site failed the smoke test: it needs a 200 on / with the not-affiliated notice, and a 404 on /__nope."
exit 1
