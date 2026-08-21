// ui/brain-canvas.js -- the painter, and the only file here that owns a loop.
//
// It draws the cloud brain-model built, and it launches ONE travelling
// signal per REAL event drained from the activity meter. Nothing happening
// on the bus means nothing crossing the mesh: the brain goes still, the
// rings stop, and that stillness is the truth rather than a failure.
//
// TESTABLE WITHOUT A BROWSER, by construction. If the element cannot give a
// 2D context -- a fake DOM, a headless harness, a canvas-less environment --
// this returns a painter that draws nothing and says so through `drawable`,
// instead of throwing and taking the whole core down with it. That is the
// same doctrine core-visual.js follows, applied to the one file that has a
// real reason to touch a browser API.

import { buildBrain, projectNode, bearingOf } from './brain-model.js';

/**
 * Colour per system tone. THE FALLBACK LIVES OUTSIDE THE TABLE IT GUARDS --
 * S1's lesson pre-applied rather than re-learned: a lookup into the very
 * object it is protecting throws on exactly the input it exists to absorb.
 */
const TONE_COLOURS = {
  ok:   { core: '#39d98a', edge: 'rgba(57, 217, 138, 0.30)', signal: '#7ef7bd' },
  info: { core: '#4ea8ff', edge: 'rgba(78, 168, 255, 0.30)', signal: '#a8d6ff' },
  warn: { core: '#e0a63c', edge: 'rgba(224, 166, 60, 0.30)', signal: '#ffd489' },
  bad:  { core: '#e0523c', edge: 'rgba(224, 82, 60, 0.32)',  signal: '#ff9c88' },
};

/** @type {{core: string, edge: string, signal: string}} */
const FALLBACK_COLOURS = { core: '#4ea8ff', edge: 'rgba(78, 168, 255, 0.30)', signal: '#a8d6ff' };

/** @param {string} tone @returns {{core:string, edge:string, signal:string}} */
export function coloursFor(tone) {
  return Object.hasOwn(TONE_COLOURS, tone) ? TONE_COLOURS[tone] : FALLBACK_COLOURS;
}

/**
 * Create the brain layer.
 *
 * @param {Document} doc
 * @param {{
 *   model?: Object, activity?: Object, tone?: string, rings?: Object,
 *   reducedMotion?: boolean, now?: () => number,
 *   raf?: (cb: Function) => number, caf?: (id: number) => void,
 *   spec?: Object
 * }} [opts]
 * @returns {{el: Element, paint: (t?: number) => void, start: () => void,
 *            stop: () => void, setTone: (t: string) => void,
 *            running: () => boolean, drawable: () => boolean,
 *            signals: () => number, model: Object}}
 */
