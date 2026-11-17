'use strict';
// Synthetic market data only; no request reaches the collector or Kiwoom.
const assert=require('node:assert/strict'),path=require('node:path');
let pw;try{pw=require('playwright');}catch{pw=require(path.join(path.dirname(process.execPath),'../node_modules/playwright'));}
(async()=>{
 const browser=await pw.chromium.launch({headless:true,...(process.env.COLLECTOR_BROWSER_EXE?{executablePath:process.env.COLLECTOR_BROWSER_EXE}:{})});
 try{
  for(const pagePath of ['/','/observations']){
   const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],chartRequests=[];
   let saved=[],writes=0;
   const day='2026-11-16',stock={code:'123456',name:'수집안된종목',market:'코넥스'};
   page.on('pageerror',e=>{errors.push(e.message);console.log('pageerror',e.message);});
   await page.addInitScript(()=>localStorage.setItem('collector-hero-chart','off'));
   await page.route('**/*',async route=>{
    const request=route.request(),u=new URL(request.url()),p=u.pathname;
    if(!p.startsWith('/api/')){
     const file=p==='/'?'index.html':p==='/observations'?'observations.html':path.basename(p);
     return route.fulfill({path:path.join(__dirname,'web',file)});
    }
    let data={};
    if(p==='/api/status')data={identity:'fixture',now:day+'T15:00:00+09:00',credentials:true,token:'fixture',state:{message:'fixture'},catalog:[]};
    else if(p==='/api/observations'){
     if(request.method()==='POST'){
      const body=request.postDataJSON();assert.equal(body.source,'search');assert.equal(body.code,stock.code);writes++;
      saved=[{...stock,source:'search',source_label:'종목 검색',source_day:day,added_at:day+'T15:00:00+09:00'}];
      data={created:true,stock:saved[0]};
     }else data={stocks:saved,day,token:'fixture'};
    }else if(p==='/api/stock-search')data={stocks:[{...stock,observed:saved.length>0}],day,master_day:day,token:'fixture'};
    else if(p==='/api/chart'){
     chartRequests.push(Object.fromEntries(u.searchParams));
     const frame=u.searchParams.get('frame');
     data={day,frame,stock,kind:'preview',fetched_at:day+'T15:00:00+09:00',chart_notice:'fixture chart',bars:Array.from({length:30},(_,i)=>({ts:frame.startsWith('minute')?day+` 09:${String(i).padStart(2,'0')}:00`:`2026-10-${String(i+1).padStart(2,'0')}`,open:100+i,high:103+i,low:99+i,close:102+i,volume:100+i}))};
    }else if(p==='/api/hero-targets')data={targets:[],preferred:'off',diagnostic:{state:'ready'}};
    else if(p==='/api/watchlists')data={groups:[]};
    else if(p==='/api/stock-profiles')data={profiles:{}};
    else if(p==='/api/themes')data={days:[],record:null};
    else if(p==='/api/stock-memo')data={day,code:stock.code,name:stock.name,note:'',evidence:[]};
    else if(p==='/api/notes')data={notes:{},infostock:{items:{}},hero4:{}};
    else if(request.method()==='POST')assert.equal(p,'/api/open','unexpected write '+p);
    await route.fulfill({json:data});
   });
   await page.goto('http://collector.test'+pagePath,{timeout:15000});
   assert.equal(await page.locator(pagePath==='/'?'#search':'#observation-search').count(),1,(await page.content()).slice(0,600));
   const input=page.locator(pagePath==='/'?'#search':'#observation-search');
   await input.fill(stock.name);
   await page.getByRole('button',{name:stock.name+' 차트 보기',exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('#chart-empty')?.style.display==='none'||document.querySelector('#rank-notice')?.textContent==='fixture chart');
   assert.equal(writes,0,'preview must not save observations');
   assert.equal(chartRequests.at(-1).source,'search');assert.equal(chartRequests.at(-1).code,stock.code);
   // Background list refresh must not replace the market-search chart.
   if(pagePath==='/observations')await page.evaluate(()=>loadObservations());
   else await page.evaluate(()=>refresh());
   await page.locator(pagePath==='/'?'#chart-frame':'#rank-frame').selectOption('month');
   await page.waitForFunction(()=>document.querySelector('#chart-empty')?.style.display==='none'||document.querySelector('#rank-notice')?.textContent==='fixture chart');
   assert.equal(chartRequests.at(-1).frame,'month');assert.equal(chartRequests.at(-1).source,'search');
   await page.locator('#observe-stock').click();
   await page.waitForFunction(()=>document.querySelector('#observe-stock').textContent.includes('담김'));
   assert.equal(writes,1);
   await page.reload();
   await page.waitForTimeout(100);
   if(pagePath==='/observations')assert.equal(await page.locator('#rows tr[data-code="123456"]').count(),1);
   await page.setViewportSize({width:430,height:900});
   await input.fill(stock.name);
   await page.getByRole('button',{name:stock.name+' 차트 보기',exact:true}).waitFor();
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'narrow layout overflow');
   assert.deepEqual(errors,[],pagePath+' page errors');
   console.log('PASS',pagePath,'uncollected search → chart → observation, frame change, reload, narrow layout');
   await page.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
