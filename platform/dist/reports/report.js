// Shared code for report pages: verified data loading, localised number formats, SVG charts.
// Every number on a report comes from a release file checked against its SHA-256 record.

import { t, locale, bindSwitch, onLang } from '../i18n.js?v=20261105-m2';
import './pages-i18n.js?v=20261105-m2';

export { t };
export const $ = (id) => document.getElementById(id);
const ru = (v, min, max) => v.toLocaleString(locale(), { minimumFractionDigits: min, maximumFractionDigits: max });
export const pct = (v, d = 2) => ru(v * 100, d, d) + '%';
export const num = (v, d = 0) => ru(v, d, d);
export const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

export function parseCsv(text) {
  const [head, ...rows] = text.trim().split(/\r?\n/);
  const keys = head.split(',');
  return rows.map((row) => {
    const cells = row.split(',');
    return Object.fromEntries(keys.map((k, i) => [k, cells[i] !== '' && Number.isFinite(+cells[i]) ? +cells[i] : cells[i]]));
  });
}

async function sha256(buffer) {
  const d = await crypto.subtle.digest('SHA-256', buffer);
  return Array.from(new Uint8Array(d), (v) => v.toString(16).padStart(2, '0')).join('');
}

const checked = [];
// record: JSON with an `outputs` map of file -> SHA-256. base: folder the files live in.
export async function loadVerified(record, base, files) {
  const outputs = (await (await fetch(record, { cache: 'no-store' })).json()).outputs;
  const out = {};
  await Promise.all(files.map(async (file) => {
    const expected = outputs?.[file];
    if (!expected) throw Error(`${file} отсутствует в ${record.split('/').pop()}`);
    const response = await fetch(base + file, { cache: 'no-store' });
    if (!response.ok) throw Error(`${file} не найден`);
    const buffer = await response.arrayBuffer();
    if ((await sha256(buffer)) !== expected) throw Error(`${file} не совпал с записью релиза`);
    const text = new TextDecoder().decode(buffer);
    out[file] = file.endsWith('.json') ? JSON.parse(text) : parseCsv(text);
    checked.push(file);
  }));
  return out;
}

// refs: {name: {path, sha256}} from a model manifest, paths relative to the site root.
export async function loadRefs(refs, names) {
  const out = {};
  await Promise.all(names.map(async (name) => {
    const ref = refs?.[name];
    if (!ref) throw Error(`${name} отсутствует в манифесте`);
    const file = ref.path.split('/').pop();
    const response = await fetch('.' + ref.path, { cache: 'no-store' });
    if (!response.ok) throw Error(`${file} не найден`);
    const buffer = await response.arrayBuffer();
    if ((await sha256(buffer)) !== ref.sha256) throw Error(`${file} не совпал с записью релиза`);
    const text = new TextDecoder().decode(buffer);
    out[name] = file.endsWith('.json') ? JSON.parse(text) : parseCsv(text);
    checked.push(file);
  }));
  return out;
}

// The badge names the model the map opens with: v7 from the live log, else v6, else v5.
export async function header() {
  try {
    const live = await fetch('../assets/forecast-live.json');
    const v7 = live.ok ? (await live.json()).models?.v7 : null;
    if (v7) {
      $('release').innerHTML = t('release', { model: 'XGBoost v7', hash: esc(v7.release_sha256.slice(0, 8)) });
      return;
    }
    const v6 = await fetch('../assets/forecast-manifest-v6.json');
    const m = v6.ok ? await v6.json() : await (await fetch('../assets/forecast-manifest.json')).json();
    $('release').innerHTML = t('release', { model: v6.ok ? 'XGBoost v6' : t('model.stack'), hash: esc(m.release_sha256.slice(0, 8)) });
  } catch { /* the badge is optional */ }
}

