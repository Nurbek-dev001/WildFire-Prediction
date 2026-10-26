import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {webcrypto} from 'node:crypto';
import {loadOperatingPolicy,activeProfile,profileMetrics,policyComparison} from '../dist/operating-policy.js';

globalThis.crypto ??= webcrypto;
const base=new URL('../dist/',import.meta.url);
const original=JSON.parse(readFileSync(new URL('assets/forecast-manifest.json',base)));
if(original.upgrade){await import('./test-upgraded-model.mjs');process.exit(0)}
globalThis.fetch=async url=>new Response(readFileSync(new URL(url,base)));
const m=structuredClone(original);
await loadOperatingPolicy(m);
assert.equal(activeProfile(m).threshold,m.operating_policy.policy.profiles.balanced.threshold);
assert.equal(activeProfile(m,'precision').threshold,m.threshold);
assert(profileMetrics(m,'balanced').recall>profileMetrics(m,'precision').recall);
assert(profileMetrics(m,'balanced').precision<profileMetrics(m,'precision').precision);
assert(policyComparison(m).includes('не новая независимая'));
for(const url of ['policy_path','evaluation_path']){
  globalThis.fetch=async path=>new Response(readFileSync(new URL(path,base))+(path===original.operating_policy[url]?' ':'') );
  await assert.rejects(loadOperatingPolicy(structuredClone(original)),/checksum/);
}
console.log('Verified: 2022-only policy, default F2, old threshold, precision/recall tradeoff, both tamper guards.');
