// ui/brain-model.js -- the brain, as pure geometry.
//
// No DOM, no canvas, no globals, no clock. Given a spec it returns a point
// cloud and the edges between the points; given a node and a view it returns
// where that node lands on screen. Every number here is a pure function of
// its arguments, which is the whole reason the shape of JARVIS's brain can
// be tested at all.
//
// The cloud is SEEDED. Serge's example did this and it was the right call:
// a brain that is a different blob on every refresh cannot be tested, cannot
// be reviewed, and cannot be recognised. Same seed, same brain, forever.

/**
 * mulberry32 -- a small, fast, seeded PRNG.
 *
 * The generator is the reason the cloud is reproducible, so it is exported
 * and tested directly rather than hidden inside buildBrain(). A seed that is
 * not a finite number would silently become NaN and produce a cloud of NaNs
 * that renders as nothing at all -- so it is coerced to a real integer here,
 * where the failure is one line from its cause.
 *
 * @param {number} seed
 * @returns {() => number} successive values in [0, 1)
 */
export function mulberry32(seed) {
  let a = Number.isFinite(seed) ? Math.trunc(seed) >>> 0 : 0;
  return function next() {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * The default shape of the brain. It is DATA, handed to buildBrain as an
 * argument -- the cloud is configuration like every other thing in this
 * skeleton, and no future session has to edit a function to change a count.
 *
 * @typedef {Object} BrainSpec
 * @property {number} seed
 * @property {number} cortex      points in the cortical shell
 * @property {number} white       points in the white matter (crosses the midline)
 * @property {number} cerebellum  points in the cerebellum
 * @property {number} stem        points in the brain stem
 * @property {number} fissure     half-width of the empty midline slab
 * @property {number} maxDegree   most edges any one node may carry
 * @property {number} linkRadius  how close two nodes must be to be wired
 */

/** @type {BrainSpec} */
export const BRAIN_SPEC = {
  seed: 0x5EED17,
  cortex: 1400,
  white: 420,
  cerebellum: 240,
  stem: 70,
  fissure: 0.035,
  maxDegree: 3,
  linkRadius: 0.085,
};

/**
 * The fold field: how deep the cortical sulci run at a point on the shell.
 *
 * Pure trigonometry, exported because the painter shades with the same
 * number the geometry was built from -- one spelling of "how folded is it
 * here", so the grooves in the picture are the grooves in the model rather
 * than a second, decorative approximation of them.
 *
 * @param {number} x @param {number} y @param {number} z
 * @returns {number} roughly -1..1; low is a sulcus, high is a gyrus
 */
export function foldField(x, y, z) {
  return (
    Math.sin(x * 9.0) * 0.5 +
    Math.sin(y * 7.5 + 1.3) * 0.3 +
    Math.sin(z * 8.2 + 2.1) * 0.2
  );
}

/**
 * Build the cloud.
 *
 * The four regions are built in the order the anatomy reads, and two of them
 * carry a property a test pins, because both are the kind of thing a future
 * tidy-up would quietly destroy:
 *
 *   THE FISSURE IS ACTUALLY EMPTY. Cortex points inside the midline slab are
 *   REJECTED, not nudged aside -- the longitudinal fissure is a hole, and a
 *   hole made by pushing points to its edges is a seam, not a fissure.
 *
 *   THE WHITE MATTER ACTUALLY CROSSES IT. The corpus callosum is the reason
 *   the hemispheres have anything to fire across. A session that "fixes" the
 *   fissure by applying it to every region severs it, the picture still
 *   looks like a brain, and the signals stop crossing. That is exactly the
 *   silent-and-plausible failure this project keeps meeting, so it is a
 *   test, not a comment.
 *
 * @param {Partial<BrainSpec>} [spec]
 * @returns {{nodes: {x:number,y:number,z:number,region:string,fold:number}[],
 *            edges: [number,number][], adj: number[][], spec: BrainSpec}}
 */
export function buildBrain(spec = {}) {
  const s = { ...BRAIN_SPEC, ...spec };
  const rnd = mulberry32(s.seed);
  const nodes = [];

  // -- cortex: a shell, dented inward along the sulci -----------------------
  let guard = 0;
  const wanted = Math.max(0, Math.trunc(s.cortex));
  // A rejection loop needs a ceiling or a hostile spec (fissure >= 1) spins
  // forever. It stops and returns what it has: fewer points, never a hang.
  while (nodes.length < wanted && guard < wanted * 40) {
    guard += 1;
    const u = rnd() * 2 - 1;
    const theta = rnd() * Math.PI * 2;
    const r = Math.sqrt(1 - u * u);
    let x = r * Math.cos(theta) * 1.0;
    let y = u * 0.78;
    let z = r * Math.sin(theta) * 0.86;
    if (Math.abs(x) < s.fissure) continue; // the fissure is a HOLE
    const fold = foldField(x, y, z);
    const dent = 1 - 0.06 * (1 - fold);
    x *= dent; y *= dent; z *= dent;
    nodes.push({ x, y, z, region: 'cortex', fold });
  }

  // -- white matter: fills the interior AND crosses the midline -------------
  for (let i = 0; i < s.white; i += 1) {
    const rad = Math.cbrt(rnd()) * 0.62;
    const u = rnd() * 2 - 1;
    const theta = rnd() * Math.PI * 2;
    const r = Math.sqrt(1 - u * u);
    const x = r * Math.cos(theta) * rad;
    const y = u * rad * 0.7;
    const z = r * Math.sin(theta) * rad * 0.85;
    nodes.push({ x, y, z, region: 'white', fold: foldField(x, y, z) });
  }

  // -- cerebellum: tight horizontal foliation, low and behind ---------------
  for (let i = 0; i < s.cerebellum; i += 1) {
    const a = rnd() * Math.PI * 2;
    const rr = 0.16 + rnd() * 0.2;
    const x = Math.cos(a) * rr * 1.05;
    const z = 0.52 + Math.sin(a) * rr * 0.5;
    // The foliation is banded on purpose: rounding y to a comb of leaves is
    // what makes a cerebellum read as a cerebellum and not as a second blob.
    const y = -0.42 + Math.round(rnd() * 7) * 0.018;
    nodes.push({ x, y, z, region: 'cerebellum', fold: foldField(x, y, z) });
  }

  // -- stem: tapered, dropping away from the middle -------------------------
  for (let i = 0; i < s.stem; i += 1) {
    const t = i / Math.max(1, s.stem - 1);
    const taper = 0.085 * (1 - t * 0.55);
    const a = rnd() * Math.PI * 2;
    const x = Math.cos(a) * taper;
    const z = 0.16 + Math.sin(a) * taper;
    const y = -0.42 - t * 0.44;
    nodes.push({ x, y, z, region: 'stem', fold: foldField(x, y, z) });
  }

  const { edges, adj } = wire(nodes, s.linkRadius, s.maxDegree);
  return { nodes, edges, adj, spec: s };
}

/**
 * Wire near neighbours through a spatial hash, capped at maxDegree.
 *
 * The cap is the point: an uncapped near-neighbour wiring on 2,000 points is
 * a hairball that hides the shape and costs the painter dearly. The hash is
 * what keeps this from being O(n^2) -- 2,000 nodes compared pairwise is four
 * million tests on every load.
 *
 * @param {{x:number,y:number,z:number}[]} nodes
 * @param {number} radius
 * @param {number} maxDegree
 * @returns {{edges: [number,number][], adj: number[][]}}
 */
export function wire(nodes, radius = BRAIN_SPEC.linkRadius, maxDegree = BRAIN_SPEC.maxDegree) {
  const adj = nodes.map(() => []);
  const edges = [];
  const cell = Math.max(radius, 1e-6);
  const key = (x, y, z) => `${Math.floor(x / cell)},${Math.floor(y / cell)},${Math.floor(z / cell)}`;
  const buckets = new Map();
  nodes.forEach((n, i) => {
    const k = key(n.x, n.y, n.z);
    if (!buckets.has(k)) buckets.set(k, []);
    buckets.get(k).push(i);
  });

  const r2 = radius * radius;
  nodes.forEach((n, i) => {
    if (adj[i].length >= maxDegree) return;
    const cx = Math.floor(n.x / cell);
    const cy = Math.floor(n.y / cell);
    const cz = Math.floor(n.z / cell);
    for (let dx = -1; dx <= 1; dx += 1) {
      for (let dy = -1; dy <= 1; dy += 1) {
        for (let dz = -1; dz <= 1; dz += 1) {
          const bucket = buckets.get(`${cx + dx},${cy + dy},${cz + dz}`);
          if (!bucket) continue;
          for (const j of bucket) {
            if (j <= i) continue; // each pair considered once
            if (adj[i].length >= maxDegree) return;
            if (adj[j].length >= maxDegree) continue;
            const ddx = n.x - nodes[j].x;
            const ddy = n.y - nodes[j].y;
            const ddz = n.z - nodes[j].z;
            if (ddx * ddx + ddy * ddy + ddz * ddz > r2) continue;
            adj[i].push(j);
            adj[j].push(i);
            edges.push([i, j]);
          }
        }
      }
    }
  });
  return { edges, adj };
}

/**
 * Project one node to the screen.
 *
 * Never returns NaN, whatever it is handed. A single NaN here propagates
 * into a canvas path and silently blanks the whole brain -- one bad number
 * and the centrepiece of the OS renders nothing, with no error anywhere. So
 * a non-finite view value falls back to the identity view, and the result is
 * asserted finite before it leaves.
 *
 * @param {{x:number,y:number,z:number}} node
 * @param {{yaw?:number, pitch?:number, scale?:number, ox?:number, oy?:number, tilt?:number}} [view]
 * @returns {{px:number, py:number, depth:number, scale:number}}
 */
export function projectNode(node, view = {}) {
  const num = (v, d) => (Number.isFinite(v) ? v : d);
  const yaw = num(view.yaw, 0);
  const pitch = num(view.pitch, 0);
  const tilt = num(view.tilt, -0.22); // brains do not sit axis-aligned
  const size = num(view.scale, 1);
  const ox = num(view.ox, 0);
  const oy = num(view.oy, 0);

  const x0 = num(node?.x, 0);
  const y0 = num(node?.y, 0);
  const z0 = num(node?.z, 0);

  // tilt (about x), then yaw (about y), then pitch (about x again)
  const ty = y0 * Math.cos(tilt) - z0 * Math.sin(tilt);
  const tz = y0 * Math.sin(tilt) + z0 * Math.cos(tilt);
  const rx = x0 * Math.cos(yaw) + tz * Math.sin(yaw);
  const rz = -x0 * Math.sin(yaw) + tz * Math.cos(yaw);
  const ry = ty * Math.cos(pitch) - rz * Math.sin(pitch);
  const rz2 = ty * Math.sin(pitch) + rz * Math.cos(pitch);

  // Perspective divide, floored so a node behind the camera cannot flip the
  // sign of the whole projection or divide by zero.
  const persp = 2.6;
  const denom = Math.max(0.35, persp - rz2);
  const k = (persp / denom) * size;

  const px = ox + rx * k;
  const py = oy + ry * k;
  return {
    px: Number.isFinite(px) ? px : ox,
    py: Number.isFinite(py) ? py : oy,
    depth: Number.isFinite(rz2) ? rz2 : 0,
    scale: Number.isFinite(k) ? k : size,
  };
}

/**
 * The bearing of a point from a centre, in degrees.
 *
 * ONE spelling of "which way did that signal land" -- the rings light by it
 * and the tests check it, so the picture and the proof cannot drift apart.
 * Returns 0..360 measured clockwise from twelve o'clock, which is how a
 * bezel is read and therefore the only convention that will not confuse the
 * next person to touch the rings.
 *
 * @param {number} px @param {number} py @param {number} ox @param {number} oy
 * @returns {number} 0 <= bearing < 360
 */
export function bearingOf(px, py, ox = 0, oy = 0) {
  const dx = Number.isFinite(px) ? px - ox : 0;
  const dy = Number.isFinite(py) ? py - oy : 0;
  if (dx === 0 && dy === 0) return 0;
  const deg = (Math.atan2(dx, -dy) * 180) / Math.PI;
  return ((deg % 360) + 360) % 360;
}
