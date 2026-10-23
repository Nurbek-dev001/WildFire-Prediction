import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {gunzipSync} from 'node:zlib';

const dist=fileURLToPath(new URL('../dist/',import.meta.url));
const read=name=>readFileSync(path.join(dist,name));
const json=name=>JSON.parse(read(name));
const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
const manifest=json('assets/forecast-manifest.json');
const verification=json('assets/export-verification.json');
const evaluation=json('assets/model-evaluation.json');
assert.equal(manifest.ready,true);
assert.equal(manifest.synthetic,false);
assert.equal(manifest.evaluation_released,true);
assert.equal(manifest.retrospective,true);
assert.equal(manifest.operational_validation,false);
assert.equal(verification.days,731);
assert.equal(verification.synthetic,false);
assert.equal(manifest.release_sha256,verification.release_sha256);
assert.equal(manifest.release_sha256,evaluation.release_sha256);
assert.equal(manifest.model,evaluation.selected_model);
assert.equal(manifest.model,verification.model);
assert.deepEqual(manifest.test_metrics,evaluation.metrics);
assert.equal(read('assets/cells.bin').length,verification.grid_cells*34);
const days=[];
for(let time=Date.parse('2023-01-01');time<=Date.parse('2024-12-31');time+=86400000)
  days.push(new Date(time).toISOString().slice(0,10));
assert.deepEqual(manifest.available_days,days);
assert.deepEqual(Object.keys(manifest.prediction_assets).sort(),days);
let totalBytes=0,minimum=Infinity,maximum=0;
const missingDays=[];
for(const day of days){
  const proof=manifest.prediction_assets[day];
  assert.equal(proof.target_day,day);
  assert.equal(proof.synthetic,false);
  assert.equal(proof.model,manifest.model);
  assert.equal(proof.release_sha256,manifest.release_sha256);
  assert.equal(proof.count,verification.grid_cells);
  const compressed=read(`assets/predictions/${day}.f32.gz`);
  assert.equal(digest(compressed),proof.payload_sha256,`Payload hash: ${day}`);
  let values=gunzipSync(compressed);
  assert.equal(values.length,verification.grid_cells*4);
  assert.equal(proof.format,manifest.format);
  if(manifest.format==='little_endian_float32_byte_shuffle_gzip'){
    const interleaved=Buffer.alloc(values.length),count=verification.grid_cells;
    for(let i=0;i<count;i++)for(let b=0;b<4;b++)interleaved[i*4+b]=values[b*count+i];
    values=interleaved;
  }else assert.equal(manifest.format,'little_endian_float32_gzip');
  let finite=0;
  for(let offset=0;offset<values.length;offset+=4){
    const value=values.readFloatLE(offset);
    if(Number.isNaN(value))continue;
    assert(Number.isFinite(value)&&value>=0&&value<=1,`Probability: ${day}`);
    finite++;
  }
  assert.equal(finite,proof.finite_cells,`Coverage: ${day}`);
  totalBytes+=compressed.length;
  minimum=Math.min(minimum,finite);maximum=Math.max(maximum,finite);
  if(finite===0)missingDays.push(day);
}
assert.equal(totalBytes,verification.browser_payload_bytes);
assert.equal(minimum,verification.minimum_finite_cells);
assert.equal(maximum,verification.maximum_finite_cells);
assert.equal(digest(read('assets/full_grid_top_capture.csv')),verification.exact_alert_burden_sha256);
for(const [name,hash] of Object.entries(evaluation.outputs))
  assert.equal(digest(read(`evaluate/${name}`)),hash,`Evaluation: ${name}`);
const report=json('results/complete.json');
assert.equal(report.release_sha256,manifest.release_sha256);
for(const [name,hash] of Object.entries(report.outputs))
  assert.equal(digest(read(`results/${name}`)),hash,`Report: ${name}`);
console.log(JSON.stringify({verified_dates:days.length,grid_cells:verification.grid_cells,
  payload_bytes:totalBytes,missing_days:missingDays,release_sha256:manifest.release_sha256}));
