// Cloudflare Worker: Telegram webhook for subscribers and the morning broadcast.
// Secrets and bindings (wrangler.toml / GitHub workflow): TELEGRAM_TOKEN, SITE_URL, ADMIN_CHAT_ID
// (optional), KV namespace SUBS. Only chat id, language, regions, an optional point and a few
// switches are stored, as key metadata, so one KV list call reads every subscriber.
import {
  T, langOf, defaults, command, menuAction, menuKeyboard, findRegion, regionKeyboard, toggleRegion,
  regionList, summary, regionSummary, nearby, national, regionCounts, radiusKeyboard, RADII, migrate,
  settingsKeyboard, applySetting, COMMANDS,
} from './logic.js';
import { MODEL, DAILY_LIMIT, context as aiContext, messages as aiMessages, answer as aiAnswer } from './assistant.js';

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

// The latest bulletin: through the service binding to the site Worker, else its public address.
async function readBulletin(env) {
  const tries = [];
  if (env.SITE) tries.push(['service', () => env.SITE.fetch('https://site/assets/bulletin-latest.json')]);
  tries.push(['public', () => fetch(`${env.SITE_URL}/assets/bulletin-latest.json`, { cf: { cacheTtl: 120 } })]);
  const errors = [];
  for (const [via, get] of tries) {
    try {
      const r = await get();
      if (!r.ok) { errors.push(`${via}: HTTP ${r.status}`); continue; }
      const b = await r.json();
      if (b?.synthetic === false && Array.isArray(b.alerts)) return { bulletin: b, via, errors };
      errors.push(`${via}: unexpected content`);
    } catch (e) {
      errors.push(`${via}: ${e.message}`);
    }
  }
  return { bulletin: null, via: null, errors };
}
const bulletin = async (env) => (await readBulletin(env)).bulletin;

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
  return metadata ? { ...defaults(lang), ...migrate(metadata) } : null;
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
  const b = !c || ['start', 'regions', 'today', 'kz', 'ask'].includes(c.name) ? await bulletin(env) : null;
  if (!c) {
    const region = b ? findRegion(b, msg.text) : -1;
    if (region >= 0) return send(env, chat, regionSummary(b, sub || defaults(lang), region), { reply_markup: mapButton(env, lang) });
    // Any other text is a question for the assistant.
    if (msg.text) return ask(env, chat, msg.text, sub, lang, b);
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
    case 'ask':
      return c.arg ? ask(env, chat, c.arg, sub, lang, b) : send(env, chat, t.aiHow);
    case 'help':
      return send(env, chat, t.help, { reply_markup: menuKeyboard(lang) });
    default:
      return send(env, chat, t.unknown, { reply_markup: menuKeyboard(lang) });
  }
}

// The AI assistant: Workers AI, grounded in the bulletin and the service's fact sheet only.
async function ask(env, chat, question, sub, lang, b) {
  const t = T[lang];
  if (!env.AI) return send(env, chat, t.aiOff);
  const quota = `ai:${chat}:${new Date().toISOString().slice(0, 10)}`;
  const used = Number((await env.SUBS.get(quota)) || 0);
  if (used >= DAILY_LIMIT) return send(env, chat, t.aiLimit(DAILY_LIMIT));
  await env.SUBS.put(quota, String(used + 1), { expirationTtl: 172800 });
  await tg(env, 'sendChatAction', { chat_id: chat, action: 'typing' });
  const previous = b ? previousCounts(await history(env), b.target_day) : null;
  let text = '';
  try {
    const result = await env.AI.run(MODEL, {
      messages: aiMessages(question, aiContext(b, sub, previous)), max_tokens: 600, temperature: 0.2,
    });
    text = aiAnswer(result);
  } catch (e) {
    console.error('assistant failed', e);
  }
  if (!text) return send(env, chat, t.aiError);
  // Plain text: the model's words are never parsed as HTML.
  return send(env, chat, `${text}\n\n${t.aiNote}`, { parse_mode: undefined });
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

// One cron tick: if a new issue is published, send the next batch of summaries. A day has two
// issues: the evening one for tomorrow (kind 'dayahead', v6da) and the morning refinement
// (v6 and v7, the most accurate models); each is sent once, the second marked as an update.
export async function broadcast(env) {
  let b = await bulletin(env);
  if (!b) return { sent: 0, reason: 'no bulletin' };
  const kind = b.kind === 'dayahead' ? 'dayahead' : 'morning';
  const state = JSON.parse((await env.SUBS.get('broadcast')) || '{}');
  const sameIssue = state.day === b.target_day && (state.kind || 'morning') === kind;
  if (sameIssue && state.done) return { sent: 0, reason: 'done' };
  // An older day never follows a newer one (a redeploy can briefly show the previous issue).
  if (state.day && b.target_day < state.day) return { sent: 0, reason: 'older' };
  const refined = kind === 'morning' && (sameIssue ? state.refined : state.day === b.target_day);
  if (refined) b = { ...b, refined: true };
  if (state.day !== b.target_day) {
    // First tick of a new day: keep its counts for the trend (two weeks).
    const hist = await history(env);
    hist[b.target_day] = regionCounts(b);
    for (const d of Object.keys(hist).sort().slice(0, -14)) delete hist[d];
    await env.SUBS.put('history', JSON.stringify(hist));
  }
  const cursor = sameIssue ? state.cursor : undefined;
  const page = await env.SUBS.list({ prefix: 'chat:', cursor, limit: BATCH });
  const previous = previousCounts(await history(env), b.target_day);
  let sent = 0;
  for (const k of page.keys) {
    const sub = { ...defaults('ru'), ...migrate(k.metadata || {}) };
    if (!sub.push) continue;
    // Without regions or a point a subscriber still hears something: the national summary.
    const text = sub.regions.length || sub.home ? summary(b, sub) : national(b, sub, previous);
    if (!text) continue;
    const r = await send(env, k.name.slice(5), text, { reply_markup: mapButton(env, sub.lang) });
    // A user who blocked the bot is removed, as Telegram asks.
    if (r?.error_code === 403) await env.SUBS.delete(k.name);
    else sent++;
  }
  await env.SUBS.put('broadcast', JSON.stringify({
    day: b.target_day, kind, refined, cursor: page.list_complete ? null : page.cursor,
    done: page.list_complete, sent: (sameIssue ? state.sent || 0 : 0) + sent,
    at: new Date().toISOString(),
  }));
  return { sent, done: page.list_complete };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const secret = await webhookSecret(env);
    if (url.pathname === '/health') return new Response('ok');
    // The assistant's model answers (a fixed two-word prompt, no user data).
    if (url.pathname === '/diag/ai') {
      if (!env.AI) return Response.json({ ai: false });
      try {
        const r = await env.AI.run(MODEL, { messages: [{ role: 'user', content: 'Ответь одним словом: работаешь?' }], max_tokens: 8 });
        return Response.json({ ai: true, model: MODEL, sample: aiAnswer(r) });
      } catch (e) {
        return Response.json({ ai: true, model: MODEL, error: String(e.message || e) });
      }
    }
    // Public self-check without secrets: can the bot read the forecast, and which one.
    if (url.pathname === '/diag') {
      const r = await readBulletin(env);
      return Response.json({
        bulletin_day: r.bulletin?.target_day ?? null, issued_utc: r.bulletin?.issued_utc ?? null,
        alerts: r.bulletin?.alerts.length ?? null, via: r.via, errors: r.errors,
        broadcast: JSON.parse((await env.SUBS.get('broadcast')) || 'null'),
        subscribers: (await allSubscribers(env)).length, ai: Boolean(env.AI),
      });
    }
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
