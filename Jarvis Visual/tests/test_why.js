#!/usr/bin/env node
// The why-box on the JARVIS page.
//
// Serge, 2026-08-07 ~9:54 PM: "When I press the deny, there should be an
// inbox asking me why, and either me entering the reason or saying the reason
// with my voice. That's what I'm always waiting for."
//
// As with the other page tests, the real functions are pulled out of
// jarvis.html and RUN against stubs, so they cannot drift from what ships --
// and so that none of these can pass by matching a line that never executes,
// which is the failure this project keeps rediscovering.

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

// Code only. A comment that NAMES the thing it forbids is the single most
// repeated way a guard on this project has passed against broken code.
function noComments(s) {
  return s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\n)\s*\/\/[^\n]*/g, '$1');
}

// ⚠ THE RUNNER AWAITS. The first version of this file called fn() and moved
// on, so every `async () => {...}` test returned a promise nobody looked at:
// its assertions ran after the summary, and a REJECTION printed "ok". Three
// of these tests were passing against code that threw. A test harness that
// cannot fail is the same defect as a guard that cannot fire.
let tests = 0, failed = 0;
const queue = [];
function t(name, fn) {
  tests++;
  queue.push(async () => {
    try { await fn(); console.log('  ok   ' + name); }
    catch (e) { failed++; console.log('  FAIL ' + name + '\n       ' + e.message); }
  });
}
function section(title) { queue.push(async () => console.log('\n=== ' + title)); }

// ---- DOM stub -------------------------------------------------------------
function el() {
  return { style: {display: ''}, value: '', textContent: '', focused: false,
           classes: new Set(),
           classList: { add(c){ this.owner.classes.add(c); },
                        remove(c){ this.owner.classes.delete(c); } },
           focus(){ this.focused = true; },
           addEventListener(){}, };
}
function mkEl() { const e = el(); e.classList.owner = e; return e; }

// BUILT ONCE AND ONLY CLEARED, never replaced. The page's why-box block
// captures its elements in `const`s at load, exactly as the browser does, so
// handing it a fresh set of nodes between tests would leave it holding the
// old ones -- and every test would run against a DOM nothing could see.
const nodes = {};
for (const id of ['why-wrap', 'why-text', 'why-note', 'why-speak',
                  'why-send', 'why-skip', 'approve-yes', 'approve-no',
                  'approve-head', 'approve-detail', 'approve-box'])
  nodes[id] = mkEl();
function resetDom() {
  for (const id of Object.keys(nodes)) {
    const e = nodes[id];
    e.style.display = ''; e.value = ''; e.textContent = '';
    e.focused = false; e.classes.clear();
  }
}
const window = { addEventListener(){} };
const document = { getElementById: (id) => nodes[id] || null, body: { classList: { add(){}, remove(){} } } };

// ---- state the extracted functions close over -----------------------------
let approvalId = null, approvalQueued = null, approvalSending = false,
    approvalStale = false, approvalHttp = true, serverBoot = 'b1',
    capturing = false, approveBox = null, statusSaid = '';
// whyCapturing / whyBufs / whyBusy are declared by the page block itself and
// `let` inside eval() lives in the EVAL's scope -- so declaring them out here
// would silently shadow nothing and leave every poke invisible to the code
// under test. That is exactly how the transcription-failure test first
// "passed": whyCapturing was false in the real function, so it returned on
// its first line and asserted against a box nothing had touched.
const MIN_CAP_S = 0.20;
let micCtx = {sampleRate: 16000, state: 'running', resume(){}};
let posts = [];
const REPLY_TIMEOUT_MS = 5000;

function approvalStatus(s) { statusSaid = s; }
class AbortController { constructor(){ this.signal = {}; } abort(){} }
const setTimeout_ = setTimeout, clearTimeout_ = clearTimeout;

let fetchResult = {ok: true, json: async () => ({ok: true})};
async function fetch(url, opts) {
  posts.push({url, body: JSON.parse(opts.body)});
  if (fetchResult instanceof Error) throw fetchResult;
  return fetchResult;
}

