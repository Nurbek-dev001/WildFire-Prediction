import { $, pct, num, run, loadVerified, table, dotPanel, barChart, widthOf, panelWidth } from './report.js';

const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
const MODEL = { xgboost: 'Исходный XGBoost', xgboost_stack: 'XGBoost + второй уровень' };

run(async () => {
  const d = await loadVerified('../quality/complete.json', '../quality/', ['summary.json', 'events.json', 'spatial_metrics.csv', 'subgroups.csv', 'independent_evaluation.json', 'independent_event_metrics.json', 'independent_outage_sensitivity.json']);
  // Region names only translate labels; geography.json carries no metrics.
  const geo = await (await fetch('../assets/geography.json')).json();
  const ruRegion = Object.fromEntries(geo.regions.map((r) => [r.name, r.label]));

  const f = d['independent_evaluation.json'], m = f.metrics, base = f.baseline_metrics, ci = f.confidence_intervals_95, diff = f.paired_difference_intervals_95;
  const ev = d['events.json'], exact = ev.cell_day_exact, all = ev.all_events, cell = d['summary.json'].cell_day;
  const fe = d['independent_event_metrics.json'], out = d['independent_outage_sensitivity.json'];

  $('tiles').innerHTML = [
    ['Precision · 2025', pct(m.precision), 'независимый год, порог не менялся', true],
    ['Recall · 2025', pct(m.recall), `95% интервал ${pct(ci.recall[0])}–${pct(ci.recall[1])}`, true],
    ['Precision · все карты', pct(exact.precision), '2023–2024, полный пересчёт'],
    ['События в день обнаружения', pct(all.same_day_event_recall_all), `из ${num(all.events)} событий 2023–2024`],
  ].map(([l, v, h, a]) => `<div class="metric"><span class="label">${l}</span><span class="value${a ? ' is-accent' : ''}">${v}</span><span class="hint">${h}</span></div>`).join('');

  $('fresh-lead').textContent = `Тест 2025 завершён: precision ${pct(m.precision)}, recall ${pct(m.recall)}. Порог ${pct(f.threshold, 4)} не менялся; обучение закончилось ${f.training_max_year} годом, модель после теста не обновлялась.`;
  $('fresh-chart').innerHTML = ['precision', 'recall'].map((k) => dotPanel({
    title: k === 'precision' ? 'Precision на 2025' : 'Recall на 2025',
    width: panelWidth($('fresh-chart')),
    max: Math.max(base[k], ci[k][1]) * 1.3,
    rows: [{ label: 'Исходный XGBoost', value: base[k] }, { label: 'XGBoost + второй уровень', value: m[k], lo: ci[k][0], hi: ci[k][1], accent: true }],
  })).join('');
  $('fresh-caption').textContent = `Отрезок — 95% интервал для текущей модели: 1000 парных блочных повторов 100 км × 30 дней, seed 42. Исходный XGBoost — заранее объявленное вторичное сравнение на той же выборке, точка без интервала. Взвешенная совокупность — ${num(m.weighted_rows)} ячеек-дней, положительных — ${num(m.tp + m.fn)}. Интервал AP не рассчитывался.`;
  $('fresh-table').innerHTML = table(['Модель', 'Precision', 'Recall', 'F1', 'AP', 'ROC-AUC'], [
    ['Исходный XGBoost', pct(base.precision), pct(base.recall), num(base.f1, 4), num(base.average_precision, 4), num(base.roc_auc, 4)],
    ['XGBoost + второй уровень', pct(m.precision), pct(m.recall), num(m.f1, 4), num(m.average_precision, 4), num(m.roc_auc, 4)],
  ], { current: 1 });
  $('fresh-diff').textContent = `Рост recall сопровождается снижением precision. Разность recall: от ${num(diff.recall[0] * 100, 2)} до ${num(diff.recall[1] * 100, 2)} процентного пункта (95% интервал). Интервал разности precision (${num(diff.precision[0] * 100, 2)}…${num(diff.precision[1] * 100, 2)} п. п.) включает ноль; это не доказывает, что precision не изменилась.`;
  $('fresh-events').textContent = `Уникальных событий 2025 года — ${num(fe.events)}, в покрытой области в день первого обнаружения — ${num(fe.covered_first_day_events)}. Полнота по всем событиям: ${pct(fe.same_day_event_recall_all)} в день обнаружения и ${pct(fe.prior_day_event_recall_all)} накануне. Это сопоставление со спутниковым наблюдением; фактическое время возгорания неизвестно.`;
  $('fresh-outage').textContent = `Заранее объявленная вторичная проверка без 11–12 ноября 2025, вокруг документированного сбоя SNPP: precision ${pct(out.metrics.precision)}, recall ${pct(out.metrics.recall)}; исключено ${num(out.excluded_rows)} строк. Основной результат за весь год сохранён. Пропуск спутниковых наблюдений не доказывает отсутствие пожаров.`;

  $('exact-text').textContent = `Просмотрены все ${num(exact.rows)} допустимых ячеек-дней из 731 карты, без подвыборки отрицательных примеров. Precision — ${pct(exact.precision)}, recall — ${pct(exact.recall)}, AP — ${num(exact.average_precision, 4)}. Сигнальных ячеек-дней — ${num(ev.alert_cell_days)}: верных — ${num(exact.tp)}, ложных — ${num(exact.fp)}; пропущено положительных — ${num(exact.fn)}.`;
  $('exact-note').textContent = `Прежние precision ${pct(cell.precision)} и AP ${num(cell.average_precision, 4)} получены по выборке отрицательных ячеек с обратными весами. Различие отражает выборочную погрешность, а не улучшение модели. Recall совпадает: в выборке сохранены все положительные ячейки-дни. Интервалы прежней оценки нельзя переносить на полный пересчёт.`;
  $('events-text').textContent = `Всего ${num(all.events)} событий; в покрытой области — ${num(all.covered_events)}, вне неё — ${num(all.uncovered_events)}. Полнота в день первого обнаружения: ${pct(all.same_day_event_recall_all)} для всех событий и ${pct(all.same_day_event_recall_covered)} для покрытых. Сигнал за предыдущие сутки получили ${pct(all.prior_day_event_recall_all)} событий. Это ретроспективное сопоставление, а не измерение заблаговременного оповещения.`;
  $('components-text').textContent = `Если объединить сигналы по восьми соседям сетки и соседним суткам, получается ${num(ev.alert_components)} цепочек; ${num(ev.matched_alert_components)} совпали хотя бы с одним событием в той же ячейке в день обнаружения или накануне. Длинная цепочка может содержать много ложных ячеек, поэтому доля совпавших цепочек ${pct(ev.alert_component_match_fraction)} — это не precision ячеек-дней.`;

  const sub = d['subgroups.csv'];
  $('subgroup-lead').textContent = `Взвешенная доля ячеек-дней без NDVI — ${pct(d['summary.json'].subgroups.ndvi_missing_weighted)}. Это доля пропусков среди допустимых ячеек-дней, а не доля площади страны.`;
  const regions = sub.filter((r) => r.group === 'region').sort((a, b) => b.recall - a.recall);
  $('region-chart').innerHTML = barChart({ width: widthOf($('region-chart')), title: 'Recall по областям, 2023–2024', max: Math.max(...regions.map((r) => r.recall)) * 1.1, format: (v) => pct(v, 1),
    rows: regions.map((r) => ({ label: ruRegion[r.name] || r.name, value: r.recall })) });
  const months = sub.filter((r) => r.group === 'month').sort((a, b) => +a.name - +b.name);
  $('month-chart').innerHTML = barChart({ width: widthOf($('month-chart')), title: 'Recall по месяцам, 2023–2024', max: Math.max(...months.map((r) => r.recall)) * 1.1, format: (v) => pct(v, 1),
    rows: months.map((r) => ({ label: MONTHS[+r.name - 1], value: r.recall })) });

  const spatial = d['spatial_metrics.csv'];
  $('spatial-table').innerHTML = table(['Удержанная часть', 'Модель', 'Precision', 'Recall', 'AP', 'ROC-AUC'],
    spatial.map((r) => [`Часть ${+r.fold.split('_').pop() + 1}`, MODEL[r.model] || r.model, pct(r.precision), pct(r.recall), num(r.average_precision, 4), num(r.roc_auc, 3)]));
  $('release-hash').textContent = d['summary.json'].release_sha256;
});
