#!/usr/bin/env node
// Tests for the lost-permission notice in jarvis.html.
//
// Serge, 2026-08-06: "I press enter, whoop, it disappears... maybe that's
// the reason sometimes I think you're doing something, you're not, you're
// waiting for me and I don't know you're waiting for me."
//
// The action was never in doubt -- a cancelled request does not run. THE
// DEFECT IS THE SILENCE: the box vanished and he could not tell whether he
// had approved it, denied it, or killed it by typing. So what these guard
// is that the page says which happened, says it only when there is
// something to say, and does not let the notice disappear on its own --
// a warning that can also evaporate rebuilds the bug in a quieter costume.

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const src = fs.readFileSync(path.join(__dirname, '..', 'jarvis.html'), 'utf8');

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
function rule(sel) {
  let i = src.indexOf(sel + ' {');
  if (i === -1) {
    const re = new RegExp(sel.split(/\s+/).map(p =>
      p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+') + '\\s*\\{');
    const m = src.match(re);
    assert.ok(m, 'CSS rule is gone: ' + sel);
    i = m.index;
  }
  return src.slice(i, src.indexOf('}', i));
}

// ---- DOM stub -------------------------------------------------------------
const classes = new Set();
const lostBox = { classList: {
  add: c => classes.add(c), remove: c => classes.delete(c),
  contains: c => classes.has(c) } };
const lostText = { textContent: '' };
global.document = { getElementById: id =>
  id === 'approve-lost' ? lostBox :
  id === 'approve-lost-text' ? lostText : { onclick: null } };

eval(grab('lostWords') + '\n' + grab('showLostApproval'));

let passed = 0, failed = 0;
function test(name, fn) {
  classes.clear(); lostText.textContent = '';
  try { fn(); passed++; console.log('ok   ' + name); }
  catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + e.message); }
}
const shown = () => classes.has('on');

test('an INTERRUPTED request tells him it never ran', () => {
  showLostApproval({ reason: 'interrupted', tool: 'Bash', detail: 'rm -rf /tmp/x' });
  assert.ok(shown(), 'nothing was shown -- the box vanished silently again');
  assert.ok(/never ran/.test(lostText.textContent), lostText.textContent);
  assert.ok(lostText.textContent.includes('rm -rf /tmp/x'),
    'it does not say WHAT was cancelled');
});

test('it names the cause, because that is the thing he could not tell', () => {
  showLostApproval({ reason: 'interrupted', tool: 'Bash', detail: 'x' });
  assert.ok(/spoke or typed/.test(lostText.textContent), lostText.textContent);
});

test('a TIMED OUT request reads differently from an interrupted one', () => {
  showLostApproval({ reason: 'timeout', tool: 'Bash', detail: 'x' });
  const a = lostText.textContent;
  classes.clear();
  showLostApproval({ reason: 'interrupted', tool: 'Bash', detail: 'x' });
  assert.notStrictEqual(a, lostText.textContent,
    'both causes produce the same sentence -- he still cannot tell which happened');
});

test('an ANSWERED request says NOTHING', () => {
  // He clicked. Saying anything here is noise, and noise is what makes a
  // warning stop being read.
  showLostApproval({ reason: 'answered', tool: 'Bash', detail: 'x' });
  assert.ok(!shown(), 'it spoke on a request he actually answered');
});

test('an OLD SERVER sending no reason is silent, not wrong', () => {
  // The page ships to his tab the moment the file changes; the server only
  // changes on a restart. In that window `reason` does not exist, and
  // guessing would put a false sentence on his screen.
  showLostApproval({ id: 3 });
  assert.ok(!shown(), 'it invented a reason a stale server never sent');
  showLostApproval(null);
  assert.ok(!shown());
});

test('a long detail is clamped by the caller, not dumped', () => {
  const wire = src.slice(src.indexOf('showLostApproval(ev)'), src.length);
  assert.ok(/detail \|\| ''\)\.slice\(0, \d+\)/.test(src),
    'the detail is passed unclamped -- a 300-char command will blow out the bar');
});

test('the notice is STICKY -- nothing hides it but the dismiss button', () => {
  // A notice that fades is the original bug in a quieter costume.
  const js = src.slice(src.indexOf('const lostBox'), src.indexOf('// ---- left panel'));
  assert.ok(!/setTimeout/.test(js), 'the notice hides itself on a timer');
  const removals = (js.match(/lostBox\.classList\.remove/g) || []).length;
  assert.strictEqual(removals, 1,
    'more than one thing hides the notice -- one of them will surprise him');
  assert.ok(/approve-lost-x'\)\.onclick/.test(js),
    'the dismiss button is not wired');
});

test('it is wired into the approval_done branch', () => {
  const i = src.indexOf("ev.type === 'approval_done'");
  assert.ok(i !== -1, 'the approval_done branch is gone');
  const branch = src.slice(i, i + 600);
  assert.ok(/^[^/]*showLostApproval\(ev\)/m.test(
    branch.split('\n').filter(l => !l.trim().startsWith('//')).join('\n')),
    'showLostApproval is never called -- the notice can never appear');
});

test('the notice does not block the page', () => {
  // The request is over. A modal here would make a report into an obstacle.
  const r = rule('#approve-lost');
  assert.ok(/position: fixed/.test(r), 'the notice is not pinned');
  assert.ok(!/100vmax/.test(r),
    'it dims the page like the permission modal -- it is a report, not a question');
});

test('it wears the waiting amber, from tokens not literals', () => {
  const r = rule('#approve-lost');
  assert.ok(/var\(--warn-soft/.test(r),
    'the notice does not use the warn token -- it will drift from the alert theme');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
