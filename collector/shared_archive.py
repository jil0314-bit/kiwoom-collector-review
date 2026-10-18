"""Single-writer archive sharing. Never copy credentials or trading programs."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

import archive
from kiwoom import KST

ROOT = Path(__file__).resolve().parent
AUX = ('notes', 'reasons', 'themes', 'chart_history', 'weekly_history',
       'watchlist_history', 'volume_surge', 'investor_flows')
CODE = ('app.py', 'archive.py', 'kiwoom.py', 'chart.py', 'chart_data.py',
        'notes.py', 'reasons.py', 'themes.py', 'volume_surge.py', 'watchlists.py',
        'hero4memo.py', 'hero_link.py', 'window.py', 'shared_archive.py',
        'shared_viewer.py', 'shared_start.ps1', '공유수집기시작.cmd', '공유사용방법.txt', 'collector.ico',
        'investor_flows.py')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def regular(path):
    path = Path(path)
    return path.is_file() and not path.is_symlink() and not any(
        p.is_symlink() or p.is_junction() for p in (path, *path.parents))


def zip_files(destination, files, extra=None):
    """Build locally and publish one completed file. Embedded hashes cover all data."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='top100-share-') as tmp:
        packed = Path(tmp) / 'bundle.zip'
        hashes = {}
        with zipfile.ZipFile(packed, 'w', zipfile.ZIP_DEFLATED, compresslevel=3) as z:
            def put(name, blob):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, blob)
            for path, name in files:
                if not regular(path):
                    raise ValueError('공유 자료에 연결 경로나 누락 파일이 있습니다.')
                before = path.stat()
                blob = path.read_bytes()
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('자료가 갱신 중입니다. 다음 동기화 때 다시 시도합니다.')
                put(name, blob)
                hashes[name] = hashlib.sha256(blob).hexdigest()
            for name, value in (extra or {}).items():
                blob = json.dumps(value, ensure_ascii=False).encode('utf-8')
                put(name, blob)
                hashes[name] = hashlib.sha256(blob).hexdigest()
            put('_bundle_manifest.json', json.dumps({'sha256': hashes}).encode('utf-8'))
        checksum = digest(packed)
        # Do not replace an identical cloud object: avoids unnecessary transfers.
        if not destination.is_file() or digest(destination) != checksum:
            target = destination.with_name(destination.name + '.tmp-' + uuid.uuid4().hex)
            try:
                shutil.copyfile(packed, target)
                os.replace(target, destination)
            finally:
                target.unlink(missing_ok=True)
        return {'file': destination.name, 'sha256': checksum, 'bytes': destination.stat().st_size}


def profiles():
    import watchlists
    import hero4memo
    # Only selected watchlists, stock names and displayed memos. No full Hero profile.
    return {'groups': watchlists.groups(), 'names': watchlists.names(),
            'hero4': hero4memo.load()}


def publish(folder, data=None, source_root=None):
    source_root = Path(source_root or ROOT).resolve()
    data = Path(data or source_root / 'data').resolve()
    folder = Path(folder).resolve()
    if folder == data or data in folder.parents or folder in data.parents:
        raise ValueError('원본 자료와 공유 폴더는 분리해야 합니다.')
    folder.mkdir(parents=True, exist_ok=True)
    parts = []
    for day_root in sorted(data.glob('????-??-??')):
        day = day_root.name
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
            continue
        active = archive.active(data, day)
        meta = archive.metadata(active)
        if meta.get('status') != 'saved':
            continue
        pointer = (day_root / 'latest.json').read_bytes() if (day_root / 'latest.json').is_file() else None
        files = [(p, p.relative_to(data).as_posix()) for p in active.rglob('*')
                 if p.is_file() and not p.name.endswith('.tmp')]
        if pointer is not None:
            files.append((day_root / 'latest.json', day + '/latest.json'))
        part = zip_files(folder / ('day-' + day + '.zip'), files)
        if archive.active(data, day) != active or (pointer is not None and (day_root / 'latest.json').read_bytes() != pointer):
            raise ValueError('순위 자료가 교체 중입니다. 다음 동기화 때 다시 시도합니다.')
        parts.append(part)
    aux_files = [(p, p.relative_to(data).as_posix()) for name in AUX
                 for p in (data / name).rglob('*') if p.is_file()
                 and (p.name.endswith(('.json', '.json.gz', '.csv', '.sha256')))
                 and not p.name.startswith('last_error') and '.tmp' not in p.name]
    parts.append(zip_files(folder / 'extra-data.zip', aux_files,
                           {'shared-profiles.json': profiles()}))
    old_path = folder / 'snapshot.json'
    previous = json.loads(old_path.read_text(encoding='utf-8')) if old_path.is_file() else {}
    if previous.get('parts') != parts:
        write_json(old_path, {'schema': 1, 'generation': uuid.uuid4().hex,
                             'published_at': datetime.now(KST).isoformat(timespec='seconds'),
                             'parts': parts})
    return json.loads(old_path.read_text(encoding='utf-8'))


