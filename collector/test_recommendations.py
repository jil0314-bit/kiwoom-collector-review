"""Evidence association and safe archive/API integration regressions."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import recommendations as r


class RecommendationsTest(unittest.TestCase):
    names = {'005930': '삼성전자', '000660': 'SK하이닉스', '005935': '삼성전자우'}
    meta = dict(url='https://news.mtn.co.kr/article/1', broadcaster='MTN', program='표본', title='추천 방송', broadcast_date='2026-10-30', published_at='2026-10-31T00:18:33+09:00')

    def parse(self, text, **overrides):
        return r.extract(text, {**self.meta, **overrides}, self.names)

    def test_speaker_prices_and_reason_do_not_cross_stock(self):
        rows = self.parse('▶ 김민수 전문가\n▶▶ 최종 PICK\n삼성전자(005930)\n- 실적 성장\n매수가 70,000~72,000원 목표가 90,000원 손절가 65,000원\n▶ 이철수 소장\nSK하이닉스(000660)\n- 신규 수주\n목표가 200,000원')
        self.assertEqual(len(rows), 2)
        a, b = rows
        self.assertEqual((a['expert'], b['expert']), ('김민수', '이철수'))
        self.assertEqual(a['buy_price']['max'], 72000)
        self.assertIsNone(b['buy_price'])
        self.assertEqual(b['target_price']['min'], 200000)
        self.assertEqual(a['reason'], '실적 성장')

    def test_publication_never_becomes_recommendation_clock(self):
        row = self.parse('오늘의 추천\n삼성전자')[0]
        self.assertEqual(row['recommended_date'], '2026-10-30')
        self.assertIsNone(row['recommended_time'])
        self.assertEqual(row['published_at'][:10], '2026-10-31')

    def test_unknown_date_remains_unknown(self):
        row = self.parse('오늘의 추천\n삼성전자', broadcast_date=None)[0]
        self.assertIsNone(row['recommended_date'])
        self.assertEqual(row['date_basis'], '미확인')

    def test_explicit_recommendation_clock(self):
        row = self.parse('오늘의 추천\n삼성전자\n추천 시각: 9:05')[0]
        self.assertEqual(row['recommended_time'], '09:05')
        row = self.parse('오늘의 추천\n삼성전자\n추천일시: 2026-10-30 09:05')[0]
        self.assertEqual(row['recommended_time'], '09:05')
        row = self.parse('오늘의 추천\n삼성전자\n방송 시각: 20:40')[0]
        self.assertIsNone(row['recommended_time'])

    def test_consultation_and_review_override_new_keyword(self):
        self.assertEqual(self.parse('신규추천\n삼성전자\n보유 수량 100주 매수 단가 7만원')[0]['classification'], 'consultation')
        self.assertEqual(self.parse('신규추천\n삼성전자\n지난 추천 수익률 달성')[0]['classification'], 'review')

    def test_negation_and_interest(self):
        self.assertEqual(self.parse('삼성전자 매수 추천하지 않습니다'), [])
        self.assertEqual(self.parse('김민수 PICK\n삼성전자')[0]['classification'], 'interest')

    def test_multi_stock_heading_has_no_shared_prices(self):
        rows = self.parse('삼성전자 SK하이닉스 목표가 9만원')
        self.assertTrue(all(x['target_price'] is None for x in rows))

    def test_name_boundaries_and_ranges(self):
        rows = self.parse('오늘의 추천\n삼성전자우 목표가 7.5만원')
        self.assertEqual([x['code'] for x in rows], ['005935'])
        self.assertEqual(rows[0]['target_price']['min'], 75000)
        self.assertIsNone(r.price('목표가 10%', '목표가'))
        self.assertIsNone(r.price('목표수익률 20%', '목표가'))

    def test_korean_price_units_are_not_truncated(self):
        self.assertEqual(r.price('목표가 7만5천원', '목표가')['min'], 75000)
        self.assertEqual(r.price('목표가 7만5000원', '목표가')['min'], 75000)
        value = r.price('매수가 7~8만원', '매수가')
        self.assertEqual((value['min'], value['max']), (70000, 80000))
        self.assertIsNone(r.price('목표가 1억원', '목표가'))

    def test_current_recommendation_date_is_not_a_review_marker(self):
        row = self.parse('신규추천\n삼성전자\n추천일자: 2026-10-30')[0]
        self.assertEqual(row['classification'], 'new')

    def test_unknown_and_ambiguous_names_never_guess_codes(self):
        self.assertEqual(self.parse('미등록회사 123456'), [])
        self.assertEqual(r.extract('같은회사', self.meta, {'000001': '같은회사', '000002': '같은회사'}), [])

    def test_explicit_heading_can_identify_new_listing(self):
        row = self.parse('▶오늘의 고래사냥법 - 신규회사(486510)')[0]
        self.assertEqual((row['name'], row['code']), ('신규회사', '486510'))
        self.assertEqual(self.parse('목표가(100000)'), [])

    def test_interest_speaker_prices_and_corner_alias(self):
        rows = self.parse('▶▶▶ 마스터의 전략\n황민혁 관심주 ①\n삼성전자\n- SK하이닉스와 협력\n- 목표가 90,000원 / 손절가 65,000원', evidence_type='공개 기사')
        row = next(x for x in rows if x['name'] == '삼성전자')
        self.assertEqual((row['expert'], row['classification']), ('황민혁', 'interest'))
        self.assertEqual(row['target_price']['min'], 90000)
        self.assertIn('협력', row['reason'])

    def test_repeat_collection_idempotent_and_preserves_other_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            rows = self.parse('신규추천\n삼성전자')
            r.merge(data, '2026-10-30', rows)
            r.merge(data, '2026-10-30', rows)
            r.merge(data, '2026-10-30', self.parse('오늘의 추천\nSK하이닉스', url='https://news.mtn.co.kr/article/2'))
            doc = r.read(data, '2026-10-30')
            self.assertEqual(len(doc['records']), 2)
            self.assertEqual(len(doc['stocks']), 2)
            self.assertEqual(r.read(data, '2026-10-31')['records'], [])

    def test_legacy_mention_is_hidden_from_archive_stocks_and_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            legacy = self.parse('신규추천\n삼성전자')[0]
            legacy['classification'] = 'mention'
            r.save(data / 'recommendations/2026-10-30/index.json', {'records': [legacy], 'stocks': [{'code': '005930', 'name': '삼성전자'}]})
            doc = r.read(data, '2026-10-30')
            self.assertEqual(doc['records'], [])
            self.assertEqual(doc['stocks'], [])
            self.assertNotIn('005930', r.csv_bytes(doc).decode('utf-8-sig'))

    def test_company_in_reason_is_not_an_extra_recommendation(self):
        rows = self.parse('▶▶ 최종 PICK\n삼성전자\n- SK하이닉스와 신규 계약', evidence_type='공개 기사')
        self.assertEqual([x['code'] for x in rows], ['005930'])

    def test_nonpublic_video_has_no_metadata_records(self):
        with patch.object(r, 'captions', side_effect=r.PublicUnavailable('회원 영상')):
            with self.assertRaises(r.PublicUnavailable):
                r.document({**self.meta, 'kind': 'youtube', 'title': '삼성전자 신규추천'})

    def test_public_url_and_date_guards(self):
        for url in ['http://www.youtube.com/watch?v=x', 'https://127.0.0.1/', 'https://www.youtube.com.evil.test/', 'https://a:b@www.youtube.com/']:
            with self.assertRaises(ValueError):
                r.allowed(url)
        with self.assertRaises(ValueError):
            r.valid_day('../2026-10-30')

    def test_feed_publication_converts_utc_to_kst(self):
        xml = '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><entry><yt:videoId>abcdefghijk</yt:videoId><title>삼성전자</title><published>2026-10-30T16:00:00Z</published></entry></feed>'
        self.assertEqual(r.feed_entries(xml)[0]['published_at'][:16], '2026-10-31T01:00')

    def test_caption_failure_metadata_is_not_advice(self):
        item = {**self.meta, 'kind': 'youtube', 'title': '2026-10-30 삼성전자 신규추천 목표가 9만원', 'description': '김민수 전문가'}
        with patch.object(r, 'captions', side_effect=ValueError('자막 없음')), patch.object(r.watchlists, 'names', return_value=self.names):
            records, warning = r.document(item)
        self.assertEqual(warning, '자막 없음')
        self.assertEqual(records, [])

    def test_registered_youtube_uses_public_script_after_empty_caption(self):
        item = {**self.meta, 'kind': 'youtube', 'title': '신규추천'}
        public_script = [{'offset': 1, 'text': '오늘의 추천'}, {'offset': 5, 'text': '삼성전자'}]
        with patch.object(r, 'captions', side_effect=ValueError('자막 없음')), patch.object(r.watchlists, 'names', return_value=self.names):
            rows, warning = r.document(item, browser_fallback=lambda url: public_script)
        self.assertIsNone(warning)
        self.assertEqual([(a['code'], a['evidence_type']) for a in rows], [('005930', '공개 브라우저 스크립트')])

    def test_named_signal_keeps_pick_and_price_separate_from_mentions(self):
        lines = [
            {'offset': 1, 'text': '관심주로는 어떤 걸 볼까요? 오늘 첫'},
            {'offset': 6, 'text': '번째 종목은 산일 전기 준비해 봤습니다.'},
            {'offset': 18, 'text': '삼성전자와도 사업 비교가 가능합니다. 신규 수주가 늘었습니다.'},
            {'offset': 42, 'text': '매수가는 현재가 목표가는 15만 원, 손절가 10만5,000원입니다.'},
            {'offset': 54, 'text': '오늘 두 번째 시그널 종목은 RF 머틀리얼즈입니다.'},
            {'offset': 89, 'text': '매수가는 현재가 목표가는 35,000원, 손절가는 2만 원입니다.'},
        ]
        names = {**self.names, '062040': '산일전기', '327260': 'RF머트리얼즈'}
        meta = {**self.meta, 'broadcaster': '매일경제TV', 'title': '[이효근의 주도주 시그널] 산일전기, RF머트리얼즈 / 이효근 MBN골드 매니저',
                'evidence_type': '공개 브라우저 스크립트'}
        with patch.object(r.watchlists, 'names', return_value=names):
            rows = r.transcript_records(lines, meta)
        self.assertEqual([(x['code'], x['expert'], x['target_price']['min'], x['stop_price']['min']) for x in rows],
                         [('062040', '이효근', 150000, 105000), ('327260', '이효근', 35000, 20000)])
        self.assertTrue(all(x['buy_price'] is None and x['buy_price_basis'] == '현재가 (원문)' for x in rows))

    def test_html_keeps_inline_name_and_article_boundary(self):
        page = r.Page('<nav>SK하이닉스</nav><article><p>▶<b>삼성전자</b>(005930)</p><p>- 실적 성장</p></article><script>bad</script>')
        self.assertNotIn('SK하이닉스', page.text())
        self.assertIn('삼성전자(005930)', page.text())

    def test_common_profile_includes_recommendations(self):
        import stock_profiles
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            r.merge(data, '2026-10-30', self.parse('오늘의 추천\n삼성전자'))
            self.assertIn('005930', stock_profiles.collect(data, '2026-10-30')[0])

    def test_csv_formula_protection(self):
        rows = self.parse('오늘의 추천\n삼성전자')
        rows[0]['reason'] = '=HYPERLINK("bad")'
        self.assertIn("'=HYPERLINK", r.csv_bytes({'records': rows}).decode('utf-8-sig'))

    def test_network_failure_keeps_saved_records_and_records_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            r.merge(data, '2026-10-30', self.parse('오늘의 추천\n삼성전자'))
            config = {'programs': [{'kind': 'mtn', 'url': 'https://www.mtn.co.kr/program/588', 'name': '표본'}], 'channels': []}
            with patch.object(r, 'sources', return_value=config), patch.object(r, 'fetch', side_effect=OSError('연결 단절')), patch.dict(r.STATE, last_run=r.stamp()):
                self.assertTrue(r.RUN.acquire(blocking=False))
                r.worker(data)
            self.assertEqual(len(r.read(data, '2026-10-30')['records']), 1)
            self.assertEqual(next(iter(r.ledger(data)['sources'].values()))['status'], '수집 실패')
            self.assertFalse(r.RUN.locked())

    def test_thread_start_failure_does_not_leave_collector_busy(self):
        with patch.object(r.threading.Thread, 'start', side_effect=RuntimeError('시작 실패')), patch.dict(r.STATE):
            with self.assertRaises(RuntimeError):
                r.start(Path('unused'))
            self.assertFalse(r.STATE['busy'])
            self.assertFalse(r.RUN.locked())

    def test_public_video_listing_supplements_rss_ids(self):
        content='var ytInitialData = '+json.dumps({'contents':[{'videoRenderer':{'videoId':'abcdefghijk','title':{'runs':[{'text':'공개 회차'}]}}}]})+';'
        rows=r.channel_video_entries(content)
        self.assertEqual(rows[0]['url'],'https://www.youtube.com/watch?v=abcdefghijk')
        self.assertIsNone(rows[0]['published_at'])

    def test_channel_list_recovers_when_feed_fails(self):
        def lockup(code, age):
            return {'lockupViewModel': {'contentId': code, 'contentType': 'LOCKUP_CONTENT_TYPE_VIDEO',
                'metadata': {'lockupMetadataViewModel': {'title': {'content': '공개 회차'}, 'metadata': {'contentMetadataViewModel': {
                    'metadataRows': [{'metadataParts': [{'text': {'content': age}}]}]}}}}}}
        listing = 'var ytInitialData = ' + json.dumps({'contents': [lockup('abcdefghijk', '2시간 전'), lockup('abcdefghijl', '5일 전')]}) + ';'
        with patch.object(r, 'fetch', side_effect=[OSError('피드 404'), listing]):
            rows, warning = r.youtube_listing('UC' + 'a' * 22)
        self.assertIn('공개 동영상 목록', warning)
        self.assertEqual([row['url'] for row in rows], ['https://www.youtube.com/watch?v=abcdefghijk'])
        self.assertIsNone(rows[0]['published_at'])

    def test_mtn_empty_listing_is_warning_not_silent_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)
            config={'programs':[{'kind':'mtn','url':'https://www.mtn.co.kr/program/588','name':'표본'}],'channels':[]}
            with patch.object(r,'sources',return_value=config),patch.object(r,'discover_mtn',return_value=[]),patch.dict(r.STATE,last_run=r.stamp()):
                self.assertTrue(r.RUN.acquire(blocking=False));r.worker(data)
            source=next(iter(r.ledger(data)['sources'].values()))
            self.assertEqual(source['status'],'확인 필요')
            self.assertIn('0건',source['message'])

    def test_rss_limit_supplements_listing_without_silent_success(self):
        feed=[{'url':'https://www.youtube.com/watch?v='+str(i).zfill(11),'published_at':r.stamp(),'title':'표본','description':''} for i in range(15)]
        extra={'url':'https://www.youtube.com/watch?v=abcdefghijk','title':'추가 회차','published_at':None,'description':''}
        source={'url':'https://www.youtube.com/channel/UC'+'a'*22,'channel_id':'UC'+'a'*22,'name':'표본'}
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)
            with patch.object(r,'sources',return_value={'programs':[],'channels':[source]}),patch.object(r,'fetch',return_value='public'),patch.object(r,'feed_entries',return_value=feed),patch.object(r,'channel_video_entries',return_value=[extra]),patch.object(r,'document',return_value=([],None)),patch.dict(r.STATE,last_run=r.stamp()):
                self.assertTrue(r.RUN.acquire(blocking=False));r.worker(data)
            book=r.ledger(data)
            self.assertIn(extra['url'],book['documents'])
            self.assertEqual(book['sources'][source['url']]['status'],'범위 제한')


if __name__ == '__main__':
    unittest.main()
