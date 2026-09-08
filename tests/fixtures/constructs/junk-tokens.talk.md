---
type: Talk
format-version: 1.0
content-version: 1
slug: junk-tokens
title: "The tokenizer is honest"
theme: workshop
status: "construct fixture (spec §10 unknown vocabulary; register check 25) - nothing in a shot comment is silently dropped; every unrecognized token warns by name."
test-expect: warned
---
<!-- shot: junk-host wibble=3 +bogus wobble kb=out -->

The voice survives the junk tokens; each one warned instead of vanishing. The known flag applied.
