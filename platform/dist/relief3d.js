// 3D relief layer for the main map: SRTM elevation per 5 km cell as a WebGL2 block model.
// The map passes in whatever values its 2D layer shows; this module only draws them.

import { t, cityName } from './i18n.js?v=20261028-lang';

const css = getComputedStyle(document.documentElement);
const token = (name) => css.getPropertyValue(name).trim();
const hexRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const SKIRT = 22;
const HOME = 3500;
const EXAG = 25;
// Values below this are drawn as bare relief (layer filters, zero counts).
export const HIDDEN = -2;
export const MISSING = -1;

async function sha256(buffer) {
  const d = await crypto.subtle.digest('SHA-256', buffer);
  return Array.from(new Uint8Array(d), (v) => v.toString(16).padStart(2, '0')).join('');
}

const mat = {
  perspective(fovy, aspect, near, far) {
    const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0];
  },
  lookAt(e, t, up) {
    let zx = e[0] - t[0], zy = e[1] - t[1], zz = e[2] - t[2];
    let l = Math.hypot(zx, zy, zz); zx /= l; zy /= l; zz /= l;
    let xx = up[1] * zz - up[2] * zy, xy = up[2] * zx - up[0] * zz, xz = up[0] * zy - up[1] * zx;
    l = Math.hypot(xx, xy, xz); xx /= l; xy /= l; xz /= l;
    const yx = zy * xz - zz * xy, yy = zz * xx - zx * xz, yz = zx * xy - zy * xx;
    return [xx, yx, zx, 0, xy, yy, zy, 0, xz, yz, zz, 0,
      -(xx * e[0] + xy * e[1] + xz * e[2]), -(yx * e[0] + yy * e[1] + yz * e[2]), -(zx * e[0] + zy * e[1] + zz * e[2]), 1];
  },
  mul(a, b) {
    const o = new Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
      o[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
    }
    return o;
  },
};

