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

ROOT = Path(__file__).resolve().parent
LOCK = threading.RLock()
RUN = threading.Lock()
STATE = {"busy": False, "message": "공개 자료 수집 대기", "last_run": None}
INTERVAL = 1200
PARSER_VERSION = 1
HOSTS = {"www.mtn.co.kr", "news.mtn.co.kr", "www.youtube.com", "youtube.com", "www.youtube-nocookie.com"}
LABELS = {"new": "신규추천", "consultation": "보유종목 상담", "review": "과거추천 복기", "sell": "매도·축소", "interest": "관심종목", "mention": "단순 언급"}


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


def read(data, day):
    valid_day(day)
    with LOCK:
        return load(data / "recommendations" / day / "index.json", {"day": day, "records": [], "stocks": []})


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
        items = {r["id"]: r for r in doc["records"] if r['url'] not in incoming}
        items.update({r["id"]: r for r in records})
        doc["records"] = sorted(items.values(), key=lambda r: (r.get("recommended_time") or "", r["id"]), reverse=True)
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
        if (NEW.search(line) or re.search(r"종목\s*상담|보유\s*종목|복기|관심\s*(?:종목|주)|후보|PICK", line, re.I)) and not (pattern and pattern.search(line)):
            section = line
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
            kind = category(evidence, section, meta.get("title", ""))
            primary = primary_name(line, name)
            if meta.get('evidence_type') == '공개 기사' and not primary:
                kind = 'mention'
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


def document(item):
    meta = {k: item.get(k) for k in ("url", "title", "program", "broadcaster", "broadcast_date", "published_at")}
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
    try:
        lines = captions(item["url"])
    except PublicUnavailable:
        raise
    except Exception as exc:
        # Metadata is evidence of mention only; never fabricate spoken advice.
        meta["evidence_type"] = "제목·설명만 확인 · 발언 미확인"
        records = extract(title + "\n" + item.get("description", "")[:6000], meta)
        for record in records:
            record.update(classification="consultation" if "상담" in title else "mention", buy_price=None, target_price=None, stop_price=None, reason=None,
                          recommended_time=None, review_status="자막 미확인: " + str(exc)[:160])
            record["id"] = hashlib.sha256((meta["url"] + record["code"] + "metadata").encode()).hexdigest()[:24]
        return records, str(exc)[:180]
    meta["evidence_type"] = "공개 한국어 자막"
    # Captions carry offsets, not a wall-clock recommendation time.
    records = extract("\n".join(x["text"] for x in lines), meta)
    for record in records:
        hit = next((x for x in lines if record["name"] in x["text"]), None)
        if hit:
            record["video_offset_seconds"] = hit["offset"]
    return records, None


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
        cutoff = (datetime.now(KST).date() - timedelta(days=2)).isoformat()
        for source in config["programs"] + config["channels"]:
            if not source.get("enabled", True):
                continue
            key = source["url"]
            try:
                if source.get("kind") == "mtn":
                    items = discover_mtn(source, cutoff)
                else:
                    cid = source.get("channel_id") or book["sources"].get(key, {}).get("channel_id")
                    if not cid:
                        content = fetch(source["url"])
                        initial = json_after(content, r'(?:var\s+)?ytInitialData\s*=\s*')
                        cid = initial.get('metadata', {}).get('channelMetadataRenderer', {}).get('externalId')
                        if not cid or not re.fullmatch(r'UC[\w-]{22}', cid):
                            raise ValueError("공식 채널 ID 확인 필요")
                    entries = feed_entries(fetch("https://www.youtube.com/feeds/videos.xml?" + urlencode({"channel_id": cid})))
                    items = [{**e, "kind": "youtube", "broadcaster": source["name"], "program": next((p["name"] for p in config.get("broadcast_programs", []) if p["broadcaster"] == source["name"] and p["name"] in e["title"]), None)} for e in entries if e.get("published_at") and e["published_at"][:10] >= cutoff]
                for item in items:
                    old = book["documents"].get(item["url"], {})
                    book["documents"][item["url"]] = {**item, **old}
                book["sources"][key] = {"name": source["name"], "status": "목록 확인", "checked_at": stamp(), "found": len(items), "coverage": "최신 공개 목록·최근 3일; 전체 회차 보장 아님"}
                if source.get("kind") != "mtn":
                    book["sources"][key]["channel_id"] = cid
            except Exception as exc:
                book["sources"][key] = {"name": source["name"], "status": "수집 실패", "checked_at": stamp(), "message": str(exc)[:180]}
            with LOCK:
                save(data / "recommendations" / "ledger.json", book)
        # Bounded work per round. Failed documents retry after six hours.
        def priority(x):
            date = (x.get('published_at') or x.get('broadcast_date') or '1970-01-01')[:10]
            return (x.get('attempts', 0), x.get('kind') != 'mtn', -datetime.strptime(date, '%Y-%m-%d').toordinal())
        pending = sorted(book["documents"].values(), key=priority)
        for item in pending[:]:
            if (item.get("status") == "완료" and item.get('parser_version') == PARSER_VERSION) or item.get("next_retry", 0) > time.time():
                continue
            STATE["message"] = "추천 원문 확인: " + item.get("title", "")[:55]
            try:
                result = document(item)
                records, warning = result if isinstance(result, tuple) else (result, None)
                # Unknown recommendation dates are filed under publication day,
                # visibly distinct from the recommendation-date field.
                day = item.get("broadcast_date") or (item.get("published_at") or "")[:10]
                for r in records:
                    r["archive_day"] = r.get("recommended_date") or day
                grouped = {}
                for r in records:
                    grouped.setdefault(r["archive_day"], []).append(r)
                for day, rows in grouped.items():
                    merge(data, day, rows)
                item.update(status="확인 필요" if warning else "완료", record_count=len(records), checked_at=stamp(), message=warning or ("원문 종목 확인" if records else "확인 가능한 국내 종목 없음"))
                if warning:
                    item['next_retry'] = time.time() + 21600
            except Exception as exc:
                item.update(status="확인 필요", message=str(exc)[:180], checked_at=stamp(), next_retry=time.time() + 21600)
            item["attempts"] = item.get("attempts", 0) + 1
            item['parser_version'] = PARSER_VERSION
            with LOCK:
                save(data / "recommendations" / "ledger.json", book)
            if sum(1 for d in book["documents"].values() if d.get("checked_at", "") >= STATE["last_run"]) >= 60:
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
            if isinstance(value, dict):
                value = value.get("raw")
            if key == 'classification':
                value = LABELS.get(value, value)
            value = "" if value is None else str(value)
            safe[key] = "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
        writer.writerow(safe)
    return ("\ufeff" + out.getvalue()).encode("utf-8")
