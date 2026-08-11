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
`test_jarvis_os_*.js` with the rest.

## What exists (S1)

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

## Extension points (they grow with the slices)

- **Add a zone:** one entry in `ZONES` (`core/layout.js`) plus its grid area
  in `ui/skeleton.css`. Nothing else.
- **Add a system state:** one entry in `SYSTEM_STATES` (`core/states.js`)
  plus its one visual rule in `ui/skeleton.css`. The distinctness test will
  hold you to the rule.
- Registries, instruments, panels, commands, providers and plugins arrive in
  S2–S6 per the approved proposal (vault: `JARVIS Adaptive OS Skeleton —
  First-Action Proposal.md`).
