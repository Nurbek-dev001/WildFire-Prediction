import { $, pct, num, run, loadVerified, table, dotPanel, prCurve, widthOf, panelWidth } from './report.js?v=20261027-detail';

const ORDER = ['precision', 'balanced', 'coverage'];

run(async () => {
  const d = await loadVerified('../alerts/complete.json', '../alerts/', ['policy.json', 'evaluation.json', 'metrics.csv', 'cluster_intervals.csv', 'full_grid_alert_counts.csv', 'calibration_curve_plot.csv']);
  const policy = d['policy.json'], ev = d['evaluation.json'];
  const profile = (k) => policy.profiles[k];
  const test = (k) => ev.metrics[k];
  const ci = (p, m) => d['cluster_intervals.csv'].find((r) => r.profile === p && r.metric === m);
  const grid = Object.fromEntries(ORDER.map((k) => [k, d['full_grid_alert_counts.csv'].filter((r) => r.profile === k).reduce((s, r) => s + r.alert_cells, 0)]));
  const def = policy.default_profile, b = test(def);

  $('lead').textContent = `По умолчанию — «${profile(def).label}». Порог ${pct(profile(def).threshold)} выбран по максимуму взвешенного F2 на 2022 году; в F2 полнота весит больше точности. Модель, калибровка и вероятности не менялись.`;
  $('tiles').innerHTML = [
    ['Recall · баланс', pct(b.recall), `было ${pct(test('precision').recall)} в прежнем режиме`, true],
    ['Precision · баланс', pct(b.precision), `было ${pct(test('precision').precision)}`],
    ['F2 · баланс', num(b.f2, 4), `было ${num(test('precision').f2, 4)}`],
    ['Сигналов на картах', num(grid[def]), `ячеек-дней за 2023–2024; было ${num(grid.precision)}`],
  ].map(([l, v, h, a]) => `<div class="metric"><span class="label">${l}</span><span class="value${a ? ' is-accent' : ''}">${v}</span><span class="hint">${h}</span></div>`).join('');

  // Thin the 800-point curve for drawing; the profile points are exact.
  const curve = d['calibration_curve_plot.csv'].filter((_, i, a) => i % 4 === 0 || i === a.length - 1);
  $('curve').innerHTML = prCurve({
    title: 'Кривая precision–recall на 2022 году и три порога',
    width: widthOf($('curve')),
    curve,
    points: ORDER.map((k) => ({ label: `${profile(k).label} · ${pct(profile(k).threshold)}`, recall: profile(k).calibration_metrics.recall, precision: profile(k).calibration_metrics.precision, accent: k === def })),
  });
  $('curve-caption').textContent = `${num(policy.calibration_rows)} строк, ${num(policy.calibration_positive_rows)} положительных. Отрицательные примеры взвешены по вероятностям отбора; общая частота событий с учётом весов — ${pct(policy.calibration_prevalence, 3)}. Ось точности логарифмическая.`;
  $('selection-table').innerHTML = table(['Режим', 'Порог', 'Precision', 'Recall', 'F2'],
    ORDER.map((k) => { const c = profile(k).calibration_metrics; return [profile(k).label, pct(profile(k).threshold), pct(c.precision), pct(c.recall), num(c.f2, 4)]; }),
    { current: ORDER.indexOf(def), tag: 'по умолчанию' });

  $('chart').innerHTML = ['precision', 'recall'].map((metric) => dotPanel({
    title: metric === 'precision' ? 'Precision на 2023–2024' : 'Recall на 2023–2024',
    width: panelWidth($('chart')),
    max: Math.max(...ORDER.map((k) => ci(k, metric).upper)) * 1.25,
    rows: ORDER.map((k) => ({ label: profile(k).label, value: test(k)[metric], lo: ci(k, metric).lower, hi: ci(k, metric).upper, accent: k === def })),
  })).join('');
  $('test-table').innerHTML = table(['Режим', 'Порог', 'Precision', 'Recall', 'F1', 'F2', 'Доля сигналов*', 'Сигналы на полной сетке**'],
    ORDER.map((k) => { const t = test(k); return [profile(k).label, pct(t.threshold), pct(t.precision), pct(t.recall), num(t.f1, 4), num(t.f2, 4), pct(t.alert_fraction), num(grid[k])]; }),
    { current: ORDER.indexOf(def), tag: 'по умолчанию' });
  const r = ci(def, 'recall'), f2 = ci(`${def} minus precision`, 'f2');
  $('intervals-text').textContent = `Полнота режима «${profile(def).label}»: 95% интервал ${pct(r.lower)}–${pct(r.upper)}. Парный 95% интервал прироста F2 относительно прежнего режима: ${num(f2.lower, 4)}–${num(f2.upper, 4)}.`;

  $('frozen-step').textContent = `Зафиксированы три порога и режим по умолчанию: ${new Date(policy.frozen_utc).toLocaleString('ru-RU', { timeZone: 'UTC' })} UTC.`;
  const u = ev.unchanged_discrimination;
  $('unchanged').textContent = `AP ${num(u.average_precision, 5)}, ROC-AUC ${num(u.roc_auc, 4)} и Brier прежние: изменение порога не улучшает ранжирование или вероятности. Карта остаётся ретроспективной; пригодность для текущих оперативных предупреждений не подтверждена.`;
  $('policy-hash').textContent = ev.policy_sha256;
  $('model-hash').textContent = policy.model_release_sha256;
});
