#!/usr/bin/env node
/*
 * tools/check-live-js.js — behaviour check for the live-capture module.
 *
 * The present view's capture code cannot be exercised in CI (getDisplayMedia
 * needs a human at a picker), so this harness runs render.py's LIVE_JS against
 * a stub DOM and asserts the two properties the module exists for:
 *
 *   1. one session per key: hosts sharing a `live_group` share one stream
 *   2. frame cost is gated on visibility: only the active slide holds a sink,
 *      and re-attaching on arrival reuses the same session (no second prompt)
 *
 * Usage:  node tools/check-live-js.js <extracted-live-js-file>
 * Extract with: python3 -c "import render; open('/tmp/live.js','w').write(render.LIVE_JS)"
 */
"use strict";

const fs = require("fs");
const vm = require("vm");

const path = process.argv[2];
if (!path) {
  console.error("usage: node tools/check-live-js.js <live-js-file>");
  process.exit(2);
}
const source = fs.readFileSync(path, "utf8");

const failures = [];
function check(name, condition, detail) {
  if (condition) {
    console.log("  ok   " + name);
  } else {
    console.log("  FAIL " + name + (detail ? "  (" + detail + ")" : ""));
    failures.push(name);
  }
}

function makeClassList(initial) {
  const set = new Set(initial || []);
  return {
    contains: (c) => set.has(c),
    add: (c) => set.add(c),
    remove: (c) => set.delete(c),
    _set: set,
  };
}

function makeVideo() {
  return {
    tag: "video",
    srcObject: null,
    paused: true,
    playCount: 0,
    play() {
      this.paused = false;
      this.playCount++;
      return Promise.resolve();
    },
    pause() {
      this.paused = true;
    },
  };
}

function makeHost(slug, group, slide) {
  const els = {
    video: makeVideo(),
    status: { textContent: "" },
    start: null,
    stop: null,
  };
  const handlers = {};
  const host = {
    attrs: { "data-live-slug": slug },
    state: "idle",
    _slide: slide,
    getAttribute(k) {
      if (k === "data-live-state") return this.state;
      return this.attrs[k] !== undefined ? this.attrs[k] : null;
    },
    setAttribute(k, v) {
      if (k === "data-live-state") this.state = v;
      else this.attrs[k] = v;
    },
    closest(sel) {
      return sel === ".animatic-slide" ? this._slide : null;
    },
    querySelector(sel) {
      if (sel === "video.live-surface") return els.video;
      if (sel === ".live-status") return els.status;
      if (sel === ".live-start") return els.start;
      if (sel === ".live-stop") return els.stop;
      return null;
    },
  };
  if (group) host.attrs["data-live-group"] = group;

  els.start = {
    disabled: false,
    addEventListener: (ev, fn) => (handlers.start = fn),
    _fire: () => handlers.start && handlers.start(),
  };
  els.stop = {
    disabled: false,
    addEventListener: (ev, fn) => (handlers.stop = fn),
    _fire: () => handlers.stop && handlers.stop(),
  };
  host._els = els;
  return host;
}

function makeSlide() {
  return { classList: makeClassList(["animatic-slide", "active"]), id: null };
}

// ---- the world ------------------------------------------------------------

const slideA = makeSlide();
slideA.classList.remove("active");
const slideB = makeSlide();
slideB.classList.remove("active");
const slideC = makeSlide();
slideC.classList.remove("active");

const hostWindow = makeHost("live-window", null, slideA);
const hostBare = makeHost("live-bare", null, slideB);
const hostPairA = makeHost("live-pair-a", "demos", slideA);
const hostPairB = makeHost("live-pair-b", "demos", slideB);
const slides = [slideA, slideB, slideC];
const hosts = [hostWindow, hostBare, hostPairA, hostPairB];

const rowsEl = {
  children: [],
  set textContent(v) { if (v === "") this.children = []; },
  get textContent() { return ""; },
  appendChild(c) { this.children.push(c); },
};
const panelEl = {
  open: false,
  classList: {
    contains: () => panelEl.open,
    add: () => { panelEl.open = true; },
    remove: () => { panelEl.open = false; },
  },
};
const docHandlers = {};
const created = [];

const trackStops = [];
function makeStream(label) {
  const track = {
    label,
    kind: "video",
    addEventListener() {},
  };
  return {
    getVideoTracks: () => [track],
    getTracks: () => [{ stop: () => trackStops.push(label), kind: "video" }],
    _label: label,
  };
}

const pendingPrompts = [];
const navigatorStub = {
  mediaDevices: {
    getDisplayMedia(constraints) {
      navigatorStub._lastConstraints = constraints;
      return new Promise((resolve, reject) => pendingPrompts.push({ resolve, reject }));
    },
  },
};

