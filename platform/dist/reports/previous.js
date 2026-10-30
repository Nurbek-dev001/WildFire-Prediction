import { $, t, pct, num, run, loadVerified, table, barChart, reliability, widthOf } from './report.js?v=20261030-live';

const MODELS = Object.fromEntries(['logistic', 'random_forest', 'xgboost', 'catboost', 'weather_logistic', 'seasonal'].map((k, i) => [k, t('pj.models')[i]]));
const FEATURE_KEYS = ['population_density', 'month_cos', 'month_sin', 'temperature_14d', 'temperature_7d', 'cropland', 'elevation', 'other', 'ndvi', 'slope',
  'soil_moisture', 'tmax', 'tmin', 'aspect_cos', 'aspect_sin', 'settlement_distance', 'precip_14d', 'precip_7d', 'precip', 'rh', 'grassland', 'wind', 'ndvi_missing',
  'ndvi_age_days', 'forest', 'shrubland'];
const FEATURES = Object.fromEntries(FEATURE_KEYS.map((k, i) => [k, t('pj.features')[i]]));

run(async () => {
  const r = await loadVerified('../results/complete.json', '../results/', ['calibration_bins.csv', 'explain/global.csv', 'development_data_quality.csv', 'training_cpu.json']);
  // The evaluation record hashes the shared evaluate/ folder, as verify-model-assets does.
  const e = await loadVerified('../assets/model-evaluation.json', '../evaluate/', ['metrics.csv', 'cluster_intervals.csv']);
  const evaluation = await (await fetch('../assets/model-evaluation.json')).json();
  const test = e['metrics.csv'].filter((m) => m.period === '2023–2024');
  const chosen = test.find((m) => m.model === evaluation.selected_model);
  const ci = (model) => e['cluster_intervals.csv'].find((c) => c.model === model && c.metric === 'average_precision');

  $('tiles').innerHTML = [
    ['AP · XGBoost', num(chosen.average_precision, 4), t('pj.best'), true],
    ['ROC-AUC', num(chosen.roc_auc, 4), t('mj.auc')],
    ['Precision', pct(chosen.precision), t('pj.at', { t: pct(chosen.threshold) })],
    ['Recall', pct(chosen.recall), t('mj.recall')],
  ].map(([l, v, h, a]) => `<div class="metric"><span class="label">${l}</span><span class="value${a ? ' is-accent' : ''}">${v}</span><span class="hint">${h}</span></div>`).join('');

  const sorted = [...test].sort((a, b) => b.average_precision - a.average_precision);
  $('ap-chart').innerHTML = barChart({ width: widthOf($('ap-chart')), title: t('pj.apTitle'), max: Math.max(...sorted.map((m) => ci(m.model)?.upper ?? m.average_precision)) * 1.1, format: (v) => num(v, 3),
    rows: sorted.map((m) => ({ label: MODELS[m.model], value: m.average_precision, lo: ci(m.model)?.lower, hi: ci(m.model)?.upper, accent: m.model === chosen.model })) });
  $('models-table').innerHTML = table([t('rep.model'), 'AP', 'ROC-AUC', 'Brier', 'Precision', 'Recall', 'F1'],
    sorted.map((m) => [MODELS[m.model], num(m.average_precision, 4), num(m.roc_auc, 4), num(m.brier, 6), pct(m.precision), pct(m.recall), num(m.f1, 4)]),
    { current: sorted.indexOf(chosen), tag: t('pj.beforeTest') });

  $('reliability').innerHTML = reliability({ width: widthOf($('reliability')), title: t('pj.calTitle'), bins: r['calibration_bins.csv'] });

  const top = [...r['explain/global.csv']].sort((a, b) => b.weighted_mean_abs_contribution - a.weighted_mean_abs_contribution).slice(0, 15);
  $('importance').innerHTML = barChart({ width: widthOf($('importance')), title: t('pj.impTitle'), max: top[0].weighted_mean_abs_contribution * 1.1, format: (v) => num(v, 2),
    rows: top.map((f, i) => ({ label: FEATURES[f.feature] || f.feature, value: f.weighted_mean_abs_contribution, accent: i === 0 })) });

  const cpu = r['training_cpu.json'];
  $('cpu').textContent = t('pj.cpu', { h: num(cpu.total_cpu_seconds / 3600, 2) });
  $('data-table').innerHTML = table([t('pj.sample'), t('pj.rows'), t('pj.pos'), t('pj.ndviGap'), t('pj.popGap')],
    r['development_data_quality.csv'].map((row) => { const [year, kind] = row.table.replace('.parquet', '').split('_'); return [`${year} · ${kind === 'train' ? t('pj.train') : t('pj.valid')}`, num(row.rows), num(row.positives), pct(row.ndvi_missing_fraction, 1), pct(row.population_missing_fraction, 1)]; }));
  $('sample').textContent = t('pj.final', { rows: num(evaluation.rows), pos: num(evaluation.positive_rows), w: num(evaluation.weighted_cell_days) });
  $('release-hash').textContent = evaluation.release_sha256;
});
