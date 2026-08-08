#!/usr/bin/env node
// PHASE 7, SLICE ONE — THE SWITCHER: faces, jobs and departments.
//
// The face dial is style; the job dial is arrangement. The failures worth
// guarding are the ones that do not look like failures:
//
//   1. A JOB THAT TOUCHES STYLE, or a face that touches layout — decision 1
//      says neither does the other's work, and the moment one does, two dials
//      become one confusing dial.
//   2. A SECOND CODE PATH TO THE STAGE. A job that swapped the view itself
//      rather than calling setView() would leak the graph's 30 s timer, which
//      is invisible until the machine gets warm.
//   3. A DEPARTMENT THAT DOES NOT EXIST — army and airforce have no face yet,
//      so the naming table must fall back to the universal job name rather
//      than to an empty button.
//   4. JUNK IN STORAGE restoring an unarranged page — the clampVol lesson,
//      already paid for once on the volume slider and once on the face.

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const src = fs.readFileSync(path.join(__dirname, '..', 'jarvis.html'), 'utf8');

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log('ok   ' + name); passed++; }
  catch (e) { console.log('FAIL ' + name + '\n     ' + e.message); failed++; }
}

function fn(name) {
  const start = src.indexOf('function ' + name + '(');
  assert.ok(start !== -1, 'no function ' + name + ' in jarvis.html');
  let i = src.indexOf('{', start), depth = 0, end = -1;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}' && --depth === 0) { end = j + 1; break; }
  }
  assert.ok(end !== -1, name + ' has unbalanced braces');
  return src.slice(start, end);
}
function decl(name) {
  const m = new RegExp('const ' + name + ' = ([\\s\\S]*?);\\n').exec(src);
  assert.ok(m, 'no declaration for ' + name);
  return m[1];
}

const JOBS = eval('(' + decl('JOBS') + ')');
const DEPTS = eval('(' + decl('DEPTS') + ')');
const JOB_NAMES = Object.keys(JOBS);
const FACES = eval('(' + decl('FACES') + ')');

// --- the registries themselves -------------------------------------------

test('the four approved jobs are exactly the four in the plan', () => {
  assert.deepStrictEqual(JOB_NAMES.sort(),
    ['brainstorm', 'briefing', 'watch', 'workshop']);
});

test('every job names a stage the page can actually show', () => {
  for (const j of JOB_NAMES) {
    assert.ok(['avatar', 'graph'].includes(JOBS[j].stage),
      j + ' asks for a stage that does not exist: ' + JOBS[j].stage);
  }
});

test('every job carries a type scale, and it is a sane multiplier', () => {
  for (const j of JOB_NAMES) {
    const s = JOBS[j].typeScale;
    assert.strictEqual(typeof s, 'number', j + ' has no type scale');
    assert.ok(s >= 0.8 && s <= 1.5, j + ' scale ' + s + ' is off the dial');
  }
});

test('no job defines a colour — style belongs to the face (decision 1)', () => {
  const body = decl('JOBS');
  assert.ok(!/#[0-9a-f]{3,8}|rgba?\(|--(bg|text|accent)/i.test(body),
    'a job is touching style; that is the face dial\'s work');
});

test('every FACE has a complete department row, or falls back by rule', () => {
  const jobsCovered = (row) => JOB_NAMES.every(j => row[j]);
  for (const f of FACES) {
    assert.ok(DEPTS[f], 'shipped face ' + f + ' has no department row');
    assert.ok(jobsCovered(DEPTS[f]), 'face ' + f + ' is missing a department');
  }
});

test('the two unbuilt faces are named in the table, ready for their afternoon', () => {
  for (const f of ['army', 'airforce']) {
    assert.ok(DEPTS[f] && JOB_NAMES.every(j => DEPTS[f][j]),
      f + ' has no department row — the table is the approved one');
  }
});

test('the approved names are EXACTLY decision 7, not paraphrased', () => {
  assert.strictEqual(DEPTS.navy.watch, 'BRIDGE');
  assert.strictEqual(DEPTS.navy.workshop, 'ENGINEERING');
  assert.strictEqual(DEPTS.navy.brainstorm, 'CHART ROOM');
  assert.strictEqual(DEPTS.navy.briefing, 'COMMS');
  assert.strictEqual(DEPTS.airforce.briefing, 'FLIGHT BRIEF');
  assert.strictEqual(DEPTS.army.watch, 'COMMAND POST');
});

