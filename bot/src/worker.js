// Cloudflare Worker: Telegram webhook for subscribers and the morning broadcast.
// Secrets and bindings (wrangler.toml / GitHub workflow): TELEGRAM_TOKEN, SITE_URL, ADMIN_CHAT_ID
// (optional), KV namespace SUBS. Only chat id, language, regions, an optional point and a few
// switches are stored, as key metadata, so one KV list call reads every subscriber.
import {
  T, langOf, defaults, command, menuAction, menuKeyboard, findRegion, regionKeyboard, toggleRegion,
  regionList, summary, regionSummary, nearby, national, regionCounts, radiusKeyboard, RADII,
  settingsKeyboard, applySetting, COMMANDS,
} from './logic.js';

// Free Workers allow 50 subrequests per run: a broadcast run sends at most this many messages
// and continues from a saved cursor on the next cron tick.
const BATCH = 40;

const hex = async (text) => Array.from(
  new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))),
  (b) => b.toString(16).padStart(2, '0'),
).join('');
// The webhook secret is derived from the bot token, so there is one secret to manage.
const webhookSecret = async (env) => (await hex('webhook:' + env.TELEGRAM_TOKEN)).slice(0, 48);

async function tg(env, method, body) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/${method}`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  });
  return r.json();
}

async function bulletin(env) {
  const r = await fetch(`${env.SITE_URL}/assets/bulletin-latest.json`, { cf: { cacheTtl: 300 } });
  if (!r.ok) return null;
  const b = await r.json();
  return b?.synthetic === false && Array.isArray(b.alerts) ? b : null;
}

// Alert counts per region of recent days, written once per new day by the broadcast.
async function history(env) {
  return JSON.parse((await env.SUBS.get('history')) || '{}');
}
function previousCounts(hist, day) {
  const days = Object.keys(hist).filter((d) => d < day).sort();
  return days.length ? hist[days.at(-1)] : null;
}

const key = (chat) => `chat:${chat}`;
async function load(env, chat, lang) {
  const { metadata } = await env.SUBS.getWithMetadata(key(chat));
  return metadata ? { ...defaults(lang), ...metadata } : null;
}
const save = (env, chat, sub) => env.SUBS.put(key(chat), '1', { metadata: sub });

const mapButton = (env, lang) => ({ inline_keyboard: [[{ text: T[lang].map, url: `${env.SITE_URL}/?lang=${lang}` }]] });
const send = (env, chat, text, extra = {}) => tg(env, 'sendMessage', {
  chat_id: chat, text, parse_mode: 'HTML', disable_web_page_preview: true, ...extra,
});
const escapeName = (s) => (s ? String(s).replace(/[&<>]/g, '').slice(0, 40) : '');

async function onMessage(env, msg) {
  const chat = msg.chat.id;
  const lang0 = langOf(msg.from?.language_code);
  let sub = await load(env, chat, lang0);
  const lang = sub?.lang || lang0;
  const t = T[lang];
  if (msg.location) {
    sub = { ...(sub || defaults(lang)), home: { lat: +msg.location.latitude.toFixed(4), lon: +msg.location.longitude.toFixed(4) } };
    await save(env, chat, sub);
    const b = await bulletin(env);
    if (b) await send(env, chat, nearby(b, sub.home.lat, sub.home.lon, lang, sub), { reply_markup: mapButton(env, lang) });
    return send(env, chat, t.homeAsk, { reply_markup: radiusKeyboard(lang) });
  }
  const c = command(msg.text) || (menuAction(msg.text) ? { name: menuAction(msg.text), arg: '' } : null);
  const b = !c || ['start', 'regions', 'today', 'kz'].includes(c.name) ? await bulletin(env) : null;
  if (!c) {
    const region = b ? findRegion(b, msg.text) : -1;
    if (region >= 0) return send(env, chat, regionSummary(b, sub || defaults(lang), region), { reply_markup: mapButton(env, lang) });
    return send(env, chat, t.unknown, { reply_markup: menuKeyboard(lang) });
  }
  switch (c.name) {
    case 'start':
      sub = sub || defaults(lang);
      await save(env, chat, sub);
      await send(env, chat, t.welcome(escapeName(msg.from?.first_name)), { reply_markup: menuKeyboard(lang) });
      return b ? send(env, chat, t.choose, { reply_markup: regionKeyboard(b, sub) }) : send(env, chat, t.noData);
    case 'regions':
      sub = sub || defaults(lang);
      return b ? send(env, chat, t.choose, { reply_markup: regionKeyboard(b, sub) }) : send(env, chat, t.noData);
    case 'today':
      if (!b) return send(env, chat, t.noData);
      return send(env, chat, summary(b, sub || defaults(lang), { forced: true }), { reply_markup: mapButton(env, lang) });
    case 'near':
      // The menu button sends the location itself; typed /near asks for it.
      return send(env, chat, t.homeAsk, { reply_markup: menuKeyboard(lang) });
    case 'kz': {
      if (!b) return send(env, chat, t.noData);
      const prev = previousCounts(await history(env), b.target_day);
      return send(env, chat, national(b, sub || defaults(lang), prev), { reply_markup: mapButton(env, lang) });
    }
    case 'settings':
      sub = sub || defaults(lang);
      await save(env, chat, sub);
      return send(env, chat, t.settings(sub), { reply_markup: settingsKeyboard(sub) });
    case 'about':
      return send(env, chat, t.about, { reply_markup: mapButton(env, lang) });
    case 'stop':
      await env.SUBS.delete(key(chat));
      return send(env, chat, t.stopped, { reply_markup: { remove_keyboard: true } });
    case 'stats':
      if (String(chat) !== String(env.ADMIN_CHAT_ID || '')) return send(env, chat, t.unknown);
      return send(env, chat, await stats(env));
    case 'help':
      return send(env, chat, t.help, { reply_markup: menuKeyboard(lang) });
    default:
      return send(env, chat, t.unknown, { reply_markup: menuKeyboard(lang) });
  }
}

async function onCallback(env, cb) {
  const chat = cb.message.chat.id;
  let sub = (await load(env, chat, langOf(cb.from?.language_code))) || defaults(langOf(cb.from?.language_code));
  const [kind, ...rest] = cb.data.split(':');
  const value = rest.join(':');
  const t = T[sub.lang];
  const edit = (text, markup) => tg(env, 'editMessageText', {
    chat_id: chat, message_id: cb.message.message_id, text, parse_mode: 'HTML', reply_markup: markup,
  });
  await tg(env, 'answerCallbackQuery', { callback_query_id: cb.id });
  if (kind === 'r') {
    const b = await bulletin(env);
    if (!b) return edit(t.noData);
    if (value === 'done') {
      await save(env, chat, sub);
      return edit(sub.regions.length ? t.saved(regionList(b, sub)) : t.noRegions);
    }
    sub = toggleRegion(sub, value, b.regions.length);
    await save(env, chat, sub);
    return edit(t.choose, regionKeyboard(b, sub));
  }
  if (kind === 'h') {
    if (value === 'off') {
      await save(env, chat, { ...sub, home: null });
      return edit(t.homeRemoved);
    }
    const radius = RADII.includes(Number(value)) ? Number(value) : 50;
    await save(env, chat, { ...sub, radius });
    return edit(t.homeSaved(radius));
  }
  if (kind === 's') {
    sub = applySetting(sub, value);
    await save(env, chat, sub);
    return edit(T[sub.lang].settings(sub), settingsKeyboard(sub));
  }
}

async function allSubscribers(env) {
  const out = [];
  let cursor;
  do {
    const page = await env.SUBS.list({ prefix: 'chat:', cursor });
    out.push(...page.keys);
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return out;
}

async function stats(env) {
  const subs = await allSubscribers(env);
  const m = subs.map((k) => k.metadata || {});
  const state = JSON.parse((await env.SUBS.get('broadcast')) || '{}');
  return [
    `Подписчиков: ${subs.length}`,
    `с областями: ${m.filter((s) => s.regions?.length).length}, с точкой: ${m.filter((s) => s.home).length}`,
    `рассылка выключена: ${m.filter((s) => s.push === false).length}`,
    `языки: ${['ru', 'kk', 'en'].map((l) => `${l} ${m.filter((s) => (s.lang || 'ru') === l).length}`).join(', ')}`,
    `последняя рассылка: ${state.day || '—'}, отправлено ${state.sent || 0}${state.done ? '' : ' (идёт)'}`,
  ].join('\n');
}

// One cron tick: if a new day is published, send the next batch of summaries.
export async function broadcast(env) {
  const b = await bulletin(env);
  if (!b) return { sent: 0, reason: 'no bulletin' };
  const state = JSON.parse((await env.SUBS.get('broadcast')) || '{}');
  if (state.day === b.target_day && state.done) return { sent: 0, reason: 'done' };
  if (state.day !== b.target_day) {
    // First tick of a new day: keep its counts for the trend (two weeks).
    const hist = await history(env);
    hist[b.target_day] = regionCounts(b);
    for (const d of Object.keys(hist).sort().slice(0, -14)) delete hist[d];
    await env.SUBS.put('history', JSON.stringify(hist));
  }
  const cursor = state.day === b.target_day ? state.cursor : undefined;
  const page = await env.SUBS.list({ prefix: 'chat:', cursor, limit: BATCH });
  let sent = 0;
  for (const k of page.keys) {
    const sub = { ...defaults('ru'), ...(k.metadata || {}) };
    if (!sub.push) continue;
    const text = summary(b, sub);
    if (!text) continue;
    const r = await send(env, k.name.slice(5), text, { reply_markup: mapButton(env, sub.lang) });
    // A user who blocked the bot is removed, as Telegram asks.
    if (r?.error_code === 403) await env.SUBS.delete(k.name);
    else sent++;
  }
  await env.SUBS.put('broadcast', JSON.stringify({
    day: b.target_day, cursor: page.list_complete ? null : page.cursor, done: page.list_complete,
    sent: (state.day === b.target_day ? state.sent || 0 : 0) + sent,
  }));
  return { sent, done: page.list_complete };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const secret = await webhookSecret(env);
    if (url.pathname === '/health') return new Response('ok');
    // Called by the deploy workflow: registers the webhook and the command menu.
    if (url.pathname === '/setup' && url.searchParams.get('key') === secret) {
      const hook = await tg(env, 'setWebhook', {
        url: `${url.origin}/telegram`, secret_token: secret,
        allowed_updates: ['message', 'callback_query'], drop_pending_updates: false,
      });
      for (const lang of ['ru', 'kk', 'en']) {
        await tg(env, 'setMyCommands', {
          commands: COMMANDS[lang].map(([command, description]) => ({ command, description })),
          ...(lang === 'ru' ? {} : { language_code: lang }),
        });
      }
      return Response.json({ webhook: hook });
    }
    if (url.pathname === '/telegram' && request.method === 'POST') {
      if (request.headers.get('x-telegram-bot-api-secret-token') !== secret) return new Response('forbidden', { status: 403 });
      const update = await request.json();
      try {
        if (update.message) await onMessage(env, update.message);
        else if (update.callback_query) await onCallback(env, update.callback_query);
      } catch (e) {
        console.error('update failed', e);
      }
      return new Response('ok');
    }
    return new Response('not found', { status: 404 });
  },
  async scheduled(event, env, ctx) {
    ctx.waitUntil(broadcast(env));
  },
};
