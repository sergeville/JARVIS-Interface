#!/usr/bin/env node
// Tests for the ambient bed -- soft music while Jarvis works (Serge, 2026-08-05:
// "can the visual when it's thinking there music in the back, soft music").
//
// Run:  ./tests/run-tests.sh   (from Jarvis Visual/)
//    or  node tests/test_ambient.js
//
// ambientTarget() and stepAmbient() are pulled out of jarvis.html and run for
// real, so these cannot drift from the page that ships. The audio graph itself
// is not testable without a browser -- so the POLICY was deliberately written
// as two pure functions, and that policy is what breaks in practice:
//
//   - a bed that keeps playing while the mic is open bleeds into whisper's
//     transcription of Serge's own voice;
//   - a bed keyed on `thinking` alone stutters, because pump() flips to
//     speaking on every chunk and back between tool calls;
//   - a bed that is not actually soft is worse than no bed at all.
//
// Each of those has a test below, plus a guard on the numbers themselves.

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const HTML = path.join(__dirname, '..', 'jarvis.html');
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

// Read the tuning out of the page rather than restating it here: if a number is
// ever retuned these tests must follow it, not quietly contradict it.
function num(name) {
  const m = src.match(new RegExp('const\\s+' + name + '\\s*=\\s*([0-9.]+)'));
  assert.ok(m, name + ' not found in jarvis.html');
  return parseFloat(m[1]);
}
const AMB_VOL  = num('AMB_VOL');
const AMB_DUCK = num('AMB_DUCK');
const AMB_UP   = num('AMB_UP');
const AMB_DOWN = num('AMB_DOWN');

eval(grab('ambientTarget') + '\n' + grab('stepAmbient') + '\n'
     + grab('ambNext') + '\n' + grab('ambShuffle') + '\n' + grab('ambOrderFrom'));

// A full snapshot of the page's flags; each test overrides only what it means.
const S = (o) => Object.assign({
  on: true, turnOpen: false, thinking: false,
  capturing: false, playing: false, state: 'idle',
}, o);

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log('ok   ' + name); }
  catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); }
}

// ---- what he asked for ----------------------------------------------------

test('thinking with music on plays the bed at full', () => {
  assert.strictEqual(ambientTarget(S({thinking: true, state: 'thinking'})), 1);
});

test('idle is silent', () => {
  assert.strictEqual(ambientTarget(S({state: 'idle'})), 0);
});

test('warming counts as working -- the bed covers the wait for the brain', () => {
  assert.strictEqual(ambientTarget(S({state: 'warming'})), 1);
});

// ---- the switch -----------------------------------------------------------

test('music off is silent even mid-thought', () => {
  assert.strictEqual(
    ambientTarget(S({on: false, thinking: true, turnOpen: true, state: 'thinking'})), 0);
});

test('music off beats every other flag at once', () => {
  assert.strictEqual(ambientTarget(S({
    on: false, thinking: true, turnOpen: true, playing: true, state: 'warming'})), 0);
});

// ---- the microphone guard -------------------------------------------------

test('the mic wins: capturing silences the bed even while thinking', () => {
  assert.strictEqual(ambientTarget(S({
    capturing: true, thinking: true, turnOpen: true, state: 'thinking'})), 0);
});

test('the mic wins over speaking too', () => {
  assert.strictEqual(ambientTarget(S({
    capturing: true, playing: true, turnOpen: true, state: 'speaking'})), 0);
});

// ---- ducking, not stopping ------------------------------------------------

test('speaking ducks the bed instead of cutting it', () => {
  const t = ambientTarget(S({playing: true, turnOpen: true, state: 'speaking'}));
  assert.ok(t > 0, 'bed was cut under the voice instead of ducked');
  assert.ok(t < 1, 'bed did not duck at all under the voice');
  assert.strictEqual(t, AMB_DUCK);
});

test('a tool call between spoken chunks keeps the bed up (turnOpen alone)', () => {
  // pump() drops `thinking` and `playing` here while the brain runs tools.
  // Without turnOpen in the policy this is the frame where it would drop out.
  assert.strictEqual(ambientTarget(S({turnOpen: true, state: 'thinking'})), 1);
});

