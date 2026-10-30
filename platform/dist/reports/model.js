import { $, t, pct, num, run, loadRefs, table, dotPanel, panelWidth, reliability } from './report.js?v=20261030-3d';

const CANDIDATES = ['reference', 'R0_base', 'R1_history', 'R2_cell', 'R3_cell_weather', 'R4_weather'];

run(async () => {
  const m = await (await fetch('../assets/forecast-manifest-v6.json', { cache: 'no-store' })).json();
  const d = await loadRefs(m.records, ['release', 'frozen', 'evaluation_2026', 'reliability_2026', 'development_comparison', 'development_selection', 'sensitivity_2026']);
  const ev = d.evaluation_2026, rel = d.reliability_2026, sel = d.development_selection;
  if (m.records.release.sha256 !== m.release_sha256 || d.release.artifacts['frozen.json'] !== m.records.frozen.sha256 || d.frozen.threshold !== m.threshold) throw Error(t('v6j.mismatch'));
  const a = ev.metrics.v6, b = ev.metrics.v5, ci = ev.confidence_intervals_95, diff = ev.paired_difference_v6_minus_v5_95;
  for (const k of ['precision', 'recall', 'average_precision', 'bss', 'top_1pct']) if (a[k] !== m.test_metrics.xgboost_v6[k] || b[k] !== m.test_metrics.xgboost_spatiotemporal[k]) throw Error(t('v6j.mismatch'));

  const vs = (v) => t('v6j.vs', { v });
  $('tiles').innerHTML = [
    ['Recall', pct(a.recall), vs(pct(b.recall)), true],
    ['Precision', pct(a.precision), vs(pct(b.precision))],
    ['AP', num(a.average_precision, 4), vs(num(b.average_precision, 4))],
    [t('v6j.top1'), pct(a.top_1pct, 1), vs(pct(b.top_1pct, 1))],
    ['Brier skill', num(a.bss, 3), t('v6j.bss', { v: num(b.bss, 3) })],
  ].map(([l, v, h, acc]) => `<div class="metric"><span class="label">${l}</span><span class="value${acc ? ' is-accent' : ''}">${v}</span><span class="hint">${h}</span></div>`).join('');

  const width = panelWidth($('chart'));
  const dots = (metric) => [
    { label: 'v6', value: a[metric], lo: ci.v6[metric][0], hi: ci.v6[metric][1], accent: true },
    { label: 'v5', value: b[metric], lo: ci.v5[metric][0], hi: ci.v5[metric][1] },
  ];
  $('chart').innerHTML = dotPanel({ title: t('v6j.chart.recall'), rows: dots('recall'), max: Math.max(ci.v6.recall[1], ci.v5.recall[1]), width })
    + dotPanel({ title: t('v6j.chart.precision'), rows: dots('precision'), max: Math.max(ci.v6.precision[1], ci.v5.precision[1]), width });
  const row = (label, s) => [label, pct(s.precision), pct(s.recall), num(s.f1, 4), num(s.average_precision, 4), num(s.roc_auc, 3), pct(s['top_0.1pct'], 1), pct(s.top_1pct, 1), num(s.bss, 3)];
  $('metrics-table').innerHTML = table([t('rep.model'), 'Precision', 'Recall', 'F1', 'AP', 'ROC-AUC', t('v6j.top01'), t('v6j.top1'), 'BSS'], [row('v6', a), row('v5', b)], { current: 0 });
  $('test-text').textContent = t('v6j.test', {
    rows: num(ev.rows), pos: num(ev.positive_cell_days), excl: num(m.test_2026.excluded_days.length),
    r0: pct(diff.recall[0], 1), r1: pct(diff.recall[1], 1), p0: pct(diff.precision[0], 1), p1: pct(diff.precision[1], 1), x: num(a.recall / b.recall, 1),
  });

  // Post-hoc: the same sample without persistent heat sources (plants, gas flares).
  const sens = d.sensitivity_2026, all = sens.all_cells, clean = sens.without_heat_sources;
  if (['precision', 'recall'].some((k) => Math.abs(all.v6[k] - a[k]) > 1e-12 || Math.abs(all.v5[k] - b[k]) > 1e-12)) throw Error(t('v6j.mismatch'));
  const srow = (label, s) => [label, pct(s.precision), pct(s.recall), num(s.f1, 4), num(s.average_precision, 4), num(s.true_positives)];
  $('sensitivity-table').innerHTML = table([t('rep.model'), 'Precision', 'Recall', 'F1', 'AP', t('v6j.hits')],
    [srow(t('v6j.s.all', { m: 'v6' }), all.v6), srow(t('v6j.s.clean', { m: 'v6' }), clean.v6), srow(t('v6j.s.all', { m: 'v5' }), all.v5), srow(t('v6j.s.clean', { m: 'v5' }), clean.v5)], { current: 1, tag: '' });
  $('sensitivity-text').textContent = t('v6j.sens', {
    n: num(sens.cells.length), pos: num(sens.positives_in_cells), share: pct(sens.positives_in_cells / sens.positives, 0),
    h6: pct(1 - clean.v6.true_positives / all.v6.true_positives, 0), h5: pct(1 - clean.v5.true_positives / all.v5.true_positives, 0),
    x: num(clean.v6.recall / clean.v5.recall, 1),
  });

  // Reliability from the registered 2026 sample: shown value against the observed rate of first detections.
  const bins = (model) => rel.bins[model].filter((x) => x.rows && x.observed > 0).map((x) => ({ predicted: x.predicted, observed: x.observed, weight: x.share, ci_lower: 0, ci_upper: 0 }));
  const rw = panelWidth($('reliability'));
  $('reliability').innerHTML = reliability({ bins: bins('v6'), title: t('v6j.rel.v6'), width: rw }) + reliability({ bins: bins('v5'), title: t('v6j.rel.v5'), width: rw });
  const ratio = (x) => x.observed / x.predicted;
  const mid = (model) => rel.bins[model].filter((x) => x.low >= 0.003 && x.high <= 0.03 && x.rows);
  const top = (model) => rel.bins[model].find((x) => x.low >= 0.03 && x.rows);
  const spread = (x) => Math.max(ratio(x), 1 / ratio(x));
  const v5max = Math.max(...[...mid('v5'), top('v5')].map(spread));
  $('reliability-text').textContent = t('v6j.rel.text', {
    lo: num(Math.min(...mid('v6').map(ratio)), 1), hi: num(Math.max(...mid('v6').map(ratio)), 1), top: num(1 / ratio(top('v6')), 1),
    v5: num(v5max, 1), b6: num(a.bss, 3), b5: num(b.bss, 3),
  });
  $('reliability-table').innerHTML = table([t('v6.rel.bin'), t('v6.rel.share'), t('v6.rel.pred'), t('v6.rel.obs'), t('v6j.ratio'), t('v6.rel.pos')],
    rel.bins.v6.filter((x) => x.rows).map((x) => [`${pct(x.low, 2)}–${pct(x.high, 2)}`, pct(x.share, 2), pct(x.predicted, 4), pct(x.observed, 4), '×' + num(ratio(x), 2), num(x.positives)]));

  // Development: AP and top-1% capture by year, the reference first.
  const dev = d.development_comparison;
  const cell = (model, year, key) => dev.find((r) => r.year === year && (model === 'reference' ? ['original_xgboost_oof', 'release_v5'].includes(r.model) : r.model === model))?.[key];
  const years = [2020, 2021, 2022];
  $('candidates-table').innerHTML = table(
    [t('v6j.cand'), ...years.map((y) => `AP ${y}`), ...years.map((y) => `${t('v6j.top1')} ${y}`)],
    CANDIDATES.map((c) => [t('v6j.c.' + c) + (sel.qualified.includes(c) && c !== sel.selected ? ` · ${t('v6j.qualified')}` : ''), ...years.map((y) => num(cell(c, y, 'ap'), 4)), ...years.map((y) => pct(cell(c, y, 'top_1pct'), 1))]),
    { current: CANDIDATES.indexOf(sel.selected), tag: t('rep.chosen') },
  );
  $('release-hash').textContent = m.release_sha256;
});
