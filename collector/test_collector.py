"""Focused offline tests. No account, network or real archive writes."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
import app
import archive
from kiwoom import Kiwoom, DataError, code_of, parse_bar


def row(ts, close=100):
    return dict(cntr_tm=ts, open_pric='-100', high_pric='+110', low_pric='90', cur_prc=str(close), trde_qty='20')


class Stub(Kiwoom):
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []

    def request(self, api, body, cursor=''):
        self.calls.append((api, body.copy(), cursor))
        return next(self.pages)


def page(rows, continuation=False, cursor=''):
    return ({'stk_cd': '005930_AL', 'stk_min_pole_chart_qry': rows},
            {'cont-yn': 'Y' if continuation else 'N', 'next-key': cursor})


class Tests(unittest.TestCase):
    def test_deleted_optional_watchlist_group_does_not_hide_valid_groups(self):
        import watchlists
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'Portfolio.dat'
            file.write_text('[003]\nGName=관심\nItemCnt=1\n000=005930;0;\n', encoding='cp949')
            groups = watchlists.groups(file)
            self.assertEqual([g['number'] for g in groups], [3])
            self.assertEqual(groups[0]['entries'][0]['code'], '005930')
            file.write_text('[003]\nGName=관심\nItemCnt=2\n000=005930;0;\n', encoding='cp949')
            with self.assertRaises(DataError):
                watchlists.groups(file)

    def test_codes_and_prices(self):
        self.assertEqual(code_of('0200G0_AL'), '0200G0')
        self.assertEqual(code_of('A005930'), '005930')
        with self.assertRaises(DataError):
            code_of('../x')
        self.assertEqual(parse_bar(row('20260922080000', '-101'))['close'], 101)
        with self.assertRaises(DataError):
            parse_bar(row('20260922080000', 200))

    def test_pagination_causal_ma_and_no_filled_minutes(self):
        a = Stub([page([row('20260922080200', 102), row('20260922080000', 100)], True, 'a'),
                  page([row('20260921195900', 99), row('20260921195800', 98), row('20260921195700', 97)])])
        bars, raw = a.minute_bars('005930', '2026-09-22')
        self.assertEqual(len(bars), 2)
        self.assertIsNone(bars[0]['ma5'])
        self.assertEqual(bars[1]['ma5'], 99.2)
        self.assertEqual(a.calls[1][2], 'a')
        self.assertEqual(a.calls[0][1]['base_dt'], '20260922')

    def test_conflicting_duplicates_fail(self):
        a = Stub([page([row('20260922090000')], True, 'a'), page([row('20260922090000', 101)])])
        with self.assertRaisesRegex(DataError, '충돌'):
            a.minute_bars('005930', '2026-09-22')

    def test_future_date_response_fails(self):
        a = Stub([page([row('20260923090000'), row('20260922090000')])])
        with self.assertRaisesRegex(DataError, '요청일 이후'):
            a.minute_bars('005930', '2026-09-22')

    def test_latest_replaces_old_and_failed_update_preserves_it(self):
        with tempfile.TemporaryDirectory() as d, patch.object(app,'DATA',Path(d)), patch.object(app,'now',return_value=AT):
            api=Fake()
            legacy=Path(d)/DAY/'preview'
            app.save(legacy/'index.json', {'day':DAY,'kind':'preview','ranking_at':DAY+'T09:00:00+09:00','stocks':[]})
            older=Path(d)/'2026-09-21'/'final'
            app.save(older/'index.json', {'marker':'preserve previous date'})
            first=app.collect(DAY,api=api)
            first_path=archive.active(Path(d),DAY)
            self.assertFalse(legacy.exists())
            api.codes=['005930','000100']
            second=app.collect(DAY,api=api)
            second_path=archive.active(Path(d),DAY)
            self.assertFalse(first_path.exists())
            self.assertNotEqual(first['revision'],second['revision'])
            self.assertEqual(api.ranks,2)
            self.assertFalse((second_path/'000660.json').exists())
            self.assertTrue((second_path/'000100.json').exists())
            api.fail=True
            with self.assertRaisesRegex(DataError,'기존 자료 유지'):
                app.collect(DAY,api=api)
            self.assertEqual(archive.active(Path(d),DAY),second_path)
            self.assertEqual(len(list((Path(d)/DAY).glob('snapshot-*'))),1)
            self.assertTrue((older/'index.json').exists())
            data,stale=archive.payload(Path(d),DAY,'005930',revision=first['revision'])
            self.assertTrue(stale)
            self.assertIsNone(data)
            data,stale=archive.payload(Path(d),DAY,'005930',revision=second['revision'])
            self.assertFalse(stale)
            self.assertTrue(data)

    def test_publish_failure_keeps_previous_pointer(self):
        with tempfile.TemporaryDirectory() as d, patch.object(app,'DATA',Path(d)), patch.object(app,'now',return_value=AT):
            app.collect(DAY,api=Fake())
            previous=archive.active(Path(d),DAY)
            save=app.save
            def broken(path,obj):
                if path.name=='latest.json':
                    raise OSError('simulated disk failure')
                save(path,obj)
            with patch.object(app,'save',side_effect=broken), self.assertRaises(OSError):
                app.collect(DAY,api=Fake())
            self.assertEqual(archive.active(Path(d),DAY),previous)
            self.assertTrue((previous/'005930.json').is_file())
            self.assertEqual(len(list((Path(d)/DAY).glob('snapshot-*'))),1)

    def test_manual_after_20_is_final_and_replaces_intraday(self):
        with tempfile.TemporaryDirectory() as d, patch.object(app,'DATA',Path(d)):
            with patch.object(app,'now',return_value=AT):
                app.collect(DAY,api=Fake())
                previous=archive.active(Path(d),DAY)
            with patch.object(app,'now',return_value=AT.replace(hour=20,minute=1)):
                m=app.collect(DAY,api=Fake())
            self.assertEqual(m['kind'],'final')
            self.assertFalse(previous.exists())
            self.assertEqual(len(app.catalog()),1)

    def test_past_date_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as d, patch.object(app,'DATA',Path(d)), patch.object(app,'now',return_value=AT):
            with self.assertRaisesRegex(DataError,'과거'):
                app.collect('2026-09-21',api=Fake())

    def test_periodic_due_busy_and_final_priority(self):
        with tempfile.TemporaryDirectory() as d, patch.object(app,'DATA',Path(d)), patch.object(app,'now',return_value=AT), patch.object(app,'STATE',{'busy':False}), patch.object(app,'start') as start:
            app.set_monitor(True)
            app.save(Path(d)/'schedule.json',{'day':DAY,'last_start_epoch':AT.timestamp()-(app.INTERVAL-1)})
            app.scheduler_tick(AT)
            start.assert_not_called()
            app.scheduler_tick(AT+timedelta(seconds=2))
            start.assert_called_once_with(DAY,source='auto')
            start.reset_mock()
            app.STATE['busy']=True
            app.scheduler_tick(AT+timedelta(minutes=10))
            start.assert_not_called()
            app.STATE['busy']=False
            app.set_monitor(False)
            app.scheduler_tick(AT.replace(hour=20,minute=5))
            start.assert_called_once_with(DAY,source='final')

    def test_final_2001_does_not_skip_2005_final(self):
        with tempfile.TemporaryDirectory() as d, patch.object(app,'DATA',Path(d)), patch.object(app,'STATE',{'busy':False}), patch.object(app,'start') as start:
            p=Path(d)/DAY/'final'/'index.json'
            app.save(p,{'day':DAY,'status':'saved','ranking_at':DAY+'T20:01:00+09:00'})
            app.scheduler_tick(AT.replace(hour=20,minute=5))
            start.assert_called_once_with(DAY,source='final')
            start.reset_mock()
            app.save(p,{'day':DAY,'status':'saved','ranking_at':DAY+'T20:06:00+09:00'})
            app.scheduler_tick(AT.replace(hour=20,minute=10))
            start.assert_not_called()

    def test_open_enables_refresh_and_busy_requests_coalesce(self):
        with tempfile.TemporaryDirectory() as d, patch.object(app,'DATA',Path(d)), patch.object(app,'now',return_value=AT), patch.object(app,'STATE',{'busy':True,'queued':False}), patch.object(app,'LAST_OPEN',0), patch.object(app.time,'monotonic',return_value=100):
            app.GUARD.acquire()
            try:
                self.assertEqual(app.opened(),'queued')
                self.assertTrue(app.monitor_enabled())
                self.assertTrue(app.STATE['queued'])
                self.assertEqual(app.opened(),'running')
            finally:
                app.GUARD.release()

    def test_delete_cannot_target_other_day_or_root(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            target=root/'2026-09-21'/'preview'
            target.mkdir(parents=True)
            with self.assertRaises(ValueError):
                archive.remove_snapshot(root,DAY,target)
            with self.assertRaises(ValueError):
                archive.remove_snapshot(root,DAY,root)
            self.assertTrue(target.exists())


DAY='2026-09-22'
AT=datetime(2026,9,22,12,0,tzinfo=app.KST)


class Fake:
    def __init__(self):
        self.ranks=0
        self.codes=['005930','000660']
        self.fail=False
    def ranking(self):
        self.ranks+=1
        return [dict(code=c,name=c,rank=i+1,rate=2,price=100) for i,c in enumerate(self.codes)], {'fixture':True}
    def minute_bars(self,code,day):
        if self.fail and code!=self.codes[0]:
            raise DataError('fixture unavailable')
        return [dict(ts=day+' 09:00:00',open=100,high=110,low=90,close=101,volume=1,ma5=None,ma10=None,ma20=None,ma60=None)], {'fixture':True}


if __name__=='__main__':
    unittest.main()
