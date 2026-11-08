'use strict';
const $=id=>document.getElementById(id), fmt=n=>n==null?'—':Number(n).toLocaleString('ko-KR',{maximumFractionDigits:2});
let status={}, meta={stocks:[]}, record=null, choice='', code='', selected=-1, requestVersion=0, refreshing=false, openedFlag=false;
let frame='minute', loading=false, liveChart=true;
let liveQuotes={},quoteRequest=0,quotesBusy=false;
let listMode='ranking', watchlists=[], watchGroup='';
let automaticStockSectors={};
let stockThemeMap=new Map(), stockThemeDay='', stockThemeAt=0, stockThemeVersion=0;
let stockProfiles={};
const marketCapText=(profile,day)=>profile?.market_cap>0?'시총 '+Number(profile.market_cap).toLocaleString('ko-KR')+'억'+(profile.cap_day&&profile.cap_day!==day?' · '+profile.cap_day+' 기준':''):'시총 확인중';
const periods=()=>['day','week'].includes(frame)?[5,10,20,30,60,120]:[5,10,20,60,120,240];
const maColors={5:'#ff8000',10:'#800080',20:'#008000',30:'#ff0000',60:'#0000ff',120:'#000080',240:'#000000'};
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
async function api(path,options){if(path.startsWith('/api/chart?'))path+='&fast=1&async=1';const r=await (path.startsWith('/api/chart?')&&!path.includes('prefetch=1')?collectorChartFetch(path,options):fetch(path,options));const data=await r.json();if(!r.ok)throw Error(data.error||'요청 실패');return data}
function params(withRevision=false){const [day,kind]=choice.split('|');const q=new URLSearchParams({day,kind,code});q.set('frame',frame);if(liveChart)q.set('live','1');if(listMode==='watchlist'){q.set('source','watchlist');q.set('group',watchGroup)}else if(liveChart&&currentStocks().find(s=>s.code===code)?.status!=='saved')q.set('source','ranking-current');else if(withRevision)q.set('rev',meta.revision||meta.ranking_at||'');return q}
const activeGroup=()=>watchlists.find(g=>String(g.number)===watchGroup);
const currentEntries=()=>listMode==='watchlist'?(activeGroup()?.entries||[]):meta.stocks;
const currentStocks=()=>currentEntries().filter(s=>s.type!=='heading');
const displayedEntries=()=>{const query=$('search').value.trim().toLowerCase();return currentEntries().filter(s=>!query||s.type!=='heading'&&(s.name+s.code).toLowerCase().includes(query))};
async function loadWatchlists(){try{const result=await api('/api/watchlists');const previous=watchGroup;watchlists=result.groups;$('watch-group').replaceChildren(...watchlists.map(g=>new Option(String(g.number).padStart(2,'0')+' · '+g.name+' ('+g.entries.filter(e=>e.type==='stock').length+')',g.number)));watchGroup=watchlists.some(g=>String(g.number)===previous)?previous:String(watchlists[0]?.number||'');$('watch-group').value=watchGroup;if(listMode==='watchlist')renderStocks()}catch(e){if(listMode==='watchlist')$('stocks').replaceChildren(element('div',e.message,'empty'))}}
function element(tag,text,cls){const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e}
// Verified business-sector fallback; provenance: collector/data/theme_classifications.json
const verifiedStockSectors={"0158S0":{"name":"엘리스","labels":["AI·클라우드"],"url":"https://elice.io/ko","checked_at":"2026-10-21","kind":"business"},"365660":{"name":"레몬헬스케어","labels":["디지털 헬스케어"],"url":"https://www.newspim.com/news/view/20260617000637","checked_at":"2026-10-21","kind":"business"},"179880":{"name":"멜콘","labels":["반도체 장비"],"url":"https://melcon.co.kr/page/vision.html","checked_at":"2026-10-21","kind":"business"},"099520":{"name":"DGI","labels":["디지털 프린터"],"url":"https://kr.dgi-net.com/download.cm?tk=YToyOntpOjA7czoxMzoiNmE4MTFhYTM1NjZhNCI7aToxO3M6MjI6ImYyMDI0MDQwODBlMDM5M2M4Yzc4OTIiO30%3D","checked_at":"2026-10-21","kind":"business"},"011080":{"name":"형지I&C","labels":["패션·의류"],"url":"https://www.edaily.co.kr/News/Read?newsId=04582166645478440","checked_at":"2026-10-21","kind":"business"},"308100":{"name":"형지글로벌","labels":["패션·골프웨어"],"url":"https://www.jobkorea.co.kr/company/45689267","checked_at":"2026-10-21","kind":"business"},"244920":{"name":"에이플러스에셋","labels":["보험대리점(GA)"],"url":"https://www.aplusgroup.co.kr/APA/index.do?PCVersion=Y","checked_at":"2026-10-21","kind":"business"},"373200":{"name":"엑스플러스","labels":["모바일 액세서리"],"url":"https://kind.krx.co.kr/external/2026/05/15/001019/20260515002188/11013.htm","checked_at":"2026-10-21","kind":"business"},"034730":{"name":"SK","labels":["지주회사"],"url":"https://sk-inc.com/resources/download/esg/sustainability/SK-Inc_Special_Report_2023_KOR.pdf","checked_at":"2026-10-21","kind":"business"},"0035S0":{"name":"빅웨이브로보틱스","labels":["로봇 플랫폼"],"url":"https://stock.pstatic.net/stock-ipo/A0035S0/company/A0035S0_company_20251217131004.pdf","checked_at":"2026-10-21","kind":"business"},"032580":{"name":"피델릭스","labels":["메모리 반도체"],"url":"https://www.paxnet.co.kr/WWW/data/researchCenter/attach/20240103100406801.pdf","checked_at":"2026-10-21","kind":"business"},"323350":{"name":"다원넥스뷰","labels":["반도체·레이저장비"],"url":"https://www.nexview.co.kr/company1.php","checked_at":"2026-10-21","kind":"business"},"458350":{"name":"에스팀","labels":["엔터·콘텐츠"],"url":"https://www.truefriend.com/main/research/research/StrategyDetail.jsp?id=156283&jkGubun=6","checked_at":"2026-10-21","kind":"business"},"069920":{"name":"엑시온그룹","labels":["반도체 설비·로봇자동화"],"url":"https://comp.wisereport.co.kr/company/c1010001.aspx?cmp_cd=069920","checked_at":"2026-10-21","kind":"business"},"181710":{"name":"NHN","labels":["게임·클라우드"],"url":"https://inside.nhn.com/news/875","checked_at":"2026-10-21","kind":"business"},"144960":{"name":"뉴파워프라즈마","labels":["반도체·플라즈마"],"url":"https://www.ktb.co.kr/common/download.jspx?cmd=viewPDF&path=%2Fattach_file%2FRESEARCH%2F66775%2F1%2F20171117_144960_nickkim82_186.pdf","checked_at":"2026-10-21","kind":"business"},"025560":{"name":"미래산업","labels":["반도체 검사장비"],"url":"https://www.mirae.com/ko","checked_at":"2026-10-21","kind":"business"},"225190":{"name":"LK삼양","labels":["광학렌즈·드론카메라"],"url":"https://lksamyang.irpage.co.kr/","checked_at":"2026-10-21","kind":"business"},"486510":{"name":"글로벌테크놀로지","labels":["시스템반도체·LED"],"url":"https://ir.newspim.com/news/view/20260721000241","checked_at":"2026-10-21","kind":"business"},"03473K":{"name":"SK우","labels":["지주회사"],"url":"https://sk-inc.com/resources/download/esg/sustainability/SK-Inc_Special_Report_2023_KOR.pdf","checked_at":"2026-10-21","kind":"business"},"488900":{"name":"비츠로넥스텍","labels":["우주항공·핵융합"],"url":"https://vitzronextech.irpage.co.kr/","checked_at":"2026-10-21","kind":"business"},"061090":{"name":"세나테크놀로지","labels":["웨어러블·무선통신"],"url":"https://www.senakorea.kr/static/docs/ug/UserGuide_SRL2_v1.0.0_kr_JK24.pdf","checked_at":"2026-10-21","kind":"business"},"417030":{"name":"니어스랩","labels":["AI·자율비행드론"],"url":"https://www.koraia.org/base/img/_des/mp3/2020_KOREAAI.pdf","checked_at":"2026-10-21","kind":"business"},"009900":{"name":"명신산업","labels":["자동차 차체부품"],"url":"https://www.myoungshinindustry.com/summary","checked_at":"2026-10-21","kind":"business"},"354320":{"name":"알멕","labels":["전기차·알루미늄부품"],"url":"https://www.hanaw.com/main/research/research/download.cmd?attachFileSeq=1&bbsCd=2210&bbsId=&bbsSeq=1286275&dbType=","checked_at":"2026-10-21","kind":"business"},"214330":{"name":"금호에이치티","labels":["자동차 조명"],"url":"https://m.kisrating.com/fileDown.do?fileName=rs20230530-19.pdf&gubun=2&menuCd=R8","checked_at":"2026-10-21","kind":"business"},"483350":{"name":"딜리셔스","labels":["패션·이커머스"],"url":"https://www.dealicious.kr/","checked_at":"2026-10-21","kind":"business"},"114630":{"name":"폴라리스우노","labels":["가발용 합성섬유"],"url":"https://www.paxnet.co.kr/WWW/data/researchCenter/attach/20220407131110749.pdf","checked_at":"2026-10-21","kind":"business"},"138360":{"name":"앤로보틱스","labels":["AI로봇·자동화"],"url":"https://nrobotics.co.kr/company.php","checked_at":"2026-10-21","kind":"business"},"032960":{"name":"동일기연","labels":["전자부품·EMC"],"url":"https://www.dongiltech.co.kr/","checked_at":"2026-10-21","kind":"business"},"0017J0":{"name":"세미티에스","labels":["반도체 물류장비"],"url":"https://comp.nicebizline.com/co/CO0100M010GE.nice?nav=2&stockcd=0017J0","checked_at":"2026-10-21","kind":"business"},"065150":{"name":"대산F&B","labels":["식품·육가공"],"url":"https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?MenuYn=Y&NewMenuID=Y&ReportGB=D&cID=&gicode=A065150&pGB=1&stkGb=701","checked_at":"2026-10-21","kind":"business"},"484120":{"name":"도우인시스","labels":["폴더블·UTG"],"url":"https://www.eugenefn.com/common/files/amail/20250709_B45_Juhyeonglee_13.pdf","checked_at":"2026-10-21","kind":"business"},"476830":{"name":"알지노믹스","labels":["RNA·유전자치료"],"url":"https://bbn.kiwoom.com/rfCR11777","checked_at":"2026-10-21","kind":"business"},"007340":{"name":"DN오토모티브","labels":["자동차부품·공작기계"],"url":"https://bbn.kiwoom.com/research/SPdfFileView?attaFile=1758874224084.pdf&makeDt=2025.09.29&rMenuGb=CR","checked_at":"2026-10-21","kind":"business"},"148930":{"name":"에이치와이티씨","labels":["이차전지 장비부품"],"url":"https://file.irgo.co.kr/data/BOARD/ATTACH_PDF/53RPNCQMZDKEZKJ2KA8T8Q94S9FCUQCX20227614138.pdf","checked_at":"2026-10-21","kind":"business"},"042000":{"name":"카페24","labels":["이커머스·유튜브쇼핑"],"url":"https://www.cafe24.us/en","checked_at":"2026-10-21","kind":"business"},"168360":{"name":"펨트론","labels":["반도체·3D검사장비"],"url":"https://www.jobkorea.co.kr/Recruit/co_read/c/pemtron","checked_at":"2026-10-21","kind":"business"},"250930":{"name":"예선테크","labels":["디스플레이 점착소재"],"url":"https://files-scs.pstatic.net/2024/07/30/9txzerfYOF/%EC%98%88%EC%84%A0%ED%85%8C%ED%81%AC%2024%EB%85%847%EC%9B%94%20IR%EC%9E%90%EB%A3%8C.pdf","checked_at":"2026-10-21","kind":"business"},"377030":{"name":"비트맥스","labels":["AR·디지털자산"],"url":"https://corvesting.com/company/kr/377030/","checked_at":"2026-10-21","kind":"business"},"366030":{"name":"나인앤컴퍼니","labels":["패션·온라인의류"],"url":"https://corvesting.com/company/kr/366030/","checked_at":"2026-10-21","kind":"business"},"475230":{"name":"엔알비","labels":["모듈러 건축"],"url":"https://www.and-rb.com/kor/news/161/download/1","checked_at":"2026-10-21","kind":"business"},"387690":{"name":"레메디","labels":["의료기기·X-ray"],"url":"https://stock.pstatic.net/stock-ipo/A387690/company/A387690_company_20260206133003.pdf","checked_at":"2026-10-21","kind":"business"},"186230":{"name":"그린플러스","labels":["스마트팜"],"url":"https://ir.newspim.com/news/view/20231222000237","checked_at":"2026-10-21","kind":"business"},"266690":{"name":"덕산넵코어스","labels":["우주항공·위성항법"],"url":"https://www.dshm.co.kr/IR_Reference/IR_Report/2024/DSHM_24.1Q%28KR%29_V8.pdf","checked_at":"2026-10-21","kind":"business"},"123840":{"name":"뉴온","labels":["건강기능식품·생활용품"],"url":"https://nuon.kr/front/cn/board/board_view.php?bo_table=board_news&wr_id=36","checked_at":"2026-10-21","kind":"business"}};
// Read-only theme labels: existing dated Kiwoom themes plus current watchlist sectors.
function buildStockThemeMap(themeRecord, groups){
  const result=new Map();
  const add=(symbol,label,source)=>{
    if(!symbol||!label)return;
    const tags=result.get(symbol)||[];
    if(!tags.some(t=>t.label===label))tags.push({label,source});
    result.set(symbol,tags);
  };
  for(const theme of themeRecord?.themes||[]){
    for(const symbol of theme.member_codes||[])add(symbol,theme.name,'선택 날짜 키움 테마');
    for(const item of theme.leaders||[])add(item.code,theme.name,'선택 날짜 테마 분류');
  }
  for(const theme of themeRecord?.custom||[]){
    for(const item of theme.leaders||[])add(item.code,theme.name,'선택 날짜 사용자 테마');
  }
  const excluded=new Set([6,9,10,39,43,66,98,99]);
  for(const group of groups||[]){
    if(excluded.has(Number(group.number)))continue;
    for(const item of group.entries||[]){
      if(item.type==='stock')add(item.code,group.name,'현재 관심종목 섹터 분류');
    }
  }
  for(const [symbol,item] of Object.entries({...automaticStockSectors,...verifiedStockSectors})){
    if(result.has(symbol))continue;
    for(const label of item.labels||[])add(symbol,'업종 · '+label,'업종·사업 분류 (확인 '+item.checked_at+'). 당일 상승 이유 아님. '+item.url);
  }
  return result;
}
function stockThemeBadges(symbol,expanded=false){
  const box=element('span',null,'stock-themes');
  const tags=stockThemeMap.get(symbol)||[];
  box.title=tags.map(t=>t.label+' · '+t.source).join(' / ')||'기존 자료에서 확인된 테마가 없습니다.';
  if(!tags.length){box.append(element('span','테마 확인불가','theme-badge unknown'));return box;}
  for(const tag of (expanded?tags:tags.slice(0,2))){
    const chip=element('span',tag.label,'theme-badge'+(tag.label.startsWith('업종 · ')?' business':''));chip.title=tag.source;box.append(chip);
  }
  if(!expanded&&tags.length>2)box.append(element('span','+'+(tags.length-2),'theme-badge more'));
  return box;
}
function renderSelectedThemes(){
  const target=$('selected-themes');
  if(target)target.replaceChildren(...(code?[stockThemeBadges(code,true)]:[]));
  if(typeof renderInlineMemo==='function')renderInlineMemo();
}
async function loadStockThemes(day){
  if(stockThemeDay===day&&Date.now()-stockThemeAt<60000)return;
  stockThemeDay=day;stockThemeAt=Date.now();const version=++stockThemeVersion;
  stockThemeMap=buildStockThemeMap(null,watchlists);
  renderSelectedThemes();
  try{
    const [result,sectors,profiles]=await Promise.all([api('/api/themes?day='+encodeURIComponent(day)),api('/api/stock-sectors').catch(()=>({items:automaticStockSectors})),api('/api/stock-profiles?day='+encodeURIComponent(day)).catch(()=>({profiles:{}}))]);
    if(version!==stockThemeVersion||choice.split('|')[0]!==day)return;
    automaticStockSectors=sectors.items||{};
    stockProfiles=profiles.profiles||{};
    stockThemeMap=buildStockThemeMap(result.record,watchlists);
  }catch(error){if(version!==stockThemeVersion)return;}
  renderStocks();
}
async function post(path,body={}){return api(path,{method:'POST',headers:{'Content-Type':'application/json','X-Collector-Token':status.token},body:JSON.stringify(body)})}
async function refresh(){if(refreshing)return;refreshing=true;try{status=await api('/api/status');$('clock').textContent=status.now.slice(0,19).replace('T',' ')+' KST';$('auth').textContent=status.credentials?'인증정보 준비됨':'인증정보 필요';$('progress').textContent=status.state.message+(status.state.queued?' · 다음 갱신 예약됨':'');$('auto-info').textContent='항상 자동 · 20:05 최종';
if(!openedFlag){await post('/api/open');openedFlag=true}
await loadWatchlists();
const old=$('archive').value;const catalog=status.catalog; $('archive').replaceChildren();for(const c of catalog){const value=c.day+'|'+c.kind;const o=new Option(c.day+(c.phase==='final'?' · 최종':c.day<status.now.slice(0,10)?' · 장중 저장 (최종 미수집)':' · 장중 최신')+(c.status==='partial'?' · 일부 실패':''),value);$('archive').add(o)}
if(!catalog.length){$('archive').add(new Option('오늘 · 관심종목 조회',status.now.slice(0,10)+'|latest'));$('archive').value=$('archive').options[0].value;if(listMode==='ranking')return}else{const valid=catalog.some(c=>c.day+'|'+c.kind===old);$('archive').value=valid?old:$('archive').options[0].value}
const changed=choice!==$('archive').value;choice=$('archive').value;await loadDay(changed);
}catch(e){$('auth').textContent='수집기 연결 확인 필요';$('progress').textContent=e.message||'실행 파일로 수집기를 켜주세요.'}finally{refreshing=false}}
async function loadDay(changed=false){if(changed)liveQuotes={};const oldRevision=meta.revision||meta.ranking_at;meta=await api('/api/day?'+params());loadNotes(choice.split('|')[0]);loadStockThemes(choice.split('|')[0]);$('saved').replaceChildren(document.createTextNode(String(meta.stocks.filter(s=>s.status==='saved').length)+' '),element('small','/ '+meta.stocks.length+'종목'));$('ranktime').textContent=(meta.kind==='preview'?(meta.day<status.now.slice(0,10)?'장중 저장 · 최종 미수집 · ':'장중 최신 · '):'최종 · ')+(meta.ranking_at||'').slice(11,19)+' KST';renderStocks();if(changed)refreshQuotes();if(!loading&&(changed||!record||!liveChart&&listMode==='ranking'&&oldRevision!==(meta.revision||meta.ranking_at))){const keepTime=!changed&&record&&selected<record.bars.length-1?record.bars[selected]?.ts:null;const s=listMode==='watchlist'?currentStocks().find(s=>s.code===code)||currentStocks()[0]:meta.stocks.find(s=>s.status==='saved'&&s.code===code)||meta.stocks.find(s=>s.status==='saved');if(s){if(changed)chooseCurrentStock(s.code);else await selectStock(s.code,keepTime)}else clearChart()}}
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
const name=element('span',null,'name');name.append(element('span',s.name,'stock-name-text'),stockThemeBadges(s.code));name.append(element('small',s.code+' · '+marketCapText(stockProfiles[s.code],choice.split('|')[0])));name.title=s.name;b.append(name);if(listMode==='ranking'){const q=liveQuotes[s.code]||(record?.live&&code===s.code?record.quote:null);b.append(element('span',q?fmt(q.price)+'원\n'+signedPercent(q.rate):'현재 조회 중','rate '+(q?changeClass(q.rate):'')))}b.onclick=()=>chooseCurrentStock(s.code);
row.append(b,noteMark(s));$('stocks').append(row)
}
$('stocks').scrollTop=listScroll;decorateNotes();renderSelectedThemes();
if(focusCode){const row=$('stocks').querySelector(`[data-stock-code="${focusCode}"]`);row?.querySelector(focusMemo?'.memo-mark':'.stock')?.focus({preventScroll:true})}
}
function clearChart(){resetChartView();record=null;code='';selected=-1;renderSelectedThemes();$('selected-name').textContent='저장된 종목을 선택하세요';$('selected-code').textContent='MINUTE CHART';$('bars').replaceChildren();$('minute').replaceChildren();$('values').replaceChildren();$('bar-changes').replaceChildren();$('png').disabled=true;$('csv').classList.add('disabled');$('csv').removeAttribute('href');$('chart-empty').style.display='flex';draw()}
async function selectStock(next,keepTime=null,background=false){if(background&&drag){setTimeout(()=>{if(code===next&&!document.hidden)selectStock(next,keepTime,true)},500);return}const s=currentStocks().find(x=>x.code===next);if(!s||!liveChart&&listMode==='ranking'&&s.status!=='saved'){toast(s?.error||'아직 저장되지 않은 종목입니다.');return}code=next;if(!background){$('png').disabled=true;$('csv').classList.add('disabled')}const version=++requestVersion,previousRecord=record;const path='/api/chart?'+params(true);loading=true;cancelDrag();clearHover();if(!background){record=null;$('selected-name').textContent=s.name;$('selected-code').textContent=s.code+' / 차트 조회 중';$('chart-empty').textContent=frame==='day'?'일봉 이력을 불러오는 중입니다…':frame==='week'?'주봉 이력을 불러오는 중입니다…':'분봉을 불러오는 중입니다…';$('chart-empty').style.display='flex';$('values').replaceChildren();$('bar-changes').replaceChildren();$('bars').replaceChildren();$('minute').replaceChildren();$('ma-values').textContent='';draw()}try{const result=await api(path);if(version!==requestVersion)return;if(result.pending){setTimeout(()=>{if(version===requestVersion&&!document.hidden)selectStock(next,keepTime,background)},200);return}if(background&&drag){setTimeout(()=>{if(code===next&&!document.hidden)selectStock(next,keepTime,true)},500);return}prepareChartRecord(result,previousRecord);record=result;selected=keepTime?record.bars.findIndex(b=>b.ts===keepTime):-1;if(selected<0)selected=record.bars.length-1;$('selected-name').textContent=s.name+(record.live&&record.quote?' · 현재가 '+fmt(record.quote.price)+'원 ('+signedPercent(record.quote.rate)+')':'');$('selected-code').textContent=s.code+' / '+record.day+(record.live_fallback?' / 저장 분봉 · 오늘 분봉 없음':record.live?' / 현재 차트 · 조회 '+record.fetched_at.slice(11,19)+' KST':listMode==='watchlist'?' / 관심종목 별도 조회':record.kind==='preview'?' / 장중 저장 자료':' / 최종 자료');$('chart-empty').style.display='none';$('png').disabled=false;$('csv').classList.remove('disabled');$('csv').href='/api/chart.csv?'+params(true);$('minute').replaceChildren(...record.bars.map((b,i)=>new Option(barLabel(b.ts),i)));$('coverage').textContent=(record.chart_notice||'')+(record.live||listMode==='watchlist'||frame==='day'||frame==='week'?'':` 수신 ${s.count}봉 · ${s.first.slice(11,16)}~${s.last.slice(11,16)} | 09시 전 ${s.pre}봉 · 09:00~15:30 ${s.regular}봉 · 15:30 이후 ${s.after}봉. 빈 시간은 비거래/미제공 여부 미확인.`);renderStocks();renderTable();selectMinute(selected);if(!background)prefetchNeighbours();if(result.refreshing)setTimeout(()=>{if(version===requestVersion&&!document.hidden)selectStock(next,record?.bars[selected]?.ts||null,true)},1000)}catch(e){if(version!==requestVersion)return;if(background&&previousRecord){record=previousRecord;$('coverage').textContent='현재 조회 실패 · 이전 자료 유지 · '+e.message;return}record=null;$('chart-empty').textContent=e.message;$('chart-empty').style.display='flex';$('png').disabled=true;$('csv').classList.add('disabled');toast(e.message);draw()}finally{if(version===requestVersion)loading=false}}
function renderTable(){const frag=document.createDocumentFragment();record.bars.forEach((b,i)=>{const tr=element('tr');tr.dataset.index=i;for(const k of ['ts','open','high','low','close'])tr.append(element('td',k==='ts'?barLabel(b.ts):fmt(b[k])));const rates=barChanges(i);for(const rate of [rates.body,rates.previous])tr.append(element('td',signedPercent(rate),changeClass(rate)));tr.append(element('td',fmt(b.volume)));tr.onclick=()=>selectMinute(i);frag.append(tr)});$('bars').replaceChildren(frag)}
function selectMinute(i){if(!record||!record.bars[i])return;clearHover();selected=i;const b=record.bars[i];$('minute').value=i;$('values').replaceChildren(...[['시가','open'],['고가 · 최고가','high'],['저가 · 최저가','low'],[closeLabel(),'close'],['거래량 (주)','volume']].map(([label,k])=>{const d=element('div');d.append(element('span',label),element('strong',fmt(b[k])));return d}));const rates=barChanges(i);$('bar-changes').replaceChildren(...[['봉 등락률 · 시가 대비',rates.body],['직전 저장봉 종가 대비',rates.previous]].map(([label,rate])=>{const d=element('div');d.append(element('span',label),element('strong',signedPercent(rate),changeClass(rate)));return d}));$('ma-values').replaceChildren(element('span',b.ts+' KST'+(b.end_ts?(frame==='week'?' ~ '+b.end_ts+' 마지막 거래일':' ~ '+b.end_ts.slice(11,16)+' 직전 · 원본 '+b.source_count+'/'+record.interval_minutes+'개 분봉'):''),'ma-timestamp'),...periods().map(n=>element('span',n+maUnit()+'선 '+fmt(b['ma'+n])+(b['ma'+n]==null?' (이력 부족)':'원'),'ma-value ma'+n)));if(record.kind==='preview')$('ma-values').append(element('span',frame==='week'?'이번 주 봉은 진행 중일 수 있습니다.':'장중 마지막 봉은 진행 중일 수 있습니다.','ma-timestamp'));for(const tr of $('bars').rows)tr.classList.toggle('chosen',Number(tr.dataset.index)===i);draw()}
function visible(){if(!record)return[];if(viewRange)return record.bars.filter(b=>b.ts>=viewRange.start&&b.ts<=viewRange.end);const n=$('range').value;return n==='all'?record.bars:record.bars.slice(-Number(n))}
function draw(){const canvas=$('chart'),dpr=window.devicePixelRatio||1,w=canvas.clientWidth||800,h=400;canvas.width=Math.round(w*dpr);canvas.height=h*dpr;const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);chartGeometry=null;paint(ctx,w,h);updateZoomControls();positionTooltip()}
function paint(ctx,w,h){ctx.fillStyle='#ffffff';ctx.fillRect(0,0,w,h);const bars=visible();if(!bars.length)return;const left=12,right=76,top=20,bottom=52,volH=66,priceH=h-top-bottom-volH-25;const width=w-left-right;const values=bars.flatMap(b=>[b.low,b.high,...periods().map(n=>b['ma'+n])].filter(v=>v!=null));let lo=Math.min(...values),hi=Math.max(...values),pad=(hi-lo)*.08||hi*.005;lo-=pad;hi+=pad;const y=p=>top+(hi-p)/(hi-lo)*priceH,step=width/(bars.length+3),x=i=>left+(i+.5)*step;
ctx.font='10px Segoe UI';ctx.textAlign='left';for(let i=0;i<=4;i++){const p=lo+(hi-lo)*i/4,yy=y(p);ctx.strokeStyle='#cbd5e1';ctx.beginPath();ctx.moveTo(left,yy);ctx.lineTo(w-right,yy);ctx.stroke();ctx.fillStyle='#000000';ctx.fillText(fmt(p),w-right+9,yy+3)}
const vmax=Math.max(1,...bars.map(b=>b.volume)),volBase=h-bottom;bars.forEach((b,i)=>{const color=b.close>=b.open?'#ff0000':'#0000ff';ctx.strokeStyle=color;ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(x(i),y(b.high));ctx.lineTo(x(i),y(b.low));ctx.stroke();ctx.fillRect(x(i)-Math.max(.7,step*.32),Math.min(y(b.open),y(b.close)),Math.max(1.4,step*.64),Math.max(1,Math.abs(y(b.close)-y(b.open))));ctx.globalAlpha=1;ctx.fillRect(x(i)-Math.max(.7,step*.32),volBase-b.volume/vmax*volH,Math.max(1.4,step*.64),b.volume/vmax*volH);ctx.globalAlpha=1});
for(const n of periods()){const key='ma'+n;ctx.strokeStyle=maColors[n];ctx.lineWidth=[20,60].includes(n)?3.6:1.2;ctx.beginPath();let active=false;bars.forEach((b,i)=>{if(b[key]==null){active=false;return}if(active)ctx.lineTo(x(i),y(b[key]));else{ctx.moveTo(x(i),y(b[key]));active=true}});ctx.stroke()}ctx.lineWidth=1;
const count=Math.min(7,bars.length,Math.max(2,Math.floor(width/(frame==='day'?92:55))));for(let j=0;j<count;j++){const i=Math.round(j*(bars.length-1)/Math.max(1,count-1));ctx.fillStyle='#000000';ctx.textAlign='center';const label=barLabel(bars[i].ts),half=ctx.measureText(label).width/2;ctx.fillText(label,Math.max(left+half,Math.min(x(i),w-right-half)),h-28)}ctx.textAlign='left';ctx.fillStyle='#000000';ctx.fillText('거래량',left,volBase-volH-7);ctx.fillText(frame==='day'?'거래일 순서 · KST':'거래가 있는 분봉 순서 · KST',left,h-9);
chartGeometry={left,right:w-right,top,bottom:volBase,priceBottom:top+priceH,dataRight:left+bars.length*step,lo,hi,w,h,bars,step};
if(drag){const a=bars.indexOf(record.bars[Math.min(drag.start,drag.end)]),b=bars.indexOf(record.bars[Math.max(drag.start,drag.end)]);if(a>=0&&b>=0){ctx.fillStyle='#80008026';ctx.fillRect(left+a*step,top,(b-a+1)*step,volBase-top);ctx.strokeStyle='#800080';ctx.strokeRect(left+a*step,top,(b-a+1)*step,volBase-top);ctx.font='12px Malgun Gothic';ctx.fillStyle='#800080';ctx.fillText(`${barLabel(bars[a].ts)} ~ ${barLabel(bars[b].ts)} · ${b-a+1}봉`,Math.min(left+a*step+6,Math.max(left,w-right-205)),top+17)}}
const chosen=record.bars[hover?hover.index:selected],i=bars.indexOf(chosen);if(i>=0){const xx=x(i)+(!hover&&i===bars.length-1?step:0);ctx.strokeStyle='#000080';ctx.setLineDash([4,3]);ctx.beginPath();ctx.moveTo(xx,top);ctx.lineTo(xx,volBase);if(hover){ctx.moveTo(left,hover.y);ctx.lineTo(w-right,hover.y)}ctx.stroke();ctx.setLineDash([]);if(hover){ctx.font='12px Malgun Gothic';const time=barLabel(chosen.ts),tw=ctx.measureText(time).width+16,tx=Math.max(left,Math.min(xx-tw/2,w-right-tw));ctx.fillStyle='#000080';ctx.fillRect(tx,volBase+9,tw,22);ctx.fillStyle='#fff';ctx.fillText(time,tx+8,volBase+24);if(hover.y<=top+priceH){const price=hi-(hover.y-top)/priceH*(hi-lo);ctx.fillStyle='#000080';ctx.fillRect(w-right+2,hover.y-11,right-3,22);ctx.fillStyle='#fff';ctx.font='11px Segoe UI';ctx.fillText(fmt(price),w-right+6,hover.y+4)}}}}
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
$('list-mode').onchange=async()=>{listMode=$('list-mode').value;$('watch-group').hidden=listMode!=='watchlist';$('list-badge').textContent=listMode==='watchlist'?'0130 섹터':'TOP 100';$('list-heading').textContent=listMode==='watchlist'?'관심종목':'순위 / 종목';$('list-trailing').textContent=listMode==='watchlist'?'':'현재가 · 등락률';$('search').value='';requestVersion++;clearChart();renderStocks();const s=listMode==='watchlist'?currentStocks()[0]:meta.stocks.find(s=>s.status==='saved');if(s)await selectStock(s.code)};
$('watch-group').onchange=async()=>{watchGroup=$('watch-group').value;requestVersion++;clearChart();renderStocks();const s=currentStocks()[0];if(s)await selectStock(s.code)};
$('png').onclick=()=>{if(!record)return;const q=params(true);q.set('minute',record.bars[selected].ts);window.location.href='/api/chart.png?'+q};
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
        const data=await window.collectorHeroSend(symbol,chart,status.token,()=>version===heroLinkVersion);
        if(!data)return;if(data.ok){toast(data.message);return}
        throw Error(data.message||'영웅문 연동 실패');
      }catch(e){if(version===heroLinkVersion)toast('영웅문 연동: '+e.message)}
    });
  },0);
}

