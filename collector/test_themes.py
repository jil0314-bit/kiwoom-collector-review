import tempfile
import unittest
from pathlib import Path

import themes

MEMBERS = {"2": ["000001", "000002", "000003", "000004"], "4": ["000010", "000011", "000012"]}


class FakeApi:
    def __init__(self):
        self.calls = []

    def request(self, api, body, cursor=""):
        self.calls.append((api, body))
        if api == "ka90001":
            rows = [{"thema_grp_cd": "1", "thema_nm": "한종목", "stk_num": "1", "flu_rt": "+9.00", "rising_stk_num": "1", "fall_stk_num": "0"},
                    {"thema_grp_cd": "2", "thema_nm": "태양광_폴리실리콘", "stk_num": "4", "flu_rt": "+5.38", "rising_stk_num": "3", "fall_stk_num": "0"},
                    {"thema_grp_cd": "3", "thema_nm": "하락", "stk_num": "5", "flu_rt": "-0.50", "rising_stk_num": "1", "fall_stk_num": "4"},
                    {"thema_grp_cd": "4", "thema_nm": "타이어", "stk_num": "3", "flu_rt": "+3.46", "rising_stk_num": "2", "fall_stk_num": "1"}]
            return {"thema_grp": rows}, {}
        if api == "ka90002":
            codes = MEMBERS[body["thema_grp_cd"]]
            return {"thema_comp_stk": [{"stk_cd": c + "_AL", "stk_nm": "K" + c, "cur_prc": "+1000", "flu_rt": f"+{i}.00",
                                        "acc_trde_qty": "10"} for i, c in enumerate(codes)]}, {}
        codes = body["stk_cd"].split("|")
        return {"atn_stk_infr": [{"stk_cd": c, "stk_nm": "W" + c, "cur_prc": "-2000", "flu_rt": f"+{int(c) % 17}.00",
                                  "trde_qty": "5"} for c in codes]}, {}


def group(number, name, codes, headings=()):
    entries = [{"type": "heading", "label": h} for h in headings] + [{"type": "stock", "code": c} for c in codes]
    return {"number": number, "name": name, "entries": entries}


GROUPS = [group(6, "보유주", ["000001", "000002", "000003"]),
          group(19, "태양광관련주", ["000001"] + [f"{i:06d}" for i in range(100, 114)]),
          group(41, "이란사태", ["000002", "000003"]),
          group(26, "우크라나재건관련주", ["000010"])]


