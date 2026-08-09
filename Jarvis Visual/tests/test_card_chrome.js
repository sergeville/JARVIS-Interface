#!/usr/bin/env node
// PHASE 8 — THE CHROME PORT.
//
// Run:  ./tests/run-tests.sh   (from Jarvis Visual/)
//    or  node tests/test_card_chrome.js
//
// WHY THIS FILE EXISTS, and it is not the usual "guard the new feature".
// Serge put the prototype and the live page side by side on 2026-08-08 and
// the plan had finished while the page still did not look like the reference.
// The mechanisms had all shipped; the CHROME had only ever been applied to a
// mockup. No phase owned the port, so nothing failed — it was simply never
// anyone's job. These tests make it someone's job.
//
// The three failures they exist to catch, each of which has already happened
// once on this project:
//
//   1. A CARD LEFT WEARING THE OLD LOOK. His own §5 standard is "you do one
//      fix and all the cards are changing at the same time", and the check
//      that it holds is cheap: change one line, every card must move. That
//      check FAILED on the mockup — the right column and the footer were
//      still on the old page while the left column wore the chrome — and
//      nobody had run it. Here it is run: every section inside a column must
//      sit in a .card, so a new section added without one goes red.
//   2. THE FILL GETTING LIT. The measurement says card body and page field
//      are THREE points of total RGB apart — all the depth in the concept is
//      drawn with LIGHT, never with surfaces. Two restyle passes ignored that
//      and lightened the fill, and the finding was written down in the same
//      file that then contradicted it. A gradient in the card background is
//      that mistake returning.
//   3. THE CHROME HARDCODED, KILLING THE FACES. The measured values are the
//      CIVILIAN ones. Written as literals, an ARMY card wears a blue hairline
//      over a sand accent, which quietly undoes a whole phase's work. The
//      chrome is tokenised, and every face must define the tokens.
//
// These read the stylesheet as text on purpose: what is under test IS the
// source-level claim "defined once, used everywhere". Rendering proves a
// picture; only the source proves there is exactly one place to change.

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const src = fs.readFileSync(path.join(__dirname, '..', 'jarvis.html'), 'utf8');

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log('ok   ' + name); passed++; }
  catch (e) { console.log('FAIL ' + name + '\n     ' + e.message); failed++; }
}

