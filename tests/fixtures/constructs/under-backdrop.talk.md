---
type: Talk
format-version: 1.0
content-version: 1
slug: under-backdrop
title: "Under backdrop construct"
theme: workshop
status: "construct fixture (spec: The shot directive, flags under= and blur=; register check 32) - a backdrop that cannot resolve to a still image, blur with nothing to blur, a framed layout, and two bad values each warn by name."
test-expect: warned
---
<!-- shot: cons-a under=sample-art blur=24 -->

The backdrop resolves to a placeholder here, so check 32 says it has to be a still image.

<!-- shot: cons-b blur=12 -->

Blur with no under has nothing to soften.

<!-- shot: second-art layout=piece under=sample-art -->

A framed object has no full-bleed ground for a backdrop.

<!-- shot: junk-host under=Bad_Slug blur=999 -->

Both values are refused at the tokenizer, and check 25 names them.

<!-- shot: cons-a anchor=middle -->

An anchor value that is not top, center or bottom is refused at the tokenizer.

<!-- shot: cons-b anchor=bottom -->

Anchor with no under has nothing to place.
