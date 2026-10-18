"""Notes only: temporary folders, no broker calls or real archive mutation."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import notes
from kiwoom import DataError


class NoteTests(unittest.TestCase):
    def test_reason_sync_preserves_personal_notes_and_waits_for_closed_hts(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import reason_memos
        import hero4_daily_memo as writer
        import hero4_memo_import as importer
        import reasons
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '2026-10-13').mkdir()
            target = root / 'hero.dat'
            raw = importer.encode('005930=기존 영웅문 메모') + b'\r\n'
            target.write_bytes(raw)
            personal = notes.write(root, '2026-10-13', '000660', '기존 개인 의견')
            reasons.save_infostock(root, '2026-10-13', '삼성전자 (005930) 100원 (+10%) | | 수주 소식에 상승', {})
            stocks = [{'code': '005930', 'name': '삼성전자'}, {'code': '000660', 'name': 'SK하이닉스'}]
            with patch.object(reason_memos.archive, 'metadata', return_value={'stocks': stocks}), \
                 patch.object(writer.hero4memo, 'HERO4_MEMO', target), \
                 patch.object(writer, 'apply_pending', side_effect=RuntimeError('영웅문이 실행 중입니다.')):
                result = reason_memos.sync_all(root, '2026-10-13', mark_unknown=True)
                self.assertEqual(result['hero_state'], 'waiting_for_hero4_exit')
                self.assertEqual(target.read_bytes(), raw)
                self.assertEqual(notes.read_day(root, '2026-10-13')['000660'], personal)
                second = reason_memos.sync_all(root, '2026-10-13', apply=False, mark_unknown=True)
                self.assertEqual(second['notes_added'], 0)
                self.assertEqual(second['notes_updated'], 0)
                self.assertIn('수주 소식', notes.read_day(root, '2026-10-13')['005930']['text'])

    def test_market_wide_news_is_not_written_as_a_stock_reason(self):
        import reason_memos
        stock = {'code': '005930', 'name': '삼성전자'}
        record = {'news': {'items': {'005930': [{'title': '코스피 상승 마감', 'summary': '시장 전체가 상승'}]}}}
        self.assertIsNone(reason_memos.evidence(record, stock, '2026-10-13'))

    def test_memo_reordering_is_lossless_and_puts_evidence_above_unconfirmed(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import hero4_daily_memo as writer
        import hero4_memo_import as importer
        unknown = '2026-10-13 조회한 당일 기사·종목 뉴스에서 구체적 상승 사유 미확인.'
        factual = '2026-10-13 계약 체결 소식에 상승'
        raw = importer.encode('005930=개인 메모') + b'\r\n'
        result, _ = writer.candidate(raw, {'005930': [unknown, factual]})
        text = writer.hero4memo.parse(result)['005930']
        self.assertTrue(text.startswith(factual))
        self.assertIn('개인 메모', text)
        self.assertEqual(writer.candidate(result, {'005930': [unknown, factual]})[0], result)

    def test_persistence_day_symbol_isolation_and_empty_note(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            first=notes.write(root,'2026-09-22','005930','확인된 사실\n출처 https://example.com\n추정은 별도',name='삼성전자')
            notes.write(root,'2026-09-23','005930','다른 날짜')
            notes.write(root,'2026-09-22','000660','다른 종목')
            self.assertEqual(notes.read_day(root,'2026-09-22')['005930'],first)
            self.assertEqual(notes.read_day(root,'2026-09-23')['005930']['text'],'다른 날짜')
            notes.write(root,'2026-09-22','005930','',first['revision'])
            self.assertEqual(notes.read_day(root,'2026-09-22')['005930']['text'],'')
            self.assertEqual(notes.read_day(root,'2026-09-22')['000660']['text'],'다른 종목')

    def test_stale_writer_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            saved=notes.write(root,'2026-09-22','005930','기존 내용')
            with self.assertRaises(notes.Conflict):
                notes.write(root,'2026-09-22','005930','다른 창 내용')
            self.assertEqual(notes.read_day(root,'2026-09-22')['005930'],saved)

    def test_failed_replace_keeps_saved_note(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            saved=notes.write(root,'2026-09-22','005930','원본')
            with patch.object(notes.os,'replace',side_effect=OSError('disk')):
                with self.assertRaises(OSError):
                    notes.write(root,'2026-09-22','005930','새 내용',saved['revision'])
            self.assertEqual(notes.read_day(root,'2026-09-22')['005930'],saved)
            self.assertFalse(list(root.rglob('*.tmp')))

    def test_limits_paths_and_plaintext(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for day,code in [('../2026-09-22','005930'),('2026-09-22','../abc'),('2026-9-22','005930')]:
                with self.assertRaises((ValueError,DataError)):
                    notes.write(root,day,code,'bad')
            with self.assertRaises(DataError):
                notes.write(root,'2026-09-22','005930','가'*20001)
            raw='<script>alert(1)</script>\n'+'가'*15000
            saved=notes.write(root,'2026-09-22','005930',raw)
            self.assertEqual(notes.read_day(root,'2026-09-22')['005930']['text'],raw)
            self.assertTrue(saved['revision'])

    def test_notes_are_outside_replaced_snapshots(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);snapshot=root/'2026-09-22'/'final';snapshot.mkdir(parents=True)
            (snapshot/'005930.json').write_text('{"unchanged":true}')
            notes.write(root,'2026-09-22','005930','분봉과 별도 보관')
            self.assertEqual((snapshot/'005930.json').read_text(),'{"unchanged":true}')
            self.assertTrue((root/'notes'/'2026-09-22'/'005930.json').is_file())


if __name__=='__main__':
    unittest.main()
