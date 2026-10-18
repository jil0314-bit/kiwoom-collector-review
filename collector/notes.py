"""User notes live outside replaceable market snapshots."""
import json
import os
import threading
import uuid
from datetime import datetime

from kiwoom import DataError, KST, code_of

LOCK = threading.RLock()
MAX_TEXT = 20000


class Conflict(DataError):
    pass


def folder(data, day):
    if not isinstance(day, str) or datetime.strptime(day, '%Y-%m-%d').strftime('%Y-%m-%d') != day:
        raise DataError('메모 날짜 형식 오류')
    root = data.resolve()
    path = root / 'notes' / day
    if path.resolve() != path:
        raise DataError('메모 저장 경로 오류')
    return path


def read_day(data, day):
    with LOCK:
        path = folder(data, day)
        return {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in path.glob('*.json')
                if p.is_file() and not p.is_symlink()}


def write(data, day, code, text, revision='', name=''):
    code = code_of(code)
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        raise DataError('메모는 20,000자까지 저장할 수 있습니다.')
    if not isinstance(name, str) or len(name) > 100 or not isinstance(revision, str):
        raise DataError('메모 입력 형식 오류')
    with LOCK:
        path = folder(data, day) / (code + '.json')
        if path.is_symlink():
            raise DataError('메모 저장 경로 오류')
        previous = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
        if revision != previous.get('revision', ''):
            raise Conflict('다른 창에서 메모가 변경됐습니다. 작성 내용을 복사한 뒤 저장본을 다시 읽어주세요.')
        note = {'day': day, 'code': code, 'name': name, 'text': text,
                'updated_at': datetime.now(KST).isoformat(timespec='seconds'), 'revision': uuid.uuid4().hex}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        try:
            tmp.write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(tmp, path)
        finally:
            if tmp.is_file():
                tmp.unlink()
        return note
