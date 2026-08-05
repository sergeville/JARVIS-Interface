#!/usr/bin/env node
// Tests for the SESSIONS card -- Serge, 2026-08-05: "it would be cool if the
// session showed up in a card under the Active tasks."
//
// Run:  ./tests/run-tests.sh   (from Jarvis Visual/)
//    or  node tests/test_sessions_card.js
//
// As with the other page tests, the real functions are pulled out of
// jarvis.html and run against a DOM stub, so they cannot drift from what
// ships.
//
// Three ways this card can lie, and each has tests below:
//
//   1. It draws fewer sessions than are running. That is the bug the whole
//      registry exists to end, and putting it on screen makes it permanent.
//   2. The green "working now" dot sticks, or never lights. It is read as
//      "which Jarvis is busy", so a stuck dot is worse than no dot.
//   3. It rebuilds its DOM at the 15 Hz poll rate. Same guard the task card
//      and the events strip carry.
//
// The last block asserts the card is actually WIRED INTO the page -- markup
// present, renderSessions called from the poll. That guard is here because
// of this morning's lesson: 255 tests passed while `jarvis.sh sessions`
// reported zero live sessions. Tests prove the code; only checking the
// installation proves it is running.

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const HTML = path.join(__dirname, '..', 'jarvis.html');
const src = fs.readFileSync(HTML, 'utf8');

// ---- DOM stub -------------------------------------------------------------
// Attributes really store here (the hud_chrome stub no-ops them), because
// tickSessions round-trips the clocks through data-since / data-act.
let htmlWrites = 0;
function makeNode(id, cls) {
  const attrs = {};
  const n = {
    id, className: cls || '', textContent: '', title: '',
    style: {}, children: [],
    _html: '',
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = v; if (v === '') this.children = []; htmlWrites++; },
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return k in attrs ? attrs[k] : null; },
    appendChild(c) { this.children.push(c); },
  };
  return n;
}
const nodes = {
  'sessions': makeNode('sessions'),
  'sessions-body': makeNode('sessions-body'),
  'sessions-skew': makeNode('sessions-skew'),
};
function walk(node, out) {
  for (const c of node.children) { out.push(c); walk(c, out); }
  return out;
}
global.document = {
  getElementById: id => nodes[id] || null,
  createElement: () => makeNode(null),
  querySelectorAll: sel => {
    // Only the one selector the page uses.
    assert.strictEqual(sel, '#sessions-body .sess-meta');
    return walk(nodes['sessions-body'], []).filter(
      n => (n.className || '').split(/\s+/).includes('sess-meta'));
  },
};

// ---- pull the real functions out of the page ------------------------------
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
function num(name) {
  const m = src.match(new RegExp('const ' + name + '\\s*=\\s*(\\d+)'));
  assert.ok(m, name + ' not found in jarvis.html');
  return parseInt(m[1], 10);
}

const BUSY_WITHIN = num('BUSY_WITHIN');
let lastSessSig = '';
eval(grab('fmtDur') + '\n' + grab('sessBusy') + '\n' + grab('sessSig') + '\n'
   + grab('renderSessions') + '\n' + grab('tickSessions'));

// ---- harness --------------------------------------------------------------
let passed = 0, failed = 0;
function reset() {
  lastSessSig = '';
  nodes['sessions'].style = {};
  nodes['sessions-skew'].style = {};
  nodes['sessions-skew'].title = '';
  nodes['sessions-body'].children = [];
  nodes['sessions-body']._html = '';
  htmlWrites = 0;
}
function test(name, fn) {
  reset();
  try { fn(); passed++; console.log('ok   ' + name); }
  catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); }
}
const now = () => Date.now() / 1000;
const rows = () => nodes['sessions-body'].children;
const classes = i => (rows()[i].className || '').split(/\s+/);
const metaOf = i => rows()[i].children.find(
  c => (c.className || '').split(/\s+/).includes('sess-meta'));

