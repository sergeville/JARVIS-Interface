// instruments/live-stack.js -- THE FIRST REAL INSTRUMENTS. No mock anywhere.
//
// Everything in the orbit before this file was invented and branded (mock).
// This module takes the voice stack's OWN live signals feed -- the same
// payload the JARVIS HUD draws -- and turns what is actually running on
// this machine into registered instruments. The processes are real, the
// states come from the process table, and nothing here has a fixture.
//
// THE COUPLING DISCIPLINE HOLDS: this file imports no registry and no UI.
// It receives the system as an argument and speaks only through
// registration and the bus, exactly as the demo instruments did -- which is
// the point of the slice. If registration is genuinely the only door, then
// real things walk through it unchanged, and nothing downstream can tell
// the difference between a live process and a fixture. That is the contact
// test the architecture has been owed since S2.
//
// THREE HONESTY RULES, each of which has its own test:
//
//   1. THE FEED IS ITSELF AN INSTRUMENT. It registers alongside the things
//      it reports, and its state IS the health of the connection:
//      CONFIGURING before the first answer, ACTIVE while polling succeeds,
//      ERROR the moment it does not. So an unreachable feed is visible in
//      the OS's own vocabulary instead of an empty orbit that looks like a
//      working system with nothing running.
//
//   2. A FAILED POLL NEVER EDITS THE WORLD. On an error, or on a payload
//      that is not the shape promised, the instruments already on screen
//      are left exactly as they are and only the feed goes ERROR. Deleting
//      the orbit because the network blinked would be inventing the claim
//      "these processes stopped", which we did not observe.
//
//   3. AN UNKNOWN WORD IS PASSED THROUGH RAW, never translated into
//      something calmer. Only the states the server is actually documented
//      to emit are mapped; anything else reaches the shell verbatim, where
//      the vocabulary fails it closed to ERROR and the orchestra's ledger
//      keeps the raw claim beside it. A silent default here would launder
//      an unknown server state into a green light.

/** The feed's own instrument id -- exported so app.js and the tests agree. */
export const FEED_ID = 'jarvis-live-feed';

/** Id prefixes, so this source can only ever remove what it registered. */
export const STACK_PREFIX = 'stack:';
export const SESSION_PREFIX = 'session:';

/** The default signals endpoint, same-origin -- see jarvis-os/serve.py. */
export const DEFAULT_URL = '/signals';

/**
 * How long one poll may take before it is abandoned. A HUNG fetch is the
 * failure mode a dead server does not produce and a STRUGGLING one does --
 * and without this the source died permanently: `inFlight` never cleared,
 * every later poll short-circuited, the ledger recorded zero failures, and
 * the feed sat on CONFIGURING forever. (test-adversary, 2026-08-15, proved
 * with the real module: five good polls behind one hung fetch produced an
 * empty orbit and a ledger reading "polls: 0, failures: 0".)
 */
export const POLL_TIMEOUT_MS = 6000;

/**
 * The page's fetch, wrapped as the source's injected reader. Exported and
 * built HERE rather than written inline in app.js because app.js is never
 * executed by the gate -- deleting its `res.ok` check went undetected, and
 * that one line is the whole difference between "the feed is down" and a
 * healthy-looking feed watching an empty machine: the proxy's 502 body is
 * `{"error": ...}`, which is a perfectly good object, so the mapping would
 * return [] and reconcile would remove every instrument.
 *
 * @param {Function} fetchImpl  the platform fetch, handed in
 * @param {Function} [AbortCtl] AbortController, handed in
 * @param {number} [timeoutMs]
 * @returns {(url: string) => Promise<any>}
 */
