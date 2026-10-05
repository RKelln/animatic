#!/usr/bin/env bash
# pull-deck.sh — run this ON framework. It MIRRORS the built deck from experimance
# and can serve it locally, so the deck gets tested the way it will actually run:
# served from localhost on the machine that will page it.
#
#   bash pull-deck.sh --dry-run     # show what would move, write nothing (start here)
#   bash pull-deck.sh               # mirror the built deck into ~/Documents/art/animatic
#   bash pull-deck.sh --serve       # mirror, then serve on http://localhost:8787
#   bash pull-deck.sh --serve-only  # NO network: serve the copy already on this machine
#                                   # (use this at the venue, where experimance is out of reach)
#   bash pull-deck.sh --check       # verify the copy matches the source, no writes (-c, thorough)
#   bash pull-deck.sh W01 --serve   # another deck: the event slug (L01, W01, W02, W11 ...)
#                                   # maps to out-<slug lowercased>; a full deck name works too
#                                   # (W01-bring-your-problems -> out-w01)
#   bash pull-deck.sh W01 --follow  # edit on experimance with  build.py ... --watch  running there;
#                                   # this serves on localhost and re-pulls every 1.5 s, so the open
#                                   # deck reloads. Not for carrying: do a plain build + pull first
#   OUTDIR=out-w11 bash pull-deck.sh                               # or name the folder outright
#   BOX=203.0.113.10 bash pull-deck.sh                          # if name lookup fails
#
# Why pull and not push: experimance has no access into framework, so the transfer
# runs from the side that can reach the other one. Retries, --partial-dir resume
# and the verification all live here, on the machine you are sitting at.
#
# Env knobs: OUTDIR DECK BOX REMOTE_BASE LOCAL_BASE PORT
#   OUTDIR wins; else the slug argument; else DECK (same as the slug); else L01 (out-l01)
#   FOLLOW_INTERVAL seconds between pulls under --follow (default 1.5)
#   defaults: OUTDIR=out-l01
#             REMOTE_BASE=~/Documents/art/animatic
#             LOCAL_BASE=the animatic folder this script is in (<base>/tools/), else
#                        $HOME/Documents/art/animatic     PORT=8787
set -euo pipefail

DECK=${DECK:-}
OUTDIR=${OUTDIR:-}
BOX=${BOX:-}
REMOTE_BASE=${REMOTE_BASE:-~/Documents/art/animatic}
# Where the copy lives on THIS machine: the animatic folder this script sits in
# (<base>/tools/pull-deck.sh), so framework'"'"'s ~/Documents/Projects/Art/animatic and
# experimance'"'"'s ~/Documents/art/animatic both just work. LOCAL_BASE still wins; a script
# run from outside a tools/ folder falls back to the old default.
_here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ "$(basename "$_here")" = tools ]; then _base=$(dirname "$_here"); else _base=$HOME/Documents/art/animatic; fi
LOCAL_BASE=${LOCAL_BASE:-$_base}
PORT=${PORT:-8787}
FORCE=${FORCE:-0}                    # FORCE=1 skips the on-the-right-machine guard (tests only)

DRY=0; SERVE=0; CHECK=0; OFFLINE=0; FOLLOW=0; SLUG=""
FOLLOW_INTERVAL=${FOLLOW_INTERVAL:-1.5}
for a in "$@"; do
  case "$a" in
    --dry-run|-n) DRY=1 ;;
    --serve)      SERVE=1 ;;
    --serve-only) SERVE=1; OFFLINE=1 ;;
    --check)      CHECK=1 ;;
    --follow)     FOLLOW=1; SERVE=1 ;;
    -h|--help)    sed -n '2,31p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option: $a (try --help)" >&2; exit 2 ;;
    *) if [ -z "$SLUG" ]; then SLUG="$a"
       else echo "one deck at a time: got '$SLUG' and '$a' (try --help)" >&2; exit 2; fi ;;
  esac
done

