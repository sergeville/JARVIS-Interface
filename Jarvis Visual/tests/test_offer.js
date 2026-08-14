#!/usr/bin/env node
// PHASE 7, SLICE TWO — THE OFFER.
//
// The page may SUGGEST a job. It may never take one. Everything here is
// written against that sentence, because the failure mode is not a crash —
// it is a page that quietly rearranges itself, or one that nags.
//
// Decision 14 RANKS the trigger: silence beats patience beats evidence. The
// numbers are tunable and the ranking is not, so these tests pin the ranking
// by driving the real functions, and read the constants from the file rather
// than restating them here — a test that hardcodes 5 minutes would go red on
// a tuning Serge is allowed to make.

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
  assert.ok(start !== -1, 'no function ' + name);
  let i = src.indexOf('{', start), depth = 0, end = -1;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}' && --depth === 0) { end = j + 1; break; }
  }
  return src.slice(start, end);
}
const OFFER = eval('(' + /const OFFER = ([\s\S]*?);\n/.exec(src)[1] + ')');
const suggestJob = new Function(fn('suggestJob') + '\nreturn suggestJob;')();
const offerGate = new Function('OFFER', fn('offerGate') + '\nreturn offerGate;')(OFFER);

const T = (s) => ({ status: s });
// A gate call that would PASS — each test then breaks exactly one thing, so a
// failure names its own cause instead of being one of nine possible reasons.
const OK = () => ({
  suggestion: 'workshop', currentJob: 'watch',
  speaking: false, typing: false,
  permissionPending: false, questionPending: false,
  quietMs: OFFER.QUIET_MS + 1, heldMs: OFFER.HOLD_MS + 1, mutedMsLeft: 0,
});

// --- the suggestion is a pure reading of real data -----------------------

test('the baseline passes — the fixture proves something', () => {
  assert.strictEqual(offerGate(OK()), true);
});

test('no signal suggests NOTHING — silence is the common answer', () => {
  assert.strictEqual(suggestJob({ tasks: [] }), null);
  assert.strictEqual(suggestJob({}), null);
});

test('work in flight argues for the workshop', () => {
  assert.strictEqual(suggestJob({ tasks: [T('active')] }).job, 'workshop');
  assert.strictEqual(suggestJob({ tasks: [T('test')] }).job, 'workshop');
});

test('cards waiting on his eyes argue for the briefing', () => {
  assert.strictEqual(suggestJob({ tasks: [T('review'), T('review')] }).job, 'briefing');
});

test('a changed ideas note argues for the brainstorm', () => {
  assert.strictEqual(suggestJob({ tasks: [], ideasChanged: true }).job, 'brainstorm');
});

test('queued work with sessions busy argues for the watch', () => {
  assert.strictEqual(suggestJob({ tasks: [T('open')], sessionsBusy: 2 }).job, 'watch');
});

test('queued work with NO session busy argues for nothing', () => {
  assert.strictEqual(suggestJob({ tasks: [T('open')], sessionsBusy: 0 }), null);
});

test('two signals at once resolve by RANK, never by chance', () => {
  const both = suggestJob({ tasks: [T('active'), T('review')], ideasChanged: true });
  assert.strictEqual(both.job, 'workshop', 'the ranking is not being honoured');
});

test('the suggestion always carries its case — a nag has no réplique', () => {
  for (const s of [{ tasks: [T('active')] },
                   { tasks: [T('review')] },
                   { tasks: [], ideasChanged: true },
                   { tasks: [T('open')], sessionsBusy: 1 }]) {
    const r = suggestJob(s);
    assert.ok(r.because && r.because.length > 3, 'a suggestion with no case');
  }
});

test('the case never quotes free text from the payload', () => {
  // a suggestion is rendered into the page, and the tasks come from a file
  // anyone can edit — the closed-vocabulary rule the MAIL strip already obeys
  // ANY read of a free-text field, however it is spelled. The first version
  // of this guard pinned `t.title`, and an injection reading `tasks[0].title`
  // walked straight past it — an enumerated guard is defeated by the first
  // spelling nobody thought of, which is this project's oldest lesson.
  // AN ALLOW-LIST, not a blacklist. This was a list of forbidden field names
  // until the terminal session's red pen pointed out the obvious: `.gist`,
  // `.body`, `.label`, `.name`, bracket access — every one of them walks past
  // a blacklist. My own commit that same night said an enumerated guard is
  // defeated by the first spelling nobody thought of, and then I shipped one.
  // Now: every property this function reads off a task must be on the list.
  const ALLOWED = ['tasks', 'status', 'length', 'ideasChanged', 'sessionsBusy',
                   'filter', 'job', 'because'];
  // COMMENTS STRIPPED FIRST. This guard failed on its own first run because
  // the comment explaining it NAMES `.gist`, `.body` and `.label` as examples
  // of what a blacklist misses — so the allow-list read the prose describing
  // it and reported three violations that were not code. Eighth time on this
  // record that grepping source punished the explanation beside it.
  const body = fn('suggestJob').replace(/\/\/[^\n]*/g, '');
  const reads = [...body.matchAll(/\.([a-zA-Z_][a-zA-Z0-9_]*)/g)].map(m => m[1]);
  const bad = [...new Set(reads)].filter(r => !ALLOWED.includes(r));
  assert.deepStrictEqual(bad, [],
    'suggestJob reads ' + bad.join(', ') + ' — free text from the payload can reach the page');
  assert.ok(!/\[[^\]]*\]\s*\./.test(body.replace(/tasks\[0\]/g, '')),
    'bracket access would step around the allow-list');
});

