"""Daily rise reasons: Infostock's '특징 상한가 및 급등종목' pasted by the user, plus Naver stock news.

Stored apart from user notes in data/reasons/YYYY-MM-DD.json; user memos are never touched.
"""
import json
import hashlib
import os
import re
import threading
import time
import uuid
import urllib.request
from urllib.parse import urlencode
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from kiwoom import KST

# Hero4 writes the article currently open in its news viewer here. Read only.
HERO4_NEWS = Path(r"C:\KiwoomHero4\user\#Q2gsNx0%Eg$$\News.html")
TITLE = "특징 상한가 및 급등"
FEATURED = ("특징 종목(코스피)", "특징 종목(코스닥)", "특징종목(코스피)", "특징종목(코스닥)")
STAMP = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*(\d{1,2})\s*시\s*(\d{1,2})\s*분")

LOCK = threading.RLock()
MAX_TEXT = 100000
NEWS_PER_STOCK = 3
NEWS_URL = "https://m.stock.naver.com/api/news/stock/{code}?pageSize=50&page=1"
RISING = re.compile(r"특징주|상한가|급등|강세|상승|신고가|껑충|급증|치솟|뛰|↑|수혜|승인|허가|계약|수주|체결|공급|협약|MOU|인수|합병|최대|호실적|흑자|기대")
ENTRY = re.compile(r"(?:^|(?<=[\t|\n]))[ \t]*(?P<name>[^\t\n|()]*?)[ \t]*(?:\(\s*(?P<code>[0-9A-Z]{6})\s*\))?\s*"
                   r"(?P<price>\d[\d,]*)\s*원\s*\(\s*(?P<rate>[+\-↑↓]?\s*\d+(?:\.\d+)?)\s*%\s*\)", re.M)
DAYS = re.compile(r"^[ \r\n]*(?:[\t|][ ]*)?(\d{1,2})[ ]*(?=[\t|\n]|$)")


def path(data, day):
    if datetime.strptime(day, "%Y-%m-%d").strftime("%Y-%m-%d") != day:
        raise ValueError("날짜 형식 오류")
    return data / "reasons" / f"{day}.json"


def read_day(data, day):
    p = path(data, day)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def write_day(data, day, record):
    p = path(data, day)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def clean(text):
    return re.sub(r"\s+", " ", text.replace("|", " ").replace("\x00", "")).strip()


def parse(text, names):
    """Rows look like '진원생명과학 (011000) 1,322원 (+29.99%) | 2 | 사유'; tabs, pipes or line breaks between cells."""
    by_name = {re.sub(r"\s+", "", n): c for c, n in names.items()}
    matches = list(ENTRY.finditer(text.replace("\r", "")))
    items = {}
    for i, m in enumerate(matches):
        tail = text.replace("\r", "")[m.end():matches[i + 1].start() if i + 1 < len(matches) else None]
        days = DAYS.match(tail)
        if days:
            tail = tail[days.end():]
        lines = [clean(line) for line in tail.split("\n")]
        reason = next((line for line in lines if line), "")
        name = clean(m.group("name"))
        code = m.group("code") or by_name.get(name.replace(" ", ""))
        if not code or not reason:
            continue
        rate = float(re.sub(r"[^\d.]", "", m.group("rate")))
        if m.group("rate").strip().startswith(("-", "↓")):
            rate = -rate
        known = names.get(code, "")
        # The article's name is current; a wrapped cell may split it with a space.
        if not name or known.replace(" ", "") == name.replace(" ", ""):
            name = known or name
        items[code] = {"name": name, "reason": reason, "rate": rate,
                       "limit_days": int(days.group(1)) if days else None, "rank": len(items) + 1}
    return items


def article_title(text):
    for line in text.splitlines():
        line = clean(line)
        if "증시요약(" in line and (TITLE in line or any(label in line for label in FEATURED)):
            return line.removeprefix("제목 : ").removeprefix("제목 ")
    return ""


