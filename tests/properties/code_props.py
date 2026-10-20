"""Property checks for fenced code blocks (spec: Text, "Fenced code").

A fenced block is screen text that shows its lines verbatim.  For every
fixture that has fences these hold, independent of the goldens:

- the cue's `screen_text` carries one `code` entry per non-empty fence, in
  source order, with the lines exactly as written;
- no fenced line leaks into the voice-over (`script`) or the clock: a cue's
  `est_seconds` is what its script words alone would give (media-free cards);
- the document view and the present view each show every fence once, as a
  `<pre class="code-block">`;
- nothing inside a fence became a list, heading, comment, table or quote node
  (cues or HTML), and no raw `<!--` from inside a fence reaches either view.
"""

from __future__ import annotations

import html as html_mod
import re

import talkparse
import timing

from .common import err

MARKER_RE = re.compile(r"^(?:#{1,6}|[-*+>]|\d+[.)]|\|)\s*")


def _bare(line: str) -> str:
    """A fenced line without its markdown marker: what a node built from it
    would carry as text."""
    return MARKER_RE.sub("", line.strip()).strip()


PRE_RE = re.compile(r'<pre class="code-block">(.*?)</pre>', re.DOTALL)
SPAN_RE = re.compile(r'<span class="cl"[^>]*>(.*?)</span>', re.DOTALL)


def _pre_text(inner: str) -> str:
    """The text of a <pre> block: its line spans, each ending in a newline
    (kept exactly, so copy/paste is the source's lines)."""
    spans = SPAN_RE.findall(inner)
    return "".join(html_mod.unescape(x) for x in spans)[:-1]


def _fences(source_text: str) -> list:
    """[(lines, closed)] for every fence in the body, source order."""
    _, rest = talkparse._lex_frontmatter(source_text, "<fixture>")
    out = []
    for i, f in sorted(talkparse.find_fences(rest).items()):
        b0, b1 = f["body"]
        out.append(([rest[k] for k in range(b0, b1)], f["closed"]))
    return out


def check(fx, errors: list) -> None:
    fences = _fences(fx.source_text)
    if not fences:
        return
    shown = [lines for lines, _ in fences if "\n".join(lines).strip()]
    cues = fx.cues()

    # -- cues: one code entry per non-empty fence, verbatim, in order ----------
    got = [t["text"] for c in cues["cues"] for t in (c.get("screen_text") or [])
           if t.get("kind") == "code"]
    want = ["\n".join(lines) for lines in shown]
    if got != want:
        err(errors, f"cues: code entries {got!r} != the fences' lines {want!r}")

    fence_lines = {ln.strip() for lines in shown for ln in lines if len(ln.strip()) >= 6}
    for c in cues["cues"]:
        script = c.get("script") or ""
        for ln in fence_lines:
            if ln in script:
                err(errors, f"cue {c['id']}: fenced line leaked into the script: {ln[:50]!r}")
        # nothing inside a fence became another kind of node
        for t in c.get("screen_text") or []:
            if t.get("kind") in ("heading", "quote", "table", "paraphrase"):
                text = t.get("text") or " ".join(" ".join(r) for r in t.get("rows", []))
                for ln in fence_lines:
                    if text.strip() and _bare(ln) == text.strip():
                        err(errors, f"cue {c['id']}: fenced line became a {t['kind']}: {ln[:50]!r}")
            if t.get("kind") == "list":
                for it in t["items"]:
                    if any(it.strip() and it.strip() == _bare(ln) for ln in fence_lines):
                        err(errors, f"cue {c['id']}: fenced line became a list item: {it[:50]!r}")
        # the clock: media-free cards with no stage notes are timed by the
        # script alone, so fenced words never add to the estimate
        if (c.get("media") is None and not c.get("stage") and c["kind"] in ("card", "stat")
                and "timer" not in c):   # a timer screen's clock is timer_props' rule
            want_s = round(timing.estimate_seconds(
                timing.word_count(script), c["kind"]), 3)
            if abs(c["est_seconds"] - want_s) > 5e-4:
                err(errors, f"cue {c['id']}: est_seconds {c['est_seconds']} counts "
                            f"fenced text (script alone gives {want_s})")
    if len(cues["cues"]) != len({c["id"] for c in cues["cues"]}):
        err(errors, "cues: duplicate ids")

    # -- views: each fence once, as a <pre>; no live nodes from inside ---------
    # The present view carries a fenced block twice when the screen has no
    # script: once on the slide, once in the notes as the reading copy (spec:
    # Text — The reading copy).  The handout prints it once, like the slide.
    want_present = []
    for c in cues["cues"]:
        codes = [t["text"] for t in (c.get("screen_text") or [])
                 if t.get("kind") == "code"]
        want_present.extend(codes)
        if not (c.get("script") or "").strip():
            want_present.extend(codes)
    for view, path, expect in (("document", fx.out / "document" / "index.html", want),
                               ("present", fx.out / "present" / "index.html", want_present)):
        if not path.exists():
            err(errors, f"{view} view missing")
            continue
        text = path.read_text(encoding="utf-8")
        pres = [_pre_text(m) for m in PRE_RE.findall(text)]
        if pres != expect:
            err(errors, f"{view} view: <pre> blocks {pres!r} != fences {expect!r}")
        for lines in shown:
            for ln in lines:
                if "<!--" in ln and ln in text:
                    err(errors, f"{view} view: raw comment from a fence reaches the HTML: {ln[:50]!r}")
        # strip the pre blocks: what is left must hold no fenced line as a node
        rest = PRE_RE.sub("", text)
        for ln in fence_lines:
            esc = html_mod.escape(ln, quote=False)
            esc = html_mod.escape(_bare(ln), quote=False)
            if esc and re.search(r"<(?:li|h[1-6]|td|th|blockquote|p)[^>]*>\s*" + re.escape(esc) + r"\s*<", rest):
                err(errors, f"{view} view: fenced line became a node: {ln[:50]!r}")