test('suggestJob is PURE — no clock, no storage, no DOM', () => {
  const body = fn('suggestJob');
  // `new Date()` is a clock too. The first version of this guard named only
  // Date.now and an injection reading the hour sailed through it.
  assert.ok(!/Date\.now|new Date|document\.|localStorage|performance\./.test(body),
    'the suggestion reads the world instead of its argument');
});

// --- SILENCE beats everything --------------------------------------------

for (const [field, why] of [['speaking', 'he is talking'],
                            ['typing', 'he is typing'],
                            ['permissionPending', 'a permission is pending'],
                            ['questionPending', 'a question is pending']]) {
  test(`no offer while ${why}`, () => {
    const g = OK(); g[field] = true;
    assert.strictEqual(offerGate(g), false);
  });
}

test('silence OUTRANKS patience — a long quiet does not buy an interruption', () => {
  const g = OK();
  g.quietMs = OFFER.QUIET_MS * 100;
  g.heldMs = OFFER.HOLD_MS * 100;
  g.permissionPending = true;
  assert.strictEqual(offerGate(g), false,
    'a permission pending was outvoted by the clock');
});

// --- PATIENCE ------------------------------------------------------------

test('no offer before the quiet stretch has passed', () => {
  const g = OK(); g.quietMs = OFFER.QUIET_MS - 1;
  assert.strictEqual(offerGate(g), false);
});

test('no offer until the signal has HELD — no flicker between two jobs', () => {
  const g = OK(); g.heldMs = OFFER.HOLD_MS - 1;
  assert.strictEqual(offerGate(g), false);
});

test('the quiet stretch is his five minutes, and the hold is a minute', () => {
  assert.strictEqual(OFFER.QUIET_MS, 5 * 60 * 1000);
  assert.strictEqual(OFFER.HOLD_MS, 60 * 1000);
});

test('a STAY mutes that suggestion for a long stretch, not a minute', () => {
  const g = OK(); g.mutedMsLeft = 1;
  assert.strictEqual(offerGate(g), false);
  assert.ok(OFFER.MUTE_MS >= 30 * 60 * 1000, 'a STAY that expires soon is a nag');
});

// --- it never offers what he already has ---------------------------------

test('no offer for the job he is already in', () => {
  const g = OK(); g.currentJob = 'workshop';
  assert.strictEqual(offerGate(g), false);
});

test('no suggestion, no offer', () => {
  const g = OK(); g.suggestion = null;
  assert.strictEqual(offerGate(g), false);
});

test('offerGate is PURE too — it decides on its argument alone', () => {
  const body = fn('offerGate');
  assert.ok(!/Date\.now|new Date|document\.|localStorage|classList|performance\./.test(body),
    'the gate reads the world instead of its argument');
});

// --- nothing switches without his click ----------------------------------

test('ONLY offerAnswer(true) can apply a job from the offer', () => {
  const body = fn('offerTick');
  assert.ok(!/applyJob\(/.test(body),
    'the tick can switch the job by itself — the page would rearrange itself');
  assert.ok(/if \(take\) applyJob\(j\)/.test(fn('offerAnswer')),
    'SWITCH does not apply the job');
});

test('STAY mutes rather than merely closing the card', () => {
  assert.ok(/else offerMuted\[j\] = Date\.now\(\) \+ OFFER\.MUTE_MS/.test(fn('offerAnswer')),
    'a STAY that only hides the card lets the page ask again immediately');
});

test('both buttons are wired, and to different answers', () => {
  assert.ok(/offer-yes'\)[\s\S]{0,200}offerAnswer\(true\)/.test(src), 'SWITCH is not wired');
  assert.ok(/offer-no'\)[\s\S]{0,200}offerAnswer\(false\)/.test(src), 'STAY is not wired');
});

test('the offer is fed from the poll, with the live payload', () => {
  assert.ok(/\n    offerTick\(d\);/.test(src), 'the offer is never ticked');
});

test('the card speaks the FACE\'s language, like the dial does', () => {
  assert.ok(/deptName\(currentFace\(\), suggestion\.job\)/.test(fn('offerTick')),
    'the offer names a job the switcher calls something else');
});

test('the card cannot be clicked while hidden', () => {
  const at = src.indexOf('#offer {');
  const b = src.slice(at, src.indexOf('}', at));
  assert.ok(/pointer-events: none/.test(b) && /visibility: hidden/.test(b),
    'a hidden offer that still takes clicks is a trap');
});

test('the quiet clock is reset by real activity, not by polling', () => {
  const body = fn('offerTick');
  assert.ok(/webActive\(\)[\s\S]{0,160}lastBusyAt = now/.test(body),
    'the quiet clock does not follow what he and Jarvis actually do');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
