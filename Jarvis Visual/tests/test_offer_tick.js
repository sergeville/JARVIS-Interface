#!/usr/bin/env node
// THE OFFER, ACTUALLY FIRING.
//
// Owed since 2026-08-08 and named twice as the weakest thing on the page:
// `suggestJob` and `offerGate` are proven under 19 injections, but they are
// PURE. The wiring around them — offerTick, the part that measures quiet,
// decides what typing means, holds a signal before believing it, and writes
// the card — had never been executed by anything. Serge has never seen the
// card fire, by construction: it needs five minutes of silence.
//
// So this drives the REAL offerTick against a fake document and a fake clock,
// and watches the card. Nothing here paraphrases the page: offerTick,
// offerAnswer, suggestJob, offerGate and the OFFER constants are all sliced
// out of jarvis.html, and the module-level state they mutate is sliced too,
// so a test can watch the hold clock and the mute survive across ticks the
// way they do in the browser.
//
// The failure this guards against is not "the offer never shows" — it is the
// opposite: the offer showing while he is mid-sentence, mid-permission, or
// mid-question. On this page an interruption is the expensive mistake.

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const src = fs.readFileSync(path.join(__dirname, '..', 'jarvis.html'), 'utf8');

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log('ok   ' + name); passed++; }
  catch (e) { console.log('FAIL ' + name + '\n     ' + e.message); failed++; }
}

function fn(name) {
  const start = src.indexOf('function ' + name + '(');
  assert.ok(start !== -1, 'no function ' + name + ' in jarvis.html');
  let i = src.indexOf('{', start), depth = 0, end = -1;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}' && --depth === 0) { end = j + 1; break; }
  }
  return src.slice(start, end);
}
// The offer's module state, taken from the page rather than re-declared here.
// If the page renames or re-seeds one of these, this slice fails loudly
// instead of the tests quietly proving something about a copy.
function stateDecls() {
  const lines = [
    /let offerHeldSince = 0[^\n]*\n/,
    /let lastBusyAt = [^\n]*\n/,
    /const offerMuted = \{\};[^\n]*\n/,
    /let ideasSig = null[^\n]*\n/,
  ];
  return lines.map(re => {
    const m = re.exec(src);
    assert.ok(m, 'the offer lost a piece of its state: ' + re);
    return m[0];
  }).join('');
}
const OFFER = eval('(' + /const OFFER = ([\s\S]*?);\n/.exec(src)[1] + ')');

// ---- the fake world -------------------------------------------------------

function makeWorld() {
  const card = {
    cls: new Set(), attrs: {},
    classList: {
      add: (c) => card.cls.add(c),
      remove: (c) => card.cls.delete(c),
      contains: (c) => card.cls.has(c),
    },
    setAttribute: (k, v) => { card.attrs[k] = v; },
    parts: {'.of-job': {textContent: ''}, '.of-why': {textContent: ''}},
    querySelector: (sel) => card.parts[sel],
  };
  const typed = {value: '', id: 'typed'};
  const bodyCls = new Set();
  const doc = {
    activeElement: null,
    body: {classList: {contains: (c) => bodyCls.has(c)}},
    getElementById: (id) => id === 'offer' ? card : id === 'typed' ? typed : null,
  };
  const w = {
    card, typed, bodyCls, doc,
    now: 1000000,
    state: 'idle', capturing: false, job: 'watch', waitingQ: null,
    face: 'civilian', applied: [],
    showing: () => card.cls.has('on'),
  };
  const FakeDate = {now: () => w.now};

  const body = ''
    + 'const OFFER = ' + JSON.stringify(OFFER) + ';\n'
    + fn('suggestJob') + '\n'
    + fn('offerGate') + '\n'
    + stateDecls()
    + 'function webActive(){ return env.capturing; }\n'
    + 'function currentFace(){ return env.face; }\n'
    + 'function deptName(f, j){ return f + ":" + j; }\n'
    + 'function applyJob(j){ env.applied.push(j); env.job = j; }\n'
    + fn('offerTick') + '\n'
    + fn('offerAnswer') + '\n'
    + 'return {offerTick, offerAnswer, seeShown: () => offerShown,'
    + '        muted: offerMuted, bump: (ms) => { lastBusyAt = Date.now() - ms; }};';

  // `state`, `capturing`, `job`, `waitingQ` are page globals offerTick reads
  // by bare name. Declared here as real bindings the harness can move.
  const made = new Function('document', 'Date', 'env',
    'let state = "idle", capturing = false, job = "watch", waitingQ = null;\n'
  + 'const sync = () => { state = env.state; capturing = env.capturing;'
  + '                     job = env.job; waitingQ = env.waitingQ; };\n'
  + 'const _tickRaw = (function(){\n' + body + '\n})();\n'
  + 'return Object.assign({}, _tickRaw, {'
  + '  offerTick: (d) => { sync(); return _tickRaw.offerTick(d); },'
  + '  offerAnswer: (t) => { sync(); return _tickRaw.offerAnswer(t); }});'
  )(w.doc, FakeDate, w);
  return Object.assign(w, made);
}

