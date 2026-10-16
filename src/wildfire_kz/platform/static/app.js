"use strict";

const api = (path, opts) =>
  fetch(path, opts).then(async (r) => {
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  });
const $ = (id) => document.getElementById(id);
// daily cell probabilities are small: keep two significant digits below 0.1 %
const fmtP = (p) => (p == null ? "–" : p >= 0.01 ? (100 * p).toFixed(1) + "%" : p >= 0.001 ? (100 * p).toFixed(2) + "%" : p <= 0 ? "0%" : Number((100 * p).toPrecision(2)) + "%");
const fmt = (v, d = 3) => (v == null || Number.isNaN(v) ? "–" : Number(v).toFixed(d));
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const state = { cfg: null, days: [], date: null, overlay: null, summary: null, opacity: 0.8, card: null };

// ------------------------------------------------------------------ map
const map = L.map("map", { zoomControl: true, preferCanvas: true }).setView([48.0, 67.0], 5);
function addBasemap(url, attribution) {
  if (url) L.tileLayer(url, { maxZoom: 12, attribution }).addTo(map);
}
async function addBoundary() {
  try {
    const gj = await api("api/boundary");
    L.geoJSON(gj, { interactive: false,
      style: { color: "#52514e", weight: 1.5, fill: false, dashArray: "4 3" } }).addTo(map);
  } catch (e) { /* boundary is optional decoration */ }
}
let topMarkers = L.layerGroup().addTo(map);
let obsMarkers = L.layerGroup().addTo(map);
const obsIcon = L.divIcon({ className: "obs-icon", html: "✕", iconSize: [16, 16] });

function classLabel(k) {
  const labels = state.summary?.class_labels || [];
  return labels[k] ?? `class ${k}`;
}
function classColor(k) {
  return state.cfg.class_colors[Math.min(k, state.cfg.class_colors.length - 1)];
}

// ------------------------------------------------------------------ tabs
document.querySelectorAll(".tab").forEach((btn) =>
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".tabpanel").forEach((p) =>
      p.classList.toggle("active", p.id === `tab-${btn.dataset.tab}`));
    if (btn.dataset.tab === "map") setTimeout(() => map.invalidateSize(), 50);
  }));

// ------------------------------------------------------------------ day loading
async function loadDays(selectDate) {
  state.days = await api("api/days");
  const sel = $("day-select");
  sel.innerHTML = state.days
    .map((d) => `<option value="${d.date}">${d.date} · ${d.partition}${d.source === "forecast" ? " · forecast" : ""}</option>`)
    .join("");
  if (!state.days.length) {
    $("map-note").textContent = "No maps yet — run the 'map' stage or a forecast.";
    return;
  }
  // default: requested day, else the latest operational forecast, else the highest-hazard day
  const forecasts = state.days.filter((d) => d.source === "forecast");
  const peak = state.days.reduce((a, d) => ((d.max_p ?? -1) > (a.max_p ?? -1) ? d : a));
  const target = selectDate && state.days.some((d) => d.date === selectDate)
    ? selectDate
    : forecasts.length ? forecasts[forecasts.length - 1].date : peak.date;
  sel.value = target;
  await showDay(target);
}

async function showDay(date) {
  state.date = date;
  const s = await api(`api/days/${date}`);
  state.summary = s;
  $("day-source").textContent = s.source === "forecast" ? "operational forecast" : "pipeline map";
  $("day-cutoff").textContent = `Predictors observed up to ${s.predictors_up_to} (UTC). ${s.eligibility_note || ""}`;
  const pb = $("badge-partition");
  pb.hidden = false;
  pb.textContent = `${s.partition} period`;
  if (state.overlay) map.removeLayer(state.overlay);
  state.overlay = L.imageOverlay(`api/days/${date}/overlay.png`, s.bounds_latlon, {
    opacity: state.opacity, interactive: false,
  }).addTo(map);
  if (!showDay.fitted) { map.fitBounds(s.bounds_latlon, { padding: [20, 20] }); showDay.fitted = true; }
  renderLegend(s);
  const obs = s.observed_new_events;
  obsMarkers.clearLayers();
  (obs || []).forEach((o) => L.marker([o.lat, o.lon], { icon: obsIcon, interactive: false })
    .addTo(obsMarkers));
  $("map-note").innerHTML = obs == null
    ? "Observed outcomes not shown for this day."
    : `<b>✕</b> ${obs.length} observed new-event start(s) (VIIRS first detections) ·
       <span style="color:#7f2704">○</span> top-10 hazard cells`;
  renderTop(await api(`api/days/${date}/top`));
}

