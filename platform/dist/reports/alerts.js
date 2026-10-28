import { $, t, pct, num, run, loadVerified, table, dotPanel, prCurve, widthOf, panelWidth } from './report.js?v=20261029-v6';

const ORDER = ['precision', 'balanced', 'coverage'];

run(async () => {
  const d = await loadVerified('../alerts/complete.json', '../alerts/', ['policy.json', 'evaluation.json', 'metrics.csv', 'cluster_intervals.csv', 'full_grid_alert_counts.csv', 'calibration_curve_plot.csv']);
  const policy = d['policy.json'], ev = d['evaluation.json'];
  // Labels come from the frozen policy in Russian; the key picks the translated name.
  const profile = (k) => ({ ...policy.profiles[k], label: t('aj.profiles')[k] || policy.profiles[k].label });
  const test = (k) => ev.metrics[k];
  const ci = (p, m) => d['cluster_intervals.csv'].find((r) => r.profile === p && r.metric === m);
  const grid = Object.fromEntries(ORDER.map((k) => [k, d['full_grid_alert_counts.csv'].filter((r) => r.profile === k).reduce((s, r) => s + r.alert_cells, 0)]));
  const def = policy.default_profile, b = test(def);

  $('lead').textContent = t('aj.lead', { name: profile(def).label, t: pct(profile(def).threshold) });
  $('tiles').innerHTML = [
    [t('aj.recallB'), pct(b.recall), t('aj.wasMode', { v: pct(test('precision').recall) }), true],
    [t('aj.precisionB'), pct(b.precision), t('aj.was', { v: pct(test('precision').precision) })],
    [t('aj.f2B'), num(b.f2, 4), t('aj.was', { v: num(test('precision').f2, 4) })],
    [t('aj.alerts'), num(grid[def]), t('aj.alerts.h', { v: num(grid.precision) })],
  ].map(([l, v, h, a]) => `<div class="metric"><span class="label">${l}</span><span class="value${a ? ' is-accent' : ''}">${v}</span><span class="hint">${h}</span></div>`).join('');

  // Thin the 800-point curve for drawing; the profile points are exact.
  const curve = d['calibration_curve_plot.csv'].filter((_, i, a) => i % 4 === 0 || i === a.length - 1);
  $('curve').innerHTML = prCurve({
    title: t('aj.curve'),
    width: widthOf($('curve')),
    curve,
    points: ORDER.map((k) => ({ label: `${profile(k).label} · ${pct(profile(k).threshold)}`, recall: profile(k).calibration_metrics.recall, precision: profile(k).calibration_metrics.precision, accent: k === def })),
  });
  $('curve-caption').textContent = t('aj.curveCap', { rows: num(policy.calibration_rows), pos: num(policy.calibration_positive_rows), prev: pct(policy.calibration_prevalence, 3) });
  $('selection-table').innerHTML = table([t('rep.mode'), t('rep.threshold'), 'Precision', 'Recall', 'F2'],
    ORDER.map((k) => { const c = profile(k).calibration_metrics; return [profile(k).label, pct(profile(k).threshold), pct(c.precision), pct(c.recall), num(c.f2, 4)]; }),
    { current: ORDER.indexOf(def), tag: t('rep.default') });

  $('chart').innerHTML = ['precision', 'recall'].map((metric) => dotPanel({
    title: metric === 'precision' ? t('aj.pTest') : t('aj.rTest'),
    width: panelWidth($('chart')),
    max: Math.max(...ORDER.map((k) => ci(k, metric).upper)) * 1.25,
    rows: ORDER.map((k) => ({ label: profile(k).label, value: test(k)[metric], lo: ci(k, metric).lower, hi: ci(k, metric).upper, accent: k === def })),
  })).join('');
  $('test-table').innerHTML = table([t('rep.mode'), t('rep.threshold'), 'Precision', 'Recall', 'F1', 'F2', t('aj.share'), t('aj.grid')],
    ORDER.map((k) => { const t = test(k); return [profile(k).label, pct(t.threshold), pct(t.precision), pct(t.recall), num(t.f1, 4), num(t.f2, 4), pct(t.alert_fraction), num(grid[k])]; }),
    { current: ORDER.indexOf(def), tag: t('rep.default') });
  const r = ci(def, 'recall'), f2 = ci(`${def} minus precision`, 'f2');
  $('intervals-text').textContent = t('aj.intervals', { name: profile(def).label, lo: pct(r.lower), hi: pct(r.upper), flo: num(f2.lower, 4), fhi: num(f2.upper, 4) });

  $('frozen-step').textContent = t('aj.frozen', { when: new Date(policy.frozen_utc).toISOString().slice(0, 16).replace('T', ' ') });
  const u = ev.unchanged_discrimination;
  $('unchanged').textContent = t('aj.unchanged', { ap: num(u.average_precision, 5), auc: num(u.roc_auc, 4) });
  $('policy-hash').textContent = ev.policy_sha256;
  $('model-hash').textContent = policy.model_release_sha256;
});
