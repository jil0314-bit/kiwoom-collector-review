'use strict';
const $=id=>document.getElementById(id), fmt=n=>n==null?'—':Number(n).toLocaleString('ko-KR',{maximumFractionDigits:2});
const WEEK=['일','월','화','수','목','금','토'];
let state=null, chosen='', themeLoading=false, lastUpdated='', pick=null;
let stockProfiles={};
const marketCapText=(p,day)=>p?.market_cap>0?'시총 '+formatWon(p.market_cap,1e8)+(p.cap_day&&p.cap_day!==day?' · '+p.cap_day+' 기준':''):'시총 확인중';
function element(tag,text,cls){const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e}
const el=element;
const pct=n=>(n>0?'+':'')+Number(n).toFixed(2)+'%';
const tone=n=>n>0?'up':n<0?'down':'flat';
const dayLabel=day=>({md:day.slice(5).replace('-','.'),dow:WEEK[new Date(day+'T12:00:00Z').getUTCDay()]});
const toast=text=>{if($('editor')&&$('editor').open){$('ed-note').textContent=text;return}$('toast').textContent=text;$('toast').style.display='block';setTimeout(()=>$('toast').style.display='none',6500)};
async function api(path, options){if(path.startsWith('/api/chart?'))path+='&fast=1&async=1';const r=await (path.startsWith('/api/chart?')&&!path.includes('prefetch=1')?collectorChartFetch(path,options):fetch(path,options));const data=await r.json();if(!r.ok)throw Error(data.error||'요청 실패');return data}
let heroLinkVersion=0,heroLinkQueue=Promise.resolve(),heroLinkTimer;
function linkHero(symbol){
  const version=++heroLinkVersion;clearTimeout(heroLinkTimer);
  heroLinkTimer=setTimeout(()=>{
    heroLinkQueue=heroLinkQueue.then(async()=>{
      if(version!==heroLinkVersion)return;
      const chart=localStorage.getItem('collector-hero-chart')||'';
      if(chart==='off')return;
      try{
        const data=await window.collectorHeroSend(symbol,chart,await token(),()=>version===heroLinkVersion);
        if(!data)return;if(data.ok){toast(data.message);return}
        throw Error(data.message||'영웅문 연동 실패');
      }catch(e){if(version===heroLinkVersion)toast('영웅문 연동: '+e.message)}
    });
  },100);
}

