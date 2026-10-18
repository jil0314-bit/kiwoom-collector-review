"""Offline, append-only Hero4 memo import. Never modify a running HTS's file."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'collector'))
import hero4memo

PREVIEW = ROOT / 'collector/data/hero4_memo_import'
DRAFT = ROOT / '영웅문_최근3주_상승사유_입력대기.txt'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(text):
    raw = text.encode('cp949').hex().upper().encode('ascii')
    return bytes(v + hero4memo.KEY[j % len(hero4memo.KEY)] for j, v in enumerate(raw))


def additions():
    result, code = {}, None
    for line in DRAFT.read_text(encoding='utf-8-sig').splitlines():
        match = re.fullmatch(r'\[([0-9A-Z]{6})\] .+', line)
        if match:
            code = match[1]
        elif code and re.match(r'^2026-\d{2}-\d{2} ', line):
            if '\u2126' in line or '\r' in line:
                raise ValueError('메모 구분문자 충돌')
            line.encode('cp949')
            result.setdefault(code, []).append(line)
    if not result:
        raise ValueError('추가할 사유가 없습니다.')
    return result


def build(raw, incoming, top=False):
    rows = raw.split(b'\r\n')
    positions, old = {}, {}
    for index, row in enumerate(rows):
        text = hero4memo.decode_line(row)
        if row and encode(text) != row:
            raise ValueError('기존 파일 인코딩 검증 실패')
        match = hero4memo.ENTRY.match(text)
        if match:
            code, memo = match.groups()
            if code in positions:
                raise ValueError('기존 파일의 종목코드 중복: ' + code)
            positions[code], old[code] = index, memo
    expected = dict(old)
    added, changed = 0, 0
    for code, lines in incoming.items():
        memo = old.get(code, '')
        existing = set(hero4memo.BREAK.split(memo))
        if top:
            # Move only the imported lines already present. Do not recreate absent stocks.
            moving = sorted(set(lines) & existing,
                            key=lambda line: (line[:10], '조회한 당일 기사·종목 뉴스에서' not in line, line), reverse=True)
            if not moving:
                continue
            chunks = re.split(r'(\u2126+)', memo)
            for i in range(len(chunks)-1, -1, -2):
                if chunks[i] in moving:
                    if i+1 < len(chunks):
                        del chunks[i:i+2]
                    else:
                        del chunks[max(0, i-1):i+1]
            remaining = ''.join(chunks)
            combined = '\u2126\u2126'.join(moving) + ('\u2126\u2126' + remaining if remaining else '')
            if combined == memo:
                continue
            if Counter(filter(None, hero4memo.BREAK.split(combined))) != Counter(filter(None, hero4memo.BREAK.split(memo))):
                raise ValueError('정렬 중 메모 내용 보존 검증 실패')
            expected[code] = combined
            rows[positions[code]] = encode(code + '=' + combined)
            changed += 1
            continue
        unique = list(dict.fromkeys(line for line in lines if line not in existing))
        if not unique:
            continue
        combined = memo + ('\u2126\u2126' if memo else '') + '\u2126\u2126'.join(unique)
        expected[code] = combined
        row = encode(code + '=' + combined)
        if code in positions:
            rows[positions[code]] = row
        else:
            if rows and rows[-1] == b'':
                rows.insert(len(rows)-1, row)
            else:
                rows.append(row)
        added += len(unique)
        changed += 1
    candidate = b'\r\n'.join(rows)
    if hero4memo.parse(candidate) != expected:
        raise ValueError('전체 메모 재해석 검증 실패')
    # Reapplying the same input must be a no-op; original personal text is a prefix.
    for code, text in old.items():
        if not top and not expected[code].startswith(text):
            raise ValueError('기존 메모 보존 검증 실패')
    return candidate, added, changed


def ensure_closed():
    result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq nkrunlite.exe', '/FO', 'CSV', '/NH'],
                            capture_output=True, check=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if b'nkrunlite.exe' in result.stdout.lower():
        raise RuntimeError('영웅문이 실행 중입니다. 정상 종료 후 다시 실행하세요.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--top', action='store_true', help='Move existing imported reasons to the top, newest first')
    args = parser.parse_args()
    target = hero4memo.HERO4_MEMO
    original = target.read_bytes()
    candidate, added, changed = build(original, additions(), top=args.top)
    PREVIEW.mkdir(parents=True, exist_ok=True)
    (PREVIEW / 'candidate.dat').write_bytes(candidate)
    report = {'target': str(target), 'original_sha256': digest(original),
              'candidate_sha256': digest(candidate), 'added_entries': added,
              'changed_symbols': changed, 'existing_memos_preserved': True, 'applied': False,
              'operation': 'move_to_top' if args.top else 'append'}
    if args.apply and changed:
        ensure_closed()
        backup = PREVIEW / ('original-' + digest(original) + '.dat')
        if not backup.exists():
            backup.write_bytes(original)
        if backup.read_bytes() != original:
            raise RuntimeError('원본 백업 확인 실패')
        if target.read_bytes() != original:
            raise RuntimeError('메모 파일이 변경되었습니다. 다시 준비하세요.')
        ensure_closed()
        temporary = target.with_name(target.name + '.collector-import.tmp')
        with temporary.open('xb') as stream:
            stream.write(candidate)
            stream.flush()
            os.fsync(stream.fileno())
        if target.read_bytes() != original:
            raise RuntimeError('반영 직전 원본 변경 감지. 원본 유지.')
        ensure_closed()
        os.replace(temporary, target)
        if target.read_bytes() != candidate:
            raise RuntimeError('저장 후 바이트 검증 실패. 백업을 확인하세요.')
        report['applied'] = True
    (PREVIEW / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    main()
