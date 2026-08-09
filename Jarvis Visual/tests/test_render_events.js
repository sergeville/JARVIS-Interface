#!/usr/bin/env node
// Tests for renderEvents() -- the HUD's EVENTS strip (Serge, 2026-08-05).
//
// Run:  ./tests/run-tests.sh   (from Jarvis Visual/)
//    or  node tests/test_render_events.js
//
// The function is extracted from jarvis.html and run against a DOM stub, so
// these test the REAL page code rather than a copy of it -- same approach as
// the read_tasks tests importing the real server.
//
// What matters here: the strip must hide itself rather than render an empty
// box, it must map each kind onto the right colour class (Serge reads amber as
// a choice and red as a problem -- getting that backwards misinforms him), and
// it must escape text, because some of these lines are written by bash.

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const HTML = path.join(__dirname, '..', 'jarvis.html');

// ---- DOM stub: just enough for renderEvents and its helpers ---------------
const nodes = {};
function makeNode(id) {
  return { id, innerHTML: '', textContent: '', style: {},
           setAttribute() {}, getAttribute() { return null; } };
}
for (const id of ['events-sec', 'events-list', 'events-more', 'events-hint'])
  nodes[id] = makeNode(id);
global.document = {
  getElementById: id => nodes[id] || null,
  querySelectorAll: () => [],
};

// ---- pull the real functions out of the page ------------------------------
const src = fs.readFileSync(HTML, 'utf8');
function grab(name) {
  const start = src.indexOf('function ' + name + '(');
  assert.ok(start !== -1, 'function not found in jarvis.html: ' + name);
  // Walk braces from the first '{' to find the function's true end.
  let i = src.indexOf('{', start), depth = 0, end = -1;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}') { depth--; if (depth === 0) { end = j + 1; break; } }
  }
  assert.ok(end !== -1, 'unbalanced braces reading ' + name);
  return src.slice(start, end);
}
// setCount comes from the page, never a stub: this renderer gained a header
// count on 2026-08-09 and depends on the real one.
eval(grab('fmtClock') + '\n' + grab('esc') + '\n' + grab('setCount') + '\n' + grab('renderEvents'));
let eventsSig = '';   // module-level state the real page holds
// Read the real cap out of the page rather than hard-coding 3 here: if it is
// ever retuned, these tests must follow it, not contradict it.
const EV_SHOWN = (() => {
  const m = src.match(/const EV_SHOWN\s*=\s*(\d+)/);
  assert.ok(m, 'EV_SHOWN not found in jarvis.html');
  return parseInt(m[1], 10);
})();

const TS = 1785900000;
const ev = (kind, label, detail) => ({ ts: TS, kind, label, detail });

function reset() {
  eventsSig = '';
  nodes['events-sec'].style = {};
  nodes['events-list'].innerHTML = '';
  nodes['events-more'].innerHTML = '';
  nodes['events-hint'].textContent = '';
}

let passed = 0, failed = 0;
function test(name, fn) {
  reset();
  try { fn(); passed++; console.log('ok   ' + name); }
  catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); }
}

// ---- the tests ------------------------------------------------------------

test('empty list hides the section instead of drawing an empty box', () => {
  renderEvents([]);
  assert.strictEqual(nodes['events-sec'].style.display, 'none');
  assert.strictEqual(nodes['events-list'].innerHTML, '');
});

test('missing events key hides the section', () => {
  // This is the real state between shipping the page and Serge's restart:
  // the new page is live but the old server sends no `events` key at all.
  renderEvents(undefined);
  assert.strictEqual(nodes['events-sec'].style.display, 'none');
});

test('one event renders one row and shows the section', () => {
  renderEvents([ev('up', 'brain', 'warm')]);
  const html = nodes['events-list'].innerHTML;
  assert.notStrictEqual(nodes['events-sec'].style.display, 'none');
  assert.strictEqual((html.match(/ev-row/g) || []).length, 1);
  assert.ok(html.includes('brain'));
  assert.ok(html.includes('warm'));
});

test('up is green, off is amber, down is red', () => {
  renderEvents([ev('up', 'a', ''), ev('off', 'b', ''), ev('down', 'c', '')]);
  const html = nodes['events-list'].innerHTML;
  assert.ok(html.includes('ev-row up'), 'missing up class');
  assert.ok(html.includes('ev-row off'), 'missing off class');
  assert.ok(html.includes('ev-row down'), 'missing down class');
});

test('an unknown kind falls back to the calm class, never to down', () => {
  // A red dot is an alarm. An event whose kind we do not recognise must not
  // raise one.
  renderEvents([ev('banana', 'a', '')]);
  const html = nodes['events-list'].innerHTML;
  assert.ok(!html.includes('ev-row down'), 'unknown kind raised a red alarm');
  assert.ok(html.includes('ev-row off'));
});

test('order is preserved as given (server sends newest first)', () => {
  renderEvents([ev('up', 'newest', ''), ev('up', 'oldest', '')]);
  const html = nodes['events-list'].innerHTML;
  assert.ok(html.indexOf('newest') < html.indexOf('oldest'));
});

