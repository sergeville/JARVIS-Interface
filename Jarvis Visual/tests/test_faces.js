#!/usr/bin/env node
// THE FACE REGISTRY — Phase 1 of JarvisOS 5000.
//
// A face is STYLE ONLY: one class on <body> redefining the complete chrome
// token set, the mechanism body.alert already proves. These tests guard the
// three invariants that make four worlds survivable, and each is written
// against the failure it prevents rather than against the code:
//
//   1. A PARTIAL FACE is the worst failure, because it does not look like a
//      failure — the forgotten token silently inherits the previous world's
//      colour, and nothing raises.
//   2. A STATUS THAT REPAINTS with the mood has stopped being a status.
//      Green means up in every world; that is doctrine here since the
//      terminal line's amber "off" was read as a fault.
//   3. ALERT BEATS EVERY FACE. The amber means "he is being asked", and it
//      must look identical in all four worlds, in either class order.

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const src = fs.readFileSync(path.join(__dirname, '..', 'jarvis.html'), 'utf8');

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log('ok   ' + name); passed++; }
  catch (e) { console.log('FAIL ' + name + '\n     ' + e.message); failed++; }
}

// --- read a CSS block by selector, every occurrence, never just the first --
// (the first-match trap has cost this project three separate bugs)
function block(selector) {
  const out = [];
  const needle = selector + ' {';
  let i = -1;
  while ((i = src.indexOf(needle, i + 1)) !== -1) {
    out.push(src.slice(i + needle.length, src.indexOf('}', i)));
  }
  assert.ok(out.length, 'no CSS block for ' + selector);
  return out.join('\n');
}
function tokensIn(text) {
  const set = new Set();
  for (const m of text.matchAll(/(--[a-z0-9-]+)\s*:/g)) set.add(m[1]);
  return set;
}

const FACES = ['civilian', 'navy'];
const STATUS = ['--ok', '--ok-soft', '--ok-soft-rgb', '--warn', '--warn-rgb',
                '--warn-soft', '--warn-soft-rgb', '--bad'];

// the tokens the ALERT theme redefines are exactly the chrome set a face owns
const chrome = tokensIn(block('body.alert'));

test('the chrome token set is not empty (the fixture itself is real)', () => {
  assert.ok(chrome.size >= 10, 'only ' + chrome.size + ' tokens found');
});

for (const face of FACES) {
  test(`face-${face} defines the COMPLETE chrome set`, () => {
    const got = tokensIn(block('body.face-' + face));
    const missing = [...chrome].filter(t => !got.has(t));
    assert.deepStrictEqual(missing, [],
      'missing ' + missing.join(', ') + ' — it would inherit the previous world');
  });

  test(`face-${face} redefines NO status colour`, () => {
    const got = tokensIn(block('body.face-' + face));
    const bad = STATUS.filter(t => got.has(t));
    assert.deepStrictEqual(bad, [],
      bad.join(', ') + ' — a status that follows the mood is not a status');
  });

  test(`face-${face} uses no raw literal outside its own token block`, () => {
    // every value in a face block must be a literal DEFINITION (--x: value),
    // never a var() pointing at another face
    const b = block('body.face-' + face);
    assert.ok(!/var\(--(bg|text|sec|fill|stage|accent)/.test(b),
      'a face must define its own values, not borrow another face\'s');
  });
}

test('ALERT is defined after every face, so it wins on equal specificity', () => {
  const alertAt = src.indexOf('body.alert {');
  for (const face of FACES) {
    assert.ok(src.indexOf('body.face-' + face + ' {') < alertAt,
      'face-' + face + ' is defined after body.alert and would beat it');
  }
});

test('the alert theme still overrides the frame (it was not gutted)', () => {
  const b = block('body.alert');
  assert.ok(/--bg-deep/.test(b) && /--accent-rgb/.test(b),
    'an emptied alert block would pass the ordering test by being absent');
});

// --- the dial itself, RUN rather than grepped -----------------------------
function dial() {
  const i = src.indexOf('const FACES =');
  const j = src.indexOf('try { applyFace(', i);
  const body = src.slice(i, j);
  const store = {};
  const cls = new Set();
  const sandbox = {
    document: { body: { classList: {
      add: c => cls.add(c), remove: c => cls.delete(c),
      contains: c => cls.has(c) } } },
    localStorage: { getItem: k => (k in store ? store[k] : null),
                    setItem: (k, v) => { store[k] = v; } },
  };
  const fn = new Function('document', 'localStorage',
    body + '\nreturn {applyFace, currentFace, FACES};');
  return Object.assign(fn(sandbox.document, sandbox.localStorage),
                       {cls, store});
}

test('applyFace sets exactly one face class', () => {
  const d = dial();
  d.applyFace('navy');
  assert.deepStrictEqual([...d.cls], ['face-navy']);
  d.applyFace('civilian');
  assert.deepStrictEqual([...d.cls], ['face-civilian'],
    'the previous face must be removed, not stacked');
});

test('an unknown face falls back to civilian rather than to nothing', () => {
  const d = dial();
  assert.strictEqual(d.applyFace('klingon'), 'civilian');
  assert.deepStrictEqual([...d.cls], ['face-civilian'],
    'no class at all would leave the page unstyled');
});

test('junk in storage restores to civilian, not to an unstyled page', () => {
  const d = dial();
  assert.strictEqual(d.applyFace(null), 'civilian');
  assert.strictEqual(d.applyFace(undefined), 'civilian');
  assert.strictEqual(d.applyFace('{"a":1}'), 'civilian');
});

test('the choice is persisted', () => {
  const d = dial();
  d.applyFace('navy');
  assert.strictEqual(d.store.jarvisFace, 'navy');
});

test('a REFUSED face is not persisted as itself', () => {
  const d = dial();
  d.applyFace('klingon');
  assert.strictEqual(d.store.jarvisFace, 'civilian',
    'storing the junk would make the fallback happen once, then fail');
});

test('currentFace reads the real class, and is not a constant', () => {
  const d = dial();
  d.applyFace('navy');
  assert.strictEqual(d.currentFace(), 'navy');
  d.applyFace('civilian');
  assert.strictEqual(d.currentFace(), 'civilian');
});

test('currentFace with NO face applied answers civilian', () => {
  // Found by fault injection: changing this fallback to 'navy' left every
  // other test green, because they all apply a face first and so never
  // reach the branch. A fallback nothing exercises is a fallback nobody
  // has tested -- and this one decides what the page calls itself before
  // the first applyFace() runs.
  const d = dial();
  assert.strictEqual(d.currentFace(), 'civilian',
    'the unstyled state must report as civilian, the page\'s own look');
});

test('the registry names exactly the faces the CSS defines', () => {
  const d = dial();
  assert.deepStrictEqual(d.FACES.slice().sort(), FACES.slice().sort(),
    'a face in the list with no CSS renders unstyled; CSS with no list entry is unreachable');
});

test('the boot restore runs through applyFace, not around it', () => {
  assert.ok(/applyFace\(localStorage\.getItem\('jarvisFace'\)\)/.test(src),
    'a boot path that sets the class directly would skip validation');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
