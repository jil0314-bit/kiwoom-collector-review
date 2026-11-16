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

LONG_AVERAGES = (180, 240, 360, 480)
MINUTE_AVERAGES = (5, 10, 20, 60, 120) + LONG_AVERAGES
DATE_AVERAGES = (5, 10, 20, 30, 60, 120) + LONG_AVERAGES
PERIODS = dict.fromkeys(("minute", "minute3", "minute5"), MINUTE_AVERAGES)
PERIODS.update(dict.fromkeys(("day", "week", "month"), DATE_AVERAGES))
COLORS = {5: "#d28a16", 10: "#9a54d8", 20: "#109e9b", 30: "#ef6487",
          60: "#3778e6", 120: "#e57927", 180: "#b45309", 240: "#546380",
          360: "#0e7490", 480: "#9d174d"}
LOCK = threading.Lock()
CLIENT = None
LONG_RANGE = 480
DEFAULT_DATE_RANGE = 180


def chart_client():
    global CLIENT
    CLIENT = CLIENT or Kiwoom(timeout=5, attempts=2)
    return CLIENT


def read_cache(path, day):
    try:
        saved = json.loads(path.read_bytes())
        bars = saved["bars"]
        if (not bars or bars[-1]["ts"][:10] > day
                or not isinstance(saved.get("raw", {}), dict)):
            return None
        datetime.fromisoformat(saved["fetched_at"])
        return saved
    except (OSError, KeyError, IndexError, TypeError, ValueError):
        return None


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


def minute_record(record, raw, history=False):
    ordered = averages(minute_history(record, raw), PERIODS["minute"])
    lookup = {b["ts"]: b for b in ordered}
    bars = ordered[-LONG_RANGE:] if history else [lookup[b["ts"]] for b in record["bars"]]
    return {**record, "frame": "minute", "bars": bars,
            "chart_notice": "1분봉 종가 단순평균 · 이전 거래일의 저장 원본 포함 · 20·60선은 3배 굵기. 빈 분은 채우지 않으며 이력이 부족한 선은 표시하지 않습니다."}


def bucket_time(ts, minutes):
    dt = datetime.fromisoformat(ts)
    return dt.replace(minute=dt.minute-dt.minute % minutes, second=0).strftime('%Y-%m-%d %H:%M:%S')


def grouped_record(record, raw, minutes, history=False):
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
            'bars': ordered[-LONG_RANGE:] if history else [b for b in ordered if b['ts'] in visible],
            'chart_notice': f'{minutes}분봉 · 저장된 1분봉을 시계의 {minutes}분 구간으로 합산 · 시각은 구간 시작. '
                            f'이평선은 {minutes}분봉 종가의 단순평균(20·60선 3배 굵기). '
                            '빈 구간은 채우지 않습니다. 원본 분봉 누락·비거래를 구분할 수 없으며 마지막 구간은 일부만 수신됐을 수 있습니다.'}


def daily_record(record, cached, history=False):
    result = {**record, "frame": "day", "fetched_at": cached["fetched_at"],
              "bars": averages([dict(b) for b in cached["bars"]], PERIODS["day"])[-(LONG_RANGE if history else DEFAULT_DATE_RANGE):],
              "chart_notice": "일봉 · KRX+NXT 통합 · 비수정주가 · 종가 단순평균 · 20·60선 3배 굵기. 이력이 부족한 선은 표시하지 않습니다."}
    return mark_actual_session(result, result["bars"][-1]["ts"])


def mark_actual_session(record, actual_day):
    if actual_day != record["day"]:
        requested = record.get("requested_day", record["day"])
        record.update(day=actual_day, requested_day=requested)
        record["chart_notice"] = f"{requested} 거래 자료 없음 · {actual_day} 기준. " + record["chart_notice"]
    return record


def weekly_record(record, days, fetched_at, history=False):
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
    bars = averages(list(weeks.values()), PERIODS["week"])[-(LONG_RANGE if history else DEFAULT_DATE_RANGE):]
    result = {**record, "frame": "week", "bars": bars, "fetched_at": fetched_at,
            "chart_notice": "주봉 · 조회한 일봉을 월~일요일 단위로 합산 · 비수정주가 · 20·60주선 3배 굵기. "
                            "현재 주는 미완성일 수 있으며 이력이 부족한 선은 표시하지 않습니다. 조회 시각 "
                            + fetched_at[:19].replace("T", " ") + " KST."}
    return mark_actual_session(result, bars[-1]["end_ts"]) if bars else result


