import tempfile
import unittest
from pathlib import Path

import reasons

ARTICLE = """<html><head><style>td{font-size:9pt}</style></head><body>
<table><tr><td>제목</td><td>증시요약(6) - 특징 상한가 및 급등종목</td></tr>
<tr><td>일시</td><td>2026년 09월 23일 17시 07분</td></tr></table>
<table class="tbl"><tr><td>종 목</td><td>상한가 일수</td><td>사유</td></tr>
<tr><td><b><a href="#">티엔엔터테인먼트<br>(131100)</a><br>3,120원<br>(<font>+30.00%</font>)</b></td><td>1</td><td>합의금 지급 합의 체결 소식 속 상한가</td></tr>
<tr><td><b><a href="#">와이즈플래닛컴<br>퍼니<br>(0010S0)</a><br>46,300원<br>(<font>+285.83%</font>)</b></td><td></td><td>신규상장 첫날 급등</td></tr>
<tr><td><b><a href="#">티로보틱스<br>(117730)</a><br>9,820원<br>(<font>+9.36%</font>)</b></td><td></td><td>3분기 흑자전환 전망 등에 급등</td></tr>
</table></body></html>"""


class ParseTest(unittest.TestCase):
    def test_public_summary_checks_date_and_preserves_prior_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            reasons.save_infostock(data, '2026-09-23', 'A (000001) 100원 (+10%) | | 기존 사유', {})
            urls = []
            def fetch(url):
                urls.append(url)
                if '/news/view/' in url:
                    return ARTICLE
                return '<a href="/news/view/123">증시요약(6) - 특징 상한가 및 급등종목</a><p>2026-09-23</p>'
            result = reasons.fetch_summary(data, '2026-09-23', {}, fetch)
            self.assertEqual(len(result), 3)
            self.assertEqual(len(reasons.read_day(data, '2026-09-23')['infostock']['items']), 4)
            self.assertEqual(reasons.fetch_summary(data, '2026-09-24', {}, fetch), {})
            self.assertFalse(reasons.path(data, '2026-09-24').exists())
            history = reasons.recent_history(data, '2026-09-24')
            self.assertEqual(history['000001'][0]['day'], '2026-09-23')

    def test_hero4_article_rows_with_days_and_article_date(self):
        text = reasons.html_text(ARTICLE)
        self.assertEqual(reasons.article_day(text), ("2026-09-23", "17:07"))
        items = reasons.parse(text, {"0010S0": "와이즈플래닛컴퍼니", "117730": "옛이름"})
        self.assertEqual(list(items), ["131100", "0010S0", "117730"])
        self.assertEqual(items["131100"]["limit_days"], 1)
        self.assertEqual(items["131100"]["reason"], "합의금 지급 합의 체결 소식 속 상한가")
        self.assertEqual(items["0010S0"]["name"], "와이즈플래닛컴퍼니")
        self.assertIsNone(items["117730"]["limit_days"])
        self.assertEqual(items["117730"]["reason"], "3분기 흑자전환 전망 등에 급등")
        self.assertEqual(items["117730"]["name"], "티로보틱스")
        self.assertEqual(items["0010S0"]["rate"], 285.83)

    def test_pasted_pipe_table_and_rows_without_code(self):
        text = ("| 종 목 | 상한가 일수 | 사유 |\n"
                "| 진원생명과학 (011000) 1,322원 (+29.99%) | 2 | 코로나19 관련주 상승 속 상한가 |\n"
                "| 제이오 11,730원 (+26.40%) | | 2차전지 테마 상승 속 급등 |\n")
        items = reasons.parse(text, {"418550": "제이오"})
        self.assertEqual(items["011000"]["limit_days"], 2)
        self.assertEqual(items["418550"]["reason"], "2차전지 테마 상승 속 급등")

    def test_save_rejects_text_without_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                reasons.save_infostock(Path(tmp), "2026-09-23", "아무 내용", {})


class NewsTest(unittest.TestCase):
    def test_keeps_today_and_named_or_rising_titles_first(self):
        items = [{"datetime": "202609281541", "title": "[특징주] HLB, FDA 허가에 상한가", "officeName": "연합", "officeId": "001", "articleId": "1"},
                 {"datetime": "202609281638", "title": "코스피 2.70% 급락 마감", "officeName": "서울"},
                 {"datetime": "202609281500", "title": "HLB그룹 고객 감사 프로모션", "officeName": "머투", "officeId": "008", "articleId": "2"},
                 {"datetime": "202609241635", "title": "HLB 표적 항암제 승인", "officeName": "세계"}]
        picked = reasons.pick_news(items, "2026-09-28", "HLB")
        self.assertEqual([p["title"] for p in picked], ["[특징주] HLB, FDA 허가에 상한가", "HLB그룹 고객 감사 프로모션"])
        self.assertEqual(picked[0]["at"], "15:41")
        self.assertEqual(picked[0]["url"], "https://n.news.naver.com/mnews/article/001/1")

    def test_fetch_skips_single_failures_and_keeps_previous(self):
        def fetch(code):
            if code == "000002":
                raise OSError("boom")
            return [{"datetime": "202609281000", "title": "A 급등", "officeName": "x"}]
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            reasons.fetch_news(data, "2026-09-28", [{"code": "000001", "name": "A"}, {"code": "000002", "name": "B"}], fetch, pause=0)
            record = reasons.read_day(data, "2026-09-28")["news"]
            self.assertEqual(len(record["items"]["000001"]), 1)
            self.assertNotIn("000002", record["items"])
            self.assertEqual(record["failed"], 1)


class WatchTest(unittest.TestCase):
    def test_watch_saves_article_day_once_and_ignores_other_articles(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, news = Path(tmp) / "data", Path(tmp) / "News.html"
            reasons.SEEN["stamp"] = None
            news.write_bytes("<p>다른 뉴스</p><p>2026년 09월 28일 10시 00분</p>".encode("cp949"))
            self.assertIsNone(reasons.watch_hero4(data, lambda day: {}, news))
            news.write_bytes(ARTICLE.encode("cp949"))
            day, items = reasons.watch_hero4(data, lambda day: {}, news)
            self.assertEqual((day, len(items)), ("2026-09-23", 3))
            saved = reasons.read_day(data, "2026-09-23")["infostock"]
            self.assertEqual((saved["source"], saved["published"]), ("hero4", "17:07"))
            self.assertIsNone(reasons.watch_hero4(data, lambda day: {}, news))


if __name__ == "__main__":
    unittest.main()
