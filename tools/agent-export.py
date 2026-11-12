#!/usr/bin/env python3
"""Export a talkfile as one plain-text markdown file a person's own coding agent
can follow to run the whole workshop at home.

    python3 tools/agent-export.py <talk.md> <out.md> --core <core.md> \\
        --page-url <url> --reading-url <url>

The file is: a header, the shared core (verbatim, minus its leading HTML
comment), `## This workshop`, `## Get the files` (from the talk's frontmatter
`agent:` block) and `## Steps`.  Steps walk the screens in talk order:

- a content screen (no flag) joins the current step; consecutive content screens
  under one movement heading make one step (a long run splits at a screen
  heading, a skipped screen splits it too);
- an exercise screen (`do`) is its own step, `Exercise: <heading>`;
- a room screen (`live`) is skipped;
- a `(Do: ...)` stage note on any screen is appended to its step as
  `**Exercise:** ...`.

Every step carries `Reading copy: <reading-url>#cue-<cue id>`, the same element id
the web export uses.  An exercise step (which the reading copy does not print)
points at the content screen before it.

Refuses, like web-export, to write a file that names a local filesystem path
(frontmatter `web-allow:` clears a string).  A missing `agent:` block is a
warning, not a failure.  Spec: docs/format-spec-v1.md, "Agent export".
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import render  # noqa: E402
import talkparse  # noqa: E402

LOCAL_PATH_RE = re.compile(r"/home/\w+[^\"<\s]*|~/(?:Documents|\.)[^\"<\s]*")
GOAL_FIELDS = ("logline", "summary", "description")
SPLIT_WORDS = 450          # a step longer than this splits at the next screen heading


def _strip_leading_comment(text: str) -> str:
    return re.sub(r"\A\s*<!--.*?-->\s*", "", text, count=1, flags=re.S).strip()


def _screen_body(screen) -> str:
    """The screen's own text for an exercise: list, quote, code, table, stat; the
    heading and any timer token are left out (the heading is the step title)."""
    out = []
    first = screen.first_heading
    for b in screen.blocks:
        if b is first or b.kind in ("heading", "handout-heading", "timer") or b.kind == "vo":
            continue
        text = talkparse.strip_timer_tokens(b.text) if b.timer is not None else b.text
        if b.kind == "list":
            items = [talkparse.strip_timer_tokens(i) if "[" in i else i for i in b.items]
            out.append("\n".join(f"{'1.' if b.ordered else '-'} {i}" for i in items))
        elif b.kind == "code":
            out.append("```\n" + b.text + "\n```")
        elif b.kind in ("quote",):
            if text.strip():
                out.append("\n".join("> " + ln for ln in text.splitlines()))
        elif b.kind == "table":
            rows = ["| " + " | ".join(r) + " |" for r in b.rows]
            if rows:
                out.append("\n".join(rows))
        elif b.kind in ("stat", "paraphrase", "lower", "credits", "quote-source", "print"):
            if b.kind != "print" and text.strip():
                out.append(text.strip())
    return "\n\n".join(x for x in out if x.strip())


def _plain(text: str) -> str:
    return re.sub(r"[ \t]*\n[ \t]*", "\n", text.strip())


def build_steps(talk, reading_url: str) -> list:
    """[{title, anchor, body: [str]}] in talk order."""
    slug = render.deck_slug(talk)
    moves = {m.index: m.title for m in talk.movements}
    base = reading_url.split("#")[0]
    steps: list = []
    cur = None            # the open content step
    last_anchor = None    # the last content screen's anchor
    words = 0
    seen: set = set()

    def anchor(screen):
        return f"{base}#cue-{slug}-{screen.idx:03d}"

    for s in talk.screens:
        if render.is_black_screen(s) or s.room_only:
            cur = None            # a skipped screen ends the run
            continue
        if s.exercise:
            cur = None
            title = render.screen_title(s) or moves.get(s.movement) or "step"
            body = []
            if _screen_body(s):
                body.append(_screen_body(s))
            say = render.screen_script(s)
            if say.strip():
                body.append(_plain(say))
            if s.timer is not None and s.timer_parent is None:
                body.append(f"(about {max(1, round(s.timer[0] / 60))} minutes in the room)")
            body += [f"**Exercise:** {n}" for n in s.do_notes]
            steps.append({"title": f"Exercise: {title}", "anchor": last_anchor, "body": body,
                          "kind": "exercise"})
            continue
        say = render.screen_script(s)
        title = render.screen_title(s)
        if cur is None or cur["movement"] != s.movement or \
                (words >= SPLIT_WORDS and title):
            mt = moves.get(s.movement) or talk.meta.get("title") or "Opening"
            # the movement's later steps are named by their first screen
            label = f"{mt}: {title}" if mt in seen and title else mt
            seen.add(mt)
            if label in seen and label != mt:
                label = f"{label} (continued)"
            seen.add(label)
            cur = {"title": label, "anchor": anchor(s), "body": [], "kind": "content",
                   "movement": s.movement}
            steps.append(cur)
            words = 0
        if say.strip():
            cur["body"].append(_plain(say))
            words += len(say.split())
        cur["body"] += [f"**Exercise:** {n}" for n in s.do_notes]
        last_anchor = anchor(s)
    return [st for st in steps if st["body"] or st["kind"] == "exercise"]


def export(talk_path: Path, core_path: Path, page_url: str, reading_url: str):
    """Return (text, warnings, allowed)."""
    talk = talkparse.build_talk(talk_path)
    meta = talk.meta
    warnings = []
    title = str(meta.get("title") or talk_path.parent.name)
    agent = meta.get("agent") if isinstance(meta.get("agent"), dict) else {}
    if not agent:
        warnings.append("frontmatter has no `agent:` block (start, continue, guide); "
                        "'Get the files' will be empty")
    goal = str(agent.get("goal") or "").strip()
    if not goal:
        for f in GOAL_FIELDS:
            if str(meta.get(f) or "").strip():
                goal = str(meta[f]).strip()
                break
    if not goal:
        warnings.append("no `agent.goal` and no `logline` / `summary` / `description`")

    out = [f"# {title}: run this workshop with your agent", "",
           f"*A guide for a coding agent. A person pasted a message that sent you here. "
           f"Read this whole file, then take them through it. The workshop page is {page_url}. "
           f"The full reading copy is {reading_url}.*", "",
           _strip_leading_comment(core_path.read_text(encoding="utf-8")), "",
           "## This workshop", "", f"**{title}**", ""]
    if goal:
        out += [re.sub(r"\s+", " ", goal), ""]
    out += ["## Get the files", ""]
    for key, label in (("start", "Fresh start"), ("continue", "Continuing from the room"),
                       ("guide", "Guide for the build part")):
        if str(agent.get(key) or "").strip():
            out.append(f"- **{label}:** " + re.sub(r"\s+", " ", str(agent[key]).strip()))
    if not agent:
        out.append("(this workshop has no file instructions)")
    out += ["", "## Steps", ""]
    for n, st in enumerate(build_steps(talk, reading_url), 1):
        out += [f"### Step {n}: {st['title']}", ""]
        if st["anchor"]:
            out += [f"Reading copy: {st['anchor']}", ""]
        for para in st["body"]:
            out += [para, ""]
    text = "\n".join(out).rstrip() + "\n"
    allowed = [str(x) for x in (meta.get("web-allow") or [])]
    return text, warnings, allowed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("talkfile")
    ap.add_argument("out")
    ap.add_argument("--core", required=True, help="the shared core file")
    ap.add_argument("--page-url", required=True)
    ap.add_argument("--reading-url", required=True)
    ap.add_argument("--allow", action="append", default=[], metavar="TEXT",
                    help="a local-path string cleared to appear (also frontmatter `web-allow:`)")
    a = ap.parse_args()
    text, warnings, allowed = export(Path(a.talkfile).resolve(), Path(a.core),
                                     a.page_url, a.reading_url)
    for w in warnings:
        print(f"warn      : {w}", file=sys.stderr)
    bad = [m for m in LOCAL_PATH_RE.findall(text)
           if not any(x in m for x in a.allow + allowed)]
    if bad:
        print("refusing to export:\n  " + "\n  ".join(
            f"local path in file: {m}  (author-cleared? add `web-allow:` to the frontmatter)"
            for m in bad[:10]), file=sys.stderr)
        return 1
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    steps = len(re.findall(r"^### Step ", text, flags=re.M))
    print(f"agent     : {out} ({steps} steps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
