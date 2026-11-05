// Telegram bot for Wildfire KZ · Steppe: texts, keyboards and alert formatting.
// Pure functions only; worker.js does the I/O. Languages: ru (default), kk, en.

export const LANGS = ['ru', 'kk', 'en'];
export const RADII = [25, 50, 100];
const LAND = { 'лес': '🌲', 'степь': '🌾', 'кустарник': '🌿', 'пашня': '🚜', 'прочее': '▫️' };
const LAND_NAME = {
  ru: { 'лес': 'лес', 'степь': 'степь', 'кустарник': 'кустарник', 'пашня': 'пашня', 'прочее': 'прочее' },
  kk: { 'лес': 'орман', 'степь': 'дала', 'кустарник': 'бұта', 'пашня': 'егістік', 'прочее': 'басқа' },
  en: { 'лес': 'forest', 'степь': 'steppe', 'кустарник': 'shrubland', 'пашня': 'cropland', 'прочее': 'other' },
};
const MAX_ROWS = 10;
const NEAR_KM = 50;

export const T = {
  ru: {
    welcome: (name) => `Здравствуйте${name ? ', ' + name : ''}! Я присылаю ежедневный прогноз пожарной опасности по Казахстану на следующие сутки.\n\nВыберите области, по которым хотите получать тревоги, и нажмите «Готово». Или отправьте геолокацию 📍 — буду следить за тревогами рядом с вами.`,
    choose: 'Отметьте области (можно несколько):',
    all: 'Все области', done: '✅ Готово',
    saved: (n) => `Подписка сохранена: ${n}. Прогноз на завтра приходит каждый вечер, обычно в 17:00–20:00 по Казахстану; утром он уточняется.`,
    allRegions: 'все области', noRegions: 'Сначала выберите области (🗺 Области) или отправьте геолокацию (📍 Рядом со мной).',
    header: (day) => `🔥 <b>Прогноз пожарной опасности на ${day}</b>`,
    count: (n, total) => `Тревог в ваших областях: <b>${n}</b> (по Казахстану: ${total}).`,
    regionCount: (name, n) => `${name}: тревог <b>${n}</b>.`,
    none: '✅ В ваших областях тревог нет.',
    noneRegion: (name) => `✅ ${name}: тревог нет.`,
    more: (n) => `…и ещё ${n}. Все тревоги — на карте.`,
    chance: 'шанс',
    legend: '🔴 тревога v7, самой точной модели · 🟠 тревога только v6',
    legendAhead: '🟠 тревога модели прогноза на завтра (v6da)',
    byModel: (s) => `По моделям: ${s}`,
    aiHow: '💬 Напишите вопрос обычным сообщением, например: «Где сегодня самый высокий риск?» или «Сколько тревог в Костанайской области?»',
    aiOff: 'ИИ-ассистент сейчас недоступен. Используйте кнопки внизу или /help.',
    aiLimit: (n) => `На сегодня лимит вопросов исчерпан (${n}). Завтра можно снова.`,
    aiError: 'Не удалось получить ответ ассистента. Попробуйте ещё раз через минуту или используйте /today.',
    aiNote: '🤖 Ответ ИИ-ассистента по данным сервиса Steppe.',
    crop: '🚜 На пашне тревога чаще всего означает плановый пал, а не природный пожар.',
    cropHidden: (n) => `🚜 Скрыто палов на пашне: ${n} (настройки).`,
    warn: '⚠️ Часть входных данных сегодня неполная, прогноз может быть менее точным.',
    map: '🗺 Открыть карту',
    noData: 'Прогноз ещё не выпущен. Прогноз на завтра появляется вечером, обычно в 17:00–20:00 по Казахстану.',
    ahead: 'Прогноз на завтра: выпущен накануне вечером, утром он уточняется.',
    refined: 'Утреннее уточнение: модели v6 и v7 на свежих данных.',
    near: (r, n) => `📍 <b>Рядом с вами</b> (до ${r} км): тревог <b>${n}</b>.`,
    nearNone: (r) => `📍 Рядом с вами (до ${r} км) тревог нет.`,
    km: 'км',
    homeAsk: 'Присылать каждый вечер тревоги на завтра рядом с этой точкой? Выберите радиус:',
    homeSaved: (r) => `📍 Точка сохранена, радиус ${r} км. Каждый вечер пришлю тревоги на завтра рядом с ней.`,
    homeOff: 'Не следить', homeRemoved: 'Точка удалена.',
    kz: (day, total) => `🇰🇿 <b>Казахстан, ${day}</b>\nВсего тревог: <b>${total}</b>`,
    trend: (d) => (d > 0 ? ` ↑${d}` : d < 0 ? ` ↓${-d}` : ''),
    top: 'Самые высокие:',
    about: 'ℹ️ <b>Что это</b>\nКаждую ночь модель машинного обучения оценивает для каждой клетки 5×5 км вероятность, что завтра спутник увидит там новый очаг огня. Данные: спутники NASA, погода ERA5 и GFS, растительность, рельеф, история пожаров.\n\n<b>Точность.</b> Прогноз показывает, где риск выше всего, но не предсказывает конкретный пожар: из 100 клеток с тревогой горят около 7, в зону тревоги попадает около 10–15% новых очагов — это в десятки раз лучше случайного выбора. Это не официальное предупреждение МЧС.\n\n🚒 При пожаре звоните 112.',
    settings: (s) => `⚙️ <b>Настройки</b>\nВечерняя рассылка: ${s.push ? 'вкл' : 'выкл'}\nПисать, если тревог нет: ${s.quiet ? 'нет' : 'да'}\nПалы на пашне: ${s.crop ? 'показывать' : 'скрывать'}\nТочка: ${s.home ? `есть, ${s.radius} км` : 'нет'}\nЯзык: ${s.lang}`,
    pushOn: '🔔 Рассылка: вкл', pushOff: '🔕 Рассылка: выкл', quietOn: 'Без тревог — не писать', quietOff: 'Без тревог — писать',
    cropOn: '🚜 Палы: показывать', cropOff: '🚜 Палы: скрывать',
    stopped: 'Подписка удалена, данные о вас стёрты. Вернуться: /start',
    help: 'Кнопки внизу:\n💬 Любой вопрос текстом — ответит ИИ-ассистент по данным сервиса\n🔥 Прогноз — по вашим областям и точке\n📍 Рядом со мной — тревоги рядом\n🇰🇿 Весь Казахстан — сводка по областям\n🗺 Области — подписка\n⚙️ Настройки — рассылка, палы, язык\n\nНапишите название области (например, «Костанай») — покажу прогноз по ней.\n/about — что это и насколько точно · /stop — отписаться',
    unknown: 'Не понял. Нажмите кнопку внизу или напишите название области. /help — подсказка.',
    menu: ['🔥 Прогноз', '📍 Рядом со мной', '🇰🇿 Весь Казахстан', '🗺 Области', '⚙️ Настройки'],
  },
  kk: {
    welcome: (name) => `Сәлеметсіз бе${name ? ', ' + name : ''}! Мен Қазақстан бойынша келесі тәулікке өрт қаупінің күнделікті болжамын жіберемін.\n\nДабылдарын алғыңыз келетін облыстарды таңдап, «Дайын» басыңыз. Немесе геолокация жіберіңіз 📍 — жаныңыздағы дабылдарды бақылаймын.`,
    choose: 'Облыстарды белгілеңіз (бірнешеуін де):',
    all: 'Барлық облыстар', done: '✅ Дайын',
    saved: (n) => `Жазылым сақталды: ${n}. Ертеңгі болжам күн сайын кешке, әдетте Қазақстан уақытымен 17:00–20:00 аралығында келеді; таңертең нақтыланады.`,
    allRegions: 'барлық облыстар', noRegions: 'Алдымен облыстарды таңдаңыз (🗺 Облыстар) немесе геолокация жіберіңіз (📍 Жанымда).',
    header: (day) => `🔥 <b>${day} күнгі өрт қаупінің болжамы</b>`,
    count: (n, total) => `Сіздің облыстардағы дабылдар: <b>${n}</b> (Қазақстан бойынша: ${total}).`,
    regionCount: (name, n) => `${name}: дабылдар <b>${n}</b>.`,
    none: '✅ Сіздің облыстарда дабыл жоқ.',
    noneRegion: (name) => `✅ ${name}: дабыл жоқ.`,
    more: (n) => `…тағы ${n}. Барлық дабылдар — картада.`,
    chance: 'мүмкіндік',
    legend: '🔴 v7 дабылы, ең дәл модель · 🟠 тек v6 дабылы',
    legendAhead: '🟠 ертеңгі болжам моделінің дабылы (v6da)',
    byModel: (s) => `Модельдер бойынша: ${s}`,
    aiHow: '💬 Сұрағыңызды кәдімгі хабарламамен жазыңыз, мысалы: «Бүгін қауіп қай жерде ең жоғары?»',
    aiOff: 'ЖИ-көмекші қазір қолжетімсіз. Төмендегі батырмаларды немесе /help пайдаланыңыз.',
    aiLimit: (n) => `Бүгінгі сұрақ лимиті таусылды (${n}). Ертең қайта болады.`,
    aiError: 'Көмекшінің жауабы алынбады. Бір минуттан кейін қайталаңыз немесе /today пайдаланыңыз.',
    aiNote: '🤖 Steppe деректері бойынша ЖИ-көмекшінің жауабы.',
    crop: '🚜 Егістіктегі дабыл көбіне табиғи өрт емес, жоспарлы өртеуді білдіреді.',
    cropHidden: (n) => `🚜 Жасырылған егістік өртеулері: ${n} (баптаулар).`,
    warn: '⚠️ Бүгін кіріс деректердің бір бөлігі толық емес, болжам дәлдігі төмен болуы мүмкін.',
    map: '🗺 Картаны ашу',
    noData: 'Болжам әлі шықпады. Ертеңгі болжам кешке, әдетте Қазақстан уақытымен 17:00–20:00 аралығында шығады.',
    ahead: 'Ертеңгі болжам: алдыңғы күні кешке шықты, таңертең нақтыланады.',
    refined: 'Таңғы нақтылау: v6 және v7 модельдері жаңа деректермен.',
    near: (r, n) => `📍 <b>Жаныңызда</b> (${r} км дейін): дабылдар <b>${n}</b>.`,
    nearNone: (r) => `📍 Жаныңызда (${r} км дейін) дабыл жоқ.`,
    km: 'км',
    homeAsk: 'Осы нүктенің жанындағы ертеңгі дабылдарды күн сайын кешке жіберейін бе? Радиусты таңдаңыз:',
    homeSaved: (r) => `📍 Нүкте сақталды, радиус ${r} км. Күн сайын кешке ертеңгі жақын дабылдарды жіберемін.`,
    homeOff: 'Бақыламау', homeRemoved: 'Нүкте жойылды.',
    kz: (day, total) => `🇰🇿 <b>Қазақстан, ${day}</b>\nБарлық дабылдар: <b>${total}</b>`,
    trend: (d) => (d > 0 ? ` ↑${d}` : d < 0 ? ` ↓${-d}` : ''),
    top: 'Ең жоғарылары:',
    about: 'ℹ️ <b>Бұл не</b>\nМашиналық оқыту моделі әр түні 5×5 км әр ұяшық үшін ертең спутник жаңа өрт ошағын көру ықтималдығын бағалайды. Деректер: NASA спутниктері, ERA5 және GFS ауа райы, өсімдік, жер бедері, өрт тарихы.\n\n<b>Дәлдік.</b> Болжам қауіп қай жерде жоғары екенін көрсетеді, бірақ нақты өртті болжамайды: дабылы бар 100 ұяшықтың шамамен 7-еуі жанады. Бұл ТЖМ-нің ресми ескертуі емес.\n\n🚒 Өрт кезінде 112-ге қоңырау шалыңыз.',
    settings: (s) => `⚙️ <b>Баптаулар</b>\nКешкі тарату: ${s.push ? 'қосулы' : 'өшірулі'}\nДабыл болмаса жазу: ${s.quiet ? 'жоқ' : 'иә'}\nЕгістік өртеулері: ${s.crop ? 'көрсету' : 'жасыру'}\nНүкте: ${s.home ? `бар, ${s.radius} км` : 'жоқ'}\nТіл: ${s.lang}`,
    pushOn: '🔔 Тарату: қосулы', pushOff: '🔕 Тарату: өшірулі', quietOn: 'Дабылсыз — жазбау', quietOff: 'Дабылсыз — жазу',
    cropOn: '🚜 Өртеулер: көрсету', cropOff: '🚜 Өртеулер: жасыру',
    stopped: 'Жазылым жойылды, сіз туралы деректер өшірілді. Қайту: /start',
    help: 'Төмендегі батырмалар:\n💬 Кез келген сұрақ мәтінмен — сервис деректері бойынша ЖИ-көмекші жауап береді\n🔥 Болжам — облыстарыңыз бен нүктеңіз бойынша\n📍 Жанымда — жақын дабылдар\n🇰🇿 Бүкіл Қазақстан — облыстар бойынша шолу\n🗺 Облыстар — жазылым\n⚙️ Баптаулар — тарату, өртеулер, тіл\n\nОблыс атын жазыңыз (мысалы, «Қостанай») — сол бойынша болжамды көрсетемін.\n/about — бұл не · /stop — жазылымнан шығу',
    unknown: 'Түсінбедім. Төмендегі батырманы басыңыз немесе облыс атын жазыңыз. /help — көмек.',
    menu: ['🔥 Болжам', '📍 Жанымда', '🇰🇿 Бүкіл Қазақстан', '🗺 Облыстар', '⚙️ Баптаулар'],
  },
  en: {
    welcome: (name) => `Hello${name ? ', ' + name : ''}! I send a daily next-day fire danger forecast for Kazakhstan.\n\nChoose the regions you want alerts for and press “Done”. Or send your location 📍 and I will watch for alerts near you.`,
    choose: 'Tick the regions (several allowed):',
    all: 'All regions', done: '✅ Done',
    saved: (n) => `Subscription saved: ${n}. Tomorrow’s forecast arrives every evening, usually 17:00–20:00 Kazakhstan time, and is refined in the morning.`,
    allRegions: 'all regions', noRegions: 'Choose regions first (🗺 Regions) or send your location (📍 Near me).',
    header: (day) => `🔥 <b>Fire danger forecast for ${day}</b>`,
    count: (n, total) => `Alerts in your regions: <b>${n}</b> (all Kazakhstan: ${total}).`,
    regionCount: (name, n) => `${name}: <b>${n}</b> alerts.`,
    none: '✅ No alerts in your regions.',
    noneRegion: (name) => `✅ ${name}: no alerts.`,
    more: (n) => `…and ${n} more. All alerts are on the map.`,
    chance: 'chance',
    legend: '🔴 alert of v7, the most accurate model · 🟠 alert of v6 only',
    legendAhead: '🟠 alert of tomorrow’s model (v6da)',
    byModel: (s) => `By model: ${s}`,
    aiHow: '💬 Type your question as a normal message, e.g. “Where is the risk highest today?”',
    aiOff: 'The AI assistant is not available now. Use the buttons below or /help.',
    aiLimit: (n) => `Today’s question limit is used up (${n}). Try again tomorrow.`,
    aiError: 'The assistant did not answer. Try again in a minute or use /today.',
    aiNote: '🤖 AI assistant answer from Steppe’s data.',
    crop: '🚜 On cropland an alert usually means a planned burn, not a wildfire.',
    cropHidden: (n) => `🚜 Cropland burns hidden: ${n} (settings).`,
    warn: '⚠️ Some inputs are incomplete today; the forecast may be less accurate.',
    map: '🗺 Open the map',
    noData: 'The forecast is not issued yet. Tomorrow’s forecast appears in the evening, usually 17:00–20:00 Kazakhstan time.',
    ahead: 'Tomorrow’s forecast: issued the evening before, refined in the morning.',
    refined: 'Morning update: models v6 and v7 on the latest data.',
    near: (r, n) => `📍 <b>Near you</b> (within ${r} km): <b>${n}</b> alerts.`,
    nearNone: (r) => `📍 No alerts near you (within ${r} km).`,
    km: 'km',
    homeAsk: 'Send tomorrow’s alerts near this point every evening? Choose a radius:',
    homeSaved: (r) => `📍 Point saved, radius ${r} km. Every evening I will send tomorrow’s alerts near it.`,
    homeOff: 'Do not watch', homeRemoved: 'Point removed.',
    kz: (day, total) => `🇰🇿 <b>Kazakhstan, ${day}</b>\nAlerts: <b>${total}</b>`,
    trend: (d) => (d > 0 ? ` ↑${d}` : d < 0 ? ` ↓${-d}` : ''),
    top: 'Highest:',
    about: 'ℹ️ <b>What this is</b>\nEvery night a machine-learning model estimates, for each 5×5 km cell, the chance that a satellite sees a new fire there tomorrow. Data: NASA satellites, ERA5 and GFS weather, vegetation, terrain, fire history.\n\n<b>Accuracy.</b> The forecast shows where risk is highest but does not predict a specific fire: about 7 of 100 cells on alert burn. It is not an official emergency warning.\n\n🚒 In case of fire call 112.',
    settings: (s) => `⚙️ <b>Settings</b>\nEvening digest: ${s.push ? 'on' : 'off'}\nMessage when there are no alerts: ${s.quiet ? 'no' : 'yes'}\nCropland burns: ${s.crop ? 'show' : 'hide'}\nPoint: ${s.home ? `set, ${s.radius} km` : 'none'}\nLanguage: ${s.lang}`,
    pushOn: '🔔 Summary: on', pushOff: '🔕 Summary: off', quietOn: 'No alerts — stay silent', quietOff: 'No alerts — tell me',
    cropOn: '🚜 Burns: show', cropOff: '🚜 Burns: hide',
    stopped: 'Unsubscribed; your data is deleted. Come back: /start',
    help: 'Buttons below:\n💬 Any question as text — the AI assistant answers from the service’s data\n🔥 Forecast — your regions and point\n📍 Near me — alerts nearby\n🇰🇿 All Kazakhstan — summary by region\n🗺 Regions — subscription\n⚙️ Settings — summary, burns, language\n\nType a region name (e.g. “Kostanay”) to see its forecast.\n/about — what this is · /stop — unsubscribe',
    unknown: 'Not understood. Press a button below or type a region name. /help — hints.',
    menu: ['🔥 Forecast', '📍 Near me', '🇰🇿 All Kazakhstan', '🗺 Regions', '⚙️ Settings'],
  },
};

