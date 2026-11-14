#!/usr/bin/env python3
"""Export a talkfile's document view as a self-contained web page: one folder
holding index.html and the web-sized images it uses, ready to drop on a static
site (Hugo `static/`, GitHub Pages, any file server).

    python3 tools/web-export.py <talkfile> <out-dir> [--work DIR]
    python3 tools/web-export.py --home <talkfile> <out-dir> [--agent-url URL] [--coding-agent-url URL]
    either form takes [--back-url URL] [--back-label TEXT]: a link back to the event page,
    at the top and the foot of the page.  Every page gets a "Top" button.

`--home` writes the home version: the page a person reads while their own coding
agent does the hands-on parts.  Exercise screens (`do`) print in place like content
screens, `(Do: ...)` notes never print; every code block and typed line gets a
Copy button; with an `agent:` block and `--agent-url` a setup card leads the
page.  Room screens stay out.  Spec: format-spec-v1.md, "Home page".

The folder is `index.html` plus `media/*.jpg`; every link in the page is
relative, so it works under any URL prefix.  Nothing else from the build ships:
no present or presenter view, no cues.json, no originals.  Refuses to ship a
page that points outside its own folder or names a local path.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html import escape
from html import unescape as html_unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import talkparse  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MEDIA_PREFIX = "../_media/doc/"

SETUP_LINE = ("Copy this into your coding agent to start. Further down, every grey box with a "
              "Copy button is something to paste into your agent when you reach it.")
SETUP_PASTE = ("Read {url} and set up this workshop with me. Ask me before you download, "
               "install or change anything, one question at a time, in plain words.")

NAV_CSS = """<style>
.doc-back { margin: 0 0 0.8em; font-size: 0.95rem; }
.doc-back a, .doc-foot a { color: var(--doc-accent); }
.doc-foot { margin: 3em 0 1em; padding-top: 1em; border-top: 1px solid var(--doc-line, var(--doc-muted));
  display: flex; gap: 1.5em; flex-wrap: wrap; font-size: 0.95rem; }
.to-top { position: fixed; right: 1rem; bottom: 1rem; z-index: 10; padding: 0.45em 0.9em;
  font-size: 0.9rem; font-weight: 600; text-decoration: none; color: var(--doc-bg);
  background: var(--doc-accent); border-radius: 0.4em; opacity: 0.85; }
.to-top:hover, .to-top:focus-visible { opacity: 1; }
.to-top:focus-visible { outline: 3px solid var(--doc-ink); outline-offset: 2px; }
@media print { .doc-back, .doc-foot, .to-top { display: none; } }
</style>
"""


def add_nav(html: str, back_url: str, back_label: str) -> str:
    """A link back to the event page (top and foot) and a fixed Top button."""
    back = (f'<a href="{escape(back_url, quote=True)}">&larr; {escape(back_label, quote=False)}</a>'
            if back_url else "")
    html = html.replace("</head>", NAV_CSS + "</head>", 1)
    if back:
        html = html.replace('<header class="doc-head">',
                            f'<header class="doc-head"><p class="doc-back">{back}</p>', 1)
    foot = (f'<p class="doc-foot"><a href="#top">&uarr; Back to the top</a>{back}</p>')
    html = html.replace("</article>", foot + "</article>", 1)
    return html.replace("</body>", '<a class="to-top" href="#top" aria-label="Back to the top">'
                        '&uarr; Top</a>\n</body>', 1)


HOME_CSS = """<style>
.ex-card { margin: 1.8em 0; padding: 0.2em 1.1em 1.1em; border: 2px solid var(--doc-accent);
  border-radius: 0.6em; background: var(--doc-callout-bg); color: var(--doc-ink); }
.ex-kicker { margin: 0.9em 0 0; font-size: 0.8rem; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--doc-accent); }
.ex-title { margin: 0.2em 0 0.6em; font-size: 1.3rem; }
.ex-paste { margin-top: 0.8em; }
.ex-card .copy-wrap pre, .ex-card .copy-wrap blockquote { background: var(--doc-bg); }
pre.paste-box { margin: 0; padding: 0.8em 1em; font-family: var(--font-mono, monospace);
  font-size: 0.9rem; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere;
  color: var(--doc-ink); background: var(--doc-bg); border: 1px solid var(--doc-muted);
  border-radius: 0.4em; }
.copy-wrap { position: relative; margin: 1.2em 0; }
.ex-card .copy-wrap { margin: 0; }
.copy-wrap > pre, .copy-wrap > blockquote { margin: 0; }
/* The button sits inside the box, at its right edge; the text keeps clear of it. */
.js .copy-wrap > pre, .js .copy-wrap > blockquote { padding-right: 6.2em; }
.copy-btn { display: none; position: absolute; top: 0.4em; right: 0.4em; min-height: 0;
  padding: 0.3em 1em; font: inherit; font-size: 0.9rem; line-height: 1.5; font-weight: 600; color: var(--doc-bg);
  background: var(--doc-accent); border: 0; border-radius: 0.4em; cursor: pointer; }
