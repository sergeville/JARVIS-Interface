// instruments/orchestra.js -- the shell listens, instruments appear.
//
// This is the layer the whole architecture promised: registration is the
// ONLY door, the bus is the ONLY wire. It receives the system as an
// argument -- it imports no registry, so the coupling discipline holds by
// construction -- and it keeps the orbit true to the registries' state:
// registered appears, updated repaints, removed vanishes, status changes
// repaint, disabled dims. Removing an instrument never touches the layout;
// the orbit reseats what remains.
//
// Two truths this file is careful about (test-adversary + red pen,
// 2026-08-11): the DETAIL SHEET is a window onto the registries, never a
// snapshot -- it re-reads the registry every time it shows anything, and it
// closes when its subject is removed. And the STATUS LEDGER records what an
// instrument CLAIMED beside what the vocabulary made of it, so a lying
// instrument stays diagnosable instead of being laundered into ERROR.

import { createInstrumentNode, instrumentState } from './instrument-shell.js';
import { createOrbit } from '../ui/orbit.js';
import { createDetailShell } from '../ui/detail-shell.js';

/**
 * Attach the instrument layer to a running system.
 *
 * @param {Document} doc
 * @param {{bus: Object, registries: Object}} system  handed in, never imported
 * @param {Element} stageMount     where the orbit lives (the core stage)
 * @param {Element} floatingMount  where the detail shell lives
 * @returns {{nodes: Map<string, Object>, orbit: Object, detail: Object, detach: () => void}}
 */
export function attachInstrumentLayer(doc, system, stageMount, floatingMount) {
  const orbit = createOrbit(doc);
  const detail = createDetailShell(doc);
  stageMount.appendChild(orbit.el);
  floatingMount.appendChild(detail.el);

  /** @type {Map<string, {el: Element, refs: Object, setState: Function, refresh: Function, def: Object}>} */
  const nodes = new Map();
  /**
   * What each instrument last CLAIMED over the wire, beside what the
   * vocabulary resolved it to. The claim is the diagnostic: "which
   * instrument is speaking a language the OS does not hold" is only
   * answerable if the raw word survives.
   * @type {Map<string, {claimed: string, resolved: string}>}
   */
  const statusById = new Map();

  const reseat = () => {
    orbit.seat([...nodes.values()]);
  };

  // Disabled-ness is the REGISTRY'S truth and is read from it, never
  // mirrored into a local set -- a hand-kept mirror is the guard-inside-
  // the-data shape this project has now hit three times.
  const isDisabled = (id) => {
    const item = system.registries.instruments.get(id);
    return item ? item.disabled : false;
  };

  // The one door the detail sheet opens through: registry re-read on every
  // call, so the sheet can never show a definition the store no longer holds.
  const openDetailFor = (id) => {
    const item = system.registries.instruments.get(id);
    if (!item) return;
    const rec = statusById.get(id);
    const stateId = item.disabled ? 'disabled' : (rec ? rec.resolved : 'unconfigured');
    detail.open(item.def, stateId, rec ? rec.claimed : undefined);
  };
  const refreshDetailIfOpen = (id) => {
    if (detail.currentId() === id) openDetailFor(id);
  };

  const offs = [];

  // Every handler tolerates a missing payload: the bus isolates a throwing
  // listener, but the shell's own handlers must not be what feeds the
  // honesty ledger.
  offs.push(system.bus.on('instrument-registered', (p) => {
    const { id } = p ?? {};
    const item = system.registries.instruments.get(id);
    if (!item) return; // removed before we heard; nothing to draw
    const stateId = statusById.get(id)?.resolved ?? 'unconfigured';
    const node = createInstrumentNode(doc, item.def, stateId);
    node.def = item.def;
    if (node.el.addEventListener) {
      node.el.addEventListener('click', () => openDetailFor(id));
    }
    nodes.set(id, node);
    orbit.el.appendChild(node.el);
    reseat();
  }));

  offs.push(system.bus.on('instrument-updated', (p) => {
    const { id } = p ?? {};
    const item = system.registries.instruments.get(id);
    const node = nodes.get(id);
    if (!item || !node) return;
    node.def = item.def;
    node.refresh(item.def);
    reseat(); // an updated position hint moves the seat
    refreshDetailIfOpen(id);
  }));

  offs.push(system.bus.on('instrument-removed', (p) => {
    const { id } = p ?? {};
    const node = nodes.get(id);
    if (!node) return;
    if (orbit.el.removeChild) orbit.el.removeChild(node.el);
    nodes.delete(id);
    statusById.delete(id);
    if (detail.currentId() === id) detail.close(); // no sheet titled by a ghost
    reseat();
  }));

  offs.push(system.bus.on('instrument-status-changed', (p) => {
    const { id, status } = p ?? {};
    const node = nodes.get(id);
    if (!node) return;
    statusById.set(id, { claimed: status, resolved: instrumentState(status).id });
    // A status report never wakes a deliberately-dimmed instrument: the
    // claim is recorded above, the paint waits for enable.
    if (!isDisabled(id)) node.setState(status);
    refreshDetailIfOpen(id);
  }));

  offs.push(system.bus.on('instrument-disabled', (p) => {
    const { id } = p ?? {};
    if (!nodes.has(id)) return;
    nodes.get(id).setState('disabled');
    refreshDetailIfOpen(id);
  }));

  offs.push(system.bus.on('instrument-enabled', (p) => {
    const { id } = p ?? {};
    const node = nodes.get(id);
    if (!node) return;
    node.setState(statusById.get(id)?.claimed ?? 'unconfigured');
    refreshDetailIfOpen(id);
  }));

  return {
    nodes,
    orbit,
    detail,
    detach: () => { for (const off of offs) off(); },
  };
}
