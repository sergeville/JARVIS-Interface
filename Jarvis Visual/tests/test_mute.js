#!/usr/bin/env node
// Tests for MUTE (Serge, 2026-08-07 ~5:27 PM: "sometimes people come in and
// talk to me, and you're talking").
//
// His own words for what it must be: "still right, but just the sound is off."
// So the whole point of this feature is what it does NOT do. Silencing the
// speakers must not cancel the speech, must not freeze the ring, and must not
// stop the transcript -- otherwise muting costs him the thing he mutes for,
// which is being able to catch up afterwards.
//
// As with the other page tests, the real functions are pulled out of
// jarvis.html and run against stubs, so they cannot drift from what ships.

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const HTML = path.join(__dirname, '..', 'jarvis.html');
const src = fs.readFileSync(HTML, 'utf8');

function grab(name) {
  const re = new RegExp('(?:^|\\n)(?:async )?function ' + name + '\\s*\\([^)]*\\)\\s*\\{');
  const m = src.match(re);
  if (!m) throw new Error('function ' + name + ' not found in jarvis.html');
  const start = src.indexOf(m[0]) + (m[0].startsWith('\n') ? 1 : 0);
  let i = src.indexOf('{', start), depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}') { depth--; if (!depth) return src.slice(start, j + 1); }
  }
  throw new Error('unbalanced braces reading ' + name);
}

// ---- stubs ----------------------------------------------------------------
let connections = [];          // [from, to] pairs, so the ORDER of the graph is checkable
function node(label) {
  return { label, gain: { value: 1 }, fftSize: 0,
           connect(t) { connections.push([label, t.label]); } };
}
let created = [];
class AudioContextStub {
  constructor() { this.destination = node('destination'); this.state = 'running'; }
  createAnalyser() { created.push('analyser'); return node('analyser'); }
  createGain()     { created.push('gain');     return node('voiceGain'); }
}
let localStore = {};
const localStorage = {
  getItem: (k) => (k in localStore ? localStore[k] : null),
  setItem: (k, v) => { localStore[k] = String(v); },
};
let nodes = {};
const document = {
  getElementById: (id) => nodes[id] || null,
};
const AudioContext = AudioContextStub;

let outCtx = null, analyser = null, curSource = null, voiceGain = null;
let muted = false;

eval(grab('ensureOut') + '\n' + grab('renderMute') + '\n' + grab('applyMute'));

// ---- harness --------------------------------------------------------------
let passed = 0, failed = 0;
function reset() {
  outCtx = null; analyser = null; voiceGain = null; curSource = null;
  muted = false; connections = []; created = []; localStore = {};
  nodes = { 'mute-toggle': { className: '', textContent: '' } };
}
function test(name, fn) {
  reset();
  try { fn(); console.log('ok   ' + name); passed++; }
  catch (e) { console.log('FAIL ' + name + '\n     ' + e.message); failed++; }
}

// ---- the graph ------------------------------------------------------------

test('the speech path runs analyser -> gain -> speakers, in that order', () => {
  ensureOut();
  assert.deepStrictEqual(connections, [['analyser', 'voiceGain'],
                                       ['voiceGain', 'destination']]);
});

test('THE ANALYSER SITS BEFORE THE GAIN, so the ring still moves while muted', () => {
  // The load-bearing one. If the gain were placed before the analyser, muting
  // would feed it silence and the ring would go flat -- which reads as "Jarvis
  // stopped talking". He is muting the speakers, not the machine, and the page
  // must not claim otherwise.
  ensureOut();
  const gainIdx     = connections.findIndex(c => c[0] === 'voiceGain');
  const analyserIdx = connections.findIndex(c => c[0] === 'analyser');
  assert.ok(analyserIdx < gainIdx,
    'the gain is upstream of the analyser: muting would flatten the ring');
  assert.strictEqual(connections.find(c => c[1] === 'destination')[0], 'voiceGain',
    'something other than the gain reaches the speakers, so mute can be bypassed');
});

test('nothing reaches the speakers except through the gain', () => {
  // A second connection straight to the destination would leave mute
  // half-working: quieter, not silent, which is worse than not having it.
  ensureOut();
  const toSpeakers = connections.filter(c => c[1] === 'destination');
  assert.strictEqual(toSpeakers.length, 1, 'more than one path to the speakers');
});

