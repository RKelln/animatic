#!/usr/bin/env python3
"""Serve the repo and open the presenter layout probe.

Why a launcher at all: the probe has to be SERVED, not opened from disk — it
scripts the presenter page in an iframe, and under file:// every document gets
its own opaque origin, so the frame is unreachable (the same constraint that
shapes the presenter itself; see docs/presenter-view.md). This does the three
steps that were easy to get wrong by hand: serve the repo root, check the deck
is actually built, and hand over the right URL.

    python3 tools/presenter-probe.py --deck out-w01
    python3 tools/presenter-probe.py --deck out-w01 --sizes 1280x800,1920x1080
    python3 tools/presenter-probe.py --deck out-l01 --json /tmp/probe.json --open

Exit codes: 0 = served and stopped by the user, 1 = the deck is not built.
The probe itself always exits 0: it is a measuring instrument, and a layout
that fails its checks is a finding, not a crashed script. Read the page, or
window.presenterProbe.results.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import socketserver
import sys
import threading
import webbrowser
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def deck_dir(slug: str) -> Path:
    return REPO / slug


def check_build(slug: str) -> Path | None:
    deck = deck_dir(slug)
    present = deck / "present" / "presenter.html"
    if not present.is_file():
        return deck
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="serve + open the presenter layout probe")
    ap.add_argument("--deck", default="out-w01", help="built deck dir, relative to the repo root")
    ap.add_argument("--port", type=int, default=8790, help="port (0 picks a free one)")
    ap.add_argument("--sizes", default="1280x800,1440x900,1920x1080",
                    help="comma-separated WxH viewports for the iframe")
    ap.add_argument("--open", action="store_true", help="open the probe in the default browser")
    ap.add_argument("--json", metavar="PATH", help="write the probe JSON here when it lands")
    args = ap.parse_args(argv)

    if not (REPO / "build.py").is_file():
        print(f"not a checkout I recognise: {REPO}", file=sys.stderr)
        return 1
    missing = check_build(args.deck)
    if missing is not None:
        print(f"{args.deck}/present/presenter.html is missing — build it first:\n"
              f"  python3 build.py <talkfile> --out {args.deck}", file=sys.stderr)
        return 1

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(REPO), **kw)

        def end_headers(self):
            # a probe that measures a stale page is worse than no probe
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, fmt, *a):  # keep the console readable
            pass

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", args.port), Handler) as httpd:
        port = httpd.server_address[1]
        url = (f"http://127.0.0.1:{port}/tools/presenter-probe.html"
               f"?deck={args.deck}&sizes={args.sizes}")
        print(f"probe: {url}")
        print(f"serving {REPO} (deck: {args.deck}) — Ctrl+C to stop")
        if args.json:
            print(f"note: --json expects the JSON to be pasted/copied back; "
                  f"the probe writes it to the console and to window.presenterProbe.results")
        if args.open:
            threading.Timer(0.4, functools.partial(webbrowser.open, url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