def parse_feature_groups(text, names):
    """Expand explicitly named members of rising groups in a featured article."""
    by_name = {re.sub(r"\s+", "", name): code for code, name in names.items()}
    items = {}
    rows = text.replace("\r", "").splitlines()
    for index, row in enumerate(rows[:-1]):
        cells = [clean(cell) for cell in row.split("\t") if clean(cell)]
        if len(cells) != 2 or not cells[0].endswith("그룹주"):
            continue
        reason = cells[1]
        if not re.search(r"상승|급등|상한가", reason) or re.search(r"하락|급락", reason):
            continue
        members = re.search(r"\[종목\]\s*:\s*([^\n]+)", rows[index + 1])
        if not members:
            continue
        for member in members.group(1).split(","):
            name = clean(member)
            code = by_name.get(re.sub(r"\s+", "", name))
            if code:
                items[code] = {"name": names[code], "reason": reason, "rate": None,
                               "limit_days": None, "rank": None}
    return items


def save_infostock(data, day, text, names, source="paste", published="", archive=""):
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise ValueError("붙여넣은 내용이 비어 있거나 너무 깁니다.")
    path(data, day)
    dated, _ = article_day(text)
    if dated and dated != day:
        raise ValueError(f"기사 날짜 {dated}와 저장 날짜 {day}가 다릅니다. 기사 날짜를 선택하세요.")
    title = article_title(text)
    items = parse(text, names)
    if any(label in title for label in FEATURED):
        items = {code: item for code, item in items.items() if item["rate"] > 0}
        for code, item in parse_feature_groups(text, names).items():
            items.setdefault(code, item)
    if not items:
        raise ValueError("종목과 사유를 찾지 못했습니다. 영웅문 기사 본문 전체를 복사(Ctrl+A → Ctrl+C)해서 붙여넣어 주세요.")
    for item in items.values():
        item.update(article_title=title, article_day=day, source=source, published=published)
        if archive:
            item["archive"] = archive
    with LOCK:
        record = read_day(data, day)
        previous = record.get("infostock", {}).get("items", {})
        articles = record.get("infostock", {}).get("articles", [])
        article = {"day": day, "title": title, "source": source, "published": published}
        if archive:
            article["archive"] = archive
        if article not in articles:
            articles = [*articles, article]
        merged = {**items, **previous}
        if TITLE in title:
            for code, item in items.items():
                old = previous.get(code, {})
                if (any(label in old.get('article_title', '') for label in FEATURED)
                        or (TITLE in old.get('article_title', '') and old.get('source') != 'paste'
                            and published >= old.get('published', ''))):
                    merged[code] = item
        record["infostock"] = {"saved_at": datetime.now(KST).isoformat(timespec="seconds"), "source": source,
                               "published": published, "title": title or "증시요약(6) - 특징 상한가 및 급등종목",
                               "articles": articles, "items": merged,
                               "missing_codes": [code for code in record.get("infostock", {}).get("missing_codes", []) if code not in items]}
        write_day(data, day, record)
    return items


def article_day(text):
    """The article's own date ('2026년 09월 23일 17시 07분'), so old articles land on their own day."""
    m = STAMP.search(text)
    if not m:
        return None, ""
    y, mo, d, h, mi = (int(g) for g in m.groups())
    return f"{y:04d}-{mo:02d}-{d:02d}", f"{h:02d}:{mi:02d}"


