// Telegram bot for Wildfire KZ · Steppe: texts, keyboards and alert formatting.
// Pure functions only; worker.js does the I/O. Languages: ru (default), kk, en.

export const LANGS = ['ru', 'kk', 'en'];
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
    welcome: (name) => `Здравствуйте${name ? ', ' + name : ''}! Я присылаю ежедневный прогноз пожарной опасности по Казахстану на следующие сутки.\n\nВыберите области, по которым хотите получать тревоги, и нажмите «Готово».`,
    choose: 'Отметьте области (можно несколько):',
    all: 'Все области', done: '✅ Готово',
    saved: (n) => `Подписка сохранена: ${n}. Сводка будет приходить каждое утро около 6:00 по Казахстану.\n\n/today — прогноз сейчас\n📍 Отправьте геолокацию — покажу тревоги рядом с вами.`,
    allRegions: 'все области', noRegions: 'Сначала выберите области: /regions',
    header: (day) => `🔥 <b>Прогноз пожарной опасности на ${day}</b>`,
    count: (n, total) => `Тревог в ваших областях: <b>${n}</b> (по Казахстану: ${total}).`,
    none: '✅ В ваших областях тревог на завтра нет.',
    more: (n) => `…и ещё ${n}. Все тревоги — на карте.`,
    chance: 'шанс', index: 'индекс v6',
    crop: '🚜 На пашне тревога чаще всего означает плановый пал, а не природный пожар.',
    warn: '⚠️ Часть входных данных сегодня неполная, прогноз может быть менее точным.',
    map: '🗺 Открыть карту', where: 'на карте',
    noData: 'Прогноз на завтра ещё не выпущен. Обычно он появляется к 5:00–6:00 по Казахстану.',
    near: (n) => `📍 Тревог в радиусе ${NEAR_KM} км: <b>${n}</b>.`,
    nearNone: `📍 В радиусе ${NEAR_KM} км от вас тревог на завтра нет.`,
    km: 'км',
    about: 'ℹ️ <b>Что это</b>\nКаждую ночь модель машинного обучения оценивает для каждой клетки 5×5 км вероятность, что завтра спутник увидит там новый очаг огня. Данные: спутники NASA, погода ERA5 и GFS, растительность, рельеф, история пожаров.\n\n<b>Точность.</b> Прогноз показывает, где риск выше всего, но не предсказывает конкретный пожар: из 100 клеток с тревогой горят около 7, в зону тревоги попадает около 10–15% новых очагов. Это не официальное предупреждение МЧС.\n\n🚒 При пожаре звоните 112.',
    settings: (push, quiet, lang) => `⚙️ <b>Настройки</b>\nУтренняя рассылка: ${push ? 'вкл' : 'выкл'}\nПисать, если тревог нет: ${quiet ? 'нет' : 'да'}\nЯзык: ${lang}`,
    pushOn: '🔔 Рассылка: вкл', pushOff: '🔕 Рассылка: выкл', quietOn: 'Без тревог — не писать', quietOff: 'Без тревог — писать',
    stopped: 'Подписка удалена, данные о вас стёрты. Вернуться: /start',
    help: '/today — прогноз на завтра\n/regions — выбрать области\n/settings — рассылка и язык\n/about — что это и насколько точно\n/stop — отписаться\n📍 Геолокация — тревоги рядом',
    unknown: 'Не понял команду. /help — список команд.',
  },
  kk: {
    welcome: (name) => `Сәлеметсіз бе${name ? ', ' + name : ''}! Мен Қазақстан бойынша келесі тәулікке өрт қаупінің күнделікті болжамын жіберемін.\n\nДабылдарын алғыңыз келетін облыстарды таңдап, «Дайын» басыңыз.`,
    choose: 'Облыстарды белгілеңіз (бірнешеуін де):',
    all: 'Барлық облыстар', done: '✅ Дайын',
    saved: (n) => `Жазылым сақталды: ${n}. Шолу күн сайын таңертең Қазақстан уақытымен 6:00 шамасында келеді.\n\n/today — қазіргі болжам\n📍 Геолокация жіберіңіз — жаныңыздағы дабылдарды көрсетемін.`,
    allRegions: 'барлық облыстар', noRegions: 'Алдымен облыстарды таңдаңыз: /regions',
    header: (day) => `🔥 <b>${day} күнгі өрт қаупінің болжамы</b>`,
    count: (n, total) => `Сіздің облыстардағы дабылдар: <b>${n}</b> (Қазақстан бойынша: ${total}).`,
    none: '✅ Сіздің облыстарда ертеңге дабыл жоқ.',
    more: (n) => `…тағы ${n}. Барлық дабылдар — картада.`,
    chance: 'мүмкіндік', index: 'v6 индексі',
    crop: '🚜 Егістіктегі дабыл көбіне табиғи өрт емес, жоспарлы өртеуді білдіреді.',
    warn: '⚠️ Бүгін кіріс деректердің бір бөлігі толық емес, болжам дәлдігі төмен болуы мүмкін.',
    map: '🗺 Картаны ашу', where: 'картада',
    noData: 'Ертеңгі болжам әлі шықпады. Әдетте Қазақстан уақытымен 5:00–6:00 шамасында шығады.',
    near: (n) => `📍 ${NEAR_KM} км радиустағы дабылдар: <b>${n}</b>.`,
    nearNone: `📍 Сізден ${NEAR_KM} км радиуста ертеңге дабыл жоқ.`,
    km: 'км',
    about: 'ℹ️ <b>Бұл не</b>\nМашиналық оқыту моделі әр түні 5×5 км әр ұяшық үшін ертең спутник жаңа өрт ошағын көру ықтималдығын бағалайды. Деректер: NASA спутниктері, ERA5 және GFS ауа райы, өсімдік, жер бедері, өрт тарихы.\n\n<b>Дәлдік.</b> Болжам қауіп қай жерде жоғары екенін көрсетеді, бірақ нақты өртті болжамайды: дабылы бар 100 ұяшықтың шамамен 7-еуі жанады. Бұл ТЖМ-нің ресми ескертуі емес.\n\n🚒 Өрт кезінде 112-ге қоңырау шалыңыз.',
    settings: (push, quiet, lang) => `⚙️ <b>Баптаулар</b>\nТаңғы тарату: ${push ? 'қосулы' : 'өшірулі'}\nДабыл болмаса жазу: ${quiet ? 'жоқ' : 'иә'}\nТіл: ${lang}`,
    pushOn: '🔔 Тарату: қосулы', pushOff: '🔕 Тарату: өшірулі', quietOn: 'Дабылсыз — жазбау', quietOff: 'Дабылсыз — жазу',
    stopped: 'Жазылым жойылды, сіз туралы деректер өшірілді. Қайту: /start',
    help: '/today — ертеңгі болжам\n/regions — облыстарды таңдау\n/settings — тарату және тіл\n/about — бұл не және қаншалықты дәл\n/stop — жазылымнан шығу\n📍 Геолокация — жақын дабылдар',
    unknown: 'Команда түсініксіз. /help — командалар тізімі.',
  },
  en: {
    welcome: (name) => `Hello${name ? ', ' + name : ''}! I send a daily next-day fire danger forecast for Kazakhstan.\n\nChoose the regions you want alerts for and press “Done”.`,
    choose: 'Tick the regions (several allowed):',
    all: 'All regions', done: '✅ Done',
    saved: (n) => `Subscription saved: ${n}. The summary arrives every morning around 6:00 Kazakhstan time.\n\n/today — the forecast now\n📍 Send your location to see alerts near you.`,
    allRegions: 'all regions', noRegions: 'Choose regions first: /regions',
    header: (day) => `🔥 <b>Fire danger forecast for ${day}</b>`,
    count: (n, total) => `Alerts in your regions: <b>${n}</b> (all Kazakhstan: ${total}).`,
    none: '✅ No alerts for tomorrow in your regions.',
    more: (n) => `…and ${n} more. All alerts are on the map.`,
    chance: 'chance', index: 'v6 index',
    crop: '🚜 On cropland an alert usually means a planned burn, not a wildfire.',
    warn: '⚠️ Some inputs are incomplete today; the forecast may be less accurate.',
    map: '🗺 Open the map', where: 'map',
    noData: 'Tomorrow’s forecast is not issued yet. It usually appears by 5:00–6:00 Kazakhstan time.',
    near: (n) => `📍 Alerts within ${NEAR_KM} km: <b>${n}</b>.`,
    nearNone: `📍 No alerts for tomorrow within ${NEAR_KM} km of you.`,
    km: 'km',
    about: 'ℹ️ <b>What this is</b>\nEvery night a machine-learning model estimates, for each 5×5 km cell, the chance that a satellite sees a new fire there tomorrow. Data: NASA satellites, ERA5 and GFS weather, vegetation, terrain, fire history.\n\n<b>Accuracy.</b> The forecast shows where risk is highest but does not predict a specific fire: about 7 of 100 cells on alert burn. It is not an official emergency warning.\n\n🚒 In case of fire call 112.',
    settings: (push, quiet, lang) => `⚙️ <b>Settings</b>\nMorning summary: ${push ? 'on' : 'off'}\nMessage when there are no alerts: ${quiet ? 'no' : 'yes'}\nLanguage: ${lang}`,
    pushOn: '🔔 Summary: on', pushOff: '🔕 Summary: off', quietOn: 'No alerts — stay silent', quietOff: 'No alerts — tell me',
    stopped: 'Unsubscribed; your data is deleted. Come back: /start',
    help: '/today — tomorrow’s forecast\n/regions — choose regions\n/settings — summary and language\n/about — what this is and how accurate\n/stop — unsubscribe\n📍 Location — alerts nearby',
    unknown: 'Unknown command. /help lists the commands.',
  },
};