test('markup in a label or detail is escaped, not executed', () => {
  // bash writes some of these lines; a filename could carry anything.
  renderEvents([ev('up', '<img src=x onerror=1>', '"quoted" & <b>bold</b>')]);
  const html = nodes['events-list'].innerHTML;
  assert.ok(!html.includes('<img'), 'raw tag reached the DOM');
  assert.ok(!html.includes('<b>'), 'raw tag reached the DOM');
  assert.ok(html.includes('&lt;img'));
  assert.ok(html.includes('&amp;'));
});

test('null label or detail renders without printing "null"', () => {
  renderEvents([{ ts: TS, kind: 'up' }]);
  assert.ok(!nodes['events-list'].innerHTML.includes('null'));
});

test('an unchanged list is not rebuilt', () => {
  // The page polls at 15 Hz; rebuilding this innerHTML every frame would
  // fight the browser for no reason.
  renderEvents([ev('up', 'brain', 'warm')]);
  nodes['events-list'].innerHTML = 'SENTINEL';
  renderEvents([ev('up', 'brain', 'warm')]);
  assert.strictEqual(nodes['events-list'].innerHTML, 'SENTINEL');
});

test('a changed list IS rebuilt', () => {
  renderEvents([ev('up', 'brain', 'warm')]);
  renderEvents([ev('down', 'brain', 'rebuilt'), ev('up', 'brain', 'warm')]);
  const html = nodes['events-list'].innerHTML;
  assert.strictEqual((html.match(/ev-row/g) || []).length, 2);
  assert.ok(html.includes('rebuilt'));
});

test('the timestamp is rendered as a clock, not an epoch number', () => {
  renderEvents([ev('up', 'brain', 'warm')]);
  const html = nodes['events-list'].innerHTML;
  assert.ok(!html.includes(String(TS)), 'raw epoch leaked to the page');
  assert.ok(/\d\d:\d\d:\d\d/.test(html), 'no HH:MM:SS clock found');
});

// ---- the fold (Serge, 2026-08-05: the left column ran off the bottom) ------
// The rule these guard: FOLDED, never TRUNCATED. A restart Serge cannot find
// is the same as one that was never logged, so every event must still be in
// the DOM -- just in the half that only appears on hover.

test('at or under the cap, everything is on the panel and nothing is folded', () => {
  const evs = Array.from({length: EV_SHOWN}, (_, i) => ev('up', 'e' + i, ''));
  renderEvents(evs);
  assert.strictEqual(
    (nodes['events-list'].innerHTML.match(/ev-row/g) || []).length, EV_SHOWN);
  assert.strictEqual(nodes['events-more'].innerHTML, '');
  assert.strictEqual(nodes['events-hint'].textContent, '');
});

test('over the cap, the panel holds exactly EV_SHOWN rows', () => {
  const evs = Array.from({length: EV_SHOWN + 4}, (_, i) => ev('up', 'e' + i, ''));
  renderEvents(evs);
  assert.strictEqual(
    (nodes['events-list'].innerHTML.match(/ev-row/g) || []).length, EV_SHOWN);
});

test('the overflow is folded into the hover block, not dropped', () => {
  const evs = Array.from({length: EV_SHOWN + 4}, (_, i) => ev('up', 'e' + i, ''));
  renderEvents(evs);
  const shown = nodes['events-list'].innerHTML + nodes['events-more'].innerHTML;
  // Every single event must be somewhere in the DOM.
  for (let i = 0; i < EV_SHOWN + 4; i++)
    assert.ok(shown.includes('e' + i), 'event e' + i + ' was lost, not folded');
  assert.strictEqual(
    (nodes['events-more'].innerHTML.match(/ev-row/g) || []).length, 4);
});

test('the newest are the ones kept on the panel', () => {
  // The server sends newest first; the visible few must be those, not a tail.
  const evs = Array.from({length: EV_SHOWN + 2}, (_, i) => ev('up', 'e' + i, ''));
  renderEvents(evs);
  assert.ok(nodes['events-list'].innerHTML.includes('e0'));
  assert.ok(!nodes['events-list'].innerHTML.includes('e' + (EV_SHOWN + 1)));
  assert.ok(nodes['events-more'].innerHTML.includes('e' + (EV_SHOWN + 1)));
});

test('the hint counts exactly what is folded away', () => {
  renderEvents(Array.from({length: EV_SHOWN + 7}, (_, i) => ev('up', 'e' + i, '')));
  assert.strictEqual(nodes['events-hint'].textContent, '+7 more');
});

test('folded rows are escaped too', () => {
  // The hover half takes the same file-written text as the visible half.
  const evs = Array.from({length: EV_SHOWN}, (_, i) => ev('up', 'e' + i, ''));
  evs.push(ev('up', '<img src=x>', '& <b>'));
  renderEvents(evs);
  assert.ok(!nodes['events-more'].innerHTML.includes('<img'));
  assert.ok(nodes['events-more'].innerHTML.includes('&lt;img'));
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
