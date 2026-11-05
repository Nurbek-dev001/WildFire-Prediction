// Interface language: Russian (default), English, Kazakh. One dictionary for every page.
// Static markup uses data-i18n / data-i18n-html / data-i18n-attr; scripts call t().
// Safe to import in Node (the platform checks run there): browser globals are optional.

export const LANGS = ['ru', 'en', 'kk'];
// Browsers often ship without Kazakh locale data; Kazakh numbers follow the Russian pattern
// (space groups, decimal comma), and Kazakh dates are spelled out below.
const LOCALE = { ru: 'ru-RU', en: 'en-GB', kk: 'ru-RU' };
const KK_MONTHS = ['қаңтар', 'ақпан', 'наурыз', 'сәуір', 'мамыр', 'маусым', 'шілде', 'тамыз', 'қыркүйек', 'қазан', 'қараша', 'желтоқсан'];
const KK_DAYS = ['жс', 'дс', 'сс', 'ср', 'бс', 'жм', 'сб'];
const STORE = 'steppe-lang';
const listeners = new Set();

function initial() {
  try {
    const fromUrl = new URLSearchParams(globalThis.location?.search || '').get('lang');
    if (LANGS.includes(fromUrl)) return fromUrl;
    const saved = globalThis.localStorage?.getItem(STORE);
    if (LANGS.includes(saved)) return saved;
  } catch { /* storage can be blocked */ }
  return 'ru';
}
let current = initial();

export const lang = () => current;
export const locale = () => LOCALE[current];
export function setLang(next) {
  if (!LANGS.includes(next) || next === current) return;
  current = next;
  try { globalThis.localStorage?.setItem(STORE, next); } catch { /* per-viewer convenience only */ }
  if (globalThis.document) applyStatic();
  for (const fn of listeners) fn(next);
}
export const onLang = (fn) => listeners.add(fn);

export function t(key, vars = {}) {
  const entry = DICT[key];
  if (!entry) return key;
  const value = entry[current] ?? entry.ru;
  return typeof value === 'function' ? value(vars) : value;
}

