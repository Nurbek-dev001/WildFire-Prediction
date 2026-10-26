import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash,webcrypto} from 'node:crypto';
import {loadUpgrade,decodeHalf} from '../dist/upgrade-results.js';

globalThis.crypto??=webcrypto;
const run=new URL('../../runs/model_stack_v5/',import.meta.url),read=p=>readFileSync(new URL(p,run));
const json=p=>JSON.parse(read(p)),hash=b=>createHash('sha256').update(b).digest('hex');
const release=json('release.json'),evaluation=json('evaluation.json'),frozen=json('frozen.json');
const score=evaluation.metrics.find(s=>s.model==='xgboost_spatiotemporal'&&s.period==='2023–2024');
const m={model:'xgboost_spatiotemporal',release_sha256:hash(read('release.json')),threshold:frozen.threshold,input_features:frozen.features,
 test_metrics:{xgboost_spatiotemporal:score},upgrade:{release_path:'./upgrade/release.json',release_sha256:hash(read('release.json')),evaluation_path:'./upgrade/evaluation.json',evaluation_sha256:hash(read('evaluation.json'))}};
globalThis.fetch=async path=>new Response(read(path.replace('./upgrade/','')));
await loadUpgrade(m);assert.equal(m.upgrade.verified,true);
const bad=structuredClone(m);bad.threshold=.5;
await assert.rejects(loadUpgrade(bad),/threshold/);
const stale=structuredClone(m);stale.test_metrics.xgboost_spatiotemporal.recall=1;
await assert.rejects(loadUpgrade(stale),/metrics/);
globalThis.fetch=async path=>new Response(read(path.replace('./upgrade/',''))+' ');
await assert.rejects(loadUpgrade(structuredClone(m)),/checksum/);
const bits=new Uint16Array([0,0x8000,1,0x3c00,0x7e00]),bytes=new Uint8Array(bits.buffer),shuffled=new Uint8Array(10);
for(let i=0;i<5;i++)for(let j=0;j<2;j++)shuffled[j*5+i]=bytes[i*2+j];
const p=decodeHalf(shuffled.buffer,5);assert(Object.is(p[1],-0));assert.equal(p[2],2**-24);assert.equal(p[3],1);assert(Number.isNaN(p[4]));
assert.equal(release.selection_max_year,2022);
console.log('Verified frozen upgraded-model metadata, stale-threshold/metric/tamper rejection and float16 edge cases.');