test('the bed never falls to zero across a whole turn', () => {
  // The real sequence of flag snapshots through one reply: think, speak a
  // chunk, tool call, speak again, finish. Any 0 in here is an audible gap.
  const turn = [
    S({turnOpen: true, thinking: true, state: 'thinking'}),
    S({turnOpen: true, playing: true, state: 'speaking'}),
    S({turnOpen: true, state: 'thinking'}),                  // between chunks
    S({turnOpen: true, playing: true, state: 'speaking'}),
    S({turnOpen: true, thinking: true, state: 'thinking'}),
  ];
  turn.forEach((s, i) => assert.ok(ambientTarget(s) > 0,
    'bed dropped to silence at step ' + i + ' of a live turn'));
});

test('the bed stops once the turn is over', () => {
  assert.strictEqual(ambientTarget(S({state: 'idle'})), 0);
  assert.strictEqual(ambientTarget(S({state: 'offline'})), 0);
});

// ---- the fade -------------------------------------------------------------

test('rises toward the target without overshooting it', () => {
  assert.strictEqual(stepAmbient(0, 1), AMB_UP);
  assert.strictEqual(stepAmbient(1 - AMB_UP / 2, 1), 1);
});

test('falls toward the target without undershooting it', () => {
  assert.strictEqual(stepAmbient(1, 0), 1 - AMB_DOWN);
  assert.strictEqual(stepAmbient(AMB_DOWN / 2, 0), 0);
});

test('sitting exactly on target does not jitter', () => {
  assert.strictEqual(stepAmbient(0.5, 0.5), 0.5);
  assert.strictEqual(stepAmbient(0, 0), 0);
});

test('never goes negative', () => {
  for (let i = 0, g = 0.5; i < 200; i++) {
    g = stepAmbient(g, 0);
    assert.ok(g >= 0, 'gain went negative: ' + g);
  }
});

test('fades in within about a second (50 ms ticks)', () => {
  let g = 0, ticks = 0;
  while (g < 1 && ticks < 1000) { g = stepAmbient(g, 1); ticks++; }
  assert.strictEqual(g, 1);
  assert.ok(ticks * 50 <= 1500, 'fade-in took ' + (ticks * 50) + ' ms -- too slow to cover a turn');
});

test('fades out slower than it fades in -- a fade, not a cut', () => {
  let up = 0, uT = 0;   while (up < 1 && uT < 1000) { up = stepAmbient(up, 1); uT++; }
  let dn = 1, dT = 0;   while (dn > 0 && dT < 1000) { dn = stepAmbient(dn, 0); dT++; }
  assert.ok(dT > uT, 'fade-out (' + dT + ' ticks) is not slower than fade-in (' + uT + ')');
});

// ---- guards on the numbers themselves -------------------------------------

test('it is SOFT -- the ceiling stays a bed, not a soundtrack', () => {
  // Serge's word was "soft music". A future retune that turns this into a
  // foreground track should fail the suite rather than surprise him.
  //
  // THE THRESHOLD MOVED WHEN THE SOURCE DID, and that is worth defending
  // rather than quietly doing: 0.15 was calibrated against BARE OSCILLATORS,
  // which are summed by hand and peak nowhere near full scale. A decoded
  // recording is already mastered to roughly full scale, so the same gain
  // number means a completely different loudness. 0.30 on a mastered file is
  // about -10 dB -- quieter in the room than 0.065 was on three oscillators.
  // Same intent, different arithmetic. The ceiling is still a real ceiling:
  // anything approaching half scale is a soundtrack and fails here.
  assert.ok(AMB_VOL > 0, 'the bed is inaudible');
  assert.ok(AMB_VOL <= 0.45, 'AMB_VOL = ' + AMB_VOL + ' is a soundtrack, not a bed');
});

test('the duck level is a real duck', () => {
  assert.ok(AMB_DUCK > 0 && AMB_DUCK < 1, 'AMB_DUCK must sit strictly between 0 and 1');
});

// ---- promises made in the page source -------------------------------------

