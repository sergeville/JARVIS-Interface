#!/usr/bin/env node
// Tests for renderTasks() -- the ACTIVE TASKS list in the sidebar.
//
// This function had NO tests at all until 2026-08-06, which is how it came
// to disagree with the board sitting two inches from it: it carried three
// hand-written states (active / waiting / everything else) written before
// Review, Test and Done existed, so those three showed no colour and
// printed their raw status word.
//
// What these guard is Serge's own rule, stated 2026-08-06: "you should be
// in sync all the time. It should be the same thing, actually -- it's just
// a different view on it." So the assertions are all about ONE table
// driving BOTH views. A seventh status must light up the row list and the
// board together, without anyone remembering to.

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

// The table is parsed out of the page, never restated here. That is the
// whole point of the change under test: one source, two views.
const COLS_SRC = (() => {
  const m = src.match(/const BOARD_COLS = (\[[\s\S]*?\n\]);/);
  assert.ok(m, 'BOARD_COLS not found in jarvis.html');
  return m[1];
})();
const COLS = eval('(' + COLS_SRC + ')');

// ---- DOM stub -------------------------------------------------------------
function makeEl(tag) {
  return {
    tag, className: '', textContent: '', title: '', style: {},
    children: [],
    appendChild(c) { this.children.push(c); return c; },
    set innerHTML(v) { if (v === '') this.children = []; },
    get innerHTML() { return ''; },
  };
}
const card = makeEl('div');
const body = makeEl('div');
global.document = {
  createElement: makeEl,
  getElementById: id => (id === 'tasks' ? card : id === 'tasks-body' ? body : null),
};

let lastTasksJson = '';
// ONE eval, on purpose: a `const` declared inside its own eval() is scoped
// to that call and gone by the next one, so the functions would run against
// an undefined table. The first version of this file did exactly that.
eval('var BOARD_COLS = ' + COLS_SRC + ';\n'
   + grab('colFor') + '\n' + grab('renderTasks'));

let passed = 0, failed = 0;
function test(name, fn) {
  lastTasksJson = '';
  body.children = [];
  try { fn(); passed++; console.log('ok   ' + name); }
  catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); }
}
const T = (title, status) => ({ title, status, priority: 'P2', note: 'a note' });
const rows = () => body.children;
const cellOf = (row, cls) => row.children.find(c => c.className === cls);

// ---- one table, two views -------------------------------------------------

// INVERTED 2026-08-06, not deleted. The old assertion was that EVERY status
// the board knows draws a row -- which described precisely the behaviour Serge
// asked to remove ("just one line saying done, five... if I go to the board
// then I could see the done"). The property that still matters is unchanged
// and is asserted here: every status that is still LIVE gets its column's
// class and its column's word. `done` is covered by its own tests below.
const LIVE = COLS.filter(c => c.key !== 'done');

test('EVERY live status gets its column class and its column word', () => {
  renderTasks(LIVE.map(c => T('task ' + c.key, c.key)));
  const got = rows();
  assert.strictEqual(got.length, LIVE.length, 'a live status produced no row');
  LIVE.forEach((c, i) => {
    const want = 'task' + (c.cls ? ' ' + c.cls : '');
    assert.strictEqual(got[i].className, want,
      c.key + ' row is "' + got[i].className + '" -- it will not match its column');
    assert.strictEqual(cellOf(got[i], 'st').textContent, c.short,
      c.key + ' row says the wrong word');
  });
});

// ---- done sinks out of the card and leaves a count ------------------------
// Serge, 2026-08-06 ~5:40 PM. Before this the list had NO sort at all: it drew
// the note's file order, so finished items sat scattered ABOVE live work and
// the card read backwards. These guard both halves -- the order, and the count.

const doneLine = () => body.children.find(c => c.className === 'task-done-line');

test('a done task draws NO row in this card', () => {
  renderTasks([T('finished', 'done')]);
  assert.strictEqual(rows().filter(r => r.className.includes('task ')).length, 0,
    'a done task still drew a row -- the board is where those live now');
});

test('the done COUNT is drawn, and it counts them all', () => {
  renderTasks([T('a', 'done'), T('b', 'done'), T('c', 'done'), T('d', 'active')]);
  const line = doneLine();
  assert.ok(line, 'no done count line');
  assert.strictEqual(line.textContent, 'done \u00b7 3');
});

test('no done line at all when nothing finished', () => {
  // "DONE 0" is noise on a quiet day; this card already hides itself rather
  // than draw a blank box, and the line follows the same rule.
  renderTasks([T('a', 'active')]);
  assert.strictEqual(doneLine(), undefined, 'an empty done line was drawn');
});

test('the count line is LAST -- it is the floor of the card, not a row in it', () => {
  renderTasks([T('a', 'done'), T('b', 'active'), T('c', 'open')]);
  const kids = body.children;
  assert.strictEqual(kids[kids.length - 1].className, 'task-done-line',
    'the done count is not at the bottom');
});

