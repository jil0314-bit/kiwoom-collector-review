'use strict';
const $=id=>document.getElementById(id), fmt=n=>n==null?'—':Number(n).toLocaleString('ko-KR',{maximumFractionDigits:2});
let status={}, meta={stocks:[]}, record=null, choice='', code='', selected=-1, requestVersion=0, refreshing=false, openedFlag=false;
let frame='minute', loading=false, liveChart=document.body.dataset.sharedViewer!=='1', quoteList=false; /* 2026-11-17: 차트는 현재 차트로 열림. 목록 현재가 자동조회(quoteList)는 기준을 직접 고를 때만 */
let liveQuotes={},quoteRequest=0,quotesBusy=false;
let listMode='ranking', watchlists=[], watchGroup='';
let stockProfiles={}, profileDay='', profileAt=0, profileVersion=0;
const profileLabel=p=>p?.themes?.length?'테마 · '+p.themes.slice(0,2).join(' · ')+(p.themes.length>2?' 외 '+(p.themes.length-2):''):p?.groups?.length?'관심그룹 · '+p.groups.slice(0,2).join(' · ')+(p.groups.length>2?' 외 '+(p.groups.length-2):''):p?.industry?'테마 미확인 · 업종 '+p.industry:'테마 미확인';
const marketCapText=(cap,capDay,day)=>cap>0?'시총 '+formatWon(cap,1e8)+(capDay&&capDay!==day?' · '+capDay+' 기준':''):'시총 확인중';
async function loadProfiles(day){
  if(profileDay===day&&Date.now()-profileAt<60000)return;
  if(profileDay!==day)stockProfiles={};
  profileDay=day;profileAt=Date.now();const version=++profileVersion;
  try{const data=await api('/api/stock-profiles?day='+encodeURIComponent(day));if(version!==profileVersion||choice.split('|')[0]!==day)return;stockProfiles=data.profiles||{};renderStocks()}catch(e){}
}
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
const toast=text=>{$('toast').textContent=text;$('toast').style.display='block';setTimeout(()=>$('toast').style.display='none',6500)};
async function api(path,options){if(path.startsWith('/api/chart?'))path+='&fast=1&async=1';const r=await (path.startsWith('/api/chart?')&&!path.includes('prefetch=1')?collectorChartFetch(path,options):fetch(path,options));const data=await r.json();if(!r.ok)throw Error(data.error||'요청 실패');return data}
function params(withRevision=false){const [day,kind]=choice.split('|');const q=new URLSearchParams({day,kind,code});q.set('frame',frame);q.set('source','volume');if(Number(rangeBeforeZoom??$('range').value)>=360)q.set('history','1');if(liveChart)q.set('live','1');if(withRevision)q.set('rev',meta.revision||meta.ranking_at||'');return q}
const activeGroup=()=>watchlists.find(g=>String(g.number)===watchGroup);
const currentEntries=()=>listMode==='watchlist'?(meta.tracked||[]):meta.stocks;
const currentStocks=()=>currentEntries().filter(s=>s.type!=='heading');
const displayedEntries=()=>{const query=$('search').value.trim().toLowerCase();return currentEntries().filter(s=>!query||s.type!=='heading'&&(s.name+s.code).toLowerCase().includes(query))};
async function loadWatchlists(){try{const result=await api('/api/watchlists');const previous=watchGroup;watchlists=result.groups;$('watch-group').replaceChildren(...watchlists.map(g=>new Option(String(g.number).padStart(2,'0')+' · '+g.name+' ('+g.entries.filter(e=>e.type==='stock').length+')',g.number)));watchGroup=watchlists.some(g=>String(g.number)===previous)?previous:String(watchlists[0]?.number||'');$('watch-group').value=watchGroup;if(listMode==='watchlist')renderStocks()}catch(e){if(listMode==='watchlist')$('stocks').replaceChildren(element('div',e.message,'empty'))}}
function element(tag,text,cls){const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e}
async function post(path,body={}){return api(path,{method:'POST',headers:{'Content-Type':'application/json','X-Collector-Token':status.token},body:JSON.stringify(body)})}
async function refresh(){if(refreshing)return;refreshing=true;try{status=await api('/api/volume/status');$('auth').textContent=status.credentials?'인증정보 준비됨':'인증정보 필요';$('progress').textContent=status.state.message+(status.state.retention_warning?' · '+status.state.retention_warning:'')+(status.state.queued?' · 다음 갱신 예약됨':'');$('collect').disabled=false;$('collect').textContent=status.state.queued?'다음 갱신 예약됨':status.state.busy?'수집 후 다시 갱신 예약':'지금 최신 자료 저장';$('preview').disabled=false;$('preview').textContent=status.monitor.enabled?'장중 자동 갱신 중지':'장중 자동 갱신 시작';$('auto-info').textContent=status.monitor.enabled?'목록 1분 · 분봉 순차 저장 · 20:05 최종':'장중 자동 갱신 중지 · 20:05 최종';
if(!openedFlag){openedFlag=true;post('/api/volume/open').catch(()=>{openedFlag=false});}

const old=$('archive').value;const catalog=status.catalog; $('archive').replaceChildren();for(const c of catalog){const value=c.day+'|'+c.kind;const o=new Option(c.day+(c.phase==='final'?' · 최종':c.day<status.now.slice(0,10)?' · 장중 저장 (최종 미수집)':' · 장중 최신')+(c.status==='partial'?' · 일부 실패':''),value);$('archive').add(o)}
if(!catalog.length){$('archive').add(new Option('오늘 · 첫 거래량 순위 조회 중',status.now.slice(0,10)+'|latest'));$('archive').value=$('archive').options[0].value;if(listMode==='ranking')return}else{const valid=catalog.some(c=>c.day+'|'+c.kind===old);$('archive').value=valid&&!followLatestDate?old:$('archive').options[0].value}
const changed=choice!==$('archive').value;choice=$('archive').value;await loadDay(changed);
}catch(e){$('auth').textContent='수집기 연결 확인 필요';$('progress').textContent=e.message||'실행 파일로 수집기를 켜주세요.'}finally{refreshing=false}}
let dayRequest=0, followLatestDate=true;
async function loadDay(changed=false){const version=++dayRequest,requested=choice;if(changed)liveQuotes={};const oldRevision=meta.revision||meta.ranking_at;const next=await api('/api/volume/day?'+params());if(version!==dayRequest||requested!==choice)return;meta=next;loadNotes(choice.split('|')[0]);loadProfiles(choice.split('|')[0]);$('saved').replaceChildren(document.createTextNode(String(meta.stocks.filter(s=>s.status==='saved').length)+' '),element('small','/ '+meta.stocks.length+'종목'));$('ranktime').textContent=(meta.kind==='preview'?(meta.day<status.now.slice(0,10)?'장중 저장 · 최종 미수집 · ':'장중 최신 · '):'최종 · ')+(meta.ranking_at||'').slice(11,19)+' KST';renderStocks();if(changed||!loading&&(!record||!liveChart&&listMode==='ranking'&&oldRevision!==(meta.revision||meta.ranking_at))){const keepTime=!changed&&record&&selected<record.bars.length-1?record.bars[selected]?.ts:null;const s=currentStocks().find(s=>s.code===code)||currentStocks()[0];if(s){if(changed)selectStock(s.code);else selectStock(s.code,keepTime)}else clearChart()}}
async function refreshQuotes(){
  if(quotesBusy||loading||!liveChart||!quoteList||document.hidden)return;
  const symbols=currentStocks().map(s=>s.code);if(!symbols.length)return;
  quotesBusy=true;const key=symbols.join(','),version=++quoteRequest;
  const valid=()=>version===quoteRequest&&currentStocks().map(s=>s.code).join(',')===key;
  try{
    for(let offset=0;offset<symbols.length;offset+=10){
      if(!valid()||loading||!liveChart)return;
      const r=await api('/api/quotes?codes='+encodeURIComponent(symbols.slice(offset,offset+10).join(',')));
      if(!valid())return;
      Object.assign(liveQuotes,r.quotes);renderStocks();
    }
  }catch(e){if(valid())toast('현재가 목록 조회 실패: '+e.message)}
  finally{quotesBusy=false}
}
function chooseCurrentStock(symbol){selectStock(symbol);linkHero(symbol);renderStocks()}
function renderStocks(){
const listScroll=$('stocks').scrollTop;
const focused=document.activeElement?.closest('[data-stock-code]'),focusCode=focused?.dataset.stockCode,focusMemo=document.activeElement?.classList.contains('memo-mark');
$('stocks').replaceChildren();
for(const s of displayedEntries()){
if(s.type==='heading'){$('stocks').append(element('div',s.label||'구분','watch-heading'));continue}
const row=element('div',null,'stock-row');row.dataset.stockCode=s.code;
const b=element('button',null,'stock'+(s.code===code?' active':''));b.setAttribute('aria-pressed',String(s.code===code));b.append(element('span',listMode==='watchlist'?'·':String(s.rank).padStart(2,'0'),'rank'));
const profile=stockProfiles[s.code]||{};const day=choice.split('|')[0];
const name=element('span',null,'name');name.append(element('span',s.name,'stock-name-text'),element('small','• 관심그룹 · '+(profile.groups?.join(' · ')||'미확인')+(profile.themes?.length?'  • '+profileLabel(profile):'')));const metrics=element('small','• '+s.code+'  ');metrics.append(element('span','• '+marketCapText(s.market_cap||profile.market_cap,s.market_cap?day:profile.cap_day,day),'stock-money'),document.createTextNode(' · '+(s.status==='saved'?s.count+'봉':'분봉 저장 중')));name.append(metrics);b.append(name);const q=(liveChart?liveQuotes[s.code]:null)||{price:s.price,rate:s.rate};name.append(element('small',fmt(q.price)+'원 · '+signedPercent(q.rate),'stock-money '+changeClass(q.rate)));b.append(element('span',signedPercent(s.volume_rate),'rate change-up'));b.onclick=()=>chooseCurrentStock(s.code);
row.append(b,noteMark(s));$('stocks').append(row)
}
$('stocks').scrollTop=listScroll;decorateNotes();renderVolumeSummary();
if(focusCode){const row=$('stocks').querySelector(`[data-stock-code="${focusCode}"]`);row?.querySelector(focusMemo?'.memo-mark':'.stock')?.focus({preventScroll:true})}
}
function clearChart(){resetChartView();record=null;code='';window.collectorStockTools?.(null);selected=-1;$('selected-name').textContent='저장된 종목을 선택하세요';$('selected-code').textContent='종목 선택';$('bars').replaceChildren();$('minute').replaceChildren();$('values').replaceChildren();$('bar-changes').replaceChildren();$('chart-empty').style.display='flex';draw()}
async function selectStock(next,keepTime=null,background=false,reload=false){const s=currentStocks().find(x=>x.code===next);if(!s){toast('선택한 종목이 목록에 없습니다.');return}code=next;window.collectorStockTools?.({day:meta.day||choice.split('|')[0],code,name:s.name,source:'volume'});const version=++requestVersion,previousRecord=record;const path='/api/chart?'+params(true);loading=true;cancelDrag();clearHover();if(!background){record=null;$('chart-empty').textContent=frameLabel()+' 이력을 불러오는 중입니다…';$('chart-empty').style.display='flex';$('values').replaceChildren();$('bar-changes').replaceChildren();$('bars').replaceChildren();$('minute').replaceChildren();$('ma-values').textContent='';draw()}try{const result=await api(path,reload?{cache:'reload'}:undefined);if(version!==requestVersion)return;if(result.stock?.code!==code||result.frame!==frame||!result.bars?.length)throw Error('선택한 종목의 차트 자료를 확인할 수 없습니다.');prepareChartRecord(result,previousRecord);record=result;selected=keepTime?record.bars.findIndex(b=>b.ts===keepTime):-1;if(selected<0)selected=record.bars.length-1;$('selected-name').textContent=s.name+(record.live&&record.quote?' · 현재가 '+fmt(record.quote.price)+'원 ('+signedPercent(record.quote.rate)+')':'');$('selected-code').textContent=s.code+' / '+record.day+(record.requested_day||record.live_fallback?' / 최근 거래 자료':record.live?' / 현재 차트 · 조회 '+record.fetched_at.slice(11,19)+' KST':listMode==='watchlist'?' / 거래량 급증 편입 자료':record.kind==='preview'?' / 장중 저장 자료':' / 최종 자료');$('chart-empty').style.display='none';$('minute').replaceChildren(...record.bars.map((b,i)=>new Option(barLabel(b.ts),i)));$('coverage').textContent=(record.chart_notice||'')+(record.live||listMode==='watchlist'||!frame.startsWith('minute')?'':` 수신 ${s.count}봉 · ${s.first.slice(11,16)}~${s.last.slice(11,16)} | 09시 전 ${s.pre}봉 · 09:00~15:30 ${s.regular}봉 · 15:30 이후 ${s.after}봉. 빈 시간은 비거래/미제공 여부 미확인.`);renderStocks();renderTable();selectMinute(selected);renderVolumeSummary();if(result.refreshing)setTimeout(()=>{if(version===requestVersion&&!document.hidden&&!drag)selectStock(next,record?.bars[selected]?.ts||null,true)},1000)}catch(e){if(version!==requestVersion||e.name==='AbortError')return;if(background&&previousRecord){record=previousRecord;$('coverage').textContent='현재 조회 실패 · 이전 자료 유지 · '+e.message;return}record=null;$('chart-empty').textContent=e.message;$('chart-empty').style.display='flex';toast(e.message);draw()}finally{if(version===requestVersion)loading=false}}
function renderTable(){const frag=document.createDocumentFragment();record.bars.forEach((b,i)=>{const tr=element('tr');tr.dataset.index=i;for(const k of ['ts','open','high','low','close'])tr.append(element('td',k==='ts'?barLabel(b.ts):fmt(b[k])));const rates=barChanges(i);for(const rate of [rates.body,rates.previous])tr.append(element('td',signedPercent(rate),changeClass(rate)));tr.append(element('td',fmt(b.volume)));tr.onclick=()=>selectMinute(i);frag.append(tr)});$('bars').replaceChildren(frag)}
function selectMinute(i){if(!record||!record.bars[i])return;clearHover();selected=i;const b=record.bars[i];$('minute').value=i;$('values').replaceChildren(...[['시가','open'],['고가 · 최고가','high'],['저가 · 최저가','low'],[closeLabel(),'close'],['거래량 (주)','volume']].map(([label,k])=>{const d=element('div');d.append(element('span',label),element('strong',fmt(b[k])));return d}));const rates=barChanges(i);$('bar-changes').replaceChildren(...[['봉 등락률 · 시가 대비',rates.body],['직전 저장봉 종가 대비',rates.previous]].map(([label,rate])=>{const d=element('div');d.append(element('span',label),element('strong',signedPercent(rate),changeClass(rate)));return d}));$('ma-values').replaceChildren(element('span',b.ts+' KST'+(b.end_ts?(['week','month'].includes(frame)?' ~ '+b.end_ts+' 마지막 거래일':' ~ '+b.end_ts.slice(11,16)+' 직전 · 원본 '+b.source_count+'/'+record.interval_minutes+'개 분봉'):''),'ma-timestamp'),...periods().map(n=>element('span',n+maUnit()+'선 '+fmt(b['ma'+n])+(b['ma'+n]==null?' (이력 부족)':'원'),'ma-value ma'+n)));if(record.kind==='preview')$('ma-values').append(element('span',frame==='month'?'이번 달 봉은 진행 중일 수 있습니다.':frame==='week'?'이번 주 봉은 진행 중일 수 있습니다.':'장중 마지막 봉은 진행 중일 수 있습니다.','ma-timestamp'));for(const tr of $('bars').rows)tr.classList.toggle('chosen',Number(tr.dataset.index)===i);draw()}
function visible(){if(!record)return[];if(viewRange)return record.bars.filter(b=>b.ts>=viewRange.start&&b.ts<=viewRange.end);const n=$('range').value;return n==='all'?record.bars:record.bars.slice(-Number(n))}
const updateChartButtons=bindChartExports(()=>({record,bars:visible(),canvas:$('chart')}),()=>{if(code)selectStock(code,record?.bars[selected]?.ts||null,true,true)},draw);
function draw(){updateChartButtons(!!code,!!record?.bars.length);const canvas=$('chart'),dpr=window.devicePixelRatio||1,w=canvas.clientWidth||800,h=canvas.clientHeight||500;canvas.width=Math.round(w*dpr);canvas.height=h*dpr;const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);chartGeometry=null;paint(ctx,w,h);updateZoomControls();positionTooltip()}
function paint(ctx,w,h){
  const bars=visible();
  chartGeometry=paintCandles(ctx,w,h,bars,periods());
  if(!chartGeometry)return;
  if (drag) paintChartSelection(ctx, chartGeometry, bars.indexOf(record.bars[drag.start]),
    bars.indexOf(record.bars[drag.end]), barLabel);
  const index = bars.indexOf(record.bars[hover?.index ?? selected]);
  const offset = !hover&&index===bars.length-1 ? chartGeometry.step : 0;
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
$('minute').onchange=()=>selectMinute(Number($('minute').value));$('range').onchange=()=>{cancelDrag();clearHover();viewRange=null;rangeBeforeZoom=null;draw();if(code)selectStock(code,record?.bars[selected]?.ts||null,true)};$('search').oninput=renderStocks;$('archive').onchange=async()=>{followLatestDate=$('archive').selectedIndex===0;choice=$('archive').value;requestVersion++;clearChart();await loadDay(true)};
$('list-mode').onchange=async()=>{listMode=$('list-mode').value;$('watch-group').hidden=true;$('list-badge').textContent=listMode==='watchlist'?'전체 편입':'급증 TOP 100';$('list-heading').textContent=listMode==='watchlist'?'오늘 편입 종목':'순위 / 종목';$('list-trailing').textContent='거래량 급증률';$('search').value='';requestVersion++;clearChart();renderStocks();const s=listMode==='watchlist'?currentStocks()[0]:meta.stocks.find(s=>s.status==='saved'||liveChart);if(s)chooseCurrentStock(s.code)};
$('watch-group').onchange=async()=>{watchGroup=$('watch-group').value;requestVersion++;clearChart();renderStocks();const s=currentStocks()[0];if(s)chooseCurrentStock(s.code)};
async function collect(){try{const r=await post('/api/volume/collect',{day:status.now.slice(0,10)});toast(r.state==='queued'?'현재 수집이 끝나면 최신 자료로 다시 갱신합니다.':r.state==='waiting'?'평일 08:00부터 수집합니다.':'순위는 최신으로 갱신하고, 오늘 편입 이력과 분봉은 보관합니다.');await refresh()}catch(e){toast(e.message)}}
$('preview').onclick=async()=>{try{const enabled=!status.monitor.enabled;await post('/api/volume/monitor',{enabled});toast(enabled?'목록 1분 간격 자동 갱신을 시작합니다.':'장중 자동 갱신 중지. 진행 중 수집은 완료하며 20:05 최종 수집은 유지합니다.');await refresh()}catch(e){toast(e.message)}};$('collect').onclick=collect;
function updateFrameControls(){$('chart-frame').value=frame;drawChartLegend($('legend'),periods());$('detail-title').textContent=frame==='day'?'선택한 거래일':frame==='week'?'선택한 주':frame==='month'?'선택한 월':'선택한 '+frameLabel();$('time-heading').textContent=frame==='day'?'날짜 (KST)':frame==='week'?'주 시작일 (KST)':frame==='month'?'월 (KST)':'시각 (KST)';$('close-heading').textContent=closeLabel().replace(' · ',' (')+')';$('minute').setAttribute('aria-label',frame==='day'?'거래일 선택':frame==='week'?'주 선택':frame==='month'?'월 선택':'분 선택');$('chart').setAttribute('aria-label',frameLabel()+' 캔들 차트');$('change-help').textContent=frame==='day'?'봉 등락률은 시가→종가, 직전봉 대비는 이전 거래일 종가→현재 종가입니다.':frame==='month'?'봉 등락률은 해당 월 시가→종가, 직전봉 대비는 이전 월 종가→현재 종가입니다.':frame==='week'?'봉 등락률은 해당 주 시가→종가, 직전봉 대비는 이전 주 종가→현재 종가입니다.':'봉 등락률은 시가→종가, 직전봉 대비는 직전 저장봉 종가→현재 종가입니다. 빈 분은 임의로 채우지 않습니다.';}
async function switchFrame(next){if(next===frame)return;const previous=code;frame=next;requestVersion++;clearChart();updateFrameControls();if(previous)await selectStock(previous)}
$('chart-frame').onchange=()=>switchFrame($('chart-frame').value);updateFrameControls();
$('chart-source').onchange=async()=>{liveQuotes={};liveChart=$('chart-source').value==='live';quoteList=liveChart;const previous=code;requestVersion++;clearChart();if(previous)await selectStock(previous)};
async function refreshLiveChart(){if(!liveChart||loading||!code||document.hidden||drag)return;const keepTime=record&&selected<record.bars.length-1?record.bars[selected]?.ts:null;await selectStock(code,keepTime,true)}
window.addEventListener('DOMContentLoaded',()=>{new ResizeObserver(draw).observe($('chart').parentElement);refresh();setInterval(refresh,5000);setInterval(()=>{refreshLiveChart();refreshQuotes()},15000)});

let heroLinkVersion=0,heroLinkQueue=Promise.resolve(),heroLinkTimer;
function linkHero(symbol){
  const version=++heroLinkVersion;clearTimeout(heroLinkTimer);
  heroLinkTimer=setTimeout(()=>{
    heroLinkQueue=heroLinkQueue.then(async()=>{
      if(version!==heroLinkVersion)return;
      const chart=$('hero-target').value;
      if(chart==='off')return;
      try{
        const data=await window.collectorHeroSend(symbol,chart,status.token,()=>version===heroLinkVersion);
        if(!data)return;if(data.ok){toast(data.message);return}
        throw Error(data.message||'영웅문 연동 실패');
      }catch(e){if(version===heroLinkVersion)toast('영웅문 연동: '+e.message)}
    });
  },100);
}

async function loadHeroTargets(){try{const r=await api("/api/hero-targets"),previous=$("hero-target").value||localStorage.getItem("collector-hero-chart")||r.preferred||"";$("hero-target").replaceChildren(new Option("영웅문 0600 · 자동 선택",""),new Option("영웅문 연동 끄기","off"),...r.targets.map(t=>new Option(t.label,t.handle)));$("hero-target").value=previous==="off"||r.targets.some(t=>t.handle===previous)?previous:r.targets.some(t=>t.handle===r.preferred)?r.preferred:"";localStorage.setItem("collector-hero-chart",$("hero-target").value)}catch(e){}}
$("hero-target").onchange=()=>localStorage.setItem("collector-hero-chart",$("hero-target").value);
window.addEventListener("DOMContentLoaded",()=>{loadHeroTargets();setInterval(loadHeroTargets,30000)});

function renderVolumeSummary(){
 const box=$('volume-summary'),s=(meta.tracked||[]).find(s=>s.code===code);
 if(!s){box.replaceChildren(element('span','종목을 선택하면 첫 편입 이후 흐름을 보여드립니다.'));return}
 const current=liveQuotes[code]?.price||(record?.live?record.quote?.price:null)||s.price;
 const bars=record?.day===meta.day&&frame==='minute'?record.bars.filter(b=>b.ts>s.first_seen.slice(0,16).replace('T',' ')+':59'&&b.ts<status.now.slice(0,16).replace('T',' ')+':00'):[];
 const items=[['처음 순위 편입',s.first_seen.slice(11,19)+' · '+fmt(s.first_price)+'원'],['첫 편입 가격 대비',signedPercent(percent(current,s.first_price))],['거래량 급증률',signedPercent(s.volume_rate)],['편입 뒤 최고 / 최저',bars.length?fmt(Math.max(...bars.map(b=>b.high)))+' / '+fmt(Math.min(...bars.map(b=>b.low)))+'원':'저장 1분봉으로 확인']];
 box.replaceChildren(...items.map(([title,value])=>{const d=element('div');d.append(element('span',title),element('strong',value));return d}),element('p','첫 편입은 수집기가 처음 확인한 시각입니다. 급증 시작이나 매수 체결 시각을 뜻하지 않습니다. 최고·최저는 편입 다음 완성 분부터 조회된 1분봉 범위입니다.'));
}
