#!/usr/bin/env node
// Tests for renderBoard() -- the Kanban that rolls down from the top bar
// (Serge, 2026-08-05).
//
// Run:  ./tests/run-tests.sh   (from Jarvis Visual/)
//    or  node tests/test_board.js
//
// The function is extracted from jarvis.html and run against a DOM stub, so
// these test the REAL page code rather than a copy of it.
//
// What these are actually guarding:
//   * every task lands in exactly one column, including one whose status the
//     page has never heard of -- a task Serge cannot see is the worst outcome
//     this board can produce, and it is a silent one;
//   * the summary counts match the columns, because the strip is what he
//     reads at a glance and a wrong number there is worse than no number;
//   * the DONE column tells the truth about being unserved rather than
//     looking like an empty success;
//   * the hover timings and the LATCH exist, since a board that rolls up
//     mid-interaction is the failure mode he will actually hit.

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const HTML = path.join(__dirname, '..', 'jarvis.html');

// ---- DOM stub -------------------------------------------------------------
const nodes = {};
function makeNode(id) {
  return { id, innerHTML: '', textContent: '', style: {},
           setAttribute() {}, getAttribute() { return null; } };
}
for (const id of ['board-strip', 'board-cols', 'board'])
  nodes[id] = makeNode(id);
const bodyClasses = new Set();
global.document = {
  getElementById: id => nodes[id] || null,
  querySelectorAll: () => [],
  body: { classList: {
    toggle: (c, on) => { on ? bodyClasses.add(c) : bodyClasses.delete(c); },
    remove: c => bodyClasses.delete(c),
    contains: c => bodyClasses.has(c),
  } },
};

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
// The column table is parsed out of the page rather than restated, so a
// renamed column moves the tests with it instead of against them.
const COLS_SRC = (() => {
  const m = src.match(/const BOARD_COLS = (\[[\s\S]*?\n\]);/);
  assert.ok(m, 'BOARD_COLS not found in jarvis.html');
  return m[1];
})();
eval(grab('esc') + '\nconst BOARD_COLS = ' + COLS_SRC + ';\n' + grab('renderBoard'));
let boardSig = '';
const COLS = eval('(' + COLS_SRC + ')');

const T = (title, status, extra) =>
  Object.assign({ title, status, priority: 'P2', owner: 'voice line' }, extra || {});

function reset() {
  boardSig = '';
  bodyClasses.clear();
  nodes['board-strip'].innerHTML = ''; nodes['board-strip'].style = {};
  nodes['board-cols'].innerHTML = '';
}
const strip = () => nodes['board-strip'].innerHTML;
const cols  = () => nodes['board-cols'].innerHTML;

let passed = 0, failed = 0;
function test(name, fn) {
  reset();
  try { fn(); passed++; console.log('ok   ' + name); }
  catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); }
}

// ---- the columns are the statuses the vault already uses -------------------

test('the four columns are To Do, In Progress, Waiting on You, Done', () => {
  assert.deepStrictEqual(COLS.map(c => c.key),
    ['open', 'active', 'waiting-on-serge', 'done']);
});

test('a task appears under its own status', () => {
  renderBoard([T('alpha', 'active')]);
  const c = cols();
  const doingAt = c.indexOf('In Progress'), todoAt = c.indexOf('To Do');
  assert.ok(c.includes('alpha'));
  // it must sit after the In Progress heading, not after To Do
  assert.ok(c.indexOf('alpha') > doingAt, 'not under In Progress');
  assert.ok(doingAt > todoAt, 'column order changed unexpectedly');
});

test('EVERY task lands somewhere -- an unknown status is not dropped', () => {
  // The silent failure this board could produce: a status the page has never
  // heard of and a card that simply is not there.
  renderBoard([T('mystery', 'parked-by-someone'), T('beta', 'open')]);
  assert.ok(cols().includes('mystery'), 'a task with an unknown status vanished');
  assert.ok(cols().includes('beta'));
});

test('a task with NO status is treated as open, not dropped', () => {
  renderBoard([{ title: 'naked' }]);
  assert.ok(cols().includes('naked'));
});

test('the card carries priority and owner', () => {
  renderBoard([T('alpha', 'open', { priority: 'P1', owner: 'terminal' })]);
  assert.ok(cols().includes('P1'));
  assert.ok(cols().includes('terminal'));
});

test('titles are escaped', () => {
  renderBoard([T('<img src=x onerror=alert(1)>', 'open')]);
  assert.ok(!cols().includes('<img'), 'title was not escaped');
});

