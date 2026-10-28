import {t,num} from './i18n.js?v=20261028-lang';
const pct=v=>Number.isFinite(v)?num(100*v,{maximumFractionDigits:2})+'%':'—';
const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let population;
export async function populationNote(cell){
  if(!population){const response=await fetch('./assets/population-2020.json');if(!response.ok)return '';population=await response.json();if(population.year!==2020||population.model_input!==false)throw Error('Population overlay metadata differs')}
  const v=population.values[cell];
  return Number.isFinite(v)&&v>=0?t('population',{n:num(Math.round(v))}):t('population.none');
}
export async function readiness(){
  const response=await fetch('./assets/daily-status.json',{cache:'no-store'});
  if(!response.ok)return t('ready.none');
  const s=await response.json();
  const descriptions={'365-day fire history':t('ready.fire'),'meteorology':t('ready.meteo'),'landcover':t('ready.land'),'vegetation':t('ready.veg')};
  return t('ready.body',{day:esc(s.target_day),last:esc(s.nrt_last_observation),checked:esc(s.checked_utc),gaps:s.gaps.map(g=>`<li>${esc(descriptions[g.source]||g.source)}${g.from?': '+esc(g.from)+' — '+esc(g.to):''}.</li>`).join('')});
}
export async function quality(){
  const response=await fetch('./quality/summary.json');if(!response.ok)return t('q.loading');
  const s=await response.json(),a=s.events.all_events,e=s.events.cell_day_exact;
  const fresh=s.fresh_2025?.metrics;
  const freshText=fresh?t('q.fresh',{p:pct(fresh.precision),r:pct(fresh.recall),ap:fresh.average_precision.toFixed(5)}):'';
  return t('q.body',{fresh:freshText,rows:num(e.rows),p:pct(e.precision),r:pct(e.recall),sp:pct(s.cell_day.precision),sr:pct(s.cell_day.recall),events:num(a.events),ra:pct(a.same_day_event_recall_all),rc:pct(a.same_day_event_recall_covered),unc:num(a.uncovered_events)});
}
