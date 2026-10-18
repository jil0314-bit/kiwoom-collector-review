"""Chart-only history and causal averages. Source minute archives stay immutable."""
import gzip
import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta

import archive
from kiwoom import DataError, Kiwoom, KST, parse_bar

PERIODS = {"minute": (5, 10, 20, 60, 120, 240), "day": (5, 10, 20, 30, 60, 120),
           "week": (5, 10, 20, 30, 60, 120)}
PERIODS.update({"minute3": PERIODS["minute"], "minute5": PERIODS["minute"]})
COLORS = {5: "#d28a16", 10: "#9a54d8", 20: "#109e9b", 30: "#ef6487",
          60: "#3778e6", 120: "#e57927", 240: "#546380"}
LOCK = threading.Lock()
CLIENT = None


def averages(bars, periods):
    prefix = [0]
    for b in bars:
        prefix.append(prefix[-1] + b["close"])
    for i, b in enumerate(bars, 1):
        for n in periods:
            b[f"ma{n}"] = (prefix[i] - prefix[i-n]) / n if i >= n else None
    return bars


def minute_history(record, raw):
    rows = {}
    for page in raw.get("pages", []):
        for item in page.get("stk_min_pole_chart_qry", []):
            b = parse_bar(item)
            if b["ts"] <= record["bars"][-1]["ts"]:
                if b["ts"] in rows and rows[b["ts"]] != b:
                    raise DataError("저장 원본 분봉 값 충돌")
                rows[b["ts"]] = b
    # The saved record is authoritative; the raw pages supply earlier history.
    for b in record["bars"]:
        rows[b["ts"]] = {k: b[k] for k in ("ts", "open", "high", "low", "close", "volume")}
    return sorted(rows.values(), key=lambda b: b["ts"])


def minute_record(record, raw):
    ordered = averages(minute_history(record, raw), PERIODS["minute"])
    lookup = {b["ts"]: b for b in ordered}
    bars = [lookup[b["ts"]] for b in record["bars"]]
    return {**record, "frame": "minute", "bars": bars,
            "chart_notice": "1분봉 종가 단순평균 · 이전 거래일의 저장 원본 포함 · 20·60선은 3배 굵기. 빈 분은 채우지 않으며 이력이 부족한 선은 표시하지 않습니다."}


def bucket_time(ts, minutes):
    dt = datetime.fromisoformat(ts)
    return dt.replace(minute=dt.minute-dt.minute % minutes, second=0).strftime('%Y-%m-%d %H:%M:%S')


def grouped_record(record, raw, minutes):
    """Aggregate chronological stored minutes; never bridge dates or fill gaps."""
    groups = {}
    for b in minute_history(record, raw):
        key = bucket_time(b['ts'], minutes)
        if key not in groups:
            end = datetime.fromisoformat(key) + timedelta(minutes=minutes)
            groups[key] = {'ts': key, 'end_ts': end.strftime('%Y-%m-%d %H:%M:%S'),
                           **{k: b[k] for k in ('open', 'high', 'low', 'close', 'volume')},
                           'source_count': 1}
        else:
            g = groups[key]
            g['high'] = max(g['high'], b['high'])
            g['low'] = min(g['low'], b['low'])
            g['close'] = b['close']
            g['volume'] += b['volume']
            g['source_count'] += 1
    visible = {bucket_time(b['ts'], minutes) for b in record['bars']}
    ordered = averages(list(groups.values()), PERIODS['minute'])
    return {**record, 'frame': f'minute{minutes}', 'interval_minutes': minutes,
            'bars': [b for b in ordered if b['ts'] in visible],
            'chart_notice': f'{minutes}분봉 · 저장된 1분봉을 시계의 {minutes}분 구간으로 합산 · 시각은 구간 시작. '
                            f'이평선은 {minutes}분봉 종가의 5·10·20·60·120·240봉 평균(20·60선 3배 굵기). '
                            '빈 구간은 채우지 않습니다. 원본 분봉 누락·비거래를 구분할 수 없으며 마지막 구간은 일부만 수신됐을 수 있습니다.'}


