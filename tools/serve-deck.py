#!/usr/bin/env python3
"""serve-deck.py — serve a built deck, with HTTP Range support and a request log
you can read while presenting. No pull, no network beyond localhost.

    python3 tools/serve-deck.py                  # serves the animatic folder on :8787
    python3 tools/serve-deck.py --port 8788 --directory DIR --bind 127.0.0.1 --quiet

`animatic serve DECK --watch` imports this module's make_server() and runs the
same server beside the build watcher in one process, so one command and one
terminal keep a deck building and reachable over the network.

Why not `python3 -m http.server`: it ignores Range, so every video request is the
whole file as a 200 that a browser cannot seek or stop early, and a cancelled
preload shows up as ConnectionResetError / NS_BINDING_ABORTED while the next
video waits behind it. This answers Range with 206, which is what Firefox and
Chrome expect for <video>.

The log, one line per finished request (a `...` line first for anything big, so a
request that hangs is visible while it hangs):

    15:04:50  206  a15-astra-robot-paint.mp4   bytes=0-   1.2 of 70 MB   0.3s   CANCELLED by browser

Flags it raises: CANCELLED (the browser hung up before the end: normal for a
preload it no longer needs, trouble if the video then never plays), SLOW (over
3 s), WHOLE FILE (a video answered 200: the client sent no Range), 404 and 5xx.
"""
import argparse, os, re, sys, threading, time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

RANGE = re.compile(r"bytes=(\d*)-(\d*)$")
MEDIA = (".mp4", ".webm", ".mov", ".m4v", ".ogv")
BIG = 1 << 20          # announce transfers over 1 MB when they start
SLOW_S = 3.0
_lock = threading.Lock()
_color = sys.stdout.isatty()


def paint(code, text):
    return f"\033[{code}m{text}\033[0m" if _color else text


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


class RangeHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    quiet = False

    # -- request bookkeeping -------------------------------------------------

    def _begin(self):
        self._t0 = time.time()
        self._status = "-"
        self._sent = 0
        self._expect = None
        self._aborted = False
        self._announced = False

    def send_response(self, code, message=None):
        self._status = code
        super().send_response(code, message)

    def send_header(self, keyword, value):
        if keyword.lower() == "content-length":
            try:
                self._expect = int(value)
            except ValueError:
                pass
        super().send_header(keyword, value)

    def end_headers(self):
        if self.command in ("GET", "HEAD") and not self._has_header(b"Accept-Ranges"):
            self.send_header("Accept-Ranges", "bytes")
        super().end_headers()
        if (self.command == "GET" and self._expect and self._expect >= BIG
                and not self.quiet):
            self._announced = True
            self._say(f"{paint('2', '        ...')}  {self._name():<34} "
                      f"{self._range_label():<14} {human(self._expect)} starting")

    def _has_header(self, name):
        return any(name in h for h in getattr(self, "_headers_buffer", []))

    def log_request(self, code="-", size="-"):
        pass   # reported by _report() when the transfer has actually finished

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    def _name(self):
        return os.path.basename(self.path.split("?")[0]) or self.path

    def _range_label(self):
        r = self.headers.get("Range")
        return r.replace("bytes=", "bytes=") if r else "(no range)"

    def _say(self, line):
        if self.quiet:
            return
        with _lock:
            print(line, flush=True)

    def _report(self):
        # The reload poll asks for ../_watch.js once a second per open page.  It
        # is not news, and logged it buries the requests that are.
        if self._name() == RELOAD_POLL:
            return
        if self.quiet or self.command not in ("GET", "HEAD") or self._status == "-":
            return
        dt = time.time() - self._t0
        code = self._status
        name = self._name()
        notes = []
        if self._aborted:
            notes.append(paint("33;1", "CANCELLED by browser"))
        if dt > SLOW_S:
            notes.append(paint("33;1", "SLOW"))
        if code == 200 and name.lower().endswith(MEDIA):
            notes.append(paint("33", "WHOLE FILE (no Range sent)"))
        if code == 404:
            notes.append(paint("31;1", "NOT FOUND"))
        if isinstance(code, int) and code >= 500:
            notes.append(paint("31;1", "SERVER ERROR"))
        cs = (paint("32", str(code)) if code in (200, 206, 304)
              else paint("31;1", str(code)))
        if self._expect is not None and self.command == "GET" and code != 304:
            size = f"{human(self._sent)} of {human(self._expect)}"
        else:
            size = ""
        self._say(f"{time.strftime('%H:%M:%S')}  {cs}  {name:<34} "
                  f"{self._range_label():<14} {size:<18} {dt:4.1f}s  {' '.join(notes)}")

    # -- the handlers ----------------------------------------------------------

    def do_GET(self):
        self._begin()
        try:
            super().do_GET()
        finally:
            self._report()

    def do_HEAD(self):
        self._begin()
        try:
            super().do_HEAD()
        finally:
            self._report()

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            pass   # the browser closed an idle or cancelled connection

    def send_head(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        self._remaining = None
        if not rng or os.path.isdir(path) or not os.path.isfile(path):
            return super().send_head()
        m = RANGE.match(rng.strip())
        size = os.path.getsize(path)
        if not m or (not m.group(1) and not m.group(2)):
            return super().send_head()
        if m.group(1):
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
        else:                                   # suffix range: last N bytes
            start = max(0, size - int(m.group(2)))
            end = size - 1
        end = min(end, size - 1)
        if start >= size or start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        f = open(path, "rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        self._remaining = end - start + 1
        return f

    def copyfile(self, source, outputfile):
        n = self._remaining
        try:
            while n is None or n > 0:
                buf = source.read(1 << 20 if n is None else min(n, 1 << 20))
                if not buf:
                    break
                outputfile.write(buf)
                self._sent += len(buf)
                if n is not None:
                    n -= len(buf)
        except (BrokenPipeError, ConnectionResetError):
            self._aborted = True   # the browser hung up mid-transfer


def decks_under(base):
    try:
        return sorted(d for d in os.listdir(base)
                      if os.path.isfile(os.path.join(base, d, "present", "index.html")))
    except OSError:
        return []


LOOPBACK = {"127.0.0.1", "::1", "localhost"}
RELOAD_POLL = "_watch.js"
ANY_ADDR = {"0.0.0.0", "::", ""}


def make_server(bind, port, directory, quiet=False):
    """The threaded Range server for DIRECTORY.  Raises OSError when the address
    is taken, so a caller in the same process can explain it instead of dying.

    Notes the secure-context limit once: getDisplayMedia (window capture) needs
    one, and http on any address but loopback is not one. Slides and video work
    either way."""
    RangeHandler.quiet = quiet
    if bind not in LOOPBACK:
        print(f"note: {bind} is not a secure context — browser window capture "
              f"(getDisplayMedia) is unavailable over it.\n"
              f"      file:// and http://localhost are the two that work "
              f"(docs/live-capture.md).", file=sys.stderr)
    srv = ThreadingHTTPServer((bind, port),
                              partial(RangeHandler, directory=os.path.abspath(directory)))
    srv.daemon_threads = True
    return srv


def bind_failure(err, bind, port):
    print(f"cannot listen on {bind}:{port}: {err}", file=sys.stderr)
    pid = os.path.expanduser("~/.cache/pull-deck.pid")
    if os.path.exists(pid):
        print(f"a server from pull-deck.sh may hold it: kill $(cat {pid})", file=sys.stderr)


def host_for(bind):
    """The address to put in a URL someone else will open."""
    return "localhost" if bind in LOOPBACK or bind in ANY_ADDR else bind


def banner(directory, bind, port, quiet=False, deck=None):
    host = host_for(bind)
    print(f"serving {os.path.abspath(directory)} on http://{host}:{port}   "
          f"(Ctrl-C stops it)")
    decks = decks_under(directory)
    if deck and deck in decks:
        print(f"  {deck}: http://{host}:{port}/{deck}/present/index.html")
        others = [d for d in decks if d != deck]
        if others:
            print(f"  (+{len(others)} other built deck(s) under it)")
    else:
        for d in decks:
            print(f"  {d}: http://{host}:{port}/{d}/present/index.html")
    if not decks:
        print("  no built deck found under it (expected <dir>/out-*/present/index.html)")
    if not quiet:
        print("log: time  status  file  range  sent of total  duration  flags"
              "   (the _watch.js reload poll is not logged)\n", flush=True)


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    default_dir = os.path.dirname(here)         # the animatic folder next to tools/
    ap = argparse.ArgumentParser(description="Serve a built deck with Range support "
                                 "and a live request log.")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--directory", default=default_dir)
    ap.add_argument("--quiet", action="store_true", help="no request log")
    a = ap.parse_args(argv)
    try:
        srv = make_server(a.bind, a.port, a.directory, quiet=a.quiet)
    except OSError as err:
        bind_failure(err, a.bind, a.port)
        sys.exit(2)
    banner(a.directory, a.bind, a.port, quiet=a.quiet)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
