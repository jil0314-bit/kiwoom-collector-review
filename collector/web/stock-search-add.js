'use strict';
// 2026-11-16: 종목 검색 결과를 바로 관찰종목에 담기 (상승률 상위 · 관찰종목 탭 공통).
// 기존 검색창의 목록 걸러보기 동작은 그대로 두고, 그 아래에 전체 시장 검색 결과만 덧붙인다.
(() => {
  const input = document.querySelector('#search, #observation-search');
  if (!input) return;
  const box = document.createElement('div');
  box.id = 'stock-search-add';
  box.hidden = true;
  box.setAttribute('aria-live', 'polite');
  const host = input.closest('.observation-filters') || input.parentElement;
  host.append(box);

  let version = 0, timer = 0, token = '', day = '';
  const node = (tag, text, className) => {
    const el = document.createElement(tag);
    if (text) el.textContent = text;
    if (className) el.className = className;
    return el;
  };
  async function call(path, options) {
    const response = await fetch(path, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '요청을 처리하지 못했습니다.');
    return data;
  }
  function render(stocks, query, note) {
    box.replaceChildren(node('span', `전체 종목 검색 “${query}” · 종목명을 눌러 차트를 확인하세요`, 'ssa-title'));
    if (note) box.append(node('span', note, 'ssa-note'));
    if (!stocks.length) {
      box.append(node('span', note || '일치하는 종목이 없습니다.', 'ssa-note'));
    } else {
      const list = node('ul');
      for (const stock of stocks) {
        const item = node('li');
        const label = node('button', '', 'ssa-chart secondary');
        label.type = 'button';
        label.setAttribute('aria-label', stock.name + ' 차트 보기');
        label.addEventListener('click', () => window.collectorSearchSelect?.(stock, day));
        label.append(node('span', stock.name, 'ssa-name'), node('span', stock.code + (stock.market ? ' · ' + stock.market : ''), 'ssa-code'));
        const button = node('button', stock.observed ? '담겨 있음' : '＋ 관찰종목 담기', stock.observed ? 'secondary' : '');
        button.type = 'button';
        button.disabled = stock.observed;
        button.addEventListener('click', () => add(stock, button));
        item.append(label, button);
        list.append(item);
      }
      box.append(list);
    }
    box.hidden = false;
  }
  async function add(stock, button) {
    button.disabled = true;
    button.textContent = '담는 중…';
    try {
      const result = await call('/api/observations', {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-Collector-Token': token},
        body: JSON.stringify({action: 'add', code: stock.code, day, source: 'search'})
      });
      button.textContent = result.created ? '담았습니다' : '담겨 있음';
      button.className = 'secondary';
      stock.observed = true;
      window.dispatchEvent(new Event('collector-observations-changed'));
      window.collectorObservationListRefresh?.();
    } catch (error) {
      button.disabled = false;
      button.textContent = '다시 시도';
      button.title = error.message;
      box.append(node('span', error.message, 'ssa-note'));
    }
  }
  async function run(current) {
    const query = input.value.trim();
    if (query.length < 2) { box.hidden = true; return; }
    box.replaceChildren(node('span', '전체 시장 종목 목록을 확인하고 있습니다…', 'ssa-note'));
    box.hidden = false;
    try {
      const data = await call('/api/stock-search?q=' + encodeURIComponent(query));
      if (current !== version) return;
      token = data.token; day = data.day;
      render(data.stocks, query, !data.master_day ? '전체 종목 목록을 아직 받지 못했습니다. 잠시 뒤 다시 검색해 주세요.' : data.master_day!==data.day ? data.master_day+' 종목 목록으로 검색 중 · 최신 목록 재조회 대기' : '');
    } catch (error) {
      if (current === version) render([], query, error.message);
    }
  }
  input.addEventListener('input', () => { const current=++version;clearTimeout(timer);box.hidden=true;timer = setTimeout(()=>run(current), 300); });
  input.addEventListener('keydown', event=>{if(event.key==='Enter'&&!event.isComposing){event.preventDefault();if(!box.hidden)box.querySelector('.ssa-chart')?.click();}});
})();