def weekly_record(record, days, fetched_at):
    weeks = {}
    for bar in days:
        date = datetime.fromisoformat(bar["ts"])
        start = (date - timedelta(days=date.weekday())).date().isoformat()
        if start not in weeks:
            weeks[start] = {"ts": start, "end_ts": bar["ts"],
                            **{key: bar[key] for key in ("open", "high", "low", "close", "volume")}}
        else:
            week = weeks[start]
            week["end_ts"] = bar["ts"]
            week["high"] = max(week["high"], bar["high"])
            week["low"] = min(week["low"], bar["low"])
            week["close"] = bar["close"]
            week["volume"] += bar["volume"]
    bars = averages(list(weeks.values()), PERIODS["week"])[-180:]
    return {**record, "frame": "week", "bars": bars, "fetched_at": fetched_at,
            "chart_notice": "주봉 · 조회한 일봉을 월~일요일 단위로 합산 · 비수정주가 · 20·60주선 3배 굵기. "
                            "현재 주는 미완성일 수 있으며 이력이 부족한 선은 표시하지 않습니다. 조회 시각 "
                            + fetched_at[:19].replace("T", " ") + " KST."}


def history_cache(data, day, code, directory, count, ttl=300):
    global CLIENT
    current = datetime.now(KST)
    path = data / directory / day / f"{code}.json"
    cached = None
    if path.is_file():
        cached = json.loads(path.read_text(encoding="utf-8"))
        age = current.timestamp() - datetime.fromisoformat(cached["fetched_at"]).timestamp()
        final_fetch = cached["fetched_at"][:10] > day or cached["fetched_at"][11:16] >= "20:05"
        if not (age < ttl or (day < current.date().isoformat() and final_fetch)):
            cached = None
    if cached is None:
        CLIENT = CLIENT or Kiwoom()
        bars, raw = CLIENT.daily_bars(code, day, count=count)
        cached = {"fetched_at": current.isoformat(timespec="seconds"), "bars": bars, "raw": raw}
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(cached, ensure_ascii=False, indent=2).encode("utf-8")
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(content)
        os.replace(tmp, path)
        path.with_suffix(".sha256").write_text(hashlib.sha256(content).hexdigest(), encoding="ascii")
    return cached


def watchlist_minute(data, day, code, name, ttl=300):
    global CLIENT
    current = datetime.now(KST)
    path = data / "watchlist_history" / day / f"{code}.json"
    cached = None
    if path.is_file():
        cached = json.loads(path.read_text(encoding="utf-8"))
        age = current.timestamp() - datetime.fromisoformat(cached["fetched_at"]).timestamp()
        final_fetch = cached["fetched_at"][:10] > day or cached["fetched_at"][11:16] >= "20:05"
        if not (age < ttl or (day < current.date().isoformat() and final_fetch)):
            cached = None
    if cached is None:
        CLIENT = CLIENT or Kiwoom()
        bars, raw = CLIENT.minute_bars(code, day)
        cached = {"fetched_at": current.isoformat(timespec="seconds"), "bars": bars, "raw": raw}
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(cached, ensure_ascii=False).encode("utf-8")
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(content)
        os.replace(tmp, path)
        path.with_suffix(".sha256").write_text(hashlib.sha256(content).hexdigest(), encoding="ascii")
    record = {"day": day, "kind": "preview" if day == current.date().isoformat() else "final",
              "source": "watchlist", "stock": {"code": code, "name": name},
              "bars": cached["bars"], "fetched_at": cached["fetched_at"]}
    return record, cached["raw"]


