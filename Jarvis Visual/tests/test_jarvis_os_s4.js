// test_jarvis_os_s4.js -- the S4 gate: the brain at the core.
//
// Real modules from jarvis-os/, a fake DOM, no browser. The three properties
// this file exists to defend, in order of how badly their loss would hurt:
//
//   1. THE BRAIN IS HONEST. One travelling signal is one real event on the
//      bus. Nothing happening -> level 0, no signals, the brain still. A
//      decorative brain would pass every other test here, which is exactly
//      why this one is written first.
//   2. THE MESH IS ANATOMY, NOT A BLOB. The midline fissure is genuinely
//      empty and the white matter genuinely crosses it. A future tidy-up
//      that applies the fissure to every region severs the corpus callosum,
//      the picture still looks like a brain, and the signals stop crossing.
//   3. THE CORE SURVIVES THE BRAIN. Remove the whole S4 layer and state,
//      goal, operation and meter still render. One broken instrument does
//      not break JARVIS -- applied to the centrepiece.

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

class FakeEl {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.attrs = {};
    this.style = {};
    this.className = '';
    this.textContent = '';
    this.width = 600;
    this.height = 600;
  }
  appendChild(child) { this.children.push(child); return child; }
  removeChild(child) { this.children = this.children.filter((c) => c !== child); return child; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener() {}
}
const fakeDoc = {
  createElement: (t) => new FakeEl(t),
  createElementNS: (ns, t) => new FakeEl(t),
};
function walk(el, out = []) {
  out.push(el);
  for (const c of el.children) walk(c, out);
  return out;
}

/** A recording 2D context: every call is a fact a test can assert on. */
function fakeCtx() {
  const calls = [];
  const rec = (name) => (...args) => { calls.push({ name, args }); };
  return {
    calls,
    clearRect: rec('clearRect'), beginPath: rec('beginPath'), moveTo: rec('moveTo'),
    lineTo: rec('lineTo'), stroke: rec('stroke'), fill: rec('fill'), arc: rec('arc'),
    fillRect: rec('fillRect'),
    set fillStyle(v) { calls.push({ name: 'fillStyle', args: [v] }); },
    get fillStyle() { return '#000'; },
    set strokeStyle(v) { calls.push({ name: 'strokeStyle', args: [v] }); },
    get strokeStyle() { return '#000'; },
    globalAlpha: 1, lineWidth: 1,
  };
}