export const langOf = (code) => (LANGS.includes((code || '').slice(0, 2)) ? code.slice(0, 2) : 'ru');
export const escape = (s) => String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);
// v2: a daily message by default ("no alerts in your regions" is news too). Subscribers saved
// before v2 never chose silence, quiet: true was the old default, so they are moved to v2.
export const defaults = (lang) => ({ lang, regions: [], push: true, quiet: false, crop: true, home: null, radius: 50, v: 2 });
// Applied to the saved settings before the defaults are merged in.
export const migrate = (saved) => (saved.v >= 2 ? saved : { ...saved, quiet: false, v: 2 });

export function command(text) {
  const m = /^\/([a-z_]+)(@\w+)?(?:\s+(.*))?$/i.exec((text || '').trim());
  return m ? { name: m[1].toLowerCase(), arg: (m[3] || '').trim() } : null;
}

// A tap on the menu keyboard, in any language, as a command name.
const MENU_ACTIONS = ['today', 'near', 'kz', 'regions', 'settings'];
export function menuAction(text) {
  for (const lang of LANGS) {
    const i = T[lang].menu.indexOf((text || '').trim());
    if (i >= 0) return MENU_ACTIONS[i];
  }
  return null;
}

export function menuKeyboard(lang) {
  const m = T[lang].menu;
  return {
    keyboard: [[{ text: m[0] }, { text: m[1], request_location: true }], [{ text: m[2] }, { text: m[3] }, { text: m[4] }]],
    resize_keyboard: true, is_persistent: true,
  };
}