test('an untitled task still draws a card rather than an empty one', () => {
  renderBoard([{ status: 'open' }]);
  assert.ok(cols().includes('(untitled)'));
});

// ---- the summary strip must agree with the columns -------------------------

test('the strip counts match the columns', () => {
  renderBoard([T('a', 'active'), T('b', 'waiting-on-serge'),
               T('c', 'open'), T('d', 'open')]);
  const s = strip();
  assert.ok(/<b>1<\/b> doing/.test(s), 'doing count wrong: ' + s);
  assert.ok(/<b>1<\/b> you/.test(s), 'waiting count wrong: ' + s);
  assert.ok(/<b>2<\/b> open/.test(s), 'open count wrong: ' + s);
});

test('an unknown status is counted in open, matching where its card went', () => {
  // The count and the column must not disagree -- that is how a glance lies.
  renderBoard([T('mystery', 'nonsense')]);
  assert.ok(/<b>1<\/b> open/.test(strip()));
});

test('no tasks hides the strip entirely rather than showing three zeroes', () => {
  renderBoard([]);
  assert.strictEqual(nodes['board-strip'].style.display, 'none');
});

test('no tasks also force-closes the board', () => {
  renderBoard([T('a', 'open')]);
  document.body.classList.toggle('board-open', true);
  renderBoard([]);
  assert.ok(!bodyClasses.has('board-open'),
    'the board stayed open over an empty list');
});

// ---- the DONE column tells the truth ---------------------------------------

test('DONE says "not served yet" rather than pretending to be empty', () => {
  // read_tasks() stops at "### Completed Tasks" and never opens a [x] line,
  // so this column CANNOT populate until the server changes. An empty column
  // that explains itself is honest; one that just sits there is not.
  renderBoard([T('a', 'open')]);
  assert.ok(cols().includes('not served yet'));
});

test('the other empty columns say "nothing here", not the served-yet excuse', () => {
  renderBoard([T('a', 'open')]);
  const c = cols();
  assert.ok(c.includes('nothing here'));
  assert.strictEqual((c.match(/not served yet/g) || []).length, 1);
});

// ---- the 15 Hz guard -------------------------------------------------------

test('an unchanged payload does not rebuild the DOM (this polls at 15 Hz)', () => {
  const ts = [T('a', 'open')];
  renderBoard(ts);
  let writes = 0, held = nodes['board-cols'].innerHTML;
  Object.defineProperty(nodes['board-cols'], 'innerHTML', {
    get() { return held; }, set(v) { writes++; held = v; }, configurable: true,
  });
  renderBoard(ts.map(t => Object.assign({}, t)));
  assert.strictEqual(writes, 0, 'the board rebuilt on an unchanged payload');
  renderBoard([T('a', 'active')]);
  assert.ok(writes > 0, 'a real change must redraw');
  delete nodes['board-cols'].innerHTML;
  nodes['board-cols'] = makeNode('board-cols');
});

// ---- the roll-down behaviour, asserted on the source -----------------------
// These are structural: the timing and latch logic runs on real mouse events
// and a stub cannot prove the feel. What it CAN prove is that the decisions
// are still in the file, which is what a future edit would quietly undo.

test('opening waits for deliberate intent, not a cursor passing by', () => {
  const m = src.match(/const BOARD_INTENT_MS\s*=\s*(\d+)/);
  assert.ok(m, 'BOARD_INTENT_MS is gone');
  assert.ok(+m[1] >= 150, 'intent delay too short -- it will fling open: ' + m[1]);
});

test('it is slower to leave than to arrive', () => {
  const o = +src.match(/const BOARD_INTENT_MS\s*=\s*(\d+)/)[1];
  const c = +src.match(/const BOARD_CLOSE_MS\s*=\s*(\d+)/)[1];
  assert.ok(c > o, 'closing must lag opening, or it flickers on the way in');
});

test('THE LATCH EXISTS -- contact pins it open', () => {
  // Without this, hover-to-open is also hover-to-close: the cursor strays and
  // the board rolls up under whatever Serge was doing. It matters more once
  // the cards drag, which is why it is here before they do.
  assert.ok(/boardLatched\s*=\s*true/.test(src), 'nothing ever latches the board');
  assert.ok(/if \(boardLatched\) return;/.test(src),
    'the close path does not respect the latch');
});

