"""Offline checks for chart-only history, averages and exports."""
import copy
import io
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import app
import chart_data
from chart import render
from kiwoom import DataError, Kiwoom, parse_bar


def raw(ts, close):
    return dict(cntr_tm=ts, open_pric=str(close), high_pric=str(close+2),
                low_pric=str(close-2), cur_prc=str(close), trde_qty='10')


class Stub(Kiwoom):
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []

    def request(self, api, body, cursor=''):
        self.calls.append((api, body, cursor))
        return next(self.pages)


def page(items, cursor=''):
    return {'stk_cd': '005930_AL', 'stk_dt_pole_chart_qry': items}, {'cont-yn': 'Y' if cursor else 'N', 'next-key': cursor}


class ChartTests(unittest.TestCase):
    def test_live_ranking_uses_today_without_mutating_archive(self):
        saved = {"stock": {"code": "005930", "name": "삼성전자"}, "day": "2026-09-22"}
        with patch.object(chart_data.archive, "payload", return_value=(__import__('json').dumps(saved), False)), \
             patch.object(chart_data, "load_live", return_value={"live": True}) as fetch:
            result = chart_data.load(Path('unused'), '2026-09-22', '005930', 'minute', live=True)
        self.assertEqual(fetch.call_args.args[1], datetime.now(chart_data.KST).date().isoformat())
        self.assertEqual(fetch.call_args.args[-1], '삼성전자')
        self.assertEqual(result['archive_day'], '2026-09-22')
        self.assertEqual(saved['day'], '2026-09-22')

    def test_missing_today_minutes_never_shows_old_archive(self):
        import json
        with patch.object(chart_data.archive, "payload", return_value=(json.dumps({"stock": {"name": "삼성전자"}}), False)), \
             patch.object(chart_data, "load_live", side_effect=DataError("해당 날짜 08:00~20:00 분봉 없음")):
            with self.assertRaisesRegex(DataError, "분봉 없음"):
                chart_data.load(Path("unused"), "2026-09-22", "005930", "minute", live=True)

    def test_closed_session_restores_dated_saved_minutes_for_all_intervals(self):
        import json
        saved = {"stock": {"code": "005930", "name": "삼성전자"}, "day": "2026-09-22",
                 "bars": [parse_bar(raw("20260922090000", 100))]}
        for frame in ("minute", "minute3", "minute5"):
            with self.subTest(frame=frame), \
                 patch.object(chart_data.archive, "payload", return_value=(json.dumps(saved), False)), \
                 patch.object(chart_data.archive, "active", return_value=Path("unused")), \
                 patch.object(chart_data, "load_live", side_effect=DataError("해당 날짜 08:00~20:00 분봉 없음")):
                result = chart_data.load(Path("unused"), saved["day"], "005930", frame, live=True)
                self.assertFalse(result["live"])
                self.assertTrue(result["live_fallback"])
                self.assertEqual(result["day"], saved["day"])
                self.assertEqual(result["frame"], frame)
                self.assertEqual(result["bars"][0]["close"], 100)
                self.assertIn("저장 분봉 표시", result["chart_notice"])
        self.assertNotIn("live_fallback", saved)

    def test_live_authentication_failure_does_not_fall_back(self):
        import json
        with patch.object(chart_data.archive, "payload", return_value=(json.dumps({"stock": {"name": "삼성전자"}}), False)), \
             patch.object(chart_data, "load_live", side_effect=DataError("키움 응답 오류 코드 3")):
            with self.assertRaisesRegex(DataError, "오류 코드 3"):
                chart_data.load(Path("unused"), "2026-09-22", "005930", "minute", live=True)

    def test_live_minute_uses_short_cache_and_preserves_grouped_frame(self):
        rec = {'day': '2026-10-02', 'kind': 'preview', 'stock': {'code': '005930'},
               'bars': [parse_bar(raw('20261002090000', 100))], 'fetched_at': '2026-10-02T09:01:00+09:00'}
        with patch.object(chart_data, 'CLIENT') as api, patch.object(chart_data, 'watchlist_minute', return_value=(rec, {})) as fetch:
            api.quote.return_value = {'price': 100, 'rate': 1.0}
            result = chart_data.load_live(Path('unused'), '2026-10-02', '005930', 'minute5', '삼성전자')
        self.assertEqual(fetch.call_args.kwargs, {'ttl': 15, 'allow_previous_session': True,
                                                'history_interval': 5, 'history': False})
        self.assertEqual(result['frame'], 'minute5')
        self.assertTrue(result['live'])
        self.assertEqual(result['bars'][0]['close'], 100)

    def test_grouped_ohlcv_clock_boundaries_gaps_and_no_mutation(self):
        times = ['20260922090000','20260922090100','20260922090200',
                 '20260922090300','20260922090400','20260922091000']
        bars = [parse_bar(raw(ts, 100+i)) for i,ts in enumerate(times)]
        rec = {'bars': bars, 'day': '2026-09-22'}
        original = copy.deepcopy(rec)
        three = chart_data.grouped_record(rec, {}, 3)['bars']
        self.assertEqual([b['ts'][11:16] for b in three], ['09:00','09:03','09:09'])
        self.assertEqual([three[0][k] for k in ('open','high','low','close','volume')], [100,104,98,102,30])
        self.assertEqual(three[-1]['source_count'], 1)
        five = chart_data.grouped_record(rec, {}, 5)['bars']
        self.assertEqual([b['ts'][11:16] for b in five], ['09:00','09:10'])
        self.assertEqual(five[0]['close'],104)
        self.assertEqual(sum(b['volume'] for b in five),60)
        self.assertEqual(rec, original)

    def test_grouped_averages_use_group_closes_and_reject_future_history(self):
        for minutes in (3,5):
            start = datetime(2026,9,21,9)
            past = [raw((start+timedelta(minutes=i)).strftime('%Y%m%d%H%M%S'),100+i) for i in range(minutes*4)]
            today = [raw((datetime(2026,9,22,9)+timedelta(minutes=i)).strftime('%Y%m%d%H%M%S'),200+i) for i in range(minutes)]
            rec = {'bars':[parse_bar(b) for b in today], 'day':'2026-09-22'}
            raw_pages = {'pages':[{'stk_min_pole_chart_qry':past+today+[raw('20260922093000',999999)]}]}
            result = chart_data.grouped_record(rec,raw_pages,minutes)['bars']
            self.assertEqual(len(result),1)
            expected = sum([100+minutes*k-1 for k in (1,2,3,4)]+[200+minutes-1])/5
            self.assertEqual(result[0]['ma5'],expected)
            self.assertIsNone(result[0]['ma10'])
            self.assertEqual(result[0]['source_count'],minutes)

    def test_240_uses_previous_day_raw_without_changing_archive(self):
        start = datetime(2026,9,21,16,0)
        rows = [raw((start+timedelta(minutes=i)).strftime('%Y%m%d%H%M%S'),100+i) for i in range(239)]
        rows.append(raw('20260922090000',339))
        record = {'bars': [parse_bar(rows[-1])], 'day':'2026-09-22'}
        original = copy.deepcopy(record)
        result = chart_data.minute_record(record, {'pages':[{'stk_min_pole_chart_qry':rows[::-1]}]})
        self.assertEqual(result['bars'][0]['ma240'],219.5)
        self.assertEqual(result['bars'][0]['ma120'],279.5)
        self.assertEqual(record, original)
        self.assertEqual(len(result['bars']),1)

    def test_history_shortfall_is_null_and_averages_are_causal(self):
        bars=[{'close':i+1} for i in range(250)]
        first=chart_data.averages(copy.deepcopy(bars),(5,120,240))
        self.assertIsNone(first[238]['ma240'])
        self.assertEqual(first[239]['ma240'],120.5)
        bars[-1]['close']=999999
        second=chart_data.averages(bars,(5,120,240))
        self.assertEqual(first[:249],second[:249])

    def test_extended_minute_fetch_continues_past_session_and_keeps_archive_shape(self):
        def page_for(items, cursor=''):
            return ({'stk_cd': '005930_AL', 'stk_min_pole_chart_qry': items},
                    {'cont-yn': 'Y' if cursor else 'N', 'next-key': cursor})
        current = raw('20261113090000', 106)
        earlier = [raw('20261112090100', 104), raw('20261112090000', 103)]
        older = [raw('20261111090100', 102), raw('20261111090000', 101)]
        stub = Stub([page_for([current, *earlier], 'next'), page_for(older, 'unused')])
        bars, origin = stub.minute_bars('005930', '2026-11-13', earlier_bars=2, interval=5)
        self.assertEqual(len(stub.calls), 2)
        self.assertEqual([b['ts'][:10] for b in bars], ['2026-11-13'])
        record = {'day': '2026-11-13', 'bars': bars}
        self.assertEqual(len(chart_data.minute_view(record, origin, 'minute5')['bars']), 1)
        extended = chart_data.minute_view(record, origin, 'minute5', True)
        self.assertEqual([b['ts'][:10] for b in extended['bars']], ['2026-11-11', '2026-11-12', '2026-11-13'])

    def test_weekend_watchlist_chart_uses_latest_session_without_relabeling(self):
        day = '2026-11-14'
        previous = [raw('20261113195900', 104), raw('20261113195800', 103),
                    raw('20261112195900', 102)]
        page = ({'stk_cd': '005930_AL', 'stk_min_pole_chart_qry': previous}, {'cont-yn': 'N'})
        with self.assertRaisesRegex(DataError, '분봉 없음'):
            Stub([page]).minute_bars('005930', day)
        with tempfile.TemporaryDirectory() as folder, patch.object(chart_data,'CLIENT',Stub([page])):
            data = Path(folder)
            result = chart_data.load(data, day, '005930', 'minute', source='watchlist')
            self.assertEqual(result['requested_day'], day)
            self.assertEqual(result['day'], '2026-11-13')
            self.assertEqual(len(result['bars']), 2)
            self.assertIn('2026-11-13 최근 거래', result['chart_notice'])
            import chart_service
            seeded = chart_service.seed(data, day, '005930', 'minute', 'watchlist', None, False)
            self.assertEqual(seeded['bars'], result['bars'])
            self.assertEqual(seeded['requested_day'], day)

    def test_previous_session_never_accepts_future_minutes(self):
        page = ({'stk_cd': '005930_AL', 'stk_min_pole_chart_qry': [raw('20261116100000', 104)]},
                {'cont-yn': 'N'})
        with self.assertRaisesRegex(DataError, '요청일 이후 분봉 반환'):
            Stub([page]).minute_bars('005930', '2026-11-14', allow_previous_session=True)

    def test_weekend_fetch_continues_until_the_previous_session_is_complete(self):
        def page_for(items, cursor):
            return ({'stk_cd': '005930_AL', 'stk_min_pole_chart_qry': items},
                    {'cont-yn': 'Y', 'next-key': cursor})
        stub = Stub([page_for([raw('20261113195900', 104)], 'more'),
                     page_for([raw('20261113080000', 103), raw('20261112195900', 102)], 'unused')])
        bars, _ = stub.minute_bars('005930', '2026-11-14', allow_previous_session=True)
        self.assertEqual(len(stub.calls), 2)
        self.assertEqual([b['ts'] for b in bars], ['2026-11-13 08:00:00', '2026-11-13 19:59:00'])

    def test_invalid_cache_is_rebuilt_from_valid_chart_data(self):
        day = '2026-11-13'
        bars = [parse_bar(raw('20261113195900', 104))]
        with tempfile.TemporaryDirectory() as folder, patch.object(chart_data, 'CLIENT') as client:
            data = Path(folder)
            path = data / 'chart_minute_history_1' / day / '005930.json'
            path.parent.mkdir(parents=True)
            path.write_text('{"bars":[]}', encoding='utf-8')
            client.minute_bars.return_value = bars, {}
            loaded = chart_data.load(data, day, '005930', 'minute', source='watchlist')
            self.assertEqual(loaded['bars'][0]['close'], 104)
            self.assertEqual(chart_data.read_cache(path, day)['bars'], bars)

    def test_extended_daily_cache_and_weekly_display_use_up_to_480(self):
        history = [{'ts': (datetime(2014,1,6)+timedelta(days=i)).date().isoformat(),
                    'open':100,'high':102,'low':98,'close':100,'volume':10}
                   for i in range(3200) if i%7<5]
        day = history[-1]['ts']
        with tempfile.TemporaryDirectory() as d, patch.object(chart_data,'CLIENT') as api:
            data = Path(d)
            path = data/'chart_history'/day/'005930.json'
            path.parent.mkdir(parents=True)
            app.save(path, {'fetched_at': '2026-11-14T21:00:00+09:00', 'bars':history[-300:]})
            api.daily_bars.return_value = (history[-959:], {'pages':[]})
            result = chart_data.load(data, day, '005930', 'day', source='watchlist', history=True)
            self.assertEqual(len(result['bars']), 480)
            self.assertEqual(result['bars'][0]['ma120'], 100)
            self.assertEqual(result['bars'][0]['ma480'], 100)
            self.assertEqual(api.daily_bars.call_args.kwargs['count'], 959)
            self.assertEqual(chart_data.load(data,day,'005930','day',source='watchlist',history=True)['bars'], result['bars'])
            self.assertEqual(api.daily_bars.call_count, 1)
        self.assertLess(len(chart_data.weekly_record({'day':day}, history, '2026-11-14T21:00:00+09:00', True)['bars']), 480)
        self.assertEqual(len(chart_data.weekly_record({'day':day}, history[0:1] + [
            {**history[0], 'ts':(datetime(2014,1,13)+timedelta(weeks=i)).date().isoformat()} for i in range(500)
        ], '2026-11-14T21:00:00+09:00', True)['bars']), 480)

    def test_daily_pagination_and_future_rejected(self):
        def day(date, close):
            return {**raw('',close),'dt':date}
        client=Stub([page([day('20260922',102)],'next'),page([day('20260921',101)])])
        bars,_=client.daily_bars('005930','2026-09-22')
        self.assertEqual([b['ts'] for b in bars],['2026-09-21','2026-09-22'])
        self.assertEqual(client.calls[1][2],'next')
        self.assertEqual(client.calls[0][1],{'stk_cd':'005930_AL','base_dt':'20260922','upd_stkpc_tp':'0'})
        with self.assertRaises(DataError):
            Stub([page([day('20260923',103)])]).daily_bars('005930','2026-09-22')

    def test_monthly_history_paginates_and_uses_only_daily_bars_through_selected_date(self):
        selected = '2026-09-04'
        months = [{**raw('', 100+i), 'dt': f'{1986+i//12:04d}{i%12+1:02d}03'}
                  for i in range(8, 488)]
        months.reverse()
        client = Stub([
            page([{**raw('', 600), 'dt': '20260904'}, {**raw('', 580), 'dt': '20260901'}]),
            ({'stk_mth_pole_chart_qry': months[:240]}, {'cont-yn': 'Y', 'next-key': 'next'}),
            ({'stk_mth_pole_chart_qry': months[240:]}, {'cont-yn': 'N'}),
        ])
        with tempfile.TemporaryDirectory() as d, patch.object(chart_data, 'CLIENT', client):
            result = chart_data.load(Path(d), selected, '005930', 'month', source='watchlist')
        self.assertEqual(client.calls[1][0], 'ka10083')
        self.assertEqual(client.calls[1][1]['base_dt'], '20260831')
        self.assertEqual(client.calls[2][2], 'next')
        last = result['bars'][-1]
        self.assertEqual([last[key] for key in ('ts', 'end_ts', 'open', 'high', 'low', 'close', 'volume')],
                         ['2026-09-01', selected, 580, 602, 578, 600, 20])
        closes = sorted(int(item['cur_prc']) for item in months) + [600]
        for period in (180, 240, 360, 480):
            self.assertEqual(last[f'ma{period}'], sum(closes[-period:]) / period)
        self.assertTrue(render(result).startswith(b'\x89PNG'))

    def test_default_minute_ranges_load_previous_sessions_for_long_averages(self):
        selected = '2026-09-22'
        for interval, frame in [(1, 'minute'), (3, 'minute3'), (5, 'minute5')]:
            sessions = [datetime(2026, 9, day, 9) for day in (11, 14, 15, 16, 17, 18, 21)]
            times = [start + timedelta(minutes=i*interval) for start in sessions for i in range(78)][-479:]
            items = [raw(t.strftime('%Y%m%d%H%M%S'), 100+i) for i, t in enumerate(times)]
            today = raw('20260922090000', 579)
            bars = [parse_bar(today)]
            origin = {'pages': [{'stk_min_pole_chart_qry': [*items, today]}]}
            with self.subTest(frame=frame), tempfile.TemporaryDirectory() as d, patch.object(chart_data, 'CLIENT') as api:
                api.minute_bars.return_value = bars, origin
                result = chart_data.load(Path(d), selected, '005930', frame, source='watchlist')
                self.assertEqual(api.minute_bars.call_args.kwargs['earlier_bars'], 479)
                self.assertEqual(api.minute_bars.call_args.kwargs['interval'], interval)
                self.assertEqual(len(result['bars']), 1)
                for period in (180, 240, 360, 480):
                    self.assertEqual(result['bars'][0][f'ma{period}'], (579 + 580 - period) / 2)

    def test_daily_warmup_cache_and_archive_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            data=Path(d)
            day='2026-09-22';code='005930'
            folder=data/day/'final';folder.mkdir(parents=True)
            app.save(folder/'index.json',{'revision':'r1','kind':'final'})
            rec={'day':day,'kind':'final','stock':{'code':code,'name':'삼성전자'},'bars':[parse_bar(raw('20260922090000',100))]}
            app.save(folder/(code+'.json'),rec)
            before=(folder/(code+'.json')).read_bytes()
            history=[{**parse_bar(raw('20260922090000',100+i)),'ts':(datetime(2025,1,1)+timedelta(days=i)).strftime('%Y-%m-%d')} for i in range(300)]
            with patch.object(chart_data,'CLIENT') as api:
                api.daily_bars.return_value=(history,{'pages':[]})
                r=chart_data.load(data,day,code,'day','r1')
                self.assertEqual(len(r['bars']),180)
                self.assertEqual(r['bars'][0]['ma120'],160.5)
                chart_data.load(data,day,code,'day','r1')
                self.assertEqual(api.daily_bars.call_count,1)
                with self.assertRaises(DataError):
                    chart_data.load(data,day,code,'day','wrong')
            self.assertEqual(before,(folder/(code+'.json')).read_bytes())
            self.assertTrue((data/'chart_history'/day/(code+'.sha256')).is_file())

    def test_weekly_uses_monday_boundary_and_daily_ohlcv(self):
        days = [
            dict(ts='2026-09-18',open=90,high=110,low=88,close=100,volume=10),
            dict(ts='2026-09-21',open=101,high=115,low=99,close=110,volume=20),
            dict(ts='2026-09-22',open=111,high=120,low=105,close=118,volume=30),
        ]
        original = copy.deepcopy(days)
        result = chart_data.weekly_record({'day':'2026-09-22'}, days, '2026-09-22T20:05:00+09:00')
        bars = result['bars']
        self.assertEqual([b['ts'] for b in bars], ['2026-09-14','2026-09-21'])
        self.assertEqual([bars[-1][k] for k in ('open','high','low','close','volume')], [101,120,99,118,50])
        self.assertEqual(bars[-1]['end_ts'], '2026-09-22')
        self.assertIsNone(bars[-1]['ma5'])
        self.assertEqual(days, original)

    def test_watchlist_chart_has_separate_cache_from_ranking(self):
        with tempfile.TemporaryDirectory() as d:
            data=Path(d);day='2026-09-22';code='005930'
            bars=[parse_bar(raw('20260922090000',100))]
            with patch.object(chart_data,'CLIENT') as api:
                api.minute_bars.return_value=(bars, {'pages':[]})
                result=chart_data.load(data,day,code,'minute',source='watchlist',name='삼성전자')
                self.assertEqual(result['bars'][0]['close'],100)
                self.assertEqual(result['source'],'watchlist')
                self.assertTrue((data/'chart_minute_history_1'/day/(code+'.json')).is_file())
                self.assertFalse((data/day).exists())

    def test_current_quotes_batch_preserves_signed_rate(self):
        client = Stub([({'atn_stk_infr': [
            {'stk_cd': '005930', 'cur_prc': '-70000', 'flu_rt': '-2.50'},
            {'stk_cd': '000660', 'cur_prc': '+90000', 'flu_rt': '+1.25'}]}, {})])
        result = client.quotes(['005930', '000660'])
        self.assertEqual(result['005930']['price'], 70000)
        self.assertEqual(result['005930']['rate'], -2.5)
        self.assertEqual(client.calls[0][1]['stk_cd'], '005930_AL|000660_AL')

    def test_current_quotes_rejects_other_symbol(self):
        client = Stub([({'atn_stk_infr': [{'stk_cd': '000660'}]}, {})])
        with self.assertRaisesRegex(DataError, '불일치'):
            client.quotes(['005930'])

    def test_png_both_frames(self):
        for frame in ('minute','minute3','minute5','day','week'):
            bars=[parse_bar(raw('20260922090000',100+i)) for i in range(250)]
            for i,b in enumerate(bars):
                b['ts']=(datetime(2026,1,1)+timedelta(days=i)).strftime('%Y-%m-%d') if frame in ('day','week') else (datetime(2026,9,22,9)+timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S')
            chart_data.averages(bars,chart_data.PERIODS[frame])
            record={'frame':frame,'bars':bars,'stock':{'code':'005930','name':'삼성전자'},'day':'2026-09-22','kind':'final'}
            image=Image.open(io.BytesIO(render(record)))
            self.assertEqual(image.size,(1500,900))


if __name__=='__main__':
    unittest.main()
