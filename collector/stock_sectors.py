"""Background business-sector labels. Never uses the quote/order client."""
import html
import json
import os
import re
import threading
import time
import urllib.request
from datetime import datetime

from kiwoom import KST, code_of

LOCK = threading.Lock()
GUARD = threading.Lock()
STATE = {"busy": False, "pending": 0, "message": "대기"}
LAST_SCAN = 0.0


def read(data):
    result = {}
    for name in ("stock_sectors.json", "theme_classifications.json"):
        path = data / name
        if path.is_file():
            result.update(json.loads(path.read_text(encoding="utf-8")).get("items", {}))
    return result


def parse_sector(page):
    """Only store the short industry label, not analyst text or a guessed theme."""
    match = re.search(r'WI26\s*:\s*([^<\r\n]+)', page)
    if not match:
        return None
    label = html.unescape(match.group(1)).strip()
    if not label or label in ("-", "N/A", "업종 미분류") or len(label) > 60:
        return None
    return label


def fetch_sector(symbol):
    url = "https://comp.wisereport.co.kr/company/c1010001.aspx?cmp_cd=" + code_of(symbol)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as response:
        page = response.read(2_000_000).decode("utf-8", errors="replace")
    label = parse_sector(page)
    if not label:
        raise ValueError("기업정보에서 업종 미확인")
    return {"labels": [label], "url": url, "kind": "business",
            "checked_at": datetime.now(KST).date().isoformat(), "checked_epoch": time.time()}


def _save(data, entries):
    path = data / "stock_sectors.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"items": entries}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def ensure(data, stocks, fetch=fetch_sector):
    if not GUARD.acquire(blocking=False):
        return False
    try:
        with LOCK:
            cached = read(data)
        pending = []
        seen = set()
        for stock in stocks:
            symbol = code_of(stock["code"])
            if symbol in seen:
                continue
            seen.add(symbol)
            old = cached.get(symbol, {})
            # Curated labels stay authoritative. Successful automatic labels refresh weekly.
            if old.get("labels") and (not old.get("checked_epoch") or time.time()-old["checked_epoch"] < 7*86400):
                continue
            if time.time()-old.get("attempt_epoch", 0) < 86400:
                continue
            pending.append({"code": symbol, "name": stock.get("name", symbol)})
        if not pending:
            GUARD.release()
            return False
    except Exception:
        GUARD.release()
        raise

    def worker():
        STATE.update(busy=True, pending=len(pending), message="업종 자동 확인 중")
        try:
            path = data / "stock_sectors.json"
            entries = json.loads(path.read_text(encoding="utf-8")).get("items", {}) if path.is_file() else {}
            failures = 0
            for stock in pending:
                symbol = stock["code"]
                try:
                    item = {**fetch(symbol), "name": stock["name"]}
                except Exception:
                    failures += 1
                    item = {**entries.get(symbol, {}), "name": stock["name"],
                            "attempt_epoch": time.time(), "error": "기업정보 접근 실패 또는 업종 미확인"}
                entries[symbol] = item
                with LOCK:
                    _save(data, entries)
                STATE["pending"] -= 1
                time.sleep(.35)
            STATE["message"] = "업종 확인 완료" if not failures else f"업종 {failures}종목 미확인 · 다음 날 재시도"
        except Exception:
            STATE["message"] = "업종 분류 저장 실패 · 다음 확인 때 재시도"
        finally:
            STATE.update(busy=False, pending=0)
            GUARD.release()
    threading.Thread(target=worker, daemon=True, name="stock-sector-labels").start()
    return True


def tick(data):
    """Scan newly committed daily rankings without waiting on network work."""
    global LAST_SCAN
    if time.monotonic()-LAST_SCAN < 60:
        return
    LAST_SCAN = time.monotonic()
    import archive
    days = sorted(p.name for p in data.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name))
    stocks = {}
    with archive.LOCK:
        for day in reversed(days):
            for stock in archive.metadata(archive.active(data, day)).get("stocks", []):
                stocks.setdefault(stock["code"], stock)
    ensure(data, stocks.values())