const TERRAIN_VS = `
in vec2 a_pos; in float a_elev; in vec2 a_grad; in float a_val; in float a_side;
uniform mat4 u_mvp; uniform float u_exag;
out vec3 v_normal; out float v_elev; out float v_val; out float v_side; out vec2 v_xz; out float v_depth;
void main() {
  float s = u_exag / 1000.0;
  float y = a_side > 1.5 ? -${SKIRT}.0 : a_elev * s;
  v_normal = normalize(vec3(-a_grad.x * s, 1.0, -a_grad.y * s));
  v_elev = a_elev; v_val = a_val; v_side = a_side; v_xz = a_pos;
  gl_Position = u_mvp * vec4(a_pos.x, y, a_pos.y, 1.0);
  v_depth = gl_Position.w;
}`;
const TERRAIN_FS = `
in vec3 v_normal; in float v_elev; in float v_val; in float v_side; in vec2 v_xz; in float v_depth;
uniform vec3 u_ramp[7]; uniform float u_bounds[6]; uniform float u_k0; uniform vec3 u_sun; uniform vec3 u_fog;
uniform float u_fogNear; uniform float u_fogFar; uniform sampler2D u_sat; uniform float u_useSat; uniform vec4 u_satExt;
out vec4 color;
vec3 tint(float e) {
  vec3 c = mix(vec3(0.80, 0.77, 0.63), vec3(0.85, 0.82, 0.66), smoothstep(-40.0, 150.0, e));
  c = mix(c, vec3(0.78, 0.79, 0.62), smoothstep(200.0, 700.0, e));
  c = mix(c, vec3(0.62, 0.61, 0.50), smoothstep(900.0, 2200.0, e));
  c = mix(c, vec3(0.55, 0.52, 0.48), smoothstep(2200.0, 3400.0, e));
  return mix(c, vec3(0.96, 0.96, 0.95), smoothstep(3500.0, 4200.0, e));
}
void main() {
  if (v_side > 0.5) {
    float t = clamp(v_side - 1.0, 0.0, 1.0);
    vec3 c = mix(vec3(0.55, 0.47, 0.36), vec3(0.33, 0.28, 0.22), t);
    color = vec4(c, 1.0);
    return;
  }
  vec3 base = tint(v_elev);
  if (u_useSat > 0.5) {
    // Satellite colour, lifted slightly because relief shading darkens it again below.
    vec2 uv = vec2((v_xz.x - u_satExt.x) / u_satExt.z, (v_xz.y - u_satExt.y) / u_satExt.w);
    base = min(texture(u_sat, uv).rgb * 1.18 + 0.03, 1.0);
  }
  vec3 c = base;
  if (v_val > -1.5 && v_val < -0.5) {
    float stripe = step(0.5, fract((v_xz.x + v_xz.y) * 0.12));
    c = mix(vec3(0.80, 0.81, 0.78), vec3(0.70, 0.71, 0.68), stripe);
  } else if (v_val >= 0.0) {
    int k = 0;
    for (int i = 0; i < 6; i++) if (v_val >= u_bounds[i]) k = i + 1;
    float w = k == 0 ? u_k0 : (k == 1 ? 0.55 : (k == 2 ? 0.7 : (k == 3 ? 0.8 : (k == 4 ? 0.88 : (k == 5 ? 0.94 : 1.0)))));
    if (u_useSat > 0.5 && u_k0 < 0.3) w = k <= 1 ? 0.0 : w * 0.9;
    c = mix(base, u_ramp[k], w);
  }
  float diffuse = max(dot(normalize(v_normal), u_sun), 0.0);
  c *= 0.5 + 0.62 * diffuse;
  float fog = smoothstep(u_fogNear, u_fogFar, v_depth);
  color = vec4(mix(c, u_fog, fog * 0.55), 1.0);
}`;
const LINE_VS = `
in vec3 a_p; uniform mat4 u_mvp; uniform float u_exag;
void main() { gl_Position = u_mvp * vec4(a_p.x, a_p.y * u_exag / 1000.0 + 0.8, a_p.z, 1.0); }`;
const LINE_FS = `uniform vec4 u_color; out vec4 color; void main() { color = u_color; }`;
const PILLAR_VS = `
in vec3 a_box; in vec4 a_inst; uniform mat4 u_mvp; uniform float u_exag; uniform float u_grow;
out float v_t;
void main() {
  float h = a_inst.w * u_grow;
  vec3 p = vec3(a_inst.x + a_box.x * 9.0, a_inst.z * u_exag / 1000.0 + a_box.y * h, a_inst.y + a_box.z * 9.0);
  v_t = a_box.y;
  gl_Position = u_mvp * vec4(p, 1.0);
}`;
const PILLAR_FS = `
in float v_t; uniform vec3 u_low; uniform vec3 u_high; out vec4 color;
void main() { color = vec4(mix(u_low, u_high, pow(v_t, 0.8)), 1.0); }`;
const GLOW_VS = `
in vec4 a_inst; uniform mat4 u_mvp; uniform float u_exag; uniform float u_grow; uniform float u_size; uniform float u_pulse;
void main() {
  vec4 clip = u_mvp * vec4(a_inst.x, a_inst.z * u_exag / 1000.0 + a_inst.w * u_grow, a_inst.y, 1.0);
  gl_Position = clip;
  gl_PointSize = clamp(u_size * u_pulse / clip.w, 6.0, 90.0);
}`;
// Observed events: a diamond marker standing on the relief; yellow when the cell had an alert.
const MARK_VS = `
in vec4 a_m; uniform mat4 u_mvp; uniform float u_exag; uniform float u_size;
out float v_hit;
void main() {
  gl_Position = u_mvp * vec4(a_m.x, a_m.y * u_exag / 1000.0 + 3.0, a_m.z, 1.0);
  gl_PointSize = u_size;
  v_hit = a_m.w;
}`;
const MARK_FS = `
in float v_hit; out vec4 color;
void main() {
  vec2 p = abs(gl_PointCoord - 0.5) * 2.0;
  float d = p.x + p.y;
  if (d > 1.0) discard;
  vec3 fill = v_hit > 0.5 ? vec3(1.0, 0.82, 0.4) : vec3(1.0, 0.996, 0.98);
  color = vec4(d > 0.68 ? vec3(0.1, 0.24, 0.21) : fill, 1.0);
}`;
const GLOW_FS = `
out vec4 color;
void main() {
  float d = length(gl_PointCoord - 0.5) * 2.0;
  float a = pow(max(1.0 - d, 0.0), 2.2);
  color = vec4(vec3(1.0, 0.55, 0.18) * a, a);
}`;