if [ "$FOLLOW" = 1 ] && { [ "$OFFLINE" = 1 ] || [ "$DRY" = 1 ] || [ "$CHECK" = 1 ]; }; then
  echo "--follow pulls from experimance continuously; it cannot combine with --serve-only, --dry-run or --check." >&2
  exit 2
fi

# which built folder: OUTDIR outright, else the event slug (the part before the first
# dash, lowercased: W01 and W01-bring-your-problems both mean out-w01), else L01.
if [ -z "$OUTDIR" ]; then
  s=${SLUG:-${DECK:-L01-opening-talk}}
  OUTDIR="out-$(printf '%s' "${s%%-*}" | tr '[:upper:]' '[:lower:]')"
fi

if [ "$(hostname)" = "experimance" ] && [ "$FORCE" != 1 ]; then
  echo "This script runs ON framework and pulls FROM experimance; you are on experimance." >&2
  echo "(Nothing was changed. Run it on framework, or FORCE=1 for a local test run.)" >&2
  exit 2
fi

# --- serve it the way the talk will ------------------------------------------
serve_deck() {
  echo
  echo "=== serving ==="
  # Whatever already holds the port: reuse it only if it is serve-deck.py. A stock
  # `http.server` left over from an earlier run ignores Range (see below) and was
  # being silently reused, which looked like a fixed script and behaved like the old one.
  HELD=$(ss -ltnp 2>/dev/null | grep ":$PORT " | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2 || true)
  if [ -n "$HELD" ]; then
    HELD_CMD=$(ps -p "$HELD" -o cmd= 2>/dev/null || true)
    case "$HELD_CMD" in
      *serve-deck.py*) echo "  port $PORT already served by serve-deck.py (pid $HELD), reusing it" ;;
      *http.server*)
        echo "  port $PORT held by a stock http.server (pid $HELD): it ignores Range, replacing it"
        kill "$HELD" 2>/dev/null || true; sleep 1 ;;
      *) echo "  port $PORT is held by something else (pid $HELD: ${HELD_CMD:-unknown}); free it or set PORT=" >&2
         SERVE=0 ;;
    esac
  elif ss -ltn 2>/dev/null | grep -q ":$PORT "; then
    echo "  port $PORT is listening but its owner is not visible; free it or set PORT=" >&2
    SERVE=0
  fi
  if [ "$SERVE" = 1 ] && ss -ltn 2>/dev/null | grep -q ":$PORT "; then
    :   # reusing a serve-deck.py that is already up
  elif [ "$SERVE" != 1 ]; then
    :
  elif ! command -v python3 >/dev/null; then
    echo "  python3 not found here; serve it yourself some other way" >&2
    SERVE=0
  else
    # --directory, not `cd X &&`: with a list in the background $! names the wrapper
    # subshell, not the server, so a pid file written that way cannot stop the server
    # (the port stays bound and the next --serve reuses a deck nobody can kill).
    mkdir -p "$(dirname "$HOME/.cache/pull-deck.pid")"
    # NOT `python3 -m http.server`: it ignores Range, so every video is a whole-file
    # 200 that cannot be seeked or stopped early, and a cancelled preload resets the
    # connection and leaves the next slide's video black. serve-deck.py answers 206.
    mkdir -p "$LOCAL_BASE/tools"
    if [ "$OFFLINE" = 1 ]; then
      if [ ! -f "$LOCAL_BASE/tools/serve-deck.py" ]; then
        echo "  no $LOCAL_BASE/tools/serve-deck.py here: run  bash pull-deck.sh --serve  once while experimance is reachable" >&2
        return 1
      fi
    else
      rsync -a "$BOX:$REMOTE_BASE/tools/serve-deck.py" "$LOCAL_BASE/tools/serve-deck.py"
    fi
    nohup python3 "$LOCAL_BASE/tools/serve-deck.py" --port "$PORT" --bind 127.0.0.1 --directory "$LOCAL_BASE" \
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
    VID=$(find "$DST/_media" -name '*.mp4' -size +100k 2>/dev/null | head -1) || true   # a deck with no _media folder must not end the script under pipefail
    if [ -n "$VID" ]; then
      RC=$(curl -s -o /dev/null -w '%{http_code}' -H 'Range: bytes=0-99' "$URL/_media/$(basename "$VID")" || echo 000)
      if [ "$RC" = 206 ]; then echo "  range    : video requests answered 206 (seek/stop-early OK) ✓"
      else echo "  range    : got $RC, expected 206: this server cannot stream video properly ✗" >&2; fi
    fi
    echo "  presenter: press s in the deck (or $URL/present/presenter.html)"
    echo "  on screen : press i for the diagnostics dump"
  fi
}

