'use strict';
// Every request is intercepted. No real notes, recommendations, or Kiwoom calls.
const assert=require('node:assert/strict'),path=require('node:path');
let pw;try{pw=require('playwright');}catch{pw=require(path.join(path.dirname(process.execPath),'../node_modules/playwright'));}
(async()=>{
 const browser=await pw.chromium.launch({headless:true,...(process.env.COLLECTOR_BROWSER_EXE?{executablePath:process.env.COLLECTOR_BROWSER_EXE}:{})});
 const pages=['/','/volume','/volume-top','/amount-top','/themes','/investors','/recommendations','/observations'];
 let note={day:'2026-11-24',code:'005930',text:'[관찰 메모]\n기존 메모',revision:'initial'},writes=0,manual=0;
 try{for(const pagePath of pages){
  const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];let conflict=false,latestCalls=0;
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>localStorage.setItem('collector-hero-chart','off'));
  await page.route('**/*',async route=>{
   const req=route.request(),u=new URL(req.url()),p=u.pathname;
   if(!p.startsWith('/api/')){
    const file=p==='/'?'index.html':p.slice(1).includes('.')?path.basename(p):p.slice(1)+'.html';
    if(file.endsWith('.js')&&!['stock-tools.js',...(pagePath==='/recommendations'?['recommendations.js','rank-chart.js','chart-fast.js']:[])].includes(file))return route.fulfill({body:'',contentType:'text/javascript'});
    return route.fulfill({path:path.join(__dirname,'web',file)});
   }
   let data={token:'fixture',stocks:[],profiles:{},bars:[],targets:[],preferred:'off',diagnostic:{state:'ready'}};
   if(p==='/api/notes/latest'){latestCalls++;data={token:'fixture',day:'2026-11-25',notes:note.text?{[note.code]:note}:{}};}
   if(p==='/api/stock-memo')data={note:u.searchParams.get('code')===note.code&&u.searchParams.get('day')===note.day?note:{},history:[],news:[]};
   if(p==='/api/notes'&&req.method()==='POST'){
    if(conflict)return route.fulfill({status:409,json:{error:'다른 창에서 메모가 변경됐습니다.'}});
    const b=req.postDataJSON();assert.equal(b.revision,note.revision);note={...b,revision:'saved-'+(++writes)};data={note};
   }
   if(p==='/api/stock-search')data={stocks:[{code:'000660',name:'전체시장검색종목'}],day:'2026-11-25'};
   if(p==='/api/recommendations/manual'){assert.deepEqual(req.postDataJSON(),{code:'000660'});manual++;data={created:true,record:{recommended_date:'2026-11-25'}};}
   if(p==='/api/recommendations'){
    const day=u.searchParams.get('day')||'2026-11-24';data={day,days:['2026-11-25','2026-11-24'],token:'fixture',records:[{id:'fixture',code:'005930',name:'공통검증종목',classification:'new',broadcaster:'직접 등록',recommended_date:day,url:'manual:fixture'}],enabled:true,state:{message:'fixture'},ledger:{documents:{},sources:{}},sources:{programs:[],channels:[]}};
   }
   assert.ok(req.method()==='GET'||['/api/notes','/api/recommendations/manual'].includes(p),'unexpected write '+p);
   return route.fulfill({json:data});
  });
  await page.goto('http://collector.test'+pagePath);
  if(pagePath!=='/recommendations')await page.evaluate(()=>{const host=document.querySelector('main'),row=document.createElement('div');row.dataset.stockCode='005930';row.innerHTML='<span class="stock-name-text">공통검증종목</span>';row.addEventListener('click',()=>window.unwantedChartClick=true);host.prepend(row);});
  const toggle=page.locator('.collector-memo-toggle[data-code="005930"]').first();await toggle.waitFor();
  await page.waitForFunction(()=>document.querySelector('.collector-latest-memo')?.textContent!=='메모 작성');
  if(pagePath==='/')assert.equal(await page.locator('.collector-latest-memo').first().textContent(),'기존 메모','preview must show content, not a heading');
  const before=latestCalls;await page.waitForTimeout(350);assert.ok(latestCalls-before<=1,'memo observer request loop');
  await toggle.click();const dialog=page.locator('#collector-common-memo');await page.waitForFunction(()=>!document.querySelector('#collector-common-memo textarea').disabled);
  assert.equal(await page.evaluate(()=>!!window.unwantedChartClick),false,'memo must not select/send stock');
  assert.equal(await dialog.locator('input').inputValue(),'2026-11-24');
  await dialog.locator('textarea').fill(pagePath+' 최신 메모 <script>안전한 텍스트</script>');await dialog.getByRole('button',{name:'메모 저장',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#collector-common-memo [role=status]').textContent==='저장했습니다.');
  assert.match(await page.locator('.collector-latest-memo').first().textContent(),/최신 메모/);
  conflict=true;await dialog.locator('textarea').fill('충돌해도 유지할 내용');await dialog.getByRole('button',{name:'메모 저장',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#collector-common-memo [role=status]').textContent.includes('다른 창'));
  assert.equal(await dialog.locator('textarea').inputValue(),'충돌해도 유지할 내용');
  await dialog.getByRole('button',{name:'닫기',exact:true}).click();
  if(pagePath==='/recommendations'){
   await page.getByRole('searchbox',{name:'직접 등록할 종목 검색'}).fill('전체시장');
   await page.locator('.rec-manual-results button').click();await page.locator('#rec-manual button[type=submit]').click();
   await page.waitForFunction(()=>document.querySelector('#rec-day').value==='2026-11-25');
   assert.equal(manual,1);await page.waitForFunction(()=>document.querySelector('#collector-common-memo input').value==='2026-11-25');
   assert.match(await dialog.locator('h2').textContent(),/전체시장검색종목/);
  }
  await page.setViewportSize({width:430,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,pagePath+' narrow overflow');
  assert.deepEqual(errors,[],pagePath+' browser errors');console.log('PASS',pagePath,'common memo/latest/save/conflict, no chart click, mobile');await page.close();
 }}finally{await browser.close();}
 assert.equal(writes,8);console.log('PASS manual full-market pick uses server input day, 8 shared memo writes');
})().catch(e=>{console.error(e);process.exitCode=1;});
