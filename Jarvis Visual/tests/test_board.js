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
           rect: { bottom: 0 },
           getBoundingClientRect() { return this.rect; },
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
// Same reasoning for the checking set: parsed out of the page, never restated,
// so a change to which statuses count as "checking" moves these tests with it.
const CHECK_SRC = (() => {
  const m = src.match(/const BOARD_CHECKING = (\[[^\]]*\]);/);
  assert.ok(m, 'BOARD_CHECKING not found in jarvis.html');
  return m[1];
})();
eval(grab('esc') + '\nconst BOARD_COLS = ' + COLS_SRC + ';'
   + '\nconst BOARD_CHECKING = ' + CHECK_SRC + ';\n' + grab('renderBoard'));
let boardSig = '';
let boardLatched = false;
eval(grab('boardOpen'));
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

// INVERTED 2026-08-06, not extended: "the four columns are ..." and "the six
// columns are ..." cannot both guard this table. Serge added Review and Test
// (~6:44 AM), and the order is the order work flows in.
test('the six columns are To Do, In Progress, Review, Test, Waiting on You, Done', () => {
  assert.deepStrictEqual(COLS.map(c => c.key),
    ['open', 'active', 'review', 'test', 'waiting-on-serge', 'done']);
});

test('the grid draws as many columns as the table declares', () => {
  // A six-entry table rendered into a four-column grid wraps Waiting on You
  // and Done onto a second row -- which reads as a broken board, not a wide one.
  const r = rule('#board-cols');
  const m = r.match(/grid-template-columns: repeat\((\d+), 1fr\)/);
  assert.ok(m, '#board-cols is no longer a repeat() grid');
  assert.strictEqual(+m[1], COLS.length,
    'the grid and the column table disagree: ' + m[1] + ' vs ' + COLS.length);
});

test('review and test tasks land in their OWN columns', () => {
  renderBoard([T('needs eyes', 'review'), T('needs proof', 'test')]);
  const c = cols();
  const revAt = c.indexOf('Review'), tstAt = c.indexOf('Test');
  assert.ok(c.indexOf('needs eyes') > revAt, 'a review task is not under Review');
  assert.ok(c.indexOf('needs proof') > tstAt, 'a test task is not under Test');
  assert.ok(revAt < tstAt, 'Review must come before Test -- work flows that way');
});

test('THE CHECKING COUNT EXISTS -- review and test are not invisible in the strip', () => {
  // The whole reason this count was added. A status with a column of its own
  // is excluded from doing/you/open by construction, so without a count of
  // its own a task in Review vanishes from the heading Serge actually reads.
  renderBoard([T('a', 'review'), T('b', 'test')]);
  const s = strip();
  assert.ok(/<b>2<\/b> checking/.test(s), 'checking count wrong or missing: ' + s);
  assert.ok(/<b>0<\/b> open/.test(s),
    'a review task was ALSO counted as open -- the strip double-counts: ' + s);
});

test('the checking count is HIDDEN when nothing is being checked', () => {
  // His condition: only when non-zero, so a quiet day is not noisier.
  renderBoard([T('a', 'open'), T('b', 'active')]);
  assert.ok(!/checking/.test(strip()),
    'the strip shows a zero checking count on a quiet day: ' + strip());
});

test('Review and Test wear neither the doing green nor the waiting amber', () => {
  // They are work in flight that is NOT on Serge. Painting them amber would
  // say he is blocking; painting them green would say they are being worked.
  for (const k of ['review', 'test']) {
    const c = COLS.find(x => x.key === k);
    assert.notStrictEqual(c.cls, 'doing', k + ' is painted as In Progress');
    assert.notStrictEqual(c.cls, 'waiting', k + ' is painted as Waiting on You');
    assert.ok(c.cls, k + ' has no class at all -- it is indistinguishable from To Do');
  }
});

