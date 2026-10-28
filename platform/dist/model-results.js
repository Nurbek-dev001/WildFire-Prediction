import {decodeHalf,upgradeMethod,upgradeEvaluation} from './upgrade-results.js?v=20261028-lang';
import {t,locale} from './i18n.js?v=20261028-lang';
import {policyComparison} from './operating-policy.js';
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const probability = p => Number.isFinite(p) ? (p*100).toLocaleString(locale(),{minimumFractionDigits:2,maximumFractionDigits:4})+'%' : '—';
export const modelLabel = name => ({xgboost_spatiotemporal:'XGBoost + stacking',logistic:'Logistic regression',random_forest:'Random forest',xgboost:'XGBoost',catboost:'CatBoost',weather_logistic:'Только погода · logistic',seasonal:'Сезонный фон'}[name] || name);
export function modelInputs(m){return t(m.upgrade?'inputs.upgrade':m.model==='seasonal'?'inputs.seasonal':m.model==='weather_logistic'?'inputs.weather':'inputs.default')}
export function scale(m){const b=m.boundaries||[];return [0,...b,Math.min(1,Math.max(m.threshold||0,(b.at(-1)||.001)*1.5))]}
export function validateManifest(m){
  if(!m.ready)return;
  if(m.synthetic!==false||!m.evaluation_released||!Array.isArray(m.available_days)||!m.available_days.length)throw Error('Evaluated forecast dates absent');
  if(!['little_endian_float32_gzip','little_endian_float32_byte_shuffle_gzip','little_endian_float16_byte_shuffle_gzip'].includes(m.format))return;
  if(!Number.isFinite(m.threshold)||m.threshold<0||m.threshold>1||!Array.isArray(m.boundaries)||m.boundaries.length<1||m.boundaries.length>3||m.boundaries.some((p,i,a)=>!Number.isFinite(p)||p<0||p>1||i>0&&p<a[i-1]))throw Error('Frozen thresholds invalid');
  if(m.retrospective!==true||m.operational_validation!==false||!m.test_metrics?.[m.model]||!/^([a-f0-9]{64})$/.test(m.release_sha256))throw Error('Frozen evaluation provenance absent');
  if(new Set(m.available_days).size!==m.available_days.length||m.available_days.some(d=>!/^202[34]-\d{2}-\d{2}$/.test(d)||new Date(d+'T00:00:00Z').toISOString().slice(0,10)!==d))throw Error('Forecast dates invalid');
}
export function colorIndex(p,m){const b=scale(m);let i=0;while(i<b.length-2&&p>b[i+1])i++;return Math.min(13,Math.max(0,Math.floor((i+Math.min(1,(p-b[i])/Math.max(1e-12,b[i+1]-b[i])))/(b.length-1)*14)))}
export async function loadForecast(day,m,count){
  if(m.synthetic!==false||!m.evaluation_released)throw Error('Evaluation provenance absent');
  if(['little_endian_float32_gzip','little_endian_float32_byte_shuffle_gzip','little_endian_float16_byte_shuffle_gzip'].includes(m.format)){
    const proof=m.prediction_assets?.[day];if(proof?.synthetic!==false||proof.target_day!==day||proof.count!==count||proof.model!==m.model||proof.release_sha256!==m.release_sha256||proof.format!==m.format)throw Error('Forecast provenance differs');
    const response=await fetch(`./assets/predictions/${day}.${m.format.includes('float16')?'f16':'f32'}.gz`);if(!response.ok)throw Error('Forecast unavailable');
    const compressed=await response.arrayBuffer();
    const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',compressed)),v=>v.toString(16).padStart(2,'0')).join('');
    if(digest!==proof.payload_sha256)throw Error('Forecast checksum differs');
    let raw=await new Response(new Blob([compressed]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
    if(m.format==='little_endian_float16_byte_shuffle_gzip'){const values=decodeHalf(raw,count);let finite=0;for(const p of values){if(Number.isNaN(p))continue;if(!Number.isFinite(p)||p<0||p>1)throw Error('Invalid half probability');finite++}if(finite!==proof.finite_cells)throw Error('Forecast coverage differs');return values}
    if(raw.byteLength!==count*4)throw Error('Grid size differs');
    if(m.format==='little_endian_float32_byte_shuffle_gzip'){const shuffled=new Uint8Array(raw),interleaved=new Uint8Array(raw.byteLength);for(let i=0;i<count;i++)for(let b=0;b<4;b++)interleaved[i*4+b]=shuffled[b*count+i];raw=interleaved.buffer}
    const view=new DataView(raw),values=new Float32Array(count);let finite=0;for(let i=0;i<count;i++){const p=view.getFloat32(i*4,true);if(!Number.isNaN(p)&&(!Number.isFinite(p)||p<0||p>1))throw Error('Invalid probability');if(Number.isFinite(p))finite++;values[i]=p}if(finite!==proof.finite_cells)throw Error('Forecast coverage differs');return values;
  }
  const response=await fetch(`./assets/predictions/${day}.json`);if(!response.ok)throw Error('Forecast unavailable');const data=await response.json();
  if(data.synthetic!==false||data.target_day!==day||data.probabilities.length!==count||!data.probabilities.every(p=>p===null||Number.isFinite(p)&&p>=0&&p<=1))throw Error('Invalid forecast');
  return Float32Array.from(data.probabilities,p=>p===null?NaN:p);
}
export function sources(m){return t('src.body',{model:escape(modelLabel(m.model)),inputs:modelInputs(m)})}
export function methodology(m){if(m.upgrade)return upgradeMethod(m);return `<h2>Прогноз, который можно проверить.</h2><div class="method-step"><b>01</b><div><strong>Реальная сетка 5 × 5 км</strong><p>110 129 ячеек Казахстана. Цель — первое обнаружение события, объединённого в пределах 2 км и 48 часов. Ячейки с детекциями за предыдущие 48 часов исключаются из прогноза нового очага.</p></div></div><div class="method-step"><b>02</b><div><strong>Выбор модели: 2015–2021</strong><p>Сравнивались logistic regression, random forest, XGBoost, CatBoost и два базовых метода. Временная валидация: 2019, 2020, 2021; обучение каждого раза использует более ранние годы.</p></div></div><div class="method-step"><b>03</b><div><strong>Калибровка: только 2022</strong><p>Калибровка и исходный порог ${probability(m.threshold)} зафиксированы до первого открытия теста. Обновлённые режимы предупреждений выбраны отдельно только по 2022 году; модель и вероятности не менялись. Отрицательные примеры имеют веса, восстанавливающие частоту событий в допустимых ячейках.</p></div></div><div class="method-step"><b>04</b><div><strong>Финальный тест: 2023–2024</strong><p>Эти годы открыты после фиксации модели. Их метрики не использовались для выбора победителя. Обученная модель: ${escape(modelLabel(m.model))}.</p></div></div><p>Метеоархив имеет задержку: используются наблюдения не позднее чем за 7 дней до целевой даты; NDVI — с консервативной задержкой и ограничением давности. Пропуски NDVI обрабатывает препроцессор, обученный только на тренировочных данных. Это ретроспективный эксперимент на переобработанных архивах; оперативная пригодность не подтверждена.</p><p><a href="./assets/model-method.txt" target="_blank">Подробная методика ↗</a></p>`}
export function evaluation(m){
  if(m.upgrade)return upgradeEvaluation(m);
  const metrics=m.test_metrics||{};const number=(v,n=4)=>Number.isFinite(v)?v.toLocaleString('ru-RU',{maximumFractionDigits:n}):'—';
  const rows=Object.entries(metrics).map(([name,s])=>`<tr${name===m.model?' class="chosen-model"':''}><td>${escape(modelLabel(name))}${name===m.model?' · выбрана':''}</td><td>${number(s.average_precision)}</td><td>${number(s.roc_auc)}</td><td>${number(s.brier,6)}</td></tr>`).join('');const s=metrics[m.model]||{};
  return `<h2>Оценка модели · 2023–2024.</h2>${policyComparison(m)}<p>Модель выбрана по временной валидации 2019–2021. Параметры, калибровка и исходные пороги были зафиксированы до первого доступа к тесту. Новые режимы предупреждений выбраны только на 2022 году. Частота положительных событий в тестовой совокупности: ${probability(s.prevalence)}.</p><div class="metrics-scroll"><table class="metrics-table"><thead><tr><th>Модель</th><th>AP ↑</th><th>ROC-AUC ↑</th><th>Brier ↓</th></tr></thead><tbody>${rows}</tbody></table></div><p>Исходный режим выбранной модели при пороге ${probability(m.threshold)}: precision ${number(s.precision)}, recall ${number(s.recall)}, F1 ${number(s.f1)}. Метрики учитывают вероятности отбора отрицательных примеров.</p><p>AP оценивает ранжирование редких событий; Brier — качество вероятностей. Высокая общая accuracy при редких пожарах сама по себе не подтверждает полезность модели.</p><p><a href="./assets/model-evaluation.json" target="_blank">Метрики и контрольные суммы ↗</a> · <a href="./assets/cluster_intervals.csv" target="_blank">Интервалы: 1000 блочных повторов ↗</a></p><p><a href="./results/" target="_blank">Полный отчёт: графики, калибровка и объяснения ↗</a></p><p>Статус: ретроспективный эксперимент. <code>${escape(m.release_sha256?.slice(0,16)||'')}</code></p>`;
}
