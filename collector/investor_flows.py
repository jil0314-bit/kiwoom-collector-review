"""Read-only Hero4 0785 net-buy rankings; isolated daily, atomic archive."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from kiwoom import DataError, Kiwoom, KST, code_of

INTERVAL = 600
FINAL_TIME = "20:05"
LOCK = threading.RLock()
RUN = threading.Lock()
STATE = {"busy": False, "message": "평일 09:10부터 자동 수집", "day": None}
PREFIXES = {"foreign": "for_netprps", "institution": "orgn_netprps"}


def valid_day(day):
    if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("날짜 형식 오류")
    datetime.strptime(day, "%Y-%m-%d")
    return day


def root(data):
    return Path(data) / "investor_flows"


def load(path, fallback=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else fallback


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def digest(doc):
    body = {k: v for k, v in doc.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read_day(data, day):
    valid_day(day)
    with LOCK:
        doc = load(root(data) / (day + ".json"))
    if doc and (doc.get("day") != day or doc.get("sha256") != digest(doc)):
        raise DataError("외국인·기관 저장 자료 해시 또는 날짜 불일치")
    return doc


def days(data):
    return sorted((p.stem for p in root(data).glob("????-??-??.json")
                   if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem)), reverse=True)


def read_period(data, start, end):
    valid_day(start)
    valid_day(end)
    if start > end:
        raise ValueError("기간 순서 오류")
    with LOCK:
        doc = load(root(data) / "periods" / (start + "_" + end + ".json"))
    if doc and (doc.get("period_start") != start or doc.get("period_end") != end
                or doc.get("kind") != "period" or doc.get("sha256") != digest(doc)):
        raise DataError("외국인·기관 기간 자료 해시 또는 기간 불일치")
    return doc


def periods(data):
    result = []
    for path in sorted((root(data) / "periods").glob("????-??-??_????-??-??.json")):
        start, end = path.stem.split("_")
        doc = read_period(data, start, end)
        if doc:
            result.append({"start": start, "end": end})
    return result


def display_rows(doc, key, market=None):
    period = doc.get("kind") == "period"
    rankings = doc.get("markets", {}).get(market, {}).get("rankings", {}) if market else doc["rankings"]
    return sorted((row for row in rankings.get(key, []) if row["rank"] <= (30 if period else 20)),
                  key=lambda row: row["rank"])


def period_document(records, start, end, coverage, fetched_at):
    """Rank complete per-symbol period totals, never a sum of daily top lists.

    Input amounts are signed ka10061 million-KRW integers. Quantity was not
    requested in this backfill and must remain UNKNOWN, not an estimated value.
    """
    valid_day(start)
    valid_day(end)
    if start > end or coverage.get("failed_count") != 0:
        raise DataError("기간 또는 수집 실패 범위 오류")
    if coverage.get("target_count") != len(records) or coverage.get("saved_count") != len(records):
        raise DataError("기간 수집 대상과 성공 자료 수 불일치")
    codes = set()
    for record in records:
        code = code_of(record["stock"]["code"])
        if code != record["stock"]["code"] or code in codes:
            raise DataError("기간 종목코드 중복 또는 형식 오류")
        codes.add(code)
        if any(type(record["million_krw"].get(key)) is not int for key in PREFIXES):
            raise DataError("기간 순매수 금액 누락 또는 단위 형식 오류")
        for key, field in (("foreign", "frgnr_invsr"), ("institution", "orgn")):
            text = str(record["raw"].get(field, "")).replace(",", "").strip()
            if not re.fullmatch(r"(?:\+|-{1,2})?\d+", text):
                raise DataError("기간 원본 금액 형식 오류")
            amount = -int(text.lstrip("-")) if text.startswith("-") else int(text)
            if amount != record["million_krw"][key]:
                raise DataError("기간 원본과 정규화 금액 불일치")
        request = record["request"]
        if request != {"stk_cd": code + "_AL", "strt_dt": start.replace("-", ""),
                       "end_dt": end.replace("-", ""), "amt_qty_tp": "1", "trde_tp": "0", "unit_tp": "1"}:
            raise DataError("기간 자료 요청 조건 불일치")
    rankings = {}
    for key in PREFIXES:
        ordered = sorted(records, key=lambda row: (-row["million_krw"][key], row["stock"]["code"]))[:30]
        if len(ordered) != 30 or ordered[-1]["million_krw"][key] <= 0:
            raise DataError("기간 양수 순매수 TOP 30 자료 부족")
        rankings[key] = [{"rank": rank, "code": row["stock"]["code"], "name": row["stock"]["name"],
                          "net_amount_10m_krw": row["million_krw"][key] / 10,
                          "net_quantity_1000_shares": None} for rank, row in enumerate(ordered, 1)]
    doc = {"schema": 1, "kind": "period", "period_start": start, "period_end": end,
            "api_id": "ka10061", "market": "KRX+NXT", "basis": "net_buy_amount",
            "source_date": "UNKNOWN", "source_date_note": "기간은 요청값이며 API 원본 기준일은 미제공입니다.",
            "fetched_at": fetched_at, "units": {"amount": "천만원", "quantity": "천주"},
            "coverage": coverage, "rankings": rankings,
            "raw": {"source_amount_unit": "백만원", "source_quantity_collected": False, "records": records}}
    if any(row["stock"].get("market_code") in ("001", "101") for row in records):
        doc["markets"] = {}
        for market, label in (("001", "코스피"), ("101", "코스닥")):
            subset = [row for row in records if row["stock"].get("market_code") == market]
            market_rankings = {}
            for key in PREFIXES:
                ordered = sorted(subset, key=lambda r: (-r["million_krw"][key], r["stock"]["code"]))[:30]
                if len(ordered) != 30 or ordered[-1]["million_krw"][key] <= 0:
                    raise DataError("시장별 기간 TOP 30 자료 부족")
                market_rankings[key] = [{"rank": rank, "code": row["stock"]["code"], "name": row["stock"]["name"],
                    "net_amount_10m_krw": row["million_krw"][key] / 10, "net_quantity_1000_shares": None}
                    for rank, row in enumerate(ordered, 1)]
            doc["markets"][market] = {"name": label, "rankings": market_rankings, "target_count": len(subset)}
    return doc


def enabled(data):
    return bool(load(root(data) / "control.json", {}).get("enabled", True))


def set_enabled(data, value):
    if not isinstance(value, bool):
        raise ValueError("자동 수집 설정 오류")
    with LOCK:
        write(root(data) / "control.json", {"enabled": value})


def signed_int(value):
    # Never replace a missing value with zero or erase its sign.
    if value is None or str(value).strip() in ("", "--", "-"):
        return None
    text = str(value).replace(",", "").strip()
    if not re.fullmatch(r"[+-]?\d+", text):
        raise DataError("외국인·기관 응답 숫자 형식 오류")
    return int(text)


def fetch(api, day, market="000"):
    """Spec ka90009, verified official example; no kwcli dependency added."""
    valid_day(day)
    if market not in ("000", "001", "101"):
        raise ValueError("시장 구분 오류")
    body = {"mrkt_tp": market, "amt_qty_tp": "1", "qry_dt_tp": "1",
            "date": day.replace("-", ""), "stex_tp": "3"}
    cursor, seen, pages = "", set(), []
    result = {key: {} for key in PREFIXES}
    for _ in range(30):
        response, headers = api.request("ka90009", body, cursor)
        if response.get("return_code", 0) not in (0, "0"):
            raise DataError("외국인·기관 조회 응답 실패")
        rows = response.get("frgnr_orgn_trde_upper")
        if not isinstance(rows, list):
            raise DataError("외국인·기관 목록 누락")
        # Only endpoint market fields enter the archive, never tokens/headers.
        raw_rows = []
        for row in rows:
            if not isinstance(row, dict):
                raise DataError("외국인·기관 행 형식 오류")
            raw_rows.append({k: v for k, v in row.items() if any(
                k.startswith(prefix) for prefix in ("for_netprps_", "orgn_netprps_",
                                                   "for_netslmt_", "orgn_netslmt_"))})
            for investor, prefix in PREFIXES.items():
                value = row.get(prefix + "_stk_cd")
                if value is None or not str(value).strip():
                    continue
                code = code_of(value)
                amount = signed_int(row.get(prefix + "_amt"))
                quantity = signed_int(row.get(prefix + "_qty"))
                record = {"code": code, "name": str(row.get(prefix + "_stk_nm") or code),
                          "net_amount_10m_krw": amount, "net_quantity_1000_shares": quantity}
                prior = result[investor].get(code)
                if prior is not None and prior != record:
                    raise DataError("외국인·기관 중복 종목 수치 충돌")
                result[investor][code] = record
        pages.append(raw_rows)
        headers = {k.lower(): v for k, v in headers.items()}
        if headers.get("cont-yn") != "Y":
            break
        cursor = str(headers.get("next-key") or "")
        if not cursor or cursor in seen:
            raise DataError("외국인·기관 연속조회 키 누락·반복")
        seen.add(cursor)
    else:
        raise DataError("외국인·기관 연속조회 한도 초과")
    if not any(result.values()):
        raise DataError("외국인·기관 응답 없음: 이전 자료 유지")
    normalized = {}
    for key, values in result.items():
        normalized[key] = list(values.values())  # API 금액순; 수치 미제공도 순서를 보존한다.
        for rank, record in enumerate(normalized[key], 1):
            record["rank"] = rank
    return normalized, {"request": body, "pages": pages}


def refresh(data, day, api=None, clock=None):
    clock = clock or (lambda: datetime.now(KST))
    current = clock()
    if valid_day(day) != current.date().isoformat() or current.weekday() >= 5:
        raise DataError("외국인·기관 수집은 오늘 평일만 가능")
    api = api or Kiwoom()
    # Ranking API does not return a source date. Reject non-trading days using
    # dated daily-bar evidence, without pretending that it proves ranking date.
    bars, _ = api.daily_bars("005930", day, count=3)
    if not any(bar.get("ts") == day and bar.get("volume", 0) > 0 for bar in bars):
        raise DataError("당일 거래일 증거 없음: 휴장·미제공 가능, 이전 자료 유지")
    rankings, raw = fetch(api, day)
    markets = {}
    for market, label in (("001", "코스피"), ("101", "코스닥")):
        market_rankings, market_raw = fetch(api, day, market)
        if any(len(rows) < 20 for rows in market_rankings.values()):
            raise DataError("시장별 일별 TOP 20 자료 부족")
        markets[market] = {"name": label, "rankings": market_rankings}
        raw.setdefault("markets", {})[market] = market_raw
    finished = clock()
    if finished.date().isoformat() != day:
        raise DataError("외국인·기관 조회 도중 날짜 변경: 이전 자료 유지")
    doc = {"schema": 1, "day": day, "api_id": "ka90009", "hero4_screen": "0785",
           "market": "KRX+NXT", "basis": "net_buy_amount", "source_date": "UNKNOWN",
           "source_date_note": "조회 날짜는 요청값입니다. API 응답에 기준 날짜가 없습니다.",
           "trading_day_evidence": {"code": "005930", "day": day},
           "requested_at": current.isoformat(timespec="seconds"),
           "fetched_at": finished.isoformat(timespec="seconds"),
           "after_close_refresh": current.strftime("%H:%M") >= FINAL_TIME,
           "units": {"amount": "천만원", "quantity": "천주"},
           "rankings": rankings, "markets": markets, "raw": raw}
    doc["sha256"] = digest(doc)
    with LOCK:
        write(root(data) / (day + ".json"), doc)
    return doc


def csv_bytes(doc):
    out = io.StringIO(newline="")
    fields = ["day", "period_start", "period_end", "fetched_at", "market", "investor", "rank", "code", "name",
              "net_amount_10m_krw", "net_quantity_1000_shares", "source_date"]
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for market in doc.get("markets", {}) or [None]:
      for key in doc["rankings"]:
        for row in display_rows(doc, key, market):
            # Spreadsheet formula injection from market names is not executable.
            safe = dict(row)
            for field in ("code", "name"):
                if safe[field].startswith(("=", "+", "-", "@", "\t", "\r")):
                    safe[field] = "'" + safe[field]
            writer.writerow({"day": doc.get("day", ""), "period_start": doc.get("period_start", ""),
                             "period_end": doc.get("period_end", ""), "fetched_at": doc["fetched_at"],
                             "market": market or "UNKNOWN", "investor": key, "source_date": doc["source_date"], **safe})
    return out.getvalue().encode("utf-8-sig")


def due(data, current, manual=False):
    hhmm = current.strftime("%H:%M")
    if current.weekday() >= 5 or hhmm < "09:10":
        return False
    if manual:
        return True
    if not enabled(data):
        return False
    day = current.date().isoformat()
    journal = load(root(data) / "schedule.json", {})
    if journal.get("day") != day:
        journal = {}
    last = journal.get("last_start_epoch", 0)
    if hhmm >= FINAL_TIME:
        doc = read_day(data, day)
        return not (doc and doc.get("after_close_refresh")) and (
            journal.get("final_attempts", 0) < 3 and current.timestamp() - journal.get("last_final_epoch", 0) >= 900)
    return hhmm < "20:00" and current.timestamp() - last >= INTERVAL


def start(data, coordinator, manual=False, current=None):
    current = current or datetime.now(KST)
    if not RUN.acquire(blocking=False):
        return "running"
    acquired = False
    try:
        if not due(data, current, manual):
            RUN.release()
            return "waiting"
        acquired = coordinator.acquire(blocking=False)
        if not acquired:
            RUN.release()
            return "collector_busy"
        day = current.date().isoformat()
        journal = load(root(data) / "schedule.json", {})
        if journal.get("day") != day:
            journal = {"day": day}
        journal["last_start_epoch"] = current.timestamp()
        if current.strftime("%H:%M") >= FINAL_TIME:
            journal["final_attempts"] = journal.get("final_attempts", 0) + 1
            journal["last_final_epoch"] = current.timestamp()
        write(root(data) / "schedule.json", journal)
        STATE.update(busy=True, day=day, message="외국인·기관 순매수 조회 중")
    except Exception:
        if acquired:
            coordinator.release()
        RUN.release()
        raise

    def worker():
        try:
            refresh(data, day)
            STATE["message"] = "외국인·기관 순매수 저장 완료"
            write(root(data) / "last_error.json", None)
        except Exception as exc:
            message = str(exc) if isinstance(exc, DataError) else "외국인·기관 처리·저장 실패: 이전 자료 유지"
            STATE["message"] = message
            write(root(data) / "last_error.json", {"at": datetime.now(KST).isoformat(), "day": day, "message": message})
        finally:
            STATE["busy"] = False
            coordinator.release()
            RUN.release()
    try:
        threading.Thread(target=worker, daemon=True).start()
    except Exception:
        STATE["busy"] = False
        coordinator.release()
        RUN.release()
        raise
    return "started"


def tick(data, coordinator, current=None):
    return start(data, coordinator, current=current)
