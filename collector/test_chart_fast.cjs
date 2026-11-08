const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(__dirname+'/web/chart-fast.js','utf8');
function setup(fetcher){const sandbox={window:{},location:{origin:'http://localhost'},document:{hidden:false},URL,Response,DOMException,AbortController,Date,Map,fetch:fetcher,setTimeout:(fn,ms)=>ms===350?0:setTimeout(fn,ms),clearTimeout};vm.runInNewContext(source,sandbox);return sandbox.window.collectorChartFetch;}
const path=(code='005930',frame='minute',day='2026-10-30')=>`/api/chart?code=${code}&frame=${frame}&day=${day}&source=volume-top&live=0&fast=1&async=1`;
const ok=p=>new Response(JSON.stringify({stock:{code:new URL(p,'http://localhost').searchParams.get('code')},bars:[{close:1}]}));
(async()=>{
 let calls=0;const load=setup(async p=>{calls++;return ok(p);});
 await load(path());await load(path());assert.equal(calls,1,'repeat view uses cache');
 await load(path('000660'));await load(path('005930','day'));await load(path('005930','minute','2026-10-29'));assert.equal(calls,4,'date/code/frame caches remain isolated');
 let refreshCalls=0;const refreshing=setup(async()=>{refreshCalls++;return new Response(JSON.stringify({bars:[1],refreshing:true}));});await refreshing(path());await refreshing(path());assert.equal(refreshCalls,2,'refreshing snapshots never freeze background refresh in cache');
 let pendingCalls=0;const pending=setup(async()=>new Response(JSON.stringify(++pendingCalls===1?{pending:true,bars:[]}:{bars:[1]})));assert.equal((await(await pending(path())).json()).bars.length,1);assert.equal(pendingCalls,2,'first uncached chart polls without exposing pending as a chart');
 let firstStarted;const started=new Promise(r=>firstStarted=r);const racing=setup(async(p,o)=>{if(p.includes('005930')){firstStarted();await new Promise((resolve,reject)=>o.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true}));}return ok(p);});
 const old=racing(path()).then(()=>null,e=>e.name);await started;const newest=await(await racing(path('000660'))).json();assert.equal(await old,'AbortError');assert.equal(newest.stock.code,'000660','latest selection wins');
 let failedCalls=0;const failing=setup(async()=>{failedCalls++;return new Response('{}',{status:503});});await failing(path());await failing(path());assert.equal(failedCalls,2,'failures are not cached');
 console.log('PASS: cache reuse; date/code/frame isolation; refresh progress; cold polling; obsolete request cancellation; error recovery');
})().catch(e=>{console.error(e);process.exitCode=1;});