# --- offline: serve what is already here, touch no network ---------------------
if [ "$OFFLINE" = 1 ]; then
  DST="$LOCAL_BASE/$OUTDIR"
  if [ ! -f "$DST/present/index.html" ]; then
    echo "no deck at $DST: pull it first (bash pull-deck.sh) while experimance is reachable." >&2
    exit 4
  fi
  LOCAL_HTML=$(sha256sum "$DST/present/index.html" | cut -c1-12)
  printf 'serving the local copy only (no network): %s, html %s\n' "$DST" "$LOCAL_HTML"
  serve_deck || exit $?
  echo
  echo "notes: this is the copy already on this machine (build '$LOCAL_HTML'); nothing was pulled."
  echo "       Reload with ctrl-shift-R: the deck has no cache-buster."
  exit 0
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

if [ "$SERVE" = 1 ]; then serve_deck; fi

# --- follow: keep pulling so an open deck reloads as experimance rebuilds ------------
# build.py --watch swaps a finished build in and bumps _watch.js, and the open page polls
# that file. So: pull everything except _watch.js, then pull _watch.js last, so a reload
# can only fire once the rest of the build is already here.
if [ "$FOLLOW" = 1 ]; then
  trap 'echo; echo "follow stopped. The server is still up (see the kill line above); the copy is the last pull."; exit 0' INT TERM
  echo
  echo "=== following $BOX:$SRC every ${FOLLOW_INTERVAL}s (ctrl-c stops) ==="
  if grep -q 'animatic --watch' "$DST/present/index.html" 2>/dev/null; then
    echo "  WATCH BUILD: this copy has the reload snippet in it. Do not carry it to the venue:"
    echo "  stop the watch, run a plain build.py, then  bash pull-deck.sh ${SLUG:-${OUTDIR#out-}} --check"
  fi
  PULLS=0
  while sleep "$FOLLOW_INTERVAL"; do
    set +e
    CH=$(rsync "${RSYNC_COMMON[@]}" -i --delete --exclude '_watch.js' "$BOX:$SRC/" "$DST/" 2>&1)
    RC=$?
    if [ "$RC" -eq 0 ] || [ "$RC" -eq 24 ]; then
      rsync -a "$BOX:$SRC/_watch.js" "$DST/_watch.js" >/dev/null 2>&1
      WRC=$?
      # 23 = the source has no _watch.js, i.e. a plain build: drop the stale stamp
      [ "$WRC" -eq 23 ] && rm -f "$DST/_watch.js"
      N=$(printf '%s\n' "$CH" | grep -c . )
      if [ "$N" -gt 0 ]; then
        PULLS=$((PULLS+1))
        printf '  %s  pulled %s change(s), html %s\n' "$(date +%H:%M:%S)" "$N" \
          "$(sha256sum "$DST/present/index.html" 2>/dev/null | cut -c1-12)"
      fi
    else
      printf '  %s  pull failed (rsync rc=%s), will retry\n' "$(date +%H:%M:%S)" "$RC" >&2
    fi
    set -e
  done
fi

echo
echo "notes: localhost is a SECURE CONTEXT, so the live-capture screens work here and"
echo "       cannot over a Tailscale http:// address. Reload with ctrl-shift-R: the deck"
echo "       has no cache-buster, so a stale image is easy to mistake for a stale build."
echo "       This copy is build '$LOCAL_HTML'; ask the box for its hash to compare revisions."
