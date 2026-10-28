import { regionName } from '../i18n.js?v=20261028-lang';
import { $, t, pct, num, run, loadVerified, table, dotPanel, barChart, widthOf, panelWidth } from './report.js?v=20261028-lang';

const MONTHS = t('qj.months');
const MODEL = { xgboost: t('m.original'), xgboost_stack: t('m.stack') };

run(async () => {
  const d = await loadVerified('../quality/complete.json', '../quality/', ['summary.json', 'events.json', 'spatial_metrics.csv', 'subgroups.csv', 'independent_evaluation.json', 'independent_event_metrics.json', 'independent_outage_sensitivity.json']);
  // Region names only translate labels; geography.json carries no metrics.
  const geo = await (await fetch('../assets/geography.json')).json();
  const regionLabel = Object.fromEntries(geo.regions.map((r) => [r.name, regionName(r)]));

  const f = d['independent_evaluation.json'], m = f.metrics, base = f.baseline_metrics, ci = f.confidence_intervals_95, diff = f.paired_difference_intervals_95;
  const ev = d['events.json'], exact = ev.cell_day_exact, all = ev.all_events, cell = d['summary.json'].cell_day;
  const fe = d['independent_event_metrics.json'], out = d['independent_outage_sensitivity.json'];

  $('tiles').innerHTML = [
    [t('qj.p25'), pct(m.precision), t('qj.p25.h'), true],
    [t('qj.r25'), pct(m.recall), t('qj.ci', { lo: pct(ci.recall[0]), hi: pct(ci.recall[1]) }), true],
    [t('qj.pAll'), pct(exact.precision), t('qj.pAll.h')],
    [t('qj.events'), pct(all.same_day_event_recall_all), t('qj.events.h', { n: num(all.events) })],
  ].map(([l, v, h, a]) => `<div class="metric"><span class="label">${l}</span><span class="value${a ? ' is-accent' : ''}">${v}</span><span class="hint">${h}</span></div>`).join('');

  $('fresh-lead').textContent = t('qj.lead', { p: pct(m.precision), r: pct(m.recall), t: pct(f.threshold, 4), y: f.training_max_year });
  $('fresh-chart').innerHTML = ['precision', 'recall'].map((k) => dotPanel({
    title: k === 'precision' ? t('qj.pOn') : t('qj.rOn'),
    width: panelWidth($('fresh-chart')),
    max: Math.max(base[k], ci[k][1]) * 1.3,
    rows: [{ label: t('m.original'), value: base[k] }, { label: t('m.stack'), value: m[k], lo: ci[k][0], hi: ci[k][1], accent: true }],
  })).join('');
  $('fresh-caption').textContent = t('qj.cap', { w: num(m.weighted_rows), pos: num(m.tp + m.fn) });
  $('fresh-table').innerHTML = table([t('rep.model'), 'Precision', 'Recall', 'F1', 'AP', 'ROC-AUC'], [
    [t('m.original'), pct(base.precision), pct(base.recall), num(base.f1, 4), num(base.average_precision, 4), num(base.roc_auc, 4)],
    [t('m.stack'), pct(m.precision), pct(m.recall), num(m.f1, 4), num(m.average_precision, 4), num(m.roc_auc, 4)],
  ], { current: 1 });
  $('fresh-diff').textContent = t('qj.diff', { r0: num(diff.recall[0] * 100, 2), r1: num(diff.recall[1] * 100, 2), p0: num(diff.precision[0] * 100, 2), p1: num(diff.precision[1] * 100, 2) });
  $('fresh-events').textContent = t('qj.fresh', { n: num(fe.events), c: num(fe.covered_first_day_events), ra: pct(fe.same_day_event_recall_all), rp: pct(fe.prior_day_event_recall_all) });
  $('fresh-outage').textContent = t('qj.outage', { p: pct(out.metrics.precision), r: pct(out.metrics.recall), n: num(out.excluded_rows) });

  $('exact-text').textContent = t('qj.exact', { rows: num(exact.rows), p: pct(exact.precision), r: pct(exact.recall), ap: num(exact.average_precision, 4), a: num(ev.alert_cell_days), tp: num(exact.tp), fp: num(exact.fp), fn: num(exact.fn) });
  $('exact-note').textContent = t('qj.exactNote', { p: pct(cell.precision), ap: num(cell.average_precision, 4) });
  $('events-text').textContent = t('qj.ev', { n: num(all.events), c: num(all.covered_events), u: num(all.uncovered_events), ra: pct(all.same_day_event_recall_all), rc: pct(all.same_day_event_recall_covered), rp: pct(all.prior_day_event_recall_all) });
  $('components-text').textContent = t('qj.comp', { n: num(ev.alert_components), m: num(ev.matched_alert_components), f: pct(ev.alert_component_match_fraction) });

  const sub = d['subgroups.csv'];
  $('subgroup-lead').textContent = t('qj.sub', { v: pct(d['summary.json'].subgroups.ndvi_missing_weighted) });
  const regions = sub.filter((r) => r.group === 'region').sort((a, b) => b.recall - a.recall);
  $('region-chart').innerHTML = barChart({ width: widthOf($('region-chart')), title: t('qj.regions'), max: Math.max(...regions.map((r) => r.recall)) * 1.1, format: (v) => pct(v, 1),
    rows: regions.map((r) => ({ label: regionLabel[r.name] || r.name, value: r.recall })) });
  const months = sub.filter((r) => r.group === 'month').sort((a, b) => +a.name - +b.name);
  $('month-chart').innerHTML = barChart({ width: widthOf($('month-chart')), title: t('qj.months.t'), max: Math.max(...months.map((r) => r.recall)) * 1.1, format: (v) => pct(v, 1),
    rows: months.map((r) => ({ label: MONTHS[+r.name - 1], value: r.recall })) });

  const spatial = d['spatial_metrics.csv'];
  $('spatial-table').innerHTML = table([t('qj.part'), t('rep.model'), 'Precision', 'Recall', 'AP', 'ROC-AUC'],
    spatial.map((r) => [t('qj.partN', { n: +r.fold.split('_').pop() + 1 }), MODEL[r.model] || r.model, pct(r.precision), pct(r.recall), num(r.average_precision, 4), num(r.roc_auc, 3)]));
  $('release-hash').textContent = d['summary.json'].release_sha256;
});
