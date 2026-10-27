// 3D relief view: SRTM elevation per 5 km cell, coloured by the verified daily forecast.
// Forecast files go through the same loadForecast() checks as the 2D map.
import { loadForecast, validateManifest, probability } from './model-results.js';

const $ = (id) => document.getElementById(id);
const css = getComputedStyle(document.documentElement);
const token = (name) => css.getPropertyValue(name).trim();
const hexRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
const fmt = (n, d = 0) => n.toLocaleString('ru-RU', { minimumFractionDigits: d, maximumFractionDigits: d });
const DAY_FMT = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });
const dayLabel = (day) => DAY_FMT.format(new Date(day + 'T00:00:00Z')).replace(' г.', '');
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

// Log-spaced classes: 99% of cell-days are below 0.33%, so linear bins would paint one colour.
// The last boundary is the frozen alert threshold, so the top class is exactly the alert set.
const BOUNDS = [0.0001, 0.0003, 0.001, 0.003, 0.01];
const TICKS = ['0', '0,01', '0,03', '0,1', '0,3', '1', ''];
const SKIRT = 22;
const DEFAULT_DAY = '2024-07-15';

const banner = $('banner');
function showBanner(kind, title, text) {
  if (!kind) { banner.hidden = true; return; }
  banner.hidden = false;
  banner.className = 'banner' + (kind === 'danger' ? ' is-danger' : '');
  const icon = kind === 'loading' ? '<span class="spinner" aria-hidden="true"></span>' : `<svg><use href="#i-${kind === 'danger' ? 'alert' : 'info'}"/></svg>`;
  banner.innerHTML = `${icon}<span><b>${title}</b>${text}</span>`;
}

async function sha256(buffer) {
  const d = await crypto.subtle.digest('SHA-256', buffer);
  return Array.from(new Uint8Array(d), (v) => v.toString(16).padStart(2, '0')).join('');
}

// ---------- WebGL helpers ----------
const canvas = $('gl');
const gl = canvas.getContext('webgl2', { antialias: true, alpha: true, premultipliedAlpha: false });

function program(vs, fs) {
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
}

function buffer(data, loc, size, { usage = gl.STATIC_DRAW, divisor = 0 } = {}) {
  const b = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, b);
  gl.bufferData(gl.ARRAY_BUFFER, data, usage);
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
  if (divisor) gl.vertexAttribDivisor(loc, divisor);
  return b;
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