def monthly_record(record, cached, history=False):
    bars = averages([dict(bar) for bar in cached["bars"]], PERIODS["month"])
    result = {**record, "frame": "month", "fetched_at": cached["fetched_at"],
              "bars": bars[-(LONG_RANGE if history else DEFAULT_DATE_RANGE):],
              "chart_notice": "월봉 · KRX+NXT 통합 · 비수정주가 · 종가 단순평균 · 20·60선 3배 굵기. "
                              "선택 월은 기준일까지의 일봉 합산이며 이력이 부족한 선은 표시하지 않습니다."}
    return mark_actual_session(result, cached["raw"]["actual_day"])


def history_cache(data, day, code, directory, count, ttl=300):
    current = datetime.now(KST)
    path = data / directory / day / f"{code}.json"
    cached = read_cache(path, day)
    if cached:
        age = current.timestamp() - datetime.fromisoformat(cached["fetched_at"]).timestamp()
        final_fetch = cached["fetched_at"][:10] > day or cached["fetched_at"][11:16] >= "20:05"
        if (max(len(cached["bars"]), cached.get("requested_count", 0)) < count
                or not (age < ttl or (day < current.date().isoformat() and final_fetch))):
            cached = None
    if cached is None:
        client = chart_client()
        fetch = client.monthly_bars if directory == "monthly_history" else client.daily_bars
        bars, raw = fetch(code, day, count=count)
        cached = {"fetched_at": current.isoformat(timespec="seconds"), "bars": bars, "raw": raw,
                  "requested_count": count}
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(cached, ensure_ascii=False, indent=2).encode("utf-8")
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(content)
        os.replace(tmp, path)
        path.with_suffix(".sha256").write_text(hashlib.sha256(content).hexdigest(), encoding="ascii")
    return cached


def watchlist_minute(data, day, code, name, ttl=300, history_interval=0, allow_previous_session=False, history=False):
    current = datetime.now(KST)
    directory = f"chart_minute_history_{history_interval}" if history_interval else "watchlist_history"
    earlier_bars = max(MINUTE_AVERAGES) - 1 + (LONG_RANGE if history else 0) if history_interval else 0
    path = data / directory / day / f"{code}.json"
    cached = read_cache(path, day)
    if cached:
        age = current.timestamp() - datetime.fromisoformat(cached["fetched_at"]).timestamp()
        final_fetch = cached["fetched_at"][:10] > day or cached["fetched_at"][11:16] >= "20:05"
        same_session = cached["bars"][-1]["ts"][:10] == day
        if ((not same_session and (not allow_previous_session or not cached.get("previous_session_complete")))
                or cached.get("requested_earlier_bars", 0) < earlier_bars
                or not (age < ttl or (day < current.date().isoformat() and final_fetch))):
            cached = None
    if cached is None:
        kwargs = ({"earlier_bars": earlier_bars, "interval": history_interval}
                  if history_interval else {})
        bars, raw = chart_client().minute_bars(code, day, allow_previous_session=allow_previous_session, **kwargs)
        cached = {"fetched_at": current.isoformat(timespec="seconds"), "bars": bars, "raw": raw,
                  "previous_session_complete": allow_previous_session, "requested_earlier_bars": earlier_bars}
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(cached, ensure_ascii=False).encode("utf-8")
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(content)
        os.replace(tmp, path)
        path.with_suffix(".sha256").write_text(hashlib.sha256(content).hexdigest(), encoding="ascii")
    actual_day = cached["bars"][-1]["ts"][:10]
    record = {"day": actual_day, "kind": "preview" if actual_day == current.date().isoformat() else "final",
              "source": "watchlist", "stock": {"code": code, "name": name},
              "bars": cached["bars"], "fetched_at": cached["fetched_at"]}
    if actual_day != day:
        record["requested_day"] = day
    return record, cached["raw"]


def minute_view(record, raw, frame, history=False):
    if frame == "minute":
        result = minute_record(record, raw, history)
    else:
        result = grouped_record(record, raw, int(frame[-1]), history)
    if requested := record.get("requested_day"):
        result["chart_notice"] = (f"{requested} 분봉 없음 · {record['day']} 최근 거래 자료 표시. "
                                  + result["chart_notice"])
    return result