export function createBrain(doc, opts = {}) {
  const el = doc.createElement('canvas');
  el.className = 'os-brain';
  el.setAttribute('aria-hidden', 'true'); // a picture; the caption speaks

  const model = opts.model ?? buildBrain(opts.spec ?? {});
  const activity = opts.activity ?? null;
  const rings = opts.rings ?? null;
  const now = typeof opts.now === 'function' ? opts.now : () => Date.now();
  const reduced = opts.reducedMotion === true;
  const raf = typeof opts.raf === 'function' ? opts.raf
    : (typeof globalThis.requestAnimationFrame === 'function'
      ? globalThis.requestAnimationFrame.bind(globalThis) : null);
  const caf = typeof opts.caf === 'function' ? opts.caf
    : (typeof globalThis.cancelAnimationFrame === 'function'
      ? globalThis.cancelAnimationFrame.bind(globalThis) : null);

  let tone = typeof opts.tone === 'string' ? opts.tone : 'info';
  let handle = null;
  let last = now();
  let yaw = 0;

  /** @type {{edge: [number, number], t: number, speed: number}[]} */
  let signals = [];

  const ctx = (() => {
    try {
      return typeof el.getContext === 'function' ? el.getContext('2d') : null;
    } catch (e) {
      return null;
    }
  })();

  const size = () => ({
    w: Number(el.width) || 600,
    h: Number(el.height) || 600,
  });

  /**
   * Take the real events waiting in the meter and put one signal on the mesh
   * for each. This is the whole honesty of the slice in four lines: no
   * events, no signals.
   */
  const enlist = () => {
    if (!activity || typeof activity.drain !== 'function') return 0;
    const events = activity.drain();
    if (!events || events.length === 0) return 0;
    const edges = model.edges ?? [];
    if (edges.length === 0) return 0;
    let added = 0;
    for (let i = 0; i < events.length; i += 1) {
      // Deterministic placement: the nth event of a batch lands on a spread
      // of the mesh rather than at random, so a test can predict it and a
      // reader can see there is no hidden RNG driving the picture.
      const idx = (signals.length * 7 + i * 131 + events.length) % edges.length;
      signals.push({ edge: edges[idx], t: 0, speed: 0.6 + (i % 5) * 0.12 });
      added += 1;
    }
    // The same cap discipline the meter uses: a painter that never drains
    // (reduced motion, hidden tab) must not accumulate for the session.
    if (signals.length > 400) signals = signals.slice(-400);
    return added;
  };

  const paint = (t) => {
    const stamp = Number.isFinite(t) ? t : now();
    const dt = Math.max(0, Math.min(120, stamp - last));
    last = stamp;

    const level = activity && typeof activity.level === 'function' ? activity.level() : 0;
    enlist();

    if (rings) {
      // Ring speed rides on activity -- still bus, still bezels.
      if (typeof rings.spin === 'function') rings.spin(0.35 + level * 6);
      if (typeof rings.tick === 'function') rings.tick(dt);
      if (typeof rings.fade === 'function') rings.fade(0.93);
    }

    // The brain turns only while something is happening; a still system
    // shows a still brain, which is the property this slice exists for.
    yaw += (0.00004 + level * 0.0006) * dt;

    if (!ctx) {
      // No context: advance the signals so the model still progresses (a
      // test can watch them arrive), but draw nothing.
      advance(dt);
      return;
    }

    const { w, h } = size();
    const view = { yaw, pitch: 0.06, scale: Math.min(w, h) * 0.32, ox: w / 2, oy: h / 2 };
    const colours = coloursFor(tone);

    ctx.clearRect(0, 0, w, h);

    const nodes = model.nodes ?? [];
    const projected = new Array(nodes.length);
    for (let i = 0; i < nodes.length; i += 1) projected[i] = projectNode(nodes[i], view);

    // edges first, under the points
    ctx.strokeStyle = colours.edge;
    ctx.lineWidth = 0.6;
    ctx.beginPath();
    for (const [a, b] of model.edges ?? []) {
      const pa = projected[a];
      const pb = projected[b];
      if (!pa || !pb) continue;
      ctx.moveTo(pa.px, pa.py);
      ctx.lineTo(pb.px, pb.py);
    }
    ctx.stroke();

    // points, shaded by the fold field so sulci read dark and gyri bright
    for (let i = 0; i < nodes.length; i += 1) {
      const p = projected[i];
      const fold = Number.isFinite(nodes[i].fold) ? nodes[i].fold : 0;
      const depth = Math.max(0, Math.min(1, (p.depth + 1.2) / 2.4));
      ctx.globalAlpha = 0.18 + depth * 0.5 + fold * 0.12;
      ctx.fillStyle = colours.core;
      ctx.fillRect(p.px, p.py, 1.4, 1.4);
    }
    ctx.globalAlpha = 1;

    // travelling signals -- one per real event
    ctx.fillStyle = colours.signal;
    for (const s of signals) {
      const pa = projected[s.edge[0]];
      const pb = projected[s.edge[1]];
      if (!pa || !pb) continue;
      const x = pa.px + (pb.px - pa.px) * s.t;
      const y = pa.py + (pb.py - pa.py) * s.t;
      ctx.beginPath();
      ctx.arc(x, y, 1.9, 0, Math.PI * 2);
      ctx.fill();
      if (rings && typeof rings.light === 'function') {
        rings.light(bearingOf(x, y, view.ox, view.oy), 0.55 + 0.45 * s.t);
      }
    }

    advance(dt);
  };

  const advance = (dt) => {
    for (const s of signals) s.t += (s.speed * dt) / 1000;
    signals = signals.filter((s) => s.t < 1);
  };

  const loop = (t) => {
    paint(t);
    if (handle !== null && raf) handle = raf(loop);
  };

  return {
    el,
    model,
    paint,
    signals: () => signals.length,
    drawable: () => ctx !== null,
    running: () => handle !== null,

    start() {
      // REDUCED MOTION: one static paint, no loop. The truth still renders;
      // only the motion quiets -- the rule S1 set, and the reason the brain
      // is not the exception to it.
      if (reduced || !raf) { paint(now()); return; }
      if (handle !== null) return;
      handle = raf(loop);
    },

    stop() {
      if (handle !== null && caf) caf(handle);
      handle = null;
    },

    /**
     * The state changed, so repaint -- EVEN UNDER REDUCED MOTION, where
     * there is no loop to notice. A single paint taken at construction with
     * the state changing afterwards leaves the core showing the wrong colour
     * indefinitely: quiet the motion, never the truth (voice-line red pen,
     * finding 7).
     * @param {string} next
     */
    setTone(next) {
      tone = typeof next === 'string' ? next : tone;
      if (handle === null) paint(now());
    },
  };
}
