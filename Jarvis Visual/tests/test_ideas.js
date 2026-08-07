#!/usr/bin/env node
// Tests for the IDEAS panel -- renderIdeas() and ideasOpen().
//
// Serge, 2026-08-07 ~4:00 PM: "a header just on top of sessions... I'll click
// on that and boom, we have a brand new page that goes to the vault."
//
// This is the only panel on the page that is NOT about work, and most of what
// is asserted here is about it staying that way: nothing on it can start
// anything, and nothing on it counts.

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

// ---- DOM stub -------------------------------------------------------------
const nodes = {};
function makeNode(id) {
  return { id, innerHTML: '', style: {}, contains: () => false };
}
for (const id of ['ideas-sec', 'ideas-list', 'ideas', 'ideas-head']) {
  nodes[id] = makeNode(id);
}
const bodyClasses = new Set();
global.document = {
  getElementById: id => nodes[id] || null,
  body: { classList: {
    add: c => bodyClasses.add(c),
    remove: c => bodyClasses.delete(c),
    contains: c => bodyClasses.has(c),
  } },
  addEventListener: () => {},
};

let lastIdeasJson = '';
let ideasLatched = false;
let boardClosedCalls = 0;
function boardOpen(v) { if (v === false) boardClosedCalls++; }
eval(grab('esc') + '\n' + grab('renderIdeas') + '\n' + grab('ideasOpen'));

let passed = 0, failed = 0;
function test(name, fn) {
  lastIdeasJson = '';
  bodyClasses.clear();
  nodes['ideas-list'].innerHTML = '';
  nodes['ideas-sec'].style = {};
  try { fn(); passed++; console.log('ok   ' + name); }
  catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); }
}
const list = () => nodes['ideas-list'].innerHTML;
const I = (title, extra) =>
  Object.assign({ title, raised: '2026-08-07', gist: 'a gist' }, extra || {});

// ---- it shows the ideas ---------------------------------------------------

test('an idea draws its title, its gist and the date it was raised', () => {
  renderIdeas([I('A better mousetrap')]);
  const h = list();
  assert.ok(h.includes('A better mousetrap'), 'no title: ' + h);
  assert.ok(h.includes('a gist'), 'no gist: ' + h);
  assert.ok(h.includes('raised 2026-08-07'), 'no raised date: ' + h);
});

test('every idea is drawn, in the note\'s own order', () => {
  renderIdeas([I('First'), I('Second'), I('Third')]);
  const h = list();
  assert.ok(h.indexOf('First') < h.indexOf('Second'), 'order lost: ' + h);
  assert.ok(h.indexOf('Second') < h.indexOf('Third'), 'order lost: ' + h);
});

test('an idea with no gist still draws, without an empty box', () => {
  renderIdeas([{ title: 'Bare', raised: '', gist: '' }]);
  assert.ok(list().includes('Bare'), 'the idea vanished');
  assert.ok(!list().includes('class="ig"'), 'an empty gist row was drawn');
  assert.ok(!list().includes('raised'), 'an empty raised row was drawn');
});

test('an empty queue HIDES the panel rather than drawing a heading over nothing', () => {
  renderIdeas([I('x')]);
  assert.strictEqual(nodes['ideas-sec'].style.display, '');
  renderIdeas([]);
  assert.strictEqual(nodes['ideas-sec'].style.display, 'none',
    'an empty panel is chrome, not information');
  assert.strictEqual(list(), '', 'stale ideas left behind after emptying');
});

test('emptying the note also CLOSES the sheet', () => {
  // Otherwise the sheet hangs open over the stage with nothing in it and
  // no heading left to click to close it.
  renderIdeas([I('x')]);
  ideasOpen(true);
  assert.ok(bodyClasses.has('ideas-open'));
  renderIdeas([]);
  assert.ok(!bodyClasses.has('ideas-open'), 'the empty sheet stayed open');
});

// ---- it is not a board ----------------------------------------------------

test('a card offers NO control that could start anything', () => {
  // The whole point of the panel. An approve, a move, a drag handle or a
  // status here would make it possible to promote an idea without Serge --
  // which is the one thing the split between the two notes exists to stop.
  renderIdeas([I('A tempting idea')]);
  const h = list();
  for (const bad of ['<button', 'draggable', 'data-act', 'data-status']) {
    assert.ok(!h.includes(bad),
      'the ideas panel grew a control (' + bad + '): ' + h);
  }
});

test('NOTHING on a card counts elapsed time', () => {
  // The hard line, and it is a decision rather than an omission: the board
  // is the half of this system allowed to nag. If this panel starts telling
  // Serge an idea has waited eleven days, he stops saying half-formed
  // things, and that is where the good ones start.
  renderIdeas([I('Old thought', { raised: '2020-01-01' })]);
  const h = list().toLowerCase();
  for (const word of ['days', 'ago', 'stale', 'overdue', 'waiting since']) {
    assert.ok(!h.includes(word),
      'the panel counted how long an idea has waited ("' + word + '"): ' + h);
  }
});

test('a title carrying HTML is escaped', () => {
  // The note is hand-edited and this value reaches the DOM.
  renderIdeas([I('<img src=x onerror=alert(1)>')]);
  assert.ok(!list().includes('<img'), 'markup from the note reached the DOM');
  assert.ok(list().includes('&lt;img'), 'not escaped: ' + list());
});

// ---- opening and closing --------------------------------------------------

test('opening the ideas sheet CLOSES the board', () => {
  // Both sheets are fixed at the same place. Open together, one sits
  // invisibly under the other and his click lands on the wrong thing.
  boardClosedCalls = 0;
  ideasOpen(true);
  assert.strictEqual(boardClosedCalls, 1, 'the board was left open underneath');
});

test('closing drops the latch, so the next click opens again', () => {
  ideasOpen(true);
  ideasLatched = true;
  ideasOpen(false);
  assert.strictEqual(ideasLatched, false, 'the latch stuck shut');
  assert.ok(!bodyClasses.has('ideas-open'));
});

test('a redraw with unchanged data does not rebuild the DOM', () => {
  // The poll runs at 15 Hz. A rebuild on every tick would reset his scroll
  // mid-read -- the same catch the board already carries.
  renderIdeas([I('Steady')]);
  nodes['ideas-list'].innerHTML = 'SENTINEL';
  renderIdeas([I('Steady')]);
  assert.strictEqual(list(), 'SENTINEL', 'the panel rebuilt for no change');
});

// ---- the heading is a heading, not a button -------------------------------

test('the ideas heading carries NO border', () => {
  // This page's own rule: a border says pressable. The heading reacts to a
  // click but is styled as a section title, exactly like Sessions.
  const m = src.match(/#ideas-head \{([^}]*)\}/);
  assert.ok(m, 'the #ideas-head rule is gone');
  assert.ok(!/(^|[^-])border:/.test(m[1]),
    'the ideas heading grew a border: ' + m[1].trim());
});

test('the ideas heading sits ABOVE the sessions card', () => {
  // Serge placed it: "a header just on top of sessions".
  const i = src.indexOf('id="ideas-sec"');
  const j = src.indexOf('<div id="sessions"');
  assert.ok(i !== -1 && j !== -1, 'a section is missing');
  assert.ok(i < j, 'ideas is no longer above sessions');
});

test('the sheet says out loud that it is read-only', () => {
  // A panel that looks like the board must say how it differs, or it will
  // be read as one.
  const m = src.match(/class="isheet-foot"[^>]*>([\s\S]*?)<\/div>/);
  assert.ok(m, 'the ideas sheet lost its footer');
  assert.ok(/read-only/i.test(m[1]), 'the footer no longer says read-only');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
