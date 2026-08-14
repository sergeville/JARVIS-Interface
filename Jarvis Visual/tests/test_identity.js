#!/usr/bin/env node
// PHASE 2 — IDENTITY. The brand block, the user badge, the stacked clock,
// and the idle welcome.
//
// The failure this file exists to prevent is a badge that LOOKS informed.
// Every other instrument on this page is held to the board-never-lies rule;
// an identity chip is exactly where a plausible hardcoded number would go
// unnoticed for weeks, because nobody checks their own name. So these tests
// RUN the render function against payloads rather than reading its source —
// this project has lost six rounds to guards that only grepped.
//
// The second failure is quieter: the top bar was rebuilt in this phase, and
// the reviewer named two behaviours living in that bar that a rebuild could
// silently drop (the usage strip's hover/stale treatment, and the music and
// volume controls whose state is persisted). Their own suites prove they
// work; what is proven HERE is that the elements they need still exist.

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const src = fs.readFileSync(path.join(__dirname, '..', 'jarvis.html'), 'utf8');

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log('ok   ' + name); passed++; }
  catch (e) { console.log('FAIL ' + name + '\n     ' + e.message); failed++; }
}

// ---- run the real function, never a paraphrase of it ----------------------
// Slice by brace balance from the real file, so the thing under test is the
// thing that ships. A copy of the logic here would pass forever after the
// page changed.
function fn(name) {
  const start = src.indexOf('function ' + name + '(');
  assert.ok(start !== -1, 'no function ' + name + ' in jarvis.html');
  let i = src.indexOf('{', start), depth = 0, end = -1;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}' && --depth === 0) { end = j + 1; break; }
  }
  assert.ok(end !== -1, name + ' has unbalanced braces');
  return src.slice(start, end);
}

// A DOM small enough to read and honest about what it was asked for.
function fakeDom(ids) {
  const els = {};
  for (const id of ids) els[id] = { textContent: null, title: null, id };
  return {
    els,
    document: {
      getElementById: (id) => els[id] || null,
      querySelector: (sel) => els[sel] || null,
    },
  };
}

function runBadge(sessions, stats) {
  const d = fakeDom(['badge', 'badge-sessions', 'badge-model']);
  const f = new Function('document', fn('renderBadge') + '\nreturn renderBadge;');
  f(d.document)(sessions, stats);
  return d.els;
}

// --- the badge counts what it was given, and only that --------------------

test('the session count comes from the payload — three sessions read three', () => {
  const els = runBadge([{}, {}, {}], { model: 'claude-opus-5' });
  assert.strictEqual(els['badge-sessions'].textContent, '3 sessions');
});

test('a DIFFERENT payload gives a different count (nothing is hardcoded)', () => {
  const a = runBadge([{}, {}, {}], null)['badge-sessions'].textContent;
  const b = runBadge([{}, {}, {}, {}, {}, {}, {}], null)['badge-sessions'].textContent;
  assert.notStrictEqual(a, b, 'the count did not move when the payload did');
  assert.strictEqual(b, '7 sessions');
});

test('one session is singular — a count that reads wrong is read as a bug', () => {
  assert.strictEqual(runBadge([{}], null)['badge-sessions'].textContent, '1 session');
});

test('zero sessions is a real reading, not a placeholder', () => {
  assert.strictEqual(runBadge([], null)['badge-sessions'].textContent, '0 sessions');
});

test('NO payload leaves the placeholder — it never invents a zero', () => {
  // the difference that matters: "0 sessions" is a claim, and the page has
  // not been told anything yet. An unknown must not render as a number.
  const els = runBadge(undefined, undefined);
  assert.strictEqual(els['badge-sessions'].textContent, null,
    'the count was written before any payload arrived');
});

test('the model comes from stats, and a missing one says so', () => {
  assert.strictEqual(runBadge([], { model: 'claude-fable-5' })['badge-model'].textContent,
    'claude-fable-5');
  assert.strictEqual(runBadge([], {})['badge-model'].textContent, 'model …');
  assert.strictEqual(runBadge([], null)['badge-model'].textContent, 'model …');
});

test('no model name is written into the markup as a fallback', () => {
  const badge = src.slice(src.indexOf('<div id="badge"'), src.indexOf('id="clock"'));
  assert.ok(!/claude-/.test(badge),
    'a model name in the markup would survive a dead payload as a lie');
  assert.ok(!/\d/.test(badge.replace(/badge-\w+/g, '')),
    'a digit in the badge markup can be mistaken for a live reading');
});

test('the badge is fed on every poll, from the same payload as the cards', () => {
  assert.ok(/renderBadge\(d\.sessions \|\| \[\], d\.stats\)/.test(src),
    'renderBadge is not called from the poll with the live payload');
});