// Runs render() after data loads; shows a verified chip or a blocking error.
export async function run(render) {
  // Charts and tables are built once from verified files, so a language switch reloads the page.
  bindSwitch();
  onLang(() => location.reload());
  header();
  const status = $('status');
  // Sections open before rendering so charts can measure their width; an error closes them again.
  const late = document.querySelectorAll('[data-after-load]');
  late.forEach((el) => { el.hidden = false; el.style.visibility = 'hidden'; });
  try {
    await render();
    status.className = 'chip is-verified';
    status.textContent = t('rep.verified', { n: checked.length });
    status.title = checked.join(', ');
    late.forEach((el) => { el.style.visibility = ''; });
  } catch (error) {
    late.forEach((el) => { el.hidden = true; el.style.visibility = ''; });
    console.error(error);
    status.className = 'chip is-accent';
    status.textContent = t('rep.notPassed');
    $('error').hidden = false;
    $('error').querySelector('p').textContent = error.message + t('rep.hidden');
  }
}

export function table(headers, rows, { current = -1, tag = t('rep.current') } = {}) {
  return `<div class="table-wrap"><table class="table"><thead><tr>${headers.map((h) => `<th scope="col">${h}</th>`).join('')}</tr></thead><tbody>${rows
    .map((r, i) => `<tr${i === current ? ' class="is-current"' : ''}>${r.map((c, j) => `<td>${c}${j === 0 && i === current && tag ? `<span class="tag">${tag}</span>` : ''}</td>`).join('')}</tr>`)
    .join('')}</tbody></table></div>`;
}

// Charts are drawn at the container's pixel width so text stays at its real size on phones.
export const widthOf = (el) => Math.round(el.clientWidth - parseFloat(getComputedStyle(el).paddingLeft) - parseFloat(getComputedStyle(el).paddingRight));
// Two panels side by side when there is room, else stacked.
export const panelWidth = (el) => { const w = widthOf(el); return w >= 600 ? Math.floor((w - 24) / 2) : w; };

const niceStep =(max) => { const raw = max / 4, p = 10 ** Math.floor(Math.log10(raw)); return [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw); };

// One panel of points with 95% intervals on a shared percent axis.
export function dotPanel({ title, rows, max, width = 360 }) {
  const W = Math.max(280, width), left = 8, right = W - 16, rowH = 48, top = 34, H = top + rows.length * rowH + 28;
  const step = niceStep(max), top_ = Math.ceil(max / step) * step;
  const x = (v) => left + (v / top_) * (right - left);
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title)}"><text x="${left}" y="16" class="t-strong">${esc(title)}</text>`;
  for (let t = 0; t <= top_ + 1e-12; t += step) {
    s += `<line class="grid" x1="${x(t)}" x2="${x(t)}" y1="${top - 6}" y2="${H - 24}"/><text x="${x(t)}" y="${H - 8}" text-anchor="middle">${num(t * 100, step * 100 < 1 ? 1 : 0)}%</text>`;
  }
  rows.forEach((r, i) => {
    const y = top + i * rowH + 30, fill = r.accent ? 'var(--accent)' : 'var(--ink-soft)';
    s += `<text x="${left}" y="${y - 14}" class="t-ink">${esc(r.label)}</text>`;
    if (r.lo !== undefined) s += `<line x1="${x(r.lo)}" x2="${x(r.hi)}" y1="${y}" y2="${y}" stroke="${fill}" stroke-width="2"/><line x1="${x(r.lo)}" x2="${x(r.lo)}" y1="${y - 5}" y2="${y + 5}" stroke="${fill}" stroke-width="2"/><line x1="${x(r.hi)}" x2="${x(r.hi)}" y1="${y - 5}" y2="${y + 5}" stroke="${fill}" stroke-width="2"/>`;
    const anchor = x(r.value) > right - 70 ? 'end' : 'start', dx = anchor === 'end' ? -10 : 10;
    const edge = anchor === 'end' ? (r.lo ?? r.value) : (r.hi ?? r.value);
    s += `<circle cx="${x(r.value)}" cy="${y}" r="5.5" fill="${fill}" stroke="var(--surface)" stroke-width="2"/><text x="${x(edge) + dx}" y="${y + 4}" text-anchor="${anchor}" class="t-ink">${pct(r.value)}</text>`;
  });
  return s + '</svg>';
}

