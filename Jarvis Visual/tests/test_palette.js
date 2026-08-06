#!/usr/bin/env node
// Tests for the HUD palette -- the CSS custom property set in jarvis.html.
//
// Run:  ./tests/run-tests.sh   (from Jarvis Visual/)
//    or  node tests/test_palette.js
//
// WHY THIS FILE EXISTS:
// the palette extraction was started piecemeal (it arrived with the amber
// alert theme and the de-crowding pass) and sat half done for a day -- tokens
// defined in :root while raw hex literals kept being written beside them. Two
// conventions inside one file is worse than either end: the next person reads
// whichever half they land on. This file makes the finished half stay finished.
//
// It matters beyond tidiness. Serge's iPhone client will be native Swift, and
// Swift cannot read CSS -- so the palette's home has to be ONE place both
// surfaces can compile from, or they become two hand-kept lists of hex codes
// that drift. A literal re-introduced here is a literal that never reaches the
// phone.
//
// The load-bearing assertion is the LAST one: status colours must NOT be
// redefined under body.alert. Green means up, amber means waiting, red means
// broken -- in both moods. A status that repaints with the theme is a status
// that has stopped meaning anything, and the alert theme exists precisely so
// the frame can change around instruments that do not.

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const src = fs.readFileSync(path.join(__dirname, '..', 'jarvis.html'), 'utf8');

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log('ok   ' + name); passed++; }
  catch (e) { console.log('FAIL ' + name + '\n     ' + e.message); failed++; }
}

// ---- helpers ---------------------------------------------------------------

// The stylesheet only. Colour literals in the canvas code (the avatar, the
// vault graph) are deliberately out of scope for this pass -- they are drawn,
// not themed, and sweeping them in blind is how a refactor becomes visible.
const STYLE = src.slice(src.indexOf('<style>'), src.indexOf('</style>'));

function block(selector) {
  const at = STYLE.indexOf(selector);
  assert.ok(at !== -1, 'no ' + selector + ' block in the stylesheet');
  const open = STYLE.indexOf('{', at);
  return STYLE.slice(open + 1, STYLE.indexOf('\n  }', open));
}

const ROOT = block(':root {');
const ALERT = block('body.alert {');

// The status tokens, and the literal each one owns. Stated here rather than
// parsed out of the file on purpose: if someone changes a value, this test
// should make them come and change it here too, because that is the moment to
// ask whether the Swift side needs the same edit.
const STATUS = {
  '--ok':        '#00ffa8',
  '--ok-soft':   '#7ff0c8',
  '--warn':      '#ffb020',
  '--warn-soft': '#ffc75a',
  '--off':       '#6b5a1f',
  '--bad':       '#ff5f57',
};

// ---- the tokens exist and are defined once ---------------------------------

test('every status token is defined in :root', () => {
  for (const name of Object.keys(STATUS))
    assert.ok(new RegExp('^\\s*' + name + ':', 'm').test(ROOT),
              'missing token: ' + name);
});

test('each status token carries its own literal, exactly once', () => {
  for (const [name, hex] of Object.entries(STATUS)) {
    const line = ROOT.split('\n').filter(l => l.trim().startsWith(name + ':'));
    assert.strictEqual(line.length, 1, name + ' is defined ' + line.length + ' times');
    assert.ok(line[0].includes(hex), name + ' should be ' + hex);
  }
});

test('the rgb companions match their hex, so an rgba() cannot drift', () => {
  // rgba(var(--ok-soft-rgb), 0.5) has to be the same colour as var(--ok-soft),
  // or a border and the text it surrounds quietly disagree.
  const pairs = [['--ok-soft-rgb', '#7ff0c8'], ['--warn-soft-rgb', '#ffc75a']];
  for (const [name, hex] of pairs) {
    const m = ROOT.match(new RegExp(name + ':\\s*([0-9]+),\\s*([0-9]+),\\s*([0-9]+)'));
    assert.ok(m, 'missing or malformed token: ' + name);
    const got = [1, 2, 3].map(i => Number(m[i]));
    const want = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
    assert.deepStrictEqual(got, want, name + ' does not match ' + hex);
  }
});

// ---- no literal survives outside the definition ----------------------------

