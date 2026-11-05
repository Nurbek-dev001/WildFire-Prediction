// Model v6: its own manifest, maps and records, verified by hash before the map uses them.
import {t,pctText as pct,num} from './i18n.js?v=20261105-m';
const hex=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');
const METRICS=['precision','recall','f1','average_precision','roc_auc','brier','bss','top_0.1pct','top_1pct'];
// v7 shares v6's transport and map; isV7 picks its own texts.
export const isV6=m=>m?.model==='xgboost_v6'||m?.model==='xgboost_v7'||m?.model==='xgboost_v6da';
export const isDayAhead=m=>m?.model==='xgboost_v6da';
export const isV7=m=>m?.model==='xgboost_v7';
export function validateV6(m){
  if(m.synthetic!==false||!m.evaluation_released||m.retrospective!==true||m.operational_validation!==false)throw Error('Frozen evaluation provenance absent');
  if(m.format!=='little_endian_float16_byte_shuffle_gzip'||m.prediction_path!=='./assets/predictions-v6/'||!/^[a-f0-9]{64}$/.test(m.release_sha256))throw Error('v6 transport invalid');
  if(!Number.isFinite(m.threshold)||m.threshold<=0||m.threshold>=1||!m.test_metrics?.xgboost_v6||!m.test_metrics?.xgboost_spatiotemporal)throw Error('v6 thresholds invalid');
  const days=m.available_days;
  if(!Array.isArray(days)||!days.length||days.some((d,i)=>!/^202[3-9]-\d{2}-\d{2}$/.test(d)||new Date(d+'T00:00:00Z').toISOString().slice(0,10)!==d||i>0&&d<=days[i-1]))throw Error('Forecast dates invalid');
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
export function v6Method(m){return t(isV7(m)?'v7.method':'v6.method',{n:m.input_features.length,t:pct(m.threshold,3)})}
export function v6Evaluation(m){
  if(isV7(m))return v7Evaluation(m);
  const a=m.test_metrics.xgboost_v6,b=m.test_metrics.xgboost_spatiotemporal,d=m.test_2026;
  const row=(label,s,cls='')=>`<tr${cls}><td>${label}</td><td>${pct(s.precision)}</td><td>${pct(s.recall)}</td><td>${f(s.average_precision)}</td><td>${f(s.roc_auc,3)}</td><td>${pct(s['top_1pct'],1)}</td><td>${f(s.bss,3)}</td></tr>`;
  const table=`<div class="metrics-scroll"><table class="metrics-table"><thead><tr><th>${t('up.model')}</th><th>Precision</th><th>Recall</th><th>AP ↑</th><th>ROC-AUC ↑</th><th>${t('v6.top1')}</th><th>BSS ↑</th></tr></thead><tbody>${row('v6',a,' class="chosen-model"')}${row('v5',b)}</tbody></table></div>`;
  const ci=d.paired_difference;
  const bins=m.v6?.reliability?.bins?.v6||[];
  const rel=bins.filter(x=>x.rows).map(x=>`<tr><td>${pct(x.low,2)}–${pct(x.high,2)}</td><td>${pct(x.share,2)}</td><td>${pct(x.predicted,3)}</td><td>${pct(x.observed,3)}</td><td>${num(x.positives)}</td></tr>`).join('');
  const reliability=rel?`<h3>${t('v6.rel.title')}</h3><div class="metrics-scroll"><table class="metrics-table"><thead><tr><th>${t('v6.rel.bin')}</th><th>${t('v6.rel.share')}</th><th>${t('v6.rel.pred')}</th><th>${t('v6.rel.obs')}</th><th>${t('v6.rel.pos')}</th></tr></thead><tbody>${rel}</tbody></table></div>`:'';
  return t('v6.eval',{table,reliability,rows:num(d.rows),pos:num(d.positive_cell_days),r0:pct(ci.recall[0],1),r1:pct(ci.recall[1],1),p0:pct(ci.precision[0],1),p1:pct(ci.precision[1],1),hash:m.release_sha256.slice(0,16)});
}

// Daily forecasts issued after the v6 release, bound to the hash-chained forecast log.
const LIVE_FIELDS=['target_day','synthetic','model','format','count','finite_cells','alert_cells','payload_sha256','release_sha256','retrospective','issued_utc','on_time','log_entry_sha256'];
export async function loadLive(v6){
  const r=await fetch('./assets/forecast-live.json',{cache:'no-store'});if(!r.ok)return null;
  const live=await r.json(),days=live.days||[];
  if(live.synthetic!==false||live.kind!=='daily_forecasts'||!Array.isArray(days))throw Error('Daily forecasts provenance absent');
  const mv6=live.models?.v6,mv7=live.models?.v7;
  if(mv6?.release_sha256!==v6.release_sha256||mv6.threshold!==v6.threshold)throw Error('Daily v6 forecasts are not from the registered v6');
  if(!/^[a-f0-9]{64}$/.test(mv7?.release_sha256||'')||!Number.isFinite(mv7.threshold)||mv7.prediction_path!=='./assets/predictions-v7/')throw Error('v7 release invalid');
  const last=v6.available_days.at(-1);
  if(days.some((d,i)=>!/^202[6-9]-\d{2}-\d{2}$/.test(d)||d<=last||i>0&&d<=days[i-1]))throw Error('Daily forecast dates invalid');
  for(const [key,m] of [['v6',mv6],['v7',mv7]])for(const d of days){
    const p=live.assets?.[key]?.[d];
    if(!p||LIVE_FIELDS.some(f=>!(f in p))||p.target_day!==d||p.synthetic!==false||p.retrospective!==false||p.model!=='xgboost_'+key||p.release_sha256!==m.release_sha256||p.format!==v6.format)throw Error('Daily forecast provenance differs: '+key+' '+d);
  }
  v6.available_days=[...v6.available_days,...days];v6.live_days=days;
  for(const d of days)v6.prediction_assets[d]=live.assets.v6[d];
  const v7={ready:days.length>0,synthetic:false,evaluation_released:true,retrospective:false,operational_validation:false,model:'xgboost_v7',format:v6.format,
    prediction_path:mv7.prediction_path,release_sha256:mv7.release_sha256,frozen_utc:mv7.frozen_utc,threshold:mv7.threshold,input_features:mv7.input_features,
    available_days:days,live_days:days,prediction_assets:live.assets.v7,development:mv7.development,calibration:mv7.calibration,
    test_metrics:{xgboost_v7:{precision:mv7.calibration_metrics?.precision,recall:mv7.calibration_metrics?.recall}},summary:live.summary,missed_days:live.missed_days};
  let dayahead=null;
  // Day-ahead v6da (issued during D-1): its own release and log; a fault here leaves v6 and v7 intact.
  try{dayahead=loadDayAhead(live.dayahead,v6)}catch(e){console.warn('Day-ahead forecast unavailable',e)}
  return {v7,heat:Array.isArray(live.heat_cells)?live.heat_cells:[],summary:live.summary,dayahead};
}
function loadDayAhead(da,v6){
  if(!da?.tomorrow)return null;
  if(da.model!=='xgboost_v6da'||!/^[a-f0-9]{64}$/.test(da.release_sha256||'')||!Number.isFinite(da.threshold)||da.prediction_path!=='./assets/predictions-v6da/')throw Error('Day-ahead release invalid');
  const d=da.tomorrow,p=da.assets?.[d];
  if(!/^202[6-9]-\d{2}-\d{2}$/.test(d)||d<=v6.available_days.at(-1))throw Error('Day-ahead date invalid');
  if(!p||LIVE_FIELDS.some(f=>!(f in p))||p.target_day!==d||p.synthetic!==false||p.retrospective!==false||p.model!=='xgboost_v6da'||p.release_sha256!==da.release_sha256||p.format!==v6.format)throw Error('Day-ahead provenance differs: '+d);
  return {...v6,model:'xgboost_v6da',retrospective:false,prediction_path:da.prediction_path,release_sha256:da.release_sha256,threshold:da.threshold,
    available_days:[d],live_days:[d],prediction_assets:{[d]:p},era5_lag_days:da.era5_lag_days,issued_utc:p.issued_utc,on_time:p.on_time,
    test_metrics:{...v6.test_metrics,xgboost_v6da:v6.test_metrics?.xgboost_v6}};
}
export function v7Evaluation(m){
  const d=m.development||{},boot=d.paired_bootstrap_95||{},rows=d.origins||[];
  const by=(o,k)=>rows.find(r=>r.origin===o&&r.model===k)||{};
  const table=[...new Set(rows.map(r=>r.origin))].sort().map(o=>{const a=by(o,'v6_recipe'),b=by(o,'v7'),ci=boot[String(o)]?.ap;
    return `<tr><td>${o}${b.inputs==='gfs'?' · GFS':''}</td><td>${f(a.ap)}</td><td><b>${f(b.ap)}</b></td><td>${ci?f(ci[0])+' … '+f(ci[1]):'—'}</td><td>${pct(a.recall_at_v6_recipe_precision||0,1)} → <b>${pct(b.recall_at_v6_recipe_precision||0,1)}</b></td><td>${f(b.bss,3)}</td></tr>`}).join('');
  const s=m.summary||{};
  return t('v7.eval',{table,days:num(m.live_days.length),onTime:num(s.test_days_on_time||0),missed:num(s.test_days_missed||0),hash:m.release_sha256.slice(0,16)});
}