// A region typed by name, in any language, matched on its first letters.
export function findRegion(bulletin, text) {
  const q = (text || '').trim().toLowerCase().replace(/ё/g, 'е');
  if (q.length < 3) return -1;
  return bulletin.regions.findIndex((r) => LANGS.some((l) => (r[l] || '').toLowerCase().replace(/ё/g, 'е').startsWith(q.slice(0, Math.max(4, Math.min(q.length, 6))))));
}

export function regionKeyboard(bulletin, sub) {
  const t = T[sub.lang];
  const names = bulletin.regions.map((r, i) => ({ i, name: r[sub.lang] || r.ru }));
  names.sort((a, b) => a.name.localeCompare(b.name, sub.lang === 'en' ? 'en' : 'ru'));
  const rows = [];
  for (let k = 0; k < names.length; k += 2) {
    rows.push(names.slice(k, k + 2).map(({ i, name }) => ({
      text: (sub.regions.includes(i) ? '✅ ' : '') + name, callback_data: `r:${i}`,
    })));
  }
  rows.push([{ text: (sub.regions.length === bulletin.regions.length ? '✅ ' : '') + t.all, callback_data: 'r:all' }]);
  rows.push([{ text: t.done, callback_data: 'r:done' }]);
  return { inline_keyboard: rows };
}

