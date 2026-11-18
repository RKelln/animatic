"""The watch stamp and the reload snippet are two things, not one.

`_watch.js` says "a watcher is building here" — `animatic pack` and the
transport scripts read that.  The `<script>` injected into each page is what
actually refreshes an open tab, and it is the default (`--no-reload` opts out).
Turning reload off must not turn the marker off, or a watch build starts looking
like a sealed one.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import build as build_mod

from .common import err


def check(fx, errors: list) -> None:
    if (fx.out / "_watch.js").exists():
        err(errors, "a plain build must not write _watch.js (pack reads it as "
                    "'a watcher is building here')")

    page = fx.out / "present" / "index.html"
    if not page.is_file():
        err(errors, "watch props: no present/index.html in the build")
        return

    tmp = Path(tempfile.mkdtemp()) / "out-x"
    (tmp / "present").mkdir(parents=True)
    shutil.copy(page, tmp / "present" / "index.html")

    build_mod.stamp_watch(tmp, "stamp-one")
    html = (tmp / "present" / "index.html").read_text(encoding="utf-8")
    if "animatic --watch: auto-reload" in html:
        err(errors, "stamp_watch injected the reload snippet: the marker and "
                    "the reload must be separable")
    marker = tmp / "_watch.js"
    if not marker.is_file():
        err(errors, "a watch build must write _watch.js")
    elif "stamp-one" not in marker.read_text(encoding="utf-8"):
        err(errors, "_watch.js must carry the build's stamp")

    build_mod.inject_reload(tmp, "stamp-two")
    html = (tmp / "present" / "index.html").read_text(encoding="utf-8")
    if "animatic --watch: auto-reload" not in html:
        err(errors, "--reload must inject the reload snippet into the pages")
    if "stamp-two" not in marker.read_text(encoding="utf-8"):
        err(errors, "the stamp goes last, so it carries the newest build")

    # Reload is what --watch is for, so it is the default; --no-reload opts out.
    ap = build_mod.parser()
    if not ap.parse_args(["x.md", "--watch"]).reload:
        err(errors, "--watch must reload open pages by default")
    if ap.parse_args(["x.md", "--watch", "--no-reload"]).reload:
        err(errors, "--no-reload must turn the snippet off")
    if not ap.parse_args(["x.md", "--watch", "--reload"]).reload:
        err(errors, "--reload must still read as an explicit yes")
