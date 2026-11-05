"""Quick select (docs/quick-select.md): the shelf, over tests/fixtures/quick.

A throwaway copy of the fixture deck under /tmp, built through build.py.  The
browser half (paging, jumping, the search box) is tests/browser_quick_select.py.

- the shelf is the sections of `quick_sections` that declare `quick:`, in
  filename order, after the talk's last real screen: existing slide numbers do
  not move, a section with no `quick:` block stays off, and a section the talk
  already includes is not shelved a second time (its title and keywords still
  reach the search, through the cue index);
- shelf screens are in the present view (`data-quick`), the presenter cue index,
  cues.json (`quick` and `live_only`), nav.json (`include`, `quick`) and the
  media manifest, and absent from the document view, so from the handout and the
  web export (tools/web-export.py is run for real);
- the shelf does not lengthen the talk (check 19 reports what it reported with no
  shelf) and is in no movement;
- a shelf section's `cites:` / `sources:` never reach the talk's, the handout's
  Sources list, `deck.sources` or any public page, yet its own screens still
  resolve them (`Talk.shelf_cite`);
- the presenter's cue index mirrors cues.json id for id and carries search text
  that has the screen's text and script and never its stage notes;
- builds are byte-identical twice; a deck with no `quick_sections` has an empty shelf
  (no shelf markers or fields, document view, cues, nav and slide markup equal to the
  same talk built with a shelf); and a `quick:` block means nothing in a deck that has
  not opted in;
- check 48: a missing directory, a `quick:` with no title or with keywords that
  are not a list is fatal, with the file and line; `--quick-sections` overrides
  the frontmatter line.
"""

from __future__ import annotations

import hashlib
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
FIXTURE = REPO / "tests" / "fixtures" / "quick"


def _build(talk: Path, out: Path, *extra: str) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = build_mod.main([str(talk), "--out", str(out), *extra])
    if code != 0:
        raise RuntimeError(f"build exited {code}")
    return buf.getvalue()


