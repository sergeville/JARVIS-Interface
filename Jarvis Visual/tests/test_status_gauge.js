#!/usr/bin/env node
// PHASE 4 — THE SYSTEM STATUS RING.
//
// This is the only number on the page that is a JUDGEMENT rather than a
// reading, which makes it the easiest place on the page to tell a comfortable
// lie. Two properties carry the whole thing:
//
//   1. NO PATH FABRICATES 100%. An empty payload, a missing key, a list of
//      nothing but off-by-choice components — none of those may render as
//      OPTIMAL. A ring that looks healthy because there was nothing to
//      measure is worse than no ring, because it is believed.
//   2. OFF BY CHOICE IS NOT A FAILURE. ./jarvis.sh says "off -- not in use"
//      and means it; the terminal line is off most of the day. Counting it
//      would pin the machine at DEGRADED forever, and an instrument that
//      cries wolf gets ignored.

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
const stackHealth = new Function(fn('stackHealth') + '\nreturn stackHealth;')();
const C = (label, state) => ({ label, state });

// --- the fraction ---------------------------------------------------------

test('all up is OPTIMAL, and it is a real 100%', () => {
  const h = stackHealth([C('a', 'up'), C('b', 'up')]);
  assert.strictEqual(h.word, 'OPTIMAL');
  assert.strictEqual(h.pct, 1);
  assert.strictEqual(h.expected, 2);
});

test('one down of three is DEGRADED, not DOWN', () => {
  const h = stackHealth([C('a', 'up'), C('b', 'up'), C('c', 'down')]);
  assert.strictEqual(h.word, 'DEGRADED');
  assert.ok(h.pct > 0 && h.pct < 1);
});

test('everything down is DOWN', () => {
  const h = stackHealth([C('a', 'down'), C('b', 'down')]);
  assert.strictEqual(h.word, 'DOWN');
  assert.strictEqual(h.pct, 0);
});

// --- off by choice is not a failure --------------------------------------

test('an OFF component is excluded from the denominator', () => {
  // the live shape: four up, terminal line off. That is a healthy machine.
  const h = stackHealth([C('server', 'up'), C('brain', 'up'), C('whisper', 'up'),
                         C('kokoro', 'up'), C('terminal line', 'off')]);
  assert.strictEqual(h.word, 'OPTIMAL', 'an off-by-choice component read as a failure');
  assert.strictEqual(h.expected, 4, 'the off component was counted');
});

test('OFF is excluded from the numerator too — it is not "up"', () => {
  const h = stackHealth([C('a', 'up'), C('b', 'off'), C('c', 'down')]);
  assert.strictEqual(h.up, 1);
  assert.strictEqual(h.expected, 2);
});

// --- NO PATH FABRICATES 100% ---------------------------------------------

test('an EMPTY list is UNKNOWN, never OPTIMAL', () => {
  const h = stackHealth([]);
  assert.strictEqual(h.word, 'UNKNOWN');
  assert.strictEqual(h.pct, null, 'an empty list produced a percentage');
});

test('a list of nothing but OFF is UNKNOWN, never OPTIMAL', () => {
  // the trap case: filtering off-by-choice out leaves an empty denominator,
  // and 0/0 is the classic way a gauge invents a perfect score.
  const h = stackHealth([C('a', 'off'), C('b', 'off')]);
  assert.strictEqual(h.word, 'UNKNOWN');
  assert.strictEqual(h.pct, null);
});

test('a missing or malformed payload is UNKNOWN', () => {
  for (const bad of [undefined, null, 'stack', 42, {}]) {
    const h = stackHealth(bad);
    assert.strictEqual(h.word, 'UNKNOWN', String(bad) + ' produced a verdict');
    assert.strictEqual(h.pct, null);
  }
});

test('NO input of any shape can return OPTIMAL without counting something', () => {
  // exhaustive over the shapes that reach this function
  const states = ['up', 'down', 'off', 'weird', undefined];
  for (const a of states) for (const b of states) {
    const h = stackHealth([C('a', a), C('b', b)]);
    if (h.word === 'OPTIMAL') {
      assert.ok(h.expected > 0, 'OPTIMAL with an empty denominator');
      assert.strictEqual(h.up, h.expected, 'OPTIMAL without every counted component up');
    }
    if (h.pct !== null) assert.ok(h.expected > 0, 'a percentage with nothing counted');
  }
});

test('an unknown state counts as EXPECTED but not as up — it fails closed', () => {
  const h = stackHealth([C('a', 'up'), C('b', 'gremlins')]);
  assert.strictEqual(h.expected, 2, 'an unrecognised state was silently dropped');
  assert.strictEqual(h.up, 1);
  assert.strictEqual(h.word, 'DEGRADED');
});

test('stackHealth is PURE — no clock, no DOM, no payload beyond its argument', () => {
  const body = fn('stackHealth');
  // `new Date()` does not contain "Date." — the first version of this guard
  // missed it, and an injection that made the verdict depend on the hour ran
  // clean. THIRD time tonight that a purity check named one spelling of the
  // clock; the shape of the mistake is what matters, not the spelling.
  assert.ok(!/document\.|Date\.|new Date|performance\.|localStorage|fetch/.test(body),
    'the judgement reads the world instead of its argument');
});

// --- the ring tells the truth the function computed -----------------------

test('UNKNOWN does not paint the ring green', () => {
  assert.ok(/#health\.unknown[^}]*stroke: var\(--off\)/.test(src.replace(/\s+/g, ' ')),
    'a ring with nothing to measure would look healthy');
});

test('the three verdicts each get their own colour, from the STATUS tokens', () => {
  const flat = src.replace(/\s+/g, ' ');
  assert.ok(/\.hr-arc \{[^}]*stroke: var\(--ok\)/.test(flat), 'OPTIMAL is not the ok colour');
  assert.ok(/#health\.degraded[^}]*var\(--warn\)/.test(flat), 'DEGRADED is not the warn colour');
  assert.ok(/#health\.down[^}]*var\(--bad\)/.test(flat), 'DOWN is not the bad colour');
});

test('the arc length is DRIVEN by the fraction, not by a class', () => {
  const body = fn('renderHealth');
  assert.ok(/strokeDashoffset = String\(119\.4 \* \(1 - /.test(body),
    'the ring is not drawn from the computed percentage');
});

test('an UNKNOWN ring draws EMPTY, not full', () => {
  const body = fn('renderHealth');
  assert.ok(/h\.pct === null \? 0 : h\.pct/.test(body),
    'a null percentage would render as a complete ring');
});

test('the sub-line never states a fraction it does not have', () => {
  const body = fn('renderHealth');
  assert.ok(/h\.pct === null \? 'nothing to measure'/.test(body),
    'the caption would read "0 of 0 up", which sounds like a measurement');
});

test('the tooltip names every component, including the excluded ones', () => {
  const body = fn('renderHealth');
  assert.ok(/off, not counted/.test(body),
    'components dropped from the denominator are dropped silently');
  assert.ok(/comps\.map/.test(body), 'the tooltip does not enumerate the components');
});

test('the ring is fed on every poll, from the same payload as the stack list', () => {
  assert.ok(/renderStack\(d\.stack\);\n\s*renderHealth\(d\.stack\);/.test(src),
    'the ring and the stack list could show different moments');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
