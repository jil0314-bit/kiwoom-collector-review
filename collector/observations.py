"""Collector-owned observations saved independently of ranking snapshots."""
import safeio
import json
import os
import threading
from datetime import datetime

import archive
from kiwoom import KST, code_of


LOCK = threading.RLock()
SOURCE_LABELS = {
    'ranking': '상승률 상위', 'watchlist': '상승률 상위', 'volume': '거래량 급증',
    'volume-top': '당일 거래량 상위', 'amount-top': '당일 거래대금 상위',
    'theme': '상승테마', 'investor': '외국인·기관', 'recommendations': '방송·유튜브 추천',
    'search': '종목 검색',
}


def _path(data):
    return data / 'observations' / 'index.json'


def read(data):
    with LOCK:
        path = _path(data)
        if not path.is_file():
            return []
        rows = json.loads(path.read_text(encoding='utf-8'))['stocks']
        return sorted(({'source': 'ranking', **row,
                        'source_label': SOURCE_LABELS.get(row.get('source', 'ranking'), '출처 미확인')}
                       for row in rows), key=lambda row: row['added_at'], reverse=True)


def _save(data, rows):
    path = _path(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps({'stocks': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
    safeio.replace(tmp, path)


def add(data, code, source_day, source='ranking', context=None):
    code = code_of(code)
    archive.day_root(data, source_day)
    if not isinstance(source, str) or source not in SOURCE_LABELS:
        raise ValueError('관찰종목 출처 오류')
    with LOCK:
        rows = read(data)
        if existing := next((row for row in rows if row['code'] == code), None):
            return existing, False
        stock = find_stock(data, code, source_day, source, context or {})
        if not stock:
            raise LookupError('선택한 탭에 해당 종목이 없습니다. 목록을 다시 확인해 주세요.')
        added_at = datetime.now(KST)
        row = {'code': code, 'name': stock.get('name') or code, 'source_day': source_day, 'source': source,
               'source_label': SOURCE_LABELS[source],
               'added_at': added_at.isoformat(timespec='microseconds')}
        _save(data, [row, *rows])
        return row, True


def find_stock(data, code, day, source, context):
    if source == 'search':
        # 2026-11-16: any listed stock found by the whole-market search may be observed.
        import stock_search
        return stock_search.lookup(data, code)
    if source == 'ranking':
        with archive.LOCK:
            rows = archive.metadata(archive.active(data, day)).get('stocks', [])
    elif source == 'watchlist':
        import watchlists
        group = int(context['group'])
        if watchlists.contains(code, group):
            return {'name': watchlists.names().get(code, code)}
        return None
    elif source == 'volume':
        import volume_surge
        doc = volume_surge.metadata(data, day)
        rows = doc.get('stocks', []) + doc.get('tracked', [])
    elif source in ('volume-top', 'amount-top', 'recommendations'):
        import amount_top
        import recommendations
        import volume_top
        module = {'volume-top': volume_top, 'amount-top': amount_top, 'recommendations': recommendations}[source]
        rows = module.read(data, day).get('stocks', [])
    elif source == 'theme':
        import themes
        doc = themes.read_day(data, day) or {}
        rows = [row for group in doc.get('themes', []) + doc.get('custom', []) for row in group.get('leaders', [])]
    elif source == 'investor':
        import investor_flows
        market = context.get('market')
        if context.get('start'):
            doc = investor_flows.read_period(data, context['start'], day)
        else:
            doc = investor_flows.read_day(data, day)
        rankings = (doc or {}).get('markets', {}).get(market, {}).get('rankings', {})
        rows = [row for side in ('foreign', 'institution') for row in rankings.get(side, [])]
    else:
        raise ValueError('관찰종목 출처 오류')
    return next((row for row in rows if row['code'] == code), None)


def remove(data, code):
    code = code_of(code)
    with LOCK:
        rows = read(data)
        remaining = [row for row in rows if row['code'] != code]
        if len(remaining) != len(rows):
            _save(data, remaining)
        return remaining