// The why-box block is a run of top-level declarations, not one function, so
// it is sliced by its own banner rather than by grab().
const WHY_START = src.indexOf('const whyWrap  = document.getElementById');
const WHY_END = src.indexOf("document.getElementById('approve-yes').onclick");
assert.ok(WHY_START > 0 && WHY_END > WHY_START, 'why-box block not found in jarvis.html');
const whyBlock = src.slice(WHY_START, WHY_END);

eval(whyBlock + '\n'
     + grab('retryWords') + '\n'
     + grab('deliverApproval') + '\n'
     + grab('answerApproval') + '\n'
     + grab('flushApproval') + '\n'
     + grab('showApproval') + '\n'
     // Evaluated in the SAME scope as the block, which is the only way to
     // reach its `let`s. A test that cannot set the state it is testing is
     // not a test.
     + 'function __why(cap, bufs, busy){ whyCapturing = cap; whyBufs = bufs || [];'
     + ' whyBusy = !!busy; }');

function reset() {
  resetDom();
  approveBox = nodes['approve-box'];
  approvalId = 1; approvalQueued = null; approvalSending = false;
  approvalStale = false; approvalHttp = true; serverBoot = 'b1';
  __why(false, [], false); capturing = false;
  posts = []; statusSaid = '';
  fetchResult = {ok: true, json: async () => ({ok: true})};
}

// Re-eval inside reset() rebinds consts in this scope; simpler is to keep the
// handles as lookups. Redefine the four helpers against live lookups instead.
const whyWrapOf  = () => nodes['why-wrap'];
const whyTextOf  = () => nodes['why-text'];
const whyNoteOf  = () => nodes['why-note'];

section('the box opens on DENY, and DENY alone does not send');

t('DENY opens the box and sends nothing', () => {
  reset();
  openWhy();
  assert.strictEqual(whyWrapOf().style.display, 'block');
  assert.strictEqual(posts.length, 0, 'a deny was sent before he said why');
});

t('the box does not open when there is no request to refuse', () => {
  reset();
  approvalId = null;
  openWhy();
  assert.notStrictEqual(whyWrapOf().style.display, 'block');
});

t('the textarea takes focus so he can just type', () => {
  reset();
  openWhy();
  assert.ok(whyTextOf().focused);
});

section('SEND carries his words with the refusal, in ONE post');

t('the reason and the verdict travel together', async () => {
  reset();
  openWhy();
  whyTextOf().value = 'that is the wrong branch';
  sendWhy();
  await new Promise(r => setImmediate(r));
  assert.strictEqual(posts.length, 1, 'expected exactly one post');
  assert.strictEqual(posts[0].url, '/approval-reply');
  assert.strictEqual(posts[0].body.allow, false);
  assert.strictEqual(posts[0].body.reason, 'that is the wrong branch');
});

t('the reason is trimmed before it is sent', async () => {
  reset();
  openWhy();
  whyTextOf().value = '   spaced out   ';
  sendWhy();
  await new Promise(r => setImmediate(r));
  assert.strictEqual(posts[0].body.reason, 'spaced out');
});

t('an empty SEND says so instead of doing nothing', async () => {
  reset();
  openWhy();
  whyTextOf().value = '   ';
  sendWhy();
  await new Promise(r => setImmediate(r));
  assert.strictEqual(posts.length, 0, 'an empty reason was sent');
  assert.ok(whyNoteOf().textContent.length > 0,
            'the press was silently ignored');
});

t('APPROVE sends no reason at all', async () => {
  reset();
  answerApproval(true);
  await new Promise(r => setImmediate(r));
  assert.strictEqual(posts[0].body.allow, true);
  assert.strictEqual(posts[0].body.reason, null);
});

section('he is never trapped in the box');

t('DENY WITHOUT A REASON sends the refusal with a null reason', async () => {
  reset();
  openWhy();
  whyTextOf().value = 'half a thought';
  answerApproval(false, null);
  await new Promise(r => setImmediate(r));
  assert.strictEqual(posts.length, 1);
  assert.strictEqual(posts[0].body.allow, false);
  assert.strictEqual(posts[0].body.reason, null,
                     'skipping still leaked the half-typed text');
});

