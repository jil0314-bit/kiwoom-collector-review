"""Offline regressions: scheduler failures and uncollected market-stock charts."""
import json
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import app
import chart_data
import observations
import safeio
import stock_search
import volume_surge
from kiwoom import DataError, KST

AT = datetime(2026, 11, 16, 20, 10, tzinfo=KST)
DAY = AT.date().isoformat()


class RegressionTests(unittest.TestCase):
    def test_theme_thread_start_releases_shared_lock(self):
        with patch.object(app, 'now', return_value=AT), patch.object(app, 'GUARD', threading.Lock()), \
                patch.object(app, 'STATE', {'busy': False, 'queued': False}), \
                patch('themes.read_day', return_value={'day': DAY}), \
                patch.object(app.threading.Thread, 'start', side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):
                app.refresh_themes_now()
            self.assertFalse(app.GUARD.locked())
            self.assertFalse(app.STATE['busy'])

    def test_start_releases_lock_on_schedule_read_and_thread_start_failure(self):
        for failure in ('read', 'thread'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp, \
                    patch.object(app, 'DATA', Path(tmp)), patch.object(app, 'now', return_value=AT), \
                    patch.object(app, 'GUARD', threading.Lock()), \
                    patch.object(app, 'STATE', {'busy': False, 'queued': False}), \
                    patch.object(app, 'read', side_effect=PermissionError('fixture') if failure == 'read' else None, return_value={}), \
                    patch.object(app.threading.Thread, 'start', side_effect=RuntimeError('fixture')):
                with self.assertRaises((PermissionError, RuntimeError)):
                    app.start(DAY)
                self.assertFalse(app.GUARD.locked())
                self.assertFalse(app.STATE['busy'])
                self.assertFalse(app.STATE['queued'])

    def test_error_file_failure_does_not_stop_next_worker(self):
        class EndIteration(BaseException):
            pass
        for idle in (False, True):
            with self.subTest(idle=idle), tempfile.TemporaryDirectory() as tmp, \
                    patch.object(app, 'DATA', Path(tmp)), patch.object(app, 'now', return_value=AT), \
                    patch.object(app, 'idle_now', return_value=idle), \
                    patch.object(app.recommendations, 'tick'), patch('reasons.watch_hero4', side_effect=OSError('fixture')), \
                    patch.object(app, 'ranking_and_investor_tick'), \
                    patch.object(app, 'reasons_tick', side_effect=OSError('fixture')), \
                    patch.object(app, 'memo_tick', side_effect=OSError('fixture')), \
                    patch.object(app, 'save', side_effect=PermissionError('fixture')), \
                    patch.object(app.volume_surge, 'tick') as volume, \
                    patch.object(app.stock_sectors, 'tick'), patch.object(app.stock_profiles, 'tick'), \
                    patch.object(app.time, 'sleep', side_effect=EndIteration):
                with self.assertRaises(EndIteration):
                    app.scheduler()
                self.assertEqual(volume.call_count, 0 if idle else 1)

    def test_volume_retry_clears_error_and_completes_final(self):
        class Clock:
            @staticmethod
            def now(tz=None):
                return AT
        class API:
            fail = True
            def minute_bars(self, code, day):
                if self.fail:
                    raise DataError('temporary fixture failure')
                return [dict(ts=day+' 09:00:00', open=100, high=101, low=99, close=100, volume=10)], {'pages': []}
        api = API()
        with tempfile.TemporaryDirectory() as tmp, patch.object(volume_surge, 'datetime', Clock), \
                patch.object(chart_data, 'CLIENT', api), patch.object(volume_surge.time, 'sleep'), \
                patch.object(safeio, 'LOG_ROOT', Path(tmp)):
            data = Path(tmp)
            volume_surge.commit_rank(data, DAY, [dict(code='000001', name='fixture', rank=1, price=100)],
                                     {'unknown_cap_excluded': []}, AT.isoformat())
            volume_surge.collect_bars(data, DAY)
            self.assertTrue(volume_surge.metadata(data, DAY)['stocks'][0]['error'])
            api.fail = False
            volume_surge.collect_bars(data, DAY)
            result = volume_surge.metadata(data, DAY)
            self.assertEqual(result['saved'], 1)
            self.assertTrue(result['final_complete'])
            self.assertNotIn('error', result['stocks'][0])
            self.assertNotIn('error', result['tracked'][0])
            self.assertEqual(volume_surge.pending_bars(result), [])

    def test_market_stock_chart_before_observation_and_persistent_add(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'DATA', Path(tmp)), \
                patch.object(app, 'PORT', 8766):
            data = Path(tmp)
            master = {'schema': stock_search.MASTER_SCHEMA, 'day': datetime.now(KST).date().isoformat(),
                      'items': {'123456': {'name': '수집안된종목', 'market': '코넥스'}}}
            (data/'stock_master.json').write_text(json.dumps(master), encoding='utf-8')
            handler = object.__new__(app.Handler)
            handler.headers = {'Host': '127.0.0.1:8766'}
            replies = []
            handler.respond = lambda body, status=200, **kw: replies.append((status, body))
            for frame in ('minute', 'minute3', 'minute5', 'day', 'week', 'month'):
                handler.path = f'/api/chart?day={DAY}&code=123456&source=search&frame={frame}'
                with patch.object(chart_data, 'load', return_value={'bars': [], 'stock': {'code': '123456'}}) as load, \
                        patch('archive.payload', side_effect=AssertionError('must not require a saved ranking')):
                    handler.do_GET()
                self.assertEqual(replies[-1][0], 200)
                self.assertEqual(load.call_args.kwargs['source'], 'watchlist')
                self.assertEqual(load.call_args.kwargs['name'], '수집안된종목')
            self.assertEqual(observations.read(data), [])
            row, created = observations.add(data, '123456', DAY, 'search')
            self.assertTrue(created)
            self.assertEqual(observations.read(data)[0]['code'], '123456')
            self.assertFalse(observations.add(data, '123456', DAY, 'search')[1])
            handler.path = f'/api/chart?day={DAY}&code=999999&source=search&frame=day'
            handler.do_GET()
            self.assertEqual(replies[-1][0], 404)

    def test_market_cache_isolated_by_data_folder(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            day = datetime.now(KST).date().isoformat()
            for folder, code in ((a, '111111'), (b, '222222')):
                (Path(folder)/'stock_master.json').write_text(json.dumps({'schema': stock_search.MASTER_SCHEMA,
                    'day': day, 'items': {code: {'name': '검색표본', 'market': '코스피'}}}), encoding='utf-8')
            self.assertEqual(stock_search.search(Path(a), '검색')[0][0]['code'], '111111')
            self.assertEqual(stock_search.search(Path(b), '검색')[0][0]['code'], '222222')
