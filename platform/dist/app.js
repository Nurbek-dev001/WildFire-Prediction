import {loadUpgrade} from './upgrade-results.js?v=20261105-da';
import {t,num,pctText,onLang,bindSwitch,regionName,cityName,coords,longDate,weekday} from './i18n.js?v=20261105-da';
import {populationNote,readiness,quality} from './quality.js?v=20261105-da';
import {probability,modelLabel,modelInputs,loadForecast,validateManifest,sources,methodology,evaluation} from './model-results.js?v=20261105-da';
import {loadOperatingPolicy,activeProfile,profileMetrics} from './operating-policy.js';
import {isV6,isV7,isDayAhead,loadV6,loadLive} from './model-v6.js?v=20261105-da';
const $ = id => document.getElementById(id);
const nf = {format:v=>num(v)};
const df = {format:d=>longDate(d)};
const pf = p => state.mode==='real'&&manifest?.ready?probability(p):num(p*100,{minimumFractionDigits:1,maximumFractionDigits:1})+'%';
const canvas = $('map'), ctx = canvas.getContext('2d');
const state = {mode:'demo', model:'v5', hideHeat:true, layer:'forecast', view:'2d', detail:-1, basemap:'satellite', day:'2022-07-15', year:2022, zoom:1, panX:0, panY:0, selected:-1, region:-1, highOnly:false, lines:true, showPredicted:true, showObserved:true};
let manifests = {}, eventsByModel = {}, geo, manifest, cells, values, history, boundary, regionPaths, raster, cellByKey, baseScale=1, width=1, height=1, toastTimer, renderFrame, relief, hatch, satellite, events;
const digest=async buffer=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',buffer)),v=>v.toString(16).padStart(2,'0')).join('');
// NASA Blue Marble basemap, checked against satellite.json before use; the map works without it.
async function loadSatellite(){
  const meta=await (await fetch('./assets/satellite.json')).json();
  const buffer=await (await fetch('./assets/satellite.jpg')).arrayBuffer();
  if(await digest(buffer)!==meta.sha256)throw Error('Снимок не совпал с satellite.json');
  const img=new Image();img.src=URL.createObjectURL(new Blob([buffer],{type:'image/jpeg'}));await img.decode();
  satellite={img,extent:meta.extent_km};relief?.setSatellite(img,satellite.extent);syncBasemap();
}
// Observed new-fire events, opened after each release was evaluated; grouped by day index of that model's manifest.
const EVENTS={v5:'./assets/events-2023-2024',v6:'./assets/events-v6',v7:null};
async function loadEvents(key){
  if(eventsByModel[key])return eventsByModel[key];
  // Daily forecasts have no observed events until the season is scored.
  if(!EVENTS[key])return eventsByModel[key]=new Map();
  const meta=await (await fetch(EVENTS[key]+'.json')).json();
  const buffer=await (await fetch(EVENTS[key]+'.bin')).arrayBuffer();
  if(await digest(buffer)!==meta.sha256||buffer.byteLength!==meta.events*16||meta.release_sha256!==manifests[key].release_sha256)throw Error('Файл событий не совпал с '+EVENTS[key]+'.json');
  const dv=new DataView(buffer),byDay=new Map();
  for(let o=0;o<buffer.byteLength;o+=16){const day=dv.getUint16(o,true),flags=dv.getUint8(o+2);if(!byDay.has(day))byDay.set(day,[]);byDay.get(day).push({cell:dv.getInt32(o+4,true),x:dv.getFloat32(o+8,true),y:dv.getFloat32(o+12,true),covered:!!(flags&1),hit:!!(flags&2),hitBefore:!!(flags&4)})}
  return eventsByModel[key]=byDay;
}
async function useEvents(key){const byDay=await loadEvents(key);if(state.model!==key)return;events=byDay;allEventsCache=null;renderPoints();scheduleDraw()}
// v6 and v5 cover different days; keep the season when switching (2026 ↔ 2024).
function nearestDay(days,day){if(day>days.at(-1))return days.at(-1);const md=day.slice(4);for(const y of [day.slice(0,4),'2024','2023','2026'])if(days.includes(y+md))return y+md;let best=days[0];for(const d of days)if(Math.abs(Date.parse(d)-Date.parse(day))<Math.abs(Date.parse(best)-Date.parse(day)))best=d;return best}
function setModel(key){
  if(!manifests[key]||manifest===manifests[key])return;
  state.model=key;manifest=manifests[key];events=eventsByModel[key]||null;allEventsCache=null;
  if(!manifest.available_days.includes(state.day)){state.day=nearestDay(manifest.available_days,state.day);toast(t('toast.modelDay',{day:df.format(new Date(state.day+'T00:00:00Z'))}))}
  for(const k of ['v6da','v7','v6','v5'])$('model-'+k).setAttribute('aria-pressed',String(k===key));
  useEvents(key).catch(e=>console.warn('Observed events unavailable',e));
  setMode('real');
}
// Cells with at least 20 VIIRS detections in every year 2015–2022: smelters, steel works and gas flares the
// frozen industrial list missed. Both models give them very high values; the map hides them by default.
const HEAT_MIN=20;let heat;
const isHeat=i=>state.hideHeat&&state.mode==='real'&&!!heat?.[i];
const pointsActive=()=>state.mode==='real'&&state.layer==='forecast'&&!!state.realValues&&!state.noEligibleForecast;
const dayEvents=()=>pointsActive()&&events?(events.get(manifest.available_days.indexOf(state.day))||[]).filter(e=>!isHeat(e.cell)):[];
function syncBasemap(){
  const sat=state.basemap==='satellite'&&!!satellite;
  for(const k of ['satellite','scheme'])$('basemap-'+k).setAttribute('aria-pressed',String(state.basemap===k));
  $('map-shell').classList.toggle('is-satellite',sat);$('satellite-credit').hidden=!sat;
  relief?.setBasemap(sat);if(geo)makeRaster();
}
function predictedCells(){if(!pointsActive())return [];const t=riskThreshold(),out=[];for(let i=0;i<cells.length;i++)if(values[i]>=t)out.push(i);return out.sort((a,b)=>values[b]-values[a])}
const riskThreshold=()=>state.mode==='real'&&manifest?.ready?activeProfile(manifest,state.alertProfile).threshold:.05;
function syncProfile(){
  const policy=manifest?.operating_policy?.policy;
  if(manifest?.upgrade||isV6(manifest)){$('alert-profile-panel').querySelector('label').textContent=t('profile.active');$('alert-profile-panel').hidden=!(state.mode==='real'&&state.layer==='forecast');$('alert-profile').innerHTML=`<option>${t(isV7(manifest)?'model.v7':isV6(manifest)?'model.v6':'model.stack')}</option>`;$('alert-profile').disabled=true;const s=manifest.test_metrics[manifest.model];$('alert-profile-metrics').textContent=t('profile.metrics',{r:pctText(s.recall),p:pctText(s.precision),t:probability(manifest.threshold)});$('alert-profile-help').textContent=t(isV7(manifest)?'profile.help.v7':isV6(manifest)?'profile.help.v6':'profile.help.upgrade');const link=$('alert-profile-panel').querySelector('a');link.textContent=t('profile.compareModels');link.href='./reports/model.html';return}
  $('alert-profile-panel').hidden=!(policy&&state.mode==='real'&&state.layer==='forecast');
  if(!policy)return;
  const select=$('alert-profile');
  if(!select.options.length)for(const [key,p] of Object.entries(policy.profiles)){
    const option=document.createElement('option');option.value=key;option.textContent=p.label;select.append(option);
  }
  state.alertProfile=state.alertProfile||policy.default_profile;select.value=state.alertProfile;
  const s=profileMetrics(manifest,state.alertProfile),p=activeProfile(manifest,state.alertProfile);
  $('alert-profile-metrics').textContent=t('profile.metrics',{r:pctText(s.recall),p:pctText(s.precision),t:probability(p.threshold)});
}
const tokens = getComputedStyle(document.documentElement);
const colors = [1,2,3,4,5,6,7].map(i=>tokens.getPropertyValue('--p'+i).trim());
const LAND = [241,242,234];
// Log-spaced forecast classes: 99% of cell-days are below 0.33%, so linear bins paint one colour.
// The last edge is the alert threshold, so the top class is exactly the alert set.
const LOG_BOUNDS = [1e-4,3e-4,1e-3,3e-3,1e-2];
const HISTORY_BOUNDS = [2,4,8,16,32,64];
// The demo formula spans 0.1–12%, so it gets its own edges ending at its 5% filter.
const DEMO_BOUNDS = [.005,.01,.02,.03,.04];
function forecastBounds(){const t=riskThreshold();if(state.mode==='demo')return [...DEMO_BOUNDS,t];const b=LOG_BOUNDS.filter(v=>v<t);while(b.length<5)b.unshift(b[0]/3);return [...b,t]}
function classOf(p,bounds){let k=0;for(let i=0;i<bounds.length;i++)if(p>=bounds[i])k=i+1;return k}
const pct = v => num(v*100,{maximumFractionDigits:2});
const centerX = -17, centerY = -5;
function pathFrom(rings){const p=new Path2D();for(const ring of rings){ring.forEach(([x,y],i)=>i?p.lineTo(x,y):p.moveTo(x,y));p.closePath()}return p}
function view(){return {s:baseScale*state.zoom,x:width/2+state.panX-centerX*baseScale*state.zoom,y:height/2+state.panY-centerY*baseScale*state.zoom}}
function toWorld(x,y){const v=view();return [(x-v.x)/v.s,(y-v.y)/v.s]}
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,4500)}
let dialogSource=null;
function showDialog(title,html,source=null){dialogSource=source;$('dialog-eyebrow').textContent=title.toUpperCase();$('dialog-content').innerHTML=html;$('info-dialog').showModal()}
function dataDialog(){if(manifest?.ready){showDialog(t('dlg.sources'),sources(manifest),dataDialog);return}showDialog('ИСТОЧНИКИ И ГОТОВНОСТЬ', `<h2>Реальная география.<br>Прозрачный статус данных.</h2><p>Карта использует 110 129 ячеек реальной сетки Казахстана и разрешённую часть архива NASA. Национальная модель ещё не обучена.</p><div class="data-line"><span>Граница и сетка 5 км</span><span class="ready">ПОДКЛЮЧЕНЫ</span></div><div class="data-line"><span>VIIRS S-NPP · 2015–2022</span><span class="ready">ПОДКЛЮЧЕНЫ</span></div><div class="data-line"><span>Метеоданные · ERA5-Land</span><span class="pending">НУЖНЫ ДАННЫЕ</span></div><div class="data-line"><span>Растительность · MOD13A2</span><span class="pending">НУЖНЫ ДАННЫЕ</span></div><div class="data-line"><span>Покров, рельеф, антропогенные признаки</span><span class="pending">НУЖНЫ ДАННЫЕ</span></div><div class="data-line"><span>Тестовая выборка · 2023–2024</span><span class="sealed">ЗАКРЫТА</span></div><p>Исторический слой — исходные детекции номинальной и высокой уверенности, до выделения событий и удаления промышленных источников. Количество детекций не равно количеству пожаров.</p><p>Границы областей соответствуют источнику 2017 года. <a href="https://www.geoboundaries.org/" target="_blank" rel="noopener">geoBoundaries / OSM, ODbL</a> · <a href="https://firms.modaps.eosdis.nasa.gov/" target="_blank" rel="noopener">NASA FIRMS</a></p>`)}
function methodDialog(){if(manifest?.ready){showDialog(t('dlg.method'),methodology(manifest),methodDialog);return}showDialog('МЕТОДИКА', `<h2>Прогноз начинается<br>с конкретного места.</h2><div class="method-step"><b>01</b><div><strong>Ячейка 5 × 5 км</strong><p>Равновеликая сетка в проекции LAEA. Прибрежные ячейки обрезаны по национальной границе; в карточке указана их фактическая площадь.</p></div></div><div class="method-step"><b>02</b><div><strong>Вероятность нового очага за сутки</strong><p>Цель исследования — первое обнаружение нового природного пожара на следующие сутки. Это вероятность возникновения, без оценки ущерба или экспозиции.</p></div></div><div class="method-step"><b>03</b><div><strong>Проверка на будущих данных</strong><p>2015–2021 — обучение и временная валидация. 2022 — калибровка. Данные 2023–2024 остаются закрытыми до финальной оценки.</p></div></div><div class="method-step"><b>04</b><div><strong>Сейчас: демонстрация интерфейса</strong><p>Поле вероятностей создано иллюстративной формулой. Дата меняет условный сценарий, факторы — условные индексы. Здесь нет результатов обученной национальной модели, реального прогноза погоды или SHAP-объяснений. Шкала и порог 5% заданы для демонстрации.</p></div></div>`)}