/* ---------- Chart: same drawing and interaction as the collector's main chart (app.js) ---------- */
let record=null, code='', selected=-1, requestVersion=0, frame='minute', chartLoading=false;
const periods=()=>chartPeriods(frame);
const barLabel=ts=>frame==='month'?ts.slice(0,7):frame==='day'?ts:frame==='week'?ts+' 주':Number(rangeBeforeZoom??$('range').value)>=360 ? ts.slice(5,16) : ts.slice(11,16);
const maUnit=()=>frame==='month'?'월':frame==='day'?'일':frame==='week'?'주':frame==='minute'?'분':'봉';
const frameLabel=()=>({minute:'1분봉',minute3:'3분봉',minute5:'5분봉',day:'일봉',week:'주봉',month:'월봉'}[frame]);
const closeLabel=()=>frame==='month'?'종가 · 해당 월 마지막':frame==='day'?'종가 · 해당 일 마지막':frame==='week'?'종가 · 해당 주 마지막':frame==='minute'?'종가 · 해당 분 마지막':'종가 · 해당 구간 마지막';
let viewRange=null, rangeBeforeZoom=null, hover=null, drag=null, chartGeometry=null, drawFrame=null;
const percent=(value,base)=>Number.isFinite(value)&&Number.isFinite(base)&&base>0?(value/base-1)*100:null;
const signedPercent=n=>n==null?'—':(n>0?'+':'')+n.toFixed(2)+'%';
const changeClass=n=>n>0?'change-up':n<0?'change-down':'change-flat';
function barChanges(i){const b=record.bars[i];return {body:percent(b.close,b.open),previous:i>0?percent(b.close,record.bars[i-1].close):null}}
function params(){const query=new URLSearchParams({day:chosen,code,frame,source:'theme',live:$('chart-source').value==='live'?'1':'0'});if(Number(rangeBeforeZoom??$('range').value)>=360)query.set('history','1');return query}
function clearChart(){resetChartView();record=null;code='';window.collectorStockTools?.(null);pick=null;selected=-1;$('selected-name').textContent='테마 주도주를 선택하세요';$('selected-code').textContent='종목 선택';$('bars').replaceChildren();$('minute').replaceChildren();$('values').replaceChildren();$('bar-changes').replaceChildren();$('chart-empty').style.display='flex';draw()}
async function selectStock(p,keepTime=null,background=false,reload=false){pick=p;code=p.code;window.collectorStockTools?.({day:chosen,code,name:p.name,source:'theme'});markPicked();const version=++requestVersion,previousRecord=record;const path='/api/chart?'+params();chartLoading=true;cancelDrag();clearHover();if(!background){record=null;$('chart-empty').textContent=frameLabel()+' 이력을 불러오는 중입니다…';$('chart-empty').style.display='flex';$('values').replaceChildren();$('bar-changes').replaceChildren();$('bars').replaceChildren();$('minute').replaceChildren();$('ma-values').textContent='';draw()}try{const result=await api(path,reload?{cache:'reload'}:undefined);if(version!==requestVersion)return;if(result.stock?.code!==code||result.frame!==frame||!result.bars?.length)throw Error('선택한 종목의 차트 자료를 확인할 수 없습니다.');prepareChartRecord(result,previousRecord);record=result;selected=keepTime?record.bars.findIndex(b=>b.ts===keepTime):-1;if(selected<0)selected=record.bars.length-1;$('selected-name').textContent=p.name;$('selected-code').textContent=p.code+' / '+record.day+' / 테마 주도주 별도 조회';$('chart-empty').style.display='none';$('minute').replaceChildren(...record.bars.map((b,i)=>new Option(barLabel(b.ts),i)));$('coverage').textContent=record.chart_notice||'';renderTable();selectMinute(selected);if(result.refreshing)setTimeout(()=>{if(version===requestVersion&&!document.hidden&&!drag)selectStock(p,record?.bars[selected]?.ts||null,true)},1000)}catch(e){if(version!==requestVersion||e.name==='AbortError')return;if(background&&previousRecord){record=previousRecord;$('coverage').textContent='차트 재조회 실패 · 이전 자료 유지 · '+e.message;return}record=null;$('chart-empty').textContent=e.message;$('chart-empty').style.display='flex';toast(e.message);draw()}finally{if(version===requestVersion)chartLoading=false}}
function renderTable(){const frag=document.createDocumentFragment();record.bars.forEach((b,i)=>{const tr=element('tr');tr.dataset.index=i;for(const k of ['ts','open','high','low','close'])tr.append(element('td',k==='ts'?barLabel(b.ts):fmt(b[k])));const rates=barChanges(i);for(const rate of [rates.body,rates.previous])tr.append(element('td',signedPercent(rate),changeClass(rate)));tr.append(element('td',fmt(b.volume)));tr.onclick=()=>selectMinute(i);frag.append(tr)});$('bars').replaceChildren(frag)}
function selectMinute(i){if(!record||!record.bars[i])return;clearHover();selected=i;const b=record.bars[i];$('minute').value=i;$('values').replaceChildren(...[['시가','open'],['고가 · 최고가','high'],['저가 · 최저가','low'],[closeLabel(),'close'],['거래량 (주)','volume']].map(([label,k])=>{const d=element('div');d.append(element('span',label),element('strong',fmt(b[k])));return d}));const rates=barChanges(i);$('bar-changes').replaceChildren(...[['봉 등락률 · 시가 대비',rates.body],['직전 저장봉 종가 대비',rates.previous]].map(([label,rate])=>{const d=element('div');d.append(element('span',label),element('strong',signedPercent(rate),changeClass(rate)));return d}));$('ma-values').replaceChildren(element('span',b.ts+' KST'+(b.end_ts?(['week','month'].includes(frame)?' ~ '+b.end_ts+' 마지막 거래일':' ~ '+b.end_ts.slice(11,16)+' 직전 · 원본 '+b.source_count+'/'+record.interval_minutes+'개 분봉'):''),'ma-timestamp'),...periods().map(n=>element('span',n+maUnit()+'선 '+fmt(b['ma'+n])+(b['ma'+n]==null?' (이력 부족)':'원'),'ma-value ma'+n)));if(record.kind==='preview')$('ma-values').append(element('span',frame==='month'?'이번 달 봉은 진행 중일 수 있습니다.':frame==='week'?'이번 주 봉은 진행 중일 수 있습니다.':'장중 마지막 봉은 진행 중일 수 있습니다.','ma-timestamp'));for(const tr of $('bars').rows)tr.classList.toggle('chosen',Number(tr.dataset.index)===i);draw()}
function visible(){if(!record)return[];if(viewRange)return record.bars.filter(b=>b.ts>=viewRange.start&&b.ts<=viewRange.end);const n=$('range').value;return n==='all'?record.bars:record.bars.slice(-Number(n))}
const updateChartButtons=bindChartExports(()=>({record,bars:visible(),canvas:$('chart')}),()=>{if(pick)selectStock(pick,record?.bars[selected]?.ts||null,true,true)},draw);
function draw(){updateChartButtons(!!code,!!record?.bars.length);const canvas=$('chart'),dpr=window.devicePixelRatio||1,w=canvas.clientWidth||800,h=canvas.clientHeight||500;canvas.width=Math.round(w*dpr);canvas.height=h*dpr;const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);chartGeometry=null;paint(ctx,w,h);updateZoomControls();positionTooltip()}
function paint(ctx,w,h){
  const bars=visible();
  chartGeometry=paintCandles(ctx,w,h,bars,periods());
  if(!chartGeometry)return;
  if (drag) paintChartSelection(ctx, chartGeometry, bars.indexOf(record.bars[drag.start]),
    bars.indexOf(record.bars[drag.end]), barLabel);
  const index = bars.indexOf(record.bars[hover?.index ?? selected]);
  const offset = 0;
  paintChartCrosshair(ctx, chartGeometry, index, hover?.y, barLabel, offset, hover ? '#000080' : '#6b5a9d');
}
function clearHover(){hover=null;$('chart-hover').hidden=true}
function cancelDrag(){const d=drag;drag=null;if(d&&$('chart').hasPointerCapture(d.pointerId))$('chart').releasePointerCapture(d.pointerId)}
function resetChartView(){cancelDrag();clearHover();viewRange=null;if($('range').value==='custom')$('range').value=rangeBeforeZoom||'all';rangeBeforeZoom=null}
function prepareChartRecord(next,previous=record){if(!previous||previous.frame!==next.frame||previous.day!==next.day||previous.stock.code!==next.stock.code)resetChartView();else{cancelDrag();clearHover()}}
function updateZoomControls(){const bars=visible();$('zoom-reset').disabled=!viewRange;$('zoom-status').textContent=bars.length?`표시 ${barLabel(bars[0].ts)} ~ ${barLabel(bars[bars.length-1].ts)} · ${chartRangeStatus(bars.length,$('range').value)}`:''}
function zoomTo(start,end){if(!record)return;const a=Math.min(start,end),b=Math.max(start,end);if(b-a<2)return;if($('range').value!=='custom')rangeBeforeZoom=$('range').value;viewRange={start:record.bars[a].ts,end:record.bars[b].ts};$('range').value='custom';clearHover();draw()}
function zoomReset(){resetChartView();draw();}
function queueDraw(){if(drawFrame!==null)return;drawFrame=requestAnimationFrame(()=>{drawFrame=null;draw()})}
function chartPoint(event, clamp = false) {
  const point = chartPointer($('chart'), chartGeometry, event, clamp);
  if (!point) return null;
  return {...point, index:record.bars.indexOf(chartGeometry.bars[point.index])};
}
function positionTooltip() {
  const bar = hover && !drag ? record?.bars[hover.index] : null;
  positionChartHover($('chart-hover'), $('chart'), chartGeometry,
    chartGeometry?.bars.includes(bar) ? bar : null, record?.bars[(hover?.index ?? 0)-1], hover?.y);
}
$('chart').addEventListener('pointermove',event=>{const p=chartPoint(event,!!drag);if(!p){clearHover();queueDraw();return}hover=p;if(drag&&drag.pointerId===event.pointerId)drag.end=p.index;queueDraw()});
$('chart').addEventListener('pointerleave',()=>{if(!drag){clearHover();queueDraw()}});
$('chart').addEventListener('pointerdown',event=>{if(event.button!==0)return;const p=chartPoint(event);if(!p)return;drag={start:p.index,end:p.index,startX:p.x,pointerId:event.pointerId};hover=p;$('chart').setPointerCapture(event.pointerId);event.preventDefault();queueDraw()});
$('chart').addEventListener('pointerup',event=>{if(!drag||drag.pointerId!==event.pointerId)return;const p=chartPoint(event,true),d=drag;cancelDrag();if(!p){clearHover();draw();return}if(Math.abs(p.x-d.startX)>=6&&Math.abs(p.index-d.start)>=2)zoomTo(d.start,p.index);else if(Math.abs(p.x-d.startX)<6)selectMinute(p.index);else{clearHover();draw()}});
$('chart').addEventListener('pointercancel',()=>{cancelDrag();clearHover();draw()});
$('chart').addEventListener('lostpointercapture',()=>{if(drag){drag=null;clearHover();draw()}});
$('chart').addEventListener('dblclick',zoomReset);
$('zoom-reset').onclick=zoomReset;
$('minute').onchange=()=>selectMinute(Number($('minute').value));$('range').onchange=()=>{cancelDrag();clearHover();viewRange=null;rangeBeforeZoom=null;draw();if(pick)selectStock(pick,record?.bars[selected]?.ts||null,true)};