// host: positioned element to draw into. cells: decoded cells.bin records. onPick(index) on click.
export async function createRelief({ host, geo, cells, onPick }) {
  const [eb, emeta] = await Promise.all([
    fetch('./assets/elevation.i16').then((r) => { if (!r.ok) throw Error('Нет файла высот'); return r.arrayBuffer(); }),
    fetch('./assets/elevation.json').then((r) => r.json()),
  ]);
  if (eb.byteLength !== geo.count * 2 || (await sha256(eb)) !== emeta.sha256) throw Error('Файл высот не совпал с elevation.json');

  const canvas = document.createElement('canvas');
  canvas.className = 'relief-canvas';
  canvas.tabIndex = 0;
  canvas.setAttribute('aria-label', t('relief.aria'));
  const labels = document.createElement('div');
  labels.className = 'relief-labels';
  labels.setAttribute('aria-hidden', 'true');
  host.append(canvas, labels);
  const gl = canvas.getContext('webgl2', { antialias: true, alpha: true });
  if (!gl) { canvas.remove(); labels.remove(); throw Error('WebGL 2 недоступен в этом браузере'); }

  const program = (vs, fs) => {
    const p = gl.createProgram();
    for (const [type, src] of [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]]) {
      const s = gl.createShader(type);
      gl.shaderSource(s, '#version 300 es\nprecision highp float;\n' + src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(s));
      gl.attachShader(p, s);
    }
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(p));
    const u = {};
    for (let i = 0; i < gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS); i++) {
      const name = gl.getActiveUniform(p, i).name.replace(/\[0\]$/, '');
      u[name] = gl.getUniformLocation(p, name);
    }
    return { p, u };
  };
  const buffer = (data, loc, size, { usage = gl.STATIC_DRAW, divisor = 0 } = {}) => {
    const b = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, data, usage);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
    if (divisor) gl.vertexAttribDivisor(loc, divisor);
    return b;
  };

  // Lattice lookup by row/column.
  let minR = 1e9, maxR = -1e9, minC = 1e9, maxC = -1e9;
  for (const c of cells) { minR = Math.min(minR, c.row); maxR = Math.max(maxR, c.row); minC = Math.min(minC, c.col); maxC = Math.max(maxC, c.col); }
  const W = maxC - minC + 1;
  const lattice = new Int32Array(W * (maxR - minR + 1)).fill(-1);
  cells.forEach((c, i) => { lattice[(c.row - minR) * W + (c.col - minC)] = i; });
  const at = (r, c) => (r < minR || r > maxR || c < minC || c > maxC ? -1 : lattice[(r - minR) * W + (c - minC)]);

  // Elevation in metres; the cells without SRTM take their neighbours' mean.
  const raw = new Int16Array(eb);
  const elev = new Float32Array(geo.count);
  for (let i = 0; i < geo.count; i++) elev[i] = raw[i] === emeta.missing ? NaN : raw[i];
  for (let i = 0; i < geo.count; i++) {
    if (!Number.isNaN(elev[i])) continue;
    let s = 0, n = 0;
    for (const [dr, dc] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { const j = at(cells[i].row + dr, cells[i].col + dc); if (j >= 0 && !Number.isNaN(elev[j])) { s += elev[j]; n++; } }
    elev[i] = n ? s / n : 0;
  }

  // Vertices at cell centres: x east, z south, so north faces away from the default camera.
  const N = geo.count;
  const pos = [], el = [], grad = [], side = [];
  for (let i = 0; i < N; i++) {
    const c = cells[i];
    pos.push((c.col + 0.5) * 5, -(c.row + 0.5) * 5);
    el.push(elev[i]);
    const e = (r, cc) => { const j = at(r, cc); return j >= 0 ? elev[j] : elev[i]; };
    grad.push((e(c.row, c.col + 1) - e(c.row, c.col - 1)) / 10, (e(c.row - 1, c.col) - e(c.row + 1, c.col)) / 10);
    side.push(0);
  }
  const idx = [];
  const edges = new Map();
  const edge = (a, b) => { const k = a < b ? a * N + b : b * N + a; edges.set(k, edges.has(k) ? null : [a, b]); };
  const tri = (a, b, c) => { idx.push(a, b, c); edge(a, b); edge(b, c); edge(c, a); };
  for (let r = minR; r < maxR; r++) for (let c = minC; c < maxC; c++) {
    const a = at(r, c), b = at(r, c + 1), d = at(r + 1, c), e = at(r + 1, c + 1);
    const n = (a >= 0) + (b >= 0) + (d >= 0) + (e >= 0);
    if (n === 4) { tri(a, d, b); tri(b, d, e); } else if (n === 3) { const q = [a, b, e, d].filter((v) => v >= 0); tri(q[0], q[2], q[1]); }
  }
  // Walls along the outer edge turn the surface into a cut block of land.
  for (const v of edges.values()) {
    if (!v) continue;
    const [a, b] = v;
    const base = pos.length / 2;
    for (const [j, s] of [[a, 1], [b, 1], [a, 2], [b, 2]]) { pos.push(pos[j * 2], pos[j * 2 + 1]); el.push(elev[j]); grad.push(0, 0); side.push(s); }
    idx.push(base, base + 2, base + 1, base + 1, base + 2, base + 3);
  }
  const vertexCount = pos.length / 2, indexCount = idx.length;
  let sx = 0, sz = 0;
  for (let i = 0; i < N; i++) { sx += pos[i * 2]; sz += pos[i * 2 + 1]; }
  const home = [sx / N, 0, sz / N];

  const terrain = program(TERRAIN_VS, TERRAIN_FS);
  terrain.vao = gl.createVertexArray();
  gl.bindVertexArray(terrain.vao);
  const loc = (n) => gl.getAttribLocation(terrain.p, n);
  buffer(new Float32Array(pos), loc('a_pos'), 2);
  buffer(new Float32Array(el), loc('a_elev'), 1);
  buffer(new Float32Array(grad), loc('a_grad'), 2);
  buffer(new Float32Array(side), loc('a_side'), 1);
  const vals = new Float32Array(vertexCount).fill(HIDDEN);
  const valBuffer = buffer(vals, loc('a_val'), 1, { usage: gl.DYNAMIC_DRAW });
  const ib = gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint32Array(idx), gl.STATIC_DRAW);

  const heightAt = (x, z) => { const j = at(Math.round(-z / 5 - 0.5), Math.round(x / 5 - 0.5)); return j >= 0 ? elev[j] : 0; };
  const segs = (rings, out) => { for (const ring of rings) for (let i = 1; i < ring.length; i++) for (const [x, z] of [ring[i - 1], ring[i]]) out.push(x, heightAt(x, z), z); };
  const regionPts = [], outlinePts = [];
  for (const r of geo.regions) segs(r.rings, regionPts);
  segs(geo.outline, outlinePts);
  const lines = program(LINE_VS, LINE_FS);
  lines.sets = [regionPts, outlinePts].map((pts) => {
    const vao = gl.createVertexArray(); gl.bindVertexArray(vao);
    buffer(new Float32Array(pts), gl.getAttribLocation(lines.p, 'a_p'), 3);
    return { vao, n: pts.length / 3 };
  });

  const pillars = program(PILLAR_VS, PILLAR_FS);
  pillars.vao = gl.createVertexArray(); gl.bindVertexArray(pillars.vao);
  const box = [];
  const f = [[-0.5, 0, -0.5], [0.5, 0, -0.5], [0.5, 1, -0.5], [-0.5, 1, -0.5], [-0.5, 0, 0.5], [0.5, 0, 0.5], [0.5, 1, 0.5], [-0.5, 1, 0.5]];
  for (const q of [[0, 1, 2, 3], [5, 4, 7, 6], [4, 0, 3, 7], [1, 5, 6, 2], [3, 2, 6, 7]]) for (const k of [0, 1, 2, 0, 2, 3]) box.push(...f[q[k]]);
  buffer(new Float32Array(box), gl.getAttribLocation(pillars.p, 'a_box'), 3);
  pillars.inst = buffer(new Float32Array(4), gl.getAttribLocation(pillars.p, 'a_inst'), 4, { usage: gl.DYNAMIC_DRAW, divisor: 1 });
  pillars.n = 0;
  const glow = program(GLOW_VS, GLOW_FS);
  glow.vao = gl.createVertexArray(); gl.bindVertexArray(glow.vao);
  gl.bindBuffer(gl.ARRAY_BUFFER, pillars.inst);
  const gi = gl.getAttribLocation(glow.p, 'a_inst');
  gl.enableVertexAttribArray(gi); gl.vertexAttribPointer(gi, 4, gl.FLOAT, false, 0, 0); gl.vertexAttribDivisor(gi, 1);
  const marks = program(MARK_VS, MARK_FS);
  marks.vao = gl.createVertexArray(); gl.bindVertexArray(marks.vao);
  marks.buf = buffer(new Float32Array(4), gl.getAttribLocation(marks.p, 'a_m'), 4, { usage: gl.DYNAMIC_DRAW });
  marks.n = 0;
  gl.bindVertexArray(null);
  const satTexture = gl.createTexture();
  let satExt = [0, 0, 1, 1], hasSat = false;

  const cityEls = geo.cities.map((c) => {
    const e = document.createElement('span');
    e.className = 'relief-city'; e.textContent = cityName(c.name); labels.append(e);
    return { el: e, x: c.x, z: c.y, h: heightAt(c.x, c.y) };
  });
  const marker = document.createElement('span');
  marker.className = 'relief-marker';
  labels.append(marker);

  const ramp = [1, 2, 3, 4, 5, 6, 7].flatMap((i) => hexRgb(token('--p' + i)));
  const sun = [-0.55, 0.72, -0.42].map((v, _, a) => v / Math.hypot(...a));
  const state = { yaw: 0, pitch: 0.82, dist: HOME, target: [...home], grow: 1, bounds: [1, 1, 1, 1, 1, 1], k0: 0.22, selected: -1, visible: false, lines: true, fit: true };
  const goal = { yaw: 0, pitch: 0.82, dist: HOME };
  // Distance at which the whole country fits the current canvas width; phones need more.
  const fitDist = (aspect) => Math.max(HOME, 1650 / (Math.tan(0.3) * aspect));
  let mvp = [], frameId = 0;

  const project = (x, y, z) => {
    const m = mvp;
    const cx = m[0] * x + m[4] * y + m[8] * z + m[12], cy = m[1] * x + m[5] * y + m[9] * z + m[13], cw = m[3] * x + m[7] * y + m[11] * z + m[15];
    if (cw <= 0) return null;
    return [(cx / cw * 0.5 + 0.5) * canvas.clientWidth, (1 - (cy / cw * 0.5 + 0.5)) * canvas.clientHeight, cw];
  };

  function pick(px, py) {
    const r = canvas.getBoundingClientRect();
    px -= r.left; py -= r.top;
    const s = EXAG / 1000;
    let best = -1, bestScore = 1e9;
    for (let i = 0; i < N; i++) {
      const c = cells[i];
      const q = project((c.col + 0.5) * 5, elev[i] * s, -(c.row + 0.5) * 5);
      if (!q) continue;
      const d = Math.hypot(q[0] - px, q[1] - py);
      if (d < 14) { const score = d + q[2] * 0.002; if (score < bestScore) { bestScore = score; best = i; } }
    }
    onPick(best);
  }

  let drag = null;
  const pointers = new Map();
  canvas.addEventListener('pointerdown', (e) => {
    canvas.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    drag = { moved: 0, pan: e.shiftKey || e.button === 2 };
    canvas.classList.add('dragging');
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const prev = pointers.get(e.pointerId);
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (drag.pinch) { state.fit = false; goal.dist = Math.min(9000, Math.max(250, goal.dist * drag.pinch / d)); }
      drag.pinch = d; drag.moved = 99;
      return;
    }
    const dx = e.clientX - prev[0], dy = e.clientY - prev[1];
    drag.moved += Math.abs(dx) + Math.abs(dy);
    if (drag.pan) {
      const k = goal.dist / canvas.clientHeight, c = Math.cos(state.yaw), s = Math.sin(state.yaw);
      state.target[0] -= (dx * c - dy * s * 1.3) * k;
      state.target[2] -= (-dx * s - dy * c * 1.3) * k;
    } else {
      goal.yaw -= dx * 0.005;
      goal.pitch = Math.min(1.45, Math.max(0.25, goal.pitch + dy * 0.004));
    }
  });
  const end = (e) => {
    pointers.delete(e.pointerId);
    if (!drag) return;
    if (drag.moved < 5 && pointers.size === 0) pick(e.clientX, e.clientY);
    if (pointers.size === 0) { drag = null; canvas.classList.remove('dragging'); }
  };
  canvas.addEventListener('pointerup', end);
  canvas.addEventListener('pointercancel', end);
  canvas.addEventListener('contextmenu', (e) => e.preventDefault());
  canvas.addEventListener('wheel', (e) => { e.preventDefault(); state.fit = false; goal.dist = Math.min(9000, Math.max(250, goal.dist * Math.exp(e.deltaY * 0.0012))); }, { passive: false });

  function frame(t) {
    frameId = 0;
    if (!state.visible) return;
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) { frameId = requestAnimationFrame(frame); return; }
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    if (state.fit) { goal.dist = fitDist(w / h); if (state.dist === HOME) state.dist = goal.dist; }
    const ease = reducedMotion ? 1 : 0.12;
    state.yaw += (goal.yaw - state.yaw) * ease;
    state.pitch += (goal.pitch - state.pitch) * ease;
    state.dist += (goal.dist - state.dist) * ease;
    state.grow = Math.min(1, state.grow + (reducedMotion ? 1 : 0.035));
    const cp = Math.cos(state.pitch), sp = Math.sin(state.pitch);
    const [tx, ty, tz] = state.target;
    const eye = [tx + state.dist * cp * Math.sin(state.yaw), ty + state.dist * sp, tz + state.dist * cp * Math.cos(state.yaw)];
    mvp = mat.mul(mat.perspective(0.6, w / h, 20, 20000), mat.lookAt(eye, state.target, [0, 1, 0]));

    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST);
    gl.disable(gl.BLEND);
    gl.useProgram(terrain.p);
    gl.uniformMatrix4fv(terrain.u.u_mvp, false, mvp);
    gl.uniform1f(terrain.u.u_exag, EXAG);
    gl.uniform3fv(terrain.u.u_ramp, ramp);
    gl.uniform1fv(terrain.u.u_bounds, state.bounds);
    gl.uniform1f(terrain.u.u_k0, state.k0);
    gl.uniform3fv(terrain.u.u_sun, sun);
    gl.uniform3fv(terrain.u.u_fog, [0.91, 0.93, 0.89]);
    gl.uniform1f(terrain.u.u_fogNear, state.dist * 0.9);
    gl.uniform1f(terrain.u.u_fogFar, state.dist * 2.2);
    gl.uniform1f(terrain.u.u_useSat, state.useSat && hasSat ? 1 : 0);
    gl.uniform4fv(terrain.u.u_satExt, satExt);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, satTexture);
    gl.uniform1i(terrain.u.u_sat, 0);
    gl.bindVertexArray(terrain.vao);
    gl.drawElements(gl.TRIANGLES, indexCount, gl.UNSIGNED_INT, 0);

    gl.useProgram(lines.p);
    gl.uniformMatrix4fv(lines.u.u_mvp, false, mvp);
    gl.uniform1f(lines.u.u_exag, EXAG);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    lines.sets.forEach((set, k) => {
      if (!k && !state.lines) return;
      gl.uniform4fv(lines.u.u_color, k ? [0.1, 0.24, 0.21, 0.85] : [0.1, 0.24, 0.21, 0.35]);
      gl.bindVertexArray(set.vao);
      gl.drawArrays(gl.LINES, 0, set.n);
    });

    if (pillars.n) {
      const grow = 1 - (1 - state.grow) ** 3;
      gl.disable(gl.BLEND);
      gl.useProgram(pillars.p);
      gl.uniformMatrix4fv(pillars.u.u_mvp, false, mvp);
      gl.uniform1f(pillars.u.u_exag, EXAG);
      gl.uniform1f(pillars.u.u_grow, grow);
      gl.uniform3fv(pillars.u.u_low, hexRgb(token('--p7')));
      gl.uniform3fv(pillars.u.u_high, [1.0, 0.72, 0.32]);
      gl.bindVertexArray(pillars.vao);
      gl.drawArraysInstanced(gl.TRIANGLES, 0, 30, pillars.n);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.ONE, gl.ONE);
      gl.depthMask(false);
      gl.useProgram(glow.p);
      gl.uniformMatrix4fv(glow.u.u_mvp, false, mvp);
      gl.uniform1f(glow.u.u_exag, EXAG);
      gl.uniform1f(glow.u.u_grow, grow);
      gl.uniform1f(glow.u.u_size, 110000 * dpr);
      gl.uniform1f(glow.u.u_pulse, reducedMotion ? 1 : 0.85 + 0.15 * Math.sin(t / 420));
      gl.bindVertexArray(glow.vao);
      gl.drawArraysInstanced(gl.POINTS, 0, 1, pillars.n);
      gl.depthMask(true);
    }
    if (marks.n) {
      gl.disable(gl.BLEND);
      gl.useProgram(marks.p);
      gl.uniformMatrix4fv(marks.u.u_mvp, false, mvp);
      gl.uniform1f(marks.u.u_exag, EXAG);
      gl.uniform1f(marks.u.u_size, 13 * dpr);
      gl.bindVertexArray(marks.vao);
      gl.drawArrays(gl.POINTS, 0, marks.n);
    }
    gl.bindVertexArray(null);

    const s = EXAG / 1000;
    for (const c of cityEls) {
      const q = project(c.x, c.h * s + 2, c.z);
      c.el.style.display = q ? '' : 'none';
      if (q) c.el.style.transform = `translate(${q[0]}px, ${q[1]}px)`;
    }
    const sel = state.selected;
    const q = sel >= 0 ? project((cells[sel].col + 0.5) * 5, elev[sel] * s, -(cells[sel].row + 0.5) * 5) : null;
    marker.style.display = q ? '' : 'none';
    if (q) marker.style.transform = `translate(${q[0]}px, ${q[1]}px)`;
    frameId = requestAnimationFrame(frame);
  }

  return {
    elevation: elev,
    // values: one per cell. bounds: six class edges. k0: tint strength of the lowest class.
    // alertAt: values at or above it rise as pillars (null for none). hidden(i): draw bare relief.
    setValues(values, { bounds, k0 = 0.22, alertAt = null, hidden = () => false }) {
      const inst = [];
      for (let i = 0; i < N; i++) {
        const v = values[i];
        if (!Number.isFinite(v)) { vals[i] = MISSING; continue; }
        if (hidden(i, v)) { vals[i] = HIDDEN; continue; }
        vals[i] = v;
        if (alertAt !== null && v >= alertAt) inst.push((cells[i].col + 0.5) * 5, -(cells[i].row + 0.5) * 5, elev[i], 40 + Math.sqrt(v) * 320);
      }
      gl.bindBuffer(gl.ARRAY_BUFFER, valBuffer);
      gl.bufferSubData(gl.ARRAY_BUFFER, 0, vals);
      gl.bindBuffer(gl.ARRAY_BUFFER, pillars.inst);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(inst.length ? inst : [0, 0, 0, 0]), gl.DYNAMIC_DRAW);
      const grew = pillars.n === inst.length / 4;
      pillars.n = inst.length / 4;
      if (!grew) state.grow = reducedMotion ? 1 : 0;
      state.bounds = bounds;
      state.k0 = k0;
    },
    setSelected(i) { state.selected = i; },
    // extent: {x0, x1, y0, y1} in map km, y south positive, as satellite.json records it.
    setSatellite(image, extent) {
      gl.bindTexture(gl.TEXTURE_2D, satTexture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, image);
      gl.generateMipmap(gl.TEXTURE_2D);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      satExt = [extent.x0, extent.y0, extent.x1 - extent.x0, extent.y1 - extent.y0];
      hasSat = true;
    },
    setBasemap(useSatellite) { state.useSat = useSatellite; },
    // points: [{x, y, hit}] in map km; drawn on the relief surface.
    relabel() {
      canvas.setAttribute('aria-label', t('relief.aria'));
      cityEls.forEach((c, k) => { c.el.textContent = cityName(geo.cities[k].name); });
    },
    setMarkers(points) {
      const data = new Float32Array(Math.max(4, points.length * 4));
      points.forEach((p, i) => { data.set([p.x, heightAt(p.x, p.y), p.y, p.hit ? 1 : 0], i * 4); });
      gl.bindBuffer(gl.ARRAY_BUFFER, marks.buf);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW);
      marks.n = points.length;
    },
    flyTo(x, z) { state.fit = false; state.target = [x, 0, z]; goal.dist = 900; },
    setLines(on) { state.lines = on; },
    zoom(factor) { state.fit = false; goal.dist = Math.min(9000, Math.max(250, goal.dist / factor)); },
    reset() { state.fit = true; goal.yaw = 0; goal.pitch = 0.82; state.target = [...home]; },
    setVisible(on) {
      state.visible = on;
      canvas.hidden = !on;
      labels.hidden = !on;
      if (on && !frameId) frameId = requestAnimationFrame(frame);
    },
    focus() { canvas.focus(); },
  };
}
