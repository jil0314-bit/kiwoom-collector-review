"""Fill empty collector notes and queue the same dated evidence for a closed Hero4."""
import json
import msvcrt
import re
import sys
import threading
from pathlib import Path

import archive
import notes
import reasons

LOCK = threading.Lock()


def evidence(record, stock, day):
    code, name = stock['code'], stock['name']
    info = record.get('infostock', {}).get('items', {}).get(code)
    if info:
        source = record['infostock'].get('source', '')
        return info['reason'], '인포스탁', source if source.startswith('https://') else '영웅문 증시요약(6)', '기사 사유'
    reviewed = record.get('reviewed', {}).get('items', {}).get(code)
    if reviewed:
        return reviewed['reason'], reviewed.get('source', '검토 자료'), reviewed.get('url', ''), '출처 분석'
    for item in record.get('news', {}).get('items', {}).get(code, []):
        title, summary = item.get('title', ''), item.get('summary', '')
        # A market-wide headline is not this stock's reason merely because it is in its feed.
        if (name in title or name in summary) and reasons.RISING.search(title + ' ' + summary):
            return title, item.get('office', '뉴스'), item.get('url', ''), '관련 보도 · 직접 상승 원인 미확정'
    return None


def from_note(text):
    """Copy existing researched reasons, never reinterpret unrelated personal text."""
    if '판정: 미확인' in text or '판정: 근거없음' in text:
        return None
    match = re.search(r'상승 관련 배경:\s*(.+?)(?:\n\n|$)', text, re.S)
    urls = re.findall(r'https://[^\s]+', text)
    if match and urls:
        return reasons.clean(match[1]), '기존 수집기 조사', urls[0], '기존 기재 내용'
    return None


def block(day, item):
    reason, source, url, verdict = item
    return f'[자동 상승 사유 | {day}]\n판정: {verdict}\n{reason}\n출처: {source}\n{url}\n[/자동 상승 사유]'.strip()


def hero_line(day, item):
    reason, source, url, verdict = item
    text = reasons.clean(f'{day} {reason} | {verdict} | 출처: {source} {url}')
    # Hero4's memo format is CP949. Replace unrepresentable decorative characters only.
    return text.replace('\u2126', ' ').encode('cp949', errors='replace').decode('cp949')


def merge_queue(previous, incoming):
    result = list(previous)
    for line in incoming:
        # Replace only our queued UNKNOWN for this date, never personal memos.
        if ' 출처: ' in line and '구체적 상승 사유 미확인.' not in line:
            result = [old for old in result if not (
                old.startswith(line[:10] + ' 조회한 당일 기사·종목 뉴스에서 구체적 상승 사유 미확인. 추측하여 기재하지 않음. 미확인 출처: '))]
        if line not in result:
            result.append(line)
    return result


def sync_all(data, through, *, apply=True, mark_unknown=False):
    """Never overwrite existing text; never write an open HTS's memo file."""
    with LOCK:
        state = data / 'hero4_daily_memo'
        state.mkdir(parents=True, exist_ok=True)
        report = {'through': through, 'notes_added': 0, 'notes_updated': 0, 'by_day': [], 'hero_state': 'prepared'}
        incoming = {}
        for folder in sorted(data.glob('????-??-??')):
            day = folder.name
            if not folder.is_dir() or day > through:
                continue
            stocks = archive.metadata(archive.active(data, day)).get('stocks', [])
            record, existing = reasons.read_day(data, day), notes.read_day(data, day)
            added, missing, supported = 0, [], 0
            for stock in stocks:
                code = stock['code']
                note = existing.get(code, {})
                text = note.get('text', '').strip()
                item = evidence(record, stock, day)
                researched = from_note(text) if text else None
                owned = re.search(r'\[자동 상승 사유 \| ' + re.escape(day) + r'\].*?\[/자동 상승 사유\]', text, re.S)
                if item or researched:
                    supported += 1
                else:
                    missing.append({'code': code, 'name': stock['name']})
                if not item and (mark_unknown or owned):
                    item = ('조회한 당일 기사·종목 뉴스에서 구체적 상승 사유 미확인. 추측하여 기재하지 않음.',
                            '인포스탁 저장 기사·네이버 종목 뉴스 조회 범위', '', '미확인')
                if item and (not text or owned or item[3] != '미확인'):
                    replacement = (text[:owned.start()] + block(day, item) + text[owned.end():]
                                   if owned else text + ('\n\n' if text else '') + block(day, item))
                    if replacement != text:
                        try:
                            notes.write(data, day, code, replacement, note.get('revision', ''), stock['name'])
                        except notes.Conflict:
                            continue
                        if not text:
                            added += 1
                        else:
                            report['notes_updated'] += 1
                if text:
                    # Prefer the previously written research when preserving an existing note.
                    item = item or researched
                if item:
                    incoming.setdefault(code, []).append(hero_line(day, item))
            report['notes_added'] += added
            report['by_day'].append({'day': day, 'stocks': len(stocks), 'added': added, 'supported': supported, 'unconfirmed': missing})
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import hero4_daily_memo as writer
        with (state / 'worker.lock').open('a+b') as lock:
            if lock.tell() == 0:
                lock.write(b'0'); lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                report['hero_state'] = 'existing_worker_busy'
            else:
                try:
                    file = state / 'pending.json'
                    queue = json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
                    # Reuse identical legacy dated reasons rather than adding their source-decorated duplicate.
                    current_memos = writer.hero4memo.parse(writer.hero4memo.HERO4_MEMO.read_bytes())
                    for code, lines in incoming.items():
                        chunks = writer.hero4memo.BREAK.split(current_memos.get(code, ''))
                        lines = [next((old for old in chunks if old == line.split(' | ', 1)[0]), line) for line in lines]
                        queue[code] = merge_queue(queue.get(code, []), lines)
                    writer.save(file, queue)
                    report['hero_pending_symbols'] = len(queue)
                    if apply and queue:
                        try:
                            report['hero_added_lines'] = writer.apply_pending(queue, writer.hero4memo.HERO4_MEMO)
                            writer.save(file, {})
                            report['hero_pending_symbols'] = 0
                            report['hero_state'] = 'saved'
                        except RuntimeError as exc:
                            if '실행 중' not in str(exc):
                                raise
                            report['hero_state'] = 'waiting_for_hero4_exit'
                finally:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        writer.save(state / 'sync_report.json', report)
        return report