def archived_minutes(data, day, code, frame, record, raw, history):
    available = minute_view(record, raw, frame, history)
    if available["bars"][0]["ma480"] is not None and (not history or len(available["bars"]) >= LONG_RANGE):
        return available
    interval = 1 if frame == "minute" else int(frame[-1])
    # Keep the saved session untouched. Add only preceding trading dates.
    with LOCK:
        stock = record.get("stock", {})
        try:
            _, earlier = watchlist_minute(data, day, code, stock.get("name") or code,
                                         history_interval=interval, history=history)
        except DataError as exc:
            available["chart_notice"] += f" 추가 분봉 조회 실패 · {exc}"
            return available
    boundary = day.replace("-", "")
    raw_pages = raw.get("pages", [])
    saved_times = {row["cntr_tm"] for page in raw_pages for row in page.get("stk_min_pole_chart_qry", [])}
    pages = [{"stk_min_pole_chart_qry": [row for row in page.get("stk_min_pole_chart_qry", [])
                                       if row["cntr_tm"][:8] < boundary and row["cntr_tm"] not in saved_times]}
             for page in earlier.get("pages", [])]
    result = minute_view(record, {"pages": pages + raw_pages}, frame, history)
    result["chart_notice"] += " 선택 날짜의 저장 봉을 기준으로 이전 거래일 이력을 표시합니다."
    return result


def history_view(data, day, code, frame, record, history, ttl=300):
    count = (LONG_RANGE if history else DEFAULT_DATE_RANGE) + max(DATE_AVERAGES) - 1
    if frame == "month":
        cached = history_cache(data, day, code, "monthly_history", count, ttl)
        return monthly_record(record, cached, history)
    if frame == "week":
        # Fetch whole weeks plus one boundary week to keep incomplete warmup data out.
        cached = history_cache(data, day, code, "weekly_history", (count + 1) * 5, ttl)
        return weekly_record(record, cached["bars"], cached["fetched_at"], history)
    cached = history_cache(data, day, code, "chart_history", count, ttl)
    return daily_record(record, cached, history)


def load(data, day, code, frame, revision=None, source="ranking", name=None, live=False, history=False):
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
        try:
            result = load_live(data, current_day, code, frame, name or code, history=history)
        except DataError as exc:
            # A closed session may have no minutes. Keep the selected archive visible,
            # with its actual date, rather than describing it as live/today's data.
            if not frame.startswith("minute") or day >= current_day or str(exc) != "해당 날짜 08:00~20:00 분봉 없음":
                raise
            try:
                result = load(data, day, code, frame, source=source, name=name, live=False, history=history)
                if not result.get("bars"):
                    raise exc
            except (DataError, OSError, KeyError, ValueError):
                raise exc
            result["live"] = False
            result["live_fallback"] = True
            result["requested_live_day"] = current_day
            result["chart_notice"] += f" 현재 조회일 {current_day} 분봉 없음 · {day} 저장 분봉 표시."
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
        if frame.startswith("minute"):
            return archived_minutes(data, day, code, frame, record, raw, history)
    elif source == "watchlist":
        record = {"day": day, "kind": "preview" if day == datetime.now(KST).date().isoformat() else "final",
                  "source": "watchlist", "stock": {"code": code, "name": name or code}}
        if frame in ("minute", "minute3", "minute5"):
            interval = 1 if frame == "minute" else int(frame[-1])
            with LOCK:
                record, raw = watchlist_minute(data, day, code, name or code, history_interval=interval,
                                              allow_previous_session=True, history=history)
            return minute_view(record, raw, frame, history)
    else:
        raise DataError("차트 출처 오류")
    # Separate cache: never add/delete files in the committed minute snapshot.
    with LOCK:
        return history_view(data, day, code, frame, record, history)


def load_live(data, day, code, frame, name, history=False):
    """Read current chart into a separate cache; never replace ranked archives."""
    with LOCK:
        if frame in ("minute", "minute3", "minute5"):
            interval = 1 if frame == "minute" else int(frame[-1])
            record, raw = watchlist_minute(data, day, code, name, ttl=15, allow_previous_session=True,
                                          history_interval=interval, history=history)
            result = minute_view(record, raw, frame, history)
        else:
            record = {"day": day, "kind": "preview", "stock": {"code": code, "name": name}}
            result = history_view(data, day, code, frame, record, history, ttl=15)
    with LOCK:
        try:
            result["quote"] = chart_client().quote(code)
        except DataError:
            result["chart_notice"] += " 현재가 별도 조회 실패."
    result["live"] = "requested_day" not in result
    result["source"] = "live"
    result["chart_notice"] += (" 현재 조회 · 15초 간격 갱신 · 마지막 봉은 진행 중일 수 있습니다." if result["live"] else "")
    result["chart_notice"] += " 조회 " + result["fetched_at"][:19].replace("T", " ") + " KST."
    return result


QUOTE_CACHE = {}

def current_quotes(codes):
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
            result.update(chart_client().quotes(key[offset:offset + 10]))
        time.sleep(0.01)
    with LOCK:
        QUOTE_CACHE.clear()
        QUOTE_CACHE[key] = (current, result)
        return result
