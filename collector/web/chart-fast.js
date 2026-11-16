/* Shared bounded display cache. Never changes chart calculations or order paths. */
(()=>{
 const cache=new Map();let active=null;
 const keyOf=p=>{const u=new URL(p,location.origin);for(const key of ['prefetch','fast','async','reload'])u.searchParams.delete(key);u.searchParams.sort();return u.pathname+'?'+u.searchParams;};
 const store=(key,data)=>{if(!data.pending&&!data.refreshing&&!data.refresh_error&&data.bars?.length){cache.delete(key);cache.set(key,{at:Date.now(),data});while(cache.size>96)cache.delete(cache.keys().next().value);}};
 const response=data=>new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
 window.collectorChartFetch=async(path,options={})=>{
  const key=keyOf(path),u=new URL(path,location.origin),ttl=u.searchParams.get('live')==='1'?10000:60000;
  active?.controller.abort();const controller=new AbortController(),request={key,controller};active=request;
  const abort=()=>controller.abort();options.signal?.addEventListener('abort',abort,{once:true});if(options.signal?.aborted)controller.abort();
  let timedOut=false;
  try{
   if(options.cache==='reload')cache.delete(key);
   const saved=cache.get(key);if(saved&&Date.now()-saved.at<ttl&&options.cache!=='reload'){if(controller.signal.aborted)throw new DOMException('Aborted','AbortError');return response(saved.data);}
   const until=Date.now()+40000;
   const forced=new URL(path,location.origin);
   if(options.cache==='reload')forced.searchParams.set('reload','1');
   let requestPath=options.cache==='reload'?forced.pathname+'?'+forced.searchParams:path;
   while(true){const timer=setTimeout(()=>{timedOut=true;controller.abort();},8000);let r,data;
    try{r=await fetch(requestPath,{...options,signal:controller.signal});if(!r.ok)return r;data=await r.json();}finally{clearTimeout(timer);}
    requestPath=path;
    if(controller.signal.aborted)throw new DOMException('Aborted','AbortError');
    if(!data.pending){store(key,data);return response(data);}
    if(Date.now()>=until)throw Error('첫 차트 조회가 지연됩니다. 키움 연결 상태를 확인해주세요.');
    await new Promise((resolve,reject)=>{const stop=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};const timer=setTimeout(()=>{controller.signal.removeEventListener('abort',stop);resolve();},450);controller.signal.addEventListener('abort',stop,{once:true});});
   }
  }catch(error){if(timedOut)throw Error('수집기 차트 응답이 지연됩니다. 연결 상태를 확인한 뒤 다시 선택해주세요.');throw error;}finally{options.signal?.removeEventListener('abort',abort);}
 };
})();