export const langOf = (code) => (LANGS.includes((code || '').slice(0, 2)) ? code.slice(0, 2) : 'ru');
export const escape = (s) => String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);
export const defaults = (lang) => ({ lang, regions: [], push: true, quiet: true });

export function command(text) {
  const m = /^\/([a-z_]+)(@\w+)?(?:\s+(.*))?$/i.exec((text || '').trim());
  return m ? { name: m[1].toLowerCase(), arg: (m[3] || '').trim() } : null;
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
  const score = a.v7 ? `${t.chance} ${pct(a.p_v7)}` : `${t.index} ${pct(a.p_v6)}`;
  return `${LAND[a.land] || '▫️'} ${region} · ${LAND_NAME[lang][a.land] || ''} · <b>${score}</b> · <a href="${link}">${a.lat.toFixed(3)}, ${a.lon.toFixed(3)}</a>`;
}

// The morning summary for one subscriber; null when there is nothing to say and they asked for quiet.
export function summary(bulletin, sub, { forced = false } = {}) {
  const t = T[sub.lang];
  if (!sub.regions.length) return forced ? t.noRegions : null;
  const mine = bulletin.alerts.filter((a) => sub.regions.includes(a.region));
  if (!mine.length && sub.quiet && !forced) return null;
  const lines = [t.header(dayText(bulletin.target_day, sub.lang))];
  if (!mine.length) lines.push(t.none);
  else {
    lines.push(t.count(mine.length, bulletin.alerts.length), '');
    for (const a of mine.slice(0, MAX_ROWS)) lines.push(alertLine(a, bulletin, sub.lang));
    if (mine.length > MAX_ROWS) lines.push(t.more(mine.length - MAX_ROWS));
    if (mine.some((a) => a.land === 'пашня')) lines.push('', t.crop);
  }
  if (bulletin.warnings?.length) lines.push('', t.warn);
  return lines.join('\n');
}

