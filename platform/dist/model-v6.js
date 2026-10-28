// Model v6: its own manifest, maps and records, verified by hash before the map uses them.
import {t,pctText as pct,num} from './i18n.js?v=20261029-v6';
const hex=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');
const METRICS=['precision','recall','f1','average_precision','roc_auc','brier','bss','top_0.1pct','top_1pct'];
export const isV6=m=>m?.model==='xgboost_v6';
export function validateV6(m){
  if(m.synthetic!==false||!m.evaluation_released||m.retrospective!==true||m.operational_validation!==false)throw Error('Frozen evaluation provenance absent');
  if(m.format!=='little_endian_float16_byte_shuffle_gzip'||m.prediction_path!=='./assets/predictions-v6/'||!/^[a-f0-9]{64}$/.test(m.release_sha256))throw Error('v6 transport invalid');
  if(!Number.isFinite(m.threshold)||m.threshold<=0||m.threshold>=1||!m.test_metrics?.xgboost_v6||!m.test_metrics?.xgboost_spatiotemporal)throw Error('v6 thresholds invalid');
  const days=m.available_days;
  if(!Array.isArray(days)||!days.length||days.some((d,i)=>!/^202[346]-\d{2}-\d{2}$/.test(d)||new Date(d+'T00:00:00Z').toISOString().slice(0,10)!==d||i>0&&d<=days[i-1]))throw Error('Forecast dates invalid');
}
export async function loadV6(m){
  const read=async ref=>{
    const r=await fetch(ref.path);if(!r.ok)throw Error('v6 record unavailable');
    const b=await r.arrayBuffer();if(await hex(b)!==ref.sha256)throw Error('v6 record checksum differs');
    return ref.path.endsWith('.json')?JSON.parse(new TextDecoder().decode(b)):new TextDecoder().decode(b);
  };
  const r=m.records||{};
  const [release,frozen,evaluation,reliability,selection]=await Promise.all(['release','frozen','evaluation_2026','reliability_2026','development_selection'].map(k=>read(r[k])));
  const metrics=evaluation.metrics?.v6,v5=evaluation.metrics?.v5;
  if(r.release.sha256!==m.release_sha256||release.artifacts['frozen.json']!==r.frozen.sha256||release.selection_max_year!==2022||release.labels_after_2022_accessed!==false)throw Error('v6 release provenance differs');
  if(frozen.threshold!==m.threshold||JSON.stringify(frozen.features)!==JSON.stringify(m.input_features)||frozen.test_used_for_selection!==false)throw Error('v6 threshold or inputs differ');
  if(evaluation.synthetic!==false||evaluation.models_updated_after_test!==false||!metrics||!v5||METRICS.some(k=>metrics[k]!==m.test_metrics.xgboost_v6[k]||v5[k]!==m.test_metrics.xgboost_spatiotemporal[k]))throw Error('v6 test metrics differ');
  if(reliability.synthetic!==false||reliability.used_for_selection_or_recalibration!==false||selection.test_years_accessed!==false)throw Error('v6 records invalid');
  m.v6={release,frozen,evaluation,reliability,selection};
}
const f=(v,n=4)=>Number.isFinite(v)?num(v,{maximumFractionDigits:n}):'—';
export function v6Method(m){return t('v6.method',{n:m.input_features.length,t:pct(m.threshold,3)})}
export function v6Evaluation(m){
  const a=m.test_metrics.xgboost_v6,b=m.test_metrics.xgboost_spatiotemporal,d=m.test_2026;
  const row=(label,s,cls='')=>`<tr${cls}><td>${label}</td><td>${pct(s.precision)}</td><td>${pct(s.recall)}</td><td>${f(s.average_precision)}</td><td>${f(s.roc_auc,3)}</td><td>${pct(s['top_1pct'],1)}</td><td>${f(s.bss,3)}</td></tr>`;
  const table=`<div class="metrics-scroll"><table class="metrics-table"><thead><tr><th>${t('up.model')}</th><th>Precision</th><th>Recall</th><th>AP ↑</th><th>ROC-AUC ↑</th><th>${t('v6.top1')}</th><th>BSS ↑</th></tr></thead><tbody>${row('v6',a,' class="chosen-model"')}${row('v5',b)}</tbody></table></div>`;
  const ci=d.paired_difference;
  const bins=m.v6?.reliability?.bins?.v6||[];
  const rel=bins.filter(x=>x.rows).map(x=>`<tr><td>${pct(x.low,2)}–${pct(x.high,2)}</td><td>${pct(x.share,2)}</td><td>${pct(x.predicted,3)}</td><td>${pct(x.observed,3)}</td><td>${num(x.positives)}</td></tr>`).join('');
  const reliability=rel?`<h3>${t('v6.rel.title')}</h3><div class="metrics-scroll"><table class="metrics-table"><thead><tr><th>${t('v6.rel.bin')}</th><th>${t('v6.rel.share')}</th><th>${t('v6.rel.pred')}</th><th>${t('v6.rel.obs')}</th><th>${t('v6.rel.pos')}</th></tr></thead><tbody>${rel}</tbody></table></div>`:'';
  return t('v6.eval',{table,reliability,rows:num(d.rows),pos:num(d.positive_cell_days),r0:pct(ci.recall[0],1),r1:pct(ci.recall[1],1),p0:pct(ci.precision[0],1),p1:pct(ci.precision[1],1),hash:m.release_sha256.slice(0,16)});
}
