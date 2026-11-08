"""Absolute trading-value ranking; separate storage and controls from volume rankings."""
import threading
import time

import archive
import volume_surge
import volume_top

LOCK = threading.Lock()
STATE = {'busy': False, 'message': '아직 조회하지 않았습니다.'}
LAST = 0.0


def read(data, day):
    return volume_surge.read(archive.day_root(data / 'amount_top', day) / 'index.json',
                             {'day': day, 'stocks': []})


def start(data):
    global LAST
    if not LOCK.acquire(blocking=False):
        return 'busy'
    if time.monotonic() - LAST < 60:
        LOCK.release()
        return 'recent'
    LAST = time.monotonic()
    STATE.update(busy=True, message='당일 거래대금 순위 조회 중')

    def work():
        try:
            record = volume_top.ranking(sort='3')
            volume_surge.write(archive.day_root(data / 'amount_top', record['day']) / 'index.json', record)
            STATE['message'] = record['day'] + ' · ' + str(len(record['stocks'])) + '종목 저장'
        except Exception as exc:
            STATE['message'] = str(exc)[:160]
        finally:
            STATE['busy'] = False
            LOCK.release()
    threading.Thread(target=work, daemon=True).start()
    return 'started'
