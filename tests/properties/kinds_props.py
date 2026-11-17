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
  `## The hands-on parts`: one `### <N>. <heading>` per `do` screen or `(Do: ...)`
  note in page order (Do note, screen text, spoken text, timer length); no
  content steps; room screens absent; it warns on a missing `agent:` block, and
  refuses a local path unless `web-allow:` clears it;
- tools/web-export.py --home: `do` screens print in place like content screens
  (their typed prompts get Copy buttons), `(Do: ...)` notes never print, every
  code block and typed line has a Copy button, the setup card comes from
  `--agent-url` / `--coding-agent-url`, room screens and `agent-export: skip`
  sections are out, and the plain reading copy is untouched.
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

        # section numbers skip room-only sections (a Break): no gaps in print
        secs = tmp / "secs.md"
        secs.write_text(
            '---\ntitle: "Sections"\n---\n<!-- shot -->\n\n# Sections\n\nHello.\n\n## One\n\n<!-- shot -->\n### A\nSaid.\n\n'
            '## Break\n\n<!-- shot: live -->\n### Break\nRest.\n\n'
            '## Try it\n\n<!-- shot: do -->\n### Do\nTry.\n\n'
            '## Two\n\n<!-- shot -->\n### B\nSaid.\n', encoding="utf-8")
        labels = [m.display for m in talkparse.build_talk(secs).movements]
        if labels != ["1. One", "Break", "2. Try it", "3. Two"]:
            err(errors, f"kinds: section labels {labels}")

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
        if 'class="to-top" href="#top"' not in page or "doc-back" in page.split("</style>")[-1]:
            err(errors, "kinds: web export lacks the Top button, or adds a back link unasked")
        web2 = tmp / "web2"
        r = subprocess.run([sys.executable, str(REPO / "tools" / "web-export.py"), str(talk_md), str(web2),
                            "--back-url", "/event/page/"], capture_output=True, text=True)
        page2 = (web2 / "index.html").read_text() if r.returncode == 0 else ""
        back_href = 'href="/event/page/"'
        if page2.count(back_href) != 2:
            err(errors, f"kinds: --back-url gives {page2.count(back_href)} back links, want 2 "
                        f"(rc {r.returncode}: {r.stderr[:160]})")
        r = subprocess.run([sys.executable, str(REPO / "tools" / "web-export.py"), str(talk_md), str(tmp / "w3"),
                            "--back-url", "../elsewhere/"], capture_output=True, text=True)
        if r.returncode == 0:
            err(errors, "kinds: --back-url accepted a relative path")

        # `[text](url)`: plain words on the slide and in speech, a link in print;
        # a type-in line that is a web address links in print too
        if (talkparse.inline_md("see [the site](https://example.org/a?b=1&c=2) now")
                != 'see <a class="md-link" href="https://example.org/a?b=1&amp;c=2">the site</a> now'
                or talkparse.plain_md("see [**the** site](https://example.org/) now") != "see the site now"
                or "md-link" in talkparse.inline_md("[^src] [timer:5m] [notes] [x](ftp://a.b) [y](relative/)")):
            err(errors, "kinds: markdown links render wrongly")
        lk = tmp / "lk"
        lk.mkdir()
        (lk / "talk.md").write_text(
            '---\ntitle: "Links"\n---\n<!-- shot -->\n\n# Links\n\nHello.\n\n## One\n\n<!-- shot -->\n'
            '### Where\n- Go to [example.org](https://example.org/)\n\nSay [the name](https://example.org/) aloud.\n\n'
            '> `example.org/start`\n', encoding="utf-8")
        lo = tmp / "lk-out"
        subprocess.run([sys.executable, str(REPO / "build.py"), str(lk / "talk.md"), "--out", str(lo)],
                       capture_output=True, text=True)
        ld = (lo / "document" / "index.html").read_text() if (lo / "document" / "index.html").exists() else ""
        lc = json.loads((lo / "cues.json").read_text()) if (lo / "cues.json").exists() else {"cues": []}
        said = " ".join(c.get("script") or "" for c in lc["cues"])
        if ('href="https://example.org/"' not in ld or 'href="https://example.org/start"' not in ld
                or "Say the name aloud." not in said or "](" in said):
            err(errors, "kinds: links missing from print, or link markup in the spoken script")

        # card `reading-copy: false`: on the slide, never in the reading copy
        deck = tmp / "rc"
        (deck / "media").mkdir(parents=True)
        shutil.copy(REPO / "tests/fixtures/decks/stepped-images-warned/media/frame-1.png", deck / "media" / "art.png")
        shutil.copy(REPO / "tests/fixtures/decks/stepped-images-warned/media/frame-2.png", deck / "media" / "fig.png")
        (deck / "media" / "cards.yaml").write_text(
            "- slug: art\n  type: image\n  status: file\n  file: art.png\n  reading-copy: false\n"
            "- slug: fig\n  type: image\n  status: file\n  file: fig.png\n", encoding="utf-8")
        (deck / "talk.md").write_text(
            '---\ntitle: "Pictures"\n---\n<!-- shot: art -->\n\n# Pictures\n\nThe words still print.\n\n'
            '## One\n\n<!-- shot: fig -->\n### A figure\nAbout the figure.\n', encoding="utf-8")
        out = tmp / "rc-out"
        subprocess.run([sys.executable, str(REPO / "build.py"), str(deck / "talk.md"), "--out", str(out)],
                       capture_output=True, text=True)
        doc = (out / "document" / "index.html").read_text() if (out / "document" / "index.html").exists() else ""
        present = (out / "present" / "index.html").read_text() if (out / "present" / "index.html").exists() else ""
        if ('data-slug="art"' in doc or 'data-slug="fig"' not in doc
                or "The words still print." not in doc or "art" not in present):
            err(errors, "kinds: `reading-copy: false` should drop the picture from print only")

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
                       " and pastes the grey boxes into this chat as they reach them. Use 'The hands-on "
                       "parts' below to know what each one is for. Answer questions about anything on "
                       "that page; fetch it if you need to.\n", "## The hands-on parts"):
            if needle not in txt:
                err(errors, f"kinds: agent export lacks {needle!r}")
        heads = re.findall(r"^### (\d+\. .*)$", txt, flags=re.M)
        if heads != ["1. First idea", "2. Try it"]:
            err(errors, f"kinds: agent hands-on parts {heads}")
        body = txt.split("## The hands-on parts", 1)[1]
        if "They paste" in txt or "```" in body.split("### 2.")[0]:
            err(errors, "kinds: agent export carries paste text")
        for needle in (                       "**Exercise:** Ask the person which folder they are in.",
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
        if r.returncode or "## How this runs" in mn or "reading copy is" in mn or "## The hands-on parts" not in mn:
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
        if re.findall(r"^### (\d+\. .*)$", out, flags=re.M) != [
                "1. Kept", "2. First idea", "3. Try it"]:
            err(errors, "kinds: hands-on order or headings with an included section")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _home(errors: list, tmp: Path, talk_md: Path, core: Path, agent_txt: str) -> None:
    """tools/web-export.py --home over a variant of the screen-kinds fixture."""
    import html as htmllib

    src = talk_md.read_text()
    src = src.replace("Say the second idea.",
                      "Say the second idea.\n\n> `Hi.`\n\n```\nprint(\"a < b\")\n```"
                      "\n\n[notes]\n```\nnotes prompt\n```")
    src = src.replace("- write one line", "- write one line\n\n> `Hello there.`")
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
    for needle in ("ex-card", "copy-btn", "Paste this", "<script", "Hello there."):
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
    # one setup card, and no exercise cards
    if page.count('<aside class="ex-card"') != 1:
        err(errors, "kinds: home page has exercise cards")
    for needle in ("Exercise 1", "Paste this to your agent", "Run it on Dana", "(Do:", "Ask the person which folder"):
        if needle in page:
            err(errors, f"kinds: home page carries {needle!r}")
    want_setup = (f"Read {AGENT_URL} and set up this workshop with me. Ask me before you download, "
                  "install or change anything, one question at a time, in plain words.")
    m = re.search(r'id="ex-setup".*?<pre class="paste-box">(.*?)</pre>', page, flags=re.S)
    if not m or htmllib.unescape(m.group(1)) != want_setup:
        err(errors, "kinds: setup paste")
    line = ("Copy this into your coding agent to start. Further down, every grey box with a Copy "
            "button is something to paste into your agent when you reach it.")
    if page.find(line) < 0 or page.find(line) > page.find('<pre class="paste-box">'):
        err(errors, "kinds: setup line is not above the box")
    if f'<a href="{CODING_URL}">Set one up first.</a>' not in page or "No coding agent yet?" not in page:
        err(errors, "kinds: setup card lacks the coding-agent link")
    if page.index("ex-setup") > page.index('<div class="screen"'):
        err(errors, "kinds: setup card is not before the first screen")
    # the do screen is in place, with its text and typed prompt, between the second and third idea
    j = page.find("Hello there.")
    if not page.index("Say the second idea.") < page.find("open the folder") < j < page.index("Say the third idea."):
        err(errors, "kinds: the do screen is not in place")
    if "Spend five minutes on this." not in page or "Room only" in page or "Ask the room" in page:
        err(errors, "kinds: do screen text, or a room screen leaked")
    # copy buttons: only the setup box, a `do` screen's typed line and a `[notes]` code block. A quote
    # or code block on a content screen is for reading: no button (and the markers are gone)
    boxes = len(re.findall(r"<pre\b", page)) + page.count('<blockquote class="type-in">')
    wraps = page.count('<div class="copy-wrap">')
    btns = page.count('<button type="button" class="copy-btn">Copy</button>')
    if not (boxes == 5 and wraps == btns == 3):
        err(errors, f"kinds: copy buttons: {boxes} boxes, {wraps} wraps, {btns} buttons (want 5, 3, 3)")
    if "copy:on" in page or "copy:off" in page:
        err(errors, "kinds: copy markers left in the page")
    if re.search(r'<div class="copy-wrap"><blockquote class="type-in"><p><code>Hi\.</code>', page):
        err(errors, "kinds: a quote on a content screen has a Copy button")
    if not re.search(r'<div class="copy-wrap"><pre[^>]*>(?:<[^>]+>)*notes prompt', page):
        err(errors, "kinds: a [notes] code block has no Copy button")
    if not re.search(r'<div class="copy-wrap"><blockquote class="type-in"><p><code>Hello there\.</code>', page):
        err(errors, "kinds: the do screen's typed prompt has no Copy button")
    for needle in ("navigator.clipboard.writeText", 'execCommand("copy")', 'aria-live="polite"',
                   'role="status"', "2000", "@keyframes copy-next", "prefers-reduced-motion",
                   'classList.add("next-up")'):
        if needle not in page:
            err(errors, f"kinds: copy script lacks {needle!r}")
    if 'print("a &lt; b")' not in page and "print(&quot;a &lt; b&quot;)" not in page:
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
    # refusals hold: a local path on the page, a non-http URL
    leak = tmp / "homeleak.md"
    leak.write_text(src.replace("Say the third idea.", "Say it from /home/someone/notes."))
    r = subprocess.run([sys.executable, exe, str(leak), str(tmp / "home4"), "--home"],
                       capture_output=True, text=True)
    if r.returncode != 1:
        err(errors, "kinds: home export did not refuse a local path")
    r = run(tmp / "home5", "--home", "--agent-url", "file:///etc/x")
    if r.returncode != 1:
        err(errors, "kinds: home export did not refuse a non-http agent URL")
