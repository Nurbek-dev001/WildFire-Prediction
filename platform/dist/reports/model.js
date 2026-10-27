import { $, pct, num, run, loadVerified, table, dotPanel, panelWidth } from './report.js?v=20261027-detail';

const LABEL = { xgboost_original: 'Исходный XGBoost', xgboost_spatiotemporal: 'XGBoost + второй уровень' };

run(async () => {
  const d = await loadVerified('../upgrade/complete.json', '../upgrade/', ['metrics.csv', 'cluster_intervals.csv', 'joint_comparison.csv', 'comparison.csv', 'frozen.json', 'selection.json', 'evaluation.json']);
  const metrics = d['metrics.csv'], frozen = d['frozen.json'], sel = d['selection.json'];
  const row = (model, period = '2023–2024') => metrics.find((m) => m.model === model && m.period === period);
  const old = row('xgboost_original'), cur = row('xgboost_spatiotemporal');
  const ci = (model, metric) => d['cluster_intervals.csv'].find((r) => r.model === model && r.metric === metric);

  $('lead').textContent = `Recall вырос с ${pct(old.recall)} до ${pct(cur.recall)}, precision снизилась с ${pct(old.precision)} до ${pct(cur.precision)}. Обучение и выбор — только на данных до 2023 года.`;
  $('tiles').innerHTML = [
    ['Recall', pct(cur.recall), 'доля найденных новых очагов', true],
    ['Precision', pct(cur.precision), 'доля верных предупреждений'],
    ['AP', num(cur.average_precision, 4), `качество ранжирования; доля положительных ${pct(cur.prevalence, 3)}`],
    ['ROC-AUC', num(cur.roc_auc, 4), 'различение очагов и фона'],
    ['Порог тревоги', pct(frozen.threshold, 4), 'выбран на 2022 году'],
  ].map(([l, v, h, a]) => `<div class="metric"><span class="label">${l}</span><span class="value${a ? ' is-accent' : ''}">${v}</span><span class="hint">${h}</span></div>`).join('');

  const max = Math.max(...d['cluster_intervals.csv'].map((r) => r.upper)) * 1.05;
  $('chart').innerHTML = ['precision', 'recall'].map((metric) => dotPanel({
    title: metric === 'precision' ? 'Precision: снизилась' : 'Recall: выросла',
    width: panelWidth($('chart')),
    max,
    rows: [['original', old, 'Исходный XGBoost'], ['new', cur, 'XGBoost + второй уровень']].map(([key, r, label]) => ({ label, value: r[metric], lo: ci(key, metric).lower, hi: ci(key, metric).upper, accent: key === 'new' })),
  })).join('');

  $('metrics-table').innerHTML = table(['Модель', 'Порог', 'Precision', 'Recall', 'F1', 'AP', 'ROC-AUC'],
    [old, cur].map((r) => [LABEL[r.model], pct(r.threshold, 2), pct(r.precision), pct(r.recall), num(r.f1, 4), num(r.average_precision, 4), num(r.roc_auc, 4)]), { current: 1 });
  $('years-table').innerHTML = table(['Модель и год', 'Precision', 'Recall', 'AP', 'Верных сигналов', 'Ложных (взвеш.)', 'Пропущено'],
    metrics.filter((r) => r.period !== '2023–2024').map((r) => [`${LABEL[r.model]} · ${r.period}`, pct(r.precision), pct(r.recall), num(r.average_precision, 4), num(r.tp), num(r.fp), num(r.fn)]));
  $('floor').textContent = pct(frozen.precision_floor);
  $('test-precision').textContent = pct(cur.precision);

  const joint = d['joint_comparison.csv'];
  $('joint-table').innerHTML = table(['Вес XGBoost', 'Мин. относительный прирост recall', 'Recall 2021', 'AP 2021', 'Recall 2022', 'AP 2022'],
    joint.map((r) => [num(r.weight, 2), num(r.minimum_relative_recall, 3), pct(r.recall_2021), num(r.ap_2021, 4), pct(r.recall_2022), num(r.ap_2022, 4)]),
    { current: joint.findIndex((r) => r.weight === sel.joint_criterion.weight), tag: 'выбран' });
  const cand = d['comparison.csv'];
  $('candidates-table').innerHTML = table(['Кандидат', 'Вес XGBoost', 'Порог', 'Precision', 'Recall', 'F1', 'AP'],
    cand.map((r) => [r.name.replace('logistic_C', 'Логистический, C = ').replace('.', ','), num(r.weight, 2), pct(r.threshold), pct(r.precision), pct(r.recall), num(r.f1, 4), num(r.average_precision, 4)]),
    { current: cand.findIndex((r) => r.name === sel.selected.name.replace(/_blend.*/, '') && r.weight === sel.selected.weight), tag: 'выбран' });

  $('cal-precision').textContent = pct(frozen.calibration_metrics.precision);
  $('cal-recall').textContent = pct(frozen.calibration_metrics.recall);
  $('cal-threshold').textContent = pct(frozen.threshold, 4);
  $('release-hash').textContent = d['evaluation.json'].release_sha256;
});
