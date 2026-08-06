#!/usr/bin/env node
// Tests for the approve button's ANSWER path in jarvis.html.
//
// Serge, 2026-08-06 ~6:20 PM: "stuck in an endless loop... I click on
// approve, always come back."
//
// THE BUG. The popup is drawn from /signals -- plain polling, which survives
// a server restart because every poll is a fresh request. The answer went
// over the websocket, which does NOT survive one: it closes and the page only
// retries 2s later, while a fresh brain asks for its first permission about
// 1s after boot. So the first approval of every restart was sent into a dead
// socket, `catch(e){}` ate the failure, the box hid as though he had
// answered, and the next poll drew it again. Click, silence, redraw, forever.
//
// So these guard three properties, in order of how badly each one bit him:
//   1. THE BOX NEVER HIDES ON AN UNCONFIRMED CLICK.
//   2. A CLICK THAT CANNOT BE DELIVERED IS KEPT AND RETRIED, not discarded.
//   3. THE PAGE SAYS WHICH HAPPENED -- no empty catch anywhere in the path.

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const src = fs.readFileSync(path.join(__dirname, '..', 'jarvis.html'), 'utf8');

function grab(name) {
  const pats = ['async function ' + name + '(', 'function ' + name + '('];
  let start = -1;
  for (const p of pats) { const i = src.indexOf(p); if (i !== -1) { start = i; break; } }
  assert.ok(start !== -1, 'function not found in jarvis.html: ' + name);
  let i = src.indexOf('{', start), depth = 0, end = -1;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}') { depth--; if (depth === 0) { end = j + 1; break; } }
  }
  assert.ok(end !== -1, 'unbalanced braces reading ' + name);
  return src.slice(start, end);
}

// ---- DOM / network stubs --------------------------------------------------
const classes = new Set();
const box = { style: { display: 'none' } };
const note = { textContent: '' };
const head = { textContent: '' };
const detail = { textContent: '' };
global.document = {
  getElementById: id =>
    id === 'approve-note' ? note :
    id === 'approve-head' ? head :
    id === 'approve-detail' ? detail : { onclick: null },
  body: { classList: {
    add: c => classes.add(c), remove: c => classes.delete(c),
    contains: c => classes.has(c) } },
};
global.WebSocket = { OPEN: 1, CLOSED: 3, CONNECTING: 0 };

// The page declares these at module scope, outside the functions grabbed
// below, so the harness has to stand them up itself.
let approveBox = box;
const approveNote = note;
let approvalId = null;
let approvalHttp = false;
let approvalSending = false;
let approvalQueued = null;
let serverBoot = null;
let ws = null;
let posted = [];
let sent = [];
let connectCalls = 0;
let fetchImpl = null;

function connect(){ connectCalls++; }
global.fetch = (...a) => fetchImpl(...a);

eval(grab('approvalStatus') + '\n' + grab('retryWords') + '\n'
   + grab('deliverApproval') + '\n' + grab('answerApproval') + '\n'
   + grab('flushApproval') + '\n' + grab('approvalPoll') + '\n'
   + grab('showApproval'));

// ---- helpers --------------------------------------------------------------
function okServer() {
  fetchImpl = async (url, opt) => {
    posted.push({url, body: JSON.parse(opt.body)});
    return {ok: true, json: async () => ({ok: true})};
  };
}
function deadServer() {
  fetchImpl = async () => { throw new TypeError('Failed to fetch'); };
}
function refusingServer(error) {
  fetchImpl = async (url, opt) => {
    posted.push({url, body: JSON.parse(opt.body)});
    return {ok: true, json: async () => ({ok: false, error: error})};
  };
}
function openSocket() {
  ws = {readyState: WebSocket.OPEN, send: m => sent.push(JSON.parse(m))};
}
function deadSocket() {
  // A CLOSED WebSocket's send() DOES NOT THROW in a browser -- the spec says
  // the data is discarded silently. My first stub threw, which made the
  // readyState guard look untested: a fault removing it stayed green because
  // the throw covered for it. This is the real mechanism of Serge's endless
  // loop -- the click did not error, it simply evaporated.
  ws = {readyState: WebSocket.CLOSED, send: () => { sent.push('DISCARDED'); }};
}
function throwingSocket() {
  // CONNECTING does throw (InvalidStateError), so both shapes must be handled.
  ws = {readyState: WebSocket.CONNECTING,
        send: () => { throw new Error('InvalidStateError'); }};
}
function showing(id) {
  approvalId = null; box.style.display = 'none';
  showApproval({id: id, tool: 'Bash', detail: 'x'});
}

let passed = 0, failed = 0;
// SEQUENTIAL ON PURPOSE. These tests are async and share the page's own
// module-level state (approvalId, the queue). Firing them concurrently --
// which the first version of this runner did -- lets one test's request id
// land in another's assertion, and the failures look like page bugs. A
// harness that races is a harness that lies.
const queue = [];
function test(name, fn) { queue.push([name, fn]); }

