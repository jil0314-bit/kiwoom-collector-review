'use strict';
const $=id=>document.getElementById(id), fmt=n=>n==null?'—':Number(n).toLocaleString('ko-KR',{maximumFractionDigits:2});
let status={}, meta={stocks:[]}, record=null, choice='', code='', selected=-1, requestVersion=0, refreshing=false, openedFlag=false;
let frame='minute', loading=false, liveChart=true;
let liveQuotes={},quoteRequest=0,quotesBusy=false;
let listMode='ranking', watchlists=[], watchGroup='';
const periods=()=>['day','week'].includes(frame)?[5,10,20,30,60,120]:[5,10,20,60,120,240];
const maColors={5:'#d28a16',10:'#9a54d8',20:'#109e9b',30:'#ef6487',60:'#3778e6',120:'#e57927',240:'#546380'};
const barLabel=ts=>frame==='day'?ts:frame==='week'?ts+' 주':ts.slice(11,16);
const maUnit=()=>frame==='day'?'일':frame==='week'?'주':frame==='minute'?'분':'봉';
const frameLabel=()=>({minute:'1분봉',minute3:'3분봉',minute5:'5분봉',day:'일봉',week:'주봉'}[frame]);
const closeLabel=()=>frame==='day'?'종가 · 해당 일 마지막':frame==='week'?'종가 · 해당 주 마지막':frame==='minute'?'종가 · 해당 분 마지막':'종가 · 해당 구간 마지막';
let viewRange=null, zoomHistory=[], hover=null, drag=null, chartGeometry=null, drawFrame=null;
const percent=(value,base)=>Number.isFinite(value)&&Number.isFinite(base)&&base>0?(value/base-1)*100:null;
const signedPercent=n=>n==null?'—':(n>0?'+':'')+n.toFixed(2)+'%';
const changeClass=n=>n>0?'change-up':n<0?'change-down':'change-flat';
function barChanges(i){const b=record.bars[i];return {body:percent(b.close,b.open),previous:i>0?percent(b.close,record.bars[i-1].close):null}}
const toast=text=>{$('toast').textContent=text;$('toast').style.display='block';setTimeout(()=>$('toast').style.display='none',6500)};
async function api(path,options){if(path.startsWith('/api/chart?'))path+='&fast=1';const r=await fetch(path,options);const data=await r.json();if(!r.ok)throw Error(data.error||'요청 실패');return data}
function params(withRevision=false){const [day,kind]=choice.split('|');const q=new URLSearchParams({day,kind,code});q.set('frame',frame);q.set('source','volume');if(liveChart)q.set('live','1');if(withRevision)q.set('rev',meta.revision||meta.ranking_at||'');return q}
const activeGroup=()=>watchlists.find(g=>String(g.number)===watchGroup);
const currentEntries=()=>listMode==='watchlist'?(meta.tracked||[]):meta.stocks;
const currentStocks=()=>currentEntries().filter(s=>s.type!=='heading');
const displayedEntries=()=>{const query=$('search').value.trim().toLowerCase();return currentEntries().filter(s=>!query||s.type!=='heading'&&(s.name+s.code).toLowerCase().includes(query))};
async function loadWatchlists(){try{const result=await api('/api/watchlists');const previous=watchGroup;watchlists=result.groups;$('watch-group').replaceChildren(...watchlists.map(g=>new Option(String(g.number).padStart(2,'0')+' · '+g.name+' ('+g.entries.filter(e=>e.type==='stock').length+')',g.number)));watchGroup=watchlists.some(g=>String(g.number)===previous)?previous:String(watchlists[0]?.number||'');$('watch-group').value=watchGroup;if(listMode==='watchlist')renderStocks()}catch(e){if(listMode==='watchlist')$('stocks').replaceChildren(element('div',e.message,'empty'))}}
function element(tag,text,cls){const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e}
async function post(path,body={}){return api(path,{method:'POST',headers:{'Content-Type':'application/json','X-Collector-Token':status.token},body:JSON.stringify(body)})}
async function refresh(){if(refreshing)return;refreshing=true;try{status=await api('/api/volume/status');$('clock').textContent=status.now.slice(0,19).replace('T',' ')+' KST';$('auth').textContent=status.credentials?'인증정보 준비됨':'인증정보 필요';$('progress').textContent=status.state.message+(status.state.queued?' · 다음 갱신 예약됨':'');$('collect').disabled=false;$('collect').textContent=status.state.queued?'다음 갱신 예약됨':status.state.busy?'수집 후 다시 갱신 예약':'지금 최신 자료 저장';$('preview').disabled=false;$('preview').textContent=status.monitor.enabled?'장중 자동 갱신 중지':'장중 자동 갱신 시작';$('auto-info').textContent=status.monitor.enabled?'목록 1분 · 분봉 순차 저장 · 20:05 최종':'장중 자동 갱신 중지 · 20:05 최종';
if(!openedFlag){await post('/api/volume/open');openedFlag=true}

const old=$('archive').value;const catalog=status.catalog; $('archive').replaceChildren();for(const c of catalog){const value=c.day+'|'+c.kind;const o=new Option(c.day+(c.phase==='final'?' · 최종':c.day<status.now.slice(0,10)?' · 장중 저장 (최종 미수집)':' · 장중 최신')+(c.status==='partial'?' · 일부 실패':''),value);$('archive').add(o)}
if(!catalog.length){$('archive').add(new Option('오늘 · 첫 거래량 순위 조회 중',status.now.slice(0,10)+'|latest'));$('archive').value=$('archive').options[0].value;if(listMode==='ranking')return}else{const valid=catalog.some(c=>c.day+'|'+c.kind===old);$('archive').value=valid?old:$('archive').options[0].value}
const changed=choice!==$('archive').value;choice=$('archive').value;await loadDay(changed);
}catch(e){$('auth').textContent='수집기 연결 확인 필요';$('progress').textContent=e.message||'실행 파일로 수집기를 켜주세요.'}finally{refreshing=false}}
async function loadDay(changed=false){if(changed)liveQuotes={};const oldRevision=meta.revision||meta.ranking_at;meta=await api('/api/volume/day?'+params());loadNotes(choice.split('|')[0]);$('saved').replaceChildren(document.createTextNode(String(meta.stocks.filter(s=>s.status==='saved').length)+' '),element('small','/ '+meta.stocks.length+'종목'));$('ranktime').textContent=(meta.kind==='preview'?(meta.day<status.now.slice(0,10)?'장중 저장 · 최종 미수집 · ':'장중 최신 · '):'최종 · ')+(meta.ranking_at||'').slice(11,19)+' KST';renderStocks();if(changed)refreshQuotes();if(!loading&&(changed||!record||!liveChart&&listMode==='ranking'&&oldRevision!==(meta.revision||meta.ranking_at))){const keepTime=!changed&&record&&selected<record.bars.length-1?record.bars[selected]?.ts:null;const s=listMode==='watchlist'?currentStocks().find(s=>s.code===code)||currentStocks()[0]:meta.stocks.find(s=>(s.status==='saved'||liveChart)&&s.code===code)||meta.stocks.find(s=>s.status==='saved'||liveChart);if(s){if(changed)chooseCurrentStock(s.code);else await selectStock(s.code,keepTime)}else clearChart()}}
async function refreshQuotes(){
  if(quotesBusy)return;
  const symbols=currentStocks().map(s=>s.code);if(!symbols.length)return;
  quotesBusy=true;const key=symbols.join(','),version=++quoteRequest;
  const valid=()=>version===quoteRequest&&currentStocks().map(s=>s.code).join(',')===key;
  try{
    for(let offset=0;offset<symbols.length;offset+=10){
      if(!valid())return;
      const r=await api('/api/quotes?codes='+encodeURIComponent(symbols.slice(offset,offset+10).join(',')));
      if(!valid())return;
      Object.assign(liveQuotes,r.quotes);renderStocks();
    }
  }catch(e){if(valid())toast('현재가 목록 조회 실패: '+e.message)}
  finally{quotesBusy=false;if(currentStocks().map(s=>s.code).join(',')!==key)refreshQuotes()}
}
function chooseCurrentStock(symbol){liveChart=true;$('chart-source').value='live';selectStock(symbol);linkHero(symbol);renderStocks()}
function renderStocks(){
const listScroll=$('stocks').scrollTop;
const focused=document.activeElement?.closest('[data-stock-code]'),focusCode=focused?.dataset.stockCode,focusMemo=document.activeElement?.classList.contains('memo-mark');
$('stocks').replaceChildren();
for(const s of displayedEntries()){
if(s.type==='heading'){$('stocks').append(element('div',s.label||'구분','watch-heading'));continue}
const row=element('div',null,'stock-row');row.dataset.stockCode=s.code;
const b=element('button',null,'stock'+(s.code===code?' active':''));b.setAttribute('aria-pressed',String(s.code===code));b.append(element('span',listMode==='watchlist'?'·':String(s.rank).padStart(2,'0'),'rank'));
const name=element('span',s.name,'name');name.append(element('small',s.code+' · 시총 '+fmt(s.market_cap)+'억 · '+(s.status==='saved'?s.count+'봉':'분봉 저장 중')));b.append(name);const q=liveQuotes[s.code]||{price:s.price,rate:s.rate};name.append(element('small',fmt(q.price)+'원 · '+signedPercent(q.rate),changeClass(q.rate)));b.append(element('span',signedPercent(s.volume_rate),'rate change-up'));b.onclick=()=>chooseCurrentStock(s.code);
row.append(b,noteMark(s));$('stocks').append(row)
}
$('stocks').scrollTop=listScroll;decorateNotes();renderVolumeSummary();
if(focusCode){const row=$('stocks').querySelector(`[data-stock-code="${focusCode}"]`);row?.querySelector(focusMemo?'.memo-mark':'.stock')?.focus({preventScroll:true})}
}
function clearChart(){resetChartView();record=null;code='';selected=-1;$('selected-name').textContent='저장된 종목을 선택하세요';$('selected-code').textContent='MINUTE CHART';$('bars').replaceChildren();$('minute').replaceChildren();$('values').replaceChildren();$('bar-changes').replaceChildren();$('png').disabled=true;$('csv').classList.add('disabled');$('csv').removeAttribute('href');$('chart-empty').style.display='flex';draw()}
async function selectStock(next,keepTime=null,background=false){const s=currentStocks().find(x=>x.code===next);if(!s||!liveChart&&s.status!=='saved'&&['minute','minute3','minute5'].includes(frame)){toast(s?.error||'아직 저장되지 않은 종목입니다.');return}code=next;if(!background){$('png').disabled=true;$('csv').classList.add('disabled')}const version=++requestVersion,previousRecord=record;const path='/api/chart?'+params(true);loading=true;cancelDrag();clearHover();if(!background){record=null;$('chart-empty').textContent=frame==='day'?'일봉 이력을 불러오는 중입니다…':frame==='week'?'주봉 이력을 불러오는 중입니다…':'분봉을 불러오는 중입니다…';$('chart-empty').style.display='flex';$('values').replaceChildren();$('bar-changes').replaceChildren();$('bars').replaceChildren();$('minute').replaceChildren();$('ma-values').textContent='';draw()}try{const result=await api(path);if(version!==requestVersion)return;prepareChartRecord(result,previousRecord);record=result;selected=keepTime?record.bars.findIndex(b=>b.ts===keepTime):-1;if(selected<0)selected=record.bars.length-1;$('selected-name').textContent=s.name+(record.live&&record.quote?' · 현재가 '+fmt(record.quote.price)+'원 ('+signedPercent(record.quote.rate)+')':'');$('selected-code').textContent=s.code+' / '+record.day+(record.live_fallback?' / 저장 분봉 · 오늘 분봉 없음':record.live?' / 현재 차트 · 조회 '+record.fetched_at.slice(11,19)+' KST':listMode==='watchlist'?' / 거래량 급증 편입 자료':record.kind==='preview'?' / 장중 저장 자료':' / 최종 자료');$('chart-empty').style.display='none';$('png').disabled=false;$('csv').classList.remove('disabled');$('csv').href='/api/chart.csv?'+params(true);$('minute').replaceChildren(...record.bars.map((b,i)=>new Option(barLabel(b.ts),i)));$('coverage').textContent=(record.chart_notice||'')+(record.live||listMode==='watchlist'||frame==='day'||frame==='week'?'':` 수신 ${s.count}봉 · ${s.first.slice(11,16)}~${s.last.slice(11,16)} | 09시 전 ${s.pre}봉 · 09:00~15:30 ${s.regular}봉 · 15:30 이후 ${s.after}봉. 빈 시간은 비거래/미제공 여부 미확인.`);renderStocks();renderTable();selectMinute(selected);renderVolumeSummary();if(result.refreshing)setTimeout(()=>{if(version===requestVersion&&!document.hidden&&!drag)selectStock(next,record?.bars[selected]?.ts||null,true)},1000)}catch(e){if(version!==requestVersion)return;if(background&&previousRecord){record=previousRecord;$('coverage').textContent='현재 조회 실패 · 이전 자료 유지 · '+e.message;return}record=null;$('chart-empty').textContent=e.message;$('chart-empty').style.display='flex';$('png').disabled=true;$('csv').classList.add('disabled');toast(e.message);draw()}finally{if(version===requestVersion)loading=false}}
function renderTable(){const frag=document.createDocumentFragment();record.bars.forEach((b,i)=>{const tr=element('tr');tr.dataset.index=i;for(const k of ['ts','open','high','low','close'])tr.append(element('td',k==='ts'?barLabel(b.ts):fmt(b[k])));const rates=barChanges(i);for(const rate of [rates.body,rates.previous])tr.append(element('td',signedPercent(rate),changeClass(rate)));tr.append(element('td',fmt(b.volume)));tr.onclick=()=>selectMinute(i);frag.append(tr)});$('bars').replaceChildren(frag)}
function selectMinute(i){if(!record||!record.bars[i])return;clearHover();selected=i;const b=record.bars[i];$('minute').value=i;$('values').replaceChildren(...[['시가','open'],['고가 · 최고가','high'],['저가 · 최저가','low'],[closeLabel(),'close'],['거래량 (주)','volume']].map(([label,k])=>{const d=element('div');d.append(element('span',label),element('strong',fmt(b[k])));return d}));const rates=barChanges(i);$('bar-changes').replaceChildren(...[['봉 등락률 · 시가 대비',rates.body],['직전 저장봉 종가 대비',rates.previous]].map(([label,rate])=>{const d=element('div');d.append(element('span',label),element('strong',signedPercent(rate),changeClass(rate)));return d}));$('ma-values').replaceChildren(element('span',b.ts+' KST'+(b.end_ts?(frame==='week'?' ~ '+b.end_ts+' 마지막 거래일':' ~ '+b.end_ts.slice(11,16)+' 직전 · 원본 '+b.source_count+'/'+record.interval_minutes+'개 분봉'):''),'ma-timestamp'),...periods().map(n=>element('span',n+maUnit()+'선 '+fmt(b['ma'+n])+(b['ma'+n]==null?' (이력 부족)':'원'),'ma-value ma'+n)));if(record.kind==='preview')$('ma-values').append(element('span',frame==='week'?'이번 주 봉은 진행 중일 수 있습니다.':'장중 마지막 봉은 진행 중일 수 있습니다.','ma-timestamp'));for(const tr of $('bars').rows)tr.classList.toggle('chosen',Number(tr.dataset.index)===i);draw()}
function visible(){if(!record)return[];if(viewRange)return record.bars.filter(b=>b.ts>=viewRange.start&&b.ts<=viewRange.end);const n=$('range').value;return n==='all'?record.bars:record.bars.slice(-Number(n))}
function draw(){const canvas=$('chart'),dpr=window.devicePixelRatio||1,w=canvas.clientWidth||800,h=400;canvas.width=Math.round(w*dpr);canvas.height=h*dpr;const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);chartGeometry=null;paint(ctx,w,h);updateZoomControls();positionTooltip()}
function paint(ctx,w,h){ctx.fillStyle='#ffffff';ctx.fillRect(0,0,w,h);const bars=visible();if(!bars.length)return;const left=12,right=76,top=20,bottom=52,volH=66,priceH=h-top-bottom-volH-25;const width=w-left-right;const values=bars.flatMap(b=>[b.low,b.high,...periods().map(n=>b['ma'+n])].filter(v=>v!=null));let lo=Math.min(...values),hi=Math.max(...values),pad=(hi-lo)*.08||hi*.005;lo-=pad;hi+=pad;const y=p=>top+(hi-p)/(hi-lo)*priceH,step=width/(bars.length+3),x=i=>left+(i+.5)*step;
ctx.font='10px Segoe UI';ctx.textAlign='left';for(let i=0;i<=4;i++){const p=lo+(hi-lo)*i/4,yy=y(p);ctx.strokeStyle='#cbd5e1';ctx.beginPath();ctx.moveTo(left,yy);ctx.lineTo(w-right,yy);ctx.stroke();ctx.fillStyle='#334155';ctx.fillText(fmt(p),w-right+9,yy+3)}
const vmax=Math.max(1,...bars.map(b=>b.volume)),volBase=h-bottom;bars.forEach((b,i)=>{const color=b.close>=b.open?'#e60012':'#0057e7';ctx.strokeStyle=color;ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(x(i),y(b.high));ctx.lineTo(x(i),y(b.low));ctx.stroke();ctx.fillRect(x(i)-Math.max(.7,step*.32),Math.min(y(b.open),y(b.close)),Math.max(1.4,step*.64),Math.max(1,Math.abs(y(b.close)-y(b.open))));ctx.globalAlpha=1;ctx.fillRect(x(i)-Math.max(.7,step*.32),volBase-b.volume/vmax*volH,Math.max(1.4,step*.64),b.volume/vmax*volH);ctx.globalAlpha=1});
for(const n of periods()){const key='ma'+n;ctx.strokeStyle=maColors[n];ctx.lineWidth=[20,60].includes(n)?3.6:1.2;ctx.beginPath();let active=false;bars.forEach((b,i)=>{if(b[key]==null){active=false;return}if(active)ctx.lineTo(x(i),y(b[key]));else{ctx.moveTo(x(i),y(b[key]));active=true}});ctx.stroke()}ctx.lineWidth=1;
const count=Math.min(7,bars.length,Math.max(2,Math.floor(width/(frame==='day'?92:55))));for(let j=0;j<count;j++){const i=Math.round(j*(bars.length-1)/Math.max(1,count-1));ctx.fillStyle='#334155';ctx.textAlign='center';const label=barLabel(bars[i].ts),half=ctx.measureText(label).width/2;ctx.fillText(label,Math.max(left+half,Math.min(x(i),w-right-half)),h-28)}ctx.textAlign='left';ctx.fillStyle='#334155';ctx.fillText('거래량',left,volBase-volH-7);ctx.fillText(frame==='day'?'거래일 순서 · KST':'거래가 있는 분봉 순서 · KST',left,h-9);
chartGeometry={left,right:w-right,top,bottom:volBase,priceBottom:top+priceH,dataRight:left+bars.length*step,lo,hi,w,h,bars,step};
if(drag){const a=bars.indexOf(record.bars[Math.min(drag.start,drag.end)]),b=bars.indexOf(record.bars[Math.max(drag.start,drag.end)]);if(a>=0&&b>=0){ctx.fillStyle='#785bdd26';ctx.fillRect(left+a*step,top,(b-a+1)*step,volBase-top);ctx.strokeStyle='#785bdd';ctx.strokeRect(left+a*step,top,(b-a+1)*step,volBase-top);ctx.font='12px Malgun Gothic';ctx.fillStyle='#6243bd';ctx.fillText(`${barLabel(bars[a].ts)} ~ ${barLabel(bars[b].ts)} · ${b-a+1}봉`,Math.min(left+a*step+6,Math.max(left,w-right-205)),top+17)}}
const chosen=record.bars[hover?hover.index:selected],i=bars.indexOf(chosen);if(i>=0){const xx=x(i)+(!hover&&i===bars.length-1?step:0);ctx.strokeStyle='#6b5a9d';ctx.setLineDash([4,3]);ctx.beginPath();ctx.moveTo(xx,top);ctx.lineTo(xx,volBase);if(hover){ctx.moveTo(left,hover.y);ctx.lineTo(w-right,hover.y)}ctx.stroke();ctx.setLineDash([]);if(hover){ctx.font='12px Malgun Gothic';const time=barLabel(chosen.ts),tw=ctx.measureText(time).width+16,tx=Math.max(left,Math.min(xx-tw/2,w-right-tw));ctx.fillStyle='#342951';ctx.fillRect(tx,volBase+9,tw,22);ctx.fillStyle='#fff';ctx.fillText(time,tx+8,volBase+24);if(hover.y<=top+priceH){const price=hi-(hover.y-top)/priceH*(hi-lo);ctx.fillStyle='#342951';ctx.fillRect(w-right+2,hover.y-11,right-3,22);ctx.fillStyle='#fff';ctx.font='11px Segoe UI';ctx.fillText(fmt(price),w-right+6,hover.y+4)}}}}
function clearHover(){hover=null;$('chart-hover').hidden=true}
function cancelDrag(){const d=drag;drag=null;if(d&&$('chart').hasPointerCapture(d.pointerId))$('chart').releasePointerCapture(d.pointerId)}
function resetChartView(){cancelDrag();clearHover();viewRange=null;zoomHistory=[];if($('range').value==='custom')$('range').value='all'}
function prepareChartRecord(next,previous=record){if(!previous||previous.frame!==next.frame||previous.day!==next.day||previous.stock.code!==next.stock.code)resetChartView();else{cancelDrag();clearHover()}}
function updateZoomControls(){const bars=visible();$('zoom-back').disabled=!zoomHistory.length;$('zoom-reset').disabled=!record||(!viewRange&&$('range').value==='all');$('zoom-status').textContent=bars.length?`표시 ${barLabel(bars[0].ts)} ~ ${barLabel(bars[bars.length-1].ts)} · ${bars.length}봉`:''}
function viewport(){return {range:viewRange?{...viewRange}:null,preset:$('range').value}}
function zoomTo(start,end){if(!record)return;const a=Math.min(start,end),b=Math.max(start,end);if(b-a<2)return;zoomHistory.push(viewport());viewRange={start:record.bars[a].ts,end:record.bars[b].ts};$('range').value='custom';clearHover();draw()}
function zoomBack(){const previous=zoomHistory.pop();if(!previous)return;cancelDrag();clearHover();viewRange=previous.range;$('range').value=previous.preset;draw()}
function zoomReset(){resetChartView();$('range').value='all';draw()}
function queueDraw(){if(drawFrame!==null)return;drawFrame=requestAnimationFrame(()=>{drawFrame=null;draw()})}
function chartPoint(event,clamp=false){const g=chartGeometry;if(!g)return null;const r=$('chart').getBoundingClientRect(),rawX=(event.clientX-r.left)*g.w/r.width,rawY=(event.clientY-r.top)*g.h/r.height;if(!clamp&&(rawX<g.left||rawX>g.dataRight||rawY<g.top||rawY>g.bottom))return null;const x=Math.max(g.left,Math.min(rawX,g.right)),y=Math.max(g.top,Math.min(rawY,g.bottom)),i=Math.min(g.bars.length-1,Math.floor((x-g.left)/g.step));return {index:record.bars.indexOf(g.bars[i]),x,y}}
function positionTooltip(){const box=$('chart-hover'),g=chartGeometry;if(!hover||drag||!g){box.hidden=true;return}const b=record.bars[hover.index];if(!b||!g.bars.includes(b)){box.hidden=true;return}const rates=barChanges(hover.index),grid=element('div',null,'hover-grid');for(const [label,value,cls] of [['시가',fmt(b.open)],['고가',fmt(b.high)],['저가',fmt(b.low)],['종가',fmt(b.close)],['봉 등락률',signedPercent(rates.body),changeClass(rates.body)],['직전봉 대비',signedPercent(rates.previous),changeClass(rates.previous)]]){const cell=element('div');cell.append(element('span',label),element('strong',value,cls));grid.append(cell)}box.replaceChildren(element('strong',b.ts.slice(0,16)+' KST','hover-time'),grid,element('div','거래량 '+fmt(b.volume)+'주','hover-volume'));box.hidden=false;const x=g.left+(g.bars.indexOf(b)+.5)*g.step,bw=box.offsetWidth,bh=box.offsetHeight;box.style.left=Math.max(4,Math.min(x+16+bw>g.w?x-bw-16:x+16,g.w-bw-4))+'px';box.style.top=Math.max(4,Math.min(hover.y+16+bh>g.h?hover.y-bh-16:hover.y+16,g.h-bh-4))+'px'}
$('chart').addEventListener('pointermove',event=>{const p=chartPoint(event,!!drag);if(!p){clearHover();queueDraw();return}hover=p;if(drag&&drag.pointerId===event.pointerId)drag.end=p.index;queueDraw()});
$('chart').addEventListener('pointerleave',()=>{if(!drag){clearHover();queueDraw()}});
$('chart').addEventListener('pointerdown',event=>{if(event.button!==0)return;const p=chartPoint(event);if(!p)return;drag={start:p.index,end:p.index,startX:p.x,pointerId:event.pointerId};hover=p;$('chart').setPointerCapture(event.pointerId);event.preventDefault();queueDraw()});
$('chart').addEventListener('pointerup',event=>{if(!drag||drag.pointerId!==event.pointerId)return;const p=chartPoint(event,true),d=drag;cancelDrag();if(!p){clearHover();draw();return}if(Math.abs(p.x-d.startX)>=6&&Math.abs(p.index-d.start)>=2)zoomTo(d.start,p.index);else if(Math.abs(p.x-d.startX)<6)selectMinute(p.index);else{clearHover();draw()}});
$('chart').addEventListener('pointercancel',()=>{cancelDrag();clearHover();draw()});
$('chart').addEventListener('lostpointercapture',()=>{if(drag){drag=null;clearHover();draw()}});
$('chart').addEventListener('dblclick',zoomReset);
$('zoom-back').onclick=zoomBack;$('zoom-reset').onclick=zoomReset;
$('minute').onchange=()=>selectMinute(Number($('minute').value));$('range').onchange=()=>{cancelDrag();clearHover();viewRange=null;zoomHistory=[];draw()};$('search').oninput=renderStocks;$('archive').onchange=async()=>{choice=$('archive').value;requestVersion++;clearChart();await loadDay(true)};
$('list-mode').onchange=async()=>{listMode=$('list-mode').value;$('watch-group').hidden=true;$('list-badge').textContent=listMode==='watchlist'?'전체 편입':'급증 TOP 100';$('list-heading').textContent=listMode==='watchlist'?'오늘 편입 종목':'순위 / 종목';$('list-trailing').textContent='거래량 급증률';$('search').value='';requestVersion++;clearChart();renderStocks();const s=listMode==='watchlist'?currentStocks()[0]:meta.stocks.find(s=>s.status==='saved'||liveChart);if(s)chooseCurrentStock(s.code)};
$('watch-group').onchange=async()=>{watchGroup=$('watch-group').value;requestVersion++;clearChart();renderStocks();const s=currentStocks()[0];if(s)chooseCurrentStock(s.code)};
async function collect(){try{const r=await post('/api/volume/collect',{day:status.now.slice(0,10)});toast(r.state==='queued'?'현재 수집이 끝나면 최신 자료로 다시 갱신합니다.':r.state==='waiting'?'평일 08:00부터 수집합니다.':'순위는 최신으로 갱신하고, 오늘 편입 이력과 분봉은 보관합니다.');await refresh()}catch(e){toast(e.message)}}
$('preview').onclick=async()=>{try{const enabled=!status.monitor.enabled;await post('/api/volume/monitor',{enabled});toast(enabled?'목록 1분 간격 자동 갱신을 시작합니다.':'장중 자동 갱신 중지. 진행 중 수집은 완료하며 20:05 최종 수집은 유지합니다.');await refresh()}catch(e){toast(e.message)}};$('collect').onclick=collect;$('png').onclick=()=>{if(!record)return;const q=params(true);q.set('minute',record.bars[selected].ts);window.location.href='/api/chart.png?'+q};
function updateFrameControls(){for(const mode of ['minute','minute3','minute5','day','week']){$('frame-'+mode).classList.toggle('active',frame===mode);$('frame-'+mode).setAttribute('aria-pressed',String(frame===mode))}$('legend').replaceChildren(...periods().map(n=>element('span',n+maUnit()+'선','ma-key ma'+n+([20,60].includes(n)?' thick':''))),element('span','종가 단순평균 · 20·60선 3배 굵기','legend-note'));$('detail-title').textContent=frame==='day'?'선택한 거래일':frame==='week'?'선택한 주':'선택한 '+frameLabel();$('time-heading').textContent=frame==='day'?'날짜 (KST)':frame==='week'?'주 시작일 (KST)':'시각 (KST)';$('close-heading').textContent=closeLabel().replace(' · ',' (')+')';$('csv').textContent=frameLabel()+' CSV';$('minute').setAttribute('aria-label',frame==='day'?'거래일 선택':frame==='week'?'주 선택':'분 선택');$('chart').setAttribute('aria-label',frameLabel()+' 캔들 차트');$('change-help').textContent=frame==='day'?'봉 등락률은 시가→종가, 직전봉 대비는 이전 거래일 종가→현재 종가입니다.':frame==='week'?'봉 등락률은 해당 주 시가→종가, 직전봉 대비는 이전 주 종가→현재 종가입니다.':'봉 등락률은 시가→종가, 직전봉 대비는 직전 저장봉 종가→현재 종가입니다. 빈 분은 임의로 채우지 않습니다.';}
async function switchFrame(next){if(next===frame)return;const previous=code;frame=next;requestVersion++;clearChart();updateFrameControls();if(previous)await selectStock(previous)}
for(const mode of ['minute','minute3','minute5','day','week'])$('frame-'+mode).onclick=()=>switchFrame(mode);updateFrameControls();
$('chart-source').onchange=async()=>{liveChart=$('chart-source').value==='live';const previous=code;requestVersion++;clearChart();if(previous)await selectStock(previous)};
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
        for(let attempt=0;attempt<2;attempt++){
          if(version!==heroLinkVersion)return;
          const send=async()=>fetch('/api/hero-link',{method:'POST',headers:{'Content-Type':'application/json','X-Collector-Token':status.token},body:JSON.stringify({code:symbol,chart})});
          let r=await send();if(r.status===403){status=await api('/api/volume/status');r=await send()}
          const data=await r.json();if(version!==heroLinkVersion)return;
          if(!r.ok)throw Error(data.error||'영웅문 연동 실패');
          if(data.ok){toast(data.message);return}
          if(attempt===0&&/입력칸|응답 실패|입력 확인|Enter 전달/.test(data.message||'')){
            await new Promise(resolve=>setTimeout(resolve,180));continue;
          }
          throw Error(data.message||'영웅문 연동 실패');
        }
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
