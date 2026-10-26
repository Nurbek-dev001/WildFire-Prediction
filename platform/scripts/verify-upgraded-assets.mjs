import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
import {decodeHalf} from '../dist/upgrade-results.js';

const base=new URL('../dist/',import.meta.url),read=p=>readFileSync(new URL(p,base));
const json=p=>JSON.parse(read(p)),digest=b=>createHash('sha256').update(b).digest('hex');
const m=json('assets/forecast-manifest.json'),release=json('upgrade/release.json'),evaluation=json('upgrade/evaluation.json');
assert.equal(m.model,'xgboost_spatiotemporal');assert.equal(m.synthetic,false);assert.equal(m.operational_validation,false);
assert.equal(digest(read('upgrade/release.json')),m.release_sha256);assert.equal(release.selection_max_year,2022);
assert.equal(digest(read('upgrade/evaluation.json')),m.upgrade.evaluation_sha256);assert.equal(evaluation.release_sha256,m.release_sha256);
assert.equal(evaluation.model_frozen_before_reassessment,true);assert.equal(evaluation.test_previously_reported,true);
const frozen=json('upgrade/frozen.json');assert.equal(digest(read('upgrade/frozen.json')),release.artifacts['frozen.json']);assert.equal(m.threshold,frozen.threshold);assert.deepEqual(m.input_features,frozen.features);
const days=[];for(let t=Date.parse('2023-01-01');t<=Date.parse('2024-12-31');t+=86400000)days.push(new Date(t).toISOString().slice(0,10));
assert.deepEqual(m.available_days,days);const count=read('assets/cells.bin').length/34;
let bytes=0;const missing=[];
for(const day of days){
  const proof=m.prediction_assets[day],payload=read(`assets/predictions/${day}.f16.gz`);
  assert.equal(digest(payload),proof.payload_sha256);assert.equal(proof.release_sha256,m.release_sha256);
  const raw=gunzipSync(payload),p=decodeHalf(raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength),count);
  let finite=0,alerts=0;
  for(const value of p){if(Number.isNaN(value))continue;assert(Number.isFinite(value)&&value>=0&&value<=1);finite++;if(value>=m.threshold)alerts++}
  assert.equal(finite,proof.finite_cells);assert.equal(alerts,proof.alert_cells);bytes+=payload.length;if(!finite)missing.push(day);
}
for(const directory of ['upgrade','results','alerts']){
  const complete=json(`${directory}/complete.json`);
  for(const [file,hash] of Object.entries(complete.outputs))assert.equal(digest(read(`${directory}/${file}`)),hash,`${directory}/${file}`);
}
console.log(JSON.stringify({verified_dates:days.length,grid_cells:count,payload_bytes:bytes,missing_days:missing,release_sha256:m.release_sha256}));
