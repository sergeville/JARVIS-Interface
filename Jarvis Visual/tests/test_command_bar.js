#!/usr/bin/env node
// PHASE 3 — THE COMMAND BAR'S STRUCTURAL MOVE.
//
// The plan is explicit about why this file has to exist: the page's existing
// tests extract JS by SOURCE-SLICING and are position-blind, so "the old suite
// still passes" proves the script is untouched and proves nothing at all
// about the relocation. What can break here is placement and wiring, and both
// are invisible to every other test in the suite.
//
// The move-intact checklist is the plan's, and it names the behaviours that
// live in exactly this code — the ones a relocation could silently destroy.
// Each gets an assertion here AND a line in the live walkthrough, because a
// source assertion cannot prove a button works in his hands.

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const src = fs.readFileSync(path.join(__dirname, '..', 'jarvis.html'), 'utf8');

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log('ok   ' + name); passed++; }
  catch (e) { console.log('FAIL ' + name + '\n     ' + e.message); failed++; }
}
const at = (needle) => src.indexOf(needle);

// --- PLACEMENT: the thing no other test in this suite can see -------------

test('the command group is OUT of the right column', () => {
  const rightStart = at('<div id="right" class="panel">');
  const mainEnd = at('<div id="cmdbar">');
  const right = src.slice(rightStart, mainEnd);
  for (const id of ['id="typed"', 'id="send"', 'id="attach"', 'id="micline"', 'id="cmd-hint"']) {
    assert.ok(!right.includes(id), id + ' is still inside the right column');
  }
});

test('the bar sits BELOW #main and ABOVE the status bar', () => {
  const mainAt = at('<div id="main">');
  const barAt = at('<div id="cmdbar">');
  const botAt = at('<div id="botbar">');
  assert.ok(mainAt !== -1 && barAt !== -1 && botAt !== -1, 'a landmark is missing');
  assert.ok(mainAt < barAt, 'the bar is above the main grid');
  assert.ok(barAt < botAt, 'the bar is below the status bar');
});

test('the bar is OUTSIDE the main grid, or it would take a column', () => {
  // #main is a three-column grid; a fourth child would become a grid item and
  // land in a column rather than spanning the page.
  // COUNT THE NESTING, do not look for a nearby closing tag. The first
  // version asked whether a `</div>` appeared before the bar, which is
  // trivially true anywhere on this page — it passed with the bar left
  // inside the grid, which is the one thing it was written to catch.
  const from = at('<div id="main">');
  const to = at('<div id="cmdbar">');
  const between = src.slice(from, to);
  const opens = (between.match(/<div\b/g) || []).length;
  const closes = (between.match(/<\/div>/g) || []).length;
  assert.strictEqual(opens, closes,
    'the bar sits ' + (opens - closes) + ' level(s) deep inside the main grid, ' +
    'so it would become a grid item instead of spanning the page');
});

test('each moved element appears EXACTLY once — no copy left behind', () => {
  for (const id of ['id="typed"', 'id="send"', 'id="attach"',
                    'id="micline"', 'id="cmd-hint"', 'id="cmd-sec"']) {
    const n = src.split(id).length - 1;
    assert.strictEqual(n, 1, id + ' appears ' + n + ' times — a duplicate id breaks getElementById');
  }
});

test('the bottom-pinning trick did not travel with the group', () => {
  const i = at('#cmd-sec {');
  assert.ok(!/margin-top:\s*auto/.test(src.slice(i, src.indexOf('}', i))),
    'margin-top:auto only made sense inside the right column');
});

test('the placeholder is the one the plan specifies', () => {
  assert.ok(/placeholder="How can I assist you today, Serge\?"/.test(src),
    'the placeholder did not change with the move');
});

// --- WIRING: every reference must be position-independent -----------------

test('nothing reaches these elements through a parent selector', () => {
  // A descendant selector like `#right #typed` would have silently stopped
  // matching the moment the element moved — and CSS fails silently.
  for (const bad of ['#right #typed', '#right #cmd', '#right #attach',
                     '#right #micline', '#right #send']) {
    assert.ok(!src.includes(bad), bad + ' would have broken on the move');
  }
});

test('every binding is by id or by element reference', () => {
  // Only the elements the SCRIPT drives. `cmd-hint` is static markup styled
  // by id and read by nothing — the first version of this test demanded a
  // binding for it and went red against correct code. A test that invents a
  // requirement is worse than no test: it pushes you to add a reference
  // nothing needs, just to make it green.
  for (const id of ['typed', 'send', 'attach', 'micline']) {
    const byId = src.includes("getElementById('" + id + "')");
    const byQuery = new RegExp("querySelector\\('#" + id + "'\\)").test(src);
    assert.ok(byId || byQuery, id + ' is not reached by id anywhere');
  }
});

test('the static members of the group are styled by ID alone', () => {
  // What actually matters for the ones the script never touches: their CSS
  // must not depend on where they sit, or the move breaks them silently.
  for (const id of ['cmd-hint', 'cmd-foot']) {
    assert.ok(src.includes('#' + id + ' {') || src.includes('#' + id + ' '),
      '#' + id + ' has no rule of its own');
    assert.ok(!new RegExp('#(right|main|left)[^{]*#' + id).test(src),
      '#' + id + ' is styled through a parent and would break on the move');
  }
});

test('the Right-Command focus guard is position-independent', () => {
  // The plan calls this out by name: it compares the ACTIVE ELEMENT, which
  // knows nothing about where the input sits in the document.
  assert.ok(/document\.activeElement !== typedEl/.test(src),
    'the focus guard no longer compares the active element');
});