// A payload that WOULD suggest a job. Read off suggestJob rather than
// guessed: a card in `review` is waiting for his eyes, which ranks to
// BRIEFING — and the world below starts on `watch`, so the suggestion is
// genuinely a change. The first fixture here used `open`, which suggests
// nothing unless a session is also busy, and every test failed for that
// reason rather than for the reason it was written.
const TASKS = [{status: 'review', title: 'waiting on you'}];
function payload(over) {
  return Object.assign({tasks: TASKS, ideas: [], sessions: []}, over || {});
}

// Drive the clock forward far enough that quiet AND hold are both satisfied.
function settle(w, d) {
  w.offerTick(payload(d));                 // first tick establishes the hold
  w.now += OFFER.QUIET_MS + OFFER.HOLD_MS + 1000;
  w.bump(OFFER.QUIET_MS + 1000);           // he has been silent that long
  w.offerTick(payload(d));
}

// ---- does it fire at all --------------------------------------------------

test('THE OFFER FIRES — the thing nobody had ever seen', () => {
  const w = makeWorld();
  settle(w);
  assert.ok(w.showing(), 'the offer never appeared under ideal conditions');
  assert.strictEqual(w.card.attrs['aria-hidden'], 'false');
  assert.ok(w.card.parts['.of-job'].textContent.length > 0, 'the card has no job on it');
  assert.ok(w.card.parts['.of-why'].textContent.length > 0, 'the card gives no reason');
});

test('it does NOT fire on the first tick — a signal must hold first', () => {
  const w = makeWorld();
  w.bump(OFFER.QUIET_MS + 1000);           // quiet, but the signal is brand new
  w.offerTick(payload());
  assert.ok(!w.showing(), 'a suggestion showed the instant it appeared');
});

test('it does not fire before the room has been quiet', () => {
  const w = makeWorld();
  w.offerTick(payload());
  w.now += OFFER.HOLD_MS + 1000;           // held long enough...
  w.offerTick(payload());                  // ...but he was busy just now
  assert.ok(!w.showing(), 'the offer landed without the silence it requires');
});

// ---- the interruptions it must never commit -------------------------------

const NEVER = [
  ['he is speaking',            (w) => { w.state = 'speaking'; }],
  ['he is listening',           (w) => { w.state = 'listening'; }],
  ['the microphone is open',    (w) => { w.capturing = true; }],
  ['a permission is pending',   (w) => { w.bodyCls.add('alert'); }],
  ['a question of mine is open',(w) => { w.waitingQ = 'well?'; }],
  ['he is typing',              (w) => { w.doc.activeElement = w.typed;
                                         w.typed.value = 'half a command'; }],
];

for (const [what, set] of NEVER) {
  test('it stays hidden while ' + what, () => {
    const w = makeWorld();
    settle(w);
    assert.ok(w.showing(), 'precondition failed: the offer was not up');
    set(w);
    w.offerTick(payload());
    assert.ok(!w.showing(), 'the offer interrupted him while ' + what);
  });
}

