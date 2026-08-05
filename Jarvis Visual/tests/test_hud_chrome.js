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
// Turn state the real page holds. tickLogIdle reads these: the overlay must
// not fade while Jarvis is mid-turn or still speaking.
let turnOpen = false, thinking = false, playQueue = [];
let usageSig = '', usageWrittenAt = null, usageResets = [], logLastAt = 0;
const shownLines = new Set();
const LOG_KEEP = num('LOG_KEEP');
const LOG_IDLE_AFTER = num('LOG_IDLE_AFTER');

eval(grab('fmtDur') + '\n' + grab('useClass') + '\n'
   + grab('renderUsage') + '\n' + grab('tickUsageRest') + '\n'
   + grab('setChip') + '\n' + grab('showLine') + '\n' + grab('tickLogIdle'));

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

test('a new line wakes the overlay out of idle', () => {
  nodes['log'].classList.add('idle');
  showLine('jarvis', 'something happened');
  assert.ok(!nodes['log'].classList.contains('idle'), 'stayed faded while talking');
});

test('silence past the threshold fades the overlay away', () => {
  // Without this it becomes permanent furniture over the avatar, which is the
  // thing moving it off the right column was meant to avoid.
  showLine('jarvis', 'a line');
  logLastAt = NOW() - (LOG_IDLE_AFTER + 1);
  tickLogIdle();
  assert.ok(nodes['log'].classList.contains('idle'));
});

test('a recent line keeps it visible', () => {
  showLine('jarvis', 'a line');
  logLastAt = NOW() - 1;
  tickLogIdle();
  assert.ok(!nodes['log'].classList.contains('idle'));
});

test('a page that has never had a line starts faded, not blank-but-present', () => {
  tickLogIdle();
  assert.ok(nodes['log'].classList.contains('idle'));
});

// The regression Serge caught live on 2026-08-05: the overlay counted its
// silence from when a line was ADDED, so a long spoken reply outlived its own
// transcript and the stage went blank while Jarvis was still talking.

test('it does not fade mid-turn, however long the turn runs', () => {
  showLine('jarvis', 'a long answer');
  logLastAt = NOW() - (LOG_IDLE_AFTER + 500);   // ancient by the old rule
  turnOpen = true;
  tickLogIdle();
  assert.ok(!nodes['log'].classList.contains('idle'), 'faded during a turn');
});

test('it does not fade while there is still audio to play', () => {
  // Speech outlasts the text that produced it. This is the exact case.
  showLine('jarvis', 'still speaking');
  logLastAt = NOW() - (LOG_IDLE_AFTER + 500);
  playQueue = ['wav'];
  tickLogIdle();
  assert.ok(!nodes['log'].classList.contains('idle'), 'faded mid-speech');
});

test('it does not fade while thinking', () => {
  showLine('you', 'a question');
  logLastAt = NOW() - (LOG_IDLE_AFTER + 500);
  thinking = true;
  tickLogIdle();
  assert.ok(!nodes['log'].classList.contains('idle'));
});

test('being busy restarts the silence clock, so it lingers after speech ends', () => {
  // Otherwise the transcript would vanish the instant the last word played.
  showLine('jarvis', 'done talking');
  logLastAt = NOW() - (LOG_IDLE_AFTER + 500);
  playQueue = ['wav'];
  tickLogIdle();                       // busy: clock reset
  playQueue = [];
  tickLogIdle();                       // now idle-eligible, but freshly reset
  assert.ok(!nodes['log'].classList.contains('idle'),
            'cleared the stage the moment the audio stopped');
});

test('once genuinely silent past the threshold it still fades', () => {
  showLine('jarvis', 'done');
  turnOpen = false; thinking = false; playQueue = [];
  logLastAt = NOW() - (LOG_IDLE_AFTER + 1);
  tickLogIdle();
  assert.ok(nodes['log'].classList.contains('idle'));
});

test('the silence threshold is long enough to outlast a spoken reply', () => {
  // A guard on the number itself: 25 s was shorter than Jarvis speaks for,
  // which is what made the bug. Anything under a minute reintroduces it.
  assert.ok(LOG_IDLE_AFTER >= 60,
            'LOG_IDLE_AFTER is ' + LOG_IDLE_AFTER + 's -- too short again');
});

test('showLine records the line so the terminal mirror will not double it', () => {
  showLine('you', 'hello');
  assert.ok(shownLines.has('you|hello'));
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
