"""Public recommendation archive. No login, media download, or order requests.

Dates/times/prices are evidence fields; publication is never recommendation time.
Unusable captions and blocked sources remain visible in the collection ledger.
"""
from __future__ import annotations
import csv
import hashlib
import io
import json
import os
import re
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

from kiwoom import KST
import watchlists
import broadcast_recommendations as broadcasts
import broadcast_audio

ROOT = Path(__file__).resolve().parent
LOCK = threading.RLock()
RUN = threading.Lock()
STATE = {"busy": False, "message": "공개 자료 수집 대기", "last_run": None}
INTERVAL = 1200
PARSER_VERSION = 4
HOSTS = {"www.mtn.co.kr", "news.mtn.co.kr", "www.youtube.com", "youtube.com", "www.youtube-nocookie.com", "mbnmoney.mbn.co.kr", "vodmm.mbn.co.kr"}
LABELS = {"new": "신규추천", "consultation": "보유종목 상담", "review": "과거추천 복기", "sell": "매도·축소", "interest": "관심종목", "mention": "단순 언급", "pending": "음성전사 검수대기"}


def today():
    return datetime.now(KST).date().isoformat()


def stamp():
    return datetime.now(KST).isoformat(timespec="seconds")


def valid_day(day):
    if datetime.strptime(day, "%Y-%m-%d").strftime("%Y-%m-%d") != day:
        raise ValueError("날짜 형식 오류")
    return day


def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def sources():
    return load(ROOT / "recommendation_sources.json", {"channels": [], "programs": []})


def excluded_program(item, config):
    text = broadcasts.compact((item.get('program') or '') + ' ' + (item.get('title') or ''))
    return any(broadcasts.compact(name) in text for name in config.get('excluded_programs', []))


def newest_record(record):
    return (record.get('first_collected_at') or record.get('collected_at') or '',
            record.get('published_at') or '', record.get('recommended_time') or '', record['id'])


def broadcast_program_match(title, description, broadcaster, config):
    text = broadcasts.compact((title or '') + ' ' + (description or ''))
    for program in config.get('broadcast_programs', []):
        if program.get('broadcaster') != broadcaster:
            continue
        labels = [program.get('name', ''), *program.get('aliases', [])]
        if any(label and broadcasts.compact(label) in text for label in labels):
            return program.get('name')
    return None


def read(data, day):
    valid_day(day)
    with LOCK:
        doc = load(data / "recommendations" / day / "index.json", {"day": day, "records": [], "stocks": []})
        doc['records'] = sorted((r for r in doc.get('records', []) if r.get('classification') != 'mention'),
                                key=newest_record, reverse=True)
        doc["stocks"] = list({r["code"]: {"code": r["code"], "name": r["name"]}
                              for r in doc["records"] if r.get("code")}.values())
        return doc


def days(data):
    return sorted((p.name for p in (data / "recommendations").glob("????-??-??") if p.is_dir()), reverse=True)


def ledger(data):
    with LOCK:
        return load(data / "recommendations" / "ledger.json", {"sources": {}, "documents": {}})


def ledger_view(data, day):
    book = ledger(data)
    selected = {u: d for u, d in book['documents'].items() if (d.get('broadcast_date') or (d.get('published_at') or '')[:10]) == day}
    return {'sources': book['sources'], 'documents': selected,
            'total_documents': len(book['documents']), 'pending_total': sum(d.get('status') != '완료' for d in book['documents'].values())}


def status(data):
    if STATE.get('last_run'):
        return dict(STATE)
    previous = load(data / 'recommendations' / 'last_run.json', {})
    return {**STATE, **previous, 'busy': False}


def merge(data, day, records):
    with LOCK:
        doc = read(data, day)
        incoming = {r['url'] for r in records}
        existing = {r['id']: r for r in doc['records']}
        items = {r["id"]: r for r in doc["records"] if r['url'] not in incoming}
        for record in records:
            old = existing.get(record['id'], {})
            first = old.get('first_collected_at') or old.get('collected_at') or record.get('collected_at') or stamp()
            items[record['id']] = {**record, 'first_collected_at': first}
        doc['records'] = sorted(items.values(), key=newest_record, reverse=True)
        doc["stocks"] = list({r["code"]: {"code": r["code"], "name": r["name"]} for r in doc["records"] if r.get("code")}.values())
        doc["updated_at"] = stamp()
        save(data / "recommendations" / valid_day(day) / "index.json", doc)


def allowed(url):
    p = urlparse(url)
    if p.scheme != "https" or p.hostname not in HOSTS or p.username or p.password or p.port not in (None, 443):
        raise ValueError("허용한 공개 원문 주소가 아닙니다")
    return url


class Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    allowed(url)
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; PublicStockArchive/1.0)", "Accept-Language": "ko,en;q=0.7"})
    with build_opener(Redirects()).open(req, timeout=15) as response:
        body = response.read(6_000_001)
        if len(body) > 6_000_000:
            raise ValueError("공개 문서 크기 제한 초과")
        return body.decode("utf-8", errors="replace")