test('no status colour is written as a raw literal anywhere else in the CSS', () => {
  // This is the assertion that keeps the extraction finished. Comments are
  // stripped first: the bottom status bar carries a comment naming #6b5a1f and
  // quoting Serge on why "off" is amber, and punishing the prose that explains
  // a decision is a mistake this project has now made three times.
  const code = STYLE.replace(/\/\*[\s\S]*?\*\//g, '');
  for (const [name, hex] of Object.entries(STATUS)) {
    const uses = code.split(hex).length - 1;
    assert.strictEqual(uses, 1,
      hex + ' (' + name + ') appears ' + uses + ' times; it should appear only ' +
      'in its :root definition -- use var(' + name + ') instead');
  }
});

test('the tokens are actually referenced -- a palette nothing uses is dead code', () => {
  for (const name of Object.keys(STATUS)) {
    const uses = STYLE.split('var(' + name + ')').length - 1;
    assert.ok(uses >= 1, 'nothing uses var(' + name + ')');
  }
});

// ---- the doctrine ----------------------------------------------------------

test('the alert theme does NOT redefine any status colour', () => {
  // The load-bearing one. body.alert repaints the frame -- backgrounds, text,
  // the accent -- around instruments whose meaning must not move. If green
  // becomes an amber-tinted green while Jarvis is blocked on Serge, then the
  // one moment the page most needs to be readable is the moment its status
  // language changes.
  for (const name of Object.keys(STATUS))
    assert.ok(!new RegExp('^\\s*' + name + ':', 'm').test(ALERT),
              name + ' is overridden in body.alert -- status must not follow the mood');
});

test('the alert theme still overrides the frame tokens it is for', () => {
  // The mirror of the test above: proving status colours are absent is only
  // meaningful if the alert block is otherwise intact. An empty body.alert
  // would pass the previous test and ship a theme that does nothing.
  for (const name of ['--accent-rgb', '--bg-deep', '--text', '--sec'])
    assert.ok(new RegExp('^\\s*' + name + ':', 'm').test(ALERT),
              'body.alert no longer overrides ' + name);
});

// ---- the alert theme's ambers, reconciled 2026-08-06 ----------------------
// Serge chose UNIFORM in one word. Four near-identical ambers had been
// hand-written into the alert theme and the approval popup -- 255,176,32 at
// both 0.30 and 0.32, plus 255,190,80 and 255,180,60 -- differences that were
// accidents of editing rather than decisions. A token is the instrument that
// stops that, so these guard that it cannot happen again.

test('--warn-rgb is exactly --warn, not a fifth shade of amber', () => {
  const hex = (ROOT.match(/--warn:\s*#([0-9a-f]{6})/i) || [])[1];
  const rgb = (ROOT.match(/--warn-rgb:\s*([0-9]+),\s*([0-9]+),\s*([0-9]+)/) || []).slice(1);
  assert.ok(hex && rgb.length === 3, 'could not read --warn / --warn-rgb');
  const fromHex = [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16));
  assert.deepStrictEqual(rgb.map(Number), fromHex,
    '--warn-rgb (' + rgb + ') is not --warn (#' + hex + ') -- a token that lies is worse than a literal');
});

test('no raw amber literal survives in the approval popup or its pulse', () => {
  // The block is #approve-lost, and its pulse keyframes follow it. Bounded by
  // the keyframes' end rather than by a guessed next selector, so the region
  // genuinely covers what the test claims to cover.
  const from = STYLE.indexOf('#approve-lost {');
  const to = STYLE.indexOf('@keyframes approve-pulse');
  const end = STYLE.indexOf('}', STYLE.indexOf('50%', to));
  const region = STYLE.slice(from, end);
  assert.ok(from !== -1 && to > from && end > to,
            'could not locate the approval popup block');
  const raw = region.match(/rgba\(\s*2[0-9]{2}\s*,/g) || [];
  assert.deepStrictEqual(raw, [],
    'hand-written amber back in the popup: ' + raw.join(', '));
});

test('the waiting column and card read the SAME amber token', () => {
  // NARROWED after a first version failed a CORRECT page: it demanded
  // --warn-rgb on every waiting rule, which outlawed --warn-soft-rgb on the
  // step line -- a different token in the same family, and the right one
  // there. The property that matters is that NO waiting rule writes its own
  // amber by hand, not that they all read one particular token.
  const rules = STYLE.match(/\.bcol\.waiting[^\n]*rgba\([^)]*\)/g) || [];
  assert.ok(rules.length >= 2, 'expected the waiting column head and card');
  for (const r of rules)
    assert.ok(/var\(--warn(-soft)?-rgb\)/.test(r),
      'a waiting rule carries a literal amber: ' + r.trim());
});

test('the modal scrim is ONE token, repeated in every keyframe stop', () => {
  // box-shadow animates as a whole, so the backdrop must appear in all three
  // stops. Three hand-kept copies of one colour is what this token replaced --
  // and dropping it from a single stop strobes the entire page.
  const uses = STYLE.split('var(--scrim)').length - 1;
  assert.strictEqual(uses, 3,
    'the scrim appears ' + uses + ' times; it must be in the rule and both keyframe stops');
  assert.ok(!/rgba\(\s*4\s*,\s*8\s*,\s*16\s*,/.test(STYLE.replace(/--scrim:[^;]+;/, '')),
    'a hand-written scrim literal is back');
});

test('"off by choice" tan is one token, not three copies', () => {
  const uses = STYLE.split('var(--off-soft)').length - 1;
  assert.ok(uses >= 3, '--off-soft is used ' + uses + ' times; three rules should read it');
  assert.ok(!/rgba\(\s*190\s*,\s*175\s*,\s*110/.test(STYLE.replace(/--off-soft:[^;]+;/, '')),
    'a hand-written tan literal is back');
});

test('the new tokens are NOT redefined by the alert theme either', () => {
  // Same doctrine as the status colours: the scrim behind a modal and the
  // "deliberately off" tan mean the same thing in both moods.
  for (const name of ['--warn-rgb', '--scrim', '--off-soft'])
    assert.ok(!new RegExp('^\\s*' + name + ':', 'm').test(ALERT),
      name + ' is overridden in body.alert');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
