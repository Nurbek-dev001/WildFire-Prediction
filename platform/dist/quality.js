const pct=v=>Number.isFinite(v)?(100*v).toLocaleString('ru-RU',{maximumFractionDigits:2})+'%':'—';
const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let population;
export async function populationNote(cell){
  if(!population){const response=await fetch('./assets/population-2020.json');if(!response.ok)return '';population=await response.json();if(population.year!==2020||population.model_input!==false)throw Error('Population overlay metadata differs')}
  const v=population.values[cell];
  return Number.isFinite(v)&&v>=0?`Население: ≈ ${Math.round(v).toLocaleString('ru-RU')} чел. · WorldPop 2020. Отдельный слой экспозиции; не входит в эту модель и не оценивает ущерб.`:'Население 2020: нет данных.';
}
export async function readiness(){
  const response=await fetch('./assets/daily-status.json',{cache:'no-store'});
  if(!response.ok)return '<h2>Текущий прогноз не подтверждён.</h2><p>Нет проверенного статуса ежедневного расчёта.</p>';
  const s=await response.json();
  const descriptions={'365-day fire history':'Пожарная история: нет проверенного непрерывного архива за указанный период','meteorology':'Погода: массивы ERA5 за текущий год ещё не загружены','landcover':'Земной покров: не загружен MODIS за предыдущий год','vegetation':'Растительность: нет проверенного NDVI допустимой давности'};
  return `<h2>Сегодня: прогноз не выпущен.</h2><p>Проверка для ${esc(s.target_day)}. Получены реальные текущие наблюдения SNPP; это наблюдения, а не прогноз и не метки научного теста.</p><p>Последнее наблюдение в полученном источнике: ${esc(s.nrt_last_observation)}. Проверено: ${esc(s.checked_utc)}. Этот статус относится только к указанной дате.</p><ul>${s.gaps.map(g=>`<li>${esc(descriptions[g.source]||g.source)}${g.from?': '+esc(g.from)+' — '+esc(g.to):''}.</li>`).join('')}</ul><p>Для 365-дневного признака нельзя заменить отсутствующие дни нулевой активностью. Автоматическая публикация и оперативная проверка пока не запущены. На основной карте сохранена явно обозначенная ретроспектива 2023–2024.</p><p><a href="./assets/daily-status.json">Проверенный статус JSON ↗</a> · <a href="./quality/">Полный аудит ↗</a></p>`;
}
export async function quality(){
  const response=await fetch('./quality/summary.json');if(!response.ok)return '<h2>Аудит загружается.</h2><p><a href="./upgrade/">Отчёт текущей модели ↗</a></p>';
  const s=await response.json(),a=s.events.all_events,e=s.events.cell_day_exact;
  const fresh=s.fresh_2025?.metrics;
  const freshText=fresh?`<p><strong>Новая временная проверка 2025:</strong> precision ${pct(fresh.precision)}, recall ${pct(fresh.recall)}, AP ${fresh.average_precision.toFixed(5)}. Для обучения и настройки использованы только годы до 2023. После этой проверки модель и порог не менялись.</p>`:'';
  return `<h2>Качество и границы применения.</h2>${freshText}<p>Полный пересчёт ${e.rows.toLocaleString('ru-RU')} ячеек-дней 2023–2024: precision ${pct(e.precision)}, recall ${pct(e.recall)}. Прежняя взвешенная выборочная оценка: precision ${pct(s.cell_day.precision)}, recall ${pct(s.cell_day.recall)}. Это уточнение измерения, а не изменение модели. Для самостоятельного оперативного предупреждения качество не подтверждено.</p><p>Уникальные спутниковые события: ${a.events.toLocaleString('ru-RU')}. Полнота для всех событий в день первого обнаружения: ${pct(a.same_day_event_recall_all)}; для событий в покрытых ячейках: ${pct(a.same_day_event_recall_covered)}. Вне допустимой области модели: ${a.uncovered_events} событий.</p><p>Сетка карты — 5 км; метеосетка — 0,25°, приблизительно 18–28 км по разным направлениям в Казахстане. Более мелкая отрисовка не повышает точность метеоданных. Пропуски NDVI видны в отдельном аудите; обработка пропусков не восстанавливает наблюдения.</p><p>Добавлен слой населения WorldPop 2020 для оценки экспозиции. Исторические признаки модели сохраняют исходные даты, чтобы обновление слоя не внесло утечку будущего.</p><p>Цель — первое спутниковое обнаружение; время возгорания, распространение и ущерб не оцениваются. Новый тест 2025 и пространственный аудит имеют отдельные протоколы и ограничения.</p><p><a href="./quality/">События, регионы, источники и независимая проверка ↗</a></p>`;
}