export function distanceKm(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180, dLat = (lat2 - lat1) * r, dLon = (lon2 - lon1) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
}

export function nearby(bulletin, lat, lon, lang) {
  const t = T[lang];
  const close = bulletin.alerts
    .map((a) => ({ a, d: distanceKm(lat, lon, a.lat, a.lon) }))
    .filter((x) => x.d <= NEAR_KM)
    .sort((x, y) => x.d - y.d);
  if (!close.length) return `${t.header(dayText(bulletin.target_day, lang))}\n${t.nearNone}`;
  const lines = [t.header(dayText(bulletin.target_day, lang)), t.near(close.length), ''];
  for (const { a, d } of close.slice(0, MAX_ROWS)) lines.push(`${Math.round(d)} ${t.km} · ${alertLine(a, bulletin, lang)}`);
  if (close.some(({ a }) => a.land === 'пашня')) lines.push('', t.crop);
  return lines.join('\n');
}

export function settingsKeyboard(sub) {
  const t = T[sub.lang];
  return {
    inline_keyboard: [
      [{ text: sub.push ? t.pushOn : t.pushOff, callback_data: 's:push' }],
      [{ text: sub.quiet ? t.quietOn : t.quietOff, callback_data: 's:quiet' }],
      LANGS.map((l) => ({ text: (l === sub.lang ? '✅ ' : '') + { ru: 'Русский', kk: 'Қазақша', en: 'English' }[l], callback_data: `s:lang:${l}` })),
    ],
  };
}

export function applySetting(sub, data) {
  if (data === 'push') return { ...sub, push: !sub.push };
  if (data === 'quiet') return { ...sub, quiet: !sub.quiet };
  if (data.startsWith('lang:') && LANGS.includes(data.slice(5))) return { ...sub, lang: data.slice(5) };
  return sub;
}

export const COMMANDS = {
  ru: [['today', 'Прогноз на завтра'], ['regions', 'Выбрать области'], ['settings', 'Рассылка и язык'], ['about', 'Что это и насколько точно'], ['stop', 'Отписаться']],
  kk: [['today', 'Ертеңгі болжам'], ['regions', 'Облыстарды таңдау'], ['settings', 'Тарату және тіл'], ['about', 'Бұл не'], ['stop', 'Жазылымнан шығу']],
  en: [['today', 'Tomorrow’s forecast'], ['regions', 'Choose regions'], ['settings', 'Summary and language'], ['about', 'What this is'], ['stop', 'Unsubscribe']],
};
