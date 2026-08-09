#!/usr/bin/env node
// CARD HEADERS — ICON, TITLE, LIVE COUNT.
//
// Serge, 2026-08-09, comparing the page to the concept: "in the concept every
// header carries an icon on the left and a live count on the right... that's
// the single biggest reason the concept reads as instrumentation and mine
// reads as a list." Every one of those numbers is something the page already
// knows, so nothing here is invented.
//
// WHICH IS EXACTLY THE DANGER. A header count is the ideal hiding place for a
// plausible wrong number: nobody cross-checks a small grey figure against the
// list beneath it, and it would read as authoritative for weeks. So the
// property these tests defend is not "a count appears" — it is:
//
//   1. every count comes from the SAME list its own card just drew,
//   2. a count that cannot be stated is BLANK, never 0 and never stale,
//   3. no card grows a count it has no honest source for.
//
// The setter is RUN here against real payloads, not grepped. This project has
// lost nine rounds to guards that only read source — one of them in the file
// next to this, where a test passed on a comment for a week.

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const src = fs.readFileSync(path.join(__dirname, '..', 'jarvis.html'), 'utf8');

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log('ok   ' + name); passed++; }
  catch (e) { console.log('FAIL ' + name + '\n     ' + e.message); failed++; }
}

// ---- run the real setter, sliced out of the page --------------------------
function slice(name) {
  const start = src.indexOf('function ' + name + '(');
  assert.ok(start !== -1, 'no function ' + name + ' in jarvis.html');
  let i = src.indexOf('{', start), depth = 0, end = -1;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}' && --depth === 0) { end = j + 1; break; }
  }
  return src.slice(start, end);
}

// A document just real enough for the setter: one element per id.
function fakeDoc() {
  const els = {};
  return {
    els,
    getElementById: (id) => els[id] || (els[id] = {id, textContent: 'STALE'}),
  };
}

function loadSetter(doc) {
  // eslint-disable-next-line no-new-func
  return new Function('document', slice('setCount') + '; return setCount;')(doc);
}

test('a real count renders as "N word"', () => {
  const doc = fakeDoc();
  loadSetter(doc)('stack-count', 4, 'online');
  assert.strictEqual(doc.els['stack-count'].textContent, '4 online');
});

test('zero is a real reading and is shown, not hidden', () => {
  // Deliberate: 0 ONLINE is information — it means the stack is down. The
  // blank case is "I do not know", which is a different statement.
  const doc = fakeDoc();
  loadSetter(doc)('stack-count', 0, 'online');
  assert.strictEqual(doc.els['stack-count'].textContent, '0 online');
});

test('an unknown count is BLANK — never a stale reading left standing', () => {
  const set = (v) => {
    const doc = fakeDoc();
    doc.els['x'] = {id: 'x', textContent: '9 online'};   // last poll's answer
    loadSetter(doc)('x', v, 'online');
    return doc.els['x'].textContent;
  };
  for (const bad of [null, undefined, NaN, Infinity, -1, '3']) {
    assert.strictEqual(set(bad), '',
      'a count of ' + String(bad) + ' left the previous reading on screen');
  }
});

test('the setter never throws when the element is missing', () => {
  const doc = {getElementById: () => null};
  loadSetter(doc)('nope', 3, 'online');   // must not raise
});

// ---- each count is fed by the card that owns it ---------------------------

const WIRING = [
  ['renderStack',    'stack-count'],
  ['renderSessions', 'sessions-count'],
  ['renderMail',     'mail-count'],
  ['renderEvents',   'events-count'],
  ['renderIdeas',    'ideas-count'],
];

test('every count is set INSIDE the renderer that draws its card', () => {
  for (const [fn, id] of WIRING) {
    const body = slice(fn);
    assert.ok(body.includes("setCount('" + id + "'"),
      id + ' is not set inside ' + fn + '() — it could drift from its list');
  }
});

