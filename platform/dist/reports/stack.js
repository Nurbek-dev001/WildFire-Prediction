import { $, t, pct, num, run, loadVerified, table, dotPanel, panelWidth } from './report.js?v=20261105-da';

const LABEL = { xgboost_original: t('m.original'), xgboost_spatiotemporal: t('m.stack') };

run(async () => {
  const d = await loadVerified('../upgrade/complete.json', '../upgrade/', ['metrics.csv', 'cluster_intervals.csv', 'joint_comparison.csv', 'comparison.csv', 'frozen.json', 'selection.json', 'evaluation.json']);
  const metrics = d['metrics.csv'], frozen = d['frozen.json'], sel = d['selection.json'];
  const row = (model, period = '2023–2024') => metrics.find((m) => m.model === model && m.period === period);
  const old = row('xgboost_original'), cur = row('xgboost_spatiotemporal');
  const ci = (model, metric) => d['cluster_intervals.csv'].find((r) => r.model === model && r.metric === metric);

  $('lead').textContent = t('mj.lead', { r0: pct(old.recall), r1: pct(cur.recall), p0: pct(old.precision), p1: pct(cur.precision) });
  $('tiles').innerHTML = [
    ['Recall', pct(cur.recall), t('mj.recall'), true],
    ['Precision', pct(cur.precision), t('mj.precision')],
    ['AP', num(cur.average_precision, 4), t('mj.ap', { p: pct(cur.prevalence, 3) })],
    ['ROC-AUC', num(cur.roc_auc, 4), t('mj.auc')],
    [t('mj.threshold'), pct(frozen.threshold, 4), t('mj.threshold.h')],
  ].map(([l, v, h, a]) => `<div class="metric"><span class="label">${l}</span><span class="value${a ? ' is-accent' : ''}">${v}</span><span class="hint">${h}</span></div>`).join('');

  const max = Math.max(...d['cluster_intervals.csv'].map((r) => r.upper)) * 1.05;
  $('chart').innerHTML = ['precision', 'recall'].map((metric) => dotPanel({
    title: metric === 'precision' ? t('mj.pDown') : t('mj.rUp'),
    width: panelWidth($('chart')),
    max,
    rows: [['original', old, t('m.original')], ['new', cur, t('m.stack')]].map(([key, r, label]) => ({ label, value: r[metric], lo: ci(key, metric).lower, hi: ci(key, metric).upper, accent: key === 'new' })),
  })).join('');

  $('metrics-table').innerHTML = table([t('rep.model'), t('rep.threshold'), 'Precision', 'Recall', 'F1', 'AP', 'ROC-AUC'],
    [old, cur].map((r) => [LABEL[r.model], pct(r.threshold, 2), pct(r.precision), pct(r.recall), num(r.f1, 4), num(r.average_precision, 4), num(r.roc_auc, 4)]), { current: 1 });
  $('years-table').innerHTML = table([t('mj.modelYear'), 'Precision', 'Recall', 'AP', t('mj.tp'), t('mj.fp'), t('mj.fn')],
    metrics.filter((r) => r.period !== '2023–2024').map((r) => [`${LABEL[r.model]} · ${r.period}`, pct(r.precision), pct(r.recall), num(r.average_precision, 4), num(r.tp), num(r.fp), num(r.fn)]));
  $('floor').textContent = pct(frozen.precision_floor);
  $('test-precision').textContent = pct(cur.precision);

  const joint = d['joint_comparison.csv'];
  $('joint-table').innerHTML = table([t('mj.weight'), t('mj.minGain'), 'Recall 2021', 'AP 2021', 'Recall 2022', 'AP 2022'],
    joint.map((r) => [num(r.weight, 2), num(r.minimum_relative_recall, 3), pct(r.recall_2021), num(r.ap_2021, 4), pct(r.recall_2022), num(r.ap_2022, 4)]),
    { current: joint.findIndex((r) => r.weight === sel.joint_criterion.weight), tag: t('rep.chosen') });
  const cand = d['comparison.csv'];
  $('candidates-table').innerHTML = table([t('mj.candidate'), t('mj.weight'), t('rep.threshold'), 'Precision', 'Recall', 'F1', 'AP'],
    cand.map((r) => [r.name.replace('logistic_C', t('mj.logistic')).replace('.', num(1.5, 1)[1]), num(r.weight, 2), pct(r.threshold), pct(r.precision), pct(r.recall), num(r.f1, 4), num(r.average_precision, 4)]),
    { current: cand.findIndex((r) => r.name === sel.selected.name.replace(/_blend.*/, '') && r.weight === sel.selected.weight), tag: t('rep.chosen') });

  $('cal-precision').textContent = pct(frozen.calibration_metrics.precision);
  $('cal-recall').textContent = pct(frozen.calibration_metrics.recall);
  $('cal-threshold').textContent = pct(frozen.threshold, 4);
  $('release-hash').textContent = d['evaluation.json'].release_sha256;
});
