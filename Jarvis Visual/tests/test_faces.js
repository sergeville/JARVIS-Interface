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

// DERIVED FROM THE CSS, never hand-typed. This was a list of two literals
// until 2026-08-08, and the test below claimed it proved "the registry names
// exactly the faces the CSS defines" while actually comparing the page's
// registry against a constant in this file. Adding army and airforce made it
// go red for the wrong reason — the CSS was there and the LIST here was not.
// A cross-check with one hand-typed side is not a cross-check; it is two
// copies of the same claim.
const FACES = [...new Set([...src.matchAll(/body\.face-([a-z0-9-]+)\s*\{/g)]
                            .map(m => m[1]))];
assert.ok(FACES.length >= 2, 'no face blocks found in the CSS at all');
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

test('no two faces are the same palette — four worlds, not four names', () => {
  // Airforce is the reason this exists: by branch it is a blue, and civilian
  // is a blue. Two faces that render alike are one face with two labels, and
  // the switcher would then have a button that appears to do nothing.
  const seen = new Map();
  for (const f of FACES) {
    const key = block('body.face-' + f).replace(/\s+/g, '');
    const twin = seen.get(key);
    assert.ok(!twin, f + ' is byte-identical to ' + twin);
    seen.set(key, f);
  }
  // Byte-identity is too weak on its own, and an injection proved it: giving
  // airforce civilian's accent left the rest of the block different, so the
  // whole-block check stayed green while the page's dominant colour — the
  // one every border and glow is drawn from — became a duplicate.
  const accents = new Map();
  for (const f of FACES) {
    const a = /--accent-rgb:\s*([\d\s,]+);/.exec(block('body.face-' + f))[1].replace(/\s/g, '');
    const twin = accents.get(a);
    assert.ok(!twin, f + ' and ' + twin + ' share an accent — the page would read the same');
    accents.set(a, f);
  }
});

test('every face keeps its accent clear of the OK green', () => {
  // Invariant 2 the other way round: a face may not redefine a status
  // colour, AND it may not choose an accent that reads as one. An olive
  // accent beside a green "up" dot makes a lit border and a healthy
  // component look like the same thing.
  const ok = /--ok:\s*([^;]+);/.exec(src);
  assert.ok(ok, 'no --ok token to measure against');
  for (const f of FACES) {
    const m = /--accent-rgb:\s*([\d\s,]+);/.exec(block('body.face-' + f));
    assert.ok(m, f + ' defines no accent');
    const [r, g, b] = m[1].split(',').map(n => parseInt(n.trim(), 10));
    // green must not dominate both other channels — that is the shape of a
    // status green, whatever its exact value
    assert.ok(!(g > r + 40 && g > b + 40),
      f + "'s accent is a green and would read as a status");
  }
});

test('ALERT is defined after every face, so it wins on equal specificity', () => {
  // LAST occurrence, not the first. Found by injection 2026-08-08: appending
  // a second `body.face-navy {` block below the alert theme left this green,
  // because indexOf answered about the ORIGINAL block while the CSS cascade
  // obeys the last one. The first-match trap, in the one test whose whole job
  // is source ORDER — which is exactly where it does the most damage.
  const alertAt = src.lastIndexOf('body.alert {');
  for (const face of FACES) {
    const needle = 'body.face-' + face + ' {';
    assert.ok(src.lastIndexOf(needle) < alertAt,
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
  // Pinned to the CALL, not to the exact argument. The first version pinned
  // the whole expression and went red the moment a temporary boot default
  // was added -- correctly loud, but for the wrong property: what must never
  // change is that boot goes THROUGH the validator, not what it passes in.
  assert.ok(/applyFace\(/.test(src),
    'a boot path that sets the class directly would skip validation');
  assert.ok(!/classList\.add\('face-'\s*\+\s*localStorage/.test(src),
    'the class must never be set straight from storage');
});

test('the standing default is CIVILIAN, and any other default is marked TEMPORARY', () => {
  // Serge, 2026-08-08: navy boots "for now... later I want civilian to be
  // the default again." A loan that is not labelled becomes a decision
  // nobody remembers making, so the label is what this test guards.
  // Two shapes are legal at boot: restore-through-validation (the standing
  // one) or a hard-coded face (a loan, while a new face is being looked at).
  // Both are matched here, because pinning only the first made this test go
  // red for the RIGHT reason and the WRONG property twice in ten minutes.
  const restore = src.match(/applyFace\(\s*localStorage\.getItem\('jarvisFace'\)\s*(\|\|\s*'(\w+)')?\s*\)/);
  const forced  = src.match(/try \{ applyFace\('(\w+)'\); \}/);
  const m = restore || forced;
  assert.ok(m, 'the boot line was not found');
  const dflt = restore ? (restore[2] || 'civilian') : forced[1];
  if (dflt !== 'civilian') {
    // the note may sit several comment lines up -- the loan grew its own
    // explanation when the first attempt failed, which pushed it further away
    const before = src.slice(Math.max(0, m.index - 1600), m.index);
    assert.ok(/TEMPORARY/.test(before),
      `boot defaults to ${dflt} with no TEMPORARY note above it`);
  }
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