export function toggleRegion(sub, data, total) {
  const regions = new Set(sub.regions);
  if (data === 'all') return { ...sub, regions: regions.size === total ? [] : [...Array(total).keys()] };
  const i = Number(data);
  if (Number.isInteger(i) && i >= 0 && i < total) regions.has(i) ? regions.delete(i) : regions.add(i);
  return { ...sub, regions: [...regions].sort((a, b) => a - b) };
}

export function regionList(bulletin, sub) {
  const t = T[sub.lang];
  if (sub.regions.length === bulletin.regions.length) return t.allRegions;
  return sub.regions.map((i) => bulletin.regions[i]?.[sub.lang] || '?').join(', ');
}

const pct = (p) => (p * 100).toLocaleString('ru-RU', { maximumFractionDigits: p >= 0.01 ? 1 : 2 }) + '%';
const dayText = (iso, lang) => {
  const d = new Date(iso + 'T00:00:00Z');
  return d.toLocaleDateString(lang === 'en' ? 'en-GB' : 'ru-RU', { day: 'numeric', month: 'long', timeZone: 'UTC' });
};

function alertLine(a, bulletin, lang) {
  const t = T[lang];
  const region = escape(bulletin.regions[a.region]?.[lang] || '');
  const link = `https://maps.google.com/?q=${a.lat},${a.lon}`;
  // One scale for every alert: v7's calibrated chance; a red mark when v7 itself is on alert,
  // orange when only v6 flags the cell.
  const level = (a.strong ?? a.v7) ? '🔴' : '🟠';
  return `${level} ${LAND[a.land] || '▫️'} ${region} · ${LAND_NAME[lang][a.land] || ''} · <b>${t.chance} ${pct(a.p ?? a.p_v7)}</b> · <a href="${link}">${a.lat.toFixed(3)}, ${a.lon.toFixed(3)}</a>`;
}