// COMMENTS ARE STRIPPED FIRST, and this is not fussiness — it is the eighth
// time on this project that grepping the source has punished the prose beside
// it. The comment above the chrome rule NAMES the literals it forbids, so any
// guard that greps raw source for those literals fails on correct code.
const css = (() => {
  const open = src.indexOf('<style');
  const close = src.indexOf('</style>');
  let s = src.slice(src.indexOf('>', open) + 1, close);
  s = s.replace(/\/\*[\s\S]*?\*\//g, '');            // CSS comments
  return s;
})();
const html = (() => {
  const start = src.indexOf('<body');
  let s = src.slice(start);
  return s.replace(/<!--[\s\S]*?-->/g, '');           // HTML comments
})();

// Slice a CSS rule body by selector, to its own closing brace — never a fixed
// character count. A test that goes red when a COMMENT grows is measuring the
// wrong thing, and one did.
function rule(selector) {
  const at = css.indexOf(selector);
  assert.ok(at !== -1, 'no rule for ' + selector);
  const open = css.indexOf('{', at);
  const end = css.indexOf('}', open);
  assert.ok(end !== -1, 'unterminated rule for ' + selector);
  return css.slice(open + 1, end);
}

// --- 1. ONE RULE, EVERY CARD ---------------------------------------------

test('the notch is defined exactly once', () => {
  const notches = (css.match(/clip-path:\s*polygon/g) || []).length;
  assert.strictEqual(notches, 1,
    'the card notch must live in ONE rule; found ' + notches +
    ' clip-path polygons — a second one is the chrome starting to drift');
});

test('the one rule covers the cards, the stage and the footer pods', () => {
  const sel = css.slice(css.indexOf('.card, #stage, #botbar > div'),
                        css.indexOf('.card, #stage, #botbar > div') + 40);
  assert.ok(sel.includes('.card'), 'cards not in the chrome rule');
  assert.ok(sel.includes('#stage'), 'the stage is a panel in the concept and must take the same rule');
  assert.ok(sel.includes('#botbar > div'), 'the footer pods must take the same rule');
});

test('every section inside a column sits in a card', () => {
  // The failure this catches: a new section added to a column without a
  // wrapper renders as a bare heading on open field, and nobody notices
  // because the page still "works".
  for (const col of ['left', 'right']) {
    const start = html.indexOf('<div id="' + col + '"');
    assert.ok(start !== -1, 'no #' + col);
    // walk to the matching close of the column
    let depth = 0, i = start, end = -1;
    const re = /<div\b|<\/div>/g;
    re.lastIndex = start;
    let m;
    while ((m = re.exec(html))) {
      if (m[0] === '</div>') { if (--depth === 0) { end = m.index; break; } }
      else depth++;
    }
    assert.ok(end !== -1, 'unbalanced markup in #' + col);
    const body = html.slice(start, end);

    // every .sec-title / #tasks-head in the column must have a .card ancestor
    const heads = [...body.matchAll(/class="sec-title"|id="tasks-head"/g)];
    assert.ok(heads.length > 0, 'no sections found in #' + col);
    for (const h of heads) {
      const before = body.slice(0, h.index);
      const opens = [...before.matchAll(/<div\b[^>]*>/g)].map(x => x[0]);
      const closes = (before.match(/<\/div>/g) || []).length;
      // reconstruct the open-tag stack at this point
      const stack = [];
      let ci = 0;
      const tags = [...before.matchAll(/<div\b[^>]*>|<\/div>/g)];
      for (const t of tags) {
        if (t[0] === '</div>') stack.pop(); else stack.push(t[0]);
      }
      const inCard = stack.some(t => /class="[^"]*\bcard\b/.test(t));
      assert.ok(inCard,
        'a section in #' + col + ' has no .card wrapper — it will render ' +
        'as a bare heading while every other card wears the chrome');
      void opens; void closes; void ci;
    }
  }
});

// --- 2. THE FILL IS FLAT, THE DEPTH IS LIGHT -----------------------------

test('the card fill is flat — no gradient lights the surface', () => {
  const body = rule('.card, #stage, #botbar > div');
  assert.ok(!/gradient/.test(body),
    'the card background carries a gradient. The concept holds body within ' +
    'THREE points of field everywhere: all its depth is a hairline and its ' +
    'halo over near-black. Lightening the fill pushes AWAY from the reference.');
});

test('the halo rides a filter, not a shadow on the clipped layer', () => {
  const after = rule('.card::after, #stage::after, #botbar > div::after');
  assert.ok(/filter:\s*drop-shadow/.test(after),
    'clip-path clips the border AND the outer box-shadow with the shape, so ' +
    'a notched card cannot carry its glow that way — it simply vanishes, ' +
    'which reads as "the glow is not working". drop-shadow is not clipped.');
});