test('live rows are ordered by the BOARD table, not by the note file order', () => {
  // Handed in deliberately backwards. If this ever draws them in the order
  // received, the card is reading the note instead of the shared table.
  const backwards = ['waiting-on-serge', 'test', 'review', 'active', 'open'];
  renderTasks(backwards.map(k => T('task ' + k, k)));
  const words = rows().map(r => cellOf(r, 'st').textContent);
  const want = COLS.filter(c => backwards.includes(c.key)).map(c => c.short);
  assert.deepStrictEqual(words, want,
    'rows are out of board order: ' + words.join(', '));
});

test('an unknown status sorts with To Do rather than sinking or vanishing', () => {
  // colFor() already resolves an unheard-of status to To Do; the sort must
  // agree with it, or a task could sort below the done line and be lost.
  renderTasks([T('weird', 'no-such-status'), T('a', 'active')]);
  const titles = rows().map(r => cellOf(r, 'title').textContent);
  assert.ok(titles[0].includes('weird'),
    'an unknown status did not sort with To Do: ' + titles.join(', '));
  assert.strictEqual(rows().length, 2, 'the unknown status vanished');
});

test('the done count line carries no border -- a border says pressable', () => {
  // This page's own rule. The line is a fact, and the board is the control.
  const block = src.slice(src.indexOf('#tasks .task-done-line {'));
  const rule = block.slice(0, block.indexOf('}'));
  assert.ok(!/(^|[^-])border:/.test(rule),
    'the done count line has a border -- it will read as a button');
});

test('the row class is the COLUMN class, not a second vocabulary', () => {
  // If these two ever diverge, the sidebar and the board paint the same
  // status differently and the eye has to learn two languages for one fact.
  const classes = new Set(COLS.map(c => c.cls).filter(Boolean));
  for (const cls of classes) {
    assert.ok(src.includes('#tasks .task.' + cls),
      'no #tasks styling for "' + cls + '" -- that status is colourless in the list');
    assert.ok(src.includes('.bcol.' + cls),
      'no board column styling for "' + cls + '" -- the two views disagree');
  }
});

test('review and test are NOT painted as doing or waiting', () => {
  // Amber would say Serge is blocking; green would say it is being typed.
  // Both are lies about work in flight that is not on him.
  const chk = COLS.filter(c => c.key === 'review' || c.key === 'test');
  assert.strictEqual(chk.length, 2, 'review and test left the table');
  for (const c of chk) {
    assert.strictEqual(c.cls, 'checking', c.key + ' changed column class');
    assert.notStrictEqual(c.cls, 'doing');
    assert.notStrictEqual(c.cls, 'waiting');
  }
});

test('only ONE status pulses -- the one being worked right now', () => {
  // Serge asked to "see a task running". A second pulsing row drains the
  // meaning out of the first.
  const pulsing = [...src.matchAll(/#tasks \.task\.([a-z-]+) \.dot \{[^}]*animation:/g)]
    .map(m => m[1]);
  assert.deepStrictEqual(pulsing, ['doing'],
    'these row states pulse: ' + pulsing.join(', '));
});

test('an unknown status falls back to To Do rather than vanishing', () => {
  renderTasks([T('from the future', 'shipped-to-mars')]);
  assert.strictEqual(rows().length, 1, 'the task disappeared');
  assert.strictEqual(rows()[0].className, 'task');
  assert.strictEqual(cellOf(rows()[0], 'st').textContent, COLS[0].short);
});

test('the title carries the priority and the note stays in the tooltip', () => {
  renderTasks([T('do the thing', 'active')]);
  const t = cellOf(rows()[0], 'title');
  assert.strictEqual(t.textContent, 'P2 · do the thing');
  assert.strictEqual(t.title, 'a note',
    'the note left the tooltip -- the row is a glance, not a report');
});

test('an empty queue hides the card instead of leaving an empty box', () => {
  renderTasks([]);
  assert.strictEqual(card.style.display, 'none');
  renderTasks([T('one', 'open')]);
  assert.strictEqual(card.style.display, 'block');
});

test('the list is not rebuilt when nothing changed -- this polls at 15 Hz', () => {
  renderTasks([T('one', 'open')]);
  const first = rows()[0];
  renderTasks([T('one', 'open')]);
  assert.strictEqual(rows()[0], first, 'the DOM was rebuilt for an identical payload');
});

test('a status CHANGE does rebuild it', () => {
  renderTasks([T('one', 'open')]);
  renderTasks([T('one', 'active')]);
  assert.strictEqual(rows()[0].className, 'task doing');
});

test('no status colour is a raw literal -- they come from the palette tokens', () => {
  const block = src.slice(src.indexOf('#tasks .task {'),
                          src.indexOf('@keyframes taskpulse'));
  const raw = block.match(/#[0-9a-fA-F]{3,6}\b/g) || [];
  assert.deepStrictEqual(raw, [],
    'raw colour literals in the task rows: ' + raw.join(', '));
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
