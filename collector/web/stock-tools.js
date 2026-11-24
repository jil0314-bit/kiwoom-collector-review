'use strict';

// Korean public holidays, verified 2026-11-14. UI filtering only, not a trading calendar.
// KASI: https://astro.kasi.re.kr/kor/life/post/calendarData?search_year=2026 (and 2027)
// 2026 Labor/Constitution Day update: https://www.mpm.go.kr/mpm/comm/newsPress/newsPressRelease/?cntId=4250&mode=view
const collectorHolidayDates={
  2026:new Set('01-01 02-16 02-17 02-18 03-01 03-02 05-01 05-05 05-24 05-25 06-03 06-06 07-17 08-15 08-17 09-24 09-25 09-26 10-03 10-05 10-09 12-25'.split(' ')),
  2027:new Set('01-01 02-06 02-07 02-08 02-09 03-01 05-01 05-03 05-05 05-13 06-06 07-17 07-19 08-15 08-16 09-14 09-15 09-16 10-03 10-04 10-09 10-11 12-25 12-27'.split(' ')),
};
const collectorIsCalendarDay=day=>/^\d{4}-\d{2}-\d{2}$/.test(day);
window.collectorIsDisplayDay=day=>{
  if(!collectorIsCalendarDay(day))return false;
  const date=new Date(day+'T12:00:00Z');
  return ![0,6].includes(date.getUTCDay())&&!collectorHolidayDates[day.slice(0,4)]?.has(day.slice(5));
};
const collectorDayLabel=day=>day.slice(5).replace('-','/')+' ('+'일월화수목금토'[new Date(day+'T12:00:00Z').getUTCDay()]+')';

// Presentation adapter: reuse each page's original date selector and change handler.
window.collectorRenderDateTabs = (nav, options, selected, choose, isDisplayDay = window.collectorIsDisplayDay) => {
  nav.classList.add('collector-date-tabs');
  nav.setAttribute('aria-label','보관 날짜 선택');
  const byDay=new Map();
  for(const option of options)if(isDisplayDay(option.day)&&!byDay.has(option.day))byDay.set(option.day,option);
  const available=[...byDay.keys()].sort().reverse();
  const dates=new Set(available.slice(0,20));
  const anchor=available[0]||new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul'}).format(new Date());
  const cursor=new Date(anchor+'T12:00:00Z');
  while(dates.size<20){
    if(isDisplayDay(cursor.toISOString().slice(0,10)))dates.add(cursor.toISOString().slice(0,10));
    cursor.setUTCDate(cursor.getUTCDate()-1);
  }
  const selectedOption=options.find(o=>o.value===selected);
  if(isDisplayDay(selectedOption?.day||''))dates.add(selectedOption.day);
  const make=(text,value,disabled,title)=>{
    const b=document.createElement('button');b.type='button';b.textContent=text;b.disabled=disabled;
    b.title=title;b.dataset.value=value;b.setAttribute('aria-label',title);
    b.className='collector-date'+(value===selected&&!disabled?' active':'');
    b.setAttribute('aria-pressed',String(value===selected&&!disabled));
    if(!disabled)b.onclick=()=>choose(value);
    return b;
  };
  const buttons=[...dates].sort().reverse().map(day=>{
    const option=day===selectedOption?.day?selectedOption:byDay.get(day);
    return make(collectorDayLabel(day),option?.value||day,!option,day+' · '+(option?.label||'자료 없음'));
  });
  const all=options.find(o=>o.value===''&&o.label.includes('전체'));
  if(all)buttons.unshift(make('전체','',false,'전체 등록일'));
  nav.replaceChildren(...buttons);
};

document.addEventListener('DOMContentLoaded',()=>{
  const select=document.querySelector('#archive,#day,#rec-day,#observation-day');
  if(!select)return;
  const isDisplayDay=select.id==='rec-day'?collectorIsCalendarDay:window.collectorIsDisplayDay;
  const intro=document.querySelector('main .collector-intro');
  if(!intro)return;
  const panel=document.createElement('section');panel.className='collector-dates';
  const nav=document.createElement('nav');
  const details=document.createElement('details');details.className='collector-date-more';
  const summary=document.createElement('summary');summary.textContent='전체 날짜 · 저장본 선택';
  const oldLabel=select.closest('label');
  // Keep the archive's heading label: it also labels the stock list.
  if(oldLabel)oldLabel.hidden=true;
  if(select.id==='day')document.querySelector('label[for="day"]')?.setAttribute('hidden','');
  select.setAttribute('aria-label','전체 보관 날짜 및 저장본');
  details.append(summary,select);panel.append(nav,details);intro.after(panel);
  let previous='';
  const sync=()=>{
    const original=select.value;
    for(const option of Array.from(select.options)){
      const day=option.value.slice(0,10);
      if(!collectorIsCalendarDay(day))continue;
      if(!isDisplayDay(day)){option.remove();continue;}
      const weekday='일월화수목금토'[new Date(day+'T12:00:00Z').getUTCDay()];
      if(!option.textContent.includes(' ('+weekday+')'))option.textContent=option.textContent.includes(day)?option.textContent.replace(day,day+' ('+weekday+')'):option.textContent+' ('+weekday+')';
    }
    if(original!==select.value&&select.options.length)queueMicrotask(()=>select.dispatchEvent(new Event('change',{bubbles:true})));
    const options=Array.from(select.options,o=>({value:o.value,day:o.value.slice(0,10),label:o.textContent}));
    const signature=JSON.stringify([options,select.value]);
    if(signature===previous)return;previous=signature;
    window.collectorRenderDateTabs(nav,options,select.value,value=>{
      select.value=value;select.dispatchEvent(new Event('change',{bubbles:true}));sync();
    },isDisplayDay);
  };
  new MutationObserver(sync).observe(select,{childList:true,subtree:true,attributes:true});
  select.addEventListener('change',sync);sync();
  // Some existing page actions assign select.value without changing its options.
  setInterval(()=>{if(!document.hidden)sync();},1000);
});

