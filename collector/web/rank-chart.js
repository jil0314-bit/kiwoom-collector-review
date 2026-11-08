'use strict';
// Only the two absolute-ranking pages use this view. Data/MA calculation stays server-side.
const chartEl=id=>document.getElementById(id);
let rankStocks=[],rankDay='',rankCode='',rankRecord=null,rankVersion=0,rankTimer=null,rankAbort=null,rankHover=-1;
let rankHeroVersion=0,rankHeroTimer,rankHeroQueue=Promise.resolve();
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
      const response=await fetch('/api/hero-link',{method:'POST',headers:{'Content-Type':'application/json','X-Collector-Token':status.token},body:JSON.stringify({code:symbol,chart})});const result=await response.json();
      if(version!==rankHeroVersion)return;chartEl('rank-hero-status').textContent=result.message||result.error||'영웅문 응답 확인 필요';
    }catch(error){if(version===rankHeroVersion)chartEl('rank-hero-status').textContent='영웅문 연동: '+error.message;}
  });},100);
}
const rankColors={5:'#d28a16',10:'#9a54d8',20:'#109e9b',30:'#ef6487',60:'#3778e6',120:'#e57927',240:'#546380'};
const rankFormat=value=>value==null?'—':Number(value).toLocaleString('ko-KR',{maximumFractionDigits:2});
function rankParams(){return new URLSearchParams({day:rankDay,code:rankCode,source:document.body.dataset.chartSource||(document.body.dataset.rankApi==='/api/amount-top'?'amount-top':'volume-top'),frame:chartEl('rank-frame').value,live:chartEl('rank-live')?.checked?'1':'0'});}
function rankHighlight(){for(const row of document.querySelectorAll('#rows tr')){const selected=row.dataset.code===rankCode;row.classList.toggle('selected',selected);row.querySelector('button')?.setAttribute('aria-pressed',String(selected));}}
function rankDetails(bar){
  if(!bar){chartEl('rank-details').textContent='';return;}
  const periods=['day','week'].includes(chartEl('rank-frame').value)?[5,10,20,30,60,120]:[5,10,20,60,120,240];
  chartEl('rank-details').textContent=bar.ts+' KST · 시가 '+rankFormat(bar.open)+' · 고가 '+rankFormat(bar.high)+' · 저가 '+rankFormat(bar.low)+' · 종가 '+rankFormat(bar.close)+' · 거래량 '+rankFormat(bar.volume)+'주\n'+periods.map(n=>n+'선 '+rankFormat(bar['ma'+n])).join(' / ');
}
function rankBars(){const bars=rankRecord?.bars||[];const count=Number(chartEl('rank-range').value);return count?bars.slice(-count):bars;}
function rankDraw(){
  const canvas=chartEl('rank-canvas'),ratio=window.devicePixelRatio||1,width=Math.max(300,canvas.clientWidth),height=440;
  canvas.width=Math.round(width*ratio);canvas.height=height*ratio;const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);ctx.clearRect(0,0,width,height);
  const bars=rankBars();if(!bars.length)return;
  const periods=['day','week'].includes(chartEl('rank-frame').value)?[5,10,20,30,60,120]:[5,10,20,60,120,240];
  const values=bars.flatMap(b=>[b.low,b.high,...periods.map(n=>b['ma'+n])]).filter(Number.isFinite);
  let lo=Math.min(...values),hi=Math.max(...values);const pad=(hi-lo)*.06||Math.max(1,hi*.005);lo-=pad;hi+=pad;
  const left=10,right=width-85,top=32,bottom=320,step=(right-left)/bars.length;
  const x=i=>left+(i+.5)*step,y=p=>top+(hi-p)/(hi-lo)*(bottom-top);
  ctx.font='11px Malgun Gothic';ctx.fillStyle='#63708a';ctx.fillText('20·60선은 3배 굵기 · KRX+NXT 통합',left,15);
  for(let i=0;i<6;i++){const p=lo+(hi-lo)*i/5,yy=y(p);ctx.strokeStyle='#e3e7f0';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(left,yy);ctx.lineTo(right,yy);ctx.stroke();ctx.fillText(rankFormat(p),right+5,yy+4);}
  const maxVolume=Math.max(1,...bars.map(b=>b.volume));
  bars.forEach((b,i)=>{ctx.fillStyle=ctx.strokeStyle=b.close>=b.open?'#d44763':'#397bd0';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x(i),y(b.high));ctx.lineTo(x(i),y(b.low));ctx.stroke();ctx.fillRect(x(i)-Math.max(.4,step*.3),Math.min(y(b.open),y(b.close)),Math.max(.8,step*.6),Math.max(1,Math.abs(y(b.open)-y(b.close))));ctx.fillRect(x(i)-step*.3,405-b.volume/maxVolume*60,Math.max(.8,step*.6),b.volume/maxVolume*60);});
  periods.forEach(n=>{ctx.strokeStyle=rankColors[n];ctx.lineWidth=[20,60].includes(n)?3:1;ctx.beginPath();let active=false;bars.forEach((b,i)=>{const p=b['ma'+n];if(!Number.isFinite(p)){active=false;return;}if(active)ctx.lineTo(x(i),y(p));else ctx.moveTo(x(i),y(p));active=true;});ctx.stroke();});
  ctx.fillStyle='#63708a';ctx.fillText('거래량(주)',left,342);
  const frame=chartEl('rank-frame').value;for(let i=0;i<5;i++){const j=Math.round(i*(bars.length-1)/4),label=frame==='day'||frame==='week'?bars[j].ts:bars[j].ts.slice(11,16);ctx.fillText(label,Math.min(right-45,Math.max(left,x(j)-15)),430);}
  if(rankHover>=0&&rankHover<bars.length){ctx.strokeStyle='#785bdd';ctx.lineWidth=1;ctx.setLineDash([4,3]);ctx.beginPath();ctx.moveTo(x(rankHover),top);ctx.lineTo(x(rankHover),405);ctx.stroke();ctx.setLineDash([]);}
}
function rankChoose(code,scroll=false,sendHero=true){
  const stock=rankStocks.find(s=>s.code===code);if(!stock)return;
  rankCode=code;rankRecord=null;rankHover=-1;rankVersion++;clearTimeout(rankTimer);rankAbort?.abort();rankAbort=null;
  chartEl('rank-title').textContent=stock.name+' ('+stock.code+')';chartEl('rank-notice').textContent='분봉 조회 중…';
  chartEl('rank-details').textContent='';for(const id of ['rank-csv','rank-png']){chartEl(id).removeAttribute('href');chartEl(id).setAttribute('aria-disabled','true');}
  rankHighlight();rankDraw();if(scroll)document.querySelector('#rows tr[data-code="'+code+'"]')?.scrollIntoView({block:'nearest'});
  rankLoad(rankVersion);
  if(sendHero)rankLinkHero(code);
}
async function rankLoad(version,attempt=0){
  const params=rankParams();params.set('fast','1');params.set('async','1');const controller=new AbortController();rankAbort=controller;
  try{
    const response=await collectorChartFetch('/api/chart?'+params,{signal:controller.signal}),data=await response.json();if(version!==rankVersion)return;
    if(!response.ok)throw Error(data.error||'차트 조회 실패');
    if(data.pending){if(attempt>=40)throw Error('차트 조회가 지연됩니다. 차트 다시 조회를 눌러주세요.');rankTimer=setTimeout(()=>rankLoad(version,attempt+1),1000);return;}
    if(!data.bars?.length)throw Error('선택한 날짜의 분봉 자료가 없습니다.');
    if(data.stock?.code!==rankCode)throw Error('선택 종목과 차트 응답이 다릅니다.');
    rankRecord=data;chartEl('rank-notice').textContent=data.chart_notice||('기준일 '+data.day);rankDetails(data.bars.at(-1));rankDraw();
    for(const [id,path] of [['rank-csv','/api/chart.csv?'],['rank-png','/api/chart.png?']]){chartEl(id).href=path+rankParams();chartEl(id).setAttribute('aria-disabled','false');}
    if(data.refreshing&&attempt<40)rankTimer=setTimeout(()=>rankLoad(version,attempt+1),1000);
  }catch(error){if(version!==rankVersion||error.name==='AbortError')return;chartEl('rank-notice').textContent=error.message;}
}
window.rankUpdate=(day,stocks)=>{
  const changed=day!==rankDay;rankDay=day;rankStocks=stocks;
  if(!stocks.length){rankVersion++;clearTimeout(rankTimer);rankAbort?.abort();rankCode='';rankRecord=null;chartEl('rank-title').textContent='저장된 종목 없음';rankDetails(null);rankDraw();return;}
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
chartEl('rank-frame').addEventListener('change',()=>rankChoose(rankCode,false,false));chartEl('rank-reload').addEventListener('click',()=>rankChoose(rankCode,false,false));
chartEl('rank-hero-target').addEventListener('change',()=>{localStorage.setItem('collector-hero-chart',chartEl('rank-hero-target').value);if(rankCode)rankLinkHero(rankCode);});
rankHeroTargets();setInterval(rankHeroTargets,30000);
chartEl('rank-range').addEventListener('change',()=>{rankHover=-1;rankDraw();});
chartEl('rank-canvas').addEventListener('mousemove',event=>{const bars=rankBars();if(!bars.length)return;const rect=event.currentTarget.getBoundingClientRect();rankHover=Math.max(0,Math.min(bars.length-1,Math.floor((event.clientX-rect.left-10)/(rect.width-95)*bars.length)));rankDetails(bars[rankHover]);rankDraw();});
chartEl('rank-canvas').addEventListener('mouseleave',()=>{rankHover=-1;rankDetails(rankRecord?.bars.at(-1));rankDraw();});
window.addEventListener('resize',rankDraw);