function updateFrameControls(){$('chart-frame').value=frame;drawChartLegend($('legend'),periods());$('detail-title').textContent=frame==='day'?'선택한 거래일':frame==='week'?'선택한 주':frame==='month'?'선택한 월':'선택한 '+frameLabel();$('time-heading').textContent=frame==='day'?'날짜 (KST)':frame==='week'?'주 시작일 (KST)':frame==='month'?'월 (KST)':'시각 (KST)';$('close-heading').textContent=closeLabel().replace(' · ',' (')+')';$('minute').setAttribute('aria-label',frame==='day'?'거래일 선택':frame==='week'?'주 선택':frame==='month'?'월 선택':'분 선택');$('chart').setAttribute('aria-label',frameLabel()+' 캔들 차트');$('change-help').textContent=frame==='day'?'봉 등락률은 시가→종가, 직전봉 대비는 이전 거래일 종가→현재 종가입니다.':frame==='month'?'봉 등락률은 해당 월 시가→종가, 직전봉 대비는 이전 월 종가→현재 종가입니다.':frame==='week'?'봉 등락률은 해당 주 시가→종가, 직전봉 대비는 이전 주 종가→현재 종가입니다.':'봉 등락률은 시가→종가, 직전봉 대비는 직전 저장봉 종가→현재 종가입니다. 빈 분은 임의로 채우지 않습니다.';}
async function switchFrame(next){if(next===frame)return;const previous=pick;frame=next;requestVersion++;resetChartView();record=null;updateFrameControls();if(previous)await selectStock(previous);else draw()}
$('chart-frame').onchange=()=>switchFrame($('chart-frame').value);updateFrameControls();
$('chart-source').onchange=()=>{if(pick)selectStock(pick)};
setInterval(()=>{if(pick&&!chartLoading&&!document.hidden&&!drag&&$('chart-source').value==='live')selectStock(pick,record?.bars[selected]?.ts||null,true);},15000);

