"""One low-priority local speech worker for unencrypted official MKTV VOD.

Only bounded recommendation candidates/offsets are saved, never a full transcript
or downloaded video. Prices from speech remain unverified candidates.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urljoin, urlparse
from urllib.request import Request, build_opener

ROOT = Path(__file__).resolve().parent
PROCESS = None


def paths(item):
    namespace = 'manager-board:' if item.get('ai_segment') else ''
    key = hashlib.sha256((namespace + item['url']).encode()).hexdigest()[:24]
    folder = ROOT / 'data/recommendations/speech'
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (key + '.job.json'), folder / (key + '.result.json')


def read_or_start(item):
    import recommendations as r
    global PROCESS
    job, result = paths(item)
    saved = r.load(result, {})
    board = item.get('ai_segment')
    if board:
        from broadcast_board import BOARD_VERSION
        if saved.get('board_version') != BOARD_VERSION:
            saved = {}
    if saved.get('complete'):
        if board:
            return saved.get('records', []), saved.get('warning')
        return saved.get('records', []), None if saved.get('records') else '전사 완료·국내 종목/추천 구간 식별 확인 필요'
    message = saved.get('message', '전체 다시보기 추천표 검사 대기' if board else '공개 다시보기 음성전사 대기')
    records = saved.get('records', [])
    if PROCESS is not None and PROCESS.poll() is None:
        return records, message
    # Heavy work starts only outside domestic regular/extended market hours.
    from datetime import datetime
    from kiwoom import KST
    if not board and 8 <= datetime.now(KST).hour < 21:
        return records, '21시 이후 로컬 음성전사 대기·클립/기사는 계속 수집'
    if board and not (ROOT / '.broadcast-ocr-runtime/winrt').is_dir():
        return records, '한국어 추천표 OCR 실행 환경 확인 필요'
    if not (ROOT / '.speech-runtime' / ('av' if board else 'faster_whisper')).is_dir():
        return records, '로컬 음성인식 실행 환경 확인 필요'
    if saved.get('retry_after', 0) > __import__('time').time():
        return records, message
    r.save(job, item)
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0)
    PROCESS = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), str(job)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    return records, '전체 다시보기에서 추천표 검사 중' if board else '공개 다시보기 로컬 음성전사 진행·가격 검수 대기'


def media_url(item, keyframes=False):
    import recommendations as r
    if urlparse(item['url']).hostname != 'mbnmoney.mbn.co.kr' or item.get('kind') != 'mktv':
        raise ValueError('공식 매일경제TV 다시보기만 전사 가능')
    def get(url):
        p = urlparse(url)
        if p.scheme != 'https' or p.hostname not in ('mbnmoney.mbn.co.kr', 'vodmm.mbn.co.kr') or p.port not in (None, 443) or p.username:
            raise ValueError('공식 공개 미디어 주소 오류')
        with build_opener(r.Redirects()).open(Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': item['url']}), timeout=20) as response:
            if urlparse(response.url).hostname not in ('mbnmoney.mbn.co.kr', 'vodmm.mbn.co.kr'):
                raise ValueError('미디어 리디렉션 주소 확인 필요')
            return response.read(3_000_000).decode('utf-8', errors='replace')
    html = get(item['url'])
    match = re.search(r"loadSource\('([^']+)'", html)
    if not match:
        raise ValueError('공개 다시보기 음성 주소 없음')
    url = urljoin('https://mbnmoney.mbn.co.kr', match.group(1))
    master = get(url)
    if not master.startswith('#EXTM3U') or '#EXT-X-KEY' in master:
        raise ValueError('공개 비암호화 미디어로 확인되지 않음')
    if keyframes:
        iframe = re.search(r'^#EXT-X-I-FRAME-STREAM-INF:[^\r\n]*?URI="([^"\r\n]+)"', master, re.M)
        if iframe:
            candidate = urljoin(url, iframe.group(1))
            listing = get(candidate)
            if listing.startswith('#EXTM3U') and '#EXT-X-I-FRAMES-ONLY' in listing and '#EXT-X-KEY' not in listing:
                return candidate
    child = next((line.strip() for line in master.splitlines() if line.strip() and not line.startswith('#')), None) if '#EXT-X-STREAM-INF' in master else None
    if child:
        url = urljoin(url, child)
        if '#EXT-X-KEY' in get(url):
            raise ValueError('보호된 미디어는 전사하지 않음')
    return url


def candidates(lines, item):
    import recommendations as r
    rows = r.transcript_records(lines, {**item, 'video_url': item['url'], 'evidence_type': '공개 다시보기 음성전사·검수 대기'})
    for row in rows:
        row['proposed_classification'] = row['classification']
        row['classification'] = 'pending'
        row['candidate_prices'] = {key: row.get(key) for key in ('buy_price', 'target_price', 'stop_price')}
        row.update(buy_price=None, target_price=None, stop_price=None,
                   review_status='로컬 한국어 음성전사·발화자/종목/가격 원문 대조 필요', verification_status='asr_pending')
        row['id'] = hashlib.sha256((item['url'] + row['code'] + str(row.get('expert')) + 'speech-pending').encode()).hexdigest()[:24]
    return rows


def transcribe(item, result, max_seconds=None):
    import recommendations as r
    sys.path.insert(0, str(ROOT / '.speech-runtime'))
    os.environ['OMP_NUM_THREADS'] = '2'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
    os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
    import av
    import numpy as np
    from faster_whisper import WhisperModel
    model = WhisperModel('small', device='cpu', compute_type='int8', cpu_threads=2, num_workers=1,
                         download_root=str(ROOT / 'data/speech_models'), local_files_only=True)
    source = media_url(item)
    pool, samples, elapsed, records = [], 0, 0.0, {}
    resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
    def flush():
        nonlocal pool, samples, elapsed
        if not samples:
            return
        audio = np.concatenate(pool).astype(np.float32) / 32768.0
        segments, _ = model.transcribe(audio, language='ko', beam_size=3, vad_filter=True)
        lines = [{'offset': round(elapsed + x.start), 'text': x.text.strip()} for x in segments]
        for row in candidates(lines, item):
            records[row['id']] = row
        elapsed += len(audio) / 16000
        pool, samples = [], 0
        r.save(result, {'complete': False, 'processed_seconds': round(elapsed), 'records': list(records.values()),
                        'message': '음성전사 진행·' + str(round(elapsed / 60)) + '분 처리·가격 검수 대기'})
    with av.open(source, timeout=(20, 30)) as container:
        for frame in container.decode(audio=0):
            for audio in resampler.resample(frame):
                array = audio.to_ndarray().reshape(-1).copy()
                pool.append(array)
                samples += len(array)
            if samples >= 300 * 16000 or (max_seconds and elapsed + samples / 16000 >= max_seconds):
                flush()
            if max_seconds and elapsed >= max_seconds:
                break
        flush()
    r.save(result, {'complete': not bool(max_seconds), 'processed_seconds': round(elapsed), 'records': list(records.values()),
                    'message': '음성전사 완료·원문 대조 대기' if not max_seconds else '표본 전사 검증 완료(전체 회차 아님)'})
    return round(elapsed), len(records)


def main():
    import msvcrt
    import recommendations as r
    job = Path(sys.argv[1]).resolve()
    if job.parent != (ROOT / 'data/recommendations/speech').resolve():
        raise ValueError('작업 파일 경로 오류')
    item = r.load(job, {})
    _, result = paths(item)
    lock = (job.parent / 'worker.lock').open('a+b', buffering=0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        return
    try:
        if item.get('ai_segment'):
            from broadcast_board import scan
            scan(item, result)
        else:
            transcribe(item, result)
    except Exception as exc:
        saved = r.load(result, {})
        prefix = '추천표 검사 확인 필요: ' if item.get('ai_segment') else '음성전사 확인 필요: '
        if item.get('ai_segment'):
            from broadcast_board import BOARD_VERSION
            saved['board_version'] = BOARD_VERSION
        r.save(result, {**saved, 'complete': False, 'message': prefix + str(exc)[:180],
                        'retry_after': __import__('time').time() + 7200})
    finally:
        lock.close()


if __name__ == '__main__':
    main()