function renderLegend(s) {
  const b = s.class_boundaries;
  const counts = s.class_counts;
  const max = Math.max(1, ...counts);
  const freq = state.card?.class_frequencies_calibration || [];
  $("legend").innerHTML = s.class_labels.map((lab, k) => {
    const lo = k === 0 ? 0 : b[k - 1];
    const hi = k < b.length ? b[k] : 1;
    const f = freq[k]?.observed_event_frequency;
    const title = f != null ? ` title="Observed event frequency in this class (calibration year): ${fmtP(f)}"` : "";
    return `<div class="legend-row"${title}>
      <span class="swatch" style="background:${classColor(k)}"></span>
      <span>${esc(lab)} <span class="legend-range">${fmtP(lo)}–${fmtP(hi)}</span></span>
      <span class="legend-bar"><span style="width:${(100 * counts[k]) / max}%"></span></span>
      <span class="legend-count">${counts[k]}</span></div>`;
  }).join("");
}

function renderTop(rows) {
  topMarkers.clearLayers();
  $("top-list").innerHTML = rows.map((r, i) =>
    `<li data-i="${i}">cell ${r.cell_id} <span class="p">${fmtP(r.p)}</span></li>`).join("");
  rows.slice(0, 10).forEach((r) =>
    L.circleMarker([r.lat, r.lon], { radius: 5, color: "#7f2704", weight: 2, fillOpacity: 0 })
      .addTo(topMarkers));
  $("top-list").querySelectorAll("li").forEach((li) =>
    li.addEventListener("click", () => {
      const r = rows[+li.dataset.i];
      map.setView([r.lat, r.lon], Math.max(map.getZoom(), 8));
      openCell(L.latLng(r.lat, r.lon));
    }));
}

// ------------------------------------------------------------------ cell drill-down
async function openCell(latlng) {
  const popup = L.popup({ maxWidth: 360 }).setLatLng(latlng).setContent("Loading…").openOn(map);
  try {
    const c = await api(`api/days/${state.date}/cell?lat=${latlng.lat}&lon=${latlng.lng}`);
    popup.setContent(cellHtml(c));
  } catch (e) {
    popup.setContent(`<span class="muted">${esc(e.message)}</span>`);
  }
}
map.on("click", (e) => openCell(e.latlng));

function cellHtml(c) {
  if (!c.eligible) {
    return `<b>Cell ${c.cell_id}</b><div class="pop-note">Not in the new-event risk set
      today (a detection in the previous 48 h).</div>`;
  }
  const obs = c.observed_new_event == null ? "" :
    `<div class="small">Observed new-event start: <b>${c.observed_new_event ? "yes" : "no"}</b></div>`;
  let drivers = "";
  const ex = c.explanation;
  if (ex && ex.drivers) {
    const m = Math.max(...ex.drivers.map((d) => Math.abs(d.contribution)), 1e-9);
    drivers = `<div class="small muted" style="margin-top:8px">Top drivers (${esc(ex.scale)} contribution)</div>
      <div class="drivers">${ex.drivers.map((d) => {
        const w = (50 * Math.abs(d.contribution)) / m;
        const left = d.contribution >= 0 ? 50 : 50 - w;
        const col = d.contribution >= 0 ? "var(--pos)" : "var(--neg)";
        return `<div class="driver"><span class="name" title="${esc(d.feature)}">${esc(d.feature)}</span>
          <span class="track"><span class="bar" style="left:${left}%;width:${w}%;background:${col}"></span></span>
          <span class="val">${d.contribution >= 0 ? "+" : ""}${fmt(d.contribution, 2)}</span></div>`;
      }).join("")}</div>`;
  } else if (ex && ex.error) {
    drivers = `<div class="pop-note">${esc(ex.error)}</div>`;
  }
  return `<div class="small muted">Cell ${c.cell_id} · ${fmt(c.lat, 3)}°N ${fmt(c.lon, 3)}°E</div>
    <div class="pop-p">${fmtP(c.p)}</div>
    <div class="pop-class"><span class="swatch" style="background:${classColor(c.hazard_class)}"></span>
      ${esc(classLabel(c.hazard_class))} hazard</div>${obs}${drivers}
    <div class="pop-note">Red raises, blue lowers the score. Predictive associations, not causes.
      Hazard of a new fire start, not damage or risk.</div>`;
}

