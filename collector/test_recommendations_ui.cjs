'use strict';
// Read-only local UI test. Synthetic API fixtures never write collector data.
const assert=require('node:assert/strict'),path=require('node:path');
let pw;try{pw=require('playwright');}catch{pw=require(path.join(path.dirname(process.execPath),'../node_modules/playwright'));}
(async()=>{
 const browser=await pw.chromium.launch({headless:true,...(process.env.COLLECTOR_BROWSER_EXE?{executablePath:process.env.COLLECTOR_BROWSER_EXE}:{})});
 try{
 const page=await browser.newPage({viewport:{width:1415,height:910}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const record=(kind,code)=>({id:code,code,name:'검증종목',classification:kind,broadcaster:'표본 방송',url:'https://example.test/source',date_basis:'원문 명시',time_basis:'미확인'});
 let fail=false;
 await page.route('**/*',async route=>{
  const u=new URL(route.request().url());assert.equal(route.request().method(),'GET','UI test must not send writes');
  if(!u.pathname.startsWith('/api/')){const name=u.pathname==='/recommendations'?'recommendations.html':path.basename(u.pathname);return route.fulfill({path:path.join(__dirname,'web',name)});}
  if(u.pathname==='/api/stock-profiles'){await new Promise(r=>setTimeout(r,1500));return route.fulfill({json:{profiles:{}}});}
  if(u.pathname==='/api/recommendations'){
   if(fail)return route.fulfill({status:503,json:{error:'표본 통신 실패'}});
   const day=u.searchParams.get('day')||'2026-11-08';return route.fulfill({json:{day,days:['2026-11-08','2026-11-06'],records:day==='2026-11-08'?[record('mention','000001')]:[record('new','000002')],enabled:true,state:{message:'표본 수집 완료',busy:false},ledger:{documents:{sample:{status:'확인 필요',message:'공개 자막 응답 없음'}},sources:{},total_documents:1},sources:{programs:[],channels:[]}}});
  }
  if(u.pathname==='/api/hero-targets')return route.fulfill({json:{targets:[],preferred:'',diagnostic:{state:'ready'}}});
  return route.fulfill({json:{bars:[],token:'test',profiles:{}}});
 });
 await page.goto((process.env.COLLECTOR_TEST_URL||'http://127.0.0.1:8766')+'/recommendations');
 await page.waitForFunction(()=>document.querySelectorAll('#rows tr').length===1,{},{timeout:5000}).catch(async e=>{console.error({errors,status:await page.locator('#rec-status').textContent()});throw e;});
 assert.equal(await page.locator('#rec-kind').inputValue(),'');
 assert.match(await page.locator('#rec-summary').textContent(),/単純|단순 언급 1/);
 assert.match(await page.locator('#rec-health').textContent(),/자막 확인 필요 1/);
 assert.equal(await page.locator('.rank-list').evaluate(e=>e.scrollWidth>e.clientWidth),false);
 await page.locator('#rec-kind').selectOption('new');assert.equal(await page.locator('#rows tr').count(),0);
 assert.equal(await page.locator('#rec-empty').isVisible(),true);
 await page.locator('#rec-latest-new').click();await page.waitForFunction(()=>!document.querySelector('#rec-latest-new').disabled);
 assert.equal(await page.locator('#rec-day').inputValue(),'2026-11-06');assert.equal(await page.locator('#rows tr').count(),1);
 await page.setViewportSize({width:720,height:910});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 fail=true;await page.locator('#rec-refresh').click();await page.waitForFunction(()=>document.querySelector('#rec-status').textContent.includes('표본 통신 실패'));
 assert.equal(await page.locator('#rows tr').count(),1);assert.equal(errors.length,0,errors.join('\n'));
 console.log('PASS: default all, caption warning, profiles delay, new/date navigation, empty/filter state, responsive overflow, API failure preserves list; no writes');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});