// Horizontal bars with optional interval whiskers, value axis in the given formatter.
// Narrow screens put each label above its bar instead of beside it.
export function barChart({ rows, max, format, title, width = 720 }) {
  const W = Math.max(300, width), stacked = W < 520;
  const labelW = stacked ? 18 : Math.min(190, Math.round(W * 0.42)), right = stacked ? W - 22 : W - 56, rowH = stacked ? 46 : 34, bar = stacked ? 18 : 7;
  const top = title ? 30 : 8, H = top + rows.length * rowH + 30;
  const step = niceStep(max), top_ = Math.ceil(max / step) * step;
  const x = (v) => labelW + (v / top_) * (right - labelW);
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title || '')}">${title ? `<text x="0" y="16" class="t-strong">${esc(title)}</text>` : ''}`;
  for (let t = 0; t <= top_ + 1e-12; t += step) s += `<line class="grid" x1="${x(t)}" x2="${x(t)}" y1="${top}" y2="${H - 24}"/><text x="${x(t)}" y="${H - 8}" text-anchor="middle">${format(t)}</text>`;
  rows.forEach((r, i) => {
    const y = top + i * rowH, fill = r.accent ? 'var(--accent)' : 'var(--p3)', mid = y + bar + 10;
    s += stacked
      ? `<text x="${labelW}" y="${y + 14}" class="${r.accent ? 't-strong' : 't-ink'}">${esc(r.label)}</text>`
      : `<text x="${labelW - 10}" y="${y + 21}" text-anchor="end" class="${r.accent ? 't-strong' : 't-ink'}">${esc(r.label)}</text>`;
    s += `<rect x="${labelW}" y="${y + bar}" width="${Math.max(1, x(r.value) - labelW)}" height="20" rx="3" fill="${fill}"/>`;
    if (r.lo !== undefined) s += `<line x1="${x(r.lo)}" x2="${x(r.hi)}" y1="${mid}" y2="${mid}" stroke="var(--ink)" stroke-width="1.5"/><line x1="${x(r.lo)}" x2="${x(r.lo)}" y1="${mid - 5}" y2="${mid + 5}" stroke="var(--ink)" stroke-width="1.5"/><line x1="${x(r.hi)}" x2="${x(r.hi)}" y1="${mid - 5}" y2="${mid + 5}" stroke="var(--ink)" stroke-width="1.5"/>`;
    s += stacked
      ? `<text x="${W - 4}" y="${y + 14}" class="t-ink" text-anchor="end">${format(r.value)}</text>`
      : `<text x="${Math.min(right, x(r.hi ?? r.value) + 8)}" y="${mid + 4}" class="t-ink" text-anchor="${x(r.hi ?? r.value) + 60 > right ? 'end' : 'start'}">${format(r.value)}</text>`;
  });
  return s + '</svg>';
}

// Log-scale y axis helper shared by the curve and reliability charts.
const logTicks = (lo, hi) => { const t = []; for (let e = Math.ceil(Math.log10(lo)); e <= Math.floor(Math.log10(hi)); e++) t.push(10 ** e); return t; };
const pctTick = (v) => (v * 100 >= 1 ? num(v * 100) : (v * 100).toLocaleString(locale(), { maximumSignificantDigits: 1 })) + '%';

