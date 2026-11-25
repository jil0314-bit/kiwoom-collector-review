'use strict';
const assert=require('node:assert/strict'),path=require('node:path');
let pw;try{pw=require('playwright');}catch{pw=require(path.join(path.dirname(process.execPath),'../node_modules/playwright'));}
(async()=>{const browser=await pw.chromium.launch({headless:true,...(process.env.COLLECTOR_BROWSER_EXE?{executablePath:process.env.COLLECTOR_BROWSER_EXE}:{})});
try{for(const url of ['/','/volume','/volume-top','/amount-top','/themes','/investors','/recommendations','/observations']){
 const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];let direction='up';
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{const req=route.request(),p=new URL(req.url()).pathname;assert.equal(req.method(),'GET');
  if(!p.startsWith('/api/')){const name=p==='/'?'index.html':p.includes('.')?path.basename(p):p.slice(1)+'.html';if(name.endsWith('.js')&&name!=='stock-tools.js')return route.fulfill({body:'',contentType:'text/javascript'});return route.fulfill({path:path.join(__dirname,'web',name)});}
  if(p==='/api/market-index')return direction==='failure'?route.fulfill({status:503,json:{error:'fixture'}}):route.fulfill({json:{name:'KOSPI',ready:true,direction,rate:direction==='up'?1:direction==='down'?-1:0,fetched_at:'2026-11-25T14:30:00+09:00'}});
  return route.fulfill({json:{stocks:[],notes:{},day:'2026-11-25',token:'fixture'}});
 });
 await page.goto('http://collector.test'+url);
 const clock=page.locator('#clock'),digits=page.locator('.collector-clock-digits');
 for(const [state,colour] of [['up','rgb(230, 0, 18)'],['down','rgb(0, 87, 231)'],['flat','rgb(51, 51, 51)'],['failure','rgb(51, 51, 51)'],['up','rgb(230, 0, 18)']]){
  direction=state;await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
  await page.waitForFunction(s=>document.querySelector('#clock').dataset.market===(s==='failure'?'unknown':s),state);
  assert.equal(await digits.evaluate(e=>getComputedStyle(e).color),colour);
 }
 const dimensions=await clock.evaluate(e=>{const d=e.querySelector('.collector-clock-digits');return {width:e.getBoundingClientRect().width,natural:parseFloat(getComputedStyle(d).width),height:e.getBoundingClientRect().height,font:parseFloat(getComputedStyle(d).fontSize)};});
 assert.ok(Math.abs(dimensions.width/dimensions.natural-1.5)<0.01,JSON.stringify(dimensions));assert.equal(dimensions.font,43.2);assert.ok(dimensions.height<62);
 await page.setViewportSize({width:430,height:900});await page.waitForTimeout(50);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 assert.deepEqual(errors,[]);console.log('PASS',url,'KOSPI up/down/flat/failure/recovery, width 1.5x, unchanged font/height, mobile');await page.close();
}}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
