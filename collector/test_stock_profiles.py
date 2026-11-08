import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import stock_profiles as profiles


class StockProfilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        profiles.REQUESTED.clear()
        profiles.LAST_SCAN = 0

    def test_all_collected_lists_are_included(self):
        theme = {'themes': [{'name': '로봇', 'member_codes': ['000003'],
                             'leaders': [{'code': '000004', 'name': 'D'}]}], 'custom': []}
        flows = {'markets': {'all': {'rankings': {'foreign': [{'code': '000005', 'name': 'E'}],
                                                'institution': []}}}}
        with patch.object(profiles.archive, 'active', return_value=self.data), \
             patch.object(profiles.archive, 'metadata', return_value={'stocks': [{'code': '000001', 'name': 'A'}]}), \
             patch.object(profiles.volume_surge, 'metadata', return_value={'stocks': [{'code': '000002', 'name': 'B'}], 'tracked': []}), \
             patch.object(profiles.themes, 'read_day', return_value=theme), \
             patch.object(profiles.investor_flows, 'read_day', return_value=flows):
            stocks, _, _ = profiles.collect(self.data, '2026-10-23')
        self.assertEqual(set(stocks), {'000001', '000002', '000003', '000004', '000005'})

    def test_absolute_rankings_join_common_profiles(self):
        for folder, code in [('volume_top', '000011'), ('amount_top', '000012')]:
            target = self.data / folder / '2026-10-23' / 'index.json'
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({'stocks': [{'code': code, 'name': code}]}), encoding='utf-8')
        stocks, _, _ = profiles.collect(self.data, '2026-10-23')
        self.assertIn('000011', stocks)
        self.assertIn('000012', stocks)

    def test_dated_profile_retains_membership_and_same_day_cap(self):
        stocks = {'000001': {'code': '000001', 'name': 'A'}}
        theme = {'themes': [{'name': '로봇', 'member_codes': ['000001']}], 'custom': []}
        with patch.object(profiles, 'collect', return_value=(stocks, {'stocks': [{'code': '000001', 'market_cap': 1200}]}, theme)), patch.object(profiles.stock_sectors, 'read', return_value={}):
            profiles.view(self.data, '2026-10-23')
        (self.data / 'market_caps.json').write_text(json.dumps({'items': {'000001': {'market_cap': 9999, 'day': '2026-10-26'}}}), encoding='utf-8')
        with patch.object(profiles, 'collect', return_value=(stocks, {'stocks': []}, {})), patch.object(profiles.stock_sectors, 'read', return_value={}):
            found = profiles.view(self.data, '2026-10-23')['profiles']['000001']
        self.assertEqual(found['themes'], ['로봇'])
        self.assertEqual((found['market_cap'], found['cap_day']), (1200, '2026-10-23'))

    def test_theme_industry_and_cap_date_remain_distinct(self):
        stocks = {'000001': {'code': '000001', 'name': 'A'}, '000002': {'code': '000002', 'name': 'B'}}
        volume = {'stocks': [{'code': '000001', 'market_cap': 1200}], 'tracked': []}
        theme = {'themes': [{'name': '로봇', 'member_codes': ['000001'], 'leaders': []}], 'custom': []}
        (self.data/'market_caps.json').write_text(json.dumps({'items': {'000002': {'market_cap': 900, 'day': '2026-10-23'}}}), encoding='utf-8')
        with patch.object(profiles, 'collect', return_value=(stocks, volume, theme)), \
             patch.object(profiles.stock_sectors, 'read', return_value={'000002': {'labels': ['반도체']}}):
            found = profiles.view(self.data, '2026-10-22')['profiles']
        self.assertEqual(found['000001']['themes'], ['로봇'])
        self.assertEqual((found['000001']['market_cap'], found['000001']['cap_day']), (1200, '2026-10-22'))
        self.assertEqual(found['000002']['industry'], '반도체')
        self.assertEqual((found['000002']['market_cap'], found['000002']['cap_day']), (900, '2026-10-23'))

    def test_current_watchlist_group_is_labeled_separately_from_kiwoom_theme(self):
        today = profiles.datetime.now(profiles.KST).date().isoformat()
        stocks = {'000001': {'code': '000001', 'name': 'A'}}
        groups = [{'number': 3, 'name': '반도체 관심', 'entries': [{'type': 'stock', 'code': '000001'}]},
                  {'number': 98, 'name': '분류 제외', 'entries': [{'type': 'stock', 'code': '000001'}]}]
        with patch.object(profiles, 'collect', return_value=(stocks, {'stocks': [], 'tracked': []}, {'themes': [], 'custom': []})), \
             patch.object(profiles.stock_sectors, 'read', return_value={}), \
             patch.object(profiles.watchlists, 'groups', return_value=groups):
            row = profiles.view(self.data, today)['profiles']['000001']
        self.assertEqual(row['themes'], [])
        self.assertEqual(row['groups'], ['반도체 관심'])

    def test_only_matching_quote_date_is_saved(self):
        stocks = {'000001': {'code': '000001', 'name': 'A'}, '000002': {'code': '000002', 'name': 'B'}}
        def quote(_):
            return {'000001': {'date': '20261023', 'market_cap': 1200},
                    '000002': {'date': '20261022', 'market_cap': 900}}
        with patch.object(profiles, 'collect', return_value=(stocks, {'stocks': [], 'tracked': []}, {})), \
             patch.object(profiles.stock_sectors, 'ensure', return_value=False), \
             patch.object(profiles.threading, 'Thread', side_effect=lambda target, **kw: SimpleNamespace(start=target)), \
             patch.object(profiles.time, 'sleep'):
            self.assertTrue(profiles.tick(self.data, '2026-10-23', quote))
        saved = profiles._read_caps(self.data)
        self.assertEqual(saved['000001']['market_cap'], 1200)
        self.assertNotIn('market_cap', saved['000002'])


if __name__ == '__main__':
    unittest.main()