function session(over) {
  return Object.assign({
    session_id: 'abc12345-0000-0000-0000-000000000000',
    pid: 16965, channel: 'voice line', model: 'claude-opus-5',
    cwd: '/Users/mike/Documents/Jarvis',
    transcript_path: '/Users/mike/.claude/projects/x/abc.jsonl',
    started_at: now() - 600, age: 600,
    last_activity: now() - 300, unregistered: false,
  }, over || {});
}

// ---- 1. it shows what is running -----------------------------------------

test('an empty list hides the card rather than drawing an empty box', () => {
  renderSessions([]);
  assert.strictEqual(nodes['sessions'].style.display, 'none');
});

test('one session shows the card and draws one row', () => {
  renderSessions([session()]);
  assert.strictEqual(nodes['sessions'].style.display, 'block');
  assert.strictEqual(rows().length, 1);
});

test('two sessions draw two rows -- the bug this card exists to expose', () => {
  renderSessions([session(), session({pid: 98650, session_id: '',
                                      unregistered: true})]);
  assert.strictEqual(rows().length, 2);
});

test('the face carries the channel and the pid, nothing else', () => {
  renderSessions([session()]);
  const who = rows()[0].children.find(c => c.className === 'who');
  assert.ok(who.textContent.includes('voice line'), who.textContent);
  assert.ok(who.textContent.includes('16965'), who.textContent);
  assert.ok(!who.textContent.includes('abc12345'), 'id belongs in the tooltip');
});

test('a session with no pid still renders instead of being skipped', () => {
  renderSessions([session({pid: null})]);
  assert.strictEqual(rows().length, 1);
});

// ---- 2. the three states --------------------------------------------------

test('an idle registered session is neither busy nor unregistered', () => {
  renderSessions([session({last_activity: now() - 600})]);
  assert.deepStrictEqual(classes(0), ['sess']);
});

test('a session that just wrote its transcript is busy (the green dot)', () => {
  renderSessions([session({last_activity: now() - 1})]);
  assert.ok(classes(0).includes('busy'));
});

test('activity older than BUSY_WITHIN is not busy', () => {
  renderSessions([session({last_activity: now() - (BUSY_WITHIN + 5)})]);
  assert.ok(!classes(0).includes('busy'));
});

test('a session with no activity at all is never busy', () => {
  renderSessions([session({last_activity: null})]);
  assert.ok(!classes(0).includes('busy'));
});

test('an unregistered session is amber', () => {
  renderSessions([session({unregistered: true, session_id: ''})]);
  assert.ok(classes(0).includes('unreg'));
});

test('unregistered wins over busy -- one row cannot claim two states', () => {
  renderSessions([session({unregistered: true, last_activity: now() - 1})]);
  assert.ok(classes(0).includes('unreg'));
  assert.ok(!classes(0).includes('busy'));
});

test('BUSY_WITHIN is a sane window', () => {
  // Guard the number, not just the logic: a huge value pins every dot green
  // and a zero pins them all dim. Both are silent failures.
  assert.ok(BUSY_WITHIN >= 5 && BUSY_WITHIN <= 120, 'BUSY_WITHIN=' + BUSY_WITHIN);
});

// ---- 3. the tooltip is the report ----------------------------------------

test('the tooltip carries the whole record', () => {
  renderSessions([session()]);
  const t = rows()[0].children.find(c => c.className === 'who').title;
  for (const bit of ['abc12345', 'voice line', 'claude-opus-5',
                     '/Users/mike/Documents/Jarvis', 'abc.jsonl']) {
    assert.ok(t.includes(bit), 'tooltip missing ' + bit + ': ' + t);
  }
});

test('an unregistered row explains the blank instead of showing nothing', () => {
  renderSessions([session({unregistered: true, session_id: '',
                           transcript_path: ''})]);
  const t = rows()[0].children.find(c => c.className === 'who').title;
  assert.ok(/unregistered/i.test(t), t);
  assert.ok(!/session\s+$/m.test(t), 'a bare empty session line reads as a bug');
});

// ---- 4. it must not rebuild at 15 Hz -------------------------------------

