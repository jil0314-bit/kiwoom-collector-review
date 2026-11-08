// Two display-only attempts across every tab; never retry an obsolete selection.
window.collectorHeroSend=async function(symbol,chart,token,current=()=>true){
 for(let attempt=0;attempt<2;attempt++){
  if(!current())return null;
  let response=await fetch('/api/hero-link',{method:'POST',headers:{'Content-Type':'application/json','X-Collector-Token':token},body:JSON.stringify({code:symbol,chart})});
  if(response.status===403){
   token=(await(await fetch('/api/status')).json()).token;
   if(!current())return null;
   response=await fetch('/api/hero-link',{method:'POST',headers:{'Content-Type':'application/json','X-Collector-Token':token},body:JSON.stringify({code:symbol,chart})});
  }
  const data=await response.json();if(!current())return null;
  if(!response.ok)throw Error(data.error||'영웅문 연동 실패');
  if(data.ok||attempt===1||!/입력칸|응답 실패|입력 확인|Enter 전달/.test(data.message||''))return data;
  await new Promise(resolve=>setTimeout(resolve,180));
 }
};
// Explicit account confirmation restores trust after a Hero4 restart.
(()=>{
 const select=document.getElementById('hero-target')||document.getElementById('rank-hero-target');
 if(!select)return;
 const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='0311 계좌 확인 후 재연결';button.hidden=true;button.style.display='none';
 const notice=document.createElement('span');notice.setAttribute('role','status');
 select.parentElement.append(button,notice);
 async function refresh(){try{const r=await fetch('/api/hero-targets');if(!r.ok)return;const d=await r.json();
  const issue=d.diagnostic&&d.diagnostic.state!=='ready';button.hidden=!issue||select.value==='off';button.style.display=button.hidden?'none':'';notice.textContent=issue&&select.value!=='off'?d.diagnostic.message:'';
 }catch{notice.textContent='영웅문 연결 상태 조회 실패';}}
 button.onclick=async()=>{
  if(!window.confirm('화면에 펼친 영웅문 0600이 끝자리 0311 계좌인지 직접 확인하셨나요? 확인한 경우에만 현재 창에 다시 연결합니다.'))return;
  button.disabled=true;
  try{const status=await(await fetch('/api/status')).json();const r=await fetch('/api/hero-confirm',{method:'POST',headers:{'Content-Type':'application/json','X-Collector-Token':status.token},body:JSON.stringify({account_suffix:'0311'})});const d=await r.json();notice.textContent=d.message||d.error;if(d.ok)location.reload();}
  catch{notice.textContent='재연결 요청 실패';}finally{button.disabled=false;}
 };
 refresh();setInterval(refresh,30000);
})();
