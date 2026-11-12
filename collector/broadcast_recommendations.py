"""Post-broadcast discovery/evidence for the five approved TV programmes."""
import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

from kiwoom import KST


def compact(value):
    return re.sub(r'[^가-힣A-Za-z0-9]', '', value).lower()


def ready(program, day, current=None):
    current = current or datetime.now(KST)
    date = datetime.strptime(day, '%Y-%m-%d').date()
    if date != current.date():
        return date < current.date()
    end = program.get('post_broadcast', {}).get('end')
    if not end:
        return True
    end_time = datetime.fromisoformat(day + 'T' + end).replace(tzinfo=KST)
    return current >= end_time + timedelta(minutes=program['post_broadcast'].get('delay_minutes', 10))


def tag(item, program):
    return {**item, 'broadcast_program_id': program['program_id'], 'post_broadcast': program['post_broadcast'],
            'program': program['name'], 'broadcaster': program['broadcaster']}


def discover_mktv(program, cutoff):
    import recommendations as r
    page = r.Page(r.fetch(program['url']))
    result = {}
    for link in page.links:
        url = urljoin(program['url'], link['url'])
        match = re.search(r'20\d{2}[.-]\d{2}[.-]\d{2}', link['text'])
        if not match or '/program/vod?' not in url or ('program_no=' + program['program_id']) not in url:
            continue
        day = match.group().replace('.', '-')
        if day >= cutoff and ready(program, day):
            result[url] = tag({'url': url, 'title': link['text'].strip(), 'broadcast_date': day, 'kind': 'mktv'}, program)
    return list(result.values())


def discover_clips(program):
    """Search results must identify the verified broadcaster as the owner."""
    import recommendations as r
    url = 'https://www.youtube.com/results?' + urlencode({'search_query': program['name'] + ' ' + program['broadcaster']})
    initial = r.json_after(r.fetch(url), r'(?:var\s+)?ytInitialData\s*=\s*')
    found = {}
    labels = [compact(x) for x in [program['name'], *program.get('aliases', [])] if compact(x)]
    def walk(value):
        if isinstance(value, dict):
            video = value.get('videoRenderer', {})
            vid = video.get('videoId', '')
            title = ''.join(x.get('text', '') for x in video.get('title', {}).get('runs', []))
            owners = [x.get('navigationEndpoint', {}).get('browseEndpoint', {}).get('browseId')
                      for x in video.get('ownerText', {}).get('runs', []) + video.get('shortBylineText', {}).get('runs', [])]
            if re.fullmatch(r'[\w-]{11}', vid) and program['channel_id'] in owners and any(label in compact(title) for label in labels):
                found[vid] = tag({'url': 'https://www.youtube.com/watch?v=' + vid, 'title': title,
                                  'published_at': None, 'kind': 'youtube', 'description': ''}, program)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(initial)
    return list(found.values())[:12]


def discover_articles(program):
    import recommendations as r
    if program['broadcaster'] != '매일경제TV':
        return []
    page = r.Page(r.fetch('https://mbnmoney.mbn.co.kr/search?' + urlencode({'query': program['name']})))
    result = {}
    for link in page.links:
        url = urljoin('https://mbnmoney.mbn.co.kr', link['url'])
        # Fetch only the official news view route; the body is checked again.
        if urlparse(url).hostname == 'mbnmoney.mbn.co.kr' and re.search(r'/news/view\?news_no=[A-Z0-9]+', url):
            result[url] = tag({'url': url, 'title': link['text'].strip(), 'kind': 'mktv-article', 'broadcast_date': None}, program)
    return list(result.values())[:8]


class ArticleBody(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.active = 0
        self.parts = []
        self.skip = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('script', 'style'):
            self.skip += 1
        if tag == 'div':
            if self.active:
                self.active += 1
            elif 'news_contents' in a.get('class', '').split():
                self.active = 1
        if self.active and tag in ('br', 'p', 'div'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        if self.active and tag == 'div':
            self.active -= 1

    def handle_data(self, text):
        if self.active and not self.skip:
            self.parts.append(text)


def article(item):
    import recommendations as r
    html = r.fetch(item['url'])
    page = r.Page(html)
    title = page.meta.get('og:title', '')
    body = ''.join(ArticleBody(html).parts)
    if compact(item['program']) not in compact(title + body):
        raise ValueError('해당 프로그램 기사로 확인되지 않음')
    date = re.search(r'기사입력\s*(20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2})', page.text())
    if not body.strip() or not date:
        raise ValueError('공식 기사 본문·게시일 확인 필요')
    meta = {**item, 'title': title, 'published_at': r.published(date.group(1)), 'evidence_type': '공개 기사'}
    # News recaps of profit rankings are not today's new recommendations.
    if re.search(r'수익률|선두|순위|집계|수성', title):
        body = '▶▶ 과거추천 복기\n' + body
    return r.extract(body, meta)


def browser_lines(url):
    root = Path(__file__).resolve().parent
    node = Path(os.environ.get('USERPROFILE', '')) / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    if not node.is_file():
        raise ValueError('공개 스크립트용 Node 실행 파일 확인 필요')
    try:
        result = subprocess.run([str(node), str(root / 'broadcast_transcript.cjs'), url],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=65,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        doc = json.loads(result.stdout.decode('utf-8'))
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ValueError('공개 브라우저 스크립트 작업 실패·다음 주기 재시도') from exc
    if result.returncode or not doc.get('lines'):
        raise ValueError(doc.get('error', '공개 브라우저 스크립트 없음'))
    return doc['lines']