document.addEventListener('DOMContentLoaded',()=>{
  const themeWorkspace=document.querySelector('.th-workspace');
  if(themeWorkspace){
    const article=themeWorkspace.querySelector('article'),bottom=document.querySelector('.th-bottom');
    const timeline=bottom?.querySelector('div.th-panel'),help=bottom?.querySelector('details.th-panel');
    if(timeline){timeline.classList.add('theme-chart-timeline');article.append(timeline);}
    if(help){help.classList.add('theme-mini-help');article.querySelector('.chart-head').append(help);}
    if(bottom&&!bottom.children.length)bottom.remove();
  }
  // Match list scrollports to the independent chart panel, never to the viewport.
  const workspace=document.querySelector('.rank-workspace,.investor-workspace,.th-workspace');
  if(!workspace)return;
  const chart=workspace.querySelector('.rank-chart,.flow-chart-panel')||workspace.querySelector(':scope > article');
  const list=workspace.querySelector('.rank-list,.flow-panels,.th-list');
  if(!chart||!list)return;
  let scheduled=false;
  const fit=()=>{
    scheduled=false;
    const style=getComputedStyle(workspace);
    const sideBySide=style.display==='grid'&&style.gridTemplateColumns.trim().split(/\s+/).length>1;
    let available=Math.ceil(chart.getBoundingClientRect().height);
    const table=list.matches('.rank-list')?list.querySelector('table'):null;
    // A date with only a few saved records must not become a giant empty box.
    if(table)available=Math.min(available,table.scrollHeight+2);
    const height=sideBySide?available+'px':'';
    if(list.style.height!==height)list.style.height=height;
    list.classList.toggle('chart-height-list',sideBySide);
  };
  const queue=()=>{if(!scheduled){scheduled=true;requestAnimationFrame(fit);}};
  new ResizeObserver(queue).observe(chart);
  new MutationObserver(queue).observe(list,{childList:true,subtree:true,characterData:true});
  window.addEventListener('resize',queue);queue();
});

const collectorClock = document.querySelector('.collector-header #clock');
if (collectorClock) {
  const formatClock = new Intl.DateTimeFormat('ko-KR', {
    timeZone:'Asia/Seoul', month:'2-digit',day:'2-digit',
    hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23',
  });
  const digits = document.createElement('span');
  digits.className = 'collector-clock-digits';
  const date = document.createElement('span');
  date.className = 'collector-clock-date';
  collectorClock.replaceChildren(digits, date);
  const updateClock = () => {
    const now = new Date();
    const parts = Object.fromEntries(formatClock.formatToParts(now).map(({type,value}) => [type,value]));
    collectorClock.dateTime = now.toISOString();
    digits.textContent = [parts.hour, parts.minute, parts.second].join(':');
    date.textContent = `${parts.month}월 ${parts.day}일 KST`;
    collectorClock.setAttribute('aria-label', `한국 시각 ${date.textContent} ${digits.textContent}`);
  };
  updateClock();
  setInterval(updateClock,1000);
}

function formatWon(value, unit = 1) {
  if (value == null || value === '' || !Number.isFinite(Number(value))) return '미확인';
  let won = Math.round(Math.abs(Number(value)) * unit);
  const parts = [];
  for (const [scale, suffix] of [[1e12, '조'], [1e8, '억'], [1e4, '만원'], [1, '원']]) {
    const amount = Math.floor(won / scale);
    if (!amount) continue;
    parts.push(amount.toLocaleString('ko-KR') + suffix);
    won %= scale;
  }
  return parts.length ? (Number(value) < 0 ? '−' : '') + parts.join(' ') : '0원';
}

function chartRangeStatus(count, range) {
  const requested = Number(range);
  return requested > count && count ? `최근 ${requested}봉 요청 · 자료 ${count}봉 표시` : `${count}봉 표시`;
}

const chartToolbar = document.querySelector('[data-chart-toolbar]');
if (chartToolbar) {
  const group = chartToolbar.dataset.chartToolbar;
  const isRank = group === 'rank';
  const isFlow = group === 'flow';
  const id = {
    hero: isRank ? 'rank-hero-target' : 'hero-target',
    source: isRank ? 'rank-live' : isFlow ? 'flow-chart-source' : 'chart-source',
    frame: isRank ? 'rank-frame' : isFlow ? 'flow-frame' : 'chart-frame',
    range: isRank ? 'rank-range' : isFlow ? 'flow-range' : 'range',
  };
  chartToolbar.classList.add('collector-chart-toolbar');
  chartToolbar.innerHTML = `
    <div class="collector-chart-selects">
      <label>기준 <select id="${id.source}"><option value="archive">선택 날짜</option><option value="live" selected>현재 차트 · 15초 갱신</option></select></label>
      <label>주기 <select id="${id.frame}"><option value="minute">1분봉</option><option value="minute3">3분봉</option><option value="minute5">5분봉</option><option value="day">일봉</option><option value="week">주봉</option><option value="month">월봉</option></select></label>
      <label>표시 <select id="${id.range}"><option value="60">최근 60봉</option><option value="120">최근 120봉</option><option value="240">최근 240봉</option><option value="360">최근 360봉</option><option value="480">최근 480봉</option><option value="${isRank ? '0' : 'all'}" selected>전체</option><option value="custom" disabled>선택 구간</option></select></label>
      <label>영웅문 <select id="${id.hero}"><option value="">0600 자동 선택</option><option value="off">연동 끄기</option></select></label>
    </div>
    <div class="collector-chart-actions">
      <button id="chart-reload" type="button" class="secondary" disabled>차트 다시 조회</button>
      <button id="zoom-reset" type="button" class="secondary" disabled>확대 초기화</button>
      <button id="observe-stock" type="button" disabled>＋ 관찰종목 담기</button>
      <details class="chart-exports"><summary>저장</summary><div>
        <button id="chart-export-csv" type="button" class="secondary" disabled>데이터 CSV</button>
        <button id="chart-export-png" type="button" class="secondary" disabled>이미지 PNG</button>
      </div></details>
      <small id="stock-tool-feedback" class="stock-tool-feedback" role="status"></small>
    </div>`;
  if (isFlow) {
    document.getElementById(id.frame).value = 'day';
    document.getElementById(id.range).value = '240';
  }
  if (document.body.dataset.sharedViewer === '1') {
    document.getElementById(id.source).querySelector('[value=live]').disabled = true;
    document.getElementById(id.source).value = 'archive';  // 공유 보기는 현재 차트를 쓸 수 없으므로 선택 날짜로 둔다
  }
}

function bindChartExports(readChart, reload, redraw) {
  const csv = document.getElementById('chart-export-csv');
  const png = document.getElementById('chart-export-png');
  const refresh = document.getElementById('chart-reload');
  refresh.onclick = reload;
  document.addEventListener('DOMContentLoaded', () => mountChartDrawing(readChart, redraw), {once:true});
  function download(url, name) {
    const link = document.createElement('a');
    link.href = url;
    link.download = name;
    link.click();
  }
  function getChart() {
    const {record, bars, canvas} = readChart();
    if (!record || !bars.length) return null;
    return {bars, canvas, frame:record.frame, name:`${record.stock.code}_${bars.at(-1).ts.slice(0,10)}_${record.frame}`};
  }
  csv.onclick = () => {
    const chart = getChart();
    if (!chart) return;
    const fields = ['ts','open','high','low','close','volume',
      ...chartPeriods(chart.frame).map(n => 'ma'+n).filter(key => key in chart.bars[0])];
    const text = [fields, ...chart.bars.map(bar => fields.map(key => bar[key] ?? ''))].map(row=>row.join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob(['\ufeff',text], {type:'text/csv;charset=utf-8'}));
    download(url, chart.name+'.csv');
    setTimeout(()=>URL.revokeObjectURL(url),1000);
    csv.closest('details').open = false;
  };
  png.onclick = () => {
    const chart = getChart();
    if (!chart) return;
    download(chart.canvas.toDataURL('image/png'), chart.name+'.png');
    png.closest('details').open = false;
  };
  return (selected, hasBars) => {
    refresh.disabled = !selected;
    csv.disabled = png.disabled = !hasBars;
    if (!hasBars) chartDrawingLayers.get(readChart().canvas)?.(null, null);
  };
}

