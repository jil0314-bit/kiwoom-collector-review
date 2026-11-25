'use strict';
// Synthetic responses only: shared styling, signed values, data basis and stale responses.
const assert=require('node:assert/strict'),path=require('node:path');
let pw;try{pw=require('playwright');}catch{pw=require(path.join(path.dirname(process.execPath),'../node_modules/playwright'));}
(async()=>{const browser=await pw.chromium.launch({headless:true,...(process.env.COLLECTOR_BROWSER_EXE?{executablePath:process.env.COLLECTOR_BROWSER_EXE}:{})});
try{for(const url of ['/','/volume','/volume-top','/amount-top','/themes','/investors','/recommendations','/observations']){
 const page=await browser.newPage({viewport:{width:1366,height:768}}),errors=[];let calls=0;
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{const req=route.request(),p=new URL(req.url());assert.equal(req.method(),'GET');
  if(!p.pathname.startsWith('/api/')){const name=p.pathname==='/'?'index.html':p.pathname.includes('.')?path.basename(p.pathname):p.pathname.slice(1)+'.html';if(name.endsWith('.js')&&name!=='stock-tools.js')return route.fulfill({body:'',contentType:'text/javascript'});return route.fulfill({path:path.join(__dirname,'web',name)});}
  if(p.pathname==='/api/quotes'){calls++;const codes=p.searchParams.get('codes').split(',');assert.ok(codes.length<=10,'bounded quote batch');await new Promise(r=>setTimeout(r,250));return route.fulfill({json:{quotes:Object.fromEntries(codes.map(code=>[code,{rate:code==='0039P0'?-1.23:7.25,fetched_at:'2026-11-25T09:10:00+09:00'}]))}});}
  return route.fulfill({json:{stocks:[],notes:{},day:'2026-11-25',token:'fixture'}});
 });
 await page.goto('http://collector.test'+url);
 for(const selector of ['.collector-clock-digits','.collector-clock-date'])assert.equal(await page.locator(selector).evaluate(e=>getComputedStyle(e).color),'rgb(51, 51, 51)');
 await page.evaluate(()=>{const row=document.createElement('div');row.dataset.stockCode='005930';row.id='rate-fixture';const label=document.createElement('span');label.className='stock-name-text';label.textContent='검증종목';row.append(label);document.querySelector('main').prepend(row);window.collectorSetStockRate(label,'005930',-3.14,'2026-11-24 저장 기준');});
 const badge=page.locator('#rate-fixture .collector-price-rate');assert.equal(await badge.textContent(),'-3.14%');assert.equal(await badge.evaluate(e=>getComputedStyle(e).color),'rgb(0, 87, 231)');
 await page.waitForFunction(()=>document.querySelector('#rate-fixture .collector-memo-toggle'));
 assert.equal(await page.locator('#rate-fixture .collector-memo-toggle').getAttribute('data-name'),'검증종목');
 for(const [value,expected] of [[2.5,'+2.50%'],[0,'+0.00%'],[-0.005,'-0.01%'],[-0.001,'+0.00%'],[null,'등락률 미확인']]){assert.equal(await page.evaluate(v=>collectorRateText(v),value),expected);}
 const title=page.locator('#selected-name,#rank-title,#flow-chart-name').first();
 await title.evaluate(e=>collectorSetChartTitle(e,{name:'차트종목',code:'005930',rate:99},{live:true,quote:{rate:-2.22,price:12345},day:'2026-11-25'},'2026-11-24'));
 assert.equal(await title.locator('.collector-price-rate').textContent(),'-2.22%');assert.equal(await title.locator('.collector-price-rate').evaluate(e=>getComputedStyle(e).color),'rgb(0, 87, 231)');
 await title.evaluate(e=>collectorSetChartTitle(e,{name:'다른날종목',rate:99},{live:false,day:'2026-11-23',quote:{rate:8}},'2026-11-24'));
 assert.equal(await title.locator('.collector-price-rate').textContent(),'등락률 미확인','must not mix current quote or another archive day');
 await title.evaluate(e=>collectorSetChartTitle(e,{name:'과거종목',rate:-4},{live:false,day:'2026-11-24'},'2026-11-24'));
 assert.equal(await title.locator('.collector-price-rate').textContent(),'-4.00%');
 await page.evaluate(()=>collectorSetStockRate(document.querySelector('#rate-fixture .stock-name-text'),'005930',null,'현재 조회',true));
 await page.waitForTimeout(190);
 await page.evaluate(()=>collectorSetStockRate(document.querySelector('#rate-fixture .stock-name-text'),'0039P0',null,'현재 조회',true));
 await page.waitForFunction(()=>document.querySelector('#rate-fixture .collector-price-rate').textContent==='-1.23%');
 await page.evaluate(()=>collectorSetStockRate(document.querySelector('#rate-fixture .stock-name-text'),'0039P0',2.5,'저장 기준',false));assert.equal(await badge.textContent(),'+2.50%');assert.equal(await badge.evaluate(e=>getComputedStyle(e).color),'rgb(230, 0, 18)');
 assert.equal(await badge.getAttribute('data-current'),null);assert.ok(calls<=2,'no quote request loop');
 await page.setViewportSize({width:430,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 assert.deepEqual(errors,[]);console.log('PASS',url,'signed red/blue rates, neutral index clock, memo coexistence, date isolation, stale quote, mobile');await page.close();
}}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
