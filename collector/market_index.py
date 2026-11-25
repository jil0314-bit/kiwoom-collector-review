"""Read-only KOSPI summary for the clock; shared cache, no archive writes."""
import threading
import time
from datetime import datetime

from kiwoom import DataError, KST, number

LOCK = threading.Lock()
TTL = 30
MAX_AGE = 90
_state = {'busy': False, 'attempt': float('-inf'), 'updated': 0,
          'snapshot': None, 'error': ''}


def parse(payload):
    # ka20001: mrkt_tp=0 / inds_cd=001. Summary only; no time-series pagination.
    value = number(payload.get('cur_prc', ''), price=True)
    rate = number(payload.get('flu_rt', ''))
    change = number(payload.get('pred_pre', ''))
    direction = {'1': 'up', '2': 'up', '3': 'flat', '4': 'down', '5': 'down'}.get(str(payload.get('pred_pre_sig', '')))
    if value <= 0 or direction is None:
        raise DataError('코스피 지수 응답 확인 필요')
    for item in (rate, change):
        if (item > 0 and direction != 'up') or (item < 0 and direction != 'down'):
            raise DataError('코스피 등락 방향 불일치')
    return {'name': 'KOSPI', 'code': '001', 'value': value, 'rate': rate,
            'change': change, 'direction': direction,
            'fetched_at': datetime.now(KST).isoformat(timespec='seconds')}


def _fetch():
    import volume_surge
    try:
        payload, _ = volume_surge.request('ka20001', {'mrkt_tp': '0', 'inds_cd': '001'})
        snapshot = parse(payload)
        with LOCK:
            _state.update(snapshot=snapshot, updated=time.monotonic(), error='')
    except Exception:
        # No provider error body or authentication material is exposed to the UI.
        with LOCK:
            _state['error'] = '코스피 조회 확인 필요'
    finally:
        with LOCK:
            _state['busy'] = False


def read():
    with LOCK:
        current = time.monotonic()
        if not _state['busy'] and current - _state['attempt'] >= TTL:
            _state.update(busy=True, attempt=current)
            try:
                threading.Thread(target=_fetch, daemon=True, name='collector-kospi-clock').start()
            except RuntimeError:
                _state.update(busy=False, error='코스피 조회 시작 실패')
        snapshot = _state['snapshot']
        ready = bool(snapshot and not _state['error'] and current - _state['updated'] <= MAX_AGE
                     and snapshot['fetched_at'][:10] == datetime.now(KST).date().isoformat())
        return {**(snapshot if ready else {'name': 'KOSPI', 'code': '001', 'direction': 'unknown', 'rate': None}),
                'ready': ready, 'pending': _state['busy'], 'error': _state['error']}