async function runAll() {
  for (const [name, fn] of queue) {
    approvalId = null; approvalQueued = null; approvalSending = false;
    approvalHttp = false; serverBoot = null;
    posted = []; sent = []; connectCalls = 0;
    note.textContent = ''; box.style.display = 'none'; classes.clear();
    try { await fn(); passed++; console.log('ok   ' + name); }
    catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); }
  }
}

// ---- 1. the box never hides on an unconfirmed click -----------------------

test('a click into a dead server leaves the popup UP', async () => {
  approvalHttp = true; deadServer(); showing(1);
  await answerApproval(true);
  assert.strictEqual(box.style.display, 'block',
    'the box hid on a click that was never delivered -- the endless loop');
  assert.strictEqual(approvalId, 1, 'the request was forgotten');
});

test('a click into a dead SOCKET leaves the popup UP', async () => {
  approvalHttp = false; deadSocket(); showing(1);
  await answerApproval(true);
  assert.strictEqual(box.style.display, 'block');
});

test('a delivered answer still does not hide the box itself', async () => {
  // It goes away when the SERVER says so -- the approval_done push or the
  // poll dropping it. A click is a request, not a confirmation.
  approvalHttp = true; okServer(); showing(1);
  await answerApproval(true);
  assert.strictEqual(box.style.display, 'block',
    'the page hid the box on its own authority again');
});

test('the server clearing the request is what hides it', async () => {
  approvalHttp = true; okServer(); showing(1);
  await answerApproval(true);
  showApproval(null);
  assert.strictEqual(box.style.display, 'none');
  assert.strictEqual(approvalId, null);
});

// ---- 2. a click that cannot be delivered is KEPT --------------------------

test('an undelivered click is queued, not discarded', async () => {
  approvalHttp = true; deadServer(); showing(1);
  await answerApproval(false);
  assert.ok(approvalQueued, 'his decision was thrown away');
  assert.strictEqual(approvalQueued.id, 1);
  assert.strictEqual(approvalQueued.allow, false, 'a deny became something else');
});

test('the queued answer is delivered when the link comes back', async () => {
  approvalHttp = true; deadServer(); showing(1);
  await answerApproval(true);
  okServer();
  await flushApproval();
  assert.strictEqual(posted.length, 1, 'the retry never went');
  assert.strictEqual(posted[0].body.id, 1);
  assert.strictEqual(posted[0].body.allow, true);
  assert.strictEqual(approvalQueued, null, 'it would send forever');
});

test('a still-dead link keeps the answer queued rather than losing it', async () => {
  approvalHttp = true; deadServer(); showing(1);
  await answerApproval(true);
  await flushApproval();
  assert.ok(approvalQueued, 'a failed retry dropped his click');
});

test('a NEW request drops the stale queued answer', async () => {
  // Delivering an old id against a new request is worse than losing it:
  // it would answer a question he never saw.
  approvalHttp = true; deadServer(); showing(1);
  await answerApproval(true);
  assert.ok(approvalQueued);
  showApproval({id: 2, tool: 'Bash', detail: 'y'});
  assert.strictEqual(approvalQueued, null, 'a stale answer survived a new request');
});

test('an answered-and-cleared request drops the queue too', async () => {
  approvalHttp = true; deadServer(); showing(1);
  await answerApproval(true);
  showApproval(null);
  assert.strictEqual(approvalQueued, null);
});

// ---- THE WIRING, which the first gate never touched ----------------------
// The reviewer proved three edits that left all 33 tests green: delete the
// retry call, move it above showApproval, delete the capability read. They
// lived loose inside poll(), which no test extracts. Now they live in
// approvalPoll(d) and these drive it.

test('the poll reads the capability flag', async () => {
  approvalPoll({approval: null, approval_http: true, boot_id: 'b1'});
  assert.strictEqual(approvalHttp, true, 'the page would use the socket forever');
});

test('the poll RETRIES a queued answer', async () => {
  approvalHttp = true; deadServer();
  approvalPoll({approval: {id: 1, tool: 'Bash', detail: 'x'},
                approval_http: true, boot_id: 'b1'});
  await answerApproval(true);
  assert.ok(approvalQueued, 'setup');
  okServer();
  approvalPoll({approval: {id: 1, tool: 'Bash', detail: 'x'},
                approval_http: true, boot_id: 'b1'});
  await new Promise(r => setTimeout(r, 5));
  assert.strictEqual(posted.length, 1, 'the retry is not wired to the poll');
  assert.strictEqual(approvalQueued, null);
});