.copy-wrap > blockquote + .copy-btn { top: 50%; transform: translateY(-50%); }
.js .copy-btn { display: inline-block; }
/* The next box to copy: a gentle pulse, moved along each time a box is copied. */
@keyframes copy-next { 0%, 100% { box-shadow: 0 0 0 0 transparent; }
  50% { box-shadow: 0 0 0 4px var(--doc-accent); } }
.copy-wrap.next-up > pre, .copy-wrap.next-up > blockquote { animation: copy-next 1.8s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .copy-wrap.next-up > pre, .copy-wrap.next-up > blockquote { animation: none;
    box-shadow: 0 0 0 3px var(--doc-accent); } }
.copy-btn:focus-visible { outline: 3px solid var(--doc-ink); outline-offset: 2px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
@media (max-width: 30rem) { .ex-card { padding: 0.1em 0.8em 0.9em; } }
</style>
"""

HOME_JS = """<div id="copy-status" class="sr-only" role="status" aria-live="polite"></div>
<script>
(function () {
  document.documentElement.className += " js";
  var live = document.getElementById("copy-status");
  function fallback(el) {
    var ok = false;
    try {
      var r = document.createRange(); r.selectNodeContents(el);
      var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
      ok = document.execCommand("copy");
    } catch (e) {}
    return ok;
  }
  function done(btn, ok) {
    btn.textContent = ok ? "Copied" : "Press Ctrl+C to copy";
    live.textContent = ok ? "Copied to clipboard" : "Text selected. Press Control C to copy.";
    clearTimeout(btn._t);
    btn._t = setTimeout(function () { btn.textContent = "Copy"; live.textContent = ""; }, 2000);
  }
  var wraps = Array.prototype.slice.call(document.querySelectorAll(".copy-wrap"));
  function nextUp(i) {
    wraps.forEach(function (w) { w.classList.remove("next-up"); });
    if (i >= 0 && i < wraps.length) wraps[i].classList.add("next-up");
  }
  nextUp(0);
  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest(".copy-btn") : null;
    if (!btn) return;
    nextUp(wraps.indexOf(btn.parentNode) + 1);
    var src = btn.parentNode.firstElementChild;
    var text = src.textContent.replace(/\\s+$/, "");
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done(btn, true); },
        function () { done(btn, fallback(src)); });
    } else {
      done(btn, fallback(src));
    }
  });
})();
</script>
"""


def add_copy_buttons(html: str) -> str:
    """Wrap every <pre> and typed-line quote with a Copy button that sits inside the box, at its right edge."""
    btn = '<button type="button" class="copy-btn">Copy</button>'
    html = re.sub(r"<pre\b[^>]*>.*?</pre>", lambda m: f'<div class="copy-wrap">{m.group(0)}{btn}</div>',
                  html, flags=re.S)
    return re.sub(r'<blockquote class="type-in">.*?</blockquote>',
                  lambda m: f'<div class="copy-wrap">{m.group(0)}{btn}</div>', html, flags=re.S)


def setup_card(agent_url: str, coding_agent_url: str) -> str:
    paste = escape(SETUP_PASTE.format(url=agent_url), quote=False)
    more = (f'<p>No coding agent yet? <a href="{escape(coding_agent_url, quote=True)}">'
            f'Set one up first.</a></p>' if coding_agent_url else "")
    return ('<aside class="ex-card" id="ex-setup" aria-label="Before you start: set up your agent">'
            '<p class="ex-kicker">Before you start</p><h3 class="ex-title">Set up your agent</h3>'
            f'<p>{SETUP_LINE}</p>'
            '<div class="ex-paste">'
            f'<pre class="paste-box">{paste}</pre></div>{more}</aside>')


def web_videos(html: str, work: Path) -> tuple[str, dict]:
    """Frontmatter `web-video: true`: each video figure's still becomes a
    click-to-play web copy (webvideo.py), the still its poster. It loops once
    started; a card without `sound: true` plays muted. A card with
    `web-video: false` keeps its still. Returns the page and {name: cached file}."""
    import webvideo
    manifest = json.loads((work / "media-manifest.json").read_text(encoding="utf-8"))
    media = {e["slug"]: e["media"] for e in manifest["referenced"]}
    files = {}

    def swap(m: re.Match) -> str:
        slug, fig = html_unescape(m.group(1)), m.group(0)
        info = media.get(slug) or {}
        f = info.get("file") or ""
        if info.get("live") or info.get("web_video") is False or Path(f).suffix.lower() not in webvideo.VIDEO_EXTS:
            return fig
        src = Path(f) if Path(f).is_absolute() else work / f
        got = webvideo.web_copy(src, bool(info.get("sound")))
        img = re.search(r'<img class="figure-media media-image" src="(media/[^"]+)" alt="([^"]*)"[^>]*>', fig)
        if not got or not img:
            print(f"warn      : {slug}: no web copy; the page keeps the still", file=sys.stderr)
            return fig
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", slug) + ".mp4"
        files[name] = got
        muted = "" if info.get("sound") else " muted"
        video = (f'<video class="figure-media media-video" src="media/{name}" poster="{img.group(1)}" '
                 f'controls loop playsinline preload="none"{muted} aria-label="{img.group(2)}"></video>')
        return fig.replace(img.group(0), video, 1)

    html = re.sub(r'<figure class="shot" data-slug="([^"]+)">.*?</figure>', swap, html, flags=re.S)
    return html, files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("talkfile")
    ap.add_argument("out")
    ap.add_argument("--work", help="build directory (default: a temporary one)")
    ap.add_argument("--allow", action="append", default=[], metavar="TEXT",
                    help="a local-path string the author has cleared to appear in the page "
                         "(also frontmatter `web-allow:`, a list)")
    ap.add_argument("--home", action="store_true",
                    help="the home version: exercise cards, Copy buttons, an optional setup card")
    ap.add_argument("--agent-url", help="with --home: the agent file; adds the setup card")
    ap.add_argument("--coding-agent-url", help="with --home: where to get a coding agent")
    ap.add_argument("--back-url", help="the event page: a link back to it, top and foot")
    ap.add_argument("--back-label", default="Back to the workshop page")
    a = ap.parse_args()
    if a.back_url and not a.back_url.startswith(("http://", "https://", "/")):
        print(f"refusing to export: --back-url is not an http(s) URL or a site path: {a.back_url}", file=sys.stderr)
        return 1
    for u in (a.agent_url, a.coding_agent_url):
        if u and not u.startswith(("http://", "https://")):
            print(f"refusing to export: not an http(s) URL: {u}", file=sys.stderr)
            return 1
    talk = Path(a.talkfile).resolve()
    out = Path(a.out).resolve()
    work = Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix="animatic-web-"))
    r = subprocess.run([sys.executable, str(ROOT / "build.py"), str(talk), "--out", str(work),
                        "--no-handout-placeholders"] + (["--home-page"] if a.home else []), stdout=subprocess.DEVNULL,
                       env={k: v for k, v in os.environ.items() if k != "ANIMATIC_WAYPOINT_TOKEN"})
    if r.returncode:
        return r.returncode
    html = (work / "document" / "index.html").read_text(encoding="utf-8")

    used = sorted(set(re.findall(re.escape(MEDIA_PREFIX) + r"([^\"')\s]+)", html)))
    html = html.replace(MEDIA_PREFIX, "media/")

    meta = talkparse.build_talk(talk).meta
    videos = {}
    if str(meta.get("web-video", "")).strip().lower() in ("true", "yes", "on", "1"):
        html, videos = web_videos(html, work)
    title = escape(str(meta.get("title", "")), quote=True)
    desc = escape(str(meta.get("logline", "")), quote=True)
    head = ""
    if desc:
        head += f'<meta name="description" content="{desc}">\n'
    head += f'<meta property="og:title" content="{title}">\n'
    if desc:
        head += f'<meta property="og:description" content="{desc}">\n'
    html = re.sub(r"(</title>\n?)", r"\1" + head.replace("\\", "\\\\"), html, count=1)

    if a.home:
        html = html.replace("</head>", HOME_CSS + "</head>", 1)
        if meta.get("agent") and a.agent_url:
            html = re.sub(r'<section class="(?:opening|movement)"',
                          lambda m: setup_card(a.agent_url, a.coding_agent_url or "") + m.group(0),
                          html, count=1)
        elif a.agent_url:
            print("warn      : no `agent:` block in the frontmatter; no setup card", file=sys.stderr)
        html = add_copy_buttons(html).replace("</body>", HOME_JS + "</body>", 1)

    if "</article>" not in html or '<header class="doc-head">' not in html:
        print("warn      : page layout changed; no back links added", file=sys.stderr)
    html = add_nav(html, a.back_url or "", a.back_label)

    allowed = list(a.allow) + [str(x) for x in (meta.get("web-allow") or [])]
    problems = []
    for ref in re.findall(r'(?:src|href)="([^"#][^"]*)"', html):
        if ref.startswith(("http://", "https://", "mailto:", "data:", "media/")):
            continue
        if a.back_url and ref == escape(a.back_url, quote=True):
            continue    # the author's own link back to the event page
        problems.append(f"link leaves the folder: {ref}")
    for leak in re.findall(r"/home/\w+[^\"<\s]*|~/(?:Documents|\.)[^\"<\s]*", html):
        if not any(x in leak for x in allowed):
            problems.append(f"local path in page: {leak}  (author-cleared? add `web-allow:` to the frontmatter)")
    if problems:
        print("refusing to export:\n  " + "\n  ".join(problems[:10]), file=sys.stderr)
        return 1

    if out.exists():
        shutil.rmtree(out)
    (out / "media").mkdir(parents=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    for name in used:
        shutil.copy2(work / "_media" / "doc" / name, out / "media" / name)
    for name, src in videos.items():
        shutil.copy2(src, out / "media" / name)
        (out / "media" / name).chmod(0o644)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"web       : {out} ({len(used)} images, {len(videos)} videos, {size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
