#!/usr/bin/env python3
"""The room's waypoint: one word per event, set from the presenter's deck, read by the machines.

    python3 server.py serve --data ./data
    WAYPOINT_TOKEN=... python3 server.py serve --data ./data --port 8472

    GET     <prefix>/<EVENT>   200 and the word (no newline), or 404 if none is set.
                               The header X-Waypoint-Age is the whole seconds since the word was
                               written, counted here so a machine's own clock never matters. The
                               body stays a bare word, so a reader that ignores the header works.
                               No authentication: the word is a bare label such as
                               "expanding", and a machine can only act on it if a line for
                               it exists in that machine's own seed files.
    POST    <prefix>/<EVENT>   Bearer token required. The body is the word, plain text.
                               Written atomically; the last write wins.
    OPTIONS <prefix>/<EVENT>   Preflight for a deck opened from file:// or localhost.

EVENT matches ^[A-Za-z0-9][A-Za-z0-9-]{0,31}$ (workshop-3, W11) and a word matches ^[a-z0-9-]{1,24}$. Anything
else is 400. Design rules, and where each one lives:

- Remote text never reaches an agent. This service stores a word and nothing else; the
  machines look the word up in their own files and use only the fixed text found
  there (see hook/waypoint.sh.in).
- The token comes from the environment (systemd EnvironmentFile), never from a file in
  this repo, is compared in constant time, and is at least MIN_TOKEN characters or the
  server will not start. With no token set the server starts read-only and POST is 503.
- Words live in <data>/<EVENT>.word, one file per event, written to a temporary file in
  the same folder, flushed, then renamed over the old one. Keep the data folder outside
  any web root, so publishing a site can neither overwrite nor delete the words.
- It keeps no IP addresses, request logs or participant data. The log line is the method,
  the path and the status, and nothing else.
- Access-Control-Allow-Origin is not set here: the reverse proxy's site-wide header
  supplies it, and a second copy from this service would make browsers reject the
  response. The preflight answer carries only the methods and headers.

Standard library only. Listens on 127.0.0.1; a reverse proxy in front (Caddy, nginx) does TLS and caps the request
body at 1 KB (the server refuses over MAX_BODY itself, too).
"""

from __future__ import annotations

import argparse
import hmac
import os
import re
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

PREFIX = "/waypoint"
DEFAULT_PORT = 8472
EVENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,31}")
WORD_RE = re.compile(r"[a-z0-9-]{1,24}")
MAX_BODY = 1024
MIN_TOKEN = 20


def valid_event(event: str) -> bool:
    return EVENT_RE.fullmatch(event) is not None


def valid_word(word: str) -> bool:
    return WORD_RE.fullmatch(word) is not None


def word_path(data: Path, event: str) -> Path:
    assert valid_event(event)
    return data / f"{event}.word"


def read_word(data: Path, event: str) -> str | None:
    """The stored word, or None if there is none or the file is not a valid word."""
    try:
        text = word_path(data, event).read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        return None
    return text if valid_word(text) else None


def word_age(data: Path, event: str, now: float | None = None) -> int | None:
    """Whole seconds since the word was written (its file's mtime), or None."""
    import time
    try:
        mtime = word_path(data, event).stat().st_mtime
    except OSError:
        return None
    return max(0, int((time.time() if now is None else now) - mtime))


def write_word(data: Path, event: str, word: str) -> None:
    """Atomic: a reader sees the old word or the new one, never half of one."""
    assert valid_event(event) and valid_word(word)
    fd, tmp = tempfile.mkstemp(dir=data, prefix=f".{event}.", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(word)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, word_path(data, event))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def make_handler(data: Path, token: str, prefix: str = PREFIX):
    class Handler(BaseHTTPRequestHandler):
        server_version = "waypoint"
        sys_version = ""
        # HTTP/1.0: every response closes its connection, so a refused POST never
        # leaves an unread body to be parsed as the next request.

        def log_message(self, fmt, *args):  # method, path, status: no address
            status = args[1] if len(args) > 1 else ""
            sys.stderr.write(f"{self.log_date_time_string()} {self.command} {urlsplit(self.path or '').path} {status}\n")

        def reply(self, status: int, body: str = "", extra: dict | None = None):
            raw = body.encode("ascii", "replace")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Robots-Tag", "noindex, nofollow")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(raw)

        def event(self) -> str | None:
            """The event named by the path, or None after sending the refusal."""
            path = urlsplit(self.path).path
            if not path.startswith(prefix + "/"):
                self.reply(404, "not found")
                return None
            event = path[len(prefix) + 1:]
            if not valid_event(event):
                self.reply(400, "bad event")
                return None
            return event

        def do_GET(self):
            event = self.event()
            if event is None:
                return
            word = read_word(data, event)
            if word is None:
                self.reply(404, "no word set")
            else:
                age = word_age(data, event)
                self.reply(200, word, {} if age is None else {"X-Waypoint-Age": str(age)})

        def do_OPTIONS(self):
            if self.event() is None:
                return
            self.reply(204, "", {
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
                "Access-Control-Max-Age": "600",
            })

        def authorised(self) -> bool:
            header = self.headers.get("Authorization", "")
            scheme, _, given = header.partition(" ")
            if scheme.lower() != "bearer" or not given:
                return False
            # compare_digest on bytes: constant time, and no error on non-ASCII input
            return hmac.compare_digest(given.strip().encode("utf-8", "replace"), token.encode("utf-8"))

        def do_POST(self):
            event = self.event()
            if event is None:
                return
            if not token:
                self.reply(503, "writes are switched off: no token is set")
                return
            if not self.authorised():
                self.reply(401, "token required", {"WWW-Authenticate": "Bearer"})
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self.reply(411, "length required")
                return
            if length < 0 or length > MAX_BODY:
                self.reply(413, "too large")
                return
            word = self.rfile.read(length).decode("utf-8", "replace").strip()
            if not valid_word(word):
                self.reply(400, "bad word")
                return
            try:
                write_word(data, event, word)
            except OSError:
                self.reply(500, "could not write")
                return
            self.reply(200, word)

        def do_PUT(self):
            self.reply(405, "method not allowed", {"Allow": "GET, POST, OPTIONS"})

        do_DELETE = do_PATCH = do_PUT

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the service")
    serve.add_argument("--data", type=Path, required=True, help="folder for the word files (created, mode 700)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--prefix", default=PREFIX)
    args = parser.parse_args()

    token = os.environ.get("WAYPOINT_TOKEN", "").strip()
    if token and len(token) < MIN_TOKEN:
        print(f"WAYPOINT_TOKEN is shorter than {MIN_TOKEN} characters: refusing to start", file=sys.stderr)
        return 2
    args.data.mkdir(mode=0o700, parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.data, token, args.prefix.rstrip("/")))
    server.daemon_threads = True
    print(f"waypoint on {args.host}:{args.port}{args.prefix}  data {args.data}  "
          f"writes {'on' if token else 'OFF (no WAYPOINT_TOKEN)'}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
