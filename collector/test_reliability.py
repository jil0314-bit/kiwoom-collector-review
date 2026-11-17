"""2026-11-16 reliability repair: offline tests. No account, network or real archive writes."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import app
import archive
import kiwoom
import safeio
from kiwoom import DataError, KST, parse_bar
from test_collector import Stub, page, row

DAY = '2026-09-22'
AT = datetime(2026, 9, 22, 10, 0, tzinfo=KST)


def live(ts, high, low, close, volume):
    return dict(cntr_tm=ts, open_pric='100', high_pric=str(high), low_pric=str(low), cur_prc=str(close), trde_qty=str(volume))


class Api:
    """100-stock fixture whose failures can be scripted per stock code."""
    expected_count = 100

    def __init__(self, count=100):
        self.codes = [f'{i:06d}' for i in range(1, count + 1)]
        self.expected_count = count
        self.failures = {}      # code -> remaining failures (None = always)
        self.calls = {}
        self.error = DataError('분봉 시각 형식 오류')

    def ranking(self):
        return [dict(code=c, name='종목' + c, rank=i + 1, rate=5, price=100) for i, c in enumerate(self.codes)], {'fixture': True}

    def minute_bars(self, code, day):
        self.calls[code] = self.calls.get(code, 0) + 1
        left = self.failures.get(code, 0)
        if left is None or left > 0:
            if left:
                self.failures[code] = left - 1
            raise self.error
        stamp = f'{day} 09:{self.calls[code]:02d}:00'
        return [dict(ts=stamp, open=100, high=110, low=90, close=101, volume=1, ma5=None, ma10=None, ma20=None, ma60=None)], {'fixture': True}


class BarTests(unittest.TestCase):
    def test_millisecond_stamp_is_accepted(self):
        self.assertEqual(parse_bar(row('20261113140800380'))['ts'], '2026-11-13 14:08:00')
        with self.assertRaises(DataError):
            parse_bar(row('2026111314'))
        with self.assertRaises(DataError):
            parse_bar(row('20261113140803380'))          # seconds inside a minute bar are still rejected

    def test_live_bar_growing_between_pages_is_one_bar(self):
        api = Stub([page([live('20260922090100', 105, 99, 104, 50), live('20260922090000', 102, 98, 101, 30)], True, 'a'),
                    page([live('20260922090000', 103, 97, 102, 45), live('20260921195900', 101, 99, 100, 5)])])
        bars, raw = api.minute_bars('005930', DAY)
        first = next(b for b in bars if b['ts'].endswith('09:00:00'))
        self.assertEqual((first['high'], first['low'], first['close'], first['volume']), (103, 97, 102, 45))

    def test_real_contradiction_still_fails(self):
        api = Stub([page([row('20260922090000')], True, 'a'), page([row('20260922090000', 101)])])
        with self.assertRaisesRegex(DataError, '충돌'):
            api.minute_bars('005930', DAY)

    def test_few_bad_rows_are_dropped_many_fail(self):
        bad = dict(row('20260922090200'), high_pric='1')          # high below low
        api = Stub([page([bad, row('20260922090100'), row('20260922090000')])])
        bars, raw = api.minute_bars('005930', DAY)
        self.assertEqual(len(bars), 2)
        self.assertEqual(len(raw['dropped_rows']), 1)
        many = [dict(row(f'202609220901{i:02d}')) for i in range(1, 6)]   # five rows with seconds
        api = Stub([page(many + [row('20260922090000')])])
        with self.assertRaisesRegex(DataError, '형식 오류 행'):
            api.minute_bars('005930', DAY)


class SnapshotTests(unittest.TestCase):
    def run_collect(self, api, folder):
        with patch.object(app, 'DATA', Path(folder)), patch.object(app, 'now', return_value=AT), \
                patch.object(app, 'STOCK_RETRY_PAUSE', 0), patch.object(safeio, 'LOG_ROOT', Path(folder)):
            return app.collect(DAY, api=api)

    def test_transient_failure_is_retried_and_nothing_is_missing(self):
        with tempfile.TemporaryDirectory() as d:
            api = Api()
            api.failures = {'000007': 1, '000050': 2}
            meta = self.run_collect(api, d)
            self.assertEqual((meta['status'], meta['saved'], meta['missing']), ('saved', 100, []))
            self.assertEqual(api.calls['000050'], 3)
            self.assertEqual(api.calls['000001'], 1)            # healthy stocks are not fetched again
            lines = (Path(d) / 'logs').glob('errors-*.jsonl')
            entries = [json.loads(x) for f in lines for x in f.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(sum(e['where'] == 'rise.stock' for e in entries), 3)
            self.assertIn('분봉 시각 형식 오류', entries[0]['error'])

    def test_one_dead_stock_keeps_the_other_99_and_carries_old_bars(self):
        with tempfile.TemporaryDirectory() as d:
            api = Api()
            first = self.run_collect(api, d)
            api.failures = {'000042': None}
            meta = self.run_collect(api, d)
            self.assertNotEqual(meta['revision'], first['revision'])
            self.assertEqual((meta['status'], meta['saved'], meta['expected']), ('saved', 99, 100))
            self.assertEqual([(m['code'], m['carried']) for m in meta['missing']], [('000042', True)])
            folder = archive.active(Path(d), DAY)
            self.assertEqual(archive.metadata(folder)['revision'], meta['revision'])
            kept = json.loads((folder / '000042.json').read_text(encoding='utf-8'))
            self.assertEqual(kept['bars'][0]['ts'], DAY + ' 09:01:00')      # bars of the earlier snapshot
            self.assertEqual(kept['revision'], meta['revision'])
            fresh = json.loads((folder / '000001.json').read_text(encoding='utf-8'))
            self.assertEqual(fresh['bars'][0]['ts'], DAY + ' 09:02:00')
            stock = next(s for s in meta['stocks'] if s['code'] == '000042')
            self.assertTrue(stock['carried'])

    def test_dead_stock_without_earlier_bars_is_marked_not_hidden(self):
        with tempfile.TemporaryDirectory() as d:
            api = Api()
            api.failures = {'000042': None}
            meta = self.run_collect(api, d)
            self.assertEqual(meta['missing'][0]['carried'], False)
            self.assertEqual(next(s for s in meta['stocks'] if s['code'] == '000042')['status'], 'error')
            self.assertEqual(meta['saved'], 99)

    def test_first_ranked_stock_failing_does_not_block_the_day(self):
        with tempfile.TemporaryDirectory() as d:
            api = Api()
            api.failures = {'000001': None}
            meta = self.run_collect(api, d)
            self.assertEqual(meta['saved'], 99)

    def test_outage_keeps_previous_snapshot_and_does_not_hammer(self):
        with tempfile.TemporaryDirectory() as d:
            api = Api()
            first = self.run_collect(api, d)
            api.calls.clear()
            api.failures = {c: None for c in api.codes[3:60]}
            with self.assertRaisesRegex(DataError, '교체 보류'):
                self.run_collect(api, d)
            self.assertEqual(archive.metadata(archive.active(Path(d), DAY))['revision'], first['revision'])
            self.assertEqual(max(api.calls.values()), 1)        # 57 failures > 30: no retry rounds
            self.assertEqual(len(list((Path(d) / DAY).glob('snapshot-*'))), 1)

    def test_eleven_missing_is_over_the_ten_percent_limit(self):
        with tempfile.TemporaryDirectory() as d:
            api = Api()
            api.failures = {c: None for c in api.codes[10:21]}
            with self.assertRaisesRegex(DataError, '89/100'):
                self.run_collect(api, d)
            api.failures = {c: None for c in api.codes[10:20]}
            self.assertEqual(self.run_collect(api, d)['saved'], 90)


class ScheduleTests(unittest.TestCase):
    def test_rest_gap_after_a_long_cycle(self):
        with tempfile.TemporaryDirectory() as d, patch.object(app, 'DATA', Path(d)), \
                patch.object(app, 'STATE', {'busy': False}), patch.object(app, 'start') as start:
            app.save(Path(d) / 'schedule.json', {'day': DAY, 'last_start_epoch': (AT - timedelta(seconds=215)).timestamp(),
                                                 'last_finish_epoch': (AT - timedelta(seconds=5)).timestamp()})
            app.scheduler_tick(AT)
            start.assert_not_called()
            app.scheduler_tick(AT + timedelta(seconds=36))
            start.assert_called_once_with(DAY, source='auto')

    def test_final_with_missing_stocks_is_retried_three_times_only(self):
        with tempfile.TemporaryDirectory() as d, patch.object(app, 'DATA', Path(d)), \
                patch.object(app, 'STATE', {'busy': False}), patch.object(app, 'start') as start:
            late = AT.replace(hour=20, minute=30)
            app.save(Path(d) / DAY / 'final' / 'index.json', {'day': DAY, 'status': 'saved', 'ranking_at': DAY + 'T20:06:00+09:00',
                                                              'missing': [{'code': '000042'}]})
            app.save(Path(d) / 'schedule.json', {'day': DAY, 'final_attempts': 1, 'last_final_epoch': (late - timedelta(minutes=16)).timestamp()})
            app.scheduler_tick(late)
            start.assert_called_once_with(DAY, source='final')
            start.reset_mock()
            app.save(Path(d) / 'schedule.json', {'day': DAY, 'final_attempts': 3, 'last_final_epoch': (late - timedelta(minutes=40)).timestamp()})
            app.scheduler_tick(late)
            start.assert_not_called()


class FileTests(unittest.TestCase):
    def test_replace_retries_while_destination_is_locked(self):
        with tempfile.TemporaryDirectory() as d, patch.object(safeio, 'LOG_ROOT', Path(d)), patch.object(safeio, 'REPLACE_DELAYS', (0, 0, 0)):
            real, calls = safeio.os.replace, []

            def flaky(a, b):
                calls.append(1)
                if len(calls) < 3:
                    raise PermissionError('사용 중')
                return real(a, b)
            with patch.object(safeio.os, 'replace', flaky):
                safeio.write_bytes(Path(d) / 'x.json', b'{"a": 1}')
            self.assertEqual(safeio.load_json(Path(d) / 'x.json'), {'a': 1})
            self.assertEqual(len(calls), 3)
            with patch.object(safeio.os, 'replace', side_effect=PermissionError('잠김')), self.assertRaises(PermissionError):
                safeio.write_bytes(Path(d) / 'y.json', b'{}')
            self.assertTrue(any(e['where'] == 'file.replace' for e in safeio.recent_errors(Path(d))))

    def test_corrupt_json_is_set_aside_and_fallback_used(self):
        with tempfile.TemporaryDirectory() as d, patch.object(safeio, 'LOG_ROOT', Path(d)), patch.object(safeio.time, 'sleep'):
            path = Path(d) / 'schedule.json'
            path.write_text('{"day": "2026-', encoding='utf-8')
            self.assertEqual(safeio.load_json(path, {'ok': True}), {'ok': True})
            self.assertFalse(path.exists())
            self.assertTrue((Path(d) / 'schedule.json.bad').is_file())
            self.assertEqual(safeio.recent_errors(Path(d))[-1]['where'], 'file.corrupt')

    def test_corrupt_latest_pointer_falls_back_to_newest_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as d, patch.object(safeio, 'LOG_ROOT', Path(d)), patch.object(safeio.time, 'sleep'):
            root = Path(d) / DAY
            for name, at in (('snapshot-' + 'a' * 32, 'T09:00'), ('snapshot-' + 'b' * 32, 'T09:03')):
                app.save(root / name / 'index.json', {'status': 'saved', 'ranking_at': DAY + at, 'stocks': [1]})
            (root / 'latest.json').write_text('{"folder": "snap', encoding='utf-8')
            self.assertEqual(archive.active(Path(d), DAY).name, 'snapshot-' + 'b' * 32)

    def test_unmasked_error_text(self):
        self.assertIn('PermissionError', app.safe_error(PermissionError('x.json 사용 중')))
        self.assertEqual(app.safe_error(DataError('순위 목록 누락')), '순위 목록 누락')


class TokenTests(unittest.TestCase):
    def test_revoked_token_waits_before_reissue(self):
        sleeps = []
        api = kiwoom.Kiwoom(interval=0, transport=lambda *a: None)
        api.shared = True
        sent = []

        def send(path, body, headers):
            sent.append(path)
            if path == '/oauth2/token':
                return {'token': 'T%d' % len(sent), 'expires_dt': '20991231000000', 'return_code': 0}, {}
            if headers['authorization'] == 'Bearer old':
                raise DataError('키움 응답 오류 코드 3')
            return {'return_code': 0, 'ok': True}, {}
        api._send = send
        api.token, api.expires = 'old', datetime(2099, 1, 1, tzinfo=KST)
        with patch.object(kiwoom, '_SHARED_AUTH', {'token': 'old', 'expires': api.expires}), \
                patch.object(kiwoom, 'credentials', return_value=('k', 's', 'x')), \
                patch.object(kiwoom.time, 'sleep', sleeps.append), patch.object(safeio, 'log_error'):
            data, _ = api.request('ka10080', {})
        self.assertTrue(data['ok'])
        self.assertIn(kiwoom.TOKEN_REISSUE_WAIT, sleeps)


if __name__ == '__main__':
    unittest.main()


class SearchTests(unittest.TestCase):
    def setUp(self):
        import stock_search
        self.search = stock_search
        stock_search._memory.update(day='', items={})
        stock_search._last_attempt = 0.0
        self.calls = 0

    def call(self, api, body, cursor=''):
        self.calls += 1
        rows = {'0': [{'code': '005930', 'name': '삼성전자'}, {'code': '005935', 'name': '삼성전자우'}, {'code': 'bad', 'name': 'x'}],
                '10': [{'code': '086520', 'name': '에코프로'}, {'code': '247540', 'name': '에코프로비엠'}]}.get(body['mrkt_tp'], [])
        rows = rows + [{'code': f'{i:06d}', 'name': f'가상{i}'} for i in range(100000 + int(body['mrkt_tp']) * 1000, 100300 + int(body['mrkt_tp']) * 1000)]
        return {'list': rows}, {'cont-yn': 'N'}

    def test_search_ranks_exact_then_prefix_and_caches_for_the_day(self):
        with tempfile.TemporaryDirectory() as d:
            found, day = self.search.search(Path(d), '에코프로', call=self.call, extra={})
            self.assertEqual([s['code'] for s in found[:2]], ['086520', '247540'])
            self.assertEqual(found[0]['market'], '코스닥')
            self.assertEqual(self.search.search(Path(d), '00593', call=self.call)[0][0]['name'], '삼성전자')
            self.assertEqual(self.calls, len(self.search.MARKETS))                       # one lookup per market, then cached
            self.assertEqual(self.search.search(Path(d), '삼', call=self.call)[0], [])   # too short
            self.assertTrue((Path(d) / 'stock_master.json').is_file())

    def test_master_failure_falls_back_to_saved_list_and_known_names(self):
        def broken(*args):
            raise DataError('API 통신·호출 제한: 5회 조회 실패')
        with tempfile.TemporaryDirectory() as d, patch.object(safeio, 'LOG_ROOT', Path(d)):
            found, day = self.search.search(Path(d), '씨어스', call=broken, extra={'458870': '씨어스테크놀로지'})
            self.assertEqual((found, day), ([], ''))  # collected names must not masquerade as whole-market results
            self.assertEqual(self.search.search(Path(d), '씨어스', call=self.call, extra={})[0], [])   # no hammering within 10 minutes

    def test_searched_stock_can_be_observed_and_unknown_code_is_refused(self):
        import observations
        with tempfile.TemporaryDirectory() as d:
            self.search.master(Path(d), self.call)
            row, created = observations.add(Path(d), '086520', DAY, 'search', {})
            self.assertEqual((row['name'], row['source_label'], created), ('에코프로', '종목 검색', True))
            self.assertEqual(observations.add(Path(d), '086520', DAY, 'search', {})[1], False)
            with self.assertRaises(LookupError):
                observations.add(Path(d), '999999', DAY, 'search', {})
            self.assertEqual(observations.read(Path(d))[0]['code'], '086520')
