// core/states.js -- the operating system's own states.
//
// Eight states, from the goals document, each visually distinct (the CSS
// carries one rule per id; a test holds that true). The tone vocabulary is
// the house one: green means up in every world, amber means attention, red
// means bad -- states borrow those meanings, they never redefine them.

/**
 * @typedef {Object} SystemState
 * @property {string} id
 * @property {string} label  what the screen says
 * @property {'ok'|'info'|'warn'|'bad'} tone
 */

/** @type {SystemState[]} */
export const SYSTEM_STATES = [
  { id: 'starting',       label: 'STARTING',       tone: 'info' },
  { id: 'ready',          label: 'READY',          tone: 'ok'   },
  { id: 'working',        label: 'WORKING',        tone: 'info' },
  { id: 'degraded',       label: 'DEGRADED',       tone: 'warn' },
  { id: 'offline',        label: 'OFFLINE',        tone: 'warn' },
  { id: 'maintenance',    label: 'MAINTENANCE',    tone: 'info' },
  { id: 'emergency-stop', label: 'EMERGENCY STOP', tone: 'bad'  },
  { id: 'recovering',     label: 'RECOVERING',     tone: 'warn' },
];

const byId = new Map(SYSTEM_STATES.map((s) => [s.id, s]));

/**
 * Apply a system state to the shell root.
 *
 * Unknown ids fail CLOSED: the shell goes to 'degraded' -- the honest word
 * for "the OS was told something it does not understand" -- and the caller
 * is told the apply was refused. It never throws (one bad input must not
 * break JARVIS) and it never applies a word the vocabulary does not hold.
 *
 * @param {Element} rootEl
 * @param {string}  id
 * @returns {boolean} true if the requested state was applied as asked
 */
export function applySystemState(rootEl, id) {
  const known = byId.has(id);
  const state = known ? byId.get(id) : byId.get('degraded');
  rootEl.setAttribute('data-os-state', state.id);
  rootEl.setAttribute('data-os-tone', state.tone);
  return known;
}

/**
 * @param {string} id
 * @returns {SystemState|undefined}
 */
export function getState(id) {
  return byId.get(id);
}
