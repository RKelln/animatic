# Media pipeline — how a talk's visuals live and get made

Per-talk media lives under `media/` next to the talkfile; humans write the
talk, agents run the pipeline, and a human approves every final.

## Files per deck (one set each)

| File | Role | Who edits |
|---|---|---|
| `talk.md` | the talk: VO + shots. One file | the author (and agents, in chat) |
| `media/cards.yaml` | CURRENT state per visual: brief, live prompt, approved outputs, credit/licence/alt | Agent drafts, author approves |
| `media/gen-log.md` | ARCHAEOLOGY: append-only attempts with intent/delta/verdict/keep/surprise | Agent appends while iterating |
| `media/style.md` | deck visual defaults; cards inherit unless overridden | the author (with agent) |
| `media/<slug>/attempts/` | every generated file + saved expanded_prompts, one attempt per file | agent |
| shared `_media/library.yaml` | media reused across talks + third-party credits | agent |

## Card lifecycle

idea > brief > prompting > candidates (local bulk) > shortlist > approved.
Shot refs in talk.md are extensionless slugs. Resolution order for a shot in
the talk's own slides:
deck `media/cards.yaml` -> deck `media/` dir -> shared media (below) -> a
`--media-remap` stand-in.
Type and file format live in the card, never in the script.

## Shared media (`_media/`, beside the deck folders)

The shared stage reads, in this order:

1. a `library.yaml` entry for the slug that has a `file:` (path relative to
   `_media/`);
2. a file named for the slug: `_media/<slug>.<ext>`, then
   `_media/<slug>/<slug>.<ext>`. No entry is needed. The type comes from the
   extension, as everywhere else.

An entry is optional. Write one for what a bare file cannot say: `alt`,
`credit`, `licence`, a `type` override (`live`), `playback`/`sound`/`still` for
video, `steps:`, or `pool:`. The entry is the card for a section's shot and for a
slide with no card of its own; a deck's own card keeps its words. A file with no
credit, entry or not, warns (check 51), because nothing else would notice the handout
credits nobody. An entry whose `file:` is not there warns (check 50) and the file
named for the slug is tried instead.
If two files match one slug (`_media/hero.png` and `_media/hero.webp`, or the
flat file and the folder one) the flat file wins, then the extension order of
`MEDIA_EXTS`, and check 50 warns. Keep one.

### Section media comes only from here

A shot that comes from a section, whether the talk includes it
(`<!-- include: -->`) or it sits on the quick-select shelf, **never** reads the
deck's `cards.yaml` or `media/`. It resolves from the shared stage only (entry,
then named file, then a `--media-remap` stand-in), so a section looks the same in
every deck. That holds for pool slugs too: `my-art` is a library pool, and a
deck card of the same name does not replace it inside a section. For a
section's shot the entry is the card: its alt, credit, licence, type and
playback apply. A `--media-remap` stand-in for the deck's `pic` does not fill a
section's `pic--lib`; name that one to stand in for it.

A section slug with no shared media is, in an ordinary include, a placeholder
plus the usual warnings. On the shelf it is fatal (check 48): nobody pages
through hidden slides, so the build stops and names the section file.

**The same slug in a slide and in a section.** If the deck owns something of the
section's slug (a card, a pool pin, or a file in `media/`), the section's shot is
renamed `<slug>--lib` (a pool's uses `<slug>--lib--NN`; a stepped card's frames
`<frame>--lib`). Every table keyed by slug then keeps them apart: `_media/<slug>.png` and
`_media/<slug>--lib.png` in the output, two rows in `media-manifest.json` and
`cues.json`, two handout images in `_media/doc/`. With no clash nothing is
renamed and output names are the slug, as before. `--quick-sections DIR` does not
move the shared library: it is always the `_media/` beside the deck's own folder,
whatever DIR is.

## Current state vs archaeology (the split that makes iteration sane)

- `cards.yaml` is the current state: the live prompt and approved outputs. Clean, small, what the builder reads.
- `gen-log.md` is the archaeology: every attempt records intent (what was being changed and why), delta (ONE variable: prompt text / seed / engine / params), outcome, and two mining fields: `keep` (fragments worth banking for other cards) and `surprise` (happy accidents worth revisiting).
- Iteration discipline: same prompt + new seed is a seed test, not a prompt test. Save the engine's expanded_prompt per attempt as `<slug>-a<N>.expanded.txt` beside the output; it is the diagnostic for what the model heard vs what was asked.

## Style cascade

Deck `style.md` applies to every card unless a card overrides a field with its
own `style:` block. Unknown keys pass through into prompt assembly. Later: a
program-level style layer above the deck level; closer always wins.

## Engine posture

Two-generation: LOCAL first (images only) for bulk overnight
exploration, many candidates cheap, reviewed in the morning; then a FAL pass
(fal.ai, H3 Max for video) for the shortlist and finals. Engines are per-attempt
fields in gen-log.md, never part of the talk format.

Engine mechanics (endpoints, params, pricing, expanded_prompt/seed behavior,
the harness's built-in toolset) live in `media-engines.md`.

Defaults: video clips 10-15s max (engine cap 15s), 768p, 16:9, diegetic audio
muted in deck backgrounds, seed recorded every attempt, prompt expansion
balanced for iteration / quality for finals.

Motion budget: stills + Ken Burns are the default for every shot. Video
generation only when motion/action is critical to understanding or impact. A
shot without a motion reason gets a still.

Secrets: provider keys live in env/config only, never in the repo.