const chartPeriods = frame => frame.startsWith('minute')
  ? [5,10,20,60,120,180,240,360,480]
  : [5,10,20,30,60,120,180,240,360,480];

const chartAverageColors = {5:'#ff8000',10:'#800080',20:'#008000',30:'#d63848',60:'#0000ff',120:'#174e99',180:'#b45309',240:'#364152',360:'#0e7490',480:'#9d174d'};

const chartDrawingLayers = new WeakMap();

function mountChartDrawing(readChart, redraw) {
  const {canvas} = readChart();
  const plot = canvas.closest('.chart-wrap') || canvas;
  const layout = document.createElement('div');
  layout.className = 'chart-drawing-layout';
  const toolbar = document.createElement('div');
  toolbar.className = 'chart-drawing-tools';
  toolbar.setAttribute('role', 'group');
  toolbar.setAttribute('aria-label', '차트 그리기 도구');
  const tools = [
    ['select', '↖', '봉 선택·확대'], ['horizontal', '━', '수평선'],
    ['vertical', '┃', '수직선'], ['trend', '╱', '직선추세선'],
    ['ellipse', '⬭', '타원'], ['rectangle', '▭', '사각형'],
    ['eraser', '⌫', '지우개'], ['text', 'T', '글상자'],
  ];
  const buttons = new Map(tools.map(([id, icon, label]) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = icon;
    button.title = label;
    button.setAttribute('aria-label', label);
    button.addEventListener('click', () => selectTool(id));
    toolbar.append(button);
    return [id, button];
  }));
  plot.before(layout);
  layout.append(plot, toolbar);

  const dialog = document.createElement('dialog');
  dialog.className = 'chart-drawing-dialog';
  dialog.setAttribute('aria-label', '차트 글상자');
  dialog.innerHTML = `<form method="dialog">
    <label>글상자 내용<textarea maxlength="240" rows="3" autofocus></textarea></label>
    <div><button type="submit" value="cancel" class="secondary">취소</button>
    <button type="submit" value="save">추가</button></div>
  </form>`;
  layout.after(dialog);
  const input = dialog.querySelector('textarea');
  const drawings = new Map();
  let mode = 'select', geometry, chartKey, hits = [], gesture, pendingText, drawFrame;
  const keyFor = record => record?.stock?.code && record.frame
    ? 'collector.chart-drawings.v1.' + record.stock.code + '.' + record.frame : null;
  const dragTools = new Set(['trend', 'ellipse', 'rectangle']);
  const validAnchor = anchor => typeof anchor?.ts === 'string' && Number.isFinite(anchor.price);

  function items(key) {
    if (!drawings.has(key)) {
      let saved;
      try { saved = JSON.parse(localStorage.getItem(key)); } catch {}
      drawings.set(key, Array.isArray(saved) ? saved.filter(shape => validAnchor(shape?.a)
        && (shape.type === 'text' ? typeof shape.text === 'string' : validAnchor(shape.b))) : []);
    }
    return drawings.get(key);
  }
  function save(key, shapes) {
    drawings.set(key, shapes);
    try {
      if (shapes.length) localStorage.setItem(key, JSON.stringify(shapes));
      else localStorage.removeItem(key);
    } catch {} // Keep edits available for the current page when storage is unavailable.
  }
  function queueRedraw() {
    if (drawFrame) return;
    drawFrame = requestAnimationFrame(() => { drawFrame = 0; redraw(); });
  }
  function cancelGesture() {
    if (!gesture) return;
    const {pointerId} = gesture;
    gesture = null;
    if (canvas.hasPointerCapture(pointerId)) canvas.releasePointerCapture(pointerId);
    queueRedraw();
  }
  function selectTool(next) {
    cancelGesture();
    mode = next;
    canvas.dataset.chartDrawing = next;
    for (const [id, button] of buttons) button.setAttribute('aria-pressed', String(id === next));
  }
  selectTool(mode);
  function pointFor(event) {
    const g = geometry;
    const rect = canvas.getBoundingClientRect();
    const x = (event.clientX - rect.left) * g.w / rect.width;
    const y = (event.clientY - rect.top) * g.h / rect.height;
    const pixelX = Math.max(g.left, Math.min(g.right, x));
    const pixelY = Math.max(g.top, Math.min(g.priceBottom, y));
    const index = Math.min(g.bars.length - 1, Math.floor((pixelX - g.left) / g.step));
    return {
      pixelX, pixelY, inside: x === pixelX && y === pixelY,
      anchor: {ts:g.bars[index].ts, price:g.hi - (pixelY - g.top) / (g.priceBottom - g.top) * (g.hi - g.lo)},
    };
  }
  function erase(point) {
    const ctx = canvas.getContext('2d');
    // Paths use CSS pixels, while the canvas bitmap can be scaled for high DPI.
    ctx.save();
    ctx.resetTransform();
    ctx.lineWidth = 12;
    const hit = hits.findLast(({path, area}) => ctx.isPointInStroke(path, point.pixelX, point.pixelY)
      || (area && ctx.isPointInPath(path, point.pixelX, point.pixelY)));
    ctx.restore();
    if (hit) save(chartKey, items(chartKey).filter(shape => shape !== hit.shape));
  }
  function add(key, shape) {
    save(key, [...items(key), shape]);
    queueRedraw();
  }
  function consume(event) {
    event.stopImmediatePropagation();
    if (event.cancelable) event.preventDefault();
  }
  const captured = {capture:true};
  canvas.addEventListener('pointerdown', event => {
    if (mode === 'select') return;
    consume(event);
    if (gesture || event.button !== 0 || !geometry || chartKey !== keyFor(readChart().record)) return;
    const start = pointFor(event);
    if (!start.inside) return;
    gesture = {pointerId:event.pointerId, key:chartKey, start, end:start};
    canvas.setPointerCapture(event.pointerId);
  }, captured);
  canvas.addEventListener('pointermove', event => {
    if (gesture?.pointerId !== event.pointerId || !geometry) return;
    gesture.end = pointFor(event);
    if (dragTools.has(mode)) queueRedraw();
  }, captured);
  canvas.addEventListener('pointerup', event => {
    if (mode === 'select') return;
    consume(event);
    if (gesture?.pointerId !== event.pointerId) return;
    const {key, start} = gesture;
    cancelGesture();
    if (!geometry || key !== keyFor(readChart().record)) return;
    const end = pointFor(event);
    if (mode === 'eraser') {
      if (end.inside) erase(end);
    } else if (mode === 'text') {
      pendingText = {key, anchor:start.anchor};
      dialog.returnValue = '';
      input.value = '';
      dialog.showModal();
    } else {
      const wideEnough = start.anchor.ts !== end.anchor.ts;
      const tallEnough = Math.abs(end.pixelY - start.pixelY) >= 3;
      const validDrag = mode === 'trend'
        ? wideEnough || tallEnough : wideEnough && tallEnough;
      if (!dragTools.has(mode) || validDrag) add(key, {type:mode, a:start.anchor, b:end.anchor});
    }
  }, captured);
  for (const type of ['pointercancel','lostpointercapture']) {
    canvas.addEventListener(type, event => {
      if (gesture?.pointerId === event.pointerId) cancelGesture();
    }, captured);
  }
  for (const type of ['click','dblclick']) {
    canvas.addEventListener(type, event => { if (mode !== 'select') consume(event); }, captured);
  }
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && mode !== 'select' && !dialog.open) selectTool('select');
  });
  dialog.addEventListener('close', () => {
    const text = input.value.trim();
    if (dialog.returnValue === 'save' && text && pendingText) {
      add(pendingText.key, {type:'text', a:pendingText.anchor, text});
    }
    pendingText = null;
  });

  chartDrawingLayers.set(canvas, (ctx, nextGeometry) => {
    const {record} = readChart();
    const key = keyFor(record);
    if (key !== chartKey || !nextGeometry) cancelGesture();
    chartKey = key;
    geometry = nextGeometry;
    hits = [];
    for (const [id, button] of buttons) button.disabled = id !== 'select' && (!geometry || !key);
    if (!geometry || !key) return;
    const shapes = items(key);
    const preview = gesture && dragTools.has(mode) && {type:mode, a:gesture.start.anchor, b:gesture.end.anchor};
    if (shapes.length || preview) hits = paintChartDrawings(ctx, geometry, record.bars, shapes, preview);
  });
  redraw();
}

