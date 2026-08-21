// test_jarvis_os_s5.js -- the S5 gate: ONE REAL INSTRUMENT, NO MOCK.
//
// The card this file gates is "the first contact test for the architecture":
// drive the real voice-line stack through registration end to end. So this
// suite imports the REAL live source, the REAL registries and the REAL
// orchestra, and drives them with a payload shaped exactly like the one the
// running server actually returns -- recorded from it, not invented.
//
// The properties that matter here are the HONESTY ones, because a live data
// source is where a UI starts lying: a failed poll must not delete the world,
// an unknown server word must not be laundered into something calmer, and an
// unreachable feed must be visible rather than looking like an idle machine.

'use strict';

const fs = require('fs');
const path = require('path');

const OS_DIR = path.join(__dirname, '..', '..', 'jarvis-os');

let passed = 0;
let failed = 0;
function ok(name, cond) {
  if (cond) { passed += 1; console.log(`  ok   ${name}`); }
  else { failed += 1; console.log(`  FAIL ${name}`); }
}

function stripComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
}
function importsFrom(src, fragment) {
  const re = new RegExp(
    String.raw`(?:from\s*|import\s*\(\s*|require\s*\(\s*)['"\`][^'"\`]*` + fragment,
  );
  return re.test(stripComments(src));
}

class FakeEl {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.attrs = {};
    this.style = {};
    this.className = '';
    this.textContent = '';
    this.handlers = {};
  }
  appendChild(child) { this.children.push(child); return child; }
  removeChild(child) {
    const i = this.children.indexOf(child);
    if (i >= 0) this.children.splice(i, 1);
    return child;
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(type, fn) { (this.handlers[type] ??= []).push(fn); }
}
const fakeDoc = { createElement: (t) => new FakeEl(t) };
function walk(el, out = []) {
  out.push(el);
  for (const c of el.children) walk(c, out);
  return out;
}

// A payload with the SHAPE and the FIELD NAMES of the real thing, recorded
// from http://127.0.0.1:8765/signals on 2026-08-15 and trimmed to the two
// keys this source reads. If the server ever renames a field, the mapping
// tests here keep passing while the page goes blank -- so the live proof
// against the running server is part of this slice's record, not optional.
const REAL_SHAPED = {
  state: 'idle',
  stack: {
    components: [
      { label: 'browser Jarvis', pids: ['1541', '1545'], state: 'up', port: 8765, since: 1786822904.0 },
      { label: 'brain', pids: ['1577'], state: 'up', port: null, since: 1786822905.0 },
      { label: 'terminal line', pids: [], state: 'off', port: null, since: null },
      { label: 'whisper', pids: ['1428'], state: 'up', port: 2022, since: 1786822836.0 },
      { label: 'kokoro', pids: ['1432'], state: 'up', port: 8880, since: 1786822836.0 },
    ],
    ports: { 8765: 'held' },
    page: 'unknown',
  },
  sessions: [
    {
      session_id: 'b6fe0371-82e3-48f6-9131-ec9ccbbd5cec',
      ended: false, pid: 1577, channel: 'voice line', model: 'claude-opus-5',
      unregistered: false, doing: 'running a command',
    },
  ],
};

// RED UNTIL PROVEN GREEN, and this is structural rather than fussy. A test
// here awaits a promise that may never settle; when that happens node simply
// runs out of work and EXITS 0, having silently skipped every assertion
// below the hang. Injecting "remove the poll ceiling entirely" did exactly
// that and shipped green. So the file starts FAILED and only the last line
// of the run clears it -- a suite that stops early can no longer report
// success by disappearing. (Same lesson as the end-sentinel in
// test_board_guard.py, learned again one file over.)
process.exitCode = 1;

