"""Atomic daily snapshot pointer and narrowly scoped old-snapshot removal."""
import json
import os
import re
import shutil
import stat
import threading
from datetime import datetime
from pathlib import Path

LOCK = threading.RLock()
SNAPSHOT = re.compile(r'snapshot-[0-9a-f]{32}')


def day_root(data, day):
    if datetime.strptime(day, '%Y-%m-%d').strftime('%Y-%m-%d') != day:
        raise ValueError('날짜 형식 오류')
    root = Path(data).resolve()
    folder = root / day
    if folder.resolve() != folder or folder.resolve().parent != root:
        raise ValueError('자료 경로가 저장소를 벗어남')
    return folder


def metadata(folder):
    p = folder / 'index.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.is_file() else {}


def active(data, day):
    folder = day_root(data, day)
    pointer = folder / 'latest.json'
    if pointer.is_file():
        name = json.loads(pointer.read_text(encoding='utf-8')).get('folder', '')
        if not SNAPSHOT.fullmatch(name):
            raise ValueError('최신 자료 포인터 형식 오류')
        target = folder / name
        if target.resolve().parent != folder.resolve():
            raise ValueError('최신 자료 경로 오류')
        return target
    # Read legacy data until the first successful replacement, without copying it.
    candidates = [folder / k for k in ('final', 'preview') if (folder / k / 'index.json').is_file()]
    return max(candidates, key=lambda p: metadata(p).get('ranking_at','')) if candidates else folder / 'latest-missing'


def remove_snapshot(data, day, target):
    """Never traverse links/junctions or delete a date folder or unrelated files."""
    parent = day_root(data, day).resolve()
    target = Path(target)
    if target.name not in ('final', 'preview') and not SNAPSHOT.fullmatch(target.name):
        raise ValueError('삭제 대상 이름 오류')
    if target.resolve().parent != parent or target.parent.resolve() != parent:
        raise ValueError('삭제 대상 경로 오류')
    if not target.exists():
        return
    def regular(path):
        info = path.lstat()
        if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('연결 경로 삭제 차단')
    regular(target)
    for root, dirs, files in os.walk(target, followlinks=False):
        for name in dirs + files:
            regular(Path(root) / name)
    shutil.rmtree(target)


def publish(data, day, target, save):
    with LOCK:
        meta = metadata(target)
        if meta.get('status') != 'saved' or not meta.get('stocks'):
            raise ValueError('완료되지 않은 자료 교체 차단')
        parent = day_root(data, day)
        if target.resolve().parent != parent.resolve() or not SNAPSHOT.fullmatch(target.name):
            raise ValueError('새 자료 경로 오류')
        save(parent / 'latest.json', {'folder': target.name, 'revision': meta['revision']})
        # The pointer is committed first. A crash here leaves an extra old copy,
        # never a missing committed snapshot. The next publish retries cleanup.
        pending = []
        for old in parent.iterdir():
            if old == target or (old.name not in ('final', 'preview') and not SNAPSHOT.fullmatch(old.name)):
                continue
            try:
                remove_snapshot(data, day, old)
            except (OSError, ValueError):
                pending.append(old.name)
        return pending


def payload(data, day, code=None, suffix='.json', revision=None):
    with LOCK:
        folder = active(data, day)
        meta = metadata(folder)
        if revision and meta.get('revision', meta.get('ranking_at')) != revision:
            return None, True
        path = folder / (code + suffix if code else 'index.json')
        return (path.read_bytes() if path.is_file() else None), False
