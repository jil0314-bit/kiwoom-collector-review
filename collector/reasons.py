"""Daily rise reasons: Infostock's '특징 상한가 및 급등종목' pasted by the user, plus Naver stock news.

Stored apart from user notes in data/reasons/YYYY-MM-DD.json; user memos are never touched.
"""
import json
import os
import re
import threading
import time
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from kiwoom import KST

# Hero4 writes the article currently open in its news viewer here. Read only.
HERO4_NEWS = Path(r"C:\KiwoomHero4\user\#Q2gsNx0%Eg$$\News.html")
TITLE = "특징 상한가 및 급등"
STAMP = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*(\d{1,2})\s*시\s*(\d{1,2})\s*분")

LOCK = threading.RLock()
MAX_TEXT = 100000
NEWS_PER_STOCK = 3
NEWS_URL = "https://m.stock.naver.com/api/news/stock/{code}?pageSize=50&page=1"
RISING = re.compile(r"특징주|상한가|급등|강세|상승|신고가|껑충|급증|치솟|뛰|↑|수혜|승인|허가|계약|수주|체결|공급|협약|MOU|인수|합병|최대|호실적|흑자|기대")
ENTRY = re.compile(r"(?:^|(?<=[\t|\n]))[ \t]*(?P<name>[^\t\n|()]*?)[ \t]*(?:\(\s*(?P<code>[0-9A-Z]{6})\s*\))?\s*"
                   r"(?P<price>\d[\d,]*)\s*원\s*\(\s*(?P<rate>[+\-↑↓]?\s*\d+(?:\.\d+)?)\s*%\s*\)", re.M)
DAYS = re.compile(r"^[\s|]*(\d{1,2})(?=[\s|]|$)")


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
    return re.sub(r"\s+", " ", text.replace("|", " ")).strip()


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


def save_infostock(data, day, text, names, source="paste", published=""):
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise ValueError("붙여넣은 내용이 비어 있거나 너무 깁니다.")
    items = parse(text, names)
    if not items:
        raise ValueError("종목과 사유를 찾지 못했습니다. 영웅문 기사 본문 전체를 복사(Ctrl+A → Ctrl+C)해서 붙여넣어 주세요.")
    with LOCK:
        record = read_day(data, day)
        previous = record.get("infostock", {}).get("items", {})
        record["infostock"] = {"saved_at": datetime.now(KST).isoformat(timespec="seconds"), "source": source,
                               "published": published, "title": "증시요약(6) - 특징 상한가 및 급등종목", "items": {**previous, **items}}
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
    parser.feed(raw)
    return "".join(parser.parts)


def read_hero4(path=None):
    """Returns (day, published, text) when the open Hero4 article is the daily limit-up summary."""
    raw = (path or HERO4_NEWS).read_bytes()
    for enc in ("cp949", "utf-8"):
        try:
            content = raw.decode(enc)
            break
        except UnicodeError:
            continue
    else:
        return None
    text = html_text(content)
    if TITLE not in text:
        return None
    day, published = article_day(text)
    return (day, published, text) if day else None


SEEN = {"stamp": None}


def watch_hero4(data, names_for, path=None):
    """Cheap stat each tick; only a changed file that holds the summary article is parsed and saved."""
    path = path or HERO4_NEWS
    try:
        info = path.stat()
    except OSError:
        return None
    stamp = (str(path), str(data), info.st_mtime_ns, info.st_size)
    if SEEN["stamp"] == stamp:
        return None
    found = read_hero4(path)
    if not found:
        SEEN["stamp"] = stamp
        return None
    day, published, text = found
    items = save_infostock(data, day, text, names_for(day), source="hero4", published=published)
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


def fetch_summary(data, day, names, fetch=public_html):
    """Public article only, exact publication day; local Hero4 remains the primary source."""
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
                                'url': record.get('infostock', {}).get('source', '') if info else news[0].get('url', '')})
    return result