/* ---------- Theme list ---------- */
function movements(r){
  const h=r.history||[], result={};
  const prev=h.length>1?h[h.length-2].themes.map(t=>t.code):null;
  const first={}, best={};
  h.forEach(m=>m.themes.forEach((t,i)=>{if(!(t.code in first))first[t.code]=m.at;best[t.code]=Math.min(best[t.code]??99,i+1)}));
  r.themes.forEach((t,i)=>{const before=prev?prev.indexOf(t.code):-2;result[t.code]={move:before===-2?null:before<0?'new':before-i,first:first[t.code],best:best[t.code]}});
  return result;
}
function moveChip(m){
  if(m==null)return null;
  if(m==='new')return el('span','NEW','th-move new');
  if(m===0)return el('span','–','th-move flat');
  return el('span',(m>0?'▲':'▼')+Math.abs(m),'th-move '+(m>0?'up':'down'));
}
function leaders(){const r=state&&state.record;if(!r)return[];return [...r.themes.map((t,i)=>[t,i+1]),...(r.custom||[]).map(t=>[t,'내'])].flatMap(([t,rank])=>(t.leaders||[]).map(s=>({code:s.code,name:s.name,rate:s.rate,theme:t.code,themeName:t.name,rank})))}
function markPicked(){for(const li of document.querySelectorAll('.th-leaders li[data-code]')){const on=!!pick&&li.dataset.code===pick.code&&li.dataset.theme===pick.theme;li.classList.toggle('sel',on);li.setAttribute('aria-pressed',String(on))}}
function card(t,i,info,top100){
  const custom=t.source==='custom';
  const c=el('div',null,'th-card'+(custom?' custom':i<3?' podium p'+(i+1):''));
  const head=el('div',null,'th-card-head');
  head.append(el('span',custom?'내':String(i+1),'th-rank'));
  const title=el('div',null,'th-title');title.append(el('h3',t.name));
  const meta=el('div',null,'th-meta');const chip=moveChip(info.move);if(chip)meta.append(chip);meta.append(el('span',custom?`${t.stocks}종목 평균`:`구성 ${t.stocks}종목`));
  if(t.edited)meta.append(el('span','편집됨','th-edited'));
  const edit=el('button','편집','th-edit');edit.type='button';edit.title=custom?'내 테마 편집':'이 테마의 종목 편집';edit.onclick=()=>openEditor(custom?{custom:t.id}:{theme:t});meta.append(edit);
  title.append(meta);head.append(title);head.append(el('strong',pct(t.rate),'th-rate '+tone(t.rate)));c.append(head);
  const flat=Math.max(0,t.stocks-t.rising-t.falling);
  const bar=el('div',null,'th-breadth');bar.setAttribute('role','img');bar.setAttribute('aria-label',`상승 ${t.rising} 하락 ${t.falling} 보합 ${flat}`);
  for(const [n,cls] of [[t.rising,'r'],[t.falling,'f'],[flat,'z']]){if(!n)continue;const s=el('i',null,cls);s.style.flexGrow=n;bar.append(s)}
  c.append(bar,el('div',`상승 ${t.rising} · 하락 ${t.falling} · 보합 ${flat}`,'th-breadth-text'));
  const src=el('div',null,'th-source'+(t.source==='watchlist'?' mine':''));
  if(t.source==='watchlist'&&t.group){src.append(el('b','내 테마'),el('span',groupLabel(t.group)),el('small',`${t.group.reason} · 그룹 ${t.group.size}종목 중 등락률 상위 ${(t.leaders||[]).length}`))}
  else if(custom){src.append(el('b','직접 만든 테마'),el('span',`${t.stocks}종목`),el('small','내가 고른 종목의 오늘 등락률 평균 · 고정 종목이 먼저 표시'))}
  else if(t.source){src.append(el('b','키움 종목'),el('span',t.match_note||'관심종목 없음'),el('small','맞는 관심종목 그룹이 없어 키움 구성종목 표시'))}
  if(t.source)c.append(src);
  const list=el('ul',null,'th-leaders');
  for(const s of t.leaders||[]){
    const li=el('li');li.dataset.code=s.code;li.dataset.theme=t.code;li.tabIndex=0;li.setAttribute('role','button');
    const profile=stockProfiles[s.code]||{};
    const left=el('div',null,'th-stock');left.append(el('b',s.name,'stock-name-text'),el('small','• '+s.code),memoButton(s));
    left.append(el('small','테마 · '+t.name,'th-classification'),el('small','• 관심그룹 · '+(profile.groups?.join(' · ')||'미확인'),'th-classification'));
    left.append(el('small',(profile.industry?'업종 · '+profile.industry:'업종 확인중'),'th-classification'),el('small','• '+marketCapText(profile,chosen),'th-classification stock-money'));
    if(s.pinned)left.append(el('span','고정','th-tag pin'));
    if(s.added)left.append(el('span','추가','th-tag add'));
    if(top100&&s.code in top100)left.append(el('span','TOP100 '+top100[s.code]+'위','th-top100'));
    li.append(left,el('span',fmt(s.price),'th-price'),el('span',pct(s.rate),'th-chip '+tone(s.rate)));
    const p={code:s.code,name:s.name,rate:s.rate,theme:t.code,themeName:t.name,rank:custom?'내':i+1};
    li.onclick=()=>{selectStock(p);linkHero(p.code)};li.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectStock(p);linkHero(p.code)}};
    list.append(li);
  }
  if(!(t.leaders||[]).length)list.append(el('li','구성종목 정보 없음','th-none'));
  c.append(list);
  const foot=[];if(info.first)foot.push('첫 진입 '+info.first);if(info.best)foot.push('오늘 최고 '+info.best+'위');
  if(foot.length)c.append(el('div',foot.join(' · '),'th-card-foot'));
  return c;
}
function timeline(r){
  const box=$('timeline');box.replaceChildren();
  const slots=new Map();
  for(const m of r.history||[]){
    const match=String(m.at).match(/(\d{2}):(\d{2})/), t=m.themes?.[0];
    if(!match||!t)continue;
    const minute=Number(match[1])*60+Number(match[2]);
    const slot=Math.floor((minute-480)/45)*45+480;
    const previous=slots.get(slot);
    if(!previous||minute>=previous.minute)slots.set(slot,{at:m.at,t,minute});
  }
  const time=m=>String(Math.floor(m/60)).padStart(2,'0')+':'+String(m%60).padStart(2,'0');
  const items=[...slots].sort((a,b)=>b[0]-a[0]);
  if(!items.length){box.append(el('li','기록 없음','th-none'));return}
  for(const [i,[slot,{at,t}]] of items.entries()){
    const li=el('li',null,i===0?'now':'');
    const stamp=el('time',time(slot)+'–'+time(slot+44));
    stamp.title='실제 수집 '+at;
    const name=el('b',t.name);name.append(el('small',' · 수집 '+at,'timeline-collected'));
    li.append(stamp,name,el('span',pct(t.rate),'th-chip '+tone(t.rate)));box.append(li);
  }
}
function renderDays(){
  window.collectorRenderDateTabs($('days'),state.days.map(day=>({value:day,day,label:day})),chosen,day=>load(day));
}

