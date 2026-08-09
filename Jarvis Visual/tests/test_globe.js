#!/usr/bin/env node
// PHASE 6 — THE GLOBE GLOW-UP.
//
// Canvas colours on this page are deliberately NOT tokenised, which the plan
// says plainly: they are drawn, not themed, and a blind sweep is how a
// zero-visual-change refactor becomes visible. So this phase is a scoped,
// deliberate edit, and these tests guard the two things that can go wrong in
// a way nobody would notice for weeks:
//
//   1. A CALLOUT THAT PRINTS A NUMBER IT DOES NOT HAVE. The vault count is
//      unknown until the graph has been loaded once, and "0 notes" beside a
//      full vault is a worse lie than silence. This is the concept's most
//      decorative feature landing on the page whose whole doctrine is that
//      no instrument invents data.
//   2. A SHADOW DRAWN IN ADDITIVE MODE. The globe's particle pass runs under
//      globalCompositeOperation = 'lighter'; a terminator drawn there would
//      BRIGHTEN the dark side, which is the exact opposite of the change and
//      looks merely "a bit off" rather than broken.

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

// --- the callouts never invent a number ----------------------------------

// Run the real function against a fake canvas that records what it drew.
function runCallouts({ nodes, sessions, model }) {
  const drawn = [];
  const ctx = {
    save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {},
    fillText(s) { drawn.push(s); },
    set font(v) {}, set textAlign(v) {}, set textBaseline(v) {},
    set strokeStyle(v) {}, set fillStyle(v) {}, set lineWidth(v) {},
  };
  const body = fn('drawGlobeCallouts');
  const f = new Function('ctx', 'cx', 'cy', 'gNodes', 'calloutSessions',
                         'calloutModel', 'ACCENT_RGB',
                         body + '\nreturn drawGlobeCallouts;');
  f(ctx, 100, 100, new Array(nodes).fill(0), sessions, model, '0,150,255')(50);
  return drawn;
}

test('a known vault count is drawn', () => {
  assert.ok(runCallouts({ nodes: 42, sessions: null, model: null })
              .some(s => s === '42 notes'));
});

test('an UNLOADED graph draws no note count at all — not "0 notes"', () => {
  // gNodes is empty until the vault graph has been opened once. A zero here
  // would sit beside a full vault and read as a measurement.
  const drawn = runCallouts({ nodes: 0, sessions: 2, model: 'claude-opus-5' });
  assert.ok(!drawn.some(s => /notes/.test(s)),
    'it printed a note count with nothing loaded: ' + JSON.stringify(drawn));
});

test('an unknown session count draws nothing', () => {
  const drawn = runCallouts({ nodes: 0, sessions: null, model: null });
  assert.deepStrictEqual(drawn, [], 'it drew something it did not know');
});

test('a known session count is drawn, and reads singular at one', () => {
  assert.ok(runCallouts({ nodes: 0, sessions: 1, model: null }).includes('1 session'));
  assert.ok(runCallouts({ nodes: 0, sessions: 3, model: null }).includes('3 sessions'));
});

test('ZERO sessions is a real reading and IS drawn', () => {
  // different from the vault count on purpose: the page always knows how many
  // sessions there are, so zero is a fact rather than an absence.
  assert.ok(runCallouts({ nodes: 0, sessions: 0, model: null }).includes('0 sessions'));
});

test('no model means no model line — never a placeholder dressed as data', () => {
  const drawn = runCallouts({ nodes: 0, sessions: 0, model: null });
  assert.ok(!drawn.some(s => /model|claude/i.test(s)), JSON.stringify(drawn));
});

test('the callouts read the SAME values the badge does', () => {
  assert.ok(/calloutSessions = Array\.isArray\(sessions\) \? sessions\.length : null/.test(src),
    'the globe counts sessions its own way and could disagree with the badge');
  assert.ok(/calloutModel = \(stats && stats\.model\) \? stats\.model : null/.test(src),
    'the globe reads the model its own way');
});

test('no callout string is hardcoded in the drawing function', () => {
  const body = fn('drawGlobeCallouts');
  assert.ok(!/claude-|'\d+ notes'|Serge/.test(body),
    'a literal here would survive a dead payload as a lie');
});

// --- the atmosphere is drawn in the right mode ---------------------------

test('the TERMINATOR is drawn in source-over, never additive', () => {
  const i = src.indexOf('PHASE 6: THE TERMINATOR');
  assert.ok(i !== -1, 'the terminator is gone');
  const back = src.slice(Math.max(0, i - 400), i);
  assert.ok(/globalCompositeOperation = 'source-over'/.test(back),
    'the shadow is drawn while the canvas is still additive — it would BRIGHTEN');
});

// Slice to the block's own closing brace, never a fixed number of characters.
// The first version of the clip test used a 900-char window and went red
// against correct code because `ctx.restore()` sat at character 930 — a test
// that fails when a COMMENT grows is measuring the wrong thing.
function blockAfter(marker) {
  const i = src.indexOf(marker);
  assert.ok(i !== -1, 'missing marker: ' + marker);
  const end = src.indexOf('\n  }', i);
  assert.ok(end !== -1, 'unterminated block after ' + marker);
  return src.slice(i, end);
}

test('the terminator is CLIPPED to the sphere', () => {
  const body = blockAfter('PHASE 6: THE TERMINATOR');
  assert.ok(/ctx\.clip\(\)/.test(body), 'the shadow would darken the field behind the globe');
  assert.ok(/ctx\.save\(\)/.test(body) && /ctx\.restore\(\)/.test(body),
    'an unrestored clip would silently crop everything drawn afterwards');
});

test('the rim glow IS additive, and sits outside the limb', () => {
  const i = src.indexOf('PHASE 6: ATMOSPHERE');
  assert.ok(i !== -1, 'the rim glow is gone');
  const back = src.slice(Math.max(0, i - 3000), i);
  const lastLighter = back.lastIndexOf("globalCompositeOperation = 'lighter'");
  const lastSource = back.lastIndexOf("globalCompositeOperation = 'source-over'");
  assert.ok(lastLighter > lastSource, 'the rim glow is not being drawn additively');
  const body = blockAfter('PHASE 6: ATMOSPHERE');
  assert.ok(/emberR \* 1\.[0-9]+/.test(body), 'the glow does not extend past the limb');
});

test('all three light sources agree on where the sun is (up-left)', () => {
  // the body gradient, the white-hot core and the terminator each pick an
  // offset; if they disagree the globe reads as lit from two directions and
  // nobody can say why it looks wrong.
  assert.ok(/cx - emberR \* 0\.3/.test(src), 'the body gradient moved its light');
  assert.ok(/const gx = cx - emberR \* 0\.18, gy = cy - emberR \* 0\.2;/.test(src),
    'the core moved its light');
  assert.ok(/const lx = cx - emberR \* 0\.30, ly = cy - emberR \* 0\.32;/.test(src),
    'the terminator lights the globe from somewhere else');
});

test('the avatar stays STATE-REACTIVE — that is why a static Earth was declined', () => {
  const body = blockAfter('PHASE 6: ATMOSPHERE');
  assert.ok(/smooth/.test(body), 'the rim glow ignores the state and is pure decoration');
});

test('the callouts take their colour from the FACE', () => {
  const body = fn('drawGlobeCallouts');
  assert.ok(/ACCENT_RGB/.test(body), 'the callouts ignore the face dial');
  assert.ok(/refreshAccent\(\);/.test(src), 'the cached accent is never refreshed');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
