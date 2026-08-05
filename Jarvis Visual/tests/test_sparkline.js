#!/usr/bin/env node
// Tests for the SYS MONITOR sparklines and the history behind them.
//
// Run:  ./tests/run-tests.sh   (from Jarvis Visual/)
//    or  node tests/test_sparkline.js
//
// Serge, 2026-08-05: "the CPU, the MEM, I think it does not refresh fast
// enough. It's a bit oversized. Maybe it could be a circle... no, no circle.
// A pie. I don't like the pie... you think about it."
//
// The answer was: keep the bar, shrink it, and add a minute of history so the
// panel visibly moves -- plus a real fix to the server's 2 s sample rate,
// which was the actual cause of the sluggishness.
//
// Three ways this fails silently, which is what these guard:
//
//   the 15 Hz trap -- /signals is polled fifteen times a second. If every poll
//                     appended, "the last minute" would really be the last
//                     four seconds, and Serge would have no way to tell.
//   unbounded       -- a history that never drops its oldest sample grows for
//                     as long as the tab is open.
//   the geometry    -- a partly-filled history stretched across the full box
//                     draws ten seconds as though it were a minute.
//
// The real functions are pulled out of jarvis.html and run against a DOM stub,
// so they cannot drift from what ships.

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const HTML = path.join(__dirname, '..', 'jarvis.html');
const src = fs.readFileSync(HTML, 'utf8');

// ---- DOM stub -------------------------------------------------------------
function makeNode(id) {
  return { id, innerHTML: '', textContent: '', className: '', style: {},
           querySelector() { return null; } };
}
const nodes = {};
for (const id of ['cpu-s', 'mem-s', 'cpu-v', 'cpu-b', 'mem-v', 'mem-b',
                  'net-v', 'net-b', 'up-v', 'proc-v', 'os-v']) {
  nodes[id] = makeNode(id);
}
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

const SPARK_N = num('SPARK_N');
const SPARK_W = num('SPARK_W');
const SPARK_H = num('SPARK_H');

// State renderStats owns on the real page.
let cpuHist = [], memHist = [], statsLastAt = 0;
function fmtRate(v) { return String(v); }
function fmtUp(v) { return String(v); }
function setChip() {}

eval(grab('pushSample') + '\n' + grab('sparkPoints') + '\n'
   + grab('renderSpark') + '\n' + grab('renderStats'));

// ---- harness --------------------------------------------------------------
let passed = 0, failed = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) { passed++; console.log('ok   ' + name); }
  else {
    failed++;
    console.log('FAIL ' + name + '\n       got:  ' + JSON.stringify(got) +
                '\n       want: ' + JSON.stringify(want));
  }
}
function reset() { cpuHist = []; memHist = []; statsLastAt = 0;
                   nodes['cpu-s'].innerHTML = ''; nodes['mem-s'].innerHTML = ''; }
function sample(at, cpu, mem) {
  return { at, cpu, mem, net_kbs: 0, uptime_s: 1, procs: 1, os: 'macOS' };
}

// ---- the history ----------------------------------------------------------
reset();
check('the cap is a full minute at one sample a second', SPARK_N, 60);

const h = [];
for (let i = 0; i < 5; i++) pushSample(h, i, SPARK_N);
check('samples accumulate in order', h, [0, 1, 2, 3, 4]);

const big = [];
for (let i = 0; i < SPARK_N + 25; i++) pushSample(big, i, SPARK_N);
check('the history never grows past the cap', big.length, SPARK_N);
check('the OLDEST samples are the ones dropped', big[0], 25);
check('the newest sample is last', big[big.length - 1], SPARK_N + 24);

// ---- the geometry ---------------------------------------------------------
check('no line from an empty history', sparkPoints([], SPARK_W, SPARK_H, SPARK_N), '');
check('no line from a single point -- one sample is not a line',
      sparkPoints([50], SPARK_W, SPARK_H, SPARK_N), '');