export function createFetchJson(fetchImpl, AbortCtl, timeoutMs = POLL_TIMEOUT_MS) {
  return async (url) => {
    const ctl = typeof AbortCtl === 'function' ? new AbortCtl() : null;
    let axe = null;
    // THE CEILING DOES NOT DEPEND ON AbortController. The first version
    // armed the timer only when one was handed in, so on any platform
    // without it -- and in every test that omits it -- this reader had no
    // ceiling AT ALL, silently (test-adversary, 2026-08-15). Abort is the
    // courtesy that frees the socket; the race is the guarantee.
    const ceiling = new Promise((_, reject) => {
      axe = setTimeout(() => {
        if (ctl) { try { ctl.abort(); } catch (e) { /* best effort */ } }
        reject(new Error(`feed did not answer within ${timeoutMs}ms`));
      }, timeoutMs);
    });
    try {
      const res = await Promise.race([
        fetchImpl(url, { cache: 'no-store', signal: ctl ? ctl.signal : undefined }),
        ceiling,
      ]);
      // A 502 from the proxy IS the answer "the feed is down". It must reach
      // the source as a FAILURE, never as a payload.
      //
      // `!== true`, NOT `!res.ok`: a response object carrying the STRING
      // 'false' is truthy, so the negation let an error body through as a
      // payload -- and the proxy's 502 body is `{"error": ...}`, a perfectly
      // good object, which the mapping turns into [] and reconcile turns
      // into an empty orbit under a healthy-looking feed.
      if (res.ok !== true) throw new Error(`feed answered ${res.status}`);
      // The body is raced too: headers arriving is not the same event as a
      // body arriving, and only one of them was bounded before.
      return await Promise.race([res.json(), ceiling]);
    } finally {
      if (axe !== null) clearTimeout(axe);
    }
  };
}

/**
 * The stack states the voice server actually emits, mapped into the twelve.
 * DELIBERATELY NOT EXHAUSTIVE and deliberately without a default: a state
 * this table does not hold is passed through untranslated so it fails
 * closed to ERROR downstream. (Rule 3 above.)
 * @type {Record<string, string>}
 */
export const STACK_STATE = {
  up: 'active',
  // A component the stack lists as OPTIONAL and that is not running.
  off: 'offline',
  // A REQUIRED component with no process -- the one word that means
  // something is actually wrong, and the one this table used to be missing
  // while claiming to be complete. (reviewer, 2026-08-15, confirmed at
  // voice-web-server.py:905-911, which is the only place these are built.)
  down: 'error',
};

