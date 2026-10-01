#!/usr/bin/env bash
# pull-deck-test.sh — harness for tools/pull-deck.sh.
#
# pull-deck.sh drives ANOTHER machine over ssh+rsync, so it cannot be tested by
# calling it with a real argv array on one box: the thing that breaks (ssh joins
# its arguments into one string for the remote shell to re-parse) has to be
# reproduced, not bypassed. This harness puts an `ssh` stand-in first in PATH that
# does exactly what ssh does -- options, then the host, then the remote command
# joined into ONE string for a shell to parse -- so the script's own quoting is
# exercised and its argv is never passed through as an array.
# rsync speaks its normal protocol to the local rsync through that same shim.
#
#   bash tools/pull-deck-test.sh
set -uo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
SCRIPT="$REPO/tools/pull-deck.sh"
T=${T:-"$HOME/.hermes/cache/scratch/pull-deck-test"}
PASS=0; FAIL=0

ok()   { printf '  ok   %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  FAIL %s\n' "$1"; FAIL=$((FAIL+1)); }
want() { [ "$2" = "$3" ] && ok "$1 ($3)" || bad "$1 (wanted $3, got $2)"; }

rm -rf "$T"; mkdir -p "$T/bin" "$T/local" "$T/failbin" "$T/failrsync"

# --- the ssh stand-in: options, host, then the command joined into one string --
cat > "$T/bin/ssh" <<'SHIM'
#!/usr/bin/env bash
host=""; cmd=()
while [ $# -gt 0 ]; do
  if [ -z "$host" ]; then
    case "$1" in
      -o) shift ;;                 # an option that takes a separate value
      -*) ;;                       # any other option
      *)  host="$1" ;;             # the first non-option is the host
    esac
  else
    cmd+=("$1")                    # everything after the host is the remote command,
  fi                               # including dash-arguments (rsync --server ...)
  shift
done
[ -n "$host" ] || { echo "shim: no host given" >&2; exit 255; }
bash -c "$(printf '%s ' "${cmd[@]}")"
SHIM
# a box that cannot be reached at all
cat > "$T/failbin/ssh" <<'SHIM'
#!/usr/bin/env bash
echo "ssh: connect to host: Connection refused" >&2
exit 255
SHIM
# a box that answers ssh fine but whose remote rsync will not start: the case that
# used to produce a false "identical ✓" from --check
cat > "$T/failrsync/ssh" <<'SHIM'
#!/usr/bin/env bash
host=""; cmd=()
while [ $# -gt 0 ]; do
  if [ -z "$host" ]; then
    case "$1" in -o) shift ;; -*) ;; *) host="$1" ;; esac
  else cmd+=("$1"); fi
  shift
done
case "$(printf '%s ' "${cmd[@]}")" in
  *--server*) echo "simulated: remote rsync failed to start" >&2; exit 255 ;;
esac
bash -c "$(printf '%s ' "${cmd[@]}")"
SHIM
chmod +x "$T/bin/ssh" "$T/failbin/ssh" "$T/failrsync/ssh"

echo "=== 0. the shim reproduces ssh's join-then-parse behaviour ==="
JOINED=$(PATH="$T/bin:$PATH" ssh box echo one two)
want "argv is joined into one string and re-split" "$JOINED" "one two"
QUOTED=$(PATH="$T/bin:$PATH" ssh box "printf '%s' 'a  b'")
want "a quoted string survives as one remote word" "$QUOTED" "a  b"
META=$(PATH="$T/bin:$PATH" ssh box printf '%s|' one two three 2>/dev/null)
[ "$META" != "one|two|three" ] && ok "an unquoted | is still a pipe (shim does not sanitise)" \
  || bad "the shim sanitised an argument, so it would hide real quoting bugs"

echo "=== 1. refuses to run on experimance (the wrong machine) ==="
bash "$SCRIPT" --dry-run >/dev/null 2>&1; want "guard exit code" "$?" "2"

echo "=== 2. box unreachable -> exit 3, names the candidates ==="
OUT=$(PATH="$T/failbin:$PATH" FORCE=1 BOX= bash "$SCRIPT" --dry-run 2>&1); RC=$?
want "exit code" "$RC" "3"
case "$OUT" in *"cannot reach experimance"*) ok "says what it could not reach";; *) bad "message unclear: $OUT";; esac

echo "=== 3. no built deck over there -> exit 4, tells you how to build ==="
OUT=$(PATH="$T/bin:$PATH" FORCE=1 BOX=fakebox REMOTE_BASE=/nonexistent bash "$SCRIPT" --dry-run 2>&1); RC=$?
want "exit code" "$RC" "4"
case "$OUT" in *"build it on the box first"*) ok "points at the build command";; *) bad "message unclear: $OUT";; esac

echo "=== 4. dry run writes nothing, and the fingerprint is real ==="
OUT=$(PATH="$T/bin:$PATH" FORCE=1 BOX=fakebox LOCAL_BASE="$T/local" bash "$SCRIPT" --dry-run 2>&1)
want "dry run exit code" "$?" "0"
case "$OUT" in
  *\(*" files, html "*) ok "size, file count and html hash all read back";;
  *) bad "fingerprint incomplete: $(printf '%s' "$OUT" | grep source)";;
esac
if [ -e "$T/local/out-l01" ]; then bad "dry run created files"; else ok "nothing written"; fi