// ---------- shaders ----------
const TERRAIN_VS = `
in vec2 a_pos; in float a_elev; in vec2 a_grad; in float a_prob; in float a_side;
uniform mat4 u_mvp; uniform float u_exag;
out vec3 v_normal; out float v_elev; out float v_prob; out float v_side; out vec2 v_xz; out float v_depth;
void main() {
  float s = u_exag / 1000.0;
  float y = a_side > 1.5 ? -${SKIRT}.0 : a_elev * s;
  v_normal = normalize(vec3(-a_grad.x * s, 1.0, -a_grad.y * s));
  v_elev = a_elev; v_prob = a_prob; v_side = a_side; v_xz = a_pos;
  gl_Position = u_mvp * vec4(a_pos.x, y, a_pos.y, 1.0);
  v_depth = gl_Position.w;
}`;
const TERRAIN_FS = `
in vec3 v_normal; in float v_elev; in float v_prob; in float v_side; in vec2 v_xz; in float v_depth;
uniform vec3 u_ramp[7]; uniform float u_bounds[6]; uniform vec3 u_sun; uniform vec3 u_fog; uniform float u_fogNear; uniform float u_fogFar;
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
    // Cut face of the slab: layered earth, darker towards the base.
    float t = clamp(v_side - 1.0, 0.0, 1.0);
    vec3 c = mix(vec3(0.55, 0.47, 0.36), vec3(0.33, 0.28, 0.22), t);
    c *= 0.92 + 0.08 * step(0.5, fract(v_elev * 0.004));
    color = vec4(c, 1.0);
    return;
  }
  vec3 base = tint(v_elev);
  vec3 c = base;
  if (v_prob < 0.0) {
    float stripe = step(0.5, fract((v_xz.x + v_xz.y) * 0.12));
    c = mix(vec3(0.80, 0.81, 0.78), vec3(0.70, 0.71, 0.68), stripe);
  } else {
    int k = 0;
    for (int i = 0; i < 6; i++) if (v_prob >= u_bounds[i]) k = i + 1;
    float w = k == 0 ? 0.22 : (k == 1 ? 0.55 : (k == 2 ? 0.7 : (k == 3 ? 0.8 : (k == 4 ? 0.88 : (k == 5 ? 0.94 : 1.0)))));
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
const GLOW_FS = `
out vec4 color;
void main() {
  float d = length(gl_PointCoord - 0.5) * 2.0;
  float a = pow(max(1.0 - d, 0.0), 2.2);
  color = vec4(vec3(1.0, 0.55, 0.18) * a, a);
}`;

// ---------- state ----------
const HOME = 3500;
const state = { yaw: 0, pitch: 0.82, dist: HOME, target: [0, 0, 0], exag: 25, grow: 0, view: '3d' };
const goal = { yaw: 0, pitch: 0.82, dist: HOME };
let geo, manifest, cells, elev, grid, probs, days, dayIndex = -1, selected = -1, loadToken = 0;
let terrain, lines, pillars, glow, vertexCount, indexCount, cityEls = [], marker, mvp = [];

async function init() {
  if (!gl) { showBanner('danger', 'WebGL 2 недоступен', 'Браузер не умеет показывать 3D. Обычная карта работает без него: <a href="./">открыть карту</a>.'); return; }
  showBanner('loading', 'Загружаем рельеф и прогноз', 'Проверяем хеши файлов перед показом');
  const [g, m, cb, eb, emeta] = await Promise.all([
    fetch('./assets/geography.json').then((r) => r.json()),
    fetch('./assets/forecast-manifest.json').then((r) => r.json()),
    fetch('./assets/cells.bin').then((r) => r.arrayBuffer()),
    fetch('./assets/elevation.i16').then((r) => r.arrayBuffer()),
    fetch('./assets/elevation.json').then((r) => r.json()),
  ]);
  geo = g; manifest = m;
  validateManifest(manifest);
  if (eb.byteLength !== geo.count * 2 || (await sha256(eb)) !== emeta.sha256) throw Error('Файл высот не совпал с elevation.json');
  $('release').innerHTML = `Модель <b>XGBoost + второй уровень</b> · релиз ${manifest.release_sha256.slice(0, 8)}`;

  const dv = new DataView(cb);
  const raw = new Int16Array(eb);
  cells = new Array(geo.count);
  let minR = 1e9, maxR = -1e9, minC = 1e9, maxC = -1e9;
  for (let i = 0; i < geo.count; i++) {
    const p = i * 34;
    const c = { row: dv.getInt16(p, true), col: dv.getInt16(p + 2, true), lon: dv.getFloat32(p + 8, true), lat: dv.getFloat32(p + 12, true), region: dv.getUint16(p + 16, true) };
    cells[i] = c;
    minR = Math.min(minR, c.row); maxR = Math.max(maxR, c.row); minC = Math.min(minC, c.col); maxC = Math.max(maxC, c.col);
  }
  const W = maxC - minC + 1, H = maxR - minR + 1;
  grid = { W, H, minR, minC, idx: new Int32Array(W * H).fill(-1) };
  for (let i = 0; i < geo.count; i++) grid.idx[(cells[i].row - minR) * W + (cells[i].col - minC)] = i;
  const at = (r, c) => (r < minR || r > maxR || c < minC || c > maxC ? -1 : grid.idx[(r - minR) * W + (c - minC)]);

  // Elevation in metres; the 29 cells without SRTM take their neighbours' mean.
  elev = new Float32Array(geo.count);
  for (let i = 0; i < geo.count; i++) elev[i] = raw[i] === emeta.missing ? NaN : raw[i];
  for (let i = 0; i < geo.count; i++) {
    if (!Number.isNaN(elev[i])) continue;
    let s = 0, n = 0;
    for (const [dr, dc] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { const j = at(cells[i].row + dr, cells[i].col + dc); if (j >= 0 && !Number.isNaN(elev[j])) { s += elev[j]; n++; } }
    elev[i] = n ? s / n : 0;
  }

  // Vertices sit at cell centres: x east, z south (north is away from the default camera).
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
    if (n === 4) { tri(a, d, b); tri(b, d, e); } else if (n === 3) {
      const q = [a, b, e, d].filter((v) => v >= 0); tri(q[0], q[2], q[1]);
    }
  }
  // Skirt: vertical walls along the outer edge turn the surface into a cut block of land.
  for (const v of edges.values()) {
    if (!v) continue;
    const [a, b] = v;
    const base = pos.length / 2;
    for (const [j, s] of [[a, 1], [b, 1], [a, 2], [b, 2]]) { pos.push(pos[j * 2], pos[j * 2 + 1]); el.push(elev[j]); grad.push(0, 0); side.push(s); }
    idx.push(base, base + 2, base + 1, base + 1, base + 2, base + 3);
  }
  vertexCount = pos.length / 2;
  indexCount = idx.length;

  let sx = 0, sz = 0;
  for (let i = 0; i < N; i++) { sx += pos[i * 2]; sz += pos[i * 2 + 1]; }
  state.target = [sx / N, 0, sz / N];

  terrain = program(TERRAIN_VS, TERRAIN_FS);
  terrain.vao = gl.createVertexArray();
  gl.bindVertexArray(terrain.vao);
  const loc = (n) => gl.getAttribLocation(terrain.p, n);
  buffer(new Float32Array(pos), loc('a_pos'), 2);
  buffer(new Float32Array(el), loc('a_elev'), 1);
  buffer(new Float32Array(grad), loc('a_grad'), 2);
  buffer(new Float32Array(side), loc('a_side'), 1);
  probs = new Float32Array(vertexCount).fill(-1);
  terrain.prob = buffer(probs, loc('a_prob'), 1, { usage: gl.DYNAMIC_DRAW });
  const ib = gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint32Array(idx), gl.STATIC_DRAW);

  // Region and national outlines draped over the relief.
  const heightAt = (x, z) => { const j = at(Math.round(-z / 5 - 0.5), Math.round(x / 5 - 0.5)); return j >= 0 ? elev[j] : 0; };
  const segs = (rings, out) => { for (const ring of rings) for (let i = 1; i < ring.length; i++) { for (const [x, z] of [ring[i - 1], ring[i]]) out.push(x, heightAt(x, z), z); } };
  const regionPts = [], outlinePts = [];
  for (const r of geo.regions) segs(r.rings, regionPts);
  segs(geo.outline, outlinePts);
  lines = program(LINE_VS, LINE_FS);
  lines.sets = [regionPts, outlinePts].map((pts) => {
    const vao = gl.createVertexArray(); gl.bindVertexArray(vao);
    buffer(new Float32Array(pts), gl.getAttribLocation(lines.p, 'a_p'), 3);
    return { vao, n: pts.length / 3 };
  });

  // Alert pillars: one instanced box per cell at or above the frozen threshold.
  pillars = program(PILLAR_VS, PILLAR_FS);
  pillars.vao = gl.createVertexArray(); gl.bindVertexArray(pillars.vao);
  const box = [];
  const f = [[-0.5, 0, -0.5], [0.5, 0, -0.5], [0.5, 1, -0.5], [-0.5, 1, -0.5], [-0.5, 0, 0.5], [0.5, 0, 0.5], [0.5, 1, 0.5], [-0.5, 1, 0.5]];
  for (const q of [[0, 1, 2, 3], [5, 4, 7, 6], [4, 0, 3, 7], [1, 5, 6, 2], [3, 2, 6, 7]]) for (const k of [0, 1, 2, 0, 2, 3]) box.push(...f[q[k]]);
  buffer(new Float32Array(box), gl.getAttribLocation(pillars.p, 'a_box'), 3);
  pillars.inst = buffer(new Float32Array(4), gl.getAttribLocation(pillars.p, 'a_inst'), 4, { usage: gl.DYNAMIC_DRAW, divisor: 1 });
  pillars.n = 0;
  glow = program(GLOW_VS, GLOW_FS);
  glow.vao = gl.createVertexArray(); gl.bindVertexArray(glow.vao);
  gl.bindBuffer(gl.ARRAY_BUFFER, pillars.inst);
  const gl_inst = gl.getAttribLocation(glow.p, 'a_inst');
  gl.enableVertexAttribArray(gl_inst); gl.vertexAttribPointer(gl_inst, 4, gl.FLOAT, false, 0, 0); gl.vertexAttribDivisor(gl_inst, 1);
  gl.bindVertexArray(null);

  const labels = $('labels');
  cityEls = geo.cities.map((c) => {
    const el2 = document.createElement('span');
    el2.className = 'city'; el2.textContent = c.name; labels.append(el2);
    return { el: el2, x: c.x, z: c.y, h: heightAt(c.x, c.y) };
  });
  marker = document.createElement('span');
  marker.style.cssText = 'position:absolute;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;border:2.5px solid #193d35;box-shadow:0 0 0 3px #fffefa;display:none';
  labels.append(marker);

  days = manifest.available_days;
  const input = $('date');
  input.min = days[0]; input.max = days.at(-1);
  renderLegend(null);
  bindControls();
  requestAnimationFrame(frame);
  await setDay(days.includes(DEFAULT_DAY) ? days.indexOf(DEFAULT_DAY) : days.length - 1);
}

async function setDay(i) {
  if (i < 0 || i >= days.length) return;
  dayIndex = i;
  const day = days[i];
  const token = ++loadToken;
  $('date').value = day;
  $('date-label').textContent = dayLabel(day);
  $('prev').disabled = i === 0;
  $('next').disabled = i === days.length - 1;
  showBanner('loading', `Загружаем прогноз на ${dayLabel(day)}`, 'Проверяем хеш файла перед показом');
  let values;
  try {
    values = await loadForecast(day, manifest, geo.count);
  } catch (err) {
    if (token !== loadToken) return;
    console.error(err);
    applyForecast(null);
    showBanner('danger', 'Файл прогноза не прошёл проверку', `Карта на ${dayLabel(day)} не показана. ${err.message}`);
    return;
  }
  if (token !== loadToken) return;
  applyForecast(values);
  const finite = manifest.prediction_assets[day].finite_cells;
  if (finite === 0) showBanner('info', `Нет данных на ${dayLabel(day)}`, 'Нет обязательных наблюдений влажности почвы. Значения не подставляются.');
  else showBanner(null);
}

function applyForecast(values) {
  const N = geo.count;
  const threshold = manifest.threshold;
  const counts = new Array(7).fill(0);
  const inst = [];
  let finite = 0, above = 0, max = -1;
  for (let i = 0; i < N; i++) {
    const p = values ? values[i] : NaN;
    if (Number.isNaN(p)) { probs[i] = -1; continue; }
    probs[i] = p; finite++;
    if (p > max) max = p;
    let k = 0;
    for (let b = 0; b < BOUNDS.length; b++) if (p >= BOUNDS[b]) k = b + 1;
    if (p >= threshold) { k = 6; above++; inst.push((cells[i].col + 0.5) * 5, -(cells[i].row + 0.5) * 5, elev[i], 40 + Math.sqrt(p) * 320); }
    counts[k]++;
  }
  // Skirt vertices keep the "missing" value; their colour comes from the earth shader.
  gl.bindBuffer(gl.ARRAY_BUFFER, terrain.prob);
  gl.bufferSubData(gl.ARRAY_BUFFER, 0, probs);
  gl.bindBuffer(gl.ARRAY_BUFFER, pillars.inst);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(inst.length ? inst : [0, 0, 0, 0]), gl.DYNAMIC_DRAW);
  pillars.n = inst.length / 4;
  state.grow = reducedMotion ? 1 : 0;
  $('metrics').innerHTML = values ? `
    <div class="metric"><span class="label">Ячеек с прогнозом</span><span class="value">${fmt(finite)}</span></div>
    <div class="metric"><span class="label">Выше порога</span><span class="value${above ? ' is-accent' : ''}">${fmt(above)}</span></div>
    <div class="metric"><span class="label">Максимум</span><span class="value">${finite ? probability(max) : '—'}</span></div>` : '';
  renderLegend(values ? counts : null);
  if (selected >= 0) showCard(selected);
}

function renderLegend(counts) {
  const ramp = [1, 2, 3, 4, 5, 6, 7].map((i) => token('--p' + i));
  const th = probability(manifest ? manifest.threshold : NaN).replace(/0+%$/, '%');
  $('legend').innerHTML = `
    <span class="title">Вероятность нового очага за сутки, %</span>
    <div class="bins">${ramp.map((c) => `<i style="background:${c}"></i>`).join('')}<span class="threshold" title="Порог тревоги"></span></div>
    <div class="ticks">${TICKS.map((t, i) => `<span>${i === 6 ? th : t}</span>`).join('')}</div>
    ${counts ? `<div class="counts">${counts.map((n) => `<span>${fmt(n)}</span>`).join('')}</div>` : ''}
    <span class="note">Шкала логарифмическая: у 99% ячеек-дней вероятность ниже 0,33%. Светящиеся столбы — ячейки выше порога тревоги ${th}, выбранного на 2022 году. Штриховка — нет данных.</span>`;
}

function showCard(i) {
  selected = i;
  const c = cells[i];
  const p = probs[i];
  const label = geo.regions[c.region].label;
  const region = /ская$/.test(label) ? label + ' область' : label;
  const alert = p >= manifest.threshold;
  const card = $('card');
  card.hidden = false;
  card.innerHTML = `<header><div><span class="label">Выбранная ячейка</span><h3>${region}</h3></div><button class="btn is-icon" id="card-close" aria-label="Закрыть карточку"><svg><use href="#i-close"/></svg></button></header>
    <div><span class="big${alert ? ' is-alert' : ''}">${p < 0 ? '—' : probability(p)}</span></div>
    ${alert ? '<span class="chip is-alert">Выше порога тревоги</span>' : ''}
    <span class="label">${p < 0 ? 'Нет прогноза на эту дату' : 'Вероятность нового очага за сутки'}</span>
    <dl class="kv"><dt>Высота</dt><dd>${fmt(Math.round(elev[i]))} м</dd><dt>Координаты</dt><dd>${fmt(c.lat, 3)}° с. ш., ${fmt(c.lon, 3)}° в. д.</dd><dt>Ячейка</dt><dd>g5000_${c.row}_${c.col}</dd></dl>`;
  $('card-close').onclick = () => { card.hidden = true; selected = -1; };
}

// ---------- interaction ----------
function setView(view) {
  state.view = view;
  $('view-3d').setAttribute('aria-pressed', view === '3d');
  $('view-top').setAttribute('aria-pressed', view === 'top');
  if (view === 'top') { goal.pitch = 1.5607; goal.yaw = 0; } else { goal.pitch = 0.82; }
}

function bindControls() {
  $('prev').onclick = () => setDay(dayIndex - 1);
  $('next').onclick = () => setDay(dayIndex + 1);
  $('date').onchange = (e) => { const i = days.indexOf(e.target.value); if (i >= 0) setDay(i); };
  $('view-3d').onclick = () => setView('3d');
  $('view-top').onclick = () => setView('top');
  $('reset').onclick = () => { goal.dist = HOME; goal.yaw = 0; setView(state.view); fitTarget(); };
  $('exag').oninput = (e) => { state.exag = +e.target.value; $('exag-label').textContent = e.target.value; };
  addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT') return;
    if (e.key === 'ArrowLeft') setDay(dayIndex - 1);
    if (e.key === 'ArrowRight') setDay(dayIndex + 1);
  });

  let drag = null;
  const pointers = new Map();
  canvas.addEventListener('pointerdown', (e) => {
    canvas.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    drag = { x: e.clientX, y: e.clientY, moved: 0, pan: e.shiftKey || e.button === 2 };
    canvas.classList.add('dragging');
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const prev = pointers.get(e.pointerId);
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (drag.pinch) goal.dist = Math.min(6000, Math.max(250, goal.dist * drag.pinch / d));
      drag.pinch = d; drag.moved = 99;
      return;
    }
    const dx = e.clientX - prev[0], dy = e.clientY - prev[1];
    drag.moved += Math.abs(dx) + Math.abs(dy);
    if (drag.pan) {
      const k = goal.dist / canvas.clientHeight;
      const c = Math.cos(state.yaw), s = Math.sin(state.yaw);
      state.target[0] -= (dx * c - dy * s * 1.3) * k;
      state.target[2] -= (-dx * s - dy * c * 1.3) * k;
    } else {
      goal.yaw -= dx * 0.005;
      if (state.view === '3d') goal.pitch = Math.min(1.45, Math.max(0.25, goal.pitch + dy * 0.004));
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
  canvas.addEventListener('wheel', (e) => { e.preventDefault(); goal.dist = Math.min(6000, Math.max(250, goal.dist * Math.exp(e.deltaY * 0.0012))); }, { passive: false });
}

function fitTarget() {
  let sx = 0, sz = 0;
  for (const c of cells) { sx += (c.col + 0.5) * 5; sz += -(c.row + 0.5) * 5; }
  state.target = [sx / cells.length, 0, sz / cells.length];
}

function project(x, y, z) {
  const m = mvp;
  const cx = m[0] * x + m[4] * y + m[8] * z + m[12], cy = m[1] * x + m[5] * y + m[9] * z + m[13], cw = m[3] * x + m[7] * y + m[11] * z + m[15];
  if (cw <= 0) return null;
  return [(cx / cw * 0.5 + 0.5) * canvas.clientWidth, (1 - (cy / cw * 0.5 + 0.5)) * canvas.clientHeight, cw];
}

function pick(px, py) {
  const r = canvas.getBoundingClientRect();
  px -= r.left; py -= r.top;
  const s = state.exag / 1000;
  let best = -1, bestScore = 1e9;
  for (let i = 0; i < cells.length; i++) {
    const c = cells[i];
    const q = project((c.col + 0.5) * 5, elev[i] * s, -(c.row + 0.5) * 5);
    if (!q) continue;
    const d = Math.hypot(q[0] - px, q[1] - py);
    if (d < 14) { const score = d + q[2] * 0.002; if (score < bestScore) { bestScore = score; best = i; } }
  }
  if (best >= 0) showCard(best); else { $('card').hidden = true; selected = -1; }
}

// ---------- render loop ----------
function frame(t) {
  const dpr = Math.min(devicePixelRatio || 1, 2);
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
  const ease = reducedMotion ? 1 : 0.12;
  state.yaw += (goal.yaw - state.yaw) * ease;
  state.pitch += (goal.pitch - state.pitch) * ease;
  state.dist += (goal.dist - state.dist) * ease;
  state.grow = Math.min(1, state.grow + (reducedMotion ? 1 : 0.035));

  const cp = Math.cos(state.pitch), sp = Math.sin(state.pitch);
  const [tx, ty, tz] = state.target;
  const eye = [tx + state.dist * cp * Math.sin(state.yaw), ty + state.dist * sp, tz + state.dist * cp * Math.cos(state.yaw)];
  const up = state.pitch > 1.5 ? [-Math.sin(state.yaw), 0, -Math.cos(state.yaw)] : [0, 1, 0];
  mvp = mat.mul(mat.perspective(0.6, w / h, 20, 20000), mat.lookAt(eye, state.target, up));

  gl.viewport(0, 0, canvas.width, canvas.height);
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  gl.enable(gl.DEPTH_TEST);
  gl.disable(gl.BLEND);

  gl.useProgram(terrain.p);
  gl.uniformMatrix4fv(terrain.u.u_mvp, false, mvp);
  gl.uniform1f(terrain.u.u_exag, state.exag);
  gl.uniform3fv(terrain.u.u_ramp, [1, 2, 3, 4, 5, 6, 7].flatMap((i) => hexRgb(token('--p' + i))));
  gl.uniform1fv(terrain.u.u_bounds, [...BOUNDS, manifest ? manifest.threshold : 1]);
  const sun = [-0.55, 0.72, -0.42], sl = Math.hypot(...sun);
  gl.uniform3fv(terrain.u.u_sun, sun.map((v) => v / sl));
  gl.uniform3fv(terrain.u.u_fog, [0.91, 0.93, 0.89]);
  gl.uniform1f(terrain.u.u_fogNear, state.dist * 0.9);
  gl.uniform1f(terrain.u.u_fogFar, state.dist * 2.2);
  gl.bindVertexArray(terrain.vao);
  gl.drawElements(gl.TRIANGLES, indexCount, gl.UNSIGNED_INT, 0);

  gl.useProgram(lines.p);
  gl.uniformMatrix4fv(lines.u.u_mvp, false, mvp);
  gl.uniform1f(lines.u.u_exag, state.exag);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  lines.sets.forEach((set, k) => {
    gl.uniform4fv(lines.u.u_color, k ? [0.1, 0.24, 0.21, 0.85] : [0.1, 0.24, 0.21, 0.35]);
    gl.bindVertexArray(set.vao);
    gl.drawArrays(gl.LINES, 0, set.n);
  });

  if (pillars.n) {
    const grow = 1 - (1 - state.grow) ** 3;
    gl.disable(gl.BLEND);
    gl.useProgram(pillars.p);
    gl.uniformMatrix4fv(pillars.u.u_mvp, false, mvp);
    gl.uniform1f(pillars.u.u_exag, state.exag);
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
    gl.uniform1f(glow.u.u_exag, state.exag);
    gl.uniform1f(glow.u.u_grow, grow);
    gl.uniform1f(glow.u.u_size, 110000 * dpr);
    gl.uniform1f(glow.u.u_pulse, reducedMotion ? 1 : 0.85 + 0.15 * Math.sin(t / 420));
    gl.bindVertexArray(glow.vao);
    gl.drawArraysInstanced(gl.POINTS, 0, 1, pillars.n);
    gl.depthMask(true);
  }
  gl.bindVertexArray(null);

  const s = state.exag / 1000;
  for (const c of cityEls) {
    const q = project(c.x, c.h * s + 2, c.z);
    c.el.style.display = q ? '' : 'none';
    if (q) c.el.style.transform = `translate(${q[0] + 8}px, ${q[1]}px) translate(0, -50%)`;
  }
  if (selected >= 0 && !$('card').hidden) {
    const c = cells[selected];
    const q = project((c.col + 0.5) * 5, elev[selected] * s, -(c.row + 0.5) * 5);
    marker.style.display = q ? '' : 'none';
    if (q) marker.style.transform = `translate(${q[0]}px, ${q[1]}px)`;
  } else marker.style.display = 'none';

  requestAnimationFrame(frame);
}

init().catch((err) => {
  console.error(err);
  showBanner('danger', 'Не удалось открыть 3D-вид', err.message);
});
