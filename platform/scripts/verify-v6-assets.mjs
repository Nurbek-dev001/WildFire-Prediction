import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
import {decodeHalf} from '../dist/upgrade-results.js';

const base=new URL('../dist/',import.meta.url),read=p=>readFileSync(new URL(p,base));
const json=p=>JSON.parse(read(p)),digest=b=>createHash('sha256').update(b).digest('hex');
const m=json('assets/forecast-manifest-v6.json');
assert.equal(m.model,'xgboost_v6');assert.equal(m.synthetic,false);assert.equal(m.operational_validation,false);assert.equal(m.prediction_path,'./assets/predictions-v6/');
for(const [name,ref] of Object.entries(m.records))assert.equal(digest(read(ref.path.slice(2))),ref.sha256,name);
const release=json('v6/release.json'),frozen=json('v6/frozen.json'),evaluation=json('v6/evaluation_2026.json');
assert.equal(m.records.release.sha256,m.release_sha256);assert.equal(release.selection_max_year,2022);assert.equal(release.labels_after_2022_accessed,false);
assert.equal(release.artifacts['frozen.json'],m.records.frozen.sha256);assert.equal(m.threshold,frozen.threshold);assert.deepEqual(m.input_features,frozen.features);
assert.equal(evaluation.models_updated_after_test,false);
for(const [model,key] of [['xgboost_v6','v6'],['xgboost_spatiotemporal','v5']])for(const [metric,value] of Object.entries(m.test_metrics[model]))assert.equal(evaluation.metrics[key][metric],value,`${model} ${metric}`);
// Every day of 2023–2024 and of the 2026 test period, except the registered archive gaps.
const days=[],range=(a,b)=>{for(let t=Date.parse(a);t<=Date.parse(b);t+=86400000){const d=new Date(t).toISOString().slice(0,10);if(!m.test_2026.excluded_days.includes(d))days.push(d)}};
range('2023-01-01','2024-12-31');range(m.test_2026.period[0],m.test_2026.period[1]);
assert.deepEqual(m.available_days,days);assert.deepEqual(m.test_days,days.filter(d=>d.startsWith('2026')));
const count=read('assets/cells.bin').length/34;
let bytes=0,checked=0;const missing=[];
for(const day of days){
  const proof=m.prediction_assets[day],payload=read(`assets/predictions-v6/${day}.f16.gz`);
  assert.equal(digest(payload),proof.payload_sha256);assert.equal(proof.release_sha256,m.release_sha256);assert.equal(proof.model,m.model);assert.equal(proof.count,count);
  // A 2026 day with no eligible cells has no test rows either, so there is nothing to compare.
  assert.equal(proof.checked_against_test_sample,day.startsWith('2026')&&proof.finite_cells>0);if(proof.checked_against_test_sample)checked++;
  const raw=gunzipSync(payload),p=decodeHalf(raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength),count);
  let finite=0,alerts=0;
  for(const value of p){if(Number.isNaN(value))continue;assert(Number.isFinite(value)&&value>=0&&value<=1);finite++;if(value>=m.threshold)alerts++}
  assert.equal(finite,proof.finite_cells);assert.equal(alerts,proof.alert_cells);bytes+=payload.length;if(!finite)missing.push(day);
}
const events=json('assets/events-v6.json'),records=read('assets/events-v6.bin');
assert.equal(digest(records),events.sha256);assert.equal(events.sha256,m.observed_events.sha256);assert.equal(events.release_sha256,m.release_sha256);assert.equal(records.length,events.events*16);
for(let o=0;o<records.length;o+=16)assert(records.readUInt16LE(o)<days.length);
console.log(JSON.stringify({verified_dates:days.length,checked_against_test:checked,grid_cells:count,payload_bytes:bytes,missing_days:missing,events:events.events,release_sha256:m.release_sha256}));
