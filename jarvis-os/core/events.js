// core/events.js -- the event bus: the ONLY channel between modules.
//
// Instruments communicate through documented events, never by reaching into
// unrelated components -- the goals document's rule, enforced two ways here:
// an event type must be documented before it may be emitted (an undocumented
// emit is refused, not delivered), and a listener that throws is isolated so
// one broken subscriber cannot silence the others.

export class EventBus {
  constructor() {
    /** @type {Map<string, string>} type -> description */
    this.vocabulary = new Map();
    /** @type {Map<string, Set<Function>>} */
    this.listeners = new Map();
    /** count of listener errors swallowed by isolation -- honesty's ledger */
    this.listenerFaults = 0;
    /** count of emits refused for lack of documentation */
    this.refusedEmits = 0;
    /** count of subscriptions refused for lack of documentation */
    this.refusedSubscribes = 0;
    /** @type {Set<Function>} notified the moment a new type is documented */
    this.documentWatchers = new Set();
  }

  /**
   * Document an event type. Idempotent; documenting is what makes a type
   * emittable at all.
   * @param {string} type
   * @param {string} [description]
   */
  document(type, description = '') {
    if (typeof type === 'string' && type.trim() !== '' && !this.vocabulary.has(type)) {
      this.vocabulary.set(type, description);
      // Tell anyone who tracks the vocabulary, IMMEDIATELY.
      //
      // Added for S4's activity meter, and the reason is worth keeping: a
      // listener that re-reads the vocabulary when it is next polled is
      // still deaf to an event documented and emitted before that poll --
      // which is the ordinary shape, since whoever documents a type
      // usually emits it in the next breath. Polling narrowed the window;
      // it did not close it. This closes it.
      //
      // A watcher that throws is isolated and counted, exactly like a
      // listener: registering interest in the vocabulary must not become a
      // way to break the bus.
      for (const fn of [...this.documentWatchers]) {
        try { fn(type); } catch (e) { this.listenerFaults += 1; }
      }
    }
  }

  /**
   * Watch the vocabulary itself. Called with each newly documented type.
   * @param {Function} fn
   * @returns {() => void} unwatch
   */
  onDocument(fn) {
    if (typeof fn !== 'function') return () => {};
    this.documentWatchers.add(fn);
    return () => { this.documentWatchers.delete(fn); };
  }

  /** @param {string} type @returns {boolean} */
  documented(type) {
    return this.vocabulary.has(type);
  }

  /**
   * Subscribe. Returns the unsubscribe function -- hold it, call it, done.
   * @param {string} type
   * @param {Function} fn
   * @returns {() => void}
   */
  on(type, fn) {
    // A non-function subscriber is refused at the door -- storing it would
    // only surface later as a phantom fault count at emit time. And the
    // door is guarded the same way on both sides: subscribing to an
    // UNDOCUMENTED type is refused and counted, because a typo'd listener
    // name would otherwise be permanent silent deafness that no ledger
    // ever counts (voice-line red pen, 2026-08-11). Document first, then
    // subscribe -- the same contract emit already enforces.
    if (typeof fn !== 'function') return () => {};
    if (!this.vocabulary.has(type)) {
      this.refusedSubscribes += 1;
      return () => {};
    }
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(fn);
    return () => {
      const set = this.listeners.get(type);
      if (!set) return;
      set.delete(fn);
      if (set.size === 0) this.listeners.delete(type);
    };
  }

  /**
   * Emit a documented event. An undocumented type is REFUSED -- returns
   * false and delivers nothing, because an event nobody wrote down is a
   * coupling nobody agreed to. A throwing listener is isolated: counted,
   * never rethrown, and never allowed to starve the listeners after it.
   *
   * @param {string} type
   * @param {*} [payload]
   * @returns {boolean} true if the emit was delivered (even to nobody)
   */
  emit(type, payload) {
    if (!this.vocabulary.has(type)) {
      this.refusedEmits += 1;
      return false;
    }
    // Deliver to a SNAPSHOT of the listeners as of emit time: a listener
    // that subscribes others mid-emit cannot make them hear the in-flight
    // event (or itself, unboundedly), and one that unsubscribes a later
    // listener cannot starve it of an event already in the air. Found by
    // the test-adversary, 2026-08-11 -- the live Set allowed all three.
    for (const fn of [...(this.listeners.get(type) ?? [])]) {
      try {
        fn(payload, type);
      } catch (e) {
        this.listenerFaults += 1;
      }
    }
    return true;
  }

  /** @param {string} type @returns {number} */
  listenerCount(type) {
    return this.listeners.get(type)?.size ?? 0;
  }
}
