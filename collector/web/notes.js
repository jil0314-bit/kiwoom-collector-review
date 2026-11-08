'use strict';
let notesLoadedDay='', notesDay='', stockNotes={}, dayReasons={}, hero4Memos={}, notesRequest=0, notesPending=false, memoTarget=null, memoSaving=false, memoOpenRequest=0;
let memoHoverCode='', memoHideTimer=null;
const memoDrafts=new Map();
const memoKey=(day,symbol)=>day+'|'+symbol;
const displayedStocks=()=>displayedEntries().filter(s=>s.type!=='heading');

async function loadNotes(day){
  if(notesPending&&notesDay===day)return;
  if(notesDay!==day){notesLoadedDay='';notesDay=day;stockNotes={};dayReasons={};hideMemoPreview()}
  const version=++notesRequest;notesPending=true;
  try{const result=await api('/api/notes?'+new URLSearchParams({day}));if(version!==notesRequest||day!==choice.split('|')[0]||result.day!==day)return;stockNotes=result.notes;dayReasons=result.reasons||{};hero4Memos=result.hero4||{};notesLoadedDay=day;decorateNotes()}
  catch(e){if(version===notesRequest)$('memo-status').textContent='메모 조회 실패: '+e.message}
  finally{if(version===notesRequest){notesPending=false;renderInlineMemo()}}
}
function decorateNotes(){
  renderInlineMemo();
  for(const button of $('stocks').querySelectorAll('.memo-mark')){
    const note=stockNotes[button.dataset.code];button.classList.toggle('has-note',!!note?.text.trim()||!!hero4Memos[button.dataset.code]||!!dayReasons.infostock?.items?.[button.dataset.code]||!!dayReasons.news?.items?.[button.dataset.code]?.length||!!dayReasons.history?.[button.dataset.code]?.length);
    button.setAttribute('aria-label',button.dataset.name+(note?.text.trim()?' 저장된 메모 보기':' 메모 작성'));
  }
  if(memoHoverCode){const button=$('stocks').querySelector(`.memo-mark[data-code="${memoHoverCode}"]`);if(button)showMemoPreview(button);else hideMemoPreview()}
}
/* Presentation only: combine stored evidence without rewriting source or personal notes. */
function conciseReason(text){
  text=String(text||'').replace(/\s*(?:기사\s*사유\s*)?출처\s*[:：][\s\S]*$/,'').trim();
  return /확인\s*불가|사유.{0,20}미확인|구체적.{0,20}미확인|추측하여 기재하지|근거없음|사유가 없습니다/.test(text)?'확인불가':text;
}
function reasonKey(text){return conciseReason(text).normalize('NFKC').replace(/[\s\p{P}\p{S}]/gu,'').toLowerCase()}
function heroMemoEntries(text){
  const entries=[];let item=null;
  for(const line of String(text||'').split(/\r?\n/)){
    const full=line.match(/^\s*(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\s*(.*)$/);
    const short=line.match(/^\s*(\d{1,2})\/(\d{1,2})\/(\d{2}|20\d{2})\s+(.*)$/);
    let day='',body=line;
    if(full){day=full[1]+'-'+full[2].padStart(2,'0')+'-'+full[3].padStart(2,'0');body=full[4]}
    else if(short){day=(short[3].length===2?'20'+short[3]:short[3])+'-'+short[1].padStart(2,'0')+'-'+short[2].padStart(2,'0');body=short[4]}
    if(day||!item){item={day,text:body,source:'영웅문 메모',url:''};entries.push(item)}
    else item.text+='\n'+body;
  }
  return entries;
}
function memoEvidenceEntries(symbol,reasons=dayReasons,day=notesDay){
  const entries=[],info=reasons.infostock?.items?.[symbol],reviewed=reasons.reviewed?.items?.[symbol];
  if(info)entries.push({day,text:info.reason,source:'인포스탁',url:[info.source,reasons.infostock.source].find(url=>/^https?:\/\//.test(url||''))||''});
  else if(reviewed)entries.push({day,text:reviewed.reason,source:reviewed.source||'확인 자료',url:reviewed.url||''});
  for(const n of reasons.news?.items?.[symbol]||[])entries.push({day,text:n.title,source:'관련 뉴스 · '+(n.office||'뉴스'),url:n.url||''});
  for(const h of reasons.history?.[symbol]||[])entries.push({day:h.day,text:h.reason,source:h.source,url:h.url||''});
  entries.push(...heroMemoEntries(hero4Memos[symbol]));
  entries.sort((a,b)=>(b.day||'').localeCompare(a.day||''));
  const seen=new Set();
  return entries.map(e=>({...e,text:conciseReason(e.text)})).filter(e=>{const key=(e.day||'')+'|'+reasonKey(e.text);if(!reasonKey(e.text)||seen.has(key))return false;seen.add(key);return true});
}
function reasonBox(symbol,reasons=dayReasons,compact=false,day=notesDay){
  const box=element('div',null,'reason-box'+(compact?' compact':''));
  const entries=memoEvidenceEntries(symbol,reasons,day);
  if(!entries.length){box.append(element('p','확인불가','reason-text'));return box}
  for(const entry of entries){
    const row=element('div',null,'memo-evidence-entry'),head=element('div',null,'reason-head');
    head.append(element('span',entry.day||'날짜 미기재','reason-tag'));
    if(entry.text!=='확인불가')head.append(element('small',entry.source));
    row.append(head,element('p',entry.text,'reason-text'));
    if(/^https?:\/\//.test(entry.url)){const link=element('a','출처');link.href=entry.url;link.target='_blank';link.rel='noopener noreferrer';row.append(link)}
    box.append(row);
  }
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
  if(notesDay!==choice.split('|')[0]||notesLoadedDay!==notesDay){hideMemoPreview();return}
  if($('memo-dialog').open)return;
  clearTimeout(memoHideTimer);memoHoverCode=button.dataset.code;
  const note=stockNotes[memoHoverCode],box=$('memo-preview');
  box.replaceChildren(element('strong',button.dataset.name+' · '+notesDay),reasonBox(memoHoverCode,dayReasons,true),element('div',note?.text.trim()?note.text:'메모가 없습니다. 삼각형을 클릭하면 상승 이유·뉴스·개인 메모를 작성할 수 있습니다.','memo-preview-text'),element('small',note?.updated_at?'저장 '+note.updated_at.slice(0,19).replace('T',' ')+' · 클릭하여 편집':'클릭하여 메모 작성'));
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
    if(openVersion!==memoOpenRequest||day!==choice.split('|')[0]||result.day!==day)return;
    const note=result.notes[stock.code]||{},draft=memoDrafts.get(memoKey(day,stock.code));
    memoTarget={day,code:stock.code,name:stock.name,revision:draft?.revision??note.revision??'',savedText:draft?.savedText??note.text??''};
    $('memo-title').textContent=stock.name+' · 종목 메모';$('memo-date').textContent=day+' / '+stock.code+' · 날짜별 보관';
    hero4Memos=result.hero4||hero4Memos;
    $('memo-reason').replaceChildren(reasonBox(stock.code,result.reasons||{},false,day));
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
    hero4Memos=result.hero4||hero4Memos;$('memo-reason').replaceChildren(reasonBox(target.code,result.reasons||{},false,target.day));
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

// Expanded editor uses the existing date/symbol notes endpoint and revision protection.
let inlineMemoTarget=null, inlineMemoSaving=false, inlineReasonSignature='';
const inlineMemoDrafts=new Map();
function keepInlineMemoDraft(){
  if(!inlineMemoTarget)return;
  const value=$('inline-memo-text').value,key=memoKey(inlineMemoTarget.day,inlineMemoTarget.code);
  if(value===inlineMemoTarget.savedText)inlineMemoDrafts.delete(key);
  else inlineMemoDrafts.set(key,{...inlineMemoTarget,text:value});
}
function renderInlineMemo(){
  if(!$('inline-memo')||inlineMemoSaving)return;
  const stock=currentStocks().find(s=>s.code===code),day=choice.split('|')[0];
  const ready=!!stock&&notesDay===day&&notesLoadedDay===day;
  if(!stock){
    keepInlineMemoDraft();inlineMemoTarget=null;inlineReasonSignature='';
    $('inline-memo-title').textContent='종목 메모 · 상승 사유';$('inline-memo-date').textContent='';
    $('inline-memo-reasons').replaceChildren();$('inline-memo-text').value='';
  }else if(ready){
    const key=memoKey(day,code),note=stockNotes[code]||{};
    if(!inlineMemoTarget||memoKey(inlineMemoTarget.day,inlineMemoTarget.code)!==key){
      keepInlineMemoDraft();const draft=inlineMemoDrafts.get(key);
      inlineMemoTarget={day,code,name:stock.name,revision:draft?.revision??note.revision??'',savedText:draft?.savedText??note.text??''};
      $('inline-memo-text').value=draft?.text??note.text??'';
      $('inline-memo-status').textContent=draft?'작성 중 · 저장 버튼을 눌러주세요.':note.updated_at?'저장 '+note.updated_at.slice(0,19).replace('T',' '):'개인 메모가 없습니다.';
    }else if($('inline-memo-text').value===inlineMemoTarget.savedText&&note.revision!==inlineMemoTarget.revision){
      inlineMemoTarget={day,code,name:stock.name,revision:note.revision||'',savedText:note.text||''};
      $('inline-memo-text').value=note.text||'';
    }
    $('inline-memo-title').textContent=stock.name+' · 메모 / 상승 사유';
    $('inline-memo-date').textContent=day+' · '+code;
    const signature=JSON.stringify([key,dayReasons,hero4Memos[code]]);
    if(signature!==inlineReasonSignature){
      inlineReasonSignature=signature;
      $('inline-memo-reasons').replaceChildren(reasonBox(code,dayReasons,true));
    }
  }else{
    keepInlineMemoDraft();inlineMemoTarget=null;inlineReasonSignature='';
    $('inline-memo-title').textContent=stock.name+' · 메모 / 상승 사유';
    $('inline-memo-date').textContent=day+' · '+code;
    $('inline-memo-reasons').replaceChildren();$('inline-memo-text').value='';
    $('inline-memo-status').textContent='메모 불러오는 중…';
  }
  for(const id of ['inline-memo-text','inline-memo-save','inline-memo-reload'])$(id).disabled=!ready;
}
$('inline-memo-text').oninput=()=>{keepInlineMemoDraft();$('inline-memo-status').textContent='작성 중 · 저장 버튼을 눌러주세요.'};
$('inline-memo-save').onclick=async()=>{
  if(!inlineMemoTarget||inlineMemoSaving)return;
  const target={...inlineMemoTarget},text=$('inline-memo-text').value;
  keepInlineMemoDraft();inlineMemoSaving=true;
  for(const id of ['inline-memo-save','inline-memo-reload'])$(id).disabled=true;
  $('inline-memo-text').readOnly=true;$('inline-memo-status').textContent='저장 중…';
  try{
    const result=await post('/api/notes',{day:target.day,code:target.code,name:target.name,revision:target.revision,text});
    inlineMemoDrafts.delete(memoKey(target.day,target.code));
    inlineMemoTarget={...target,revision:result.note.revision,savedText:text};
    if(notesDay===target.day)stockNotes[target.code]=result.note;
    $('inline-memo-status').textContent='저장 완료 · '+result.note.updated_at.slice(0,19).replace('T',' ');
    decorateNotes();
  }catch(e){$('inline-memo-status').textContent=e.message}
  finally{inlineMemoSaving=false;$('inline-memo-text').readOnly=false;renderInlineMemo()}
};
$('inline-memo-reload').onclick=async()=>{
  if(!inlineMemoTarget||inlineMemoSaving)return;
  if($('inline-memo-text').value!==inlineMemoTarget.savedText&&!window.confirm('작성 중 내용을 저장된 메모로 바꿀까요?'))return;
  const target={...inlineMemoTarget};
  try{
    const result=await api('/api/notes?'+new URLSearchParams({day:target.day}));
    if(!inlineMemoTarget||memoKey(inlineMemoTarget.day,inlineMemoTarget.code)!==memoKey(target.day,target.code))return;
    inlineMemoDrafts.delete(memoKey(target.day,target.code));
    stockNotes=result.notes;dayReasons=result.reasons||{};hero4Memos=result.hero4||{};
    inlineMemoTarget=null;$('inline-memo-text').value='';renderInlineMemo();
    $('inline-memo-status').textContent='저장된 메모를 다시 읽었습니다.';
  }catch(e){$('inline-memo-status').textContent=e.message}
};
