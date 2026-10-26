const pct=v=>(v*100).toLocaleString('ru-RU',{maximumFractionDigits:2})+'%';
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
export function upgradeMethod(m){return `<h2>Переобученная модель · ${m.input_features.length} признаков.</h2><p>Обучен новый ансамбль: исходный XGBoost и логистический второй уровень, который использует его оценку и шесть признаков предшествующей пожарной активности. Итоговая оценка смешивает два прогноза с весами 50/50 и проходит калибровку по 2022 году.</p><p>Пожарная история использует активные ячейки из прошлых спутниковых детекций в квадратных окрестностях 15 и 55 км. Окна 7, 30, 90 и 365 дней заканчиваются не позднее чем за двое суток до цели. Будущие детекции, метки целевого дня и будущие связи событий в признаки не входят.</p><p>Базовая модель обучена на 2015–2021. Второй уровень обучен на прогнозах 2019–2021, каждый из которых построен по более ранним годам. Регуляризация выбрана на 2021; вес смеси — по улучшению на 2021 и 2022. Порог выбран по 2022 при precision не ниже исходной модели на том же году. Порог ${pct(m.threshold)} зафиксирован вместе с моделью перед повторной оценкой на 2023–2024.</p><p>Тест уже публиковался ранее, поэтому это повторная оценка на прежнем наборе. Вероятности округлены в float16 перед расчётом порога и метрик; карта показывает ровно эти значения. Пропуски сохранены. Пригодность для текущего оперативного прогноза не подтверждена.</p><p><a href="./upgrade/">Обучение, сравнение, метрики и контрольные суммы ↗</a></p>`}
export function upgradeEvaluation(m){
  const original=m.test_metrics.xgboost,s=m.test_metrics[m.model];
  const row=(label,v)=>`<tr><td>${label}</td><td>${pct(v.precision)}</td><td>${pct(v.recall)}</td><td>${v.f1.toFixed(4)}</td><td>${v.average_precision.toFixed(5)}</td></tr>`;
  return `<h2>Новая модель · оценка 2023–2024.</h2><p>Обучен новый второй уровень ансамбля и добавлена причинно упорядоченная история детекций. Порог выбран только по 2022 году с precision не ниже исходной модели на том же году; это ограничение настройки, без гарантии на иной период.</p><div class="metrics-scroll"><table class="metrics-table"><thead><tr><th>Модель</th><th>Precision</th><th>Recall</th><th>F1</th><th>AP</th></tr></thead><tbody>${row('Исходный XGBoost',original)}${row(`XGBoost · ${m.input_features.length} признаков`,s)}</tbody></table></div><p>Сложность второго уровня выбрана на 2021; вес смеси проверен на 2021 и 2022. Обучение использует годы до 2022. Калибровка и порог — 2022. Все параметры зафиксированы перед этой оценкой. Данные 2023–2024 не использовались для обучения или выбора.</p><p>Это повторная оценка на ранее опубликованном тесте, а не новая независимая контрольная выборка. Сигналы обозначают первые спутниковые обнаружения новых событий в ячейках 5 × 5 км.</p><p><a href="./upgrade/">Отчёт по новой модели ↗</a> · <a href="./upgrade/metrics.csv">Метрики CSV ↗</a> · <a href="./upgrade/cluster_intervals.csv">Интервалы CSV ↗</a> · <a href="./results/">Исходное сравнение шести моделей ↗</a></p>`;
}
