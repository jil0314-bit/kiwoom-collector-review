'use strict';
const $ = id => document.getElementById(id);
let token = '', enabled = true, shared = false, record = null, loading = false;
let flowPick = null, flowChart = null, flowVersion = 0, flowAbort = null, flowContext = '', flowHover = -1;
let flowHeroVersion = 0, flowHeroQueue = Promise.resolve(), flowHeroTimer;
const flowColors = {5:'#d28a16',10:'#9a54d8',20:'#109e9b',30:'#ef6487',60:'#3778e6',120:'#e57927',240:'#546380'};
function flowRows(key) {
  const query = $('search').value.trim().toLowerCase(), period = record?.kind === 'period';
  return (record?.markets?.[$('market').value]?.rankings[key] || [])
    .filter(r => r.rank <= (period ? 30 : 20) && (r.code+' '+r.name).toLowerCase().includes(query))
    .sort((a,b) => a.rank-b.rank);
}
function flowItems() {return ['foreign','institution'].flatMap(key => flowRows(key).map(row => ({key,...row})));}
function resetFlow() {
  flowPick = null; flowChart = null; flowHover = -1; ++flowVersion; ++flowHeroVersion;
  clearTimeout(flowHeroTimer); flowAbort?.abort();
  $('flow-chart-name').textContent = '목록에서 종목을 선택하세요'; $('flow-chart-code').textContent = '종목 선택';
  $('flow-chart-status').textContent = ''; $('flow-hero-status').textContent = ''; paintFlow();
}
async function api(path, body) {
  const options = body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Collector-Token':token}, body:JSON.stringify(body)};
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '자료 조회 실패');
  return result;
}
function render() {
  const focused = document.activeElement?.closest('tr[data-code]');
  const focusCode = focused?.dataset.code, focusKey = focused?.dataset.investor;
  const query = $('search').value.trim().toLowerCase();
  for (const key of ['foreign','institution']) {
    const body = $(key); body.replaceChildren();
    const period = record?.kind === 'period';
    const rows = (record?.markets?.[$('market').value]?.rankings[key] || []).filter(r => r.rank <= (period ? 30 : 20))
      .sort((a,b) => a.rank-b.rank);
    $(key+'-count').textContent = rows.length ? `${$('market').selectedOptions[0].textContent} · ${rows.length}종목` : '';
    for (const row of rows.filter(r => (r.code+' '+r.name).toLowerCase().includes(query))) {
      const tr = document.createElement('tr');
      tr.dataset.code = row.code; tr.dataset.investor = key; tr.tabIndex = 0;
      tr.setAttribute('aria-label', `${key === 'foreign' ? '외국인' : '기관'} ${row.rank}위 ${row.name} ${row.code}`);
      tr.classList.toggle('selected', flowPick?.code === row.code && flowPick?.key === key);
      tr.setAttribute('aria-selected', String(flowPick?.code === row.code && flowPick?.key === key));
      tr.addEventListener('click', () => chooseFlow({key,...row}, true));
      tr.addEventListener('keydown', e => {if (e.key === 'Enter' || e.key === ' ') {e.preventDefault();chooseFlow({key,...row}, true);}});
      for (const value of [row.rank, row.name, row.net_amount_10m_krw, row.net_quantity_1000_shares]) {
        const td = document.createElement('td');
        td.textContent = value === null || value === undefined ? 'UNKNOWN' : typeof value === 'number' ? value.toLocaleString('ko-KR') : value;
        tr.append(td);
      }
      const code = document.createElement('small'); code.textContent = row.code; tr.children[1].append(code);
      for (const cell of [tr.children[2],tr.children[3]]) {
        const n = Number(cell.textContent.replaceAll(',',''));
        if (Number.isFinite(n)) cell.className = n < 0 ? 'negative' : n > 0 ? 'positive' : '';
      }
      body.append(tr);
    }
    if (!body.children.length) {
      const tr = document.createElement('tr'), td = document.createElement('td'); td.colSpan = 4;
      td.textContent = rows.length ? '검색 결과 없음' : '저장 자료 없음 · 당일 수집 성공 후 표시됩니다.'; tr.append(td); body.append(tr);
    }
  }
  if (focusCode) document.querySelector(`tr[data-code="${focusCode}"][data-investor="${focusKey}"]`)?.focus({preventScroll:true});
  const items = flowItems();
  if (flowPick && !items.some(s => s.code === flowPick.code && s.key === flowPick.key)) resetFlow();
  if (!flowPick && items.length) chooseFlow(items[0], false);
}
async function loadDay() {
  const day = $('day').value;
  if (flowContext !== day) {flowContext = day;resetFlow();}
  const period = day.startsWith('period:');
  const [start,end] = period ? day.slice(7).split('_') : [];
  const params = period ? 'start='+encodeURIComponent(start)+'&end='+encodeURIComponent(end) : 'day='+encodeURIComponent(day);
  const received = day ? await api('/api/investors/'+(period ? 'period' : 'day')+'?'+params) : null;
  if (day !== $('day').value) return;
  record = received;
  $('download').hidden = !record;
  if (record) {
    $('download').href = '/api/investors/'+(period ? 'period-csv' : 'csv')+'?'+params;
    $('basis').textContent = period
      ? `기간 합산 ${start}~${end} · 각 TOP 30 · 순매수금액 기준 · ${record.coverage?.note || '조회 범위 UNKNOWN'} · 기간 수량 UNKNOWN`
      : `조회일 ${record.day} · 1위 → 20위 · 수신 ${record.fetched_at.replace('T',' ')} · ${record.collection_mode === 'historical_backfill' ? '과거일 조회' : record.after_close_refresh ? '20:05 이후 재조회' : '장중 자료'} · 원본 기준일 UNKNOWN (API 미제공)`;
  }
  render();
}
async function poll() {
  if (loading) return;
  loading = true;
  try {
    const status = await api('/api/investors/status');
    token = status.token; enabled = status.enabled; shared = Boolean(status.shared_viewer);
    $('monitor').textContent = enabled ? '자동 수집 중지' : '자동 수집 시작';
    $('collect').disabled = shared || status.state.busy; $('monitor').disabled = shared;
    $('progress').textContent = shared ? '동기화 저장 자료 조회 · 새 수집은 원본 PC에서 합니다.' : `${enabled ? '자동 수집 켜짐' : '자동 수집 꺼짐'} · ${status.state.message}` + (status.last_error ? '\n최근 실패: '+status.last_error.message : '');
    const old = $('day').value;
    const opts = status.days.map(day => {const o = document.createElement('option');o.value = day;o.textContent = day;return o;});
    for (const period of status.periods || []) {
      const o = document.createElement('option'); o.value='period:'+period.start+'_'+period.end;
      o.textContent=`기간 합산 ${period.start}~${period.end} · TOP 30`; opts.push(o);
    }
    if (!opts.length) {const o=document.createElement('option');o.value='';o.textContent='저장 자료 없음';opts.push(o);}
    $('day').replaceChildren(...opts);
    if (opts.some(o => o.value === old)) $('day').value = old;
    await loadDay();
  } catch (error) { $('progress').textContent = error.message; }
  finally {loading = false;}
}
async function action(path, body) {
  try {
    const result = await api(path, body);
    await poll();
    const messages = {waiting:'평일 09:10 이후 수집합니다.',collector_busy:'상승률 수집 중입니다. 자동 수집이 켜져 있으면 완료 후 다시 시도합니다.',running:'이미 외국인·기관 수집 중입니다.'};
    if (messages[result.state]) $('progress').textContent = messages[result.state];
  } catch (error) {$('progress').textContent = error.message;}
}
$('day').addEventListener('change', () => loadDay().catch(e => {$('progress').textContent=e.message;}));
$('search').addEventListener('input', render);
$('market').addEventListener('change', () => {resetFlow();render();});
$('collect').addEventListener('click', () => action('/api/investors/collect', {}));
$('monitor').addEventListener('click', () => action('/api/investors/monitor', {enabled:!enabled}));
poll(); setInterval(poll, 10000);