const documentStub = {
  querySelectorAll(sel) {
    if (sel === "[data-live-surface]") return hosts;
    if (sel === ".animatic-slide") return slides;
    return [];
  },
  getElementById(id) {
    if (id === "hookup-panel") return panelEl;
    if (id === "hookup-rows") return rowsEl;
    return null;
  },
  addEventListener(ev, fn) { docHandlers[ev] = fn; },
  createElement(tag) {
    const el = {
      tag,
      className: "",
      textContent: "",
      children: [],
      attrs: {},
      appendChild(c) { this.children.push(c); },
      setAttribute(k, v) { this.attrs[k] = v; },
      addEventListener(ev, fn) { this["on" + ev] = fn; },
    };
    created.push(el);
    return el;
  },
};

const windowStub = {
  isSecureContext: true,
  animatic: {
    go() {},
    count: () => slides.length,
    current: () => 0,
    onChange: null,
  },
};

// ---- run the module -------------------------------------------------------

function tick() {
  // promise callbacks (getDisplayMedia .then) are microtasks: every assertion
  // after a resolution has to let the queue drain, or it reads pre-state and
  // false-passes (which is exactly how the first draft of this harness lied).
  return new Promise((resolve) => setImmediate(resolve));
}

async function main() {
  console.log("live-capture module checks:");
  // The module under test is a raw script (render.py's LIVE_JS), not a module
  // export, so it is evaluated in a vm context with the stub globals. vm rather
  // than Function-constructor eval: the source comes from this repo's own
  // render.py, read from a path the caller names, and this keeps it out of the
  // host realm.
  const sandbox = {
    document: documentStub,
    navigator: navigatorStub,
    window: windowStub,
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: "LIVE_JS" });

  const keyedOnChange = windowStub.animatic.onChange;
  check("module registers a slide-change hook",
    typeof keyedOnChange === "function");

  check("no session before any click",
    hosts.every((h) => h.state === "idle"),
    hosts.map((h) => h.state).join(","));

  check("panel lists one row per session key (3 keys, 4 hosts)",
    rowsEl.children.length === 3,
    "rows=" + rowsEl.children.length);

  // activate slide A and hook the demos group from its live-pair-a host
  slideA.classList.add("active");
  keyedOnChange(0);
  hostPairA._els.start._fire();
  check("clicking start asks for a window, not a screen",
    navigatorStub._lastConstraints &&
    navigatorStub._lastConstraints.video.displaySurface === "window" &&
    navigatorStub._lastConstraints.selfBrowserSurface === "exclude",
    JSON.stringify(navigatorStub._lastConstraints));

  const stream = makeStream("arena.ai");
  pendingPrompts.shift().resolve(stream);
  await tick();

  check("the active host of the group holds a sink",
    hostPairA.state === "live" && hostPairA._els.video.srcObject === stream,
    hostPairA.state + "/" + String(hostPairA._els.video.srcObject));
  check("the same group's other host is armed, not attached",
    hostPairB.state === "armed" && hostPairB._els.video.srcObject === null,
    hostPairB.state + "/" + String(hostPairB._els.video.srcObject));
  check("an ungrouped host is untouched by the group's session",
    hostWindow.state === "idle" && hostBare.state === "idle",
    hostWindow.state + "/" + hostBare.state);

  // slide change: same session, sink moves
  slideA.classList.remove("active");
  slideB.classList.add("active");
  keyedOnChange(1);
  await tick();
  check("arriving on the other slide re-attaches the SAME stream",
    hostPairB._els.video.srcObject === stream && hostPairB.state === "live",
    hostPairB.state + "/" + String(hostPairB._els.video.srcObject));
  check("leaving detaches the first sink",
    hostPairA._els.video.srcObject === null && hostPairA.state === "armed",
    hostPairA.state);
  check("no further prompt was raised by the slide change",
    pendingPrompts.length === 0,
    "pending=" + pendingPrompts.length);

  // teardown stops the capture for every host in the group
  hostPairB._els.stop._fire();
  await tick();
  check("stop ends the track",
    trackStops.length === 1 && trackStops[0] === "arena.ai",
    trackStops.join(","));
  check("stop returns every host in the group to idle",
    hostPairA.state === "idle" && hostPairB.state === "idle" &&
    hostPairB._els.video.srcObject === null,
    hostPairA.state + "/" + hostPairB.state);

  // the panel reports hook state
  const hookedRows = rowsEl.children.filter((r) => r.attrs["data-hooked"] === "1");
  check("panel rows carry a hook marker only while hooked", hookedRows.length === 0,
    "hooked rows=" + hookedRows.length);

  console.log("");
  if (failures.length) {
    console.log("FAILED: " + failures.length + " check(s)");
    process.exit(1);
  }
  console.log("all live-capture module checks passed");
}

main();