test('the near-white lands on the corners the clip actually cuts', () => {
  // The mockup paired the peak with bottom-left/top-right, inherited from a
  // different notch set. Here the clip cuts the TOP two corners, so a peak
  // drawn at the bottom is a bright diagonal across a square corner.
  const chrome = rule('.card, #stage, #botbar > div');
  const after = rule('.card::after, #stage::after, #botbar > div::after');
  const cutsTopLeft = /polygon\(\s*14px 0/.test(chrome);
  const cutsTopRight = /calc\(100% - 14px\) 0/.test(chrome);
  assert.ok(cutsTopLeft && cutsTopRight, 'the clip no longer cuts both top corners');
  assert.ok(/top left/.test(after) && /top right/.test(after),
    'the peak must be painted at the two corners the clip-path cuts');
  assert.ok(!/bottom/.test(after),
    'a peak painted at a square corner draws a bright diagonal across nothing');
});

test('the hairline RUNS dull — the peak is spent only on the corners', () => {
  const chrome = rule('.card, #stage, #botbar > div');
  assert.ok(/--chrome-line/.test(chrome),
    'the border must use the dull run token');
  assert.ok(!/--chrome-peak/.test(chrome),
    'the PEAK on a long edge reads as neon, not as machined metal — ' +
    '#6eebfa was measured at the notch vertices only');
});

test('interior frames run dimmer than the outer cards', () => {
  // ⚠ LAST match, not first. There is an older #stage rule further up the
  // sheet, and the cascade obeys the LAST block — a first-match anchor here
  // reads the wrong rule and reports the wrong answer. This is the same trap
  // that has now cost this project eight separate reds; it went red here on
  // its first run, against correct code.
  const at = css.lastIndexOf('#stage { border-color');
  assert.ok(at !== -1, 'no stage chrome override');
  const stage = css.slice(css.indexOf('{', at) + 1, css.indexOf('}', at));
  const alpha = /0\.(\d+)\)/.exec(stage);
  assert.ok(alpha, 'the stage border carries no alpha');
  assert.ok(Number('0.' + alpha[1]) < 0.5,
    'the concept\'s interior frames run at ~0.2 alpha; a stage border as ' +
    'bright as the columns around it shouts over them');
});

// --- 3. THE CHROME IS TOKENISED, SO THE FACES SURVIVE --------------------