// ---- the switch -----------------------------------------------------------

test('muting sets the gain to a true zero, not merely a low value', () => {
  ensureOut();
  muted = true; applyMute();
  assert.strictEqual(voiceGain.gain.value, 0);
});

test('unmuting restores full volume', () => {
  ensureOut();
  muted = true;  applyMute();
  muted = false; applyMute();
  assert.strictEqual(voiceGain.gain.value, 1);
});

test('muting before Jarvis has ever spoken does not throw', () => {
  // The graph is built lazily on the first sound. He can press the button on a
  // silent page, and a crash there would take the whole script down.
  muted = true;
  assert.doesNotThrow(() => applyMute());
});

test('a mute set before the graph exists survives into it', () => {
  // The other half of the same case: pressing mute on a silent page must still
  // be honoured when the first sound eventually builds the graph.
  muted = true;
  applyMute();          // no graph yet -- no-op
  ensureOut();          // graph built now
  assert.strictEqual(voiceGain.gain.value, 0,
    'the graph came up unmuted after he had already muted it');
});

// ---- the label ------------------------------------------------------------

test('the label says MUTED, not VOICE OFF', () => {
  // The voice is not off. It is still being produced and still being written
  // to the screen; only the speakers are silent. The label must not claim more
  // than the feature does -- this page's standing rule about not lying.
  renderMute(true);
  assert.strictEqual(nodes['mute-toggle'].textContent, 'MUTED');
  renderMute(false);
  assert.strictEqual(nodes['mute-toggle'].textContent, 'VOICE ON');
});

test('muted wears the warn colour and unmuted the ok colour', () => {
  renderMute(true);
  assert.strictEqual(nodes['mute-toggle'].className, 'off');
  renderMute(false);
  assert.strictEqual(nodes['mute-toggle'].className, 'on');
});

// ---- what mute must NOT do ------------------------------------------------

test('the mute handler does not touch the speech queue or the current source', () => {
  // "Still right, but just the sound is off." Dropping the queue or stopping
  // the source would make this a STOP button wearing a mute label, and he
  // would lose the answer he muted in order to hear about later.
  const h = src.match(/getElementById\('mute-toggle'\)\.addEventListener\('click',[\s\S]*?\n\}\);/);
  assert.ok(h, 'the mute click handler is gone');
  for (const forbidden of ['playQueue', 'curSource', 'stopPlayback',
                           'suspend', 'turnOpen', 'thinking']) {
    assert.ok(!h[0].includes(forbidden),
      'the mute handler touches ' + forbidden + ' -- that is a stop, not a mute');
  }
});

test('mute is nowhere near showLine, so the transcript keeps writing', () => {
  // The reason the overlay stopped fading the same afternoon: he reads it to
  // catch up. A mute that also stopped the text would take that away exactly
  // when someone is talking to him.
  const body = grab('showLine');
  for (const forbidden of ['muted', 'voiceGain']) {
    assert.ok(!body.includes(forbidden),
      'showLine consults ' + forbidden + ': muting would stop the transcript');
  }
});

test('pump does not consult the mute, so speech is never skipped while silent', () => {
  // If pump skipped chunks while muted, unmuting mid-answer would drop back in
  // somewhere arbitrary, and the queue would drain faster than it played.
  const body = grab('pump');
  assert.ok(!body.includes('muted'),
    'pump branches on the mute -- speech would be discarded rather than silenced');
});

test('the choice is remembered across a reload', () => {
  const h = src.match(/getElementById\('mute-toggle'\)\.addEventListener\('click',[\s\S]*?\n\}\);/)[0];
  assert.ok(/localStorage\.setItem\('jarvisMute'/.test(h), 'the mute is not persisted');
  assert.ok(/localStorage\.getItem\('jarvisMute'\)/.test(src), 'the mute is not restored at boot');
});

test('the button exists in the markup and sits beside the music toggle', () => {
  assert.ok(/<button id="mute-toggle"/.test(src), 'the mute button is not on the page');
  assert.ok(src.indexOf('id="mute-toggle"') < src.indexOf('id="music-toggle"'),
    'the two sound controls have been separated');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
