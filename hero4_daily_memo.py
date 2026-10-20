"""Queue dated Infostock reasons; write Hero4 memos only while HTS is closed."""
import argparse
from datetime import datetime
import json
import msvcrt
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'collector'))
import reasons
import hero4memo
import hero4_memo_import as importer
from kiwoom import KST

DATA = ROOT / 'collector' / 'data'
STATE = DATA / 'hero4_daily_memo'


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def dated_lines(day, items):
    datetime.strptime(day, '%Y-%m-%d')
    result = {}
    for code, item in items.items():
        reason = reasons.clean(item.get('reason', ''))
        if re.fullmatch(r'[0-9A-Z]{6}', code) and reason and reason != '확인불가':
            line = day + ' ' + reason
            if '\u2126' in line:
                raise ValueError('메모 구분문자 충돌')
            line.encode('cp949')
            result[code] = [line]
    return result


def candidate(raw, incoming):
    # Existing importer checks encoding, preserves personal notes and deduplicates.
    appended, added, _ = importer.build(raw, incoming)
    ordered, _, _ = importer.build(appended, incoming, top=True)
    return ordered, added


def apply_pending(incoming, target):
    importer.ensure_closed()
    original = target.read_bytes()
    updated, added = candidate(original, incoming)
    if updated == original:
        return 0
    backup = STATE / ('original-' + importer.digest(original) + '.dat')
    if not backup.exists():
        backup.write_bytes(original)
    if backup.read_bytes() != original:
        raise RuntimeError('메모 백업 검증 실패')
    temporary = target.with_name(target.name + '.daily-memo.tmp')
    try:
        importer.ensure_closed()
        with temporary.open('xb') as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        if target.read_bytes() != original:
            raise RuntimeError('메모 변경 감지: 기존 파일 유지')
        importer.ensure_closed()
        os.replace(temporary, target)
        if target.read_bytes() != updated:
            raise RuntimeError('메모 저장 후 검증 실패')
    finally:
        if temporary.exists():
            temporary.unlink()
    return added


def tick(day, prepare_only=False):
    queue_path = STATE / 'pending.json'
    queue = json.loads(queue_path.read_text(encoding='utf-8')) if queue_path.exists() else {}
    stored = reasons.read_day(DATA, day).get('infostock', {})
    items = stored.get('items', {})
    article = reasons.read_hero4() if reasons.HERO4_NEWS.is_file() else None
    if article and article[0] == day:
        items = reasons.parse(article[2], {}) or items
    incoming = dated_lines(day, items)
    if incoming:
        # Preserve previously queued lines, even if the later article has fewer rows.
        for code, lines in incoming.items():
            queue[code] = list(dict.fromkeys(queue.get(code, []) + lines))
        save(queue_path, queue)
    report = {'day': day, 'at': datetime.now(KST).isoformat(timespec='seconds'),
              'today_symbols': len(incoming), 'pending_symbols': len(queue),
              'source_ready': bool(incoming), 'state': 'prepared' if prepare_only else 'no_source'}
    if queue and not prepare_only:
        try:
            report['added_entries'] = apply_pending(queue, hero4memo.HERO4_MEMO)
            save(queue_path, {})
            report['pending_symbols'] = 0
            report['state'] = 'saved'
        except RuntimeError as exc:
            if '실행 중' not in str(exc):
                raise
            report['state'] = 'waiting_for_hero4_exit'
    save(STATE / 'status.json', report)
    return report


def locked_tick(day, prepare_only=False):
    # Share the queue lock only while reading/updating it, never during sleep.
    with (STATE / 'worker.lock').open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return {'day': day, 'state': 'existing_worker_busy'}
        try:
            return tick(day, prepare_only)
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--day', default=datetime.now(KST).date().isoformat())
    parser.add_argument('--prepare', action='store_true', help='No writes to Hero4')
    parser.add_argument('--watch', action='store_true', help='Retry for up to 14 hours')
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'watcher.lock').open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print('{"state":"already_running"}')
            return
        deadline = time.monotonic() + 14 * 3600
        while True:
            try:
                result = locked_tick(args.day, args.prepare)
            except Exception as exc:
                result = {'day': args.day, 'state': 'error', 'message': str(exc),
                          'at': datetime.now(KST).isoformat(timespec='seconds')}
                save(STATE / 'status.json', result)
            if not args.watch or (result.get('state') == 'saved' and result.get('source_ready')):
                print(json.dumps(result, ensure_ascii=True))
                return
            if time.monotonic() >= deadline:
                result['watch_expired'] = True
                save(STATE / 'status.json', result)
                return
            time.sleep(60)


if __name__ == '__main__':
    main()
