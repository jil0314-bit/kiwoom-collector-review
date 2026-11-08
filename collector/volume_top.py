"""Today's absolute volume ranking, separate from volume-surge archives. Read only."""
import threading
import time
from datetime import datetime

import archive
import volume_surge
from kiwoom import DataError, KST, code_of, number

BODY = dict(mrkt_tp='000', sort_tp='1', mang_stk_incls='16', crd_tp='0',
            trde_qty_tp='0', pric_tp='0', trde_prica_tp='0', mrkt_open_tp='0', stex_tp='3')
LOCK = threading.Lock()
STATE = {'busy': False, 'message': '아직 조회하지 않았습니다.'}
LAST = 0.0
CLASS_LOCK = threading.Lock()
CLASS_CACHE = {}


def excluded_codes(call):
    """Use exchange product classes, not brand-name guesses. Fail closed on lookup errors."""
    key = (datetime.now(KST).strftime('%Y-%m-%d'), call)
    with CLASS_LOCK:
        if key in CLASS_CACHE:
            return CLASS_CACHE[key]
        excluded, counts = set(), {}
        for market, label in [('8', 'ETF'), ('3', 'ELW'), ('60', 'ETN'),
                              ('70', '손실제한 ETN'), ('90', '변동성 ETN')]:
            cursor, seen, codes = '', set(), set()
            for _ in range(100):
                payload, header = call('ka10099', {'mrkt_tp': market}, cursor)
                items = payload.get('list')
                if not isinstance(items, list):
                    raise DataError(label + ' 종목분류 목록 확인 실패')
                codes.update(code_of(item.get('code', '')) for item in items)
                if header.get('cont-yn') != 'Y':
                    break
                cursor = str(header.get('next-key', ''))
                if not cursor or cursor in seen:
                    raise DataError(label + ' 분류 연속조회 키 누락·반복')
                seen.add(cursor)
            else:
                raise DataError(label + ' 분류 연속조회 한도 초과')
            if label == 'ETF' and not codes:
                raise DataError('ETF 분류가 비었습니다. 기존 저장 유지')
            excluded.update(codes)
            counts[label] = len(codes)
        CLASS_CACHE.clear()
        CLASS_CACHE[key] = (frozenset(excluded), counts)
        return CLASS_CACHE[key]


def read(data, day):
    return volume_surge.read(archive.day_root(data / 'volume_top', day) / 'index.json',
                             {'day': day, 'stocks': []})


def ranking(call=volume_surge.request, *, sort='1'):
    if sort not in ('1', '3'):
        raise DataError('지원하지 않는 거래 순위 정렬')
    body = {**BODY, 'sort_tp': sort}
    excluded, classes = excluded_codes(call)
    rows, seen, cursor = {}, set(), ''
    excluded_count = 0
    for _ in range(30):
        payload, header = call('ka10030', dict(body), cursor)
        items = payload.get('tdy_trde_qty_upper')
        if not isinstance(items, list):
            raise DataError('당일 거래량 상위 응답 목록 누락')
        for item in items:
            code = code_of(item.get('stk_cd', ''))
            if code in excluded:
                excluded_count += 1
                continue
            if code in rows:
                continue
            rows[code] = {'code': code, 'name': str(item.get('stk_nm', code)),
                          'price': number(item.get('cur_prc', ''), price=True),
                          'rate': number(item.get('flu_rt', '')),
                          'volume': number(item.get('trde_qty', '')),
                          'volume_limit_possible': number(item.get('trde_qty', '')) == 4294967295,
                          'turnover': number(item.get('trde_tern_rt', '')),
                          'amount_million': number(item.get('trde_amt', ''))}
            if len(rows) >= 100:
                break
        if len(rows) >= 100 or header.get('cont-yn') != 'Y':
            break
        cursor = str(header.get('next-key', ''))
        if not cursor or cursor in seen:
            raise DataError('당일 거래량 연속조회 키 누락·반복')
        seen.add(cursor)
    else:
        raise DataError('당일 거래량 연속조회 한도 초과')
    stocks = sorted(rows.values(), key=lambda x: -x['amount_million' if sort == '3' else 'volume'])[:100]
    if not stocks:
        raise DataError('당일 거래량 상위 응답이 비었습니다. 기존 자료 유지')
    # Ranking itself has no session date. Verify a dated quote before archiving.
    quote, _ = call('ka10095', {'stk_cd': stocks[0]['code'] + '_AL'}, '')
    dated = [x for x in quote.get('atn_stk_infr', [])
             if code_of(x.get('stk_cd', '')) == stocks[0]['code']]
    if len(dated) != 1:
        raise DataError('거래량 순위 기준일 확인 실패')
    day = datetime.strptime(str(dated[0].get('dt', '')), '%Y%m%d').strftime('%Y-%m-%d')
    for i, stock in enumerate(stocks, 1):
        stock['rank'] = i
    return {'day': day, 'observed_at': datetime.now(KST).isoformat(timespec='seconds'),
            'api': 'ka10030', 'request': body, 'stocks': stocks,
            'filter': 'ETF·ELW·ETN 제외', 'excluded_from_response': excluded_count,
            'classification': {'api': 'ka10099', 'markets': classes,
                               'checked_day': datetime.now(KST).strftime('%Y-%m-%d')}}


def start(data):
    global LAST
    if not LOCK.acquire(blocking=False):
        return 'busy'
    if time.monotonic() - LAST < 60:
        LOCK.release()
        return 'recent'
    LAST = time.monotonic()
    STATE.update(busy=True, message='당일 거래량 순위 조회 중')

    def work():
        try:
            record = ranking()
            volume_surge.write(archive.day_root(data / 'volume_top', record['day']) / 'index.json', record)
            STATE['message'] = record['day'] + ' · ' + str(len(record['stocks'])) + '종목 저장'
        except Exception as exc:
            STATE['message'] = str(exc)[:160]
        finally:
            STATE['busy'] = False
            LOCK.release()
    threading.Thread(target=work, daemon=True).start()
    return 'started'
