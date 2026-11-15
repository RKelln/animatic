# Media engines: what generates deck media, and how to call it

Reference for the generation engines behind a deck's media. Card and prompt
conventions live in [media-pipeline.md](media-pipeline.md); this file covers the
engines themselves: endpoints, parameters, pricing, what comes back, and working
conventions. Cards and prompts stay engine-agnostic; the engine appears only as a
per-attempt field in the generation log (`gen-log.md`). Animatic works without any
of this: media can be files you made or found, and generation is optional.

Verify prices and parameters against the provider before relying on them.

## Engine posture

- **Cloud (fal.ai, MiniMax H3 Max):** finals and all video.
- **Local (for example ComfyUI):** bulk image candidates, many seeds, cheap,
  reviewed later. Images only; local video is not practical on a consumer GPU.
  Local engines never return an expanded prompt (ComfyUI runs your prompt
  verbatim), so record the prompt and full parameters in the log entry: the
  prompt is what the model heard. Tag the engine in the log, for example
  `local-comfyui`.

## fal.ai — MiniMax H3 Max family

Post-trained H3 variant tuned for prompt adherence and aesthetics. Agent-readable
surface per model: `https://fal.ai/models/minimax/h3-max/<task>/llms.txt`.
**Rule: fetch the model's llms.txt before any run campaign** — it carries the
live input/output schema, the current pricing note, and usage examples. Schemas
below were verified against llms.txt in September 2026.

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

### Parameters

| Param | Values | Default |
|---|---|---|
| `prompt` | required | — |
| `duration` | 5-15s | 5 |
| `resolution` | `480P` / `768P` | `768P` |
| `prompt_expansion_mode` | `balanced` (~1s rewrite) / `quality` (~30s richer) | `balanced` |
| `aspect_ratio` | t2v: 21:9 / 16:9 / 4:3 / 1:1 / 3:4 / 9:16; r2v: same + adaptive. **i2v has NO aspect_ratio param** — output aspect follows `image_url`, so crop/export the input to the aspect you want | 16:9 (t2v), adaptive (r2v) |
| `seed` | integer, optional; per-endpoint return behavior, see below | random when omitted |
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
- `seed` — returned by **reference-to-video only** (required field, "Base seed
  for reproducing the generation"). Record it per attempt; it is what makes an
  r2v run reproducible even when you did not pass a seed.
- `timings` — inference seconds (when the route reports them).

**Seed behaviour is per endpoint:**

| Endpoint | seed in output schema? |
|---|---|
| text-to-video | NO — never echoed. Pass an explicit seed + record it yourself, or the run is unreproducible |
| image-to-video | NO — same rule |
| reference-to-video | YES — returned as `seed` ("Base seed for reproducing the generation") |

If you omit the seed on text-to-video or image-to-video you cannot reproduce the run;
on reference-to-video the response tells you what was used.

### Pricing

Rates in September 2026, per second of output (verify before a campaign; the
model's `llms.txt` carries the current rate and any promotion):

| Endpoint | 480p | 768p |
|---|---|---|
| text-to-video | $0.05 | $0.08 |
| image-to-video | $0.05 | $0.08 |
| reference-to-video | $0.05 | $0.08 |

Launch promotions existed and expired without notice, with rates jumping to four
times the promo price the next day. Reference images bill as tokens: the first
4096 tokens are included (about four 1024x1024 images), then about $0.02 per 1k
tokens. A 10 s 768p clip is about $0.80. A deck using video as a motion accent
(5 to 10 clips) is about $4 to $8. Text-only renders and CSS Ken Burns cost nothing.

### Conventions that follow

- Videos arrive with diegetic audio baked in: deck backgrounds default to
  muted; sound becomes a deliberate choice per clip.
- Duration cap 15s per clip. Shots longer than that get CSS Ken Burns on a
  still, or split into 2 clips. Loop-friendly cuts ~6s with a final frame
  identical to the first.
- Expansion: `balanced` for iteration, `quality` for finals.
- `FAL_KEY` is read from the environment only, never the repo. Export it in
  the session when a direct API call is made.
- Defaults for deck media: 10-15s max, 768p, 16:9, seed recorded every attempt.