test('the retry runs after showApproval, so a new id drops it first', async () => {
  // Injection (b): move the flush above showApproval and it still passed --
  // because my order test only used a boot-id change, which is dropped
  // earlier anyway. THE case it misses is a NEW id in the SAME generation,
  // where showApproval is what clears the queue. Found by re-running the
  // reviewer's own four against the fix rather than trusting the fix.
  approvalHttp = true; deadServer();
  approvalPoll({approval: {id: 1, tool: 'Bash', detail: 'old'},
                approval_http: true, boot_id: 'b1'});
  await answerApproval(true);
  assert.ok(approvalQueued, 'setup');
  okServer();
  approvalPoll({approval: {id: 2, tool: 'Bash', detail: 'a NEW question'},
                approval_http: true, boot_id: 'b1'});
  await new Promise(r => setTimeout(r, 5));
  assert.strictEqual(posted.length, 0,
    'the verdict for #1 was POSTed while #2 was the pending request');
  assert.strictEqual(approvalQueued, null);
});

test('the retry runs AFTER the stale-drop, never before', async () => {
  // Order is the whole safety property: flushing first would ship the stale
  // verdict at the reused id before anything had a chance to drop it.
  approvalHttp = true; deadServer();
  approvalPoll({approval: {id: 1, tool: 'Bash', detail: 'old'},
                approval_http: true, boot_id: 'b1'});
  await answerApproval(true);
  okServer();
  approvalPoll({approval: {id: 1, tool: 'Bash', detail: 'NEW question'},
                approval_http: true, boot_id: 'b2'});
  await new Promise(r => setTimeout(r, 5));
  assert.strictEqual(posted.length, 0,
    'a stale verdict was POSTed against a new server generation');
});

// ---- id REUSE across a restart: the reviewer's finding 2 ------------------

test('a REUSED id from a NEW server does not inherit the queued answer', async () => {
  approvalHttp = true; deadServer();
  approvalPoll({approval: {id: 1, tool: 'Bash', detail: 'old'},
                approval_http: true, boot_id: 'b1'});
  await answerApproval(true);
  assert.ok(approvalQueued, 'setup');
  approvalPoll({approval: {id: 1, tool: 'Bash', detail: 'a different one'},
                approval_http: true, boot_id: 'b2'});
  assert.strictEqual(approvalQueued, null,
    'a stale ALLOW survived into a request he never saw');
});

test('a request that GOES AWAY drops the queue, even with no boot id', async () => {
  // The rule that protects him against a server too old to send boot_id.
  approvalHttp = true; deadServer();
  approvalPoll({approval: {id: 1, tool: 'Bash', detail: 'x'}, approval_http: true});
  await answerApproval(true);
  assert.ok(approvalQueued, 'setup');
  approvalPoll({approval: null, approval_http: true});
  assert.strictEqual(approvalQueued, null, 'a dead request kept its answer');
});

test('the SAME request across polls keeps its queued answer', async () => {
  // The drops must not be so eager that a genuine retry never happens.
  approvalHttp = true; deadServer();
  approvalPoll({approval: {id: 1, tool: 'Bash', detail: 'x'},
                approval_http: true, boot_id: 'b1'});
  await answerApproval(true);
  deadServer();
  approvalPoll({approval: {id: 1, tool: 'Bash', detail: 'x'},
                approval_http: true, boot_id: 'b1'});
  await new Promise(r => setTimeout(r, 5));
  assert.ok(approvalQueued, 'a valid queued answer was thrown away');
});

// ---- a later DENY must not lose to an earlier queued ALLOW ---------------

test('a flush in flight blocks a second send', async () => {
  approvalHttp = true; showing(1);
  let calls = 0;
  fetchImpl = async () => {
    calls++;
    await new Promise(r => setTimeout(r, 20));
    return {ok: true, json: async () => ({ok: true})};
  };
  approvalQueued = {id: 1, allow: true, boot: null};
  const f = flushApproval();
  await answerApproval(false);      // his change of mind, mid-flush
  await f;
  assert.strictEqual(calls, 1, 'an ALLOW and a DENY were both sent');
});

// ---- the refusal message tells the truth ---------------------------------

test('a server refusal does not claim the link is down', async () => {
  approvalHttp = true; refusingServer('already answered'); showing(1);
  await answerApproval(true);
  assert.ok(!/not connected/i.test(note.textContent),
    'it blamed the link when the link was fine: ' + note.textContent);
  assert.ok(/already answered/.test(note.textContent), note.textContent);
});

test('a genuine link failure still says so', async () => {
  approvalHttp = true; deadServer(); showing(1);
  await answerApproval(true);
  assert.ok(/not connected/i.test(note.textContent), note.textContent);
});

