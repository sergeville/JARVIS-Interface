#!/usr/bin/env node
// THE THREE CARDS THAT WRAPPED.
//
// Serge, 2026-08-09, reading his own screen: the stack rows broke their
// uptime across three lines, the sessions card cut a word in half, and the
// ports pod crammed three ports and a page clock onto one line and lost the
// end of it. All three are the same failure — a fixed-width slot given text
// that does not fit, with no instruction about what to give up.
//
// THE RULE THIS FILE DEFENDS: in a narrow panel, a line CLIPS, it does not
// wrap — and anything that can be clipped must be recoverable. A wrapped
// timestamp reads as three fragments of nothing; a clipped one still reads
// as a time. But a clipped NAME is a lost name, so it carries its full text
// in a tooltip. Clipping without recovery is just a nicer-looking data loss.
//
// These are CSS properties, which no other test in the suite looks at, and
// which fail silently — the page renders, it simply renders wrong.

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const src = fs.readFileSync(path.join(__dirname, '..', 'jarvis.html'), 'utf8');

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log('ok   ' + name); passed++; }
  catch (e) { console.log('FAIL ' + name + '\n     ' + e.message); failed++; }
}

// Read a rule body by its exact selector, so a second rule elsewhere cannot
// satisfy the assertion for it — the first-match trap this project has been
// bitten by nine times.
function rule(selector) {
  const i = src.indexOf(selector + ' {');
  assert.ok(i !== -1, 'no rule for ' + selector);
  const body = src.slice(i + selector.length, src.indexOf('}', i));
  // COMMENTS OUT FIRST. A `.sec-count` injection survived this file because
  // the comment inside that rule explains why `min-width: 0` is needed — so
  // deleting the real declaration left the words behind and the test passed.
  // Fourth time in one afternoon that a guard measured the prose beside the
  // code. Every rule reader in this project strips comments before looking.
  return body.replace(/\/\*[\s\S]*?\*\//g, '');
}

const CLIPPERS = [
  ['.st-sub',                    'the stack timestamps'],
  ['.st-row .name',              'the stack component names'],
  ['#sessions .sess .sess-meta', 'the session uptime and idle pair'],
  ['#pod-ports #page-age',       'the page clock in the footer'],
];

test('every narrow line CLIPS instead of wrapping', () => {
  for (const [sel, what] of CLIPPERS) {
    const r = rule(sel);
    assert.ok(/white-space:\s*nowrap/.test(r), what + ' can still wrap');
    assert.ok(/overflow:\s*hidden/.test(r), what + ' can overflow its card');
    assert.ok(/text-overflow:\s*ellipsis/.test(r),
      what + ' is cut with no sign that anything was cut');
  }
});

test('a clipping flex or grid child can actually shrink', () => {
  // min-width defaults to auto for flex and grid items, which means "never
  // smaller than my content" — so ellipsis silently does nothing and the
  // item pushes its neighbours out instead. This is the half of the fix
  // that looks unnecessary and is not.
  for (const sel of ['#sessions .sess .sess-meta', '.st-row .pid', '.sec-count']) {
    assert.ok(/min-width:\s*0/.test(rule(sel)),
      sel + ' cannot shrink, so its ellipsis will never trigger');
  }
});

test('IN THE STACK ROW THE NAME HOLDS AND THE NUMBER GIVES', () => {
  // Serge, 2026-08-09 ~4:53 PM, in a narrow window: "browser Jarvis" had
  // been clipped to "br...". The name was the row's only flexible part, so
  // it absorbed every pixel the PID column wanted — backwards. A two-letter
  // label names nothing; a PID is recoverable from its tooltip and from
  // `jarvis.sh status`. So the name gets a FLOOR and the number shrinks.
  const name = rule('.st-row .name');
  const m = /min-width:\s*([\d.]+)em/.exec(name);
  assert.ok(m, 'the stack name has no floor width — it can collapse again');
  assert.ok(parseFloat(m[1]) >= 6,
    'the floor is ' + m[1] + 'em, too narrow to hold a real component label');
  assert.ok(/min-width:\s*0/.test(rule('.st-row .pid')),
    'the PID will not yield, so the name will be the thing that does');
});

test('a clipped PID is recoverable too', () => {
  assert.ok(/<span class="pid" title="' \+ esc\(pid\) \+ '">/.test(src),
    'the PID clips with no way to read the whole thing');
});

// ---- the card headers, which wrapped the moment they grew counts ---------

test('a card header NEVER wraps — the title is what survives', () => {
  const r = rule('.sec-title');
  assert.ok(/white-space:\s*nowrap/.test(r),
    'SYS MONITOR can break in half again');
  assert.ok(/overflow:\s*hidden/.test(r), 'a long title can overflow its card');
  assert.ok(/min-width:\s*0/.test(r), 'the header cannot shrink inside its card');
});

test('the COUNT is what yields, not the title', () => {
  const r = rule('.sec-count');
  assert.ok(/white-space:\s*nowrap/.test(r), 'the count can drop to a second line');
  assert.ok(/overflow:\s*hidden/.test(r), 'the count can push the title around');
  assert.ok(/margin-left:\s*auto/.test(r), 'the count no longer sits at the right edge');
});

test('a clipped NAME keeps its full text in a tooltip', () => {
  // The one thing that must not be lost. The stack row's label is clipped
  // now, so it has to be recoverable on hover.
  assert.ok(/<span class="name" title="' \+ esc\(c\.label\) \+ '">/.test(src),
    'the stack name is clipped with no way to read the whole thing');
});

test('the tooltip text is ESCAPED — the label comes off disk', () => {
  // Same reason renderEvents escapes: these labels are written by scripts,
  // and a quote in one would otherwise close the attribute.
  const i = src.indexOf('<span class="name" title=');
  const line = src.slice(i, src.indexOf('\n', i));
  assert.ok(/esc\(c\.label\)/.test(line),
    'a component label reaches an HTML attribute unescaped');
});

test('the ports pod stacks its two readings instead of racing for one line', () => {
  const r = rule('#pod-ports');
  assert.ok(/flex-direction:\s*column/.test(r),
    'the ports and the page clock share a line again — the clock loses its tail');
  assert.ok(/min-width:\s*0/.test(r), 'the pod cannot shrink inside the footer');
});

test('the port pairs themselves never break mid-pair', () => {
  assert.ok(/#pod-ports \.ports-row > span \{ white-space: nowrap; \}/.test(src),
    'a port number can be separated from its state');
});

// ---- the events card: the one place that MUST still wrap ----------------

test('an event still WRAPS — it is not put on one clipped line', () => {
  // A locked reason, and it survives this change: "an event Serge cannot read
  // is the same as an event that was never logged." So this is deliberately
  // the opposite of every other rule in this file — no nowrap here.
  const r = rule('.ev-row .msg');
  assert.ok(!/white-space:\s*nowrap/.test(r),
    'an event is now clipped to one line — half a sentence names nothing');
});

test('but it CLAMPS at two lines, so one event cannot eat the card', () => {
  // His narrow window: a four-line event, three of them, filled the whole
  // panel — which hides the other events just as effectively as clipping.
  const r = rule('.ev-row .msg');
  const m = /-webkit-line-clamp:\s*(\d+)/.exec(r);
  assert.ok(m, 'the event text has no ceiling — it can run to four lines again');
  assert.ok(parseInt(m[1], 10) <= 2, 'the ceiling is ' + m[1] + ' lines, too tall');
  assert.ok(/-webkit-box-orient:\s*vertical/.test(r) && /display:\s*-webkit-box/.test(r),
    'the clamp has no box to work in, so it does nothing at all');
  assert.ok(/overflow:\s*hidden/.test(r), 'the clamped lines still render');
  assert.ok(/min-width:\s*0/.test(r), 'the message cannot shrink inside its row');
});

test('a clamped event is recoverable in full, and escaped', () => {
  assert.ok(/<div class="ev-row ' \+ kind \+ '" title="' \+ full \+ '">/.test(src),
    'a clamped event has no tooltip carrying the whole thing');
  assert.ok(/const full = esc\(e\.label\) \+ ' — ' \+ esc\(e\.detail\);/.test(src),
    'the event text reaches an HTML attribute unescaped — bash writes some of it');
});

test('nothing was "fixed" by shrinking the type instead', () => {
  // The lazy fix for a wrap is a smaller font, and it makes the panel
  // unreadable at his desk distance rather than at his screen distance.
  // These sizes are the ones that were there before the wrap fix.
  assert.ok(/font-size: 9\.5px/.test(rule('.st-sub')), '.st-sub type size changed');
  assert.ok(/font-size: 11\.5px/.test(rule('.st-row')), '.st-row type size changed');
});

console.log('\n' + passed + '/' + (passed + failed) + ' passed');
process.exit(failed ? 1 : 0);