test('an unchanged payload does not rebuild the DOM', () => {
  const list = [session()];
  renderSessions(list);
  const after = htmlWrites;
  for (let i = 0; i < 15; i++) renderSessions(list);
  assert.strictEqual(htmlWrites, after, 'rebuilt while nothing changed');
});

test('a new session DOES rebuild', () => {
  renderSessions([session()]);
  const after = htmlWrites;
  renderSessions([session(), session({pid: 98650})]);
  assert.ok(htmlWrites > after, 'a new session must redraw');
});

test('a busy -> idle transition rebuilds, so the dot cannot stick', () => {
  // The signature has to carry the drawn state, not just identity.
  renderSessions([session({last_activity: now() - 1})]);
  const after = htmlWrites;
  renderSessions([session({last_activity: now() - 600})]);
  assert.ok(htmlWrites > after, 'the green dot would have stuck on');
});

test('the age changing alone does not rebuild', () => {
  renderSessions([session({age: 600})]);
  const after = htmlWrites;
  renderSessions([session({age: 601})]);
  assert.strictEqual(htmlWrites, after, 'age must not be in the signature');
});

// ---- 5. the clocks --------------------------------------------------------

test('tickSessions writes an up-time from data-since', () => {
  renderSessions([session({started_at: now() - 3600})]);
  tickSessions();
  assert.ok(/up\s+1h/.test(metaOf(0).textContent), metaOf(0).textContent);
});

test('tickSessions writes an idle time when there is activity', () => {
  renderSessions([session({last_activity: now() - 120})]);
  tickSessions();
  assert.ok(/idle/.test(metaOf(0).textContent), metaOf(0).textContent);
});

test('no activity means no idle clock, not "idle NaN"', () => {
  renderSessions([session({last_activity: null})]);
  tickSessions();
  const txt = metaOf(0).textContent;
  assert.ok(!/idle/.test(txt), txt);
  assert.ok(!/NaN/.test(txt), txt);
});

test('the clocks are drawn once on render, before any tick', () => {
  renderSessions([session({started_at: now() - 90})]);
  assert.ok(/up/.test(metaOf(0).textContent),
            'a fresh row must not sit blank for up to a second');
});

test('tickSessions with no rows does not throw', () => {
  renderSessions([]);
  tickSessions();
});

// ---- 5b. version skew: an old server can only see registered sessions ----

test('a payload with no unregistered field marks the card partial', () => {
  const old = session();
  delete old.unregistered;                 // what an old server serves
  renderSessions([old]);
  assert.strictEqual(nodes['sessions-skew'].style.display, 'inline');
  assert.ok(/restart/i.test(nodes['sessions-skew'].title),
            'the note must say what to do about it');
});

test('a current payload shows no partial marker', () => {
  renderSessions([session()]);
  assert.strictEqual(nodes['sessions-skew'].style.display, 'none');
});

test('unregistered:false is NOT mistaken for a missing field', () => {
  // `false` is the normal state of a registered session; only `undefined`
  // means the server never had the field at all.
  renderSessions([session({unregistered: false})]);
  assert.strictEqual(nodes['sessions-skew'].style.display, 'none');
});

// ---- 6. is it actually wired into the page? ------------------------------

test('the markup exists in jarvis.html', () => {
  assert.ok(src.includes('id="sessions"'), 'no #sessions card');
  assert.ok(src.includes('id="sessions-body"'), 'no #sessions-body');
});

test('the poll calls renderSessions', () => {
  assert.ok(/renderSessions\(d\.sessions/.test(src),
            'the card is never fed from /signals');
});

test('the 1 s tick drives the session clocks', () => {
  const tick = grab('tickAges');
  assert.ok(tick.includes('tickSessions()'),
            'up/idle would freeze between rebuilds');
});

test('the card sits under the task card, where Serge asked for it', () => {
  assert.ok(src.indexOf('id="tasks"') < src.indexOf('id="sessions"'),
            'sessions must come after tasks in the column');
});

// ---- done -----------------------------------------------------------------
console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
