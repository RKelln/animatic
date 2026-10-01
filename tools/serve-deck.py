#!/usr/bin/env python3
"""serve-deck.py — static server for a built deck, with HTTP Range support.

`python3 -m http.server` ignores Range: every video request is the whole file
as a 200, so a browser cannot seek, cannot stop reading once it has enough,
and a cancelled preload shows up as ConnectionResetError / NS_BINDING_ABORTED
while the next video waits behind it. This answers Range with 206 (what
Firefox and Chrome expect for <video>) and is otherwise the stock handler.

    python3 tools/serve-deck.py [--port 8787] [--directory DIR] [--bind 127.0.0.1]
"""
import argparse, os, re, sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

RANGE = re.compile(r"bytes=(\d*)-(\d*)$")


class RangeHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send_head(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not rng or os.path.isdir(path) or not os.path.isfile(path):
            return self._plain_head()
        m = RANGE.match(rng.strip())
        size = os.path.getsize(path)
        if not m or (not m.group(1) and not m.group(2)):
            return self._plain_head()
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

    def _plain_head(self):
        self._remaining = None
        f = super().send_head()
        return f

    def end_headers(self):
        if self.command in ("GET", "HEAD") and not self._sent_accept():
            self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def _sent_accept(self):
        return any(b"Accept-Ranges" in h for h in getattr(self, "_headers_buffer", []))

    def copyfile(self, source, outputfile):
        n = getattr(self, "_remaining", None)
        try:
            if n is None:
                super().copyfile(source, outputfile)
                return
            while n > 0:
                buf = source.read(min(n, 1 << 20))
                if not buf:
                    break
                outputfile.write(buf)
                n -= len(buf)
        except (BrokenPipeError, ConnectionResetError):
            pass   # the browser cancelled (preload done, slide changed): not an error

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            pass   # the browser closed an idle or cancelled connection

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--directory", default=".")
    a = ap.parse_args()
    handler = partial(RangeHandler, directory=a.directory)
    srv = ThreadingHTTPServer((a.bind, a.port), handler)
    srv.daemon_threads = True
    print(f"serving {os.path.abspath(a.directory)} on http://{a.bind}:{a.port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
