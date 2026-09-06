# Media engines — what generates deck media, and how to call it

> Agent-maintained. Canonical reference for generation-engine mechanics in the
> ANIMATIC deck pipeline. Card and prompt conventions live in `media-pipeline.md`;
> this file covers the engines themselves: endpoints, parameters, pricing, what
> comes back, and per-engine working conventions. Cards and prompts stay
> engine-agnostic; the engine appears only as a per-attempt field in gen-log.md.
>
> Operated by two Hermes skills: `fal-gen` (cloud/fal leg: finals + all video)
> and `local-gen` (steamy/ComfyUI leg: bulk local images). This file supersedes
> `decks/_media/engine-notes.md` (2026-09-05 recon), moved here 2026-09-06 (E5)
> with corrections from live schema checks.

## Engine posture (one pipeline, two legs)

- LOCAL first when steamy is healthy: bulk image candidates overnight, many
  seeds, cheap, reviewed in the morning. Local = images ONLY (GTX 1080 Ti 11GB,
  established 2026-09-05: video is not viable on steamy).
- FAL pass for the shortlist and finals, and for ALL video (fal.ai MiniMax H3
  Max).
- Steamy status: DOWN since 2026-09-05 (GPU wedge after a kill -9 on ComfyUI:
  NV_ERR_TIMEOUT / nvidia_modeset oops, survives warm reboot; fix = full power
  cycle, PSU off 60s, then 3-5 min quiet; graceful stops only via comfy.sh stop).
  While down, the pipeline runs fal-only. Local mechanics land with E4
  (t_918106c9); when it lands, extend the `local-gen` skill rather than creating
  a sibling.

## fal.ai — MiniMax H3 Max family

Post-trained H3 variant tuned for prompt adherence and aesthetics. Agent-readable
surface per model: `https://fal.ai/models/minimax/h3-max/<task>/llms.txt`.
**Rule: fetch the model's llms.txt before any run campaign** — it carries the
live input/output schema, the current pricing note, and usage examples. Schemas
below were verified against llms.txt on 2026-09-06 and correct the 2026-09-05
recon where they disagree.

### Endpoints (fal.run / queue.fal.run both route)

| Endpoint (`/minimax/h3-max/…`) | Inputs | Use case |
|---|---|---|
| `text-to-video` | prompt only | zero-asset shots, full scene gen |
| `image-to-video` | prompt + `image_url` (first frame; output aspect follows the image) + optional `end_image_url` (last frame, first-to-last keyframe gen) | animate one approved still |
| `reference-to-video` | prompt + up to 12 refs across `reference_image_urls` / `reference_video_urls` / `reference_audio_urls` | animate our stills with style/subject refs; carry motion from a clip; add sound |

Reference-to-video details:
- Prompt refers to refs by modality + order: "Image 1 is the scene. Animate
  only its left half…".
- Video refs 2-15s each, combined ≤ 15s. Audio refs 2-15s each, combined ≤ 15s.
  Audio cannot be the only ref (pair it with at least one image or video).
- Total refs (all modalities) ≤ 12 files.

### Parameters (verified 2026-09-06)

| Param | Values | Default |
|---|---|---|
| `prompt` | required | — |
| `duration` | 5-15s | 5 |
| `resolution` | `480P` / `768P` | `768P` |
| `prompt_expansion_mode` | `balanced` (~1s rewrite) / `quality` (~30s richer) | `balanced` |
| `aspect_ratio` | text-to-video: 21:9 / 16:9 / 4:3 / 1:1 / 3:4 / 9:16 | 16:9 (t2v), adaptive (r2v) |
| `seed` | integer, INPUT ONLY (see below) | random when omitted |
| `sync_mode` | base64 response instead of CDN URL | false (keep false; download the URL) |
| `enable_safety_checker` | bool | true |

### What comes back (design-relevant)

- `video` — File object with a CDN `url`. **CDN delivery, not storage: download
  into the deck's attempts dir promptly.**
- `expanded_prompt` — the model's rewritten prompt (structured director's
  breakdown with `[Shot N]` scenes, character IDs, camera moves,
  `overall_soundscape`, `non_diegetic_music`). THE diagnostic: what the model
  heard vs what we asked. Save it per attempt as
  `<slug>-a<N>.expanded.txt` beside the output. It is null when expansion was
  disabled, left the prompt unchanged, or was done internally by MiniMax's
  hosted API — null is not an error.
- `timings` — inference seconds (when the route reports them).

**Seed correction (2026-09-06):** the 2026-09-05 recon claimed seed is
"returned on output for exact reproduction". The live llms.txt output schema
shows NO seed field — seed is input-only. To make a run reproducible, pass your
own explicit seed and record it in gen-log yourself. Same prompt + seed + params
should reproduce (provider-dependent; treat as best-effort, verify visually).

### Pricing (llms.txt, 2026-09-06)