test('it ships OFF -- nothing makes a sound he did not ask for', () => {
  assert.ok(/let musicOn = false/.test(src), 'musicOn no longer defaults to false');
  assert.ok(/id="music-toggle"[^>]*class="off"/.test(src),
            'the toggle no longer ships in the off state');
});

test('the bed bypasses the analyser, so the ring does not pulse to music', () => {
  // analyser drives the ring and the waveform. Feeding it the bed would make
  // the visualiser dance to the music as though Jarvis were speaking.
  // Comments are stripped first: this block explains itself by naming the very
  // node it must not use, and a test that reads prose is not reading code.
  const body = grab('ensureAmbient').replace(/\/\/[^\n]*/g, '');
  assert.ok(/out\.connect\(ctx\.destination\)/.test(body),
            'the bed no longer goes straight to the destination');
  assert.ok(!/analyser/.test(body),
            'the bed was wired through the analyser -- the ring will pulse to music');
});

// ---- digital: the step sequencer ------------------------------------------
// Serge, 2026-08-05: "for the music, and it be digital." The first pass was
// three sines and came out warm and orchestral -- the wrong machine. These
// guard the things that would quietly turn it back into a pad, or into a tune.

// ---- THE RECORDING (Serge, 2026-08-05 ~1:05 PM) ----------------------
// "It's too repeated. I was like a Mozart back or something like that."
//
// Every synth-era test below this line was DELETED rather than kept, and that
// is the honest bookkeeping: they guarded a sequencer that no longer exists.
// Four passes tuned that sequencer -- waveform, tempo, scale, then dropping the
// drone -- and all four were the wrong variable. An eight-step pattern repeats
// every four seconds no matter how it is voiced. A test suite that still
// asserted "the pattern never resolves to the root" would be guarding a lesson
// we learned was beside the point.
//
// What survives unchanged is the POLICY -- the mic guard, the duck, the
// turn-scoping, the fade -- because none of that ever depended on where the
// sound came from. Those tests are above and still pass untouched, which is the
// argument for having written the policy as pure functions in the first place.