export function distanceKm(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180, dLat = (lat2 - lat1) * r, dLon = (lon2 - lon1) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
}

// A one-line key under any message that lists alerts.
// The evening (day-ahead) bulletin is marked as tomorrow's preliminary forecast.
const note = (b, lang) => (b.kind === 'dayahead' ? T[lang].ahead : b.refined ? T[lang].refined : '');
const heading = (b, lang) => T[lang].header(dayText(b.target_day, lang)) + (note(b, lang) ? `\n<i>${note(b, lang)}</i>` : '');
const withLegend = (text, lang, b = null) =>
  (/🔴|🟠/.test(text) ? `${text}\n\n<i>${b?.kind === 'dayahead' ? T[lang].legendAhead : T[lang].legend}</i>` : text);
// Alerts per model, as the site counts them per model.
export const modelCounts = (b, alerts = b.alerts) =>
  b.kind === 'dayahead'
    ? `v6da ${alerts.length}`
    : `v7 ${alerts.filter((a) => a.strong ?? a.v7).length} · v6 ${alerts.filter((a) => a.v6).length}`;

// Alerts the subscriber wants to see: cropland burns only if they keep them.

const visible = (bulletin, sub) => bulletin.alerts.filter((a) => sub.crop || a.land !== 'пашня');

function nearLines(bulletin, sub, lat, lon, radius) {
  const t = T[sub.lang];
  const close = visible(bulletin, sub)
    .map((a) => ({ a, d: distanceKm(lat, lon, a.lat, a.lon) }))
    .filter((x) => x.d <= radius)
    .sort((x, y) => x.d - y.d);
  if (!close.length) return { n: 0, lines: [t.nearNone(radius)], alerts: [] };
  const lines = [t.near(radius, close.length)];
  for (const { a, d } of close.slice(0, MAX_ROWS)) lines.push(`${Math.round(d)} ${t.km} · ${alertLine(a, bulletin, sub.lang)}`);
  if (close.length > MAX_ROWS) lines.push(t.more(close.length - MAX_ROWS));
  return { n: close.length, lines, alerts: close.map((x) => x.a) };
}