function scenario(cell,day){
  const t=Date.parse(day+'T00:00:00Z')/86400000, season=.35+.65*Math.pow(Math.sin((new Date(day+'T00:00:00Z').getUTCMonth()+.3)/12*Math.PI),2);
  const x=(cell.col+.5)*5,y=(cell.row+.5)*5;
  const bump=(cx,cy,sx,sy)=>Math.exp(-((x-cx)**2/(sx*sx)+(y-cy)**2/(sy*sy)));
  const wave=(Math.sin(x/85+t*.12)*Math.cos(y/103-t*.08)+1)/2;
  const dryness=Math.min(1,.2+.48*bump(-140,200,600,380)+.38*bump(750,300,440,280)+.18*wave);
  const heat=Math.min(1,.2+.55*bump(80,-120,800,600)+.23*wave);
  const wind=(Math.sin(x/230+y/190+t*.31)+1)/2;
  const p=(.001+.084*bump(-180+100*Math.sin(t*.05),220,540,280)+.069*bump(800,350,380,300)+.034*bump(-990,400,300,270)+.023*bump(400,-400,360,180))*(.54+.46*wave)*season;
  return {p:Math.min(.12,p),factors:[dryness,heat,wind]};
}
function makeRaster(){
  raster=document.createElement('canvas');raster.width=593;raster.height=332;
  const rctx=raster.getContext('2d'), image=rctx.createImageData(593,332);
  const rgb=colors.map(c=>[parseInt(c.slice(1,3),16),parseInt(c.slice(3,5),16),parseInt(c.slice(5,7),16)]);
  const hist=state.layer==='history',bounds=hist?HISTORY_BOUNDS:forecastBounds(),classCounts=new Array(7).fill(0);
  const totals=new Array(16).fill(0), sizes=new Array(16).fill(0);let high=0,max=0,active=0,total=0,finite=0;
  values=new Float32Array(cells.length);
  // Over the satellite image the two lowest classes (93% of cells) stay clear, higher classes grow opaque.
  const sat=state.basemap==='satellite'&&satellite,alpha=sat?(hist?[170,185,200,215,230,245,250]:[0,0,165,200,225,240,250]):null;
  const paint=(c,color,a)=>{const pos=((166-c.row)*593+(c.col+300))*4;image.data[pos]=color[0];image.data[pos+1]=color[1];image.data[pos+2]=color[2];image.data[pos+3]=state.region>=0&&c.region!==state.region?Math.round(a*.27):a};
  for(let i=0;i<cells.length;i++){
    const c=cells[i];let p;
    if(hist){p=history[i*8+state.year-2015];values[i]=p;total+=p;if(p>0)active++;max=Math.max(max,p);totals[c.region]+=p;sizes[c.region]++;}
    else {p=state.mode==='demo'?scenario(c,state.day).p:isHeat(i)?NaN:(state.realValues?.[i]??NaN);values[i]=p;if(Number.isFinite(p)){finite++;max=Math.max(max,p);if(p>=riskThreshold())high++;totals[c.region]+=p;sizes[c.region]++;}}
    if(!hist&&state.mode==='real'&&!state.realValues)continue;
    if(!Number.isFinite(p)){if(sat&&!hist)paint(c,[200,203,196],170);continue}
    if(hist&&p===0)continue;
    const k=classOf(p,bounds);classCounts[k]++;
    // Filtered-out cells are plain land (or clear over the image), so the hatch keeps meaning "no data".
    if(!hist&&state.highOnly&&p<riskThreshold()){if(!sat)paint(c,LAND,245);continue}
    paint(c,rgb[k],sat?alpha[k]:245);
  }
  rctx.putImageData(image,0,0);
  if(state.layer==='history'){
    $('stat-one-label').textContent=t('stat.detections');$('stat-cells').textContent=nf.format(total);$('stat-cells-unit').textContent=t('stat.year',{year:state.year});
    $('stat-two-label').textContent=t('stat.cellsWith');$('stat-high').textContent=nf.format(active);$('stat-high-unit').textContent=t('unit.cell');
    $('stat-three-label').textContent=t('stat.cellMax');$('stat-max').textContent=nf.format(max);$('stat-max-unit').textContent=t('stat.perYear');
  }else{
    $('stat-one-label').textContent=t(state.mode==='real'?'stat.cellsForecast':'stat.cellsMap');$('stat-cells').textContent=nf.format(state.mode==='real'?finite:cells.length);$('stat-cells-unit').textContent=state.mode==='real'?t('stat.of',{n:nf.format(cells.length)}):t('unit.cell');
    $('stat-two-label').textContent=t('stat.above',{t:pf(riskThreshold())});$('stat-high').textContent=state.mode==='real'&&(!state.realValues||finite===0)?'—':nf.format(high);$('stat-high-unit').textContent=t(state.mode==='demo'?'stat.demoCells':'stat.cells');
    $('stat-three-label').textContent=t('stat.max');$('stat-max').textContent=state.mode==='real'&&(!state.realValues||finite===0)?'—':pf(max);$('stat-max-unit').textContent=t(state.mode==='demo'?'stat.illustrative':'stat.probability');
  }
  state.regionStats=totals.map((v,i)=>state.layer==='history'?v:sizes[i]?v/sizes[i]:NaN);
  renderLegend(bounds,!hist&&state.mode==='real'&&!state.realValues?null:classCounts);
  renderRegions();renderPoints();updateCell();scheduleDraw();syncRelief();if(state.detail>=0)detail?.refresh(detailData());
}
function renderPoints(){
  const on=pointsActive();$('points-group').hidden=!on;$('points-legend').hidden=!on;if(!on){relief?.setMarkers([]);return}
  const pred=predictedCells(),obs=dayEvents(),hits=obs.filter(e=>e.hit).length,covered=obs.filter(e=>e.covered).length;
  $('points-summary').innerHTML=t('points.summary',{pred:nf.format(pred.length),obs:events?nf.format(obs.length):'…',hits:events?nf.format(hits):null});
  $('points-summary').title=events?t('points.summary.title',{n:nf.format(covered)}):'';
  const label=i=>regionName(geo.regions[cells[i].region],'abbr');
  const hitCells=new Set(obs.filter(e=>e.hit).map(e=>e.cell));
  $('points-list').replaceChildren(...pred.slice(0,12).map(i=>{const b=document.createElement('button');b.className='point-item';b.innerHTML=`<i class="mk mk-pred${hitCells.has(i)?' is-hit':''}"></i><span><b>${label(i)}</b><small>${coords(cells[i].lat,cells[i].lon,2)}${hitCells.has(i)?' · '+t('points.confirmed'):''}</small></span><span class="point-value">${pf(values[i])}</span>`;b.onclick=()=>openDetail(i);b.title=t('points.open');return b}));
  if(pred.length>12){const p=document.createElement('p');p.className='blank-list';p.textContent=t('points.more',{n:nf.format(pred.length-12)});$('points-list').append(p)}
  relief?.setMarkers(state.showObserved?obs.map(e=>({x:e.x,y:e.y,hit:e.hit})):[]);
}
// Satellite detail view: zoomable Esri / Sentinel-2 tiles of one place. Loads on first use.
let detail=null,detailRequest=null,allEventsCache=null;
function allEvents(){
  if(!events||!manifest?.ready)return [];
  if(!allEventsCache){allEventsCache=[];for(const [d,list] of events)for(const e of list){if(isHeat(e.cell))continue;const date=manifest.available_days[d];allEventsCache.push({...e,date:df.format(new Date(date+'T00:00:00Z')).replace(' г.',''),year:+date.slice(0,4)})}}
  return allEventsCache;
}
function detailData(){
  const hist=state.layer==='history',real=pointsActive();
  return {values,layer:state.layer,colors,history,classOf:v=>classOf(v,hist?HISTORY_BOUNDS:forecastBounds()),alertAt:real?riskThreshold():null,alerts:real?predictedCells():[],
    dayEvents:dayEvents(),allEvents:state.mode==='real'?allEvents():[],format:v=>hist?nf.format(v):pf(v),dayLabel:df.format(new Date(state.day+'T00:00:00Z')).replace(' г.',''),
    showPast:$('detail-past').checked,showPredicted:state.showPredicted,showObserved:state.showObserved};
}
async function openDetail(i){
  if(!detail){
    $('loading').hidden=false;$('loading').lastElementChild.textContent=t('loading.detail');
    try{detailRequest=detailRequest||import('./detail.js?v=20261105-da').then(({createDetail})=>createDetail({host:$('map-shell'),geo,cells,onSelect:selectCell}));detail=await detailRequest}
    catch(error){detailRequest=null;console.error('Detail view unavailable',error);toast(t('toast.noDetail',{e:error.message}));return}
    finally{syncLayer()}
  }
  state.detail=i;$('map-shell').classList.add('is-detail');$('detail-bar').hidden=false;$('detail-legend').hidden=false;
  detailHeading(i);
  detail.refresh(detailData());detail.open(i);selectCell(i);
}
function detailHeading(i){const c=cells[i];$('detail-title').textContent=regionName(geo.regions[c.region],'long');$('detail-sub').textContent=t('detail.sub',{c:coords(c.lat,c.lon,3)})}
function closeDetail(){state.detail=-1;detail?.close();$('map-shell').classList.remove('is-detail');$('detail-bar').hidden=true;$('detail-legend').hidden=true;scheduleDraw()}
function focusCell(i){
  const c=cells[i];
  if(state.view==='3d'){relief.flyTo((c.col+.5)*5,-(c.row+.5)*5)}
  else{state.zoom=4;const s=baseScale*state.zoom;state.panX=-((c.col+.5)*5-centerX)*s;state.panY=-(-(c.row+.5)*5-centerY)*s}
  selectCell(i);
}
function drawPoints(v){
  if(!pointsActive())return;
  const at=(x,y)=>[x*v.s+v.x,y*v.s+v.y],r=Math.max(4,Math.min(9,3+v.s*4));
  if(state.showObserved)for(const e of dayEvents()){const [x,y]=at(e.x,e.y);if(x<-10||y<-10||x>width+10||y>height+10)continue;ctx.beginPath();ctx.moveTo(x,y-r);ctx.lineTo(x+r,y);ctx.lineTo(x,y+r);ctx.lineTo(x-r,y);ctx.closePath();ctx.fillStyle=e.hit?'#ffd166':'#fffefa';ctx.fill();ctx.lineWidth=1.6;ctx.strokeStyle='#193d35';ctx.stroke()}
  if(state.showPredicted)for(const i of predictedCells()){const c=cells[i],[x,y]=at((c.col+.5)*5,-(c.row+.5)*5);ctx.beginPath();ctx.arc(x,y,r+3,0,Math.PI*2);ctx.lineWidth=3;ctx.strokeStyle='#fffefa';ctx.stroke();ctx.lineWidth=2;ctx.strokeStyle=colors[6];ctx.stroke();ctx.beginPath();ctx.arc(x,y,2.5,0,Math.PI*2);ctx.fillStyle=colors[6];ctx.fill()}
}
function renderLegend(bounds,counts){
  const hist=state.layer==='history',real=state.mode==='real'&&manifest?.ready;
  $('legend-title').textContent=hist?t('legend.title.history',{year:state.year}):t(real&&isV7(manifest)?'legend.title.v7':real&&isDayAhead(manifest)?'legend.title.v6da':real&&isV6(manifest)?'legend.title.v6':'legend.title')+(state.mode==='demo'?t('legend.demo'):'');
  $('legend-ticks').innerHTML=(hist?['1',...bounds.map((b,i)=>i===bounds.length-1?b+'+':String(b))]:['0',...bounds.map(pct)]).map(t=>`<span>${t}</span>`).join('');
  $('legend-threshold').hidden=hist;
  $('legend-counts').innerHTML=counts?counts.map(n=>`<span>${nf.format(n)}</span>`).join(''):'';
  $('legend-counts').title=t('legend.counts');
  $('legend-note').textContent=hist?t('legend.note.history'):real?t('legend.note.real',{t:pf(riskThreshold()),sat:state.basemap==='satellite'&&!!satellite})+(isV7(manifest)?' '+t('legend.note.v7'):isV6(manifest)?' '+t('legend.note.v6'):''):t('legend.note.demo',{t:pf(riskThreshold())});
}
function syncRelief(){
  if(!relief||state.view!=='3d')return;
  const hist=state.layer==='history',t=riskThreshold();
  relief.setValues(values,{bounds:hist?HISTORY_BOUNDS:forecastBounds(),k0:hist?.55:.22,alertAt:hist||!state.showPredicted?null:t,hidden:(i,v)=>(hist&&v===0)||(!hist&&state.highOnly&&v<t)||(state.region>=0&&cells[i].region!==state.region)});
  relief.setLines(state.lines);
  relief.setSelected($('cell-card').hidden?-1:state.selected);
}
let reliefRequest=null;
// The GPU can drop the WebGL context (sleep, driver reset); go back to 2D and rebuild 3D on the next click.
function reliefLost(){relief=null;reliefRequest=null;if(state.view==='3d'){setView('2d');toast(t('toast.3dlost'))}}
async function setView(view){
  if(!geo)return;
  if(view==='3d'&&!relief){
    $('view-3d').disabled=true;
    $('loading').hidden=false;$('loading').lastElementChild.textContent=t('loading.relief');
    try{
      reliefRequest=reliefRequest||import('./relief3d.js?v=20261105-da').then(({createRelief})=>createRelief({host:$('map-shell'),geo,cells,onPick:i=>{if(i>=0)selectCell(i);else{state.selected=-1;updateCell();syncRelief()}},onLost:reliefLost}));
      relief=await reliefRequest;
      if(satellite)relief.setSatellite(satellite.img,satellite.extent);
      relief.setBasemap(state.basemap==='satellite'&&!!satellite);renderPoints();
    }catch(error){
      reliefRequest=null;console.error('3D unavailable',error);toast(t('toast.no3d',{e:error.message}));view='2d';
    }finally{$('view-3d').disabled=false;syncLayer()}
  }
  state.view=view;
  for(const v of ['2d','3d'])$('view-'+v).setAttribute('aria-pressed',String(view===v));
  $('map-shell').classList.toggle('is-3d',view==='3d');
  $('relief-credit').hidden=view!=='3d';
  relief?.setVisible(view==='3d');
  syncLayer();
  if(view==='3d')syncRelief();else scheduleDraw();
}
// Zoomed in, the 1 km basemap blurs. Esri World Imagery tiles (Web Mercator) are then warped onto
// the equal-area map one tile at a time with an affine transform from three projected corners;
// across one 256 px tile the projection is linear to well under a pixel. Needs the network;
// without it the 1 km image stays underneath.
const TILE_MIN_SCALE=1.2,tileCache=new Map();let laea=null,laeaRequest=null,tilesShown=false;
function loadLaea(){return laeaRequest||=new Promise((resolve,reject)=>{const s=document.createElement('script');s.src='./vendor/proj4.js';s.onload=()=>{laea=window.proj4('+proj=laea +lat_0=48 +lon_0=67 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs','EPSG:4326');resolve();scheduleDraw()};s.onerror=reject;document.head.append(s)}).catch(e=>console.warn('Projection unavailable',e))}
function tileImage(z,x,y){
  const key=`${z}/${x}/${y}`;let img=tileCache.get(key);
  if(!img){img=new Image();img.onload=scheduleDraw;img.src=`https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y}/${x}`;tileCache.set(key,img);if(tileCache.size>400)tileCache.delete(tileCache.keys().next().value)}
  return img;
}
function drawTiles(v,dpr){
  if(v.s<TILE_MIN_SCALE)return false;
  if(!laea){loadLaea();return false}
  const screen=(lon,lat)=>{const [mx,my]=laea.inverse([lon,lat]);return [mx/1000*v.s+v.x,-my/1000*v.s+v.y]};
  const corners=[[0,0],[width,0],[0,height],[width,height]].map(([sx,sy])=>{const [wx,wy]=toWorld(sx,sy);return laea.forward([wx*1000,-wy*1000])});
  const lons=corners.map(c=>c[0]),lats=corners.map(c=>c[1]),latc=(Math.min(...lats)+Math.max(...lats))/2;
  // Level 17 (about 1 m) has imagery across the country; deeper levels are often blank in the steppe.
  const z=Math.max(5,Math.min(17,Math.round(Math.log2(156543.03*Math.cos(latc*Math.PI/180)*v.s*dpr/1000))));
  const n=2**z,tx=lon=>Math.floor((lon+180)/360*n),ty=lat=>{const r=lat*Math.PI/180;return Math.floor((1-Math.log(Math.tan(r)+1/Math.cos(r))/Math.PI)/2*n)};
  const lonOf=x=>x/n*360-180,latOf=y=>Math.atan(Math.sinh(Math.PI*(1-2*y/n)))*180/Math.PI;
  const x0=tx(Math.min(...lons)),x1=tx(Math.max(...lons)),y0=ty(Math.max(...lats)),y1=ty(Math.min(...lats));
  if((x1-x0+1)*(y1-y0+1)>160)return false;
  ctx.save();
  for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){
    // Until a tile arrives, stretch the matching part of a cached coarser tile over its place.
    let img=tileImage(z,x,y),sx=0,sy=0,sw=256;
    for(let d=1;d<=5&&(!img.complete||!img.naturalWidth);d++){const up=tileCache.get(`${z-d}/${x>>d}/${y>>d}`);if(up?.complete&&up.naturalWidth){img=up;sw=256/2**d;sx=(x-((x>>d)<<d))*sw;sy=(y-((y>>d)<<d))*sw}}
    if(!img.complete||!img.naturalWidth)continue;
    const [ax,ay]=screen(lonOf(x),latOf(y)),[bx,by]=screen(lonOf(x+1),latOf(y)),[cx,cy]=screen(lonOf(x),latOf(y+1));
    ctx.setTransform(dpr*(bx-ax)/256,dpr*(by-ay)/256,dpr*(cx-ax)/256,dpr*(cy-ay)/256,dpr*ax,dpr*ay);
    ctx.drawImage(img,sx,sy,sw,sw,0,0,256.6,256.6);
  }
  ctx.restore();
  return true;
}
// Thin 5 km cell borders for close zoom, only for the cells in view.
function drawCellOutlines(v){
  const [wx0,wy0]=toWorld(0,0),[wx1,wy1]=toWorld(width,height);
  const c0=Math.floor(wx0/5),c1=Math.ceil(wx1/5),r0=Math.floor(-wy1/5),r1=Math.ceil(-wy0/5);
  if((c1-c0)*(r1-r0)>4000)return;
  ctx.lineWidth=1/v.s;ctx.strokeStyle='rgba(255,254,250,.4)';ctx.beginPath();
  for(let r=r0;r<=r1;r++)for(let c=c0;c<=c1;c++){if(cellByKey.get(`${r},${c}`)===undefined)continue;ctx.rect(c*5,-(r+1)*5,5,5)}
  ctx.stroke();
}
function scheduleDraw(){cancelAnimationFrame(renderFrame);renderFrame=requestAnimationFrame(draw)}
function draw(){
  const dpr=Math.min(devicePixelRatio||1,2),v=view();
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
  const sat=state.basemap==='satellite'&&satellite;
  ctx.save();ctx.translate(v.x,v.y);ctx.scale(v.s,v.s);
  if(sat){
    // The image covers neighbouring countries too: show them washed out, Kazakhstan at full colour.
    const e=satellite.extent;ctx.imageSmoothingEnabled=true;
    ctx.drawImage(satellite.img,e.x0,e.y0,e.x1-e.x0,e.y1-e.y0);ctx.fillStyle='rgba(246,247,241,.55)';ctx.fillRect(e.x0,e.y0,e.x1-e.x0,e.y1-e.y0);
    ctx.save();ctx.clip(boundary,'evenodd');ctx.drawImage(satellite.img,e.x0,e.y0,e.x1-e.x0,e.y1-e.y0);ctx.restore();
    tilesShown=drawTiles(v,dpr);
    if(tilesShown){const outside=new Path2D();outside.rect(-3500,-2500,7000,5000);outside.addPath(boundary);ctx.fillStyle='rgba(246,247,241,.5)';ctx.fill(outside,'evenodd')}
  }else{
    tilesShown=false;
    // Quiet cartographic reference grid, independent of the study cell lattice.
    ctx.lineWidth=.6/v.s;ctx.strokeStyle='#e1e6d7';
    for(let x=-3500;x<3500;x+=250){ctx.beginPath();ctx.moveTo(x,-2500);ctx.lineTo(x,2500);ctx.stroke()}
    for(let y=-2500;y<2500;y+=250){ctx.beginPath();ctx.moveTo(-3500,y);ctx.lineTo(3500,y);ctx.stroke()}
    // Under real forecasts, any cell left unpainted has no prediction: show it hatched, not blank.
    const missingVisible=state.layer==='forecast'&&state.mode==='real'&&state.realValues;
    if(missingVisible&&!hatch){const h=document.createElement('canvas');h.width=h.height=8;const g=h.getContext('2d');g.fillStyle='#e3e6dc';g.fillRect(0,0,8,8);g.strokeStyle='#c9cec1';g.lineWidth=2;g.beginPath();g.moveTo(-2,10);g.lineTo(10,-2);g.stroke();hatch=ctx.createPattern(h,'repeat')}
    if(missingVisible)hatch.setTransform(new DOMMatrix().scale(1/v.s));
    ctx.fillStyle=missingVisible?hatch:`rgb(${LAND})`;ctx.strokeStyle='#c0cbb0';ctx.lineWidth=1.2/v.s;ctx.fill(boundary,'evenodd');ctx.stroke(boundary);
  }
  // Over sharp tiles the forecast is a light veil with cell outlines, so the ground stays readable.
  ctx.save();ctx.clip(boundary,'evenodd');ctx.imageSmoothingEnabled=false;if(tilesShown)ctx.globalAlpha=Math.max(.12,Math.min(.42,4/v.s));if(raster)ctx.drawImage(raster,-1500,-835,2965,1660);ctx.restore();
  if(tilesShown&&v.s>8)drawCellOutlines(v);
  $('satellite-credit').textContent=t(tilesShown?'credit.esri':'credit.nasa');
  if(state.lines){ctx.lineWidth=(sat?.8:.6)/v.s;ctx.strokeStyle=sat?'rgba(255,254,250,.55)':'#7f946b77';for(let i=0;i<regionPaths.length;i++){if(i===state.region){ctx.fillStyle='#ffffff10';ctx.fill(regionPaths[i],'evenodd')}ctx.stroke(regionPaths[i])}}
  ctx.lineWidth=(sat?1.6:1)/v.s;ctx.strokeStyle=sat?'#fffefa':'#aebd98';ctx.stroke(boundary);
  if(state.region>=0){ctx.lineWidth=1.7/v.s;ctx.strokeStyle=sat?'#fffefa':'#627e50';ctx.stroke(regionPaths[state.region])}
  ctx.restore();
  drawPoints(v);
  ctx.textAlign='left';ctx.textBaseline='middle';
  for(const city of geo.cities){const x=city.x*v.s+v.x,y=city.y*v.s+v.y;if(x<12||x>width-20||y<20||y>height-35)continue;
    ctx.beginPath();ctx.arc(x,y,city.name==='Астана'?3.5:2.8,0,Math.PI*2);ctx.fillStyle='#fffefa';ctx.fill();ctx.strokeStyle='#193d35';ctx.lineWidth=1.4;ctx.stroke();
    ctx.font=`${city.name==='Астана'?'600':'500'} ${state.zoom>1.5?13:12}px 'Golos Text','Segoe UI',sans-serif`;ctx.lineWidth=3.5;ctx.strokeStyle='#fffefaee';const name=cityName(city.name);ctx.strokeText(name,x+8,y-.5);ctx.fillStyle='#193d35';ctx.fillText(name,x+8,y-.5);
  }
  if(state.selected>=0&&!$('cell-card').hidden){const c=cells[state.selected],x=(c.col+.5)*5*v.s+v.x,y=-(c.row+.5)*5*v.s+v.y;ctx.beginPath();ctx.arc(x,y,9,0,Math.PI*2);ctx.strokeStyle='#fffefb';ctx.lineWidth=5;ctx.stroke();ctx.strokeStyle='#193d35';ctx.lineWidth=1.8;ctx.stroke();ctx.fillStyle='#193d35';ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fill();}
  const span=64/v.s,km=Math.round(span/50)*50;$('scale-label').textContent=km?t('scale.km',{n:km}):span>=1?t('scale.km',{n:Math.round(span)}):t('scale.m',{n:Math.max(1,Math.round(span*1000/10)*10)});
}
function resize(){const r=canvas.getBoundingClientRect();width=r.width;height=r.height;const dpr=Math.min(devicePixelRatio||1,2);canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);const narrow=width<600;baseScale=Math.min((width-(narrow?16:80))/2965,(height-(narrow?150:200))/1660);scheduleDraw()}
function allowedDate(day){return /^\d{4}-\d{2}-\d{2}$/.test(day)&&(state.mode==='real'&&manifest?.ready?manifest.available_days.includes(day):day>='2015-01-01'&&day<='2022-12-31')}
function setDate(day){if(!allowedDate(day)){toast(t(state.mode==='real'&&manifest?.ready?'toast.noForecastDate':'toast.demoRange'));$('forecast-date').value=state.day;return}state.day=day;$('forecast-date').value=day;renderTimeline();if(geo){if(state.mode==='real')setMode('real');else{syncLayer();makeRaster()}}}
function renderTimeline(){const d=new Date(state.day+'T00:00:00Z'),wrap=$('timeline-days');wrap.replaceChildren();for(let n=-3;n<=3;n++){const date=new Date(d);date.setUTCDate(date.getUTCDate()+n);const iso=date.toISOString().slice(0,10);if(!allowedDate(iso))continue;const b=document.createElement('button');b.className='timeline-day'+(n===0?' active':'');b.innerHTML=`<span>${weekday(date)}</span><strong>${date.getUTCDate()}</strong>`;b.setAttribute('aria-label',df.format(date));b.setAttribute('aria-pressed',String(n===0));b.onclick=()=>setDate(iso);wrap.append(b)}const real=state.mode==='real'&&manifest?.ready;$('previous-day').disabled=real?manifest.available_days.indexOf(state.day)<=0:state.day==='2015-01-01';$('next-day').disabled=real?manifest.available_days.indexOf(state.day)>=manifest.available_days.length-1:state.day==='2022-12-31'}
function changeDay(delta){if(state.mode==='real'&&manifest.ready){const days=manifest.available_days,day=days[days.indexOf(state.day)+delta];if(day)setDate(day);return}const d=new Date(state.day+'T00:00:00Z');d.setUTCDate(d.getUTCDate()+delta);setDate(d.toISOString().slice(0,10))}
function renderRegions(){const query=$('region-search').value.toLowerCase(),list=$('region-list');list.replaceChildren();const sorted=geo.regions.map((r,i)=>({...r,i})).filter(r=>(regionName(r)+' '+r.label+' '+r.name).toLowerCase().includes(query)).sort((a,b)=>(state.regionStats?.[b.i]||0)-(state.regionStats?.[a.i]||0));$('region-count').textContent=sorted.length;for(const r of sorted){const b=document.createElement('button');b.className='region-item'+(state.region===r.i?' selected':'');b.innerHTML=`<span class="region-circle"></span><span>${regionName(r)}</span><span class="region-value">${state.layer==='history'?nf.format(state.regionStats[r.i]):Number.isFinite(state.regionStats[r.i])?pf(state.regionStats[r.i]):'—'}</span>`;b.setAttribute('aria-label',t('regions.show',{name:regionName(r)}));b.onclick=()=>selectRegion(r.i);list.append(b)}if(!sorted.length){const p=document.createElement('p');p.className='blank-list';p.textContent=t('regions.none');list.append(p)}}
function selectRegion(index){state.region=index;state.selected=-1;let best=-1;for(let i=0;i<cells.length;i++)if(cells[i].region===index&&Number.isFinite(values[i])&&(best<0||values[i]>values[best]))best=i;if(best>=0){const c=cells[best];state.zoom=2;const s=baseScale*state.zoom;state.panX=-( (c.col+.5)*5-centerX)*s-width*.12;state.panY=-(-(c.row+.5)*5-centerY)*s;selectCell(best)}makeRaster()}
function selectCell(index){state.selected=index;updateCell();scheduleDraw();relief?.setSelected($('cell-card').hidden?-1:index)}
function updateCell(){
  if(state.selected<0||state.mode==='real'&&state.layer==='forecast'&&(!state.realValues||state.noEligibleForecast)){$('cell-card').hidden=true;return}
  const c=cells[state.selected],p=values[state.selected];$('cell-card').hidden=false;$('cell-region').textContent=regionName(geo.regions[c.region],'long');$('cell-coordinates').textContent=coords(c.lat,c.lon,3);$('cell-area').textContent=t('unit.km2',{n:num(c.area,{maximumFractionDigits:2})});$('cell-id').textContent=`g5000_${c.row}_${c.col}`;$('cell-elevation').textContent=relief?t('card.elevation',{n:nf.format(Math.round(relief.elevation[state.selected]))}):'';
  const hist=state.layer==='history',real=state.mode==='real'&&!hist;$('cell-probability').textContent=hist?nf.format(p):Number.isFinite(p)?pf(p):'—';$('cell-category').textContent=hist?t('card.hist.cat',{year:state.year}):real?t(Number.isFinite(p)?(isV6(manifest)&&!isV7(manifest)?'card.rank':'card.cal'):'card.nofc'):t(p>=.05?'card.demo.high':p>=.02?'card.demo.elev':p>=.005?'card.demo.mod':'card.demo.low');$('cell-category').style.whiteSpace='pre-line';$('probability-meter').style.width=(Number.isFinite(p)&&(!hist||p>0)?(classOf(p,hist?HISTORY_BOUNDS:forecastBounds())+1)/7*100:0)+'%';$('cell-context').textContent=t(hist?'card.ctx.hist':real?'card.ctx.real':'card.ctx.demo');$('factor-title').textContent=t(hist?'card.f.hist':real?'card.f.real':'card.f.demo');$('card-disclaimer').textContent=t(hist?'card.disc.hist':real?'card.disc.real':'card.disc.demo');
  const wrap=$('cell-factors');wrap.replaceChildren();
  if(real&&isHeat(state.selected)&&state.realValues){const raw=state.realValues[state.selected];$('cell-probability').textContent=Number.isFinite(raw)?pf(raw):'—';$('cell-category').textContent=t('card.heat');const note=document.createElement('p');note.className='empty-history caution-note';note.textContent=t('card.heat.note',{n:nf.format(Math.min(...Array.from({length:8},(_,y)=>history[state.selected*8+y])))});wrap.append(note);return}
  if(real){const note=document.createElement('p');note.className='empty-history';const profile=activeProfile(manifest,state.alertProfile);note.textContent=t('card.source',{model:modelLabel(manifest.model),day:state.day,profile:profile.label,t:probability(profile.threshold),inputs:modelInputs(manifest)});wrap.append(note);if(isV6(manifest)){const caution=document.createElement('p');caution.className='empty-history caution-note';caution.textContent=isV7(manifest)?t('card.v7warn'):t('card.v6warn')+(state.day.startsWith('2026')||manifest.live_days?.includes(state.day)?'':' '+t('card.v6cont'));wrap.append(caution)}if(events&&pointsActive()){const n=dayEvents().filter(e=>e.cell===state.selected).length,seen=document.createElement('p');seen.className='empty-history seen-note';seen.textContent=n?t('card.seen.yes',{n}):t('card.seen.no');wrap.append(seen)}const selected=state.selected;populationNote(`g5000_${c.row}_${c.col}`).then(text=>{if(state.selected===selected&&state.mode==="real"&&text&&!wrap.querySelector(".pop-note")){const exposure=document.createElement("p");exposure.className="empty-history pop-note";exposure.textContent=text;wrap.append(exposure)}}).catch(()=>{});if(Number.isFinite(p))$('cell-category').textContent=t(p>=riskThreshold()?'card.alert':'card.below');return}
  const historyYears=[state.year-1,state.year,state.year+1].filter(y=>y>=2015&&y<=2022);
  const factors=hist?historyYears.map(y=>[String(y),history[state.selected*8+y-2015],Math.max(1,...historyYears.map(z=>history[state.selected*8+z-2015]))]):[t('factor.dry'),t('factor.heat'),t('factor.wind')].map((name,j)=>[name,Math.round(scenario(c,state.day).factors[j]*100),100]);
  for(const [name,n,max] of factors){const row=document.createElement('div');row.className='factor';row.innerHTML=`<span>${name}</span><span class="factor-track"><i style="width:${n/max*100}%"></i></span><span class="factor-value">${n}</span>`;wrap.append(row)}
}
let forecastRequest=0;
async function setMode(mode){
  if(!geo)return;
  const request=++forecastRequest;
  state.mode=mode;state.realValues=null;state.noEligibleForecast=false;state.forecastError=null;
  const days=manifest.available_days||[],ready=mode==='real'&&manifest.ready;
  state.loadingForecast=ready;
  if(!allowedDate(state.day))state.day=ready?days[0]:'2022-07-15';
  $('forecast-date').min=ready?days[0]:'2015-01-01';
  $('forecast-date').max=ready?days.at(-1):'2022-12-31';
  $('forecast-date').value=state.day;renderTimeline();
  for(const kind of ['demo','real']){
    $(kind+'-mode').classList.toggle('selected',mode===kind);
    $(kind+'-mode').setAttribute('aria-pressed',String(mode===kind));
  }
  syncNote();
  syncLayer();makeRaster();
  if(!ready)return;
  const day=state.day;
  try{
    const probabilities=await loadForecast(day,manifest,cells.length);
    if(request!==forecastRequest)return;
    state.realValues=probabilities;state.noEligibleForecast=!probabilities.some(Number.isFinite);state.loadingForecast=false;state.autoReal=false;state.payloadMissing=false;
    syncLayer();makeRaster();
  }catch(error){
    if(request!==forecastRequest)return;
    console.error('Forecast verification failed',error);
    state.loadingForecast=false;state.forecastError=error.message;
    // Daily payloads are not in Git, so a fresh checkout has none: open the demo instead of an error.
    if(error.message==='Forecast unavailable'){state.payloadMissing=true;if(state.autoReal){state.autoReal=false;setMode('demo');return}}
    state.autoReal=false;syncLayer();
  }
}
function syncNote(){const v6=state.mode==='real'&&isV6(manifest);$('mode-note').className='note '+(state.mode==='demo'?'is-demo':v6?'is-caution':manifest.ready?'is-verified':'');$('mode-note').innerHTML=t(state.mode==='demo'?(state.payloadMissing?'note.demo.missing':'note.demo'):v6?(isV7(manifest)?'note.real.v7':manifest.live_days?.includes(state.day)?'note.real.live':state.day.startsWith('2026')?'note.real.v6':'note.real.v6.cont'):manifest.ready?'note.real':'note.pending')}
function syncLayer(){
  const hist=state.layer==='history',empty=state.mode==='real'&&state.noEligibleForecast&&!hist,unavailable=state.mode==='real'&&(!state.realValues||empty)&&!hist;
  const loading=unavailable&&state.loadingForecast;
  $('forecast-layer').classList.toggle('selected',!hist);
  $('history-layer').classList.toggle('selected',hist);
  $('forecast-layer').setAttribute('aria-pressed',String(!hist));
  $('history-layer').setAttribute('aria-pressed',String(hist));
  $('history-options').hidden=!hist;$('model-row').hidden=!(state.mode==='real'&&!hist&&manifests.v6&&manifests.v5);$('detail-l-2026').hidden=!isV6(manifest);$('high-only-row').hidden=hist;$('heat-row').hidden=hist||state.mode!=='real';$('timeline').hidden=hist;
  $('map-empty').hidden=!unavailable||loading;$('loading').hidden=!loading;
  if(loading)$('loading').lastElementChild.textContent=t('loading.forecast');
  $('map-empty').classList.toggle('is-danger',!empty&&!state.payloadMissing);
  const emptyKind=empty?'empty':state.payloadMissing?'missing':manifest.ready?'failed':'pending';$('map-empty').querySelector('strong').textContent=t('empty.title.'+emptyKind);
  $('map-empty').querySelector('p').textContent=t('empty.text.'+emptyKind);
  $('map-intro').textContent=t(hist?'map.intro.history':'map.intro');
  $('map-title').innerHTML=hist?t('map.title.history',{year:state.year}):t('map.title',{date:df.format(new Date(state.day+'T00:00:00Z'))});
  $('map-badge').textContent=t(hist?'badge.history':state.mode==='demo'?'badge.demo':empty?'badge.empty':state.realValues?'badge.verified':loading?'badge.loading':'badge.none');
  $('map-chip').className='chip'+(state.mode==='demo'&&!hist?' is-demo':state.realValues&&!hist?' is-verified':'');
  $('stat-source').textContent=hist?t('source.history'):state.mode==='demo'?t('source.demo'):state.realValues?t('source.real'):'';
  $('release').innerHTML=manifest.ready?t('release',{model:manifest.upgrade?t('model.stack'):modelLabel(manifest.model),hash:manifest.release_sha256.slice(0,8)}):'';
  syncProfile();
  $('threshold-label').textContent=t('highOnly',{t:pf(riskThreshold())});
  document.querySelector('.timeline-title strong').textContent=t(state.mode==='real'?'date.forecast':'date.scenario');
  $('forecast-date').setAttribute('aria-label',t(state.mode==='real'?'date.forecast.aria':'date.scenario.aria'));
  $('export-button').disabled=unavailable;
  $('map-hint').textContent=t(state.view==='3d'?'hint.3d':hist?'hint.history':'hint.map');
  $('holdout-button').textContent=t(manifest.ready?(isV7(manifest)?'checks.metricsTest.v7':isV6(manifest)?'checks.metricsTest.v6':'checks.metricsTest'):'checks.metrics');
}
function setLayer(layer){state.layer=layer;syncLayer();makeRaster()}
function zoomAt(factor,x=width/2,y=height/2){const [wx,wy]=toWorld(x,y);state.zoom=Math.max(.7,Math.min(4000,state.zoom*factor));const s=baseScale*state.zoom;state.panX=x-width/2-(wx-centerX)*s;state.panY=y-height/2-(wy-centerY)*s;scheduleDraw()}
function reset(){state.zoom=1;state.panX=0;state.panY=0;state.region=-1;relief?.reset();makeRaster()}
function download(){
  if(state.mode==='real'&&state.layer==='forecast'&&(!state.realValues||state.noEligibleForecast)){toast(t('toast.noForecast'));return}
  const hist=state.layer==='history',real=state.mode==='real'&&!hist;
  const header=hist?'cell_id,longitude,latitude,area_km2,region,year,viirs_detections,source\n':'cell_id,longitude,latitude,area_km2,region,target_day,probability,alert,threshold,profile,model_release_sha256,policy_sha256,synthetic\n';
  let text=header,rows=0;
  for(let i=0;i<cells.length;i++){
    const c=cells[i],p=values[i];if(state.region>=0&&c.region!==state.region)continue;
    if(!hist&&(state.highOnly&&p<riskThreshold()||!Number.isFinite(p)))continue;
    if(hist&&p===0)continue;
    text+=`g5000_${c.row}_${c.col},${c.lon.toFixed(5)},${c.lat.toFixed(5)},${c.area.toFixed(4)},${geo.regions[c.region].name},`+(hist?`${state.year},${p},NASA_FIRMS_SNPP_VIIRS`:`${state.day},${p.toPrecision(9)},${p>=riskThreshold()},${riskThreshold()},${real?isV6(manifest)?manifest.model.replace('xgboost_','model_'):manifest.upgrade?'model_v3':state.alertProfile||'original':'demo'},${real?manifest.release_sha256:''},${real?manifest.operating_policy?.policy_sha256||'':''},${!real}`)+'\n';rows++;
  }
  const url=URL.createObjectURL(new Blob(['\uFEFF',text],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=hist?`steppe_VIIRS_${state.year}.csv`:`steppe_${real?(isV6(manifest)?manifest.model.replace('xgboost_','model_'):manifest.upgrade?'model_v3':state.alertProfile)+'_':'DEMO_'}${state.day}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);toast(t('toast.exported',{n:nf.format(rows)}));
}

$('nav-data').onclick=dataDialog;$('nav-method').onclick=methodDialog;$('nav-map').onclick=e=>{e.preventDefault();if($('info-dialog').open)$('info-dialog').close();reset()};$('view-2d').onclick=()=>setView('2d');$('view-3d').onclick=()=>setView('3d');$('close-dialog').onclick=()=>$('info-dialog').close();$('info-dialog').addEventListener('click',e=>{if(e.target===$('info-dialog')){const r=$('info-dialog').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('info-dialog').close()}});$('holdout-button').onclick=holdoutDialog;function holdoutDialog(){manifest?.ready?showDialog(t('dlg.metrics'),evaluation(manifest),holdoutDialog):showDialog('ЗАКРЫТАЯ ТЕСТОВАЯ ВЫБОРКА','<h2>2023–2024 остаются закрытыми.</h2><p>Архивы скачаны и проверены по контрольным суммам. Наблюдения из этих файлов не прочитаны и не используются на карте, для выбора модели, калибровки или демонстрации.</p><p>Финальная оценка выполняется только после фиксации модели, признаков и порогов. В эту платформу включены исторические наблюдения только за 2015–2022 годы.</p>')}
$('demo-mode').onclick=()=>setMode('demo');$('real-mode').onclick=()=>setMode('real');$('return-demo').onclick=()=>setMode('demo');$('forecast-layer').onclick=()=>setLayer('forecast');$('history-layer').onclick=()=>setLayer('history');$('history-year').onchange=e=>{state.year=Number(e.target.value);syncLayer();makeRaster()};$('region-search').oninput=renderRegions;$('open-detail').onclick=()=>state.selected>=0&&openDetail(state.selected);$('close-detail').onclick=closeDetail;$('detail-past').onchange=()=>detail?.refresh(detailData());for(const [id,key] of [['detail-esri','esri'],['detail-s2','s2']])$(id).onclick=()=>{detail?.setSource(key);$('detail-esri').setAttribute('aria-pressed',String(key==='esri'));$('detail-s2').setAttribute('aria-pressed',String(key==='s2'))};$('model-v6da').onclick=()=>setModel('v6da');$('model-v6').onclick=()=>setModel('v6');$('model-v7').onclick=()=>setModel('v7');$('model-v5').onclick=()=>setModel('v5');$('basemap-satellite').onclick=()=>{state.basemap='satellite';syncBasemap()};$('basemap-scheme').onclick=()=>{state.basemap='scheme';syncBasemap()};$('show-predicted').onchange=e=>{state.showPredicted=e.target.checked;syncRelief();scheduleDraw()};$('show-observed').onchange=e=>{state.showObserved=e.target.checked;renderPoints();scheduleDraw()};$('region-lines').onchange=e=>{state.lines=e.target.checked;relief?.setLines(state.lines);scheduleDraw()};$('high-only').onchange=e=>{state.highOnly=e.target.checked;makeRaster()};$('hide-heat').onchange=e=>{state.hideHeat=e.target.checked;allEventsCache=null;makeRaster();updateCell()};$('forecast-date').onchange=e=>setDate(e.target.value);$('previous-day').onclick=()=>changeDay(-1);$('next-day').onclick=()=>changeDay(1);$('zoom-in').onclick=()=>state.view==='3d'?relief.zoom(1.4):zoomAt(2);$('zoom-out').onclick=()=>state.view==='3d'?relief.zoom(1/1.4):zoomAt(.5);$('reset-map').onclick=reset;$('close-card').onclick=()=>{state.selected=-1;$('cell-card').hidden=true;relief?.setSelected(-1);scheduleDraw()};$('export-button').onclick=download;
$('alert-profile').onchange=e=>{state.alertProfile=e.target.value;syncLayer();makeRaster()};
async function readinessDialog(){showDialog(t('dlg.readiness'),await readiness(),readinessDialog)}$('today-button').onclick=readinessDialog;
async function qualityDialog(){showDialog(t('dlg.quality'),await quality(),qualityDialog)}$('quality-button').onclick=qualityDialog;
let drag=null;
canvas.addEventListener('pointerdown',e=>{if(e.button!==0)return;drag={x:e.clientX,y:e.clientY,px:state.panX,py:state.panY,moved:false};canvas.setPointerCapture(e.pointerId)});
canvas.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.hypot(dx,dy)>4)drag.moved=true;if(drag.moved){state.panX=drag.px+dx;state.panY=drag.py+dy;canvas.style.cursor='grabbing';scheduleDraw()}});
canvas.addEventListener('pointerup',e=>{if(!drag)return;if(!drag.moved){const r=canvas.getBoundingClientRect(),[x,y]=toWorld(e.clientX-r.left,e.clientY-r.top);ctx.save();ctx.setTransform(1,0,0,1,0,0);const inside=ctx.isPointInPath(boundary,x,y,'evenodd');ctx.restore();const index=cellByKey.get(`${Math.floor(-y/5)},${Math.floor(x/5)}`);if(inside&&index!==undefined)selectCell(index);else toast(t('toast.outside'))}drag=null;canvas.style.cursor='crosshair'});
canvas.addEventListener('pointercancel',()=>{drag=null;canvas.style.cursor='crosshair'});
canvas.addEventListener('wheel',e=>{e.preventDefault();const r=canvas.getBoundingClientRect();zoomAt(Math.exp(-Math.max(-300,Math.min(300,e.deltaY))*.0025),e.clientX-r.left,e.clientY-r.top)},{passive:false});
canvas.addEventListener('keydown',e=>{if(!geo)return;if(e.key==='+'||e.key==='='){e.preventDefault();zoomAt(1.4)}else if(e.key==='-'){e.preventDefault();zoomAt(1/1.4)}else if(e.key==='Escape'){state.selected=-1;updateCell();scheduleDraw()}else if(e.key==='Enter'){e.preventDefault();selectCell(cellByKey.get('36,20')??0)}else if(e.key.startsWith('Arrow')){e.preventDefault();if(state.selected<0){selectCell(cellByKey.get('36,20')??0);return}const c=cells[state.selected],row=c.row+(e.key==='ArrowUp'?1:e.key==='ArrowDown'?-1:0),col=c.col+(e.key==='ArrowRight'?1:e.key==='ArrowLeft'?-1:0),i=cellByKey.get(`${row},${col}`);if(i!==undefined)selectCell(i)}});
// v6 is the default when its manifest and records verify; otherwise the map stays on v5.
const START_DAY={v5:'2024-07-15',v6:'2026-04-02'};
let liveHeat=[];
async function loadModelV6(){
  try{const r=await fetch('./assets/forecast-manifest-v6.json');if(!r.ok)return;const m=await r.json();validateManifest(m);await loadV6(m);manifests.v6=m;manifest=m;state.model='v6';try{const live=await loadLive(m);if(live){liveHeat=live.heat;if(m.live_days?.length)START_DAY.v6=m.live_days.at(-1);if(live.v7.ready){manifests.v7=live.v7;$('model-v7').hidden=false}if(live.dayahead){manifests.v6da=live.dayahead;START_DAY.v6da=live.dayahead.available_days[0];$('model-v6da').hidden=false;manifest=live.dayahead;state.model='v6da'}}}catch(e){console.warn('Daily forecasts unavailable',e)}for(const k of ['v6da','v7','v6','v5'])$('model-'+k).setAttribute('aria-pressed',String(k===state.model))}
  catch(e){console.warn('Model v6 unavailable',e)}
}
async function init(){try{const responses=await Promise.all([fetch('./assets/geography.json'),fetch('./assets/cells.bin'),fetch('./assets/forecast-manifest.json')]);if(responses.some(r=>!r.ok))throw Error('Не удалось получить файлы карты.');[geo,manifest]=await Promise.all([responses[0].json(),responses[2].json()]);validateManifest(manifest);await loadOperatingPolicy(manifest);await loadUpgrade(manifest);manifests.v5=manifest;await loadModelV6();const buffer=await responses[1].arrayBuffer();if(buffer.byteLength!==geo.count*geo.record_bytes)throw Error('Неполный файл сетки.');const data=new DataView(buffer);cells=[];history=new Uint16Array(geo.count*8);cellByKey=new Map();for(let i=0;i<geo.count;i++){const p=i*34,c={row:data.getInt16(p,true),col:data.getInt16(p+2,true),area:data.getFloat32(p+4,true),lon:data.getFloat32(p+8,true),lat:data.getFloat32(p+12,true),region:data.getUint16(p+16,true)};cells.push(c);cellByKey.set(`${c.row},${c.col}`,i);for(let y=0;y<8;y++)history[i*8+y]=data.getUint16(p+18+y*2,true)}heat=new Uint8Array(geo.count);for(let i=0;i<geo.count;i++){let low=Infinity;for(let y=0;y<8;y++)low=Math.min(low,history[i*8+y]);heat[i]=low>=HEAT_MIN?1:0}for(const i of liveHeat)if(i>=0&&i<geo.count)heat[i]=1;boundary=pathFrom(geo.outline);regionPaths=geo.regions.map(r=>pathFrom(r.rings));$('loading').hidden=true;renderTimeline();resize();setMode('demo');new ResizeObserver(resize).observe($('map-shell'));loadSatellite().catch(e=>{console.warn('Satellite basemap unavailable',e);state.basemap='scheme';$('basemap-satellite').disabled=true;syncBasemap()});if(manifest.ready)useEvents(state.model).catch(e=>console.warn('Observed events unavailable',e));if(manifest.ready){state.day=manifest.available_days.includes(START_DAY[state.model])?START_DAY[state.model]:manifest.available_days[0];state.autoReal=true;setMode('real')}document.fonts.ready.then(scheduleDraw)}catch(e){$('loading').lastElementChild.textContent=t('loading.failed');console.error(e)}}
// A language switch redraws every text the scripts write; i18n.js has already redone the static markup.
onLang(()=>{if($('info-dialog').open&&dialogSource)dialogSource();if(!geo)return;allEventsCache=null;renderTimeline();syncNote();syncLayer();makeRaster();if(state.detail>=0){detailHeading(state.detail);detail?.relabel()}relief?.relabel()});
bindSwitch();
init();