class Page(HTMLParser):
    """Small stdlib parser: article text, metadata and anchors, no scripts."""
    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.lines, self.links, self.meta = [], [], {}
        self.skip = 0
        self.article = 0
        self.parts = []
        self.anchor = None
        self.feed(content)
        self.flush()

    def flush(self):
        line = re.sub(r"\s+", " ", "".join(self.parts)).strip()
        if line:
            self.lines.append((self.article > 0, line))
        self.parts = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        if self.skip:
            return
        if tag == "meta":
            self.meta[a.get("property") or a.get("name", "")] = a.get("content", "")
        if tag == "article":
            self.flush()
            self.article += 1
        if tag in ("p", "div", "br", "li", "h1", "h2", "h3", "section", "time"):
            self.flush()
        if tag == "a":
            self.anchor = {"url": a.get("href", ""), "text": "", "date": ""}
        if tag == "time" and self.anchor:
            self.anchor["date"] = a.get("datetime", "")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag in ("p", "div", "li", "h1", "h2", "h3", "section", "time", "article"):
            self.flush()
        if tag == "article":
            self.article = max(0, self.article - 1)
        if tag == "a" and self.anchor:
            self.links.append(self.anchor)
            self.anchor = None

    def handle_data(self, value):
        if not self.skip:
            self.parts.append(value)
            if self.anchor:
                self.anchor["text"] += value + " "

    def text(self):
        inside = [line for yes, line in self.lines if yes]
        return "\n".join(inside or [line for _, line in self.lines])


def json_after(content, pattern):
    found = re.search(pattern, content)
    if not found:
        return {}
    try:
        return json.JSONDecoder().raw_decode(content[found.end():].lstrip())[0]
    except ValueError:
        return {}


