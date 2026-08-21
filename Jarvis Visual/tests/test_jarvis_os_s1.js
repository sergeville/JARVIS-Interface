// test_jarvis_os_s1.js -- the S1 gate for the JARVIS OS skeleton.
//
// Imports the REAL modules from jarvis-os/ (ES modules, via dynamic import
// from this CommonJS harness) and runs them against a fake DOM, so the code
// under test is the code that ships. Source-reading checks strip nothing:
// the skeleton's tests assert behaviour, and where they must read source
// (CSS rules, import discipline) they say so and read the file raw.

'use strict';

const fs = require('fs');
const path = require('path');

const OS_DIR = path.join(__dirname, '..', '..', 'jarvis-os');

let passed = 0;
let failed = 0;
function ok(name, cond) {
  if (cond) { passed += 1; console.log(`  ok   ${name}`); }
  else { failed += 1; console.log(`  FAIL ${name}`); }
}

// ---- A fake DOM: exactly what the modules use, nothing more --------------

class FakeEl {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.attrs = {};
    this.style = {};
    this.className = '';
    this.textContent = '';
  }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
}
const fakeDoc = { createElement: (t) => new FakeEl(t) };

function walk(el, out = []) {
  out.push(el);
  for (const c of el.children) walk(c, out);
  return out;
}

