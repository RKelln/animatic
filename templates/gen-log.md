# Generation log — the archaeology of attempts

> Deck copies: retitle this line to `<slug> generation log` (e.g. "my-talk
> generation log") — the log belongs to one deck's media pipeline.
>
> Append-only. One entry per attempt, newest at the bottom. This file holds the
> mess on purpose: failed prompts, near misses, and happy accidents are its
> material. `cards.yaml` holds only the current prompt and approved outputs;
> this file holds everything else.
>
> **MUST — the entry minimum (spec §11):** every entry opens
> `## <ISO date> · <slug> · a<N>` and carries `intent`, `delta`, `verdict`,
> `keep`, `surprise` (`keep`/`surprise` write `—` when empty). Attempt
> numbers are per-slug and monotonic. Entries are never reordered,
> renumbered, or edited.
>
> **SHOULD — this template's fuller anatomy:** entries that ran a real
> generation also record:
>   intent:   what I was trying to change and why
>   delta:    what changed vs the previous attempt
>   image:    the image prompt (or "unchanged")
>   video:    the video prompt (or "unchanged")
>   engine:   which tool/model (e.g. "fal:h3-max/reference-to-video")
>   params:   seed, resolution, duration, expansion mode, aspect
>   expanded: expanded_prompt saved as media/<slug>/attempts/<slug>-a<N>.expanded.txt
>            (the diagnostic: what the model heard vs what we asked)
>   output:   file refs of what came out
>   verdict:  worked / interesting-but-wrong / failed / not-yet-run
>   keep:     fragments worth banking for this or other cards
>   surprise: happy accidents worth revisiting later
>
> The MUST set is the contract (spec §11); the SHOULD fields make an attempt
> reproducible and mineable — omit them only when an attempt ran nothing.
>
> Iteration discipline (one variable at a time):
>   delta:   name the ONE variable changed vs the previous attempt
>            (prompt text / seed / engine / params). Same prompt + new seed is a
>            seed test, not a prompt test. Outputs download into
>            media/<slug>/attempts/.
>
> Agents append entries when iterating; you steer in chat. "keep" and
> "surprise" lines are how good accidents get mined for other cards later.

<!-- append below this line -->
