// app.js -- the S1 shell wiring, and nothing more.
//
// Builds the zones from configuration, mounts the core in the central zone,
// and runs the mock boot sequence. This file is deliberately thin: every
// piece of behaviour lives in a module that takes its document and its data
// as arguments, so the wiring here is the only place that touches globals.

import { ZONES, buildLayout } from './core/layout.js';
import { applySystemState } from './core/states.js';
import { createSystem } from './core/registries.js';
import { createCore, updateCore } from './ui/core-visual.js';
import { createActivityMeter } from './core/activity.js';
import { createBrain } from './ui/brain-canvas.js';
import { createRings } from './ui/core-rings.js';
import { getState } from './core/states.js';
import { attachInstrumentLayer } from './instruments/orchestra.js';
import { createLiveStackSource, createFetchJson } from './instruments/live-stack.js';
import { MOCK_BOOT_SEQUENCE } from './mock/state.js';

// The system spine: one bus, ten registries (S2). Inert until the shell
// starts subscribing in S3; on the window so a person can inspect it --
// app.js is the one file allowed to touch globals.
window.JARVIS_OS = createSystem();

const root = document.getElementById('jarvis-os-root');
const zones = buildLayout(document, root, ZONES);

const core = createCore(document, {});
zones.get('core-stage').appendChild(core.el);

// The instrument layer: the shell subscribes BEFORE anything registers, so
// every instrument-registered event lands on open ears. The system is
// handed in as an argument -- the layer imports no registry. The handle
// rides the debug global so a person can detach or inspect it.
window.JARVIS_OS.layer = attachInstrumentLayer(
  document, window.JARVIS_OS, zones.get('core-stage'), zones.get('floating-layer'),
);

// THE REAL INSTRUMENTS. The four demo definitions are gone from the running
// page: what orbits the core now is what is actually running on this machine
// -- the voice server, the brain, whisper, kokoro, and every live Claude
// session -- read from the voice stack's own signals feed and arriving the
// only way anything ever does, registered. mock/instruments.js still exists
// as a fixture for the gate; nothing on screen comes from it.
//
// The fetch is injected rather than reached for, so these are the only
// lines that know the page has a network at all. The reader itself lives in
// live-stack.js and is driven by the gate: written inline here it was
// UNTESTED, and deleting its `res.ok` check went undetected -- which is the
// whole difference between "the feed is down" and a healthy-looking feed
// watching an empty machine, since the proxy's 502 body is a perfectly good
// object (test-adversary, 2026-08-15).
window.JARVIS_OS.live = createLiveStackSource({
  system: window.JARVIS_OS,
  fetchJson: createFetchJson(fetch, window.AbortController),
});
window.JARVIS_OS.live.start();

// S4 -- THE BRAIN. The rings and the cloud mount into the core's stage; the
// core itself imports neither, so a failure in this block leaves state, goal,
// operation and meter rendering exactly as before.
//
// THE BOOT IS REAL TRAFFIC, NOT A FAKE PULSE. A state change IS something
// happening, so it is documented and emitted like anything else, and the
// brain moves during boot because the bus is genuinely busy -- not because
// the painter was told to look alive. Documenting it HERE, after the meter
// already exists, is also the production exercise of the meter's re-read:
// a snapshot taken at construction would be permanently deaf to this event.
window.JARVIS_OS.bus.document('system-state-changed', 'the OS moved to a new state');

const activity = createActivityMeter(window.JARVIS_OS);
window.JARVIS_OS.activity = activity;

const reducedMotion = typeof window.matchMedia === 'function'
  && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const rings = createRings(document);
const brain = createBrain(document, { activity, rings, reducedMotion, tone: 'info' });
core.refs.stage.appendChild(brain.el);
core.refs.stage.appendChild(rings.el);

// The canvas needs real pixels; CSS sizes the box, this sizes the bitmap.
const sizeBrain = () => {
  const box = core.refs.stage.getBoundingClientRect
    ? core.refs.stage.getBoundingClientRect() : { width: 420, height: 420 };
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  brain.el.width = Math.max(1, Math.round((box.width || 420) * dpr));
  brain.el.height = Math.max(1, Math.round((box.height || 420) * dpr));
};
sizeBrain();
window.addEventListener('resize', sizeBrain);
brain.start();
window.JARVIS_OS.brain = brain;

// The mock boot: state transitions land regardless of motion preference --
// reduced motion quiets the ANIMATIONS (the CSS owns that), never the truth
// of what state the system is in. One stateId drives root and core alike.
for (const step of MOCK_BOOT_SEQUENCE) {
  setTimeout(() => {
    applySystemState(root, step.model.stateId);
    updateCore(core, step.model);
    window.JARVIS_OS.bus.emit('system-state-changed', { stateId: step.model.stateId });
    // The brain wears the state's tone -- and setTone repaints even with no
    // loop running, so a reduced-motion brain cannot sit on a stale colour.
    brain.setTone(getState(step.model.stateId)?.tone ?? 'info');
  }, step.at);
}
