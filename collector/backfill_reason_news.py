"""Fetch missing dated news for archived top-100 stocks, preserving written reasons."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from pathlib import Path
import time
import urllib.request

import archive
import notes
import reason_memos
import reasons


def history(code, earliest):
    seen, result = set(), []
    for page in range(1, 13):
        url = reasons.NEWS_URL.format(code=code).replace('page=1', f'page={page}')
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=15) as response:
                    groups = json.load(response)
                break
            except (OSError, ValueError):
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)
        items = [item for group in groups if isinstance(group, dict) for item in group.get('items', [])]
        new = [item for item in items if (item.get('id'), item.get('datetime'), item.get('title')) not in seen]
        if not new:
            break
        result.extend(new)
        seen.update((item.get('id'), item.get('datetime'), item.get('title')) for item in new)
        dates = [str(item.get('datetime', ''))[:8] for item in items if item.get('datetime')]
        if dates and min(dates) < earliest.replace('-', ''):
            break
        time.sleep(.15)
    return result


def run(data, through):
    datetime.strptime(through, '%Y-%m-%d')
    targets = {}
    for folder in sorted(data.glob('????-??-??')):
        day = folder.name
        if day > through or not folder.is_dir():
            continue
        record, existing = reasons.read_day(data, day), notes.read_day(data, day)
        for stock in archive.metadata(archive.active(data, day)).get('stocks', []):
            if existing.get(stock['code'], {}).get('text', '').strip():
                continue
            if reason_memos.evidence(record, stock, day):
                continue
            targets.setdefault(stock['code'], []).append((day, stock))
    report = {'through': through, 'searched_symbols': len(targets), 'added_evidence': 0, 'failed': []}
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = {pool.submit(history, code, min(day for day, _ in wanted)): code for code, wanted in targets.items()}
        for done, future in enumerate(as_completed(jobs), 1):
            code = jobs[future]
            try:
                articles = future.result()
                for day, stock in targets[code]:
                    picked = reasons.pick_news(articles, day, stock['name'])
                    # Preserve existing related links; prepend newly found stock-specific evidence.
                    picked = [item for item in picked if reason_memos.evidence({'news': {'items': {code: [item]}}}, stock, day)]
                    if picked:
                        previous = reasons.read_day(data, day).get('news', {}).get('items', {}).get(code, [])
                        urls = {item['url'] for item in picked}
                        reasons.save_news(data, day, {code: picked + [item for item in previous if item.get('url') not in urls]})
                        report['added_evidence'] += 1
            except Exception as exc:
                report['failed'].append({'code': code, 'message': str(exc)[:200]})
            if done % 10 == 0 or done == len(jobs):
                print(json.dumps({'done': done, 'total': len(jobs), 'added_evidence': report['added_evidence'], 'failed': len(report['failed'])}), flush=True)
    target = data / 'hero4_daily_memo' / 'backfill_report.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--through', required=True)
    args = parser.parse_args()
    run(Path(__file__).resolve().parent / 'data', args.through)
