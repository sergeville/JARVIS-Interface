// ui/orbit.js -- instruments ride rings around the core.
//
// Pure placement: given N nodes, distribute them on the orbit evenly,
// honouring a definition's optional position hint (an angle in degrees).
// The connection lines are one SVG under the nodes -- the concept's threads
// from the core to its agents. Nothing here reads instrument data beyond
// the position hint; the shell hands nodes in, the orbit seats them.

/**
 * Compute each node's angle in degrees. Hinted nodes keep their hint (a
 * finite number, or the contract's numeric string); unhinted nodes fill the
 * gaps BETWEEN the hinted seats -- never on top of one (test-adversary,
 * 2026-08-11: free nodes used to divide the circle blind and land exactly
 * on a hint). With no hints at all, they share the circle evenly from -90
 * (top). Pure function -- the tests drive it directly.
 *
 * @param {{position?: number|string}[]} defs
 * @returns {number[]} one angle per def, same order
 */
export function orbitAngles(defs) {
  const angles = new Array(defs.length).fill(null);
  defs.forEach((d, i) => {
    const raw = d ? d.position : undefined;
    const n = typeof raw === 'number' ? raw
      : (typeof raw === 'string' && raw.trim() !== '' ? Number(raw) : NaN);
    if (Number.isFinite(n)) angles[i] = ((n % 360) + 360) % 360;
  });
  const free = angles.map((a, i) => (a === null ? i : null)).filter((i) => i !== null);
  if (free.length === 0) return angles;

  const hinted = [...new Set(angles.filter((a) => a !== null))].sort((a, b) => a - b);
  if (hinted.length === 0) {
    free.forEach((defIdx, k) => {
      angles[defIdx] = (((-90 + (360 / free.length) * k) % 360) + 360) % 360;
    });
    return angles;
  }

  // The circle minus the hinted seats is a set of arcs; free nodes are
  // dealt into the arcs by size (largest remainder, so counts always sum),
  // then spaced evenly INSIDE each arc, endpoints excluded.
  const gaps = hinted.map((start, i) => {
    const next = hinted[(i + 1) % hinted.length];
    return { start, size: i === hinted.length - 1 ? (next - start + 360) % 360 || 360 : next - start };
  });
  // hinted is deduped and sorted, so the arcs are all positive and sum to
  // exactly 360 (a single hint's arc is the whole circle back to itself).
  const quotas = gaps.map((g) => (free.length * g.size) / 360);
  const counts = quotas.map(Math.floor);
  let leftover = free.length - counts.reduce((s, c) => s + c, 0);
  quotas
    .map((q, i) => ({ i, frac: q - counts[i] }))
    .sort((a, b) => b.frac - a.frac)
    .forEach(({ i }) => { if (leftover > 0) { counts[i] += 1; leftover -= 1; } });
  let f = 0;
  gaps.forEach((g, i) => {
    for (let j = 0; j < counts[i]; j += 1) {
      angles[free[f]] = (g.start + (g.size * (j + 1)) / (counts[i] + 1)) % 360;
      f += 1;
    }
  });
  return angles;
}

/**
 * Build the orbit layer: an SVG for the connection lines and an absolute
 * container for the nodes. Radius is in percent of the container's half --
 * CSS owns the visual size; this owns only geometry.
 *
 * @param {Document} doc
 * @returns {{el: Element, svg: Element, seat: (nodes: {el: Element, def: Object}[]) => void}}
 */
export function createOrbit(doc) {
  const el = doc.createElement('div');
  el.className = 'os-orbit';

  const svg = doc.createElementNS
    ? doc.createElementNS('http://www.w3.org/2000/svg', 'svg')
    : doc.createElement('svg');
  svg.setAttribute('class', 'os-orbit__lines');
  svg.setAttribute('viewBox', '0 0 100 100');
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  el.appendChild(svg);

  const RADIUS = 41; // percent of the viewBox half -- outside the core rings

  const seat = (nodes) => {
    while (svg.children.length > 0) svg.removeChild(svg.children[svg.children.length - 1]);
    const angles = orbitAngles(nodes.map((n) => n.def));
    nodes.forEach((node, i) => {
      const rad = (angles[i] * Math.PI) / 180;
      const x = 50 + RADIUS * Math.cos(rad);
      const y = 50 + RADIUS * Math.sin(rad);
      const line = doc.createElementNS
        ? doc.createElementNS('http://www.w3.org/2000/svg', 'line')
        : doc.createElement('line');
      line.setAttribute('x1', '50');
      line.setAttribute('y1', '50');
      line.setAttribute('x2', String(x));
      line.setAttribute('y2', String(y));
      line.setAttribute('class', 'os-orbit__line');
      svg.appendChild(line);
      node.el.style.left = `${x}%`;
      node.el.style.top = `${y}%`;
    });
  };

  return { el, svg, seat };
}