test('the playlist URL is a FIXED constant -- the server takes no filename', () => {
  // The security property Serge asked about, asserted rather than promised. A
  // traversal attack needs somewhere to put "../"; there must be nowhere.
  const m = src.match(/const AMB_LIST\s*=\s*'([^']+)'/);
  assert.ok(m, 'AMB_LIST is gone');
  assert.strictEqual(m[1], '/ambient-list');
  const body = grab('ensureAmbient').replace(/\/\/[^\n]*/g, '');
  assert.ok(/fetch\(AMB_LIST\)/.test(body),
            'the fetch no longer uses the constant -- a built URL is a way in');
  assert.ok(!/fetch\(\s*[`'"][^`'"]*\$\{/.test(body) && !/fetch\([^)]*\+/.test(body),
            'the fetch URL is interpolated or concatenated -- it must be a constant');
});

test('the page never hard-codes track URLs -- it plays what the server lists', () => {
  const body = grab('ensureAmbient') + grab('ambPlay');
  assert.ok(!/\.mp3/.test(body.replace(/\/\/[^\n]*/g, '')),
            'a track filename is baked into the page -- it will rot when the list changes');
  assert.ok(/t\.url/.test(grab('ambPlay')), 'ambPlay no longer plays the listed URL');
});

// ---- the rotation ---------------------------------------------------------

test('the mix advances one track at a time', () => {
  assert.strictEqual(ambNext(0, 4), 1);
  assert.strictEqual(ambNext(1, 4), 2);
  assert.strictEqual(ambNext(2, 4), 3);
});

test('the mix WRAPS instead of running out', () => {
  // The bug this exists for: rotation that stops at the end of the list and
  // leaves the page silent for the rest of the day.
  assert.strictEqual(ambNext(3, 4), 0);
  for (let i = 0, at = 0; i < 50; i++) {
    at = ambNext(at, 4);
    assert.ok(at >= 0 && at < 4, 'index left the list at step ' + i);
  }
});

test('an empty playlist cannot throw or spin', () => {
  assert.strictEqual(ambNext(0, 0), 0);
  assert.strictEqual(ambNext(7, 0), 0);
});

test('a single track still rotates onto itself', () => {
  assert.strictEqual(ambNext(0, 1), 0);
});

test('the shuffle keeps every track exactly once', () => {
  // A shuffle that drops or duplicates a track is the repetition problem again.
  const list = [{url: 'a'}, {url: 'b'}, {url: 'c'}, {url: 'd'}];
  for (let trial = 0; trial < 200; trial++) {
    const out = ambShuffle(list);
    assert.strictEqual(out.length, list.length);
    assert.deepStrictEqual(out.map(t => t.url).sort(), ['a', 'b', 'c', 'd']);
  }
});

test('the shuffle does not mutate the list it was given', () => {
  const list = [{url: 'a'}, {url: 'b'}, {url: 'c'}];
  const before = list.map(t => t.url);
  ambShuffle(list);
  assert.deepStrictEqual(list.map(t => t.url), before);
});

test('the shuffle actually shuffles', () => {
  const list = [1, 2, 3, 4, 5, 6].map(n => ({url: String(n)}));
  let moved = false;
  for (let i = 0; i < 40 && !moved; i++) {
    if (ambShuffle(list).map(t => t.url).join() !== '1,2,3,4,5,6') moved = true;
  }
  assert.ok(moved, 'ambShuffle returned the input order 40 times -- it is a no-op');
});

// ---- the calm opener (Serge, ~1:50 PM: "if the thing is safer") ----------

test('the mix ALWAYS opens with the first listed track, never a random one', () => {
  // The server hands the list back calmest-first. Switching the music on must
  // never open with Beethoven's Fifth at full tilt.
  const list = [{url: 'calm'}, {url: 'b'}, {url: 'c'}, {url: 'd'}];
  for (let i = 0; i < 200; i++) {
    assert.strictEqual(ambOrderFrom(list)[0].url, 'calm',
      'the opener was randomised on trial ' + i);
  }
});

test('the tail is still shuffled -- it is a mix, not a fixed order', () => {
  const list = [{url: 'calm'}, {url: 'b'}, {url: 'c'}, {url: 'd'}, {url: 'e'}];
  let moved = false;
  for (let i = 0; i < 60 && !moved; i++) {
    const o = ambOrderFrom(list).map(t => t.url).join();
    if (o !== 'calm,b,c,d,e') moved = true;
  }
  assert.ok(moved, 'the order never varies -- the mix became a fixed playlist');
});

test('the calm opener keeps every track exactly once', () => {
  const list = [{url: 'a'}, {url: 'b'}, {url: 'c'}, {url: 'd'}];
  for (let i = 0; i < 200; i++) {
    const o = ambOrderFrom(list);
    assert.strictEqual(o.length, 4);
    assert.deepStrictEqual(o.map(t => t.url).sort(), ['a', 'b', 'c', 'd']);
  }
});

test('one track, or none, does not throw', () => {
  assert.deepStrictEqual(ambOrderFrom([]), []);
  assert.deepStrictEqual(ambOrderFrom([{url: 'x'}]).map(t => t.url), ['x']);
  assert.deepStrictEqual(ambOrderFrom(null), []);
});

test('ambOrderFrom does not mutate the list it was given', () => {
  const list = [{url: 'a'}, {url: 'b'}, {url: 'c'}];
  const before = list.map(t => t.url);
  ambOrderFrom(list);
  assert.deepStrictEqual(list.map(t => t.url), before);
});

test('a track ENDING is what advances the mix, not a timer', () => {
  // A timer and a real track length drift apart, and the seam lands mid-phrase.
  const body = grab('ensureAmbient');
  assert.ok(/addEventListener\('ended'/.test(body), "nothing listens for 'ended'");
  // Narrowed 2026-08-05 1:35 PM. This banned EVERY timer in ensureAmbient, which
  // also outlawed the failed-fetch retry -- a different mechanism with none of
  // the drift problem. What it must actually forbid is a timer that ADVANCES the
  // mix, so it now checks what the timer callbacks do rather than that they
  // exist. Banning the whole construct would have blocked a correct fix.
  const clean = body.replace(/\/\/[^\n]*/g, '');
  const timers = clean.match(/set(?:Timeout|Interval)\s*\([\s\S]*?\)\s*,\s*[^)]*\)/g) || [];
  for (const t of timers) {
    assert.ok(!/ambNext|ambPlay|ambAt\s*=/.test(t),
              'the rotation is on a timer -- it will drift out of step with the music');
  }
});

