#!/usr/bin/env python3
"""Export a talkfile as one plain-text markdown file a person's own coding agent
can follow to run the hands-on parts of a workshop at home, beside the home page
(`tools/web-export.py --home`), which carries the content.

    python3 tools/agent-export.py <talk.md> <out.md> --core <core.md> \\
        --page-url <url> [--home-url <url>] [--reading-url <url>]

The file is: a header, the shared core (verbatim, minus its leading HTML
comment), `## This workshop` (goal, practice person, their own), `## Get the
files` (from the talk's frontmatter `agent:` block), `## How this runs` (with
`--home-url`) and `## Exercises`.  There is one `### Exercise <N>: <heading>`
section per exercise card on the home page, in page order, with the same
heading and the same paste text (exercises.py makes both), then the full
instruction text: screen text, spoken text, `(Do: ...)` notes.  A `do` screen is
one card; each `(Do: ...)` note on a content screen is one.  Room screens (`live`)
and sections whose frontmatter says `agent-export: skip` make none.  The content
is not repeated: the page carries it.

Refuses, like web-export, to write a file that names a local filesystem path
(frontmatter `web-allow:` clears a string).  A missing `agent:` block is a
warning, not a failure.  Spec: docs/format-spec-v1.md, "Agent export".
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import exercises  # noqa: E402
import talkparse  # noqa: E402

LOCAL_PATH_RE = re.compile(r"/home/\w+[^\"<\s]*|~/(?:Documents|\.)[^\"<\s]*")
GOAL_FIELDS = ("logline", "summary", "description")


def _strip_leading_comment(text: str) -> str:
    return re.sub(r"\A\s*<!--.*?-->\s*", "", text, count=1, flags=re.S).strip()


def export(talk_path: Path, core_path: Path, page_url: str, reading_url: str = "",
           home_url: str = ""):
    """Return (text, warnings, allowed)."""
    talk = talkparse.build_talk(talk_path)
    meta = talk.meta
    warnings = []
    title = str(meta.get("title") or talk_path.parent.name)
    agent = meta.get("agent") if isinstance(meta.get("agent"), dict) else {}
    if not agent:
        warnings.append("frontmatter has no `agent:` block (start, continue, guide); "
                        "'Get the files' will be empty")
    author = str(agent.get("author") or meta.get("author") or "").strip()
    if not author:
        warnings.append("no `agent.author`: the export cannot say whose voice the spoken text is in")
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
           f"Read this whole file, then set up the workshop with them as it says. The workshop page is {page_url}."
           + (f" The full reading copy is {reading_url}." if reading_url else "")
           + (f" The workshop was made and led by {author}; the spoken text is in their voice.*" if author else "*"), "",
           _strip_leading_comment(core_path.read_text(encoding="utf-8")), "",
           "## This workshop", "", f"**{title}**", ""]
    if goal:
        out += [re.sub(r"\s+", " ", goal), ""]
    for key, label in (("practice", "Practice person"), ("own", "Their own")):
        if str(agent.get(key) or "").strip():
            out.append(f"- **{label}:** " + re.sub(r"\s+", " ", str(agent[key]).strip()))
    if agent.get("practice") or agent.get("own"):
        out.append("")
    out += ["## Get the files", ""]
    for key, label in (("start", "Fresh start"), ("continue", "Continuing from the room"),
                       ("guide", "Guide for the build part")):
        if str(agent.get(key) or "").strip():
            out.append(f"- **{label}:** " + re.sub(r"\s+", " ", str(agent[key]).strip()))
    if not agent:
        out.append("(this workshop has no file instructions)")
    out.append("")
    if home_url:
        out += ["## How this runs", "",
                f"The person reads the workshop page at {home_url}. When they paste an exercise, run it. "
                "Answer questions about anything on that page; fetch it if you need to.", ""]
    out += ["## Exercises", ""]
    for card in exercises.collect(talk, talk_path.parent):
        out += [f"### {card.title}", "", "They paste:", "", "```", card.paste, "```", ""]
        for para in card.instructions():
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
    ap.add_argument("--reading-url", default="", help="optional: the full reading copy")
    ap.add_argument("--home-url", default="", help="where the home page is published")
    ap.add_argument("--allow", action="append", default=[], metavar="TEXT",
                    help="a local-path string cleared to appear (also frontmatter `web-allow:`)")
    a = ap.parse_args()
    text, warnings, allowed = export(Path(a.talkfile).resolve(), Path(a.core),
                                     a.page_url, a.reading_url, a.home_url)
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
    n = len(re.findall(r"^### Exercise \d+: ", text, flags=re.M))
    print(f"agent     : {out} ({n} exercises)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
