#!/usr/bin/env python3
"""Browser clip check for the specimen decks (examples/specimens/*/talk.md).

Builds every specimen deck in every theme, loads the present view in headless
Chromium at a few real window shapes, and fails on any slide whose text does
not fit:
  - data-fit="floor": the pager shrank the text to its floor and it still
    overflows (the slide is clipped), or
  - a line of screen text, or a list's bullet, outside the slide's safe area
    (1.5% in from each edge): text the fitter did not see, run into the frame.

One page load per deck, theme and size: the pager fits every slide at load,
hidden ones included, so a probe reads them all at once.

    python3 tests/browser_specimens.py            # all decks, both themes, all sizes
    python3 tests/browser_specimens.py -v         # list every slide checked
    python3 tests/browser_specimens.py DECK ...   # your own decks instead, in their own theme

Exit 0 clean, 1 on a clipped slide, 77 when no chromium is installed. Run it
after touching themes/ or the pager's fitting (render.py); a new feature gets a
screen in a specimen deck first (AGENTS.md), so this checks it too.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPECIMENS = ROOT / "examples" / "specimens"
THEMES = ("lecture", "workshop")
# a 1080p projector, a 720p one, a 16:10 laptop and a 4:3 projector
SIZES = ((1920, 1080), (1280, 720), (1280, 800), (1024, 768))
SAFE = 0.015

PROBE = r"""
<script>
setTimeout(function () {
  var out = [];
  var slides = document.querySelectorAll("section.animatic-slide");
  for (var i = 0; i < slides.length; i++) {
    var sl = slides[i], body = sl.querySelector(".screen-body");
    var r = sl.getBoundingClientRect();
    var mx = r.width * SAFE_, my = r.height * SAFE_;
    var L = r.left + mx, R = r.right - mx, T = r.top + my, B = r.bottom - my;
    var bad = [];
    if (sl.getAttribute("data-fit") === "floor") bad.push("clipped at the fit floor");
    if (body) {
      var w = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, null), n, range = document.createRange();
      while ((n = w.nextNode()) && bad.length < 4) {
        if (!/\S/.test(n.nodeValue)) continue;
        var el = n.parentElement;
        // text the slide hides on purpose (a reveal step not shown yet) still
        // takes its space, so it is checked like any other
        if (!el || getComputedStyle(el).display === "none") continue;
        range.selectNodeContents(n);
        var rs = range.getClientRects();
        for (var k = 0; k < rs.length; k++) {
          var q = rs[k];
          if (q.width < 1) continue;
          if (q.left < L - 0.5 || q.right > R + 0.5 || q.top < T - 0.5 || q.bottom > B + 0.5) {
            bad.push("text outside the safe area: \"" + n.nodeValue.trim().slice(0, 40) + "\"");
            break;
          }
        }
      }
      // a bullet sits in its list's indent, outside every text box: an item
      // whose marker would start left of the safe area
      var lis = body.querySelectorAll("li");
      for (var j = 0; j < lis.length && bad.length < 4; j++) {
        var li = lis[j], lr = li.getBoundingClientRect();
        if (getComputedStyle(li.parentElement).listStyleType === "none") continue;
        if (li.closest("[data-cols]")) continue;   // cols checks its own cells
        var fs = parseFloat(getComputedStyle(li).fontSize) || 16;
        if (lr.width && lr.left - fs * 0.8 < L - 0.5) { bad.push("bullet outside the safe area"); break; }
      }
    }
    out.push({id: sl.id, n: i + 1, fit: sl.getAttribute("data-fit"), bad: bad});
  }
  var pre = document.createElement("pre");
  pre.id = "clip-probe";
  pre.textContent = JSON.stringify(out);
  document.body.appendChild(pre);
}, 2500);
</script>
""".replace("SAFE_", str(SAFE))


def chromium_path() -> str | None:
    return shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")


def probe(chromium: str, page: Path, w: int, h: int) -> list[dict] | None:
    proc = subprocess.run(
        [chromium, "--headless=new", "--no-sandbox", "--disable-gpu", "--mute-audio",
         f"--window-size={w},{h}", "--virtual-time-budget=5000", "--dump-dom", page.as_uri()],
        capture_output=True, text=True, timeout=180)
    m = re.search(r'<pre id="clip-probe">(.*?)</pre>', proc.stdout, re.DOTALL)
    if not m:
        return None
    import html
    return json.loads(html.unescape(m.group(1)))


def main() -> int:
    args = sys.argv[1:]
    verbose = "-v" in args
    given = [Path(a) for a in args if a != "-v"]
    chromium = chromium_path()
    if not chromium:
        print("skip: chromium not found")
        return 77
    decks = [(d / "talk.md" if d.is_dir() else d).resolve() for d in given] or sorted(SPECIMENS.glob("*/talk.md"))
    if not decks:
        print("FAIL: no specimen decks under examples/specimens/")
        return 1
    # snap chromium reads only under $HOME: build inside the repo
    work = Path(tempfile.mkdtemp(prefix="specimen-clip-", dir=ROOT))
    failures = 0
    try:
        for deck in decks:
            for theme in (THEMES if not given else (None,)):
                out = work / f"{deck.parent.name}-{theme or 'own'}"
                cmd = [sys.executable, str(ROOT / "build.py"), str(deck), "--out", str(out), "-q"]
                b = subprocess.run(cmd + (["--theme", theme] if theme else []), capture_output=True, text=True)
                if b.returncode != 0:
                    print(f"FAIL  {deck.parent.name} {theme}: build failed\n{b.stdout}{b.stderr}")
                    failures += 1
                    continue
                cues = {c["id"]: c for c in json.loads((out / "cues.json").read_text())["cues"]}
                page = out / "present" / "index.html"
                page.write_text(page.read_text().replace("</body>", PROBE + "</body>"))
                for w, h in SIZES:
                    rows = probe(chromium, page, w, h)
                    tag = f"{deck.parent.name} {theme or 'own theme'} {w}x{h}"
                    if rows is None:
                        print(f"FAIL  {tag}: the probe never reported")
                        failures += 1
                        continue
                    bad = [r for r in rows if r["bad"]]
                    for r in bad:
                        title = (cues.get(r["id"], {}).get("title") or "").strip() or r["id"]
                        print(f"FAIL  {tag}  slide {r['n']} ({title}): " + "; ".join(r["bad"]))
                    failures += len(bad)
                    if not bad:
                        print(f"ok    {tag}: {len(rows)} slides")
                    if verbose:
                        for r in rows:
                            print(f"        {r['n']:3d} fit={r['fit']}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{'FAIL' if failures else 'PASS'}: {failures} clipped slide(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