async function loadHeroTargets(){try{const r=await api("/api/hero-targets"),previous=$("hero-target").value||localStorage.getItem("collector-hero-chart")||r.preferred||"";$("hero-target").replaceChildren(new Option("영웅문 0600 · 자동 선택",""),new Option("영웅문 연동 끄기","off"),...r.targets.map(t=>new Option(t.label,t.handle)));$("hero-target").value=previous==="off"||r.targets.some(t=>t.handle===previous)?previous:r.targets.some(t=>t.handle===r.preferred)?r.preferred:"";localStorage.setItem("collector-hero-chart",$("hero-target").value)}catch(e){}}
$("hero-target").onchange=()=>localStorage.setItem("collector-hero-chart",$("hero-target").value);
window.addEventListener("DOMContentLoaded",()=>{loadHeroTargets();setInterval(loadHeroTargets,30000)});

const neighbourPrefetch=new Map();
function prefetchNeighbours(){
  const stocks=currentStocks().filter(s=>listMode==='watchlist'||s.status==='saved'),i=stocks.findIndex(s=>s.code===code);
  for(const neighbour of [stocks[i-1],stocks[i+1]]){
    if(!neighbour)continue;
    const q=params(true);q.set('code',neighbour.code);q.set('prefetch','1');
    const key=q.toString(),now=Date.now();if(now-(neighbourPrefetch.get(key)||0)<15000)continue;
    neighbourPrefetch.set(key,now);if(neighbourPrefetch.size>128)neighbourPrefetch.delete(neighbourPrefetch.keys().next().value);
    api('/api/chart?'+q).catch(()=>{});
  }
}