def published(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(KST).isoformat(timespec="seconds") if dt.tzinfo else dt.replace(tzinfo=KST).isoformat(timespec="seconds")
    except ValueError:
        return None


def feed_entries(content):
    root = ET.fromstring(content)
    ns = {"a": "http://www.w3.org/2005/Atom", "y": "http://www.youtube.com/xml/schemas/2015", "m": "http://search.yahoo.com/mrss/"}
    result = []
    for e in root.findall("a:entry", ns):
        video = e.findtext("y:videoId", "", ns)
        if re.fullmatch(r"[\w-]{11}", video):
            result.append({"url": "https://www.youtube.com/watch?v=" + video, "title": e.findtext("a:title", "", ns),
                           "published_at": published(e.findtext("a:published", "", ns)),
                           "description": e.findtext("m:group/m:description", "", ns)})
    return result


class PublicUnavailable(ValueError):
    pass


def channel_video_entries(content, limit=60):
    """Read both versions of the public YouTube channel video list."""
    initial = json_after(content, r'(?:var\s+)?ytInitialData\s*=\s*')
    result = {}
    def walk(value):
        if len(result) >= limit:
            return
        if isinstance(value, dict):
            video = value.get('videoRenderer') or value.get('gridVideoRenderer') or {}
            code = video.get('videoId', '')
            title = video.get('title', {})
            text = title.get('simpleText') or ''.join(x.get('text', '') for x in title.get('runs', []))
            lockup = value.get('lockupViewModel', {})
            if lockup.get('contentType') == 'LOCKUP_CONTENT_TYPE_VIDEO':
                code = lockup.get('contentId', '')
                info = lockup.get('metadata', {}).get('lockupMetadataViewModel', {})
                text = info.get('title', {}).get('content', '')
                rows = info.get('metadata', {}).get('contentMetadataViewModel', {}).get('metadataRows', [])
                age = ' '.join(p.get('text', {}).get('content', '') for row in rows for p in row.get('metadataParts', []))
                if re.search(r'(?:\d+\s*(?:주|개월|년)\s*전|(?:[3-9]|\d{2,})\s*일\s*전|\d+\s*(?:weeks?|months?|years?)\s+ago|(?:[3-9]|\d{2,})\s+days?\s+ago)', age, re.I):
                    return
            if text and re.fullmatch(r'[A-Za-z0-9_-]{11}', code):
                result[code] = {'url': 'https://www.youtube.com/watch?v=' + code,
                                'title': text, 'published_at': None, 'description': ''}
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(initial)
    return list(result.values())


def youtube_listing(channel_id):
    feed_error = None
    try:
        entries = feed_entries(fetch('https://www.youtube.com/feeds/videos.xml?' + urlencode({'channel_id': channel_id})))
    except Exception as exc:
        entries, feed_error = [], str(exc)[:100]
    if entries and len(entries) < 15:
        return entries, ''
    try:
        supplement = channel_video_entries(fetch('https://www.youtube.com/channel/' + channel_id + '/videos'))
    except Exception as exc:
        if not entries:
            raise ValueError('피드·공개 동영상 목록 확인 실패: ' + str(exc)[:100]) from exc
        return entries, 'RSS 15건 상한·동영상 목록 보충 실패: ' + str(exc)[:100]
    warning = '피드 응답 없음·공개 동영상 목록으로 확인' if not entries else 'RSS 15건 상한·공개 동영상 목록으로 보완'
    if not entries and not supplement:
        warning += ' · 최근 영상 0건'
    if feed_error:
        warning += ' (' + feed_error + ')'
    return list({e['url']: e for e in [*supplement, *entries]}.values()), warning


def captions(url):
    player = json_after(fetch(url), r"(?:var\s+)?ytInitialPlayerResponse\s*=\s*")
    if player.get("playabilityStatus", {}).get("status") != "OK":
        raise PublicUnavailable("영상 공개 재생 확인 불가·회원/차단 여부 확인 필요")
    tracks = player.get("captions", {}).get("playerCaptionsTracklistRenderer", {}).get("captionTracks", [])
    track = next((t for t in tracks if t.get("languageCode", "").startswith("ko")), None)
    if not track:
        raise ValueError("한국어 공개 자막 없음")
    url = track["baseUrl"] + "&fmt=json3"
    body = fetch(url)
    if not body.strip():
        raise ValueError("공개 자막 응답 없음·발언 수집 불가")
    try:
        doc = json.loads(body)
    except ValueError as exc:
        raise ValueError("공개 자막 형식 확인 불가·발언 수집 불가") from exc
    lines = [{"text": "".join(s.get("utf8", "") for s in e.get("segs", [])).strip(), "offset": round(e.get("tStartMs", 0) / 1000)} for e in doc.get("events", [])]
    lines = [x for x in lines if x["text"]]
    if not lines:
        raise ValueError("공개 자막 응답 비어 있음")
    return lines


EXPERT = re.compile(r"(?:^|[▶>\[/|· ])([가-힣A-Za-z][가-힣A-Za-z ]{1,18}?)\s*(?:어드바이저|전문가|대표|소장|매니저|팀장|연구원|이사)(?:\s|$|[\]/|])")
NEW = re.compile(r"최종\s*(?:PICK|픽)|신규\s*(?:추천|매수|편입)|오늘의\s*추천|추천\s*종목|추천주|공략\s*(?:종목|주)|고래사냥법|탑픽레이더|내일장\s*(?:고래|추천)|매수\s*추천|추천드립니다|추천드리는", re.I)
NUMBER = r"[0-9][0-9,]*(?:\.[0-9]+)?"
PRICE = rf"({NUMBER}(?:\s*만(?:\s*{NUMBER})?(?:\s*천(?:\s*{NUMBER})?)?|\s*천(?:\s*{NUMBER})?)?\s*원?)"


def price(text, labels):
    found = re.search(r"(?:" + labels + r")\s*[:：=]?\s*" + PRICE + r"(?:\s*[~∼～-]\s*" + PRICE + r")?", text)
    if not found:
        return None
    # Percentage returns and non-price expressions must not become won prices.
    if text[found.end():].lstrip().startswith(("%", "퍼센트", "배", "억", "조", "백", "십", "만", "천")):
        return None
    def number(s):
        s = re.sub(r'[\s,원]', '', s)
        total = 0
        for unit, scale in [('만', 10000), ('천', 1000)]:
            if unit in s:
                head, s = s.split(unit, 1)
                total += float(head) * scale
        return round(total + (float(s) if s else 0))
    lo = number(found.group(1))
    hi = number(found.group(2)) if found.group(2) else lo
    if found.group(2):
        a, b = found.group(1), found.group(2)
        if not re.search('[만천원]', a) and lo < 1000:
            lo *= 10000 if '만' in b else 1000 if '천' in b else 1
        if not re.search('[만천원]', b) and hi < 1000:
            hi *= 10000 if '만' in a else 1000 if '천' in a else 1
    if lo <= 0 or hi < lo:
        return None
    return {"min": lo, "max": hi, "raw": found.group(0), "currency": "KRW"}


def category(text, section, title):
    context = text + " " + section
    if re.search(r"매도\s*(?:추천|의견|종목)|비중\s*축소|전량\s*매도", context):
        return "sell"
    if re.search(r"지난\s*추천|기존\s*추천|과거\s*추천|추천\s*(?:이후|당시)|추천일\s*대비|수익률\s*(?:달성|점검)|복기", context):
        return "review"
    if re.search(r"보유\s*종목|보유자|보유\s*수량|매수\s*단가|평균\s*단가|종목\s*상담|시청자\s*상담", context):
        return "consultation"
    if re.search(r"추천하지|매수하지|추천\s*아님|매수\s*금지|추천은\s*아니", context):
        return "mention"
    if NEW.search(context):
        return "new"
    if re.search(r"관심\s*종목|관심주|후보|PICK|픽", context, re.I):
        return "interest"
    if "상담" in title:
        return "consultation"
    return "mention"


def extract(text, meta, names=None):
    """Conservative, local evidence extraction. Never infer price or speaker."""
    names = dict(watchlists.names() if names is None else names)
    # Newly listed stocks may not yet exist in Hero4's local master. Accept a
    # code only when the public stock heading explicitly pairs name and code.
    for raw in text.splitlines():
        heading = re.sub(r'^[▶<>\s]+', '', raw.strip())
        heading = re.sub(r'^오늘의\s*고래사냥법\s*-\s*', '', heading)
        pair = re.fullmatch(r'([가-힣A-Za-z0-9&. -]{2,35})\s*\(([0-9][A-Z0-9]{5})\)>?', heading)
        if pair and not re.search(r'가격|목표가|매수가|손절|매출|수량', pair.group(1)):
            names.setdefault(pair.group(2), pair.group(1).strip())
    reverse = {}
    for code, name in names.items():
        reverse.setdefault(name, []).append(code)
    # Boundary guards avoid '삼성전자우' becoming '삼성전자'.
    pattern = re.compile(r"(?<![가-힣A-Za-z0-9])(?:" + "|".join(re.escape(n) for n in sorted(reverse, key=len, reverse=True)) + r")(?:(?![가-힣A-Za-z0-9])|(?=(?:은|는|이|가|을|를|와|과|도|의|에|부터|에서|하고|로)(?:\s|[,?!.…])))") if reverse else None
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
    if meta.get("evidence_type") == "공개 기사":
        start = next((i for i, line in enumerate(lines) if line.startswith("▶▶")), None)
        if start is not None:
            lines = lines[start:]
    expert, section, results = None, "", []
    section_index = -100
    spoken = meta.get('evidence_type') in ('공개 한국어 자막', '공개 브라우저 스크립트')
    title_experts = list(dict.fromkeys(m.group(1).strip() for m in EXPERT.finditer(meta.get("title", ""))))
    if len(title_experts) == 1:
        expert = title_experts[0]
    def primary_name(line, name):
        clean = re.sub(r"^[▶>\s'\"‘’“”\[<]+", '', line)
        clean = re.sub(r"^[가-힣A-Za-z]{2,12}\s*(?:관심주|추천주)\s*[-:：]?\s*", '', clean)
        clean = re.sub(r"^오늘의\s*고래사냥법\s*[-:：]?\s*", '', clean)
        return bool(re.match(re.escape(name) + r"(?:\s|\(|$|[,'\"‘’“”>])", clean))
    for i, line in enumerate(lines):
        if line.startswith("시청 방법") or "무단전재" in line:
            break
        em = EXPERT.search(line)
        if em and not (pattern and pattern.search(line)):
            expert = re.sub(r'\s*MTNW?\s*$', '', em.group(1)).strip()
        speaker = re.match(r"^[▶>\s]*([가-힣A-Za-z]{2,12})(?:의\s*[<〈]|\s+(?:관심주|추천주|PICK))", line, re.I)
        if speaker and speaker.group(1) not in ('최종', '오늘', '내일', '신규', '이번', '추천', '관심'):
            expert = speaker.group(1)
        if line.startswith('▶▶'):
            section = line
            section_index = i
        if (NEW.search(line) or re.search(r"종목\s*상담|보유\s*종목|복기|관심\s*(?:종목|주)|후보|PICK", line, re.I)) and not (pattern and pattern.search(line)):
            section = line
            section_index = i
        hits = list(dict.fromkeys(pattern.findall(line))) if pattern else []
        explicit = re.findall(r"(?<![A-Z0-9])([0-9][A-Z0-9]{5})(?![A-Z0-9])", line)
        for code in explicit:
            if code in names and names[code] not in hits:
                hits.append(names[code])
        for name in hits:
            codes = reverse[name]
            code = next((c for c in explicit if c in codes), codes[0] if len(codes) == 1 else None)
            if not code:
                continue
            block = [line]
            for follow in lines[i + 1:i + 10]:
                if follow.startswith(('시청 방법', '* 이 방송', '생방송 ')):
                    break
                next_names = pattern.findall(follow) if pattern else []
                next_stock = bool(next_names) and (meta.get('evidence_type') != '공개 기사' or any(primary_name(follow, n) for n in next_names))
                if next_stock or EXPERT.search(follow) or (NEW.search(follow) and follow.startswith('▶')) or follow.startswith("▶▶") or re.match(r'^[가-힣A-Za-z]{2,12}\s+관심주', follow):
                    break
                block.append(follow)
            evidence = "\n".join(block)
            primary = primary_name(line, name)
            context = section if not spoken or (primary and i - section_index <= 2) else ''
            kind = category(evidence, context, meta.get("title", ""))
            if meta.get('evidence_type') == '공개 기사' and not primary:
                kind = 'mention'
            if kind == 'mention':
                continue
            # A multi-stock heading cannot assign the same price/reason to all stocks.
            unambiguous = len(hits) == 1
            reasons = [s.lstrip("-•· ") for s in block[1:] if (s.startswith(("-", "•", "·")) or re.search(r"때문|실적|수주|매출|수급|성장|돌파|지지|계약", s)) and not re.search(r"목표가|손절가|매수가|매수 가격|매수가격|공략가|매매가", s)] if unambiguous else []
            clock = re.search(r"추천\s*(?:시각|시간)\s*[:：]?\s*([012]?\d):([0-5]\d)", evidence)
            rec_time = f"{int(clock.group(1)):02d}:{clock.group(2)}" if clock and int(clock.group(1)) < 24 else None
            day = meta.get("broadcast_date")
            explicit_date = re.search(r"추천\s*(?:일자|일시|날짜)\s*[:：]?\s*(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", evidence)
            if explicit_date:
                day = valid_day("%04d-%02d-%02d" % tuple(map(int, explicit_date.groups())))
                following = re.match(r'\s+([012]?\d):([0-5]\d)', evidence[explicit_date.end():])
                if following and int(following.group(1)) < 24:
                    rec_time = f'{int(following.group(1)):02d}:{following.group(2)}'
            record = {**meta, "code": code, "name": name, "expert": expert, "classification": kind,
                      "recommended_date": day, "recommended_time": rec_time, "timezone": "Asia/Seoul",
                      "date_basis": "방송 회차일" if day and not explicit_date else "원문 명시" if explicit_date else "미확인",
                      "time_basis": "원문 명시" if rec_time else "미확인·게시시각으로 대체하지 않음",
                      "buy_price": price(evidence, "매수(?:가|가격)|추천가|공략가|매매가") if unambiguous else None,
                      "target_price": price(evidence, "목표(?:가|가격)") if unambiguous else None,
                      "stop_price": price(evidence, "손절(?:가|가격)|손절선") if unambiguous else None,
                      "reason": " / ".join(reasons[:3])[:240] or None,
                      "evidence": evidence[:600], "collected_at": stamp(), "review_status": "규칙 추출·원문 확인 가능"}
            record['parser_version'] = PARSER_VERSION
            identity = [meta["url"], code, expert, kind, day]
            record["id"] = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:24]
            results.append(record)
    # The final, richer occurrence wins within one source; no cross-source guessing.
    return list({r["id"]: r for r in results}.values())


