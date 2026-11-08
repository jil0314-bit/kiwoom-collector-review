"""Offline checks for collector-wide quote pacing and token recovery."""
import unittest
from unittest.mock import patch

import kiwoom


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        kiwoom._SHARED_AUTH.update(token='', expires=kiwoom.datetime.min.replace(tzinfo=kiwoom.KST))
        kiwoom._RATE_LAST = 0.0

    def tearDown(self):
        kiwoom._SHARED_AUTH.update(token='', expires=kiwoom.datetime.min.replace(tzinfo=kiwoom.KST))
        kiwoom._RATE_LAST = 0.0

    def test_two_collector_clients_share_one_token(self):
        calls = []
        def transport(path, body, headers):
            calls.append((path, headers.get('authorization')))
            if path == '/oauth2/token':
                return {'return_code': 0, 'token': 'test-token', 'expires_dt': '20991231000000'}, {}
            return {'return_code': 0}, {}
        a, b = (kiwoom.Kiwoom(interval=0, transport=transport) for _ in range(2))
        a.shared = b.shared = True
        with patch.object(kiwoom, 'credentials', return_value=('test-key', 'test-secret', 'test')):
            a.request('ka10095', {'stk_cd': '005930_AL'})
            b.request('ka10095', {'stk_cd': '000660_AL'})
        self.assertEqual([path for path, _ in calls].count('/oauth2/token'), 1)
        self.assertEqual([auth for path, auth in calls if path != '/oauth2/token'],
                         ['Bearer test-token', 'Bearer test-token'])

    def test_revoked_token_refreshes_once_then_second_client_reuses_it(self):
        issued = []
        def transport(path, body, headers):
            if path == '/oauth2/token':
                issued.append('token')
                return {'return_code': 0, 'token': 't' + str(len(issued)),
                        'expires_dt': '20991231000000'}, {}
            if headers['authorization'] == 'Bearer t1':
                return {'return_code': 3}, {}
            return {'return_code': 0}, {}
        a, b = (kiwoom.Kiwoom(interval=0, transport=transport) for _ in range(2))
        a.shared = b.shared = True
        with patch.object(kiwoom, 'credentials', return_value=('test-key', 'test-secret', 'test')):
            a.request('ka10095', {'stk_cd': '005930_AL'})
            b.request('ka10095', {'stk_cd': '000660_AL'})
        self.assertEqual(len(issued), 2)
        self.assertEqual(b.token, 't2')

    def test_rate_limit_honors_retry_after_without_network(self):
        calls = []
        def transport(path, body, headers):
            calls.append(path)
            return ({'return_code': 1700}, {'Retry-After': '3'}) if len(calls) == 1 else ({'return_code': 0}, {})
        client = kiwoom.Kiwoom(interval=0, transport=transport)
        sleeps = []
        with patch.object(kiwoom.time, 'sleep', side_effect=sleeps.append):
            client._send('/test', {}, {})
        self.assertEqual(len(calls), 2)
        self.assertIn(3.0, sleeps)

    def test_separate_clients_use_one_start_interval(self):
        def transport(path, body, headers):
            return {'return_code': 0}, {}
        a, b = (kiwoom.Kiwoom(interval=1, transport=transport) for _ in range(2))
        a.shared = b.shared = True
        sleeps = []
        with patch.object(kiwoom.time, 'monotonic', side_effect=[10, 10, 10, 11]), \
             patch.object(kiwoom.time, 'sleep', side_effect=sleeps.append):
            a._send('/test', {}, {})
            b._send('/test', {}, {})
        self.assertEqual(sleeps, [0, 1])


if __name__ == '__main__':
    unittest.main()
