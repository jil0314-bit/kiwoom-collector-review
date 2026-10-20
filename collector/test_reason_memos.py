import importlib.util
import json
import msvcrt
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import notes
import reason_memos as sync


class ReasonMemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.day = '2026-10-20'
        (self.data / self.day).mkdir()
        memo = self.data / 'fixture.dat'; memo.write_bytes(b'')
        self.writer = types.SimpleNamespace(
            hero4memo=types.SimpleNamespace(HERO4_MEMO=memo, parse=lambda raw: {}, BREAK=sync.re.compile('Ω+')),
            save=lambda p, v: p.write_text(json.dumps(v), encoding='utf-8'),
            apply_pending=lambda queue, target: len(queue))

    def run_sync(self, reason='공급계약 체결 소식에 급등', apply=False):
        record = {'infostock': {'source': 'hero4', 'items': {'000001': {'reason': reason}}}} if reason else {}
        with patch.object(sync.archive, 'active', return_value=self.data), \
             patch.object(sync.archive, 'metadata', return_value={'stocks': [{'code': '000001', 'name': '예제'}]}), \
             patch.object(sync.reasons, 'read_day', return_value=record), \
             patch.dict(sys.modules, {'hero4_daily_memo': self.writer}):
            return sync.sync_all(self.data, self.day, apply=apply, mark_unknown=not reason)

    def test_personal_note_is_preserved_and_reason_added_once(self):
        personal = '내 메모: 지지선 확인\n둘째 줄'
        notes.write(self.data, self.day, '000001', personal, '', '예제')
        self.run_sync(); self.run_sync()
        text = notes.read_day(self.data, self.day)['000001']['text']
        self.assertTrue(text.startswith(personal + '\n\n'))
        self.assertEqual(text.count('[자동 상승 사유 |'), 1)

    def test_only_owned_block_updates_and_queues_latest_reason(self):
        personal = '개인 메모'
        notes.write(self.data, self.day, '000001', personal, '', '예제')
        self.run_sync(reason=None)
        self.run_sync(reason='새 계약 소식에 급등')
        text = notes.read_day(self.data, self.day)['000001']['text']
        self.assertTrue(text.startswith(personal))
        self.assertIn('새 계약 소식', text)
        self.assertNotIn('구체적 상승 사유 미확인', text)

    def test_open_hero_keeps_pending_and_reports_waiting(self):
        def opened(*args): raise RuntimeError('영웅문이 실행 중입니다.')
        self.writer.apply_pending = opened
        report = self.run_sync(apply=True)
        self.assertEqual(report['hero_state'], 'waiting_for_hero4_exit')
        self.assertTrue(json.loads((self.data/'hero4_daily_memo/pending.json').read_text()))

    def test_verified_apply_clears_queue(self):
        report = self.run_sync(apply=True)
        self.assertEqual(report['hero_state'], 'saved')
        self.assertEqual(json.loads((self.data/'hero4_daily_memo/pending.json').read_text()), {})
        self.assertEqual(report['hero_pending_symbols'], 0)

    def test_queue_upgrades_only_owned_unknown(self):
        unknown = sync.hero_line(self.day, ('조회한 당일 기사·종목 뉴스에서 구체적 상승 사유 미확인. 추측하여 기재하지 않음.', '조회 범위', '', '미확인'))
        verified = sync.hero_line(self.day, ('계약 체결에 급등', '인포스탁', '영웅문 증시요약(6)', '기사 사유'))
        personal = self.day + ' 개인 메모: 미확인'
        self.assertEqual(sync.merge_queue([unknown, personal], [verified]), [personal, verified])


class QueueLockTests(unittest.TestCase):
    def test_queue_lock_is_released_between_ticks_and_on_error(self):
        spec = importlib.util.spec_from_file_location('memo_worker_fixture', Path(__file__).resolve().parent.parent/'hero4_daily_memo.py')
        worker = importlib.util.module_from_spec(spec)
        with patch.object(sys, 'path', [str(Path(__file__).resolve().parent.parent)] + sys.path):
            spec.loader.exec_module(worker)
        with tempfile.TemporaryDirectory() as tmp, patch.object(worker, 'STATE', Path(tmp)):
            with patch.object(worker, 'tick', return_value={'state': 'waiting_for_hero4_exit'}):
                self.assertEqual(worker.locked_tick('2026-10-20')['state'], 'waiting_for_hero4_exit')
            with patch.object(worker, 'tick', side_effect=ValueError('fixture error')):
                with self.assertRaises(ValueError): worker.locked_tick('2026-10-20')
            with (Path(tmp)/'worker.lock').open('r+b') as lock:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == '__main__': unittest.main()
