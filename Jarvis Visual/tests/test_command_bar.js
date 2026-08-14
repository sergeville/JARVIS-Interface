#!/usr/bin/env node
// THE COMMAND GROUP'S PLACEMENT — and the talk pill it is now separate from.
//
// HISTORY, because this file has asserted two opposite layouts and the second
// one is not a bug fix. Phase 3 moved the group OUT of the right column into a
// full-width strip, and Serge approved that. On 2026-08-09 he put the concept
// and the live page side by side and asked why we were not simply doing what
// the picture does — and the picture splits the two ways in rather than
// merging them: TALKING is a pill inside the stage with a real mic roundel
// between two waveforms, TYPING is an ordinary card in the right column. He
// chose the picture. So the group moved back, and these placement tests were
// INVERTED on his word rather than deleted.
//
// The reason this file has to exist at all is unchanged: the page's other
// tests extract JS by SOURCE-SLICING and are position-blind, so "the old suite
// still passes" proves the script is untouched and proves nothing about where
// the markup sits. What can break here is placement and wiring.
//
// The move-intact checklist below is the plan's, and it names the behaviours
// that live in exactly this code — the ones a relocation could silently
// destroy. It survives the second move unchanged, because those behaviours
// never depended on the layout either time.

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

// The whole @keyframes block, by brace depth — a keyframes rule contains
// nested blocks, so the first closing brace is never the end of it.
function kfBlock(name = 'tkripple') {
  const i = src.indexOf('@keyframes ' + name);
  assert.ok(i !== -1, 'no @keyframes ' + name);
  let depth = 0;
  for (let j = src.indexOf('{', i); j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}' && --depth === 0) return src.slice(i, j + 1);
  }
  throw new Error('@keyframes ' + name + ' never closes');
}

// --- PLACEMENT: the thing no other test in this suite can see -------------

// The right column, sliced by nesting depth rather than by looking for the
// next closing tag — the column contains many nested divs, so "the first
// </div> after it" is nowhere near the end of it.
function rightColumn() {
  const start = src.indexOf('<div id="right" class="panel">');
  assert.ok(start !== -1, 'the right column is gone');
  let depth = 0;
  for (let j = start; j < src.length; j++) {
    if (src.startsWith('<div', j)) depth++;
    else if (src.startsWith('</div>', j)) {
      if (--depth === 0) return src.slice(start, j + 6);
    }
  }
  throw new Error('the right column never closes');
}

test('the command group is INSIDE the right column, as the concept draws it', () => {
  const right = rightColumn();
  for (const id of ['id="cmd-sec"', 'id="typed"', 'id="send"', 'id="attach"',
                    'id="micline"', 'id="cmd-hint"']) {
    assert.ok(right.includes(id), id + ' is not in the right column');
  }
});

test('the full-width strip is GONE — not left behind as a second home', () => {
  assert.ok(!src.includes('id="cmdbar"'),
    'the Phase 3 strip is still in the page; two homes means a duplicate id');
});

test('the group is the LAST card in the column — the way in sits under the state', () => {
  const right = rightColumn();
  const cards = [...right.matchAll(/id="(cmd-sec|tasks|sessions|mail-sec|ideas-sec|avcard)"/g)];
  assert.ok(cards.length >= 2, 'the column lost its cards');
  assert.strictEqual(cards[cards.length - 1][1], 'cmd-sec',
    'the command card is not last — the concept puts it at the foot of the column');
});

test('the group is a real card, so the chrome reaches it like every other', () => {
  const right = rightColumn();
  assert.ok(/<div id="cmd-sec" class="card">/.test(right),
    'the command group is not a .card — Phase 8 chrome would skip it');
  const head = right.slice(right.indexOf('id="cmd-sec"'));
  assert.ok(/<div class="sec-title"[^>]*>Command Input<\/div>/.test(head),
    'the card has no header strip of its own');
});

test('each moved element appears EXACTLY once — no copy left behind', () => {
  for (const id of ['id="typed"', 'id="send"', 'id="attach"',
                    'id="micline"', 'id="cmd-hint"', 'id="cmd-sec"']) {
    const n = src.split(id).length - 1;
    assert.strictEqual(n, 1, id + ' appears ' + n + ' times — a duplicate id breaks getElementById');
  }
});

