"""Offline contract, retention, scheduler, and HTTP boundary tests."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import urllib.error
import urllib.request

import app
import investor_flows as flows
from kiwoom import DataError, KST, ROUTES

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=KST)
DAY = NOW.date().isoformat()


def row(code="005930", amount="+1,234", quantity="-56"):
    return {"for_netprps_stk_cd": code, "for_netprps_stk_nm": "삼성전자",
            "for_netprps_amt": amount, "for_netprps_qty": quantity,
            "orgn_netprps_stk_cd": "000660", "orgn_netprps_stk_nm": "SK하이닉스",
            "orgn_netprps_amt": "234", "orgn_netprps_qty": "12"}


class FakeAPI:
    def __init__(self, pages=None, trading=True):
        self.pages = iter(pages or [([row()], {})])
        self.calls = []
        self.trading = trading

    def daily_bars(self, code, day, count):
        return ([{"ts": day, "volume": 10}] if self.trading else [], {})

    def request(self, api, body, cursor):
        self.calls.append((api, body, cursor))
        if body.get('mrkt_tp') in ('001','101'):
            rows=[dict(row(),for_netprps_stk_cd=f'{n:06d}',orgn_netprps_stk_cd=f'{n+100:06d}') for n in range(1,21)]
            return {'frgnr_orgn_trde_upper':rows,'return_code':0},{}
        rows, headers = next(self.pages)
        return {"frgnr_orgn_trde_upper": rows, "return_code": 0}, headers


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)

    def save(self, api=None, current=NOW):
        return flows.refresh(self.data, current.date().isoformat(), api or FakeAPI(), lambda: current)

    def test_contract_signed_units_and_alphanumeric_code(self):
        api = FakeAPI([([row("0200G0_AL")], {})])
        result, raw = flows.fetch(api, DAY)
        self.assertEqual(ROUTES["ka90009"], "/api/dostk/rkinfo")
        self.assertEqual(api.calls[0], ("ka90009", {"mrkt_tp":"000", "amt_qty_tp":"1", "qry_dt_tp":"1", "date":"20261019", "stex_tp":"3"}, ""))
        value = result["foreign"][0]
        self.assertEqual((value["code"], value["net_amount_10m_krw"], value["net_quantity_1000_shares"]), ("0200G0",1234,-56))

    def test_missing_numbers_remain_unknown(self):
        result, _ = flows.fetch(FakeAPI([([row(amount="", quantity=None)], {})]), DAY)
        self.assertIsNone(result["foreign"][0]["net_amount_10m_krw"])
        self.assertEqual(flows.signed_int("0"),0)

    def test_bad_numbers_and_shapes_rejected(self):
        for bad in ("NaN","1.2","1e6",True):
            with self.assertRaises(DataError):flows.fetch(FakeAPI([([row(amount=bad)], {})]), DAY)
        with self.assertRaises(DataError):flows.fetch(FakeAPI([(None,{})]), DAY)
        with self.assertRaises(DataError):flows.fetch(FakeAPI([([5],{})]), DAY)

    def test_two_investor_lists_are_independent(self):
        rows=[row(),{"for_netprps_stk_cd":"", "orgn_netprps_stk_cd":"035420", "orgn_netprps_amt":"50"}]
        result,_=flows.fetch(FakeAPI([(rows,{})]),DAY)
        self.assertEqual(len(result['foreign']),1)
        self.assertEqual(len(result['institution']),2)
        self.assertIsNone(result['institution'][1]['net_quantity_1000_shares'])

    def test_pagination_duplicate_overlap_and_conflict(self):
        api=FakeAPI([([row()],{'cont-yn':'Y','next-key':'x'}),([row()],{})])
        result,_=flows.fetch(api,DAY)
        self.assertEqual(len(result['foreign']),1)
        self.assertEqual(api.calls[1][2],'x')
        with self.assertRaises(DataError):
            flows.fetch(FakeAPI([([row()],{'cont-yn':'Y','next-key':'x'}),([row(amount='99')],{})]),DAY)

    def test_missing_repeated_cursor_and_page_limit(self):
        for pages in [ [([row()],{'cont-yn':'Y'})],
            [([row()],{'cont-yn':'Y','next-key':'x'})]*2,
            [([row()],{'cont-yn':'Y','next-key':str(n)}) for n in range(30)]]:
            with self.assertRaises(DataError): flows.fetch(FakeAPI(pages),DAY)

    def test_atomic_success_and_hash(self):
        doc=self.save()
        self.assertEqual(flows.read_day(self.data,DAY),doc)
        self.assertEqual(doc['source_date'],'UNKNOWN')
        self.assertEqual(doc['units'],{'amount':'천만원','quantity':'천주'})
        self.assertFalse(doc['after_close_refresh'])
        self.assertEqual(flows.days(self.data),[DAY])
        self.assertFalse(list(self.data.rglob('*.tmp-*')))

    def test_failed_refresh_and_other_day_preserved(self):
        self.save()
        before=(flows.root(self.data)/(DAY+'.json')).read_bytes()
        for bad in FakeAPI([([], {})]), FakeAPI(trading=False), FakeAPI([([row(amount='bad')],{})]):
            with self.assertRaises(DataError):self.save(bad)
            self.assertEqual((flows.root(self.data)/(DAY+'.json')).read_bytes(),before)
        self.save(current=NOW+timedelta(days=1))
        self.assertEqual(flows.days(self.data),['2026-10-20',DAY])

    def test_atomic_replace_failure_preserves_previous(self):
        self.save()
        previous=flows.read_day(self.data,DAY)
        with patch.object(flows.os,'replace',side_effect=PermissionError):
            with self.assertRaises(PermissionError):self.save()
        self.assertEqual(flows.read_day(self.data,DAY),previous)
        self.assertFalse(list(self.data.rglob('*.tmp-*')))

    def test_midnight_and_weekend_and_wrong_day(self):
        clocks=iter([NOW,NOW+timedelta(days=1)])
        with self.assertRaises(DataError):flows.refresh(self.data,DAY,FakeAPI(),lambda:next(clocks))
        with self.assertRaises(DataError):flows.refresh(self.data,'2026-10-18',FakeAPI(),lambda:NOW-timedelta(days=1))
        with self.assertRaises(DataError):flows.refresh(self.data,'2026-10-20',FakeAPI(),lambda:NOW)
        self.assertFalse(flows.days(self.data))

    def test_hash_tampering_detected(self):
        doc=self.save();doc['day']='2026-10-20'
        flows.write(flows.root(self.data)/(DAY+'.json'),doc)
        with self.assertRaises(DataError):flows.read_day(self.data,DAY)

    def test_csv_signed_numbers_null_and_formula_name(self):
        doc=self.save(FakeAPI([([row(amount='', quantity='-5')],{})]))
        doc.pop('markets')
        doc['rankings']['foreign'][0]['name']='=HYPERLINK("bad")'
        result=flows.csv_bytes(doc).decode('utf-8-sig')
        self.assertIn("'=HYPERLINK",result)
        self.assertIn(',-5,UNKNOWN',result)
        self.assertIn('net_amount_10m_krw',result)

    def test_daily_top20_reverse_and_period_top30(self):
        doc=self.save()
        doc.pop('markets')
        rows=[dict(doc['rankings']['foreign'][0],rank=n,code=f'{n:06d}') for n in range(1,36)]
        doc['rankings']={'foreign':rows,'institution':rows}
        self.assertEqual([r['rank'] for r in flows.display_rows(doc,'foreign')],list(range(20,0,-1)))
        self.assertEqual(len(flows.csv_bytes(doc).decode('utf-8-sig').splitlines()),41)
        doc.update(kind='period',period_start='2026-01-01',period_end='2026-08-17')
        self.assertEqual([r['rank'] for r in flows.display_rows(doc,'foreign')],list(range(1,31)))
        self.assertEqual(len(flows.csv_bytes(doc).decode('utf-8-sig').splitlines()),61)

    def test_period_archive_validation_and_http(self):
        doc=self.save()
        doc.update(kind='period',period_start='2026-01-01',period_end='2026-08-17')
        doc.pop('day')
        doc['sha256']=flows.digest(doc)
        path=flows.root(self.data)/'periods/2026-01-01_2026-08-17.json'
        flows.write(path,doc)
        self.assertEqual(flows.periods(self.data),[{'start':'2026-01-01','end':'2026-08-17'}])
        self.assertEqual(flows.read_period(self.data,'2026-01-01','2026-08-17'),doc)
        with self.assertRaises(ValueError):flows.read_period(self.data,'../x','2026-08-17')
        with self.assertRaises(ValueError):flows.read_period(self.data,'2026-08-18','2026-08-17')
        server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        port=server.server_address[1]
        with patch.object(app,'PORT',port),patch.object(app,'DATA',self.data):
            t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            try:
                base=f'http://127.0.0.1:{port}/api/investors/'
                for route in ('period','period-csv'):
                    with urllib.request.urlopen(base+route+'?start=2026-01-01&end=2026-08-17') as r:
                        payload=r.read()
                        if route=='period':self.assertNotIn('raw',json.loads(payload))
                        else:self.assertIn(b'2026-01-01',payload)
            finally:server.shutdown();server.server_close();t.join(3)
        doc['period_end']='2026-08-18'
        flows.write(path,doc)
        with self.assertRaises(DataError):flows.read_period(self.data,'2026-01-01','2026-08-17')

    def test_period_totals_rank_integer_money_before_unit_conversion(self):
        start,end='2026-01-01','2026-08-17'
        records=[{'stock':{'code':f'{n:06d}','name':str(n)},
                  'million_krw':{'foreign':1001-n,'institution':n*10},
                  'raw':{'frgnr_invsr':str(1001-n),'orgn':str(n*10)},
                  'request':{'stk_cd':f'{n:06d}_AL','strt_dt':'20260101','end_dt':'20260817',
                             'amt_qty_tp':'1','trde_tp':'0','unit_tp':'1'}} for n in range(1,36)]
        coverage={'target_count':35,'saved_count':35,'failed_count':0}
        doc=flows.period_document(records,start,end,coverage,'test')
        self.assertEqual(doc['rankings']['foreign'][0]['code'],'000001')
        self.assertEqual(doc['rankings']['foreign'][0]['net_amount_10m_krw'],100)
        self.assertEqual(doc['rankings']['institution'][0]['code'],'000035')
        self.assertIsNone(doc['rankings']['institution'][0]['net_quantity_1000_shares'])
        for bad in [records+[records[0]],records[:29]]:
            with self.assertRaises(DataError):flows.period_document(bad,start,end,coverage,'test')
        for change in ({'failed_count':1},{'target_count':36}):
            with self.assertRaises(DataError):flows.period_document(records,start,end,dict(coverage,**change),'test')
        damaged=copy.deepcopy(records);damaged[0]['request']['end_dt']='20260818'
        with self.assertRaises(DataError):flows.period_document(damaged,start,end,coverage,'test')
        damaged=copy.deepcopy(records);damaged[0]['million_krw']['foreign']=None
        with self.assertRaises(DataError):flows.period_document(damaged,start,end,coverage,'test')
        tied=copy.deepcopy(records);tied[1]['million_krw']['foreign']=1000
        tied[1]['raw']['frgnr_invsr']='1000'
        tied.reverse()
        self.assertEqual(flows.period_document(tied,start,end,coverage,'test')['rankings']['foreign'][0]['code'],'000001')
        negative=copy.deepcopy(records)
        negative[0]['million_krw']['foreign']=-500
        negative[0]['raw']['frgnr_invsr']='--500'
        self.assertEqual(flows.period_document(negative,start,end,coverage,'test')['rankings']['foreign'][0]['code'],'000002')
        negative[0]['raw']['frgnr_invsr']='+-500'
        with self.assertRaises(DataError):flows.period_document(negative,start,end,coverage,'test')

    def test_market_requests_and_market_period_rankings(self):
        api=FakeAPI()
        doc=self.save(api)
        self.assertEqual([call[1]['mrkt_tp'] for call in api.calls],['000','001','101'])
        self.assertEqual(set(doc['markets']),{'001','101'})
        self.assertEqual(len(flows.display_rows(doc,'foreign','001')),20)
        self.assertEqual(len(flows.csv_bytes(doc).decode('utf-8-sig').splitlines()),81)
        records=[]
        for n in range(1,71):
            records.append({'stock':{'code':f'{n:06d}','name':str(n),'market_code':'001' if n<=35 else '101'},
                'million_krw':{'foreign':1000-n,'institution':n},'raw':{'frgnr_invsr':str(1000-n),'orgn':str(n)},
                'request':{'stk_cd':f'{n:06d}_AL','strt_dt':'20260101','end_dt':'20260817','amt_qty_tp':'1','trde_tp':'0','unit_tp':'1'}})
        doc=flows.period_document(records,'2026-01-01','2026-08-17',{'target_count':70,'saved_count':70,'failed_count':0},'test')
        self.assertEqual(doc['markets']['001']['rankings']['foreign'][0]['code'],'000001')
        self.assertEqual(doc['markets']['101']['rankings']['foreign'][0]['code'],'000036')
        self.assertEqual(doc['markets']['001']['rankings']['institution'][0]['code'],'000035')
        self.assertEqual(doc['markets']['101']['rankings']['institution'][0]['code'],'000070')
        self.assertEqual(len(flows.csv_bytes(doc).decode('utf-8-sig').splitlines()),121)

    def test_scheduler_default_pause_weekend_and_interval(self):
        self.assertTrue(flows.enabled(self.data))
        self.assertTrue(flows.due(self.data,NOW))
        flows.write(flows.root(self.data)/'schedule.json',{'day':DAY,'last_start_epoch':NOW.timestamp()})
        self.assertFalse(flows.due(self.data,NOW+timedelta(seconds=599)))
        self.assertTrue(flows.due(self.data,NOW+timedelta(seconds=600)))
        self.assertFalse(flows.due(self.data,NOW.replace(hour=8)))
        self.assertFalse(flows.due(self.data,NOW-timedelta(days=1)))
        flows.set_enabled(self.data,False)
        self.assertFalse(flows.due(self.data,NOW+timedelta(minutes=10)))
        self.assertTrue(flows.due(self.data,NOW,manual=True))
        with self.assertRaises(ValueError):flows.set_enabled(self.data,'false')

    def test_final_2005_independent_of_intraday_timer_and_restart(self):
        final=NOW.replace(hour=20,minute=5)
        flows.write(flows.root(self.data)/'schedule.json',{'day':DAY,'last_start_epoch':final.timestamp()-60})
        self.assertTrue(flows.due(self.data,final))
        doc=self.save(current=final)
        self.assertTrue(doc['after_close_refresh'])
        self.assertFalse(flows.due(self.data,final+timedelta(minutes=30)))
        self.assertFalse(flows.due(self.data,NOW.replace(hour=20,minute=1)))

    def test_final_retry_budget_persisted(self):
        final=NOW.replace(hour=20,minute=5)
        path=flows.root(self.data)/'schedule.json'
        flows.write(path,{'day':DAY,'final_attempts':1,'last_final_epoch':final.timestamp()})
        self.assertFalse(flows.due(self.data,final+timedelta(minutes=14)))
        self.assertTrue(flows.due(self.data,final+timedelta(minutes=15)))
        flows.write(path,{'day':DAY,'final_attempts':3})
        self.assertFalse(flows.due(self.data,final+timedelta(minutes=60)))

    def test_coordinator_prevents_overlap_without_charging_attempt(self):
        guard=threading.Lock();guard.acquire()
        self.assertEqual(flows.start(self.data,guard,current=NOW),'collector_busy')
        self.assertFalse((flows.root(self.data)/'schedule.json').exists())
        guard.release()
        self.assertFalse(flows.RUN.locked())

    def test_background_error_sanitized_and_lock_released(self):
        guard=threading.Lock();thread_list=[]
        real=threading.Thread
        def record_thread(*args,**kw):
            t=real(*args,**kw);thread_list.append(t);return t
        with patch.object(flows,'refresh',side_effect=RuntimeError('secret-content')),patch.object(flows.threading,'Thread',side_effect=record_thread):
            self.assertEqual(flows.start(self.data,guard,current=NOW),'started')
            thread_list[0].join(3)
        self.assertFalse(guard.locked());self.assertFalse(flows.RUN.locked())
        self.assertNotIn('secret-content',(flows.root(self.data)/'last_error.json').read_text(encoding='utf-8'))

    def test_traversal_dates_rejected(self):
        for day in ['../schedule','2026-1-1','2026-02-30','2026-10-19/../x']:
            with self.assertRaises(ValueError):flows.read_day(self.data,day)

    def test_http_read_csv_and_post_token(self):
        self.save()
        server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        port=server.server_address[1]
        with patch.object(app,'PORT',port),patch.object(app,'DATA',self.data):
            t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            try:
                base=f'http://127.0.0.1:{port}'
                with urllib.request.urlopen(base+'/api/investors/day?day='+DAY) as r:doc=json.load(r)
                self.assertNotIn('raw',doc)
                self.assertEqual(doc['day'],DAY)
                with urllib.request.urlopen(base+'/api/investors/csv?day='+DAY) as r:self.assertIn(b'foreign',r.read())
                req=urllib.request.Request(base+'/api/investors/collect',data=b'{}',headers={'Content-Type':'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as ctx:urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code,403)
                with patch.object(flows,'start',return_value='waiting') as start:
                    req=urllib.request.Request(base+'/api/investors/collect',data=b'{}',headers={'Content-Type':'application/json','X-Collector-Token':app.TOKEN})
                    with urllib.request.urlopen(req) as r:self.assertEqual(json.load(r)['state'],'waiting')
                    start.assert_called_once()
            finally:server.shutdown();server.server_close();t.join(3)


if __name__=='__main__':unittest.main()
