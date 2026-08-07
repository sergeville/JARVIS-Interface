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

// ---- the thinking, folded (Serge, 2026-08-07 ~6:00 PM) ---------------------
// "Is it possible to have everything that was spoken so I could see what's on
// file now?" The gist is one line; the argument is the point. It is FOLDED
// rather than always-open because five unrolled ideas would bury the list --
// his own EVENTS rule: fold, never truncate.

test('an idea with thinking carries every paragraph of it', () => {
  renderIdeas([{ title: 'T', raised: '', gist: '',
                 body: ['first thought', 'second thought'] }]);
  assert.ok(list().includes('first thought'), 'the thinking was dropped');
  assert.ok(list().includes('second thought'), 'only the first paragraph survived');
});

test('the thinking is marked foldable and says how much there is', () => {
  renderIdeas([{ title: 'T', raised: '', gist: '', body: ['a', 'b', 'c'] }]);
  assert.ok(/class="icard has-more"/.test(list()), 'the card is not foldable');
  // Read the VISIBLE label, not the whole HTML. The count also lives in the
  // element's data-shut attribute (the folded caption, kept there so the
  // render owns it and the click handler does not recompute it) -- and a
  // first version of this assertion matched THAT, so deleting the visible
  // count passed. Same trap as the two-identical-selectors miss: a guard that
  // matches the wrong occurrence guards nothing.
  const shown = list().match(/<div class="imore"[^>]*>([^<]*)<\/div>/);
  assert.ok(shown, 'the fold hint is gone');
  assert.ok(/3 more/.test(shown[1]),
    'the fold does not say how much is hidden: ' + shown[1]);
});

test('an idea with NO thinking is not dressed up as foldable', () => {
  // A card that invites a click and then does nothing is worse than a plain
  // one. Most of the panel will be these.
  renderIdeas([{ title: 'T', raised: '', gist: 'g', body: [] }]);
  assert.ok(!/has-more/.test(list()), 'a bodyless idea claims to have more');
  assert.ok(!/imore/.test(list()), 'a bodyless idea draws a fold hint');
  assert.ok(!/tabindex/.test(list()), 'a bodyless idea is focusable for nothing');
});

test('an OLD server with no body field does not break the panel', () => {
  // The page reloads on its own; the server needs Serge to restart it. So the
  // page WILL run against a server that knows nothing about bodies, and it has
  // to render the old shape rather than throw.
  assert.doesNotThrow(() => renderIdeas([{ title: 'T', raised: '', gist: 'g' }]));
  assert.ok(list().includes('T'));
  assert.ok(!/has-more/.test(list()));
});

test('THE THINKING IS ESCAPED -- the note is hand-editable and this reaches the DOM', () => {
  renderIdeas([{ title: 'T', raised: '', gist: '',
                 body: ['<img src=x onerror=alert(1)>'] }]);
  assert.ok(!/<img/.test(list()), 'markup from the vault reached the DOM');
  assert.ok(/&lt;img/.test(list()), 'the paragraph was dropped instead of escaped');
});

test('the fold is a fold -- nothing on an idea can start, open or change anything', () => {
  // The panel is read-only BY CONSTRUCTION; that is the whole reason ideas
  // live apart from the board. A click handler is the obvious place for that
  // to erode, so the handler is read here.
  const h = src.match(/function wireIdeaFold\(\)\{[\s\S]*?\n\}\)\(\);/);
  assert.ok(h, 'the fold wiring is gone');
  for (const forbidden of ['fetch(', 'move_task', 'task_move', 'ws.send',
                           'location', 'window.open']) {
    assert.ok(!h[0].includes(forbidden),
      'the ideas panel reaches out via ' + forbidden + ' -- it is read-only');
  }
});

test('the fold is delegated to the list, not bound per card', () => {
  // renderIdeas rebuilds the list HTML on every change, so per-card handlers
  // would be thrown away with it and the fold would go dead after a poll.
  const h = src.match(/function wireIdeaFold\(\)\{[\s\S]*?\n\}\)\(\);/)[0];
  assert.ok(/list\.addEventListener\('click'/.test(h),
    'the click is not delegated to the list');
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
