import {t,pctText as pct} from './i18n.js?v=20261105-m';
export function decodeHalf(raw,count){
  if(raw.byteLength!==count*2)throw Error('Half grid size differs');
  const b=new Uint8Array(raw),out=new Float32Array(count);
  for(let i=0;i<count;i++){
    const h=b[i]|b[count+i]<<8,sign=h&32768?-1:1,e=(h>>10)&31,f=h&1023;
    out[i]=e===0?sign*2**-14*(f/1024):e===31?(f?NaN:sign*Infinity):sign*2**(e-15)*(1+f/1024);
  }
  return out;
}
export async function loadUpgrade(m){
  if(!m.upgrade)return;
  const read=async(path,hash)=>{
    const r=await fetch(path);if(!r.ok)throw Error('Upgrade metadata unavailable');
    const b=await r.arrayBuffer(),digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',b)),v=>v.toString(16).padStart(2,'0')).join('');
    if(digest!==hash)throw Error('Upgrade metadata checksum differs');return JSON.parse(new TextDecoder().decode(b));
  };
  const [release,evaluation]=await Promise.all([read(m.upgrade.release_path,m.upgrade.release_sha256),read(m.upgrade.evaluation_path,m.upgrade.evaluation_sha256)]);
  if(release.selection_max_year!==2022||evaluation.synthetic!==false||evaluation.release_sha256!==m.release_sha256||evaluation.model_frozen_before_reassessment!==true||!release.artifacts['model.joblib'])throw Error('Upgrade model provenance differs');
  const frozen=await read('./upgrade/frozen.json',release.artifacts['frozen.json']);
  const score=evaluation.metrics.find(s=>s.model===m.model&&s.period==='2023–2024');
  if(frozen.threshold!==m.threshold||JSON.stringify(frozen.features)!==JSON.stringify(m.input_features)||!score||Object.entries(score).some(([key,value])=>m.test_metrics[m.model][key]!==value))throw Error('Upgrade threshold or metrics differ');
  m.upgrade.verified=true;
}
export function upgradeMethod(m){return t('up.method',{n:m.input_features.length,t:pct(m.threshold)})}
export function upgradeEvaluation(m){
  const original=m.test_metrics.xgboost,s=m.test_metrics[m.model];
  const row=(label,v)=>`<tr><td>${label}</td><td>${pct(v.precision)}</td><td>${pct(v.recall)}</td><td>${v.f1.toFixed(4)}</td><td>${v.average_precision.toFixed(5)}</td></tr>`;
  const table=`<div class="metrics-scroll"><table class="metrics-table"><thead><tr><th>${t('up.model')}</th><th>Precision</th><th>Recall</th><th>F1</th><th>AP</th></tr></thead><tbody>${row(t('up.original'),original)}${row(t('up.features',{n:m.input_features.length}),s)}</tbody></table></div>`;
  return t('up.eval',{table});
}