function paintChartDrawings(ctx, g, bars, shapes, preview) {
  const timeFrom = ts => Date.parse(ts.replace(' ', 'T') + (ts.length > 10 ? 'Z' : 'T00:00:00Z'));
  const times = bars.map(bar => timeFrom(bar.ts));
  const first = bars.findIndex(bar => bar.ts === g.bars[0].ts);
  const indices = new Map(bars.map((bar, index) => [bar.ts, index]));
  const averageStep = times.length > 1 ? (times.at(-1) - times[0]) / (times.length - 1)
    : bars[0].ts.length > 10 ? 60_000 : 86_400_000;
  function indexOf(ts) {
    if (indices.has(ts)) return indices.get(ts);
    const time = timeFrom(ts);
    const after = times.findIndex(value => value >= time);
    if (after === 0) return (time - times[0]) / averageStep;
    if (after < 0) return times.length - 1 + (time - times.at(-1)) / averageStep;
    return after - (times[after] - time) / (times[after] - times[after-1]);
  }
  function project(anchor) {
    return [g.x(indexOf(anchor.ts) - first),
      g.top + (g.hi - anchor.price) / (g.hi - g.lo) * (g.priceBottom - g.top)];
  }
  ctx.save();
  ctx.beginPath();
  ctx.rect(g.left, g.top, g.right - g.left, g.priceBottom - g.top);
  ctx.clip();
  ctx.strokeStyle = '#1557a4';
  ctx.lineWidth = 1.8;
  ctx.font = '13px "Malgun Gothic", sans-serif';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';

  function draw(shape) {
    const [ax, ay] = project(shape.a);
    const [bx, by] = shape.b ? project(shape.b) : [ax, ay];
    const left = Math.min(ax, bx), top = Math.min(ay, by);
    const width = Math.abs(ax - bx), height = Math.abs(ay - by);
    const path = new Path2D();
    let area = false;
    switch (shape.type) {
      case 'horizontal': path.moveTo(g.left, ay); path.lineTo(g.right, ay); break;
      case 'vertical': path.moveTo(ax, g.top); path.lineTo(ax, g.priceBottom); break;
      case 'trend': path.moveTo(ax, ay); path.lineTo(bx, by); break;
      case 'rectangle': path.rect(left, top, width, height); area = true; break;
      case 'ellipse': path.ellipse(left + width/2, top + height/2, width/2, height/2, 0, 0, 2*Math.PI); area = true; break;
      case 'text': {
        if (ax < g.left || ax > g.right || ay < g.top || ay > g.priceBottom) return null;
        const maxWidth = Math.min(260, g.right-g.left) - 16;
        if (maxWidth <= 0) return null;
        const lines = [''];
        for (const char of shape.text) {
          if (char === '\n') lines.push('');
          else if (ctx.measureText(lines.at(-1) + char).width > maxWidth) lines.push(char);
          else lines[lines.length-1] += char;
        }
        const boxWidth = Math.min(g.right-g.left, Math.max(...lines.map(line => ctx.measureText(line).width)) + 16);
        const boxHeight = lines.length * 17 + 12;
        const x = Math.min(ax, g.right - boxWidth);
        const y = Math.max(g.top, Math.min(ay, g.priceBottom - boxHeight));
        path.rect(x, y, boxWidth, boxHeight);
        ctx.fillStyle = '#f1f7ff';
        ctx.fill(path);
        ctx.fillStyle = '#153d68';
        lines.forEach((line, i) => ctx.fillText(line, x+8, y+6+i*17, boxWidth-16));
        area = true;
        break;
      }
      default: return null;
    }
    ctx.stroke(path);
    return {shape, path, area};
  }
  const hits = shapes.map(draw).filter(Boolean);
  if (preview) {
    ctx.setLineDash([5, 4]);
    draw(preview);
  }
  ctx.restore();
  return hits;
}

