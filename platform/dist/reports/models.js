// The models page: static description plus the live log of issues from forecast-live.json.
import { $, t, num, esc, header, table } from './report.js?v=20261105-m2';
import { bindSwitch, onLang, locale } from '../i18n.js?v=20261105-m2';

bindSwitch();
onLang(() => location.reload());
header();

const time = (iso) => (iso ? new Date(iso).toLocaleString(locale(), { timeZone: 'Asia/Almaty', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—');
const day = (d) => new Date(`${d}T00:00:00Z`).toLocaleDateString(locale(), { timeZone: 'UTC', day: 'numeric', month: 'long' });

try {
  const live = await (await fetch('../assets/forecast-live.json', { cache: 'no-store' })).json();
  const bulletin = await (await fetch('../assets/bulletin-latest.json', { cache: 'no-store' })).json().catch(() => null);
  const s = live.summary;
  const da = live.dayahead;
  $('tiles').innerHTML = [
    [t('mods.tEntries'), num(s.entries), t('mods.tSince', { d: day(live.days[0]) })],
    [t('mods.tLast'), day(s.last), time(live.assets.v7?.[s.last]?.issued_utc)],
    [t('mods.tAhead'), da?.days?.length ? day(da.days.at(-1)) : '—', da?.days?.length ? time(da.assets?.[da.days.at(-1)]?.issued_utc) : ''],
    [t('mods.tMissed'), num(live.missed_days.length + (da?.missed_days?.length || 0)), ''],
  ].map(([label, value, hint]) => `<div class="metric"><span class="label">${esc(label)}</span><span class="value">${esc(value)}</span><span class="hint">${esc(hint)}</span></div>`).join('');
  const rows = [...live.days].reverse().map((d) => {
    const v7 = live.assets.v7?.[d], v6 = live.assets.v6?.[d];
    return [day(d), time(v7?.issued_utc), v7?.on_time ? t('mods.yes') : t('mods.late'), v7 ? num(v7.alert_cells) : '—', v6 ? num(v6.alert_cells) : '—'];
  });
  $('days').innerHTML = table([t('mods.hDay'), t('mods.hIssued'), t('mods.hOnTime'), t('mods.hV7'), t('mods.hV6')], rows) + `<p class="caption">${esc(t('mods.note'))}</p>`;
  if (bulletin?.warnings?.length) {
    $('warn-text').textContent = bulletin.warnings.join(' · ');
    $('warnings').hidden = false;
  }
  $('live').hidden = false;
  $('status').className = 'chip is-verified';
  $('status').textContent = t('mods.updated', { at: time(live.updated_utc) });
} catch (error) {
  console.error(error);
  $('status').className = 'chip is-accent';
  $('status').textContent = t('mods.failed');
  $('error').hidden = false;
}
