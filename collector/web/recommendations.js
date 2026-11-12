'use strict';
const recEl=id=>document.getElementById(id),recNode=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
const recLabels={pending:'음성전사 검수대기',new:'신규추천',consultation:'보유종목 상담',review:'과거추천 복기',sell:'매도·축소',interest:'관심종목'};
const recKindClass={pending:'rec-kind-pending',new:'rec-kind-new',consultation:'rec-kind-consultation',review:'rec-kind-review',sell:'rec-kind-sell',interest:'rec-kind-interest'};
let recData=null,recProfiles={},recVersion=0,recSelected='',recNoteTarget=null,recRevision='',recNoteSaving=false;
const recDrafts=new Map();
const recMoney=p=>p?p.min.toLocaleString('ko-KR')+(p.max!==p.min?'~'+p.max.toLocaleString('ko-KR'):'')+'원':'미확인';
async function recApi(url,body){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);try{const response=await fetch(url,{signal:controller.signal,...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Collector-Token':recData.token},body:JSON.stringify(body)})});const data=await response.json();if(!response.ok)throw Error(data.error||'요청 실패');return data;}catch(e){if(e.name==='AbortError')throw Error('응답 지연 · 보관 자료를 다시 확인해주세요.');throw e;}finally{clearTimeout(timer);}}
function recLink(url,label){const a=recNode('a',label,'rec-source-link');if(!/^https:\/\//.test(url||''))return a;a.href=url;a.target='_blank';a.rel='noopener noreferrer';a.onclick=e=>e.stopPropagation();return a;}
function recRows(){const kind=recEl('rec-kind').value,source=recEl('rec-source').value,term=recEl('rec-search').value.trim().toLowerCase();return(recData?.records||[]).filter(r=>(!kind||(kind==='focus'?['new','interest'].includes(r.classification):r.classification===kind))&&r.classification!=='mention'&&(!source||r.broadcaster===source)&&(!term||[r.name,r.code,r.expert,r.program,r.reason].join(' ').toLowerCase().includes(term)));}
function recRender(){
 const focusCode=document.activeElement?.closest('#rows tr[data-code]')?.dataset.code;
 const rows=recRows(),stocks=[...new Map(rows.map(r=>[r.code,{code:r.code,name:r.name}])).values()];
 recEl('rec-count').textContent=rows.length+'건 · '+stocks.length+'종목';recEl('rec-empty').hidden=!!rows.length;
 recEl('rec-empty').textContent=recData.records.length?'선택한 조건에 맞는 자료가 없습니다. 분류·채널·검색 조건을 바꾸거나 최근 신규추천을 확인하세요.':'이 날짜의 보관 자료가 없습니다. 다른 날짜 또는 수집 현황을 확인하세요.';
 const counts=recData.records.reduce((a,r)=>(a[r.classification]=(a[r.classification]||0)+1,a),{});
 recEl('rec-summary').textContent='보관 '+recData.day+' · 표시 '+rows.length+'건 / 신규추천 '+(counts.new||0)+' / 관심종목 '+(counts.interest||0)+' / 상담 '+(counts.consultation||0)+' · 단순 언급 제외';
 recEl('rows').replaceChildren(...rows.map(r=>{const tr=recNode('tr');tr.dataset.code=r.code;tr.dataset.record=r.id;const importantProgram=r.program==='AI황금분석';if(importantProgram)tr.classList.add('rec-important-program');
  const left=recNode('td'),button=recNode('button',r.name,'rank-stock');button.type='button';left.append(button,recNode('small',r.code));const p=recProfiles[r.code]||{};
  left.append(recNode('small',p.market_cap>0?'시총 '+Number(p.market_cap).toLocaleString('ko-KR')+'억'+(p.cap_day!==recData.day?' · '+p.cap_day+' 기준':''):'시총 미확인','rec-sector rec-cap'));
  left.append(recNode('small','키움 테마 · '+(p.themes?.join(' · ')||'미확인'),'rec-sector rec-theme'),recNode('small','관심테마그룹 · '+(p.groups?.join(' · ')||'미확인'),'rec-sector rec-group'),recNode('small','업종 · '+(p.industry||'미확인'),'rec-sector rec-industry'));
  const right=recNode('td'),attribution=recNode('div',null,'rec-attribution');right.append(recNode('span',recLabels[r.classification]||'분류 확인 필요','rec-badge '+(recKindClass[r.classification]||'rec-kind-pending')));if(importantProgram)right.append(recNode('span','중요 방송 · AI황금분석','rec-badge rec-important-label'));attribution.append(recNode('span',r.broadcaster||'방송 미확인','rec-origin rec-broadcaster'),recNode('span',r.program||'프로그램 미확인','rec-origin rec-program'),recNode('span',r.expert||'전문가 미확인','rec-origin rec-expert'));right.append(attribution,
   recNode('small','추천 '+(r.recommended_date||'날짜 미확인')+' '+(r.recommended_time||'시각 미확인')+' KST'),recNode('p','추천·매수가 '+recMoney(r.buy_price)+' / 목표가 '+recMoney(r.target_price)+' / 손절가 '+recMoney(r.stop_price)),recNode('p','이유: '+(r.reason||'명시적 근거 요약 미확인')),
   recLink(r.url,'원문 확인'),recNode('small',(r.evidence_type||'')+' · 게시 '+(r.published_at||'미확인')));
  if(r.candidate_prices)right.append(recNode('small','음성인식 후보(미검증): 매수 '+recMoney(r.candidate_prices.buy_price)+' / 목표 '+recMoney(r.candidate_prices.target_price)+' / 손절 '+recMoney(r.candidate_prices.stop_price)));
  tr.append(left,right);return tr;
 }));
 if(focusCode)recEl('rows').querySelector('tr[data-code="'+focusCode+'"] .rank-stock')?.focus({preventScroll:true});
 window.rankUpdate(recData.day,stocks);if(!stocks.length)for(const id of ['rank-csv','rank-png'])recEl(id).removeAttribute('href');
 const record=rows.find(r=>r.id===recSelected&&r.code===rankCode)||rows.find(r=>r.code===rankCode);recDetail(record);
}
function recDetail(r){recEl('rec-note').disabled=!r;const box=recEl('rec-detail');box.replaceChildren();if(!r){recSelected='';return;}recSelected=r.id;
 box.append(recNode('strong',r.name+' · '+(r.expert||'전문가 미확인')),recNode('p',r.reason||'추천 이유 미확인'),recNode('small','추천일 근거: '+r.date_basis+' / 시각 근거: '+r.time_basis+' / '+(r.review_status||'원문 확인 필요')),recNode('pre',r.evidence||''),recLink(r.url,'추천 원문'));
 if(r.video_url)box.append(document.createTextNode(' · '),recLink(r.video_url,'방송 원본'));
 if(r.video_offset_seconds!=null)box.append(document.createTextNode(' · '),recLink(r.url+'&t='+r.video_offset_seconds,'영상 '+Math.floor(r.video_offset_seconds/60)+'분 '+r.video_offset_seconds%60+'초 (방송 시각 아님)'));
}
function recLedger(){const book=recData.ledger,box=recEl('rec-ledger-body');box.replaceChildren();
 const done=Object.values(book.documents).filter(d=>d.status==='완료').length;box.append(recNode('strong','선택 날짜: 원문 완료 '+done+' / 발견 '+Object.keys(book.documents).length+'개 · 전체 발견 '+(book.total_documents??Object.keys(book.documents).length)+'개'));
 for(const s of [...recData.sources.programs,...recData.sources.channels]){const state=book.sources[s.url];const p=recNode('p');p.append(recLink(s.url,s.name),document.createTextNode(' · '+(state?.status||'확인 대기')+' · '+(state?.message||state?.coverage||'')+' · '+(state?.checked_at||'')));box.append(p);}
 for(const d of Object.values(book.documents).filter(d=>d.status!=='완료')){const p=recNode('p'),message=d.message?.startsWith('Expecting value')?'공개 자막 응답 확인 불가·발언 미확인':d.message||'';p.append(recLink(d.url,d.title||d.url),document.createTextNode(' · '+(d.status||'확인 대기')+' · '+message));box.append(p);}
}
async function recRefresh(){const version=++recVersion,selected=recEl('rec-day').value;const data=await recApi('/api/recommendations'+(selected?'?day='+encodeURIComponent(selected):''));if(version!==recVersion)return;
 recData=data;recProfiles={};recEl('rec-day').replaceChildren(...data.days.map(d=>new Option(d,d)));recEl('rec-day').value=data.day;
 const source=recEl('rec-source').value;recEl('rec-source').replaceChildren(new Option('전체',''),...[...new Set(data.records.map(r=>r.broadcaster))].map(s=>new Option(s,s)));recEl('rec-source').value=source;
 recEl('rec-monitor').checked=data.enabled;recEl('rec-status').textContent=data.state.message+' · '+(data.state.last_run||'수집 대기')+(data.state.busy?' · 진행 중':'')+' · 선택 날짜 신규추천 '+data.records.filter(r=>r.classification==='new').length+' / 전체 '+data.records.length+'건'+(data.profile_error?' · 시총·테마 조회 확인 필요':'');
 recEl('rec-collect').disabled=data.state.busy;recEl('rec-export').href='/api/recommendations.csv?day='+encodeURIComponent(data.day);recRender();recLedger();
 const documents=Object.values(data.ledger.documents),sources=Object.values(data.ledger.sources),captions=documents.filter(d=>/자막/.test(d.message||'')),failures=sources.filter(s=>['수집 실패','확인 필요'].includes(s.status));
 recEl('rec-health').textContent='선택 날짜 원문 '+documents.length+'개 · 자막 확인 필요 '+captions.length+'개 · 채널·방송 확인 필요 '+failures.length+'곳. '+(data.records.some(r=>['new','interest'].includes(r.classification))?'신규추천·관심종목은 기본 보기에서 확인하세요.':'이 날짜에 확인된 신규추천·관심종목이 없습니다. 최근 날짜와 수집 현황을 확인하세요.');
 // Optional profiles must never hold the saved recommendation list hostage.
 recApi('/api/stock-profiles?'+new URLSearchParams({day:data.day})).then(result=>{if(version!==recVersion)return;recProfiles=result.profiles||{};recRender();}).catch(()=>{if(version===recVersion)recEl('rec-status').textContent+=' · 시총·테마 조회 지연 (보관 목록은 표시됨)';});
}
recEl('rec-latest-new').onclick=async()=>{const button=recEl('rec-latest-new');button.disabled=true;try{if(!recData)await recRefresh();for(const day of recData.days){const data=day===recData.day?recData:await recApi('/api/recommendations?day='+encodeURIComponent(day));if(!data.records.some(r=>r.classification==='new'))continue;recEl('rec-day').value=day;recEl('rec-kind').value='new';recEl('rec-source').value='';recEl('rec-search').value='';await recRefresh();return;}recEl('rec-status').textContent='보관된 날짜에 확인된 신규추천이 없습니다. 수집 현황에서 원문·자막 상태를 확인하세요.';}catch(e){recError(e);}finally{button.disabled=false;}};
recEl('rec-day').onchange=()=>recRefresh().catch(recError);
for(const id of ['rec-kind','rec-source','rec-search'])recEl(id).addEventListener(id==='rec-search'?'input':'change',()=>{if(recData)recRender();});
function recError(e){recEl('rec-status').textContent='자료 확인 실패: '+e.message;recEl('rec-empty').hidden=false;recEl('rec-empty').textContent=recData?'마지막으로 받은 자료를 표시 중입니다. 새로고침으로 다시 확인하세요.':'자료를 불러오지 못했습니다. 새로고침으로 다시 확인하세요.';}
recEl('rec-refresh').onclick=()=>recRefresh().catch(recError);
recEl('rec-collect').onclick=async()=>{try{recEl('rec-collect').disabled=true;await recApi('/api/recommendations/collect',{});await recRefresh();}catch(e){recError(e);recEl('rec-collect').disabled=false;}};
recEl('rec-monitor').onchange=async()=>{try{await recApi('/api/recommendations/monitor',{enabled:recEl('rec-monitor').checked});}catch(e){recError(e);recEl('rec-monitor').checked=recData.enabled;}};
recEl('rows').addEventListener('click',e=>{const tr=e.target.closest('tr[data-record]');if(tr&&!e.target.closest('a'))recDetail(recData.records.find(r=>r.id===tr.dataset.record));});
document.addEventListener('keydown',e=>{if(['ArrowUp','ArrowDown'].includes(e.key)&&!e.target.closest('input,textarea,select,[contenteditable="true"],dialog'))recDetail(recRows().find(r=>r.code===rankCode));});
recEl('rank-live').onchange=()=>{if(rankCode)rankChoose(rankCode,false,false);};
// Reuse the existing renderer, candles, moving averages and cache; zoom is page-local.
let recZoom=null,recDrag=null,recZoomIdentity='';const recBaseBars=rankBars;
rankBars=function(){const identity=rankDay+'|'+rankCode+'|'+recEl('rank-frame').value+'|'+recEl('rank-range').value;if(identity!==recZoomIdentity){recZoom=null;recZoomIdentity=identity;}const bars=recBaseBars();return recZoom?bars.slice(recZoom[0],recZoom[1]):bars;};
const recCanvas=recEl('rank-canvas');
recCanvas.addEventListener('pointerdown',e=>{if(e.button!==0||!rankBars().length)return;recDrag={x:e.clientX,bars:rankBars(),base:recZoom?recZoom[0]:0};recCanvas.setPointerCapture(e.pointerId);});
recCanvas.addEventListener('pointerup',e=>{if(!recDrag)return;const drag=recDrag;recDrag=null;if(Math.abs(drag.x-e.clientX)<8)return;const rect=recCanvas.getBoundingClientRect(),width=rect.width-95,index=x=>Math.max(0,Math.min(drag.bars.length-1,Math.floor((x-rect.left-10)/width*drag.bars.length))),a=index(drag.x),b=index(e.clientX);if(Math.abs(a-b)<2)return;recZoom=[drag.base+Math.min(a,b),drag.base+Math.max(a,b)+1];rankHover=-1;rankDraw();});
recCanvas.addEventListener('pointercancel',()=>{recDrag=null;});
function recResetZoom(){recZoom=null;rankHover=-1;rankDraw();}recCanvas.addEventListener('dblclick',recResetZoom);recEl('rec-zoom-reset').onclick=recResetZoom;
// Personal notes use the collector's existing date/code revision store.
recEl('rec-note').onclick=async()=>{if(!rankCode)return;const target={day:recData.day,code:rankCode,name:rankStocks.find(s=>s.code===rankCode)?.name},key=target.day+'|'+target.code;try{const data=await recApi('/api/notes?day='+target.day);recNoteTarget=target;const note=data.notes?.[target.code];recRevision=note?.revision||'';recEl('rec-note-title').textContent=target.name+' · '+target.day;recEl('rec-note-text').value=recDrafts.get(key)??note?.text??'';
 const reason=data.reasons?.infostock?.items?.[target.code]||data.reasons?.reviewed?.items?.[target.code],context=recEl('rec-note-context');context.textContent='자동 상승 이유: '+(reason?.reason||'해당 날짜 확인 자료 없음')+'\n영웅문 메모 (읽기 전용):\n'+(data.hero4?.[target.code]||'없음');if(reason?.url)context.append(document.createTextNode('\n'),recLink(reason.url,'상승 이유 원문'));for(const news of data.reasons?.news?.items?.[target.code]||[])context.append(document.createTextNode('\n'),recLink(news.url,news.title+' · '+(news.office||'')+' '+(news.at||'')));recEl('rec-note-status').textContent='';recEl('rec-note-dialog').showModal();}catch(e){recError(e);}};
recEl('rec-note-text').oninput=()=>{if(recNoteTarget)recDrafts.set(recNoteTarget.day+'|'+recNoteTarget.code,recEl('rec-note-text').value);};
recEl('rec-note-save').onclick=async()=>{if(recNoteSaving||!recNoteTarget)return;recNoteSaving=true;recEl('rec-note-save').disabled=true;try{const text=recEl('rec-note-text').value;const result=await recApi('/api/notes',{...recNoteTarget,text,revision:recRevision});recRevision=result.note?.revision||recRevision;recDrafts.delete(recNoteTarget.day+'|'+recNoteTarget.code);recEl('rec-note-status').textContent='저장했습니다.';}catch(e){recEl('rec-note-status').textContent=e.message;}finally{recNoteSaving=false;recEl('rec-note-save').disabled=false;}};
recEl('rec-note-close').onclick=()=>recEl('rec-note-dialog').close();
recRefresh().catch(recError);setInterval(()=>recRefresh().catch(recError),10000);
