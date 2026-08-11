// mock/state.js -- SIMULATED DATA, clearly marked, easily removed.
//
// Everything in this module is invented. It exists so the S1 shell has a
// pulse to show; the goals document requires mock data to be separate from
// components and identified on sight -- so every visible string says (mock),
// and a test fails if that marking is ever stripped. Replacing this module
// with a real provider is S6's swap; nothing else may import from mock/.

/** @type {import('../ui/core-visual.js').CoreModel} */
export const MOCK_READY_MODEL = {
  state: 'READY',
  goal: 'No active goal (mock)',
  operation: 'Standing by (mock)',
  progress: null,
};

/**
 * The boot demonstration: starting, then ready. Times in ms from mount.
 * @type {{at: number, state: string, model: import('../ui/core-visual.js').CoreModel}[]}
 */
export const MOCK_BOOT_SEQUENCE = [
  {
    at: 0,
    state: 'starting',
    model: {
      state: 'STARTING',
      goal: 'No active goal (mock)',
      operation: 'Bringing systems up (mock)',
      progress: 30,
    },
  },
  {
    at: 1400,
    state: 'ready',
    model: MOCK_READY_MODEL,
  },
];
