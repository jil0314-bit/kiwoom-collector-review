"""Product exclusion, pagination and failure preservation for absolute volume ranks."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import volume_top as v
from kiwoom import DataError


def stock(code, volume=100):
    return dict(stk_cd=code, stk_nm=code, cur_prc='-1000', flu_rt='-1.5',
                trde_qty=str(volume), trde_tern_rt='2', trde_amt='10')


class VolumeTopTests(unittest.TestCase):
    def setUp(self):
        v.CLASS_CACHE.clear()

    def fake(self, api, body, cursor=''):
        if api == 'ka10099':
            return {'list': [{'code': {'8': '900001', '3': '900002', '60': '900003',
                                       '70': '900004', '90': '900005'}[body['mrkt_tp']]}]}, {}
        if api == 'ka10095':
            return {'atn_stk_infr': [{'stk_cd': body['stk_cd'], 'dt': '20261023'}]}, {}
        if not cursor:
            return {'tdy_trde_qty_upper': [stock(f'{i:06}', 1000000-i) for i in range(900001, 900006)] +
                    [stock(f'{i:06}', 1000-i) for i in range(1, 51)]}, {'cont-yn': 'Y', 'next-key': 'p2'}
        return {'tdy_trde_qty_upper': [stock(f'{i:06}', 1000-i) for i in range(50, 110)]}, {}

    def test_exclude_and_refill_100_with_duplicate_page_boundary(self):
        r = v.ranking(self.fake)
        self.assertEqual(len(r['stocks']), 100)
        self.assertEqual(r['stocks'][0]['code'], '000001')
        self.assertEqual(r['stocks'][-1]['rank'], 100)
        self.assertNotIn('900001', {s['code'] for s in r['stocks']})
        self.assertNotIn('900002', {s['code'] for s in r['stocks']})
        self.assertTrue({f'{i:06}' for i in range(900001, 900006)}.isdisjoint(s['code'] for s in r['stocks']))
        self.assertEqual(r['excluded_from_response'], 5)
        self.assertEqual(r['request']['mang_stk_incls'], '16')
        self.assertEqual(r['stocks'][0]['rate'], -1.5)
        self.assertEqual(r['stocks'][0]['price'], 1000)

    def test_missing_classification_fails_closed(self):
        with self.assertRaises(DataError):
            v.ranking(lambda *args: ({}, {}))

    def test_trading_value_order_is_not_volume_order(self):
        def call(api, body, cursor=''):
            if api == 'ka10030':
                self.assertEqual(body['sort_tp'], '3')
                return {'tdy_trde_qty_upper': [dict(stock('000001', 100), trde_amt='500'),
                                              dict(stock('000002', 1000), trde_amt='100')]}, {}
            return self.fake(api, body, cursor)
        r = v.ranking(call, sort='3')
        self.assertEqual(r['request']['sort_tp'], '3')
        self.assertEqual([s['code'] for s in r['stocks']], ['000001', '000002'])
        self.assertEqual(v.BODY['sort_tp'], '1')

    def test_amount_archive_is_separate_from_volume(self):
        import amount_top as amount
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            record = {'day': '2026-10-23', 'stocks': [{'code': '000001'}]}
            with patch.object(v, 'ranking', return_value=record) as query, patch.object(amount, 'LAST', 0):
                self.assertEqual(amount.start(data), 'started')
                self.assertTrue(amount.LOCK.acquire(timeout=3))
                amount.LOCK.release()
                query.assert_called_once_with(sort='3')
            self.assertEqual(amount.read(data, '2026-10-23'), record)
            self.assertFalse((data / 'volume_top').exists())
            self.assertFalse((data / 'volume_surge').exists())

    def test_repeated_classification_cursor_rejected(self):
        with self.assertRaises(DataError):
            v.ranking(lambda *args: ({'list': [{'code': '900001'}]}, {'cont-yn': 'Y', 'next-key': 'same'}))

    def test_small_market_returns_only_available(self):
        def call(api, body, cursor=''):
            if api == 'ka10030':
                return {'tdy_trde_qty_upper': [stock('000001')]}, {}
            return self.fake(api, body, cursor)
        self.assertEqual(len(v.ranking(call)['stocks']), 1)

    def test_failure_does_not_overwrite_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            target = data / 'volume_top' / '2026-10-23' / 'index.json'
            target.parent.mkdir(parents=True)
            target.write_text('{"keep":true}')
            with patch.object(v, 'ranking', side_effect=DataError('expected')), patch.object(v, 'LAST', 0):
                self.assertEqual(v.start(data), 'started')
                self.assertTrue(v.LOCK.acquire(timeout=3))
                v.LOCK.release()
            self.assertEqual(target.read_text(), '{"keep":true}')
            self.assertFalse(v.STATE['busy'])


if __name__ == '__main__':
    unittest.main()