class Cells(HTMLParser):
    """Table-aware text: cells separated by tabs, rows by line breaks."""
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("td", "th"):
            self.parts.append("\t")
        elif tag in ("tr", "p", "div") or tag == "br":
            self.parts.append("\n" if tag != "br" else " ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, text):
        if not self.skip:
            self.parts.append(re.sub(r"\s+", " ", text))


def html_text(raw):
    parser = Cells()
    parser.feed(raw.replace("\x00", ""))
    return "".join(parser.parts)


def hero4_news_path(root=None):
    candidates = []
    for p in (root or Path(r'C:\KiwoomHero4\user')).glob('*/News.html'):
        try:
            candidates.append((p.stat().st_mtime_ns, p))
        except OSError:
            continue
    return max(candidates, key=lambda x: x[0])[1] if candidates else HERO4_NEWS


def read_hero4(path=None):
    """Returns (day, published, text) when the open Hero4 article is the daily limit-up summary."""
    raw = (path or hero4_news_path()).read_bytes()
    for enc in ("cp949", "utf-8"):
        try:
            content = raw.decode(enc)
            break
        except UnicodeError:
            continue
    else:
        return None
    text = html_text(content)
    if not article_title(text):
        return None
    day, published = article_day(text)
    return (day, published, text) if day else None


def archive_hero4(data, day, published, source):
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()[:16]
    folder = Path(data) / "reasons" / "hero4_articles"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{day}_{published.replace(':', '')}_{digest}.html"
    target = folder / name
    if not target.exists():
        temp = folder / (name + ".tmp-" + uuid.uuid4().hex)
        try:
            temp.write_bytes(raw)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
    if target.read_bytes() != raw:
        raise OSError("기사 원문 보관 검증 실패")
    return target, read_hero4(target)


SEEN = {"stamp": None}


def write_hero_status(data, **record):
    target = Path(data) / 'reasons' / 'hero4_source_status.json'
    with LOCK:
        old = json.loads(target.read_text(encoding='utf-8')) if target.is_file() else {}
        if {k:v for k,v in old.items() if k != 'at'} == record:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + '.tmp-' + uuid.uuid4().hex)
        try:
            temp.write_text(json.dumps({**record,'at':datetime.now(KST).isoformat(timespec='seconds')},ensure_ascii=False),encoding='utf-8')
            os.replace(temp,target)
        finally:
            temp.unlink(missing_ok=True)


def source_status(data, day):
    """Explain missing original articles separately from a checked news feed."""
    record = read_day(data, day)
    target = Path(data) / 'reasons' / 'hero4_source_status.json'
    local = json.loads(target.read_text(encoding='utf-8')) if target.is_file() else {}
    summary = Path(data) / 'reasons' / ('summary_' + day + '.json')
    if not summary.is_file():
        summary = Path(data) / 'reasons' / 'summary_status.json'
    public = json.loads(summary.read_text(encoding='utf-8')) if summary.is_file() else {}
    return {'day': day, 'missing_codes': record.get('infostock', {}).get('missing_codes', []), 'article_count': len(record.get('infostock',{}).get('items',{})),
            'local_article_day': local.get('article_day'), 'local_state': local.get('state','UNKNOWN'),
            'public_state': public.get('state','UNKNOWN') if public.get('day') == day else 'UNKNOWN'}


def watch_hero4(data, names_for, path=None):
    """Cheap stat each tick; only a changed file that holds the summary article is parsed and saved."""
    path = path or hero4_news_path()
    try:
        info = path.stat()
    except OSError:
        write_hero_status(data,state='source_unavailable',article_day=None,count=0,codes=[])
        return None
    stamp = (str(path), str(data), info.st_mtime_ns, info.st_size)
    if SEEN["stamp"] == stamp:
        status_path = Path(data) / 'reasons' / 'hero4_source_status.json'
        status = json.loads(status_path.read_text(encoding='utf-8')) if status_path.is_file() else {}
        saved_day = status.get('article_day')
        if not saved_day or set(status.get('codes',[])) <= set(read_day(data,saved_day).get('infostock',{}).get('items',{})):
            return None
    found = read_hero4(path)
    if not found:
        write_hero_status(data,state='not_summary_article',article_day=None,count=0,codes=[])
        SEEN["stamp"] = stamp
        return None
    day, published, text = found
    archived, verified = archive_hero4(data, day, published, path)
    if not verified or verified[:2] != (day, published) or verified[2] != text:
        return None  # The viewer replaced News.html during our read; retry on the next tick.
    items = save_infostock(data, day, verified[2], names_for(day), source="hero4", published=published,
                           archive=str(archived.relative_to(Path(data) / "reasons")))
    write_hero_status(data,state='saved',article_day=day,published=published,count=len(items),codes=list(items))
    SEEN["stamp"] = stamp
    return day, items