export const num = (v, opts) => Number(v).toLocaleString(LOCALE[current], opts);
export const pctText = (v, max = 2) => (v * 100).toLocaleString(LOCALE[current], { maximumFractionDigits: max }) + '%';
export function longDate(date) {
  const d = typeof date === 'string' ? new Date(date + 'T00:00:00Z') : date;
  if (current === 'kk') return `${d.getUTCFullYear()} жылғы ${d.getUTCDate()} ${KK_MONTHS[d.getUTCMonth()]}`;
  return new Intl.DateTimeFormat(LOCALE[current], { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(d).replace(/ г\.$/, '');
}
export const weekday = (d) => current === 'kk' ? KK_DAYS[d.getUTCDay()] : new Intl.DateTimeFormat(LOCALE[current], { weekday: 'short', timeZone: 'UTC' }).format(d);
export function coords(lat, lon, digits = 3) {
  const f = (v) => v.toLocaleString(LOCALE[current], { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return { ru: `${f(lat)}° с. ш., ${f(lon)}° в. д.`, en: `${f(lat)}° N, ${f(lon)}° E`, kk: `${f(lat)}° с. е., ${f(lon)}° ш. б.` }[current];
}

// Regions follow the 2017 source geography; keys are the source's English names.
const REGIONS = {
  'Pavlodar Region': ['Павлодарская', 'Pavlodar', 'Павлодар'],
  'Jambyl Region': ['Жамбылская', 'Jambyl', 'Жамбыл'],
  'Kostanay Region': ['Костанайская', 'Kostanay', 'Қостанай'],
  'Mangystau Region': ['Мангистауская', 'Mangystau', 'Маңғыстау'],
  'Karaganda Region': ['Карагандинская', 'Karaganda', 'Қарағанды'],
  'Kyzylorda Region': ['Кызылординская', 'Kyzylorda', 'Қызылорда'],
  'East Kazakhstan Region': ['Восточно-Казахстанская', 'East Kazakhstan', 'Шығыс Қазақстан'],
  'Aktobe Region': ['Актюбинская', 'Aktobe', 'Ақтөбе'],
  'Atyrau Region': ['Атырауская', 'Atyrau', 'Атырау'],
  'South Kazakhstan Region': ['Южно-Казахстанская', 'South Kazakhstan', 'Оңтүстік Қазақстан'],
  'Akmola Region': ['Акмолинская', 'Akmola', 'Ақмола'],
  'Almaty Region': ['Алматинская', 'Almaty Region', 'Алматы облысы'],
  'North Kazakhstan Region': ['Северо-Казахстанская', 'North Kazakhstan', 'Солтүстік Қазақстан'],
  'Almaty': ['Алматы', 'Almaty', 'Алматы'],
  'West Kazakhstan Region': ['Западно-Казахстанская', 'West Kazakhstan', 'Батыс Қазақстан'],
  'Astana': ['Астана', 'Astana', 'Астана'],
};
const CITIES = { 'Астана': ['Astana', 'Астана'], 'Алматы': ['Almaty', 'Алматы'], 'Шымкент': ['Shymkent', 'Шымкент'], 'Актобе': ['Aktobe', 'Ақтөбе'],
  'Атырау': ['Atyrau', 'Атырау'], 'Караганда': ['Karaganda', 'Қарағанды'], 'Костанай': ['Kostanay', 'Қостанай'], 'Павлодар': ['Pavlodar', 'Павлодар'],
  'Семей': ['Semey', 'Семей'], 'Кызылорда': ['Kyzylorda', 'Қызылорда'], 'Актау': ['Aktau', 'Ақтау'] };
const CITY_REGIONS = new Set(['Almaty', 'Astana']);

// style: '' for lists, 'abbr' adds "обл." in Russian, 'long' gives "… область / Region / облысы" for titles.
export function regionName(region, style = '') {
  const names = REGIONS[region.name];
  if (!names) return region.label;
  const city = CITY_REGIONS.has(region.name), long = style === 'long';
  if (current === 'ru') return city || !style ? names[0] : names[0] + (long ? ' область' : ' обл.');
  if (current === 'en') return long && !city && !names[1].endsWith('Region') ? names[1] + ' Region' : names[1];
  return long && !city && !names[2].endsWith('облысы') ? names[2] + ' облысы' : names[2];
}
export function cityName(name) {
  const names = CITIES[name];
  return !names || current === 'ru' ? name : names[current === 'en' ? 0 : 1];
}

// Report pages keep their Russian in the markup, so a key without the current language falls
// back to whatever the element held on first sight.
const ORIGINAL = new WeakMap();
function staticText(el, key, html) {
  if (!ORIGINAL.has(el)) ORIGINAL.set(el, html ? el.innerHTML : el.textContent);
  return DICT[key]?.[current] !== undefined ? t(key) : ORIGINAL.get(el);
}

export function applyStatic(root = globalThis.document) {
  if (!root) return;
  root.documentElement && (root.documentElement.lang = current);
  for (const el of root.querySelectorAll('[data-i18n]')) el.textContent = staticText(el, el.dataset.i18n, false);
  for (const el of root.querySelectorAll('[data-i18n-html]')) el.innerHTML = staticText(el, el.dataset.i18nHtml, true);
  for (const el of root.querySelectorAll('[data-i18n-attr]')) {
    for (const pair of el.dataset.i18nAttr.split(';')) {
      const [attr, key] = pair.split(':');
      if (attr && key) el.setAttribute(attr.trim(), t(key.trim()));
    }
  }
  for (const b of root.querySelectorAll('[data-lang]')) b.setAttribute('aria-pressed', String(b.dataset.lang === current));
}

// The switch: three buttons with data-lang; marks the current one and listens for clicks.
export function bindSwitch(root = globalThis.document) {
  for (const b of root.querySelectorAll('[data-lang]')) b.addEventListener('click', () => setLang(b.dataset.lang));
  applyStatic(root);
}

const L = (ru, en, kk) => ({ ru, en, kk });
export const DICT = {
  // ---------- shared chrome ----------
  'page.title': L('Steppe — карта пожарной опасности', 'Steppe — wildfire danger map', 'Steppe — өрт қаупі картасы'),
  'page.desc': L('Steppe — интерактивная карта вероятности возникновения природных пожаров в Казахстане. Реальная география, рельеф SRTM, открытые данные, архив VIIRS и проверяемые результаты моделей.',
    'Steppe is an interactive map of wildfire ignition probability in Kazakhstan: real geography, SRTM relief, open data, the VIIRS archive and verifiable model results.',
    'Steppe — Қазақстандағы табиғи өрттің шығу ықтималдығының интерактивті картасы. Нақты география, SRTM жер бедері, ашық деректер, VIIRS мұрағаты және тексерілетін модель нәтижелері.'),
  'lang.switch': L('Язык интерфейса', 'Interface language', 'Интерфейс тілі'),
  'nav.sections': L('Разделы', 'Sections', 'Бөлімдер'),
  'nav.map': L('Карта', 'Map', 'Карта'),
  'nav.model': L('Модель', 'Model', 'Модель'),
  'nav.models': L('Модели', 'Models', 'Модельдер'),
  'nav.stack': L('Модель v5', 'Model v5', 'v5 моделі'),
  'nav.previous': L('Исходная модель', 'Original model', 'Бастапқы модель'),
  'nav.alerts': L('Пороги тревоги', 'Alert thresholds', 'Дабыл шектері'),
  'nav.quality': L('Качество данных', 'Data quality', 'Деректер сапасы'),
  'nav.sources': L('Источники', 'Sources', 'Дереккөздер'),
  'nav.method': L('Методика', 'Method', 'Әдістеме'),
  'brand.aria': L('Steppe, карта', 'Steppe, map', 'Steppe, карта'),
  'release': L(({ model, hash }) => `Модель <b>${model}</b> · релиз ${hash}`, ({ model, hash }) => `Model <b>${model}</b> · release ${hash}`, ({ model, hash }) => `Модель <b>${model}</b> · релиз ${hash}`),
  'model.stack': L('XGBoost + второй уровень', 'XGBoost + second level', 'XGBoost + екінші деңгей'),
  'close': L('Закрыть', 'Close', 'Жабу'),

  // ---------- main map: panel ----------
  'map.title': L(({ date }) => `Прогноз на <span id="title-date">${date}</span>`, ({ date }) => `Forecast for <span id="title-date">${date}</span>`, ({ date }) => `Болжам: <span id="title-date">${date}</span>`),
  'map.title.history': L(({ year }) => `Спутниковые наблюдения <span>${year}</span>`, ({ year }) => `Satellite observations <span>${year}</span>`, ({ year }) => `Спутниктік бақылаулар <span>${year}</span>`),
  'map.intro': L('Вероятность нового природного пожара на следующие сутки, сетка 5 × 5 км', 'Probability of a new wildfire in the next 24 hours, 5 × 5 km grid', 'Келесі тәулікте жаңа табиғи өрт шығу ықтималдығы, 5 × 5 км тор'),
  'map.intro.history': L('Детекции спутника S-NPP VIIRS за год, сетка 5 × 5 км', 'S-NPP VIIRS satellite detections for the year, 5 × 5 km grid', 'S-NPP VIIRS спутнигінің жылдық анықтаулары, 5 × 5 км тор'),
  'panel.aria': L('Управление картой', 'Map controls', 'Картаны басқару'),
  'mode.aria': L('Режим карты', 'Map mode', 'Карта режимі'),
  'mode.real': L('Модель', 'Model', 'Модель'),
  'mode.demo': L('Демо', 'Demo', 'Демо'),
  'view.aria': L('Вид карты', 'Map view', 'Карта көрінісі'),
  'note.demo.missing': L('<div><strong>Показан демо-сценарий</strong><p>В этой копии сайта нет суточных файлов прогноза (assets/predictions). Демо — формула для показа интерфейса, не результат модели.</p></div>',
    '<div><strong>Showing the demo scenario</strong><p>This copy of the site has no daily forecast files (assets/predictions). The demo is a formula for showing the interface, not a model result.</p></div>',
    '<div><strong>Демо-сценарий көрсетілген</strong><p>Сайттың бұл көшірмесінде тәуліктік болжам файлдары жоқ (assets/predictions). Демо — интерфейсті көрсетуге арналған формула, модель нәтижесі емес.</p></div>'),
  'note.demo': L('<div><strong>Демо-сценарий</strong><p>Условные вероятности на реальной карте. Значения не рассчитаны моделью.</p></div>',
    '<div><strong>Demo scenario</strong><p>Illustrative probabilities on the real map. The values are not computed by the model.</p></div>',
    '<div><strong>Демо-сценарий</strong><p>Нақты картадағы шартты ықтималдықтар. Мәндерді модель есептеген жоқ.</p></div>'),
  'note.real': L('<div><strong>Ретроспективная модель</strong><p>Открытые данные · калибровка 2022 · повторная оценка 2023–2024. Не оперативный прогноз.</p></div>',
    '<div><strong>Retrospective model</strong><p>Open data · calibrated on 2022 · reassessed on 2023–2024. Not an operational forecast.</p></div>',
    '<div><strong>Ретроспективті модель</strong><p>Ашық деректер · 2022 жылы калибрленген · 2023–2024 жылдары қайта бағаланған. Жедел болжам емес.</p></div>'),
  'note.pending': L('<div><strong>Статус национальной модели</strong><p>Обучение и проверка ещё не завершены.</p></div>',
    '<div><strong>National model status</strong><p>Training and validation are not finished yet.</p></div>',
    '<div><strong>Ұлттық модель күйі</strong><p>Оқыту мен тексеру әлі аяқталған жоқ.</p></div>'),
  'stat.detections': L('Детекций VIIRS', 'VIIRS detections', 'VIIRS анықтаулары'),
  'stat.year': L(({ year }) => `${year} год`, ({ year }) => `year ${year}`, ({ year }) => `${year} жыл`),
  'stat.cellsWith': L('Ячеек с детекциями', 'Cells with detections', 'Анықтауы бар ұяшықтар'),
  'stat.cellMax': L('Максимум в ячейке', 'Maximum in a cell', 'Ұяшықтағы ең көп'),
  'stat.perYear': L('детекций за год', 'detections per year', 'жылдағы анықтау'),
  'stat.cellsForecast': L('Ячеек с прогнозом', 'Cells with a forecast', 'Болжамы бар ұяшықтар'),
  'stat.cellsMap': L('Ячеек на карте', 'Cells on the map', 'Картадағы ұяшықтар'),
  'stat.of': L(({ n }) => `из ${n}`, ({ n }) => `of ${n}`, ({ n }) => `${n} ішінен`),
  'stat.above': L(({ t }) => `Вероятность ≥ ${t}`, ({ t }) => `Probability ≥ ${t}`, ({ t }) => `Ықтималдық ≥ ${t}`),
  'stat.demoCells': L('демо-ячейки', 'demo cells', 'демо ұяшықтар'),
  'stat.cells': L('ячейки', 'cells', 'ұяшық'),
  'stat.max': L('Максимум на карте', 'Map maximum', 'Картадағы ең жоғары'),
  'stat.illustrative': L('условная вероятность', 'illustrative probability', 'шартты ықтималдық'),
  'stat.probability': L('вероятность', 'probability', 'ықтималдық'),
  'layers': L('Слой', 'Layer', 'Қабат'),
  'basemap': L('Подложка', 'Basemap', 'Фон'),
  'basemap.aria': L('Подложка карты', 'Map basemap', 'Карта фоны'),
  'basemap.satellite': L('Спутник', 'Satellite', 'Спутник'),
  'basemap.scheme': L('Схема', 'Plain', 'Сызба'),
  'layer.forecast': L('Новый очаг за сутки', 'New fire in 24 hours', 'Тәуліктегі жаңа ошақ'),
  'layer.forecast.sub': L('Первое спутниковое обнаружение', 'First satellite detection', 'Алғашқы спутниктік анықтау'),
  'layer.history': L('Наблюдения VIIRS', 'VIIRS observations', 'VIIRS бақылаулары'),
  'layer.history.sub': L('Реальные детекции · 2015–2022', 'Real detections · 2015–2022', 'Нақты анықтаулар · 2015–2022'),
  'history.year': L('Год наблюдений', 'Observation year', 'Бақылау жылы'),
  'profile.label': L('Режим предупреждений', 'Alert mode', 'Ескерту режимі'),
  'profile.active': L('Активная модель', 'Active model', 'Белсенді модель'),
  'profile.metrics': L(({ r, p, t }) => `Recall ${r} · Precision ${p} · порог ${t}`, ({ r, p, t }) => `Recall ${r} · Precision ${p} · threshold ${t}`, ({ r, p, t }) => `Recall ${r} · Precision ${p} · шек ${t}`),
  'profile.help.upgrade': L('Обучение: до 2022. Выбор модели и порога: до 2023. Метрики: повторная оценка 2023–2024.', 'Training: before 2022. Model and threshold chosen: before 2023. Metrics: reassessment on 2023–2024.', 'Оқыту: 2022 жылға дейін. Модель мен шекті таңдау: 2023 жылға дейін. Метрикалар: 2023–2024 жылдардағы қайта бағалау.'),
  'profile.help': L('Порог выбран по 2022. Метрики — за 2023–2024, не гарантия для выбранной даты.', 'Threshold chosen on 2022. Metrics are for 2023–2024, not a guarantee for the chosen date.', 'Шек 2022 бойынша таңдалды. Метрикалар 2023–2024 жылдарға арналған, таңдалған күнге кепілдік емес.'),
  'profile.compareModels': L('Сравнить модели', 'Compare models', 'Модельдерді салыстыру'),
  'profile.compareModes': L('Сравнить режимы', 'Compare modes', 'Режимдерді салыстыру'),
  'highOnly': L(({ t }) => `Только предупреждения ≥ ${t}`, ({ t }) => `Alerts only ≥ ${t}`, ({ t }) => `Тек ескертулер ≥ ${t}`),
  'regionLines': L('Границы областей', 'Region borders', 'Облыс шекаралары'),
  'points.heading': L('Точки возгорания на эту дату', 'Fire points on this date', 'Осы күнгі өрт нүктелері'),
  'points.predicted': L('Прогноз выше порога', 'Forecast above threshold', 'Шектен жоғары болжам'),
  'points.observed': L('Реальные новые очаги VIIRS', 'Real new VIIRS fires', 'VIIRS нақты жаңа ошақтары'),
  'points.note': L('Реальные очаги — первое обнаружение каждого нового события спутником S-NPP VIIRS. Эти метки открыты после фиксации и оценки модели, поэтому сравнение ретроспективное. Совпадение — очаг в той же ячейке 5 км в тот же день.',
    'Real fires are the first S-NPP VIIRS detection of each new event. These labels were opened after the model was frozen and evaluated, so the comparison is retrospective. A match is a fire in the same 5 km cell on the same day.',
    'Нақты ошақтар — әр жаңа оқиғаны S-NPP VIIRS спутнигінің алғаш анықтауы. Бұл белгілер модель бекітіліп, бағаланғаннан кейін ашылды, сондықтан салыстыру ретроспективті. Сәйкестік — сол күні сол 5 км ұяшықтағы ошақ.'),
  'points.summary': L(({ pred, obs, hits }) => `<span><b>${pred}</b> ячеек выше порога</span><span><b>${obs}</b> реальных новых очагов${hits !== null ? `, <b>${hits}</b> из них в ячейке с предупреждением` : ''}</span>`,
    ({ pred, obs, hits }) => `<span><b>${pred}</b> cells above the threshold</span><span><b>${obs}</b> real new fires${hits !== null ? `, <b>${hits}</b> of them in an alerted cell` : ''}</span>`,
    ({ pred, obs, hits }) => `<span><b>${pred}</b> ұяшық шектен жоғары</span><span><b>${obs}</b> нақты жаңа ошақ${hits !== null ? `, оның <b>${hits}</b> ескертілген ұяшықта` : ''}</span>`),
  'points.summary.title': L(({ n }) => `${n} очагов в области с прогнозом; совпадение считается в той же ячейке 5 км в тот же день.`, ({ n }) => `${n} fires inside the forecast area; a match is the same 5 km cell on the same day.`, ({ n }) => `Болжам аймағында ${n} ошақ; сәйкестік — сол күні сол 5 км ұяшық.`),
  'points.confirmed': L('очаг подтвердился', 'fire confirmed', 'ошақ расталды'),
  'points.more': L(({ n }) => `Ещё ${n} — на карте`, ({ n }) => `${n} more on the map`, ({ n }) => `Тағы ${n} — картада`),
  'points.open': L('Открыть место на спутниковом снимке', 'Open the place on the satellite image', 'Орынды спутниктік суретте ашу'),
  'regions': L('Области', 'Regions', 'Облыстар'),
  'regions.search': L('Найти область', 'Find a region', 'Облысты іздеу'),
  'regions.list': L('Области Казахстана', 'Regions of Kazakhstan', 'Қазақстан облыстары'),
  'regions.show': L(({ name }) => `${name}, показать на карте`, ({ name }) => `${name}, show on the map`, ({ name }) => `${name}, картада көрсету`),
  'regions.none': L('Область не найдена', 'No region found', 'Облыс табылмады'),
  'checks': L('Проверки', 'Checks', 'Тексерулер'),
  'checks.metrics': L('Метрики', 'Metrics', 'Метрикалар'),
  'checks.metricsTest': L('Метрики · тест 2023–2024', 'Metrics · 2023–2024 test', 'Метрикалар · 2023–2024 тест'),
  'checks.audit': L('Аудит · тест 2025', 'Audit · 2025 test', 'Аудит · 2025 тест'),
  'checks.readiness': L('Готовность данных', 'Data readiness', 'Деректер дайындығы'),
  'panel.foot': L('Сетка 5 × 5 км · 110 129 ячеек · равновеликая проекция LAEA', '5 × 5 km grid · 110,129 cells · equal-area LAEA projection', '5 × 5 км тор · 110 129 ұяшық · тең аумақты LAEA проекциясы'),

  // ---------- main map: canvas overlays ----------
  'map.aria': L('Интерактивная карта', 'Interactive map', 'Интерактивті карта'),
  'map.canvas': L('Карта Казахстана. Нажмите на ячейку, чтобы увидеть вероятность пожара.', 'Map of Kazakhstan. Select a cell to see its fire probability.', 'Қазақстан картасы. Өрт ықтималдығын көру үшін ұяшықты басыңыз.'),
  'date.prev': L('Предыдущий день', 'Previous day', 'Алдыңғы күн'),
  'date.next': L('Следующий день', 'Next day', 'Келесі күн'),
  'date.forecast': L('Дата прогноза', 'Forecast date', 'Болжам күні'),
  'date.scenario': L('Дата сценария', 'Scenario date', 'Сценарий күні'),
  'date.forecast.aria': L('Дата ретроспективного прогноза', 'Retrospective forecast date', 'Ретроспективті болжам күні'),
  'date.scenario.aria': L('Дата демо-сценария', 'Demo scenario date', 'Демо-сценарий күні'),
  'export': L('Экспорт CSV', 'Export CSV', 'CSV экспорттау'),
  'export.aria': L('Экспорт слоя в CSV', 'Export the layer to CSV', 'Қабатты CSV-ге экспорттау'),
  'badge.history': L('Архив NASA VIIRS', 'NASA VIIRS archive', 'NASA VIIRS мұрағаты'),
  'badge.demo': L('Демо-сценарий', 'Demo scenario', 'Демо-сценарий'),
  'badge.empty': L('Модель · нет данных', 'Model · no data', 'Модель · дерек жоқ'),
  'badge.verified': L('Модель · проверено по хешу', 'Model · hash verified', 'Модель · хэш тексерілді'),
  'badge.loading': L('Модель · загрузка', 'Model · loading', 'Модель · жүктелуде'),
  'badge.none': L('Модель · нет прогноза', 'Model · no forecast', 'Модель · болжам жоқ'),
  'source.history': L('номинальная и высокая уверенность', 'nominal and high confidence', 'номиналды және жоғары сенімділік'),
  'source.demo': L('формула, не модель', 'a formula, not the model', 'модель емес, формула'),
  'source.real': L('ретроспектива, не оперативный прогноз', 'retrospective, not an operational forecast', 'ретроспектива, жедел болжам емес'),
  'loading.map': L('Загружаем карту Казахстана…', 'Loading the map of Kazakhstan…', 'Қазақстан картасы жүктелуде…'),
  'loading.forecast': L('Загружаем прогноз и проверяем хеш файла…', 'Loading the forecast and checking the file hash…', 'Болжам жүктеліп, файл хэші тексерілуде…'),
  'loading.relief': L('Загружаем рельеф SRTM…', 'Loading SRTM relief…', 'SRTM жер бедері жүктелуде…'),
  'loading.detail': L('Загружаем детальный снимок…', 'Loading the detailed image…', 'Толық сурет жүктелуде…'),
  'loading.failed': L('Не удалось загрузить карту. Обновите страницу.', 'The map failed to load. Reload the page.', 'Картаны жүктеу мүмкін болмады. Бетті жаңартыңыз.'),
  'empty.title.empty': L('На эту дату нет допустимых ячеек', 'No eligible cells on this date', 'Бұл күні жарамды ұяшық жоқ'),
  'empty.title.missing': L('Файлы прогноза не найдены', 'Forecast files not found', 'Болжам файлдары табылмады'),
  'empty.title.failed': L('Файл прогноза не прошёл проверку', 'The forecast file failed its check', 'Болжам файлы тексеруден өтпеді'),
  'empty.title.pending': L('Реальный прогноз пока недоступен', 'The real forecast is not available yet', 'Нақты болжам әзірге қолжетімсіз'),
  'empty.text.empty': L('В исходном архиве нет обязательных наблюдений влажности почвы. Пропуск не означает нулевую вероятность, экспорт отключён.', 'The source archive lacks the required soil moisture observations. A gap does not mean zero probability; export is disabled.', 'Бастапқы мұрағатта міндетті топырақ ылғалдылығы бақылаулары жоқ. Олқылық нөлдік ықтималдықты білдірмейді, экспорт өшірулі.'),
  'empty.text.missing': L('В этой копии сайта нет суточных файлов assets/predictions: они не хранятся в Git. Как их получить — в platform/README.md.', 'This copy of the site has no daily assets/predictions files: they are not stored in Git. How to get them is in platform/README.md.', 'Сайттың бұл көшірмесінде assets/predictions тәуліктік файлдары жоқ: олар Git-те сақталмайды. Оларды алу жолы — platform/README.md ішінде.'),
  'empty.text.failed': L('Хеш или покрытие файла не совпали с релизом модели, значения не показаны. Выберите другую дату.', 'The file hash or coverage did not match the model release, so no values are shown. Choose another date.', 'Файл хэші немесе қамтуы модель релизіне сәйкес келмеді, мәндер көрсетілмейді. Басқа күнді таңдаңыз.'),
  'empty.text.pending': L('Обучение и финальная оценка ещё не завершены.', 'Training and the final evaluation are not finished yet.', 'Оқыту мен қорытынды бағалау әлі аяқталған жоқ.'),
  'empty.demo': L('Посмотреть демо-сценарий', 'View the demo scenario', 'Демо-сценарийді көру'),
  'zoom.in': L('Увеличить масштаб', 'Zoom in', 'Үлкейту'),
  'zoom.out': L('Уменьшить масштаб', 'Zoom out', 'Кішірейту'),
  'zoom.reset': L('Показать весь Казахстан', 'Show all of Kazakhstan', 'Бүкіл Қазақстанды көрсету'),
  'hint.3d': L('Тяните — вращать · колесо — масштаб · Shift — сдвиг · клик — ячейка', 'Drag to rotate · wheel to zoom · Shift to pan · click a cell', 'Тартып айналдыру · дөңгелек — масштаб · Shift — жылжыту · басу — ұяшық'),
  'hint.history': L('Детекции VIIRS не равны отдельным пожарам', 'VIIRS detections are not the same as individual fires', 'VIIRS анықтаулары жеке өрттерге тең емес'),
  'hint.map': L('Нажмите на карту, чтобы изучить ячейку', 'Click the map to inspect a cell', 'Ұяшықты қарау үшін картаны басыңыз'),
  'credit.regions': L('Границы областей: 2017', 'Region borders: 2017', 'Облыс шекаралары: 2017'),
  'credit.relief': L('Рельеф SRTM', 'SRTM relief', 'SRTM жер бедері'),
  'credit.esri': L('Снимок: Esri, Maxar, Earthstar Geographics', 'Imagery: Esri, Maxar, Earthstar Geographics', 'Сурет: Esri, Maxar, Earthstar Geographics'),
  'credit.nasa': L('Снимок: NASA Blue Marble · GIBS', 'Imagery: NASA Blue Marble · GIBS', 'Сурет: NASA Blue Marble · GIBS'),
  'unit.cell': L('5 × 5 км', '5 × 5 km', '5 × 5 км'),
  'unit.km2': L(({ n }) => `${n} км²`, ({ n }) => `${n} km²`, ({ n }) => `${n} км²`),
  'relief.aria': L('Трёхмерная карта: рельеф SRTM и выбранный слой. Нажмите на ячейку, чтобы увидеть детали.', 'Three-dimensional map: SRTM relief and the chosen layer. Select a cell to see details.', 'Үш өлшемді карта: SRTM жер бедері және таңдалған қабат. Мәліметтерді көру үшін ұяшықты басыңыз.'),
  'scale.km': L(({ n }) => `${n} км`, ({ n }) => `${n} km`, ({ n }) => `${n} км`),
  'scale.m': L(({ n }) => `${n} м`, ({ n }) => `${n} m`, ({ n }) => `${n} м`),

  // ---------- legend ----------
  'legend.title.history': L(({ year }) => `Детекций VIIRS в ячейке за ${year} год`, ({ year }) => `VIIRS detections per cell in ${year}`, ({ year }) => `${year} жылы ұяшықтағы VIIRS анықтаулары`),
  'legend.title': L('Вероятность нового очага за сутки, %', 'Probability of a new fire in 24 hours, %', 'Тәулікте жаңа ошақ ықтималдығы, %'),
  'legend.demo': L(' · демо', ' · demo', ' · демо'),
  'legend.threshold': L('Порог тревоги', 'Alert threshold', 'Дабыл шегі'),
  'legend.counts': L('Число ячеек в каждом классе на эту дату', 'Number of cells in each class on this date', 'Осы күні әр кластағы ұяшықтар саны'),
  'legend.note.history': L('Детекции до связывания в события и до фильтрации промышленных источников. Не равны числу пожаров.', 'Detections before linking into events and before removing industrial sources. Not equal to the number of fires.', 'Оқиғаларға біріктіруге және өнеркәсіптік көздерді сүзуге дейінгі анықтаулар. Өрт санына тең емес.'),
  'legend.note.real': L(({ t, sat }) => `Шкала логарифмическая: у 99% ячеек-дней вероятность ниже 0,33%. Черта — порог тревоги ${t}, выбранный на 2022 году. ${sat ? 'На снимке ячейки ниже 0,03% прозрачны, серым — нет данных.' : 'Штриховка — нет данных.'}`,
    ({ t, sat }) => `Logarithmic scale: 99% of cell-days are below 0.33%. The mark is the alert threshold ${t}, chosen on 2022. ${sat ? 'On the image, cells below 0.03% are transparent; grey means no data.' : 'Hatching means no data.'}`,
    ({ t, sat }) => `Логарифмдік шкала: ұяшық-күндердің 99%-ында ықтималдық 0,33%-дан төмен. Сызық — 2022 жылы таңдалған ${t} дабыл шегі. ${sat ? 'Суретте 0,03%-дан төмен ұяшықтар мөлдір, сұр — дерек жоқ.' : 'Штрихтау — дерек жоқ.'}`),
  'legend.note.demo': L(({ t }) => `Шкала демо-сценария. Черта — его условный порог ${t}.`, ({ t }) => `Demo scenario scale. The mark is its illustrative threshold ${t}.`, ({ t }) => `Демо-сценарий шкаласы. Сызық — оның шартты шегі ${t}.`),
  'legend.points.pred': L('прогноз выше порога', 'forecast above threshold', 'шектен жоғары болжам'),
  'legend.points.obs': L('реальный новый очаг', 'real new fire', 'нақты жаңа ошақ'),
  'legend.points.hit': L('совпадение', 'match', 'сәйкестік'),

  // ---------- cell card ----------
  'card.aria': L('Выбранная ячейка', 'Selected cell', 'Таңдалған ұяшық'),
  'card.kind': L('Выбранная ячейка', 'Selected cell', 'Таңдалған ұяшық'),
  'card.close': L('Закрыть карточку', 'Close the card', 'Карточканы жабу'),
  'card.elevation': L(({ n }) => `${n} м над морем`, ({ n }) => `${n} m above sea level`, ({ n }) => `теңіз деңгейінен ${n} м`),
  'card.hist.cat': L(({ year }) => `Детекций VIIRS\nза ${year} год`, ({ year }) => `VIIRS detections\nin ${year}`, ({ year }) => `${year} жылғы\nVIIRS анықтаулары`),
  'card.cal': L('Калиброванная\nвероятность', 'Calibrated\nprobability', 'Калибрленген\nықтималдық'),
  'card.nofc': L('Нет прогноза', 'No forecast', 'Болжам жоқ'),
  'card.demo.high': L('Высокая\nв демо-сценарии', 'High\nin the demo', 'Демода\nжоғары'),
  'card.demo.elev': L('Повышенная\nв демо-сценарии', 'Elevated\nin the demo', 'Демода\nжоғарылаған'),
  'card.demo.mod': L('Умеренная\nв демо-сценарии', 'Moderate\nin the demo', 'Демода\nорташа'),
  'card.demo.low': L('Низкая\nв демо-сценарии', 'Low\nin the demo', 'Демода\nтөмен'),
  'card.alert': L('Предупреждение\nпо выбранному порогу', 'Alert at the\nchosen threshold', 'Таңдалған шек\nбойынша ескерту'),
  'card.below': L('Ниже выбранного\nпорога', 'Below the\nchosen threshold', 'Таңдалған\nшектен төмен'),
  'card.ctx.hist': L('Номинальная и высокая уверенность; до объединения в события', 'Nominal and high confidence; before linking into events', 'Номиналды және жоғары сенімділік; оқиғаларға біріктіруге дейін'),
  'card.ctx.real': L('Первое спутниковое обнаружение за сутки; нет данных = пропуск', 'First satellite detection within 24 hours; no data means a gap', 'Тәуліктегі алғашқы спутниктік анықтау; дерек жоқ = олқылық'),
  'card.ctx.demo': L('Условная вероятность нового очага за сутки', 'Illustrative probability of a new fire in 24 hours', 'Тәуліктегі жаңа ошақтың шартты ықтималдығы'),
  'card.f.hist': L('Наблюдения по годам', 'Observations by year', 'Жылдар бойынша бақылаулар'),
  'card.f.real': L('Источник прогноза', 'Forecast source', 'Болжам көзі'),
  'card.f.demo': L('Факторы демо-сценария', 'Demo scenario factors', 'Демо-сценарий факторлары'),
  'card.disc.hist': L('Спутниковые детекции не равны числу отдельных пожаров.', 'Satellite detections are not the number of separate fires.', 'Спутниктік анықтаулар жеке өрттер санына тең емес.'),
  'card.disc.real': L('Ретроспективный результат модели. Пустые ячейки исключены или не имеют обязательных данных.', 'A retrospective model result. Empty cells are excluded or lack required data.', 'Модельдің ретроспективті нәтижесі. Бос ұяшықтар алынып тасталған немесе міндетті деректері жоқ.'),
  'card.disc.demo': L('Иллюстрация интерфейса. Значения не рассчитаны обученной моделью.', 'An interface illustration. The values are not computed by a trained model.', 'Интерфейс иллюстрациясы. Мәндерді оқытылған модель есептеген жоқ.'),
  'card.source': L(({ model, day, profile, t, inputs }) => `${model} · цель ${day} UTC. Режим: ${profile}; порог ${t}. Признаки: ${inputs}. Их вклад не следует интерпретировать как причинность.`,
    ({ model, day, t, inputs }) => `${model} · target ${day} UTC. Threshold ${t}. Inputs: ${inputs}. Their contributions are not causal explanations.`,
    ({ model, day, t, inputs }) => `${model} · мақсат ${day} UTC. Шек ${t}. Белгілер: ${inputs}. Олардың үлесін себеп-салдар деп түсіндіруге болмайды.`),
  'card.seen.yes': L(({ n }) => `Реальный новый очаг VIIRS в этой ячейке в этот день: да${n > 1 ? ` (${n})` : ''}. Метки раскрыты после оценки модели.`, ({ n }) => `A real new VIIRS fire in this cell on this day: yes${n > 1 ? ` (${n})` : ''}. Labels were opened after the model was evaluated.`, ({ n }) => `Осы күні бұл ұяшықта VIIRS нақты жаңа ошағы: иә${n > 1 ? ` (${n})` : ''}. Белгілер модель бағаланғаннан кейін ашылды.`),
  'card.seen.no': L('Нового очага VIIRS в этой ячейке в этот день не обнаружено; это не доказывает отсутствие огня.', 'No new VIIRS fire was detected in this cell on this day; that does not prove there was no fire.', 'Осы күні бұл ұяшықта VIIRS жаңа ошағы анықталмады; бұл өрттің болмағанын дәлелдемейді.'),
  'card.place': L('Посмотреть место на снимке', 'View the place on the image', 'Орынды суреттен көру'),
  'factor.dry': L('Сухость', 'Dryness', 'Құрғақтық'),
  'factor.heat': L('Тепло', 'Heat', 'Жылу'),
  'factor.wind': L('Ветер', 'Wind', 'Жел'),
  'population': L(({ n }) => `Население: ≈ ${n} чел. · WorldPop 2020. Отдельный слой экспозиции; не входит в эту модель и не оценивает ущерб.`, ({ n }) => `Population: ≈ ${n} people · WorldPop 2020. A separate exposure layer; not a model input and not a damage estimate.`, ({ n }) => `Халық: ≈ ${n} адам · WorldPop 2020. Жеке экспозиция қабаты; модельге кірмейді және залалды бағаламайды.`),
  'population.none': L('Население 2020: нет данных.', 'Population 2020: no data.', '2020 жылғы халық: дерек жоқ.'),

  // ---------- detail view ----------
  'detail.back': L('Вся карта', 'Whole map', 'Бүкіл карта'),
  'detail.source': L('Источник снимка', 'Imagery source', 'Сурет көзі'),
  'detail.sub': L(({ c }) => `${c} · ячейка 5 × 5 км обведена пунктиром`, ({ c }) => `${c} · the 5 × 5 km cell is outlined with a dashed line`, ({ c }) => `${c} · 5 × 5 км ұяшық үзік сызықпен белгіленген`),
  'detail.l.pred': L('прогноз выше порога', 'forecast above threshold', 'шектен жоғары болжам'),
  'detail.l.day': L('очаг в этот день', 'fire on this day', 'осы күнгі ошақ'),
  'detail.l.2023': L('очаги 2023', 'fires in 2023', '2023 жылғы ошақтар'),
  'detail.l.2024': L('очаги 2024', 'fires in 2024', '2024 жылғы ошақтар'),
  'detail.l.cell': L('ячейка 5 км, цвет — прогноз ≥ 0,03%', '5 km cell, colour = forecast ≥ 0.03%', '5 км ұяшық, түсі — болжам ≥ 0,03%'),
  'detail.l.past': L(' показывать прошлые очаги', ' show past fires', ' бұрынғы ошақтарды көрсету'),
  'detail.l.2026': L('очаги 2026', 'fires in 2026', '2026 жылғы ошақтар'),
  'detail.l.note': L('Ячейки и точки кликабельны. Реальные очаги открыты после оценки модели.', 'Cells and points are clickable. Real fires were opened after the model was evaluated.', 'Ұяшықтар мен нүктелерді басуға болады. Нақты ошақтар модель бағаланғаннан кейін ашылды.'),
  'detail.popup.cell': L('ячейка 5 × 5 км', '5 × 5 km cell', '5 × 5 км ұяшық'),
  'detail.popup.fc': L(({ day, v, above }) => `Прогноз на ${day}: <b>${v}</b>${above ? ' · выше порога' : ''}`, ({ day, v, above }) => `Forecast for ${day}: <b>${v}</b>${above ? ' · above threshold' : ''}`, ({ day, v, above }) => `${day} болжамы: <b>${v}</b>${above ? ' · шектен жоғары' : ''}`),
  'detail.popup.nodata': L('нет данных', 'no data', 'дерек жоқ'),
  'detail.popup.hist': L('Детекции VIIRS 2015–2022', 'VIIRS detections 2015–2022', 'VIIRS анықтаулары 2015–2022'),
  'detail.popup.events': L('Новые очаги 2023–2024 в ячейке', 'New fires in the cell, 2023–2024', 'Ұяшықтағы 2023–2024 жаңа ошақтары'),
  'detail.popup.none': L('нет', 'none', 'жоқ'),
  'detail.popup.open': L('Открыть карточку ячейки', 'Open the cell card', 'Ұяшық карточкасын ашу'),
  'detail.tip.past': L(({ date, hit }) => `Новый очаг VIIRS · ${date}${hit ? ' · было предупреждение' : ''}`, ({ date, hit }) => `New VIIRS fire · ${date}${hit ? ' · alerted' : ''}`, ({ date, hit }) => `VIIRS жаңа ошағы · ${date}${hit ? ' · ескерту болған' : ''}`),
  'detail.tip.day': L(({ hit }) => `Новый очаг VIIRS в этот день${hit ? ' · в ячейке с предупреждением' : ''}`, ({ hit }) => `New VIIRS fire on this day${hit ? ' · in an alerted cell' : ''}`, ({ hit }) => `Осы күнгі VIIRS жаңа ошағы${hit ? ' · ескертілген ұяшықта' : ''}`),
  'detail.zoomIn': L('Приблизить', 'Zoom in', 'Жақындату'),
  'detail.zoomOut': L('Отдалить', 'Zoom out', 'Алыстату'),

  // ---------- toasts ----------
  'toast.noForecastDate': L('Для этой даты прогноз не опубликован.', 'No forecast is published for this date.', 'Бұл күнге болжам жарияланбаған.'),
  'toast.demoRange': L('Для сценария выберите дату 2015–2022. Тестовые годы закрыты.', 'Pick a date in 2015–2022 for the scenario. Test years are sealed.', 'Сценарий үшін 2015–2022 аралығындағы күнді таңдаңыз. Тест жылдары жабық.'),
  'toast.noForecast': L('Для этой даты нет прогноза.', 'There is no forecast for this date.', 'Бұл күнге болжам жоқ.'),
  'toast.exported': L(({ n }) => `Экспортировано ${n} ячеек`, ({ n }) => `Exported ${n} cells`, ({ n }) => `${n} ұяшық экспортталды`),
  'toast.outside': L('Выберите ячейку внутри границы Казахстана.', 'Choose a cell inside the border of Kazakhstan.', 'Қазақстан шекарасының ішіндегі ұяшықты таңдаңыз.'),
  'toast.3dlost': L('Видеокарта сбросила 3D. Карта вернулась в 2D, нажмите 3D ещё раз.', 'The graphics card reset 3D. The map is back in 2D; press 3D again.', 'Бейнекарта 3D-ны тоқтатты. Карта 2D-ға оралды, 3D-ны қайта басыңыз.'),
  'toast.no3d': L(({ e }) => `3D недоступно: ${e}`, ({ e }) => `3D unavailable: ${e}`, ({ e }) => `3D қолжетімсіз: ${e}`),
  'toast.noDetail': L(({ e }) => `Детальный снимок недоступен: ${e}`, ({ e }) => `Detailed imagery unavailable: ${e}`, ({ e }) => `Толық сурет қолжетімсіз: ${e}`),

  // ---------- dialogs: titles ----------
  'dlg.sources': L('Реальные источники', 'Real data sources', 'Нақты дереккөздер'),
  'dlg.method': L('Методика модели', 'Model method', 'Модель әдістемесі'),
  'dlg.metrics': L('Реальные метрики', 'Real metrics', 'Нақты метрикалар'),
  'dlg.readiness': L('Текущие данные', 'Current data', 'Ағымдағы деректер'),
  'dlg.quality': L('Проверка качества', 'Quality check', 'Сапаны тексеру'),

  // ---------- dialogs: content ----------
  'inputs.upgrade': L('погода, NDVI, земной покров, рельеф, человеческая активность и предшествующая пожарная активность', 'weather, NDVI, land cover, terrain, human activity and past fire activity', 'ауа райы, NDVI, жер жамылғысы, жер бедері, адам белсенділігі және бұрынғы өрт белсенділігі'),
  'inputs.seasonal': L('земной покров и календарный месяц', 'land cover and calendar month', 'жер жамылғысы және күнтізбелік ай'),
  'inputs.weather': L('погода и предшествующие метеоусловия', 'weather and preceding weather conditions', 'ауа райы және алдыңғы метеожағдайлар'),
  'inputs.default': L('погода, NDVI, земной покров, рельеф, человеческая активность и календарный месяц', 'weather, NDVI, land cover, terrain, human activity and calendar month', 'ауа райы, NDVI, жер жамылғысы, жер бедері, адам белсенділігі және күнтізбелік ай'),
  'src.body': L(({ model, inputs, period }) => `<h2>Пять групп реальных данных.</h2><p>Модель ${model} выбрана по временной валидации на открытых данных Казахстана. Её входные признаки: ${inputs}. На карте — ретроспективные вероятности для выбранных суток ${period}.</p><div class="data-line"><span>Погода · ERA5 / Open-Meteo</span><span class="ready">0,25° · ПОЧАСОВО</span></div><div class="data-line"><span>Растительность · NOAA VIIRS NDVI</span><span class="ready">0,05° · QA</span></div><div class="data-line"><span>Земной покров · MODIS MCD12Q1</span><span class="ready">ПРЕДЫДУЩИЙ ГОД</span></div><div class="data-line"><span>Рельеф · SRTM CGIAR</span><span class="ready">90 М → 5 КМ</span></div><div class="data-line"><span>WorldPop 2010 · поселения 2013</span><span class="ready">ПОДКЛЮЧЕНЫ</span></div><p>Открытые аналоги отличаются от исходного научного протокола: ERA5 вместо ERA5-Land, NOAA NDVI вместо MOD13A2, SRTM 90 м. EVI и современные дороги не подставлялись. Архивы переобработаны позже дат наблюдений; это ограничивает выводы об оперативном прогнозировании.</p><p><a href="./assets/model-method.txt" target="_blank">Полная методика и источники ↗</a> · <a href="./assets/source-quality.txt" target="_blank">Аудит источников и загрузки ↗</a></p>`,
    ({ model, inputs, period }) => `<h2>Five groups of real data.</h2><p>The ${model} model was chosen by temporal validation on open data for Kazakhstan. Its inputs: ${inputs}. The map shows retrospective probabilities for selected days of ${period}.</p><div class="data-line"><span>Weather · ERA5 / Open-Meteo</span><span class="ready">0.25° · HOURLY</span></div><div class="data-line"><span>Vegetation · NOAA VIIRS NDVI</span><span class="ready">0.05° · QA</span></div><div class="data-line"><span>Land cover · MODIS MCD12Q1</span><span class="ready">PREVIOUS YEAR</span></div><div class="data-line"><span>Terrain · SRTM CGIAR</span><span class="ready">90 M → 5 KM</span></div><div class="data-line"><span>WorldPop 2010 · settlements 2013</span><span class="ready">CONNECTED</span></div><p>The open substitutes differ from the original research protocol: ERA5 instead of ERA5-Land, NOAA NDVI instead of MOD13A2, SRTM at 90 m. EVI and present-day roads were not substituted. The archives were reprocessed after the observation dates, which limits conclusions about operational forecasting.</p><p><a href="./assets/model-method.txt" target="_blank">Full method and sources (Russian) ↗</a> · <a href="./assets/source-quality.txt" target="_blank">Source and download audit (Russian) ↗</a></p>`,
    ({ model, inputs, period }) => `<h2>Нақты деректердің бес тобы.</h2><p>${model} моделі Қазақстанның ашық деректеріндегі уақыттық валидация бойынша таңдалды. Оның кіріс белгілері: ${inputs}. Картада ${period} жылдардың таңдалған тәуліктеріне арналған ретроспективті ықтималдықтар көрсетілген.</p><div class="data-line"><span>Ауа райы · ERA5 / Open-Meteo</span><span class="ready">0,25° · САҒАТ САЙЫН</span></div><div class="data-line"><span>Өсімдік жамылғысы · NOAA VIIRS NDVI</span><span class="ready">0,05° · QA</span></div><div class="data-line"><span>Жер жамылғысы · MODIS MCD12Q1</span><span class="ready">ӨТКЕН ЖЫЛ</span></div><div class="data-line"><span>Жер бедері · SRTM CGIAR</span><span class="ready">90 М → 5 КМ</span></div><div class="data-line"><span>WorldPop 2010 · елді мекендер 2013</span><span class="ready">ҚОСЫЛҒАН</span></div><p>Ашық баламалар бастапқы ғылыми хаттамадан өзгеше: ERA5-Land орнына ERA5, MOD13A2 орнына NOAA NDVI, 90 м SRTM. EVI мен қазіргі жолдар қосылған жоқ. Мұрағаттар бақылау күндерінен кейін қайта өңделген; бұл жедел болжау туралы қорытындыларды шектейді.</p><p><a href="./assets/model-method.txt" target="_blank">Толық әдістеме мен дереккөздер (орысша) ↗</a> · <a href="./assets/source-quality.txt" target="_blank">Дереккөздер мен жүктеу аудиті (орысша) ↗</a></p>`),
  'up.method': L(({ n, t }) => `<h2>Переобученная модель · ${n} признаков.</h2><p>Обучен новый ансамбль: исходный XGBoost и логистический второй уровень, который использует его оценку и шесть признаков предшествующей пожарной активности. Итоговая оценка смешивает два прогноза с весами 50/50 и проходит калибровку по 2022 году.</p><p>Пожарная история использует активные ячейки из прошлых спутниковых детекций в квадратных окрестностях 15 и 55 км. Окна 7, 30, 90 и 365 дней заканчиваются не позднее чем за двое суток до цели. Будущие детекции, метки целевого дня и будущие связи событий в признаки не входят.</p><p>Базовая модель обучена на 2015–2021. Второй уровень обучен на прогнозах 2019–2021, каждый из которых построен по более ранним годам. Регуляризация выбрана на 2021; вес смеси — по улучшению на 2021 и 2022. Порог выбран по 2022 при precision не ниже исходной модели на том же году. Порог ${t} зафиксирован вместе с моделью перед повторной оценкой на 2023–2024.</p><p>Тест уже публиковался ранее, поэтому это повторная оценка на прежнем наборе. Вероятности округлены в float16 перед расчётом порога и метрик; карта показывает ровно эти значения. Пропуски сохранены. Пригодность для текущего оперативного прогноза не подтверждена.</p><p><a href="./upgrade/">Обучение, сравнение, метрики и контрольные суммы ↗</a></p>`,
    ({ n, t }) => `<h2>Retrained model · ${n} inputs.</h2><p>A new ensemble was trained: the original XGBoost plus a logistic second level that uses its score and six features of past fire activity. The final score blends the two forecasts 50/50 and is calibrated on 2022.</p><p>Fire history uses active cells from past satellite detections in square neighbourhoods of 15 and 55 km. The 7, 30, 90 and 365-day windows end at least two days before the target. Future detections, target-day labels and future event links are not among the inputs.</p><p>The base model was trained on 2015–2021. The second level was trained on 2019–2021 forecasts, each built from earlier years. Regularisation was chosen on 2021; the blend weight by the gain on 2021 and 2022. The threshold was chosen on 2022 with precision no lower than the original model in the same year. The ${t} threshold was frozen with the model before the reassessment on 2023–2024.</p><p>The test had been published before, so this is a reassessment on the same set. Probabilities are rounded to float16 before the threshold and metrics are computed; the map shows exactly these values. Gaps are kept. Fitness for current operational forecasting is not confirmed.</p><p><a href="./upgrade/">Training, comparison, metrics and checksums (Russian) ↗</a></p>`,
    ({ n, t }) => `<h2>Қайта оқытылған модель · ${n} белгі.</h2><p>Жаңа ансамбль оқытылды: бастапқы XGBoost және оның бағасы мен бұрынғы өрт белсенділігінің алты белгісін пайдаланатын логистикалық екінші деңгей. Қорытынды баға екі болжамды 50/50 салмақпен араластырады және 2022 жыл бойынша калибрленеді.</p><p>Өрт тарихы 15 және 55 км шаршы маңайлардағы бұрынғы спутниктік анықтаулардың белсенді ұяшықтарын пайдаланады. 7, 30, 90 және 365 күндік терезелер мақсатты күннен кемінде екі тәулік бұрын аяқталады. Болашақ анықтаулар, мақсатты күн белгілері және болашақ оқиға байланыстары белгілерге кірмейді.</p><p>Негізгі модель 2015–2021 жылдарда оқытылды. Екінші деңгей 2019–2021 жылдардың болжамдарында оқытылды, олардың әрқайсысы ертерек жылдар бойынша құрылған. Регуляризация 2021 жылы таңдалды; араластыру салмағы — 2021 және 2022 жылдардағы жақсару бойынша. Шек 2022 жыл бойынша сол жылғы бастапқы модельден төмен емес precision шартымен таңдалды. ${t} шегі 2023–2024 жылдардағы қайта бағалаудан бұрын модельмен бірге бекітілді.</p><p>Тест бұрын жарияланған, сондықтан бұл бұрынғы жиындағы қайта бағалау. Ықтималдықтар шек пен метрикаларды есептеу алдында float16-ға дейін дөңгелектенген; карта дәл осы мәндерді көрсетеді. Олқылықтар сақталған. Ағымдағы жедел болжамға жарамдылығы расталмаған.</p><p><a href="./upgrade/">Оқыту, салыстыру, метрикалар және бақылау қосындылары (орысша) ↗</a></p>`),
  'up.original': L('Исходный XGBoost', 'Original XGBoost', 'Бастапқы XGBoost'),
  'up.features': L(({ n }) => `XGBoost · ${n} признаков`, ({ n }) => `XGBoost · ${n} inputs`, ({ n }) => `XGBoost · ${n} белгі`),
  'up.model': L('Модель', 'Model', 'Модель'),
  'up.eval': L(({ table }) => `<h2>Новая модель · оценка 2023–2024.</h2><p>Обучен новый второй уровень ансамбля и добавлена причинно упорядоченная история детекций. Порог выбран только по 2022 году с precision не ниже исходной модели на том же году; это ограничение настройки, без гарантии на иной период.</p>${table}<p>Сложность второго уровня выбрана на 2021; вес смеси проверен на 2021 и 2022. Обучение использует годы до 2022. Калибровка и порог — 2022. Все параметры зафиксированы перед этой оценкой. Данные 2023–2024 не использовались для обучения или выбора.</p><p>Это повторная оценка на ранее опубликованном тесте, а не новая независимая контрольная выборка. Сигналы обозначают первые спутниковые обнаружения новых событий в ячейках 5 × 5 км.</p><p><a href="./upgrade/">Отчёт по новой модели ↗</a> · <a href="./upgrade/metrics.csv">Метрики CSV ↗</a> · <a href="./upgrade/cluster_intervals.csv">Интервалы CSV ↗</a> · <a href="./results/">Исходное сравнение шести моделей ↗</a></p>`,
    ({ table }) => `<h2>New model · 2023–2024 evaluation.</h2><p>A new second level of the ensemble was trained and a causally ordered detection history was added. The threshold was chosen on 2022 only, with precision no lower than the original model in the same year; this constrains the tuning and guarantees nothing for another period.</p>${table}<p>The second-level complexity was chosen on 2021; the blend weight was checked on 2021 and 2022. Training uses years before 2022. Calibration and threshold: 2022. Every parameter was frozen before this evaluation. The 2023–2024 data were not used for training or selection.</p><p>This is a reassessment on a previously published test, not a new independent hold-out set. Alerts mark first satellite detections of new events in 5 × 5 km cells.</p><p><a href="./upgrade/">New model report (Russian) ↗</a> · <a href="./upgrade/metrics.csv">Metrics CSV ↗</a> · <a href="./upgrade/cluster_intervals.csv">Intervals CSV ↗</a> · <a href="./results/">Original comparison of six models (Russian) ↗</a></p>`,
    ({ table }) => `<h2>Жаңа модель · 2023–2024 бағалауы.</h2><p>Ансамбльдің жаңа екінші деңгейі оқытылып, себеп-салдар ретімен реттелген анықтаулар тарихы қосылды. Шек тек 2022 жыл бойынша сол жылғы бастапқы модельден төмен емес precision шартымен таңдалды; бұл баптаудың шектеуі, басқа кезеңге кепілдік емес.</p>${table}<p>Екінші деңгейдің күрделілігі 2021 жылы таңдалды; араластыру салмағы 2021 және 2022 жылдарда тексерілді. Оқыту 2022 жылға дейінгі жылдарды пайдаланады. Калибрлеу мен шек — 2022. Барлық параметрлер осы бағалаудан бұрын бекітілді. 2023–2024 деректері оқытуға немесе таңдауға пайдаланылған жоқ.</p><p>Бұл бұрын жарияланған тесттегі қайта бағалау, жаңа тәуелсіз бақылау іріктемесі емес. Сигналдар 5 × 5 км ұяшықтардағы жаңа оқиғалардың алғашқы спутниктік анықтауларын білдіреді.</p><p><a href="./upgrade/">Жаңа модель есебі (орысша) ↗</a> · <a href="./upgrade/metrics.csv">Метрикалар CSV ↗</a> · <a href="./upgrade/cluster_intervals.csv">Аралықтар CSV ↗</a> · <a href="./results/">Алты модельдің бастапқы салыстыруы (орысша) ↗</a></p>`),
  'ready.none': L('<h2>Текущий прогноз не подтверждён.</h2><p>Нет проверенного статуса ежедневного расчёта.</p>', '<h2>The current forecast is not confirmed.</h2><p>There is no verified status of the daily run.</p>', '<h2>Ағымдағы болжам расталмаған.</h2><p>Күнделікті есептеудің тексерілген күйі жоқ.</p>'),
  'ready.fire': L('Пожарная история: нет проверенного непрерывного архива за указанный период', 'Fire history: no verified continuous archive for this period', 'Өрт тарихы: көрсетілген кезеңге тексерілген үздіксіз мұрағат жоқ'),
  'ready.meteo': L('Погода: массивы ERA5 за текущий год ещё не загружены', 'Weather: ERA5 arrays for the current year are not downloaded yet', 'Ауа райы: ағымдағы жылдың ERA5 массивтері әлі жүктелмеген'),
  'ready.land': L('Земной покров: не загружен MODIS за предыдущий год', 'Land cover: MODIS for the previous year is not downloaded', 'Жер жамылғысы: өткен жылғы MODIS жүктелмеген'),
  'ready.veg': L('Растительность: нет проверенного NDVI допустимой давности', 'Vegetation: no verified NDVI recent enough', 'Өсімдік жамылғысы: жарамды мерзімдегі тексерілген NDVI жоқ'),
  'ready.body': L(({ day, last, checked, gaps }) => `<h2>Сегодня: прогноз не выпущен.</h2><p>Проверка для ${day}. Получены реальные текущие наблюдения SNPP; это наблюдения, а не прогноз и не метки научного теста.</p><p>Последнее наблюдение в полученном источнике: ${last}. Проверено: ${checked}. Этот статус относится только к указанной дате.</p><ul>${gaps}</ul><p>Для 365-дневного признака нельзя заменить отсутствующие дни нулевой активностью. Автоматическая публикация и оперативная проверка пока не запущены. На основной карте сохранена явно обозначенная ретроспектива 2023–2024.</p><p><a href="./assets/daily-status.json">Проверенный статус JSON ↗</a> · <a href="./quality/">Полный аудит ↗</a></p>`,
    ({ day, last, checked, gaps }) => `<h2>Today: no forecast issued.</h2><p>Check for ${day}. Real current SNPP observations were received; they are observations, not a forecast and not labels of the research test.</p><p>Latest observation in the received source: ${last}. Checked: ${checked}. This status applies to the stated date only.</p><ul>${gaps}</ul><p>Missing days cannot be replaced with zero activity for the 365-day feature. Automatic publishing and operational checks are not running yet. The main map keeps the clearly labelled 2023–2024 retrospective.</p><p><a href="./assets/daily-status.json">Verified status JSON ↗</a> · <a href="./quality/">Full audit (Russian) ↗</a></p>`,
    ({ day, last, checked, gaps }) => `<h2>Бүгін: болжам шығарылған жоқ.</h2><p>${day} күнге тексеру. SNPP нақты ағымдағы бақылаулары алынды; бұл болжам емес және ғылыми тест белгілері емес, бақылаулар.</p><p>Алынған дереккөздегі соңғы бақылау: ${last}. Тексерілді: ${checked}. Бұл күй тек көрсетілген күнге қатысты.</p><ul>${gaps}</ul><p>365 күндік белгі үшін жоқ күндерді нөлдік белсенділікпен алмастыруға болмайды. Автоматты жариялау мен жедел тексеру әлі іске қосылған жоқ. Негізгі картада 2023–2024 жылдардың анық белгіленген ретроспективасы сақталған.</p><p><a href="./assets/daily-status.json">Тексерілген күй JSON ↗</a> · <a href="./quality/">Толық аудит (орысша) ↗</a></p>`),
  'q.loading': L('<h2>Аудит загружается.</h2><p><a href="./upgrade/">Отчёт текущей модели ↗</a></p>', '<h2>Loading the audit.</h2><p><a href="./upgrade/">Current model report ↗</a></p>', '<h2>Аудит жүктелуде.</h2><p><a href="./upgrade/">Ағымдағы модель есебі ↗</a></p>'),
  'q.fresh': L(({ p, r, ap }) => `<p><strong>Новая временная проверка 2025:</strong> precision ${p}, recall ${r}, AP ${ap}. Для обучения и настройки использованы только годы до 2023. После этой проверки модель и порог не менялись.</p>`,
    ({ p, r, ap }) => `<p><strong>New temporal check on 2025:</strong> precision ${p}, recall ${r}, AP ${ap}. Only years before 2023 were used for training and tuning. The model and threshold were not changed after this check.</p>`,
    ({ p, r, ap }) => `<p><strong>2025 жылғы жаңа уақыттық тексеру:</strong> precision ${p}, recall ${r}, AP ${ap}. Оқыту мен баптауға тек 2023 жылға дейінгі жылдар пайдаланылды. Осы тексеруден кейін модель мен шек өзгертілген жоқ.</p>`),
  'q.body': L(({ fresh, rows, p, r, sp, sr, events, ra, rc, unc }) => `<h2>Качество и границы применения.</h2>${fresh}<p>Полный пересчёт ${rows} ячеек-дней 2023–2024: precision ${p}, recall ${r}. Прежняя взвешенная выборочная оценка: precision ${sp}, recall ${sr}. Это уточнение измерения, а не изменение модели. Для самостоятельного оперативного предупреждения качество не подтверждено.</p><p>Уникальные спутниковые события: ${events}. Полнота для всех событий в день первого обнаружения: ${ra}; для событий в покрытых ячейках: ${rc}. Вне допустимой области модели: ${unc} событий.</p><p>Сетка карты — 5 км; метеосетка — 0,25°, приблизительно 18–28 км по разным направлениям в Казахстане. Более мелкая отрисовка не повышает точность метеоданных. Пропуски NDVI видны в отдельном аудите; обработка пропусков не восстанавливает наблюдения.</p><p>Добавлен слой населения WorldPop 2020 для оценки экспозиции. Исторические признаки модели сохраняют исходные даты, чтобы обновление слоя не внесло утечку будущего.</p><p>Цель — первое спутниковое обнаружение; время возгорания, распространение и ущерб не оцениваются. Новый тест 2025 и пространственный аудит имеют отдельные протоколы и ограничения.</p><p><a href="./quality/">События, регионы, источники и независимая проверка ↗</a></p>`,
    ({ fresh, rows, p, r, sp, sr, events, ra, rc, unc }) => `<h2>Quality and limits of use.</h2>${fresh}<p>Full recount of ${rows} cell-days in 2023–2024: precision ${p}, recall ${r}. The earlier weighted sample estimate: precision ${sp}, recall ${sr}. This refines the measurement; the model did not change. Quality is not confirmed for stand-alone operational warnings.</p><p>Unique satellite events: ${events}. Recall for all events on the day of first detection: ${ra}; for events in covered cells: ${rc}. Outside the model's eligible area: ${unc} events.</p><p>The map grid is 5 km; the weather grid is 0.25°, roughly 18–28 km in different directions across Kazakhstan. Finer drawing does not make the weather data more precise. NDVI gaps are shown in a separate audit; gap handling does not restore observations.</p><p>A WorldPop 2020 population layer was added for exposure. The model's historical inputs keep their original dates, so the layer update does not leak the future.</p><p>The target is the first satellite detection; ignition time, spread and damage are not estimated. The new 2025 test and the spatial audit have their own protocols and limits.</p><p><a href="./quality/">Events, regions, sources and independent check (Russian) ↗</a></p>`,
    ({ fresh, rows, p, r, sp, sr, events, ra, rc, unc }) => `<h2>Сапа және қолдану шектері.</h2>${fresh}<p>2023–2024 жылдардың ${rows} ұяшық-күнін толық қайта есептеу: precision ${p}, recall ${r}. Бұрынғы салмақталған іріктемелі баға: precision ${sp}, recall ${sr}. Бұл модельді өзгерту емес, өлшеуді нақтылау. Дербес жедел ескерту үшін сапа расталмаған.</p><p>Бірегей спутниктік оқиғалар: ${events}. Алғаш анықталған күнгі барлық оқиғалар үшін толықтық: ${ra}; қамтылған ұяшықтардағы оқиғалар үшін: ${rc}. Модельдің жарамды аймағынан тыс: ${unc} оқиға.</p><p>Карта торы — 5 км; метеотор — 0,25°, Қазақстанда әр бағытта шамамен 18–28 км. Ұсақ сызу метеодеректердің дәлдігін арттырмайды. NDVI олқылықтары жеке аудитте көрсетілген; олқылықтарды өңдеу бақылауларды қалпына келтірмейді.</p><p>Экспозицияны бағалау үшін WorldPop 2020 халық қабаты қосылды. Модельдің тарихи белгілері бастапқы күндерін сақтайды, сондықтан қабатты жаңарту болашақтан ақпарат ағуына әкелмейді.</p><p>Мақсат — алғашқы спутниктік анықтау; тұтану уақыты, таралуы және залал бағаланбайды. 2025 жылғы жаңа тест пен кеңістіктік аудиттің өз хаттамалары мен шектеулері бар.</p><p><a href="./quality/">Оқиғалар, өңірлер, дереккөздер және тәуелсіз тексеру (орысша) ↗</a></p>`),
  // ---------- model v6 ----------
  'model.version': L('Версия модели', 'Model version', 'Модель нұсқасы'),
  'model.v6': L('v6 · история очагов', 'v6 · fire history', 'v6 · өрт тарихы'),
  'model.tomorrow': L('Завтра', 'Tomorrow', 'Ертең'),
  'model.v6da': L('Прогноз на завтра · v6da, выпускается накануне с 17:00', 'Tomorrow · v6da, issued the day before from 17:00', 'Ертеңгі болжам · v6da, алдыңғы күні 17:00-ден бастап шығады'),
  'model.v7': L('v7 · погода дня прогноза', 'v7 · weather of the target day', 'v7 · болжам күнінің ауа райы'),
  'inputs.v7': L('всё, что у v6, плюс вчерашние очаги (до 21:00 UTC) и прогноз погоды GFS на сам день прогноза', 'everything v6 uses, plus yesterday’s fires (to 21:00 UTC) and the GFS weather forecast for the target day', 'v6 қолданатынның бәрі, сонымен қатар кешегі ошақтар (21:00 UTC дейін) және болжам күніне GFS ауа райы болжамы'),
  'checks.metricsTest.v7': L('Метрики · разработка 2020–2025', 'Metrics · development 2020–2025', 'Метрикалар · әзірлеу 2020–2025'),
  'profile.help.v7': L('Обучение: 2015–2023. Калибровка и порог: 2024–2025 с прогнозами GFS. Точность и полнота: при пороге на 2024–2025. Решающий тест — март–октябрь 2027.', 'Training: 2015–2023. Calibration and threshold: 2024–2025 with GFS forecasts. Precision and recall: at the threshold on 2024–2025. The deciding test is March–October 2027.', 'Оқыту: 2015–2023. Калибрлеу мен шек: GFS болжамдарымен 2024–2025. Дәлдік пен толықтық: 2024–2025 жылдардағы шекте. Шешуші тест — 2027 жылғы наурыз–қазан.'),
  'legend.title.v7': L('Вероятность нового очага за сутки (v7), %', 'Chance of a new fire in 24 hours (v7), %', 'Тәулікте жаңа ошақ ықтималдығы (v7), %'),
  'legend.note.v7': L('v7 откалибрована на 2024–2025: показанное и реальное расходились не больше чем в 1,6 раза.', 'v7 is calibrated on 2024–2025: shown and observed differed by at most 1.6 times.', 'v7 2024–2025 жылдарға калибрленген: көрсетілген мен нақты 1,6 еседен артық ажырамады.'),
  'card.v7warn': L('v7 — претендент: в разработке она находила больше пожаров, чем v6, в 5 годах из 6, но не во всех. Основную модель выберет тест 2027 года.', 'v7 is the challenger: in development it found more fires than v6 in 5 of 6 years, not in all. The 2027 test chooses the default model.', 'v7 — үміткер: әзірлеуде 6 жылдың 5-інде v6-дан көп өрт тапты, бірақ бәрінде емес. Негізгі модельді 2027 жылғы тест таңдайды.'),
  'note.real.live': L('<div><strong>Модель v6 · ежедневный прогноз</strong><p>Выпущен до начала суток по данным, известным на момент выпуска, и записан в журнал с хешами. Значения ранжируют риск, это не вероятность.</p></div>', '<div><strong>Model v6 · daily forecast</strong><p>Issued before the day began from the data known at issue time, and recorded in the hashed log. Values rank risk; they are not a probability.</p></div>', '<div><strong>v6 моделі · күнделікті болжам</strong><p>Тәулік басталмай тұрып, шығару сәтіндегі деректермен шығарылды және хэштері бар журналға жазылды. Мәндер қауіпті саралайды, бұл ықтималдық емес.</p></div>'),
  'note.real.v7': L('<div><strong>Модель v7 · ежедневный прогноз, претендент</strong><p>Выпущен до начала суток вместе с v6 и записан в тот же журнал. Значения откалиброваны и близки к реальному шансу пожара. Какая модель станет основной, решит тест 2027 года.</p></div>', '<div><strong>Model v7 · daily forecast, challenger</strong><p>Issued before the day began together with v6 and recorded in the same log. Values are calibrated and close to the real chance of fire. The 2027 test decides which model becomes the default.</p></div>', '<div><strong>v7 моделі · күнделікті болжам, үміткер</strong><p>Тәулік басталмай тұрып v6-пен бірге шығарылды және сол журналға жазылды. Мәндер калибрленген, өрттің нақты мүмкіндігіне жақын. Қай модель негізгі болатынын 2027 жылғы тест шешеді.</p></div>'),
  'inputs.v6': L('погода, NDVI, земной покров, рельеф, человеческая активность, пожары по соседству и история самой ячейки', 'weather, NDVI, land cover, terrain, human activity, nearby fires and the cell’s own fire history', 'ауа райы, NDVI, жер жамылғысы, жер бедері, адам белсенділігі, маңайдағы өрттер және ұяшықтың өз өрт тарихы'),
  'checks.metricsTest.v6': L('Метрики · тест 2026', 'Metrics · 2026 test', 'Метрикалар · 2026 тест'),
  'note.real.v6': L('<div><strong>Модель v6 · ранжирование риска</strong><p>Независимый тест 2026 по меткам NASA GIBS. Значения v6 не откалиброваны: сравнивайте ячейки между собой, а не читайте значение как шанс пожара. Не оперативный прогноз.</p></div>',
    '<div><strong>Model v6 · risk ranking</strong><p>Independent 2026 test with NASA GIBS labels. v6 values are not calibrated: compare cells with each other rather than reading a value as the chance of fire. Not an operational forecast.</p></div>',
    '<div><strong>v6 моделі · қауіпті саралау</strong><p>NASA GIBS белгілері бойынша 2026 жылғы тәуелсіз тест. v6 мәндері калибрленбеген: мәнді өрт шығу мүмкіндігі ретінде оқымай, ұяшықтарды бір-бірімен салыстырыңыз. Жедел болжам емес.</p></div>'),
  'note.real.v6.cont': L('<div><strong>Модель v6 · 2023–2024 для непрерывности</strong><p>Эти годы повлияли на разработку v6, поэтому здесь они не тест. Независимая проверка — 2026 год. Значения ранжируют риск и не являются шансом пожара.</p></div>',
    '<div><strong>Model v6 · 2023–2024 for continuity</strong><p>These years informed the design of v6, so here they are not a test. The independent check is 2026. Values rank risk; they are not the chance of fire.</p></div>',
    '<div><strong>v6 моделі · 2023–2024 жалғастық үшін</strong><p>Бұл жылдар v6 әзірлеуіне әсер етті, сондықтан мұнда тест емес. Тәуелсіз тексеру — 2026 жыл. Мәндер қауіпті саралайды, өрт шығу мүмкіндігі емес.</p></div>'),
  'profile.help.v6': L('Обучение и выбор модели: до 2022. Порог: 2022. Метрики: независимый тест 2026 по меткам GIBS NRT.', 'Training and model choice: through 2022. Threshold: 2022. Metrics: independent 2026 test with GIBS NRT labels.', 'Оқыту және модельді таңдау: 2022 жылға дейін. Шек: 2022. Метрикалар: GIBS NRT белгілері бойынша 2026 жылғы тәуелсіз тест.'),
  'legend.title.v6da': L('Прогноз на завтра (v6da): риск нового очага за сутки, %', 'Tomorrow (v6da): risk of a new fire in 24 hours, %', 'Ертеңгі болжам (v6da): тәулікте жаңа ошақ қаупі, %'),
  'legend.title.v6': L('Индекс риска нового очага за сутки (v6), %', 'Risk index of a new fire in 24 hours (v6), %', 'Тәулікте жаңа ошақ қаупінің индексі (v6), %'),
  'legend.note.v6': L('Значения v6 — ранжирование: в 2026 году около порога реальная частота была в 4–6 раз выше показанной.', 'v6 values are a ranking: in 2026, near the threshold the observed rate was 4–6 times higher than shown.', 'v6 мәндері — саралау: 2026 жылы шек маңында нақты жиілік көрсетілгеннен 4–6 есе жоғары болды.'),
  'card.rank': L('Индекс риска\n(не вероятность)', 'Risk index\n(not a probability)', 'Қауіп индексі\n(ықтималдық емес)'),
  'card.v6warn': L('v6 ранжирует ячейки лучше v5, но её значения не откалиброваны на 2026: около порога реальная частота была в 4–6 раз выше показанной, а в редких ячейках выше 3% — примерно в 2,7 раза ниже. Сравнивайте ячейки между собой.',
    'v6 ranks cells better than v5, but its values were not calibrated on 2026: near the threshold the observed rate was 4–6 times higher than shown, and in the rare cells above 3% about 2.7 times lower. Compare cells with each other.',
    'v6 ұяшықтарды v5-тен жақсы саралайды, бірақ оның мәндері 2026 жылы калибрленбеген: шек маңында нақты жиілік көрсетілгеннен 4–6 есе жоғары, ал 3%-дан жоғары сирек ұяшықтарда шамамен 2,7 есе төмен болды. Ұяшықтарды бір-бірімен салыстырыңыз.'),
  'card.v6cont': L('Дата 2023–2024 показана для непрерывности: эти годы повлияли на разработку v6.', 'This 2023–2024 date is shown for continuity: these years informed the design of v6.', 'Бұл 2023–2024 күні жалғастық үшін көрсетілген: бұл жылдар v6 әзірлеуіне әсер етті.'),
  'toast.modelDay': L(({ day }) => `У этой модели нет карты на выбранную дату. Показано ${day}.`, ({ day }) => `This model has no map for the chosen date. Showing ${day}.`, ({ day }) => `Бұл модельде таңдалған күнге карта жоқ. ${day} көрсетілген.`),
  'v6.top1': L('Топ 1%', 'Top 1%', 'Үздік 1%'),
  'v6.rel.title': L('Калибровка на 2026: показанное и реальное', 'Calibration on 2026: shown and observed', '2026 жылғы калибрлеу: көрсетілген және нақты'),
  'v6.rel.bin': L('Значение v6', 'v6 value', 'v6 мәні'),
  'v6.rel.share': L('Доля ячеек-дней', 'Share of cell-days', 'Ұяшық-күн үлесі'),
  'v6.rel.pred': L('Показано, в среднем', 'Shown, mean', 'Көрсетілген, орташа'),
  'v6.rel.obs': L('Реальная частота', 'Observed rate', 'Нақты жиілік'),
  'v6.rel.pos': L('Очагов', 'Fires', 'Ошақтар'),
  'v6.method': L(({ n, t }) => `<h2>Модель v6 · ${n} признаков.</h2><p>Один XGBoost с исходными параметрами. К 26 физическим признакам v5 добавлены шесть признаков пожаров по соседству (окрестности 15 и 55 км, окна 7–365 дней) и пять признаков самой ячейки: очаги за 30 и 365 дней, дни с последнего очага, многолетняя частота очагов в этом месяце в ячейке и в окрестности 15 км.</p><p>История заканчивается не позднее чем за двое суток до цели, погода — за семь. Разработка и выбор — только 2015–2022: v6 выбрана по заранее записанному правилу (AP выше v5 и не хуже в топ 1% в каждом из 2020–2022 годов). Калибровка и порог ${t} — 2022 год.</p><p>Финальная проверка — независимый 2026 год с метками NASA GIBS S-NPP NRT; модель и порог после неё не менялись. Даты 2023–2024 на карте показаны для непрерывности: аудит этих лет повлиял на разработку v6.</p><p><a href="./reports/model.html">Полный отчёт «Модель» ↗</a></p>`,
    ({ n, t }) => `<h2>Model v6 · ${n} inputs.</h2><p>A single XGBoost with the original parameters. To the 26 physical inputs of v5 it adds six features of nearby fires (15 and 55 km neighbourhoods, 7–365 day windows) and five features of the cell itself: fires in the last 30 and 365 days, days since the last fire, and the long-term fire rate in this month for the cell and its 15 km neighbourhood.</p><p>History ends at least two days before the target, weather seven. Development and choice used 2015–2022 only: v6 was picked by a rule written in advance (AP above v5 and no worse top-1% capture in each of 2020–2022). Calibration and the threshold ${t}: 2022.</p><p>The final check is the independent year 2026 with NASA GIBS S-NPP NRT labels; the model and threshold were not changed after it. The 2023–2024 dates on the map are shown for continuity: an audit of those years informed the design of v6.</p><p><a href="./reports/model.html">Full “Model” report ↗</a></p>`,
    ({ n, t }) => `<h2>v6 моделі · ${n} белгі.</h2><p>Бастапқы параметрлері бар бір XGBoost. v5-тің 26 физикалық белгісіне маңайдағы өрттердің алты белгісі (15 және 55 км маңай, 7–365 күндік терезелер) және ұяшықтың өзінің бес белгісі қосылды: соңғы 30 және 365 күндегі ошақтар, соңғы ошақтан бергі күндер, осы айдағы ұяшық пен оның 15 км маңайындағы көпжылдық ошақ жиілігі.</p><p>Тарих мақсаттан кемінде екі тәулік бұрын, ауа райы жеті тәулік бұрын аяқталады. Әзірлеу мен таңдау тек 2015–2022 жылдарда: v6 алдын ала жазылған ереже бойынша таңдалды (2020–2022 жылдардың әрқайсысында AP v5-тен жоғары және үздік 1%-да кем емес). Калибрлеу және ${t} шегі — 2022 жыл.</p><p>Соңғы тексеру — NASA GIBS S-NPP NRT белгілері бар тәуелсіз 2026 жыл; одан кейін модель мен шек өзгертілген жоқ. Картадағы 2023–2024 күндері жалғастық үшін көрсетілген: сол жылдардың аудиті v6 әзірлеуіне әсер етті.</p><p><a href="./reports/model.html">«Модель» толық есебі ↗</a></p>`),
  'v7.method': L(
    ({ n, t }) => `<h2>Модель v7 · ${n} признаков.</h2><p>Те же входы, что у v6, плюс вчерашние очаги до 21:00 UTC и прогноз погоды GFS (выпуск 18 UTC накануне) на сам день прогноза: температура, влажность, ветер, осадки, дефицит влажности.</p><p>Обучение на 2015–2023 по реанализу ERA5, калибровка isotonic на 2024–2025 с настоящими прогнозами GFS, оба года с равным весом. Порог тревоги ${t}. Модель заморожена 29.10.2026 до любого использования меток 2026–2027 годов.</p>`,
    ({ n, t }) => `<h2>Model v7 · ${n} inputs.</h2><p>The inputs of v6, plus yesterday’s fires to 21:00 UTC and the GFS weather forecast (the 18 UTC run of the day before) for the target day itself: temperature, humidity, wind, precipitation, vapour pressure deficit.</p><p>Trained on 2015–2023 with ERA5 reanalysis, isotonic calibration on 2024–2025 with real GFS forecasts, both years weighted equally. Alert threshold ${t}. Frozen on 29.10.2026, before any 2026–2027 label was used for it.</p>`,
    ({ n, t }) => `<h2>v7 моделі · ${n} белгі.</h2><p>v6 кірістері, сонымен қатар 21:00 UTC дейінгі кешегі ошақтар және болжам күнінің өзіне GFS ауа райы болжамы (алдыңғы күнгі 18 UTC шығарылымы): температура, ылғалдылық, жел, жауын-шашын, ылғал тапшылығы.</p><p>ERA5 реанализімен 2015–2023 жылдарға оқытылды, нақты GFS болжамдарымен 2024–2025 жылдарға isotonic калибрленді, екі жылдың салмағы тең. Дабыл шегі ${t}. 29.10.2026 2026–2027 белгілері қолданылмай тұрып бекітілді.</p>`),
  'v7.eval': L(
    ({ table, days, onTime, missed, hash }) => `<h2>Модель v7 · проверка на шести годах.</h2><p>Каждый год оценивался моделью, обученной только на более ранних годах. 2024 и 2025 — с настоящими прогнозами GFS, как в работе.</p><div class="metrics-scroll"><table class="metrics-table"><thead><tr><th>Год</th><th>AP v6</th><th>AP v7</th><th>Разница AP, 95%</th><th>Найдено при точности v6</th><th>Brier skill v7</th></tr></thead><tbody>${table}</tbody></table></div><p>Правило выпуска требовало выигрыша в каждом году; в 2023 и 2024 v7 хуже по AP, поэтому основной на карте остаётся v6. Ежедневных прогнозов выпущено: ${days}. Тест 2027 года: вовремя ${onTime}, пропущено ${missed}.</p><p>Статус: претендент. <code>${hash}</code></p>`,
    ({ table, days, onTime, missed, hash }) => `<h2>Model v7 · checked on six years.</h2><p>Each year was scored by a model trained on earlier years only. 2024 and 2025 use real GFS forecasts, as in operation.</p><div class="metrics-scroll"><table class="metrics-table"><thead><tr><th>Year</th><th>AP v6</th><th>AP v7</th><th>AP difference, 95%</th><th>Found at v6 precision</th><th>Brier skill v7</th></tr></thead><tbody>${table}</tbody></table></div><p>The release rule required a win in every year; in 2023 and 2024 v7 has lower AP, so v6 stays the map default. Daily forecasts issued: ${days}. 2027 test: on time ${onTime}, missed ${missed}.</p><p>Status: challenger. <code>${hash}</code></p>`,
    ({ table, days, onTime, missed, hash }) => `<h2>v7 моделі · алты жылда тексеру.</h2><p>Әр жыл тек ертерек жылдарға оқытылған модельмен бағаланды. 2024 және 2025 — жұмыстағыдай нақты GFS болжамдарымен.</p><div class="metrics-scroll"><table class="metrics-table"><thead><tr><th>Жыл</th><th>AP v6</th><th>AP v7</th><th>AP айырмасы, 95%</th><th>v6 дәлдігінде табылғаны</th><th>Brier skill v7</th></tr></thead><tbody>${table}</tbody></table></div><p>Шығару ережесі әр жылда жеңісті талап етті; 2023 және 2024 жылдары v7 AP бойынша нашар, сондықтан картада негізгі v6 қалады. Шығарылған күнделікті болжамдар: ${days}. 2027 тест: уақытында ${onTime}, өткізілген ${missed}.</p><p>Мәртебесі: үміткер. <code>${hash}</code></p>`),
  'v6.eval': L(({ table, reliability, rows, pos, r0, r1, p0, p1, hash }) => `<h2>Модель v6 · независимый тест 2026.</h2><p>${rows} ячеек-дней выборки, ${pos} первых обнаружений. Метки — NASA GIBS S-NPP NRT; дни с пропусками архива исключены заранее. v6 и v5 оценены на одной и той же выборке.</p>${table}<p>Парная разность v6 − v5, 95% блочный интервал: recall от +${r0} до +${r1}, precision от ${p0} до +${p1}. v6 находит заметно больше очагов при сопоставимой точности.</p>${reliability}<p><strong>Ограничение.</strong> Значения v6 на 2026 году не откалиброваны (Brier skill −0,062 против +0,009 у v5): около порога реальная частота в 4–6 раз выше показанной, в редких ячейках выше 3% — ниже. Используйте v6 для ранжирования ячеек, а значение — как относительный индекс риска. Перекалибровка на данных теста не делалась, чтобы тест оставался честным.</p><p>Статус: ретроспективный эксперимент. <code>${hash}</code></p>`,
    ({ table, reliability, rows, pos, r0, r1, p0, p1, hash }) => `<h2>Model v6 · independent 2026 test.</h2><p>${rows} sampled cell-days, ${pos} first detections. Labels are NASA GIBS S-NPP NRT; days with archive gaps were excluded in advance. v6 and v5 were scored on the same sample.</p>${table}<p>Paired difference v6 − v5, 95% block interval: recall +${r0} to +${r1}, precision ${p0} to +${p1}. v6 finds clearly more fires at comparable precision.</p>${reliability}<p><strong>Limitation.</strong> v6 values were not calibrated on 2026 (Brier skill −0.062 against +0.009 for v5): near the threshold the observed rate is 4–6 times higher than shown, and lower in the rare cells above 3%. Use v6 to rank cells and read a value as a relative risk index. No recalibration was done on the test data, so that the test stays fair.</p><p>Status: retrospective experiment. <code>${hash}</code></p>`,
    ({ table, reliability, rows, pos, r0, r1, p0, p1, hash }) => `<h2>v6 моделі · 2026 жылғы тәуелсіз тест.</h2><p>Іріктемеде ${rows} ұяшық-күн, ${pos} алғашқы анықтау. Белгілер — NASA GIBS S-NPP NRT; мұрағатта олқылығы бар күндер алдын ала алынып тасталды. v6 пен v5 бір іріктемеде бағаланды.</p>${table}<p>v6 − v5 жұптық айырмасы, 95% блоктық интервал: recall +${r0}-дан +${r1}-ға дейін, precision ${p0}-дан +${p1}-ға дейін. v6 салыстырмалы дәлдікпен әлдеқайда көп ошақ табады.</p>${reliability}<p><strong>Шектеу.</strong> v6 мәндері 2026 жылы калибрленбеген (Brier skill −0,062, v5-те +0,009): шек маңында нақты жиілік көрсетілгеннен 4–6 есе жоғары, 3%-дан жоғары сирек ұяшықтарда төмен. v6-ны ұяшықтарды саралау үшін қолданып, мәнді салыстырмалы қауіп индексі ретінде оқыңыз. Тест әділ болуы үшін тест деректерінде қайта калибрлеу жасалған жоқ.</p><p>Мәртебе: ретроспективті эксперимент. <code>${hash}</code></p>`),
  'heat.hide': L('Скрыть постоянные тепловые источники', 'Hide persistent heat sources', 'Тұрақты жылу көздерін жасыру'),
  'heat.help': L('Ячейки, где VIIRS видел тепло каждый год 2015–2022 не меньше 20 раз: заводы, факелы. Обе модели дают им очень высокие значения.', 'Cells where VIIRS saw heat at least 20 times in every year 2015–2022: plants and gas flares. Both models give them very high values.', 'VIIRS 2015–2022 жылдардың әрқайсысында кемінде 20 рет жылу көрген ұяшықтар: зауыттар, алау. Екі модель де оларға өте жоғары мән береді.'),
  'card.heat': L('Постоянный\nтепловой источник', 'Persistent\nheat source', 'Тұрақты\nжылу көзі'),
  'card.heat.note': L(({ n }) => `VIIRS фиксировал тепло в этой ячейке каждый год 2015–2022, не меньше ${n} раз за год. Это, скорее всего, завод или газовый факел, а не природный пожар. Значение модели показано для справки; на карте ячейка скрыта, её можно показать переключателем в панели.`,
    ({ n }) => `VIIRS recorded heat in this cell in every year 2015–2022, at least ${n} times a year. It is most likely a plant or a gas flare, not a wildfire. The model value is shown for reference; the cell is hidden on the map and can be shown with the switch in the panel.`,
    ({ n }) => `VIIRS бұл ұяшықта 2015–2022 жылдардың әрқайсысында жылына кемінде ${n} рет жылу тіркеді. Бұл табиғи өрт емес, зауыт немесе газ алауы болуы ықтимал. Модель мәні анықтама үшін көрсетілген; картада ұяшық жасырылған, оны панельдегі ауыстырғышпен көрсетуге болады.`),
};
