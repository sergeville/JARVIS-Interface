// instruments/instrument-shell.js -- one shell, any instrument.
//
// An instrument is anything the OS can represent -- agent, service, project,
// database, device, feature yet unnamed -- and this shell renders every one
// of them from its registered definition alone. Nothing here knows Archon
// from a lawnmower: the definition is the whole story. Renderers return
// refs and never re-query; the S1 doctrine.

/**
 * The twelve instrument states from the goals document, each with its own
 * visual rule in the CSS (a test holds the one-rule-per-state property).
 * Tones borrow the house vocabulary and never redefine it.
 * @type {{id: string, label: string, tone: 'ok'|'info'|'warn'|'bad'|'off'}[]}
 */
export const INSTRUMENT_STATES = [
  { id: 'unconfigured', label: 'UNCONFIGURED', tone: 'warn' },
  { id: 'configuring',  label: 'CONFIGURING',  tone: 'info' },
  { id: 'ready',        label: 'READY',        tone: 'ok'   },
  { id: 'idle',         label: 'IDLE',         tone: 'info' },
  { id: 'active',       label: 'ACTIVE',       tone: 'ok'   },
  { id: 'waiting',      label: 'WAITING',      tone: 'warn' },
  { id: 'paused',       label: 'PAUSED',       tone: 'info' },
  { id: 'blocked',      label: 'BLOCKED',      tone: 'warn' },
  { id: 'offline',      label: 'OFFLINE',      tone: 'warn' },
  { id: 'error',        label: 'ERROR',        tone: 'bad'  },
  { id: 'completed',    label: 'COMPLETED',    tone: 'ok'   },
  { id: 'disabled',     label: 'DISABLED',     tone: 'off'  },
];

const byId = new Map(INSTRUMENT_STATES.map((s) => [s.id, s]));

/**
 * The fail-closed landing spot, held OUTSIDE the list it guards (the S1
 * states lesson, applied on arrival instead of after a red pen): an
 * instrument reporting a state the vocabulary does not hold IS an error
 * condition, and it is shown as one rather than invented into something
 * calmer.
 * @type {{id: string, label: string, tone: string}}
 */
const FALLBACK = { id: 'error', label: 'ERROR', tone: 'bad' };

/** @param {string} id @returns {{id: string, label: string, tone: string}} */
export function instrumentState(id) {
  return byId.get(id) ?? FALLBACK;
}

/**
 * Short code for the roundel (one to three characters): the definition's
 * icon field if it is a short string, else the first letters of the first
 * two words of the name, else the first two letters. Pure; never throws on
 * junk.
 * @param {{icon?: string, name?: string}} def
 * @returns {string}
 */
export function abbrev(def) {
  try {
    if (typeof def.icon === 'string' && def.icon.trim().length >= 1 && def.icon.trim().length <= 3) {
      return def.icon.trim().toUpperCase();
    }
    if (typeof def.name !== 'string') return '??';
    const words = def.name.trim().split(/\s+/).filter(Boolean);
    // Array.from splits by CODE POINT: an emoji initial stays whole instead
    // of shedding half a surrogate pair into the roundel.
    if (words.length >= 2) return (Array.from(words[0])[0] + Array.from(words[1])[0]).toUpperCase();
    if (words.length === 1) return Array.from(words[0]).slice(0, 2).join('').toUpperCase();
    return '??';
  } catch (e) {
    return '??';
  }
}

/**
 * Build one orbit node for an instrument. The node is a real <button> so a
 * keyboard reaches it from day one; the S7 pass widens this, it does not
 * begin it.
 *
 * @param {Document} doc
 * @param {Object} def        a registered InstrumentDefinition (a clone --
 *                            registries never hand out live store pointers)
 * @param {string} [stateId]  initial instrument state; default 'unconfigured'
 * @returns {{el: Element, refs: Object, setState: (id: string) => void}}
 */
export function createInstrumentNode(doc, def, stateId = 'unconfigured') {
  const el = doc.createElement('button');
  el.className = 'os-instrument';
  el.setAttribute('data-instrument-id', def.id);
  el.setAttribute('type', 'button');
  // The name clips at the node's width; anything clipped is recoverable on
  // hover -- the house rule, applied where the clipping happens.
  if (typeof def.name === 'string') el.setAttribute('title', def.name);

  const roundel = doc.createElement('span');
  roundel.className = 'os-instrument__roundel';
  roundel.textContent = abbrev(def);

  const name = doc.createElement('span');
  name.className = 'os-instrument__name';
  name.textContent = def.name ?? def.id;

  const type = doc.createElement('span');
  type.className = 'os-instrument__type';
  type.textContent = def.type ?? '';

  const state = doc.createElement('span');
  state.className = 'os-instrument__state';

  if (def.demo === true) {
    const demoTag = doc.createElement('span');
    demoTag.className = 'os-instrument__demo';
    demoTag.textContent = 'DEMO';
    el.appendChild(demoTag);
  }

  for (const part of [roundel, name, type, state]) el.appendChild(part);

  const refs = { roundel, name, type, state };
  const setState = (id) => {
    const s = instrumentState(id);
    el.setAttribute('data-instrument-state', s.id);
    el.setAttribute('data-instrument-tone', s.tone);
    refs.state.textContent = s.label;
  };
  // The registry's update path changes truth; refresh is how a node hears
  // it (test-adversary + reviewer, 2026-08-11: the node was a snapshot
  // nothing ever refreshed).
  const refresh = (freshDef) => {
    refs.roundel.textContent = abbrev(freshDef);
    refs.name.textContent = freshDef.name ?? freshDef.id;
    refs.type.textContent = freshDef.type ?? '';
    if (typeof freshDef.name === 'string') el.setAttribute('title', freshDef.name);
  };
  setState(stateId);
  return { el, refs, setState, refresh };
}
