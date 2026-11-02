import test from 'node:test';
import assert from 'node:assert/strict';
import {
  command, summary, nearby, toggleRegion, regionKeyboard, applySetting, defaults, distanceKm, langOf,
  menuAction, menuKeyboard, findRegion, national, regionSummary,
} from '../src/logic.js';
import worker, { broadcast } from '../src/worker.js';

const bulletin = {
  synthetic: false, target_day: '2026-10-31', warnings: [],
  regions: [{ ru: 'Павлодарская', en: 'Pavlodar', kk: 'Павлодар' }, { ru: 'Кызылординская', en: 'Kyzylorda', kk: 'Қызылорда' }],
  alerts: [
    { region: 1, lat: 45.1255, lon: 64.9983, land: 'пашня', p_v7: 0.16553, p_v6: 0.00918, v7: true, v6: true },
    { region: 1, lat: 45.3, lon: 65.1, land: 'степь', p_v7: 0.02, p_v6: 0.012, v7: false, v6: true },
  ],
};

test('commands are parsed with or without the bot name', () => {
  assert.deepEqual(command('/today'), { name: 'today', arg: '' });
  assert.deepEqual(command('/regions@SteppeBot 3'), { name: 'regions', arg: '3' });
  assert.equal(command('hello'), null);
  assert.equal(langOf('kk-KZ'), 'kk');
  assert.equal(langOf('de'), 'ru');
});

test('a summary lists only the subscriber regions and explains cropland alerts', () => {
  const sub = { ...defaults('ru'), regions: [1] };
  const text = summary(bulletin, sub);
  assert.match(text, /Тревог в ваших областях: <b>2<\/b>/);
  assert.match(text, /шанс 16,6%/);
  assert.match(text, /индекс v6 1,2%/);
  assert.match(text, /плановый пал/);
  assert.equal(summary(bulletin, { ...sub, regions: [0] }), null, 'quiet when nothing to say');
  assert.match(summary(bulletin, { ...sub, regions: [0], quiet: false }), /тревог на завтра нет/);
  assert.match(summary(bulletin, { ...defaults('en'), regions: [1] }), /Alerts in your regions/);
});

test('menu buttons, typed region names and the national summary', () => {
  assert.equal(menuAction('🔥 Прогноз'), 'today');
  assert.equal(menuAction('🇰🇿 Бүкіл Қазақстан'), 'kz');
  assert.equal(menuAction('hello'), null);
  assert.equal(menuKeyboard('ru').keyboard[0][1].request_location, true);
  assert.equal(findRegion(bulletin, 'кызылорда'), 1);
  assert.equal(findRegion(bulletin, 'Pavlodar'), 0);
  assert.equal(findRegion(bulletin, 'ок'), -1);
  assert.match(regionSummary(bulletin, defaults('ru'), 1), /Кызылординская: тревог <b>2<\/b>/);
  assert.match(regionSummary(bulletin, defaults('ru'), 0), /Павлодарская: тревог на завтра нет/);
  const kz = national(bulletin, defaults('ru'), { 1: 5 });
  assert.match(kz, /Всего тревог: <b>2<\/b>/);
  assert.match(kz, /Кызылординская: <b>2<\/b> ↓3/);
});

test('cropland burns can be hidden; a saved point gets its own section', () => {
  const sub = { ...defaults('ru'), regions: [1], crop: false };
  const text = summary(bulletin, sub);
  assert.match(text, /Тревог в ваших областях: <b>1<\/b>/);
  assert.match(text, /Скрыто палов на пашне: 1/);
  const home = { ...defaults('ru'), home: { lat: 45.13, lon: 65.0 }, radius: 25 };
  assert.match(summary(bulletin, home), /Рядом с вами<\/b> \(до 25 км\): тревог <b>2<\/b>/);
  assert.equal(summary(bulletin, { ...home, home: { lat: 51, lon: 71 } }), null, 'quiet when nothing near');
  assert.equal(applySetting(defaults('ru'), 'crop').crop, false);
});

test('region toggles, all and the keyboard marks', () => {
  let sub = defaults('ru');
  sub = toggleRegion(sub, '1', 2);
  assert.deepEqual(sub.regions, [1]);
  sub = toggleRegion(sub, 'all', 2);
  assert.deepEqual(sub.regions, [0, 1]);
  sub = toggleRegion(sub, 'all', 2);
  assert.deepEqual(sub.regions, []);
  const kb = regionKeyboard(bulletin, toggleRegion(defaults('ru'), '0', 2));
  assert.equal(kb.inline_keyboard[0].find((b) => b.callback_data === 'r:0').text, '✅ Павлодарская');
  assert.equal(toggleRegion(defaults('ru'), '99', 2).regions.length, 0);
});

test('settings switch push, quiet and language', () => {
  const s = defaults('ru');
  assert.equal(applySetting(s, 'push').push, false);
  assert.equal(applySetting(s, 'quiet').quiet, false);
  assert.equal(applySetting(s, 'lang:kk').lang, 'kk');
  assert.equal(applySetting(s, 'lang:xx').lang, 'ru');
});

test('nearby alerts are sorted by distance within 50 km', () => {
  assert.ok(Math.abs(distanceKm(45, 65, 46, 65) - 111.2) < 0.5);
  const text = nearby(bulletin, 45.13, 65.0, 'ru');
  assert.match(text, /до 50 км\): тревог <b>2<\/b>/);
  assert.ok(text.indexOf('пашня') < text.indexOf('степь'));
  assert.match(nearby(bulletin, 51, 71, 'ru'), /тревог нет/);
});

