'use strict';
let notesDay='', stockNotes={}, dayReasons={}, hero4Memos={}, notesRequest=0, notesPending=false, memoTarget=null, memoSaving=false, memoOpenRequest=0;
let memoHoverCode='', memoHideTimer=null;
const memoDrafts=new Map();
const memoKey=(day,symbol)=>day+'|'+symbol;
const displayedStocks=()=>displayedEntries().filter(s=>s.type!=='heading');

async function loadNotes(day){
  if(notesPending&&notesDay===day)return;
  if(notesDay!==day){notesDay=day;stockNotes={};dayReasons={};hideMemoPreview()}
  const version=++notesRequest;notesPending=true;
  try{const result=await api('/api/notes?'+new URLSearchParams({day}));if(version!==notesRequest)return;stockNotes=result.notes;dayReasons=result.reasons||{};hero4Memos=result.hero4||{};decorateNotes()}
  catch(e){if(version===notesRequest)$('memo-status').textContent='메모 조회 실패: '+e.message}
  finally{if(version===notesRequest)notesPending=false}
}
function decorateNotes(){
  for(const button of $('stocks').querySelectorAll('.memo-mark')){
    const note=stockNotes[button.dataset.code];button.classList.toggle('has-note',!!note?.text.trim()||!!hero4Memos[button.dataset.code]);
    button.setAttribute('aria-label',button.dataset.name+(note?.text.trim()?' 저장된 메모 보기':' 메모 작성'));
  }
  if(memoHoverCode){const button=$('stocks').querySelector(`.memo-mark[data-code="${memoHoverCode}"]`);if(button)showMemoPreview(button);else hideMemoPreview()}
}
/* Auto rise reason: Infostock article first, else today's Naver news, else 근거없음. */
function reasonBox(symbol,reasons=dayReasons,compact=false){
  const reviewed=reasons.reviewed?.items?.[symbol],info=reasons.infostock?.items?.[symbol],news=reasons.news?.items?.[symbol]||[],checked=!!reasons.news?.fetched_at;
  const box=element('div',null,'reason-box'+(compact?' compact':'')),head=element('div',null,'reason-head');
  head.append(element('b','자동 상승 사유'));box.append(head);
  if(info){
    head.append(element('span','인포스탁'+(info.limit_days?' · 상한가 '+info.limit_days+'일':''),'reason-tag'));
    box.append(element('p',info.reason,'reason-text'));
  }else if(reviewed){
    head.append(element('span','출처 분석 요약','reason-tag news'));
    box.append(element('p',reviewed.reason,'reason-text'));
    const link=element('a',reviewed.source+' · '+reviewed.published);
    link.href=reviewed.url;link.target='_blank';link.rel='noopener noreferrer';
    box.append(link,element('small',reviewed.basis,'reason-text muted'));
  }else if(news.length){
    head.append(element('span','관련 뉴스 · 네이버','reason-tag news'));
    const list=element('ul',null,'reason-news');
    for(const n of news){const li=element('li'),link=element('a',n.title);link.href=n.url;link.target='_blank';link.rel='noopener noreferrer';li.append(link,element('small',n.office+' '+n.at));list.append(li)}
    box.append(list);
  }else{
    head.append(element('span',checked?'확인 완료':'확인 전','reason-tag none'));
    box.append(element('p',checked?'해당 날짜 뉴스에서 상승 사유 미확인':'18시 이후 네이버 뉴스를 자동 확인합니다. 영웅문에서 인포스탁 기사를 열면 사유가 자동으로 들어옵니다.','reason-text muted'));
  }
  return box;
}
/* Hero4 종목 메모 (read only, this year's lines). */
function hero4Box(symbol,compact=false){
  const text=hero4Memos[symbol];if(!text)return '';
  const box=element('div',null,'hero4-box'+(compact?' compact':'')),head=element('div',null,'reason-head');
  head.append(element('b','영웅문 메모'),element('span','올해 · 읽기 전용','reason-tag hero4'));
  box.append(head,element('p',text,'hero4-text'));
  return box;
}
function noteMark(s){
  const button=element('button',null,'memo-mark');button.type='button';button.dataset.code=s.code;button.dataset.name=s.name;
  button.append(element('span',null,'memo-triangle'));
  button.onclick=()=>openMemo(s);
  button.onpointerenter=()=>showMemoPreview(button);button.onpointerleave=scheduleMemoHide;
  button.onfocus=()=>showMemoPreview(button);button.onblur=scheduleMemoHide;
  return button;
}
function hideMemoPreview(){clearTimeout(memoHideTimer);memoHoverCode='';$('memo-preview').hidden=true}
function scheduleMemoHide(){clearTimeout(memoHideTimer);memoHideTimer=setTimeout(hideMemoPreview,200)}
function showMemoPreview(button){
  if($('memo-dialog').open)return;
  clearTimeout(memoHideTimer);memoHoverCode=button.dataset.code;
  const note=stockNotes[memoHoverCode],box=$('memo-preview');
  box.replaceChildren(element('strong',button.dataset.name+' · '+notesDay),reasonBox(memoHoverCode,dayReasons,true),hero4Box(memoHoverCode,true),element('div',note?.text.trim()?note.text:'메모가 없습니다. 삼각형을 클릭하면 상승 이유·뉴스·개인 메모를 작성할 수 있습니다.','memo-preview-text'),element('small',note?.updated_at?'저장 '+note.updated_at.slice(0,19).replace('T',' ')+' · 클릭하여 편집':'클릭하여 메모 작성'));
  box.hidden=false;const r=button.getBoundingClientRect(),width=box.offsetWidth,height=box.offsetHeight;
  box.style.left=Math.max(8,Math.min(r.right+9,window.innerWidth-width-8))+'px';
  box.style.top=Math.max(8,Math.min(r.top,window.innerHeight-height-8))+'px';
}
function keepMemoDraft(){
  if(!memoTarget)return;
  const key=memoKey(memoTarget.day,memoTarget.code),text=$('memo-text').value;
  if(text===memoTarget.savedText)memoDrafts.delete(key);else memoDrafts.set(key,{text,revision:memoTarget.revision,savedText:memoTarget.savedText});
}
async function openMemo(stock){
  hideMemoPreview();
  const day=choice.split('|')[0],openVersion=++memoOpenRequest;
  // Opening always reads the latest saved version. Never edit a stale copy silently.
  try{
    const result=await api('/api/notes?'+new URLSearchParams({day}));
    if(openVersion!==memoOpenRequest)return;
    const note=result.notes[stock.code]||{},draft=memoDrafts.get(memoKey(day,stock.code));
    memoTarget={day,code:stock.code,name:stock.name,revision:draft?.revision??note.revision??'',savedText:draft?.savedText??note.text??''};
    $('memo-title').textContent=stock.name+' · 종목 메모';$('memo-date').textContent=day+' / '+stock.code+' · 날짜별 보관';
    hero4Memos=result.hero4||hero4Memos;
    $('memo-reason').replaceChildren(reasonBox(stock.code,result.reasons||{}),hero4Box(stock.code));
    $('memo-text').value=draft?.text??note.text??'';
    $('memo-status').textContent=draft?'작성 중인 내용을 복원했습니다. 저장 버튼을 눌러 보관하세요.':note.updated_at?'마지막 저장 '+note.updated_at.slice(0,19).replace('T',' ')+' KST':'상승 이유·출처·개인 의견을 자유롭게 기록하세요.';
    if(day===notesDay){stockNotes=result.notes;dayReasons=result.reasons||{};decorateNotes()}
    $('memo-dialog').showModal();$('memo-text').focus();
  }catch(e){toast('메모를 열지 못했습니다: '+e.message)}
}
function closeMemo(){if(memoSaving)return;keepMemoDraft();$('memo-dialog').close();memoTarget=null}
async function saveMemo(){
  if(!memoTarget||memoSaving)return;
  const target={...memoTarget},text=$('memo-text').value;
  memoSaving=true;$('memo-save').disabled=true;$('memo-close').disabled=true;$('memo-reload').disabled=true;$('memo-text').readOnly=true;
  $('memo-status').textContent='저장 중…';
  try{
    const result=await post('/api/notes',{day:target.day,code:target.code,name:target.name,revision:target.revision,text});
    memoDrafts.delete(memoKey(target.day,target.code));memoTarget={...target,revision:result.note.revision,savedText:text};
    if(notesDay===target.day){stockNotes[target.code]=result.note;decorateNotes()}
    $('memo-status').textContent='저장 완료 · '+result.note.updated_at.slice(0,19).replace('T',' ')+' KST';
  }catch(e){keepMemoDraft();$('memo-status').textContent=e.message}
  finally{memoSaving=false;$('memo-save').disabled=false;$('memo-close').disabled=false;$('memo-reload').disabled=false;$('memo-text').readOnly=false}
}
$('memo-save').onclick=saveMemo;$('memo-close').onclick=closeMemo;
$('memo-text').oninput=()=>{$('memo-status').textContent='작성 중 · 저장 버튼을 눌러 보관하세요.';keepMemoDraft()};
$('memo-dialog').addEventListener('cancel',event=>{event.preventDefault();closeMemo()});
$('memo-reload').onclick=async()=>{
  if(!memoTarget||memoSaving)return;
  if($('memo-text').value!==memoTarget.savedText&&!window.confirm('작성 중 내용을 저장된 메모로 바꿀까요? 필요한 내용은 먼저 복사하세요.'))return;
  const target={...memoTarget};memoDrafts.delete(memoKey(target.day,target.code));$('memo-dialog').close();memoTarget=null;
  // Keep the original date even if the underlying dashboard refreshed.
  try{const result=await api('/api/notes?'+new URLSearchParams({day:target.day}));const note=result.notes[target.code]||{};
    memoTarget={...target,revision:note.revision||'',savedText:note.text||''};$('memo-text').value=note.text||'';$('memo-status').textContent='저장된 메모를 다시 읽었습니다.';$('memo-dialog').showModal();$('memo-text').focus();
  }catch(e){toast(e.message)}
};
$('reason-paste').onclick=()=>{const day=choice.split('|')[0];if(!day)return toast('날짜를 먼저 선택하세요.');$('reason-date').textContent=day+' 자료에 입력';$('reason-status').textContent=dayReasons.infostock?'이미 입력됨 · '+Object.keys(dayReasons.infostock.items).length+'종목 ('+(dayReasons.infostock.source==='hero4'?'영웅문 자동':'붙여넣기')+' '+dayReasons.infostock.saved_at.slice(11,16)+') · 다시 넣으면 교체됩니다.':'';$('reason-text').value='';$('reason-dialog').showModal();$('reason-text').focus()};
$('reason-close').onclick=()=>$('reason-dialog').close();
$('reason-save').onclick=async()=>{
  const day=choice.split('|')[0],text=$('reason-text').value;
  if(!text.trim())return void($('reason-status').textContent='기사 본문을 붙여넣어 주세요.');
  $('reason-save').disabled=true;$('reason-status').textContent='분석 중…';
  try{const result=await post('/api/reasons',{day,text});if(day===notesDay){dayReasons=result.reasons;decorateNotes()}$('reason-status').textContent=result.count+'종목 사유를 입력했습니다.';$('reason-text').value=''}
  catch(e){$('reason-status').textContent=e.message}
  finally{$('reason-save').disabled=false}
};
$('memo-preview').onpointerenter=()=>clearTimeout(memoHideTimer);$('memo-preview').onpointerleave=scheduleMemoHide;
$('stocks').addEventListener('scroll',hideMemoPreview);window.addEventListener('resize',hideMemoPreview);window.addEventListener('scroll',hideMemoPreview);
document.addEventListener('keydown',event=>{
  if(!['ArrowDown','ArrowUp'].includes(event.key)||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey||event.isComposing||$('memo-dialog').open)return;
  if(event.target.closest('input,textarea,select,dialog,[contenteditable="true"]'))return;
  const rows=displayedStocks();if(!rows.length)return;
  event.preventDefault();hideMemoPreview();
  const current=rows.findIndex(s=>s.code===code),direction=event.key==='ArrowDown'?1:-1;
  const i=current<0?(direction>0?0:rows.length-1):Math.max(0,Math.min(rows.length-1,current+direction));
  if(rows[i].code!==code){chooseCurrentStock(rows[i].code)}
  const row=$('stocks').querySelector(`[data-stock-code="${rows[i].code}"]`),button=row?.querySelector('.stock');
  if(row){const list=$('stocks'),top=row.getBoundingClientRect().top-list.getBoundingClientRect().top;if(top<0)list.scrollTop+=top;else if(top+row.offsetHeight>list.clientHeight)list.scrollTop+=top+row.offsetHeight-list.clientHeight;button.focus({preventScroll:true})}
});
window.addEventListener('beforeunload',event=>{keepMemoDraft();if(memoDrafts.size){event.preventDefault();event.returnValue=''}});
