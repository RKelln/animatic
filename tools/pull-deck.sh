#!/usr/bin/env bash
# pull-deck.sh — run this ON framework. It MIRRORS the built deck from experimance
# and can serve it locally, so the deck gets tested the way it will actually run:
# served from localhost on the machine that will page it.
#
#   bash pull-deck.sh --dry-run     # show what would move, write nothing (start here)
#   bash pull-deck.sh               # mirror the built deck into ~/Documents/art/animatic
#   bash pull-deck.sh --serve       # mirror, then serve on http://localhost:8787
#   bash pull-deck.sh --check       # verify the copy matches the source, no writes (-c, thorough)
#   DECK=W11-vibe-coding-games OUTDIR=out-w11 bash pull-deck.sh    # another deck
#   BOX=203.0.113.10 bash pull-deck.sh                          # if name lookup fails
#
# Why pull and not push: experimance has no access into framework, so the transfer
# runs from the side that can reach the other one. Retries, --partial-dir resume
# and the verification all live here, on the machine you are sitting at.
#
# Env knobs: DECK OUTDIR BOX REMOTE_BASE LOCAL_BASE PORT
#   defaults: DECK=L01-opening-talk OUTDIR=out-l01
#             REMOTE_BASE=~/Documents/art/animatic
#             LOCAL_BASE=$HOME/Documents/art/animatic  PORT=8787
set -euo pipefail

DECK=${DECK:-L01-opening-talk}
OUTDIR=${OUTDIR:-out-l01}
BOX=${BOX:-}
REMOTE_BASE=${REMOTE_BASE:-~/Documents/art/animatic}
LOCAL_BASE=${LOCAL_BASE:-$HOME/Documents/art/animatic}
PORT=${PORT:-8787}
FORCE=${FORCE:-0}                    # FORCE=1 skips the on-the-right-machine guard (tests only)

DRY=0; SERVE=0; CHECK=0
for a in "$@"; do
  case "$a" in
    --dry-run|-n) DRY=1 ;;
    --serve)      SERVE=1 ;;
    --check)      CHECK=1 ;;
    -h|--help)    sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $a (try --help)" >&2; exit 2 ;;
  esac
done

if [ "$(hostname)" = "experimance" ] && [ "$FORCE" != 1 ]; then
  echo "This script runs ON framework and pulls FROM experimance; you are on experimance." >&2
  echo "(Nothing was changed. Run it on framework, or FORCE=1 for a local test run.)" >&2
  exit 2
fi

SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=6 -o StrictHostKeyChecking=accept-new)

# --- resolve the box rather than hardcoding it -------------------------------
if [ -z "$BOX" ]; then
  for cand in experimance host.example.ts.net 203.0.113.10; do
    if ssh "${SSH_OPTS[@]}" "$cand" true 2>/dev/null; then BOX=$cand; break; fi
  done
fi
if [ -z "$BOX" ]; then
  echo "cannot reach experimance (tried: experimance, host.example.ts.net, 203.0.113.10)." >&2
  echo "If SSH to the box needs a key or an alias, pass it: BOX=<ssh-target> bash $0" >&2
  exit 3
fi

SRC="$REMOTE_BASE/$OUTDIR"
DST="$LOCAL_BASE/$OUTDIR"

# --- what is over there ------------------------------------------------------
if ! ssh "${SSH_OPTS[@]}" "$BOX" "test -d '$SRC'"; then
  echo "no built deck at $BOX:$SRC" >&2
  echo "build it on the box first:  python3 build.py <talk.md> --out $OUTDIR" >&2
  exit 4
fi

INFO=()
while IFS= read -r line; do INFO+=("$line"); done < <(ssh "${SSH_OPTS[@]}" "$BOX" \
  "du -sh '$SRC' | cut -f1; find '$SRC' -type f | wc -l; sha256sum '$SRC/present/index.html' | cut -c1-12" 2>/dev/null)
SRC_SIZE=${INFO[0]:-}; SRC_N=${INFO[1]:-}; SRC_HTML=${INFO[2]:-}
if [ -z "$SRC_SIZE" ] || [ -z "$SRC_N" ] || [ -z "$SRC_HTML" ]; then
  echo "could not read the deck's size, file count and hash over ssh — the connection" >&2
  echo "answered 'test -d' but not the follow-up (dropped link, or a login banner on stdout)." >&2
  exit 5
fi
printf 'box      : %s\n' "$BOX"
printf 'source   : %s/%s  (%s, %s files, html %s)\n' "$REMOTE_BASE" "$OUTDIR" "$SRC_SIZE" "$SRC_N" "$SRC_HTML"
printf 'target   : %s\n' "$DST"

RSYNC_COMMON=(-a --partial-dir=.rsync-partial --human-readable
              --exclude '.DS_Store' --exclude '.giosave*' --exclude '.rsync-partial')