test('a broken track skips on instead of ending the mix', () => {
  const body = grab('ensureAmbient');
  assert.ok(/addEventListener\('error'/.test(body),
            'one unplayable file will stop the music for the whole session');
});

// ---- the graph, unchanged by any of this ----------------------------------

test('the source runs continuously and the GAIN is what gates it', () => {
  // If a turn started and stopped playback it would replay the same opening
  // bar every time -- which rebuilds the repetition he rejected.
  const tick = grab('tickAmbient').replace(/\/\/[^\n]*/g, '');
  // Follows the 2026-08-05 1:50 PM volume control: AMB_VOL became the DEFAULT
  // and ambVol is the live level. The property being guarded is unchanged --
  // one gain node controls the music and the tick never touches play/pause.
  assert.ok(/out\.gain\.value\s*=\s*ambVol\s*\*\s*ambGain/.test(tick),
            'the gain is no longer what controls the music');
  assert.ok(!/\.play\(|\.pause\(/.test(tick),
            'the tick starts or stops playback -- the piece will restart every turn');
});

test('the music rides the master gain, so the mic guard and the duck cover it', () => {
  const body = grab('ensureAmbient').replace(/\/\/[^\n]*/g, '');
  assert.ok(/src\.connect\(tone\)/.test(body), 'the source no longer feeds the tone filter');
  assert.ok(/tone\.connect\(out\)/.test(body),
            'the music no longer reaches the master gain -- the duck and mic guard are bypassed');
});

test('the music bypasses the analyser, so the ring does not dance to Mozart', () => {
  const body = grab('ensureAmbient').replace(/\/\/[^\n]*/g, '');
  assert.ok(!/analyser/.test(body),
            'the music was wired through the analyser -- the visualiser will pulse to it');
  assert.ok(/out\.connect\(ctx\.destination\)/.test(body),
            'the master no longer reaches the destination');
});

test('missing routes are survivable -- no restart, no broken page', () => {
  const body = grab('ensureAmbient');
  assert.ok(/\.catch\(/.test(body),
            'the fetch has no catch -- an old server will throw every turn');
  assert.ok(/ambLoading/.test(body), 'nothing guards against re-fetching the list');
});

// THE RETRY LATCH. Serge switched MUSIC ON after his restart and heard nothing:
// his tab had loaded ~40 s before the restart, so its single playlist fetch hit
// a dead route and ambLoading latched true for the life of the page. The failure
// was expected and correct; never retrying was the bug. These guard the fix in
// both directions -- it must retry, and it must not hammer.
test('a failed playlist fetch clears the latch so the next turn retries', () => {
  const body = grab('ensureAmbient');
  const cat = body.slice(body.indexOf('.catch('));
  assert.ok(/ambLoading\s*=\s*false/.test(cat),
            'the catch never clears ambLoading -- a tab that loaded before the ' +
            'restart can never pick the music up without a manual reload');
});

test('the retry is delayed, not bare -- tickAmbient runs at 20 Hz', () => {
  const body = grab('ensureAmbient');
  const cat = body.slice(body.indexOf('.catch('));
  assert.ok(/setTimeout\([^)]*AMB_RETRY_MS|setTimeout\(\s*\(\)\s*=>\s*\{\s*ambLoading\s*=\s*false;?\s*\}\s*,\s*AMB_RETRY_MS/.test(cat),
            'the latch is cleared without a delay -- ensureAmbient is called on ' +
            'every 50 ms tick, so this refetches 20x a second against a dead route');
  assert.ok(/const\s+AMB_RETRY_MS\s*=\s*(\d+)/.test(src),
            'AMB_RETRY_MS is not defined');
  const ms = Number(/const\s+AMB_RETRY_MS\s*=\s*(\d+)/.exec(src)[1]);
  assert.ok(ms >= 1000, 'the retry delay is under a second -- that is a hammer, not a retry');
});

test('a successful fetch does NOT clear the latch', () => {
  const body = grab('ensureAmbient');
  const then = body.slice(body.indexOf('.then(list'), body.indexOf('.catch('));
  assert.ok(!/ambLoading\s*=\s*false/.test(then),
            'the success path clears the latch -- the list would be refetched ' +
            'on every tick for the life of the page');
});

// ---- the volume control (Serge, 2026-08-05 ~1:45 PM) -----------------------
// "I would like to have control of the volume... I would like to even maybe
// lower it" -- and, asked first: "I like the cap." So these guard both halves:
// he can move it, and it cannot become a soundtrack.
const AMB_MAX = num('AMB_MAX');
eval(grab('clampVol'));

test('the cap is a real cap -- the top of the slider is still a bed', () => {
  assert.ok(AMB_MAX > 0, 'the cap silences the music');
  assert.ok(AMB_MAX <= 0.45,
            'AMB_MAX = ' + AMB_MAX + ' is a soundtrack, not a bed');
  assert.ok(AMB_MAX >= AMB_VOL,
            'the cap sits below the default -- the music would open quieter ' +
            'than it does today and the slider could never reach the old level');
});

test('he can turn it all the way down -- silence is a valid setting', () => {
  // He asked for this in the same breath as the cap. A floor above zero would
  // mean the only way to shut the music up is the toggle.
  assert.strictEqual(clampVol(0), 0, 'zero is not reachable');
});

test('the cap is enforced in code, not by the input element', () => {
  assert.strictEqual(clampVol(0.9), AMB_MAX, 'a value above the cap survives');
  assert.strictEqual(clampVol(999), AMB_MAX, 'a wild value survives');
  assert.strictEqual(clampVol(-5), 0, 'a negative value is not floored at zero');
  const body = grab('renderVol') + src.slice(src.indexOf('const volEl'));
  assert.ok(/clampVol\(/.test(body),
            'the slider does not go through clampVol -- the max attribute is a ' +
            'suggestion to the browser, not a guarantee');
});

test('junk in storage does not silence the music', () => {
  // The failure mode this guards: Number('') is 0, so a bare fallback would
  // restore an empty stored value as total silence and read as a broken build.
  assert.strictEqual(clampVol('abc'), AMB_VOL, 'junk restores as something odd');
  assert.strictEqual(clampVol(undefined), AMB_VOL, 'undefined restores as odd');
});

test('a stored value is restored through the SAME clamp as the slider', () => {
  // Two paths writing one number is exactly where a cap gets bypassed: an older
  // page with a higher ceiling could otherwise leave a too-loud value behind.
  const tail = src.slice(src.indexOf("localStorage.getItem('jarvisMusicVol')"));
  assert.ok(/clampVol\(\s*saved\s*\)/.test(tail.slice(0, 400)),
            'the restore path does not clamp -- a stored value can exceed the cap');
});

test('the volume is persisted, like the toggle', () => {
  assert.ok(/setItem\('jarvisMusicVol'/.test(src),
            'the volume is not saved -- the page reloads on every edit, so his ' +
            'setting would reset under him all day');
});

test('the slider is live, not apply-on-release', () => {
  assert.ok(/addEventListener\('input'/.test(src.slice(src.indexOf('const volEl'))),
            "the slider listens for 'change', not 'input' -- he cannot hear the " +
            'level while dragging, which is the only way to set it by ear');
});

test('the volume changes nothing else in the policy', () => {
  // ambVol multiplies on top; the mic guard and the duck must not have moved.
  const t = ambientTarget(S({capturing: true, turnOpen: true}));
  assert.strictEqual(t, 0, 'the mic guard was disturbed by the volume work');
  const d = ambientTarget(S({turnOpen: true, playing: true}));
  assert.strictEqual(d, AMB_DUCK, 'the duck was disturbed by the volume work');
});

test('there is no sequencer left to repeat', () => {
  assert.ok(!/function\s+scheduleArp/.test(src), 'scheduleArp() is back');
  assert.ok(!/ARP_PAT/.test(src), 'the step pattern is back -- that is the repetition he rejected');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
