import unittest
from datetime import datetime
from unittest.mock import patch

import market_index as m
from kiwoom import DataError, KST


class MarketIndexTests(unittest.TestCase):
    def test_direction_and_signed_index_price(self):
        for sign, rate, change, direction in [('2', '+1.20', '+30', 'up'), ('5', '-1.20', '-30', 'down'),
                                               ('3', '0', '0', 'flat'), ('5', '-0.00', '-0.01', 'down')]:
            with self.subTest(direction=direction, rate=rate):
                parsed = m.parse(dict(cur_prc='-2500.20', flu_rt=rate, pred_pre=change, pred_pre_sig=sign))
                self.assertEqual(parsed['value'], 2500.20)
                self.assertEqual(parsed['direction'], direction)

    def test_missing_and_conflicting_values_are_not_flat(self):
        for payload in [{}, dict(cur_prc='2500', flu_rt='-1', pred_pre='-25', pred_pre_sig='2'),
                        dict(cur_prc='2500', flu_rt='NaN', pred_pre='0', pred_pre_sig='3')]:
            with self.subTest(payload=payload), self.assertRaises(DataError):
                m.parse(payload)

    def test_single_flight_and_failed_refresh_are_neutral(self):
        state = dict(busy=False, attempt=float('-inf'), updated=0, snapshot=None, error='')
        with patch.object(m, '_state', state), patch.object(m.time, 'monotonic', return_value=100), \
                patch.object(m.threading.Thread, 'start') as start:
            for _ in range(8):
                self.assertEqual(m.read()['direction'], 'unknown')
            self.assertEqual(start.call_count, 1)
        state.update(snapshot=dict(name='KOSPI', direction='up', rate=1,
                     fetched_at=datetime.now(KST).isoformat()), busy=False, attempt=100, updated=100)
        with patch.object(m, '_state', state), patch.object(m.time, 'monotonic', return_value=110):
            self.assertTrue(m.read()['ready'])
            state['error'] = 'fixture failure'
            self.assertFalse(m.read()['ready'])

    def test_expired_previous_day_and_thread_failure_are_neutral(self):
        state = dict(busy=True, attempt=100, updated=100, error='',
                     snapshot=dict(name='KOSPI', direction='up', rate=1, fetched_at='2020-01-01T10:00:00+09:00'))
        with patch.object(m, '_state', state), patch.object(m.time, 'monotonic', return_value=110):
            self.assertEqual(m.read()['direction'], 'unknown')
        state.update(busy=False, attempt=float('-inf'))
        with patch.object(m, '_state', state), patch.object(m.threading.Thread, 'start', side_effect=RuntimeError):
            self.assertFalse(m.read()['pending'])

    def test_request_uses_kospi_summary_and_does_not_paginate(self):
        state = dict(busy=True, attempt=0, updated=0, snapshot=None, error='')
        payload = dict(cur_prc='2500', flu_rt='+1', pred_pre='+25', pred_pre_sig='2')
        with patch.object(m, '_state', state), patch('volume_surge.request', return_value=(payload, {'cont-yn':'Y'})) as call:
            m._fetch()
            call.assert_called_once_with('ka20001', {'mrkt_tp':'0', 'inds_cd':'001'})
            self.assertFalse(state['busy'])
            self.assertEqual(state['snapshot']['direction'], 'up')


if __name__ == '__main__':
    unittest.main()
