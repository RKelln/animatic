"""Screen kinds and the agent export (spec: Screen kinds, Agent export), over
tests/fixtures/constructs/screen-kinds*.talk.md.

- `do` marks an exercise screen, `live` a room screen, no flag content; a
  screen with both is a room screen and check 53 warns;
- cues.json carries `use` (`exercise` / `room`, absent for content) and
  `live_only` for both non-content kinds; the nav map says why a screen is not
  in the document view;
- the present view keeps every screen; the document view, the web export and
  the handout source leave out the exercise and room screens, and a `(Do: ...)`
  note appears in no reading copy, but is in the presenter notes;
- tools/agent-export.py: the header, the core verbatim (leading comment
  stripped), the frontmatter fields, steps in talk order with the reading-copy
  anchors the web export uses, an exercise step for a `do` screen (heading,
  screen text, spoken text, timer length), `(Do: ...)` appended as
  `**Exercise:**`, room screens and stage notes absent; it warns on a missing
  `agent:` block, and refuses a local path unless `web-allow:` clears it.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import build as build_mod
import check as check_mod
import talkparse

from .common import err

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures" / "constructs"
CORE = "<!--\nshared core, leading comment\n-->\n\n## Your job\n\nCore line one.\n"
URL_PAGE = "https://example.org/page/"
URL_READ = "https://example.org/read/"


def _export(talk: Path, out: Path, core: Path):
    return subprocess.run(
        [sys.executable, str(REPO / "tools" / "agent-export.py"), str(talk), str(out),
         "--core", str(core), "--page-url", URL_PAGE, "--reading-url", URL_READ],
        capture_output=True, text=True)


def check(errors: list) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="animatic-kinds-"))
    try:
        talk_md = tmp / "talk.md"
        shutil.copy(FIX / "screen-kinds.talk.md", talk_md)
        t = talkparse.build_talk(talk_md)
        uses = [s.use for s in t.screens]
        if uses != ["content", "content", "content", "exercise", "room", "content"]:
            err(errors, f"kinds: screen uses {uses}")

        # both flags: a room screen, one check-53 warning
        both = tmp / "both.md"
        shutil.copy(FIX / "screen-kinds-warned.talk.md", both)
        tb = talkparse.build_talk(both)
        if [s.use for s in tb.screens][3] != "room":
            err(errors, "kinds: live+do is not a room screen")
        res = check_mod.check_file(both, strict=False, cues_path=None)
        if sum(1 for f in res.findings if f.check == 53) != 1:
            err(errors, "kinds: live+do does not give exactly one check 53 warning")

        # the build
        out = tmp / "out"
        with redirect_stdout(io.StringIO()):
            if build_mod.main([str(talk_md), "--out", str(out)]) != 0:
                err(errors, "kinds: build failed")
                return
        cues = json.loads((out / "cues.json").read_text())["cues"]
        if [c.get("use") for c in cues] != [None, None, None, "exercise", "room", None]:
            err(errors, f"kinds: cues use {[c.get('use') for c in cues]}")
        if [bool(c.get("live_only")) for c in cues] != [False, False, False, True, True, False]:
            err(errors, "kinds: live_only is not set for exactly the exercise and room cues")
        nav = json.loads((out / "nav.json").read_text())
        reasons = [v["document"].get("reason") for v in nav["screens"].values()]
        if reasons[3:5] != ["exercise", "live-only"]:
            err(errors, f"kinds: nav document reasons {reasons}")

        present = (out / "present" / "index.html").read_text()
        doc = (out / "document" / "index.html").read_text()
        for needle in ("Try it", "Room only", "Ask the person which folder"):
            if needle not in present:
                err(errors, f"kinds: present view lacks {needle!r}")
        for needle in ("Try it", "Room only", "Ask the person", "Do:", "write one line"):
            if needle in doc:
                err(errors, f"kinds: document view carries {needle!r}")
        for needle in ("First idea", "Third idea"):
            if needle not in doc:
                err(errors, f"kinds: document view lacks {needle!r}")

        # web export
        web = tmp / "web"
        r = subprocess.run([sys.executable, str(REPO / "tools" / "web-export.py"),
                            str(talk_md), str(web)], capture_output=True, text=True)
        page = (web / "index.html").read_text() if r.returncode == 0 else ""
        if r.returncode or "Try it" in page or "Ask the person" in page:
            err(errors, "kinds: web export failed or carries an exercise screen")

        # agent export
        core = tmp / "core.md"
        core.write_text(CORE)
        res = tmp / "agent.md"
        r = _export(talk_md, res, core)
        if r.returncode or r.stderr.strip():
            err(errors, f"kinds: agent export rc {r.returncode}: {r.stderr[:200]}")
            return
        txt = res.read_text()
        if not txt.startswith("# Screen kinds: run this workshop with your agent\n\n*A guide for a "
                              "coding agent. A person pasted a message that sent you here. Read "
                              f"this whole file, then take them through it. The workshop page is "
                              f"{URL_PAGE}. The full reading copy is {URL_READ}. The workshop was made and led by "
                              "A. Presenter; the steps are in their voice.*\n"):
            err(errors, "kinds: agent export header is wrong")
        if "shared core" in txt or "## Your job\n\nCore line one.\n" not in txt:
            err(errors, "kinds: core not verbatim minus its leading comment")
        for needle in ("## This workshop", "A throwaway talk with content, exercise and room screens.",
                       "## Get the files", "- **Fresh start:** https://example.org/files.zip",
                       "- **Continuing from the room:** A folder holding a notes.txt file.", "## Steps"):
            if needle not in txt:
                err(errors, f"kinds: agent export lacks {needle!r}")
        steps = re.findall(r"^### Step (\d+): (.*)$", txt, flags=re.M)
        if [s[1] for s in steps] != ["Screen kinds", "Warm up", "Exercise: Try it", "Warm up: Third idea"]:
            err(errors, f"kinds: agent steps {steps}")
        body = txt.split("## Steps", 1)[1]
        if "Reading copy: https://example.org/read/#cue-screen-kinds-001" not in body:
            err(errors, "kinds: first step has no reading-copy anchor")
        anchors = re.findall(r"^Reading copy: (\S+)$", body, flags=re.M)
        want = [URL_READ + f"#cue-screen-kinds-{n:03d}" for n in (1, 2, 3, 6)]
        if anchors != want:
            err(errors, f"kinds: anchors {anchors}")
        for a in anchors:
            if a.split("#", 1)[1] not in doc.replace('id="', 'id="') and \
                    f'id="{a.split("#", 1)[1]}"' not in page:
                err(errors, f"kinds: anchor {a} is not an element id in the web export")
        for needle in ("Say the first idea plainly.", "**Exercise:** Ask the person which folder they are in.",
                       "- open the folder", "- write one line", "Spend five minutes on this.",
                       "(about 5 minutes in the room)", "Say the third idea."):
            if needle not in body:
                err(errors, f"kinds: agent export lacks {needle!r}")
        for needle in ("Room only", "Ask the room", "(Do:", "[Timer", "<!--", "shot:"):
            if needle in body:
                err(errors, f"kinds: agent export carries {needle!r}")

        # no `agent:` block: a warning, not a failure
        bare = tmp / "bare.md"
        bare.write_text(re.sub(r"agent:\n(  .*\n)+", "", talk_md.read_text()))
        r = _export(bare, tmp / "bare-out.md", core)
        if r.returncode or "agent:" not in r.stderr:
            err(errors, f"kinds: missing agent block: rc {r.returncode}, stderr {r.stderr!r}")

        # a local path refuses, unless the talk clears it
        leak = tmp / "leak.md"
        leak.write_text(talk_md.read_text().replace("Say the second idea.",
                                                    "Say it from /home/someone/notes."))
        if _export(leak, tmp / "leak-out.md", core).returncode != 1:
            err(errors, "kinds: a local path did not refuse the agent export")
        leak.write_text(leak.read_text().replace("theme: workshop",
                                                 "theme: workshop\nweb-allow: [\"/home/someone\"]"))
        if _export(leak, tmp / "leak-out.md", core).returncode != 0:
            err(errors, "kinds: web-allow did not clear the path")

        # a section whose frontmatter says `agent-export: skip` is left out of the
        # export, and its movement heading does not name the talk's next screen
        (tmp / "intro.section.md").write_text(
            "---\nagent-export: skip\n---\n\n## Intro Person\n<!-- shot -->\n### About me\n\n"
            "Intro spoken line.\n")
        (tmp / "kept.section.md").write_text("---\n---\n\n<!-- shot -->\n### Kept\n\nKept section line.\n")
        src = (FIX / "screen-kinds.talk.md").read_text()
        head, body = src.split("\n---\n", 1)
        body = body.replace("# Opening\n\nWelcome to the throwaway workshop.\n",
                            "<!-- include: intro.section.md -->\n\n<!-- shot -->\n### Real opening\n\n"
                            "Welcome to the throwaway workshop.\n\n<!-- include: kept.section.md -->\n", 1)
        skip_md = tmp / "skip.md"
        skip_md.write_text(head + "\n---\n" + body)
        r = _export(skip_md, tmp / "skip-out.md", core)
        out = (tmp / "skip-out.md").read_text() if r.returncode == 0 else ""
        if r.returncode or "Intro spoken line" in out or "Kept section line" not in out:
            err(errors, "kinds: agent-export: skip section not left out (or a kept section lost)")
        first = re.search(r"^### Step 1: (.*)$", out, flags=re.M)
        if not first or "Intro Person" in first.group(1):
            err(errors, f"kinds: skipped section's heading names step 1: {first.group(1) if first else None}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