// A Telegram, KV and site double for the worker.
function harness() {
  const kv = new Map();
  const sent = [];
  const env = {
    TELEGRAM_TOKEN: 'test-token', SITE_URL: 'https://site.test', ADMIN_CHAT_ID: '7',
    SUBS: {
      async get(k) { return kv.get(k)?.value ?? null; },
      async getWithMetadata(k) { const v = kv.get(k); return { value: v?.value ?? null, metadata: v?.metadata ?? null }; },
      async put(k, value, o = {}) { kv.set(k, { value, metadata: o.metadata }); },
      async delete(k) { kv.delete(k); },
      async list({ prefix, cursor, limit = 1000 }) {
        const keys = [...kv.keys()].filter((k) => k.startsWith(prefix)).sort();
        const start = cursor ? Number(cursor) : 0;
        const page = keys.slice(start, start + limit);
        const done = start + limit >= keys.length;
        return { keys: page.map((name) => ({ name, metadata: kv.get(name).metadata })), list_complete: done, cursor: done ? undefined : String(start + limit) };
      },
    },
  };
  globalThis.fetch = async (url, init) => {
    if (String(url).startsWith('https://site.test/')) return new Response(JSON.stringify(bulletin));
    const body = JSON.parse(init.body);
    sent.push({ method: String(url).split('/').pop(), body });
    return new Response(JSON.stringify(Number(body.chat_id) === 403 ? { ok: false, error_code: 403 } : { ok: true, result: {} }));
  };
  return { env, kv, sent };
}

const update = (env, payload, secret) => worker.fetch(new Request('https://bot.test/telegram', {
  method: 'POST', headers: { 'x-telegram-bot-api-secret-token': secret }, body: JSON.stringify(payload),
}), env);

test('webhook refuses requests without the secret and runs a subscription end to end', async () => {
  const { env, kv, sent } = harness();
  const bad = await update(env, { message: { chat: { id: 1 }, text: '/start' } }, 'wrong');
  assert.equal(bad.status, 403);
  const setup = await worker.fetch(new Request('https://bot.test/setup?key=nope'), env);
  assert.equal(setup.status, 404);
  // The secret is what /setup registers; read it from a setup call with the real key.
  const hex = async (t) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(t))), (b) => b.toString(16).padStart(2, '0')).join('');
  const secret = (await hex('webhook:test-token')).slice(0, 48);
  await update(env, { message: { chat: { id: 1 }, from: { first_name: 'Айгуль', language_code: 'ru' }, text: '/start' } }, secret);
  assert.ok(kv.has('chat:1'));
  assert.equal(sent.at(-1).body.reply_markup.inline_keyboard.at(-1)[0].callback_data, 'r:done');
  await update(env, { callback_query: { id: 'c', from: { language_code: 'ru' }, data: 'r:1', message: { chat: { id: 1 }, message_id: 5 } } }, secret);
  assert.deepEqual(kv.get('chat:1').metadata.regions, [1]);
  await update(env, { message: { chat: { id: 1 }, text: '/today' } }, secret);
  assert.match(sent.at(-1).body.text, /Кызылорд|Тревог/);
  await update(env, { message: { chat: { id: 1 }, location: { latitude: 45.13, longitude: 65 } } }, secret);
  assert.deepEqual(kv.get('chat:1').metadata.home, { lat: 45.13, lon: 65 });
  assert.equal(sent.at(-1).body.reply_markup.inline_keyboard[0][1].callback_data, 'h:50');
  await update(env, { callback_query: { id: 'h', from: {}, data: 'h:100', message: { chat: { id: 1 }, message_id: 6 } } }, secret);
  assert.equal(kv.get('chat:1').metadata.radius, 100);
  await update(env, { message: { chat: { id: 1 }, text: '🇰🇿 Весь Казахстан' } }, secret);
  assert.match(sent.at(-1).body.text, /Всего тревог/);
  await update(env, { message: { chat: { id: 1 }, text: 'Кызылорда' } }, secret);
  assert.match(sent.at(-1).body.text, /Кызылординская: тревог/);
  await update(env, { message: { chat: { id: 7 }, text: '/stats' } }, secret);
  assert.match(sent.at(-1).body.text, /Подписчиков: 1/);
  await update(env, { message: { chat: { id: 1 }, text: '/stop' } }, secret);
  assert.ok(!kv.has('chat:1'));
});

test('broadcast sends once per day in batches and drops blocked users', async () => {
  const { env, kv, sent } = harness();
  for (let i = 0; i < 45; i++) await env.SUBS.put(`chat:${1000 + i}`, '1', { metadata: { ...defaults('ru'), regions: [1] } });
  await env.SUBS.put('chat:403', '1', { metadata: { ...defaults('ru'), regions: [1] } });
  await env.SUBS.put('chat:2000', '1', { metadata: { ...defaults('ru'), regions: [0] } });
  const first = await broadcast(env);
  assert.equal(first.done, false);
  const second = await broadcast(env);
  assert.equal(second.done, true);
  assert.equal(sent.filter((s) => s.method === 'sendMessage').length, 46, '45 subscribers plus the blocked one; region 0 stays quiet');
  assert.ok(!kv.has('chat:403'));
  assert.equal((await broadcast(env)).reason, 'done');
  assert.deepEqual(JSON.parse(kv.get('history').value)['2026-10-31'], { 1: 2 });
});
