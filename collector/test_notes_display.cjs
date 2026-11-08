const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const nodes=new Map();
function node(tag='div',text='',className=''){
 return {tag,textContent:text||'',className,children:[],value:'',hidden:true,disabled:false,dataset:{},classList:{toggle(){}},append(...children){this.children.push(...children)},replaceChildren(...children){this.children=children},addEventListener(){},querySelectorAll(){return []},focus(){},showModal(){this.open=true},close(){this.open=false}};
}
const context=vm.createContext({console,URLSearchParams,setTimeout,clearTimeout,
 choice:'2026-11-02|latest',code:'000001',currentStocks:()=>[],displayedEntries:()=>[],
 $:id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id)},element:node,
 api:async()=>{throw Error('unexpected API call')},post:async()=>{throw Error('unexpected write')},
 document:{addEventListener(){}},window:{addEventListener(){},confirm(){return true}},toast(){}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'web/notes.js'),'utf8'),context);
const run=code=>vm.runInContext(code,context);
let checks=0;
function check(fn){fn();checks++}
(async()=>{
 // Same wording across dates must remain visible for each date; same-date duplicates collapse.
 context.fixture={infostock:{items:{'000001':{reason:'수주 소식에 급등',source:'https://example.test/source'}}},history:[ ]};
 context.fixture.history={'000001':[{day:'2026-11-01',reason:'수주 소식에 급등',source:'인포스탁',url:''}]};
 run("notesDay='2026-11-02';hero4Memos={'000001':'2026-11-02 수주 소식에 급등'}");
 check(()=>assert.equal(run("memoEvidenceEntries('000001',fixture).length"),2));
 check(()=>assert.equal(run("memoEvidenceEntries('000001',fixture)[0].url"),'https://example.test/source'));
 check(()=>assert.equal(run("memoEvidenceEntries('000001',fixture,'2026-10-30').find(x=>x.source==='인포스탁'&&x.url).day"),'2026-10-30'));
 // All saved reasons in the requested five-day archive survive presentation exactly.
 let items=0;
 for(const day of ['2026-11-02','2026-11-03','2026-11-04','2026-11-05','2026-11-06']){
  context.fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'data/reasons',day+'.json'),'utf8'));
  context.currentDay=day;run('notesDay=currentDay;hero4Memos={};');
  for(const [code,item] of Object.entries(context.fixture.infostock.items)){
   context.symbol=code;context.reason=item.reason;
   assert(run('memoEvidenceEntries(symbol,fixture).some(x=>x.day===currentDay&&x.text===reason)'),day+'/'+code);
   items++;
  }
 }
 check(()=>assert.equal(items,151));
 // Simulate a delayed previous-date response arriving after the archive selection changed.
 run('decorateNotes=()=>{};renderInlineMemo=()=>{};');
 let complete;
 context.api=()=>new Promise(resolve=>{complete=resolve});
 context.choice='2026-11-02|latest';
 const pending=run("loadNotes('2026-11-02')");
 context.choice='2026-11-03|latest';
 complete({day:'2026-11-02',notes:{},reasons:{infostock:{items:{old:{reason:'stale'}}}}});
 await pending;
 check(()=>assert.equal(run("notesLoadedDay"),''));
 // A new reason arriving for an already-open date must replace the visible model without reload.
 context.api=async()=>({day:'2026-11-03',notes:{},reasons:{infostock:{items:{fresh:{reason:'new'}}}}});
 await run("loadNotes('2026-11-03')");
 check(()=>assert.equal(run("dayReasons.infostock.items.fresh.reason"),'new'));
 context.api=async()=>({day:'2026-11-03',notes:{},reasons:{infostock:{items:{fresh:{reason:'updated'}}}}});
 await run("loadNotes('2026-11-03')");
 check(()=>assert.equal(run("dayReasons.infostock.items.fresh.reason"),'updated'));
 // A modal response for an abandoned date must not open or show wrong-date reasons.
 context.api=()=>new Promise(resolve=>{complete=resolve});
 const modal=run("openMemo({code:'000001',name:'test'})");
 context.choice='2026-11-04|latest';
 complete({day:'2026-11-03',notes:{},reasons:{}});await modal;
 check(()=>assert.notEqual(nodes.get('memo-dialog').open,true));
 console.log('PASS',checks,'regression checks;',items,'archived reasons preserved; no network or writes.');
})().catch(error=>{console.error(error);process.exitCode=1});
