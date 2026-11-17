"""Waypoints, the animatic half (docs/waypoints.md, section 1), over tests/fixtures/waypoints.

A throwaway copy of the fixture deck under /tmp, built through build.py.  The
browser half (the publish rules, failure and retry, the presenter's `w`, the inert
build) is tests/browser_waypoint.py.

- `waypoint=word` in a screen's shot (`<!-- shot: waypoint=word -->`) marks that screen, and the
  screens come out in order with the right words; a word of 24 characters is fine; the old
  standalone `<!-- waypoint: word -->` line is a fatal that says where the word goes now;
- check 49 is a fatal with the file and line for: a bad word (capitals, a space,
  25 characters, empty), a word used twice, one on a shot that opens no new screen,
  one inside a section (included, or on the shelf), waypoints with no
  `waypoints.url`, a `waypoints:` with a url that is not http(s); check.py reports it;
- `cues.json` and `nav.json` carry `waypoint` on marked screens and nowhere else,
  with a token or without; the document view, the handout and the web export never
  show a word, nor does the presenter page or an inert present page;
- a deck without the directives builds the same document view, the same slide markup
  and the same cues, nav and media manifest as the same deck with them, bar the
  `waypoint` field (the golden suite covers the decks that never had any);
- the token (`ANIMATIC_WAYPOINT_TOKEN`) lands in `present/index.html` only: no other
  output file, no build log, no web export has it.  A build without it is inert: no
  module, no `Bearer`, no status line in the presenter page.  Builds are
  deterministic with it.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
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
FIXTURE = REPO / "tests" / "fixtures" / "waypoints"
TOKEN = "PROPTOKEN-93kd8Zq-not-a-real-secret"


def _build(talk: Path, out: Path, token: str | None = None, *extra: str) -> str:
    buf = io.StringIO()
    old = os.environ.pop("ANIMATIC_WAYPOINT_TOKEN", None)
    if token:
        os.environ["ANIMATIC_WAYPOINT_TOKEN"] = token
    try:
        with redirect_stdout(buf):
            code = build_mod.main([str(talk), "--out", str(out), *extra])
    finally:
        os.environ.pop("ANIMATIC_WAYPOINT_TOKEN", None)
        if old is not None:
            os.environ["ANIMATIC_WAYPOINT_TOKEN"] = old
    if code != 0:
        raise RuntimeError(f"build exited {code}")
    return buf.getvalue()


def _hashes(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _fatal(talk: Path, want: str, errors: list, label: str) -> None:
    try:
        talkparse.build_talk(talk)
    except ValueError as exc:
        msg = str(exc)
        if want not in msg or not re.search(r":\d+: check 49:", msg):
            err(errors, f"waypoint {label}: wrong error {msg!r} (wanted a line number, check 49 and {want!r})")
        return
    err(errors, f"waypoint {label}: no error raised")


def check(errors: list) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="animatic-waypoint-"))
    try:
        deck = tmp / "deck"
        shutil.copytree(FIXTURE, deck)
        talk_md = deck / "talk.md"
        src = talk_md.read_text(encoding="utf-8")

        # --- the parse ------------------------------------------------------------
        t = talkparse.build_talk(talk_md)
        got = [s.waypoint for s in t.main_screens]
        want = ["start", None, None, "key-choice", None, "expanding", None, "sharing", None]
        if got != want:
            err(errors, f"waypoint: marked screens {got}, want {want}")
        if any(s.waypoint for s in t.shelf_screens):
            err(errors, "waypoint: a shelf screen carries a waypoint")
        if talkparse.build_talk(talk_md).screens[3].waypoint_line != src.split("\n").index("<!-- shot: waypoint=key-choice -->") + 1:
            err(errors, "waypoint: the shot's line is not the talkfile's own")

        # --- check 49 ---------------------------------------------------------------
        bad = tmp / "bad"
        bad.mkdir()
        (bad / "sections").mkdir()
        head = ("---\ntype: Talk\nformat-version: 1.0\nslug: bad\ntitle: Bad\ntheme: workshop\n"
                "waypoints: { url: http://127.0.0.1:1/x }\n")

        def talk_with(body: str, front: str = head, section: str | None = None,
                      extra_front: str = "") -> Path:
            (bad / "talk.md").write_text(front + extra_front + "---\n" + body, encoding="utf-8")
            for f in (bad / "sections").iterdir():
                f.unlink()
            if section is not None:
                (bad / "sections" / "s.section.md").write_text(section, encoding="utf-8")
            return bad / "talk.md"

        def shot_wp(word: str) -> str:
            return f"<!-- shot: waypoint={word} -->\n# Hi\n\nHello.\n"

        shot = "<!-- shot -->\n# Hi\n\nHello.\n"
        ok24 = "a" * 24
        t24 = talkparse.build_talk(talk_with(shot_wp(ok24)))
        if t24.screens[0].waypoint != ok24:
            err(errors, "waypoint: a 24-character word was refused")
        for word, label in (("Start", "capital"), ("a" * 25, "25 characters"),
                            ("", "empty"), ("under_score", "underscore")):
            _fatal(talk_with(shot_wp(word)), "bad waypoint", errors, f"bad word ({label})")
        # a role-first shot and a slug-first shot take the flag too
        tr = talkparse.build_talk(talk_with("<!-- shot: stat waypoint=stat-one -->\n# Hi\n\nHello.\n"))
        if tr.screens[0].waypoint != "stat-one":
            err(errors, "waypoint: a role shot did not take waypoint=")
        _fatal(talk_with("<!-- waypoint: x -->\n" + shot), "standalone waypoint line is gone", errors, "old standalone line")
        _fatal(talk_with("<!-- waypoint: x\n-->\n" + shot), "standalone waypoint line is gone", errors, "old two-line form")
        _fatal(talk_with(shot_wp("a") + "\n" + shot_wp("a")), "used twice", errors, "duplicate")
        _fatal(talk_with(shot_wp("a"), front=head.replace("waypoints: { url: http://127.0.0.1:1/x }\n", "")),
               "no `waypoints:", errors, "no url")
        _fatal(talk_with(shot_wp("a"), front=head.replace("http://127.0.0.1:1/x", "ftp://x")),
               "http:// or https://", errors, "url not http")
        _fatal(talk_with(shot, front=head.replace("{ url: http://127.0.0.1:1/x }", "yes")),
               "http:// or https://", errors, "waypoints: with no url")
        _fatal(talk_with("<!-- include: sections/s.section.md -->\n", section="---\ntitle: S\n---\n" + shot_wp("a")),
               "cannot sit in a section", errors, "in an included section")
        _fatal(talk_with(shot, front=head + "quick_sections: sections\n",
                         section="---\nquick:\n  title: T\n---\n" + shot_wp("a")),
               "cannot sit in a section", errors, "in a shelf section")
        rep = check_mod.check_file(talk_with(shot_wp("A")))
        if not any(f.check == 49 and f.severity == check_mod.FATAL for f in rep.findings):
            err(errors, "waypoint: check.py did not report check 49 as a fatal")
        rep_ok = check_mod.check_file(talk_md)
        if any(f.check == 49 for f in rep_ok.findings):
            err(errors, "waypoint: a good fixture reported check 49")
        # the flag changes nothing else about the screens
        plain = src.replace(" waypoint=key-choice", "").replace("<!-- shot: -->", "<!-- shot -->")
        (deck / "plain-between.md").write_text(plain, encoding="utf-8")
        tp = talkparse.build_talk(deck / "plain-between.md")
        if [len(s.blocks) for s in tp.screens] != [len(s.blocks) for s in t.screens]:
            err(errors, "waypoint: a directive changed how many blocks a screen has")

        # --- the outputs, inert ---------------------------------------------------------
        out_a, out_b = tmp / "out-a", tmp / "out-b"
        log_a = _build(talk_md, out_a)
        _build(talk_md, out_b)
        if _hashes(out_a) != _hashes(out_b):
            err(errors, "waypoint: two inert builds differ (determinism)")
        if "inert" not in log_a:
            err(errors, "waypoint: the build log does not say the build is inert")
        cues = json.loads((out_a / "cues.json").read_text(encoding="utf-8"))["cues"]
        nav = list(json.loads((out_a / "nav.json").read_text(encoding="utf-8"))["screens"].values())
        if [c.get("waypoint") for c in cues[:9]] != want or any("waypoint" in c for c in cues[9:]):
            err(errors, f"waypoint: cues.json waypoint fields {[c.get('waypoint') for c in cues]}")
        if [v.get("waypoint") for v in nav[:9]] != want or any("waypoint" in v for v in nav[9:]):
            err(errors, "waypoint: nav.json waypoint fields")
        pres_a = (out_a / "present" / "presenter.html").read_text(encoding="utf-8")
        page_a = (out_a / "present" / "index.html").read_text(encoding="utf-8")
        if "presenter-waypoint" in re.sub(r"<script>.*?</script>", "", pres_a, flags=re.DOTALL):
            err(errors, "waypoint: an inert build's presenter page has a status line")
        for word in ("key-choice", "expanding", "sharing"):
            if re.search(r'"%s"' % word, page_a) or "Bearer" in page_a or "127.0.0.1:1" in page_a:
                err(errors, f"waypoint: an inert present page carries waypoint data ({word})")
        # the module itself is not in the inert page; only the pager's hook is
        if "waypoint_cfg" in page_a.lower() or "TIMEOUT_MS" in page_a:
            err(errors, "waypoint: the publishing module is in an inert page")
        doc = (out_a / "document" / "index.html").read_text(encoding="utf-8")

        # a distinctive word, so "not in the document view" means something
        zq = src
        for w in ("start", "key-choice", "expanding", "sharing"):
            zq = zq.replace(f"waypoint={w} ", f"waypoint=zq-{w} ")
        (deck / "zq.md").write_text(zq, encoding="utf-8")
        out_z = tmp / "out-z"
        _build(deck / "zq.md", out_z, TOKEN)
        zdoc = (out_z / "document" / "index.html").read_text(encoding="utf-8")
        if "zq-" in zdoc:
            err(errors, "waypoint: a waypoint word is in the document view / handout")
        zc = json.loads((out_z / "cues.json").read_text(encoding="utf-8"))["cues"]
        if [c.get("waypoint") for c in zc[:9]] != ["zq-start", None, None, "zq-key-choice", None, "zq-expanding", None, "zq-sharing", None]:
            err(errors, "waypoint: the cues.json word is not the authored one")
        zp = (out_z / "present" / "presenter.html").read_text(encoding="utf-8")
        if "zq-" in zp:
            err(errors, "waypoint: a word reached the presenter page")

        # --- the token ---------------------------------------------------------------------
        out_t, out_t2 = tmp / "out-t", tmp / "out-t2"
        log_t = _build(talk_md, out_t, TOKEN)
        _build(talk_md, out_t2, TOKEN)
        if TOKEN in log_t:
            err(errors, "waypoint: the build log printed the token")
        if "publishing ON" not in log_t:
            err(errors, "waypoint: the build log does not say publishing is on")
        if _hashes(out_t) != _hashes(out_t2):
            err(errors, "waypoint: two builds with the token differ (determinism)")
        holders = [str(p.relative_to(out_t)) for p in sorted(out_t.rglob("*"))
                   if p.is_file() and TOKEN.encode() in p.read_bytes()]
        if holders != ["present/index.html"]:
            err(errors, f"waypoint: the token is in {holders}, want present/index.html only")
        page_t = (out_t / "present" / "index.html").read_text(encoding="utf-8")
        if page_t.count(TOKEN) != 1:
            err(errors, f"waypoint: the token appears {page_t.count(TOKEN)} times in the present page")
        m = re.search(r'var CFG = (\{.*?\});', page_t)
        cfg = json.loads(m.group(1)) if m else {}
        if cfg.get("token") != TOKEN or cfg.get("url") != "http://127.0.0.1:8472/event/waypoint/W99" \
                or cfg.get("words") != {"0": "start", "3": "key-choice", "5": "expanding", "7": "sharing"}:
            err(errors, f"waypoint: the page's config is {cfg}")
        pres_t = (out_t / "present" / "presenter.html").read_text(encoding="utf-8")
        if 'id="presenter-waypoint"' not in pres_t:
            err(errors, "waypoint: a build with the token has no status line in the presenter page")
        if TOKEN in pres_t or TOKEN in (out_t / "cues.json").read_text(encoding="utf-8"):
            err(errors, "waypoint: the token reached the presenter page or cues.json")
        # whitespace around the token is not part of it
        out_ws = tmp / "out-ws"
        _build(talk_md, out_ws, "  " + TOKEN + "\n")
        if (out_ws / "present" / "index.html").read_text(encoding="utf-8").count(TOKEN) != 1:
            err(errors, "waypoint: a token with surrounding whitespace was not trimmed")
        # an empty token is no token
        out_e = tmp / "out-e"
        _build(talk_md, out_e, "   ")
        if "Bearer" in (out_e / "present" / "index.html").read_text(encoding="utf-8"):
            err(errors, "waypoint: a blank token turned publishing on")
        # a token with characters that could break the script element
        nasty = "t</script><b>'\"\\x"
        out_n = tmp / "out-n"
        _build(talk_md, out_n, nasty)
        page_n = (out_n / "present" / "index.html").read_text(encoding="utf-8")
        if page_n.count("</script>") != page_t.count("</script>"):
            err(errors, "waypoint: a token with </script> in it broke out of the script element")
        mn = re.search(r'var CFG = (\{.*?\});', page_n)
        if not mn or json.loads(mn.group(1)).get("token") != nasty:
            err(errors, "waypoint: a token with quotes did not survive the config round trip")
        # a talk with no waypoints is untouched by a token
        out_q = tmp / "out-q"
        _build(REPO / "tests" / "fixtures" / "quick" / "deck" / "talk.md", out_q, TOKEN)
        if any(TOKEN.encode() in p.read_bytes() for p in out_q.rglob("*") if p.is_file()):
            err(errors, "waypoint: a talk with no waypoints carries the token")

        # --- an inert build will not replace a publishing one ---------------------------
        out_g = tmp / "out-guard"
        _build(talk_md, out_g, TOKEN)
        try:
            _build(talk_md, out_g)
            err(errors, "waypoint: an inert build replaced a publishing one")
        except RuntimeError:
            pass
        if b"Bearer " not in (out_g / "present" / "index.html").read_bytes():
            err(errors, "waypoint: the refused inert build still damaged the publishing output")
        _build(talk_md, out_g, TOKEN)          # a keyed rebuild is fine
        _build(talk_md, out_g, None, "--allow-inert")
        if b"Bearer " in (out_g / "present" / "index.html").read_bytes():
            err(errors, "waypoint: --allow-inert did not replace the publishing output")
        _build(talk_md, tmp / "out-guard-fresh")   # an inert build into a fresh folder is fine

        # --- the web export never carries it ------------------------------------------------
        web = tmp / "web"
        env = dict(os.environ, ANIMATIC_WAYPOINT_TOKEN=TOKEN)
        r = subprocess.run([sys.executable, str(REPO / "tools" / "web-export.py"), str(talk_md), str(web)],
                           capture_output=True, text=True, env=env)
        if r.returncode != 0:
            err(errors, f"waypoint: web-export failed: {r.stderr[-300:]}")
        else:
            if any(TOKEN.encode() in p.read_bytes() for p in web.rglob("*") if p.is_file()):
                err(errors, "waypoint: the web export carries the token")
            if (web / "present").exists() or (web / "cues.json").exists():
                err(errors, "waypoint: the web export ships a present view or cues")

        # --- a deck with the directives out is the same deck, bar the field ---------------------
        bare = tmp / "bare"
        bare.mkdir()
        txt = re.sub(r" waypoint=[a-z0-9-]+", "", src).replace("<!-- shot: -->", "<!-- shot -->")
        txt = txt.replace("waypoints: { url: http://127.0.0.1:8472/event/waypoint/W99 }\n", "")
        (bare / "talk.md").write_text(txt, encoding="utf-8")
        shutil.copytree(deck / "sections", bare / "sections")
        out_b0 = tmp / "out-bare"
        _build(bare / "talk.md", out_b0)
        if (out_b0 / "document" / "index.html").read_bytes() != (out_a / "document" / "index.html").read_bytes():
            err(errors, "waypoint: the document view differs with and without waypoints")
        # (nav ranges move when the directive lines go, so `lines` is left out)
        strip = lambda cs: [{k: v for k, v in c.items() if k not in ("waypoint", "lines")} for c in cs]
        cb = json.loads((out_b0 / "cues.json").read_text(encoding="utf-8"))["cues"]
        nb = list(json.loads((out_b0 / "nav.json").read_text(encoding="utf-8"))["screens"].values())
        if strip(cb) != strip(cues) or strip(nb) != strip(nav):
            err(errors, "waypoint: cues.json or nav.json differ beyond the waypoint field")
        if any("waypoint" in c for c in cb) or any("waypoint" in v for v in nb):
            err(errors, "waypoint: a deck with no waypoints has a waypoint field")
        if (out_b0 / "media-manifest.json").read_bytes() != (out_a / "media-manifest.json").read_bytes():
            err(errors, "waypoint: the media manifest differs with and without waypoints")
        slides_of = lambda page: re.findall(r'<section id="[^"]+" class="[^"]*"[^>]*>.*?</section>',
                                            re.sub(r"<script>.*?</script>", "", page, flags=re.DOTALL), re.DOTALL)
        pb = (out_b0 / "present" / "index.html").read_text(encoding="utf-8")
        if slides_of(pb) != slides_of(page_a) or slides_of(pb) != slides_of(page_t):
            err(errors, "waypoint: the slide markup differs with and without waypoints")
        css = lambda page: re.findall(r"<style.*?</style>", page, flags=re.DOTALL)
        if css(pb) != css(page_a) or css(pb) != css(page_t):
            err(errors, "waypoint: the present page's CSS differs with and without waypoints")
        pres_b = (out_b0 / "present" / "presenter.html").read_text(encoding="utf-8")
        if pres_b != pres_a:
            err(errors, "waypoint: an inert waypoint build's presenter page differs from the same deck with none")
        if "presenter-waypoint" in re.sub(r"<script>.*?</script>", "", pres_b, flags=re.DOTALL):
            err(errors, "waypoint: a deck with no waypoints has a status line")

        # --- where the token comes from -------------------------------------------
        # The env var wins; otherwise the machine key file (so the secret is not
        # typed per build and never rides in a remote watch's ssh command).
        token_file = tmp / "waypoint-token"
        token_file.write_text("  FIXTURE-TOKEN\n", encoding="utf-8")
        token_file.chmod(0o600)
        saved = {k: os.environ.get(k) for k in
                 ("ANIMATIC_WAYPOINT_TOKEN", "ANIMATIC_WAYPOINT_TOKEN_FILE")}
        try:
            os.environ.pop("ANIMATIC_WAYPOINT_TOKEN", None)
            os.environ["ANIMATIC_WAYPOINT_TOKEN_FILE"] = str(token_file)
            got, src = build_mod.waypoint_token()
            if got != "FIXTURE-TOKEN" or src != str(token_file):
                err(errors, f"waypoint token: the key file is not read/trimmed, "
                            f"got {(got, src)!r}")
            os.environ["ANIMATIC_WAYPOINT_TOKEN"] = "ENV-WINS"
            got, src = build_mod.waypoint_token()
            if got != "ENV-WINS" or src != "ANIMATIC_WAYPOINT_TOKEN":
                err(errors, f"waypoint token: the env var must win, got {(got, src)!r}")
            os.environ.pop("ANIMATIC_WAYPOINT_TOKEN", None)
            os.environ["ANIMATIC_WAYPOINT_TOKEN_FILE"] = str(tmp / "absent-token")
            got, src = build_mod.waypoint_token()
            if got or src:
                err(errors, f"waypoint token: a missing key file must mean none, "
                            f"got {(got, src)!r}")
            token_file.write_text("   \n", encoding="utf-8")
            os.environ["ANIMATIC_WAYPOINT_TOKEN_FILE"] = str(token_file)
            got, _ = build_mod.waypoint_token()
            if got:
                err(errors, "waypoint token: a blank key file must mean none")
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
