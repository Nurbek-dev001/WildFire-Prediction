import { $, pct, num, run, loadVerified, table, barChart, reliability, widthOf } from './report.js';

const MODELS = { logistic: 'Логистическая регрессия', random_forest: 'Случайный лес', xgboost: 'XGBoost', catboost: 'CatBoost', weather_logistic: 'Логистическая, только погода', seasonal: 'Сезонная база' };
const FEATURES = {
  population_density: 'Плотность населения', month_cos: 'Сезон, косинус месяца', month_sin: 'Сезон, синус месяца', temperature_14d: 'Температура за 14 дней',
  temperature_7d: 'Температура за 7 дней', cropland: 'Пашня', elevation: 'Высота', other: 'Прочий покров', ndvi: 'NDVI', slope: 'Уклон',
  soil_moisture: 'Влажность почвы', tmax: 'Максимальная температура', tmin: 'Минимальная температура', aspect_cos: 'Экспозиция склона, cos',
  aspect_sin: 'Экспозиция склона, sin', settlement_distance: 'Расстояние до поселений', precip_14d: 'Осадки за 14 дней', precip_7d: 'Осадки за 7 дней',
  precip: 'Осадки за сутки', rh: 'Относительная влажность', grassland: 'Луга', wind: 'Ветер', ndvi_missing: 'Нет наблюдения NDVI',
  ndvi_age_days: 'Давность NDVI, дней', forest: 'Лес', shrubland: 'Кустарник',
};

run(async () => {
  const r = await loadVerified('../results/complete.json', '../results/', ['calibration_bins.csv', 'explain/global.csv', 'development_data_quality.csv', 'training_cpu.json']);
  // The evaluation record hashes the shared evaluate/ folder, as verify-model-assets does.
  const e = await loadVerified('../assets/model-evaluation.json', '../evaluate/', ['metrics.csv', 'cluster_intervals.csv']);
  const evaluation = await (await fetch('../assets/model-evaluation.json')).json();
  const test = e['metrics.csv'].filter((m) => m.period === '2023–2024');
  const chosen = test.find((m) => m.model === evaluation.selected_model);
  const ci = (model) => e['cluster_intervals.csv'].find((c) => c.model === model && c.metric === 'average_precision');

  $('tiles').innerHTML = [
    ['AP · XGBoost', num(chosen.average_precision, 4), 'лучшая из шести моделей', true],
    ['ROC-AUC', num(chosen.roc_auc, 4), 'различение очагов и фона'],
    ['Precision', pct(chosen.precision), `при пороге ${pct(chosen.threshold)}`],
    ['Recall', pct(chosen.recall), 'доля найденных новых очагов'],
  ].map(([l, v, h, a]) => `<div class="metric"><span class="label">${l}</span><span class="value${a ? ' is-accent' : ''}">${v}</span><span class="hint">${h}</span></div>`).join('');

  const sorted = [...test].sort((a, b) => b.average_precision - a.average_precision);
  $('ap-chart').innerHTML = barChart({ width: widthOf($('ap-chart')), title: 'Average precision на 2023–2024', max: Math.max(...sorted.map((m) => ci(m.model)?.upper ?? m.average_precision)) * 1.1, format: (v) => num(v, 3),
    rows: sorted.map((m) => ({ label: MODELS[m.model], value: m.average_precision, lo: ci(m.model)?.lower, hi: ci(m.model)?.upper, accent: m.model === chosen.model })) });
  $('models-table').innerHTML = table(['Модель', 'AP', 'ROC-AUC', 'Brier', 'Precision', 'Recall', 'F1'],
    sorted.map((m) => [MODELS[m.model], num(m.average_precision, 4), num(m.roc_auc, 4), num(m.brier, 6), pct(m.precision), pct(m.recall), num(m.f1, 4)]),
    { current: sorted.indexOf(chosen), tag: 'выбрана до теста' });

  $('reliability').innerHTML = reliability({ width: widthOf($('reliability')), title: 'Калибровка XGBoost', bins: r['calibration_bins.csv'] });

  const top = [...r['explain/global.csv']].sort((a, b) => b.weighted_mean_abs_contribution - a.weighted_mean_abs_contribution).slice(0, 15);
  $('importance').innerHTML = barChart({ width: widthOf($('importance')), title: 'Средний |вклад| признака, лог-шансы · 15 сильнейших', max: top[0].weighted_mean_abs_contribution * 1.1, format: (v) => num(v, 2),
    rows: top.map((f, i) => ({ label: FEATURES[f.feature] || f.feature, value: f.weighted_mean_abs_contribution, accent: i === 0 })) });

  const cpu = r['training_cpu.json'];
  $('cpu').textContent = `Процессорное время процесса, суммарно по всем потокам: ${num(cpu.total_cpu_seconds / 3600, 2)} CPU·ч. Это отдельное измерение Windows GetProcessTimes за всё время жизни процесса; оно не равно календарному времени запуска.`;
  $('data-table').innerHTML = table(['Выборка', 'Строк', 'Положительных', 'NDVI: пропуски', 'Население: пропуски'],
    r['development_data_quality.csv'].map((t) => { const [year, kind] = t.table.replace('.parquet', '').split('_'); return [`${year} · ${kind === 'train' ? 'обучение' : 'проверка'}`, num(t.rows), num(t.positives), pct(t.ndvi_missing_fraction, 1), pct(t.population_missing_fraction, 1)]; }));
  $('sample').textContent = `В финальной выборке ${num(evaluation.rows)} строк, ${num(evaluation.positive_rows)} положительных. Оценка взвешенного числа допустимых ячеек-дней — ${num(evaluation.weighted_cell_days)}.`;
  $('release-hash').textContent = evaluation.release_sha256;
});
