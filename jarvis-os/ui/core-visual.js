// ui/core-visual.js -- the holographic JARVIS core.
//
// The permanent centre of the OS: a STAGE that the brain and its generated
// rings mount into (S4), and a CAPTION beneath it naming the state, the
// active goal, the current operation and its progress. S1 renders it from a
// model object; later slices feed that model from real services. The
// renderer returns references to everything it will ever update -- nothing
// re-queries the document, so a fake DOM with no selector engine can test it.
//
// S4 CHANGED THE SHAPE OF THIS FILE, AND ONE S1 TEST WITH IT. Named here
// rather than left for someone to notice in a diff, because editing a test
// to match the code is the move that must never happen unwatched:
//
//   test_jarvis_os_s1.js -- "the core renders rings, title, state, goal,
//   operation and meter" asserted THREE `.os-core__ring` divs. Those divs
//   are gone: the rings are now generated SVG in ui/core-rings.js, and the
//   centre belongs to the brain. That one assertion is repointed at the
//   stage element; everything else in that test is untouched and still
//   asserts the same things. The proposal called "S1's 28 tests keep
//   passing unchanged" an acceptance condition of this slice -- it was
//   checkably false when it was written, and this is the honest version.
//
// THE EXPORTED CONTRACT DOES NOT MOVE: createCore(doc, model) and
// updateCore(core, model) keep their signatures, the em-dash empty value,
// the clamped meter, null progress hiding the meter, and data-core-state
// written from the state id.
//
// One spelling of truth: the model carries the state ID (the same word the
// shell root wears in data-os-state) and the label is DERIVED through the
// states vocabulary -- the core and the root can no longer disagree on how
// a state is spelled (voice-line red pen, 2026-08-11).

import { getState } from '../core/states.js';

/**
 * @typedef {Object} CoreModel
 * @property {string}  [stateId]    system state id ('ready', 'working', ...)
 * @property {string}  [goal]       active goal, or nothing
 * @property {string}  [operation]  current operation, or nothing
 * @property {number|null} [progress]  0-100, or null for "no meter"
 */

const EMPTY = '—'; // an em dash: the honest empty value, never a fake one

/**
 * @param {Document} doc
 * @param {CoreModel} model
 * @returns {{el: Element, refs: Object}} the mounted core and its live refs
 */
export function createCore(doc, model = {}) {
  const el = doc.createElement('div');
  el.className = 'os-core';

  // The stage: an empty mount the brain and the rings attach into. It is
  // created here and left EMPTY on purpose -- core-visual imports neither of
  // them, so the core still renders in full with the whole S4 layer absent,
  // missing or broken. One broken instrument does not break JARVIS, applied
  // to the centrepiece itself.
  const stage = doc.createElement('div');
  stage.className = 'os-core__stage';
  el.appendChild(stage);

  const caption = doc.createElement('div');
  caption.className = 'os-core__caption';

  const title = doc.createElement('div');
  title.className = 'os-core__title';
  title.textContent = 'JARVIS';

  const state = doc.createElement('div');
  state.className = 'os-core__state';

  const goal = doc.createElement('div');
  goal.className = 'os-core__goal';

  const operation = doc.createElement('div');
  operation.className = 'os-core__operation';

  const meter = doc.createElement('div');
  meter.className = 'os-core__meter';
  const fill = doc.createElement('div');
  fill.className = 'os-core__meter-fill';
  meter.appendChild(fill);

  for (const part of [title, state, goal, operation, meter]) caption.appendChild(part);
  el.appendChild(caption);

  const refs = { state, goal, operation, meter, fill, stage, caption };
  updateCore({ el, refs }, model);
  return { el, refs };
}

/**
 * Update the core in place. Absent fields render the honest empty value;
 * progress is clamped to 0-100 (junk in must not draw a lying meter -- the
 * clampVol lesson) and null hides the meter entirely rather than showing 0%,
 * because "no reading" and "zero" are different truths.
 *
 * @param {{el: Element, refs: Object}} core
 * @param {CoreModel} model
 */
export function updateCore(core, model = {}) {
  const { el, refs } = core;
  const known = model.stateId ? getState(model.stateId) : undefined;
  refs.state.textContent = known ? known.label : EMPTY;
  refs.goal.textContent = model.goal || EMPTY;
  refs.operation.textContent = model.operation || EMPTY;

  const p = model.progress;
  if (p === null || p === undefined || Number.isNaN(Number(p))) {
    refs.meter.setAttribute('data-empty', 'true');
    refs.fill.style.width = '0%';
  } else {
    const clamped = Math.min(100, Math.max(0, Number(p)));
    refs.meter.setAttribute('data-empty', 'false');
    refs.fill.style.width = `${clamped}%`;
  }
  el.setAttribute('data-core-state', known ? known.id : 'none');
}