echo "=== 5. real pull ==="
PATH="$T/bin:$PATH" FORCE=1 BOX=fakebox LOCAL_BASE="$T/local" bash "$SCRIPT" > "$T/pull.log" 2>&1
RC=$?; want "exit code" "$RC" "0"
SRC_N=$(find "$REPO/out-l01" -type f | wc -l); DST_N=$(find "$T/local/out-l01" -type f 2>/dev/null | wc -l)
want "file count matches source" "$DST_N" "$SRC_N"
SRC_H=$(sha256sum "$REPO/out-l01/present/index.html" | cut -c1-12)
DST_H=$(sha256sum "$T/local/out-l01/present/index.html" 2>/dev/null | cut -c1-12)
want "present/index.html hash matches" "$DST_H" "$SRC_H"
grep -q "match ✓" "$T/pull.log" && ok "the script reports the hash match itself" || bad "no hash verdict in output"
grep -q "entries still differing : 0" "$T/pull.log" && ok "verification pass reports an exact mirror" \
  || bad "verification did not report 0 differences"

echo "=== 6. --check on a good copy -> identical ==="
OUT=$(PATH="$T/bin:$PATH" FORCE=1 BOX=fakebox LOCAL_BASE="$T/local" bash "$SCRIPT" --check 2>&1)
case "$OUT" in *"identical to the source, file for file ✓"*) ok "reports identical";; *) bad "unexpected: $OUT";; esac

echo "=== 6b. --check with remote rsync broken -> must NOT claim identical ==="
OUT=$(PATH="$T/failrsync:$PATH" FORCE=1 BOX=fakebox LOCAL_BASE="$T/local" bash "$SCRIPT" --check 2>&1); RC=$?
case "$OUT" in
  *"identical to the source"*) bad "false green: reported identical while rsync could not run";;
  *"rsync could not run"*)     ok "says rsync could not run instead of guessing";;
  *) bad "unexpected: $OUT";;
esac
[ "$RC" != 0 ] && ok "exits non-zero on a failed check ($RC)" || bad "exited 0 on a failed check"

echo "=== 7. negative control: corrupt the copy, --check must notice ==="
printf 'x' >> "$T/local/out-l01/present/index.html"
OUT=$(PATH="$T/bin:$PATH" FORCE=1 BOX=fakebox LOCAL_BASE="$T/local" bash "$SCRIPT" --check 2>&1)
case "$OUT" in *"identical to the source"*) bad "--check passed on a corrupted copy (false green)";;
               *"differences"*) ok "--check catches the corruption (so the check can fail)";; *) bad "unexpected: $OUT";; esac
PATH="$T/bin:$PATH" FORCE=1 BOX=fakebox LOCAL_BASE="$T/local" bash "$SCRIPT" >/dev/null 2>&1
want "a re-run repairs it" "$(sha256sum "$T/local/out-l01/present/index.html" | cut -c1-12)" "$SRC_H"

echo "=== 8. --serve: the recorded pid must actually stop the server ==="
PIDFILE="$HOME/.cache/pull-deck.pid"; rm -f "$PIDFILE"
PORT=8799; while ss -ltn 2>/dev/null | grep -q ":$PORT "; do PORT=$((PORT+1)); done
PATH="$T/bin:$PATH" FORCE=1 BOX=fakebox LOCAL_BASE="$T/local" PORT="$PORT" bash "$SCRIPT" --serve > "$T/serve.log" 2>&1
CODE=$(curl -s --retry 6 --retry-connrefused --retry-delay 1 -m 10 -o /dev/null -w '%{http_code}' "http://localhost:$PORT/out-l01/present/index.html")
want "http status of the served deck" "$CODE" "200"
CODE2=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$PORT/out-l01/document/index.html")
want "http status of the handout view" "$CODE2" "200"
grep -qi "localhost is a secure context" "$T/serve.log" && ok "mentions the localhost secure-context win" || bad "no secure-context note"
SRVPID=$(cat "$PIDFILE" 2>/dev/null)
LIVE=$(ss -ltnp 2>/dev/null | grep ":$PORT " | grep -o 'pid=[0-9]*' | cut -d= -f2 | head -1)
if [ -n "$SRVPID" ] && ps -p "$SRVPID" -o cmd= 2>/dev/null | grep -q "serve-deck.py --port $PORT"; then
  ok "pid file names the real server (pid $SRVPID)"
else
  bad "pid file does not name the server: file='${SRVPID:-empty}', actually listening pid='${LIVE:-none}'"
fi
if [ -n "$SRVPID" ] && kill "$SRVPID" 2>/dev/null; then ok "kill from the pid file terminates it"; else bad "kill from the pid file failed"; fi
for _ in 1 2 3 4 5 6; do ss -ltn 2>/dev/null | grep -q ":$PORT " || break; sleep 0.4; done
ss -ltn 2>/dev/null | grep -q ":$PORT " && bad "port $PORT still bound after the kill" || ok "port $PORT released"
LIVE=$(ss -ltnp 2>/dev/null | grep ":$PORT " | grep -o 'pid=[0-9]*' | cut -d= -f2 | head -1)
[ -n "$LIVE" ] && { kill "$LIVE" 2>/dev/null; printf '  (cleaned up a listener left on %s)\n' "$PORT"; }

echo
printf '=== %d passed, %d failed ===\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ] || exit 1