/** @param {unknown} v @returns {boolean} */
function isPlainObject(v) {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/**
 * A stable, readable id fragment. Anything not [a-z0-9] becomes a dash;
 * an empty result becomes 'unnamed' rather than an id of "".
 * @param {unknown} s
 * @returns {string}
 */
export function slug(s) {
  const out = String(s ?? '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return out || 'unnamed';
}

/**
 * TRUE means true. The server's booleans arrive as JSON booleans today, but
 * `=== true` fails OPEN: `ended: 'yes'` or `ended: 1` would render a
 * FINISHED session as ACTIVE -- a confident wrong answer, which is worse
 * than a blank one, and invisible on both sides of the gate.
 * (reviewer + test-adversary, 2026-08-15, independently.)
 * @param {unknown} v
 * @returns {boolean}
 */
export function isTrue(v) {
  if (v === true || v === 1) return true;
  if (typeof v === 'string') return ['true', 'yes', '1'].includes(v.trim().toLowerCase());
  return false;
}

/** The six declaration arrays every instrument definition must carry. */
function declarations(extra = {}) {
  return {
    capabilities: [], actions: [], panels: [], dataSources: [],
    permissions: [], events: [], ...extra,
  };
}

/**
 * The feed's own definition. It declares the one data source it really has,
 * because the detail sheet reads declarations and an empty list here would
 * understate what this instrument is.
 * @param {string} url
 * @returns {Object}
 */
export function feedDefinition(url = DEFAULT_URL) {
  return {
    id: FEED_ID,
    name: 'Live signals feed',
    type: 'data-provider',
    icon: 'LF',
    description: `Polls ${url} -- the voice stack's own signals payload. Real, not simulated.`,
    ...declarations({
      dataSources: [{ id: 'signals', name: `GET ${url}`, kind: 'rest' }],
      events: [{ id: 'instrument-status-changed', description: 'republished for every live process' }],
    }),
  };
}

/**
 * One stack component -> one instrument. The description carries the port
 * and the pids because that is what makes it identifiable on the machine,
 * and an instrument nobody can find in Activity Monitor is half real.
 * @param {Object} c
 * @returns {{def: Object, status: string}|null}
 */
function fromComponent(c) {
  if (!isPlainObject(c) || typeof c.label !== 'string' || !c.label.trim()) return null;
  const pids = Array.isArray(c.pids) ? c.pids.map(String).filter(Boolean) : [];
  const bits = [];
  if (c.port) bits.push(`port ${c.port}`);
  bits.push(pids.length ? `pid ${pids.join(', ')}` : 'no process');
  return {
    def: {
      id: STACK_PREFIX + slug(c.label),
      name: c.label,
      type: 'service',
      description: bits.join(' -- '),
      ...declarations(),
    },
    // Rule 3: unmapped words pass through raw and fail closed downstream.
    status: Object.hasOwn(STACK_STATE, c.state) ? STACK_STATE[c.state] : String(c.state),
  };
}

/**
 * One live Claude session -> one instrument. A session is an AGENT, which
 * is the goals document's own first example of an instrument, so this is
 * the kind the architecture was drawn for.
 * @param {Object} s
 * @returns {{def: Object, status: string}|null}
 */
function fromSession(s) {
  if (!isPlainObject(s)) return null;
  // session_id is the REAL identity; pid is the readable one. Prefer the pid
  // only when it is genuinely present, and fall back rather than minting
  // "session:undefined" out of a null (test-adversary, 2026-08-15).
  const hasPid = s.pid !== undefined && s.pid !== null && String(s.pid).trim() !== '';
  const hasSid = s.session_id !== undefined && s.session_id !== null && String(s.session_id).trim() !== '';
  if (!hasPid && !hasSid) return null;
  const key = hasPid ? String(s.pid) : String(s.session_id);
  const channel = typeof s.channel === 'string' && s.channel.trim() ? s.channel : 'session';
  // ENDED beats UNREGISTERED: a finished session is finished whatever it
  // failed to sign. Asked in this order so the two can never disagree.
  const status = isTrue(s.ended) ? 'completed'
    : (isTrue(s.unregistered) ? 'unconfigured' : 'active');
  const doing = typeof s.doing === 'string' && s.doing.trim() ? s.doing : null;
  return {
    def: {
      id: SESSION_PREFIX + slug(key),
      name: `${channel} (${key})`,
      type: 'agent',
      description: [doing, typeof s.model === 'string' ? s.model : null]
        .filter(Boolean).join(' -- ') || 'a Claude session on this machine',
      ...declarations(),
    },
    status,
  };
}

/**
 * The whole mapping, pure and total: a signals payload in, the instruments
 * it describes out. Never throws, whatever the payload is -- a data source
 * that can crash the shell is the thing S2's registries exist to prevent.
 *
 * @param {unknown} signals
 * @returns {{def: Object, status: string}[]}
 */
export function instrumentsFromSignals(signals) {
  const out = [];
  // TOTAL means total. A hostile or exotic payload -- a throwing getter, a
  // throwing toString -- must not escape as an exception, because the whole
  // promise of this function is that a data source cannot crash the shell.
  // Each item is isolated so one bad entry costs one instrument, not all.
  try {
    if (!isPlainObject(signals)) return [];
    const stack = isPlainObject(signals.stack) ? signals.stack : {};
    const components = Array.isArray(stack.components) ? stack.components : [];
    for (const c of components) {
      try { const made = fromComponent(c); if (made) out.push(made); } catch (e) { /* one bad entry */ }
    }
    const sessions = Array.isArray(signals.sessions) ? signals.sessions : [];
    for (const s of sessions) {
      try { const made = fromSession(s); if (made) out.push(made); } catch (e) { /* one bad entry */ }
    }
  } catch (e) {
    return out;
  }
  // TWO DIFFERENT THINGS MUST NOT BECOME ONE. 'voice line' and 'voice-line'
  // slug identically, and so does every pair of non-Latin labels (both land
  // on 'unnamed') -- so the old first-wins filter made a real second process
  // VANISH from the orbit with nothing recording that it had. A colliding id
  // is disambiguated instead; an identical one (the same thing listed twice)
  // still collapses, first wins.
  //
  // TWO SETS, BECAUSE THEY ANSWER TWO QUESTIONS. `seen` is identity -- the
  // same base id AND the same name is the same thing listed twice, and it
  // collapses. `taken` is the ids already handed out, so a genuine collision
  // gets a suffix. The first version kept one map of id -> FIRST name, which
  // meant the third of ['voice line', 'voice-line', 'voice-line'] compared
  // against the wrong name, failed the identity test and was disambiguated
  // into a THIRD instrument -- the same duplication the block exists to
  // prevent, in the direction nobody looked (test-adversary, 2026-08-15).
  const seen = new Set();
  const taken = new Set();
  const result = [];
  for (const m of out) {
    // NUL as the joiner, not a space or a colon, and written as an
    // ESCAPE rather than as a raw byte: a separator that can occur
    // inside either field is how two different pairs sign identically,
    // which is a live open card on this project already (the sessSig
    // delimiter collision, 2026-08-12).
    const identity = `${m.def.id}\u0000${m.def.name}`;
    if (seen.has(identity)) continue; // genuinely the same instrument
    seen.add(identity);
    let id = m.def.id;
    if (taken.has(id)) {
      let n = 2;
      while (taken.has(`${m.def.id}-${n}`)) n += 1;
      id = `${m.def.id}-${n}`;
    }
    taken.add(id);
    m.def.id = id;
    result.push(m);
  }
  return result;
}

/** Deep-equal enough for definitions, which are plain JSON data by contract. */
function sameDef(a, b) {
  try { return JSON.stringify(a) === JSON.stringify(b); } catch (e) { return false; }
}

/**
 * The live source. Polls the feed, reconciles the instrument registry
 * against what is actually running, and republishes status changes.
 *
 * Every dependency is injected -- the fetch, the clock, the interval -- so
 * the gate drives this against a fake feed with no network and no waiting,
 * and so nothing here reaches for a global.
 *
 * @param {Object} opts
 * @param {{bus: Object, registries: Object}} opts.system  handed in, never imported
 * @param {(url: string) => Promise<any>} opts.fetchJson
 * @param {string} [opts.url]
 * @param {number} [opts.intervalMs]
 * @param {(fn: Function, ms: number) => any} [opts.setTimer]
 * @param {(h: any) => void} [opts.clearTimer]
 * @returns {{start: Function, stop: Function, poll: () => Promise<Object>, stats: () => Object}}
 */
export function createLiveStackSource(opts) {
  const {
    system,
    fetchJson,
    url = DEFAULT_URL,
    intervalMs = 4000,
    pollTimeoutMs = POLL_TIMEOUT_MS,
    setTimer = (fn, ms) => setTimeout(fn, ms),
    clearTimer = (h) => clearTimeout(h),
  } = opts ?? {};

  const instruments = system.registries.instruments;
  /** ids this source registered -- it may never remove anything else. */
  const owned = new Set();
  /** last status published per id, so an unchanged state is not re-emitted. */
  const lastStatus = new Map();
  let timer = null;
  let running = false;
  let inFlight = false;
  // `generation` is what makes stop() final: an in-flight tick belonging to
  // an older generation may not schedule anything, so start-stop-start
  // across a running poll cannot leave an orphan loop nothing can cancel
  // (test-adversary, 2026-08-15).
  let generation = 0;
  const ledger = {
    polls: 0, failures: 0, lastError: null,
    registered: 0, removed: 0, refused: 0, foreign: 0, timeouts: 0, dropped: 0,
  };

  const setFeed = (status) => {
    if (lastStatus.get(FEED_ID) === status) return;
    lastStatus.set(FEED_ID, status);
    system.bus.emit('instrument-status-changed', { id: FEED_ID, status });
  };

  // The feed announces itself before it knows anything: CONFIGURING is the
  // honest word for "asked, no answer yet", and it means the orbit is never
  // empty even on the first frame.
  const born = instruments.register(feedDefinition(url));
  if (born.ok) { owned.add(FEED_ID); ledger.registered += 1; } else { ledger.refused += 1; }
  setFeed('configuring');

  const publish = (id, status) => {
    if (lastStatus.get(id) === status) return;
    lastStatus.set(id, status);
    system.bus.emit('instrument-status-changed', { id, status });
  };

  /** Reconcile the registry against one good payload. */
  const reconcile = (wanted) => {
    const wantedIds = new Set(wanted.map((m) => m.def.id));
    for (const m of wanted) {
      const existing = instruments.get(m.def.id);
      if (!existing) {
        const verdict = instruments.register(m.def);
        if (verdict.ok) { owned.add(m.def.id); ledger.registered += 1; } else { ledger.refused += 1; continue; }
      } else if (!owned.has(m.def.id)) {
        // SOMEBODY ELSE OWNS THIS ID. Ownership was enforced on removal and
        // not on update, so a foreign instrument's definition could be
        // overwritten by whatever the feed happened to say (test-adversary,
        // 2026-08-15). Leave it alone entirely -- not even its status.
        ledger.foreign += 1;
        continue;
      } else if (!sameDef(existing.def, m.def)) {
        // Identity is the id; everything else may drift, and an update is
        // how the node hears it. Registering again would be refused as a
        // duplicate and the screen would quietly go stale.
        const verdict = instruments.update(m.def.id, m.def);
        if (!verdict.ok) ledger.refused += 1;
      }
      publish(m.def.id, m.status);
    }
    // Gone from the feed means gone from the machine -- but only for ids
    // this source owns, and never the feed itself.
    for (const id of [...owned]) {
      if (id === FEED_ID || wantedIds.has(id)) continue;
      const verdict = instruments.remove(id);
      if (verdict.ok) { owned.delete(id); lastStatus.delete(id); ledger.removed += 1; }
    }
  };

  /**
   * One poll. Resolves to the ledger rather than rejecting: a source that
   * throws into its own timer is a source that stops polling on the first
   * bad night.
   */
  const poll = async () => {
    // A poll arriving while one is in flight is DROPPED, and that is the
    // right call -- but it used to be dropped silently, so a source being
    // asked twice as fast as it can answer looked identical to a healthy
    // one. Counted now (test-adversary, 2026-08-15).
    if (inFlight) { ledger.dropped += 1; return ledger; }
    inFlight = true;
    let axe = null;
    try {
      // THE POLL HAS ITS OWN CEILING, and it is the fix for the worst bug
      // this file has had: a fetch that never settles used to leave
      // `inFlight` stuck true forever, so every later poll returned early,
      // the ledger stayed at zero failures, and the feed sat on CONFIGURING
      // for the life of the page. A source that cannot report its own
      // silence is exactly the lie this module exists to refuse.
      //
      // HOLD THE HANDLE AND CANCEL IT. The first version threw the timer
      // away, so the loser of every SUCCESSFUL race kept running: three good
      // polls left `timeouts: 3` and three live timers, forever. A
      // diagnostic added to prove this source can report its own silence
      // was reporting silence during perfect health (reviewer +
      // test-adversary, 2026-08-15, independently).
      const payload = await Promise.race([
        fetchJson(url),
        new Promise((_, reject) => {
          axe = setTimer(() => {
            ledger.timeouts += 1;
            reject(new Error(`no answer within ${pollTimeoutMs}ms`));
          }, pollTimeoutMs);
        }),
      ]);
      ledger.polls += 1;
      if (!isPlainObject(payload)) throw new Error('signals payload is not an object');
      reconcile(instrumentsFromSignals(payload));
      ledger.lastError = null;
      setFeed('active');
    } catch (e) {
      // RULE 2: nothing is removed and nothing is restated. The world on
      // screen is the last thing we actually saw; only the feed changes.
      ledger.failures += 1;
      ledger.lastError = e && e.message ? String(e.message) : 'unknown error';
      setFeed('error');
    } finally {
      if (axe !== null) { clearTimer(axe); axe = null; }
      inFlight = false;
    }
    return ledger;
  };

  const tick = async (mine) => {
    await poll();
    // Only the CURRENT generation may reschedule. An older tick that was
    // in flight across a stop() is finished, not resumed.
    if (running && mine === generation) timer = setTimer(() => tick(mine), intervalMs);
  };

  return {
    start() {
      if (running) return;
      running = true;
      generation += 1;
      const mine = generation;
      timer = setTimer(() => tick(mine), 0);
    },
    stop() {
      running = false;
      generation += 1; // orphans any tick still in flight
      if (timer !== null) clearTimer(timer);
      timer = null;
    },
    poll,
    stats: () => ({ ...ledger, owned: [...owned] }),
  };
}