def discover_mtn(program, cutoff):
    page = Page(fetch(program["url"] + "/replay"))
    items = []
    for a in page.links:
        url = urljoin(program["url"], a["url"])
        if not re.search(r"/program/\d+/replay/[\w-]+", url):
            continue
        dm = re.search(r"20\d{2}-\d{2}-\d{2}", a["date"] + " " + a["text"])
        day = dm.group() if dm else None
        if day and day >= cutoff:
            items.append({"url": url, "title": a["text"].strip(), "broadcast_date": day, "program": program["name"], "broadcaster": "MTN", "kind": "mtn"})
    return list({x["url"]: x for x in items}.values())


def document(item, browser_fallback=None):
    meta = {k: item.get(k) for k in ("url", "title", "program", "broadcaster", "broadcast_date", "published_at", "broadcast_program_id", "post_broadcast")}
    if item['kind'] == 'mktv-article':
        return broadcasts.article(item)
    if item['kind'] == 'mktv':
        page = Page(fetch(item['url']))
        if not re.search(r'방영일\s*' + item['broadcast_date'].replace('-', r'\.'), page.text()):
            raise ValueError('공식 다시보기 회차일 확인 필요')
        return broadcast_audio.read_or_start(item)
    if item["kind"] == "mtn":
        page = Page(fetch(item["url"]))
        article = next((urljoin(item["url"], a["url"]) for a in page.links if re.search(r"news.mtn.co.kr/(?:news-detail|article)/\d+", a["url"])), None)
        if not article:
            raise ValueError("공개 추천 기사 없음·영상 발언 확인 필요")
        page = Page(fetch(article))
        meta.update(url=article.replace("/news-detail/", "/article/"), video_url=item["url"], title=page.meta.get("og:title", item["title"]), published_at=published(page.meta.get("article:published_time", "")), evidence_type="공개 기사")
        return extract(page.text(), meta)
    # Only an explicit date in the video title establishes a broadcast date.
    title = item["title"]
    dm = re.search(r"(20\d{2})(?:[./-]|년\s*)(\d{1,2})(?:[./-]|월\s*)(\d{1,2})", title)
    if not dm:
        dm = re.search(r'(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)', title)
    if dm:
        meta["broadcast_date"] = valid_day("%04d-%02d-%02d" % tuple(map(int, dm.groups())))
    else:
        dm = re.search(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)", title)
        if dm:
            try:
                meta["broadcast_date"] = valid_day("20%s-%s-%s" % dm.groups())
            except ValueError:
                pass
    if not meta.get('published_at'):
        player = json_after(fetch(item['url']), r'(?:var\s+)?ytInitialPlayerResponse\s*=\s*')
        micro = player.get('microformat', {}).get('playerMicroformatRenderer', {})
        value = micro.get('publishDate') or micro.get('uploadDate')
        if value:
            meta['published_at'] = published(value)
        if not meta.get('published_at') and not meta.get('broadcast_date'):
            raise ValueError('영상 게시일·방송일 확인 불가; 날짜 추정 저장하지 않음')
    if item.get('post_broadcast') and meta.get('published_at') and not broadcasts.ready(item, meta['published_at'][:10]):
        return [], '방송 종료 후 수집 대기'
    browser_warning = None
    try:
        lines = captions(item["url"])
    except PublicUnavailable:
        raise
    except Exception as exc:
        if browser_fallback:
            try:
                lines = browser_fallback(item['url'])
            except ValueError as browser_error:
                browser_warning = str(browser_error)
            else:
                return transcript_records(lines, {**meta, 'evidence_type': '공개 브라우저 스크립트'}), None
        return [], (str(exc) + (' · ' + browser_warning if browser_warning else ''))[:240]
    meta["evidence_type"] = "공개 한국어 자막"
    return transcript_records(lines, meta), None


