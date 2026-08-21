# JARVIS OS — the Adaptive Operating System skeleton

The modular skeleton demanded by the goals document (vault:
`02 - Learning AI/JARVIS Adaptive OS Skeleton — Goals.md`), approved 2026-08-11.
Plain ES modules, JSDoc contracts, **no dependencies, no build step** — by
decision. The live page (`Jarvis Visual/jarvis.html`) is untouched by anything
here; integration is a later, separately-gated phase.

## Run it

    ./run.sh          # serves http://127.0.0.1:8090 (static files only)

Chrome will not load ES modules over `file://`, hence the tiny server. It is
not part of the voice stack and stops nothing but itself.

## Test it

The suite gate is the house one: `Jarvis Visual/tests/run-tests.sh` picks up
`test_jarvis_os_*.js` with the rest — one file per slice.

## What exists

**S1 — the shell.**

- `core/layout.js` — the nine layout zones, built from configuration only.
- `core/states.js` — the eight system states; unknown ids fail closed to
  DEGRADED, never applied raw, never thrown.
- `ui/core-visual.js` — the holographic core: rings, state, goal, operation,
  clamped progress meter. Renderers return refs; nothing re-queries the DOM.
- `ui/skeleton.css` — the concept's field, one visual rule per system state,
  reduced-motion support (animations stop, truth stays).
- `mock/state.js` — simulated data, every visible string marked "(mock)".
  Only `app.js` may import from `mock/`.
- `app.js` — thin wiring; the only file that touches globals.

**S2 — the spine: one bus, ten registries, one vocabulary.**

- `core/events.js` — the event bus, and the **only** channel between modules.
  A type must be documented before it may be emitted: an undocumented emit is
  refused, not delivered. A listener that throws is isolated, so one bad
  subscriber cannot take the bus down with it.
- `core/registry.js` — one registry, any kind: add, update, disable, enable,
  remove, all announced on the bus. **A refusal is a return value, never an
  exception, and never a partial write.**
- `core/registries.js` — `createSystem()`, the spine. Every registrable kind
  gets its registry on the shared bus, and the event vocabulary is documented
  before anything can speak.
- `types/contracts.js` — the ten kinds (`instrument`, `capability`, `panel`,
  `command`, `action`, `event`, `data-provider`, `plugin`, `permission`,
  `theme`), their required fields, and `validate()`. The typedefs are the
  documentation; `validate()` is the enforcement. *"One broken instrument does
  not break JARVIS"* starts at the front door.

**S3 — instruments, rendered from their definitions alone.**

- `instruments/instrument-shell.js` — one shell, any instrument. An instrument
  is anything the OS can represent — agent, service, project, database, device,
  something not yet named — and this renders every one of them from its
  registered definition. Nothing here knows Archon from a lawnmower.
- `instruments/orchestra.js` — the layer the architecture promised:
  **registration is the only door, the bus is the only wire.** It receives the
  system as an argument and imports no registry, so the coupling discipline
  holds by construction rather than by discipline.
- `ui/orbit.js` — pure placement: N nodes distributed evenly on the orbit,
  honouring a definition's optional angle hint. The connection lines are one
  SVG beneath the nodes.
- `ui/detail-shell.js` — the reusable detail sheet. It renders **only** the
  sections a definition declares: a section with nothing to say gets no
  heading, because absence is honest and a placeholder is not.
- `mock/instruments.js` — sample definitions, every visible string marked
  "(mock)".

## Extension points

They grow with the slices, and each is deliberately one edit:

- **Add a zone:** one entry in `ZONES` (`core/layout.js`) plus its grid area in
  `ui/skeleton.css`. Nothing else.
- **Add a system state:** one entry in `SYSTEM_STATES` (`core/states.js`) plus
  its one visual rule in `ui/skeleton.css`. The distinctness test will hold you
  to the rule.
- **Add an instrument:** register a definition that satisfies its contract.
  Nothing downstream is edited — not the orchestra, not the orbit, not the
  detail sheet. **That is the architecture's contact test**, and it is the
  reason the shell was built before anything real was plugged into it.
- **Add an event type:** document it on the bus first. An emit of an
  undocumented type is refused, so the vocabulary cannot drift by accident.

## What comes next

S4 onward per the approved proposal (vault: `JARVIS Adaptive OS Skeleton —
First-Action Proposal.md`). **This file describes what is committed to the
repository, and nothing else** — if a slice is in flight in someone's working
tree, it belongs in that slice's commit, not here.
