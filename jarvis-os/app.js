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
import { MOCK_BOOT_SEQUENCE } from './mock/state.js';

// The system spine: one bus, ten registries (S2). Inert until the shell
// starts subscribing in S3; on the window so a person can inspect it --
// app.js is the one file allowed to touch globals.
window.JARVIS_OS = createSystem();

const root = document.getElementById('jarvis-os-root');
const zones = buildLayout(document, root, ZONES);

const core = createCore(document, {});
zones.get('core-stage').appendChild(core.el);

// The mock boot: state transitions land regardless of motion preference --
// reduced motion quiets the ANIMATIONS (the CSS owns that), never the truth
// of what state the system is in. One stateId drives root and core alike.
for (const step of MOCK_BOOT_SEQUENCE) {
  setTimeout(() => {
    applySystemState(root, step.model.stateId);
    updateCore(core, step.model);
  }, step.at);
}