SIGNAL_PICK = re.compile(r'(?:오늘\s*(?:첫|두|세)\s*번째|(?:첫|두|세)\s*번째\s*시그널)\s*(?:시그널\s*)?종목(?:은|으로)')


def signal_clip_records(lines, meta):
    """Use the official named clip's spoken selection and price block together."""
    title = meta.get('title', '')
    if meta.get('broadcaster') != '매일경제TV' or '주도주 시그널' not in title:
        return None
    names = {code: name for code, name in watchlists.names().items() if len(name) > 2 and name in title}
    if not names:
        return []
    blocks = []
    for i, line in enumerate(lines):
        previous = lines[i - 1] if i else line
        text = previous['text'] + ' ' + line['text'] if 0 < line['offset'] - previous['offset'] <= 15 else line['text']
        anchor = SIGNAL_PICK.search(text)
        if anchor:
            if not blocks or line['offset'] - blocks[-1][0] > 15:
                blocks.append((line['offset'], text[anchor.end():]))
    rows = []
    for i, (offset, named_text) in enumerate(blocks):
        end = min(offset + 115, blocks[i + 1][0] if i + 1 < len(blocks) else offset + 115)
        excerpt = ' '.join(line['text'] for line in lines if offset <= line['offset'] < end)
        compact_named = re.sub(r'\s+', '', named_text)
        candidates = [(code, name) for code, name in names.items()
                      if name in compact_named or (name == 'RF머트리얼즈' and re.search(r'RF머[틀티]리얼즈', compact_named))]
        if len(candidates) != 1:
            continue
        price_block = re.search(r'매수\s*가(?:는)?[^.。]{0,110}(?:목표\s*가|손절\s*가)[^.。]{0,95}', excerpt)
        if not price_block:
            continue
        code, name = candidates[0]
        normalized_prices = re.sub(r'(매수가|목표가|손절가)\s*는', r'\1 ', price_block.group())
        reasons = re.split(r'(?<=[.!?])\s+', excerpt[:price_block.start()])
        body = '관심종목\n' + name + ' ' + normalized_prices + '\n' + '\n'.join(reasons[:8])
        for row in extract(body, meta, {code: name}):
            if row['classification'] != 'interest' or not (row['target_price'] or row['stop_price']):
                continue
            row['video_offset_seconds'] = offset
            row['expert'] = re.sub(r'\s*MBN골드$', '', row.get('expert') or '') or None
            row['evidence'] = (named_text[:190] + '\n' + price_block.group())[:600]
            if re.search(r'매수가\s*현재가', normalized_prices):
                row['buy_price_basis'] = '현재가 (원문)'
            rows.append(row)
    return list({row['id']: row for row in rows}.values())


