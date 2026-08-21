// ui/core-rings.js -- the instrument rings, generated rather than pasted.
//
// Serge's example draws these bezels with about 1,600 hand-written SVG tick
// elements inline. They are trigonometry, so here they are generated from a
// spec: roughly a hundred lines instead of hundreds of kilobytes of markup,
// and -- the part that matters -- the geometry becomes a pure function a
// test can drive without a browser.
//
// The coupling this file exists for: a signal that lands somewhere on the
// brain lights the ring segment AT THAT BEARING, with the ring's current
// rotation subtracted, so the lit bin tracks the brain in screen space while
// the bezel keeps turning through it. Without the subtraction the light
// rides the bezel and the coupling is a decoration.

/**
 * @typedef {Object} RingSpec
 * @property {number} radius    percent of the 100x100 viewBox half
 * @property {number} ticks     tick marks around the ring
 * @property {number} segments  lightable bins (the resolution of the coupling)
 * @property {number} tickLen   tick length in viewBox units
 * @property {number} width     stroke width
 */

/** @type {RingSpec[]} -- three bezels, outer to inner. Data, not markup. */
export const RING_SPECS = [
  { radius: 46, ticks: 120, segments: 60, tickLen: 3.0, width: 0.5 },
  { radius: 40, ticks: 72, segments: 36, tickLen: 2.2, width: 0.7 },
  { radius: 34, ticks: 36, segments: 24, tickLen: 1.6, width: 0.5 },
];

const CENTRE = 50;

/**
 * Where a bearing lands on the ring, in viewBox coordinates.
 *
 * Bearing is measured clockwise from twelve o'clock -- the same convention
 * as brain-model's bearingOf(), and it has to be the same or the lit segment
 * is somewhere else entirely. One spelling of the angle, used by the
 * geometry, the painter and the tests.
 *
 * @param {number} bearing degrees
 * @param {number} radius
 * @returns {{x: number, y: number}}
 */
export function pointAt(bearing, radius) {
  const rad = ((Number.isFinite(bearing) ? bearing : 0) - 90) * (Math.PI / 180);
  return { x: CENTRE + radius * Math.cos(rad), y: CENTRE + radius * Math.sin(rad) };
}

/**
 * Generate one ring's geometry as plain data.
 *
 * Pure: no document, no side effects. The tests drive this directly, so the
 * question "are the ticks where the spec says" is answered without a canvas,
 * a browser or a screenshot.
 *
 * @param {RingSpec} spec
 * @returns {{ticks: {x1:number,y1:number,x2:number,y2:number,at:number}[],
 *            segments: {index:number, from:number, to:number, mid:number}[],
 *            radius: number}}
 */
export function ringGeometry(spec) {
  const radius = Number.isFinite(spec?.radius) ? spec.radius : 40;
  const count = Math.max(0, Math.trunc(spec?.ticks ?? 0));
  const bins = Math.max(1, Math.trunc(spec?.segments ?? 1));
  const len = Number.isFinite(spec?.tickLen) ? spec.tickLen : 2;

  const ticks = [];
  for (let i = 0; i < count; i += 1) {
    const at = (360 / count) * i;
    const outer = pointAt(at, radius);
    const inner = pointAt(at, radius - len);
    ticks.push({ x1: inner.x, y1: inner.y, x2: outer.x, y2: outer.y, at });
  }

  const segments = [];
  const span = 360 / bins;
  for (let i = 0; i < bins; i += 1) {
    const from = span * i;
    segments.push({ index: i, from, to: from + span, mid: from + span / 2 });
  }
  return { ticks, segments, radius };
}

/**
 * Which segment a bearing falls in.
 *
 * Returns -1 for a bearing that is not a real number, so "nothing to light"
 * is a value the caller can see rather than segment zero quietly flashing
 * every time a signal arrives with a broken bearing.
 *
 * @param {number} bearing
 * @param {number} bins
 * @returns {number} index, or -1
 */
export function segmentFor(bearing, bins) {
  if (!Number.isFinite(bearing) || !Number.isFinite(bins) || bins < 1) return -1;
  const b = ((bearing % 360) + 360) % 360;
  return Math.min(Math.trunc(bins) - 1, Math.floor((b / 360) * Math.trunc(bins)));
}

/**
 * Build the ring layer.
 *
 * Constructible against a fake DOM: if the document cannot make namespaced
 * SVG elements it falls back to plain ones, exactly as ui/orbit.js does, so
 * the whole layer is testable without a browser.
 *
 * @param {Document} doc
 * @param {RingSpec[]} [specs]
 * @returns {{el: Element, light: (bearing: number, energy?: number) => number,
 *            spin: (rate: number) => void, rotation: () => number,
 *            tick: (dtMs: number) => void, refs: Object}}
 */