def load(data, day, code, frame, revision=None, source="ranking", name=None, live=False):
    if frame not in PERIODS:
        raise DataError("차트 종류 오류")
    if live:
        current_day = datetime.now(KST).date().isoformat()
        if source == "ranking":
            with archive.LOCK:
                payload, _ = archive.payload(data, day, code)
            if not payload:
                raise DataError("저장된 종목 자료가 없습니다.")
            name = json.loads(payload)["stock"]["name"]
        result = load_live(data, current_day, code, frame, name or code)
        result["archive_day"] = day
        return result
    if source == "ranking":
        with archive.LOCK:
            payload, stale = archive.payload(data, day, code, revision=revision)
            if stale:
                raise DataError("최신 자료로 교체되었습니다. 화면 갱신 후 다시 선택하세요.")
            if not payload:
                raise DataError("저장된 종목 자료가 없습니다.")
            record = json.loads(payload)
            if frame in ("minute", "minute3", "minute5"):
                path = archive.active(data, day) / f"{code}.raw.json.gz"
                raw = json.loads(gzip.decompress(path.read_bytes())) if path.is_file() else {}
                return minute_record(record, raw) if frame == 'minute' else grouped_record(record, raw, int(frame[-1]))
    elif source == "watchlist":
        record = {"day": day, "kind": "preview" if day == datetime.now(KST).date().isoformat() else "final",
                  "source": "watchlist", "stock": {"code": code, "name": name or code}}
        if frame in ("minute", "minute3", "minute5"):
            with LOCK:
                record, raw = watchlist_minute(data, day, code, name or code)
            return minute_record(record, raw) if frame == "minute" else grouped_record(record, raw, int(frame[-1]))
    else:
        raise DataError("차트 출처 오류")
    # Separate cache: never add/delete files in the committed minute snapshot.
    with LOCK:
        cached = history_cache(data, day, code, "weekly_history" if frame == "week" else "chart_history",
                               700 if frame == "week" else 300)
        if frame == "week":
            return weekly_record(record, cached["bars"], cached["fetched_at"])
        bars = averages([dict(b) for b in cached["bars"]], PERIODS["day"])[-180:]
        return {**record, "frame": "day", "bars": bars, "fetched_at": cached["fetched_at"],
                "chart_notice": "일봉 · KRX+NXT 통합 · 비수정주가 · 최대 최근 180거래일 표시. 20·60일선은 3배 굵기. 120일 미만 이력은 해당 선 미표시. 조회 시각 " + cached["fetched_at"][:19].replace("T", " ") + " KST. 일봉은 별도 조회 자료이며 과거 장중 분봉 저장 시점과 다를 수 있습니다."}


def load_live(data, day, code, frame, name):
    """Read current chart into a separate cache; never replace ranked archives."""
    with LOCK:
        if frame in ("minute", "minute3", "minute5"):
            record, raw = watchlist_minute(data, day, code, name, ttl=15)
            result = minute_record(record, raw) if frame == "minute" else grouped_record(record, raw, int(frame[-1]))
        else:
            cached = history_cache(data, day, code, "weekly_history" if frame == "week" else "chart_history",
                                   700 if frame == "week" else 300, ttl=15)
            record = {"day": day, "kind": "preview", "stock": {"code": code, "name": name}}
            result = weekly_record(record, cached["bars"], cached["fetched_at"]) if frame == "week" else {
                **record, "frame": "day", "bars": averages([dict(b) for b in cached["bars"]], PERIODS["day"])[-180:],
                "fetched_at": cached["fetched_at"], "chart_notice": "일봉 · KRX+NXT 통합 · 비수정주가."}
    with LOCK:
        global CLIENT
        CLIENT = CLIENT or Kiwoom()
        result["quote"] = CLIENT.quote(code)
    result["live"] = True
    result["source"] = "live"
    result["chart_notice"] += " 현재 조회 · 15초 간격 갱신 · 마지막 봉은 진행 중일 수 있습니다. 조회 " + result["fetched_at"][:19].replace("T", " ") + " KST."
    return result


QUOTE_CACHE = {}

def current_quotes(codes):
    global CLIENT
    key = tuple(sorted(set(codes)))
    if not key or len(key) > 100:
        raise DataError("현재가 종목 수 오류")
    with LOCK:
        cached = QUOTE_CACHE.get(key)
        current = datetime.now(KST).timestamp()
        if cached and current - cached[0] < 15:
            return cached[1]
    result = {}
    # Let a selected chart acquire the client between quote batches.
    # Preserve the same client's rate limit and token; do not create competitors.
    for offset in range(0, len(key), 10):
        with LOCK:
            CLIENT = CLIENT or Kiwoom()
            result.update(CLIENT.quotes(key[offset:offset + 10]))
        time.sleep(0.01)
    with LOCK:
        QUOTE_CACHE.clear()
        QUOTE_CACHE[key] = (current, result)
        return result
