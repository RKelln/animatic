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
#   bash pull-deck.sh W01 --follow  # pulls every 1.5 s and serves, AND makes sure a watcher is
#                                   # running on experimance for that outdir: reuses one if it is
#                                   # there, starts one if not. Not for carrying: plain build first
#   bash pull-deck.sh W01 --follow --no-watch       # follow, but never start or stop the box's
#                                                   # build (you started one yourself)
#   bash pull-deck.sh W01 --follow --talk=/path/on/box/talk.md
#                                                   # skip discovery: watch this talkfile
#   OUTDIR=out-w11 bash pull-deck.sh                               # or name the folder outright
#   BOX=203.0.113.10 bash pull-deck.sh                          # if name lookup fails
#
# Why pull and not push: experimance has no access into framework, so the transfer
# runs from the side that can reach the other one. Retries, --partial-dir resume
# and the verification all live here, on the machine you are sitting at.
#
# --follow OWNS ITS WATCH. It reuses a watcher already running for this outdir and
# never doubles one (two build.py --watch on the same --out fight over the same
# staging directory). If there is none, it starts one over ssh and stamps a lease
# file on the box; the pull loop heartbeats that file, and the watcher stops
# itself when the beat goes stale, so a SIGKILLed puller, a closed window or a
# dropped link cannot leave a watch rebuilding behind your back. Ctrl-c stops it
# directly; the lease is the backstop, not the plan.
#
# Env knobs: OUTDIR DECK BOX TALK REMOTE_BASE LOCAL_BASE PORT
#   OUTDIR wins; else the slug argument; else DECK (same as the slug); else L01 (out-l01)
#   FOLLOW_INTERVAL seconds between pulls under --follow (default 1.5)
#   LEASE_TIMEOUT seconds of silence before a started watch stops itself (60)
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
TALK=${TALK:-}                       # talkfile ON THE BOX: skips discovery under --follow

# Defined up here because the exit trap below may need to reach the box, and it
# can fire from any exit after this point.
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=6 -o StrictHostKeyChecking=accept-new)

DRY=0; SERVE=0; CHECK=0; OFFLINE=0; FOLLOW=0; NOWATCH=0; SLUG=""
FOLLOW_INTERVAL=${FOLLOW_INTERVAL:-1.5}
LEASE_TIMEOUT=${LEASE_TIMEOUT:-60}
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY=1 ;;
    --serve)      SERVE=1 ;;
    --serve-only) SERVE=1; OFFLINE=1 ;;
    --check)      CHECK=1 ;;
    --follow)     FOLLOW=1; SERVE=1 ;;
    --no-watch)   NOWATCH=1 ;;
    --talk=*)     TALK=${1#--talk=} ;;
    -h|--help)    sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
    *) if [ -z "$SLUG" ]; then SLUG="$1"
       else echo "one deck at a time: got '$SLUG' and '$1' (try --help)" >&2; exit 2; fi ;;
  esac
  shift
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

# --- what we started on the box, and how it gets stopped ----------------------
WATCH_SSH=""; WATCH_PID=""; WATCH_OWNED=0; LEASE_REL=""; BEAT_AT=0
WATCH_LOG="$HOME/.cache/pull-deck-watch.log"

# One cleanup path for ctrl-c, TERM, a failed command under set -e and the normal
# end of the script. INT and TERM only convert into an exit, so this always runs.
stop_watch() {
  set +e
  trap '' INT TERM          # a second ctrl-c must not cut the cleanup short
  if [ "$FOLLOW" = 1 ]; then
    echo
    echo "follow stopped. The copy is the last pull; the server is still up (see the kill line above)."
  fi
  if [ "$WATCH_OWNED" = 1 ] && [ -n "$WATCH_PID" ]; then
    # bounded on purpose: ctrl-c must not hang on a dead link
    if timeout 5 ssh "${SSH_OPTS[@]}" "$BOX" "kill $WATCH_PID" 2>/dev/null; then
      echo "  watch    : stopped (pid $WATCH_PID on $BOX)"
    else
      echo "  watch    : could not reach $BOX; the lease stops pid $WATCH_PID" \
           "within ${LEASE_TIMEOUT}s of silence" >&2
    fi
    [ -n "$WATCH_SSH" ] && kill "$WATCH_SSH" 2>/dev/null
  elif [ -n "$WATCH_PID" ]; then
    echo "  watch    : left running (you started it): kill $WATCH_PID on $BOX"
  fi
  if [ "$FOLLOW" = 1 ] && [ -f "${DST:-/nonexistent}/_watch.js" ]; then
    echo "note: this local copy is a WATCH build. Before carrying it anywhere: stop the"
    echo "      watch, run a plain build.py on the box, then  bash $0 ${SLUG:-${OUTDIR#out-}} --check"
  fi
  return 0                  # a trap's last command decides the exit status otherwise
}
trap 'exit 130' INT
trap 'exit 143' TERM
trap stop_watch EXIT

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