def transcript_records(lines, meta):
    # Captions carry offsets, not a wall-clock recommendation time.
    signal_rows = signal_clip_records(lines, meta)
    if signal_rows is not None:
        return signal_rows
    records = extract("\n".join(x["text"] for x in lines), meta)
    for record in records:
        hit = next((x for x in lines if record["name"] in x["text"]), None)
        if hit:
            record["video_offset_seconds"] = hit["offset"]
    return records


def enabled(data):
    return load(data / "recommendations" / "settings.json", {"enabled": True})["enabled"]


def set_enabled(data, value):
    if not isinstance(value, bool):
        raise ValueError("자동수집 설정 오류")
    with LOCK:
        save(data / "recommendations" / "settings.json", {"enabled": value})


def worker(data):
    try:
        STATE.update(busy=True, message="공개 방송·채널 최신 목록 확인 중")
        book = ledger(data)
        config = sources()
        current_day = datetime.now(KST).date()
        cutoff = (current_day - timedelta(days=2)).isoformat()
        for source in config["programs"] + config["channels"]:
            if not source.get("enabled", True):
                continue
            key = source["url"]
            coverage_warning = ''
            try:
                lookback_days = 7 if source.get('post_broadcast') else 3
                source_cutoff = (current_day - timedelta(days=lookback_days - 1)).isoformat()
                if source.get("kind") == "mtn":
                    items = discover_mtn(source, source_cutoff)
                elif source.get('kind') == 'mktv-segment':
                    items = [{**item, 'ai_segment': True} for item in broadcasts.discover_mktv(source, source_cutoff)]
                elif source.get('kind') == 'mktv':
                    items = broadcasts.discover_mktv(source, source_cutoff)
                else:
                    cid = source.get("channel_id") or book["sources"].get(key, {}).get("channel_id")
                    if not cid:
                        content = fetch(source["url"])
                        initial = json_after(content, r'(?:var\s+)?ytInitialData\s*=\s*')
                        cid = initial.get('metadata', {}).get('channelMetadataRenderer', {}).get('externalId')
                        if not cid or not re.fullmatch(r'UC[\w-]{22}', cid):
                            raise ValueError("공식 채널 ID 확인 필요")
                    entries, coverage_warning = youtube_listing(cid)
                    items = [{**e, "kind": "youtube", "broadcaster": source["name"], "program": broadcast_program_match(e["title"], e.get("description", ""), source["name"], config)} for e in entries if not e.get("published_at") or e["published_at"][:10] >= cutoff]
                if source.get('post_broadcast') and not source.get('ai_segment'):
                    items = [broadcasts.tag(item, source) for item in items if not item.get('broadcast_date') or broadcasts.ready(source, item['broadcast_date'])]
                    for discover in (broadcasts.discover_clips, broadcasts.discover_articles):
                        try:
                            items.extend(discover(source))
                        except Exception:
                            coverage_warning += ' · 공식 클립/기사 목록 보완 실패·재시도 예정'
                for item in items:
                    if excluded_program(item, config):
                        continue
                    old = book["documents"].get(item["url"], {})
                    saved = {**item, **old, 'last_seen_day': current_day.isoformat()}
                    if not saved.get('published_at') and item.get('published_at'):
                        saved['published_at'] = item['published_at']
                    book['documents'][item['url']] = saved
                    if item.get('post_broadcast'):
                        if not old.get('post_broadcast'):
                            book['documents'][item['url']]['next_retry'] = 0
                        for field in ('program', 'broadcaster', 'post_broadcast', 'broadcast_program_id'):
                            book['documents'][item['url']][field] = item[field]
                    if item.get('ai_segment') or item.get('program') == 'AI황금분석':
                        saved.update(ai_segment=True, program='AI황금분석')
                book["sources"][key] = {"name": source["name"], "status": "목록 확인", "checked_at": stamp(), "found": len(items), "coverage": f"최신 공개 목록·최근 {lookback_days}일; 전체 회차 보장 아님"}
                if source.get("kind") == "mtn" and not items:
                    book['sources'][key].update(status='확인 필요', message=f'최근 {lookback_days}일 공개 회차 0건·휴방 또는 페이지 구조 변경 확인 필요')
                if source.get("kind") == 'youtube':
                    book["sources"][key]["channel_id"] = cid
                if source.get('post_broadcast'):
                    book['sources'][key].update(schedule=source['post_broadcast'], coverage='방송 종료 10분 후·최근 7일 누락 보완·공개 다시보기/기사/공식 클립(전체 발언 보장 아님)')
                if source.get('ai_segment'):
                    book['sources'][key]['coverage'] = '공식 오후 방송 전체 다시보기의 5인 추천표 확인'
                    if not items:
                        book['sources'][key].update(status='확인 필요', message='최근 공식 오후 방송 전체 다시보기 없음')
                    else:
                        latest = max(item['broadcast_date'] for item in items)
                        book['sources'][key].update(message=f'최신 공개 오후 방송 {latest} · 5인 추천표 확인 대상')
                if coverage_warning:
                    book['sources'][key].update(status='범위 제한', message=coverage_warning)
            except Exception as exc:
                book["sources"][key] = {"name": source["name"], "status": "수집 실패", "checked_at": stamp(), "message": str(exc)[:180]}
            with LOCK:
                save(data / "recommendations" / "ledger.json", book)
        # The archive remains available even after a document ages out of the work queue.
        broadcast_cutoff = (current_day - timedelta(days=6)).isoformat()

        def document_day(x):
            return (x.get('broadcast_date') or x.get('published_at') or '')[:10]

        def priority(x):
            date = (document_day(x) or x.get('last_seen_day') or '1970-01-01').replace('-', '')
            attempts = x.get('attempts', 0) if x.get('parser_version') == PARSER_VERSION else 0
            title = x.get('title') or ''
            has_pick = bool(NEW.search(title) or re.search(r'관심\s*(?:주|종목)|주도주\s*시그널', title))
            return (not bool(x.get('ai_segment')), not bool(x.get('post_broadcast')), attempts,
                    x.get('kind') not in ('mtn', 'mktv', 'mktv-article'), not has_pick, -int(date) if date.isdecimal() else 0,
                    '주도주 시그널' not in title)

        browser_attempts = 0

        def read_public_transcript(url):
            nonlocal browser_attempts
            if browser_attempts >= 5:
                raise ValueError('공개 스크립트 처리 대기')
            browser_attempts += 1
            return broadcasts.browser_lines(url)

        pending = sorted(book["documents"].values(), key=priority)
        processed = priority_processed = non_youtube_processed = 0
        for item in pending[:]:
            if excluded_program(item, config):
                continue
            item_cutoff = broadcast_cutoff if item.get('post_broadcast') else cutoff
            if (document_day(item) or item.get('last_seen_day') or '') < item_cutoff:
                continue
            if item.get('post_broadcast') and priority_processed >= 20:
                continue
            if item.get('kind') != 'youtube' and non_youtube_processed >= 40:
                continue
            completed = item.get('status') == '완료' and item.get('parser_version') == PARSER_VERSION
            retry_wait = item.get('parser_version') == PARSER_VERSION and item.get('next_retry', 0) > time.time()
            if (completed and (not item.get('post_broadcast') or item.get('next_refresh', 0) > time.time())) or retry_wait:
                continue
            if item.get('post_broadcast') and item.get('broadcast_date') and not broadcasts.ready(item, item['broadcast_date']):
                continue
            STATE["message"] = "추천 원문 확인: " + item.get("title", "")[:55]
            try:
                result = document(item, browser_fallback=read_public_transcript)
                records, warning = result if isinstance(result, tuple) else (result, None)
                if item.get('kind') == 'mtn' and not records:
                    warning = '공개 기사 종목 0건·본문 구조 또는 종목 식별 확인 필요'
                if item.get('post_broadcast') and not records and not warning:
                    warning = '방송 원문의 종목·추천 구간 식별 확인 필요'
                # Unknown recommendation dates are filed under publication day,
                # visibly distinct from the recommendation-date field.
                day = item.get("broadcast_date") or (item.get("published_at") or "")[:10]
                for r in records:
                    r["archive_day"] = r.get("recommended_date") or (r.get('published_at') or '')[:10] or day
                    if not r['archive_day']:
                        raise ValueError('원문 날짜 확인 불가; 저장 보류')
                records = [r for r in records if not r.get('published_at') or r['published_at'][:10] >= item_cutoff]
                grouped = {}
                for r in records:
                    grouped.setdefault(r["archive_day"], []).append(r)
                for day, rows in grouped.items():
                    merge(data, day, rows)
                item.update(status="확인 필요" if warning else "완료", record_count=len(records), checked_at=stamp(), message=warning or ("원문 종목 확인" if records else "확인 가능한 국내 종목 없음"))
                if warning:
                    soon = item.get('post_broadcast') or '공개 스크립트 처리 대기' in warning
                    item['next_retry'] = time.time() + (INTERVAL if soon else 21600)
                else:
                    item['next_retry'] = 0
                    item['next_refresh'] = time.time() + 7200
            except Exception as exc:
                item.update(status="확인 필요", message=str(exc)[:180], checked_at=stamp(), next_retry=time.time() + (INTERVAL if item.get('post_broadcast') else 21600))
            processed += 1
            priority_processed += bool(item.get('post_broadcast'))
            non_youtube_processed += item.get('kind') != 'youtube'
            item['attempts'] = (item.get('attempts', 0) if item.get('parser_version') == PARSER_VERSION else 0) + 1
            item['parser_version'] = PARSER_VERSION
            with LOCK:
                save(data / "recommendations" / "ledger.json", book)
            if processed >= 60:
                break
        STATE["message"] = "공개 자료 확인 완료 · 누락·차단·자막 없음은 수집 현황 참조"
    except Exception as exc:
        STATE["message"] = "수집 확인 필요: " + str(exc)[:160]
    finally:
        STATE["busy"] = False
        try:
            with LOCK:
                save(data / "recommendations" / "last_run.json", dict(STATE))
        except OSError:
            STATE['message'] = '수집 상태 저장 실패 · 디스크·권한 확인 필요'
        finally:
            RUN.release()