(async () => {
  const layout = await import(path.join(OS_DIR, 'core', 'layout.js'));
  const states = await import(path.join(OS_DIR, 'core', 'states.js'));
  const coreVisual = await import(path.join(OS_DIR, 'ui', 'core-visual.js'));
  const mock = await import(path.join(OS_DIR, 'mock', 'state.js'));

  // ---- zones -------------------------------------------------------------

  const EXPECTED_ZONES = [
    'header', 'left-rail', 'core-stage', 'right-rail', 'floating-layer',
    'notification-layer', 'command-dock', 'footer', 'mobile-nav',
  ];
  const zoneIds = layout.ZONES.map((z) => z.id);
  ok('all nine zones are defined', EXPECTED_ZONES.every((id) => zoneIds.includes(id)) && zoneIds.length === 9);
  ok('zone ids are unique', new Set(zoneIds).size === zoneIds.length);
  ok('every zone carries a human name', layout.ZONES.every((z) => typeof z.name === 'string' && z.name.length > 0));

  const root = new FakeEl('div');
  const built = layout.buildLayout(fakeDoc, root, layout.ZONES);
  ok('the full config builds all nine zones', built.size === 9 && root.children.length === 9);
  ok('zones land in config order', root.children.map((el) => el.getAttribute('data-zone')).join(',') === zoneIds.join(','));

  const trimmedRoot = new FakeEl('div');
  const trimmed = layout.buildLayout(fakeDoc, trimmedRoot, layout.ZONES.slice(0, 3));
  ok('a trimmed config builds ONLY what it names -- zones are data, not markup',
    trimmed.size === 3 && trimmedRoot.children.length === 3 && !trimmed.has('footer'));

  const occupiedRoot = new FakeEl('div');
  occupiedRoot.appendChild(new FakeEl('div'));
  layout.buildLayout(fakeDoc, occupiedRoot, layout.ZONES.slice(0, 1));
  ok('buildLayout never destroys children it did not create', occupiedRoot.children.length === 2);

  const dupRoot = new FakeEl('div');
  const dupMap = layout.buildLayout(fakeDoc, dupRoot, [
    { id: 'header', name: 'First' }, { id: 'header', name: 'Second' }, { id: 'footer', name: 'Foot' },
  ]);
  ok('a duplicate zone id is skipped -- first wins, no orphan element, no lost handle',
    dupRoot.children.length === 2 && dupMap.size === 2 &&
    dupMap.get('header').children[0].textContent === 'First');

  // ---- system states -----------------------------------------------------

  const EXPECTED_STATES = [
    'starting', 'ready', 'working', 'degraded', 'offline', 'maintenance',
    'emergency-stop', 'recovering',
  ];
  const stateIds = states.SYSTEM_STATES.map((s) => s.id);
  ok('exactly the eight goal-document states exist',
    EXPECTED_STATES.every((id) => stateIds.includes(id)) && stateIds.length === 8);
  ok('state ids are unique', new Set(stateIds).size === stateIds.length);
  ok('every state keeps to the house tone vocabulary',
    states.SYSTEM_STATES.every((s) => ['ok', 'info', 'warn', 'bad'].includes(s.tone)));

  const shell = new FakeEl('div');
  ok('every known state applies as asked',
    stateIds.every((id) => states.applySystemState(shell, id) === true && shell.getAttribute('data-os-state') === id));

  const shell2 = new FakeEl('div');
  let threw = false;
  let refusedResult = null;
  try { refusedResult = states.applySystemState(shell2, 'quantum-overdrive'); } catch (e) { threw = true; }
  ok('an unknown state fails CLOSED to degraded, refused but never thrown',
    !threw && refusedResult === false && shell2.getAttribute('data-os-state') === 'degraded');

  // Source check, comments stripped: the fail-closed landing spot must not
  // live inside the list it guards -- a lookup into SYSTEM_STATES would
  // throw the day someone renames the 'degraded' entry (voice-line red pen).
  const statesSrc = fs.readFileSync(path.join(OS_DIR, 'core', 'states.js'), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  ok('the fallback is a constant outside the guarded list, not a lookup into it',
    /const state = known \? byId\.get\(id\) : FALLBACK;/.test(statesSrc) &&
    /const FALLBACK = \{/.test(statesSrc));

  // ---- state visuals in the CSS (source check, read raw) -----------------

  const css = fs.readFileSync(path.join(OS_DIR, 'ui', 'skeleton.css'), 'utf8');
  ok('the CSS carries one visual rule per system state',
    stateIds.every((id) => css.includes(`[data-os-state='${id}']`)));
  const rmBlock = css.split('prefers-reduced-motion')[1] || '';
  ok('reduced motion is honoured and it stops the animations',
    css.includes('prefers-reduced-motion: reduce') && rmBlock.includes('animation: none'));

  // ---- the core ----------------------------------------------------------

  const core = coreVisual.createCore(fakeDoc, { stateId: 'ready', goal: 'g', operation: 'o', progress: 40 });
  const all = walk(core.el);
  // REPOINTED BY S4, 2026-08-15, and disclosed here rather than left in a
  // diff. This assertion required THREE `.os-core__ring` divs. S4 deletes
  // them: the bezels are generated SVG (ui/core-rings.js) and the centre is
  // the brain (ui/brain-canvas.js). It now requires the STAGE those mount
  // into, which is the same claim -- "the core builds its visual layer" --
  // against the element that layer actually uses. Everything else in this
  // assertion is untouched and still checks exactly what it did.
  //
  // Editing a test to match the code is the move that must never happen
  // unwatched, so: the proposal called "S1's 28 tests keep passing
  // unchanged" an acceptance condition of S4. That was checkably false when
  // it was written -- this one test had to move, and this comment is the
  // watching.
  ok('the core renders its visual stage, title, state, goal, operation and meter',
    all.filter((el) => el.className === 'os-core__stage').length === 1 &&
    all.some((el) => el.className === 'os-core__title' && el.textContent === 'JARVIS') &&
    core.refs.state.textContent === 'READY' && core.refs.fill.style.width === '40%');

  ok('ONE spelling of truth -- the core carries the state ID the root wears, label derived',
    core.el.getAttribute('data-core-state') === 'ready');
  coreVisual.updateCore(core, { stateId: 'emergency-stop' });
  ok('the derived label comes from the vocabulary, spaces and all',
    core.refs.state.textContent === 'EMERGENCY STOP' &&
    core.el.getAttribute('data-core-state') === 'emergency-stop');
  coreVisual.updateCore(core, { stateId: 'quantum-overdrive' });
  ok('an unknown stateId renders the honest empty value, never an invented label',
    core.refs.state.textContent === '—' && core.el.getAttribute('data-core-state') === 'none');

  coreVisual.updateCore(core, { stateId: 'working', progress: 150 });
  const overClamped = core.refs.fill.style.width;
  coreVisual.updateCore(core, { stateId: 'working', progress: -5 });
  const underClamped = core.refs.fill.style.width;
  ok('progress is clamped -- junk in cannot draw a lying meter',
    overClamped === '100%' && underClamped === '0%');

  coreVisual.updateCore(core, { stateId: 'ready', progress: null });
  ok('null progress hides the meter -- "no reading" is not "zero"',
    core.refs.meter.getAttribute('data-empty') === 'true');

  coreVisual.updateCore(core, {});
  ok('absent fields render the honest empty value, never undefined',
    core.refs.goal.textContent === '—' && core.refs.state.textContent === '—');

  // ---- the mock is marked and quarantined --------------------------------

  const mockModels = [mock.MOCK_READY_MODEL, ...mock.MOCK_BOOT_SEQUENCE.map((s) => s.model)];
  ok('every mock goal and operation says (mock) on sight',
    mockModels.every((m) =>
      (!m.goal || m.goal.includes('(mock)')) && (!m.operation || m.operation.includes('(mock)'))));
  ok('every mock stateId is a word the vocabulary actually holds',
    mockModels.every((m) => !m.stateId || states.getState(m.stateId) !== undefined));

  // Comments stripped first, every import style matched -- a quarantine that
  // only catches single-quote static imports is a door with one lock
  // (test-adversary, 2026-08-11, on the S2 twins of this check).
  const stripComments = (src) => src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  const importsMock = (src) =>
    /(?:from\s*|import\s*\(\s*|require\s*\(\s*)['"`][^'"`]*mock\//.test(stripComments(src));
  const nonWiring = ['core/layout.js', 'core/states.js', 'ui/core-visual.js'];
  ok('only app.js imports from mock/ -- simulated data stays quarantined, in any import style',
    nonWiring.every((f) => !importsMock(fs.readFileSync(path.join(OS_DIR, f), 'utf8'))));

  // ---- the entry shell and the manifest ----------------------------------

  const html = fs.readFileSync(path.join(OS_DIR, 'index.html'), 'utf8');
  ok('index.html loads the app as an ES module into the root element',
    html.includes('type="module"') && html.includes('jarvis-os-root') && html.includes('<noscript>'));

  const manifest = JSON.parse(fs.readFileSync(path.join(OS_DIR, 'package.json'), 'utf8'));
  ok('the manifest declares ES modules and NO dependencies -- no toolchain by decision',
    manifest.type === 'module' && !('dependencies' in manifest) && !('devDependencies' in manifest));

  console.log(`\n${passed}/${passed + failed} passed`);
  if (failed > 0) process.exit(1);
})().catch((e) => {
  console.error('  FAIL suite errored:', e.message);
  process.exit(1);
});