// Precision–recall curve: recall linear on x, precision log on y, with labelled points.
export function prCurve({ curve, points, title, width = 720 }) {
  const W = Math.max(300, width), H = W < 500 ? 320 : 380, L = 64, R = W - 20, T = 34, B = H - 50;
  const yLo = 1e-4, yHi = 1;
  const x = (v) => L + v * (R - L);
  const y = (v) => B - ((Math.log10(Math.max(v, yLo)) - Math.log10(yLo)) / (Math.log10(yHi) - Math.log10(yLo))) * (B - T);
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title)}"><text x="0" y="16" class="t-strong">${esc(title)}</text>`;
  for (const t of logTicks(yLo, yHi)) s += `<line class="grid" x1="${L}" x2="${R}" y1="${y(t)}" y2="${y(t)}"/><text x="${L - 8}" y="${y(t) + 4}" text-anchor="end">${pctTick(t)}</text>`;
  for (let t = 0; t <= 1.0001; t += 0.2) s += `<line class="grid" x1="${x(t)}" x2="${x(t)}" y1="${T}" y2="${B}"/><text x="${x(t)}" y="${B + 18}" text-anchor="middle">${num(t * 100)}%</text>`;
  s += `<text x="${(L + R) / 2}" y="${H - 6}" text-anchor="middle">${t('rep.recallAxis')}</text><text x="14" y="${(T + B) / 2}" transform="rotate(-90 14 ${(T + B) / 2})" text-anchor="middle">${t('rep.precisionAxis')}</text>`;
  s += `<polyline fill="none" stroke="var(--ink-soft)" stroke-width="1.8" points="${curve.map((c) => `${x(c.recall).toFixed(1)},${y(c.precision).toFixed(1)}`).join(' ')}"/>`;
  for (const p of points) s += `<circle cx="${x(p.recall)}" cy="${y(p.precision)}" r="6" fill="${p.accent ? 'var(--accent)' : 'var(--p5)'}" stroke="var(--surface)" stroke-width="2"/><text x="${x(p.recall) + 10}" y="${y(p.precision) - 8}" class="t-ink">${esc(p.label)}</text>`;
  return s + '</svg>';
}

// Reliability: predicted vs observed frequency, both on log axes, with interval whiskers.
export function reliability({ bins, title, width = 560 }) {
  const W = Math.max(300, Math.min(560, width)), H = W < 500 ? 360 : 440, L = 70, R = W - 20, T = 34, B = H - 50;
  const vals = bins.flatMap((b) => [b.predicted, b.observed, b.ci_lower, b.ci_upper]).filter((v) => v > 0);
  const lo = 10 ** Math.floor(Math.log10(Math.min(...vals))), hi = 10 ** Math.ceil(Math.log10(Math.max(...vals)));
  const sc = (v, a, b) => a + ((Math.log10(Math.max(v, lo)) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * (b - a);
  const x = (v) => sc(v, L, R), y = (v) => sc(v, B, T);
  const maxW = Math.max(...bins.map((b) => b.weight));
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" style="max-width:${W}px" role="img" aria-label="${esc(title)}"><text x="0" y="16" class="t-strong">${esc(title)}</text>`;
  // On narrow charts every other x label is dropped so neighbours do not collide.
  logTicks(lo, hi).forEach((t, i, all) => {
    s += `<line class="grid" x1="${L}" x2="${R}" y1="${y(t)}" y2="${y(t)}"/><line class="grid" x1="${x(t)}" x2="${x(t)}" y1="${T}" y2="${B}"/><text x="${L - 8}" y="${y(t) + 4}" text-anchor="end">${pctTick(t)}</text>`;
    if (W >= 500 || (all.length - 1 - i) % 2 === 0) s += `<text x="${x(t)}" y="${B + 18}" text-anchor="middle">${pctTick(t)}</text>`;
  });
  s += `<line x1="${x(lo)}" y1="${y(lo)}" x2="${x(hi)}" y2="${y(hi)}" stroke="var(--line-strong)" stroke-dasharray="4 4"/>`;
  s += `<text x="${(L + R) / 2}" y="${H - 4}" text-anchor="middle">${t('rep.predAxis')}</text><text x="14" y="${(T + B) / 2}" transform="rotate(-90 14 ${(T + B) / 2})" text-anchor="middle">${t('rep.obsAxis')}</text>`;
  for (const b of bins) {
    if (b.ci_lower > 0) s += `<line x1="${x(b.predicted)}" x2="${x(b.predicted)}" y1="${y(b.ci_lower)}" y2="${y(b.ci_upper)}" stroke="var(--ink-soft)" stroke-width="1.5"/>`;
    s += `<circle cx="${x(b.predicted)}" cy="${y(b.observed)}" r="${3 + 6 * Math.sqrt(b.weight / maxW)}" fill="var(--accent)" fill-opacity="0.85" stroke="var(--surface)" stroke-width="1.5"/>`;
  }
  return s + '</svg>';
}
