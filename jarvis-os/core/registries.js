// core/registries.js -- the system: one bus, ten registries, one vocabulary.
//
// createSystem() is the OS's spine. Every registrable kind from the goals
// document gets its registry on the shared bus, and the goals' own event
// vocabulary is documented before anything can speak. Nothing here renders;
// the shell subscribes in a later slice.

import { EventBus } from './events.js';
import { Registry } from './registry.js';
import { KINDS } from '../types/contracts.js';

/**
 * The goals document's event vocabulary, verbatim in meaning, kebab in
 * spelling. Registry lifecycle events (kind-registered and friends) are
 * documented by each Registry at construction.
 * @type {[string, string][]}
 */
export const GOAL_EVENTS = [
  ['instrument-status-changed', 'an instrument moved between its states'],
  ['action-requested', 'someone asked an instrument to act'],
  ['action-started', 'an action began'],
  ['action-progressed', 'an action reported progress'],
  ['action-completed', 'an action finished'],
  ['action-failed', 'an action failed'],
  ['approval-required', 'an action waits on explicit approval'],
  ['notification-created', 'something wants attention'],
];

/** registry property name per kind -- 'data-provider' -> dataProviders */
const PLURAL = {
  instrument: 'instruments',
  capability: 'capabilities',
  panel: 'panels',
  command: 'commands',
  action: 'actions',
  event: 'events',
  'data-provider': 'dataProviders',
  plugin: 'plugins',
  permission: 'permissions',
  theme: 'themes',
};

/**
 * @returns {{bus: EventBus, registries: Record<string, Registry>, kinds: string[]}}
 */
export function createSystem() {
  const bus = new EventBus();
  for (const [type, description] of GOAL_EVENTS) bus.document(type, description);

  /** @type {Record<string, Registry>} */
  const registries = {};
  for (const kind of KINDS) {
    // A kind PLURAL forgot must not land under the key "undefined" -- the
    // kind's own name is the honest fallback, and a test pins the coverage
    // so the drift is a named red at build time, not a silent burial.
    const key = Object.hasOwn(PLURAL, kind) ? PLURAL[kind] : kind;
    registries[key] = new Registry(kind, bus);
  }

  return { bus, registries, kinds: [...KINDS] };
}
