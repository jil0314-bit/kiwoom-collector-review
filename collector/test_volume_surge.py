"""Focused offline checks for the new category; all files live in temporary directories."""
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
import volume_surge as v
from kiwoom import DataError, KST


def item(code, rate):
    return {"stk_cd": code+"_AL", "stk_nm": code, "cur_prc": "+1000", "flu_rt": "-2",
            "sdnin_rt": str(rate), "prev_trde_qty": "100", "now_trde_qty": "500"}


class VolumeTests(unittest.TestCase):
    def test_filtered_continuation_and_rate_order(self):
        calls = []
        def request(api, body, cursor):
            calls.append((api, body, cursor))
            if api == "ka10023":
                return ({"trde_qty_sdnin": [item("000001", 900), item("000002", 800)]} if not cursor
                        else {"trde_qty_sdnin": [item("000003", 700)]}), {"cont-yn": "Y" if not cursor else "N", "next-key": "page2"}
            return {"atn_stk_infr": [{"stk_cd": c, "mac": "499" if c.startswith("000001") else "500", "dt": "20261008"}
                                     for c in body["stk_cd"].split("|")]}, {}
        rows, raw = v.ranking("2026-10-08", request, 2)
        self.assertEqual([s["code"] for s in rows], ["000002", "000003"])
        self.assertEqual(rows[0]["rate"], -2)  # falling-price volume surges stay included
        self.assertEqual(calls[0][1], v.BODY)
        self.assertEqual(v.BODY["sort_tp"], "2")
        self.assertEqual(v.BODY["stk_cnd"], "20")

    def test_stale_date_rejected(self):
        def request(api, body, cursor):
            return ({"trde_qty_sdnin": [item("000001", 100)]}, {}) if api == "ka10023" else ({"atn_stk_infr": [{"stk_cd": "000001", "mac": "600", "dt": "20261007"}]}, {})
        with self.assertRaises(DataError):
            v.ranking("2026-10-08", request)

    def test_missing_cap_never_qualifies(self):
        def request(api, body, cursor):
            return ({"trde_qty_sdnin": [item("000001", 100)]}, {}) if api == "ka10023" else ({"atn_stk_infr": [{"stk_cd": "000001", "mac": "", "dt": "20261008"}]}, {})
        with self.assertRaises(DataError):
            v.ranking("2026-10-08", request)

    def test_first_seen_and_rank_history_survive_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            s = {"code": "000001", "price": 1000, "rank": 8, "volume_rate": 200}
            raw = {"unknown_cap_excluded": 0}
            v.commit_rank(data, "2026-10-08", [s], raw, "2026-10-08T09:00:00+09:00")
            v.commit_rank(data, "2026-10-08", [{**s, "price": 1500, "rank": 1}], raw, "2026-10-08T10:00:00+09:00")
            m = v.metadata(data, "2026-10-08")
            self.assertEqual(m["stocks"][0]["first_price"], 1000)
            self.assertEqual(m["stocks"][0]["first_seen"][11:16], "09:00")
            self.assertEqual(m["stocks"][0]["best_rank"], 1)
            self.assertEqual(len((v.root(data)/"2026-10-08"/"ranking_history.csv").read_text(encoding="utf-8-sig").splitlines()), 3)

    def test_month_pruning_preserves_original_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            for p in [data/"2026-09-01", v.root(data)/"2026-09-08", v.root(data)/"2026-09-09", v.root(data)/"2026-10-08"]:
                p.mkdir(parents=True);(p/"index.json").write_text("{}")
            v.prune(data, date(2026,10,8))
            self.assertTrue((data/"2026-09-01"/"index.json").exists())
            self.assertFalse((v.root(data)/"2026-09-08").exists())
            self.assertTrue((v.root(data)/"2026-09-09").exists())
            self.assertEqual(v.cutoff(date(2028,3,31)), date(2028,2,29))

    def test_schedule_and_final_guards(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(v, 'start') as start:
            data = Path(tmp)
            with patch.dict(v.STATE, {"busy":False, "bars_busy":False}), patch.object(v, 'LAST_START', 0):
                for h,m in [(7,59),(20,0),(20,4)]:
                    v.tick(data, datetime(2026,10,8,h,m,tzinfo=KST))
                start.assert_not_called()
                v.tick(data, datetime(2026,10,8,8,0,tzinfo=KST));self.assertEqual(start.call_count, 1)
                v.write(v.root(data)/"2026-10-08"/"index.json", {"final_complete":True})
                v.tick(data, datetime(2026,10,8,20,5,tzinfo=KST));self.assertEqual(start.call_count, 1)

    def test_saved_record_kept_when_bar_request_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp);day="2026-10-08"
            s={"code":"000001", "name":"test", "price":1000, "rank":1}
            v.commit_rank(data, day, [s], {"unknown_cap_excluded":0}, day+"T09:00:00+09:00")
            path=v.root(data)/day/"000001.json";path.write_text('{"original":true}')
            with patch.object(v.chart_data,'CLIENT') as api, patch.object(v,'datetime') as dt:
                dt.now.return_value=datetime(2026,10,8,10,0,tzinfo=KST)
                api.minute_bars.side_effect=DataError("no data")
                v.collect_bars(data,day)
            self.assertEqual(path.read_text(), '{"original":true}')
            self.assertEqual(v.metadata(data,day)["stocks"][0]["status"], "error")


if __name__ == "__main__":
    unittest.main()
