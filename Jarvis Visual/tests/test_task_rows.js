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

test('EVERY status the board knows gets a row class and a word', () => {
  renderTasks(COLS.map(c => T('task ' + c.key, c.key)));
  const got = rows();
  assert.strictEqual(got.length, COLS.length, 'a status produced no row');
  COLS.forEach((c, i) => {
    const want = 'task' + (c.cls ? ' ' + c.cls : '');
    assert.strictEqual(got[i].className, want,
      c.key + ' row is "' + got[i].className + '" -- it will not match its column');
    assert.strictEqual(cellOf(got[i], 'st').textContent, c.short,
      c.key + ' row says the wrong word');
  });
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
