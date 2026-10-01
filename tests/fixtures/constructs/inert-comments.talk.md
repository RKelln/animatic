---
type: Talk
format-version: 1.0
content-version: 1
slug: inert-comments
title: "Inert comments"
theme: workshop
status: "construct fixture (spec §0 principle 4) - non-directive comments are inert, always; adding, moving, or removing them changes no output."
---
<!-- provenance: this whole deck is a comment-inertness test -->

<!-- shot -->
### Screen one

A paragraph between comments. None of the comment text speaks, renders, or warns.

A trailing comment never speaks. <!-- a note on the same line as prose -->

A multi-line trailing one does not either. <!-- this note
runs over two lines -->

<!-- an inert comment sitting between blocks -->

### Screen two

This heading opened no new screen: a non-shot comment never closes one.

<!-- another inert comment, right before the end -->