// --- the brand block names a version the repo actually shipped ------------

test('the brand version is WRITTEN from SHIP_VERSION, not typed in markup', () => {
  assert.ok(/brand-version'\)[\s\S]{0,120}textContent = SHIP_VERSION/.test(src),
    'the brand version is not written from the constant');
});

test('the markup carries no version literal of its own', () => {
  const brand = src.slice(src.indexOf('<div id="brand">'), src.indexOf('</div>', src.indexOf('bsub')));
  assert.ok(!/v\d+\.\d+\.\d+/.test(brand),
    'a hand-typed version can name a release that was never shipped');
});

test('SHIP_VERSION is still a single stampable constant', () => {
  const hits = src.match(/const SHIP_VERSION = '[^']+';/g) || [];
  assert.strictEqual(hits.length, 1, 'the stamper needs exactly one target');
});

// --- the stacked clock ----------------------------------------------------

test('the clock writes time and date into their own elements', () => {
  const body = fn('tickClock');
  assert.ok(/\.ctime/.test(body) && /\.cdate/.test(body),
    'the stacked clock does not address both halves');
});

test('both halves come from ONE Date — they cannot straddle a midnight', () => {
  const body = fn('tickClock');
  const news = body.match(/new Date\(\)/g) || [];
  assert.strictEqual(news.length, 1,
    'two reads of the clock can disagree across a second boundary');
});

test('the clock still ticks once a second, on the existing timer', () => {
  assert.ok(/setInterval\(tickClock, 1000\); tickClock\(\);/.test(src),
    'the clock lost its tick or its first draw');
});

// --- the welcome defers to everything ------------------------------------

test('the welcome shows ONLY when idle, unasked and not mid-turn', () => {
  // ANCHORED ON THE WELCOME'S OWN ELEMENT, not on the first `toggle('on'` in
  // the file. The first version matched whichever came first, and Phase 5's
  // icon rail later added one ABOVE it — so this test reported the welcome
  // broken while reading the rail's line. SEVENTH instance of the first-match
  // trap on this record, and the one no injection could have caught: the
  // colliding code did not exist when the injections ran. Found by the
  // terminal session's red pen, 2026-08-08.
  const m = src.match(/wEl\.classList\.toggle\('on',([^)]+)\)/);
  assert.ok(m, 'the welcome is never toggled through its own element');
  const cond = m[1];
  assert.ok(/state === 'idle'/.test(cond), 'it can show while Jarvis works');
  assert.ok(/!showWait/.test(cond), 'it can cover the waiting banner');
  assert.ok(/!turnOpen/.test(cond), 'it can show with a turn in flight');
});

test('the welcome cannot be clicked and cannot take the stage', () => {
  const b = src.slice(src.indexOf('#welcome {'), src.indexOf('}', src.indexOf('#welcome {')));
  assert.ok(/pointer-events: none/.test(b), 'a decoration must not be pressable');
  assert.ok(/opacity: 0/.test(b), 'it must start invisible, not flash on load');
});

// --- what the top-bar rebuild was not allowed to drop ---------------------

for (const id of ['topbar-usage', 'usage-toggle', 'mute-toggle', 'clock']) {
  test(`the rebuilt top bar still carries #${id}`, () => {
    assert.ok(src.includes('id="' + id + '"'), '#' + id + ' vanished in the rebuild');
  });
}

test('the usage strip keeps its stale treatment and its hover title', () => {
  assert.ok(/#topbar-usage\.stale/.test(src), 'the stale dimming rule is gone');
  assert.ok(/id="topbar-usage" title=""/.test(src), 'the hover title hook is gone');
});

test('the old duplicated title is gone, not merely hidden', () => {
  // COMMENTS ARE STRIPPED FIRST, and the reason is that this test failed on
  // its own first run against correct code: the comment three lines above the
  // new brand block NAMES the title it replaced. That is the seventh time on
  // this project's record that grepping source punished the prose explaining
  // a decision — so the guard reads markup, never the reasoning beside it.
  const bar = src.slice(src.indexOf('<div id="topbar">'), src.indexOf('<div id="instrbar">'))
                 .replace(/<!--[\s\S]*?-->/g, '');
  assert.ok(!/J\.A\.R\.V\.I\.S/.test(bar), 'the replaced title is still in the bar');
  // a BARE `hidden` attribute only — `aria-hidden` is the ideas sheet's own,
  // and banning the substring would outlaw correct markup.
  assert.ok(!/(?<!aria-)\bhidden\b(?!=")/.test(bar) && !/\shidden>/.test(bar),
    'the old markup was hidden rather than removed');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
