import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
import {decodeHalf} from '../dist/upgrade-results.js';
// Daily forecasts on the map: each payload equals its log entry, from the registered releases.
const base=new URL('../dist/',import.meta.url),read=p=>readFileSync(new URL(p,base));
const json=p=>JSON.parse(read(p)),digest=b=>createHash('sha256').update(b).digest('hex');
if(!existsSync(new URL('assets/forecast-live.json',base))){console.log(JSON.stringify({daily_forecasts:0}));process.exit(0)}
const live=json('assets/forecast-live.json'),v6=json('assets/forecast-manifest-v6.json');
assert.equal(live.synthetic,false);assert.equal(live.kind,'daily_forecasts');
assert.equal(live.models.v6.release_sha256,v6.release_sha256);assert.equal(live.models.v6.threshold,v6.threshold);
assert(live.days.every((d,i)=>d>v6.available_days.at(-1)&&(i===0||d>live.days[i-1])));
const count=read('assets/cells.bin').length/34;
let alerts={v6:0,v7:0};
for(const key of ['v6','v7'])for(const day of live.days){
  const proof=live.assets[key][day],payload=read(`assets/predictions-${key}/${day}.f16.gz`);
  assert.equal(digest(payload),proof.payload_sha256,`${key} ${day}`);assert.equal(proof.release_sha256,live.models[key].release_sha256);
  assert.equal(proof.model,'xgboost_'+key);assert.equal(proof.count,count);assert.equal(proof.retrospective,false);
  const raw=gunzipSync(payload),p=decodeHalf(raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength),count);
  let finite=0,n=0;for(const v of p){if(Number.isNaN(v))continue;assert(v>=0&&v<=1);finite++;if(v>=live.models[key].threshold)n++}
  assert.equal(finite,proof.finite_cells);assert.equal(n,proof.alert_cells);alerts[key]+=n;
}
assert(live.heat_cells.every(i=>Number.isInteger(i)&&i>=0&&i<count));
console.log(JSON.stringify({daily_forecasts:live.days.length,first:live.days[0],last:live.days.at(-1),alerts,summary:live.summary}));