function paintCandles(ctx, w, h, bars, periods) {
  ctx.fillStyle='#fff';
  ctx.fillRect(0,0,w,h);
  if (!bars.length) return null;
  const left=12,right=w-74,top=24,bottom=h-34,volumeHeight=Math.round((h-58)*.26),priceBottom=bottom-volumeHeight-30;
  const step=(right-left)/bars.length;
  const values=bars.flatMap(bar=>[bar.low,bar.high,...periods.map(n=>bar['ma'+n])]).filter(Number.isFinite);
  const low=Math.min(...values),high=Math.max(...values);
  const pad=(high-low)*.06||Math.max(1,high*.005),lo=low-pad,hi=high+pad;
  const x=i=>left+(i+.5)*step,y=price=>top+(hi-price)/(hi-lo)*(priceBottom-top);
  ctx.font='11px "Malgun Gothic", sans-serif';
  ctx.textAlign='left';
  for(let i=0;i<=4;i++){
    const price=lo+(hi-lo)*i/4, py=y(price);
    ctx.strokeStyle='#d8e1eb';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(left,py);ctx.lineTo(right,py);ctx.stroke();
    ctx.fillStyle='#334155';ctx.fillText(Math.round(price).toLocaleString('ko-KR'),right+6,py+4);
  }
  const maxVolume=Math.max(1,...bars.map(bar=>bar.volume)), bodyWidth=Math.max(.7,Math.min(12,step*.64));
  // Keep a linear volume scale; give it its own panel and reference levels.
  ctx.fillStyle='#f5f2fc';ctx.fillRect(left,bottom-volumeHeight,right-left,volumeHeight);
  for(const fraction of [0,.5,1]){
    const vy=bottom-volumeHeight*fraction;
    ctx.strokeStyle='#d6cde8';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(left,vy);ctx.lineTo(right,vy);ctx.stroke();
    ctx.fillStyle='#536078';ctx.fillText(Math.round(maxVolume*fraction).toLocaleString('ko-KR'),right+6,vy+4);
  }
  bars.forEach((bar,i)=>{
    const center=x(i), bodyTop=Math.min(y(bar.open),y(bar.close));
    ctx.strokeStyle=ctx.fillStyle=bar.close>=bar.open?'#ff0000':'#0000ff';
    ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(center,y(bar.high));ctx.lineTo(center,y(bar.low));ctx.stroke();
    ctx.fillRect(center-bodyWidth/2,bodyTop,bodyWidth,Math.max(1,Math.abs(y(bar.open)-y(bar.close))));
    const volume=bar.volume/maxVolume*volumeHeight;
    ctx.fillRect(center-bodyWidth/2,bottom-volume,bodyWidth,volume);
  });
  for(const n of periods){
    ctx.strokeStyle=ctx.fillStyle=chartAverageColors[n];ctx.lineWidth=[20,60].includes(n)?3:1;
    ctx.beginPath();
    let connected=false;
    bars.forEach((bar,i)=>{
      const price=bar['ma'+n];
      if(!Number.isFinite(price)){connected=false;return;}
      if(connected)ctx.lineTo(x(i),y(price));
      else {
        ctx.moveTo(x(i),y(price));
        if(!Number.isFinite(bars[i+1]?.['ma'+n]))ctx.fillRect(x(i)-1,y(price)-1,3,3);
      }
      connected=true;
    });
    ctx.stroke();
  }
  ctx.lineWidth=1;ctx.fillStyle='#334155';
  ctx.fillText('거래량(주)',left,bottom-volumeHeight-7);
  const intraday=bars[0].ts.length>10;
  const multipleSessions=bars[0].ts.slice(0,10)!==bars.at(-1).ts.slice(0,10);
  const count=Math.min(6,bars.length,Math.max(2,Math.floor((right-left)/92)));
  ctx.textAlign='center';
  for(let i=0;i<count;i++){
    const index=Math.round(i*(bars.length-1)/Math.max(1,count-1)), ts=bars[index].ts;
    const label=intraday?ts.slice(multipleSessions?5:11,16):ts.slice(0,10),half=ctx.measureText(label).width/2;
    ctx.fillText(label,Math.max(left+half,Math.min(right-half,x(index))),h-11);
  }
  ctx.textAlign='left';
  const geometry = {left,right,top,bottom,priceBottom,volumeHeight,dataRight:right,lo,hi,w,h,bars,step,x};
  chartDrawingLayers.get(ctx.canvas)?.(ctx, geometry);
  return geometry;
}

const chartPriceFormat = new Intl.NumberFormat('ko-KR', {maximumFractionDigits:2});

function chartPointer(canvas, geometry, event, clamp = false) {
  if (!geometry) return null;
  const {left, right, top, bottom, w, h, bars, step} = geometry;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const rawX = (event.clientX - rect.left) * w / rect.width;
  const rawY = (event.clientY - rect.top) * h / rect.height;
  if (!clamp && (rawX < left || rawX > right || rawY < top || rawY > bottom)) return null;
  const x = Math.max(left, Math.min(right, rawX));
  const y = Math.max(top, Math.min(bottom, rawY));
  const index = Math.min(bars.length - 1, Math.floor((x - left) / step));
  return {index, x, y};
}

function paintChartSelection(ctx, g, start, end, label) {
  if (start < 0 || end < 0) return;
  const first = Math.min(start, end), last = Math.max(start, end);
  const left = g.left + first * g.step;
  const width = (last - first + 1) * g.step;
  ctx.save();
  ctx.fillStyle = '#80008026';
  ctx.fillRect(left, g.top, width, g.bottom - g.top);
  ctx.strokeStyle = '#800080';
  ctx.strokeRect(left, g.top, width, g.bottom - g.top);
  ctx.font = '12px "Malgun Gothic", sans-serif';
  ctx.fillStyle = '#800080';
  const caption = `${label(g.bars[first].ts)} ~ ${label(g.bars[last].ts)} · ${last - first + 1}봉`;
  const captionX = Math.max(g.left, Math.min(left + 6, g.right - ctx.measureText(caption).width - 6));
  ctx.fillText(caption, captionX, g.top + 17, g.right - captionX);
  ctx.restore();
}

function paintChartCrosshair(ctx, g, index, cursorY, label, selectedOffset = 0, color = '#000080') {
  if (!g.bars[index]) return;
  const {left, right, top, bottom, priceBottom, lo, hi, w} = g;
  const x = g.x(index) + selectedOffset;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.moveTo(x, top);
  ctx.lineTo(x, bottom);
  if (cursorY != null) {
    ctx.moveTo(left, cursorY);
    ctx.lineTo(right, cursorY);
  }
  ctx.stroke();
  if (cursorY != null) {
    ctx.font = '12px "Malgun Gothic", sans-serif';
    const time = label(g.bars[index].ts);
    const width = ctx.measureText(time).width + 16;
    const timeX = Math.max(left, Math.min(x - width / 2, right - width));
    ctx.fillStyle = color;
    ctx.fillRect(timeX, bottom + 9, width, 22);
    ctx.fillStyle = '#fff';
    ctx.fillText(time, timeX + 8, bottom + 24);
    if (cursorY <= priceBottom) {
      const price = hi - (cursorY - top) / (priceBottom - top) * (hi - lo);
      ctx.fillStyle = color;
      ctx.fillRect(right + 2, cursorY - 11, w - right - 3, 22);
      ctx.fillStyle = '#fff';
      ctx.font = '11px "Segoe UI", sans-serif';
      ctx.fillText(chartPriceFormat.format(price), right + 6, cursorY + 4, w - right - 8);
    }
  }
  ctx.restore();
}