function render(){
  const r=state.record;

  $('kept').textContent=`${state.days.length} / ${state.keep_days}거래일`;
  $('auto').textContent=state.monitor?`${Math.round(state.interval_seconds/60)}분 간격`:'중지됨';
  $('auto').className=state.monitor?'on':'off';
  $('updated').textContent=r?r.updated_at.slice(11,16):'—';
  renderDays();
  const err=state.last_error;
  $('status').textContent=err&&(err.day===chosen||err.day>chosen)&&(!r||err.at>r.updated_at)?err.day+' '+err.at.slice(11,16)+' 테마 갱신 확인 필요 · '+err.message+(r?' · '+chosen+' 저장본 표시':''):'';
  const grid=$('grid'),scroll=grid.scrollTop;grid.replaceChildren();
  if(!r||!r.themes.length){
    grid.append(el('div',r?'조건에 맞는 상승 테마가 없습니다.':'아직 이 날짜의 테마 자료가 없습니다. 당일 거래 확인 후 자동으로 갱신합니다.','th-empty'));
    $('timeline').replaceChildren(el('li','기록 없음','th-none'));
  }else{
    const info=movements(r);
    r.themes.forEach((t,i)=>grid.append(card(t,i,info[t.code]||{},state.top100)));
    timeline(r);
  }
  const mine=el('div',null,'th-mine-head');mine.append(el('b','내가 만든 테마'),el('span',r&&r.custom&&r.custom.length?`${r.custom.length}개 · 평균 등락률 순`:'관심종목에서 골라 나만의 테마를 만들어 보세요'));grid.append(mine);
  for(const t of (r&&r.custom)||[])grid.append(card(t,0,{},state.top100));
  const add=el('button','+ 새 테마 만들기','th-new');add.type='button';add.onclick=()=>openEditor({custom:null});grid.append(add);
  grid.scrollTop=scroll;markPicked();
}