def naver(code, opener=urllib.request.urlopen):
    req = urllib.request.Request(NEWS_URL.format(code=code), headers={"User-Agent": "Mozilla/5.0"})
    with opener(req, timeout=15) as r:
        groups = json.loads(r.read())
    return [i for g in groups if isinstance(g, dict) for i in g.get("items", [])]


def pick_news(items, day, name):
    compact = day.replace("-", "")
    today = [i for i in items if str(i.get("datetime", "")).startswith(compact) and i.get("title")]
    wanted = [i for i in today if name in i["title"] or RISING.search(i["title"])
              or (name in i.get("body", "") and RISING.search(i.get("body", "")))]
    wanted.sort(key=lambda i: (name not in i["title"], not RISING.search(i["title"]), -int(i["datetime"])))
    return [{"title": clean(i.get("titleFull") or i["title"]), "office": i.get("officeName", ""),
             "summary": clean(i.get("body", ""))[:300],
             "at": f"{i['datetime'][8:10]}:{i['datetime'][10:12]}",
             "url": f"https://n.news.naver.com/mnews/article/{i.get('officeId', '')}/{i.get('articleId', '')}"}
            for i in wanted[:NEWS_PER_STOCK]]


def fetch_news(data, day, stocks, fetch=naver, pause=0.25):
    """Naver news for every listed stock; failures of single stocks are skipped, not fatal."""
    found, failed = {}, 0
    for s in stocks:
        try:
            found[s["code"]] = pick_news(fetch(s["code"]), day, s["name"])
        except Exception:
            failed += 1
        time.sleep(pause)
    if stocks and failed == len(stocks):
        raise OSError("네이버 뉴스 조회 실패")
    return save_news(data, day, found, failed)


def save_news(data, day, found, failed=0):
    with LOCK:
        record = read_day(data, day)
        previous = record.get("news", {}).get("items", {})
        record["news"] = {"fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
                          "items": {**previous, **{code: value for code, value in found.items() if value or not previous.get(code)}}, "failed": failed}
        write_day(data, day, record)
    return found


class SummaryLinks(HTMLParser):
    """Only named summary links on the public distributor's news list."""
    def __init__(self):
        super().__init__()
        self.href, self.text, self.links = '', [], []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.href, self.text = dict(attrs).get('href', ''), []

    def handle_data(self, text):
        if self.href:
            self.text.append(text)

    def handle_endtag(self, tag):
        if tag == 'a':
            if TITLE in clean(' '.join(self.text)) and re.fullmatch(r'(?:https://stock\.mk\.co\.kr)?/news/view/\d+', self.href):
                self.links.append('https://stock.mk.co.kr' + self.href if self.href.startswith('/') else self.href)
            self.href, self.text = '', []


def public_html(url, opener=urllib.request.urlopen):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with opener(req, timeout=12) as response:
        return response.read(2_000_000).decode('utf-8')


SAMSUNG_BASE = 'https://www.samsungpop.com/ux/kor/trading/marketStock/analysis/company/'


def summary_complete(record):
    info = record.get('infostock', {})
    articles = info.get('articles') or [info]
    return bool(info.get('items')) and not info.get('missing_codes') and any(TITLE in a.get('title', '') for a in articles)