// ------------------------------------------------------------------ models & evaluation
async function loadModels() {
  try {
    const card = await api("api/model");
    state.card = card;
    $("badge-model").hidden = false;
    $("badge-model").textContent = `model: ${card.production_model}`;
    const cal = card.calibration || {};
    const tm = card.test_metrics;
    $("model-card").innerHTML = `<div class="card-head"><h2>Production model</h2>
        <span class="badge badge-model">${esc(card.production_model)}</span></div>
      <dl class="kv">
        <dt>Selected by</dt><dd>${esc(card.selection_criterion || "")}</dd>
        <dt>Dev CV weighted AP</dt><dd>${fmt(card.candidates_dev_cv_ap?.[card.production_model], 4)}</dd>
        <dt>Training weights</dt><dd>${esc(card.training_scheme || "–")}</dd>
        <dt>Features</dt><dd>${card.n_features}</dd>
        <dt>Calibration</dt><dd>Platt a=${fmt(cal.platt_a, 3)}, b=${fmt(cal.platt_b, 3)}</dd>
        <dt>Decision threshold τ</dt><dd>${fmtP(cal.tau)} (max weighted F1, calibration year)</dd>
        ${tm ? `<dt>Test AP</dt><dd>${fmt(tm.average_precision, 4)} (prevalence ${fmt(tm.prevalence, 4)})</dd>
        <dt>Test ROC-AUC</dt><dd>${fmt(tm.roc_auc, 3)}</dd>
        <dt>Test BSS</dt><dd>${fmt(tm.bss, 4)} vs seasonal reference</dd>
        <dt>Test ECE (10 bins)</dt><dd>${fmt(tm.ece_10bin, 4)}</dd>` :
        `<dt>Test metrics</dt><dd>not evaluated yet</dd>`}
      </dl>`;
    const rows = await api("api/models");
    const hasTest = rows.some((r) => r.test_average_precision != null);
    const cols = [["dev_cv_ap", "Dev AP"]]
      .concat(hasTest ? [["test_average_precision", "Test AP"], ["test_roc_auc", "AUC"],
        ["test_bss", "BSS"]] : []);
    const kindLabel = { classifier: "classifier", ensemble: "ensemble", baseline: "baseline",
      class_weight_sensitivity: "class-weight sensitivity" };
    rows.sort((a, b) => (b.dev_cv_ap ?? -1) - (a.dev_cv_ap ?? -1));
    $("models-table").innerHTML = `<thead><tr><th>Model</th>${cols.map((c) => `<th>${c[1]}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((r) => `<tr class="${r.production ? "prod" : ""}">
        <td>${esc(r.model.split("__")[0])}<div class="small muted">${esc(kindLabel[r.kind] || r.kind)}</div></td>
        ${cols.map(([k]) => `<td>${fmt(r[k], 4)}</td>`).join("")}</tr>`).join("")}</tbody>`;
  } catch (e) {
    $("model-card").innerHTML = `<span class="muted">${esc(e.message)}</span>`;
  }
  try {
    const ev = await api("api/evaluation");
    $("eval-card").innerHTML = `<div class="card-head"><h2>Reliability (test years)</h2></div>
      ${reliabilitySvg(ev.reliability)}
      <p class="small muted">Weighted observed frequency vs mean calibrated probability
        (quantile bins, log axes, 95% Wilson intervals). Dashed: perfect calibration.</p>
      <h2 style="margin-top:10px">Flagged results</h2>
      <ul class="flags">${(ev.flags.length ? ev.flags : ["none"]).slice(0, 12)
        .map((f) => `<li>${esc(f)}</li>`).join("")}</ul>`;
  } catch (e) {
    $("eval-card").innerHTML = `<div class="card-head"><h2>Test-year evaluation</h2></div>
      <span class="muted small">${esc(e.message)}</span>`;
  }
}

function reliabilitySvg(rows) {
  const W = 330, H = 220, P = 34;
  const pts = rows.filter((r) => r.mean_pred > 0);
  if (!pts.length) return "<p class='muted small'>no data</p>";
  const lo = Math.min(...pts.map((r) => r.mean_pred)) / 2;
  const hi = Math.max(...pts.map((r) => Math.max(r.mean_pred, r.obs_hi || 0))) * 1.2;
  const sx = (v) => P + ((Math.log10(Math.max(v, lo)) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * (W - P - 8);
  const sy = (v) => H - P - ((Math.log10(Math.max(v, lo)) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * (H - P - 8);
  const ticks = [];
  for (let e = Math.ceil(Math.log10(lo)); e <= Math.floor(Math.log10(hi)); e++) ticks.push(10 ** e);
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Reliability diagram">
    <line x1="${sx(lo)}" y1="${sy(lo)}" x2="${sx(hi)}" y2="${sy(hi)}" stroke="#8a8984" stroke-dasharray="4 3"/>
    ${ticks.map((t) => `<text x="${sx(t)}" y="${H - P + 14}" text-anchor="middle">${t}</text>
      <text x="${P - 4}" y="${sy(t) + 3}" text-anchor="end">${t}</text>`).join("")}
    <text x="${W / 2}" y="${H - 4}" text-anchor="middle">mean calibrated probability</text>
    ${pts.map((r) => `<line x1="${sx(r.mean_pred)}" x2="${sx(r.mean_pred)}" y1="${sy(r.obs_lo || lo)}" y2="${sy(r.obs_hi)}" stroke="#d94801" stroke-width="1.5"/>
      <circle cx="${sx(r.mean_pred)}" cy="${sy(r.obs_freq || lo)}" r="4" fill="#d94801">
      <title>pred ${fmt(r.mean_pred, 4)} · observed ${fmt(r.obs_freq, 4)} · n=${r.n}</title></circle>`).join("")}
  </svg>`;
}