class ThemeTest(unittest.TestCase):
    def test_ranking_keeps_rising_themes_with_three_or_more_stocks(self):
        self.assertEqual([t["name"] for t in themes.ranking(FakeApi())], ["태양광_폴리실리콘", "타이어"])

    def test_name_match_beats_larger_overlap_and_skips_non_theme_groups(self):
        usable = themes.theme_groups(GROUPS)
        self.assertNotIn(6, [g["number"] for g in usable])
        g, reason = themes.match("태양광_폴리실리콘", MEMBERS["2"], usable, {})
        self.assertEqual(g["number"], 19)
        self.assertTrue(reason.startswith("이름 일치"))

    def test_overlap_needs_two_stocks_and_forty_percent(self):
        usable = themes.theme_groups(GROUPS)
        g, _ = themes.match("합성수지", MEMBERS["2"], usable, {})
        self.assertEqual(g["number"], 41)
        g, reason = themes.match("타이어", MEMBERS["4"], usable, {})
        self.assertIsNone(g)
        self.assertEqual(reason, "관심종목 없음")

    def test_manual_map_wins_and_null_forces_kiwoom(self):
        usable = themes.theme_groups(GROUPS)
        g, reason = themes.match("타이어", MEMBERS["4"], usable, {"타이어": 26})
        self.assertEqual((g["number"], reason), (26, "직접 지정"))
        g, _ = themes.match("태양광_폴리실리콘", MEMBERS["2"], usable, {"태양광_폴리실리콘": None})
        self.assertIsNone(g)

    def test_build_picks_top10_watchlist_stocks_or_kiwoom_fallback(self):
        (solar, tire), custom = themes.build(FakeApi(), GROUPS, {})
        self.assertEqual(custom, [])
        self.assertEqual(solar["source"], "watchlist")
        self.assertEqual(solar["group"]["number"], 19)
        self.assertEqual(len(solar["leaders"]), 10)
        rates = [s["rate"] for s in solar["leaders"]]
        self.assertEqual(rates, sorted(rates, reverse=True))
        self.assertEqual(solar["leaders"][0]["price"], 2000)
        self.assertEqual(tire["source"], "kiwoom")
        self.assertEqual([s["code"] for s in tire["leaders"]], ["000012", "000011", "000010"])

    def test_history_appends_and_same_minute_replaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = lambda at, rate: {"updated_at": f"2026-09-28T{at}:00+09:00", "themes": [{"code": "2", "name": "태양광", "rate": rate}]}
            themes.write(tmp, "2026-09-28", snap("10:00", 1.0))
            themes.write(tmp, "2026-09-28", snap("10:03", 2.0))
            record = themes.write(tmp, "2026-09-28", snap("10:03", 3.0))
            self.assertEqual([m["at"] for m in record["history"]], ["10:00", "10:03"])
            self.assertEqual(record["history"][-1]["themes"][0]["rate"], 3.0)

    def test_keeps_latest_ten_trading_days_and_ignores_other_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "themes"
            root.mkdir()
            for name in ("last_error.json", "map.json", "note.txt"):
                (root / name).write_text("{}", encoding="utf-8")
            dates = [f"2026-09-{d:02d}" for d in (1, 2, 3, 4, 7, 8, 9, 10, 11, 14, 15)]
            for day in dates:
                themes.write(tmp, day, {"updated_at": day + "T10:00:00+09:00", "themes": []})
            self.assertEqual(themes.days(tmp), sorted(dates, reverse=True)[:10])
            self.assertFalse((root / "2026-09-01.json").exists())
            self.assertTrue(all((root / n).exists() for n in ("last_error.json", "map.json", "note.txt")))

    def test_rejects_bad_dates(self):
        with self.assertRaises(ValueError):
            themes.day_path("x", "../2026-09-28")


