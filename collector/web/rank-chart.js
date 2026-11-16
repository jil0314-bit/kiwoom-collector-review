'use strict';
// Shared chart for the absolute rankings, recommendations and observations.
const chartEl=id=>document.getElementById(id);
let rankStocks=[],rankDay='',rankCode='',rankRecord=null,rankVersion=0,rankTimer=null,rankAbort=null;
let rankHeroVersion=0,rankHeroTimer,rankHeroQueue=Promise.resolve();
let rankZoom=null, rankRangeBeforeZoom=null;
let rankLoading=false;
async function rankHeroTargets(){
  try{const r=await fetch('/api/hero-targets');if(!r.ok)return;const data=await r.json(),select=chartEl('rank-hero-target'),previous=select.value||localStorage.getItem('collector-hero-chart')||data.preferred||'';
    select.replaceChildren(new Option('영웅문 0600 · 자동 선택',''),new Option('영웅문 연동 끄기','off'),...data.targets.map(t=>new Option(t.label,t.handle)));
    select.value=previous==='off'||data.targets.some(t=>t.handle===previous)?previous:data.preferred||'';
    if(select.value!=='off'&&data.diagnostic?.state!=='ready')chartEl('rank-hero-status').textContent=data.diagnostic?.message||'영웅문 연결 대상 확인 필요';
  }catch(error){chartEl('rank-hero-status').textContent='영웅문 대상 확인 실패';}
}
function rankLinkHero(symbol){
  const version=++rankHeroVersion;clearTimeout(rankHeroTimer);
  rankHeroTimer=setTimeout(()=>{rankHeroQueue=rankHeroQueue.then(async()=>{
    if(version!==rankHeroVersion)return;const chart=chartEl('rank-hero-target').value;
    if(chart==='off'){chartEl('rank-hero-status').textContent='영웅문 연동 꺼짐';return;}
    try{const status=await (await fetch('/api/status')).json();if(version!==rankHeroVersion)return;
      const result=await window.collectorHeroSend(symbol,chart,status.token,()=>version===rankHeroVersion);
      if(!result)return;chartEl('rank-hero-status').textContent=result.message||result.error||'영웅문 응답 확인 필요';
    }catch(error){if(version===rankHeroVersion)chartEl('rank-hero-status').textContent='영웅문 연동: '+error.message;}
  });},100);
}
const rankFormat=value=>value==null?'—':Number(value).toLocaleString('ko-KR',{maximumFractionDigits:2});
const rankSource = () => document.body.dataset.chartSource || (document.body.dataset.rankApi === '/api/amount-top' ? 'amount-top' : 'volume-top');
function rankParams(){const day=rankStocks.find(stock=>stock.code===rankCode)?.chart_day||rankDay;const query=new URLSearchParams({day,code:rankCode,source:rankSource(),frame:chartEl('rank-frame').value,live:chartEl('rank-live').value==='live'?'1':'0'});if(Number(rankRangeBeforeZoom??chartEl('rank-range').value)>=360)query.set('history','1');return query;}
function rankHighlight(){for(const row of document.querySelectorAll('#rows tr')){const selected=row.dataset.code===rankCode;row.classList.toggle('selected',selected);row.querySelector('button')?.setAttribute('aria-pressed',String(selected));}}
function rankDetails(bar){
  if(!bar){chartEl('rank-details').textContent='';return;}
  const periods=chartPeriods(chartEl('rank-frame').value);
  chartEl('rank-details').textContent=bar.ts+' KST · 시가 '+rankFormat(bar.open)+' · 고가 '+rankFormat(bar.high)+' · 저가 '+rankFormat(bar.low)+' · 종가 '+rankFormat(bar.close)+' · 거래량 '+rankFormat(bar.volume)+'주\n'+periods.map(n=>n+'선 '+rankFormat(bar['ma'+n])).join(' / ');
}
function rankBars(){
  const bars=rankRecord?.bars||[];
  if(rankZoom)return bars.filter(bar=>bar.ts>=rankZoom.start && bar.ts<=rankZoom.end);
  const count=Number(chartEl('rank-range').value);
  return count?bars.slice(-count):bars;
}
const rankButtons=bindChartExports(()=>({record:rankRecord,bars:rankBars(),canvas:chartEl('rank-canvas')}),()=>rankRefresh(true),rankDraw);
let rankGeometry;
const rankInspection = bindChartInspection(chartEl('rank-canvas'), () => rankGeometry, rankDraw, zoomRank, resetRankZoom);
function rankDraw(){
  const canvas=chartEl('rank-canvas'),ratio=window.devicePixelRatio||1,width=canvas.clientWidth||400,height=canvas.clientHeight||500;
  canvas.width=Math.round(width*ratio);canvas.height=height*ratio;
  const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);
  const bars=rankBars();
  const periods=chartPeriods(chartEl('rank-frame').value);
  rankButtons(!!rankCode,!!bars.length);
  chartEl('zoom-reset').disabled=!rankZoom;
  drawChartLegend(chartEl('rank-legend'),bars.length?periods:[]);
  chartEl('rank-count').textContent=bars.length?chartRangeStatus(bars.length,chartEl('rank-range').value):'';
  rankGeometry=paintCandles(ctx,width,height,bars,periods);
  rankDetails(rankInspection.paint(ctx, rankGeometry, rankRecord) || rankRecord?.bars.at(-1));
}
function rankChoose(code,scroll=false,sendHero=true){
  const stock=rankStocks.find(s=>s.code===code);if(!stock)return;
  rankCode=code;window.collectorStockTools?.({day:stock.chart_day||rankDay,code,name:stock.name,source:rankSource()});rankRecord=null;clearRankZoom();
  chartEl('rank-title').textContent=stock.name+' ('+stock.code+')';chartEl('rank-notice').textContent='차트 조회 중…';
  rankHighlight();rankDraw();if(scroll)document.querySelector('#rows tr[data-code="'+code+'"]')?.scrollIntoView({block:'nearest'});
  rankRefresh();
  if(sendHero)rankLinkHero(code);
}
function rankRefresh(reload=false){
  if(!rankCode)return;
  rankVersion++;clearTimeout(rankTimer);rankAbort?.abort();
  rankLoad(rankVersion,0,reload);
}
async function rankLoad(version,attempt=0,reload=false){
  const params=rankParams();params.set('fast','1');params.set('async','1');const controller=new AbortController();rankAbort=controller;
  rankLoading=true;
  try{
    const response=await collectorChartFetch('/api/chart?'+params,{signal:controller.signal,cache:reload?'reload':'default'}),data=await response.json();if(version!==rankVersion)return;
    if(!response.ok)throw Error(data.error||'차트 조회 실패');
    if(data.pending){if(attempt>=40)throw Error('차트 조회가 지연됩니다. 차트 다시 조회를 눌러주세요.');rankTimer=setTimeout(()=>rankLoad(version,attempt+1),1000);return;}
    if(!data.bars?.length)throw Error('선택한 종목의 차트 자료가 없습니다.');
    if(data.stock?.code!==rankCode)throw Error('선택 종목과 차트 응답이 다릅니다.');
    rankRecord=data;chartEl('rank-notice').textContent=data.chart_notice||('기준일 '+data.day);rankDraw();
    if(data.refreshing&&attempt<40)rankTimer=setTimeout(()=>rankLoad(version,attempt+1),1000);
  }catch(error){
    if(version!==rankVersion||error.name==='AbortError')return;
    chartEl('rank-notice').textContent=(rankRecord?'이전 차트 표시 · ':'')+error.message;
  }finally{if(version===rankVersion)rankLoading=false;}
}
window.rankUpdate=(day,stocks)=>{
  const oldChartDay=rankStocks.find(stock=>stock.code===rankCode)?.chart_day||rankDay;
  const newChartDay=stocks.find(stock=>stock.code===rankCode)?.chart_day||day;
  const changed=oldChartDay!==newChartDay;rankDay=day;rankStocks=stocks;
  if(!stocks.length){rankVersion++;clearTimeout(rankTimer);rankAbort?.abort();rankCode='';window.collectorStockTools?.(null);rankRecord=null;clearRankZoom();chartEl('rank-title').textContent='표시할 종목 없음';chartEl('rank-notice').textContent='';rankDraw();return;}
  if(changed||!stocks.some(s=>s.code===rankCode))rankChoose(stocks[0].code,false,false);else rankHighlight();
};
chartEl('rows').addEventListener('click',event=>{const row=event.target.closest('tr[data-code]');if(row)rankChoose(row.dataset.code);});
document.addEventListener('keydown',event=>{
  if(!['ArrowUp','ArrowDown'].includes(event.key)||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey)return;
  if(event.target.closest('input,textarea,select,[contenteditable="true"],dialog'))return;
  const index=rankStocks.findIndex(s=>s.code===rankCode);if(index<0)return;
  event.preventDefault();const next=Math.max(0,Math.min(rankStocks.length-1,index+(event.key==='ArrowDown'?1:-1)));
  if(next!==index)rankChoose(rankStocks[next].code,true);
});
for(const id of ['rank-frame','rank-live'])chartEl(id).addEventListener('change',()=>rankChoose(rankCode,false,false));
chartEl('rank-hero-target').addEventListener('change',()=>{localStorage.setItem('collector-hero-chart',chartEl('rank-hero-target').value);if(rankCode)rankLinkHero(rankCode);});
rankHeroTargets();setInterval(rankHeroTargets,30000);
chartEl('rank-range').addEventListener('change',()=>{clearRankZoom();rankDraw();rankRefresh();});
window.addEventListener('resize',rankDraw);

function zoomRank(start, end) {
  const range = chartEl('rank-range');
  if (range.value !== 'custom') rankRangeBeforeZoom = range.value;
  rankZoom = {start, end};
  range.querySelector('option[value="custom"]').disabled = false;
  range.value = 'custom';
  rankDraw();
}
function clearRankZoom() {
  const range = chartEl('rank-range');
  rankInspection.clear();
  if (range.value === 'custom') range.value = rankRangeBeforeZoom ?? '0';
  range.querySelector('option[value="custom"]').disabled = true;
  rankRangeBeforeZoom = rankZoom = null;
}
function resetRankZoom() { clearRankZoom(); rankDraw(); }
chartEl('zoom-reset').onclick = resetRankZoom;
setInterval(()=>{if(rankCode&&!rankLoading&&!document.hidden&&!rankInspection.dragging()&&chartEl('rank-live').value==='live')rankRefresh();},15000);
