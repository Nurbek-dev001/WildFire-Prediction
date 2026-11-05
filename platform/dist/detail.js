// Zoomable satellite view of one place: Esri or Sentinel-2 tiles under the 5 km forecast grid,
// the day's alert cells and observed events, and every observed 2023–2024 event nearby.
// Only this view needs the network; Leaflet and proj4 are vendored and load on first use.

import { t, regionName, coords } from './i18n.js?v=20261105-m2';

const LAEA = '+proj=laea +lat_0=48 +lon_0=67 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs';
const SOURCES = {
  esri: {
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    maxNativeZoom: 18,
    attribution: () => t('credit.esri').replace(': ', ': © '),
  },
  s2: {
    url: 'https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg',
    maxNativeZoom: 15,
    attribution: () => '<a href="https://s2maps.eu" target="_blank" rel="noopener">Sentinel-2 cloudless 2016</a> · EOX IT Services · Copernicus Sentinel data 2016 · CC BY 4.0',
  },
};
const GRID_MIN_ZOOM = 9;

const loadScript = (src) => new Promise((resolve, reject) => {
  const s = document.createElement('script');
  s.src = src; s.onload = resolve; s.onerror = () => reject(Error('Не удалось загрузить ' + src));
  document.head.append(s);
});
const loadCss = (href) => new Promise((resolve) => {
  const l = document.createElement('link');
  l.rel = 'stylesheet'; l.href = href; l.onload = resolve; l.onerror = resolve;
  document.head.append(l);
});
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