def start(data):
    if not RUN.acquire(blocking=False):
        return dict(STATE)
    STATE.update(busy=True, last_run=stamp(), message="공개 자료 수집 시작")
    try:
        threading.Thread(target=worker, args=(data,), daemon=True, name="public-recommendations").start()
    except Exception:
        STATE.update(busy=False, message='수집 실행 실패 · 다시 시작하세요')
        RUN.release()
        raise
    return dict(STATE)


def tick(data):
    if not enabled(data) or STATE["busy"]:
        return
    previous = STATE.get("last_run") or load(data / "recommendations" / "last_run.json", {}).get("last_run")
    if not previous or (datetime.now(KST) - datetime.fromisoformat(previous)).total_seconds() >= INTERVAL:
        start(data)


def csv_bytes(doc):
    fields = ["broadcaster", "program", "expert", "recommended_date", "recommended_time", "classification", "name", "code", "buy_price", "target_price", "stop_price", "reason", "url", "published_at", "date_basis", "time_basis", "evidence_type"]
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    labels = ['방송사·채널', '프로그램', '전문가', '추천일', '추천시각(KST)', '분류', '종목명', '종목코드', '추천·매수가(원)', '목표가(원)', '손절가(원)', '추천이유', '원문링크', '게시시각', '날짜근거', '시각근거', '확인자료']
    writer.writerow(dict(zip(fields, labels)))
    for row in doc["records"]:
        safe = {}
        for key in fields:
            value = row.get(key)
            if key == 'buy_price' and value is None:
                value = row.get('buy_price_basis')
            if isinstance(value, dict):
                value = value.get("raw")
            if key == 'classification':
                value = LABELS.get(value, value)
            value = "" if value is None else str(value)
            safe[key] = "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
        writer.writerow(safe)
    return ("\ufeff" + out.getvalue()).encode("utf-8")
