# Media pipeline — how a talk's visuals live and get made

Migrated 2026-09-05 from the TPL instance conventions. Per-talk media lives
under `media/` next to the talkfile; humans write the talk, agents run the
pipeline, Ryan approves every final.

## Files per deck (one set each)

| File | Role | Who edits |
|---|---|---|
| `talk.md` | the talk: VO + shots. One file | Ryan (and agents, in chat) |
| `media/cards.yaml` | CURRENT state per visual: brief, live prompt, approved outputs, credit/licence/alt | Agent drafts, Ryan approves |
| `media/gen-log.md` | ARCHAEOLOGY: append-only attempts with intent/delta/verdict/keep/surprise | Agent appends while iterating |
| `media/style.md` | deck visual defaults; cards inherit unless overridden | Ryan (with agent) |
| `media/<slug>/attempts/` | every generated file + saved expanded_prompts, one attempt per file | agent |
| shared `_media/library.yaml` | media reused across talks + third-party credits | agent |

## Card lifecycle

idea > brief > prompting > candidates (local bulk) > shortlist > approved.
Shot refs in talk.md are extensionless slugs. Resolution order:
deck `media/cards.yaml` -> deck `media/` dir -> shared `library.yaml`.
Type and file format live in the card, never in the script.

## Current state vs archaeology (the split that makes iteration sane)

- `cards.yaml` is the current state: the live prompt and approved outputs. Clean, small, what the builder reads.
- `gen-log.md` is the archaeology: every attempt records intent (what was being changed and why), delta (ONE variable: prompt text / seed / engine / params), outcome, and two mining fields: `keep` (fragments worth banking for other cards) and `surprise` (happy accidents worth revisiting).
- Iteration discipline: same prompt + new seed is a seed test, not a prompt test. Save the engine's expanded_prompt per attempt as `<slug>-a<N>.expanded.txt` beside the output; it is the diagnostic for what the model heard vs what was asked.

## Style cascade

Deck `style.md` applies to every card unless a card overrides a field with its
own `style:` block. Unknown keys pass through into prompt assembly. Later: a
program-level style layer above the deck level; closer always wins.

## Engine posture (2026-09-05)

Two-generation: LOCAL first (steamy box, images only) for bulk overnight
exploration, many candidates cheap, reviewed in the morning; then a FAL pass
(fal.ai, H3 Max for video) for the shortlist and finals. Engines are per-attempt
fields in gen-log.md, never part of the talk format.

Engine mechanics (endpoints, params, pricing, expanded_prompt/seed behavior,
the built-in Hermes toolset) live in `media-engines.md`; the two legs are
operated by the `fal-gen` and `local-gen` Hermes skills.

Defaults: video clips 10-15s max (engine cap 15s), 768p, 16:9, diegetic audio
muted in deck backgrounds, seed recorded every attempt, prompt expansion
balanced for iteration / quality for finals.

Motion budget: stills + Ken Burns are the default for every shot. Video
generation only when motion/action is critical to understanding or impact. A
shot without a motion reason gets a still.

Secrets: provider keys live in env/config only, never in the repo.