// --- THE MOVE-INTACT CHECKLIST -------------------------------------------
// Each of these lives in the code that moved. A source assertion here, and a
// line in the walkthrough record, because neither alone is proof.

// SLICE THE FUNCTION, do not grep the file. The terminal session's red pen,
// 2026-08-08: the first versions of the next two tests asserted that an
// IDENTIFIER appears anywhere in 4,000 lines. Gut the behaviour and both stay
// green, because the name survives somewhere else. And these are exactly the
// two behaviours nobody has walked through in Serge's hands — so a
// word-existence assertion left them covered by nothing at all.
function slice(name) {
  const start = src.indexOf('function ' + name + '(');
  assert.ok(start !== -1, 'no function ' + name);
  let i = src.indexOf('{', start), depth = 0, end = -1;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}' && --depth === 0) { end = j + 1; break; }
  }
  return src.slice(start, end);
}

test('images ride a SPOKEN turn — asserted INSIDE release(), where it happens', () => {
  const body = slice('release');
  assert.ok(/attached\.length && serverVoiceImage/.test(body),
    'the spoken turn no longer checks for attached images');
  assert.ok(/msg\.images = take\.map/.test(body),
    'the audio message does not carry the images');
  assert.ok(/msg\.image = msg\.images\[0\]/.test(body),
    'the one-image shape for an old server is gone from the spoken path');
  assert.ok(/id="attach"/.test(src), 'the attach queue has no home in the new bar');
});

test('the old-server degradation ladder survived', () => {
  // The ASSIGNMENT from the payload, not the identifier. The first version
  // matched the declaration, so deleting the line that actually reads the
  // server's answer left it green — and an old server would then look
  // exactly like a capable one, which is the whole failure this ladder
  // exists to prevent.
  assert.ok(/serverVoiceImage = !!d\.voice_image;/.test(src),
    'the voice-image capability is never read from the payload');
  assert.ok(/serverMultiImage = !!d\.multi_image;/.test(src),
    'the multi-image capability is never read from the payload');
});

test('tap-vs-hold survived: a sub-250 ms press is interrupt-only', () => {
  assert.ok(/Date\.now\(\) - pressT < 250/.test(src), 'the tap rule is gone');
});

test('interrupt suppression under a pending approval survived — EVERY site', () => {
  // There are FOUR places that send an interrupt, and the first version of
  // this test matched whichever one it found first. Deleting the guard from
  // press() — the one that moved — left it green because three others still
  // carried it. The first-match trap, in a test guarding four copies of one
  // rule. So: every interrupt send must be gated, and the count is asserted
  // too, or a deleted site would simply stop being counted.
  const sends = [...src.matchAll(/ws\.send\(JSON\.stringify\(\{type: 'interrupt'\}\)\)/g)];
  assert.ok(sends.length >= 4, 'an interrupt site vanished — ' + sends.length + ' left');
  for (const m of sends) {
    const before = src.slice(Math.max(0, m.index - 200), m.index);
    assert.ok(/approvalId === null/.test(before),
      'an interrupt at index ' + m.index + ' can kill a pending permission');
  }
});

test('terminal-line routing survived — asserted INSIDE sendTyped()', () => {
  // Same correction as the images test above: `/lineAlive/` anywhere in the
  // file proved nothing. The routing decision has to live in the function
  // that sends, or a typed message goes to the wrong place while the
  // identifier sits happily in some unrelated handler.
  const body = slice('sendTyped');
  assert.ok(/lineAlive/.test(body),
    'the typed-send path no longer branches on the terminal line');
  assert.ok(/if \(!lineAlive\)/.test(body),
    'the stand-down branch is gone from the send path');
});

test('press() still stands down while the terminal line owns the key', () => {
  const body = slice('press');
  assert.ok(/if \(capturing \|\| lineAlive\) return;/.test(body),
    'the browser would grab a microphone the terminal line owns');
});

test('the mic line still renders from its own function', () => {
  assert.ok(/renderMicLine\(\)/.test(src), 'the mic status line is no longer drawn');
});

// --- THE WAVEFORM: one microphone, one story -----------------------------

test('the waveform is FED the stage\'s own level, never its own', () => {
  assert.ok(/drawCmdWave\(smooth\)/.test(src),
    'the waveform is not fed the smoothed level the ring uses');
  const i = at('function drawCmdWave(');
  const body = src.slice(i, src.indexOf('\n}', i));
  assert.ok(!/level\(\)|micLevel|analyser/.test(body),
    'the waveform reads the microphone itself — two meters, two stories');
});

test('the waveform is right-anchored, like every other sparkline here', () => {
  const i = at('function drawCmdWave(');
  const body = src.slice(i, src.indexOf('\n}', i));
  assert.ok(/W2 - \(cmdWaveHist\.length - i\)/.test(body),
    'the newest sample does not sit at a fixed edge');
});

test('the waveform takes its colour from the FACE, not from a literal', () => {
  const i = at('function drawCmdWave(');
  const body = src.slice(i, src.indexOf('\n}', i));
  // The accent is CACHED now (one read at applyFace instead of one per
  // animation frame), so the property to assert moved: the drawing must use
  // the cache, and the cache must be refreshed by the face dial.
  assert.ok(/ACCENT_RGB/.test(body), 'the waveform ignores the face dial');
  assert.ok(/refreshAccent\(\);/.test(src) && /ACCENT_RGB = getComputedStyle/.test(src),
    'the cached accent is never refreshed, so it would freeze on one face');
  assert.ok(!/#[0-9a-f]{6}/i.test(body), 'a colour literal would survive every face');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
