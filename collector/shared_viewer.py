"""Separate local shared-archive viewer. The primary collector is unchanged."""
from __future__ import annotations
import argparse
import copy
import json
import os
import re
import threading
import time
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import app
import archive
import chart_data
import hero4memo
import hero_link
import watchlists
import kiwoom
from kiwoom import DataError
from shared_archive import receive

LOCK = threading.RLock()
STATE = {'published_at': '', 'error': ''}
IDENTITY = 'kiwoom-shared-archive-viewer-v1'
PROFILES = {}


def cached_history(data, day, code, subfolder, count=None, ttl=300):
    path = data / subfolder / day / (code + '.json')
    if not path.is_file():
        raise DataError('이 차트는 원본 PC에서 아직 저장하지 않았습니다. 원본 PC에서 조회한 뒤 동기화하세요.')
    return json.loads(path.read_text(encoding='utf-8'))


def cached_minute(data, day, code, name=None, ttl=300):
    saved = cached_history(data, day, code, 'watchlist_history')
    return {'day': day, 'stock': {'code': code, 'name': PROFILES.get('names', {}).get(code, code)},
            'bars': saved['bars'], 'fetched_at': saved['fetched_at']}, saved['raw']


def quotes(codes):
    found = {}
    for entry in app.catalog():
        meta = archive.metadata(archive.active(app.DATA, entry['day']))
        for s in meta.get('stocks', []):
            if s['code'] in codes and s['code'] not in found:
                found[s['code']] = {'price': s['price'], 'rate': s['rate'], 'source': 'saved'}
    return found


def activate(data, doc):
    global PROFILES
    profile = json.loads((data / 'shared-profiles.json').read_text(encoding='utf-8'))
    with LOCK:
        app.DATA = data
        PROFILES = profile
        watchlists.SOURCE = data / 'shared-profiles.json'
        STATE.update(published_at=doc['published_at'], error='')


class Handler(app.Handler):
    def respond(self, body, status=200, mime='application/json; charset=utf-8', filename=None):
        if isinstance(body, dict) and urlparse(self.path).path == '/api/investors/status':
            body.update(shared_viewer=True, enabled=False)
            body['state'] = {'busy': False, 'message': '동기화 저장 자료 조회'}
        if isinstance(body, dict) and 'credentials' in body:
            body.update(identity=IDENTITY, credentials=False, shared_viewer=True,
                        shared_published_at=STATE['published_at'], shared_error=STATE['error'])
            body['state'] = {'busy': False, 'queued': False, 'done': 0, 'total': 0,
                             'message': '동기화 저장 자료 조회 · 마지막 공유 ' + STATE['published_at']}
            body['monitor'] = {'enabled': False, 'interval_seconds': 300}
        if isinstance(body, bytes) and mime.startswith('text/javascript'):
            text = body.decode('utf-8')
            if urlparse(self.path).path in ('/app.js', '/volume.js'):
                text = text.replace('liveChart=true', 'liveChart=false')
                text = text.replace("$('chart-source').value='live'", "$('chart-source').value='archive'")
                text = text.replace("liveChart=$('chart-source').value==='live'", 'liveChart=false')
                text = text.replace("'인증정보 필요'", "'동기화 저장본 · 현재가 아님'")
            body = text.encode('utf-8')
        if isinstance(body, bytes) and mime.startswith('text/html'):
            text = body.decode('utf-8')
            notice = '<div class="shared-notice">동기화 조회용 · 현재가는 저장 당시 가격입니다. 마지막 공유: ' + STATE['published_at'] + ' · 새 수집·공용 메모 편집은 원본 PC에서 합니다.</div>'
            text = re.sub(r'(<body[^>]*>)', r'\1' + notice, text, count=1)
            text = re.sub(r'(<option[^>]*value="live"[^>]*)(>)', r'\1 disabled\2', text)
            text = text.replace('value="archive"', 'value="archive" selected')
            body = text.encode('utf-8')
        if isinstance(body, bytes) and mime.startswith('text/css'):
            body += b'\n.shared-notice{padding:12px 20px;background:#fff3cc;color:#594415;font-size:14px;line-height:1.6;text-align:center;}'
        return super().respond(body, status, mime, filename)

    def do_GET(self):
        with LOCK:
            parsed = urlparse(self.path)
            if parsed.path.startswith('/api/chart'):
                q = parse_qs(parsed.query)
                q['live'] = ['0']
                self.path = parsed.path + '?' + urlencode(q, doseq=True)
            if parsed.path == '/api/quotes':
                if not self.valid_host():
                    return self.respond({'error': '로컬 접속만 허용'}, 403)
                codes = parse_qs(parsed.query).get('codes', [''])[0].split(',')
                return self.respond({'quotes': quotes(codes), 'source': 'saved'})
            return super().do_GET()

    def do_POST(self):
        with LOCK:
            if self.path.startswith('/api/hero-'):
                return super().do_POST()
            # Opening another PC must not start duplicate collection or change shared data.
            if self.path in ('/api/open', '/api/volume/open'):
                if not self.valid_host() or self.headers.get('X-Collector-Token') != app.TOKEN:
                    return self.respond({'error': '로컬 인증 실패'}, 403)
                return self.respond({'ok': True, 'state': 'shared-view'}, 202)
            return self.respond({'error': '동기화 조회용입니다. 수집과 공용 메모·테마 수정은 원본 PC에서 해주세요.'}, 409)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--folder', type=Path, required=True)
    p.add_argument('--open-only', action='store_true')
    args = p.parse_args()
    if args.open_only:
        app.open_dashboard('http://127.0.0.1:8766')
        return
    cache = Path(os.environ['LOCALAPPDATA']) / 'Top100SharedCollector' / 'cache'
    cache.mkdir(parents=True, exist_ok=True)
    app.IDENTITY = IDENTITY
    hero_link.TARGET_FILE = cache.parent / 'hero-link-target.json'
    try:
        data, doc = receive(args.folder, cache)
    except Exception:
        pointer = json.loads((cache / 'last-ready.json').read_text(encoding='utf-8'))
        name = pointer['folder']
        if not re.fullmatch('generation-[a-f0-9]{32}', name):
            raise ValueError('이전 공유 자료 경로 오류')
        data = cache / name
        doc = json.loads((data / '_shared_ready.json').read_text(encoding='utf-8'))
    activate(data, doc)
    watchlists.groups = lambda path=None: copy.deepcopy(PROFILES['groups'])
    watchlists.names = lambda path=None: dict(PROFILES['names'])
    hero4memo.load = lambda path=None, year=None: dict(PROFILES['hero4'])
    chart_data.history_cache = cached_history
    chart_data.watchlist_minute = cached_minute
    # No Kiwoom credentials are required or read by this viewer.
    app.credentials = lambda: (_ for _ in ()).throw(DataError('공유 자료 조회 모드'))
    kiwoom.credentials = app.credentials
    server = ThreadingHTTPServer(('127.0.0.1', app.PORT), Handler)

    def sync():
        while True:
            time.sleep(60)
            try:
                data, doc = receive(args.folder, cache)
                if doc['published_at'] != STATE['published_at']:
                    activate(data, doc)
            except Exception:
                STATE['error'] = '공유 파일이 아직 도착하지 않았습니다. 이전 정상 자료를 유지합니다.'
    threading.Thread(target=sync, daemon=True).start()
    app.open_dashboard('http://127.0.0.1:8766')
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