test('there is no empty catch in ANY function of the path', () => {
  // The old version read two of the three functions -- and the one it
  // skipped was the one that had it, shipped in the commit that claimed
  // otherwise. A guard scoped to where you expect the fault is a grep.
  const body = grab('answerApproval') + grab('deliverApproval')
             + grab('flushApproval') + grab('approvalPoll') + grab('retryWords');
  assert.ok(!/catch\s*\([^)]*\)\s*\{\s*(\/\*[^]*?\*\/|\/\/[^\n]*)?\s*\}/.test(body),
    'an empty catch is back in the approval path');
});

// ---- 3. the page says which happened --------------------------------------

test('a failed click says so, in words', async () => {
  approvalHttp = true; deadServer(); showing(1);
  await answerApproval(true);
  assert.ok(/not connected/i.test(note.textContent),
    'the click failed and the page said nothing: ' + JSON.stringify(note.textContent));
});

test('a delivered click says so too', async () => {
  approvalHttp = true; okServer(); showing(1);
  await answerApproval(true);
  assert.ok(/answered/i.test(note.textContent), note.textContent);
});

test('a server refusal is reported, not swallowed', async () => {
  approvalHttp = true; refusingServer('already answered'); showing(1);
  await answerApproval(true);
  assert.ok(note.textContent.length > 0, 'ok:false was treated as success');
  assert.ok(approvalQueued, 'a refused answer was neither kept nor reported');
});

test('the note is cleared when a new request arrives', async () => {
  approvalHttp = true; deadServer(); showing(1);
  await answerApproval(true);
  showApproval({id: 2, tool: 'Bash', detail: 'y'});
  assert.strictEqual(note.textContent, '', 'a stale status hung over a new request');
});

test('there is no empty catch left in the answer path', () => {
  // Third silent-failure bug on this page in one day. The class is the bug.
  const body = grab('answerApproval') + grab('deliverApproval');
  assert.ok(!/catch\s*\([^)]*\)\s*\{\s*\}/.test(body),
    'an empty catch is back in the approval path');
});

// ---- version skew ---------------------------------------------------------

test('against an OLD server the answer goes over the socket, not a 404', async () => {
  approvalHttp = false; openSocket(); showing(1);
  await answerApproval(true);
  assert.strictEqual(posted.length, 0, 'POSTed into a route that does not exist');
  assert.strictEqual(sent.length, 1, 'nothing reached the socket either');
  assert.strictEqual(sent[0].type, 'approval_reply');
  assert.strictEqual(sent[0].id, 1);
});

test('against a NEW server the answer goes over HTTP, not the socket', async () => {
  approvalHttp = true; okServer(); openSocket(); showing(1);
  await answerApproval(true);
  assert.strictEqual(posted.length, 1, 'the durable channel was not used');
  assert.strictEqual(posted[0].url, '/approval-reply');
  assert.strictEqual(sent.length, 0, 'it used the socket anyway');
});

test('a CLOSED socket that discards silently counts as UNDELIVERED', async () => {
  // The heart of the bug: no exception, no delivery, and the old code called
  // that success. Only the readyState check can tell the difference.
  approvalHttp = false; deadSocket(); showing(1);
  await answerApproval(true);
  assert.ok(approvalQueued, 'a silently discarded send was treated as delivered');
  assert.ok(/not connected/i.test(note.textContent), note.textContent);
  assert.strictEqual(box.style.display, 'block');
});

test('a CONNECTING socket that throws is also undelivered', async () => {
  approvalHttp = false; throwingSocket(); showing(1);
  await answerApproval(true);
  assert.ok(approvalQueued, 'a throwing send was treated as delivered');
});

test('a dead socket on the old path kicks a reconnect', async () => {
  approvalHttp = false; deadSocket(); showing(1);
  await answerApproval(true);
  assert.strictEqual(connectCalls, 1, 'it waited out the 2s timer instead');
});

test('a null socket does not throw an unhandled error', async () => {
  approvalHttp = false; ws = null; showing(1);
  await answerApproval(true);
  assert.ok(approvalQueued, 'the click vanished with no socket at all');
});

// ---- the double-click guard -----------------------------------------------

test('a second click while one is in flight is ignored', async () => {
  approvalHttp = true; showing(1);
  let calls = 0;
  fetchImpl = async () => {
    calls++;
    await new Promise(r => setTimeout(r, 10));
    return {ok: true, json: async () => ({ok: true})};
  };
  const a = answerApproval(true);
  const b = answerApproval(false);   // must not race the first
  await Promise.all([a, b]);
  assert.strictEqual(calls, 1, 'an allow and a deny were both sent');
});

test('a click with nothing pending sends nothing', async () => {
  approvalHttp = true; okServer(); approvalId = null;
  await answerApproval(true);
  assert.strictEqual(posted.length, 0);
});

runAll().then(() => {
  console.log('\n' + passed + ' passed, ' + failed + ' failed');
  if (failed) process.exit(1);
});
