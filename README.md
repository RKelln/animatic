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

- `docs/format-spec.md` — the talkfile grammar (authoritative, v0.5, migrated 2026-09-05)
- `docs/media-pipeline.md` — media cards, generation log, style cascade, engine posture
- `templates/` — starter media card set (style, cards, gen-log) copied from the L01 instance

## Instances

- TPL Applied AI residency (first deployment): `~/talks/decks/` — content, banks, and per-talk files; its README points here for the spec.

## Related

- Hermes skill `talkfile-decks` (creative/) — authoring workflow (draft decks from content banks)
- Kanban board `animatic` — build tickets (E1-E5)
- Controller (Phase 2): live captions + voice/script advance, designed as a Peripherous plugin family — design brief t_dc90108c on the `peripherous` board

Status: format v0.5 experiment, Ryan's feel-check in progress. Grammar is the
deliverable in flux, not a locked standard.