test('the bottom-pinning trick came BACK with the group', () => {
  // The exact inverse of what this test asserted under Phase 3, and
  // deliberately so: inside the right column `margin-top: auto` is what
  // pushes the card to the foot of the column, which is where the concept
  // puts it. In the full-width strip it meant nothing, so it was removed.
  const i = at('#cmd-sec {');
  assert.ok(i !== -1, '#cmd-sec has no rule of its own');
  assert.ok(/margin-top:\s*auto/.test(src.slice(i, src.indexOf('}', i))),
    'the card is not pinned to the foot of the column');
});

test('the placeholder is the concept\'s', () => {
  assert.ok(/placeholder="Type a command or question&#8230;"/.test(src),
    'the placeholder is not the one the reference card carries');
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

test('the Right-Command focus guard is position-independent — BOTH key handlers', () => {
  // The plan calls this out by name: it compares the ACTIVE ELEMENT, which
  // knows nothing about where the input sits in the document.
  //
  // ⚠ THIS TEST WAS GREEN ON PROSE UNTIL 2026-08-09. It asserted the string
  // `document.activeElement !== typedEl`, and the ONLY place that string ever
  // appeared in this page was the comment above the Phase 3 markup explaining
  // the guard. The real guard is spelled `=== typedEl` with an early return.
  // Deleting that comment during the move turned the test red while the code
  // was untouched — which is how the fake was found. Ninth time on this
  // record that grepping source has measured the prose beside it.
  // So: assert the guard INSIDE each handler, and require both.
  const guards = [...src.matchAll(/e\.code !== 'MetaRight'[^\n]*\n/g)];
  assert.strictEqual(guards.length, 2,
    'expected the keydown and keyup guards, found ' + guards.length);
  for (const g of guards) {
    assert.ok(/document\.activeElement === typedEl\) return;/.test(g[0]),
      'a Right-Command handler no longer stands down while he is typing');
  }
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

test('the waveform is anchored AT THE MICROPHONE and the two strips mirror', () => {
  const i = at('function drawCmdWave(');
  const body = src.slice(i, src.indexOf('\n}\n', i));
  assert.ok(/w\.out === 'left' \? W2 - 1 - age \* 3 : 1 \+ age \* 3/.test(body),
    'the newest sample no longer sits against the roundel on both sides');
  assert.ok(/const age = cmdWaveHist\.length - 1 - i/.test(body),
    'the age of a sample is not what places it');
});

test('both strips read ONE history — not a buffer each', () => {
  const i = at('function drawCmdWave(');
  const body = src.slice(i, src.indexOf('\n}\n', i));
  const pushes = (body.match(/cmdWaveHist\.push\(/g) || []).length;
  assert.strictEqual(pushes, 1,
    'the level is pushed ' + pushes + ' times — two buffers drift apart');
  assert.ok(/for \(const w of cmdWaves\)/.test(body),
    'the strips are not drawn from one loop over one list');
});

// --- THE TALK PILL: the microphone the eye lands on -----------------------

test('the pill carries a mic roundel between two waveform strips', () => {
  const start = src.indexOf('<button id="talk">');
  assert.ok(start !== -1, 'the talk button is gone');
  const pill = src.slice(start, src.indexOf('</button>', start));
  const order = [...pill.matchAll(/id="(tk-wave-l|tk-mic|tk-wave-r)"/g)].map(m => m[1]);
  assert.deepStrictEqual(order, ['tk-wave-l', 'tk-mic', 'tk-wave-r'],
    'the roundel is not centred between the two strips');
  assert.strictEqual((pill.match(/class="tk-label"/g) || []).length, 2,
    'the pill lost one of its two labels');
});

test('nothing inside the pill is its own pointer target', () => {
  // A child swallowing a pointerdown is a second mic path that carries none
  // of the rules press()/release() enforce — tap-vs-hold, interrupt
  // suppression, the terminal-line stand-down.
  assert.ok(/#talk > \* \{ pointer-events: none; \}/.test(src),
    'a child of the talk button can take the press');
});

test('NOTHING rebuilds the pill\'s markup — its structure is not state', () => {
  // ⚠ THE BUG THIS EXISTS FOR, found by rendering the running page and by
  // nothing else. The signals poll ran `talkBtn.innerHTML = '…'` at 15 Hz to
  // swap the wording when the terminal line is up. The instant the pill grew
  // a roundel and two canvases, that line deleted them on the next poll —
  // and SILENTLY, because the draw loop kept writing into canvas elements
  // that were no longer in the document. No error, no red test, just an
  // empty pill. Structure is markup; only the WORDS may be state.
  // Comments stripped FIRST. The comment directly above names the very
  // expression it forbids, and the first run of this test went red on its
  // own prose — the third time in one afternoon. Measure code, not writing.
  const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  assert.ok(!/talkBtn\.innerHTML/.test(code),
    'something rebuilds the talk button — the roundel and canvases will be wiped');
  const l = src.match(/tkL\.textContent = lineAlive \? '([^']*)' : '([^']*)'/);
  const r = src.match(/tkR\.textContent = lineAlive \? '([^']*)'/);
  assert.ok(l && r, 'the pill no longer swaps its wording for the terminal line');
});

test('the canvases the draw loop holds are the ones in the document', () => {
  // The same failure by another route: if the strips were re-created, the
  // cached references would go on being drawn into forever, off-screen.
  assert.ok(/const cmdWaves = \[/.test(src), 'the strip list is gone');
  const i = src.indexOf('const cmdWaves = [');
  const decl = src.slice(i, src.indexOf('];', i));
  assert.ok(/getElementById\('tk-wave-l'\)/.test(decl)
         && /getElementById\('tk-wave-r'\)/.test(decl),
    'the strips are not the two in the pill');
  assert.strictEqual((src.match(/cmdWaves = /g) || []).length, 1,
    'the strip list is reassigned somewhere — a stale reference draws nowhere');
});

test('the roundel glows from the SAME level the strips draw — one reading', () => {
  // Serge, 2026-08-09: "the mic should glow in the same thing, in the same
  // time too." The property that makes that true is not "it glows" — it is
  // that the glow is driven by drawCmdWave's own argument, so the roundel
  // and the two strips can never be a frame or a source apart.
  const i = at('function drawCmdWave(');
  const body = src.slice(i, src.indexOf('\n}\n', i));
  assert.ok(/tkMic\.style\.setProperty\('--lv', q\)/.test(body),
    'the roundel is not driven from inside the waveform draw');
  assert.ok(/lv \* 3/.test(body), 'the glow does not come from the passed level');
  assert.ok(!/level\(\)|micLevel|analyser/.test(body),
    'the roundel reads the microphone itself — a second source, a second story');
  // Injection found this hole: `if (false)` disabled the whole glow and every
  // assertion above still passed, because the CODE was all still there. The
  // guard has to be the element's existence and nothing else.
  assert.ok(/if \(tkMic\) \{/.test(body),
    'the glow block is guarded by something other than the element existing');
});

test('the glow is written only when it CHANGES', () => {
  // This runs at 60 fps. An unquantised level never repeats, so the guard
  // would never hold and a style write would land on every frame forever.
  const i = at('function drawCmdWave(');
  const body = src.slice(i, src.indexOf('\n}\n', i));
  assert.ok(/Math\.round\(/.test(body), 'the level is not quantised before the write');
  assert.ok(/if \(q !== lastMicLv\)/.test(body), 'the write is not guarded on change');
});

test('open-microphone and loudness stay TWO signals, not one', () => {
  // A lit roundel in a silent room must still mean "listening". If `hot` only
  // changed the level, holding the key in silence would look like nothing.
  const i = at('#talk.hot #tk-mic {');
  const rule = src.slice(i, src.indexOf('}', i));
  assert.ok(/border-color: rgba\(var\(--accent-rgb\), 1\)/.test(rule),
    'holding the key no longer raises the floor on its own');
  // Injection found this hole too: gutting the box-shadow left `var(--lv)`
  // in the background line, so a whole-rule search still passed while the
  // halo — the part he can actually see across the room — stopped moving.
  // Assert the SHADOW carries the level, not merely the rule.
  const shadow = rule.slice(rule.indexOf('box-shadow'));
  assert.ok(/var\(--lv\)/.test(shadow),
    'the halo stops following his voice while the microphone is open');
});

test('the ripple carries the level on the WRAPPER, never inside the keyframes', () => {
  // Serge, 2026-08-09 ~5:10 PM, on the halo alone: he expected "a round
  // circle, bigger, that goes away" — a ring travelling outward.
  //
  // The property that matters is not that a ring exists. A custom property
  // read INSIDE an @keyframes block is not reliably re-read while the
  // animation is already running, so the ripple would have been frozen at
  // whatever the level was when it started — moving, and lying. The
  // keyframes are therefore constant and the wrapper's opacity carries his
  // voice; opacity multiplies down the tree, so silence hides the rings
  // while the animation keeps turning underneath and never restarts.
  // The WHOLE block. This used to stop at the first closing brace, which is
  // the end of the 0% step — so a `var(--lv)` added to any later keyframe
  // walked straight past the guard. Injection found it.
  const kf = kfBlock();
  assert.ok(kf.length > 10, 'the ripple keyframes are gone');
  assert.ok(!/var\(--lv\)/.test(kf),
    'the level is read inside the keyframes — the ripple will freeze mid-flight');
  const wrap = src.slice(src.indexOf('#tk-rings {'), src.indexOf('}', src.indexOf('#tk-rings {')));
  assert.ok(/opacity:\s*var\(--lv\)/.test(wrap),
    'the ripple does not follow his voice at all');
});

test('the ripple is BORN AT THE CENTRE and travels past the roundel', () => {
  // Serge, 2026-08-09 ~5:20 PM: the first version started at scale 1 — the
  // roundel's own rim — so the ring looked like it peeled off the border
  // instead of coming out of the microphone. "Started in the middle, wider."
  // Balance the braces. Slicing at the first `}` newline stopped at the end
  // of the 0% step, so the test reported the ripple had "lost its scales"
  // while both were sitting right there — a test lying about what it read.
  const kf = kfBlock();
  // ANCHOR THE STEP, do not match a substring of another one. `0%` also
  // matches the tail of `100%`, so the first version of this test read the
  // LAST keyframe as the first and pronounced a hard-popping ring healthy.
  // Injection caught it; the assertions were reading the wrong line.
  const start = /(?:^|\n)\s*0%\s*\{ transform: scale\(([\d.]+)\)/.exec(kf);
  const end = /(?:^|\n)\s*100%\s*\{ transform: scale\(([\d.]+)\)/.exec(kf);
  assert.ok(start && end, 'the ripple lost its start or end scale');
  assert.ok(parseFloat(start[1]) < 0.5,
    'the ring starts at ' + start[1] + ' — that is the rim, not the middle');
  assert.ok(parseFloat(end[1]) > 2.4,
    'the ring only reaches ' + end[1] + ' — it does not travel past the roundel');
  assert.ok(/(?:^|\n)\s*0%\s*\{[^}]*opacity: 0;/.test(kf),
    'the ring pops into existence as a hard dot in the middle of the icon');
});

test('there are TWO rings, offset, so the ripple reads as continuous', () => {
  const start = src.indexOf('<span id="tk-rings">');
  assert.ok(start !== -1, 'the ripple wrapper is gone from the markup');
  const wrap = src.slice(start, src.indexOf('</span></span>', start));
  assert.strictEqual((wrap.match(/class="tk-ring"/g) || []).length, 2,
    'the ripple is one ring, so it blinks rather than flows');
  assert.ok(/\.tk-ring:nth-child\(2\) \{ animation-delay: 0\.8s; \}/.test(src),
    'both rings travel together — a single pulse, not a ripple');
});

test('the ripple sits inside the roundel\'s own positioning, and is not clickable', () => {
  const mic = src.slice(src.indexOf('#tk-mic {'), src.indexOf('}', src.indexOf('#tk-mic {')));
  assert.ok(/position: relative/.test(mic),
    'the rings would position against the page, not the microphone');
  const wrap = src.slice(src.indexOf('#tk-rings {'), src.indexOf('}', src.indexOf('#tk-rings {')));
  assert.ok(/pointer-events: none/.test(wrap), 'a ring can swallow the press');
});

test('the ripple takes the face accent, not a literal', () => {
  const ring = src.slice(src.indexOf('.tk-ring {'), src.indexOf('}', src.indexOf('.tk-ring {')));
  assert.ok(/var\(--accent-rgb\)/.test(ring), 'the ripple ignores the face dial');
  assert.ok(!/#[0-9a-f]{6}/i.test(ring), 'a colour literal would survive every face');
  // Injection found this hole: `animation: none` left every other assertion
  // green and the ripple simply never moved. The ring must actually run.
  assert.ok(/animation:\s*tkripple\s+[\d.]+s\s+linear\s+infinite/.test(ring),
    'the ripple is not animating — the ring sits still at the roundel edge');
});

test('the roundel reports the live state, and not with a colour literal', () => {
  const i = at('#talk.hot #tk-mic {');
  assert.ok(i !== -1, 'the roundel does not change when the microphone is live');
  const rule = src.slice(i, src.indexOf('}', i));
  assert.ok(/var\(--accent-rgb\)/.test(rule), 'the roundel ignores the face dial');
  assert.ok(!/#[0-9a-f]{6}/i.test(rule), 'a colour literal would survive every face');
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
