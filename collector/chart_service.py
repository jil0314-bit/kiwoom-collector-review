"""Fast display of known chart data; one deduplicated background refresh queue."""
from collections import OrderedDict
from datetime import datetime
import gzip
import json
import threading
import time

import archive
import chart_data
from kiwoom import DataError, KST

GUARD = threading.Condition()
CACHE = OrderedDict()
JOBS = OrderedDict()
ACTIVE = {}
ERRORS = {}
STARTED = False
LIMIT = 128


def seed(data, day, code, frame, source, name, live, revision=None):
    """Read existing files without waiting for the API-client lock or making requests."""
    target_day = datetime.now(KST).date().isoformat() if live else day
    cache_data = data / 'volume_surge' / 'cache' if source == 'volume' else data
    record = None
    if source == 'ranking' and (not live or day == target_day):
        payload, stale = archive.payload(data, day, code, revision=revision if not live else None)
        if stale:
            raise DataError('최신 자료로 교체되었습니다. 화면 갱신 후 다시 선택하세요.')
        if payload:
            record = json.loads(payload)
    elif source == 'volume' and (not live or day == target_day):
        path = data / 'volume_surge' / day / (code + '.json')
        if path.is_file():
            record = json.loads(path.read_bytes())
    base = record or {'day': target_day, 'kind': 'preview', 'stock': {'code': code, 'name': name or code}}
    if frame.startswith('minute'):
        path = cache_data / 'watchlist_history' / target_day / (code + '.json')
        if (live or source == 'watchlist') and path.is_file():
            saved = json.loads(path.read_bytes())
            base = {**base, 'day': target_day, 'bars': saved['bars'], 'fetched_at': saved['fetched_at']}
            raw = saved['raw']
        elif record:
            path = (archive.active(data, day) if source == 'ranking' else data / 'volume_surge' / day) / (code + '.raw.json.gz')
            raw = json.loads(gzip.decompress(path.read_bytes())) if path.is_file() else {}
            base['fetched_at'] = record.get('fetched_at') or record.get('saved_at') or record['bars'][-1]['ts'].replace(' ', 'T') + '+09:00'
        else:
            return None
        result = chart_data.minute_record(base, raw) if frame == 'minute' else chart_data.grouped_record(base, raw, int(frame[-1]))
    else:
        directories = ('weekly_history', 'chart_history') if frame == 'week' else ('chart_history', 'weekly_history')
        saved = None
        for directory in directories:
            path = cache_data / directory / target_day / (code + '.json')
            if path.is_file():
                saved = json.loads(path.read_bytes())
                break
        if not saved:
            return None
        if frame == 'week':
            result = chart_data.weekly_record(base, saved['bars'], saved['fetched_at'])
        else:
            result = {**base, 'frame': 'day', 'bars': chart_data.averages([dict(b) for b in saved['bars']], chart_data.PERIODS['day'])[-180:],
                      'fetched_at': saved['fetched_at'], 'chart_notice': '일봉 · 저장된 조회 자료 · 종가 단순평균 · 20·60선 3배 굵기.'}
    if not result.get('bars'):
        return None
    # A persisted snapshot is never silently presented as newly fetched market data.
    result['live'] = live
    result['archive_day'] = day
    result['chart_notice'] += ' 저장 자료 먼저 표시 · 조회 ' + result['fetched_at'][:19].replace('T', ' ') + ' KST.'
    return result


def worker():
    while True:
        with GUARD:
            GUARD.wait_for(lambda: bool(JOBS))
            key, (loader, event) = JOBS.popitem(last=True)
            ACTIVE[key] = event
        try:
            result = loader()
            with GUARD:
                CACHE[key] = (time.monotonic(), result)
                CACHE.move_to_end(key)
                ERRORS.pop(key, None)
                while len(CACHE) > LIMIT:
                    CACHE.popitem(last=False)
        except Exception as exc:
            with GUARD:
                ERRORS[key] = (time.monotonic(), str(exc) if isinstance(exc, DataError) else '차트 최신 조회 실패')
                while len(ERRORS) > LIMIT:
                    ERRORS.pop(next(iter(ERRORS)))
        finally:
            with GUARD:
                ACTIVE.pop(key, None)
                event.set()


def get(key, loader, fallback, ttl, *, wait=True, prefetch=False):
    global STARTED
    with GUARD:
        if not STARTED:
            threading.Thread(target=worker, daemon=True).start()
            STARTED = True
        cached = CACHE.get(key)
    if cached is None:
        try:
            first = fallback()
        except (OSError, ValueError, KeyError):
            first = None
        if first:
            with GUARD:
                CACHE.setdefault(key, (float('-inf'), first))
                cached = CACHE[key]
                while len(CACHE) > LIMIT:
                    CACHE.popitem(last=False)
    with GUARD:
        cached = CACHE.get(key)
        error = ERRORS.get(key)
        if cached and time.monotonic() - cached[0] < ttl:
            return cached[1]
        if error and time.monotonic() - error[0] < 15:
            if not cached:
                raise DataError(error[1])
            return {**cached[1], 'refresh_error': error[1], 'chart_notice': cached[1].get('chart_notice', '') + ' 최신 조회 실패 · 이전 자료 유지: ' + error[1]}
        event = JOBS[key][1] if key in JOBS else ACTIVE.get(key) or threading.Event()
        if key not in JOBS and key not in ACTIVE:
            JOBS[key] = (loader, event)
            if prefetch:
                JOBS.move_to_end(key, last=False)
            while len(JOBS) > 16:
                _, (_, cancelled) = JOBS.popitem(last=False)
                cancelled.set()
            GUARD.notify()
        elif key in JOBS and not prefetch:
            JOBS.move_to_end(key)
        if cached:
            return {**cached[1], 'refreshing': True, 'chart_notice': cached[1].get('chart_notice', '') + ' 최신 자료 갱신 중.'}
        if not wait:
            return {'pending': True, 'refreshing': True, 'bars': []}
    # Only the very first uncached view must wait for the actual remote response.
    event.wait(35)
    with GUARD:
        cached = CACHE.get(key)
        error = ERRORS.get(key)
        if cached:
            return cached[1]
        raise DataError(error[1] if error else '첫 차트 조회 중입니다. 잠시 후 다시 선택하세요.')
