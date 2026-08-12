// ui/detail-shell.js -- the reusable instrument detail sheet.
//
// Selecting an instrument opens this shell, and it renders ONLY the
// sections the definition declares -- the goals document's rule. A section
// with nothing to say gets no heading; absence is honest, a placeholder is
// not. Name, type and status always show: an instrument without those is
// not an instrument.

import { instrumentState } from '../instruments/instrument-shell.js';

/** The declarable sections, in display order: [key, heading]. */
export const DECLARED_SECTIONS = [
  ['description', 'DESCRIPTION'],
  ['capabilities', 'CAPABILITIES'],
  ['actions', 'ACTIONS'],
  ['panels', 'PANELS'],
  ['dataSources', 'DATA SOURCES'],
  ['permissions', 'PERMISSIONS'],
  ['events', 'EVENTS'],
];

/**
 * A section is declared when it is present and has content: a non-empty
 * string, or a non-empty array. An empty array is a decision to declare
 * nothing, and nothing is what it shows.
 * @param {*} v
 * @returns {boolean}
 */
export function declared(v) {
  if (typeof v === 'string') return v.trim() !== '';
  if (Array.isArray(v)) return v.length > 0;
  return false;
}

/**
 * @param {Document} doc
 * @returns {{el: Element, open: (def: Object, stateId: string, claimedId?: string) => void, close: () => void, isOpen: () => boolean, currentId: () => *}}
 */
export function createDetailShell(doc) {
  const el = doc.createElement('div');
  el.className = 'os-detail';
  el.setAttribute('data-open', 'false');

  const head = doc.createElement('div');
  head.className = 'os-detail__head';
  const title = doc.createElement('span');
  title.className = 'os-detail__title';
  const type = doc.createElement('span');
  type.className = 'os-detail__type';
  const state = doc.createElement('span');
  state.className = 'os-detail__state';
  const closeBtn = doc.createElement('button');
  closeBtn.className = 'os-detail__close';
  closeBtn.setAttribute('type', 'button');
  closeBtn.textContent = '✕';
  for (const part of [title, type, state, closeBtn]) head.appendChild(part);

  const body = doc.createElement('div');
  body.className = 'os-detail__body';

  el.appendChild(head);
  el.appendChild(body);

  let currentId = null;

  const close = () => {
    currentId = null;
    el.setAttribute('data-open', 'false');
  };
  if (closeBtn.addEventListener) closeBtn.addEventListener('click', close);

  const open = (def, stateId, claimedId) => {
    currentId = def && def.id != null ? def.id : null;
    title.textContent = def.name ?? def.id;
    type.textContent = def.type ?? '';
    const s = instrumentState(stateId);
    state.textContent = s.label;
    state.setAttribute('data-instrument-tone', s.tone);
    // The claim survives the coercion: an instrument speaking outside the
    // vocabulary shows its resolved state with the raw claim recoverable on
    // hover -- the house rule for anything the chrome cannot fit.
    if (claimedId !== undefined && instrumentState(claimedId).id !== claimedId) {
      state.setAttribute('title', `claimed '${String(claimedId)}' -- not in the vocabulary`);
    } else if (state.removeAttribute) {
      state.removeAttribute('title');
    }

    while (body.children.length > 0) body.removeChild(body.children[body.children.length - 1]);
    for (const [key, heading] of DECLARED_SECTIONS) {
      if (!declared(def[key])) continue;
      const section = doc.createElement('div');
      section.className = `os-detail__section os-detail__section--${key}`;
      const h = doc.createElement('div');
      h.className = 'os-detail__heading';
      h.textContent = heading;
      section.appendChild(h);
      const content = doc.createElement('div');
      content.className = 'os-detail__content';
      if (typeof def[key] === 'string') {
        content.textContent = def[key];
      } else {
        for (const item of def[key]) {
          const row = doc.createElement('div');
          row.className = 'os-detail__row';
          // != null, not truthiness: an id of 0 is an id, not an absence.
          const label = item && item.name != null ? item.name : (item && item.id != null ? item.id : '—');
          row.textContent = String(label);
          content.appendChild(row);
        }
      }
      section.appendChild(content);
      body.appendChild(section);
    }
    el.setAttribute('data-open', 'true');
  };

  return {
    el,
    open,
    close,
    isOpen: () => el.getAttribute('data-open') === 'true',
    // Who the sheet is about -- the orchestra keeps it a WINDOW onto the
    // registries, never a snapshot (test-adversary, 2026-08-11: the sheet
    // held stale truth three ways).
    currentId: () => currentId,
  };
}