const two = sparkPoints([0, 100], SPARK_W, SPARK_H, SPARK_N).split(' ');
check('two samples produce two points', two.length, 2);
check('the NEWEST sample sits on the right edge',
      parseFloat(two[1].split(',')[0]), SPARK_W);
// Right-anchored: with 2 of 60 samples the older one is one step in from the
// right, NOT at x=0. Stretching a short history across the whole box would
// draw two seconds as though it were a minute.
const step = SPARK_W / (SPARK_N - 1);
check('a partly-filled history grows in from the right, it does not stretch',
      Math.round(parseFloat(two[0].split(',')[0]) * 10) / 10,
      Math.round((SPARK_W - step) * 10) / 10);

const full = [];
for (let i = 0; i < SPARK_N; i++) full.push(50);
const fp = sparkPoints(full, SPARK_W, SPARK_H, SPARK_N).split(' ');
check('a full history spans the whole box', parseFloat(fp[0].split(',')[0]), 0);
check('a full history ends at the right edge',
      parseFloat(fp[fp.length - 1].split(',')[0]), SPARK_W);

// y is inverted: 100% must draw at the TOP. Getting this backwards produces a
// plausible-looking chart that reports every spike as a dip.
const lo = parseFloat(sparkPoints([0, 0], SPARK_W, SPARK_H, SPARK_N).split(' ')[0].split(',')[1]);
const hi = parseFloat(sparkPoints([100, 100], SPARK_W, SPARK_H, SPARK_N).split(' ')[0].split(',')[1]);
check('100% draws above 0% -- the y axis is inverted', hi < lo, true);
check('0% stays inside the box', lo <= SPARK_H, true);
check('100% stays inside the box', hi >= 0, true);

// Out-of-range values are clamped, not drawn off the canvas.
const over = parseFloat(sparkPoints([150, 150], SPARK_W, SPARK_H, SPARK_N).split(' ')[0].split(',')[1]);
const under = parseFloat(sparkPoints([-40, -40], SPARK_W, SPARK_H, SPARK_N).split(' ')[0].split(',')[1]);
check('a value over 100 is clamped to the ceiling', over, hi);
check('a negative value is clamped to the floor', under, lo);

// ---- the 15 Hz trap -------------------------------------------------------
reset();
renderStats(sample(1000, 10, 20));
check('a first sample is recorded', cpuHist, [10]);

for (let i = 0; i < 30; i++) renderStats(sample(1000, 10, 20));
check('30 polls of the SAME server sample add nothing', cpuHist, [10]);

renderStats(sample(1001, 40, 50));
check('a NEW server sample extends the history', cpuHist, [10, 40]);
check('memory is tracked on the same samples', memHist, [20, 50]);

// A server too old to send `at` must not spam the history at 15 Hz.
reset();
for (let i = 0; i < 20; i++) renderStats({ cpu: 5, mem: 5, net_kbs: 0,
                                           uptime_s: 1, procs: 1, os: 'macOS' });
check('a payload with no timestamp never grows the history', cpuHist.length, 0);
check('...and the sparkline stays empty rather than drawing a flat lie',
      nodes['cpu-s'].innerHTML, '');

// ---- the drawing ----------------------------------------------------------
reset();
renderStats(sample(1, 10, 10));
check('one sample draws nothing', nodes['cpu-s'].innerHTML, '');
renderStats(sample(2, 20, 20));
check('two samples draw a polyline',
      nodes['cpu-s'].innerHTML.startsWith('<polyline points="'), true);

// The page repaints at 15 Hz; an unchanged sparkline must not be rebuilt.
const before = nodes['cpu-s'].innerHTML;
let writes = 0;
Object.defineProperty(nodes['cpu-s'], 'innerHTML', {
  get() { return before; },
  set() { writes++; },
  configurable: true,
});
for (let i = 0; i < 15; i++) renderStats(sample(2, 20, 20));
check('an unchanged sparkline is not rewritten', writes, 0);
delete nodes['cpu-s'].innerHTML;
nodes['cpu-s'].innerHTML = before;

// ---- report ---------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
