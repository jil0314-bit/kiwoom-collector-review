import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from uuid import uuid4

import chart_service
from kiwoom import DataError


class FastChartTests(unittest.TestCase):
    def test_cold_fast_view_returns_pending_without_blocking(self):
        key = (uuid4().hex,)
        release = threading.Event()
        def fetch():
            release.wait(2)
            return {'bars': [5]}
        try:
            before = time.monotonic()
            result = chart_service.get(key, fetch, lambda: None, 15, wait=False)
            self.assertLess(time.monotonic() - before, .3)
            self.assertTrue(result['pending'])
        finally:
            release.set()

    def test_saved_chart_returns_without_waiting_for_slow_api(self):
        key = (uuid4().hex,)
        release = threading.Event()
        started = threading.Event()
        def fetch():
            started.set()
            release.wait(2)
            return {'bars': [2], 'chart_notice': 'fresh'}
        try:
            before = time.monotonic()
            result = chart_service.get(key, fetch, lambda: {'bars': [1], 'chart_notice': 'saved'}, 15)
            self.assertLess(time.monotonic() - before, .3)
            self.assertTrue(result['refreshing'])
            self.assertEqual(result['bars'], [1])
            self.assertTrue(started.wait(1))
            # Concurrent readers share the running job, never enqueue another API request.
            self.assertTrue(chart_service.get(key, fetch, lambda: None, 15)['refreshing'])
        finally:
            release.set()
        for _ in range(100):
            result = chart_service.get(key, fetch, lambda: None, 15)
            if not result.get('refreshing'):
                break
            time.sleep(.01)
        self.assertEqual(result['bars'], [2])

    def test_two_cold_readers_share_completion_and_api_call(self):
        key = (uuid4().hex,)
        calls = []
        results = []
        def fetch():
            calls.append(1)
            time.sleep(.1)
            return {'bars': [3]}
        threads = [threading.Thread(target=lambda: results.append(chart_service.get(key, fetch, lambda: None, 15))) for _ in range(2)]
        before = time.monotonic()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
        self.assertLess(time.monotonic() - before, 2)
        self.assertEqual(calls, [1])
        self.assertEqual(len(results), 2)

    def test_failed_refresh_keeps_previous_data_and_reports_failure(self):
        key = (uuid4().hex,)
        def fetch():
            raise DataError('인증 시험 오류')
        chart_service.get(key, fetch, lambda: {'bars': [4]}, 15)
        for _ in range(100):
            result = chart_service.get(key, fetch, lambda: None, 15)
            if result.get('refresh_error'):
                break
            time.sleep(.01)
        self.assertEqual(result['bars'], [4])
        self.assertIn('인증', result['refresh_error'])
        self.assertFalse(result.get('refreshing', False))

    def test_disk_daily_cache_is_readable_while_api_lock_is_held(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            day = '2026-10-07'
            path = data / 'chart_history' / day / '005930.json'
            path.parent.mkdir(parents=True)
            bars = [{'ts': day, 'open': 100, 'high': 102, 'low': 99, 'close': 101, 'volume': 10}]
            path.write_text(json.dumps({'bars': bars, 'fetched_at': day+'T15:00:00+09:00'}))
            with chart_service.chart_data.LOCK:
                result = chart_service.seed(data, day, '005930', 'day', 'watchlist', '삼성전자', False)
            self.assertEqual(result['bars'][0]['close'], 101)
            self.assertIn('2026-10-07 15:00:00', result['chart_notice'])

    def test_live_seed_never_uses_yesterday_as_today(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(chart_service.seed(Path(folder), '2000-01-01', '005930', 'minute', 'ranking', None, True))


if __name__ == '__main__':
    unittest.main()
