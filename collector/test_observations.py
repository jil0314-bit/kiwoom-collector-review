import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import observations
import stock_profiles


class ObservationsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data = Path(self.directory.name)
        self.day = '2026-11-11'
        snapshot = self.data / self.day / 'final'
        snapshot.mkdir(parents=True)
        (snapshot / 'index.json').write_text(json.dumps({'stocks': [
            {'code': '005930', 'name': '삼성전자'}, {'code': '000660', 'name': 'SK하이닉스'}
        ]}), encoding='utf-8')

    def test_dated_entries_survive_snapshot_loss_and_can_be_removed(self):
        first, created = observations.add(self.data, '005930', self.day)
        self.assertTrue(created)
        second, _ = observations.add(self.data, '000660', self.day)
        self.assertEqual(first['source_day'], self.day)
        self.assertTrue(first['added_at'].endswith('+09:00'))
        (self.data / self.day / 'final' / 'index.json').unlink()
        self.assertEqual(observations.read(self.data), [second, first])
        self.assertEqual(observations.add(self.data, '005930', self.day), (first, False))
        self.assertIn('005930', stock_profiles.collect(self.data, self.day)[0])
        self.assertEqual(observations.remove(self.data, '005930'), [second])
        self.assertEqual(observations.read(self.data), [second])

    def test_concurrent_adds_keep_one_entry(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: observations.add(self.data, '005930', self.day), range(6)))
        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(len(observations.read(self.data)), 1)
        self.assertEqual({row['added_at'] for row, _ in results}, {observations.read(self.data)[0]['added_at']})

    def test_unknown_stock_does_not_create_entry(self):
        with self.assertRaises(LookupError):
            observations.add(self.data, '999999', self.day)
        self.assertEqual(observations.read(self.data), [])

    def test_each_tab_saves_its_source_in_the_shared_list(self):
        stock = {'code': '000660', 'name': 'SK하이닉스'}
        stocks = {'stocks': [stock]}
        investor = {'markets': {'KOSPI': {'rankings': {'foreign': [stock]}}}}
        cases = [
            ('volume', 'volume_surge.metadata', {'stocks': [], 'tracked': [stock]}, {}),
            ('volume-top', 'volume_top.read', stocks, {}),
            ('amount-top', 'amount_top.read', stocks, {}),
            ('theme', 'themes.read_day', {'custom': [{'leaders': [stock]}]}, {}),
            ('investor', 'investor_flows.read_day', investor, {'market': 'KOSPI'}),
            ('investor', 'investor_flows.read_period', investor, {'market': 'KOSPI', 'start': '2026-11-10'}),
            ('recommendations', 'recommendations.read', stocks, {}),
        ]
        for source, reader, record, context in cases:
            with self.subTest(source=source, reader=reader), patch(reader, return_value=record):
                row, created = observations.add(self.data, stock['code'], self.day, source, context)
                self.assertTrue(created)
                self.assertEqual(row['source'], source)
                self.assertEqual(row['source_day'], self.day)
                self.assertEqual(observations.read(self.data), [row])
                observations.remove(self.data, stock['code'])