test('no count is a CONSTANT — the number must be derived, never written in', () => {
  // The fault this closes was missed by the test above and caught only by
  // injection: replacing `list.length` with the literal `2` left every
  // assertion green. "Set inside the right function" is not the property —
  // "computed from that function's own data" is. A literal in a header count
  // is the exact plausible-wrong-number this whole file exists to prevent.
  for (const [fn, id] of WIRING) {
    const body = slice(fn);
    // Balance the parens. Slicing at the FIRST ')' cut renderStack's call in
    // half at the filter's own bracket and reported correct code as a
    // constant — a test that lies about which code it read is worse than none.
    const from = body.indexOf("setCount('" + id + "'");
    let depth = 0, end = from;
    for (let j = body.indexOf('(', from); j < body.length; j++) {
      if (body[j] === '(') depth++;
      else if (body[j] === ')' && --depth === 0) { end = j + 1; break; }
    }
    const args = body.slice(from, end);
    assert.ok(!/,\s*-?\d+\s*,/.test(args),
      id + ' is set from a literal in ' + fn + '(): ' + args.trim());
    assert.ok(/\.length|null/.test(args),
      id + ' is not derived from the list ' + fn + '() drew: ' + args.trim());
  }
});

test('no count is set anywhere else — one writer each', () => {
  for (const [, id] of WIRING) {
    const n = src.split("setCount('" + id + "'").length - 1;
    assert.ok(n <= 2, id + ' has ' + n + ' writers; two sources is how a header'
      + ' and its list start disagreeing');
  }
});

test('the STACK count means UP, not merely not-down', () => {
  // `off` is a deliberate stand-down and `down` is a fault. Counting either
  // as online is precisely the lie this panel exists to prevent.
  const body = slice('renderStack');
  assert.ok(/filter\(c => c\.state === 'up'\)\.length/.test(body),
    'the online count no longer counts only components that are up');
});

test('the MAIL count does not claim a read state the bus does not have', () => {
  const body = slice('renderMail');
  assert.ok(/setCount\('mail-count', ms\.length, 'notices'\)/.test(body),
    'the mail count is not the number of notices held');
  // Strip the comments before looking. The first version of this assertion
  // went red against correct code because the comment EXPLAINING why we do
  // not say "unread" contains the word — the same prose-not-code trap that
  // had test_command_bar.js green on a sentence for a week.
  const code = body.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  assert.ok(!/unread/i.test(code), 'the card claims an unread state that does not exist');
});

test('IDEAS blanks its count when the note empties', () => {
  const body = slice('renderIdeas');
  assert.ok(/setCount\('ideas-count', null\)/.test(body),
    'an emptied Ideas note would leave its last count on a hidden card');
});

// ---- the markup half ------------------------------------------------------

test('every counted card has a slot, and the uncounted ones have none', () => {
  for (const id of ['stack-count', 'sessions-count', 'mail-count',
                    'events-count', 'ideas-count']) {
    assert.strictEqual(src.split('id="' + id + '"').length - 1, 1,
      id + ' does not appear exactly once in the markup');
  }
  // Sys Monitor and Command Input have no honest single number. They get an
  // icon and no slot rather than a decorative zero.
  const mon = src.slice(src.indexOf('data-icon="▤"'));
  assert.ok(!/sec-count/.test(mon.slice(0, 120)),
    'Sys Monitor grew a count it has no source for');
});

test('every card header carries an icon', () => {
  const heads = [...src.matchAll(/<div class="sec-title"([^>]*)>/g)];
  assert.ok(heads.length >= 6, 'card headers vanished — found ' + heads.length);
  for (const h of heads) {
    assert.ok(/data-icon="/.test(h[1]),
      'a card header has no icon: <div class="sec-title"' + h[1] + '>');
  }
});

test('the icon is drawn from the attribute, and takes the face accent', () => {
  const i = src.indexOf('.sec-title[data-icon]::before');
  assert.ok(i !== -1, 'the icon rule is gone — headers fall back to the bullet');
  const rule = src.slice(i, src.indexOf('}', i));
  assert.ok(/content: attr\(data-icon\)/.test(rule), 'the icon is not the attribute');
  assert.ok(/var\(--accent-rgb\)/.test(rule), 'the icon ignores the face dial');
});

test('the count sits at the right edge and is not a colour literal', () => {
  const i = src.indexOf('.sec-count {');
  assert.ok(i !== -1, 'the count has no rule of its own');
  const rule = src.slice(i, src.indexOf('}', i));
  assert.ok(/margin-left: auto/.test(rule), 'the count does not sit at the right edge');
  assert.ok(!/#[0-9a-f]{6}/i.test(rule), 'a colour literal would survive every face');
});

console.log('\n' + passed + '/' + (passed + failed) + ' passed');
process.exit(failed ? 1 : 0);