section('a reason never bleeds onto a request it was not written for');

t('sending clears the box', async () => {
  reset();
  openWhy();
  whyTextOf().value = 'first reason';
  sendWhy();
  await new Promise(r => setImmediate(r));
  assert.strictEqual(whyTextOf().value, '');
  assert.notStrictEqual(whyWrapOf().style.display, 'block');
});

t('a NEW request closes the box and drops the old text', () => {
  reset();
  openWhy();
  whyTextOf().value = 'about the OLD request';
  showApproval({id: 2, tool: 'Bash', detail: 'rm -rf'});
  assert.strictEqual(whyTextOf().value, '',
                     "the previous request's reason survived into a new one");
  assert.notStrictEqual(whyWrapOf().style.display, 'block');
});

t('the request going away closes the box', () => {
  reset();
  openWhy();
  whyTextOf().value = 'typing…';
  showApproval(null);
  assert.strictEqual(whyTextOf().value, '');
  assert.notStrictEqual(whyWrapOf().style.display, 'block');
});

t('a REDRAW of the same request leaves what he is typing alone', () => {
  reset();
  openWhy();
  whyTextOf().value = 'half a sentence';
  showApproval({id: 1, tool: 'Bash', detail: 'ls'});   // the 15Hz poll
  assert.strictEqual(whyTextOf().value, 'half a sentence',
                     'the poll ate his words mid-typing');
});

section('his words survive a failed send');

t('a refused post keeps the reason queued with the verdict', async () => {
  reset();
  fetchResult = {ok: false, json: async () => ({ok: false, error: 'nope'})};
  openWhy();
  whyTextOf().value = 'because I said so';
  sendWhy();
  await new Promise(r => setImmediate(r));
  assert.ok(approvalQueued, 'his click was dropped');
  assert.strictEqual(approvalQueued.reason, 'because I said so',
                     'the retry would deliver an unexplained refusal');
});

t('the queued retry delivers the reason too', async () => {
  reset();
  approvalQueued = {id: 1, allow: false, reason: 'kept', boot: 'b1'};
  await flushApproval();
  assert.strictEqual(posts[0].body.reason, 'kept');
});

t('a superseding click keeps its own reason', async () => {
  reset();
  approvalSending = true;
  answerApproval(false, 'the second thought');
  assert.strictEqual(approvalQueued.reason, 'the second thought');
});

section('speaking the reason is transcription and nothing else');

t('the spoken buffer is never the turn buffer', () => {
  // capBufs is what becomes a spoken TURN. If the why-box wrote into it, a
  // refusal reason could be sent to the brain as speech while a permission
  // is pending -- the one thing that must not happen.
  // COMMENTS STRIPPED FIRST, and that is not a detail: the first version of
  // this test read the raw slice and failed against correct code, because the
  // comment explaining why the buffers are separate says "capBufs". Seventh
  // time on this project's record that grepping source punished the prose
  // explaining the decision -- walked into again while writing the guard.
  const branch = noComments(
    grab('ensureMic').slice(grab('ensureMic').indexOf('else if (whyCapturing)')));
  assert.ok(branch.includes('whyBufs.push'), 'the why branch fills no buffer');
  assert.ok(!branch.includes('capBufs'),
            'the why-box writes into the turn buffer');
});

t('the talk button stands down while he is speaking a reason', () => {
  const press = grab('press');
  assert.ok(/if \(whyCapturing \|\| whyBusy\) return;/.test(press),
            'press() would grab the microphone mid-reason');
});

t('the transcription post goes to the transcribe-only route', () => {
  assert.ok(src.includes("fetch('/reason-transcribe'"),
            'the spoken reason has no route to text');
  // And it must NOT be the socket, which is how a turn is opened.
  const stop = grab('whyStopSpeaking');
  assert.ok(!/ws\.send/.test(stop),
            'the spoken reason can reach the brain as a turn');
});