// ------------------------------------------------------------------ controls
$("day-select").addEventListener("change", (e) => showDay(e.target.value));
function step(delta) {
  const i = state.days.findIndex((d) => d.date === state.date) + delta;
  if (i >= 0 && i < state.days.length) {
    $("day-select").value = state.days[i].date;
    showDay(state.days[i].date);
  }
}
$("prev-day").addEventListener("click", () => step(-1));
$("next-day").addEventListener("click", () => step(1));
$("opacity").addEventListener("input", (e) => {
  state.opacity = e.target.value / 100;
  if (state.overlay) state.overlay.setOpacity(state.opacity);
});
$("forecast-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const d = $("forecast-date").value;
  $("forecast-status").textContent = `Running forecast for ${d}…`;
  try {
    await api(`api/forecast?date=${d}`, { method: "POST" });
    $("forecast-status").textContent = `Forecast for ${d} ready.`;
    await loadDays(d);
  } catch (err) {
    $("forecast-status").textContent = `Failed: ${err.message}`;
  }
});

// ------------------------------------------------------------------ boot
(async function boot() {
  try {
    state.cfg = await api("api/config");
    addBasemap(state.cfg.basemap_url, state.cfg.basemap_attribution);
    addBoundary();
    $("title").textContent = state.cfg.title;
    $("subtitle").textContent = `run “${state.cfg.run_label}” · ${state.cfg.cell_size_m / 1000} km equal-area grid · study ${state.cfg.study.join(" – ")}`;
    $("disclaimer").textContent = state.cfg.disclaimer;
    $("badge-synthetic").hidden = !state.cfg.synthetic;
    await loadModels();
    await loadDays();
  } catch (e) {
    $("map-note").textContent = `Platform not ready: ${e.message}`;
  }
})();
