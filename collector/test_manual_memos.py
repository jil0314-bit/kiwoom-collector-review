"""Offline regressions for manual picks and shared personal memos."""
import json
import tempfile
import unittest
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import notes
import recommendations
import app


class ManualMemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)

    def manual(self, code='005930'):
        with patch('stock_search.lookup', return_value={'code': code, 'name': '검증종목'}), \
                patch.object(recommendations, 'stamp', return_value='2026-11-25T00:00:01+09:00'):
            return recommendations.add_manual(self.data, code)

    def test_input_date_duplicate_and_collection_retention(self):
        record, created = self.manual()
        self.assertTrue(created)
        self.assertEqual(record['recommended_date'], '2026-11-25')
        self.assertEqual(record['recommended_time'], '00:00:01')
        self.assertFalse(self.manual()[1])
        recommendations.merge(self.data, '2026-11-25', [dict(record, id='news', url='https://example.test/news', manual=False)])
        recommendations.merge(self.data, '2026-11-25', [dict(record, id='updated', url='https://example.test/news', manual=False)])
        stored = recommendations.read(self.data, '2026-11-25')['records']
        self.assertEqual({r['id'] for r in stored}, {record['id'], 'updated'})
        self.assertEqual(len(recommendations.read(self.data, '2026-11-24')['records']), 0)

    def test_unknown_stock_rejected(self):
        with patch('stock_search.lookup', return_value=None), self.assertRaises(ValueError):
            recommendations.add_manual(self.data, '005930')
        self.assertEqual(recommendations.days(self.data), [])

    def test_manual_registration_preserves_existing_memo(self):
        note = notes.write(self.data, '2026-11-25', '005930', '기존 개인 사유')
        self.manual()
        self.assertEqual(notes.read_day(self.data, '2026-11-25')['005930'], note)

    def test_latest_uses_last_edit_and_empty_does_not_hide_history(self):
        old = notes.write(self.data, '2026-11-23', '005930', '과거 메모')
        newer = notes.write(self.data, '2026-11-24', '005930', '최근 메모')
        self.assertEqual(notes.latest(self.data, ['005930'])['005930']['text'], '최근 메모')
        notes.write(self.data, '2026-11-24', '005930', '', newer['revision'])
        self.assertEqual(notes.latest(self.data, ['005930'])['005930']['text'], '과거 메모')
        self.assertEqual(notes.latest(self.data, ['000660']), {})

    def test_stale_revision_cannot_overwrite_and_invalid_code_rejected(self):
        note = notes.write(self.data, '2026-11-25', '005930', '첫 메모')
        notes.write(self.data, '2026-11-25', '005930', '다른 창 수정', note['revision'])
        with self.assertRaises(notes.Conflict):
            notes.write(self.data, '2026-11-25', '005930', '오래된 창 수정', note['revision'])
        self.assertEqual(notes.latest(self.data, ['005930'])['005930']['text'], '다른 창 수정')
        with self.assertRaises(Exception):
            notes.latest(self.data, ['../../secret'])

    def test_concurrent_manual_registration_is_idempotent(self):
        with patch('stock_search.lookup', return_value={'code': '005930', 'name': '검증종목'}), \
                patch.object(recommendations, 'stamp', return_value='2026-11-25T12:00:00+09:00'):
            with ThreadPoolExecutor(max_workers=4) as pool:
                result = list(pool.map(lambda _: recommendations.add_manual(self.data, '005930'), range(8)))
        self.assertEqual(sum(created for _, created in result), 1)
        self.assertEqual(len(recommendations.read(self.data, '2026-11-25')['records']), 1)

    def test_http_auth_input_date_and_memo_readback(self):
        server = app.CollectorHTTPServer(('127.0.0.1', 0), app.Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(app, 'DATA', self.data), patch.object(app, 'PORT', port), \
                    patch.object(app, 'TOKEN', 'fixture'), \
                    patch('stock_search.lookup', return_value={'code': '005930', 'name': '검증종목'}), \
                    patch.object(recommendations, 'stamp', return_value='2026-11-25T12:00:00+09:00'):
                def request(path, body=None, token='fixture'):
                    return json.load(urlopen(Request('http://127.0.0.1:'+str(port)+path,
                        data=json.dumps(body).encode() if body is not None else None,
                        headers={'Content-Type': 'application/json', 'X-Collector-Token': token})))
                with self.assertRaises(HTTPError) as failure:
                    request('/api/recommendations/manual', {'code': '005930'}, token='wrong')
                self.assertEqual(failure.exception.code, 403)
                result = request('/api/recommendations/manual', {'code': '005930', 'day': '2020-01-01'})
                self.assertEqual(result['record']['recommended_date'], '2026-11-25')
                request('/api/notes', {'code': '005930', 'day': '2026-11-25', 'text': '검증 메모'})
                self.assertEqual(request('/api/notes/latest?codes=005930')['notes']['005930']['text'], '검증 메모')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
