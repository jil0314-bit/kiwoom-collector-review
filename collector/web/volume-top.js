'use strict';
const el=id=>document.getElementById(id), fmt=x=>Number(x).toLocaleString('ko-KR',{maximumFractionDigits:2});
let token='',busy=false;
let listVersion=0;
let rankProfiles={},rankProfileDay='',rankProfileAt=0;
async function loadRankProfiles(day){
  if(rankProfileDay===day&&Date.now()-rankProfileAt<60000)return;
  if(rankProfileDay!==day)rankProfiles={};
  try{const r=await fetch('/api/stock-profiles?'+new URLSearchParams({day}));if(!r.ok)return;const data=await r.json();rankProfiles=data.profiles||{};rankProfileDay=day;rankProfileAt=Date.now();}catch(error){}
}
const rankApi=document.body.dataset.rankApi||'/api/volume-top';
async function refresh(){
  const version=++listVersion;
  const selected=el('day').value;
  const response=await fetch(rankApi+(selected?'?day='+encodeURIComponent(selected):''));
  const data=await response.json();if(version!==listVersion)return;if(!response.ok)throw Error(data.error||'조회 실패');token=data.token;
  await loadRankProfiles(data.day);if(version!==listVersion)return;
  el('day').replaceChildren(...data.days.map(day=>new Option(day,day)));
  if(data.days.includes(selected))el('day').value=selected;
  el('status').textContent=data.state.message+' · '+(data.observed_at||'저장 자료 없음')+' · '+data.stocks.length+'종목';
  const focusCode=document.activeElement?.closest('tr[data-code]')?.dataset.code;
  el('rows').replaceChildren(...data.stocks.map(stock=>{const row=document.createElement('tr');row.dataset.code=stock.code;
    for(const key of ['rank','name','code','price','rate','volume','turnover','amount_million']){
      const cell=document.createElement('td');if(key==='name'){const button=document.createElement('button');button.type='button';button.className='rank-stock';button.textContent=stock.name;button.setAttribute('aria-label',stock.name+' 분봉 차트 보기');cell.append(button);const profile=rankProfiles[stock.code]||{};const theme=document.createElement('small');theme.className='rank-profile';theme.textContent=profile.themes?.length?'테마 · '+profile.themes.join(' · '):profile.groups?.length?'관심테마그룹 · '+profile.groups.join(' · '):'테마 미확인'+(profile.industry?' · 업종 '+profile.industry:'');theme.title=theme.textContent;const cap=document.createElement('small');cap.className='rank-profile';cap.textContent=profile.market_cap>0?'시총 '+fmt(profile.market_cap)+'억'+(profile.cap_day!==data.day?' · '+profile.cap_day+' 기준':''):'시총 미확인';cell.append(theme,cap);}else cell.textContent=key==='code'?stock[key]:fmt(stock[key])+(key==='volume'&&stock.volume_limit_possible?' (API 상한값 가능)':'');row.append(cell);
    }return row;}));
  if(focusCode)el('rows').querySelector('tr[data-code="'+focusCode+'"] button')?.focus({preventScroll:true});
  window.rankUpdate?.(data.day,data.stocks);
}
async function collect(){if(busy)return;busy=true;el('collect').disabled=true;
  try{if(!token)await refresh();const r=await fetch(rankApi+'/collect',{method:'POST',headers:{'Content-Type':'application/json','X-Collector-Token':token},body:'{}'});if(!r.ok)throw Error('조회 시작 실패');await refresh();}
  catch(e){el('status').textContent=e.message;}finally{busy=false;el('collect').disabled=false;}}
el('day').addEventListener('change',()=>refresh().catch(e=>el('status').textContent=e.message));
el('collect').addEventListener('click',collect);
collect();
setInterval(()=>refresh().catch(e=>el('status').textContent=e.message),5000);
setInterval(()=>{const now=new Date(new Date().toLocaleString('en-US',{timeZone:'Asia/Seoul'}));const minute=now.getHours()*60+now.getMinutes();if(now.getDay()>0&&now.getDay()<6&&minute>=480&&minute<=1205)collect();},60000);