mkdir -p "$LOCAL_BASE"

# --- transfer (or inspect) ---------------------------------------------------
if [ "$CHECK" = 1 ]; then
  echo
  echo "=== check: does the local copy match the source? (checksums, no writes) ==="
  set +e
  OUT=$(rsync "${RSYNC_COMMON[@]}" -n -c -i --delete "$BOX:$SRC/" "$DST/" 2>&1)
  RC=$?
  set -e
  if [ "$RC" -ne 0 ]; then
    echo "  rsync could not run (rc=$RC) — this is NOT a verdict about the copy:" >&2
    printf '%s\n' "$OUT" | sed 's/^/    /' >&2
    exit 5
  fi
  if [ -z "$OUT" ]; then
    echo "  identical to the source, file for file ✓"
  else
    echo "  differences ($(printf '%s\n' "$OUT" | grep -c .) entries, first 20):"
    printf '%s\n' "$OUT" | head -20 | sed 's/^/    /'
    echo "  run without --check to bring it up to date."
  fi
  exit 0
fi

if [ "$DRY" = 1 ]; then
  echo
  echo "=== dry run: nothing will be written ==="
  rsync "${RSYNC_COMMON[@]}" -n -i --delete "$BOX:$SRC/" "$DST/" | sed 's/^/  /'
  echo "  (re-run without --dry-run to apply)"
  exit 0
fi

echo
echo "=== pulling ==="
rsync "${RSYNC_COMMON[@]}" --info=stats2 --delete "$BOX:$SRC/" "$DST/"

# --- prove the mirror instead of assuming it ---------------------------------
echo
echo "=== verify ==="
set +e
DIFF=$(rsync "${RSYNC_COMMON[@]}" -n -i --delete "$BOX:$SRC/" "$DST/" 2>&1)
RCV=$?
set -e
if [ "$RCV" -ne 0 ]; then
  echo "  verification could not run (rsync rc=$RCV):" >&2
  printf '%s\n' "$DIFF" | sed 's/^/    /' >&2
  LEFT="could-not-verify"
else
  LEFT=$(printf '%s\n' "$DIFF" | grep -c . || true)
fi
LOCAL_HTML=$(sha256sum "$DST/present/index.html" | cut -c1-12)
printf '  entries still differing : %s\n' "$LEFT"
printf '  present/index.html      : source %s / copy %s  %s\n' \
  "$SRC_HTML" "$LOCAL_HTML" \
  "$([ "$SRC_HTML" = "$LOCAL_HTML" ] && echo 'match ✓' || echo 'MISMATCH ✗')"
if [ "$LEFT" != "0" ] || [ "$SRC_HTML" != "$LOCAL_HTML" ]; then
  echo "  mirror is not proven exact; re-run, or --check for the full list" >&2
fi

# --- serve it the way the talk will ------------------------------------------
if [ "$SERVE" = 1 ]; then
  echo
  echo "=== serving ==="
  if ss -ltn 2>/dev/null | grep -q ":$PORT "; then
    echo "  port $PORT already listening (reusing it)"
  elif ! command -v python3 >/dev/null; then
    echo "  python3 not found here; serve it yourself some other way" >&2
    SERVE=0
  else
    # --directory, not `cd X &&`: with a list in the background $! names the wrapper
    # subshell, not the server, so a pid file written that way cannot stop the server
    # (the port stays bound and the next --serve reuses a deck nobody can kill).
    mkdir -p "$(dirname "$HOME/.cache/pull-deck.pid")"
    nohup python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$LOCAL_BASE" \
      >> "$HOME/.cache/pull-deck-server.log" 2>&1 &
    SRV_PID=$!
    echo "$SRV_PID" > "$HOME/.cache/pull-deck.pid"
    echo "  serving pid $SRV_PID (log: ~/.cache/pull-deck-server.log)"
    echo "  stop it with: kill $SRV_PID"
  fi
  if [ "$SERVE" = 1 ]; then
    URL="http://localhost:$PORT/$OUTDIR"
    CODE=$(curl -s --retry 6 --retry-connrefused --retry-delay 1 -m 10 -o /dev/null -w '%{http_code}' "$URL/present/index.html" || echo 000)
    echo
    echo "  present  : $URL/present/index.html   [$CODE]"
    echo "  handout  : $URL/document/index.html"
    echo "  presenter: press s in the deck (or $URL/present/presenter.html)"
    echo "  on screen : press i for the diagnostics dump"
  fi
fi

echo
echo "notes: localhost is a SECURE CONTEXT, so the live-capture screens work here and"
echo "       cannot over a Tailscale http:// address. Reload with ctrl-shift-R: the deck"
echo "       has no cache-buster, so a stale image is easy to mistake for a stale build."
echo "       This copy is build '$LOCAL_HTML'; ask the box for its hash to compare revisions."