// host: positioned element to fill. cells: decoded cells.bin. onSelect(index): show the cell card.
export async function createDetail({ host, geo, cells, onSelect }) {
  await Promise.all([loadCss('./vendor/leaflet.min.css'), loadScript('./vendor/leaflet.min.js'), loadScript('./vendor/proj4.js')]);
  const L = window.L, project = window.proj4(LAEA, 'EPSG:4326');
  // Map km (x east, y north) -> Leaflet [lat, lon].
  const ll = (x, y) => { const [lon, lat] = project.forward([x * 1000, y * 1000]); return [lat, lon]; };
  const km = (lat, lon) => { const [x, y] = project.inverse([lon, lat]); return [x / 1000, y / 1000]; };
  const byKey = new Map(cells.map((c, i) => [c.row * 1000 + c.col, i]));
  const square = (c) => [ll(c.col * 5, c.row * 5), ll((c.col + 1) * 5, c.row * 5), ll((c.col + 1) * 5, (c.row + 1) * 5), ll(c.col * 5, (c.row + 1) * 5)];
  const centre = (c) => ll((c.col + 0.5) * 5, (c.row + 0.5) * 5);

  const el = document.createElement('div');
  el.className = 'detail-map';
  el.hidden = true;
  host.append(el);
  const map = L.map(el, { zoomControl: false, preferCanvas: true, minZoom: 5, maxZoom: 18, worldCopyJump: false });
  map.attributionControl.setPrefix(false);
  const zoom = L.control.zoom({ position: 'topright', zoomInTitle: t('detail.zoomIn'), zoomOutTitle: t('detail.zoomOut') }).addTo(map);
  L.control.scale({ imperial: false, position: 'bottomright' }).addTo(map);
  let base = null, source = 'esri';
  const setSource = (key) => {
    if (base) map.removeLayer(base);
    source = key;
    base = L.tileLayer(SOURCES[key].url, { maxNativeZoom: SOURCES[key].maxNativeZoom, maxZoom: 18, attribution: SOURCES[key].attribution(), crossOrigin: true }).addTo(map);
    base.bringToBack();
  };
  setSource('esri');

  const renderer = L.canvas({ padding: 0.4 });
  const grid = L.layerGroup().addTo(map), past = L.layerGroup().addTo(map), today = L.layerGroup().addTo(map), focus = L.layerGroup().addTo(map);
  let data = null, focused = -1;

  function popup(i) {
    const c = cells[i], d = data;
    const v = d.values[i], years = d.history ? Array.from({ length: 8 }, (_, y) => d.history[i * 8 + y]) : [];
    const seen = d.allEvents.filter((e) => e.cell === i);
    const above = Number.isFinite(v) && d.alertAt !== null && v >= d.alertAt;
    return `<div class="detail-popup"><b>${esc(regionName(geo.regions[c.region], 'long'))}</b>
      <span>${coords(c.lat, c.lon, 3)} · ${t('detail.popup.cell')}</span>
      ${d.layer === 'forecast' ? `<span>${t('detail.popup.fc', { day: esc(d.dayLabel), v: Number.isFinite(v) ? esc(d.format(v)) : t('detail.popup.nodata'), above })}</span>` : ''}
      ${years.length ? `<span>${t('detail.popup.hist')}: ${years.map((n, y) => `${2015 + y}: ${n}`).join(', ')}</span>` : ''}
      <span>${t('detail.popup.events')}: ${seen.length ? seen.map((e) => esc(e.date)).join(', ') : t('detail.popup.none')}</span>
      <button type="button" data-select="${i}">${t('detail.popup.open')}</button></div>`;
  }

  function drawGrid() {
    grid.clearLayers();
    if (!data || map.getZoom() < GRID_MIN_ZOOM) return;
    const b = map.getBounds();
    const pts = [b.getSouthWest(), b.getNorthEast(), b.getNorthWest(), b.getSouthEast()].map((p) => km(p.lat, p.lng));
    const r0 = Math.floor(Math.min(...pts.map((p) => p[1])) / 5), r1 = Math.ceil(Math.max(...pts.map((p) => p[1])) / 5);
    const c0 = Math.floor(Math.min(...pts.map((p) => p[0])) / 5), c1 = Math.ceil(Math.max(...pts.map((p) => p[0])) / 5);
    if ((r1 - r0) * (c1 - c0) > 6000) return;
    for (let r = r0; r <= r1; r++) for (let c = c0; c <= c1; c++) {
      const i = byKey.get(r * 1000 + c);
      if (i === undefined) continue;
      const v = data.values[i];
      const k = Number.isFinite(v) && !(data.layer === 'history' && v === 0) ? data.classOf(v) : -1;
      // Low classes stay as thin outlines so the ground stays visible.
      const fill = k >= 2 ? data.colors[k] : null;
      L.polygon(square(cells[i]), { renderer, color: k >= 2 ? data.colors[k] : 'rgba(255,254,250,.45)', weight: k >= 2 ? 1.2 : 0.6, fillColor: fill || '#000', fillOpacity: fill ? 0.06 + 0.04 * k : 0, interactive: true })
        .bindPopup(() => popup(i), { maxWidth: 300 }).addTo(grid);
    }
  }

  function drawPoints() {
    past.clearLayers(); today.clearLayers();
    if (!data) return;
    const b = map.getBounds().pad(0.2);
    if (data.showPast) for (const e of data.allEvents) {
      const p = ll(e.x, -e.y);
      if (!b.contains(p)) continue;
      L.circleMarker(p, { renderer, radius: 4, color: '#193d35', weight: 1.4, fillColor: e.year === 2023 ? '#f2f5ef' : e.year === 2024 ? '#c9e3ff' : '#ffd7a8', fillOpacity: 1 })
        .bindTooltip(t('detail.tip.past', { date: esc(e.date), hit: e.hit })).addTo(past);
    }
    if (data.alertAt !== null && data.showPredicted) for (const i of data.alerts) {
      const c = cells[i];
      L.polygon(square(c), { renderer, color: '#fffefa', weight: 4, fill: false, interactive: false }).addTo(today);
      L.polygon(square(c), { renderer, color: data.colors[6], weight: 2.5, fillOpacity: 0 }).bindPopup(() => popup(i), { maxWidth: 300 }).addTo(today);
    }
    if (data.showObserved) for (const e of data.dayEvents) {
      L.marker(ll(e.x, -e.y), { icon: L.divIcon({ className: '', html: `<i class="detail-diamond${e.hit ? ' is-hit' : ''}"></i>`, iconSize: [16, 16], iconAnchor: [8, 8] }) })
        .bindTooltip(t('detail.tip.day', { hit: e.hit })).addTo(today);
    }
  }

  function drawFocus() {
    focus.clearLayers();
    if (focused < 0) return;
    L.polygon(square(cells[focused]), { renderer, color: '#fffefa', weight: 5, fill: false, interactive: false }).addTo(focus);
    L.polygon(square(cells[focused]), { renderer, color: '#193d35', weight: 2.5, dashArray: '6 5', fill: false, interactive: false }).addTo(focus);
  }

  // The focus outline is drawn last so it stays on top of the grid and alerts.
  map.on('moveend', () => { drawGrid(); drawPoints(); drawFocus(); });
  map.on('popupopen', (e) => {
    e.popup.getElement()?.querySelector('[data-select]')?.addEventListener('click', (ev) => { onSelect(+ev.target.dataset.select); map.closePopup(); });
  });

  return {
    open(i) {
      el.hidden = false;
      map.invalidateSize();
      focused = i;
      map.setView(centre(cells[i]), 12, { animate: false });
      drawGrid(); drawPoints(); drawFocus();
    },
    close() { el.hidden = true; map.closePopup(); },
    // values, classOf, colors, alertAt, alerts, dayEvents, allEvents, history, layer, format, dayLabel, show* flags
    refresh(next) { data = next; if (!el.hidden) { drawGrid(); drawPoints(); drawFocus(); } },
    setSource,
    // Popups and tooltips are built in the current language; the controls need redoing.
    relabel() {
      const c = zoom.getContainer();
      c.querySelector('.leaflet-control-zoom-in').title = t('detail.zoomIn');
      c.querySelector('.leaflet-control-zoom-out').title = t('detail.zoomOut');
      setSource(source); map.closePopup();
    },
    get source() { return source; },
    focus(i) { focused = i; drawFocus(); },
    resize() { map.invalidateSize(); },
  };
}
