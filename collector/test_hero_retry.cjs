const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function harness(replies){let calls=0;const ctx=vm.createContext({window:{},document:{getElementById:()=>null},setTimeout:fn=>fn(),fetch:async(url)=>{calls++;const item=replies.shift();if(!item)throw Error('unexpected fetch '+url);return {ok:item.status===undefined||item.status<400,status:item.status||200,json:async()=>item.data}}});vm.runInContext(fs.readFileSync(path.join(__dirname,'web/hero-reconnect.js'),'utf8'),ctx);return {send:ctx.window.collectorHeroSend,calls:()=>calls};}
(async()=>{
 let h=harness([{data:{ok:false,message:'영웅문 응답 실패'}},{data:{ok:true,message:'전송'}}]);assert((await h.send('005930','10','token')).ok);assert.equal(h.calls(),2);
 h=harness([{data:{ok:false,message:'입력칸 확인 필요'}},{data:{ok:false,message:'입력칸 확인 필요'}}]);assert.equal((await h.send('005930','10','token')).ok,false);assert.equal(h.calls(),2);
 h=harness([{data:{ok:false,message:'0311 계좌 재확인 필요'}}]);await h.send('005930','10','token');assert.equal(h.calls(),1);
 h=harness([]);assert.equal(await h.send('005930','10','token',()=>false),null);assert.equal(h.calls(),0);
 h=harness([{status:403,data:{}},{data:{token:'new'}},{data:{ok:true}}]);assert((await h.send('005930','10','old')).ok);assert.equal(h.calls(),3);
 for(const file of ['app.js','volume.js','themes.js','rank-chart.js','investors.js']){const source=fs.readFileSync(path.join(__dirname,'web',file),'utf8');assert(source.includes('window.collectorHeroSend('),file);assert(!source.includes("fetch('/api/hero-link'"),file);}
 console.log('PASS: bounded 2 attempts, no trust-error retry, cancellation, token refresh and all tab callers.');
})().catch(e=>{console.error(e);process.exitCode=1});