def _hashes(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _fatal(talk: Path, want: str, errors: list, label: str, **kw) -> None:
    try:
        talkparse.build_talk(talk, **kw)
    except ValueError as exc:
        msg = str(exc)
        if "check 48" not in msg or want not in msg:
            err(errors, f"{label}: wrong error {msg!r} (wanted check 48 / {want!r})")
        elif not re.search(r":\d+: check 48:", msg):
            err(errors, f"{label}: no line number in {msg!r}")
        return
    err(errors, f"{label}: no error raised")


def check(errors: list) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="animatic-quick-"))
    try:
        deck = tmp / "deck"
        shutil.copytree(FIXTURE, deck)
        talk_md = deck / "talk.md"

        t = talkparse.build_talk(talk_md)
        main, shelf = t.main_screens, t.shelf_screens
        if len(main) != 8 or len(shelf) != 6:
            err(errors, f"quick: {len(main)} main / {len(shelf)} shelf screens, want 8 / 6")
        if [s.idx for s in t.screens] != list(range(1, 15)):
            err(errors, "quick: screen idx is not 1..14 in order")
        if any(s.shelf for s in t.screens[:8]) or not all(s.shelf for s in t.screens[8:]):
            err(errors, "quick: the shelf is not exactly the screens after the talk")
        order = []
        for s in shelf:
            if s.section[1] not in order:
                order.append(s.section[1])
        if order != ["What's an agent?", "Live demo", "Which model?"]:
            err(errors, f"quick: shelf order {order} is not filename order")
        if "Linked section" in order or any("Not on the shelf" in b.text
                                            for s in t.screens for b in s.blocks):
            err(errors, "quick: a section already included, or with no quick: block, was shelved")
        linked = [s for s in main if s.section]
        if len(linked) != 2 or linked[0].section[1] != "Linked section" \
                or linked[0].section[2] != ("linked", "included"):
            err(errors, f"quick: the included section lost its title/keywords: {[s.section for s in linked]}")
        if [p.name for p in t.shelf_files] != ["agents.section.md", "demo.section.md", "models.section.md"]:
            err(errors, f"quick: shelf_files {[p.name for p in t.shelf_files]}")

        # citations: the shelf's own, never the talk's
        if set(t.meta.get("cites", {})) != {"m1"} or set(t.meta.get("sources", {})) != {"m1"}:
            err(errors, f"quick: a shelf registry leaked into the talk's meta: {t.meta.get('cites')}")
        if t.footnote_ids != ["m1"] or t.shelf_footnote_ids != ["secret"]:
            err(errors, f"quick: footnote ids {t.footnote_ids} / shelf {t.shelf_footnote_ids}")
        agent1 = shelf[0]
        if t.shelf_cite(agent1, "secret") != "SHELF-ONLY public citation" \
                or t.shelf_cite(agent1, "secret", "sources") != "SHELF-ONLY working receipt":
            err(errors, "quick: a shelf screen cannot resolve its own citation")
        if t.shelf_cite(agent1, "m1") != "Public citation the talk makes.":
            err(errors, "quick: a shelf screen cannot fall back to the talk's citation")
        if not any(rid == "secret" for b in agent1.blocks for rid, _ in (b.refs or ())):
            err(errors, "quick: the shelf screen lost its [^secret] reference")
        if any("check 28" in w for w in t.warnings):
            err(errors, f"quick: a resolvable shelf footnote warned: {t.warnings}")

        # builds
        out_a, out_b = tmp / "out-a", tmp / "out-b"
        _build(talk_md, out_a)
        _build(talk_md, out_b)
        if _hashes(out_a) != _hashes(out_b):
            err(errors, "quick: two builds differ (determinism)")
        cues = json.loads((out_a / "cues.json").read_text(encoding="utf-8"))
        nav = json.loads((out_a / "nav.json").read_text(encoding="utf-8"))
        manifest = json.loads((out_a / "media-manifest.json").read_text(encoding="utf-8"))
        doc = (out_a / "document" / "index.html").read_text(encoding="utf-8")
        present = (out_a / "present" / "index.html").read_text(encoding="utf-8")
        presenter = (out_a / "present" / "presenter.html").read_text(encoding="utf-8")

        cs = cues["cues"]
        if len(cs) != 14 or [bool(c.get("quick")) for c in cs] != [False] * 8 + [True] * 6:
            err(errors, "quick: cues.json quick flags are not the last six cues")
        if not all(c.get("live_only") for c in cs[8:]) or any(c.get("live_only") for c in cs[:8]):
            err(errors, "quick: shelf cues are not exactly the live_only ones")
        if any(c["id"] in sum((m["cue_ids"] for m in cues["movements"]), []) for c in cs[8:]):
            err(errors, "quick: a shelf cue is listed in a movement")
        if [s["id"] for s in cues["deck"]["sources"]] != ["m1"]:
            err(errors, f"quick: deck.sources {cues['deck']['sources']}")
        ns = list(nav["screens"].values())
        if [bool(v.get("quick")) for v in ns] != [False] * 8 + [True] * 6:
            err(errors, "quick: nav.json quick flags")
        if any(v["document"]["present"] for v in ns[8:]) or any(not v["document"]["present"] for v in ns[:8]):
            err(errors, "quick: nav.json document presence is not 'talk yes, shelf no'")
        if not all(v.get("include", "").endswith(".section.md") for v in ns[8:]):
            err(errors, "quick: a shelf nav entry names no include")
        slugs = {r["slug"] for r in manifest["referenced"]}
        if not {"clip-shelf", "live-demo", "clip-main"} <= slugs:
            err(errors, f"quick: the media manifest misses shelf media: {sorted(slugs)}")

        # public output
        for needle in ("SHELF-ONLY", "What an agent is", "What it costs", "A shelf live window",
                       "Picking a model", "STAGEWORD"):
            if needle in doc:
                err(errors, f"quick: {needle!r} is in the document view / handout")
        if "Included in the talk" not in doc or "Public citation the talk makes." not in doc:
            err(errors, "quick: the talk's own slide or citation left the document view")
        if "Working receipt" in doc:
            err(errors, "quick: a working receipt is in the handout")
        sections = re.findall(r'<section id="[^"]+" class="[^"]*"[^>]*>', present)
        if len(sections) != 14 or [("data-quick=" in s) for s in sections] != [False] * 8 + [True] * 6:
            err(errors, "quick: data-quick is not on exactly the shelf slides")
        if "SHELF-ONLY" in present or "SHELF-ONLY" in presenter:
            err(errors, "quick: a shelf citation is in the present or presenter page")

        # the cue index mirrors cues.json
        m = re.search(r'<script type="application/json" id="cue-index">(.*?)</script>', presenter, re.DOTALL)
        idx = json.loads(m.group(1).replace("\\u003c", "<"))["cues"]
        if [c["id"] for c in idx] != [c["id"] for c in cs]:
            err(errors, "quick: the presenter cue index and cues.json differ in ids")
        if [bool(c.get("quick")) for c in idx] != [bool(c.get("quick")) for c in cs]:
            err(errors, "quick: the presenter cue index and cues.json differ in quick flags")
        if [c["kind"] for c in idx] != [c["kind"] for c in cs]:
            err(errors, "quick: the presenter cue index and cues.json differ in kinds")
        if idx[8].get("sec_title") != "What's an agent?" or "claude code" not in idx[8].get("sec_kw", []):
            err(errors, f"quick: shelf cue lost its section title/keywords: {idx[8]}")
        if idx[5].get("sec_title") != "Linked section" or idx[0].get("sec"):
            err(errors, "quick: the included section's title/keywords, or a plain cue's, are wrong")
        if "costs" not in idx[10]["st"] or "tokens" not in idx[10]["sc"] \
                or "tools" not in idx[8]["sc"] or "read your files" not in idx[9]["st"]:
            err(errors, "quick: the search text lacks the screen text or the script")
        if "STAGEWORD" in json.dumps(idx):
            err(errors, "quick: stage notes are in the search index")
        if "STAGEWORD" not in present:
            err(errors, "quick: the stage note is gone from the speaker notes")

        # timing: a shelf does not lengthen the talk
        no_shelf = deck / "noshelf"
        no_shelf.mkdir()
        shutil.copytree(deck / "sections", no_shelf / "sections")
        shutil.copytree(deck / "media", no_shelf / "media")
        txt = talk_md.read_text(encoding="utf-8").replace("quick_sections: sections\n", "")
        (no_shelf / "talk.md").write_text(txt, encoding="utf-8")
        rep_with = check_mod.check_file(talk_md)
        rep_without = check_mod.check_file(no_shelf / "talk.md")
        pick = lambda r: sorted(f.message for f in r.findings if f.check == 19)
        if pick(rep_with) != pick(rep_without):
            err(errors, f"quick: check 19 changed with a shelf: {pick(rep_with)} vs {pick(rep_without)}")
        # make the shelf long enough to matter if it were counted
        (deck / "sections" / "long.section.md").write_text(
            "---\nquick:\n  title: Long\n---\n<!-- shot -->\n" + ("word " * 4000) + "\n", encoding="utf-8")
        if pick(check_mod.check_file(talk_md)) != pick(rep_without):
            err(errors, "quick: a long shelf section moved the timing report")
        (deck / "sections" / "long.section.md").unlink()

        # a deck with no quick_sections has an empty shelf: no shelf markers, no
        # quick fields, and the visible and non-script outputs are those of the
        # same talk built with a shelf (the shelf adds screens after the talk and
        # nothing else to them).  The scripts are shared, so the page's script
        # text is not compared.
        out_n = tmp / "out-n"
        _build(no_shelf / "talk.md", out_n)
        pn = (out_n / "present" / "index.html").read_text(encoding="utf-8")
        if re.search(r"data-quick=", re.sub(r"<script>.*?</script>", "", pn, flags=re.DOTALL)):
            err(errors, "quick: a deck with no shelf has a data-quick slide")
        cn = json.loads((out_n / "cues.json").read_text(encoding="utf-8"))
        nn = json.loads((out_n / "nav.json").read_text(encoding="utf-8"))
        if any("quick" in c for c in cn["cues"]) or any("quick" in v for v in nn["screens"].values()):
            err(errors, "quick: a deck with no shelf carries quick fields in cues/nav")
        if (out_n / "document" / "index.html").read_bytes() != (out_a / "document" / "index.html").read_bytes():
            err(errors, "quick: the document view differs with and without a shelf")
        nolines = lambda es: [{k: v for k, v in e.items() if k != "lines"} for e in es]   # one line shorter
        if cn["cues"] != cs[:8] or nolines(nn["screens"].values()) != nolines(ns[:8]):
            err(errors, "quick: the talk's cues/nav entries differ with and without a shelf")
        slides_of = lambda page: re.findall(r'<section id="[^"]+" class="[^"]*"[^>]*>.*?</section>',
                                            re.sub(r"<script>.*?</script>", "", page, flags=re.DOTALL), re.DOTALL)
        if slides_of(pn) != slides_of(present)[:8]:
            err(errors, "quick: the talk's slide markup differs with and without a shelf")
        # web export follows the same exclusion (the handout PDF builds the same
        # document view; tools/handout-pdf.py needs a printing chromium)
        web = tmp / "web"
        r = subprocess.run([sys.executable, str(REPO / "tools" / "web-export.py"), str(talk_md), str(web)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            err(errors, f"quick: web-export failed: {r.stderr[-300:]}")
        else:
            page = (web / "index.html").read_text(encoding="utf-8")
            if any(n in page for n in ("SHELF-ONLY", "What an agent is", "STAGEWORD", "Live demo")):
                err(errors, "quick: the web export carries shelf content")

        # `--quick-sections` and check 48
        override = tmp / "override"
        override.mkdir()
        (override / "talk.md").write_text(txt, encoding="utf-8")
        shutil.copytree(deck / "media", override / "media")
        only = tmp / "only-models"
        only.mkdir()
        shutil.copy(deck / "sections" / "models.section.md", only)
        # (the talk includes sections/linked.section.md; a copy in another
        # directory is a different file, so it is left out of this one)
        shutil.copytree(deck / "sections", override / "sections")
        t_o = talkparse.build_talk(override / "talk.md", quick_sections=str(only))
        if [s.section[1] for s in t_o.shelf_screens[:1]] != ["Which model?"] or len(t_o.shelf_screens) != 2:
            err(errors, f"quick: --quick-sections did not shelve its own directory: "
                        f"{[s.section for s in t_o.shelf_screens]}")
        t_f = talkparse.build_talk(talk_md, quick_sections=str(only))
        if len(t_f.shelf_screens) != 2:
            err(errors, "quick: --quick-sections does not override the frontmatter line")
        _fatal(talk_md, "no such directory", errors, "missing flag dir", quick_sections=str(tmp / "nope"))
        bad = deck / "bad"
        bad.mkdir()
        (bad / "sections").mkdir()
        (bad / "media").mkdir()

        def bad_talk(front: str, section: str | None = None) -> Path:
            (bad / "talk.md").write_text(
                "---\ntype: Talk\nformat-version: 1.0\nslug: bad\ntitle: Bad\ntheme: workshop\n"
                + front + "---\n<!-- shot -->\n# Hi\n\nHello.\n", encoding="utf-8")
            for f in (bad / "sections").iterdir():
                f.unlink()
            if section is not None:
                (bad / "sections" / "s.section.md").write_text(section, encoding="utf-8")
            return bad / "talk.md"

        _fatal(bad_talk("quick_sections: nothere\n"), "no such directory", errors, "missing dir")
        _fatal(bad_talk("quick_sections: [a, b]\n"), "directory path", errors, "list value")
        _fatal(bad_talk("quick_sections: sections\n", "---\nquick:\n  keywords: [a]\n---\nx\n"),
               "title", errors, "no title")
        _fatal(bad_talk("quick_sections: sections\n", "---\nquick:\n  title: T\n  keywords: agents\n---\nx\n"),
               "list", errors, "keywords not a list")
        _fatal(bad_talk("quick_sections: sections\n", "---\nquick: yes\n---\nx\n"),
               "quick:", errors, "quick not a block")
        rep = check_mod.check_file(bad_talk("quick_sections: sections\n", "---\nquick:\n  keywords: [a]\n---\nx\n"))
        if not any(f.check == 48 and f.severity == check_mod.FATAL for f in rep.findings):
            err(errors, "quick: check.py did not report check 48 as a fatal")
        # an ok block with no keywords is fine, and is shelved
        ok = bad_talk("quick_sections: sections\n", "---\nquick:\n  title: T\n---\n<!-- shot -->\nShelf.\n")
        t_ok = talkparse.build_talk(ok)
        if len(t_ok.shelf_screens) != 1 or t_ok.shelf_screens[0].section[2] != ():
            err(errors, "quick: a quick block with no keywords was not shelved")
        # no opt-in, no effect: a malformed quick: in a plain include still parses
        (bad / "sections" / "s.section.md").write_text("---\nquick: nonsense\n---\n<!-- shot -->\nIn.\n", encoding="utf-8")
        (bad / "talk.md").write_text(
            "---\ntype: Talk\nformat-version: 1.0\nslug: bad\ntitle: Bad\ntheme: workshop\n---\n"
            "<!-- include: sections/s.section.md -->\n", encoding="utf-8")
        t_p = talkparse.build_talk(bad / "talk.md")
        if len(t_p.screens) != 1 or t_p.screens[0].section is not None or t_p.shelf_screens:
            err(errors, "quick: a quick: block changed a deck that did not opt in")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
