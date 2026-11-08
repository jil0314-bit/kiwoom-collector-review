"""Verified theme/industry and dated market-cap display for collector lists."""
import json
import os
import re
import threading
import time
from datetime import datetime

import archive
import chart_data
import investor_flows
import stock_sectors
import themes
import volume_surge
import volume_top
import amount_top
import watchlists
import recommendations
from kiwoom import DataError, Kiwoom, KST, code_of

LOCK = threading.Lock()
GUARD = threading.Lock()
LAST_SCAN = 0.0
STATE = {"busy": False, "pending": 0, "message": "대기"}
REQUEST_LOCK = threading.Lock()
REQUESTED = set()


def _add(stocks, row):
    if not isinstance(row, dict):
        return
    try:
        code = code_of(row.get("code", ""))
    except DataError:
        return
    stocks.setdefault(code, {"code": code, "name": row.get("name") or code})


def collect(data, day):
    """All saved stock lists for one date; no quote/order request here."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("날짜 형식 오류")
    stocks = {}
    with archive.LOCK:
        top = archive.metadata(archive.active(data, day))
    for row in top.get("stocks", []):
        _add(stocks, row)
    vol = volume_surge.metadata(data, day)
    for row in vol.get("stocks", []) + vol.get("tracked", []):
        _add(stocks, row)
    for module in (volume_top, amount_top, recommendations):
        for row in module.read(data, day).get('stocks', []):
            _add(stocks, row)
    thematic = themes.read_day(data, day) or {}
    for group in thematic.get("themes", []) + thematic.get("custom", []):
        for row in group.get("leaders", []) + group.get("candidates", []):
            _add(stocks, row)
        for code in group.get("member_codes", []):
            _add(stocks, {"code": code})
    flows = investor_flows.read_day(data, day) or {}
    for market in flows.get("markets", {}).values():
        for rows in market.get("rankings", {}).values():
            for row in rows:
                _add(stocks, row)
    return stocks, vol, thematic


def _caps_path(data):
    return data / "market_caps.json"


def _read_caps(data):
    path = _caps_path(data)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("items", {})


def _save_caps(data, items):
    path = _caps_path(data)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def view(data, day, extra=()):
    stocks, volume, thematic = collect(data, day)
    for code in extra:
        _add(stocks, {"code": code})
    with stock_sectors.LOCK:
        sectors = stock_sectors.read(data)
    with LOCK:
        caps = _read_caps(data)
        dated_path = data / 'stock_profiles' / (day + '.json')
        dated = json.loads(dated_path.read_text(encoding='utf-8')).get('profiles', {}) if dated_path.is_file() else {}
    profiles = {code: {"name": row["name"], "themes": [], "groups": [], "industry": None,
                       "market_cap": None, "cap_day": None} for code, row in stocks.items()}
    for code, row in sectors.items():
        if code in profiles and row.get("labels"):
            profiles[code]["industry"] = row["labels"][0]
            profiles[code]["industry_url"] = row.get("url")
    for group in thematic.get("themes", []) + thematic.get("custom", []):
        name = group.get("name")
        if not name:
            continue
        members = set(group.get("member_codes", []))
        members.update(row["code"] for row in group.get("leaders", []) if row.get("code"))
        for code in members:
            if code in profiles and name not in profiles[code]["themes"]:
                profiles[code]["themes"].append(name)
    if day == datetime.now(KST).date().isoformat():
        try:
            groups = watchlists.groups()
        except DataError:
            groups = []
        excluded = {6, 9, 10, 39, 43, 66, 98, 99}
        for group in groups:
            if group["number"] in excluded:
                continue
            for row in group["entries"]:
                code = row.get("code")
                if code in profiles and group["name"] not in profiles[code]["groups"]:
                    profiles[code]["groups"].append(group["name"])
    for row in volume.get("tracked", []) + volume.get("stocks", []):
        code = row.get("code")
        cap = row.get("market_cap")
        if code in profiles and isinstance(cap, (int, float)) and cap > 0:
            profiles[code].update(market_cap=cap, cap_day=day)
    for code, row in caps.items():
        if code in profiles and profiles[code]["market_cap"] is None:
            cap = row.get("market_cap")
            if isinstance(cap, (int, float)) and cap > 0:
                profiles[code].update(market_cap=cap, cap_day=row.get("day"))
    # Retain the recorded date's memberships/cap even after the current cache changes.
    for code, profile in profiles.items():
        previous = dated.get(code, {})
        if previous.get('cap_day') == day and profile.get('cap_day') != day:
            profile.update(market_cap=previous.get('market_cap'), cap_day=day)
        for field in ('themes', 'groups'):
            if not profile[field] and previous.get(field):
                profile[field] = previous[field]
    saved = {**dated, **profiles}
    # A later-date cap is a display reference only, never a historical-day snapshot.
    for code, profile in list(saved.items()):
        if profile.get('cap_day') and profile['cap_day'] != day:
            saved[code] = {**profile, 'market_cap': None, 'cap_day': None}
    with LOCK:
        dated_path.parent.mkdir(parents=True, exist_ok=True)
        blob = json.dumps({'day': day, 'profiles': saved}, ensure_ascii=False, indent=1)
        if not dated_path.is_file() or dated_path.read_text(encoding='utf-8') != blob:
            tmp = dated_path.with_suffix('.tmp')
            tmp.write_text(blob, encoding='utf-8')
            os.replace(tmp, dated_path)
    with REQUEST_LOCK:
        REQUESTED.update(code for code, profile in profiles.items()
                         if profile["market_cap"] is None or profile["industry"] is None)
    return {"day": day, "profiles": profiles, "state": dict(STATE)}


def tick(data, today=None, quote=None):
    """Slow background metadata fill; serializes with chart quotes, never sends orders."""
    global LAST_SCAN
    if time.monotonic() - LAST_SCAN < 60 or not GUARD.acquire(blocking=False):
        return False
    LAST_SCAN = time.monotonic()
    try:
        today = today or datetime.now(KST).date().isoformat()
        stocks, volume, _ = collect(data, today)
        with REQUEST_LOCK:
            for code in REQUESTED:
                stocks.setdefault(code, {"code": code, "name": code})
        stock_sectors.ensure(data, stocks.values())
        with LOCK:
            caps = _read_caps(data)
        for row in volume.get("tracked", []) + volume.get("stocks", []):
            cap = row.get("market_cap")
            if isinstance(cap, (int, float)) and cap > 0:
                caps[row["code"]] = {"market_cap": cap, "day": today}
        pending = [code for code in stocks if caps.get(code, {}).get("day") != today and
                   time.time() - caps.get(code, {}).get("attempt_epoch", 0) >= 300]
        if not pending:
            with LOCK:
                _save_caps(data, caps)
            GUARD.release()
            return False
        pending = pending[:50]
    except Exception:
        GUARD.release()
        raise

    def worker():
        STATE.update(busy=True, pending=len(pending), message="시가총액 확인 중")
        failures = 0
        try:
            for offset in range(0, len(pending), 10):
                batch = pending[offset:offset+10]
                try:
                    if quote is None:
                        with chart_data.LOCK:
                            chart_data.CLIENT = chart_data.CLIENT or Kiwoom()
                            rows = chart_data.CLIENT.quotes(batch)
                    else:
                        rows = quote(batch)
                    for code in batch:
                        row = rows.get(code, {})
                        cap = row.get("market_cap")
                        if row.get("date") == today.replace("-", "") and isinstance(cap, (int, float)) and cap > 0:
                            caps[code] = {"market_cap": cap, "day": today}
                        else:
                            failures += 1
                            caps[code] = {**caps.get(code, {}), "attempt_epoch": time.time()}
                except Exception:
                    failures += len(batch)
                    for code in batch:
                        caps[code] = {**caps.get(code, {}), "attempt_epoch": time.time()}
                with LOCK:
                    _save_caps(data, caps)
                STATE["pending"] -= len(batch)
                time.sleep(.35)
            STATE["message"] = "시가총액 확인 완료" if not failures else f"시가총액 {failures}종목 미확인 · 재시도 예정"
        except Exception:
            STATE["message"] = "시가총액 저장 실패 · 재시도 예정"
        finally:
            STATE.update(busy=False, pending=0)
            GUARD.release()
    threading.Thread(target=worker, daemon=True, name="stock-market-caps").start()
    return True
