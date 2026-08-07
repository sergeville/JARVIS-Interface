#!/usr/bin/env node
// Tests for the HUD chrome that moved on 2026-08-05, when Serge said the page
// "is starting to be crowded".
//
// Run:  ./tests/run-tests.sh   (from Jarvis Visual/)
//    or  node tests/test_hud_chrome.js
//
// Three things moved, and each one has a way of failing silently:
//
//   renderUsage  -- left-panel block -> a strip in the top bar. The bars and
//                   reset clocks became a hover title. The risk is that the
//                   demoted half quietly stops updating, and Serge reads a
//                   stale percentage as a live one.
//   setChip      -- the status items gained a dot element beside their label.
//                   The old body wrote textContent on the wrapper, which would
//                   delete that dot on the first update.
//   showLine     -- the activity log became an overlay on the stage. It has to
//                   cap itself and get out of the way when nothing is going on,
//                   or it becomes permanent furniture over the avatar.
//
// As with the other page tests, the real functions are pulled out of
// jarvis.html and run against a DOM stub, so they cannot drift from what ships.

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const HTML = path.join(__dirname, '..', 'jarvis.html');
const src = fs.readFileSync(HTML, 'utf8');

// ---- DOM stub -------------------------------------------------------------
function makeNode(id, cls) {
  const n = {
    id, className: cls || '', innerHTML: '', textContent: '', title: '',
    style: {}, children: [], _classes: new Set(),
    setAttribute() {}, getAttribute() { return null; },
    querySelector(sel) {
      return this.children.find(c => c.className === sel.replace('.', '')) || null;
    },
    appendChild(c) { this.children.push(c); },
    removeChild(c) { this.children = this.children.filter(x => x !== c); },
    get firstChild() { return this.children[0]; },
    classList: {
      add(c) { n._classes.add(c); },
      remove(c) { n._classes.delete(c); },
      contains(c) { return n._classes.has(c); },
      toggle(c, on) { on ? n._classes.add(c) : n._classes.delete(c); },
    },
  };
  return n;
}
const nodes = {};
for (const id of ['topbar-usage', 'log', 'lines']) nodes[id] = makeNode(id);
global.document = {
  getElementById: id => nodes[id] || null,
  createElement: () => makeNode(null),
  querySelectorAll: () => [],
};

// ---- pull the real functions out of the page ------------------------------
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
function num(name) {
  const m = src.match(new RegExp('const ' + name + '\\s*=\\s*(\\d+)'));
  assert.ok(m, name + ' not found in jarvis.html');
  return parseInt(m[1], 10);
}

const linesEl = nodes['lines'];
// Turn state the real page holds. These used to feed the fade's busy-check;
// the fade is gone (2026-08-07), and they stay because the tests below prove
// the overlay survives every one of these states.
let turnOpen = false, thinking = false, playQueue = [];
let usageSig = '', usageWrittenAt = null, usageResets = [], logLastAt = 0;
const shownLines = new Set();
const LOG_KEEP = num('LOG_KEEP');

// fitLog joined the eval 2026-08-07: showLine now calls it, so leaving it
// out made every showLine test die on `fitLog is not defined` -- the tests
// were red for a reason that had nothing to do with what they assert.
// Its own behaviour is proven in test_log_fit.js against stubbed heights;
// here it just has to exist and be harmless, which the 0-height stub
// guarantees (a zero measurement deletes nothing, by design).
eval(grab('fmtDur') + '\n' + grab('useClass') + '\n'
   + grab('renderUsage') + '\n' + grab('tickUsageRest') + '\n'
   + grab('setChip') + '\n' + grab('fitLog') + '\n'
   + grab('showLine') + '\n' + grab('tickLogIdle'));

// ---- harness --------------------------------------------------------------
let passed = 0, failed = 0;
function reset() {
  usageSig = ''; usageWrittenAt = null; usageResets = []; logLastAt = 0;
  turnOpen = false; thinking = false; playQueue = [];
  shownLines.clear();
  nodes['topbar-usage'].innerHTML = '';
  nodes['topbar-usage'].title = '';
  nodes['topbar-usage'].className = '';
  nodes['lines'].children = [];
  nodes['log']._classes = new Set();
}
function test(name, fn) {
  reset();
  try { fn(); passed++; console.log('ok   ' + name); }
  catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); }
}
const NOW = () => Date.now() / 1000;
const strip = () => nodes['topbar-usage'];

