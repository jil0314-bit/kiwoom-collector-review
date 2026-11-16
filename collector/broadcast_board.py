"""Read the five-manager board in the public afternoon replay."""
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata


ROOT = Path(__file__).resolve().parent
BOARD_VERSION = 1
EXPERTS = (('백인엽',), ('신광섭',), ('이가람',), ('조기준',), ('한규수', '한균수'))
PANEL_TITLE = re.compile(r'매니저[5오]인(?:의)?시각[차자]')


def compact(text):
    return re.sub(r'[^가-힣A-Za-z0-9]', '', text).casefold()


class KoreanOCR:
    def __init__(self):
        sys.path.insert(0, str(ROOT / '.broadcast-ocr-runtime'))
        from winrt.windows.foundation import Rect  # Register the word coordinate type.
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        self.engine = OcrEngine.try_create_from_language(Language('ko'))
        if not self.engine:
            raise RuntimeError('Windows 한국어 OCR을 사용할 수 없음')

    async def read(self, image):
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import Buffer
        pixels = image.convert('RGBA').tobytes('raw', 'BGRA')
        buffer = Buffer(len(pixels))
        buffer.length = len(pixels)
        memoryview(buffer)[:] = pixels
        bitmap = SoftwareBitmap.create_copy_from_buffer(buffer, BitmapPixelFormat.BGRA8, image.width, image.height)
        try:
            result = await self.engine.recognize_async(bitmap)
            lines = []
            for line in result.lines:
                words = []
                for word in line.words:
                    rect = word.bounding_rect
                    words.append((word.text, rect.x + rect.width / 2, rect.y + rect.height / 2))
                lines.append((line.text, words))
            return lines
        finally:
            bitmap.close()


def crop(image, area):
    left, top, right, bottom = area
    return image.crop((round(left * image.width), round(top * image.height),
                       round(right * image.width), round(bottom * image.height)))


def has_title(lines):
    text = compact(''.join(line for line, _ in lines))
    return bool(PANEL_TITLE.search(text)) or ('매니저' in text and '어디에투자할까' in text)