t('a transcription failure still leaves him able to type', async () => {
  reset();
  fetchResult = new Error('network down');
  __why(true, [new Float32Array(8000)]);
  await whyStopSpeaking(false);
  assert.ok(/type it/i.test(whyNoteOf().textContent),
            'a failed transcription said nothing about typing');
});

t('heard text is appended, never overwriting what he already typed', () => {
  const stop = grab('whyStopSpeaking');
  assert.ok(/whyText\.value \? \(whyText\.value\.trim\(\) \+ ' ' \+ heard\) : heard/.test(stop),
            'transcription replaces rather than appends');
});

section('the wiring actually points at the box');

t('the DENY button opens the box rather than sending a refusal', () => {
  assert.ok(/getElementById\('approve-no'\)\.onclick = openWhy;/.test(src),
            'DENY does not open the why box');
  assert.ok(!/getElementById\('approve-no'\)\.onclick = \(\) => answerApproval\(false\)/.test(src),
            'DENY still sends the old unexplained refusal');
});

t('both ways out of the box are wired', () => {
  assert.ok(/getElementById\('why-send'\)\.onclick = sendWhy;/.test(src));
  assert.ok(/getElementById\('why-skip'\)\.onclick = \(\) => answerApproval\(false, null\);/.test(src));
});

t('a bare Enter does not send his reason', () => {
  // This page has already cost him one popup to a stray Enter key.
  const m = src.match(/whyText\.addEventListener\('keydown'[\s\S]{0,200}?\}\);/);
  assert.ok(m, 'no keydown handler on the reason field');
  assert.ok(/metaKey \|\| e\.ctrlKey/.test(m[0]),
            'Enter alone would send an unfinished reason');
});

t('the box ships CLOSED', () => {
  assert.ok(/#why-wrap \{ display: none;/.test(src),
            'the why box would show on every permission request');
});

section('the talk key belongs to the box while the box is open');

// Serge, 2026-08-07 ~10:50 PM: "Right command did not work, but if I press
// the button, then I speak, then the text went in the input." It was not
// merely unwired -- the key still drove press()/release(), so his spoken
// reason opened a TURN and arrived as a message to Jarvis. These run the real
// handlers rather than reading them: the fault was invisible to the eye and
// the last thing this file needs is another guard that only greps.
function keyHandler(kind) {
  // Slice the MetaRight handler of the given kind out of the page. Anchored
  // on the code that actually distinguishes them, so a reordering of the two
  // cannot silently hand a test the wrong one.
  const re = new RegExp("addEventListener\\('" + kind + "', \\(e\\) => \\{[\\s\\S]*?\\n\\}\\);");
  const all = src.match(new RegExp(re, 'g')) || [];
  const one = all.filter(s => /MetaRight/.test(s));
  assert.strictEqual(one.length, 1,
    'expected exactly one MetaRight ' + kind + ' handler, found ' + one.length);
  const body = one[0].replace(/^addEventListener\('[a-z]+', \(e\) => \{/, '').replace(/\}\);$/, '');
  assert.ok(/whyIsOpen|whyCapturing/.test(noComments(body)),
            'the ' + kind + ' handler no longer consults the why box');
  return new Function(
    'e', 'lineAlive', 'typedEl', 'document', 'whyIsOpen', 'whyStartSpeaking',
    'press', 'whyCapturing', 'whyStopSpeaking', 'release', body);
}

function keyRun(kind, {open = false, cap = false, focus = 'body', line = false} = {}) {
  const calls = [];
  const typed = {};
  const active = focus === 'typed' ? typed : {};
  const e = {code: 'MetaRight', repeat: false, prevented: false,
             preventDefault(){ this.prevented = true; }};
  keyHandler(kind)(
    e, line, typed, {activeElement: active},
    () => open,
    () => calls.push('whyStart'),
    () => calls.push('press'),
    cap,
    (d) => calls.push('whyStop:' + d),
    () => calls.push('release'));
  return {calls, e};
}