test('a latched board still closes on click-away and on Escape', () => {
  assert.ok(/e\.key === 'Escape'/.test(src), 'no Escape handler');
  assert.ok(/board\.contains\(e\.target\)/.test(src), 'no click-away handler');
  // boardOpen(false) must clear the latch, or the next hover cannot re-open.
  assert.ok(/if \(!on\) boardLatched = false;/.test(src),
    'closing does not clear the latch -- it would jam open-only');
});

test('the approach zone is the whole title block, not just the strip', () => {
  assert.ok(/mid\.addEventListener\('mouseenter', boardWantOpen\)/.test(src),
    'hover is bound to the strip alone -- "near it" means the title block');
});

// ---- wiring ----------------------------------------------------------------

test('renderBoard is called from the poll loop on a live line', () => {
  const called = src.split('\n').some(
    l => /renderBoard\(d\.tasks/.test(l) && !/^\s*(\/\/|\*)/.test(l));
  assert.ok(called, 'poll() does not call renderBoard');
});

test('the markup it writes into exists in the page', () => {
  for (const id of ['board-strip', 'board-cols'])
    assert.ok(src.includes('id="' + id + '"'), 'missing markup: ' + id);
});

test('READ-ONLY in this pass -- no card is draggable and nothing writes back', () => {
  // Serge parked the drag ("for right now, maybe remove the drag part").
  // A draggable card that silently does nothing is worse than none.
  // Scoped to the FUNCTION BODY with comments stripped. The first version
  // sliced up to BOARD_INTENT_MS and so read the comment block in between --
  // which explains why the latch matters "once the cards are draggable" and
  // was duly failed for saying so. Grepping source punishes the prose that
  // documents the decision; assert on the code. (Second time today.)
  const body = grab('renderBoard')
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  assert.ok(!/draggable/.test(body), 'a card is draggable but nothing handles it');
  assert.ok(!/fetch\(/.test(body), 'the board writes back -- not in this pass');
});

test('the board is animated, per his ask', () => {
  // Scoped to the #board RULE, not "somewhere after the words #board {".
  // The first version used a lazy match that sailed past the closing brace
  // and found a transition in a later rule, so deleting the animation
  // outright still passed. Found by fault injection, not by reading it.
  const i = src.indexOf('#board {');
  assert.ok(i !== -1, '#board rule is gone');
  const rule = src.slice(i, src.indexOf('}', i));
  assert.ok(/transition:/.test(rule),
    'the roll-down has no transition -- he asked for animation');
  assert.ok(/transform:/.test(rule), 'it does not move, so it cannot roll down');
});

// ---- THE FROZEN HUD ---------------------------------------------------
// Serge, 2026-08-05 ~6:20 PM: "I don't see the board." poll() opened with
// `if (webActive()) return;` ABOVE the fetch, so for the whole length of a
// browser turn -- capturing, thinking, speaking, queued audio, turnOpen --
// the entire HUD stopped updating. The board could never appear, because it
// is only drawn from a payload it was never given. Every other panel was
// silently stale too, and the local 1 s clocks made it look alive.
//
// This bug was found and written up at 1:55 PM, handed to another session,
// and never picked up. It gets a test now.

test('poll() FETCHES even during a browser turn -- the HUD must not freeze', () => {
  const start = src.indexOf('async function poll(');
  assert.ok(start !== -1, 'poll() not found');
  const body = src.slice(start, src.indexOf('const r = await fetch', start));
  const live = body.split('\n').filter(l => !/^\s*(\/\/|\*|\/\*)/.test(l));
  assert.ok(!live.some(l => /if \(webActive\(\)\) return;/.test(l)),
    'poll() returns before fetching -- the whole HUD freezes during a turn');
});

test('the ring state is still protected during a browser turn', () => {
  // The guard was not wrong, only too wide. Removing it entirely would let
  // the terminal line's state overwrite the ring mid-sentence.
  assert.ok(/if \(!webActive\(\) && state !== 'warming'/.test(src),
    'the ring state lost its guard');
});

test('the waveform is still protected during a browser turn', () => {
  // sigLevel is the half that had NO inner guard of its own: with the early
  // return gone, an unguarded read zeroes the visualiser while Jarvis speaks.
  const i = src.indexOf("if (d.state === 'speaking' && fresh");
  assert.ok(i !== -1, 'the waveform block is gone');
  const before = src.slice(Math.max(0, i - 400), i);
  assert.ok(/if \(!webActive\(\)\) \{/.test(before),
    'sigLevel is computed during a browser turn -- the ring will go flat');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