test('the chrome carries no hardcoded colour', () => {
  const parts = [rule('.card, #stage, #botbar > div'),
                 rule('.card::after, #stage::after, #botbar > div::after')].join('\n');
  const hex = parts.match(/#[0-9a-fA-F]{3,8}\b/g) || [];
  assert.deepStrictEqual(hex, [],
    'hardcoded hex in the chrome: ' + hex.join(', ') + '. The measured values ' +
    'are the CIVILIAN ones — written as literals, an ARMY card wears a blue ' +
    'hairline over a sand accent and a whole phase quietly comes undone.');
  const rgbLit = parts.match(/rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+/g) || [];
  assert.deepStrictEqual(rgbLit, [],
    'literal rgb in the chrome: ' + rgbLit.join(' | '));
});

test('every face defines every chrome token', () => {
  // Derived from the CSS, never from a hand-typed list in this file. A
  // cross-check with one hand-typed side is two copies of the same claim,
  // and that exact mistake made an older test go red for the wrong reason.
  const faces = [...css.matchAll(/body\.face-([a-z]+)\s*\{/g)].map(m => m[1]);
  assert.ok(faces.length >= 4, 'expected four faces, found ' + faces.length);
  for (const f of faces) {
    const body = rule('body.face-' + f + ' {');
    for (const tok of ['--bg-card', '--chrome-line', '--chrome-peak']) {
      assert.ok(body.includes(tok),
        'face ' + f + ' does not define ' + tok + ' — its cards fall back to ' +
        'another face\'s chrome, which is the drift the tokens exist to stop');
    }
  }
});

test('no two faces share a chrome line colour', () => {
  const faces = [...css.matchAll(/body\.face-([a-z]+)\s*\{/g)].map(m => m[1]);
  const seen = new Map();
  for (const f of faces) {
    const line = /--chrome-line:\s*([^;]+);/.exec(rule('body.face-' + f + ' {'));
    assert.ok(line, 'face ' + f + ' has no --chrome-line');
    const v = line[1].trim();
    assert.ok(!seen.has(v),
      'faces ' + seen.get(v) + ' and ' + f + ' share a hairline — two faces ' +
      'that render alike are one face with two names');
    seen.set(v, f);
  }
});

// --- 4. THE HEADER STRIP -------------------------------------------------

test('the header strip is separated by a hairline, not by a lighter fill', () => {
  const head = rule('.card > .sec-title, .card > #tasks-head');
  assert.ok(/border-bottom/.test(head),
    'the concept puts the title on the SAME fill as the body, divided by a rule');
  assert.ok(!/background/.test(head),
    'a lighter header strip is the flat-fill finding broken in a new place');
});

test('the strip spans the card padding', () => {
  const head = rule('.card > .sec-title, .card > #tasks-head');
  assert.ok(/margin:\s*-/.test(head),
    'without negative margins the underline stops short of the frame and ' +
    'reads as an underlined word rather than as a header row');
});

test('the header rule reaches inside cards only', () => {
  const at = css.indexOf('.card > .sec-title');
  assert.ok(at !== -1, 'no scoped header rule');
  const sel = css.slice(css.lastIndexOf('}', at) + 1, css.indexOf('{', at));
  assert.ok(sel.includes('.card >'),
    'an unscoped .sec-title rule restyles headings that are not on a card');
});

// --- 5. THE READINGS THAT CAME DOWN --------------------------------------
//
// Serge, 2026-08-09: "yeah, move them." The health ring, the ports row and
// the page age left the left column for the footer pods. MOVED is the whole
// claim — his decision 11 forbids the page saying the same thing twice, and
// a copied reading is also a second place for one number to go stale while
// the other stays right, which is worse than either being wrong.

for (const id of ['health', 'health-ring', 'health-word', 'health-sub',
                  'ports-row', 'page-age']) {
  test('#' + id + ' exists exactly once in the markup', () => {
    const n = (html.match(new RegExp('id="' + id + '"', 'g')) || []).length;
    assert.strictEqual(n, 1,
      n === 0 ? '#' + id + ' vanished in the move — the reading is gone, not moved'
              : '#' + id + ' appears ' + n + ' times: it was COPIED, not moved. ' +
                'Two elements with one id also means getElementById updates ' +
                'the first and leaves the second frozen on screen.');
  });
}

test('the moved readings live in the footer now', () => {
  const bot = html.slice(html.indexOf('<div id="botbar">'));
  const end = bot.indexOf('<!-- Floating permission card');
  const foot = bot.slice(0, end === -1 ? bot.length : end);
  for (const id of ['health', 'ports-row', 'page-age']) {
    assert.ok(foot.includes('id="' + id + '"'),
      '#' + id + ' is not in the footer — the move did not land');
  }
});

test('the left column no longer claims a System Status card', () => {
  const left = html.slice(html.indexOf('<div id="left"'), html.indexOf('<div id="stage"'));
  assert.ok(!/System Status/.test(left),
    'a heading left behind after its content moved is the worst of both: ' +
    'an empty card that looks like a broken reading');
});

test('the footer sizing is scoped to the pod, not to the ring itself', () => {
  // The ring is 44px because that is its size in a column. Shrinking
  // #health-ring globally would also shrink it anywhere it is put back.
  const at = css.indexOf('#pod-health #health-ring');
  assert.ok(at !== -1, 'no pod-scoped ring size');
  const bare = /\n\s*#health-ring\s*\{[^}]*width:\s*26px/.test(css);
  assert.ok(!bare, 'the ring was resized globally rather than inside the pod');
});

test('the ports row can still be put back in a column', () => {
  // The flattening (no top rule, no wrap, no top margin) is what a footer
  // needs and what a column does not. It belongs in the pod's rule, so the
  // row itself survives being moved back.
  const row = rule('.ports-row {');
  assert.ok(/border-top/.test(row) && /flex-wrap:\s*wrap/.test(row),
    'the column behaviour was stripped from .ports-row itself — the row can ' +
    'now only ever live in a footer');
});

// -------------------------------------------------------------------------

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
