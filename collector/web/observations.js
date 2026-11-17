'use strict';

const observationEl = id => document.getElementById(id);
const observationNode = (tag, text, className) => {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
};
let observations = [], observationProfiles = {}, observationDay = '', observationToken = '';
let observationRequest = 0;
const removalsPending = new Set();

async function observationApi(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '관찰 목록 조회에 실패했습니다.');
  return data;
}

function updateDateOptions() {
  const select = observationEl('observation-day');
  const current = select.value;
  const days = [...new Set(observations.map(row => row.added_at.slice(0, 10)))];
  select.replaceChildren(new Option('전체 날짜', ''), ...days.map(day => new Option(day, day)));
  if (days.includes(current)) select.value = current;
}

function observationRow(stock) {
  const row = document.createElement('tr');
  row.dataset.code = stock.code;
  const name = document.createElement('td');
  const button = observationNode('button', stock.name, 'rank-stock');
  button.type = 'button';
  name.append(button, observationNode('small', '• ' + stock.code, 'rank-profile'));
  const profile = observationProfiles[stock.code] || {};
  const cap = profile.market_cap > 0 ? `시총 ${formatWon(profile.market_cap,1e8)}${profile.cap_day ? ` · ${profile.cap_day} 기준` : ''}` : '시총 미확인';
  name.append(observationNode('small', '• ' + cap, 'rank-profile stock-money'));
  for (const [label, values] of [['키움 테마', profile.themes], ['관심테마그룹', profile.groups], ['업종', profile.industry ? [profile.industry] : []]]) {
    name.append(observationNode('small', `• ${label} · ${values?.join(', ') || '미확인'}`, 'rank-profile'));
  }
  const date = document.createElement('td');
  const added = observationNode('time', stock.added_at.slice(0, 10), 'observation-date');
  added.dateTime = stock.added_at;
  date.append(added, observationNode('small', `${stock.source_label || '상승률 상위'} · ${stock.source_day}`, 'rank-profile'));
  const actions = document.createElement('td');
  const remove = observationNode('button', '빼기', 'secondary observation-remove');
  remove.type = 'button';
  remove.disabled = removalsPending.has(stock.code);
  remove.setAttribute('aria-label', `${stock.name} 관찰종목에서 빼기`);
  remove.addEventListener('click', event => {
    event.stopPropagation();
    if (confirm(`${stock.name}을(를) 관찰종목에서 뺄까요?`)) removeObservation(stock, remove);
  });
  actions.append(remove);
  row.append(name, date, actions);
  return row;
}

function renderObservations() {
  const day = observationEl('observation-day').value;
  const search = observationEl('observation-search').value.trim().toLowerCase();
  const rows = observations.filter(stock => (!day || stock.added_at.startsWith(day)) &&
    (!search || `${stock.name} ${stock.code}`.toLowerCase().includes(search)));
  observationEl('rows').replaceChildren(...rows.map(observationRow));
  observationEl('observation-count').textContent = `${rows.length} / ${observations.length}종목`;
  const empty = observationEl('observation-empty');
  empty.hidden = rows.length > 0;
  empty.textContent = observations.length ? '조건에 맞는 관찰종목이 없습니다.' : '각 탭의 차트에서 ‘관찰종목 담기’를 누르면 여기에 표시됩니다.';
  window.rankUpdate(observationDay, rows.map(stock => ({...stock, chart_day: stock.source_day})));

}

async function loadObservations() {
  const request = ++observationRequest;
  try {
    const data = await observationApi('/api/observations');
    if (request !== observationRequest) return;
    observations = data.stocks;
    observationDay = data.day;
    observationToken = data.token;
    updateDateOptions();
    renderObservations();
    const profiles = await observationApi('/api/stock-profiles?day=' + encodeURIComponent(data.day));
    if (request !== observationRequest) return;
    observationProfiles = profiles.profiles || {};
    renderObservations();
  } catch (error) {
    if (request === observationRequest) observationEl('observation-status').textContent = error.message;
  }
}

async function removeObservation(stock, button) {
  if (removalsPending.has(stock.code)) return;
  removalsPending.add(stock.code);
  button.disabled = true;
  try {
    await observationApi('/api/observations', {
      method: 'POST', headers: {'Content-Type':'application/json', 'X-Collector-Token':observationToken},
      body: JSON.stringify({action:'remove', code:stock.code})
    });
    observationEl('observation-status').textContent = `${stock.name}을(를) 관찰종목에서 뺐습니다.`;
    await loadObservations();
  } catch (error) {
    observationEl('observation-status').textContent = error.message;
  } finally {
    removalsPending.delete(stock.code);
    button.disabled = false;
  }
}

observationEl('observation-day').addEventListener('change', renderObservations);
observationEl('observation-search').addEventListener('input', renderObservations);

window.addEventListener('pageshow', loadObservations);

window.addEventListener('collector-observations-changed', loadObservations);
