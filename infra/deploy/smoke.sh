#!/usr/bin/env bash
# The smoke test that follows a production deploy (ADR 0011). It proves the deploy took effect,
# then that the live site is sane.
#
#   1. Poll /version.txt until it is the commit the deploy was built from. The build job writes
#      that file into the site, so the old version cannot pass for the new one.
#   2. / answers 200 and carries the not-affiliated notice, and an unknown path answers 404.
#
# The whole script has one budget, 180 seconds. Each request is held to what is left of it (and to
# 10 seconds), and nothing sleeps past it, so a site that never answers ends the run at about three
# minutes, plus at most the last request's second or two. The workflow step has its own backstop.
#
# EXPECTED_SHA is required. SMOKE_BASE_URL, SMOKE_TIMEOUT (the budget, in seconds) and SMOKE_SLEEP
# exist so the tests can point it at a local server and wait less; the workflow sets none of them.
set -euo pipefail

base="${SMOKE_BASE_URL:-https://m3-tool.broken-wood-97a9.workers.dev}"
expected="${EXPECTED_SHA:?EXPECTED_SHA is the commit the deployed site was built from}"
budget="${SMOKE_TIMEOUT:-180}"
pause="${SMOKE_SLEEP:-10}"
notice='Not affiliated with, endorsed by, or sponsored by BMW AG'

deadline=$((SECONDS + budget))
whole_pause="${pause%%.*}"
whole_pause="${whole_pause:-0}"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

fetch() { # fetch <url> <body file>: prints the HTTP status, or 000 when there was none
  local left=$((deadline - SECONDS))
  ((left > 10)) && left=10
  ((left < 1)) && left=1
  curl -sS --max-time "$left" -H 'Cache-Control: no-cache' -o "$2" -w '%{http_code}' "$1" 2>/dev/null || true
}

# Sleeps between tries, unless the sleep would run past the deadline. Returns 1 then, to stop.
wait_or_stop() {
  if ((SECONDS + whole_pause >= deadline)); then return 1; fi
  sleep "$pause"
}

found=no
attempt=0
while ((SECONDS < deadline)); do
  attempt=$((attempt + 1))
  : > "$tmp/version"
  status="$(fetch "$base/version.txt?attempt=$attempt" "$tmp/version")"
  live="$(tr -d '[:space:]' < "$tmp/version" | head -c 100 || true)"
  if [ "$status" = 200 ] && [ "$live" = "$expected" ]; then
    found=yes
    break
  fi
  echo "Attempt $attempt, $((deadline - SECONDS)) s left: /version.txt gave '$status' and '${live:0:60}', waiting for $expected."
  wait_or_stop || break
done
if [ "$found" != yes ]; then
  echo "::error::The live site never served /version.txt = $expected within $budget s, so the deploy did not take effect, or the site is down."
  exit 1
fi
echo "The live site is serving $expected."

# One try is always made, even if the version only just appeared.
attempt=0
while :; do
  attempt=$((attempt + 1))
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
  echo "Attempt $attempt: / gave '$home' (want 200), /__nope gave '$nope' (want 404), notice present: $has_notice."
  ((SECONDS < deadline)) || break
  wait_or_stop || break
done
echo "::error::The live site failed the smoke test: it needs a 200 on / with the not-affiliated notice, and a 404 on /__nope."
exit 1
