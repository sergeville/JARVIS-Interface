#!/usr/bin/env node
// fitLog() -- the activity overlay never cuts the newest message.
//
// Serge, 2026-08-07 ~5:00 PM, saying what this overlay is for: "when you
// talk, I like to read what you're saying. Sometimes I'm distracted. So if I
// miss something that you said, I could have read it at least -- I don't have
// to make you repeat yourself."
//
// The bug was that lines stack downward, so the part clipped by the height
// cap was the OPENING of the newest answer -- the half he needs. His own
// screenshot showed one of my messages starting mid-sentence.
//
// These tests DRIVE the trimming against stubbed heights rather than reading
// the source, because the property is arithmetic: what survives, and what
// gets dropped, at a given box size.

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const HTML = path.join(__dirname, '..', 'jarvis.html');
const src = fs.readFileSync(HTML, 'utf8');

function grab(name) {
  const start = src.indexOf('function ' + name + '(');
  assert.ok(start !== -1, 'function not found in jarvis.html: ' + name);
  let i = src.indexOf('{', start), depth = 0, end = -1;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}') { depth--; if (depth === 0) { end = j + 1; break; } }
  }
  assert.ok(end !== -1, 'unbalanced braces reading ' + name);
  return src.slice(start, end);
}

// ---- DOM stub with real geometry ------------------------------------------
// Each child declares a height; scrollHeight is their sum. That is the whole
// model, and it is enough to test the only thing fitLog decides.
const logBox = {
  clientHeight: 100,
  classes: new Set(),
  classList: {
    toggle(c, on) { on ? logBox.classes.add(c) : logBox.classes.delete(c); },
    add: c => logBox.classes.add(c),
    remove: c => logBox.classes.delete(c),
    contains: c => logBox.classes.has(c),
  },
};
const linesEl = {
  children: [],
  get scrollHeight() { return this.children.reduce((n, c) => n + c.h, 0); },
  removeChild(c) { this.children = this.children.filter(x => x !== c); },
  get firstChild() { return this.children[0]; },
};
global.document = { getElementById: id => (id === 'log' ? logBox : null) };
global.window = { addEventListener: () => {} };

eval(grab('fitLog'));

let passed = 0, failed = 0;
function test(name, fn) {
  linesEl.children = [];
  logBox.classes.clear();
  logBox.clientHeight = 100;
  try { fn(); passed++; console.log('ok   ' + name); }
  catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); }
}
const put = (label, h) => linesEl.children.push({ label, h });
const labels = () => linesEl.children.map(c => c.label);

// ---- what it drops, and what it never drops -------------------------------

test('nothing is dropped when everything already fits', () => {
  put('a', 20); put('b', 20); put('c', 20);
  fitLog();
  assert.deepStrictEqual(labels(), ['a', 'b', 'c']);
});

test('the OLDEST goes first, and only as many as needed', () => {
  put('oldest', 50); put('middle', 30); put('newest', 30);
  fitLog();   // 110 > 100, dropping the oldest leaves 60
  assert.deepStrictEqual(labels(), ['middle', 'newest'],
    'it dropped the wrong end, or more than it had to');
});

test('a long newest message survives whole, however much it costs', () => {
  // The actual bug: his screenshot showed my answer starting mid-sentence.
  put('old1', 30); put('old2', 30); put('old3', 30);
  put('the long answer', 95);
  fitLog();
  assert.deepStrictEqual(labels(), ['the long answer'],
    'the newest message was not preserved: ' + labels().join(', '));
});

test('the newest is NEVER removed, even alone and oversized', () => {
  // Better a clipped message than a blank overlay -- an empty box tells him
  // nothing at all, which is strictly worse than telling him part of it.
  put('enormous', 400);
  fitLog();
  assert.deepStrictEqual(labels(), ['enormous'], 'the last line was deleted');
});

test('an oversized single message is flagged clipped, so the fade is honest', () => {
  put('enormous', 400);
  fitLog();
  assert.ok(logBox.classes.has('clipped'),
    'a genuinely clipped log is not marked, so no fade hints at more above');
});

test('a fitted log is NOT flagged clipped', () => {
  // The fade must not appear over text that is entirely present -- that is
  // the exact thing that made a complete message LOOK cut off.
  put('a', 20); put('b', 20);
  fitLog();
  assert.ok(!logBox.classes.has('clipped'),
    'the deep fade is applied to a log with nothing hidden above it');
});

test('the flag CLEARS once the oversized message scrolls away', () => {
  put('enormous', 400);
  fitLog();
  assert.ok(logBox.classes.has('clipped'));
  linesEl.children = [];
  put('short', 20);
  fitLog();
  assert.ok(!logBox.classes.has('clipped'), 'the clipped flag stuck on');
});

// ---- the measurement traps ------------------------------------------------

test('a ZERO measurement deletes nothing', () => {
  // A hidden or not-yet-laid-out overlay measures 0, which would otherwise
  // mean "everything overflows" and wipe the log down to one line for a
  // number that really means "I cannot see yet". Same zero-measurement trap
  // the board's own sizing already guards against.
  put('a', 20); put('b', 20); put('c', 20);
  logBox.clientHeight = 0;
  fitLog();
  assert.deepStrictEqual(labels(), ['a', 'b', 'c'],
    'an unmeasurable overlay wiped its own contents');
});

test('a missing overlay is survived, not thrown on', () => {
  const saved = global.document.getElementById;
  global.document.getElementById = () => null;
  try {
    put('a', 20);
    fitLog();
    assert.deepStrictEqual(labels(), ['a']);
  } finally { global.document.getElementById = saved; }
});

test('exactly filling the box drops nothing', () => {
  // The off-by-one that would silently eat a line on every full log.
  put('a', 50); put('b', 50);
  fitLog();
  assert.deepStrictEqual(labels(), ['a', 'b'], 'a boundary-fitting log lost a line');
});

// ---- it is wired, not merely written --------------------------------------

test('showLine CALLS fitLog', () => {
  // The oldest failure on this project: a guard proven correct and never
  // proven called. fitLog is worthless if nothing runs it.
  const body = grab('showLine');
  assert.ok(/\bfitLog\(\)/.test(body),
    'showLine never fits the log -- the trimming can only run by accident');
});

test('a resize re-fits, because the ceiling is a PERCENTAGE of the stage', () => {
  assert.ok(/addEventListener\('resize',\s*fitLog\)/.test(src),
    'shrinking the window leaves the log overflowing until the next message');
});

test('the overlay ceiling is high enough for a real answer', () => {
  const m = src.match(/#log \{([^}]*)\}/);
  assert.ok(m, 'the #log rule is gone');
  const h = m[1].match(/max-height:\s*(\d+)%/);
  assert.ok(h, 'the log lost its max-height');
  assert.ok(Number(h[1]) >= 50,
    'the ceiling is back down at ' + h[1] + '% -- one long answer will not fit '
    + 'and every past line gets dropped to make room for it');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
