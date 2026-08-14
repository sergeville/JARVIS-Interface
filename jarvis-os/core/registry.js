// core/registry.js -- one registry, any kind.
//
// Everything installable lives in a registry: add, update, disable, enable,
// remove -- all without touching the shell, all announced on the bus. The
// registry refuses what its contract refuses; a refusal is a return value,
// never an exception, and never a partial write.

import { validate, safeString } from '../types/contracts.js';

/**
 * Run a registry operation with the never-throws promise enforced at the
 * boundary: hostile inputs (Symbol ids, throwing getters invoked by a
 * spread) become refusals like any other (reviewer, 2026-08-11 -- the old
 * refusal messages were themselves the throwing lines). Store writes all
 * happen after input evaluation, so a caught throw means nothing was
 * written -- the no-partial-write promise survives the catch.
 * @param {() => {ok: boolean, reason: string|null}} fn
 * @returns {{ok: boolean, reason: string|null}}
 */
function refusing(fn) {
  try {
    return fn();
  } catch (e) {
    return { ok: false, reason: 'hostile input -- evaluating it threw' };
  }
}

/**
 * Deep-clone a definition, refusing anything that is not plain data.
 * Contracts are configuration -- a definition carrying functions or other
 * unclonables has no business in a registry, and refusing it here is what
 * keeps register()'s never-throws promise while closing the aliasing hole.
 *
 * @param {Object} def
 * @returns {{ok: true, reason: null, value: Object}|{ok: false, reason: string}}
 */
function cloneDef(def) {
  try {
    return { ok: true, reason: null, value: structuredClone(def) };
  } catch (e) {
    return { ok: false, reason: 'definition must be plain data (it did not survive structuredClone)' };
  }
}

export class Registry {
  /**
   * @param {string} kind   one of contracts.KINDS
   * @param {import('./events.js').EventBus} bus
   */
  constructor(kind, bus) {
    this.kind = kind;
    this.bus = bus;
    /** @type {Map<string, {def: Object, disabled: boolean}>} */
    this.items = new Map();
    for (const verb of ['registered', 'updated', 'disabled', 'enabled', 'removed']) {
      bus.document(`${kind}-${verb}`, `a ${kind} was ${verb}`);
    }
  }

  /**
   * @param {Object} def
   * @returns {{ok: boolean, reason: string|null}}
   */
  register(def) {
    return refusing(() => {
    const verdict = validate(this.kind, def);
    if (!verdict.ok) return verdict;
    if (this.items.has(def.id)) {
      return { ok: false, reason: `duplicate id: ${def.id} -- update is the explicit path` };
    }
    // Deep-clone on the way IN: the caller keeps no pointer into the store,
    // so mutating their object after registration changes nothing here (the
    // shallow spread shared nested arrays -- test-adversary, 2026-08-11).
    // A definition that cannot clone is not plain data and is refused.
    const stored = cloneDef(def);
    if (!stored.ok) return stored;
    this.items.set(def.id, { def: stored.value, disabled: false });
    this.bus.emit(`${this.kind}-registered`, { id: def.id });
    return { ok: true, reason: null };
    });
  }

  /**
   * Patch an existing definition. The id is identity -- a patch may not
   * change it, and patching the unknown is a refusal, never an upsert.
   * @param {string} id
   * @param {Object} patch
   * @returns {{ok: boolean, reason: string|null}}
   */
  update(id, patch) {
    return refusing(() => {
    // A non-object patch is a refusal, not a TypeError on the 'in' operator
    // (test-adversary, 2026-08-11 -- it threw exactly on real data).
    if (patch === null || typeof patch !== 'object' || Array.isArray(patch)) {
      return { ok: false, reason: 'patch must be a plain object' };
    }
    const item = this.items.get(id);
    if (!item) return { ok: false, reason: `unknown id: ${safeString(id)}` };
    if ('id' in patch && patch.id !== id) return { ok: false, reason: 'a patch may not change the id' };
    const merged = { ...item.def, ...patch, id };
    const verdict = validate(this.kind, merged);
    if (!verdict.ok) return verdict;
    const stored = cloneDef(merged);
    if (!stored.ok) return stored;
    item.def = stored.value;
    this.bus.emit(`${this.kind}-updated`, { id });
    return { ok: true, reason: null };
    });
  }

  /** @param {string} id @returns {{ok: boolean, reason: string|null}} */
  disable(id) {
    return refusing(() => {
    const item = this.items.get(id);
    if (!item) return { ok: false, reason: `unknown id: ${safeString(id)}` };
    item.disabled = true;
    this.bus.emit(`${this.kind}-disabled`, { id });
    return { ok: true, reason: null };
    });
  }

  /** @param {string} id @returns {{ok: boolean, reason: string|null}} */
  enable(id) {
    return refusing(() => {
    const item = this.items.get(id);
    if (!item) return { ok: false, reason: `unknown id: ${safeString(id)}` };
    item.disabled = false;
    this.bus.emit(`${this.kind}-enabled`, { id });
    return { ok: true, reason: null };
    });
  }

  /** @param {string} id @returns {{ok: boolean, reason: string|null}} */
  remove(id) {
    return refusing(() => {
    if (!this.items.has(id)) return { ok: false, reason: `unknown id: ${safeString(id)}` };
    this.items.delete(id);
    this.bus.emit(`${this.kind}-removed`, { id });
    return { ok: true, reason: null };
    });
  }

  /**
   * @param {string} id
   * @returns {{def: Object, disabled: boolean}|undefined} disabled items
   *   included -- get answers "what is this", list answers "what is on".
   *   The def is a CLONE: nobody gets a write pointer into the store
   *   (test-adversary, 2026-08-11 -- a mutated return value corrupted it).
   */
  get(id) {
    const item = this.items.get(id);
    if (!item) return undefined;
    return { def: structuredClone(item.def), disabled: item.disabled };
  }

  /**
   * @param {{includeDisabled?: boolean}} [opts]
   * @returns {Object[]} definition clones; disabled ones only on explicit ask
   */
  list(opts = {}) {
    const out = [];
    for (const item of this.items.values()) {
      if (item.disabled && !opts.includeDisabled) continue;
      out.push(structuredClone(item.def));
    }
    return out;
  }
}
