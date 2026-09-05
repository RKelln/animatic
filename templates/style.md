# L01 visual style — defaults for media cards

> Cascade: this brief applies to every card in `cards.yaml` unless the card
> overrides a field with its own `style:` block. Any key may appear; unknown keys
> pass through into prompt assembly. Later we may add a program-level style above
> the deck level; the rule stays: closer wins.

## Art direction

TO DECIDE with Ryan. Until then the tokens below are placeholders grounded in
standing principles (VJ motion bar, public-copy rules) so generation drafts have
something safe to inherit.

## Tokens

- aspect: 16:9
- motion: slow, smooth, minimal inter-frame change; human timescales; no fast cuts, no whip zooms
- motion budget (Ryan 2026-09-05): stills + Ken Burns are the DEFAULT for every shot. Video generation only when motion/action is critical to understanding or impact (e.g. jungle-plantation's half-moves/half-still statement). A shot without a motion reason gets a still.
- camera: gentle drift, kb-in / kb-out preferred; any camera move must feel like breathing, not action
- palette: TBD with Ryan (CVD-safe; avoid saturated red/blue pairs) — until then: natural, desaturated-leaning, one accent family
- text overlays: sentence case, grade-6 wording, no em dashes, one idea per card
- mood: warm, civic, curious; never alarmist, never sentimental
- rendering: painterly realism preferred over photo-slick; visible authorship ok (this is an artist's talk)
- negative (common): lens flare, watermarks, text artifacts, hands, crowds, horror lighting, "AI" aesthetics (glow edges, plastic skin)

## Engine notes

See `../../_media/engine-notes.md` (agent-maintained recon). Two-generation posture
(Ryan 2026-09-05): LOCAL first (steamy box, LTX etc., free) for bulk overnight
exploration — many candidates cheap, reviewed in the morning; then a FAL pass
(fal.ai H3 Max) for the shortlist and finals where quality demands it. Two skills
will own the mechanics (local-gen vs fal-gen); the talk format stays engine-agnostic
and gen-log.md records `engine:` per attempt. Defaults that follow from the recon:
video clips 10-15s max (engine cap 15s), 768p, 16:9, diegetic audio muted in deck
backgrounds, seed recorded every attempt, expansion mode balanced for iteration /
quality for finals.

## Cards may override

Example (see `letters` in cards.yaml): a card can restate mood, palette, or any
token for its own shot. Overrides are explicit and local; they never leak to
sibling cards.
