'use strict';
// Isolated, read-only public transcript worker. Never attaches to the user's browser.
const path=require('path'),fs=require('fs');
let pw;try{pw=require('playwright');}catch{pw=require(path.join(path.dirname(process.execPath),'../node_modules/playwright'));}
async function main(){
 const url=new URL(process.argv[2]);
 if(url.protocol!=='https:'||url.hostname!=='www.youtube.com'||url.pathname!=='/watch'||!/^[-\w]{11}$/.test(url.searchParams.get('v')||''))throw Error('공개 영상 주소 오류');
 const candidates=[process.env['ProgramFiles(x86)'],process.env.ProgramFiles,process.env.LOCALAPPDATA].filter(Boolean).map(p=>path.join(p,'Microsoft/Edge/Application/msedge.exe'));
 const executablePath=candidates.find(p=>fs.existsSync(p));if(!executablePath)throw Error('Edge 실행 파일 확인 필요');
 const browser=await pw.chromium.launch({headless:true,executablePath,args:['--mute-audio','--disable-background-networking']});
 try{
  const page=await browser.newPage({locale:'ko-KR'});page.setDefaultTimeout(12000);
  await page.route('**/*',route=>route.request().resourceType()==='media'||new URL(route.request().url()).hostname.endsWith('.googlevideo.com')?route.abort():route.continue());
  await page.goto(url.href,{waitUntil:'domcontentloaded',timeout:25000});
  // No media file is downloaded for extraction. Only the displayed transcript is read.
  await page.locator('video').evaluateAll(es=>es.forEach(e=>e.pause()));
  const expand=page.locator('#description-inline-expander #expand');await expand.first().waitFor({state:'visible'});await expand.first().click();
  const show=page.getByRole('button',{name:/스크립트 표시|Show transcript/i});await show.first().click();
  const rows=page.getByRole('button',{name:/^(?:\d+분|\d+초)/});await rows.first().waitFor({state:'attached',timeout:15000});
  const segments=await rows.evaluateAll(es=>es.slice(0,4000).map(e=>e.textContent.trim()));
  const lines=segments.map(raw=>{const t=raw.match(/^(\d+):(\d{2})/);return t?{offset:Number(t[1])*60+Number(t[2]),text:raw.replace(/^\d+:\d{2}(?:\d+분(?:\s*\d+초)?|\d+초)/,'').trim()}:null;}).filter(s=>s&&s.text&&Number.isFinite(s.offset));
  if(!lines.length)throw Error('공개 브라우저 스크립트 응답 없음');
  process.stdout.write(JSON.stringify({lines}));
 }finally{await browser.close();}
}
main().catch(error=>{process.stdout.write(JSON.stringify({error:'공개 브라우저 스크립트 확인 불가',detail:String(error.message).split('\n')[0].slice(0,160)}));process.exitCode=1;});