def installer(path):
    files = [(ROOT / name, name) for name in CODE]
    files += [(p, p.relative_to(ROOT).as_posix()) for p in (ROOT / 'web').rglob('*') if p.is_file()]
    return zip_files(path, files)


def unpack_checked(path, target):
    target = Path(target).resolve()
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if len(set(names)) != len(names) or '_bundle_manifest.json' not in names:
            raise ValueError('공유 압축 파일 형식 오류')
        hashes = json.loads(z.read('_bundle_manifest.json'))['sha256']
        if set(names) != set(hashes) | {'_bundle_manifest.json'}:
            raise ValueError('공유 파일 목록 불일치')
        for info in z.infolist():
            name = info.filename
            if name == '_bundle_manifest.json':
                continue
            if '\\' in name or ':' in name or name.startswith('/') or '..' in Path(name).parts:
                raise ValueError('공유 파일 경로 오류')
            dest = (target / name).resolve()
            if target not in dest.parents or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('공유 연결 경로 차단')
            blob = z.read(name)
            if hashlib.sha256(blob).hexdigest() != hashes[name]:
                raise ValueError('공유 자료 해시 불일치')
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(blob)


def receive(folder, cache):
    folder, cache = Path(folder).resolve(), Path(cache).resolve()
    doc = json.loads((folder / 'snapshot.json').read_text(encoding='utf-8'))
    gen = doc.get('generation', '')
    if doc.get('schema') != 1 or not re.fullmatch('[a-f0-9]{32}', gen):
        raise ValueError('공유 목록 형식 오류')
    target = cache / ('generation-' + gen)
    ready = target / '_shared_ready.json'
    if ready.is_file():
        return target, doc
    target.mkdir(parents=True, exist_ok=True)
    try:
        for part in doc['parts']:
            name = part['file']
            if not re.fullmatch(r'(day-\d{4}-\d{2}-\d{2}|extra-data)\.zip', name):
                raise ValueError('공유 압축 파일 이름 오류')
            source = folder / name
            # Copy first: OneDrive may replace the source while it is being read.
            with tempfile.TemporaryDirectory(prefix='top100-receive-') as tmp:
                packed = Path(tmp) / name
                shutil.copyfile(source, packed)
                if digest(packed) != part['sha256']:
                    raise ValueError('OneDrive 동기화 진행 중입니다. 기존 자료를 유지합니다.')
                unpack_checked(packed, target)
        write_json(ready, doc)
        write_json(cache / 'last-ready.json', {'folder': target.name})
        return target, doc
    except Exception:
        # This is a newly created, unpublished receiver directory only.
        if target.parent != cache or not re.fullmatch('generation-[a-f0-9]{32}', target.name):
            raise ValueError('임시 자료 정리 경로 오류')
        shutil.rmtree(target)
        raise


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--folder', type=Path, required=True)
    p.add_argument('--loop', action='store_true')
    args = p.parse_args()
    while True:
        try:
            doc = publish(args.folder)
            print('공유 자료 준비 완료: ' + doc['published_at'], flush=True)
        except Exception:
            print('동기화 보류: 원본 갱신 또는 파일 접근 상태를 확인하세요. 기존 공유 자료는 유지합니다.', flush=True)
            if not args.loop:
                raise SystemExit(1)
        if not args.loop:
            break
        time.sleep(300)


if __name__ == '__main__':
    main()