function positionChartHover(box, canvas, g, bar, previous, cursorY) {
  if (!g || !bar || cursorY == null) {
    box.hidden = true;
    return;
  }
  const format = number => number == null ? '—' : chartPriceFormat.format(number);
  const rate = (number, base) => Number.isFinite(number) && Number.isFinite(base) && base > 0
    ? (number / base - 1) * 100 : null;
  const rateText = value => value == null ? '—' : (value > 0 ? '+' : '') + value.toFixed(2) + '%';
  const rateColor = value => value > 0 ? 'change-up' : value < 0 ? 'change-down' : 'change-flat';
  const body = rate(bar.close, bar.open), change = rate(bar.close, previous?.close);
  const node = (tag, value, className = '') => {
    const element = document.createElement(tag);
    element.className = className;
    if (value != null) element.textContent = value;
    return element;
  };
  const grid = node('div', null, 'hover-grid');
  for (const [name, value, className] of [
    ['시가', format(bar.open)], ['고가', format(bar.high)], ['저가', format(bar.low)], ['종가', format(bar.close)],
    ['봉 등락률', rateText(body), rateColor(body)], ['직전봉 대비', rateText(change), rateColor(change)],
  ]) {
    const cell = node('div');
    cell.append(node('span', name), node('strong', value, className));
    grid.append(cell);
  }
  box.replaceChildren(node('strong', bar.ts.slice(0, 16) + ' KST', 'hover-time'),
    grid, node('div', '거래량 ' + format(bar.volume) + '주', 'hover-volume'));
  box.style.maxWidth = Math.max(0, g.w - 8) + 'px';
  box.hidden = false;
  const x = g.x(g.bars.indexOf(bar)), bw = box.offsetWidth, bh = box.offsetHeight;
  const near = (value, size, bound) => Math.max(4, Math.min(
    value + 16 + size > bound ? value - size - 16 : value + 16, bound - size - 4));
  box.style.left = canvas.offsetLeft + near(x, bw, g.w) + 'px';
  box.style.top = canvas.offsetTop + near(cursorY, bh, g.h) + 'px';
}

function bindChartInspection(canvas, geometry, redraw, zoom, resetZoom) {
  const box = document.createElement('div');
  box.className = 'chart-tooltip';
  box.hidden = true;
  let hover, drag, frameRequest;
  function queueDraw() {
    if (frameRequest) return;
    frameRequest = requestAnimationFrame(() => { frameRequest = 0; redraw(); });
  }
  function clear() {
    const previous = drag;
    hover = drag = null;
    box.hidden = true;
    if (previous && canvas.hasPointerCapture(previous.pointerId)) canvas.releasePointerCapture(previous.pointerId);
  }
  function updateHover(event) {
    const g = geometry();
    const point = chartPointer(canvas, g, event, !!drag);
    hover = point && {...point, ts:g.bars[point.index].ts};
    return point;
  }
  canvas.addEventListener('pointermove', event => {
    if (drag && drag.pointerId !== event.pointerId) return;
    updateHover(event);
    queueDraw();
  });
  canvas.addEventListener('pointerleave', () => {
    if (!drag && hover) { clear(); queueDraw(); }
  });
  canvas.addEventListener('pointerdown', event => {
    if (event.button !== 0 || drag) return;
    const point = updateHover(event);
    if (!point) return;
    drag = {ts:hover.ts, x:point.x, pointerId:event.pointerId};
    canvas.setPointerCapture(event.pointerId);
    event.preventDefault();
    queueDraw();
  });
  canvas.addEventListener('pointerup', event => {
    if (drag?.pointerId !== event.pointerId) return;
    const g = geometry();
    const point = updateHover(event), start = drag;
    const index = g?.bars.findIndex(bar => bar.ts === start.ts) ?? -1;
    const range = point && index >= 0 && Math.abs(start.x - point.x) >= 6 && Math.abs(index - point.index) >= 2;
    if (range) {
      const first = g.bars[Math.min(index, point.index)], last = g.bars[Math.max(index, point.index)];
      clear();
      zoom(first.ts, last.ts);
    } else {
      drag = null;
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      queueDraw();
    }
  });
  for (const type of ['pointercancel','lostpointercapture']) {
    canvas.addEventListener(type, event => {
      if (drag?.pointerId === event.pointerId) { clear(); queueDraw(); }
    });
  }
  canvas.addEventListener('dblclick', resetZoom);
  function paint(ctx, g, record) {
    const index = hover && g ? g.bars.findIndex(bar => bar.ts === hover.ts) : -1;
    if (index < 0) {
      box.hidden = true;
      return null;
    }
    const bar = g.bars[index];
    const multipleDates = g.bars[0].ts.slice(0, 10) !== g.bars.at(-1).ts.slice(0, 10);
    const label = ts => record.frame === 'month' ? ts.slice(0, 7)
      : ts.length <= 10 ? ts : ts.slice(multipleDates ? 5 : 11, 16);
    if (drag) paintChartSelection(ctx, g, g.bars.findIndex(item => item.ts === drag.ts), index, label);
    paintChartCrosshair(ctx, g, index, hover.y, label);
    if (box.parentElement !== canvas.parentElement) canvas.after(box);
    const previous = record.bars[record.bars.indexOf(bar) - 1];
    positionChartHover(box, canvas, g, bar, previous, drag ? null : hover.y);
    return bar;
  }
  return {paint, clear, dragging:() => !!drag};
}

function drawChartLegend(legend, periods) {
  legend.replaceChildren(...periods.map(n=>{
    const label=document.createElement('span');
    label.textContent=n+'선';label.style.color=chartAverageColors[n];
    if([20,60].includes(n))label.style.fontWeight='bold';
    return label;
  }));
}

