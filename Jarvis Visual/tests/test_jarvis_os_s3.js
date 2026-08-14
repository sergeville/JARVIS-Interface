// test_jarvis_os_s3.js -- the S3 gate: the universal instrument.
//
// Imports the REAL modules and drives the real system through the real
// orchestra against a fake DOM: registration is the only door, the bus the
// only wire, and this file proves the acceptance lines -- a registered
// instrument appears, a removed one vanishes without touching the layout,
// a broken one never breaks the shell.

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

function stripComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
}
// CSS gets its own strip: only block comments exist there, and reading the
// file raw lets commented-out chrome pass the gate (test-adversary,
// 2026-08-11 -- a /* */ around the blocked rule sailed through green).
function stripCssComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, '');
}
function importsFrom(src, pathFragment) {
  const re = new RegExp(
    String.raw`(?:from\s*|import\s*\(\s*|require\s*\(\s*)['"\`][^'"\`]*` + pathFragment,
  );
  return re.test(stripComments(src));
}

class FakeEl {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.attrs = {};
    this.style = {};
    this.className = '';
    this.textContent = '';
    this.handlers = {};
  }
  appendChild(child) { this.children.push(child); return child; }
  removeChild(child) {
    const i = this.children.indexOf(child);
    if (i >= 0) this.children.splice(i, 1);
    return child;
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(type, fn) { (this.handlers[type] ??= []).push(fn); }
  click() { for (const fn of this.handlers.click ?? []) fn({}); }
}
const fakeDoc = { createElement: (t) => new FakeEl(t) };

function walk(el, out = []) {
  out.push(el);
  for (const c of el.children) walk(c, out);
  return out;
}
function byClass(rootEl, cls) {
  return walk(rootEl).filter((el) => String(el.className).split(' ').includes(cls));
}

