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
import { attachInstrumentLayer } from './instruments/orchestra.js';
import { MOCK_BOOT_SEQUENCE } from './mock/state.js';
import { MOCK_INSTRUMENTS, MOCK_STATUSES } from './mock/instruments.js';

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

// The DEMO instruments arrive the only way anything ever will: registered.
for (const def of MOCK_INSTRUMENTS) {
  window.JARVIS_OS.registries.instruments.register(def);
}
for (const [id, status] of Object.entries(MOCK_STATUSES)) {
  window.JARVIS_OS.bus.emit('instrument-status-changed', { id, status });
}

// The mock boot: state transitions land regardless of motion preference --
// reduced motion quiets the ANIMATIONS (the CSS owns that), never the truth
// of what state the system is in. One stateId drives root and core alike.
for (const step of MOCK_BOOT_SEQUENCE) {
  setTimeout(() => {
    applySystemState(root, step.model.stateId);
    updateCore(core, step.model);
  }, step.at);
}
