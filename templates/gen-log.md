# L01 generation log — the archaeology of attempts

> Append-only. One entry per attempt, newest at the bottom. This file holds the
> mess on purpose: failed prompts, near misses, and happy accidents are its
> material. `cards.yaml` holds only the current prompt and approved outputs;
> this file holds everything else.
>
> Entry anatomy:
>   ## DATE · <slug> · a<N>      (attempt number per slug)
>   intent:   what I was trying to change and why
>   delta:    what changed vs the previous attempt
>   image:    the image prompt (or "unchanged")
>   video:    the video prompt (or "unchanged")
>   output:   file refs of what came out
>   verdict:  worked / interesting-but-wrong / failed / not-yet-run
>   keep:     fragments worth banking for this or other cards
>   surprise: happy accidents worth revisiting later
>
> Agents append entries when iterating; Ryan steers in chat. "keep" and
> "surprise" lines are how good accidents get mined for other cards later.
>
> Iteration discipline (one variable at a time):
>   engine:  which tool/model (e.g. "local-steamy" vs "fal:h3-max/reference-to-video")
>   params:  seed, resolution, duration, expansion mode, aspect
>   expanded: expanded_prompt saved as media/<slug>/attempts/<slug>-a<N>.expanded.txt
>            (the diagnostic: what the model heard vs what we asked)
>   delta:   name the ONE variable changed vs the previous attempt
>            (prompt text / seed / engine / params). Same prompt + new seed is a
>            seed test, not a prompt test. Outputs download into media/<slug>/attempts/.

## 2026-09-05 · jungle-plantation · a1
- intent: first drafts from the (Visual:) brief in talk.md, no runs yet
- delta: baseline
- image: split diptych, mirror composition, identical rolling tree line; left dense luminous jungle (light shafts, fireflies, alive), right the same trees pruned into straight rows, slightly desaturated, nothing moves; single soft vertical seam; one shared horizon; 16:9 painterly realism (full text in cards.yaml)
- video: slow 20s push-in toward the seam; only the jungle half moves (canopy sway, drifting light, firefly pulse); plantation half perfectly still, as if paused; loopable
- output: none yet
- verdict: not-yet-run (drafted; pipeline TBD)
- keep: "the stillness of the right half IS the statement" — the core motion idea; may generalize to any split that contrasts living commons vs managed enclosure
- surprise: —

## 2026-09-05 · jungle-plantation · a2
- intent: first real run (test) — see if the split concept + half-motion works at all
- delta: first real run; text-to-video test — image prompt + video prompt concatenated into ONE prompt (Ryan)
- engine: fal.ai minimax h3 text-to-video
- params: 1344x768 (~768P), 24fps, 6.6s, h264 + aac (diegetic audio present), seed TBD
- expanded: not saved (Ryan has the fal response if we want it)
- output: media/jungle-plantation/attempts/jungle-plantation-a2.mp4 (renamed from fal CDN name)
- verdict: interesting-but-wrong — concept lands, execution drifts
- keep: "left half moves, right half perfectly still" READ perfectly; the stillness of the right half IS the statement — motion direction confirmed working
- surprise: the split reads as two different ecosystems (tropical broadleaf jungle vs planted conifer rows), not one landscape tended two ways — the "same trees" instruction was lost. The diptych *idea* survives it, but the deeper point (whose hands, not which trees) needs the same species mirrored
- next: (1) MIRROR DECISION (Ryan 2026-09-05): likes the mirror (same species both halves) but it may not be worth the fight — accept the two-ecosystem diptych for now; a still-first attempt (identical trees) stays an open cheap experiment, not a blocker; (2) final cut should be a short loop (~6s) or cut before end-drift; (3) if we refine: state species explicitly in the prompt ("the same grove of oak trees on both sides") rather than "same trees"

<!-- append below this line -->