def distance(left, right):
    left, right = (unicodedata.normalize('NFD', s) for s in (left, right))
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        row = [i]
        for j, b in enumerate(right, 1):
            row.append(min(row[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = row
    return previous[-1]


def stock_match(text, by_name):
    key = compact(text)
    if key in by_name:
        values = by_name[key]
        return (values[0], True) if len(values) == 1 else (None, False)
    if len(key) < 2:
        return None, False
    limit = 1 if len(key) <= 3 else 2
    plausible = []
    for name, values in by_name.items():
        if len(values) == 1 and len(name) == len(key):
            score = distance(key, name)
            if score <= limit:
                plausible.append((score, values[0]))
    plausible.sort()
    if not plausible or (len(plausible) > 1 and plausible[0][0] == plausible[1][0]):
        return None, False
    return plausible[0][1], False


def read_table(lines, names):
    """Resolve only stock names from the stock master, in the same panel column."""
    if not has_title(lines):
        return []
    words = [word for _, words in lines for word in words]
    anchors = []
    for aliases in EXPERTS:
        matches = [(distance(compact(text)[:3], alias), alias, x, y)
                   for text, x, y in words if len(compact(text)) >= 3
                   for alias in aliases if distance(compact(text)[:3], alias) <= 3]
        matches.sort()
        if matches and (len(matches) == 1 or matches[0][0] < matches[1][0] or matches[0][2:] == matches[1][2:]):
            score, alias, x, y = matches[0]
            anchors.append((alias, x, y, score == 0))
    if len(anchors) < 4:
        return []
    anchors.sort(key=lambda word: word[1])
    x_gaps = sorted(b[1] - a[1] for a, b in zip(anchors, anchors[1:]))
    spacing = x_gaps[len(x_gaps) // 2]
    baseline = sorted(y for _, _, y, _ in anchors)[len(anchors) // 2]
    if (spacing < 32 or len({x for _, x, _, _ in anchors}) != len(anchors)
            or any(abs(y - baseline) > spacing * .21 for _, _, y, _ in anchors)):
        return []
    by_name = {}
    for code, name in names.items():
        by_name.setdefault(compact(name), []).append((code, name))

    picks = []
    for expert, x, _, exact_expert in anchors:
        column = [(text, wx, wy) for text, wx, wy in words
                  if abs(wx - x) < spacing * .47 and baseline + spacing * .19 < wy < baseline + spacing * .91]
        column.sort(key=lambda word: (word[2], word[1]))
        rows = []
        for word in column:
            if not rows or word[2] - rows[-1][0][2] > spacing * .11:
                rows.append([])
            rows[-1].append(word)
        for row in rows:
            raw = ' '.join(word[0] for word in sorted(row, key=lambda word: word[1]))
            matched, exact = stock_match(raw, by_name)
            if matched:
                code, name = matched
                role = '보조 관심' if raw.lstrip().startswith(('+', '＋')) or row[0][2] > baseline + spacing * .55 else '대표 관심'
                picks.append((expert, code, name, role, exact and exact_expert))
    if len({expert for expert, _, _, _, _ in picks}) < 3:
        return []
    return picks


def records(item, found, offset):
    import recommendations as r
    rows = []
    for expert, code, name, role in found:
        identity = json.dumps([item['url'], expert, code, 'manager-board'], ensure_ascii=False)
        rows.append({'id': hashlib.sha256(identity.encode()).hexdigest()[:24], 'url': item['url'],
                     'title': item['title'], 'program': 'AI황금분석', 'broadcaster': '매일경제TV',
                     'expert': expert, 'code': code, 'name': name, 'classification': 'interest', 'board_pick_role': role,
                     'broadcast_date': item['broadcast_date'], 'recommended_date': item['broadcast_date'],
                     'recommended_time': None, 'timezone': 'Asia/Seoul', 'video_offset_seconds': offset,
                     'date_basis': '공식 다시보기 회차일', 'time_basis': '영상 재생 위치 확인 · 방송 시각 미확인',
                     'published_at': None, 'buy_price': None, 'target_price': None, 'stop_price': None, 'reason': None,
                     'evidence': '매니저 5인의 시각차, 어디에 투자할까? · ' + expert + ' · ' + role + ' · ' + name,
                     'evidence_type': '공개 다시보기 추천표 OCR', 'review_status': '표의 전문가·종목 대조 · 가격·이유 미확인',
                     'parser_version': r.PARSER_VERSION, 'collected_at': r.stamp()})
    return rows


def scan_windows(duration):
    # The station has published both one- and three-hour afternoon windows.
    # Check the likely locations first, then cover the rest of the replay.
    breaks = (0, 600, 2100, 4200, 5700, duration)
    intervals = [(a, min(b, duration)) for a, b in zip(breaks, breaks[1:]) if a < min(b, duration)]
    return [intervals[i] for i in (1, 3, 0, 2, 4) if i < len(intervals)]


def verified_picks(observations):
    counts = Counter()
    exact = Counter()
    for picks in observations.values():
        for expert, code, name, role, literal in dict.fromkeys(picks):
            key = (expert, code, name, role)
            counts[key] += 1
            exact[key] += literal
    groups = {}
    for key, count in counts.items():
        if count >= 2 or exact[key]:
            groups.setdefault((key[0], key[3]), []).append((count, exact[key], key))
    result = []
    for options in groups.values():
        options.sort(reverse=True)
        if len(options) == 1 or options[0][:2] != options[1][:2]:
            result.append(options[0][2])
    return result


async def inspect_image(ocr, image, names):
    from PIL import Image, ImageOps
    panel = crop(image, (.075, .13, .72, .90))
    scale = min(2.4, 1450 / panel.width)
    panel = panel.resize((round(panel.width * scale), round(panel.height * scale)), Image.Resampling.LANCZOS)
    lines = await ocr.read(panel)
    if not has_title(lines):
        return []
    normal = read_table(lines, names)
    contrasted = read_table(await ocr.read(ImageOps.autocontrast(panel.convert('L'))), names)
    choices = {pick[:4]: pick for pick in normal}
    for pick in contrasted:
        if pick[:4] not in choices or pick[4]:
            choices[pick[:4]] = pick
    return list(choices.values())


async def scan_media(item, result=None, windows=None):
    import broadcast_audio as audio
    import recommendations as r
    sys.path.insert(0, str(ROOT / '.speech-runtime'))
    import av

    names = r.watchlists.names()
    if not names:
        raise ValueError('종목 코드 원장을 읽을 수 없음')
    ocr = KoreanOCR()
    source = audio.media_url(item, keyframes=True)
    observations = {}
    scanned = 0
    with av.open(source, timeout=(15, 20)) as container:
        if not container.duration or not container.streams.video:
            raise ValueError('공개 다시보기의 길이 또는 영상 트랙 확인 필요')
        origin = container.start_time or 0
        for start, end in windows or scan_windows(round(container.duration / 1_000_000)):
            if start:
                container.seek(origin + start * 1_000_000)
            elif scanned:
                container.seek(origin)
            last_sample = start - 10
            stream = container.streams.video[0]
            stream.codec_context.skip_frame = 'NONKEY'
            for frame in container.decode(video=0):
                if frame.time is None:
                    continue
                offset = max(0, round(frame.time - origin / 1_000_000))
                if offset >= end:
                    break
                if offset < start - 9 or offset - last_sample < 4:
                    continue
                last_sample = offset
                scanned += 1
                picks = await inspect_image(ocr, frame.to_image(), names)
                if picks:
                    observations[offset] = picks
                    nearby = {at: table for at, table in observations.items() if abs(at - offset) <= 35}
                    if len(verified_picks(nearby)) >= 10:
                        return records(item, verified_picks(nearby), min(nearby)), scanned
                if result and scanned % 75 == 0:
                    r.save(result, {'board_version': BOARD_VERSION, 'complete': False, 'scanned_frames': scanned,
                                    'message': f'전체 다시보기 추천표 검사 중 · {scanned}개 화면 확인'})
    if not observations:
        return [], scanned
    candidates = [{at: table for at, table in observations.items() if abs(at - offset) <= 35}
                  for offset in observations]
    best = max(candidates, key=lambda group: len(verified_picks(group)))
    return records(item, verified_picks(best), min(best)), scanned


def scan(item, result):
    import recommendations as r
    rows, scanned = asyncio.run(scan_media(item, result))
    count = len({row['expert'] for row in rows if row['board_pick_role'] == '대표 관심'})
    warning = None
    if not rows:
        warning = f'전체 다시보기에서 5인 추천표 식별 안 됨 · {scanned}개 화면 확인'
    elif count < len(EXPERTS):
        warning = f'공개 다시보기 추천표 일부 확인 · 대표 관심 {count}/{len(EXPERTS)}명'
    r.save(result, {'board_version': BOARD_VERSION, 'complete': True, 'scanned_frames': scanned,
                    'records': rows, 'warning': warning, 'message': warning or '공개 다시보기 추천표 확인 완료'})
    return rows, scanned
