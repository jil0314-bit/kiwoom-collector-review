import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import stock_sectors as sectors


class SectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def run_now(self, stocks, fetch):
        with patch.object(sectors.threading, 'Thread', side_effect=lambda target, **kw: SimpleNamespace(start=target)), patch.object(sectors.time, 'sleep'):
            return sectors.ensure(self.data, stocks, fetch)

    def test_parse_does_not_guess_from_company_text(self):
        self.assertEqual(sectors.parse_sector('<span>WI26 : 반도체</span>'), '반도체')
        self.assertIsNone(sectors.parse_sector('AI 로봇 회사입니다.'))
        self.assertIsNone(sectors.parse_sector('<span>WI26 : N/A</span>'))

    def test_curated_label_wins_and_needs_no_network(self):
        curated = {'items': {'005930': {'labels': ['검증 분류']}}}
        (self.data/'theme_classifications.json').write_text(json.dumps(curated), encoding='utf-8')
        self.assertFalse(self.run_now([{'code': '005930'}], lambda _: self.fail('network called')))
        self.assertEqual(sectors.read(self.data)['005930']['labels'], ['검증 분류'])

    def test_new_symbol_is_saved_and_duplicates_only_fetch_once(self):
        calls = []
        def fetch(symbol):
            calls.append(symbol)
            return {'labels': ['반도체'], 'checked_epoch': sectors.time.time(), 'url': 'https://example.test'}
        stocks = [{'code': '005930', 'name': '삼성전자'}]*2
        self.assertTrue(self.run_now(stocks, fetch))
        self.assertEqual(calls, ['005930'])
        self.assertEqual(sectors.read(self.data)['005930']['name'], '삼성전자')
        self.assertFalse(self.run_now(stocks, fetch))

    def test_failure_is_not_a_classification_and_is_backed_off(self):
        def fail(_):
            raise TimeoutError()
        stocks = [{'code': '005930'}]
        self.assertTrue(self.run_now(stocks, fail))
        self.assertFalse(sectors.read(self.data)['005930'].get('labels'))
        self.assertFalse(self.run_now(stocks, lambda _: self.fail('retried too soon')))

    def test_old_success_is_preserved_on_refresh_failure(self):
        sectors._save(self.data, {'005930': {'labels': ['반도체'], 'checked_epoch': 1}})
        self.run_now([{'code': '005930'}], lambda _: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(sectors.read(self.data)['005930']['labels'], ['반도체'])


if __name__ == '__main__':
    unittest.main()
