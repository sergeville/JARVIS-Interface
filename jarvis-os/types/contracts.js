// types/contracts.js -- the registration contracts, and their validation.
//
// Everything installable in JARVIS OS is born from one of these definitions;
// the registries refuse anything that does not meet its contract, because
// "one broken instrument does not break JARVIS" starts at the front door.
// The typedefs are the documentation; validate() is the enforcement.

/**
 * @typedef {Object} InstrumentDefinition   anything the OS can represent:
 *   an agent, app, service, database, project, goal, workflow, device, API,
 *   MCP server, skill, data source, or a feature not invented yet.
 * @property {string} id
 * @property {string} name
 * @property {string} type          free vocabulary: 'agent', 'service', ...
 * @property {string} [description]
 * @property {string} [icon]
 * @property {number|string} [position]  orbit angle hint in degrees (a numeric string is honoured); layout decides, not the instrument
 * @property {string} [statusProvider]
 * @property {Object[]} capabilities
 * @property {Object[]} actions
 * @property {Object[]} panels
 * @property {Object[]} dataSources
 * @property {Object[]} permissions
 * @property {Object[]} events
 */

/**
 * @typedef {Object} CapabilityDefinition
 * @property {string} id
 * @property {string} name
 * @property {string} [description]
 * @property {string} [component]
 * @property {Object[]} [commands]
 * @property {Object[]} [actions]
 * @property {Object[]} [permissions]
 * @property {Object[]} [events]
 */

/**
 * @typedef {Object} PanelDefinition
 * @property {string} id
 * @property {string} name
 * @property {string} [kind]        text | status | metrics | list | table |
 *                                  chart | graph | log | tasks | form |
 *                                  alert | decision | custom | empty
 * @property {string} [zone]        assigned by configuration, never hard-coded
 */

/**
 * @typedef {Object} CommandDefinition
 * @property {string} id
 * @property {string} name
 * @property {string} [description]
 */

/**
 * @typedef {Object} ActionDefinition
 * @property {string} id
 * @property {string} name
 * @property {boolean} [destructive]  destructive actions can NEVER run unconfirmed
 */

/**
 * @typedef {Object} EventDefinition
 * @property {string} id
 * @property {string} [description]
 */

/**
 * @typedef {Object} DataProviderDefinition
 * @property {string} id
 * @property {string} name
 * @property {string} [kind]        mock | rest | graphql | websocket | file | mcp | agent
 */

/**
 * @typedef {Object} PluginDefinition
 * @property {string} id
 * @property {string} name
 * @property {Object} [manifest]
 */

/**
 * @typedef {Object} PermissionDefinition
 * @property {string} id
 * @property {string} [description]
 */

/**
 * @typedef {Object} ThemeDefinition
 * @property {string} id
 * @property {string} name
 */

/** The ten registrable kinds, in the goals document's own order. */
export const KINDS = [
  'instrument', 'capability', 'panel', 'command', 'action',
  'event', 'data-provider', 'plugin', 'permission', 'theme',
];

/**
 * Required fields per kind. An instrument must carry its six declaration
 * arrays (empty is fine, absent is not) -- the goals document makes them
 * part of the contract, and a definition that omits them is a definition
 * whose author never decided what the instrument declares.
 * @type {Record<string, string[]>}
 */
export const REQUIRED_FIELDS = {
  instrument: ['id', 'name', 'type', 'capabilities', 'actions', 'panels', 'dataSources', 'permissions', 'events'],
  capability: ['id', 'name'],
  panel: ['id', 'name'],
  command: ['id', 'name'],
  action: ['id', 'name'],
  event: ['id'],
  'data-provider': ['id', 'name'],
  plugin: ['id', 'name'],
  permission: ['id'],
  theme: ['id', 'name'],
};

const INSTRUMENT_ARRAYS = ['capabilities', 'actions', 'panels', 'dataSources', 'permissions', 'events'];

/**
 * Render any value printable for a refusal message without ever throwing --
 * a Symbol in a template literal, or an object whose toString throws, would
 * otherwise detonate the refusal on the very line that refuses (reviewer,
 * 2026-08-11: "the refusal is the exact line that throws").
 * @param {*} v
 * @returns {string}
 */
export function safeString(v) {
  try {
    return String(v);
  } catch (e) {
    return '[unprintable]';
  }
}

/**
 * Validate a definition against its kind's contract.
 * Never throws -- and that promise now covers hostile shapes too: a Symbol
 * kind or id, or a definition whose getters throw, is a refusal like any
 * other. The outer catch is the last line of that promise.
 *
 * @param {string} kind
 * @param {Object} def
 * @returns {{ok: boolean, reason: string|null}}
 */
export function validate(kind, def) {
  try {
    // Object.hasOwn, twice over: a kind named 'constructor' must not walk
    // the spec object's prototype chain, and a definition carrying its
    // fields only by inheritance never decided anything -- both refuse,
    // neither throws (both found by the test-adversary, 2026-08-11).
    if (typeof kind !== 'string' || !Object.hasOwn(REQUIRED_FIELDS, kind)) {
      return { ok: false, reason: `unknown kind: ${safeString(kind)}` };
    }
    if (def === null || typeof def !== 'object') return { ok: false, reason: 'definition is not an object' };
    const missing = REQUIRED_FIELDS[kind].filter((f) => !Object.hasOwn(def, f) || def[f] === undefined || def[f] === null);
    if (missing.length) return { ok: false, reason: `missing required field(s): ${missing.join(', ')}` };
    // Zero-width characters are not whitespace to trim(), but an id made of
    // them is still an id nobody can see or type.
    if (typeof def.id !== 'string' || def.id.replace(/[\u200B-\u200D\u2060\uFEFF]/g, '').trim() === '') {
      return { ok: false, reason: 'id must be a non-empty string' };
    }
    if (kind === 'instrument') {
      const notArrays = INSTRUMENT_ARRAYS.filter((f) => !Array.isArray(def[f]));
      if (notArrays.length) return { ok: false, reason: `must be arrays: ${notArrays.join(', ')}` };
    }
    return { ok: true, reason: null };
  } catch (e) {
    return { ok: false, reason: 'hostile definition -- evaluating it threw' };
  }
}