// --- the fallback, run rather than read ----------------------------------

const deptName = new Function('DEPTS', fn('deptName') + '\nreturn deptName;')(DEPTS);

test('a face with no table falls back to the universal job name', () => {
  assert.strictEqual(deptName('spacefarce', 'watch'), 'WATCH');
});

test('a missing CELL falls back too — never an empty button', () => {
  const partial = { navy: { watch: 'BRIDGE' } };
  const f = new Function('DEPTS', fn('deptName') + '\nreturn deptName;')(partial);
  assert.strictEqual(f('navy', 'briefing'), 'BRIEFING');
  assert.strictEqual(f('navy', 'watch'), 'BRIDGE');
});

test('civilian says the plain word — the dial is not a riddle in his own face', () => {
  for (const j of JOB_NAMES) {
    assert.strictEqual(DEPTS.civilian[j], j.toUpperCase());
  }
});

// --- one code path to the stage ------------------------------------------

test('applyJob reaches the stage through setView, not by hand', () => {
  const body = fn('applyJob');
  assert.ok(/setView\(JOBS\[j\]\.stage\)/.test(body),
    'the job does not call setView with its own stage');
  assert.ok(!/graphTimer|loadGraph|viewBtn\.textContent/.test(body),
    'the job is reimplementing the view swap — that leaks the graph timer');
});

