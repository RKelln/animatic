# Visual style — defaults for media cards

> Cascade: this brief applies to every card in `cards.yaml` unless the card
> overrides a field with its own `style:` block. Any key may appear; unknown keys
> pass through into prompt assembly. The rule: closer wins.

## Art direction

Decide this first. Until then the tokens below are safe placeholders so generation
drafts have something to inherit.

## Tokens

- aspect: 16:9
- motion: slow, smooth, minimal inter-frame change; human timescales; no fast cuts, no whip zooms
- motion budget: stills + Ken Burns are the DEFAULT for every shot. Video generation only when motion/action is critical to understanding or impact (e.g. jungle-plantation's half-moves/half-still statement). A shot without a motion reason gets a still.
- camera: gentle drift, kb-in / kb-out preferred; any camera move must feel like breathing, not action
- palette: TBD (CVD-safe; avoid saturated red/blue pairs) — until then: natural, desaturated-leaning, one accent family
- text overlays: sentence case, grade-6 wording, no em dashes, one idea per card
- mood: warm, civic, curious; never alarmist, never sentimental
- rendering: painterly realism preferred over photo-slick; visible authorship ok 
- negative (common): lens flare, watermarks, text artifacts, hands, crowds, horror lighting, "AI" aesthetics (glow edges, plastic skin)

## Engine notes

See `docs/media-engines.md`. Suggested two-pass posture: LOCAL first (free, for bulk
exploration: many cheap candidates reviewed later), then a cloud pass (for example
fal.ai) for the shortlist and finals where quality demands it. The talk format stays
engine-agnostic and gen-log.md records `engine:` per attempt. Sensible defaults:
video clips 10-15s max (engine cap 15s), 768p, 16:9, diegetic audio muted in deck
backgrounds, seed recorded every attempt, expansion mode balanced for iteration /
quality for finals.

## Cards may override

Example (see `letters` in cards.yaml): a card can restate mood, palette, or any
token for its own shot. Overrides are explicit and local; they never leak to
sibling cards.