(() => {
  const byId = id => document.getElementById(id);
  const add = byId('observe-stock');
  const panel = byId('stock-tools');
  const saved = new Set(), saving = new Set(), drafts = new Map();
  let selection, memo, token, version = 0, listVersion = 0;

  window.collectorRefreshEvidence = async stock => {
    if (!token) throw new Error('수집기 연결을 확인해 주세요.');
    return api('/api/stock-memo/refresh', stock);
  };

  async function api(path, body) {
    const options = body ? {method:'POST', headers:{'Content-Type':'application/json','X-Collector-Token':token}, body:JSON.stringify(body)} : {};
    const response = await fetch(path, options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '수집기 요청 실패');
    return result;
  }

  function updateButton() {
    if (!add) return;
    const code = selection?.code;
    add.disabled = !code || !token || saved.has(code) || saving.has(code);
    add.classList.toggle('observed', saved.has(code));
    add.textContent = saved.has(code) ? '✓ 관찰종목에 담김' : saving.has(code) ? '저장 중…' : '＋ 관찰종목 담기';
  }

  async function loadList() {
    const current = ++listVersion;
    try {
      const data = await api('/api/observations');
      if (current !== listVersion) return;
      saved.clear();
      data.stocks.forEach(stock => saved.add(stock.code));
      token = data.token;
      updateButton();
      if (memo && !editor.disabled) save.disabled = !token;
      if (refresh && selection && !evidencePending) refresh.disabled = !token;
    } catch (error) {
      byId('stock-tool-feedback').textContent = error.message;
    }
  }

  if (add) add.onclick = async () => {
    const stock = selection;
    if (!stock || add.disabled) return;
    saving.add(stock.code);
    ++listVersion;
    updateButton();
    try {
      const {created} = await api('/api/observations', {...stock, action:'add'});
      ++listVersion;
      saved.add(stock.code);
      window.dispatchEvent(new Event('collector-observations-changed'));
      byId('stock-tool-feedback').textContent = `${stock.name} · ${created ? '관찰종목에 담았습니다.' : '이미 관찰 중입니다.'}`;
    } catch (error) {
      byId('stock-tool-feedback').textContent = error.message;
    } finally {
      saving.delete(stock.code);
      updateButton();
    }
  };

  const editor = byId('stock-memo-text');
  const feedback = byId('stock-memo-feedback');
  const save = byId('stock-memo-save');
  const refresh = byId('stock-memo-refresh');
  const evidence = byId('stock-memo-evidence');
  let evidencePending = false;
  const keyOf = stock => `${stock.day}/${stock.code}`;
  const control = (ready, fetching = false) => {
    editor.disabled = !ready;
    save.disabled = !ready || !token;
    evidencePending = fetching;
    refresh.disabled = evidencePending || !selection?.code || !token;
  };

  function displayEvidence(data) {
    const entries = [
      ...(data.reason?.reason ? [{title:data.reason.reason, tag:'상승 사유', at:data.reason.published || '', url:data.reason.url}] : []),
      ...(data.news || []).map(row => ({...row, tag:'뉴스'})),
      ...(data.disclosures || []).map(row => ({...row, tag:'공시'})),
      ...(data.history || []).map(row => ({title:row.reason, tag:row.kind==='news'?'과거 뉴스':'과거 상승 사유', at:row.day+' · '+row.source, url:row.url})),
    ];
    evidence.replaceChildren();
    if (!entries.length) evidence.textContent = '이 날짜에 저장된 상승 사유·뉴스·공시가 없습니다.';
    for (const row of entries) {
      const item = document.createElement('div');
      const label = document.createElement('span');
      label.className = `evidence-label ${row.tag === '공시' ? 'disclosure' : row.tag === '뉴스' ? 'news' : 'reason'}`;
      label.textContent = row.tag;
      const title = document.createElement(/^https?:\/\//.test(row.url || '') ? 'a' : 'span');
      if (title.tagName === 'A') { title.href = row.url; title.target = '_blank'; title.rel = 'noopener noreferrer'; }
      title.textContent = [row.at, row.title].filter(Boolean).join(' · ');
      item.append(label, title);
      evidence.append(item);
    }
  }

  async function loadMemo() {
    if (!panel || !selection || !panel.open) return;
    const stock = selection, id = keyOf(stock), current = ++version;
    control(false, true);
    try {
      const data = await api('/api/stock-memo?' + new URLSearchParams({day:stock.day, code:stock.code}));
      if (current !== version) return;
      const draft = drafts.get(id);
      memo = {id, revision:draft?.revision ?? data.note.revision ?? '', text:data.note.text || ''};
      editor.value = draft?.text ?? memo.text;
      displayEvidence(data);
      feedback.textContent = draft ? '작성 중인 메모가 있습니다.' : '';
      control(true);
    } catch (error) {
      if (current === version) { feedback.textContent = error.message; control(false); }
    }
  }

  window.collectorStockTools = stock => {
    const old = selection ? keyOf(selection) : '';
    selection = stock?.code && stock?.day ? stock : null;
    updateButton();
    if (!panel || old === (selection ? keyOf(selection) : '')) return;
    ++version;
    memo = null;
    editor.value = '';
    evidence.replaceChildren();
    feedback.textContent = selection ? '' : '종목을 선택하세요.';
    byId('stock-memo-heading').textContent = selection ? `${selection.name} · ${selection.day}` : '종목 선택';
    control(false);
    loadMemo();
  };

  if (panel) {
    panel.addEventListener('toggle', () => { if (panel.open && !memo) loadMemo(); });
    editor.oninput = () => {
      if (!memo) return;
      if (editor.value === memo.text) drafts.delete(memo.id);
      else drafts.set(memo.id, {revision:memo.revision,text:editor.value});
      feedback.textContent = '작성 중';
    };
    save.onclick = async () => {
      if (!memo || save.disabled) return;
      const stock = selection, target = memo, text = editor.value;
      control(false, true);
      try {
        const result = await api('/api/notes', {day:stock.day, code:stock.code, name:stock.name, revision:target.revision, text});
        drafts.delete(target.id);
        if (memo === target) {
          memo = {id:target.id, revision:result.note.revision, text};
          feedback.textContent = '저장했습니다.';
        }
      } catch (error) {
        if (memo === target) feedback.textContent = error.message;
      } finally {
        if (memo?.id === target.id) control(true);
      }
    };
    refresh.onclick = async () => {
      const stock = selection, current = version;
      evidencePending = true;
      refresh.disabled = true;
      feedback.textContent = '뉴스·공시 조회 중…';
      try {
        const data = await api('/api/stock-memo/refresh', stock);
        if (current !== version) return;
        displayEvidence(data);
        feedback.textContent = data.failed.length ? `${data.failed.join('·')} 조회 실패 · 저장 자료 표시` : '뉴스·공시 확인 완료';
      } catch (error) {
        if (current === version) feedback.textContent = error.message;
      } finally {
        if (current === version) { evidencePending = false; refresh.disabled = !token; }
      }
    };
    window.addEventListener('beforeunload', event => { if (drafts.size) { event.preventDefault(); event.returnValue = ''; } });
  }

  window.addEventListener('pageshow', loadList);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) loadList(); });
})();