// ---- renderUsage: the top-bar strip ---------------------------------------

test('no reading clears the numbers but leaves the strip in place', () => {
  // The toggle lives beside this strip and is the only control that can go
  // fetch a reading -- so the strip must never take itself out of the bar.
  renderUsage({ctx_pct: 12, five_hour: {pct: 27}, seven_day: {pct: 82}});
  renderUsage(null);
  assert.strictEqual(strip().innerHTML, '');
  assert.strictEqual(strip().title, '');
});

test('three readings render three compact cells', () => {
  renderUsage({ctx_pct: 12, five_hour: {pct: 27}, seven_day: {pct: 82}});
  const html = strip().innerHTML;
  assert.strictEqual((html.match(/class="tu/g) || []).length, 3);
  assert.ok(html.includes('CTX'));
  assert.ok(html.includes('5H'));
  assert.ok(html.includes('WK'));
  assert.ok(html.includes('12%') && html.includes('27%') && html.includes('82%'));
});

test('a missing bucket is skipped, not drawn as a dash', () => {
  renderUsage({ctx_pct: 12});
  const html = strip().innerHTML;
  assert.strictEqual((html.match(/class="tu/g) || []).length, 1);
  assert.ok(!html.includes('NaN'));
  assert.ok(!html.includes('undefined'));
});

test('an all-null payload renders nothing rather than three NaNs', () => {
  renderUsage({ctx_pct: null, five_hour: {pct: null}, seven_day: {pct: null}});
  assert.strictEqual(strip().innerHTML, '');
});

test('the three pressure states keep the same thresholds as the old panel', () => {
  // calm under 70, warn to 90, spent above -- the doctrine used everywhere
  // else on this page. A percentage that changes colour at a different number
  // than the stack rows would teach Serge two different scales.
  renderUsage({ctx_pct: 69, five_hour: {pct: 70}, seven_day: {pct: 90}});
  const html = strip().innerHTML;
  assert.ok(html.includes('class="tu "') || html.includes('class="tu ">'),
            'calm cell should carry no pressure class');
  assert.ok(html.includes('class="tu warn"'));
  assert.ok(html.includes('class="tu bad"'));
});

test('percentages are rounded, never printed raw', () => {
  renderUsage({ctx_pct: 12.4999, five_hour: {pct: 27.5}, seven_day: {pct: 81.99}});
  const html = strip().innerHTML;
  assert.ok(html.includes('12%') && html.includes('28%') && html.includes('82%'));
  assert.ok(!html.includes('.'), 'a raw float reached the bar');
});

test('the reset clocks survive the move -- onto the hover title', () => {
  // The demotion is the risk being guarded: 91% with ten minutes to go is a
  // different fact from 91% with two days to go, so the clock must still exist.
  renderUsage({ctx_pct: 12,
               five_hour: {pct: 27, resets_at: NOW() + 3600},
               seven_day: {pct: 82, resets_at: NOW() + 86400},
               written_at: NOW()});
  assert.ok(strip().title.includes('5H resets in'), strip().title);
  assert.ok(strip().title.includes('WK resets in'), strip().title);
});

test('a reset already past reads "reset due", not a negative countdown', () => {
  renderUsage({ctx_pct: 12, five_hour: {pct: 27, resets_at: NOW() - 60},
               written_at: NOW()});
  assert.ok(strip().title.includes('5H reset due'), strip().title);
  assert.ok(!strip().title.includes('-'), strip().title);
});

test('the reading\'s age is on the title, so a stale number cannot pose as live', () => {
  renderUsage({ctx_pct: 12, written_at: NOW() - 125});
  assert.ok(/read .* ago/.test(strip().title), strip().title);
});

test('past ten minutes the whole strip dims', () => {
  renderUsage({ctx_pct: 12, written_at: NOW() - 601});
  assert.strictEqual(strip().className, 'stale');
});

test('a fresh reading is not dimmed', () => {
  renderUsage({ctx_pct: 12, written_at: NOW() - 5});
  assert.strictEqual(strip().className, '');
});

test('a payload with no written_at does not claim an age', () => {
  renderUsage({ctx_pct: 12});
  assert.ok(!strip().title.includes('read '), strip().title);
});

test('an unchanged reading is not rebuilt, but its clocks still tick', () => {
  // The page polls at 15 Hz. The markup must not be rewritten every frame --
  // but the countdown on the title has to keep moving anyway.
  // The clock is read ONCE and reused. Calling NOW() again for the second
  // render made this test flaky: if the two calls straddled a second
  // boundary the payload genuinely differed, the rebuild was correct, and
  // the test failed for a reason that had nothing to do with the guard.
  // (Caught 2026-08-05 -- it failed one run in roughly ten.)
  const t = NOW();
  const payload = () => ({ctx_pct: 12,
                          five_hour: {pct: 27, resets_at: t + 3600},
                          written_at: t});
  renderUsage(payload());
  strip().innerHTML = 'SENTINEL';
  renderUsage(payload());
  assert.strictEqual(strip().innerHTML, 'SENTINEL', 'markup was rebuilt');
  assert.ok(strip().title.includes('resets in'), 'the clock stopped ticking');
});

test('a changed reading IS rebuilt', () => {
  renderUsage({ctx_pct: 12});
  renderUsage({ctx_pct: 44});
  assert.ok(strip().innerHTML.includes('44%'));
});

// ---- setChip: the bottom-bar status items ---------------------------------

test('setChip writes the label without destroying the dot beside it', () => {
  // This is the exact regression the rewrite exists to prevent: the old body
  // set textContent on the wrapper, which would have removed the dot element
  // on the first status update and left a bare word in the bar.
  const dot = makeNode(null, 'dot');
  const label = makeNode(null, 't');
  const item = makeNode('chip-core');
  item.children = [dot, label];

  setChip(item, 'AI CORE ACTIVE', 'bs on');
  assert.strictEqual(label.textContent, 'AI CORE ACTIVE');
  assert.strictEqual(item.className, 'bs on');
  assert.ok(item.children.includes(dot), 'the dot was destroyed');
  assert.strictEqual(item.textContent, '', 'text was written over the wrapper');
});

test('setChip on a plain element still writes its own text', () => {
  const plain = makeNode('plain');
  setChip(plain, 'HELLO', 'bs off');
  assert.strictEqual(plain.textContent, 'HELLO');
  assert.strictEqual(plain.className, 'bs off');
});

test('setChip tolerates a missing element instead of throwing', () => {
  // renderStats runs 15 times a second; one missing node must not take the
  // whole render down with it.
  assert.doesNotThrow(() => setChip(null, 'X', 'bs on'));
});

test('setChip does not rewrite an unchanged label', () => {
  // renderStats runs on every poll; re-assigning identical text 15 times a
  // second is work the browser does not need. Counted with a write spy rather
  // than by poking the value between calls -- the guard compares against what
  // is actually in the DOM, so poking it would be a real change, not a
  // no-op, and the test would be asserting the opposite of the rule.
  const label = makeNode(null, 't');
  let writes = 0, held = '';
  Object.defineProperty(label, 'textContent', {
    get() { return held; },
    set(v) { writes++; held = v; },
  });
  const item = makeNode('chip-line');
  item.children = [label];

  setChip(item, 'TERMINAL LINE OFF', 'bs off');
  assert.strictEqual(writes, 1);
  setChip(item, 'TERMINAL LINE OFF', 'bs off');
  setChip(item, 'TERMINAL LINE OFF', 'bs off');
  assert.strictEqual(writes, 1, 'an unchanged label was written again');

  setChip(item, 'TERMINAL LINE ACTIVE', 'bs on');
  assert.strictEqual(writes, 2, 'a changed label was not written');
  assert.strictEqual(label.textContent, 'TERMINAL LINE ACTIVE');
});

// ---- showLine / tickLogIdle: the overlay -----------------------------------

test('the overlay keeps only the last LOG_KEEP lines', () => {
  for (let i = 0; i < LOG_KEEP + 6; i++) showLine('jarvis', 'line ' + i);
  assert.strictEqual(linesEl.children.length, LOG_KEEP);
});

test('the lines it keeps are the newest ones', () => {
  for (let i = 0; i < LOG_KEEP + 3; i++) showLine('jarvis', 'line ' + i);
  const texts = linesEl.children.map(c => c.textContent);
  assert.ok(texts[texts.length - 1].includes('line ' + (LOG_KEEP + 2)));
  assert.ok(!texts.join('|').includes('line 0'), 'an old line was kept');
});

test('who it came from survives as the class, so the two colours still differ', () => {
  showLine('you', 'hello');
  showLine('jarvis', 'hello back');
  assert.strictEqual(linesEl.children[0].className, 'you');
  assert.strictEqual(linesEl.children[1].className, 'jarvis');
});

test('the speaker is prefixed onto the text, not left implicit', () => {
  showLine('you', 'hello');
  assert.strictEqual(linesEl.children[0].textContent, 'you: hello');
});

// ---- the overlay NEVER fades ------------------------------------------------
// Serge, 2026-08-07 ~4:35 PM: "maybe no fading at all would be alright for me
// too." These assertions are the INVERSION of the ones they replace, not an
// extension of them -- "it fades after 90 s of silence" and "it never fades"
// cannot both guard this file. The old ones are preserved in git.
//
// Why invert rather than delete: with nothing setting the class, a test of the
// old shape would pass for the wrong reason forever. What is worth guarding
// now is that no code path can put the class back.

test('a new line leaves the overlay visible', () => {
  nodes['log'].classList.add('idle');
  showLine('jarvis', 'something happened');
  assert.ok(!nodes['log'].classList.contains('idle'), 'stayed faded while talking');
});

test('silence past the OLD threshold no longer fades it -- the inversion', () => {
  // 90 s was the old lifetime. Being distracted lasts longer than that, which
  // is the exact case he reads it for -- so the fade cleared the stage
  // precisely when he needed it. This assertion must fail if it comes back.
  showLine('jarvis', 'a line');
  turnOpen = false; thinking = false; playQueue = [];
  logLastAt = NOW() - 100000;          // ancient by any threshold
  tickLogIdle();
  assert.ok(!nodes['log'].classList.contains('idle'), 'the fade is back');
});

test('an hour of silence and twenty ticks do not fade it -- no threshold survives', () => {
  showLine('jarvis', 'a line');
  logLastAt = NOW() - 3600;
  for (let i = 0; i < 20; i++) tickLogIdle();
  assert.ok(!nodes['log'].classList.contains('idle'));
});

test('a page that has never had a line is visible, not pre-faded', () => {
  // The markup used to ship class="idle" so the stage started clean. That
  // class was removed along with the toggle; this guards the MARKUP half,
  // which no amount of driving tickLogIdle can see.
  tickLogIdle();
  assert.ok(!nodes['log'].classList.contains('idle'));
  const markup = src.match(/<div id="log"[^>]*>/)[0];
  assert.ok(!markup.includes('idle'), 'the markup ships the box pre-faded: ' + markup);
});

test('tickLogIdle CLEARS the class rather than merely not setting it', () => {
  // Something else could add it -- a future edit, a half-applied revert. The
  // function is the one place that guarantees the text comes back.
  nodes['log'].classList.add('idle');
  tickLogIdle();
  assert.ok(!nodes['log'].classList.contains('idle'));
});

test('no code path anywhere on the page adds the idle class back', () => {
  // The tests above only drive tickLogIdle. This one covers the whole file: a
  // helpful little fade added in some other function would pass every one of
  // them and still take his transcript away.
  const adds = src.match(/classList\s*\.\s*(add|toggle)\s*\(\s*['"]idle['"]/g) || [];
  assert.strictEqual(adds.length, 0,
    'something sets the idle class again: ' + adds.join(', '));
});

test('the CSS rule that hid the overlay is gone with it', () => {
  // The other half. If the rule returns, any stray class makes it invisible
  // again -- and an invisible overlay reads as "nothing was said".
  assert.ok(!/#log\.idle\s*\{/.test(src), '#log.idle is back in the CSS');
});

test('it stays visible mid-turn, while thinking, and while audio plays', () => {
  // Three separate guards against the 2026-08-05 regression, where a spoken
  // reply outlived its own transcript. They still matter; they are just no
  // longer the only thing keeping the text on screen.
  showLine('jarvis', 'a long answer');
  logLastAt = NOW() - 100000;
  for (const st of ['turn', 'think', 'audio']) {
    turnOpen  = st === 'turn';
    thinking  = st === 'think';
    playQueue = st === 'audio' ? ['wav'] : [];
    tickLogIdle();
    assert.ok(!nodes['log'].classList.contains('idle'), 'faded during ' + st);
  }
});

test('showLine records the line so the terminal mirror will not double it', () => {
  showLine('you', 'hello');
  assert.ok(shownLines.has('you|hello'));
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