test('TYPING FEEDS THE QUIET CLOCK — composing is not silence', () => {
  // The terminal's red pen found this one: the reset set left typing out, so
  // four minutes composing a long command counted as four minutes of quiet
  // and the offer could land mid-sentence.
  const w = makeWorld();
  w.doc.activeElement = w.typed;
  w.typed.value = 'a long command';
  w.bump(OFFER.QUIET_MS + 1000);
  w.offerTick(payload());                  // this tick must RESET the clock
  w.doc.activeElement = null; w.typed.value = '';
  w.now += OFFER.HOLD_MS + 1000;
  w.offerTick(payload());
  assert.ok(!w.showing(), 'time spent typing was counted as quiet');
});

test('an empty box with the cursor in it is NOT typing', () => {
  const w = makeWorld();
  settle(w);
  w.doc.activeElement = w.typed;           // focused, nothing written
  w.offerTick(payload());
  assert.ok(w.showing(), 'a focused empty box suppressed the offer forever');
});

// ---- the belt-and-braces the behaviour tests CANNOT reach ------------------
//
// Injection found these two, and they are worth being precise about: cutting
// `speaking` and `typing` out of the gate call changed NOTHING observable,
// because both conditions also reset the quiet clock a few lines above, and
// the quiet rule then refuses the offer on its own. The product is not broken
// — it is defended twice. But "defended twice" is only true while both
// defences exist, and a behaviour test can never see the second one, because
// the first one keeps answering first. So these two are SOURCE assertions,
// deliberately, and they are the only two in this file.
const tickSrc = fn('offerTick');

test('the gate is told about SPEAKING, even though quiet would also refuse', () => {
  assert.ok(/speaking: state === 'speaking' \|\| state === 'listening' \|\| capturing,/
    .test(tickSrc), 'the gate no longer hears that he is talking');
});

test('the gate is told about TYPING, even though quiet would also refuse', () => {
  assert.ok(/typing: isTyping,/.test(tickSrc),
    'the gate no longer hears that he is composing');
});

// ---- the answer -----------------------------------------------------------

test('STAY mutes that job, and the mute survives the next tick', () => {
  const w = makeWorld();
  settle(w);
  const job = w.seeShown();
  w.offerAnswer(false);
  assert.ok(!w.showing(), 'the card stayed up after being answered');
  assert.strictEqual(w.applied.length, 0, 'STAY switched the job anyway');
  w.now += 1000;
  w.offerTick(payload());
  assert.ok(!w.showing(), 'the offer asked again one second after a STAY');
  assert.ok(w.muted[job] > w.now, 'the mute did not outlive the answer');
});

test('the mute EXPIRES — a STAY is not forever', () => {
  const w = makeWorld();
  settle(w);
  w.offerAnswer(false);
  w.now += OFFER.MUTE_MS + 1000;
  w.bump(OFFER.QUIET_MS + 1000);
  w.offerTick(payload());
  assert.ok(w.showing(), 'a single STAY silenced that suggestion permanently');
});

test('SWITCH applies the job, exactly once, and closes the card', () => {
  const w = makeWorld();
  settle(w);
  const job = w.seeShown();
  w.offerAnswer(true);
  assert.deepStrictEqual(w.applied, [job], 'SWITCH did not apply the offered job');
  assert.ok(!w.showing(), 'the card stayed up after being taken');
  w.offerAnswer(true);                     // a second click on a dead card
  assert.deepStrictEqual(w.applied, [job], 'a second click applied the job again');
});

test('the card relabels when the FACE changes under it', () => {
  const w = makeWorld();
  settle(w);
  const before = w.card.parts['.of-job'].textContent;
  w.face = 'navy';
  w.offerTick(payload());
  assert.notStrictEqual(w.card.parts['.of-job'].textContent, before,
    'the card and the dial would speak two different languages');
});

test('it never offers the job he is already on', () => {
  const w = makeWorld();
  settle(w);
  w.job = w.seeShown();
  w.offerTick(payload());
  assert.ok(!w.showing(), 'the page offered to switch to where it already is');
});

console.log('\n' + passed + '/' + (passed + failed) + ' passed');
process.exit(failed ? 1 : 0);