// The morning summary for one subscriber: their regions and their point. Null when there is
// nothing to say and they asked for quiet.
export function summary(bulletin, sub, { forced = false } = {}) {
  const t = T[sub.lang];
  if (!sub.regions.length && !sub.home) return forced ? t.noRegions : null;
  const shown = visible(bulletin, sub);
  const hiddenCrop = bulletin.alerts.length - shown.length;
  const mine = shown.filter((a) => sub.regions.includes(a.region));
  const near = sub.home ? nearLines(bulletin, sub, sub.home.lat, sub.home.lon, sub.radius) : null;
  if (!mine.length && !(near && near.n) && sub.quiet && !forced) return null;
  const lines = [heading(bulletin, sub.lang)];
  if (near) lines.push(...near.lines, '');
  if (sub.regions.length) {
    if (!mine.length) lines.push(t.none);
    else {
      lines.push(t.count(mine.length, shown.length), '');
      for (const a of mine.slice(0, MAX_ROWS)) lines.push(alertLine(a, bulletin, sub.lang));
      if (mine.length > MAX_ROWS) lines.push(t.more(mine.length - MAX_ROWS));
    }
  }
  if (sub.crop && [...mine, ...(near ? near.alerts : [])].some((a) => a.land === 'пашня')) lines.push('', t.crop);
  if (!sub.crop && hiddenCrop) lines.push('', t.cropHidden(hiddenCrop));
  if (bulletin.warnings?.length) lines.push('', t.warn);
  return withLegend(lines.join('\n').replace(/\n{3,}/g, '\n\n').trim(), sub.lang, bulletin);
}

