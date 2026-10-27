import {loadUpgrade} from './upgrade-results.js';
import {populationNote,readiness,quality} from './quality.js?v=20261025-final';
import {probability,modelLabel,modelInputs,loadForecast,validateManifest,sources,methodology,evaluation} from './model-results.js';
import {loadOperatingPolicy,activeProfile,profileMetrics} from './operating-policy.js';
const $ = id => document.getElementById(id);
const nf = new Intl.NumberFormat('ru-RU');
const df = new Intl.DateTimeFormat('ru-RU', {day:'numeric', month:'long', year:'numeric',timeZone:'UTC'});
const pf = p => state.mode==='real'&&manifest?.ready?probability(p):(p * 100).toLocaleString('ru-RU', {minimumFractionDigits:1,maximumFractionDigits:1}) + '%';
const canvas = $('map'), ctx = canvas.getContext('2d');
const state = {mode:'demo', layer:'forecast', view:'2d', day:'2022-07-15', year:2022, zoom:1, panX:0, panY:0, selected:-1, region:-1, highOnly:false, lines:true};
let geo, manifest, cells, values, history, boundary, regionPaths, raster, cellByKey, baseScale=1, width=1, height=1, toastTimer, renderFrame, relief, hatch;
const riskThreshold=()=>state.mode==='real'&&manifest?.ready?activeProfile(manifest,state.alertProfile).threshold:.05;
function syncProfile(){
  const policy=manifest?.operating_policy?.policy;
  if(manifest?.upgrade){$('alert-profile-panel').querySelector('label').textContent='Активная модель';$('alert-profile-panel').hidden=!(state.mode==='real'&&state.layer==='forecast');$('alert-profile').innerHTML='<option>XGBoost + второй уровень</option>';$('alert-profile').disabled=true;const s=manifest.test_metrics[manifest.model];const rate=v=>(v*100).toLocaleString('ru-RU',{maximumFractionDigits:2})+'%';$('alert-profile-metrics').textContent=`Recall ${rate(s.recall)} · Precision ${rate(s.precision)} · порог ${probability(manifest.threshold)}`;$('alert-profile-help').textContent='Обучение: до 2022. Выбор модели и порога: до 2023. Метрики: повторная оценка 2023–2024.';const link=$('alert-profile-panel').querySelector('a');link.textContent='Сравнить модели';link.href='./reports/model.html';return}
  $('alert-profile-panel').hidden=!(policy&&state.mode==='real'&&state.layer==='forecast');
  if(!policy)return;
  const select=$('alert-profile');
  if(!select.options.length)for(const [key,p] of Object.entries(policy.profiles)){
    const option=document.createElement('option');option.value=key;option.textContent=p.label;select.append(option);
  }
  state.alertProfile=state.alertProfile||policy.default_profile;select.value=state.alertProfile;
  const s=profileMetrics(manifest,state.alertProfile),p=activeProfile(manifest,state.alertProfile);
  const rate=v=>(v*100).toLocaleString('ru-RU',{maximumFractionDigits:2})+'%';
  $('alert-profile-metrics').textContent=`Recall ${rate(s.recall)} · Precision ${rate(s.precision)} · порог ${probability(p.threshold)}`;
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
const pct = v => (v*100).toLocaleString('ru-RU',{maximumFractionDigits:2});
const centerX = -17, centerY = -5;
function pathFrom(rings){const p=new Path2D();for(const ring of rings){ring.forEach(([x,y],i)=>i?p.lineTo(x,y):p.moveTo(x,y));p.closePath()}return p}
function view(){return {s:baseScale*state.zoom,x:width/2+state.panX-centerX*baseScale*state.zoom,y:height/2+state.panY-centerY*baseScale*state.zoom}}
function toWorld(x,y){const v=view();return [(x-v.x)/v.s,(y-v.y)/v.s]}
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,4500)}
function showDialog(title,html){$('dialog-eyebrow').textContent=title;$('dialog-content').innerHTML=html;$('info-dialog').showModal()}
function dataDialog(){if(manifest?.ready){showDialog('РЕАЛЬНЫЕ ИСТОЧНИКИ',sources(manifest));return}showDialog('ИСТОЧНИКИ И ГОТОВНОСТЬ', `<h2>Реальная география.<br>Прозрачный статус данных.</h2><p>Карта использует 110 129 ячеек реальной сетки Казахстана и разрешённую часть архива NASA. Национальная модель ещё не обучена.</p><div class="data-line"><span>Граница и сетка 5 км</span><span class="ready">ПОДКЛЮЧЕНЫ</span></div><div class="data-line"><span>VIIRS S-NPP · 2015–2022</span><span class="ready">ПОДКЛЮЧЕНЫ</span></div><div class="data-line"><span>Метеоданные · ERA5-Land</span><span class="pending">НУЖНЫ ДАННЫЕ</span></div><div class="data-line"><span>Растительность · MOD13A2</span><span class="pending">НУЖНЫ ДАННЫЕ</span></div><div class="data-line"><span>Покров, рельеф, антропогенные признаки</span><span class="pending">НУЖНЫ ДАННЫЕ</span></div><div class="data-line"><span>Тестовая выборка · 2023–2024</span><span class="sealed">ЗАКРЫТА</span></div><p>Исторический слой — исходные детекции номинальной и высокой уверенности, до выделения событий и удаления промышленных источников. Количество детекций не равно количеству пожаров.</p><p>Границы областей соответствуют источнику 2017 года. <a href="https://www.geoboundaries.org/" target="_blank" rel="noopener">geoBoundaries / OSM, ODbL</a> · <a href="https://firms.modaps.eosdis.nasa.gov/" target="_blank" rel="noopener">NASA FIRMS</a></p>`)}
function methodDialog(){if(manifest?.ready){showDialog('МЕТОДИКА МОДЕЛИ',methodology(manifest));return}showDialog('МЕТОДИКА', `<h2>Прогноз начинается<br>с конкретного места.</h2><div class="method-step"><b>01</b><div><strong>Ячейка 5 × 5 км</strong><p>Равновеликая сетка в проекции LAEA. Прибрежные ячейки обрезаны по национальной границе; в карточке указана их фактическая площадь.</p></div></div><div class="method-step"><b>02</b><div><strong>Вероятность нового очага за сутки</strong><p>Цель исследования — первое обнаружение нового природного пожара на следующие сутки. Это вероятность возникновения, без оценки ущерба или экспозиции.</p></div></div><div class="method-step"><b>03</b><div><strong>Проверка на будущих данных</strong><p>2015–2021 — обучение и временная валидация. 2022 — калибровка. Данные 2023–2024 остаются закрытыми до финальной оценки.</p></div></div><div class="method-step"><b>04</b><div><strong>Сейчас: демонстрация интерфейса</strong><p>Поле вероятностей создано иллюстративной формулой. Дата меняет условный сценарий, факторы — условные индексы. Здесь нет результатов обученной национальной модели, реального прогноза погоды или SHAP-объяснений. Шкала и порог 5% заданы для демонстрации.</p></div></div>`)}

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
  for(let i=0;i<cells.length;i++){
    const c=cells[i];let p;
    if(hist){p=history[i*8+state.year-2015];values[i]=p;total+=p;if(p>0)active++;max=Math.max(max,p);totals[c.region]+=p;sizes[c.region]++;}
    else {p=state.mode==='demo'?scenario(c,state.day).p:(state.realValues?.[i]??NaN);values[i]=p;if(Number.isFinite(p)){finite++;max=Math.max(max,p);if(p>=riskThreshold())high++;totals[c.region]+=p;sizes[c.region]++;}}
    if(!Number.isFinite(p)||(!hist&&state.mode==='real'&&!state.realValues))continue;
    if(hist&&p===0)continue;
    const k=classOf(p,bounds);classCounts[k]++;
    // Filtered-out cells are plain land, so the hatch keeps meaning "no data".
    const color=!hist&&state.highOnly&&p<riskThreshold()?LAND:rgb[k];
    const pos=((166-c.row)*593+(c.col+300))*4;
    image.data[pos]=color[0];image.data[pos+1]=color[1];image.data[pos+2]=color[2];image.data[pos+3]=state.region>=0&&c.region!==state.region?65:245;
  }
  rctx.putImageData(image,0,0);
  if(state.layer==='history'){
    $('stat-one-label').textContent='Детекций VIIRS';$('stat-cells').textContent=nf.format(total);$('stat-cells-unit').textContent=state.year+' год';
    $('stat-two-label').textContent='Ячеек с детекциями';$('stat-high').textContent=nf.format(active);$('stat-high-unit').textContent='5 × 5 км';
    $('stat-three-label').textContent='Максимум в ячейке';$('stat-max').textContent=nf.format(max);$('stat-max-unit').textContent='детекций за год';
  }else{
    $('stat-one-label').textContent=state.mode==='real'?'Ячеек с прогнозом':'Ячеек на карте';$('stat-cells').textContent=nf.format(state.mode==='real'?finite:cells.length);$('stat-cells-unit').textContent=state.mode==='real'?'из '+nf.format(cells.length):'5 × 5 км';
    $('stat-two-label').textContent='Вероятность ≥ '+pf(riskThreshold());$('stat-high').textContent=state.mode==='real'&&(!state.realValues||finite===0)?'—':nf.format(high);$('stat-high-unit').textContent=state.mode==='demo'?'демо-ячейки':'ячейки';
    $('stat-three-label').textContent='Максимум на карте';$('stat-max').textContent=state.mode==='real'&&(!state.realValues||finite===0)?'—':pf(max);$('stat-max-unit').textContent=state.mode==='demo'?'условная вероятность':'вероятность';
  }
  state.regionStats=totals.map((v,i)=>state.layer==='history'?v:sizes[i]?v/sizes[i]:NaN);
  renderLegend(bounds,!hist&&state.mode==='real'&&!state.realValues?null:classCounts);
  renderRegions();updateCell();scheduleDraw();syncRelief();
}
function renderLegend(bounds,counts){
  const hist=state.layer==='history',real=state.mode==='real'&&manifest?.ready;
  $('legend-title').textContent=hist?`Детекций VIIRS в ячейке за ${state.year} год`:'Вероятность нового очага за сутки, %'+(state.mode==='demo'?' · демо':'');
  $('legend-ticks').innerHTML=(hist?['1',...bounds.map((b,i)=>i===bounds.length-1?b+'+':String(b))]:['0',...bounds.map(pct)]).map(t=>`<span>${t}</span>`).join('');
  $('legend-threshold').hidden=hist;
  $('legend-counts').innerHTML=counts?counts.map(n=>`<span>${nf.format(n)}</span>`).join(''):'';
  $('legend-counts').title='Число ячеек в каждом классе на эту дату';
  $('legend-note').textContent=hist?'Детекции до связывания в события и до фильтрации промышленных источников. Не равны числу пожаров.':real?`Шкала логарифмическая: у 99% ячеек-дней вероятность ниже 0,33%. Черта — порог тревоги ${pf(riskThreshold())}, выбранный на 2022 году. Штриховка — нет данных.`:`Шкала демо-сценария. Черта — его условный порог ${pf(riskThreshold())}.`;
}
function syncRelief(){
  if(!relief||state.view!=='3d')return;
  const hist=state.layer==='history',t=riskThreshold();
  relief.setValues(values,{bounds:hist?HISTORY_BOUNDS:forecastBounds(),k0:hist?.55:.22,alertAt:hist?null:t,hidden:(i,v)=>(hist&&v===0)||(!hist&&state.highOnly&&v<t)||(state.region>=0&&cells[i].region!==state.region)});
  relief.setLines(state.lines);
  relief.setSelected($('cell-card').hidden?-1:state.selected);
}
let reliefRequest=null;
async function setView(view){
  if(!geo)return;
  if(view==='3d'&&!relief){
    $('view-3d').disabled=true;
    $('loading').hidden=false;$('loading').lastElementChild.textContent='Загружаем рельеф SRTM…';
    try{
      reliefRequest=reliefRequest||import('./relief3d.js').then(({createRelief})=>createRelief({host:$('map-shell'),geo,cells,onPick:i=>{if(i>=0)selectCell(i);else{state.selected=-1;updateCell();syncRelief()}}}));
      relief=await reliefRequest;
    }catch(error){
      reliefRequest=null;console.error('3D unavailable',error);toast('3D недоступно: '+error.message);view='2d';
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
function scheduleDraw(){cancelAnimationFrame(renderFrame);renderFrame=requestAnimationFrame(draw)}
function draw(){
  const dpr=Math.min(devicePixelRatio||1,2),v=view();
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
  // Quiet cartographic reference grid, independent of the study cell lattice.
  ctx.save();ctx.translate(v.x,v.y);ctx.scale(v.s,v.s);ctx.lineWidth=.6/v.s;ctx.strokeStyle='#e1e6d7';
  for(let x=-3500;x<3500;x+=250){ctx.beginPath();ctx.moveTo(x,-2500);ctx.lineTo(x,2500);ctx.stroke()}
  for(let y=-2500;y<2500;y+=250){ctx.beginPath();ctx.moveTo(-3500,y);ctx.lineTo(3500,y);ctx.stroke()}
  // Under real forecasts, any cell left unpainted has no prediction: show it hatched, not blank.
  const missingVisible=state.layer==='forecast'&&state.mode==='real'&&state.realValues;
  if(missingVisible&&!hatch){const h=document.createElement('canvas');h.width=h.height=8;const g=h.getContext('2d');g.fillStyle='#e3e6dc';g.fillRect(0,0,8,8);g.strokeStyle='#c9cec1';g.lineWidth=2;g.beginPath();g.moveTo(-2,10);g.lineTo(10,-2);g.stroke();hatch=ctx.createPattern(h,'repeat')}
  if(missingVisible)hatch.setTransform(new DOMMatrix().scale(1/v.s));
  ctx.fillStyle=missingVisible?hatch:`rgb(${LAND})`;ctx.strokeStyle='#c0cbb0';ctx.lineWidth=1.2/v.s;ctx.fill(boundary,'evenodd');ctx.stroke(boundary);
  ctx.save();ctx.clip(boundary,'evenodd');ctx.imageSmoothingEnabled=false;if(raster)ctx.drawImage(raster,-1500,-835,2965,1660);ctx.restore();
  if(state.lines){ctx.lineWidth=.6/v.s;ctx.strokeStyle='#7f946b77';for(let i=0;i<regionPaths.length;i++){if(i===state.region){ctx.fillStyle='#ffffff10';ctx.fill(regionPaths[i],'evenodd')}ctx.stroke(regionPaths[i])}}
  ctx.lineWidth=1/v.s;ctx.strokeStyle='#aebd98';ctx.stroke(boundary);
  if(state.region>=0){ctx.lineWidth=1.7/v.s;ctx.strokeStyle='#627e50';ctx.stroke(regionPaths[state.region])}
  ctx.restore();
  ctx.textAlign='left';ctx.textBaseline='middle';
  for(const city of geo.cities){const x=city.x*v.s+v.x,y=city.y*v.s+v.y;if(x<12||x>width-20||y<20||y>height-35)continue;
    ctx.beginPath();ctx.arc(x,y,city.name==='Астана'?3.5:2.8,0,Math.PI*2);ctx.fillStyle='#fffefa';ctx.fill();ctx.strokeStyle='#193d35';ctx.lineWidth=1.4;ctx.stroke();
    ctx.font=`${city.name==='Астана'?'600':'500'} ${state.zoom>1.5?13:12}px 'Golos Text','Segoe UI',sans-serif`;ctx.lineWidth=3.5;ctx.strokeStyle='#fffefaee';ctx.strokeText(city.name,x+8,y-.5);ctx.fillStyle='#193d35';ctx.fillText(city.name,x+8,y-.5);
  }
  if(state.selected>=0&&!$('cell-card').hidden){const c=cells[state.selected],x=(c.col+.5)*5*v.s+v.x,y=-(c.row+.5)*5*v.s+v.y;ctx.beginPath();ctx.arc(x,y,9,0,Math.PI*2);ctx.strokeStyle='#fffefb';ctx.lineWidth=5;ctx.stroke();ctx.strokeStyle='#193d35';ctx.lineWidth=1.8;ctx.stroke();ctx.fillStyle='#193d35';ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fill();}
  const km=Math.round((64/v.s)/50)*50;$('scale-label').textContent=(km||Math.round(64/v.s))+' км';
}
function resize(){const r=canvas.getBoundingClientRect();width=r.width;height=r.height;const dpr=Math.min(devicePixelRatio||1,2);canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);const narrow=width<600;baseScale=Math.min((width-(narrow?16:80))/2965,(height-(narrow?150:200))/1660);scheduleDraw()}
function allowedDate(day){return /^\d{4}-\d{2}-\d{2}$/.test(day)&&(state.mode==='real'&&manifest?.ready?manifest.available_days.includes(day):day>='2015-01-01'&&day<='2022-12-31')}
function setDate(day){if(!allowedDate(day)){toast(state.mode==='real'&&manifest?.ready?'Для этой даты прогноз не опубликован.':'Для сценария выберите дату 2015–2022. Тестовые годы закрыты.');$('forecast-date').value=state.day;return}state.day=day;$('forecast-date').value=day;renderTimeline();if(geo){if(state.mode==='real')setMode('real');else{syncLayer();makeRaster()}}}
function renderTimeline(){const d=new Date(state.day+'T00:00:00Z'),wrap=$('timeline-days');wrap.replaceChildren();for(let n=-3;n<=3;n++){const date=new Date(d);date.setUTCDate(date.getUTCDate()+n);const iso=date.toISOString().slice(0,10);if(!allowedDate(iso))continue;const b=document.createElement('button');b.className='timeline-day'+(n===0?' active':'');b.innerHTML=`<span>${new Intl.DateTimeFormat('ru',{weekday:'short',timeZone:'UTC'}).format(date)}</span><strong>${date.getUTCDate()}</strong>`;b.setAttribute('aria-label',df.format(date));b.setAttribute('aria-pressed',String(n===0));b.onclick=()=>setDate(iso);wrap.append(b)}const real=state.mode==='real'&&manifest?.ready;$('previous-day').disabled=real?manifest.available_days.indexOf(state.day)<=0:state.day==='2015-01-01';$('next-day').disabled=real?manifest.available_days.indexOf(state.day)>=manifest.available_days.length-1:state.day==='2022-12-31'}
function changeDay(delta){if(state.mode==='real'&&manifest.ready){const days=manifest.available_days,day=days[days.indexOf(state.day)+delta];if(day)setDate(day);return}const d=new Date(state.day+'T00:00:00Z');d.setUTCDate(d.getUTCDate()+delta);setDate(d.toISOString().slice(0,10))}
function renderRegions(){const query=$('region-search').value.toLowerCase(),list=$('region-list');list.replaceChildren();const sorted=geo.regions.map((r,i)=>({...r,i})).filter(r=>r.label.toLowerCase().includes(query)).sort((a,b)=>(state.regionStats?.[b.i]||0)-(state.regionStats?.[a.i]||0));$('region-count').textContent=sorted.length;for(const r of sorted){const b=document.createElement('button');b.className='region-item'+(state.region===r.i?' selected':'');b.innerHTML=`<span class="region-circle"></span><span>${r.label}</span><span class="region-value">${state.layer==='history'?nf.format(state.regionStats[r.i]):Number.isFinite(state.regionStats[r.i])?pf(state.regionStats[r.i]):'—'}</span>`;b.setAttribute('aria-label',r.label+', показать на карте');b.onclick=()=>selectRegion(r.i);list.append(b)}if(!sorted.length){const p=document.createElement('p');p.className='blank-list';p.textContent='Область не найдена';list.append(p)}}
function selectRegion(index){state.region=index;state.selected=-1;let best=-1;for(let i=0;i<cells.length;i++)if(cells[i].region===index&&Number.isFinite(values[i])&&(best<0||values[i]>values[best]))best=i;if(best>=0){const c=cells[best];state.zoom=2;const s=baseScale*state.zoom;state.panX=-( (c.col+.5)*5-centerX)*s-width*.12;state.panY=-(-(c.row+.5)*5-centerY)*s;selectCell(best)}makeRaster()}
function selectCell(index){state.selected=index;updateCell();scheduleDraw();relief?.setSelected($('cell-card').hidden?-1:index)}
function updateCell(){
  if(state.selected<0||state.mode==='real'&&state.layer==='forecast'&&(!state.realValues||state.noEligibleForecast)){$('cell-card').hidden=true;return}
  const c=cells[state.selected],p=values[state.selected];$('cell-card').hidden=false;$('cell-region').textContent=geo.regions[c.region].label+(c.region===13||c.region===15?'':' область');$('cell-coordinates').textContent=c.lat.toLocaleString('ru-RU',{minimumFractionDigits:3,maximumFractionDigits:3})+'° с. ш., '+c.lon.toLocaleString('ru-RU',{minimumFractionDigits:3,maximumFractionDigits:3})+'° в. д.';$('cell-area').textContent=c.area.toLocaleString('ru',{maximumFractionDigits:2})+' км²';$('cell-id').textContent=`g5000_${c.row}_${c.col}`;$('cell-elevation').textContent=relief?nf.format(Math.round(relief.elevation[state.selected]))+' м над морем':'';
  const hist=state.layer==='history',real=state.mode==='real'&&!hist;$('cell-probability').textContent=hist?nf.format(p):Number.isFinite(p)?pf(p):'—';$('cell-category').textContent=hist?'Детекций VIIRS\nза '+state.year+' год':real?(Number.isFinite(p)?'Калиброванная\nвероятность':'Нет прогноза'):p>=.05?'Высокая\nв демо-сценарии':p>=.02?'Повышенная\nв демо-сценарии':p>=.005?'Умеренная\nв демо-сценарии':'Низкая\nв демо-сценарии';$('cell-category').style.whiteSpace='pre-line';$('probability-meter').style.width=(Number.isFinite(p)&&(!hist||p>0)?(classOf(p,hist?HISTORY_BOUNDS:forecastBounds())+1)/7*100:0)+'%';$('cell-context').textContent=hist?'Номинальная и высокая уверенность; до объединения в события':real?'Первое спутниковое обнаружение за сутки; нет данных = пропуск':'Условная вероятность нового очага за сутки';$('factor-title').textContent=hist?'Наблюдения по годам':real?'Источник прогноза':'Факторы демо-сценария';$('card-disclaimer').textContent=hist?'Спутниковые детекции не равны числу отдельных пожаров.':real?'Ретроспективный результат модели. Пустые ячейки исключены или не имеют обязательных данных.':'Иллюстрация интерфейса. Значения не рассчитаны обученной моделью.';
  const wrap=$('cell-factors');wrap.replaceChildren();
  if(real){const note=document.createElement('p');note.className='empty-history';const profile=activeProfile(manifest,state.alertProfile);note.textContent=`${modelLabel(manifest.model)} · цель ${state.day} UTC. Режим: ${profile.label}; порог ${probability(profile.threshold)}. Признаки: ${modelInputs(manifest)}. Их вклад не следует интерпретировать как причинность.`;wrap.append(note);const selected=state.selected;populationNote(`g5000_${c.row}_${c.col}`).then(text=>{if(state.selected===selected&&state.mode==="real"&&text){const exposure=document.createElement("p");exposure.className="empty-history";exposure.textContent=text;wrap.append(exposure)}}).catch(()=>{});if(Number.isFinite(p))$('cell-category').textContent=p>=riskThreshold()?'Предупреждение\nпо выбранному порогу':'Ниже выбранного\nпорога';return}
  const historyYears=[state.year-1,state.year,state.year+1].filter(y=>y>=2015&&y<=2022);
  const factors=hist?historyYears.map(y=>[String(y),history[state.selected*8+y-2015],Math.max(1,...historyYears.map(z=>history[state.selected*8+z-2015]))]):['Сухость','Тепло','Ветер'].map((name,j)=>[name,Math.round(scenario(c,state.day).factors[j]*100),100]);
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
  $('mode-note').className='note '+(mode==='demo'?'is-demo':manifest.ready?'is-verified':'');
  $('mode-note').innerHTML=mode==='demo'?(state.payloadMissing?'<div><strong>Показан демо-сценарий</strong><p>В этой копии сайта нет суточных файлов прогноза (assets/predictions). Демо — формула для показа интерфейса, не результат модели.</p></div>':'<div><strong>Демо-сценарий</strong><p>Условные вероятности на реальной карте. Значения не рассчитаны моделью.</p></div>'):manifest.ready?'<div><strong>Ретроспективная модель</strong><p>Открытые данные · калибровка 2022 · повторная оценка 2023–2024. Не оперативный прогноз.</p></div>':'<div><strong>Статус национальной модели</strong><p>Обучение и проверка ещё не завершены.</p></div>';
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
function syncLayer(){
  const hist=state.layer==='history',empty=state.mode==='real'&&state.noEligibleForecast&&!hist,unavailable=state.mode==='real'&&(!state.realValues||empty)&&!hist;
  const loading=unavailable&&state.loadingForecast;
  $('forecast-layer').classList.toggle('selected',!hist);
  $('history-layer').classList.toggle('selected',hist);
  $('forecast-layer').setAttribute('aria-pressed',String(!hist));
  $('history-layer').setAttribute('aria-pressed',String(hist));
  $('history-options').hidden=!hist;$('high-only-row').hidden=hist;$('timeline').hidden=hist;
  $('map-empty').hidden=!unavailable||loading;$('loading').hidden=!loading;
  if(loading)$('loading').lastElementChild.textContent='Загружаем прогноз и проверяем хеш файла…';
  $('map-empty').classList.toggle('is-danger',!empty&&!state.payloadMissing);
  $('map-empty').querySelector('strong').textContent=empty?'На эту дату нет допустимых ячеек':state.payloadMissing?'Файлы прогноза не найдены':manifest.ready?'Файл прогноза не прошёл проверку':'Реальный прогноз пока недоступен';
  $('map-empty').querySelector('p').textContent=empty?'В исходном архиве нет обязательных наблюдений влажности почвы. Пропуск не означает нулевую вероятность, экспорт отключён.':state.payloadMissing?'В этой копии сайта нет суточных файлов assets/predictions: они не хранятся в Git. Как их получить — в platform/README.md.':manifest.ready?'Хеш или покрытие файла не совпали с релизом модели, значения не показаны. Выберите другую дату.':'Обучение и финальная оценка ещё не завершены.';
  $('map-intro').textContent=hist?'Детекции спутника S-NPP VIIRS за год, сетка 5 × 5 км':'Вероятность нового природного пожара на следующие сутки, сетка 5 × 5 км';
  $('map-title').innerHTML=hist?`Спутниковые наблюдения <span>${state.year}</span>`:`Прогноз на <span id="title-date">${df.format(new Date(state.day+'T00:00:00Z')).replace(' г.','')}</span>`;
  $('map-badge').textContent=hist?'Архив NASA VIIRS':state.mode==='demo'?'Демо-сценарий':empty?'Модель · нет данных':state.realValues?'Модель · проверено по хешу':loading?'Модель · загрузка':'Модель · нет прогноза';
  $('map-chip').className='chip'+(state.mode==='demo'&&!hist?' is-demo':state.realValues&&!hist?' is-verified':'');
  $('stat-source').textContent=hist?'номинальная и высокая уверенность':state.mode==='demo'?'формула, не модель':state.realValues?'ретроспектива, не оперативный прогноз':'';
  $('release').innerHTML=manifest.ready?`Модель <b>${manifest.upgrade?'XGBoost + второй уровень':modelLabel(manifest.model)}</b> · релиз ${manifest.release_sha256.slice(0,8)}`:'';
  syncProfile();
  $('threshold-label').textContent='Только предупреждения ≥ '+pf(riskThreshold());
  document.querySelector('.timeline-title strong').textContent=state.mode==='real'?'Дата прогноза':'Дата сценария';
  $('forecast-date').setAttribute('aria-label',state.mode==='real'?'Дата ретроспективного прогноза':'Дата демо-сценария');
  $('export-button').disabled=unavailable;
  $('map-hint').textContent=state.view==='3d'?'Тяните — вращать · колесо — масштаб · Shift — сдвиг · клик — ячейка':hist?'Детекции VIIRS не равны отдельным пожарам':'Нажмите на карту, чтобы изучить ячейку';
}
function setLayer(layer){state.layer=layer;syncLayer();makeRaster()}
function zoomAt(factor,x=width/2,y=height/2){const [wx,wy]=toWorld(x,y);state.zoom=Math.max(.7,Math.min(12,state.zoom*factor));const s=baseScale*state.zoom;state.panX=x-width/2-(wx-centerX)*s;state.panY=y-height/2-(wy-centerY)*s;scheduleDraw()}
function reset(){state.zoom=1;state.panX=0;state.panY=0;state.region=-1;relief?.reset();makeRaster()}
function download(){
  if(state.mode==='real'&&state.layer==='forecast'&&(!state.realValues||state.noEligibleForecast)){toast('Для этой даты нет прогноза.');return}
  const hist=state.layer==='history',real=state.mode==='real'&&!hist;
  const header=hist?'cell_id,longitude,latitude,area_km2,region,year,viirs_detections,source\n':'cell_id,longitude,latitude,area_km2,region,target_day,probability,alert,threshold,profile,model_release_sha256,policy_sha256,synthetic\n';
  let text=header,rows=0;
  for(let i=0;i<cells.length;i++){
    const c=cells[i],p=values[i];if(state.region>=0&&c.region!==state.region)continue;
    if(!hist&&(state.highOnly&&p<riskThreshold()||!Number.isFinite(p)))continue;
    if(hist&&p===0)continue;
    text+=`g5000_${c.row}_${c.col},${c.lon.toFixed(5)},${c.lat.toFixed(5)},${c.area.toFixed(4)},${geo.regions[c.region].name},`+(hist?`${state.year},${p},NASA_FIRMS_SNPP_VIIRS`:`${state.day},${p.toPrecision(9)},${p>=riskThreshold()},${riskThreshold()},${real?manifest.upgrade?'model_v3':state.alertProfile||'original':'demo'},${real?manifest.release_sha256:''},${real?manifest.operating_policy?.policy_sha256||'':''},${!real}`)+'\n';rows++;
  }
  const url=URL.createObjectURL(new Blob(['\uFEFF',text],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=hist?`steppe_VIIRS_${state.year}.csv`:`steppe_${real?(manifest.upgrade?'model_v3':state.alertProfile)+'_':'DEMO_'}${state.day}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);toast(`Экспортировано ${nf.format(rows)} ячеек`);
}

$('nav-data').onclick=dataDialog;$('nav-method').onclick=methodDialog;$('nav-map').onclick=e=>{e.preventDefault();if($('info-dialog').open)$('info-dialog').close();reset()};$('view-2d').onclick=()=>setView('2d');$('view-3d').onclick=()=>setView('3d');$('close-dialog').onclick=()=>$('info-dialog').close();$('info-dialog').addEventListener('click',e=>{if(e.target===$('info-dialog')){const r=$('info-dialog').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('info-dialog').close()}});$('holdout-button').onclick=()=>manifest?.ready?showDialog('РЕАЛЬНЫЕ МЕТРИКИ',evaluation(manifest)):showDialog('ЗАКРЫТАЯ ТЕСТОВАЯ ВЫБОРКА','<h2>2023–2024 остаются закрытыми.</h2><p>Архивы скачаны и проверены по контрольным суммам. Наблюдения из этих файлов не прочитаны и не используются на карте, для выбора модели, калибровки или демонстрации.</p><p>Финальная оценка выполняется только после фиксации модели, признаков и порогов. В эту платформу включены исторические наблюдения только за 2015–2022 годы.</p>');
$('demo-mode').onclick=()=>setMode('demo');$('real-mode').onclick=()=>setMode('real');$('return-demo').onclick=()=>setMode('demo');$('forecast-layer').onclick=()=>setLayer('forecast');$('history-layer').onclick=()=>setLayer('history');$('history-year').onchange=e=>{state.year=Number(e.target.value);syncLayer();makeRaster()};$('region-search').oninput=renderRegions;$('region-lines').onchange=e=>{state.lines=e.target.checked;relief?.setLines(state.lines);scheduleDraw()};$('high-only').onchange=e=>{state.highOnly=e.target.checked;makeRaster()};$('forecast-date').onchange=e=>setDate(e.target.value);$('previous-day').onclick=()=>changeDay(-1);$('next-day').onclick=()=>changeDay(1);$('zoom-in').onclick=()=>state.view==='3d'?relief.zoom(1.4):zoomAt(1.4);$('zoom-out').onclick=()=>state.view==='3d'?relief.zoom(1/1.4):zoomAt(1/1.4);$('reset-map').onclick=reset;$('close-card').onclick=()=>{state.selected=-1;$('cell-card').hidden=true;relief?.setSelected(-1);scheduleDraw()};$('export-button').onclick=download;
$('alert-profile').onchange=e=>{state.alertProfile=e.target.value;syncLayer();makeRaster()};
$('today-button').onclick=async()=>showDialog('ТЕКУЩИЕ ДАННЫЕ',await readiness());
$('quality-button').onclick=async()=>showDialog('ПРОВЕРКА КАЧЕСТВА',await quality());
let drag=null;
canvas.addEventListener('pointerdown',e=>{if(e.button!==0)return;drag={x:e.clientX,y:e.clientY,px:state.panX,py:state.panY,moved:false};canvas.setPointerCapture(e.pointerId)});
canvas.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.hypot(dx,dy)>4)drag.moved=true;if(drag.moved){state.panX=drag.px+dx;state.panY=drag.py+dy;canvas.style.cursor='grabbing';scheduleDraw()}});
canvas.addEventListener('pointerup',e=>{if(!drag)return;if(!drag.moved){const r=canvas.getBoundingClientRect(),[x,y]=toWorld(e.clientX-r.left,e.clientY-r.top);ctx.save();ctx.setTransform(1,0,0,1,0,0);const inside=ctx.isPointInPath(boundary,x,y,'evenodd');ctx.restore();const index=cellByKey.get(`${Math.floor(-y/5)},${Math.floor(x/5)}`);if(inside&&index!==undefined)selectCell(index);else toast('Выберите ячейку внутри границы Казахстана.')}drag=null;canvas.style.cursor='crosshair'});
canvas.addEventListener('pointercancel',()=>{drag=null;canvas.style.cursor='crosshair'});
canvas.addEventListener('wheel',e=>{e.preventDefault();const r=canvas.getBoundingClientRect();zoomAt(e.deltaY<0?1.12:1/1.12,e.clientX-r.left,e.clientY-r.top)},{passive:false});
canvas.addEventListener('keydown',e=>{if(!geo)return;if(e.key==='+'||e.key==='='){e.preventDefault();zoomAt(1.4)}else if(e.key==='-'){e.preventDefault();zoomAt(1/1.4)}else if(e.key==='Escape'){state.selected=-1;updateCell();scheduleDraw()}else if(e.key==='Enter'){e.preventDefault();selectCell(cellByKey.get('36,20')??0)}else if(e.key.startsWith('Arrow')){e.preventDefault();if(state.selected<0){selectCell(cellByKey.get('36,20')??0);return}const c=cells[state.selected],row=c.row+(e.key==='ArrowUp'?1:e.key==='ArrowDown'?-1:0),col=c.col+(e.key==='ArrowRight'?1:e.key==='ArrowLeft'?-1:0),i=cellByKey.get(`${row},${col}`);if(i!==undefined)selectCell(i)}});
async function init(){try{const responses=await Promise.all([fetch('./assets/geography.json'),fetch('./assets/cells.bin'),fetch('./assets/forecast-manifest.json')]);if(responses.some(r=>!r.ok))throw Error('Не удалось получить файлы карты.');[geo,manifest]=await Promise.all([responses[0].json(),responses[2].json()]);validateManifest(manifest);await loadOperatingPolicy(manifest);await loadUpgrade(manifest);const buffer=await responses[1].arrayBuffer();if(buffer.byteLength!==geo.count*geo.record_bytes)throw Error('Неполный файл сетки.');const data=new DataView(buffer);cells=[];history=new Uint16Array(geo.count*8);cellByKey=new Map();for(let i=0;i<geo.count;i++){const p=i*34,c={row:data.getInt16(p,true),col:data.getInt16(p+2,true),area:data.getFloat32(p+4,true),lon:data.getFloat32(p+8,true),lat:data.getFloat32(p+12,true),region:data.getUint16(p+16,true)};cells.push(c);cellByKey.set(`${c.row},${c.col}`,i);for(let y=0;y<8;y++)history[i*8+y]=data.getUint16(p+18+y*2,true)}boundary=pathFrom(geo.outline);regionPaths=geo.regions.map(r=>pathFrom(r.rings));$('loading').hidden=true;renderTimeline();resize();setMode('demo');new ResizeObserver(resize).observe($('map-shell'));if(manifest.ready){state.day=manifest.available_days.includes('2024-07-15')?'2024-07-15':manifest.available_days[0];$('holdout-button').textContent='Метрики · тест 2023–2024';state.autoReal=true;setMode('real')}document.fonts.ready.then(scheduleDraw)}catch(e){$('loading').lastElementChild.textContent='Не удалось загрузить карту. Обновите страницу.';console.error(e)}}
init();