/* One personal memo surface for every stock list. Uses the existing revisioned store. */
(() => {
  const make = (tag, text, cls) => {const e=document.createElement(tag);if(text)e.textContent=text;if(cls)e.className=cls;return e;};
  const dialog=make('dialog',null,'collector-common-memo'), heading=make('h2'), day=make('input'),
    text=make('textarea'), status=make('p'), save=make('button','메모 저장'), close=make('button','닫기'),reload=make('button','저장본 다시 읽기'),
    evidence=make('details'), evidenceText=make('div');
  dialog.id='collector-common-memo';day.type='date';day.setAttribute('aria-label','메모 저장 날짜');
  text.maxLength=20000;text.setAttribute('aria-label','종목 메모');text.rows=8;
  status.setAttribute('role','status');evidence.append(make('summary','저장된 상승 사유·뉴스'),evidenceText);
  const actions=make('div',null,'common-memo-actions');actions.append(reload,save,close);
  dialog.append(heading,day,text,evidence,status,actions);document.body.append(dialog);
  let latest={},token='',today='',target=null,revision='',busy=false,generation=0,timer,loading=false;
  const drafts=new Map(), key=()=>target?.code+'/'+day.value;
  async function api(url,body){const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json','X-Collector-Token':token},body:JSON.stringify(body)}:{});const d=await r.json();if(!r.ok)throw Error(d.error||'메모 조회 실패');return d;}
  function rows(){return [...document.querySelectorAll('.stock-name-text,button.rank-stock')].map(label=>({label,row:label.closest('[data-stock-code],tr[data-code],li[data-code]')})).filter(x=>x.row);}
  function decorate(){
    for(const {label,row} of rows()){
      const code=row.dataset.stockCode||row.dataset.code;
      let line=label.closest('.collector-name-line');
      if(!line){line=make('span',null,'collector-name-line');label.before(line);line.append(label);const control=make('span','◢','collector-memo-toggle');control.tabIndex=0;control.setAttribute('role','button');control.dataset.code=code;control.dataset.name=label.textContent;control.setAttribute('aria-label',label.textContent+' 메모 열기');const preview=make('span',null,'collector-latest-memo');line.append(control,preview);}
      const note=latest[code], preview=line.querySelector('.collector-latest-memo');
      const firstLine=note?.text?.split(/\r?\n/).map(s=>s.trim()).find(s=>s&&!/^\[[^\]]+\]$/.test(s));
      const value=firstLine||note?.text?.replace(/\s+/g,' ').trim()||'메모 작성';
      if(preview.textContent!==value)preview.textContent=value;
      preview.title=note?note.day+' · '+note.text:'삼각형을 눌러 메모 작성';
      line.querySelector('.collector-memo-toggle').classList.toggle('has-note',!!note);
    }
  }
  let signature='';
  async function refresh(force=false){
    decorate();const codes=[...new Set(rows().map(x=>x.row.dataset.stockCode||x.row.dataset.code))].sort();
    const next=codes.join(',');if(loading||(!force&&signature===next))return;
    loading=true;
    try{const combined={};for(let i=0;i<codes.length||i===0;i+=150){const d=await api('/api/notes/latest?'+new URLSearchParams({codes:codes.slice(i,i+150).join(',')}));Object.assign(combined,d.notes);token=d.token;today=d.day;}latest=combined;signature=next;decorate();}
    catch(e){signature='';if(dialog.open)status.textContent=e.message;}
    finally{loading=false;}
  }
  async function load(){const version=++generation;save.disabled=true;text.disabled=true;status.textContent='메모 확인 중…';
    try{const d=await api('/api/stock-memo?'+new URLSearchParams({day:day.value,code:target.code}));if(version!==generation)return;const draft=drafts.get(key());revision=draft?.revision??d.note?.revision??'';text.value=draft?.text??d.note?.text??'';evidenceText.replaceChildren();for(const item of [d.reason?.reason,...(d.history||[]).map(x=>x.day+' · '+x.reason),...(d.news||[]).map(x=>x.title)].filter(Boolean))evidenceText.append(make('p',item));status.textContent=draft?'작성 중인 내용을 복원했습니다.':'표시된 날짜에 저장됩니다.';save.disabled=!token;text.disabled=false;}
    catch(e){if(version===generation)status.textContent=e.message;}
  }
  window.collectorOpenMemo=async stock=>{if(busy)return;if(dialog.open&&target?.code===stock.code)return;target={...stock};if(!today)await refresh(true);day.value=stock.day||latest[stock.code]?.day||today;heading.textContent=stock.name+' · 공통 메모';if(!dialog.open)dialog.showModal();await load();};
  function activate(event){const control=event.target.closest('.collector-memo-toggle');if(!control)return;if(event.type==='keydown'&&!['Enter',' '].includes(event.key))return;event.preventDefault();event.stopImmediatePropagation();window.collectorOpenMemo({code:control.dataset.code,name:control.dataset.name});}
  document.addEventListener('click',activate,true);document.addEventListener('keydown',activate,true);
  text.addEventListener('input',()=>{drafts.set(key(),{text:text.value,revision});status.textContent='작성 중 · 저장 버튼을 눌러주세요.';});
  day.onchange=()=>{if(day.value)load();};close.onclick=()=>{if(!busy)dialog.close();};
  reload.onclick=()=>{if(busy)return;if(drafts.has(key())&&!confirm('작성 중인 내용을 버리고 저장된 메모를 다시 읽을까요?'))return;drafts.delete(key());load();};
  dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
  save.onclick=async()=>{if(busy||save.disabled)return;const id=key();busy=true;save.disabled=true;day.disabled=true;text.disabled=true;close.disabled=true;
    try{const d=await api('/api/notes',{...target,day:day.value,text:text.value,revision});revision=d.note.revision;drafts.delete(id);status.textContent='저장했습니다.';await refresh(true);window.dispatchEvent(new Event('collector-memos-changed'));}
    catch(e){status.textContent=e.message;}
    finally{busy=false;save.disabled=false;day.disabled=false;text.disabled=false;close.disabled=false;}
  };
  const observer=new MutationObserver(changes=>{if(!changes.some(c=>[...c.addedNodes].some(n=>n.nodeType===1&&!n.closest?.('.collector-name-line,#collector-common-memo'))))return;clearTimeout(timer);timer=setTimeout(()=>refresh(),120);});
  observer.observe(document.querySelector('main')||document.body,{childList:true,subtree:true});
  window.addEventListener('collector-memos-changed',()=>refresh(true));
  window.addEventListener('beforeunload',e=>{if(drafts.size){e.preventDefault();e.returnValue='';}});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh(true);});
  setInterval(()=>{if(!document.hidden)refresh(true);},60000);refresh();
})();

// Keep the list/chart above explanatory panels; all original controls remain reachable.
document.addEventListener('DOMContentLoaded', () => {
  const main=document.querySelector('main');if(!main)return;
  const extras=[...main.querySelectorAll(':scope > .cards,:scope > .notice,:scope > p.muted,:scope > p:not([id]),:scope > .rec-overview')];
  if(extras.length){const details=document.createElement('details'),summary=document.createElement('summary');details.className='collector-collection-details';summary.textContent='수집 현황·조건 펼치기';details.append(summary);extras[0].before(details);extras.forEach(e=>details.append(e));}
  const volume=document.querySelector('#volume-summary');if(volume){const d=document.createElement('details'),s=document.createElement('summary');d.className='collector-collection-details';s.textContent='첫 편입 이후 가격 흐름';volume.before(d);d.append(s,volume);}
  const notice=document.querySelector('#rank-notice');
  if(notice){const d=document.createElement('details'),s=document.createElement('summary'),canvas=document.querySelector('#rank-canvas');d.className='collector-collection-details';s.textContent='차트 데이터 기준·상태';(canvas.closest('.chart-drawing-layout')||canvas).after(d);d.append(s,notice);}
  const canvas=main.querySelector('canvas');if(!canvas)return;
  let pending=false;
  const fit=()=>{pending=false;if(innerWidth<=1000)return;const top=canvas.getBoundingClientRect().top+scrollY;const height=Math.max(300,Math.min(620,Math.floor(innerHeight-top-24)));if(main.style.getPropertyValue('--collector-chart-height')!==height+'px'){main.style.setProperty('--collector-chart-height',height+'px');window.dispatchEvent(new Event('resize'));}};
  const queue=()=>{if(!pending){pending=true;requestAnimationFrame(fit);}};
  new ResizeObserver(queue).observe(main);window.addEventListener('resize',queue);queue();
});