test('setView exists as a function the button ALSO calls', () => {
  assert.ok(/function setView\(/.test(src), 'setView was inlined again');
  assert.ok(/viewBtn\.onclick = \(\) => setView\(/.test(src),
    'the button no longer goes through setView, so there are two paths again');
});

test('setView still owns the graph timer, both directions', () => {
  const body = fn('setView');
  assert.ok(/graphTimer = setInterval\(loadGraph/.test(body), 'the graph stopped refreshing');
  assert.ok(/clearInterval\(graphTimer\)/.test(body), 'leaving the graph leaks its timer');
});

// --- persistence, through validation -------------------------------------

test('the job is restored THROUGH validation, never applied raw', () => {
  const m = /applyJob\(localStorage\.getItem\('jarvisJob'\)\)/.exec(src);
  assert.ok(m, 'the job is not restored from storage at all');
  const body = fn('applyJob');
  assert.ok(/JOB_NAMES\.includes\(name\) \? name : 'watch'/.test(body),
    'junk in storage would restore an unarranged page');
});

test('the restore runs AFTER viewBtn exists (it would throw in the dead zone)', () => {
  assert.ok(src.indexOf("const viewBtn") < src.indexOf("localStorage.getItem('jarvisJob')"),
    'applyJob at boot would hit viewBtn in its temporal dead zone');
});

test('applying a job persists it, like the face does', () => {
  assert.ok(/setItem\('jarvisJob', j\)/.test(fn('applyJob')), 'the job is not saved');
});

// --- the switcher offers only what exists --------------------------------

test('no face or department name is written into the markup', () => {
  const sw = src.slice(src.indexOf('<div id="switcher">'), src.indexOf('</div>', src.indexOf('<div id="switcher">')));
  const forbidden = [...FACES.map(f => f.toUpperCase()),
                     ...Object.values(DEPTS.navy), ...Object.values(DEPTS.civilian)];
  for (const name of forbidden) {
    assert.ok(!sw.includes(name),
      name + ' is hardcoded in the switcher markup and could outlive its registry');
  }
});

test('the dials are built FROM the registries', () => {
  const body = fn('renderSwitcher');
  assert.ok(/build\(fd, FACES,/.test(body), 'the face dial is not built from FACES');
  assert.ok(/build\(jd, JOB_NAMES,/.test(body), 'the job dial is not built from JOB_NAMES');
  // Scoped to the BUILD CALL, not to the function. `deptName(face, j)` also
  // appears in the hover-title loop below, so a whole-function match stayed
  // green with the dial's own labels swapped to raw job names — the guard was
  // reading a different occurrence than the one it was written for. Same
  // first-match family as the three bugs this file's siblings have paid for.
  // The label argument is itself a lambda CONTAINING a comma, so a lazy
  // [^,]+ capture cuts it in half and the assertion fails against correct
  // code. Anchored on the next argument instead.
  const call = /build\(jd, JOB_NAMES, job, ([\s\S]*?), \(j\) =>/.exec(body);
  assert.ok(call, 'the job dial is not built with a label function at all');
  assert.ok(/deptName\(face, j\)/.test(call[1]),
    'the dial labels itself with raw job names — the naming layer is bypassed');
});

test('the label reads DEPT in a service face and JOB in civilian', () => {
  const body = fn('renderSwitcher');
  assert.ok(/face === 'civilian'\) \? 'JOB' : 'DEPT'/.test(body),
    'the switcher label does not follow the face');
});

test('hovering a department names the universal job underneath', () => {
  assert.ok(/' · the ' \+ j \+ ' job'/.test(fn('renderSwitcher')),
    'the two vocabularies would have to be memorised against each other');
});

// --- the avatar is exempt from every job (decision 9) --------------------

test('no job hides the stage or the avatar', () => {
  const body = decl('JOBS');
  assert.ok(!/hideAvatar|avatar: *false|display: *'none'/.test(body),
    'a job is hiding the avatar — decision 9 exempts it everywhere');
});

test('a job may take the graph ONLY while the avatar card exists to hold it', () => {
  // The real invariant, and the one that outlived the deferral. Decision 9
  // says no job may hide the avatar; the graph stage replaces it outright.
  // For one version watch held the avatar stage because the demoted card
  // existed only in the prototype — Serge: "Keep the avatar." The card is
  // what resolved it, and this is what keeps it resolved: delete the card and
  // every graph job becomes illegal again, loudly.
  const onGraph = JOB_NAMES.filter(j => JOBS[j].stage === 'graph');
  if (onGraph.length) {
    assert.ok(/id="avcard"/.test(src),
      onGraph.join(', ') + ' hides the avatar and there is no card to hold it');
  }
});

test('the card appears EXACTLY when the stage is not the avatar', () => {
  // Not "when watch is chosen" — the Vault Graph button can take the stage
  // from any job, and the avatar must not vanish because he pressed it.
  assert.ok(/avEl\.style\.display = \(view === 'avatar'\) \? 'none' : 'flex'/.test(src),
    'the card follows the job rather than the stage, so the button can hide the avatar');
});

test('the card is a MICROPHONE, through the existing handlers only', () => {
  const at = src.indexOf("const av = document.getElementById('avcard')");
  assert.ok(at !== -1, 'the avatar card is not wired at all');
  const block = src.slice(at, at + 1200);
  assert.ok(/press\(\);/.test(block) && /release\(\);/.test(block),
    'the card does not drive the real talk handlers');
  assert.ok(!/ensureMic|getUserMedia|capBufs|micCtx/.test(block),
    'the card opened its own microphone — a second path drops every mic rule');
});

test('HOLD talks and TAP brings the avatar back — the page\'s own gesture', () => {
  const at = src.indexOf("const av = document.getElementById('avcard')");
  const block = src.slice(at, at + 1200);
  assert.ok(/Date\.now\(\) - avT < 250/.test(block), 'the tap threshold is not the page\'s 250 ms');
  assert.ok(/if \(tap\) setView\('avatar'\)/.test(block), 'a tap does not restore the avatar');
  assert.ok(/release\(\);\n\s*if \(tap\)/.test(block),
    'the tap must still go through release(), or the capture is left open');
});

test('the card and the talk button agree on what HOT means', () => {
  assert.ok(/avEl\.classList\.toggle\('hot', capturing\)/.test(src),
    'the card shows hot from something other than the real capture flag');
});

test('the graph is still reachable — the deferral costs no feature', () => {
  assert.ok(/id="viewbtn"/.test(src) && /viewBtn\.onclick/.test(src),
    'the Vault Graph button is how the graph is reached; it must survive');
});

test('the type scale is applied by the JOB, on a variable, not per element', () => {
  assert.ok(/setProperty\('--type-scale', String\(JOBS\[j\]\.typeScale\)\)/.test(fn('applyJob')),
    'the type scale is not driven from the job registry');
  assert.ok(/var\(--type-scale, 1\)/.test(src), 'nothing consumes the type scale');
});

test('no FACE block defines the type scale — scale rides the job alone', () => {
  for (const f of FACES) {
    const at = src.indexOf('body.face-' + f + ' {');
    const b = src.slice(at, src.indexOf('}', at));
    assert.ok(!/--type-scale/.test(b), 'face ' + f + ' sets the type scale');
  }
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
