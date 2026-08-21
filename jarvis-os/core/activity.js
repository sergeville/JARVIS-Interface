// core/activity.js -- the honesty layer, and the reason this slice is not
// decoration.
//
// Serge's example invented its activity: 160 pulses on a random walk plus a
// burst timer, so the brain looked busy while nothing was happening. Ported
// as-is that is a beautiful lie, and the exact fault this project has
// red-penned all week. So the pulses become REAL EVENTS. One signal crossing
// the mesh is one thing that actually happened on the bus, and with nothing
// happening the brain goes still.
//
// This module LISTENS AND NOTHING ELSE. It documents no event type and emits
// nothing, so it can never become a source of the activity it measures.
//
// THE THING IT MEASURES IS BUS TRAFFIC, NOT LIVENESS -- said plainly here
// because it is the sentence someone will otherwise decide is a bug and
// "fix" by faking pulses (voice-line red pen, finding 4). A system sitting
// perfectly still with nothing on the wire SHOULD show a still brain. If the
// boot animation is to move it, the boot must emit; that is app.js's job and
// it does it, rather than this file pretending.

const DEFAULT_HALF_LIFE = 1400;   // ms for the level to halve
const DEFAULT_IMPULSE = 0.34;     // what one event adds
const EPSILON = 1e-4;             // below this, the level IS zero
const DEFAULT_CAP = 240;          // most impulses held between drains

/**
 * @typedef {Object} ActivityMeter
 * @property {() => number} level      0..1, decaying from the last impulse
 * @property {() => Object[]} drain    impulses since the last call, each once
 * @property {() => number} dropped    impulses lost to the cap -- the ledger
 * @property {() => number} seen       events counted, ever
 * @property {() => number} sync       re-read the vocabulary; new subs made
 * @property {() => void} detach
 */

/**
 * Create the meter.
 *
 * IT SUBSCRIBES TO EVERY TYPE THE BUS ALREADY DOCUMENTS, and it re-reads
 * that vocabulary on every drain() and every level(). The re-read is the
 * whole difference between this and the version that was red-penned before
 * it was built: a set of subscriptions taken once at construction makes the
 * brain permanently deaf to anything documented later -- a plugin, a new
 * registry, the first real instrument -- and the deafness is INVISIBLE,
 * because the bus's refusedSubscribes ledger never counts a subscribe that
 * was never attempted. A meter that goes quietly blind to the newest thing
 * in the system is worse than no meter.
 *
 * There is deliberately NO second list of event names here. The bus's own
 * vocabulary is the single source, because a parallel hand-kept list is the
 * guard-living-in-the-data shape this project has now been bitten by three
 * times.
 *
 * @param {{bus: Object}} system
 * @param {{now?: () => number, halfLifeMs?: number, impulse?: number, cap?: number}} [opts]
 * @returns {ActivityMeter}
 */
export function createActivityMeter(system, opts = {}) {
  const now = typeof opts.now === 'function' ? opts.now : () => Date.now();
  const halfLife = Number.isFinite(opts.halfLifeMs) && opts.halfLifeMs > 0
    ? opts.halfLifeMs : DEFAULT_HALF_LIFE;
  const impulse = Number.isFinite(opts.impulse) && opts.impulse > 0
    ? opts.impulse : DEFAULT_IMPULSE;
  const cap = Number.isFinite(opts.cap) && opts.cap > 0
    ? Math.trunc(opts.cap) : DEFAULT_CAP;

  const bus = system?.bus;
  /** @type {Map<string, () => void>} type -> unsubscribe */
  const subs = new Map();
  /** @type {{type: string, at: number}[]} */
  let pending = [];

  let value = 0;          // the level as of `stamp`
  let stamp = now();
  let dropped = 0;        // impulses lost to the cap -- honesty's ledger
  let seen = 0;           // every event this meter has counted, ever

  const decayTo = (t) => {
    const dt = t - stamp;
    if (!(dt > 0)) { stamp = t; return; }
    value *= Math.pow(0.5, dt / halfLife);
    // An explicit floor, because exponential decay never reaches zero on its
    // own -- it lands on a denormal and the painter keeps painting a brain
    // nobody can see, forever. "Reaches exactly 0" has to be made true, not
    // asserted (voice-line red pen, finding 5).
    if (value < EPSILON) value = 0;
    stamp = t;
  };

  const record = (type) => {
    const t = now();
    decayTo(t);
    value = Math.min(1, value + impulse);
    seen += 1;
    // The buffer is CAPPED and the loss is COUNTED. Unbounded, a reduced-
    // motion brain (which never drains) or a hidden tab (whose rAF is
    // throttled) grows this list for the life of the session, and then
    // resumes by firing a burst of events that happened minutes ago -- a
    // worse lie than the fake pulses, because it looks like real traffic.
    if (pending.length >= cap) {
      pending.shift();
      dropped += 1;
    }
    pending.push({ type, at: t });
  };

  /**
   * Re-read the bus vocabulary and subscribe to anything new.
   * @returns {number} how many new subscriptions were made
   */
  const sync = () => {
    if (!bus || typeof bus.on !== 'function' || !bus.vocabulary) return 0;
    let added = 0;
    for (const type of bus.vocabulary.keys()) {
      if (subs.has(type)) continue;
      const off = bus.on(type, () => record(type));
      subs.set(type, typeof off === 'function' ? off : () => {});
      added += 1;
    }
    return added;
  };

  sync();

  // AND the immediate half: polling on drain()/level() narrows the deaf
  // window but does not close it, because whoever documents a type usually
  // emits it in the very next line -- before anything polls. My own gate
  // caught that, on my own fix. The bus now announces a new type the moment
  // it is documented, and the meter subscribes right then.
  const unwatch = typeof bus?.onDocument === 'function' ? bus.onDocument(() => sync()) : () => {};

  return {
    level() {
      sync();
      decayTo(now());
      return value;
    },
    drain() {
      sync();
      const out = pending;
      pending = [];
      return out;
    },
    dropped: () => dropped,
    seen: () => seen,
    sync,
    detach() {
      unwatch();
      for (const off of subs.values()) off();
      subs.clear();
      pending = [];
    },
  };
}

export const ACTIVITY_EPSILON = EPSILON;