export function createRings(doc, specs = RING_SPECS) {
  const svgEl = (name) => (doc.createElementNS
    ? doc.createElementNS('http://www.w3.org/2000/svg', name)
    : doc.createElement(name));

  const el = svgEl('svg');
  el.setAttribute('class', 'os-rings');
  el.setAttribute('viewBox', '0 0 100 100');
  el.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  el.setAttribute('aria-hidden', 'true'); // decoration; the caption carries the truth

  const rings = specs.map((spec, ri) => {
    const geo = ringGeometry(spec);
    const group = svgEl('g');
    group.setAttribute('class', `os-rings__ring os-rings__ring--${ri}`);

    for (const t of geo.ticks) {
      const line = svgEl('line');
      line.setAttribute('x1', String(t.x1));
      line.setAttribute('y1', String(t.y1));
      line.setAttribute('x2', String(t.x2));
      line.setAttribute('y2', String(t.y2));
      line.setAttribute('class', 'os-rings__tick');
      line.setAttribute('stroke-width', String(spec.width ?? 0.5));
      group.appendChild(line);
    }

    // One lightable element per segment, seated at the segment's midpoint.
    const bins = geo.segments.map((seg) => {
      const dot = svgEl('circle');
      const p = pointAt(seg.mid, geo.radius);
      dot.setAttribute('cx', String(p.x));
      dot.setAttribute('cy', String(p.y));
      dot.setAttribute('r', String((spec.tickLen ?? 2) * 0.34));
      dot.setAttribute('class', 'os-rings__bin');
      dot.setAttribute('data-bin', String(seg.index));
      dot.setAttribute('data-energy', '0');
      group.appendChild(dot);
      return dot;
    });

    el.appendChild(group);
    return { spec, geo, group, bins, rotation: 0, rate: (ri % 2 === 0 ? 1 : -1) * 2 };
  });

  /** Degrees per second, scaled by activity. Set by the painter. */
  let speed = 1;

  const setTransform = (ring) => {
    // A fake DOM has no style engine; guard rather than assume.
    if (ring.group.setAttribute) {
      ring.group.setAttribute('transform', `rotate(${ring.rotation.toFixed(2)} ${CENTRE} ${CENTRE})`);
    }
  };

  return {
    el,
    refs: { rings },

    /**
     * Advance the bezels. Rotation is kept in the model, not read back out
     * of a transform string, so light() can subtract a number rather than
     * parse one.
     * @param {number} dtMs
     */
    tick(dtMs) {
      const dt = Number.isFinite(dtMs) ? Math.max(0, Math.min(250, dtMs)) : 0;
      for (const ring of rings) {
        ring.rotation = (ring.rotation + (ring.rate * speed * dt) / 1000) % 360;
        setTransform(ring);
      }
    },

    /**
     * Ring speed rides on activity, exactly as the example does. Clamped so
     * a runaway level cannot spin the bezels into a blur.
     * @param {number} rate
     */
    spin(rate) {
      speed = Number.isFinite(rate) ? Math.max(0, Math.min(12, rate)) : 0;
    },

    rotation: () => rings.map((r) => r.rotation),

    /**
     * Light the bin at a bearing, ON EVERY RING, with that ring's current
     * rotation subtracted so the lit bin stays put in screen space while the
     * bezel turns through it.
     *
     * @param {number} bearing degrees, screen space
     * @param {number} [energy] 0..1
     * @returns {number} bins lit -- 0 means the bearing was not a number
     */
    light(bearing, energy = 1) {
      if (!Number.isFinite(bearing)) return 0;
      const e = Math.max(0, Math.min(1, Number.isFinite(energy) ? energy : 1));
      let lit = 0;
      for (const ring of rings) {
        const local = bearing - ring.rotation;
        const idx = segmentFor(local, ring.geo.segments.length);
        if (idx < 0) continue;
        const dot = ring.bins[idx];
        if (!dot) continue;
        const was = Number(dot.getAttribute ? dot.getAttribute('data-energy') : 0) || 0;
        dot.setAttribute('data-energy', String(Math.max(was, e).toFixed(3)));
        lit += 1;
      }
      return lit;
    },

    /**
     * Bleed the lit bins back down. Called by the painter each frame; a bin
     * that is never faded stays lit forever and the rings become a record of
     * everything that ever happened rather than what is happening.
     * @param {number} factor 0..1
     */
    fade(factor = 0.92) {
      const f = Math.max(0, Math.min(1, Number.isFinite(factor) ? factor : 0.92));
      for (const ring of rings) {
        for (const dot of ring.bins) {
          const was = Number(dot.getAttribute('data-energy')) || 0;
          if (was <= 0) continue;
          const next = was * f;
          dot.setAttribute('data-energy', String(next < 0.004 ? '0' : next.toFixed(3)));
        }
      }
    },
  };
}