export function regionSummary(bulletin, sub, region) {
  const t = T[sub.lang];
  const name = escape(bulletin.regions[region]?.[sub.lang] || '');
  const alerts = visible(bulletin, sub).filter((a) => a.region === region);
  const lines = [heading(bulletin, sub.lang)];
  if (!alerts.length) lines.push(t.noneRegion(name));
  else {
    lines.push(t.regionCount(name, alerts.length), '');
    for (const a of alerts.slice(0, MAX_ROWS)) lines.push(alertLine(a, bulletin, sub.lang));
    if (alerts.length > MAX_ROWS) lines.push(t.more(alerts.length - MAX_ROWS));
    if (alerts.some((a) => a.land === 'пашня')) lines.push('', t.crop);
  }
  return withLegend(lines.join('\n'), sub.lang, bulletin);
}

export function nearby(bulletin, lat, lon, lang, sub = defaults(lang)) {
  const s = { ...sub, lang };
  return withLegend([heading(bulletin, lang), ...nearLines(bulletin, s, lat, lon, s.home ? s.radius : NEAR_KM).lines].join('\n'), lang, bulletin);
}

// Counts per region for a day, kept for the trend in the national summary.
export const regionCounts = (bulletin) => bulletin.alerts.reduce((c, a) => ({ ...c, [a.region]: (c[a.region] || 0) + 1 }), {});