def fetch_distributor_summary(data, day, names, fetch=public_html):
    """Public Infostock distributor. Validate list date, detail date and title before saving."""
    path(data, day)
    query = urlencode({'gubun': 'news', 'P_StartDt': day, 'A_SrchKeyWord': '증시요약(6)',
                       'P_Sect2': '1', 'P_MidSect': '13', 'P_ItemCd6': '', 'P_ReqstCnt1': '30'})
    listing = fetch(SAMSUNG_BASE + 'analysisOnestopContentsListPopup.do?' + query)
    pattern = r'onclick="goView\(([^)]+)\);">([^<]+)</a>'
    for call, title in re.findall(pattern, listing):
        args = re.findall(r"'([0-9]+)'", call)
        if len(args) != 6 or args[0] != day.replace('-', '') or TITLE not in clean(title):
            continue
        keys = ['P_Dt1', 'P_Time11', 'P_ContinueKey4', 'P_LageSect', 'P_MidSect', 'P_SmllSect']
        params = urlencode(dict(zip(keys, args)))
        url = SAMSUNG_BASE + 'analysisOnestopContentsListPopupView2.do?' + params
        detail = html_text(fetch(url))
        if day not in detail or TITLE not in detail or '인포스탁' not in detail:
            raise ValueError('인포스탁 기사 상세 날짜·제목·출처 불일치')
        raw = fetch(SAMSUNG_BASE + 'viewContent.do?' + params + '&A_ProcFlag=Y')
        text = html_text(raw)
        parsed = parse(text, names)
        linked_codes = set(re.findall(r'stockitem\?code=([0-9A-Z]{6})', raw.replace('\x00', '')))
        missing_codes = sorted(linked_codes - set(parsed))
        if TITLE not in text or not parsed:
            raise ValueError('인포스탁 기사 본문 누락 또는 형식 변경')
        own_day, _ = article_day(text)
        if own_day and own_day != day:
            raise ValueError('인포스탁 본문 날짜 불일치')
        at = args[1][:2] + ':' + args[1][2:4]
        folder = Path(data) / 'reasons' / 'public_articles'
        folder.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        target = folder / (day + '_' + digest[:16] + '.html')
        if not target.exists():
            temp = target.with_name(target.name + '.tmp-' + uuid.uuid4().hex)
            temp.write_bytes(raw.encode('utf-8'))
            os.replace(temp, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise OSError('인포스탁 공개 원문 보관 검증 실패')
        items = save_infostock(data, day, text, names, source=url, published=at,
                              archive=str(target.relative_to(Path(data) / 'reasons')))
        with LOCK:
            record = read_day(data, day)
            record['infostock']['missing_codes'] = missing_codes
            record['infostock']['parse_state'] = 'partial' if missing_codes else 'complete'
            write_day(data, day, record)
        return items
    return {}


def fetch_summary(data, day, names, fetch=public_html):
    """Public article only, exact publication day; local Hero4 remains the primary source."""
    if fetch is public_html:
        # Prefer a searchable dated distributor, not a shallow general-news scan.
        return fetch_distributor_summary(data, day, names, fetch)
    for page in range(1, 11):
        html = fetch(f'https://stock.mk.co.kr/news/all/pc?page={page}')
        links = SummaryLinks()
        links.feed(html)
        for url in dict.fromkeys(links.links):
            text = html_text(fetch(url))
            published = re.search(r'입력\s*:\s*(20\d{2})[.-](\d{2})[.-](\d{2})\s+(\d{2}:\d{2})', text)
            article_date, at = article_day(text)
            if published:
                article_date, at = '-'.join(published.group(i) for i in (1, 2, 3)), published.group(4)
            if article_date == day and TITLE in text and parse(text, names):
                return save_infostock(data, day, text, names, source=url, published=at)
        # Avoid scanning news older than the target day.
        dates = re.findall(r'20\d{2}-\d{2}-\d{2}', html_text(html))
        if dates and max(dates) < day:
            break
    return {}


def recent_history(data, day):
    """Dated evidence at the top of collector memos; personal note files stay intact."""
    result = {}
    for file in sorted((data / 'reasons').glob('????-??-??.json'), reverse=True):
        if file.stem >= day:
            continue
        record = read_day(data, file.stem)
        codes = set(record.get('infostock', {}).get('items', {})) | set(record.get('news', {}).get('items', {}))
        for code in codes:
            entries = result.setdefault(code, [])
            if len(entries) >= 5:
                continue
            info = record.get('infostock', {}).get('items', {}).get(code)
            news = record.get('news', {}).get('items', {}).get(code, [])
            if info or news:
                entries.append({'day': file.stem, 'reason': info['reason'] if info else news[0]['title'],
                                'source': '인포스탁' if info else news[0].get('office', '뉴스'),
                                'url': (info.get('source') or record.get('infostock', {}).get('source', ''))
                                       if info else news[0].get('url', '')})
    return result
