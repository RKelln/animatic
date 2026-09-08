---
type: Talk
format-version: 1.0
content-version: 1
slug: media-resolution
title: "Media resolution order"
date: 2026-09-08
venue: Internal fixture
format: Golden deck
dur: ~1 min
theme: workshop
status: "golden deck (spec §6 resolution order) - one slug per stage: cards approved path, deck media dir, attempts highest-N, shared library, remap stand-in (standin profile), placeholder. Synthetic fixture files only."
---
<!-- shot: approved-art -->

An approved path on the card outranks the same slug's file in the deck media dir; the manifest records source cards and the approved extension.

<!-- shot: deckdir-art -->

A file in the deck media dir resolves without any declared path; the manifest records source deckdir.

<!-- shot: attempt-art -->

Attempt files under the slug's attempts dir resolve by highest N; the gen-log rows match the files, so no archaeology drift reports.

<!-- shot: both-art -->

With both a direct deck file and an attempts file present, the builder's order decides; the golden pins whichever wins so a reorder shows as a diff.

<!-- shot: lib-owl -->

A shared library entry documents the media, so the deck needs no card for it; the manifest records source library.

<!-- shot: standin-only -->

Nothing resolves for this slug in the base build: card brief, no file, placeholder with a reason. The standin profile remaps it and real beats nothing.

<!-- shot: hold-art -->

A to-find card with no file and no declared path stays a placeholder; placeholders always render and always say why.
