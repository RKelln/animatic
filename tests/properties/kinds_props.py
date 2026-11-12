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
  stripped), the frontmatter fields, `## How this runs` from `--home-url`, and
  one `### Exercise <N>: <heading>` section per exercise card in page order (the
  paste text in a fence, then the screen text, spoken text, timer length and
  `(Do: ...)` notes); no content steps; room screens and stage notes absent; it
  warns on a missing `agent:` block, and refuses a local path unless
  `web-allow:` clears it;
- tools/web-export.py --home: exercise cards in place (a `do` screen, a
  `(Do: ...)` note after its screen), a paste box on each whose text matches the
  agent file's (numbered `Exercise N`, kicker "Try it · Exercise N"), Copy buttons on every code block and typed line, the setup card
  from `--agent-url` / `--coding-agent-url`, room screens out, and the plain
  reading copy untouched.
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
URL_HOME = "https://example.org/home/"
AGENT_URL = "https://example.org/agent.md"
CODING_URL = "https://example.org/coding/"


def _export(talk: Path, out: Path, core: Path):
    return subprocess.run(
        [sys.executable, str(REPO / "tools" / "agent-export.py"), str(talk), str(out),
         "--core", str(core), "--page-url", URL_PAGE, "--reading-url", URL_READ,
         "--home-url", URL_HOME],
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
                              f"this whole file, then set up the workshop with them as it says. The workshop page is "
                              f"{URL_PAGE}. The full reading copy is {URL_READ}. The workshop was made and led by "
                              "A. Presenter; the spoken text is in their voice.*\n"):
            err(errors, "kinds: agent export header is wrong")
        if "shared core" in txt or "## Your job\n\nCore line one.\n" not in txt:
            err(errors, "kinds: core not verbatim minus its leading comment")
        for needle in ("## This workshop", "A throwaway talk with content, exercise and room screens.",
                       "## Get the files", "- **Fresh start:** https://example.org/files.zip",
                       "- **Continuing from the room:** A folder holding a notes.txt file."):
            if needle not in txt:
                err(errors, f"kinds: agent export lacks {needle!r}")
        if "### Step" in txt or "## Steps" in txt:
            err(errors, "kinds: agent export still has content steps")
        for needle in ("## How this runs\n\nThe person reads the workshop page at " + URL_HOME +
                       ". When they paste an exercise, run it. Answer questions about anything on "
                       "that page; fetch it if you need to.\n", "## Exercises"):
            if needle not in txt:
                err(errors, f"kinds: agent export lacks {needle!r}")
        heads = re.findall(r"^### (Exercise \d+: .*)$", txt, flags=re.M)
        if heads != ["Exercise 1: First idea", "Exercise 2: Try it"]:
            err(errors, f"kinds: agent exercises {heads}")
        body = txt.split("## Exercises", 1)[1]
        for needle in ("```\nExercise 1: First idea. Ask the person which folder they are in.\n```",
                       "```\nExercise 2: Try it. Spend five minutes on this.\n```",
                       "**Exercise:** Ask the person which folder they are in.",
                       "Say the first idea plainly.", "- open the folder", "- write one line",
                       "Spend five minutes on this.", "(about 5 minutes in the room)"):
            if needle not in body:
                err(errors, f"kinds: agent export lacks {needle!r}")
        for needle in ("Say the second idea.", "Say the third idea.", "Room only",
                       "Ask the room", "(Do:", "[Timer", "<!--", "shot:", "Reading copy:"):
            if needle in txt:
                err(errors, f"kinds: agent export carries {needle!r}")

        # --home-url and --reading-url are optional
        r = subprocess.run([sys.executable, str(REPO / "tools" / "agent-export.py"), str(talk_md),
                            str(tmp / "min.md"), "--core", str(core), "--page-url", URL_PAGE],
                           capture_output=True, text=True)
        mn = (tmp / "min.md").read_text() if r.returncode == 0 else ""
        if r.returncode or "## How this runs" in mn or "reading copy is" in mn or "## Exercises" not in mn:
            err(errors, f"kinds: agent export without home/reading urls: rc {r.returncode}")

        _home(errors, tmp, talk_md, core, txt)

        # no `agent:` block: a warning, not a failure
        bare = tmp / "bare.md"
        bare.write_text(re.sub(r"agent:\n(  .*\n)+", "", talk_md.read_text()))
        r = _export(bare, tmp / "bare-out.md", core)
        if r.returncode or "agent:" not in r.stderr:
            err(errors, f"kinds: missing agent block: rc {r.returncode}, stderr {r.stderr!r}")

        # a local path refuses, unless the talk clears it
        leak = tmp / "leak.md"
        leak.write_text(talk_md.read_text().replace("which folder they are in.",
                                                    "which folder, say /home/someone/notes."))
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
            "Intro spoken line. (Do: Intro do note.)\n")
        (tmp / "kept.section.md").write_text(
            "---\n---\n\n<!-- shot -->\n### Kept\n\nKept section line. (Do: Kept do note.)\n")
        src = (FIX / "screen-kinds.talk.md").read_text()
        head, body = src.split("\n---\n", 1)
        body = body.replace("# Opening\n\nWelcome to the throwaway workshop.\n",
                            "<!-- include: intro.section.md -->\n\n<!-- shot -->\n### Real opening\n\n"
                            "Welcome to the throwaway workshop.\n\n<!-- include: kept.section.md -->\n", 1)
        skip_md = tmp / "skip.md"
        skip_md.write_text(head + "\n---\n" + body)
        r = _export(skip_md, tmp / "skip-out.md", core)
        out = (tmp / "skip-out.md").read_text() if r.returncode == 0 else ""
        if r.returncode or "Intro" in out or "Kept do note" not in out:
            err(errors, "kinds: agent-export: skip section not left out (or a kept section lost)")
        # the home page leaves the skipped section out too; the plain reading copy keeps it
        for flag, want_in in (((), True), (("--home",), False)):
            wr = subprocess.run([sys.executable, str(REPO / "tools" / "web-export.py"), str(skip_md),
                                 str(tmp / f"skipweb{len(flag)}"), *flag], capture_output=True, text=True)
            pg = (tmp / f"skipweb{len(flag)}" / "index.html").read_text() if wr.returncode == 0 else ""
            if wr.returncode or ("Intro spoken line" in pg) != want_in or "Kept section line" not in pg:
                err(errors, f"kinds: skipped section in web export {flag}: rc {wr.returncode}")
        if "Intro do note" in (tmp / "skipweb1" / "index.html").read_text() if (tmp / "skipweb1").exists() else False:
            err(errors, "kinds: skipped section's (Do: ...) card on the home page")
        if re.findall(r"^### (Exercise \d+: .*)$", out, flags=re.M) != [
                "Exercise 1: Kept", "Exercise 2: First idea", "Exercise 3: Try it"]:
            err(errors, "kinds: exercise order or headings with an included section")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _home(errors: list, tmp: Path, talk_md: Path, core: Path, agent_txt: str) -> None:
    """tools/web-export.py --home over a variant of the screen-kinds fixture."""
    import html as htmllib

    src = talk_md.read_text()
    src = src.replace("Say the second idea.",
                      "Say the second idea.\n\n> `Hi.`\n\n```\nprint(\"a < b\")\n```")
    src = src.replace("[Timer: 5:00]", "[Timer: 5:00]\n\n(Do: Run it on Dana, the made-up student.)")
    talk = tmp / "home.md"
    talk.write_text(src)
    exe = str(REPO / "tools" / "web-export.py")

    def run(out, *args):
        return subprocess.run([sys.executable, exe, str(talk), str(out), *args],
                              capture_output=True, text=True)

    plain = tmp / "plain"
    if run(plain).returncode:
        err(errors, "kinds: plain web export failed")
        return
    pl = (plain / "index.html").read_text()
    for needle in ("ex-card", "copy-btn", "Paste this", "<script"):
        if needle in pl:
            err(errors, f"kinds: the plain reading copy carries {needle!r}")

    home = tmp / "home"
    r = run(home, "--home", "--agent-url", AGENT_URL, "--coding-agent-url", CODING_URL)
    if r.returncode:
        err(errors, f"kinds: home export failed: {r.stderr[-300:]}")
        return
    page = (home / "index.html").read_text()
    if "<script src" in page or " src=\"http" in page:
        err(errors, "kinds: home page loads an external script")
    cards = re.findall(r'<aside class="ex-card" id="(ex-[^"]+)".*?<h3 class="ex-title">(.*?)</h3>'
                       r'.*?<pre class="paste-box">(.*?)</pre>', page, flags=re.S)
    ids = [c[0] for c in cards]
    if ids != ["ex-setup", "ex-screen-kinds-002-1", "ex-screen-kinds-004"]:
        err(errors, f"kinds: home cards {ids}")
        return
    want_setup = (f"Read {AGENT_URL} and set up this workshop with me. Ask me before you download, "
                  "install or change anything, one question at a time, in plain words.")
    if htmllib.unescape(cards[0][2]) != want_setup:
        err(errors, f"kinds: setup paste {cards[0][2]!r}")
    if f'<a href="{CODING_URL}">Set one up first.</a>' not in page or "No coding agent yet?" not in page:
        err(errors, "kinds: setup card lacks the coding-agent link")
    if page.index("ex-setup") > page.index('<div class="screen"'):
        err(errors, "kinds: setup card is not before the first screen")
    if "Before you start" not in page or "Set up your agent" not in page:
        err(errors, "kinds: setup card heading")
    # note card after its screen's text, before the next screen
    i = page.index("Say the first idea plainly.")
    j = page.index('id="ex-screen-kinds-002-1"')
    if not i < j < page.index("Say the second idea."):
        err(errors, "kinds: the (Do: ...) card is not right after its screen")
    # the do screen is in place, between the second and third idea, with its text
    k = page.index('id="ex-screen-kinds-004"')
    if not page.index("Say the second idea.") < k < page.index("Say the third idea."):
        err(errors, "kinds: the do screen's card is not in place")
    card = page[k:page.index("</aside>", k)]
    for needle in ("Try it · Exercise 2</p>", ">Try it</h3>", "open the folder", "write one line",
                   "Spend five minutes on this.", "Paste this to your agent:"):
        if needle not in card:
            err(errors, f"kinds: do card lacks {needle!r}")
    if "Room only" in page or "Ask the room" in page or "(Do:" in page:
        err(errors, "kinds: home page carries a room screen or a raw stage note")
    # paste text: the same in the page and the agent file, one card per agent exercise
    res = tmp / "home-agent.md"
    r = _export(talk, res, core)
    atxt = res.read_text() if r.returncode == 0 else ""
    heads = re.findall(r"^### (Exercise \d+: .*)$", atxt, flags=re.M)
    exercise_cards = cards[1:]
    if len(heads) != len(exercise_cards):
        err(errors, f"kinds: {len(exercise_cards)} cards but {len(heads)} agent exercises")
    for (_, _, paste), head in zip(exercise_cards, heads):
        paste = htmllib.unescape(paste)
        if not paste.startswith(head) or f"```\n{paste}\n```" not in atxt:
            err(errors, f"kinds: paste text {paste!r} is not in the agent file under {head!r}")
    if "Exercise 2: Try it. Run it on Dana, the made-up student." not in page:
        err(errors, "kinds: a do screen with a (Do: ...) note pastes the note")
    # copy buttons: every <pre> (code, typed line's box, paste boxes) and typed-line quote
    boxes = len(re.findall(r"<pre\b", page)) + page.count('<blockquote class="type-in">')
    wraps = page.count('<div class="copy-wrap">')
    btns = page.count('<button type="button" class="copy-btn">Copy</button>')
    if not (boxes == wraps == btns >= 5):
        err(errors, f"kinds: copy buttons: {boxes} boxes, {wraps} wraps, {btns} buttons")
    for needle in ("navigator.clipboard.writeText", 'execCommand("copy")', 'aria-live="polite"',
                   'role="status"', "2000"):
        if needle not in page:
            err(errors, f"kinds: copy script lacks {needle!r}")
    if "print(&quot;a &lt; b&quot;)" not in page and 'print("a &lt; b")' not in page:
        err(errors, "kinds: code block text is not escaped in place")
    # no agent-url: no setup card; no agent block: a warning only
    r = run(tmp / "home2", "--home")
    if r.returncode or "ex-setup" in (tmp / "home2" / "index.html").read_text():
        err(errors, "kinds: setup card without --agent-url")
    nob = tmp / "nob.md"
    nob.write_text(re.sub(r"agent:\n(  .*\n)+", "", src))
    r = subprocess.run([sys.executable, exe, str(nob), str(tmp / "home3"), "--home",
                        "--agent-url", AGENT_URL], capture_output=True, text=True)
    if r.returncode or "ex-setup" in (tmp / "home3" / "index.html").read_text() or "agent:" not in r.stderr:
        err(errors, "kinds: home export with no agent block")
    # refusals hold: a local path in a Do note, a non-http URL
    leak = tmp / "homeleak.md"
    leak.write_text(src.replace("Run it on Dana", "Run it from /home/someone/notes on Dana"))
    r = subprocess.run([sys.executable, exe, str(leak), str(tmp / "home4"), "--home"],
                       capture_output=True, text=True)
    if r.returncode != 1:
        err(errors, "kinds: home export did not refuse a local path in a Do note")
    r = run(tmp / "home5", "--home", "--agent-url", "file:///etc/x")
    if r.returncode != 1:
        err(errors, "kinds: home export did not refuse a non-http agent URL")