(async () => {
  const live = await import(path.join(OS_DIR, 'instruments', 'live-stack.js'));
  const { createSystem } = await import(path.join(OS_DIR, 'core', 'registries.js'));
  const { attachInstrumentLayer } = await import(path.join(OS_DIR, 'instruments', 'orchestra.js'));
  const { instrumentState } = await import(path.join(OS_DIR, 'instruments', 'instrument-shell.js'));

  // ---- the mapping, pure -------------------------------------------------

  const made = live.instrumentsFromSignals(REAL_SHAPED);
  const byId = new Map(made.map((m) => [m.def.id, m]));
  ok('every real stack component and every live session becomes an instrument',
    made.length === 6 &&
    byId.has('stack:browser-jarvis') && byId.has('stack:brain') &&
    byId.has('stack:terminal-line') && byId.has('stack:whisper') &&
    byId.has('stack:kokoro') && byId.has('session:1577'));
  ok('a running component reads ACTIVE and a stopped one reads OFFLINE -- from the process table, not a fixture',
    byId.get('stack:brain').status === 'active' &&
    byId.get('stack:terminal-line').status === 'offline');
  ok('the identifying facts survive: the port and the real pids reach the definition',
    byId.get('stack:browser-jarvis').def.description.includes('port 8765') &&
    byId.get('stack:browser-jarvis').def.description.includes('1541, 1545') &&
    byId.get('stack:terminal-line').def.description.includes('no process'));
  ok('a live session becomes an AGENT named by its channel and pid',
    byId.get('session:1577').def.type === 'agent' &&
    byId.get('session:1577').def.name === 'voice line (1577)' &&
    byId.get('session:1577').status === 'active' &&
    byId.get('session:1577').def.description.includes('running a command'));
  ok('every generated definition satisfies the instrument contract -- six declaration arrays, all present',
    made.every((m) => ['capabilities', 'actions', 'panels', 'dataSources', 'permissions', 'events']
      .every((k) => Array.isArray(m.def[k]))));

  // THE LAUNDERING TEST. This is the one that keeps a green light honest.
  const odd = live.instrumentsFromSignals({
    stack: { components: [{ label: 'ghost', pids: [], state: 'quantum-overdrive' }] },
  });
  ok('an UNKNOWN server state is passed through RAW, never defaulted to something calmer',
    odd[0].status === 'quantum-overdrive');
  ok('...and the shell then fails it CLOSED to ERROR, with the raw claim still readable',
    instrumentState(odd[0].status).id === 'error');
  ok('the mapping table holds ONLY states the server emits -- no catch-all default hides a new word',
    !Object.hasOwn(live.STACK_STATE, 'default') &&
    Object.keys(live.STACK_STATE).every((k) => typeof live.STACK_STATE[k] === 'string'));

  ok('a finished session reads COMPLETED even if it never registered -- ended outranks unregistered',
    live.instrumentsFromSignals({ sessions: [{ pid: 9, ended: true, unregistered: true }] })[0].status === 'completed' &&
    live.instrumentsFromSignals({ sessions: [{ pid: 9, ended: false, unregistered: true }] })[0].status === 'unconfigured');

  // ---- the mapping never throws, whatever arrives ------------------------

  const junk = [
    null, undefined, 0, '', 'nope', [], {}, { stack: 'not-an-object' },
    { stack: { components: 'nope' } }, { stack: { components: [null, 7, {}, { label: '   ' }] } },
    { sessions: {} }, { sessions: [null, 3, {}] },
    { stack: { components: [{ label: 'x', pids: 'nope', state: 'up' }] } },
  ];
  let threw = null;
  for (const p of junk) {
    try { live.instrumentsFromSignals(p); } catch (e) { threw = threw ?? e; }
  }
  ok('a malformed payload NEVER throws -- a data source that can crash the shell is what the registries exist to stop',
    threw === null);
  ok('junk entries are dropped rather than registered as half-instruments',
    live.instrumentsFromSignals({ stack: { components: [null, 7, {}, { label: '  ' }] } }).length === 0);
  // REPOINTED, and disclosed rather than quietly edited. This assertion used
  // to require 'Brain' and 'brain' to COLLAPSE into one instrument, and it
  // passed because the code dropped the second. The test-adversary showed
  // what that was really doing: 'voice line' and 'voice-line' slug the same
  // way, so a genuinely different process vanished from the orbit with
  // nothing recording that it had. The rule is now the opposite and it is
  // the right one -- different names stay different instruments; only an
  // identical repeat collapses (pinned two assertions down).
  ok('two components whose labels differ stay TWO instruments even when their slugs collide',
    live.instrumentsFromSignals({
      stack: { components: [{ label: 'Brain', state: 'up' }, { label: 'brain', state: 'off' }] },
    }).length === 2);
  ok('an empty label lands on a real id, never on the empty string', live.slug('   ') === 'unnamed');

  // ---- the source, driven with an injected feed and an injected clock ----

  // beforeSource runs after the system exists and BEFORE the source is
  // built -- which is the only order that works, because the feed registers
  // itself at construction and a layer attached afterwards never hears it.
  // app.js has that order; an assertion below pins it there.
  const newRig = (beforeSource = () => {}) => {
    const system = createSystem();
    const seen = [];
    system.bus.on('instrument-status-changed', (p) => seen.push(p));
    beforeSource(system);
    let answer = () => REAL_SHAPED;
    const timers = [];
    const src = live.createLiveStackSource({
      system,
      fetchJson: async () => answer(),
      intervalMs: 1000,
      setTimer: (fn) => { timers.push(fn); return timers.length; },
      clearTimer: () => {},
    });
    return {
      system, seen, src, timers,
      feed: (fn) => { answer = fn; },
      ids: () => system.registries.instruments.list().map((d) => d.id).sort(),
      statusOf: (id) => [...seen].reverse().find((p) => p.id === id)?.status,
    };
  };

  const r1 = newRig();
  ok('THE FEED IS ITSELF AN INSTRUMENT, and it says CONFIGURING before it knows anything',
    r1.ids().includes(live.FEED_ID) && r1.statusOf(live.FEED_ID) === 'configuring');

  await r1.src.poll();
  ok('one real poll registers every live process through the front door',
    r1.ids().length === 7 && r1.ids().includes('stack:whisper') && r1.ids().includes('session:1577'));
  ok('the feed goes ACTIVE once it has actually been answered',
    r1.statusOf(live.FEED_ID) === 'active');
  ok('each instrument gets its live state published on the bus',
    r1.statusOf('stack:brain') === 'active' && r1.statusOf('stack:terminal-line') === 'offline');

  const before = r1.seen.length;
  await r1.src.poll();
  ok('an unchanged world emits NOTHING -- the brain must not read a poll loop as traffic',
    r1.seen.length === before);

  // THE MOST IMPORTANT TEST IN THIS FILE.
  r1.feed(() => { throw new Error('connection refused'); });
  await r1.src.poll();
  ok('A FAILED POLL DELETES NOTHING -- "these processes stopped" is a claim we did not observe',
    r1.ids().length === 7 && r1.ids().includes('stack:whisper'));
  ok('...and the failure is VISIBLE: the feed instrument goes ERROR',
    r1.statusOf(live.FEED_ID) === 'error');
  ok('...and the stack instruments keep their last SEEN state rather than being restated',
    r1.statusOf('stack:brain') === 'active');
  ok('the source records the failure honestly instead of swallowing it',
    r1.src.stats().failures === 1 && String(r1.src.stats().lastError).includes('connection refused'));

  r1.feed(() => 'not an object');
  await r1.src.poll();
  ok('a payload of the wrong SHAPE is treated as a failure, not as an empty world',
    r1.ids().length === 7 && r1.statusOf(live.FEED_ID) === 'error');

  r1.feed(() => REAL_SHAPED);
  await r1.src.poll();
  ok('recovery is automatic: the next good answer puts the feed back to ACTIVE',
    r1.statusOf(live.FEED_ID) === 'active');

  // ---- removal, update, ownership ---------------------------------------

  const r2 = newRig();
  await r2.src.poll();
  r2.feed(() => ({ stack: { components: REAL_SHAPED.stack.components.slice(0, 2) }, sessions: [] }));
  await r2.src.poll();
  ok('a process that really stopped vanishes from the orbit',
    !r2.ids().includes('stack:whisper') && r2.ids().includes('stack:brain'));
  ok('the feed itself is never swept away by its own reconciliation',
    r2.ids().includes(live.FEED_ID));

  const r3 = newRig();
  r3.system.registries.instruments.register({
    id: 'someone-elses', name: 'Not mine', type: 'service',
    capabilities: [], actions: [], panels: [], dataSources: [], permissions: [], events: [],
  });
  await r3.src.poll();
  r3.feed(() => ({ stack: { components: [] }, sessions: [] }));
  await r3.src.poll();
  ok('the source removes ONLY what it registered -- another owner\'s instrument survives',
    r3.ids().includes('someone-elses') && !r3.ids().includes('stack:brain'));

  const r4 = newRig();
  await r4.src.poll();
  r4.feed(() => ({
    stack: { components: [{ label: 'brain', pids: ['9999'], state: 'up', port: null }] }, sessions: [],
  }));
  await r4.src.poll();
  ok('a changed definition UPDATES rather than being refused as a duplicate -- the node cannot go stale',
    r4.system.registries.instruments.get('stack:brain').def.description.includes('9999') &&
    r4.src.stats().refused === 0);

  // ---- start/stop drive the injected timer, not a real clock ------------

  const r5 = newRig();
  r5.src.start();
  ok('start schedules through the INJECTED timer -- no module here reaches for a global clock',
    r5.timers.length === 1);
  r5.src.stop();
  ok('stop really stops: nothing is scheduled after it', (() => {
    const n = r5.timers.length;
    r5.src.stop();
    return r5.timers.length === n;
  })());

  // ---- end to end, through the real orchestra ---------------------------

  const stage = new FakeEl('div');
  const floating = new FakeEl('div');
  const r6 = newRig((system) => attachInstrumentLayer(fakeDoc, system, stage, floating));
  await r6.src.poll();
  const nodes = walk(stage).filter((el) => String(el.className).split(' ').includes('os-instrument'));
  const names = nodes.map((n) => walk(n).find((c) => String(c.className).includes('__name'))?.textContent);
  ok('END TO END: the real processes reach the screen through registration alone',
    nodes.length === 7 && names.includes('brain') && names.includes('whisper') &&
    names.includes('voice line (1577)'));
  ok('...wearing their real states, the stopped one visibly OFFLINE',
    nodes.find((n) => n.getAttribute('data-instrument-id') === 'stack:terminal-line')
      .getAttribute('data-instrument-state') === 'offline' &&
    nodes.find((n) => n.getAttribute('data-instrument-id') === 'stack:brain')
      .getAttribute('data-instrument-state') === 'active');
  ok('...and NOT ONE of them is branded DEMO, because not one of them is invented',
    walk(stage).filter((el) => String(el.className).includes('os-instrument__demo')).length === 0);

  // ---- coupling: the discipline that made this slice cheap --------------

  const liveSrc = fs.readFileSync(path.join(OS_DIR, 'instruments', 'live-stack.js'), 'utf8');
  ok('the live source imports NO registry, NO ui and NO mock -- the system arrives as an argument',
    !importsFrom(liveSrc, 'registr') && !importsFrom(liveSrc, 'ui/') && !importsFrom(liveSrc, 'mock/'));
  ok('the live source reaches for no global window, document or fetch -- every dependency is injected',
    !/(^|[^.\w])window\./.test(stripComments(liveSrc)) &&
    !/(^|[^.\w])document\./.test(stripComments(liveSrc)) &&
    !/(^|[^.\w])fetch\s*\(/.test(stripComments(liveSrc)));

  const appSrc = stripComments(fs.readFileSync(path.join(OS_DIR, 'app.js'), 'utf8'));
  ok('THE RUNNING PAGE REGISTERS NO SIMULATED INSTRUMENT -- the mock definitions are off the screen',
    !appSrc.includes('MOCK_INSTRUMENTS') && !appSrc.includes('MOCK_STATUSES'));
  ok('app.js builds the live source and actually starts it',
    /createLiveStackSource\(/.test(appSrc) && /\.live\.start\(\)/.test(appSrc));
  // app.js is wiring, so it can only ever be pinned by reading it -- but the
  // pin now names the TESTED reader. Writing the reader inline here is what
  // left `res.ok` unguarded and undetected, so "inline again" must be red.
  ok('app.js uses the GATED reader rather than writing its own inline fetch',
    /fetchJson:\s*createFetchJson\(/.test(appSrc) && !/await fetch\(/.test(appSrc));
  // Found by this file's own end-to-end test going red: the feed registers
  // itself at construction, so a layer attached afterwards never hears it
  // and the connection's health is invisible on screen -- the exact failure
  // the feed instrument exists to prevent. The order is the fix, so the
  // order is pinned.
  ok('THE LAYER IS ATTACHED BEFORE THE LIVE SOURCE EXISTS -- otherwise the feed registers to nobody',
    appSrc.indexOf('attachInstrumentLayer(') < appSrc.indexOf('createLiveStackSource(') &&
    appSrc.indexOf('createLiveStackSource(') > 0);

  // ---- the dev server: exactly one read-only door ------------------------

  const serveSrc = fs.readFileSync(path.join(OS_DIR, 'serve.py'), 'utf8');
  ok('the dev server proxies ONE hard-coded path to ONE hard-coded upstream',
    /FEED_PATH = "\/signals"/.test(serveSrc) &&
    /UPSTREAM_HOST = "127\.0\.0\.1"/.test(serveSrc) &&
    /UPSTREAM_PORT = 8765/.test(serveSrc) &&
    /UPSTREAM_PATH = "\/signals"/.test(serveSrc));
  // The address is written ONCE and the display string is derived from it.
  // Two independent literals for one upstream is how a repoint stays green
  // in half the file (reviewer, 2026-08-15, on DEFAULT_URL/FEED_PATH).
  ok('the upstream URL is DERIVED from its parts, never written out a second time',
    /UPSTREAM = f"http:\/\/\{UPSTREAM_HOST\}:\{UPSTREAM_PORT\}\{UPSTREAM_PATH\}"/.test(serveSrc));
  // REPOINTED, and disclosed. This was `!/def do_POST/` -- a grep, and the
  // adversary defeated it with `do_POST = do_GET`, an alias that never
  // spells those words and served the entire live signals payload over POST
  // while this file stayed green. The file now defines do_POST DELIBERATELY,
  // as a 405 refusal, so the old assertion is not merely weak, it is
  // backwards. THE REAL CHECK IS THE BEHAVIOURAL ONE, against a running
  // server on a real port, further down this file.
  ok('the writing verbs are refused by NAME in the source, and by BEHAVIOUR below',
    /def do_GET/.test(serveSrc) && /do_POST = _refuse/.test(serveSrc) &&
    /"this server is read-only/.test(serveSrc));
  ok('it binds loopback only, like the thing it proxies', /\("127\.0\.0\.1", port\)/.test(serveSrc));
  ok('a query string cannot smuggle a request past the path check',
    /self\.path\.split\("\?", 1\)\[0\] == FEED_PATH/.test(serveSrc));
  ok('an unreachable upstream ANSWERS 502 rather than hanging -- the page needs an answer to show ERROR',
    /self\._json\(502/.test(serveSrc) && /timeout=UPSTREAM_TIMEOUT/.test(serveSrc));
  // THE BUDGET MUST START BEFORE urlopen's JOB, NOT AFTER IT. The first
  // total budget only wrapped the body read, so an upstream that dripped
  // its STATUS LINE held the proxy 52 seconds while every per-socket
  // timeout came back inside 4 (test-adversary, 2026-08-15). Owning the
  // connection is what lets a watchdog end it; the behavioural proof is
  // the header-drip case further down.
  ok('the proxy owns its connection so the budget can cover the HEADERS, not just the body',
    /http\.client\.HTTPConnection/.test(serveSrc) &&
    /deadline = time\.monotonic\(\) \+ UPSTREAM_BUDGET/.test(serveSrc) &&
    // NOT `!/urlopen/` -- the docstring beside the fix NAMES urlopen to
    // explain why it is gone, and my first version of this assertion went
    // red on my own prose. The structural fact is that urllib is not
    // imported at all; the word is allowed to appear in a sentence about
    // it. (Sixth time on this project that a guard has tripped on the
    // comment explaining the guard.)
    !/^import urllib/m.test(serveSrc) && !/urlopen\(/.test(serveSrc));
  ok('the watchdog SHUTS THE SOCKET DOWN -- a close from another thread does not reliably wake a blocked recv',
    /shutdown\(socket\.SHUT_RDWR\)/.test(serveSrc));
  ok('concurrent feed reads are CAPPED, so a bad upstream cannot pile threads on this server',
    /_INFLIGHT = threading\.BoundedSemaphore/.test(serveSrc) &&
    /acquire\(blocking=False\)/.test(serveSrc));
  ok('run.sh launches that server and still promises to kill nothing',
    /exec python3 serve\.py/.test(fs.readFileSync(path.join(OS_DIR, 'run.sh'), 'utf8')));

  // ======================================================================
  // ROUND TWO -- written after the reviewer and the test-adversary, whose
  // shared finding was that THREE OF THE FOUR FILES WERE NEVER EXECUTED BY
  // THIS GATE. serve.py, app.js and run.sh were pinned by regexes over
  // their own source, and the adversary proved what that is worth: an
  // aliased `do_POST = do_GET` served the entire live signals payload over
  // POST while every assertion here stayed green. Everything below runs the
  // real thing.
  // ======================================================================

  // ---- the state vocabulary, compared to the SERVER, not to itself ------

  const serverSrc = fs.readFileSync(
    path.join(__dirname, '..', 'voice-web-server.py'), 'utf8');
  // The one place component state is built -- voice-web-server.py's
  // `"state": ("up" if pids else ("off" if ... else "down"))`. Read the
  // words out of the server rather than restating them here, so a server
  // that grows a fourth word turns this red instead of turning an
  // instrument red.
  const stateExpr = serverSrc.split('"state": (')[1] || '';
  const serverWords = [...new Set((stateExpr.split('),')[0] || '').match(/"([a-z]+)"/g) || [])]
    .map((q) => q.replace(/"/g, ''));
  ok('the server really does build component state from a small closed set of words',
    serverWords.length >= 3 && serverWords.includes('up') && serverWords.includes('down'));
  ok('THE MAPPING TABLE MATCHES THE SERVER EXACTLY -- no word it cannot send, none of the words it can',
    JSON.stringify([...serverWords].sort()) === JSON.stringify(Object.keys(live.STACK_STATE).sort()));
  ok('every state the table maps TO is a real member of the instrument vocabulary',
    Object.values(live.STACK_STATE).every((v) => instrumentState(v).id === v));
  ok("a REQUIRED component with no process reads ERROR -- 'down' is the word that means something is wrong",
    live.instrumentsFromSignals({ stack: { components: [{ label: 'brain', state: 'down' }] } })[0].status === 'error');

  ok('the page and the proxy agree on the feed path -- two literals, pinned equal',
    new RegExp(`FEED_PATH = "${live.DEFAULT_URL}"`).test(fs.readFileSync(path.join(OS_DIR, 'serve.py'), 'utf8')));

  // ---- the DEMO check can actually fail now -----------------------------

  const demoProbe = walk((await import(path.join(OS_DIR, 'instruments', 'instrument-shell.js')))
    .createInstrumentNode(fakeDoc, { id: 'd', name: 'D', type: 't', demo: true }).el)
    .filter((el) => String(el.className).includes('os-instrument__demo')).length;
  ok('the DEMO badge DOES render when something is marked demo -- so its absence below means something',
    demoProbe === 1);

  // ---- truthiness fails CLOSED ------------------------------------------

  ok('a session ending is read as ended however the server spells true',
    live.isTrue(true) && live.isTrue('true') && live.isTrue('YES') && live.isTrue(1) &&
    !live.isTrue(false) && !live.isTrue('') && !live.isTrue(null) && !live.isTrue('no'));
  ok("ended: 'yes' renders COMPLETED, not a confident ACTIVE",
    live.instrumentsFromSignals({ sessions: [{ pid: 5, ended: 'yes' }] })[0].status === 'completed');

  // ---- two different things never become one ----------------------------

  const collide = live.instrumentsFromSignals({
    stack: { components: [{ label: 'voice line', state: 'up' }, { label: 'voice-line', state: 'up' }] },
  });
  ok('two DIFFERENT labels that slug the same stay two instruments -- a real process must not vanish',
    collide.length === 2 && new Set(collide.map((m) => m.def.id)).size === 2);
  const emoji = live.instrumentsFromSignals({
    stack: { components: [{ label: '✨', state: 'up' }, { label: '🧠', state: 'up' }] },
  });
  ok('two non-Latin labels stay two instruments rather than collapsing onto "unnamed"',
    emoji.length === 2 && new Set(emoji.map((m) => m.def.id)).size === 2);
  ok('the SAME thing listed twice still collapses to one',
    live.instrumentsFromSignals({
      stack: { components: [{ label: 'brain', state: 'up' }, { label: 'brain', state: 'up' }] },
    }).length === 1);
  ok('a session with a null pid is identified by its session_id, never "session:undefined"',
    live.instrumentsFromSignals({ sessions: [{ session_id: 'abc', pid: null }] })[0].def.id === 'session:abc');
  ok('two sessions sharing a pid both survive',
    live.instrumentsFromSignals({
      sessions: [{ pid: 7, session_id: 'a', channel: 'one' }, { pid: 7, session_id: 'b', channel: 'two' }],
    }).length === 2);
  let hostileThrew = false;
  try {
    live.instrumentsFromSignals({ stack: { get components() { throw new Error('boom'); } } });
    live.instrumentsFromSignals({
      stack: { components: [{ label: 'x', get state() { throw new Error('boom'); } }] },
    });
    live.instrumentsFromSignals({ sessions: [{ pid: 1, get ended() { throw new Error('boom'); } }] });
  } catch (e) { hostileThrew = true; }
  ok('a HOSTILE payload -- a throwing getter, a throwing toString -- still never escapes as an exception',
    hostileThrew === false);

  // ---- the reader app.js actually uses, driven for real -----------------

  const okRes = { ok: true, status: 200, json: async () => ({ hello: 'world' }) };
  let askedFor = null;
  const reader = live.createFetchJson(async (u) => { askedFor = u; return okRes; });
  ok('the reader fetches the URL it was GIVEN, not one of its own',
    (await reader('/somewhere')) && askedFor === '/somewhere');
  let readerThrew = false;
  try {
    await live.createFetchJson(async () => ({ ok: false, status: 502, json: async () => ({ error: 'down' }) }))('/signals');
  } catch (e) { readerThrew = true; }
  ok('A 502 REACHES THE SOURCE AS A FAILURE, never as a payload -- otherwise a dead feed reads as a healthy empty machine',
    readerThrew === true);

  // ---- a fetch that never settles ---------------------------------------

  {
    const system = createSystem();
    const seen = [];
    system.bus.on('instrument-status-changed', (p) => seen.push(p));
    const src = live.createLiveStackSource({
      system,
      fetchJson: () => new Promise(() => {}), // never settles, ever
      pollTimeoutMs: 30,
      setTimer: (fn, ms) => setTimeout(fn, ms),
      clearTimer: (h) => clearTimeout(h),
    });
    await src.poll();
    const statusOf = (id) => [...seen].reverse().find((p) => p.id === id)?.status;
    ok('A HUNG FEED IS REPORTED, not waited on forever -- the source used to die silently on CONFIGURING',
      statusOf(live.FEED_ID) === 'error' && src.stats().timeouts === 1);
    ok('...and the source is still ALIVE afterwards: a later good answer recovers',
      await (async () => {
        const src2 = live.createLiveStackSource({
          system: createSystem(),
          fetchJson: async () => REAL_SHAPED,
          setTimer: (fn, ms) => setTimeout(fn, ms),
          clearTimer: (h) => clearTimeout(h),
        });
        await src2.poll();
        return src2.stats().failures === 0 && src2.stats().polls === 1;
      })());
  }

  // ---- ownership on UPDATE, not only on removal -------------------------

  {
    const rig = newRig();
    rig.system.registries.instruments.remove('stack:brain');
    rig.system.registries.instruments.register({
      id: 'stack:brain', name: 'MINE, not the feed\'s', type: 'service',
      capabilities: [], actions: [], panels: [], dataSources: [], permissions: [], events: [],
    });
    await rig.src.poll();
    ok("a FOREIGN owner's instrument is never overwritten by the feed -- ownership binds the update path too",
      rig.system.registries.instruments.get('stack:brain').def.name === "MINE, not the feed's" &&
      rig.src.stats().foreign >= 1);
  }

  // ---- stop() is final, even across an in-flight poll --------------------

  {
    const timers = [];
    let release;
    const gate = new Promise((r) => { release = r; });
    const src = live.createLiveStackSource({
      system: createSystem(),
      fetchJson: async () => { await gate; return REAL_SHAPED; },
      setTimer: (fn) => { timers.push(fn); return timers.length; },
      clearTimer: () => {},
    });
    src.start();
    timers[timers.length - 1](); // run the first tick; it blocks in fetch
    src.stop();
    src.start();
    src.stop();
    release(REAL_SHAPED);
    await new Promise((r) => setTimeout(r, 20));
    const after = timers.length;
    await new Promise((r) => setTimeout(r, 20));
    ok('an in-flight poll orphaned by stop() can NEVER reschedule -- no uncancellable loop survives',
      timers.length === after);
  }

  // ---- THE DEV SERVER, RUN FOR REAL ON A REAL PORT ----------------------

  const { spawn } = require('child_process');
  const http = require('http');
  // PORT 1 NEEDS ROOT, so under S5_KILL_SERVER the dev server cannot bind and
  // this gate runs against nothing. That is not a weakening knob -- it only
  // ever makes the environment WORSE, and the meta-test at the end of this
  // file uses it to prove the gate NOTICES. See the note there for why this
  // had to exist: my own injection round removed the came-up assertion and
  // every test stayed green, because a run where the server is fine cannot
  // demonstrate an assertion that only matters when it is not.
  const PORT = process.env.S5_KILL_SERVER ? 1 : 8137;
  const proc = spawn('python3', [path.join(OS_DIR, 'serve.py'), String(PORT)], { stdio: 'ignore' });
  const req = (method, p) => new Promise((resolve) => {
    const r = http.request({ host: '127.0.0.1', port: PORT, path: p, method, timeout: 8000 }, (res) => {
      let body = '';
      res.on('data', (c) => { body += c; });
      res.on('end', () => resolve({ status: res.statusCode, body, headers: res.headers }));
    });
    r.on('error', () => resolve({ status: 0, body: '', headers: {} }));
    r.on('timeout', () => { r.destroy(); resolve({ status: -1, body: '', headers: {} }); });
    r.end();
  });
  try {
    // ==================================================================
    // THE SERVER MUST BE PROVEN UP BEFORE ANYTHING IS ASKED OF IT.
    //
    // This is the single most important assertion in the file, and its
    // absence is the worst finding this slice has had. The adversary
    // occupied port 8137 and ran the gate: `spawn` failed to bind, every
    // request resolved to `{status: 0}`, and FIVE OF THE NINE server
    // assertions below printed `ok` -- including the four verb tests
    // written specifically to answer its previous round. `status !== 200`
    // is satisfied by "no answer". A test that asserts a NEGATIVE is a
    // test a dead server passes for free.
    // ==================================================================
    let up = false;
    for (let i = 0; i < 40; i += 1) {
      const probe = await req('GET', '/index.html');
      if (probe.status === 200) { up = true; break; }
      await new Promise((r) => setTimeout(r, 100));
    }
    ok('THE DEV SERVER ACTUALLY CAME UP -- without this, every assertion below passes against nothing', up);
    if (!up) throw new Error('dev server never bound; the assertions below would be meaningless');
    // EXACT CODES, NOT NEGATIVES, for the same reason. 405 is a statement
    // the server had to be alive to make.
    const post = await req('POST', '/signals');
    ok('BEHAVIOURAL, NOT A GREP: a real POST to the feed is refused 405 -- nothing on this port can write',
      post.status === 405);
    for (const verb of ['PUT', 'DELETE', 'PATCH', 'OPTIONS']) {
      const res = await req(verb, '/signals');
      ok(`a real ${verb} to the feed is refused 405 too`, res.status === 405);
    }
    const smuggled = await req('GET', '/signals?u=http://example.com/');
    const plain = await req('GET', '/signals');
    ok('a query string cannot redirect the proxy -- it answers with THIS machine\'s payload or not at all',
      smuggled.status === plain.status &&
      (smuggled.status !== 200 || (JSON.parse(smuggled.body).stack !== undefined)));
    const head = await req('HEAD', '/signals');
    ok('HEAD on the feed answers like the feed, not 404',
      head.status === plain.status && String(head.headers['content-type'] || '').includes('json'));
    // ==================================================================
    // EVERY SPELLING, NOT THE ONE THE IMPLEMENTATION THOUGHT OF.
    //
    // The old version asked for '/serve.py' and nothing else -- and the
    // implementation compared that exact literal against the RAW request
    // path while the static handler unquoted and normalised afterwards.
    // Both agents found it independently: '/./serve.py', '/x/../serve.py',
    // '/%73erve.py', '/serve%2Epy', '/SERVE.PY' and '/%72un.sh' all
    // returned the file. A behavioural test with ONE hard-coded input is a
    // grep that costs a socket to run.
    //
    // Note these are sent as RAW request lines: an HTTP client normalises
    // dot segments on the way out, so driving this through a helpful
    // client tests the client. I nearly recorded "cannot reproduce" off
    // exactly that.
    // ==================================================================
    const rawGet = (p) => new Promise((resolve) => {
      const sock = require('net').createConnection({ host: '127.0.0.1', port: PORT }, () => {
        sock.write(`GET ${p} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n`);
      });
      let buf = '';
      sock.setTimeout(8000, () => { sock.destroy(); resolve({ status: -1, bytes: 0 }); });
      sock.on('data', (c) => { buf += c; });
      sock.on('error', () => resolve({ status: 0, bytes: 0 }));
      sock.on('close', () => {
        const m = /^HTTP\/[\d.]+ (\d+)/.exec(buf);
        resolve({ status: m ? Number(m[1]) : 0, bytes: buf.length });
      });
    });
    ok('the raw-socket probe works at all -- it can still fetch the page the server does serve',
      (await rawGet('/index.html')).status === 200);
    const SPELLINGS = [
      '/serve.py', '/./serve.py', '/x/../serve.py', '/%2e/serve.py',
      '/%73erve.py', '/serve%2Epy', '/SERVE.PY', '/%2e%2e/serve.py',
      '/run.sh', '/%72un.sh', '/RUN.SH',
    ];
    const served = [];
    for (const p of SPELLINGS) {
      const res = await rawGet(p);
      if (res.status !== 404) served.push(`${p} -> ${res.status}`);
    }
    ok(`the dev server does NOT hand out its own source, in ANY spelling of the path (${SPELLINGS.length} tried)`,
      served.length === 0);
    if (served.length) console.log('       served:', served.join(', '));
    const listing = await req('GET', '/mock/');
    ok('the dev server lists no directories', listing.status === 404);
    ok('and the one thing it exists for still works: the feed answers, or says 502 and means it',
      plain.status === 200 || plain.status === 502);

    // THE CONCURRENCY PERMIT MUST COME BACK. `UPSTREAM_MAX_INFLIGHT` is 8, so
    // a permit leaked per request wedges the proxy permanently on the 9th and
    // every feed read after it is 503 forever. SEQUENTIAL on purpose: each
    // request has fully finished before the next starts, so with a correct
    // release none of them can ever see a full semaphore, and with a leak the
    // 9th onward are 503 deterministically. My own injection round found this
    // MISSED -- nothing here drove the proxy more than a handful of times.
    const many = [];
    for (let i = 0; i < 12; i += 1) many.push((await req('GET', '/signals')).status);
    ok('the proxy still answers after 12 sequential feed reads -- the concurrency permit is RELEASED, not leaked',
      !many.includes(503));
    ok('...and the twelfth answer is as good as the first', many[11] === many[0]);
  } finally {
    proc.kill();
  }

  // ---- the proxy against a DEAD and a SLOW upstream ---------------------
  //
  // The live upstream always answers, so the whole failure half of serve.py
  // was unexercised: making the 502 branch unreachable, or deleting the
  // total budget, both shipped green. These run a COPY of serve.py with its
  // upstream constant repointed -- no production knob, no env override, and
  // the copy is proven to differ from the original.

  const runCopyOf = async (upstreamPort, port) => {
    const orig = fs.readFileSync(path.join(OS_DIR, 'serve.py'), 'utf8');
    // Repoint the PORT the fetch actually dials. The copy used to repoint
    // the UPSTREAM url string, which the proxy no longer reads -- and a
    // patch that changes a decorative constant is a test of nothing. The
    // no-op guard below is what makes that a red rather than a silent pass.
    const patched = orig.replace(/^UPSTREAM_PORT = \d+$/m, `UPSTREAM_PORT = ${upstreamPort}`);
    if (patched === orig) return null; // refuse a silent no-op
    const dir = fs.mkdtempSync(path.join(require('os').tmpdir(), 's5-serve-'));
    fs.writeFileSync(path.join(dir, 'serve.py'), patched);
    fs.writeFileSync(path.join(dir, 'index.html'), '<!doctype html><title>x</title>');
    const child = spawn('python3', [path.join(dir, 'serve.py'), String(port)], { stdio: 'ignore' });
    const ask = (p, method = 'GET') => new Promise((resolve) => {
      const r = http.request({ host: '127.0.0.1', port, path: p, method, timeout: 25000 }, (res) => {
        let b = ''; res.on('data', (c) => { b += c; }); res.on('end', () => resolve({ status: res.statusCode, body: b }));
      });
      r.on('error', () => resolve({ status: 0, body: '' }));
      r.on('timeout', () => { r.destroy(); resolve({ status: -1, body: '' }); });
      r.end();
    });
    for (let i = 0; i < 40; i += 1) {
      const probe = await ask('/index.html');
      if (probe.status === 200) break;
      await new Promise((r) => setTimeout(r, 100));
    }
    return { ask, stop: () => { child.kill(); fs.rmSync(dir, { recursive: true, force: true }); } };
  };

  {
    // Nothing listens on 8199; the connection is refused outright.
    const dead = await runCopyOf(8199, 8138);
    ok('the dead-upstream copy was really repointed -- a no-op patch must not read as a pass', dead !== null);
    ok('a DEAD upstream really does answer 502 -- proven by running it, not by grepping for the branch',
      dead !== null && (await dead.ask('/signals')).status === 502);
    if (dead) dead.stop();
  }

  {
    // A drip server: it answers, promises a body, and sends almost nothing.
    // This is a STRUGGLING voice server -- likelier than a dead one, and the
    // shape that held the proxy open past 25 seconds before the total budget.
    // Every timer and socket this block opens is tracked and closed. A test
    // that passes and then never exits is not a passing test -- it is a
    // hung suite, which is the exact failure this project lost a ten-minute
    // gate run to on 2026-08-14.
    const dripTimers = [];
    const drip = http.createServer((req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json', 'Content-Length': '100000' });
      res.write('{');
      const t = setInterval(() => { try { res.write(' '); } catch (e) { /* gone */ } }, 3000);
      t.unref();
      dripTimers.push(t);
      res.on('close', () => clearInterval(t));
    });
    await new Promise((r) => drip.listen(8198, '127.0.0.1', r));
    const slow = await runCopyOf(8198, 8139);
    ok('the slow-upstream copy was really repointed', slow !== null);
    const t0 = Date.now();
    const answer = slow ? await slow.ask('/signals') : { status: -1 };
    const elapsed = Date.now() - t0;
    ok('a SLOW upstream is abandoned on a TOTAL budget and answers 502 -- "never hangs" is true at last',
      answer.status === 502 && elapsed < 20000);
    if (slow) slow.stop();
    for (const t of dripTimers) clearInterval(t);
    drip.closeAllConnections?.();
    await new Promise((r) => drip.close(r));
  }

  {
    // THE BYTE CAP, DRIVEN RATHER THAN GREPPED. `UPSTREAM_MAX_BYTES` is 8MB
    // and an unbounded read is how a dev tool turns one bad response into an
    // out-of-memory. My own injection round deleted the cap entirely and the
    // suite stayed GREEN -- nothing here had ever handed the proxy a large
    // body. This serves 24MB as fast as it can and requires a 502.
    const conns = [];
    const fat = require('net').createServer((sock) => {
      conns.push(sock);
      sock.on('error', () => {});
      sock.once('data', () => {
        sock.write('HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                 + 'Content-Length: 25165824\r\n\r\n');
        const chunk = Buffer.alloc(1024 * 1024, 0x20);
        for (let i = 0; i < 24; i += 1) { try { sock.write(chunk); } catch (e) { break; } }
      });
    });
    await new Promise((r) => fat.listen(8196, '127.0.0.1', r));
    const huge = await runCopyOf(8196, 8141);
    ok('the oversized-upstream copy was really repointed', huge !== null);
    const answer = huge ? await huge.ask('/signals') : { status: -1 };
    ok('AN OVERSIZED UPSTREAM IS REFUSED 502 -- the byte cap is real, not a comment',
      answer.status === 502);
    if (huge) huge.stop();
    for (const c of conns) c.destroy();
    await new Promise((r) => fat.close(r));
  }

  {
    // ==================================================================
    // THE HEADER DRIP -- the half the body drip above could never reach.
    //
    // The adversary's words: "the gate's drip server sends headers
    // immediately and drips only the body -- i.e. it tests exactly the bug
    // already fixed and nothing adjacent." It measured 52.07 SECONDS here,
    // against a total budget of 6, because the budget only ever wrapped
    // the body read and urlopen does not return until the headers land.
    // This is a RAW socket server: an http.Server always flushes a
    // complete status line, so the failure mode is unreachable through it.
    // ==================================================================
    const conns = [];
    const timers = [];
    const headerDrip = require('net').createServer((sock) => {
      conns.push(sock);
      sock.on('error', () => {});
      sock.once('data', () => {
        const bytes = [...Buffer.from('HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n')];
        let i = 0;
        const t = setInterval(() => {
          if (i >= bytes.length) { clearInterval(t); return; }
          try { sock.write(Buffer.from([bytes[i++]])); } catch (e) { clearInterval(t); }
        }, 3000);
        t.unref();
        timers.push(t);
        sock.on('close', () => clearInterval(t));
      });
    });
    await new Promise((r) => headerDrip.listen(8197, '127.0.0.1', r));
    const stalled = await runCopyOf(8197, 8140);
    ok('the header-drip copy was really repointed', stalled !== null);
    const t0 = Date.now();
    const answer = stalled ? await stalled.ask('/signals') : { status: -1 };
    const elapsed = Date.now() - t0;
    ok('an upstream that drips its STATUS LINE is abandoned on the same total budget -- 52s became 6',
      answer.status === 502 && elapsed < 15000);
    if (stalled) stalled.stop();
    for (const t of timers) clearInterval(t);
    for (const c of conns) c.destroy();
    await new Promise((r) => headerDrip.close(r));
  }

  // ---- one bad entry costs ONE instrument, not the whole payload --------

  {
    // The poison must be reached AFTER the label check, or nothing throws
    // and this test passes for a reason that has nothing to do with
    // isolation -- which is what my first version did, and the injection
    // round is what exposed it.
    const mixed = live.instrumentsFromSignals({
      stack: {
        components: [
          { label: 'poison', get state() { throw new Error('boom'); } },
          { label: 'brain', state: 'up' },
        ],
      },
    });
    ok('a single poisonous entry is isolated -- the healthy instruments beside it still arrive',
      mixed.length === 1 && mixed[0].def.id === 'stack:brain');
  }

  // ---- the orphan tick, with the loop genuinely still running -----------

  {
    const timers = [];
    let release;
    const gate = new Promise((r) => { release = r; });
    const src = live.createLiveStackSource({
      system: createSystem(),
      fetchJson: async () => { await gate; return REAL_SHAPED; },
      setTimer: (fn) => { timers.push(fn); return timers.length; },
      clearTimer: () => {},
    });
    src.start();
    timers[timers.length - 1]();      // first tick, blocks in fetch
    src.stop();
    src.start();                       // running is TRUE again, new generation
    const scheduledByRestart = timers.length;
    release();
    await new Promise((r) => setTimeout(r, 30));
    ok('a restart does not resurrect the ORPHANED tick -- exactly one loop is alive, not two',
      timers.length === scheduledByRestart);
    src.stop();
  }

  // ---- round three: what the second pair of verdicts found ---------------

  {
    // A PROTOTYPE KEY IS NOT A MAPPED STATE. `c.state in STACK_STATE`
    // resolves 'toString' off Object.prototype, so `status` becomes a
    // FUNCTION and an unknown server word is laundered straight past Rule
    // 3 -- the rule this file's header says has its own test. It did not.
    // (test-adversary, 2026-08-15: the `hasOwn` -> `in` injection MISSED.)
    for (const word of ['toString', 'constructor', 'hasOwnProperty', '__proto__']) {
      const made = live.instrumentsFromSignals({ stack: { components: [{ label: 'x', state: word }] } });
      ok(`an unknown state named "${word}" stays a raw STRING -- no prototype key becomes a mapped state`,
        made.length === 1 && made[0].status === word && typeof made[0].status === 'string');
    }
    ok('a null state fails closed as a string rather than vanishing',
      live.instrumentsFromSignals({ stack: { components: [{ label: 'x', state: null }] } })[0].status === 'null');
  }

  {
    // The disambiguator kept one map of id -> FIRST name, so the THIRD of
    // these compared against the wrong name and was split off as a third
    // instrument -- the duplication the block exists to prevent, in the
    // direction nobody looked (test-adversary, 2026-08-15).
    const three = live.instrumentsFromSignals({
      stack: {
        components: [
          { label: 'voice line', state: 'up' },
          { label: 'voice-line', state: 'up' },
          { label: 'voice-line', state: 'up' },
        ],
      },
    });
    ok('two DISTINCT labels and one REPEAT make exactly two instruments, not three',
      three.length === 2 &&
      three[0].def.id === 'stack:voice-line' && three[1].def.id === 'stack:voice-line-2');
  }

  {
    // THE DIAGNOSTIC ADDED TO PROVE THIS SOURCE CAN REPORT ITS OWN SILENCE
    // WAS REPORTING SILENCE DURING PERFECT HEALTH. The loser of every
    // successful race kept running: three good polls left timeouts: 3 and
    // three live timers, forever. Both agents found it independently.
    const handles = [];
    const cleared = [];
    const src = live.createLiveStackSource({
      system: createSystem(),
      fetchJson: async () => REAL_SHAPED,
      setTimer: (fn, ms) => { const h = setTimeout(fn, ms); handles.push(h); return h; },
      clearTimer: (h) => { cleared.push(h); clearTimeout(h); },
    });
    for (let i = 0; i < 3; i += 1) await src.poll();
    ok('THREE SUCCESSFUL POLLS LEAVE timeouts AT ZERO -- a healthy feed must not report its own silence',
      src.stats().timeouts === 0 && src.stats().polls === 3);
    ok('...and each poll CANCELS its own ceiling timer rather than leaking one per poll forever',
      cleared.length === 3);
    await new Promise((r) => setTimeout(r, 60));
    ok('...and no phantom timeout files itself after the fact', src.stats().timeouts === 0);
  }

  {
    // A dropped concurrent poll was invisible: a source being asked faster
    // than it can answer looked identical to a healthy one.
    let release;
    const gate = new Promise((r) => { release = r; });
    const src = live.createLiveStackSource({
      system: createSystem(),
      fetchJson: () => gate,
      setTimer: (fn, ms) => setTimeout(fn, ms),
      clearTimer: (h) => clearTimeout(h),
    });
    const first = src.poll();
    const second = await src.poll();
    ok('a poll arriving while one is in flight is DROPPED and COUNTED, never silently discarded',
      second.dropped === 1);
    release(REAL_SHAPED);
    await first;
    ok('...and the dropped one did not disturb the poll that was already running',
      src.stats().polls === 1 && src.stats().failures === 0);
  }

  {
    // THE CEILING USED TO BE ARMED ONLY WHEN AN AbortController WAS HANDED
    // IN, so on any platform without one -- and in every test that omits
    // it, which is all of them above -- this reader had NO ceiling at all,
    // silently (test-adversary, 2026-08-15).
    const t0 = Date.now();
    let threw = null;
    try {
      await live.createFetchJson(() => new Promise(() => {}), undefined, 150)('/signals');
    } catch (e) { threw = e; }
    ok('the reader has a ceiling even with NO AbortController -- abort is the courtesy, the race is the guarantee',
      threw !== null && Date.now() - t0 < 3000);

    // A body that never arrives is a different event from headers that
    // never arrive, and only one of them used to be bounded.
    let threw2 = null;
    const t1 = Date.now();
    try {
      await live.createFetchJson(
        async () => ({ ok: true, status: 200, json: () => new Promise(() => {}) }), undefined, 150,
      )('/signals');
    } catch (e) { threw2 = e; }
    ok('a response whose BODY never arrives is bounded too, not only its headers',
      threw2 !== null && Date.now() - t1 < 3000);

    // `!res.ok` is truthy for the STRING 'false', so an error response
    // wearing a stringly-typed flag was returned as a payload.
    let threw3 = null;
    try {
      await live.createFetchJson(
        async () => ({ ok: 'false', status: 502, json: async () => ({ error: 'down' }) }), undefined, 500,
      )('/signals');
    } catch (e) { threw3 = e; }
    ok("a response flagged ok: 'false' is a FAILURE -- the check is `!== true`, not a negation",
      threw3 !== null && /502/.test(threw3.message));

    let opts = null;
    await live.createFetchJson(async (u, o) => { opts = o; return { ok: true, status: 200, json: async () => ({}) }; })('/x');
    ok('the reader asks for no-store -- a cached signals payload is a stale machine reported as live',
      opts !== null && opts.cache === 'no-store');
  }

  // ---- the meta-test: this file can actually FAIL ------------------------

  // The copy must NOT run this block itself, or it spawns a copy of a copy
  // forever. The env flag is the recursion base case, and the copy is a
  // real run of everything else.
  if (!process.env.S5_METATEST) {
    const me = fs.readFileSync(__filename, 'utf8');
    // The copy MUST live beside this file: every path here is resolved from
    // __dirname, so a copy in the system temp dir dies on import and exits 1
    // for the wrong reason -- which is exactly what this assertion caught
    // about its own first version. The name deliberately does not start with
    // "test_", so run-tests.sh never globs it.
    const tmp = path.join(__dirname, `.s5-metatest-${process.pid}.js`);
    fs.writeFileSync(tmp, me.replace(
      "  console.log(`\\n${passed}/${passed + failed} passed`);",
      "  ok('DELIBERATE FAILURE -- the meta-test', false);\n  console.log(`\\n${passed}/${passed + failed} passed`);",
    ));
    const { status, stdout } = require('child_process').spawnSync('node', [tmp],
      { encoding: 'utf8', timeout: 180000, env: { ...process.env, S5_METATEST: '1' } });
    // Exit 1 alone proves nothing -- a syntax error exits 1 too. The child
    // must have RUN, reached the injected assertion, and reported it.
    ok('the meta-test child really ran this file rather than dying on load',
      /ok   THE FEED IS ITSELF AN INSTRUMENT/.test(stdout || '') &&
      /FAIL DELIBERATE FAILURE/.test(stdout || ''));
    fs.unlinkSync(tmp);
    // ==================================================================
    // AND IT MUST GO RED WHEN THE DEV SERVER IS NOT THERE.
    //
    // THE HARDEST LESSON OF THIS SLICE, and my own injection round is what
    // taught it. The test-adversary proved on 2026-08-15 that five of nine
    // server assertions passed against a server that was not running. I
    // fixed that by adding `ok('THE DEV SERVER ACTUALLY CAME UP')` and
    // changing every `!== 200` to `=== 405` -- and then, on 2026-08-21,
    // injected the removal of that very assertion and the suite stayed
    // GREEN. Of course it did: DELETING AN ASSERTION NEVER FAILS A RUN,
    // and a run where the server is healthy cannot demonstrate a guard
    // that only matters when it is not.
    //
    // So the environment is broken on purpose, in a child, and the gate is
    // required to NOTICE. This is the only shape that can defend the
    // came-up proof and the exact-405 codes at the same time: revert
    // either one and this child goes green, which turns this red.
    // ==================================================================
    const blind = require('child_process').spawnSync('node', [__filename], {
      encoding: 'utf8', timeout: 180000,
      env: { ...process.env, S5_METATEST: '1', S5_KILL_SERVER: '1' },
    });
    ok('THE GATE GOES RED WHEN THE DEV SERVER NEVER CAME UP -- it cannot pass against nothing',
      blind.status === 1);
    ok('...and it says WHY, naming the came-up proof rather than dying of something else',
      /FAIL THE DEV SERVER ACTUALLY CAME UP/.test(blind.stdout || ''));
    ok('...and it did not hang while failing -- a hung gate is not a verdict',
      blind.status !== null);

    // Without this, every "N/N passed" above is a number with no meaning:
    // a harness that cannot report a failure reports success for free.
    ok('THE HARNESS CAN FAIL: an injected failing assertion makes this file exit non-zero', status === 1);
    // The copy is run with a hard timeout above; if it HUNG rather than
    // failed, spawnSync returns null status, and that must not read as a
    // pass. A hung gate is worse than a red one.
    ok('...and the copy FAILED rather than hanging -- a hung gate is not a verdict', status !== null);
  }

  console.log(`\n${passed}/${passed + failed} passed`);
  if (failed > 0) process.exit(1);
  // Reached the end with everything green -- the ONLY way this file may
  // report success.
  process.exitCode = 0;
})().catch((e) => {
  console.error('  FAIL suite errored:', e.message);
  process.exit(1);
});
