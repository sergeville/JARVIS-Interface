// test_jarvis_os_s2.js -- the S2 gate: contracts, registries, the event bus.
//
// Imports the REAL modules (dynamic import from this CommonJS harness). No
// DOM needed -- S2 is machinery. Where a check must read source (the
// coupling discipline), it says so and reads the files raw.

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

// Every source-reading check strips comments FIRST (Engineering Lessons --
// the better the comments, the more an unstripped check lies), and matches
// every import style: static either-quote, dynamic import(), require().
function stripComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
}
function importsFrom(src, pathFragment) {
  const re = new RegExp(
    String.raw`(?:from\s*|import\s*\(\s*|require\s*\(\s*)['"\`][^'"\`]*` + pathFragment,
  );
  return re.test(stripComments(src));
}

function goodInstrument(id = 'sample-agent') {
  return {
    id,
    name: 'Sample Agent',
    type: 'agent',
    capabilities: [], actions: [], panels: [], dataSources: [], permissions: [], events: [],
  };
}

(async () => {
  const contracts = await import(path.join(OS_DIR, 'types', 'contracts.js'));
  const { EventBus } = await import(path.join(OS_DIR, 'core', 'events.js'));
  const { Registry } = await import(path.join(OS_DIR, 'core', 'registry.js'));
  const { createSystem, GOAL_EVENTS } = await import(path.join(OS_DIR, 'core', 'registries.js'));

  // ---- contracts ---------------------------------------------------------

  ok('the ten registrable kinds exist, once each',
    contracts.KINDS.length === 10 && new Set(contracts.KINDS).size === 10);
  ok('every kind carries a required-fields contract',
    contracts.KINDS.every((k) => Array.isArray(contracts.REQUIRED_FIELDS[k]) && contracts.REQUIRED_FIELDS[k].includes('id')));

  ok('a complete instrument validates', contracts.validate('instrument', goodInstrument()).ok === true);
  ok('an instrument missing its declaration arrays is refused',
    contracts.validate('instrument', { id: 'x', name: 'X', type: 'agent' }).ok === false);
  ok('a declaration field that is not an array is refused',
    contracts.validate('instrument', { ...goodInstrument(), panels: 'none' }).ok === false);
  ok('a blank id is refused', contracts.validate('theme', { id: '  ', name: 'T' }).ok === false);
  ok('a missing required field is refused where NO other guard would catch it',
    contracts.validate('theme', { id: 't' }).ok === false &&
    contracts.validate('capability', { id: 'c' }).ok === false);
  ok('an unknown kind is refused', contracts.validate('gadget', { id: 'g' }).ok === false);
  let threw = false;
  try { contracts.validate('instrument', null); } catch (e) { threw = true; }
  ok('validate never throws -- a bad definition is a refusal, not an exception',
    !threw && contracts.validate('instrument', null).ok === false);

  let evilThrew = false;
  let evilVerdicts = [];
  try {
    evilVerdicts = ['constructor', '__proto__', 'toString', 'hasOwnProperty', 'valueOf', 42, null]
      .map((k) => contracts.validate(k, { id: 'x' }).ok);
  } catch (e) { evilThrew = true; }
  ok('an evil kind name refuses without throwing -- the spec lookup walks no prototype chain',
    !evilThrew && evilVerdicts.every((v) => v === false));
  ok('a definition carrying its fields only by inheritance is refused',
    contracts.validate('theme', Object.create({ id: 't', name: 'T' })).ok === false);
  ok('an id made of zero-width characters is refused -- invisible is empty',
    contracts.validate('theme', { id: '​﻿', name: 'T' }).ok === false);

  // ---- the event bus -----------------------------------------------------

  const bus = new EventBus();
  bus.document('test-ping', 'a test event');
  const got = [];
  const off = bus.on('test-ping', (p) => got.push(p));
  ok('a documented emit delivers its payload',
    bus.emit('test-ping', 42) === true && got.length === 1 && got[0] === 42);
  off();
  bus.emit('test-ping', 43);
  ok('unsubscribe stops delivery', got.length === 1);

  const heard = [];
  bus.on('test-ping', () => { throw new Error('bad listener'); });
  bus.on('test-ping', (p) => heard.push(p));
  const emitOk = bus.emit('test-ping', 'x');
  ok('a throwing listener is isolated -- counted, and the next listener still hears',
    emitOk === true && heard.length === 1 && bus.listenerFaults === 1);

  const ghost = [];
  bus.on('undocumented-whisper', (p) => ghost.push(p));
  ok('an UNDOCUMENTED emit is refused and delivers nothing',
    bus.emit('undocumented-whisper', 1) === false && ghost.length === 0 && bus.refusedEmits === 1);
  ok('an UNDOCUMENTED subscribe is refused and counted -- a typo cannot become silent deafness',
    bus.listenerCount('undocumented-whisper') === 0 && bus.refusedSubscribes === 1 &&
    (() => { bus.document('undocumented-whisper', 'now real'); const c = [];
      bus.on('undocumented-whisper', (p) => c.push(p)); bus.emit('undocumented-whisper', 9);
      return c.length === 1; })());

  // ---- emit delivers to a snapshot, not the live set ---------------------

  const snapBus = new EventBus();
  snapBus.document('snap', '');
  let newcomerCalls = 0;
  snapBus.on('snap', () => { snapBus.on('snap', () => { newcomerCalls += 1; }); });
  snapBus.emit('snap');
  const newcomerSilentInFlight = newcomerCalls === 0;
  snapBus.emit('snap');
  ok('a listener subscribed mid-emit stays silent for the in-flight event and hears the next',
    newcomerSilentInFlight && newcomerCalls >= 1);

  const starveBus = new EventBus();
  starveBus.document('snap', '');
  const victimHeard = [];
  let offVictim = null;
  starveBus.on('snap', () => { offVictim(); });
  offVictim = starveBus.on('snap', (p) => victimHeard.push(p));
  starveBus.emit('snap', 'x');
  ok('a listener unsubscribed mid-emit still hears the event already in the air',
    victimHeard.length === 1);

  const loopBus = new EventBus();
  loopBus.document('snap', '');
  let selfCalls = 0;
  const selfMultiplier = () => { selfCalls += 1; loopBus.on('snap', () => { selfCalls += 1; }); };
  loopBus.on('snap', selfMultiplier);
  loopBus.emit('snap');
  ok('a self-multiplying listener cannot make one emit run unboundedly', selfCalls === 1);

  const strictBus = new EventBus();
  strictBus.document('snap', '');
  const offJunk = strictBus.on('snap', 'not-a-function');
  const junkEmit = strictBus.emit('snap');
  offJunk();
  ok('a non-function subscriber is refused at the door -- no phantom faults at emit',
    junkEmit === true && strictBus.listenerFaults === 0 && strictBus.listenerCount('snap') === 0);

  // ---- one registry ------------------------------------------------------

  const rbus = new EventBus();
  const reg = new Registry('instrument', rbus);
  const announced = [];
  rbus.on('instrument-registered', (p) => announced.push(p.id));

  ok('a valid registration lands and is announced on the bus',
    reg.register(goodInstrument()).ok === true && announced.join() === 'sample-agent' && reg.list().length === 1);
  ok('an invalid registration is refused, stored nowhere, announced never',
    reg.register({ id: 'broken' }).ok === false && reg.list().length === 1 && announced.length === 1);
  ok('a duplicate id is refused -- update is the explicit path',
    reg.register(goodInstrument()).ok === false && reg.list().length === 1);

  ok('update patches in place and cannot smuggle a new id',
    reg.update('sample-agent', { name: 'Renamed' }).ok === true &&
    reg.get('sample-agent').def.name === 'Renamed' &&
    reg.update('sample-agent', { id: 'other' }).ok === false);
  ok('updating the unknown is a refusal, never an upsert',
    reg.update('nobody', { name: 'N' }).ok === false && reg.get('nobody') === undefined);
  let patchThrew = false;
  let patchVerdicts = [];
  try {
    patchVerdicts = [null, undefined, 42, 'rename', [1]].map((p) => reg.update('sample-agent', p).ok);
  } catch (e) { patchThrew = true; }
  ok('a non-object patch refuses without throwing -- it used to throw exactly on real data',
    !patchThrew && patchVerdicts.every((v) => v === false));
  ok('a patch that breaks the contract is refused and the original survives',
    reg.update('sample-agent', { panels: 'gone' }).ok === false &&
    Array.isArray(reg.get('sample-agent').def.panels));

  const lifecycle = [];
  for (const v of ['disabled', 'enabled', 'removed']) rbus.on(`instrument-${v}`, (p, t) => lifecycle.push(t));
  reg.disable('sample-agent');
  const hiddenWhileDisabled = reg.list().length === 0;
  const visibleOnAsk = reg.list({ includeDisabled: true }).length === 1;
  const stillAnswers = reg.get('sample-agent') !== undefined;
  reg.enable('sample-agent');
  const backAfterEnable = reg.list().length === 1;
  ok('disable hides from list, answers on ask, and enable restores',
    hiddenWhileDisabled && visibleOnAsk && stillAnswers && backAfterEnable);
  ok('remove forgets, and the unknown cannot be removed twice',
    reg.remove('sample-agent').ok === true && reg.get('sample-agent') === undefined &&
    reg.remove('sample-agent').ok === false);
  ok('every lifecycle change was announced',
    lifecycle.join(',') === 'instrument-disabled,instrument-enabled,instrument-removed');

  // ---- nobody holds a write pointer into the store -----------------------

  const vault = new Registry('instrument', new EventBus());
  const mine = goodInstrument('alpha');
  vault.register(mine);
  mine.capabilities.push({ id: 'smuggled' });
  mine.name = 'renamed-outside';
  ok('mutating the caller\'s object AFTER register changes nothing in the store',
    vault.get('alpha').def.capabilities.length === 0 && vault.get('alpha').def.name === 'Sample Agent');
  vault.get('alpha').def.panels = 'corrupted';
  vault.get('alpha').def.id = 'beta';
  ok('mutating a returned def changes nothing in the store -- get hands out clones',
    Array.isArray(vault.get('alpha').def.panels) && vault.get('alpha').def.id === 'alpha' &&
    vault.list()[0].id === 'alpha');
  const withFn = { ...goodInstrument('fn-bearer'), poke: () => {} };
  let fnThrew = false;
  let fnVerdict = null;
  try { fnVerdict = vault.register(withFn); } catch (e) { fnThrew = true; }
  ok('a definition that is not plain data is refused, not thrown, not stored',
    !fnThrew && fnVerdict.ok === false && vault.get('fn-bearer') === undefined);

  // ---- hostile shapes: the never-throws promise covers them too ----------
  // (reviewer, 2026-08-11: a Symbol detonated the refusal message's own
  // template literal, and throwing getters sailed through the spread)

  const sym = Symbol('evil');
  let hostileThrew = false;
  let hostileResults = [];
  try {
    hostileResults = [
      contracts.validate(sym, { id: 'x' }).ok,
      contracts.validate('theme', { id: sym, name: 'T' }).ok,
      contracts.validate('theme', { get id() { throw new Error('mine'); }, name: 'T' }).ok,
      vault.update(sym, { name: 'N' }).ok,
      vault.disable(sym).ok,
      vault.enable(sym).ok,
      vault.remove(sym).ok,
      vault.update('alpha', { get name() { throw new Error('mine'); } }).ok,
      vault.register({ get id() { throw new Error('mine'); } }).ok,
    ];
  } catch (e) { hostileThrew = true; }
  ok('hostile shapes -- Symbol kinds and ids, throwing getters -- refuse without throwing',
    !hostileThrew && hostileResults.length === 9 && hostileResults.every((v) => v === false));
  ok('a Symbol kind earns the SPECIFIC refusal, not the catch-all -- the message names it safely',
    contracts.validate(sym, { id: 'x' }).reason.includes('unknown kind'));
  ok('a hostile patch leaves the original untouched -- refusal means nothing was written',
    vault.get('alpha').def.name === 'Sample Agent' && vault.list().length === 1);

  // ---- the system --------------------------------------------------------

  const system = createSystem();
  const expectedRegistries = [
    'instruments', 'capabilities', 'panels', 'commands', 'actions',
    'events', 'dataProviders', 'plugins', 'permissions', 'themes',
  ];
  ok('the system carries all ten registries under their names',
    expectedRegistries.every((n) => system.registries[n] instanceof Registry));
  ok('the goals-document event vocabulary is documented before anyone speaks',
    GOAL_EVENTS.every(([t]) => system.bus.documented(t)) &&
    system.bus.documented('instrument-status-changed') && system.bus.documented('approval-required'));

  const sysHeard = [];
  system.bus.on('instrument-registered', (p) => sysHeard.push(p.id));
  system.registries.instruments.register(goodInstrument('demo'));
  ok('all registries speak on ONE shared bus', sysHeard.join() === 'demo');

  // ---- the coupling discipline (source check, read raw) ------------------

  const coreFiles = ['core/events.js', 'core/registry.js', 'core/registries.js', 'types/contracts.js'];
  ok('the machinery imports nothing from ui/ or mock/ in ANY style -- events are the only coupling',
    coreFiles.every((f) => {
      const src = fs.readFileSync(path.join(OS_DIR, f), 'utf8');
      return !importsFrom(src, 'ui/') && !importsFrom(src, 'mock/');
    }));
  ok('the ui renders without reaching into the registries, in any import style',
    ['ui/core-visual.js'].every((f) => !importsFrom(fs.readFileSync(path.join(OS_DIR, f), 'utf8'), 'registr')));
  ok('app.js births the system -- comments stripped first, so a commented copy of the line cannot stand in for it',
    /window\.JARVIS_OS\s*=\s*createSystem\(\)/.test(stripComments(fs.readFileSync(path.join(OS_DIR, 'app.js'), 'utf8'))));
  ok('every kind has its named home -- an 11th kind cannot land under "undefined"',
    contracts.KINDS.every((k) => {
      const reg = Object.values(system.registries).find((r) => r.kind === k);
      return reg !== undefined && !('undefined' in system.registries);
    }));

  console.log(`\n${passed}/${passed + failed} passed`);
  if (failed > 0) process.exit(1);
})().catch((e) => {
  console.error('  FAIL suite errored:', e.message);
  process.exit(1);
});
