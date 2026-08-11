// core/layout.js -- the configurable layout zones.
//
// Zones are DATA, not markup: the shell builds whatever this list says, and
// nothing else. An instrument or panel is later assigned to a zone by
// configuration (S2's registries); no feature may hard-code itself into a
// position. Removing a zone from a config removes it from the page -- that
// property is load-bearing and tested.

/**
 * @typedef {Object} ZoneDefinition
 * @property {string} id    stable identifier, used as data-zone and CSS hook
 * @property {string} name  human label, shown while the skeleton is empty
 */

/** @type {ZoneDefinition[]} */
export const ZONES = [
  { id: 'header',             name: 'System Header' },
  { id: 'left-rail',          name: 'Left Instrument Rail' },
  { id: 'core-stage',         name: 'Central JARVIS Area' },
  { id: 'right-rail',         name: 'Right Detail Rail' },
  { id: 'floating-layer',     name: 'Floating Panels' },
  { id: 'notification-layer', name: 'Notifications' },
  { id: 'command-dock',       name: 'Command Dock' },
  { id: 'footer',             name: 'System Footer' },
  { id: 'mobile-nav',         name: 'Mobile Navigation' },
];

/**
 * Build the layout from a zone list. Only what the config names is built.
 *
 * @param {Document} doc    the document to create elements with (injected so
 *                          tests can hand in a fake -- no global reads)
 * @param {Element}  root   container to build into; existing children stay
 *                          untouched (the shell never destroys what it did
 *                          not create)
 * @param {ZoneDefinition[]} [zones]  defaults to ZONES
 * @returns {Map<string, Element>} zone id -> element
 */
export function buildLayout(doc, root, zones = ZONES) {
  const built = new Map();
  for (const zone of zones) {
    const el = doc.createElement('section');
    el.setAttribute('data-zone', zone.id);
    el.className = `os-zone os-zone--${zone.id}`;
    const label = doc.createElement('span');
    label.className = 'os-zone__label';
    label.textContent = zone.name;
    el.appendChild(label);
    root.appendChild(el);
    built.set(zone.id, el);
  }
  return built;
}