(async () => {
  const shell = await import(path.join(OS_DIR, 'instruments', 'instrument-shell.js'));
  const orbitMod = await import(path.join(OS_DIR, 'ui', 'orbit.js'));
  const detailMod = await import(path.join(OS_DIR, 'ui', 'detail-shell.js'));
  const { attachInstrumentLayer } = await import(path.join(OS_DIR, 'instruments', 'orchestra.js'));
  const { createSystem } = await import(path.join(OS_DIR, 'core', 'registries.js'));
  const mock = await import(path.join(OS_DIR, 'mock', 'instruments.js'));

  // ---- the twelve states -------------------------------------------------

  const EXPECTED = [
    'unconfigured', 'configuring', 'ready', 'idle', 'active', 'waiting',
    'paused', 'blocked', 'offline', 'error', 'completed', 'disabled',
  ];
  const ids = shell.INSTRUMENT_STATES.map((s) => s.id);
  ok('exactly the twelve goal-document instrument states exist',
    EXPECTED.every((id) => ids.includes(id)) && ids.length === 12 && new Set(ids).size === 12);
  ok('every instrument state keeps to the house tone vocabulary',
    shell.INSTRUMENT_STATES.every((s) => ['ok', 'info', 'warn', 'bad', 'off'].includes(s.tone)));
  ok('an unknown instrument state fails CLOSED to ERROR -- calmer would be a lie',
    shell.instrumentState('quantum-overdrive').id === 'error' &&
    shell.instrumentState('active').id === 'active');
  const shellSrc = stripComments(fs.readFileSync(path.join(OS_DIR, 'instruments', 'instrument-shell.js'), 'utf8'));
  ok('the fail-closed landing spot lives OUTSIDE the list it guards -- the S1 lesson, pre-applied',
    /const FALLBACK = \{/.test(shellSrc) && /byId\.get\(id\) \?\? FALLBACK/.test(shellSrc));

  // ---- the abbreviation --------------------------------------------------

  ok('abbrev honours a short icon, initials a two-word name, and never throws on junk',
    shell.abbrev({ icon: 'db' }) === 'DB' &&
    shell.abbrev({ name: 'Sample Agent (mock)' }) === 'SA' &&
    shell.abbrev({ name: 'Solo' }) === 'SO' &&
    shell.abbrev({}) === '??' &&
    shell.abbrev({ name: Symbol('x') }) === '??');

  // ---- one node ----------------------------------------------------------

  const node = shell.createInstrumentNode(fakeDoc, {
    id: 'n1', name: 'Node One', type: 'agent', demo: true,
  }, 'ready');
  ok('a node renders roundel, name, type, state -- and the DEMO brand when marked',
    node.refs.roundel.textContent === 'NO' && node.refs.name.textContent === 'Node One' &&
    node.refs.type.textContent === 'agent' && node.refs.state.textContent === 'READY' &&
    byClass(node.el, 'os-instrument__demo').length === 1);
  const plain = shell.createInstrumentNode(fakeDoc, { id: 'n2', name: 'Real Thing', type: 'service' });
  ok('an unmarked instrument carries no DEMO brand', byClass(plain.el, 'os-instrument__demo').length === 0);
  ok('the clipped name is recoverable on hover -- the node carries its full title',
    node.el.getAttribute('title') === 'Node One');
  node.setState('blocked');
  const blockedShown = node.el.getAttribute('data-instrument-state') === 'blocked';
  node.setState('nonsense');
  ok('setState repaints, and nonsense lands on ERROR',
    blockedShown && node.el.getAttribute('data-instrument-state') === 'error');

  // ---- the CSS carries the chrome ----------------------------------------

  const css = stripCssComments(fs.readFileSync(path.join(OS_DIR, 'ui', 'skeleton.css'), 'utf8'));
  ok('one visual rule per instrument state, all twelve',
    ids.every((id) => css.includes(`[data-instrument-state='${id}']`)));
  const rmBlock = css.split('prefers-reduced-motion')[1] || '';
  ok('reduced motion also stills the instrument states',
    rmBlock.includes('os-instrument__state'));
  ok('the DEMO brand has its style', css.includes('.os-instrument__demo'));

  // ---- orbit geometry (pure) ---------------------------------------------

  const four = orbitMod.orbitAngles([{}, {}, {}, {}]);
  const gaps = four.map((a, i) => (four[(i + 1) % 4] - a + 360) % 360);
  ok('four unhinted nodes share the circle evenly',
    new Set(four.map((a) => Math.round(a))).size === 4 && gaps.every((g) => Math.round(g) === 90));
  ok('a position hint is honoured and normalised',
    orbitMod.orbitAngles([{ position: 45 }])[0] === 45 &&
    orbitMod.orbitAngles([{ position: -90 }])[0] === 270 &&
    orbitMod.orbitAngles([{ position: 45 }, {}])[1] !== 45);

  const orbit = orbitMod.createOrbit(fakeDoc);
  const seatNodes = [1, 2, 3].map((i) => ({ el: new FakeEl('button'), def: {} }));
  orbit.seat(seatNodes);
  ok('seating draws one connection line per node and positions every node',
    orbit.svg.children.length === 3 &&
    seatNodes.every((n) => n.el.style.left && n.el.style.top) &&
    new Set(seatNodes.map((n) => n.el.style.left + n.el.style.top)).size === 3);
  orbit.seat(seatNodes.slice(0, 2));
  ok('reseating clears the old lines instead of stacking them', orbit.svg.children.length === 2);

  // ---- the detail shell: only declared sections --------------------------

  const detail = detailMod.createDetailShell(fakeDoc);
  const richDef = {
    id: 'rich', name: 'Rich', type: 'agent',
    description: 'says things',
    capabilities: [{ id: 'c1', name: 'Cap One' }],
    actions: [], panels: [], dataSources: [], permissions: [], events: [],
  };
  detail.open(richDef, 'active');
  const headings = byClass(detail.el, 'os-detail__heading').map((h) => h.textContent);
  ok('only declared sections render -- empty arrays are a decision to show nothing',
    detail.isOpen() && headings.includes('DESCRIPTION') && headings.includes('CAPABILITIES') &&
    !headings.includes('ACTIONS') && !headings.includes('PANELS') && headings.length === 2);
  ok('the head always names the instrument, its type and its state',
    byClass(detail.el, 'os-detail__title')[0].textContent === 'Rich' &&
    byClass(detail.el, 'os-detail__state')[0].textContent === 'ACTIVE');
  detail.close();
  ok('close closes', detail.isOpen() === false);
  detail.open({ id: 'bare', name: 'Bare', type: 't' }, 'idle');
  ok('an instrument declaring nothing gets a head and an empty body, never placeholders',
    detail.isOpen() && byClass(detail.el, 'os-detail__heading').length === 0);

  // ---- the orchestra: registration is the only door ----------------------

  const system = createSystem();
  const stage = new FakeEl('section');
  const floating = new FakeEl('section');
  const layer = attachInstrumentLayer(fakeDoc, system, stage, floating);

  for (const def of mock.MOCK_INSTRUMENTS) {
    const r = system.registries.instruments.register(def);
    if (!r.ok) console.error('  mock refused:', r.reason);
  }
  ok('registered instruments APPEAR -- four demos, four nodes, four lines',
    layer.nodes.size === 4 && layer.orbit.svg.children.length === 4 &&
    byClass(layer.orbit.el, 'os-instrument').length === 4);

  for (const [id, status] of Object.entries(mock.MOCK_STATUSES)) {
    system.bus.emit('instrument-status-changed', { id, status });
  }
  ok('status changes arrive over the bus and repaint the nodes',
    layer.nodes.get('demo-agent').el.getAttribute('data-instrument-state') === 'active' &&
    layer.nodes.get('demo-service').el.getAttribute('data-instrument-state') === 'offline');

  system.bus.emit('instrument-status-changed', { id: 'demo-agent', status: 'gibberish' });
  ok('a gibberish status through the wire lands on ERROR, not on a crash',
    layer.nodes.get('demo-agent').el.getAttribute('data-instrument-state') === 'error');

  system.registries.instruments.disable('demo-project');
  const dimmed = layer.nodes.get('demo-project').el.getAttribute('data-instrument-state') === 'disabled';
  system.registries.instruments.enable('demo-project');
  ok('disable dims to DISABLED and enable restores the last reported status',
    dimmed && layer.nodes.get('demo-project').el.getAttribute('data-instrument-state') === 'idle');

  layer.nodes.get('demo-database').el.click();
  ok('clicking a node opens its detail with only its declared sections',
    layer.detail.isOpen() &&
    byClass(layer.detail.el, 'os-detail__title')[0].textContent === 'Sample Database (mock)' &&
    byClass(layer.detail.el, 'os-detail__heading').map((h) => h.textContent).join(',') === 'DATA SOURCES');

  const broken = system.registries.instruments.register({ id: 'broken-demo' });
  ok('a broken definition is refused at the door -- no node, no crash, shell intact',
    broken.ok === false && layer.nodes.size === 4 && byClass(layer.orbit.el, 'os-instrument').length === 4);

  system.registries.instruments.remove('demo-service');
  ok('a removed instrument VANISHES and the orbit reseats -- the layout never changes',
    layer.nodes.size === 3 && byClass(layer.orbit.el, 'os-instrument').length === 3 &&
    layer.orbit.svg.children.length === 3 && stage.children.length === 1);

  for (const id of ['demo-agent', 'demo-project', 'demo-database']) {
    system.registries.instruments.remove(id);
  }
  ok('removing every demo empties the orbit by configuration alone',
    layer.nodes.size === 0 && byClass(layer.orbit.el, 'os-instrument').length === 0);

  layer.detach();
  system.registries.instruments.register(mock.MOCK_INSTRUMENTS[0]);
  ok('after detach the layer is deaf -- unsubscribe really unsubscribes',
    layer.nodes.size === 0);

  // ---- the sheet is a window, the ledger keeps the claim ------------------
  // The test-adversary's round on S3 (2026-08-11) plus the voice line's
  // red pen: every case below is a hole that was live in the audited tree.

  const sys2 = createSystem();
  const layer2 = attachInstrumentLayer(fakeDoc, sys2, new FakeEl('section'), new FakeEl('section'));
  const reg2 = sys2.registries.instruments;
  for (const def of mock.MOCK_INSTRUMENTS) reg2.register(def);

  const upOk = reg2.update('demo-agent', {
    name: 'Renamed Agent (mock)', description: 'now says other things (mock)',
  });
  const n2 = layer2.nodes.get('demo-agent');
  ok('an update repaints the node -- name and hover title follow the registry',
    upOk.ok === true && n2.refs.name.textContent === 'Renamed Agent (mock)' &&
    n2.el.getAttribute('title') === 'Renamed Agent (mock)');

  n2.el.click();
  ok('clicking after an update opens the CURRENT truth, not the registration snapshot',
    byClass(layer2.detail.el, 'os-detail__title')[0].textContent === 'Renamed Agent (mock)' &&
    byClass(layer2.detail.el, 'os-detail__content').some(
      (c) => c.textContent === 'now says other things (mock)'));

  reg2.update('demo-agent', { name: 'Renamed Twice (mock)' });
  ok('an update lands on the OPEN sheet -- the detail is a window, not a snapshot',
    byClass(layer2.detail.el, 'os-detail__title')[0].textContent === 'Renamed Twice (mock)');

  reg2.disable('demo-project');
  sys2.bus.emit('instrument-status-changed', { id: 'demo-project', status: 'active' });
  const stillDim = layer2.nodes.get('demo-project').el.getAttribute('data-instrument-state') === 'disabled';
  reg2.enable('demo-project');
  ok('a status event never wakes a disabled instrument -- and enable restores the newly reported status',
    stillDim && layer2.nodes.get('demo-project').el.getAttribute('data-instrument-state') === 'active');

  reg2.disable('demo-database');
  layer2.nodes.get('demo-database').el.click();
  ok('the sheet on a DISABLED instrument says DISABLED -- one truth on the page',
    byClass(layer2.detail.el, 'os-detail__state')[0].textContent === 'DISABLED');
  reg2.enable('demo-database');

  sys2.bus.emit('instrument-status-changed', { id: 'demo-database', status: 'blocked' });
  ok('a status change lands on the open sheet',
    byClass(layer2.detail.el, 'os-detail__state')[0].textContent === 'BLOCKED');

  sys2.bus.emit('instrument-status-changed', { id: 'demo-database', status: 'on-fire' });
  ok('a claim outside the vocabulary shows ERROR and keeps the raw claim recoverable on hover',
    byClass(layer2.detail.el, 'os-detail__state')[0].textContent === 'ERROR' &&
    String(byClass(layer2.detail.el, 'os-detail__state')[0].getAttribute('title')).includes('on-fire') &&
    layer2.nodes.get('demo-database').el.getAttribute('data-instrument-state') === 'error');

  reg2.remove('demo-database');
  ok('removing the open instrument closes its sheet -- no ghost titles',
    layer2.detail.isOpen() === false);

  const faultsBefore = sys2.bus.listenerFaults;
  for (const type of ['instrument-registered', 'instrument-updated', 'instrument-removed',
    'instrument-status-changed', 'instrument-disabled', 'instrument-enabled']) {
    sys2.bus.emit(type, undefined);
  }
  ok('payload-less emits leave every handler standing -- the honesty ledger stays flat',
    sys2.bus.listenerFaults === faultsBefore);

  const hintPair = orbitMod.orbitAngles([{ position: 270 }, {}]);
  ok('a free node never lands on a hinted seat -- it takes the arc between',
    hintPair[0] === 270 && hintPair[1] === 90);
  const spread = orbitMod.orbitAngles([{ position: 0 }, { position: 180 }, {}, {}]);
  ok('free nodes deal into the arcs between hints',
    spread[2] === 90 && spread[3] === 270);
  ok("the contract's numeric-string position hint is honoured",
    orbitMod.orbitAngles([{ position: '45' }])[0] === 45);

  ok('an emoji initial stays whole in the roundel -- no severed surrogate pairs',
    shell.abbrev({ name: '💾 Store' }) === '💾S');

  const d0 = detailMod.createDetailShell(fakeDoc);
  d0.open({ id: 'z', name: 'Z', type: 't', actions: [{ id: 0 }] }, 'idle');
  ok('a row item with id 0 renders its id -- zero is an id, not an absence',
    byClass(d0.el, 'os-detail__row')[0].textContent === '0');

  // ---- coupling and wiring -----------------------------------------------

  ok('the instrument layer imports no registry and no mock -- the system arrives as an argument',
    ['instruments/orchestra.js', 'instruments/instrument-shell.js'].every((f) => {
      const src = fs.readFileSync(path.join(OS_DIR, f), 'utf8');
      return !importsFrom(src, 'registr') && !importsFrom(src, 'mock/');
    }));
  ok('app.js attaches the layer to the living system',
    /window\.JARVIS_OS\.layer\s*=\s*attachInstrumentLayer\(/.test(
      stripComments(fs.readFileSync(path.join(OS_DIR, 'app.js'), 'utf8'))));

  // ---- the demos are marked, valid, and honest ---------------------------

  ok('four demo instruments, every one branded demo:true with (mock) in its name',
    mock.MOCK_INSTRUMENTS.length === 4 &&
    mock.MOCK_INSTRUMENTS.every((d) => d.demo === true && d.name.includes('(mock)')));
  ok('every demo status names an instrument that exists and a state the vocabulary holds',
    Object.entries(mock.MOCK_STATUSES).every(([id, st]) =>
      mock.MOCK_INSTRUMENTS.some((d) => d.id === id) && ids.includes(st)));

  console.log(`\n${passed}/${passed + failed} passed`);
  if (failed > 0) process.exit(1);
})().catch((e) => {
  console.error('  FAIL suite errored:', e.message);
  process.exit(1);
});
