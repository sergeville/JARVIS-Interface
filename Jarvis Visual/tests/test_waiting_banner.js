#!/usr/bin/env node
// THE WAITING BANNER SAYS IT ONCE.
//
// Serge caught this on his own screen 2026-08-09 ~2:05 PM: the stage carried
// a small status strip reading WAITING FOR YOUR ANSWER and, directly beneath
// it, a banner whose own heading read "Waiting for your answer" again — the
// loudest text on the page, duplicated. The no-duplicates rule is the one the
// whole HUD is held to, and the biggest type on the page was breaking it.
//
// THE PROPERTY, so a future edit cannot quietly re-add it: exactly ONE place
// on the page renders that phrase, and it is the status strip in draw().
// The banner element carries the QUESTION and nothing else.
//
// These tests deliberately do NOT anchor on a first match anywhere in the
// file — this project has lost seven rounds to first-match guards that future
// code armed. The banner is sliced out by its own id and examined whole.

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const src = fs.readFileSync(path.join(__dirname, '..', 'jarvis.html'), 'utf8');

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log('ok   ' + name); passed++; }
  catch (e) { console.log('FAIL ' + name + '\n     ' + e.message); failed++; }
}

// ---- slice the banner element out of the real markup, by tag balance ------
function sliceEl(id) {
  const at = src.indexOf('id="' + id + '"');
  assert.ok(at !== -1, 'no element with id ' + id);
  let i = src.lastIndexOf('<div', at);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src.startsWith('<div', j)) depth++;
    else if (src.startsWith('</div>', j)) {
      if (--depth === 0) return src.slice(i, j + 6);
    }
  }
  throw new Error('unbalanced markup around ' + id);
}

const banner = sliceEl('waiting');

test('the phrase is rendered in exactly ONE place in the whole page', () => {
  // Prose is not a render site. Strip every comment form this file uses —
  // block, line and HTML — BEFORE counting, so a future note explaining the
  // rule cannot turn this test red for saying the words it is about.
  const code = src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/^\s*\/\/.*$/gm, '');
  const real = code.match(/waiting for your answer/gi) || [];
  assert.strictEqual(real.length, 1,
    'expected exactly one render site, found ' + real.length);
});

test('the one render site is the stage status strip', () => {
  assert.ok(/statusEl\.textContent\s*=\s*'WAITING FOR YOUR ANSWER'/.test(src),
    'the status strip no longer sets the waiting label');
});

test('the banner carries the question and no heading of its own', () => {
  assert.ok(/id="waiting-q"/.test(banner), 'the banner lost its question element');
  assert.ok(!/waiting-head/.test(banner), 'the banner grew a heading again');
  assert.ok(!/waiting for your answer/i.test(banner),
    'the banner is speaking the status strip\'s line');
});

test('no orphan #waiting-head rule or element survives anywhere', () => {
  assert.ok(!/waiting-head/.test(src), 'waiting-head is still referenced');
});

test('the dropped pulse animation left no orphan keyframes', () => {
  assert.ok(!/waitpulse/.test(src), 'waitpulse survived its only user');
});

test('the banner still shows only while idle with a question pending', () => {
  assert.ok(/const showWait = waitingQ && state === 'idle'/.test(src),
    'the showWait condition changed — the banner may now draw mid-turn');
});

console.log('\n' + passed + '/' + (passed + failed) + ' passed');
process.exit(failed ? 1 : 0);