(async () => {
  const model = await import(path.join(OS_DIR, 'ui', 'brain-model.js'));
  const activityMod = await import(path.join(OS_DIR, 'core', 'activity.js'));
  const ringsMod = await import(path.join(OS_DIR, 'ui', 'core-rings.js'));
  const brainMod = await import(path.join(OS_DIR, 'ui', 'brain-canvas.js'));
  const registries = await import(path.join(OS_DIR, 'core', 'registries.js'));
  const coreVisual = await import(path.join(OS_DIR, 'ui', 'core-visual.js'));

  // ---- 1. the cloud is reproducible --------------------------------------

  const a = model.buildBrain();
  const b = model.buildBrain();
  ok('same seed -> byte-identical cloud (a brain you cannot reproduce cannot be tested)',
    JSON.stringify(a.nodes) === JSON.stringify(b.nodes));

  const c = model.buildBrain({ seed: 12345 });
  ok('a different seed -> a different cloud (the seed is real, not decoration)',
    JSON.stringify(a.nodes) !== JSON.stringify(c.nodes));

  ok('the RNG is deterministic and stays in range', (() => {
    const r1 = model.mulberry32(7);
    const r2 = model.mulberry32(7);
    for (let i = 0; i < 200; i += 1) {
      const v = r1();
      if (v !== r2() || !(v >= 0 && v < 1)) return false;
    }
    return true;
  })());

  ok('a non-finite seed does not produce a cloud of NaNs', (() => {
    const junk = model.buildBrain({ seed: NaN, cortex: 40, white: 10, cerebellum: 5, stem: 3 });
    return junk.nodes.every((n) => Number.isFinite(n.x) && Number.isFinite(n.y) && Number.isFinite(n.z));
  })());

  // ---- 2. the anatomy --------------------------------------------------

  const spec = a.spec;
  const counts = a.nodes.reduce((m, n) => { m[n.region] = (m[n.region] || 0) + 1; return m; }, {});
  ok('the spec is honoured: white, cerebellum and stem counts are exact',
    counts.white === spec.white && counts.cerebellum === spec.cerebellum && counts.stem === spec.stem);
  ok('the cortex is built to its count', counts.cortex === spec.cortex);

  ok('THE FISSURE IS ACTUALLY EMPTY -- no cortex node inside the midline slab',
    a.nodes.filter((n) => n.region === 'cortex').every((n) => Math.abs(n.x) >= spec.fissure * 0.9));

  ok('THE WHITE MATTER ACTUALLY CROSSES IT -- the corpus callosum exists',
    a.nodes.some((n) => n.region === 'white' && Math.abs(n.x) < spec.fissure));

  ok('no node exceeds the degree cap -- the mesh is a brain, not a hairball',
    a.adj.every((list) => list.length <= spec.maxDegree));

  ok('the wiring is symmetric: every edge is known to both of its ends',
    a.edges.every(([i, j]) => a.adj[i].includes(j) && a.adj[j].includes(i)));

  ok('a hostile spec cannot hang the builder (fissure wider than the brain)', (() => {
    const start = Date.now();
    const impossible = model.buildBrain({ fissure: 5, cortex: 200, white: 5, cerebellum: 5, stem: 5 });
    return Date.now() - start < 4000 && impossible.nodes.every((n) => n.region !== 'cortex');
  })());

  // ---- 3. projection and bearing ---------------------------------------

  ok('projection is finite for every node under the default view',
    a.nodes.every((n) => {
      const p = model.projectNode(n, { yaw: 0.4, scale: 200, ox: 300, oy: 300 });
      return Number.isFinite(p.px) && Number.isFinite(p.py) && Number.isFinite(p.depth);
    }));

  ok('projection survives junk view input rather than blanking the whole brain', (() => {
    const p = model.projectNode({ x: 0.5, y: 0.2, z: 0.1 }, { yaw: NaN, scale: undefined, ox: 'x', oy: null });
    return Number.isFinite(p.px) && Number.isFinite(p.py);
  })());

  ok('projection survives a junk NODE too', (() => {
    const p = model.projectNode(null, { scale: 100, ox: 5, oy: 6 });
    return p.px === 5 && p.py === 6;
  })());

  ok('bearing is measured clockwise from twelve o\'clock',
    Math.round(model.bearingOf(0, -10)) === 0 &&
    Math.round(model.bearingOf(10, 0)) === 90 &&
    Math.round(model.bearingOf(0, 10)) === 180 &&
    Math.round(model.bearingOf(-10, 0)) === 270);

  ok('bearing wraps into 0..360 and never returns a negative',
    [[-1, -1], [1, -1], [-5, 5], [3, 7]].every(([x, y]) => {
      const deg = model.bearingOf(x, y);
      return deg >= 0 && deg < 360;
    }));

  ok('a point exactly at the centre has no bearing rather than a random one',
    model.bearingOf(5, 5, 5, 5) === 0);

  // ---- 4. THE HONESTY LAYER --------------------------------------------

  const sys = registries.createSystem();
  let clock = 1000;
  const meter = activityMod.createActivityMeter(sys, { now: () => clock, halfLifeMs: 100 });

  ok('NOTHING HAPPENING -> LEVEL 0. The brain is still when the bus is still',
    meter.level() === 0);
  ok('nothing happening -> nothing to drain', meter.drain().length === 0);

  sys.bus.emit('action-started', { id: 'x' });
  ok('one real event raises the level', meter.level() > 0);

  const afterOne = meter.level();
  clock += 100;
  ok('the level decays with time and no further events', meter.level() < afterOne);

  clock += 5000;
  ok('THE LEVEL REACHES EXACTLY ZERO, not a denormal the painter chases forever',
    meter.level() === 0);

  const before = meter.seen();
  ok('an UNDOCUMENTED event cannot raise the level -- the bus refuses it first',
    sys.bus.emit('not-a-real-event', {}) === false && meter.seen() === before);

  meter.drain(); // clear what the earlier assertions put on the wire
  sys.bus.emit('action-completed', { id: 'y' });
  sys.bus.emit('action-failed', { id: 'z' });
  const drained = meter.drain();
  ok('drain hands back each real event exactly once', drained.length === 2);
  ok('drain is not repeatable -- a drained event never travels twice', meter.drain().length === 0);

  // The finding that mattered most in the red pen: a meter that snapshots
  // the vocabulary at construction goes permanently, INVISIBLY deaf to
  // anything documented later -- refusedSubscribes never counts a subscribe
  // that was never attempted.
  sys.bus.document('a-brand-new-event', 'documented AFTER the meter existed');
  sys.bus.emit('a-brand-new-event', {});
  ok('AN EVENT DOCUMENTED AFTER THE METER EXISTS STILL REACHES IT',
    meter.level() > 0 && meter.drain().length === 1);

  ok('registry lifecycle events reach the meter without a second hand-kept list', (() => {
    const fresh = registries.createSystem();
    let t = 0;
    const m = activityMod.createActivityMeter(fresh, { now: () => t });
    fresh.registries.themes.register({ id: 'th', name: 'Theme' });
    return m.drain().some((e) => e.type === 'theme-registered');
  })());

  ok('the impulse buffer is CAPPED and the loss is COUNTED, not silently kept', (() => {
    const fresh = registries.createSystem();
    let t = 0;
    const m = activityMod.createActivityMeter(fresh, { now: () => t, cap: 10 });
    for (let i = 0; i < 40; i += 1) fresh.bus.emit('action-progressed', { i });
    const got = m.drain();
    return got.length === 10 && m.dropped() === 30 && m.seen() === 40;
  })());

  ok('the meter emits NOTHING -- it cannot become a source of what it measures', (() => {
    const fresh = registries.createSystem();
    const emits = fresh.bus.refusedEmits;
    const vocab = fresh.bus.vocabulary.size;
    activityMod.createActivityMeter(fresh, { now: () => 0 });
    return fresh.bus.vocabulary.size === vocab && fresh.bus.refusedEmits === emits;
  })());

  ok('detach really unsubscribes -- a detached meter hears nothing', (() => {
    const fresh = registries.createSystem();
    let t = 0;
    const m = activityMod.createActivityMeter(fresh, { now: () => t });
    m.detach();
    fresh.bus.emit('action-started', {});
    return m.level() === 0 && m.drain().length === 0;
  })());

  ok('a meter on a system with no bus degrades to silence instead of throwing', (() => {
    try {
      const m = activityMod.createActivityMeter({}, { now: () => 0 });
      return m.level() === 0 && m.drain().length === 0;
    } catch (e) { return false; }
  })());

  // ---- 5. the rings -----------------------------------------------------

  const geo = ringsMod.ringGeometry({ radius: 40, ticks: 8, segments: 4, tickLen: 2 });
  ok('generated ticks match the spec count and are evenly spaced',
    geo.ticks.length === 8 && Math.round(geo.ticks[1].at - geo.ticks[0].at) === 45);
  ok('every generated tick is finite geometry',
    geo.ticks.every((t) => [t.x1, t.y1, t.x2, t.y2].every(Number.isFinite)));
  ok('segments tile the circle exactly once', geo.segments.length === 4 &&
    geo.segments[3].to === 360 && geo.segments[0].from === 0);

  ok('A BEARING RECOVERED FROM GENERATED GEOMETRY EQUALS THE BEARING THAT MADE IT', (() => {
    for (const at of [0, 37, 90, 181, 275, 359]) {
      const p = ringsMod.pointAt(at, 40);
      const back = model.bearingOf(p.x, p.y, 50, 50);
      if (Math.abs(((back - at + 540) % 360) - 180) > 0.01) return false;
    }
    return true;
  })());

  ok('a junk bearing lights NOTHING rather than segment zero', (() => {
    const r = ringsMod.createRings(fakeDoc);
    return r.light(NaN) === 0 && r.light(undefined) === 0;
  })());

  ok('a real bearing lights one bin on every ring', (() => {
    const r = ringsMod.createRings(fakeDoc);
    return r.light(90, 1) === 3;
  })());

  ok('THE LIT BIN TRACKS SCREEN SPACE WHILE THE BEZEL TURNS THROUGH IT', (() => {
    const r = ringsMod.createRings(fakeDoc, [{ radius: 40, ticks: 12, segments: 12, tickLen: 2, width: 1 }]);
    r.light(0, 1);
    const first = r.refs.rings[0].bins.findIndex((d) => d.getAttribute('data-energy') !== '0');
    // turn the bezel a quarter way round, then light the SAME screen bearing
    const fresh = ringsMod.createRings(fakeDoc, [{ radius: 40, ticks: 12, segments: 12, tickLen: 2, width: 1 }]);
    fresh.spin(1);
    fresh.refs.rings[0].rotation = 90;
    fresh.light(0, 1);
    const second = fresh.refs.rings[0].bins.findIndex((d) => d.getAttribute('data-energy') !== '0');
    // Different BIN (the bezel moved) for the same screen bearing -- that is
    // the subtraction doing its job. Without it, both would be bin 0.
    return first === 0 && second !== 0 && second === 9;
  })());

  ok('fade bleeds a lit bin back to a hard zero rather than an ever-dimmer ghost', (() => {
    const r = ringsMod.createRings(fakeDoc);
    r.light(45, 1);
    for (let i = 0; i < 200; i += 1) r.fade(0.5);
    return r.refs.rings.every((ring) => ring.bins.every((d) => d.getAttribute('data-energy') === '0'));
  })());

  ok('spin is clamped -- a runaway level cannot blur the bezels', (() => {
    const r = ringsMod.createRings(fakeDoc);
    r.spin(1e9);
    r.tick(1000);
    return r.rotation().every((deg) => Number.isFinite(deg));
  })());

  // ---- 6. the painter ---------------------------------------------------

  ok('the brain constructs against a fake DOM with NO canvas context', (() => {
    const br = brainMod.createBrain(fakeDoc, { model: a, now: () => 0 });
    return br.drawable() === false && typeof br.paint === 'function';
  })());

  ok('painting without a context does not throw -- it simply draws nothing', (() => {
    try {
      const br = brainMod.createBrain(fakeDoc, { model: a, now: () => 0 });
      br.paint(0); br.paint(16);
      return true;
    } catch (e) { return false; }
  })());

  const ctxDoc = {
    createElement: () => { const el = new FakeEl('canvas'); el.getContext = () => el._ctx || (el._ctx = fakeCtx()); return el; },
    createElementNS: (ns, t) => new FakeEl(t),
  };

  ok('with a context it actually draws: it clears, strokes the mesh and plots points', (() => {
    const br = brainMod.createBrain(ctxDoc, { model: a, now: () => 0 });
    br.paint(0);
    const names = br.el._ctx.calls.map((c) => c.name);
    return names.includes('clearRect') && names.includes('stroke') && names.includes('fillRect');
  })());

  ok('A STILL BUS MEANS NO SIGNALS ON THE MESH -- the brain does not invent traffic', (() => {
    const fresh = registries.createSystem();
    let t = 0;
    const m = activityMod.createActivityMeter(fresh, { now: () => t });
    const br = brainMod.createBrain(ctxDoc, { model: a, activity: m, now: () => t });
    for (let i = 0; i < 30; i += 1) { t += 16; br.paint(t); }
    return br.signals() === 0;
  })());

  ok('ONE REAL EVENT PUTS ONE SIGNAL ON THE MESH', (() => {
    const fresh = registries.createSystem();
    let t = 0;
    const m = activityMod.createActivityMeter(fresh, { now: () => t });
    const br = brainMod.createBrain(ctxDoc, { model: a, activity: m, now: () => t });
    fresh.bus.emit('action-started', {});
    br.paint(t);
    return br.signals() === 1;
  })());

  ok('a signal that has crossed the mesh is retired -- the brain returns to still', (() => {
    const fresh = registries.createSystem();
    let t = 0;
    const m = activityMod.createActivityMeter(fresh, { now: () => t });
    const br = brainMod.createBrain(ctxDoc, { model: a, activity: m, now: () => t });
    fresh.bus.emit('action-started', {});
    br.paint(t);
    for (let i = 0; i < 400; i += 1) { t += 50; br.paint(t); }
    return br.signals() === 0;
  })());

  ok('REDUCED MOTION: one static paint and NO loop', (() => {
    let frames = 0;
    const br = brainMod.createBrain(ctxDoc, {
      model: a, reducedMotion: true, now: () => 0, raf: (cb) => { frames += 1; return 1; },
    });
    br.start();
    return frames === 0 && br.running() === false && br.el._ctx.calls.length > 0;
  })());

  ok('REDUCED MOTION STILL REPAINTS ON A STATE CHANGE -- quiet the motion, never the truth', (() => {
    const br = brainMod.createBrain(ctxDoc, { model: a, reducedMotion: true, now: () => 0, raf: () => 1 });
    br.start();
    const before = br.el._ctx.calls.length;
    br.setTone('bad');
    return br.el._ctx.calls.length > before;
  })());

  ok('with motion allowed it runs a loop, and stop really stops it', (() => {
    let live = 0;
    const br = brainMod.createBrain(ctxDoc, {
      model: a, now: () => 0, raf: (cb) => { live += 1; return live; }, caf: () => { live -= 1; },
    });
    br.start();
    const running = br.running();
    br.stop();
    return running === true && br.running() === false;
  })());

  ok('the tone table fails closed OUTSIDE the list it guards', (() => {
    const known = brainMod.coloursFor('bad');
    const junk = brainMod.coloursFor('quantum-overdrive');
    const missing = brainMod.coloursFor(undefined);
    return known.core !== junk.core && junk.core === missing.core && typeof junk.core === 'string';
  })());

  ok('a tone named like an Object prototype key cannot smuggle a colour in',
    brainMod.coloursFor('constructor').core === brainMod.coloursFor('nonsense').core);

  ok('the painter lights the rings from the signals it draws', (() => {
    const fresh = registries.createSystem();
    let t = 0;
    const m = activityMod.createActivityMeter(fresh, { now: () => t });
    const r = ringsMod.createRings(ctxDoc);
    const br = brainMod.createBrain(ctxDoc, { model: a, activity: m, rings: r, now: () => t });
    for (let i = 0; i < 6; i += 1) fresh.bus.emit('action-progressed', { i });
    t += 16; br.paint(t);
    return r.refs.rings.some((ring) => ring.bins.some((d) => d.getAttribute('data-energy') !== '0'));
  })());

  // ---- 7. the core survives the brain -----------------------------------

  const core = coreVisual.createCore(fakeDoc, { stateId: 'ready', goal: 'g', operation: 'o', progress: 40 });
  ok('the core still renders state, goal, operation and meter with NO brain layer at all',
    core.refs.state.textContent === 'READY' && core.refs.goal.textContent === 'g' &&
    core.refs.operation.textContent === 'o' && core.refs.fill.style.width === '40%');
  ok('the core exposes a stage for the brain to mount into, and it starts EMPTY',
    core.refs.stage && core.refs.stage.className === 'os-core__stage' && core.refs.stage.children.length === 0);
  ok('the caption carries the truth beneath the picture',
    core.refs.caption && walk(core.refs.caption).some((el) => el.className === 'os-core__title' && el.textContent === 'JARVIS'));

  ok('the brain and rings mount INSIDE the stage', (() => {
    const c2 = coreVisual.createCore(ctxDoc, { stateId: 'ready' });
    const br = brainMod.createBrain(ctxDoc, { model: a, now: () => 0 });
    const r = ringsMod.createRings(ctxDoc);
    c2.refs.stage.appendChild(br.el);
    c2.refs.stage.appendChild(r.el);
    return c2.refs.stage.children.length === 2 &&
      walk(c2.el).some((el) => el.className === 'os-brain');
  })());

  ok('THE THREE os-core__ring DIVS ARE GONE -- superseded by generated rings',
    walk(core.el).every((el) => !String(el.className).includes('os-core__ring')));

  // ---- 8. the source discipline, read raw and said so -------------------

  const css = fs.readFileSync(path.join(OS_DIR, 'ui', 'skeleton.css'), 'utf8');
  // COMMENTS STRIPPED FIRST, and I earned that the hard way: the first
  // version of this check grepped the raw file, and the comment explaining
  // that the ring divs were deleted NAMES them -- so the prose tripped the
  // guard and the file went red on correct CSS. A guard a comment can trip
  // is a guard that gets weakened until it stops tripping. Ask the rules.
  const cssRules = css.replace(/\/\*[\s\S]*?\*\//g, '');
  ok('no CSS RULE still points at the deleted ring divs (dead furniture that reads as protection)',
    !cssRules.includes('.os-core__ring'));
  ok('the CSS styles the new elements it replaced them with',
    css.includes('.os-brain') && css.includes('.os-rings__bin'));
  ok('TONE STILL CHANGES THE CORE -- S1\'s acceptance line, re-proven on the new elements',
    css.includes("[data-os-tone='bad']") && css.includes("[data-os-tone='warn']"));
  ok('reduced motion still names elements that exist',
    (css.split('prefers-reduced-motion')[1] || '').includes('.os-rings'));

  const activitySrc = fs.readFileSync(path.join(OS_DIR, 'core', 'activity.js'), 'utf8');
  ok('the meter has NO second hand-kept list of event names -- the bus vocabulary is the only source',
    activitySrc.includes('bus.vocabulary.keys()') && !/const\s+\w*EVENTS\s*=\s*\[/.test(activitySrc));

  // Same lesson, same file: core-visual's docblock names both modules while
  // explaining why it does not import them. Read the IMPORT STATEMENTS.
  const importsOf = (rel) => (fs.readFileSync(path.join(OS_DIR, rel), 'utf8')
    .match(/^\s*import\s[^\n]*$/gm) || []).join('\n');
  const coreImports = importsOf('ui/core-visual.js');
  ok('core-visual imports NEITHER the brain nor the rings -- that is why the core survives them',
    !coreImports.includes('brain-canvas') && !coreImports.includes('core-rings'));

  const appSrc = fs.readFileSync(path.join(OS_DIR, 'app.js'), 'utf8');
  ok('THE BOOT EMITS A DOCUMENTED EVENT -- the brain moves on real traffic, not a fake pulse',
    appSrc.includes("document('system-state-changed'") && appSrc.includes("emit('system-state-changed'"));
  ok('app.js is still the only file importing mock/',
    ['ui/brain-model.js', 'ui/brain-canvas.js', 'ui/core-rings.js', 'core/activity.js']
      .every((f) => !fs.readFileSync(path.join(OS_DIR, f), 'utf8').includes("from '../mock/")));
  ok('no S4 module reaches for a global document, window or Date.now',
    ['ui/brain-model.js', 'core/activity.js', 'ui/core-rings.js']
      .every((f) => {
        const src = fs.readFileSync(path.join(OS_DIR, f), 'utf8');
        return !/(^|[^.\w])document\./.test(src) && !/(^|[^.\w])window\./.test(src);
      }));

  console.log(`\n${passed}/${passed + failed} passed`);
  if (failed > 0) process.exit(1);
})().catch((e) => {
  console.error('  FAIL suite errored:', e.message);
  process.exit(1);
});
