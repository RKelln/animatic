---
type: Talk
format-version: 1.0
content-version: 1
slug: code-fences-warned
title: "Code fences, warned"
theme: workshop
test-expect: warned
status: "composite fixture (spec: Text, fenced code; checks 35 and 36) - a fence that never closes ends at the end of its screen (before the next shot, before a movement heading, or at the end of the file) and warns (check 35); an empty fence and a whitespace-only fence warn (check 36) and show nothing."
---
# Code fences, warned

<!-- shot -->
### Never closed, then a shot

`````
this fence has no closer
<!-- shot -->
### The shot ends it

The words after the shot are spoken.

<!-- shot -->
### Empty

```
```

Spoken after an empty fence.

<!-- shot -->
### Blank only

~~~
   

~~~

Spoken after a blank fence.

<!-- shot -->
### Never closed, then a movement

````
still open at the movement heading

## Movement 1 · The end

<!-- shot -->
### Never closed, end of file

~~~~
last lines of the file
are inside the fence
