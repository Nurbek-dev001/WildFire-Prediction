// Alert decisions are versioned separately from immutable model probabilities.
export async function loadOperatingPolicy(manifest){
  const ref=manifest.operating_policy;if(!ref)return;
  const read=async(path,expected)=>{
    const response=await fetch(path);if(!response.ok)throw Error('Alert policy unavailable');
    const bytes=await response.arrayBuffer();
    const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');
    if(hash!==expected)throw Error('Alert policy checksum differs');
    return JSON.parse(new TextDecoder().decode(bytes));
  };
  const [policy,result]=await Promise.all([read(ref.policy_path,ref.policy_sha256),read(ref.evaluation_path,ref.evaluation_sha256)]);
  if(policy.synthetic!==false||result.synthetic!==false||policy.selection_max_year!==2022||policy.test_used_to_select_threshold!==false||policy.model_retrained!==false||policy.probabilities_changed!==false||policy.model_release_sha256!==manifest.release_sha256||result.policy_sha256!==ref.policy_sha256||result.model_release_sha256!==manifest.release_sha256||result.policy_fixed_before_reassessment!==true||!policy.profiles[policy.default_profile])throw Error('Alert policy provenance differs');
  for(const [key,value] of Object.entries(policy.profiles)){
    const metric=result.metrics[key];
    if(!Number.isFinite(value.threshold)||value.threshold<0||value.threshold>1||!metric||metric.threshold!==value.threshold||!Number.isFinite(metric.recall)||!Number.isFinite(metric.precision))throw Error('Alert profile invalid');
  }
  ref.policy=policy;ref.result=result;
}
export function activeProfile(manifest,key){
  const policy=manifest?.operating_policy?.policy;
  return policy?.profiles[key||policy.default_profile]||{threshold:manifest?.threshold,label:manifest?.upgrade?'Переобученная модель':'Исходный порог'};
}
export function profileMetrics(manifest,key){
  const policy=manifest?.operating_policy?.policy;
  return manifest?.operating_policy?.result?.metrics[key||policy?.default_profile]||manifest?.test_metrics?.[manifest.model];
}
export function policyComparison(manifest){
  const ref=manifest.operating_policy;if(!ref?.policy)return '';
  const pct=value=>(value*100).toLocaleString('ru-RU',{maximumFractionDigits:2})+'%';
  const num=value=>value.toLocaleString('ru-RU',{maximumFractionDigits:4});
  const rows=Object.entries(ref.policy.profiles).map(([key,p])=>{
    const s=ref.result.metrics[key];
    return `<tr${key===ref.policy.default_profile?' class="chosen-model"':''}><td>${p.label}</td><td>${pct(p.threshold)}</td><td>${pct(s.precision)}</td><td>${pct(s.recall)}</td><td>${num(s.f2)}</td><td>${pct(s.alert_fraction)}</td></tr>`;
  }).join('');
  return `<h3>Обновлённые режимы предупреждений</h3><p>По умолчанию — «Баланс · F2». Все новые пороги выбраны только по 2022 году и зафиксированы перед повторной оценкой. F2 придаёт полноте больший вес. Модель и вероятности прежние; изменяется решение о предупреждении.</p><div class="metrics-scroll"><table class="metrics-table"><thead><tr><th>Режим</th><th>Порог</th><th>Precision</th><th>Recall</th><th>F2</th><th>Доля сигналов</th></tr></thead><tbody>${rows}</tbody></table></div><p>Таблица: 2023–2024, с весами отбора. Более высокий recall увеличивает число ложных сигналов. «Охват ≥30%» — целевая полнота на 2022 году, без гарантии на другую дату или область.</p><p>Повторная оценка использует уже опубликованный тест; это не новая независимая контрольная выборка. Режимы не настраивались по его значениям.</p><p><a href="./alerts/">Отчёт по порогам, график и доверительные интервалы ↗</a> · <a href="./alerts/metrics.csv">CSV метрик ↗</a></p>`;
}