export function national(bulletin, sub, previous = null) {
  const t = T[sub.lang];
  const shown = visible(bulletin, sub);
  const counts = {};
  for (const a of shown) counts[a.region] = (counts[a.region] || 0) + 1;
  const lines = [t.kz(dayText(bulletin.target_day, sub.lang), shown.length), t.byModel(modelCounts(bulletin, shown)), ...(note(bulletin, sub.lang) ? [`<i>${note(bulletin, sub.lang)}</i>`] : []), ''];
  const order = Object.keys(counts).map(Number).sort((a, b) => counts[b] - counts[a]);
  for (const r of order) {
    const before = previous ? previous[r] || 0 : null;
    lines.push(`${escape(bulletin.regions[r]?.[sub.lang] || '')}: <b>${counts[r]}</b>${before === null ? '' : t.trend(counts[r] - before)}`);
  }
  if (shown.length) {
    lines.push('', t.top);
    for (const a of [...shown].sort((x, y) => (y.p ?? y.p_v7) - (x.p ?? x.p_v7)).slice(0, 5)) lines.push(alertLine(a, bulletin, sub.lang));
  }
  if (!sub.crop && bulletin.alerts.length > shown.length) lines.push('', t.cropHidden(bulletin.alerts.length - shown.length));
  return withLegend(lines.join('\n'), sub.lang, bulletin);
}

export function radiusKeyboard(lang) {
  const t = T[lang];
  return { inline_keyboard: [RADII.map((r) => ({ text: `${r} ${t.km}`, callback_data: `h:${r}` })), [{ text: t.homeOff, callback_data: 'h:off' }]] };
}

export function settingsKeyboard(sub) {
  const t = T[sub.lang];
  return {
    inline_keyboard: [
      [{ text: sub.push ? t.pushOn : t.pushOff, callback_data: 's:push' }],
      [{ text: sub.quiet ? t.quietOn : t.quietOff, callback_data: 's:quiet' }],
      [{ text: sub.crop ? t.cropOn : t.cropOff, callback_data: 's:crop' }],
      LANGS.map((l) => ({ text: (l === sub.lang ? '✅ ' : '') + { ru: 'Русский', kk: 'Қазақша', en: 'English' }[l], callback_data: `s:lang:${l}` })),
    ],
  };
}

export function applySetting(sub, data) {
  if (data === 'push') return { ...sub, push: !sub.push };
  if (data === 'quiet') return { ...sub, quiet: !sub.quiet };
  if (data === 'crop') return { ...sub, crop: !sub.crop };
  if (data.startsWith('lang:') && LANGS.includes(data.slice(5))) return { ...sub, lang: data.slice(5) };
  return sub;
}

export const COMMANDS = {
  ru: [['today', 'Прогноз на завтра'], ['kz', 'Сводка по Казахстану'], ['ask', 'Спросить ИИ-ассистента'], ['regions', 'Выбрать области'], ['settings', 'Рассылка, палы, язык'], ['about', 'Что это и насколько точно'], ['stop', 'Отписаться']],
  kk: [['today', 'Ертеңгі болжам'], ['kz', 'Қазақстан бойынша шолу'], ['ask', 'ЖИ-көмекшіге сұрақ'], ['regions', 'Облыстарды таңдау'], ['settings', 'Тарату, өртеулер, тіл'], ['about', 'Бұл не'], ['stop', 'Жазылымнан шығу']],
  en: [['today', 'Tomorrow’s forecast'], ['kz', 'All Kazakhstan'], ['ask', 'Ask the AI assistant'], ['regions', 'Choose regions'], ['settings', 'Summary, burns, language'], ['about', 'What this is'], ['stop', 'Unsubscribe']],
};
