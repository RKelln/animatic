# Animatic

A personal system for writing talks, lectures, and workshops as scripts, and
rendering them as films. Named for the animatic: the timed, moving pre-visual of
a film. The automatic ring is intentional: agents do the assembly, Ryan directs
and curates.

## What a talk is here

One plain-text file per talk (the "talkfile") reads like a video-essay narration
script. The spoken words are the default text; visual shots drop in where the
picture changes; on-screen text is rare and explicit.

The same file renders as:
- present view: cinematic slides for the live talk (image-forward, slow motion, few words)
- document view: the spoken text as prose with visuals embedded = PDF handout and scrolling web page
- recorded narrated web version and YouTube video (audio captured live, sliced per slide by the advance timeline; no hand-timed subtitles)

## Repo layout

- `docs/format-spec-v1.md` — the talkfile grammar (normative; v1.0 draft, hardening 2026-09-08)
- `docs/format-spec.md` — retired v0.5 (superseded marker only; see v1)
- `docs/media-pipeline.md` — media cards, generation log, style cascade, engine posture
- `docs/engine-decision.md` — builder spike decision record (engine, PDF path, parse model)
- `templates/` — starter media card set (style, cards, gen-log)
- `build.py` + `talkparse.py` + `mediaresolve.py` + `render.py` — the builder (E2 spike):
  one talkfile in, three outputs out: present view (own-pager deck, VO in
  speaker notes), document view (static HTML handout, print-to-PDF via print CSS),
  cues.json (ordered slide id to script text for the future controller), plus a
  media-manifest.json resolution audit. Generated output lives in `out/` (gitignored).
- `check.py` — the deterministic check suite: the full 1-28 check register
  (spec §6/§7/§10/§11) with the fatal/warning/info/report taxonomy and
  `--strict` (warnings fatal). See `python3 check.py --register`.
- `corpus.yaml` — the machine-local content-root declaration the corpus
  harness (check 21) scans; a shipped copy rewrites its paths.

### Build

    python3 build.py <talkfile> [--out OUTDIR]

### Check

    python3 check.py <talkfile> [--strict] [--cues out/cues.json]

`check` exits 0 on a clean deck, 1 on any fatal (or, under `--strict`, any
warning), 2 on usage errors. Importable: `from check import check_file` is the
per-deck seam the future `animatic` wrapper and the corpus harness drive.

### Corpus check (register 21)

    python3 build.py --corpus              # roots declared in corpus.yaml
    python3 build.py --corpus <root>       # scan one directory as a corpus

Runs the full check over every deck under the declared content roots —
per-deck PASS/FAIL with finding counts, cross-deck slug collisions (check 5)
once, a shared-bank health sweep, and the tag drift / coverage reports
(spec §10) across deck and wiki concept tags. Reads only; never writes into a
content root; deterministic output. Strict variant: `python3 check.py
--corpus [ROOT] --strict` (warnings become deck failures).

Specimen (read-only input, TPL repo):

    python3 build.py ~/talks/decks/L01-opening-talk/talk.md

Deterministic output; re-running rebuilds the same bytes. See
`docs/engine-decision.md` for the decisions encoded in the builder.

## Instances

- TPL Applied AI residency (first deployment): `~/talks/decks/` — content, banks, and per-talk files; its README points here for the spec.

## Related

- Hermes skill `talkfile-decks` (creative/) — authoring workflow (draft decks from content banks)
- Kanban board `animatic` — build tickets (E1-E5, T01-T15 hardening)
- Controller (Phase 2): live captions + voice/script advance, designed as a Peripherous plugin family — design brief t_dc90108c on the `peripherous` board

Status: format v1.0 draft in hardening (`docs/format-spec-v1.md`); the
grammar freezes behind a Ryan gate (kanban T12), then v1.0 ships.