class EditTest(unittest.TestCase):
    def test_normalize_validates_and_drops_empty_edits(self):
        doc = themes.normalize_edits({"themes": {"타이어": {"group": "kiwoom", "pin": ["000010"]},
                                                 "빈것": {"group": "auto", "add": []},
                                                 "태양광": {"add": ["000200"], "remove": ["000200", "000101"]}},
                                      "custom": [{"name": "  내  테마 ", "codes": ["005930", "005930"], "pin": ["005930", "000660"]}]})
        self.assertEqual(doc["themes"]["타이어"], {"add": [], "remove": [], "pin": ["000010"], "group": None})
        self.assertNotIn("빈것", doc["themes"])
        self.assertEqual(doc["themes"]["태양광"]["remove"], ["000101"])
        mine = doc["custom"][0]
        self.assertEqual((mine["name"], mine["codes"], mine["pin"]), ("내 테마", ["005930"], ["005930"]))
        self.assertRegex(mine["id"], r"^[a-z0-9]{12}$")
        for bad in ({"themes": {"x": {"add": ["../etc"]}}}, {"themes": {"x": {"group": 500}}},
                    {"themes": {"x": {"pin": [f"{i:06d}" for i in range(11)]}}}, {"custom": [{"name": "", "codes": []}]}):
            with self.assertRaises(ValueError):
                themes.normalize_edits(bad)

    def test_save_detects_stale_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = themes.save_edits(tmp, {"themes": {"타이어": {"group": 26}}}, "")
            self.assertEqual(themes.read_edits(tmp)["themes"]["타이어"]["group"], 26)
            with self.assertRaises(themes.Conflict):
                themes.save_edits(tmp, {}, "")
            themes.save_edits(tmp, {}, first["revision"])
            self.assertEqual(themes.read_edits(tmp)["themes"], {})

    def test_build_applies_group_add_remove_pin_and_custom(self):
        edits = themes.normalize_edits({
            "themes": {"태양광_폴리실리콘": {"remove": ["000101"], "pin": ["000100"], "add": ["000500"]},
                       "타이어": {"group": 26, "add": ["000011"]}},
            "custom": [{"id": "abc", "name": "내 반도체", "codes": ["000033", "000034"], "pin": ["000033"]}]})
        (solar, tire), custom = themes.build(FakeApi(), GROUPS, {}, edits)
        codes = [s["code"] for s in solar["leaders"]]
        self.assertEqual(codes[0], "000100")
        self.assertTrue(solar["leaders"][0]["pinned"])
        self.assertNotIn("000101", codes)
        self.assertIn("000500", codes)
        self.assertTrue(next(s for s in solar["leaders"] if s["code"] == "000500")["added"])
        self.assertIn("000101", [s["code"] for s in solar["candidates"]])
        self.assertEqual(solar["edited"], {"group": False, "add": 1, "remove": 1, "pin": 1})
        self.assertEqual((tire["source"], tire["group"]["number"]), ("watchlist", 26))
        self.assertEqual({s["code"] for s in tire["leaders"]}, {"000010", "000011"})
        self.assertEqual(custom[0]["code"], "c:abc")
        self.assertEqual([s["code"] for s in custom[0]["leaders"]], ["000033", "000034"])
        self.assertEqual(custom[0]["rate"], (33 % 17 + 34 % 17) / 2)

    def test_custom_theme_can_be_paired_and_deleted_theme_falls_back_to_auto(self):
        edits = themes.normalize_edits({
            "themes": {"타이어": {"group": "c:abc", "pin": ["000034"]}},
            "custom": [{"id": "abc", "name": "내 타이어", "codes": ["000033", "000034"]}]})
        (_, tire), _ = themes.build(FakeApi(), GROUPS, {}, edits)
        self.assertEqual((tire["source"], tire["group"]["number"], tire["group"]["name"]), ("watchlist", "c:abc", "내 타이어"))
        self.assertEqual(tire["group"]["reason"], "직접 지정 · 내가 만든 테마")
        self.assertEqual([s["code"] for s in tire["leaders"]], ["000034", "000033"])
        gone = themes.normalize_edits({"themes": {"타이어": {"group": "c:abc"}, "태양광": {"group": "c:zzz", "add": ["000200"]}}})
        self.assertNotIn("타이어", gone["themes"])
        self.assertNotIn("group", gone["themes"]["태양광"])
        with self.assertRaises(ValueError):
            themes.normalize_edits({"themes": {"x": {"group": "c:../x"}}})


class RevokedTokenTest(unittest.TestCase):
    def test_reissues_token_once_when_revoked(self):
        from unittest.mock import patch
        import kiwoom
        calls = []

        def transport(path, body, headers):
            calls.append((path, headers.get("authorization", "")))
            if path == "/oauth2/token":
                return {"return_code": 0, "token": f"t{len(calls)}", "expires_dt": "20991231000000"}, {}
            if headers["authorization"] == "Bearer t1":
                return {"return_code": 3, "return_msg": "revoked"}, {}
            return {"return_code": 0, "thema_grp": []}, {}

        with patch.object(kiwoom, "credentials", return_value=("k", "s", "test")):
            api = kiwoom.Kiwoom(interval=0, transport=transport)
            data, _ = api.request("ka90001", {})
        self.assertEqual(data["thema_grp"], [])
        self.assertEqual([p for p, _ in calls], ["/oauth2/token", "/api/dostk/thme", "/oauth2/token", "/api/dostk/thme"])


if __name__ == "__main__":
    unittest.main()