function chooseFlow(stock, send) {
  flowPick = stock; flowHover = -1;
  $('flow-chart-name').textContent = stock.name; $('flow-chart-code').textContent = stock.code+' · '+$('market').selectedOptions[0].textContent;
  render(); loadFlowChart();
  if (send) {
    linkFlowHero(stock.code);
    const row = document.querySelector(`tr[data-code="${stock.code}"][data-investor="${stock.key}"]`);
    row?.focus({preventScroll:true}); row?.scrollIntoView({block:'nearest'});
  }
}
function stepFlow(direction) {
  const items = flowItems(); if (!items.length) return;
  const at = items.findIndex(s => s.code === flowPick?.code && s.key === flowPick?.key);
  const next = items[at < 0 ? (direction > 0 ? 0 : items.length-1) : Math.max(0,Math.min(items.length-1,at+direction))];
  if (next && (next.code !== flowPick?.code || next.key !== flowPick?.key)) chooseFlow(next, true);
}
async function loadFlowChart(background=false) {
  if (!flowPick || !record) return;
  const version = ++flowVersion, stock = flowPick;
  flowAbort?.abort(); flowAbort = new AbortController();
  const q = new URLSearchParams({day:record.period_end || record.day,code:stock.code,source:'investor',market:$('market').value,
    frame:$('flow-frame').value,live:$('flow-chart-source').value === 'live' && !shared ? '1' : '0',fast:'1',async:'1'});
  if (record.kind === 'period') {q.set('start',record.period_start);q.set('end',record.period_end);}
  if (!background) {flowChart=null;paintFlow();$('flow-chart-status').textContent='차트 조회 중…';}
  try {
    for (let attempt=0;attempt<180;attempt++) {
      const response = await fetch('/api/chart?'+q,{signal:flowAbort.signal}), data = await response.json();
      if (version !== flowVersion) return;
      if (!response.ok) throw new Error(data.error || '차트 조회 실패');
      if (data.pending) {await new Promise(resolve => setTimeout(resolve,500));if (version!==flowVersion)return;continue;}
      flowChart=data; flowHover=-1; paintFlow();
      $('flow-chart-status').textContent=(data.live?'현재 차트':'선택 날짜·기간 종료일 차트')+' · 마지막 봉 '+(data.bars.at(-1)?.ts || 'UNKNOWN')+' · '+(data.chart_notice || '실제 수신된 봉만 표시합니다.');
      if (data.refreshing) setTimeout(()=>{if(version===flowVersion&&!document.hidden)loadFlowChart(true);},1200);
      return;
    }
    throw new Error('차트 조회 대기 시간이 길어졌습니다. 종목을 다시 선택하세요.');
  } catch(error) {
    if (version !== flowVersion || error.name === 'AbortError') return;
    if (!background) flowChart=null;
    $('flow-chart-status').textContent=(background?'현재 조회 실패 · 이전 차트 유지 · ':'')+error.message;paintFlow();
  }
}
async function loadFlowTargets() {
  try {
    const result = await api('/api/hero-targets'), select=$('hero-target');
    const previous=select.value || localStorage.getItem('collector-hero-chart') || result.preferred || '';
    select.replaceChildren(new Option('0600 자동 선택',''),new Option('연동 끄기','off'),...result.targets.map(t=>new Option(t.label,t.handle)));
    select.value=previous==='off'||result.targets.some(t=>t.handle===previous)?previous:result.preferred || '';
  } catch(error) {$('flow-hero-status').textContent='영웅문 대상 확인: '+error.message;}
}
function linkFlowHero(symbol) {
  const version=++flowHeroVersion;clearTimeout(flowHeroTimer);
  flowHeroTimer=setTimeout(()=>{flowHeroQueue=flowHeroQueue.then(async()=>{
    if(version!==flowHeroVersion)return;
    const chart=$('hero-target').value;
    if(chart==='off'){$('flow-hero-status').textContent='영웅문 연동 꺼짐';return;}
    try {
      let response=await fetch('/api/hero-link',{method:'POST',headers:{'Content-Type':'application/json','X-Collector-Token':token},body:JSON.stringify({code:symbol,chart})});
      if(response.status===403) {
        token=(await api('/api/investors/status')).token;if(version!==flowHeroVersion)return;
        response=await fetch('/api/hero-link',{method:'POST',headers:{'Content-Type':'application/json','X-Collector-Token':token},body:JSON.stringify({code:symbol,chart})});
      }
      const result=await response.json();if(version!==flowHeroVersion)return;
      if(!response.ok)throw new Error(result.error || '영웅문 전송 실패');
      $('flow-hero-status').textContent=result.message;
    } catch(error) {if(version===flowHeroVersion)$('flow-hero-status').textContent=error.message;}
  });},80);
}
function paintFlow() {
  const canvas=$('flow-chart'), ctx=canvas.getContext('2d'), w=canvas.clientWidth || 600,h=380,dpr=devicePixelRatio || 1;
  canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);
  const all=flowChart?.bars || [], limit=$('flow-range').value, bars=limit==='all'?all:all.slice(-Number(limit));
  $('flow-legend').replaceChildren();
  if (!bars.length) {ctx.fillStyle='#777';ctx.font='14px sans-serif';ctx.fillText(flowPick?'차트 자료를 확인하고 있습니다.':'목록에서 종목을 선택하세요.',20,50);$('flow-chart-detail').textContent='실제 수신된 봉만 표시합니다.';return;}
  const ma=Object.keys(flowColors).map(Number).filter(n=>bars.some(b=>Number.isFinite(b['ma'+n])));
  for (const n of ma) {const el=document.createElement('span');el.textContent=n+'선';el.style.color=flowColors[n];$('flow-legend').append(el);}
  const left=12,right=w-78,top=20,bottom=270,volTop=292,volBottom=345,step=(right-left)/bars.length;
  const values=bars.flatMap(b=>[b.low,b.high,...ma.map(n=>b['ma'+n]).filter(Number.isFinite)]);
  let lo=Math.min(...values), hi=Math.max(...values);const pad=(hi-lo)*.06 || Math.max(1,hi*.01);lo-=pad;hi+=pad;
  const y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top),x=i=>left+(i+.5)*step;
  ctx.font='11px sans-serif';ctx.textAlign='left';
  for(let i=0;i<=4;i++){const value=lo+(hi-lo)*i/4,py=y(value);ctx.strokeStyle='#eceaf3';ctx.beginPath();ctx.moveTo(left,py);ctx.lineTo(right,py);ctx.stroke();ctx.fillStyle='#697386';ctx.fillText(Math.round(value).toLocaleString('ko-KR'),right+7,py+4);}
  const maxVolume=Math.max(1,...bars.map(b=>b.volume));
  bars.forEach((b,i)=>{const px=x(i),color=b.close>=b.open?'#d94b64':'#3778e6';ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(px,y(b.high));ctx.lineTo(px,y(b.low));ctx.stroke();const bw=Math.max(1,Math.min(10,step*.65));ctx.fillRect(px-bw/2,Math.min(y(b.open),y(b.close)),bw,Math.max(1,Math.abs(y(b.open)-y(b.close))));ctx.globalAlpha=.5;ctx.fillRect(px-bw/2,volBottom-b.volume/maxVolume*(volBottom-volTop),bw,b.volume/maxVolume*(volBottom-volTop));ctx.globalAlpha=1;});
  for(const n of ma){ctx.beginPath();ctx.strokeStyle=flowColors[n];ctx.lineWidth=[20,60].includes(n)?3:1;let connected=false;bars.forEach((b,i)=>{if(!Number.isFinite(b['ma'+n])){connected=false;return;}if(connected)ctx.lineTo(x(i),y(b['ma'+n]));else ctx.moveTo(x(i),y(b['ma'+n]));connected=true;});ctx.stroke();}
  ctx.fillStyle='#697386';ctx.textAlign='left';ctx.fillText(bars[0].ts.slice(0,16),left,370);ctx.textAlign='right';ctx.fillText(bars.at(-1).ts.slice(0,16),right,370);
  const index=flowHover>=0?Math.min(flowHover,bars.length-1):bars.length-1,b=bars[index];
  if(flowHover>=0){ctx.strokeStyle='#8892a6';ctx.lineWidth=1;ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(x(index),top);ctx.lineTo(x(index),volBottom);ctx.stroke();ctx.setLineDash([]);}
  $('flow-chart-detail').textContent=b.ts+' · 시가 '+b.open.toLocaleString('ko-KR')+' · 고가 '+b.high.toLocaleString('ko-KR')+' · 저가 '+b.low.toLocaleString('ko-KR')+' · 종가 '+b.close.toLocaleString('ko-KR')+' · 거래량 '+b.volume.toLocaleString('ko-KR');
}
$('flow-prev').addEventListener('click',()=>stepFlow(-1));$('flow-next').addEventListener('click',()=>stepFlow(1));
for (const id of ['flow-frame','flow-chart-source']) $(id).addEventListener('change',()=>loadFlowChart());
$('flow-range').addEventListener('change',()=>{flowHover=-1;paintFlow();});
$('hero-target').addEventListener('change',()=>{localStorage.setItem('collector-hero-chart',$('hero-target').value);if(flowPick)linkFlowHero(flowPick.code);});
document.addEventListener('keydown',e=>{
  if(!['ArrowUp','ArrowDown'].includes(e.key)||e.altKey||e.ctrlKey||e.metaKey||e.shiftKey||e.isComposing||e.target.closest('input,select,textarea,dialog,[contenteditable="true"]'))return;
  e.preventDefault();stepFlow(e.key==='ArrowDown'?1:-1);
});
$('flow-chart').addEventListener('pointermove',e=>{if(!flowChart)return;const rect=$('flow-chart').getBoundingClientRect(),total=$('flow-range').value==='all'?flowChart.bars.length:Math.min(Number($('flow-range').value),flowChart.bars.length);flowHover=Math.max(0,Math.min(total-1,Math.floor((e.clientX-rect.left-12)/(rect.width-90)*total)));paintFlow();});
$('flow-chart').addEventListener('pointerleave',()=>{flowHover=-1;paintFlow();});
new ResizeObserver(paintFlow).observe($('flow-chart').parentElement);
loadFlowTargets();setInterval(loadFlowTargets,30000);
setInterval(()=>{if(flowPick&&!document.hidden&&$('flow-chart-source').value==='live')loadFlowChart(true);},15000);