t('holding the key with the box open speaks INTO the box', () => {
  const r = keyRun('keydown', {open: true});
  assert.deepStrictEqual(r.calls, ['whyStart'],
    'his refusal reason opened a spoken turn instead of filling the box');
});

t('holding the key with the box shut still talks to Jarvis', () => {
  const r = keyRun('keydown', {open: false});
  assert.deepStrictEqual(r.calls, ['press'],
    'the ordinary talk key was broken by the why-box guard');
});

t('releasing while the box is capturing ENDS the box capture, and keeps it', () => {
  const r = keyRun('keyup', {cap: true});
  assert.deepStrictEqual(r.calls, ['whyStop:false'],
    'the spoken reason was discarded or sent as a turn');
});

t('releasing with no box capture falls through to the talk button', () => {
  const r = keyRun('keyup', {cap: false});
  assert.deepStrictEqual(r.calls, ['release']);
});

t('a box CLOSED mid-hold still stops the microphone', () => {
  // The key-up asks whyCapturing, never whyIsOpen -- closing the box between
  // press and release must not strand the mic live with no way back.
  const r = keyRun('keyup', {open: false, cap: true});
  assert.deepStrictEqual(r.calls, ['whyStop:false'],
    'the microphone was left capturing after the box closed');
});

t('the terminal line still owns the key, box or no box', () => {
  const r = keyRun('keydown', {open: true, line: true});
  assert.deepStrictEqual(r.calls, [],
    'the page grabbed Right Command while the terminal line held it');
});

t('typing in the command box is never a talk key', () => {
  assert.deepStrictEqual(keyRun('keydown', {focus: 'typed', open: true}).calls, []);
  assert.deepStrictEqual(keyRun('keyup', {focus: 'typed', cap: true}).calls, []);
});

t('a key REPEAT does not restart the box capture', () => {
  const calls = [];
  const typed = {};
  keyHandler('keydown')(
    {code: 'MetaRight', repeat: true, preventDefault(){}},
    false, typed, {activeElement: {}},
    () => true, () => calls.push('whyStart'), () => calls.push('press'),
    false, () => {}, () => {});
  assert.deepStrictEqual(calls, [], 'holding the key re-armed the capture');
});

t('the talk path and the box path are mutually exclusive', () => {
  // Both firing would send the audio twice -- once as a turn, once as text.
  for (const open of [true, false]) {
    const r = keyRun('keydown', {open});
    assert.strictEqual(r.calls.length, 1, 'both capture paths ran on one press');
  }
});

// ⚠ THE ONE FAULT THAT RAN UNCAUGHT: `whyIsOpen(){ return false; }` left the
// whole suite green, because every handler test above STUBS it. The key tests
// prove the routing; only these prove the thing the routing asks. A guard the
// tests supply for themselves is not a guard.
t('whyIsOpen answers the real box, opened the real way', () => {
  reset();
  assert.strictEqual(whyIsOpen(), false, 'the box reads open before any DENY');
  openWhy();
  assert.strictEqual(whyIsOpen(), true, 'a DENY leaves the key talking to Jarvis');
});

t('whyIsOpen goes false again when the box closes', () => {
  reset();
  openWhy();
  closeWhy();
  assert.strictEqual(whyIsOpen(), false,
    'the key would keep feeding a box that is no longer on screen');
});

t('whyIsOpen is not a constant', () => {
  // Kills the degenerate `return true` / `return false` bodies outright.
  reset();
  const shut = whyIsOpen();
  openWhy();
  assert.notStrictEqual(whyIsOpen(), shut, 'whyIsOpen never changes its answer');
});

t('press() still stands down while the box holds the microphone', () => {
  // The guard inside press() is the second line of defence and must stay.
  assert.ok(/if \(whyCapturing \|\| whyBusy\) return;/.test(noComments(grab('press'))),
            'press() would open a turn over a reason being spoken');
});

(async () => {
  for (const step of queue) await step();
  console.log('\n' + (tests - failed) + '/' + tests + ' passed');
  if (failed) process.exit(1);
})();
