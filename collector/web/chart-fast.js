/* Shared bounded display cache. Never changes chart calculations or order paths. */
(()=>{
 const cache=new Map(),warmAt=new Map();let active=null,warmTimer;
 const keyOf=p=>{const u=new URL(p,location.origin);u.searchParams.delete('prefetch');u.searchParams.delete('fast');u.searchParams.delete('async');u.searchParams.sort();return u.pathname+'?'+u.searchParams;};
 const store=(key,data)=>{if(!data.pending&&!data.refreshing&&data.bars?.length){cache.delete(key);cache.set(key,{at:Date.now(),data});while(cache.size>96)cache.delete(cache.keys().next().value);}};
 const response=data=>new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
 function warm(path,key){clearTimeout(warmTimer);if(Date.now()-(warmAt.get(key)||0)<60000)return;
  warmTimer=setTimeout(async()=>{if(document.hidden||active?.key!==key)return;warmAt.set(key,Date.now());while(warmAt.size>96)warmAt.delete(warmAt.keys().next().value);
   const u=new URL(path,location.origin),selected=u.searchParams.get('frame');
   for(const frame of ['week','day','minute','minute3','minute5']){if(frame===selected)continue;if(active?.key!==key||document.hidden)return;
    u.searchParams.set('frame',frame);u.searchParams.set('prefetch','1');u.searchParams.set('fast','1');u.searchParams.set('async','1');
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),4000);
    try{const r=await fetch(u.pathname+'?'+u.searchParams,{signal:controller.signal});if(r.ok)store(keyOf(u.href),await r.json());}catch{}finally{clearTimeout(timer);}
   }
  },350);
 }
 window.collectorChartFetch=async(path,options={})=>{
  const key=keyOf(path),u=new URL(path,location.origin),ttl=u.searchParams.get('live')==='1'?10000:60000;
  active?.controller.abort();const controller=new AbortController(),request={key,controller};active=request;
  const abort=()=>controller.abort();options.signal?.addEventListener('abort',abort,{once:true});if(options.signal?.aborted)controller.abort();
  let timedOut=false;
  try{
   const saved=cache.get(key);if(saved&&Date.now()-saved.at<ttl&&options.cache!=='reload'){if(controller.signal.aborted)throw new DOMException('Aborted','AbortError');warm(path,key);return response(saved.data);}
   const until=Date.now()+40000;
   while(true){const timer=setTimeout(()=>{timedOut=true;controller.abort();},8000);let r,data;
    try{r=await fetch(path,{...options,signal:controller.signal});if(!r.ok)return r;data=await r.json();}finally{clearTimeout(timer);}
    if(controller.signal.aborted)throw new DOMException('Aborted','AbortError');
    if(!data.pending){store(key,data);warm(path,key);return response(data);}
    if(Date.now()>=until)throw Error('첫 차트 조회가 지연됩니다. 키움 연결 상태를 확인해주세요.');
    await new Promise((resolve,reject)=>{const stop=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};const timer=setTimeout(()=>{controller.signal.removeEventListener('abort',stop);resolve();},200);controller.signal.addEventListener('abort',stop,{once:true});});
   }
  }catch(error){if(timedOut)throw Error('수집기 차트 응답이 지연됩니다. 연결 상태를 확인한 뒤 다시 선택해주세요.');throw error;}finally{options.signal?.removeEventListener('abort',abort);}
 };
})();