| Endpoint | 480p /s | 768p /s | Note |
|---|---|---|---|
| text-to-video | $0.0125 (promo) | $0.02 (promo) | 75% launch promo ends **2026-09-07**, then 4x |
| image-to-video | $0.0125 (promo) | $0.02 (promo) | same promo note |
| reference-to-video | $0.05 | $0.08 | listed at FULL rate, no promo note |

Reference images bill as tokens: first 4096 tokens included (about 4 x
1024x1024 images free), then ~$0.02 per 1k tokens (1024x1024 = 1k; 2048x2048 =
4k = $0.08).

Budget shapes (post-promo unless noted): a 10s 768p t2v clip ≈ $0.20 during the
promo, ≈ $0.80 after. A deck using video as a motion accent (5-10 clips) ≈ $1-4
promo / $4-8 after. Text-only renders and CSS Ken Burns = $0.

**Pricing rule:** promo notes expire silently. llms.txt per model carries the
current note; the fal.ai pricing page is the fallback. Re-check before any run
campaign — the rates jump 4x the day after a promo ends and nothing tells you.

### Conventions that follow

- Videos arrive with diegetic audio baked in: deck backgrounds default to
  muted; sound becomes a deliberate choice per clip.
- Duration cap 15s per clip. Shots longer than that get CSS Ken Burns on a
  still, or split into 2 clips. Loop-friendly cuts ~6s with a final frame
  identical to the first.
- Expansion: `balanced` for iteration, `quality` for finals.
- `FAL_KEY` lives in `~/.hermes/.env` (env-only, never the repo). Export it in
  the session when a direct API call is made.
- Defaults for deck media: 10-15s max, 768p, 16:9, seed recorded every attempt.

## Hermes built-in toolset route (video_gen / image_gen / bfl)

Enabled 2026-09-05 on the cli platform toolsets (`config.yaml`:
`platform_toolsets.cli` includes `bfl`, `image_gen`, `video_gen`;
`video_gen: {provider: fal, model: minimax-h3}`). Toolsets bind at session
start — after enabling or changing them, a FRESH session is required.

- `video_generate` tool → FAL backend, model `minimax-h3`. Routes: text-to-video
  (prompt only), image-to-video (`image_url`), reference-to-video with IMAGE
  refs (`reference_image_urls`). No video/audio reference inputs on this
  surface — motion-transfer and audio refs require the raw fal endpoint.
- `image_generate` tool → FAL backend, FLUX 2 Klein 9B (Black Forest Labs),
  text-to-image plus image-to-image/editing with up to 9 reference images.
  License check: BFL klein 9B is non-commercial for direct downloads per the
  local-ai-image-generation recon (2026-09-05); verify the API-hosted license
  before public/commercial finals use the built-in image route.

### What the built-in surface exposes vs the raw fal queue

| Capability | Built-in tool | Raw fal endpoint |
|---|---|---|
| Result | `video`/`image` URL or local path | `video.url` + `expanded_prompt` + `timings` |
| Seed | input param only; NEVER echoed in the result | input only (same; see seed correction above) |
| expanded_prompt | NOT returned | returned (the diagnostic) |
| resolution | 360p/540p/720p/1080p (clamped onto 480P/768P) | 480P / 768P |
| aspect_ratio | 16:9, 9:16, 1:1 (+ clamped) | full set incl. 21:9, adaptive |
| audio | boolean toggle | baked diegetic audio (mute in deck) |
| negative_prompt | supported | not on this family's schema |
| refs | images only (r2v); no video/audio | images + video + audio, ≤ 12 |

**Gen-log integration:** built-in runs are fine for smoke tests and quick
candidates (precedent: rainforest-canopy a1, recorded as `engine: fal.ai
minimax h3 text-to-video (Hermes video_generate tool)` with `expanded: not
saved`). Because the tool hides expanded_prompt and never echoes seed, prefer
the RAW fal endpoint for attempts where the diagnostic matters: finalists,
`quality`-expansion runs, anything you may need to reproduce or explain. Decide
per attempt; record the engine tag honestly either way.

## Local engine (steamy) — posture only

Full mechanics land with E4 (t_918106c9), which is blocked on the steamy GPU
wedge. What holds now:

- Engine tag in gen-log: `local-steamy`.
- Local = images only. Local images never carry an expanded_prompt (ComfyUI
  runs your prompt verbatim) — record prompt + full params verbatim in the
  entry instead; the prompt IS what the model heard.
- Stack mechanics (torch ceiling, GGUF quants, klein 4B Apache-clean model,
  API workflow JSON, serve/stop discipline): see the `local-ai-image-generation`
  skill (mlops category) and its `references/steamy-klein-stack.md`.
- Overnight bulk runner + review gallery: E4 scope; when it lands, patch the
  `local-gen` skill.

## Changelog

- 2026-09-06 (E5, t_34a421d1): created. Moved + corrected the 2026-09-05 recon:
  seed is input-only; promo split per endpoint; image-to-video gained
  `end_image_url`; built-in toolset section added; engine-notes.md in
  decks/_media reduced to a pointer.
