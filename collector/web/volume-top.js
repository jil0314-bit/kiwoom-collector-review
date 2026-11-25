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
const rankColumns=[
  ['rank','순위'],['name','종목명'],['price','현재가'],['rate','등락률(%)'],
  ['volume','거래량(주)'],['turnover','거래회전율(%)'],['amount_million','거래대금'],
];
function stockNameCell(stock, day){
  const cell=document.createElement('td');
  const button=document.createElement('button');
  button.type='button';
  button.className='rank-stock';
  button.textContent=stock.name;
  button.setAttribute('aria-label',stock.name+' 차트 보기');
  const profile=rankProfiles[stock.code]||{};
  const groups=profile.groups?.join(' · ')||'미확인';
  const theme=profile.themes?.length?'테마 · '+profile.themes.join(' · '):
    profile.groups?.length?'관심테마그룹 · '+groups:'테마 미확인'+(profile.industry?' · 업종 '+profile.industry:'');
  const cap=profile.market_cap>0?'시총 '+formatWon(profile.market_cap,1e8)+
    (profile.cap_day && profile.cap_day!==day?' · '+profile.cap_day+' 기준':''):'시총 미확인';
  cell.append(button);
  collectorSetStockRate(button,stock.code,stock.rate,day+' 순위 저장 기준');
  for(const [text, extraClass] of [[stock.code,'stock-code-under'],['관심그룹 · '+groups,''],[theme,''],[cap,'stock-money']]){
    const detail=document.createElement('small');
    detail.className='rank-profile'+(extraClass?' '+extraClass:'');
    detail.textContent='• '+text;
    if(text===theme)detail.title=detail.textContent;
    cell.append(detail);
  }
  return cell;
}
function stockRow(stock, day){
  const row=document.createElement('tr');
  row.dataset.code=stock.code;
  for(const [key,label] of rankColumns){
    const cell=key==='name'?stockNameCell(stock,day):document.createElement('td');
    cell.dataset.column=key;
    if(key!=='name' && key!=='rank')cell.dataset.label=label;
    if(key==='price' || key==='amount_million'){
      cell.className='money-value';
      cell.textContent=key==='price'?fmt(stock.price)+'원':formatWon(stock.amount_million,1e6);
    }else if(key!=='name'){
      cell.textContent=key==='rate'?collectorRateText(stock.rate):fmt(stock[key]);
      if(key==='rate')cell.classList.add('collector-price-rate');
      if(key==='volume' && stock.volume_limit_possible){
        const note=document.createElement('small');
        note.className='rank-volume-note';
        note.textContent='상한값 가능';
        note.title='API 거래량 상한값일 수 있습니다.';
        cell.append(note);
      }
    }
    row.append(cell);
  }
  return row;
}
async function refresh(){
  const version=++listVersion;
  const selected=el('day').value;
  const response=await fetch(rankApi+(selected?'?day='+encodeURIComponent(selected):''));
  const data=await response.json();if(version!==listVersion)return;if(!response.ok)throw Error(data.error||'조회 실패');token=data.token;
  if(rankProfileDay!==data.day)rankProfiles={};
  el('day').replaceChildren(...data.days.map(day=>new Option(day,day)));
  if(data.days.includes(selected))el('day').value=selected;
  el('status').textContent=data.state.message+' · '+(data.observed_at||'저장 자료 없음')+' · '+data.stocks.length+'종목';
  const focusCode=document.activeElement?.closest('tr[data-code]')?.dataset.code;
  el('rows').replaceChildren(...data.stocks.map(stock=>stockRow(stock,data.day)));
  if(focusCode)el('rows').querySelector('tr[data-code="'+focusCode+'"] button')?.focus({preventScroll:true});
  window.rankUpdate?.(data.day,data.stocks);
  if(rankProfileDay!==data.day || Date.now()-rankProfileAt>=60000){
    loadRankProfiles(data.day).then(()=>{
      if(version!==listVersion || rankProfileDay!==data.day)return;
      for(const stock of data.stocks){
        const cell=el('rows').querySelector(`tr[data-code="${stock.code}"] [data-column="name"]`);
        if(cell)cell.replaceChildren(cell.firstElementChild,...Array.from(stockNameCell(stock,data.day).children).slice(1));
      }
    });
  }
}
async function collect(){if(busy)return;busy=true;el('collect').disabled=true;
  try{if(!token)await refresh();const r=await fetch(rankApi+'/collect',{method:'POST',headers:{'Content-Type':'application/json','X-Collector-Token':token},body:'{}'});if(!r.ok)throw Error('조회 시작 실패');await refresh();}
  catch(e){el('status').textContent=e.message;}finally{busy=false;el('collect').disabled=false;}}
el('day').addEventListener('change',()=>refresh().catch(e=>el('status').textContent=e.message));
el('collect').addEventListener('click',collect);
collect();
setInterval(()=>refresh().catch(e=>el('status').textContent=e.message),5000);
setInterval(()=>{const now=new Date(new Date().toLocaleString('en-US',{timeZone:'Asia/Seoul'}));const minute=now.getHours()*60+now.getMinutes();if(now.getDay()>0&&now.getDay()<6&&minute>=480&&minute<=1205)collect();},60000);