/* ---------- Theme editor: saved to data/themes/edits.json, applied at every refresh ---------- */
let edits=null, directory=null, limits=null, draft=null, searchHits=[];
const ed=id=>$('ed-'+id);
const knownNames=()=>{const m={...(directory?directory.names:{})};const r=state&&state.record;for(const t of r?[...r.themes,...(r.custom||[])]:[])for(const s of [...(t.candidates||[]),...(t.leaders||[])])m[s.code]=s.name;return m};
const knownRates=()=>{const m={};const r=state&&state.record;for(const t of r?[...r.themes,...(r.custom||[])]:[])for(const s of [...(t.candidates||[]),...(t.leaders||[])])m[s.code]=s.rate;return m};
function groupLabel(g){return typeof g.number==='string'?`★ ${g.name}`:`${String(g.number).padStart(2,'0')} ${g.name}`}
function groupCodes(n){
  if(typeof n==='string'){const c=edits&&edits.custom.find(c=>'c:'+c.id===n);return c?c.codes:[]}
  const g=directory&&directory.groups.find(g=>g.number===n);return g?g.codes:[];
}
function basePool(){
  if(draft.kind==='custom')return[];
  const t=draft.theme;
  if(draft.group==='kiwoom')return t.member_codes||[];
  if(draft.group!=='auto')return groupCodes(draft.group);
  if(t.source==='watchlist'&&t.group)return groupCodes(t.group.number);
  return t.member_codes||[];
}
async function openEditor(target){
  try{
    const data=await api('/api/theme-edits');edits=data.edits;directory=data;limits=data.limits;
  }catch(e){toast(e.message);return}
  if(target.theme){
    const t=target.theme,saved=edits.themes[t.name]||{};
    draft={kind:'theme',theme:t,name:t.name,group:'group' in saved?(saved.group===null?'kiwoom':saved.group):'auto',add:[...(saved.add||[])],remove:[...(saved.remove||[])],pin:[...(saved.pin||[])]};
  }else{
    const saved=target.custom&&edits.custom.find(c=>c.id===target.custom);
    if(target.custom&&!saved){toast('편집 자료에서 이 테마를 찾지 못했습니다. 새로 고침 후 다시 시도하세요.');return}
    if(!saved&&edits.custom.length>=limits.custom){toast(`내 테마는 최대 ${limits.custom}개까지 만들 수 있습니다.`);return}
    draft={kind:'custom',id:saved?saved.id:'',name:saved?saved.name:'',codes:[...(saved?saved.codes:[])],pin:[...(saved?saved.pin:[])]};
  }
  const custom=draft.kind==='custom';
  ed('kind').textContent=custom?'MY THEME':'THEME EDIT';
  ed('title').textContent=custom?(draft.id?'내 테마 편집':'새 테마 만들기'):draft.name;
  ed('sub').textContent=custom?'관심종목을 검색해 담으면 오늘 등락률 평균으로 보여 줍니다.':`키움 순위는 그대로 두고, 이 테마에 보여 줄 종목만 바꿉니다.`;
  ed('name-box').hidden=!custom;ed('group-box').hidden=custom;ed('delete').hidden=!(custom&&draft.id);ed('reset').hidden=custom;
  ed('name').value=draft.name;ed('name').maxLength=limits.name;
  if(!custom){
    const t=draft.theme,now=t.source==='watchlist'&&t.group?groupLabel(t.group):'키움 구성종목';
    const opts=[new Option(`자동 짝짓기 (지금: ${now})`,'auto'),new Option('키움 구성종목 사용','kiwoom')];
    if(edits.custom.length){const mine=document.createElement('optgroup');mine.label='내가 만든 테마';for(const c of edits.custom)mine.append(new Option(`★ ${c.name} · ${c.codes.length}종목`,'c:'+c.id));opts.push(mine)}
    const groups=document.createElement('optgroup');groups.label='관심종목 그룹';
    for(const g of directory.groups.filter(g=>g.usable))groups.append(new Option(`${String(g.number).padStart(2,'0')} ${g.name} · ${g.codes.length}종목`,g.number));
    opts.push(groups);
    ed('group').replaceChildren(...opts);ed('group').value=String(draft.group);
    if(ed('group').value!==String(draft.group)){draft.group='auto';ed('group').value='auto'}
  }
  ed('search').value='';searchHits=[];ed('results').replaceChildren();
  renderDraft();ed('note').textContent=directory.note?'관심종목을 읽지 못했습니다: '+directory.note:'';$('editor').showModal();(custom&&!draft.id?ed('name'):ed('search')).focus();
}
function draftRows(){
  const names=knownNames(),rates=knownRates();
  const row=(code,extra)=>({code,name:names[code]||code,rate:rates[code],pinned:draft.pin.includes(code),...extra});
  let rows;
  if(draft.kind==='custom')rows=draft.codes.map(c=>row(c,{added:true}));
  else{const base=basePool();rows=[...base.map(c=>row(c,{removed:draft.remove.includes(c)})),...draft.add.filter(c=>!base.includes(c)).map(c=>row(c,{added:true}))]}
  return rows.sort((a,b)=>(b.pinned-a.pinned)||(a.removed-b.removed)||((b.rate??-999)-(a.rate??-999)));
}
function renderDraft(){
  const rows=draftRows(),list=ed('stocks');list.replaceChildren();ed('note').textContent='';
  const shown=rows.filter(r=>!r.removed);
  ed('count').textContent=draft.kind==='custom'?`${shown.length} / ${limits.custom_codes}종목 · 고정 ${draft.pin.length}/${limits.pin}`:`후보 ${shown.length}종목 중 상위 10 표시 · 고정 ${draft.pin.length}/${limits.pin} · 뺀 종목 ${draft.remove.length} · 추가 ${draft.add.length}`;
  if(!rows.length)list.append(el('li',draft.kind==='custom'?'위 검색창에서 종목을 담아 주세요.':'이 그룹에 종목이 없습니다.','ed-empty'));
  for(const r of rows){
    const li=el('li',null,'ed-stock'+(r.pinned?' pinned':'')+(r.removed?' removed':''));
    const info=el('div',null,'ed-info');info.append(el('b',r.name),el('small',r.code));if(r.added)info.append(el('span','추가','th-tag add'));
    const rate=el('span',r.rate==null?'—':pct(r.rate),'th-chip '+(r.rate==null?'flat':tone(r.rate)));
    const pin=el('button',r.pinned?'고정됨':'고정','ed-pin'+(r.pinned?' on':''));pin.type='button';pin.disabled=!!r.removed;pin.setAttribute('aria-pressed',String(r.pinned));
    pin.onclick=()=>{if(r.pinned)draft.pin=draft.pin.filter(c=>c!==r.code);else{if(draft.pin.length>=limits.pin){toast(`고정은 최대 ${limits.pin}종목까지 됩니다.`);return}draft.pin.push(r.code)}renderDraft()};
    const out=el('button',r.added?'삭제':r.removed?'되살리기':'빼기','ed-out'+(r.removed?' back':''));out.type='button';
    out.onclick=()=>{
      draft.pin=draft.pin.filter(c=>c!==r.code);
      if(draft.kind==='custom')draft.codes=draft.codes.filter(c=>c!==r.code);
      else if(r.added)draft.add=draft.add.filter(c=>c!==r.code);
      else if(r.removed)draft.remove=draft.remove.filter(c=>c!==r.code);
      else draft.remove.push(r.code);
      renderDraft()};
    li.append(info,rate,pin,out);list.append(li);
  }
}
function addCode(code){
  code=code.toUpperCase();
  if(draft.kind==='custom'){if(draft.codes.includes(code))return toast('이미 담긴 종목입니다.');if(draft.codes.length>=limits.custom_codes)return toast(`내 테마는 최대 ${limits.custom_codes}종목입니다.`);draft.codes.push(code)}
  else if(draft.remove.includes(code))draft.remove=draft.remove.filter(c=>c!==code);
  else if(basePool().includes(code)||draft.add.includes(code))return toast('이미 후보에 있는 종목입니다.');
  else{if(draft.add.length>=limits.add)return toast(`추가는 최대 ${limits.add}종목입니다.`);draft.add.push(code)}
  ed('search').value='';searchHits=[];ed('results').replaceChildren();renderDraft();ed('search').focus();
}
function search(){
  const q=ed('search').value.trim().toUpperCase(),box=ed('results');box.replaceChildren();searchHits=[];
  if(!q)return;
  const names=knownNames();
  searchHits=Object.entries(names).filter(([c,n])=>c.includes(q)||n.toUpperCase().includes(q)).sort((a,b)=>(b[1].toUpperCase().startsWith(q))-(a[1].toUpperCase().startsWith(q))||a[1].localeCompare(b[1],'ko')).slice(0,12).map(([c])=>c);
  if(!searchHits.length&&/^[0-9A-Z]{6}$/.test(q))searchHits=[q];
  if(!searchHits.length){box.append(el('li','검색 결과가 없습니다. 6자리 종목코드를 그대로 입력해도 됩니다.','ed-empty'));return}
  for(const c of searchHits){const li=el('li');li.append(el('b',names[c]||'코드로 추가'),el('small',c));li.onclick=()=>addCode(c);box.append(li)}
}
function nextEdits(){
  const doc={themes:{...edits.themes},custom:edits.custom.map(c=>({...c}))};
  if(draft.kind==='theme'){
    const item={add:draft.add,remove:draft.remove,pin:draft.pin};
    if(draft.group!=='auto')item.group=draft.group==='kiwoom'?null:draft.group;
    if('group' in item||item.add.length||item.remove.length||item.pin.length)doc.themes[draft.name]=item;else delete doc.themes[draft.name];
  }else{
    const item={id:draft.id,name:ed('name').value.trim(),codes:draft.codes,pin:draft.pin.filter(c=>draft.codes.includes(c))};
    const at=doc.custom.findIndex(c=>c.id&&c.id===draft.id);if(at>=0)doc.custom[at]=item;else doc.custom.push(item);
  }
  return doc;
}
async function saveEdits(doc,message){
  ed('save').disabled=true;
  try{
    const send=async()=>fetch('/api/theme-edits',{method:'POST',headers:{'Content-Type':'application/json','X-Collector-Token':await token()},body:JSON.stringify({edits:doc,revision:edits.revision})});
    let r=await send();
    if(r.status===403){sessionToken='';r=await send()}
    const data=await r.json();
    if(r.status===409){edits=data.edits;toast(data.error);return}
    if(!r.ok)throw Error(data.error||'저장 실패');
    edits=data.edits;$('editor').close();
    toast(message+(data.refresh==='started'?' · 오늘 테마를 바로 다시 계산합니다.':data.refresh==='queued'?' · 지금 진행 중인 수집이 끝나면 반영됩니다.':' · 다음 테마 갱신부터 반영됩니다.'));
    if(data.refresh!=='saved')watchRefresh(data.edits.revision);
  }catch(e){toast(e.message)}
  finally{ed('save').disabled=false}
}
let sessionToken='';
async function token(){if(!sessionToken)sessionToken=(await api('/api/status')).token;return sessionToken}
function watchRefresh(revision){
  const until=Date.now()+240000;
  const tick=async()=>{if(!state||chosen!==state.days[0])return;await load();const r=state&&state.record;if(r&&r.edits_revision===revision){toast('편집 내용이 반영됐습니다.');return}if(Date.now()<until)setTimeout(tick,3000)};
  setTimeout(tick,2500);
}
ed('group').onchange=()=>{const v=ed('group').value;draft.group=v==='auto'||v==='kiwoom'||v.startsWith('c:')?v:Number(v);renderDraft()};
ed('search').oninput=search;
ed('search').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();if(searchHits[0])addCode(searchHits[0])}};
ed('reset').onclick=()=>{draft.group='auto';draft.add=[];draft.remove=[];draft.pin=[];ed('group').value='auto';renderDraft()};
ed('cancel').onclick=ed('close').onclick=()=>$('editor').close();
ed('save').onclick=()=>{
  if(draft.kind==='custom'){const name=ed('name').value.trim();if(!name){toast('테마 이름을 입력하세요.');ed('name').focus();return}if(!draft.codes.length){toast('종목을 1개 이상 담아 주세요.');ed('search').focus();return}}
  saveEdits(nextEdits(),'저장했습니다');
};
ed('delete').onclick=()=>{if(!confirm(`'${draft.name}' 테마를 삭제할까요?`))return;const doc={themes:edits.themes,custom:edits.custom.filter(c=>c.id!==draft.id)};saveEdits(doc,'삭제했습니다')};
/* ---------- Stock memo: Hero4 memo (read only) + the collector's own memo for the chosen day ---------- */
let dayNotes={}, hero4Memos={}, memoTarget=null, memoHideTimer=null;
const hasMemo=c=>!!hero4Memos[c]||!!dayNotes[c]?.text?.trim();
async function loadMemos(day){
  try{const r=await api('/api/notes?'+new URLSearchParams({day}));if(day!==chosen)return;dayNotes=r.notes||{};hero4Memos=r.hero4||{};
    for(const b of document.querySelectorAll('.th-memo'))b.classList.toggle('has-note',hasMemo(b.dataset.code))}
  catch(e){}
}
function memoButton(s){
  const b=el('button',null,'memo-mark th-memo'+(hasMemo(s.code)?' has-note':''));b.type='button';b.dataset.code=s.code;b.setAttribute('aria-label',s.name+' 메모');
  b.append(el('span',null,'memo-triangle'));
  b.onclick=e=>{e.stopPropagation();openMemo(s)};b.onkeydown=e=>e.stopPropagation();
  b.onpointerenter=()=>showMemoPreview(b,s);b.onpointerleave=()=>{memoHideTimer=setTimeout(hideMemoPreview,200)};
  return b;
}
function hero4Box(c,compact=false){
  const text=hero4Memos[c],box=el('div',null,'hero4-box'+(compact?' compact':'')),head=el('div',null,'reason-head');
  head.append(el('b','영웅문 메모'),el('span',text?'올해 · 읽기 전용':'없음','reason-tag '+(text?'hero4':'none')));
  box.append(head,el('p',text||'영웅문에 올해 메모가 없습니다.','hero4-text'));
  return box;
}
function hideMemoPreview(){clearTimeout(memoHideTimer);$('memo-preview').hidden=true}
function showMemoPreview(button,s){
  if($('memo-dialog').open)return;clearTimeout(memoHideTimer);
  const note=dayNotes[s.code],box=$('memo-preview');
  box.replaceChildren(el('strong',s.name+' · '+chosen),hero4Box(s.code,true),el('div',note?.text?.trim()?note.text:'내 메모가 없습니다. 삼각형을 클릭하면 작성할 수 있습니다.','memo-preview-text'));
  box.hidden=false;const r=button.getBoundingClientRect();
  box.style.left=Math.max(8,Math.min(r.right+9,window.innerWidth-box.offsetWidth-8))+'px';
  box.style.top=Math.max(8,Math.min(r.top,window.innerHeight-box.offsetHeight-8))+'px';
}
async function openMemo(s){
  hideMemoPreview();const day=chosen;
  try{
    const r=await api('/api/notes?'+new URLSearchParams({day}));dayNotes=r.notes||{};hero4Memos=r.hero4||{};
    const note=dayNotes[s.code]||{};memoTarget={day,code:s.code,name:s.name,revision:note.revision||''};
    $('memo-title').textContent=s.name+' · 종목 메모';$('memo-date').textContent=day+' / '+s.code;
    $('memo-hero4').replaceChildren(hero4Box(s.code));$('memo-text').value=note.text||'';
    $('memo-status').textContent=note.updated_at?'마지막 저장 '+note.updated_at.slice(0,19).replace('T',' ')+' KST':'';
    $('memo-dialog').showModal();
  }catch(e){toast('메모를 열지 못했습니다: '+e.message)}
}
$('memo-save').onclick=async()=>{
  if(!memoTarget)return;const t=memoTarget;$('memo-save').disabled=true;$('memo-status').textContent='저장 중…';
  try{
    const send=async()=>fetch('/api/notes',{method:'POST',headers:{'Content-Type':'application/json','X-Collector-Token':await token()},body:JSON.stringify({day:t.day,code:t.code,name:t.name,revision:t.revision,text:$('memo-text').value})});
    let r=await send();if(r.status===403){sessionToken='';r=await send()}
    const data=await r.json();if(!r.ok)throw Error(data.error||'저장 실패');
    memoTarget={...t,revision:data.note.revision};dayNotes[t.code]=data.note;
    for(const b of document.querySelectorAll(`.th-memo[data-code="${t.code}"]`))b.classList.toggle('has-note',hasMemo(t.code));
    $('memo-status').textContent='저장 완료 · '+data.note.updated_at.slice(0,19).replace('T',' ')+' KST';
  }catch(e){$('memo-status').textContent=e.message}
  finally{$('memo-save').disabled=false}
};
$('memo-close').onclick=()=>{$('memo-dialog').close();memoTarget=null};
$('memo-preview').onpointerenter=()=>clearTimeout(memoHideTimer);$('memo-preview').onpointerleave=hideMemoPreview;
$('grid').addEventListener('scroll',hideMemoPreview);window.addEventListener('scroll',hideMemoPreview);
let themeRequest=0;
async function load(day){
  if(themeLoading&&!day)return;
  const version=++themeRequest;
  themeLoading=true;
  try{
    const data=await api('/api/themes'+(day?'?day='+encodeURIComponent(day):''));
    if(version!==themeRequest)return;
    const dayChanged=data.day!==chosen;
    if(dayChanged){dayNotes={};stockProfiles={};hideMemoPreview()}
    state=data;chosen=data.day;render();loadMemos(chosen);
    api('/api/stock-profiles?day='+encodeURIComponent(chosen)).then(result=>{if(chosen===result.day){stockProfiles=result.profiles||{};render()}}).catch(()=>{});
    const r=state.record,updated=r?r.updated_at:'';
    const available=leaders();
    const current=available.find(stock=>stock.code===pick?.code&&stock.theme===pick?.theme);
    if(dayChanged||!current){requestVersion++;clearChart();if(available.length)selectStock(available[0])}
    else if(updated!==lastUpdated&&!chartLoading)selectStock(current,record?.bars[selected]?.ts,null!==record);
    lastUpdated=updated;
  }catch(e){if(version===themeRequest)$('status').textContent=e.message||'수집기 연결을 확인하세요.'}
  finally{if(version===themeRequest)themeLoading=false}
}
document.addEventListener('keydown',e=>{
  if(!state||e.altKey||e.ctrlKey||e.metaKey||e.shiftKey||e.isComposing||e.target.closest('input,select,textarea,dialog,[contenteditable="true"]'))return;
  if(e.key==='ArrowLeft'||e.key==='ArrowRight'){const i=state.days.indexOf(chosen);if(e.key==='ArrowLeft'&&i<state.days.length-1)load(state.days[i+1]);if(e.key==='ArrowRight'&&i>0)load(state.days[i-1]);return}
  if(e.key==='ArrowUp'||e.key==='ArrowDown'){
    const list=leaders();if(!list.length)return;e.preventDefault();
    const at=pick?list.findIndex(s=>s.code===pick.code&&s.theme===pick.theme):-1;
    const next=list[Math.max(0,Math.min(list.length-1,at+(e.key==='ArrowDown'?1:-1)))];
    if(next&&(!pick||next.code!==pick.code||next.theme!==pick.theme)){selectStock(next);linkHero(next.code);document.querySelector(`.th-leaders li[data-code="${next.code}"][data-theme="${next.theme}"]`)?.scrollIntoView({block:'nearest'})}
  }
});
window.addEventListener('DOMContentLoaded',()=>{new ResizeObserver(draw).observe($('chart').parentElement);load();setInterval(()=>{if(state&&(!state.days.length||chosen===state.days[0]))load()},30000)});

async function loadHeroTargets(){try{const r=await api("/api/hero-targets"),previous=$("hero-target").value||localStorage.getItem("collector-hero-chart")||r.preferred||"";$("hero-target").replaceChildren(new Option("영웅문 0600 · 자동 선택",""),new Option("영웅문 연동 끄기","off"),...r.targets.map(t=>new Option(t.label,t.handle)));$("hero-target").value=previous==="off"||r.targets.some(t=>t.handle===previous)?previous:r.targets.some(t=>t.handle===r.preferred)?r.preferred:"";localStorage.setItem("collector-hero-chart",$("hero-target").value)}catch(e){}}
$("hero-target").onchange=()=>localStorage.setItem("collector-hero-chart",$("hero-target").value);
window.addEventListener("DOMContentLoaded",()=>{loadHeroTargets();setInterval(loadHeroTargets,30000)});