# --- make sure something on the box is building this outdir -------------------
# Three things can be true: a watch is already running (reuse it, never double
# one), none is running (start one we own), or we cannot tell which talkfile it
# came from (say so, keep following anyway). Starting needs the talkfile, which
# the built folder does not record: nav.json is deliberately path-free, so the
# box is asked instead.
watch_remote() {
  set +e
  local running mine
  running=$(ssh "${SSH_OPTS[@]}" "$BOX" "pgrep -af 'build\\.py.*--watch'" 2>/dev/null)
  # both spellings, because argparse accepts --out X and --out=X
  mine=$(printf '%s\n' "$running" | grep -E -- "--out[= ]$OUTDIR( |\$)" | head -1)
  if [ -z "$mine" ] && [ "$OUTDIR" = out ]; then    # the default --out needs no flag
    mine=$(printf '%s\n' "$running" | grep -v -- '--out' | head -1)
  fi
  if [ -n "$mine" ]; then
    WATCH_PID=$(printf '%s' "$mine" | cut -d' ' -f1)
    WATCH_OWNED=0
    echo "  watch    : already running on the box for $OUTDIR (pid $WATCH_PID)"
    echo "             following it, and leaving it alone when this stops"
    return 0
  fi

  if [ -z "$TALK" ]; then
    TALK=$(ssh "${SSH_OPTS[@]}" "$BOX" \
      "cd '$REMOTE_BASE' && python3 tools/find-talkfile.py --outdir '$OUTDIR'" 2>/dev/null)
  fi
  if [ -z "$TALK" ]; then
    echo "  watch    : nothing is building $OUTDIR on the box, and I cannot tell which" >&2
    echo "             talkfile built it. Start one there, then re-run with --no-watch:" >&2
    echo "               ssh $BOX \"cd $REMOTE_BASE && python3 build.py <talk.md> --out $OUTDIR --watch\"" >&2
    echo "             or name it here:  bash $0 ${SLUG:-<deck>} --follow --talk=/path/on/box/talk.md" >&2
    return 0
  fi

  # The lease lives under the REMOTE user's home, which is not this shell's $HOME:
  # keep it relative and let the box expand $HOME itself.
  LEASE_REL=".cache/animatic/watch-$OUTDIR.lease"
  ssh "${SSH_OPTS[@]}" "$BOX" \
    "mkdir -p \"\$HOME/$(dirname "$LEASE_REL")\" && date +%s > \"\$HOME/$LEASE_REL\""
  # echo $$ then exec: exec keeps the pid, so the first line is the watcher's own
  # pid. Nothing to clean up if the start fails halfway, and no pid file to trust.
  ssh "${SSH_OPTS[@]}" "$BOX" \
    "cd '$REMOTE_BASE' && { echo \$\$; exec python3 build.py '$TALK' --out '$OUTDIR' \
       --watch --lease \"\$HOME/$LEASE_REL\" --lease-timeout $LEASE_TIMEOUT; }" \
    </dev/null >"$WATCH_LOG" 2>&1 &
  WATCH_SSH=$!
  local i
  for i in $(seq 1 50); do                    # up to 5s for the pid line
    WATCH_PID=$(head -1 "$WATCH_LOG" 2>/dev/null | tr -dc '0-9')
    [ -n "$WATCH_PID" ] && break
    sleep 0.1
  done
  if [ -z "$WATCH_PID" ]; then
    echo "  watch    : could not start one; the box said:" >&2
    sed 's/^/             /' "$WATCH_LOG" >&2
    return 0
  fi
  WATCH_OWNED=1
  echo "  watch    : started pid $WATCH_PID on $BOX"
  echo "             $TALK --out $OUTDIR"
  echo "             it stops on ctrl-c here, or by itself ${LEASE_TIMEOUT}s after the last pull"
}

if [ "$SERVE" = 1 ]; then serve_deck; fi

# --- follow: keep pulling so an open deck reloads as experimance rebuilds ------------
# build.py --watch swaps a finished build in and bumps _watch.js, and the open page polls
# that file. So: pull everything except _watch.js, then pull _watch.js last, so a reload
# can only fire once the rest of the build is already here.
if [ "$FOLLOW" = 1 ]; then
  echo
  echo "=== following $BOX:$SRC every ${FOLLOW_INTERVAL}s (ctrl-c stops) ==="
  if [ "$NOWATCH" = 1 ]; then
    echo "  watch    : --no-watch, so I am not touching the box's build."
  else
    watch_remote
  fi
  if grep -q 'animatic --watch' "$DST/present/index.html" 2>/dev/null; then
    echo "  WATCH BUILD: this copy has the reload snippet in it. Do not carry it to the venue:"
    echo "  stop the watch, run a plain build.py, then  bash pull-deck.sh ${SLUG:-${OUTDIR#out-}} --check"
  fi
  PULLS=0
  while sleep "$FOLLOW_INTERVAL"; do
    # heartbeat + liveness in one round trip: the beat keeps the watcher's lease
    # fresh, and kill -0 tells us it is still there. Throttled to every 10s.
    if [ "$WATCH_OWNED" = 1 ] && [ $(( $(date +%s) - BEAT_AT )) -ge 10 ]; then
      if ssh "${SSH_OPTS[@]}" "$BOX" \
           "date +%s > \"\$HOME/$LEASE_REL\" && kill -0 '$WATCH_PID'" 2>/dev/null; then
        BEAT_AT=$(date +%s)
      else
        printf '  %s  the box is not answering or its watch (pid %s) is gone;' \
          "$(date +%H:%M:%S)" "$WATCH_PID" >&2
        printf ' still pulling. ctrl-c and re-run to start a new one.\n' >&2
        BEAT_AT=$(date +%s)          # do not repeat the warning every loop
      fi
    fi
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
        # a failed build never stops build.py --watch, so from here it is invisible
        if [ "$WATCH_OWNED" = 1 ] && tail -1 "$WATCH_LOG" 2>/dev/null | grep -q 'build FAILED'; then
          printf '  %s  the box build FAILED, so this pull is the last good build\n' \
            "$(date +%H:%M:%S)" >&2
        fi
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
