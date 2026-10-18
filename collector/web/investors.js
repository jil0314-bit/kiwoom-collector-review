'use strict';
const $ = id => document.getElementById(id);
let token = '', enabled = true, shared = false, record = null, loading = false;
async function api(path, body) {
  const options = body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Collector-Token':token}, body:JSON.stringify(body)};
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '자료 조회 실패');
  return result;
}
function render() {
  const query = $('search').value.trim().toLowerCase();
  for (const key of ['foreign','institution']) {
    const body = $(key); body.replaceChildren();
    const period = record?.kind === 'period';
    const rows = (record?.markets?.[$('market').value]?.rankings[key] || []).filter(r => r.rank <= (period ? 30 : 20))
      .sort((a,b) => period ? a.rank-b.rank : b.rank-a.rank);
    $(key+'-count').textContent = rows.length ? `${$('market').selectedOptions[0].textContent} · ${rows.length}종목` : '';
    for (const row of rows.filter(r => (r.code+' '+r.name).toLowerCase().includes(query))) {
      const tr = document.createElement('tr');
      for (const value of [row.rank, row.name, row.net_amount_10m_krw, row.net_quantity_1000_shares]) {
        const td = document.createElement('td');
        td.textContent = value === null || value === undefined ? 'UNKNOWN' : typeof value === 'number' ? value.toLocaleString('ko-KR') : value;
        tr.append(td);
      }
      const code = document.createElement('small'); code.textContent = row.code; tr.children[1].append(code);
      for (const cell of [tr.children[2],tr.children[3]]) {
        const n = Number(cell.textContent.replaceAll(',',''));
        if (Number.isFinite(n)) cell.className = n < 0 ? 'negative' : n > 0 ? 'positive' : '';
      }
      body.append(tr);
    }
    if (!body.children.length) {
      const tr = document.createElement('tr'), td = document.createElement('td'); td.colSpan = 4;
      td.textContent = rows.length ? '검색 결과 없음' : '저장 자료 없음 · 당일 수집 성공 후 표시됩니다.'; tr.append(td); body.append(tr);
    }
  }
}
async function loadDay() {
  const day = $('day').value;
  const period = day.startsWith('period:');
  const [start,end] = period ? day.slice(7).split('_') : [];
  const params = period ? 'start='+encodeURIComponent(start)+'&end='+encodeURIComponent(end) : 'day='+encodeURIComponent(day);
  const received = day ? await api('/api/investors/'+(period ? 'period' : 'day')+'?'+params) : null;
  if (day !== $('day').value) return;
  record = received;
  $('download').hidden = !record;
  if (record) {
    $('download').href = '/api/investors/'+(period ? 'period-csv' : 'csv')+'?'+params;
    $('basis').textContent = period
      ? `기간 합산 ${start}~${end} · 각 TOP 30 · 순매수금액 기준 · ${record.coverage?.note || '조회 범위 UNKNOWN'} · 기간 수량 UNKNOWN`
      : `조회일 ${record.day} · 20위 → 1위 · 수신 ${record.fetched_at.replace('T',' ')} · ${record.collection_mode === 'historical_backfill' ? '과거일 조회' : record.after_close_refresh ? '20:05 이후 재조회' : '장중 자료'} · 원본 기준일 UNKNOWN (API 미제공)`;
  }
  render();
}
async function poll() {
  if (loading) return;
  loading = true;
  try {
    const status = await api('/api/investors/status');
    token = status.token; enabled = status.enabled; shared = Boolean(status.shared_viewer);
    $('monitor').textContent = enabled ? '자동 수집 중지' : '자동 수집 시작';
    $('collect').disabled = shared || status.state.busy; $('monitor').disabled = shared;
    $('progress').textContent = shared ? '동기화 저장 자료 조회 · 새 수집은 원본 PC에서 합니다.' : `${enabled ? '자동 수집 켜짐' : '자동 수집 꺼짐'} · ${status.state.message}` + (status.last_error ? '\n최근 실패: '+status.last_error.message : '');
    const old = $('day').value;
    const opts = status.days.map(day => {const o = document.createElement('option');o.value = day;o.textContent = day;return o;});
    for (const period of status.periods || []) {
      const o = document.createElement('option'); o.value='period:'+period.start+'_'+period.end;
      o.textContent=`기간 합산 ${period.start}~${period.end} · TOP 30`; opts.push(o);
    }
    if (!opts.length) {const o=document.createElement('option');o.value='';o.textContent='저장 자료 없음';opts.push(o);}
    $('day').replaceChildren(...opts);
    if (opts.some(o => o.value === old)) $('day').value = old;
    await loadDay();
  } catch (error) { $('progress').textContent = error.message; }
  finally {loading = false;}
}
async function action(path, body) {
  try {
    const result = await api(path, body);
    await poll();
    const messages = {waiting:'평일 09:10 이후 수집합니다.',collector_busy:'상승률 수집 중입니다. 자동 수집이 켜져 있으면 완료 후 다시 시도합니다.',running:'이미 외국인·기관 수집 중입니다.'};
    if (messages[result.state]) $('progress').textContent = messages[result.state];
  } catch (error) {$('progress').textContent = error.message;}
}
$('day').addEventListener('change', () => loadDay().catch(e => {$('progress').textContent=e.message;}));
$('search').addEventListener('input', render);
$('market').addEventListener('change', render);
$('collect').addEventListener('click', () => action('/api/investors/collect', {}));
$('monitor').addEventListener('click', () => action('/api/investors/monitor', {enabled:!enabled}));
poll(); setInterval(poll, 10000);