test('the strip WRAPS rather than clips when the fourth count appears', () => {
  // The 300px card clipped once already with three counts on one row. A
  // fourth cannot be allowed to push a number off the edge silently.
  assert.ok(/flex-wrap: wrap/.test(rule('#board-strip')),
    'the counts row cannot wrap -- a fourth count will clip like the last one did');
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

test('DONE says nothing finished TODAY -- not "not served yet"', () => {
  // Inverted 2026-08-06. "Not served yet" was the literal truth while
  // read_tasks() could not emit a finished task at all; the server can now,
  // so the same words would be a lie -- and the worst kind, one that reads
  // as an apology for a working feature.
  renderBoard([T('a', 'open')]);
  assert.ok(cols().includes('nothing finished today'));
  assert.ok(!cols().includes('not served yet'),
    'the column still excuses itself for a feature that now exists');
});

test('the other empty columns say "nothing here", not the DONE wording', () => {
  renderBoard([T('a', 'open')]);
  const c = cols();
  assert.ok(c.includes('nothing here'));
  assert.strictEqual((c.match(/nothing finished today/g) || []).length, 1);
});

test('a finished task actually draws a card in DONE', () => {
  renderBoard([T('a', 'open'), T('shipped it', 'done')]);
  const c = cols();
  assert.ok(c.includes('shipped it'), 'a done task reaches no column');
  assert.ok(!c.includes('nothing finished today'),
    'DONE claims an empty day while holding a card');
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

// ---- THE HEADER IS THE CARD'S, NOT THE TOP BAR'S ----------------------
// Serge, 2026-08-06 ~6:05 AM: the collapsed strip should read as the header
// of the active tasks -- "it's like an extension of the active task" -- and
// the roll-down should go "down and sideways, sliding... slowly."
//
// These assert his words, not my taste, for the same reason the ambient
// tests do: a preference stated in a test survives a future restyle, one
// held in a build does not.

function rule(sel) {
  const i = src.indexOf(sel + ' {');
  assert.ok(i !== -1, 'CSS rule is gone: ' + sel);
  return src.slice(i, src.indexOf('}', i));
}

// The first pass of these tests asserted that the strip was PAINTED like the
// card while it still sat in the top bar. Serge corrected that within ten
// minutes -- "it should be ON TOP OF the active task" -- so those assertions
// were inverted rather than extended: a strip styled like the card and a
// strip that IS the card's heading cannot both be what this file guards.

test('the summary lives IN the tasks card, not in the top bar', () => {
  const head = src.indexOf('<div id="tasks-head">');
  assert.ok(head !== -1, 'the tasks card has no heading row');
  // Between the heading row opening and the task list is the whole of
  // "inside the heading" -- no offset arithmetic, which is what made the
  // first version of this assertion fail against a correct page.
  const headRow = src.slice(head, src.indexOf('id="tasks-body"', head));
  assert.ok(/id="board-strip"/.test(headRow),
    'the board summary is not inside the tasks heading row');
  // And it must not have been left behind in the title block as well.
  const mid = src.slice(src.indexOf('<div class="mid">'), src.indexOf('id="topbar-right"'));
  assert.ok(!/id="board-strip"/.test(mid),
    'the strip is still in the top bar -- exactly what he asked me to undo');
});

test('the heading row is the ACTIVE TASKS heading, title and all', () => {
  const head = src.slice(src.indexOf('<div id="tasks-head">'),
                         src.indexOf('id="tasks-body"'));
  assert.ok(/Active Tasks/.test(head),
    'the card lost its title when the strip moved in');
});

test('the heading keeps .sec-title\'s bullet and tracking', () => {
  const r = rule('#tasks-head');
  assert.ok(/letter-spacing: 0\.25em/.test(r), 'the heading no longer tracks with the other cards');
  assert.ok(/color: var\(--sec\)/.test(r), 'the heading is not the section colour');
  assert.ok(/content: "\\25CF"/.test(rule('#tasks-head .th-title::before')),
    'the section bullet is gone');
});

test('the heading is NOT styled as a control', () => {
  // A border says pressable. This row is a heading that happens to react to
  // an approach, so the hover affordance is a fill and nothing else.
  const r = rule('#tasks-head');
  assert.ok(!/border: /.test(r), 'the heading grew a border -- it will read as a button');
  assert.ok(/background: rgba\(var\(--accent-rgb\)/.test(rule('#tasks-head:hover, body.board-open #tasks-head')),
    'the approach gives no feedback at all');
});

test('the counts sit on their OWN ROW, under the title', () => {
  // Inverted from "pushed to the far edge of the card", which is what the
  // one-row version did and what CLIPPED: at 300px the title plus three
  // labelled counts plus the caret do not fit, so "1 open" was cut off.
  // Serge's call: "the active task as a title, then underneath the Kanban."
  const r = rule('#board-strip');
  assert.ok(!/margin-left: auto/.test(r),
    'the counts are back on the title row -- they will clip at 300px');
  assert.ok(/margin-top: \d+px/.test(r), 'the counts do not sit below the title');
  assert.ok(!/display: flex/.test(rule('#tasks-head')),
    'the heading is still a single flex row -- the counts cannot stack');
});

test('the sheet wears the panel EDGE the cards use', () => {
  // 0.28 is the exact accent alpha #left/#right are framed with. A different
  // number is the whole failure mode here: nearly-matching reads as a mistake.
  assert.ok(/border: 1px solid rgba\(var\(--accent-rgb\), 0\.28\)/
    .test(rule('#board')), 'the sheet edge does not match the panels');
});

test('the sheet hangs off the RIGHT, where its heading now is', () => {
  const r = rule('#board');
  assert.ok(/right: \d+px/.test(r), 'the sheet is not anchored to the right');
  assert.ok(!/left: 50%/.test(r),
    'the sheet still drops from the middle -- it has no visible parent there');
});

test('the sheet wears the card fill too', () => {
  assert.ok(/background: var\(--bg-panel\)/.test(rule('#board')),
    'the roll-down still has its own hardcoded background');
});

test('the heading tracking matches the card headings beside it', () => {
  const m = rule('.sec-title').match(/letter-spacing: ([\d.]+em)/);
  assert.ok(m, '.sec-title lost its tracking');
  assert.ok(new RegExp('letter-spacing: ' + m[1]).test(rule('#tasks-head')),
    'the tasks heading no longer tracks with SESSIONS and MAIL below it');
});

test('OPEN, the heading stays visibly lit', () => {
  // The seam-dissolve from the first pass went with the move, deliberately:
  // the sheet is far wider than the 300px card, so the two cannot be flush,
  // and faking it would draw a border stub across the stage. The heading
  // holds its highlight instead -- that is what ties the sheet to its parent.
  assert.ok(/body\.board-open #tasks-head/.test(src),
    'the heading gives no sign the board hanging below belongs to it');
});

test('the slide is SLOW -- 500ms or more', () => {
  const r = rule('#board');
  const ms = [...r.matchAll(/transform (\d+)ms/g)].map(m => +m[1]);
  assert.ok(ms.length, 'the transform is not transitioned at all');
  assert.ok(ms.every(v => v >= 500),
    'the roll-down is still fast: ' + ms.join(', ') + 'ms');
});

test('it slides SIDEWAYS as well as down', () => {
  const r = rule('#board');
  const m = r.match(/transform: translate\(([^;]+)\);/);
  assert.ok(m, '#board has no resting transform');
  // Right-anchored now, so the sideways leg is a plain positive offset: it
  // comes in from the right, the side its heading sits on.
  assert.ok(/^\s*[\d.]+px/.test(m[1]),
    'no sideways leg -- it drops straight down: ' + m[1]);
  assert.ok(/,\s*-[\d.]+px/.test(m[1]),
    'no downward leg: ' + m[1]);
});

test('the sideways move is a TRANSFORM, never a left/right animation', () => {
  // `left` is not compositable; animating it over half a second is visibly
  // janky, and jank is what a slow animation cannot hide.
  const r = rule('#board');
  assert.ok(!/transition:[^;]*\bleft\b/.test(r),
    '#board animates `left` -- it will stutter');
});

test('visibility still lifts in step with the slide', () => {
  // visibility is delayed by the transition length so the sheet is not
  // clickable while it is still on its way out. A stale 260ms here makes it
  // vanish mid-slide, which reads as a flicker.
  const r = rule('#board');
  const t = r.match(/transform (\d+)ms/)[1];
  assert.ok(new RegExp('visibility 0s linear ' + t + 'ms').test(r),
    'the visibility delay no longer matches the slide length');
});

test('the caret turns at the same pace as the sheet', () => {
  const t = rule('#board').match(/transform (\d+)ms/)[1];
  assert.ok(new RegExp('transform ' + t + 'ms').test(rule('#board-strip .caret')),
    'the caret and the sheet move at different speeds');
});

test('the INTENT delay was not slowed with the animation', () => {
  // Slowing the approach threshold would make the board feel unresponsive;
  // he asked for a slow SLIDE, which is a different number.
  const m = src.match(/BOARD_INTENT_MS = (\d+)/);
  assert.ok(m, 'the intent delay is gone');
  assert.ok(+m[1] <= 300, 'the approach delay crept up to ' + m[1] + 'ms');
});

// ---- THE SHEET MUST NOT COVER ITS OWN HEADING -------------------------
// Serge, 2026-08-06 ~7:10 AM, from his screenshot: the open sheet covered the
// ACTIVE TASKS card, so the counts strip the board hangs off was the one thing
// he could not see while looking at the board.

test('opening the board pushes the sheet BELOW the heading it hangs off', () => {
  nodes['board-strip'].rect = { bottom: 240 };
  nodes['board'].style = {};
  boardOpen(true);
  const top = parseInt(nodes['board'].style.top, 10);
  assert.ok(!isNaN(top), 'the sheet top was never set on open');
  assert.ok(top >= 240,
    'the sheet still overlaps its own heading: top ' + top + ' vs heading bottom 240');
});

test('the offset is MEASURED, never a constant', () => {
  // The heading's height varies -- the counts row wraps once the CHECKING
  // count appears -- so a magic number is right on a quiet day and wrong on
  // exactly the busy one where the board matters most.
  nodes['board-strip'].rect = { bottom: 240 };
  nodes['board'].style = {};
  boardOpen(true);
  const a = parseInt(nodes['board'].style.top, 10);
  boardOpen(false);
  nodes['board-strip'].rect = { bottom: 300 };   // the strip wrapped to two rows
  boardOpen(true);
  const b = parseInt(nodes['board'].style.top, 10);
  assert.ok(b > a,
    'the sheet ignored a taller heading -- the offset is hardcoded: ' + a + ' vs ' + b);
});

test('an unlaid-out strip does not slam the sheet to the top of the page', () => {
  // A hidden strip measures 0. Trusting that would put the sheet over the top
  // bar, which is worse than the bug being fixed.
  nodes['board-strip'].rect = { bottom: 240 };
  nodes['board'].style = {};
  boardOpen(true);
  const good = nodes['board'].style.top;
  boardOpen(false);
  nodes['board-strip'].rect = { bottom: 0 };
  boardOpen(true);
  assert.strictEqual(nodes['board'].style.top, good,
    'a zero measurement moved the sheet -- it will cover the top bar');
});

test('the CSS still carries a resting top, so a measure-less open is not broken', () => {
  assert.ok(/top: \d+px/.test(rule('#board')),
    '#board has no fallback top -- it would sit at the viewport edge');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
