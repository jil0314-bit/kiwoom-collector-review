"""Read-only volume-surge collection, isolated from the existing top100 archive."""
import calendar
import csv
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import stat
import threading
import time
from datetime import datetime, date
from pathlib import Path

import archive
import chart_data
from kiwoom import DataError, Kiwoom, KST, code_of, number

LOCK = threading.RLock()
RANK_GUARD = threading.Lock()
BAR_GUARD = threading.Lock()
STATE = {"busy": False, "bars_busy": False, "message": "08:00부터 자동 조회", "done": 0, "total": 0}
LAST_START = 0.0
INTERVAL = 60
BODY = {"mrkt_tp": "000", "sort_tp": "2", "tm_tp": "2", "trde_qty_tp": "0",
        "tm": "", "stk_cnd": "20", "pric_tp": "8", "stex_tp": "3"}
FIELDS = ["rank", "code", "name", "price", "rate", "volume_rate", "previous_volume", "volume", "market_cap"]


def root(data):
    base = Path(data).resolve()
    path = base / "volume_surge"
    if path.resolve() != path or path.is_symlink():
        raise ValueError("거래량 저장소 연결 경로 차단")
    return path


def write(path, obj):
    blob = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
    put(path, blob)


def put(path, blob):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(blob)
    os.replace(tmp, path)


def read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def request(api, body, cursor=""):
    # Reuse the existing chart client/token and serialize with chart requests.
    with chart_data.LOCK:
        chart_data.CLIENT = chart_data.CLIENT or Kiwoom()
        return chart_data.CLIENT.request(api, body, cursor)


def ranking(day, call=request, limit=100):
    rows, raw, seen, cursor, ignored = {}, [], set(), "", 0
    for _ in range(30):
        data, hdr = call("ka10023", dict(BODY), cursor)
        observed_at = datetime.now(KST).isoformat(timespec="seconds")
        raw.append(data)
        items = data.get("trde_qty_sdnin")
        if not isinstance(items, list):
            raise DataError("거래량 급증 순위 목록 누락")
        candidates = []
        for item in items:
            code = code_of(item.get("stk_cd", ""))
            if code in rows or any(c[0] == code for c in candidates):
                continue
            price = number(item.get("cur_prc", ""), price=True)
            if price < 1000:
                continue
            candidates.append((code, item))
        for offset in range(0, len(candidates), 10):
            batch = candidates[offset:offset+10]
            details, _ = call("ka10095", {"stk_cd": "|".join(c+"_AL" for c, _ in batch)}, "")
            caps = {}
            for row in details.get("atn_stk_infr", []):
                code = code_of(row.get("stk_cd", ""))
                if code not in {c for c, _ in batch}:
                    raise DataError("시가총액 요청·응답 종목 불일치")
                if row.get("dt") != day.replace("-", ""):
                    raise DataError("오늘 시세가 아닙니다. 휴장·지연 응답 여부 확인 필요")
                if str(row.get("mac", "")).strip():
                    caps[code] = number(row["mac"], price=True)
            for code, item in batch:
                if code not in caps:
                    ignored += 1
                    continue
                if caps[code] < 500:
                    continue
                rows[code] = {"code": code, "name": str(item.get("stk_nm", code)),
                              "observed_at": observed_at,
                              "price": number(item["cur_prc"], price=True), "rate": number(item["flu_rt"]),
                              "volume_rate": number(item["sdnin_rt"]), "previous_volume": number(item["prev_trde_qty"]),
                              "volume": number(item["now_trde_qty"]), "market_cap": caps[code]}
            if len(rows) >= limit:
                break
        if len(rows) >= limit or hdr.get("cont-yn") != "Y":
            break
        cursor = str(hdr.get("next-key", ""))
        if not cursor or cursor in seen:
            raise DataError("거래량 순위 연속조회 키 누락·반복")
        seen.add(cursor)
    else:
        raise DataError("거래량 순위 연속조회 한도 초과")
    result = sorted(rows.values(), key=lambda s: (-s["volume_rate"], s["code"]))[:limit]
    if not result:
        raise DataError("조건에 맞는 오늘 거래량 순위가 없습니다. 기존 저장 유지")
    for i, stock in enumerate(result, 1):
        stock["rank"] = i
    return result, {"request": BODY, "pages": raw, "unknown_cap_excluded": ignored,
                    "observed_at": min(s["observed_at"] for s in result)}


def enabled(data):
    return read(root(data) / "monitor.json", {}).get("enabled", True)


def set_enabled(data, value):
    with LOCK:
        write(root(data) / "monitor.json", {"enabled": bool(value)})


def metadata(data, day):
    with LOCK:
        result = read(archive.day_root(root(data), day) / "index.json", {"day": day, "stocks": [], "tracked": []})
        for stock in result.get("stocks", []) + result.get("tracked", []):
            stock.update(result.get("bar_status", {}).get(stock["code"], {}))
        return result


def catalog(data):
    rows = []
    with LOCK:
        for path in sorted(root(data).glob("????-??-??"), reverse=True):
            m = metadata(data, path.name)
            if m.get("stocks"):
                rows.append({k: m.get(k) for k in ("day", "status", "ranking_at", "saved", "expected", "revision")})
                rows[-1].update(kind="latest", phase=m.get("kind"))
    return rows


def cutoff(current):
    y, m = (current.year, current.month-1) if current.month > 1 else (current.year-1, 12)
    return date(y, m, min(current.day, calendar.monthrange(y, m)[1]))


def prune(data, current):
    # Only this category's dated folders/caches can be removed; never data/YYYY-MM-DD.
    base = root(data)
    expired = cutoff(current).isoformat()
    with LOCK:
        for parent in (base, base / "cache" / "watchlist_history", base / "cache" / "chart_history", base / "cache" / "weekly_history"):
            if parent.resolve() != parent:
                raise ValueError("거래량 보관 경로 연결 차단")
            for path in parent.glob("????-??-??"):
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.name) or path.name > expired:
                    continue
                date.fromisoformat(path.name)
                target = path.resolve()
                if target != path or target.parent != parent or not target.is_relative_to(base):
                    raise ValueError("거래량 삭제 범위 오류")
                for walkroot, dirs, files in os.walk(path, followlinks=False):
                    for p in [Path(walkroot)] + [Path(walkroot) / n for n in dirs + files]:
                        attrs = p.lstat()
                        if p.is_symlink() or getattr(attrs, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                            raise ValueError("연결 파일 삭제 차단")
                shutil.rmtree(target)


def commit_rank(data, day, stocks, raw, at):
    folder = archive.day_root(root(data), day)
    with LOCK:
        old = metadata(data, day)
        tracked = {s["code"]: s for s in old.get("tracked", [])}
        for s in stocks:
            prior = tracked.get(s["code"], {})
            s.update(first_seen=prior.get("first_seen", s.get("observed_at", at)), first_price=prior.get("first_price", s["price"]),
                     best_rank=min(prior.get("best_rank", s["rank"]), s["rank"]), last_seen=at)
            tracked[s["code"]] = dict(s)
        meta = {"day": day, "kind": "final" if at[11:16] >= "20:00" else "preview", "revision": at,
                "ranking_at": at, "stocks": stocks, "tracked": list(tracked.values()), "bar_status": old.get("bar_status", {}),
                "filter": "ETF·ETN·스팩 제외 · 1,000원 이상 · 시총 500억 이상 · 신용/거래대금 전체",
                "status": "running", "expected": len(stocks), "saved": 0,
                "unknown_cap_excluded": raw["unknown_cap_excluded"],
                "notice": "REST 거래량 급증률(전일) 내림차순 · KRX+NXT 통합. 영웅문 화면 설정/거래소에 따라 순위가 다를 수 있습니다."}
        write(folder / "index.json", meta)
        put(folder / "ranking.raw.json.gz", gzip.compress(json.dumps(raw, ensure_ascii=False).encode()))
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader(); writer.writerows(stocks)
        put(folder / "ranking.csv", output.getvalue().encode("utf-8-sig"))
        history = folder / "ranking_history.csv"
        new = not history.exists()
        with history.open("a", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["observed_at"] + FIELDS, extrasaction="ignore")
            if new:
                writer.writeheader()
            writer.writerows({**s, "observed_at": at} for s in stocks)
        return meta


def collect_bars(data, day):
    if not BAR_GUARD.acquire(blocking=False):
        return
    STATE.update(bars_busy=True)
    try:
        meta = metadata(data, day)
        target_at = meta["ranking_at"]
        # Include earlier entrants to retain their subsequent intraday path.
        stocks = sorted(meta["tracked"], key=lambda s: (s["code"] not in {x["code"] for x in meta["stocks"]}, s["rank"]))
        STATE.update(total=len(stocks), done=0)
        for pos, s in enumerate(stocks):
            if datetime.now(KST).date().isoformat() != day:
                break
            STATE.update(done=pos, message=f"분봉 {pos+1}/{len(stocks)} · {s['name']}")
            code = s["code"]
            try:
                with chart_data.LOCK:
                    chart_data.CLIENT = chart_data.CLIENT or Kiwoom()
                    bars, raw = chart_data.CLIENT.minute_bars(code, day)
                record = {"day": day, "kind": meta["kind"], "stock": s, "bars": bars,
                          "collected_at": datetime.now(KST).isoformat(timespec="seconds"), "source": "volume"}
                blob = json.dumps(record, ensure_ascii=False).encode()
                with LOCK:
                    folder = archive.day_root(root(data), day)
                    put(folder / f"{code}.json", blob)
                    put(folder / f"{code}.raw.json.gz", gzip.compress(json.dumps(raw, ensure_ascii=False).encode()))
                    put(folder / f"{code}.sha256", hashlib.sha256(blob).hexdigest().encode("ascii"))
                    output = io.StringIO(newline="")
                    writer = csv.DictWriter(output, fieldnames=["ts", "open", "high", "low", "close", "volume"], extrasaction="ignore")
                    writer.writeheader(); writer.writerows(bars)
                    put(folder / f"{code}.csv", output.getvalue().encode("utf-8-sig"))
                    m = metadata(data, day)
                    m["bar_status"][code] = {"status": "saved", "count": len(bars), "first": bars[0]["ts"], "last": bars[-1]["ts"],
                                             "collected_at": record["collected_at"], "rank_basis": target_at}
                    m["bar_status"][code].update(pre=sum(b["ts"][11:16] < "09:00" for b in bars),
                                                  regular=sum("09:00" <= b["ts"][11:16] <= "15:30" for b in bars),
                                                  after=sum(b["ts"][11:16] > "15:30" for b in bars))
                    write(folder / "index.json", m)
            except Exception as exc:
                with LOCK:
                    folder = archive.day_root(root(data), day)
                    m = metadata(data, day)
                    previous = m["bar_status"].get(code, {})
                    m["bar_status"][code] = {**previous, "status": previous.get("status", "error"),
                                              "error": str(exc)[:160] if isinstance(exc, DataError) else "분봉 저장 실패"}
                    write(folder / "index.json", m)
            time.sleep(.05)  # Give current-chart/ranking requests a turn between symbols.
        with LOCK:
            m = metadata(data, day)
            m["saved"] = sum(s.get("status") == "saved" for s in m["stocks"])
            m["status"] = "saved" if m["saved"] == len(m["stocks"]) else "partial"
            m["final_complete"] = m["ranking_at"][11:16] >= "20:05" and all(
                s.get("rank_basis", "") >= m["ranking_at"] and not s.get("error") for s in m["tracked"])
            write(archive.day_root(root(data), day) / "index.json", m)
            STATE.update(done=len(stocks), message=f"목록 {len(m['stocks'])}종목 · 분봉 {m['saved']}/{len(m['stocks'])} 저장" + (" · 최종 완료" if m["final_complete"] else ""))
    finally:
        STATE["bars_busy"] = False
        BAR_GUARD.release()


def start(data, manual=False, current=None):
    global LAST_START
    current = current or datetime.now(KST)
    if current.weekday() >= 5 or current.strftime("%H:%M") < "08:00":
        return "waiting"
    if not RANK_GUARD.acquire(blocking=False):
        return "running"
    LAST_START = current.timestamp()
    STATE["busy"] = True
    def worker():
        try:
            day = current.date().isoformat()
            prune(data, current.date())
            STATE["message"] = "거래량 급증률·시총 조회 중"
            stocks, raw = ranking(day)
            if datetime.now(KST).date().isoformat() != day:
                raise DataError("조회 도중 날짜 변경. 이전 자료 유지")
            at = raw["observed_at"]
            commit_rank(data, day, stocks, raw, at)
            threading.Thread(target=collect_bars, args=(data, day), daemon=True).start()
        except Exception as exc:
            STATE["message"] = str(exc) if isinstance(exc, DataError) else "거래량 수집·저장 실패"
            with LOCK:
                write(root(data) / "last_error.json", {"at": datetime.now(KST).isoformat(), "message": STATE["message"]})
        finally:
            STATE["busy"] = False
            RANK_GUARD.release()
    threading.Thread(target=worker, daemon=True).start()
    return "started"


def tick(data, current=None):
    current = current or datetime.now(KST)
    hhmm = current.strftime("%H:%M")
    if current.weekday() >= 5 or hhmm < "08:00" or STATE["busy"]:
        return
    if "20:00" <= hhmm < "20:05":
        return
    if hhmm >= "20:05":
        m = metadata(data, current.date().isoformat())
        if m.get("final_complete"):
            return
        # Freeze the final ranking while its complete bar pass runs.
        if m.get("ranking_at", "")[11:16] >= "20:05" and STATE["bars_busy"]:
            return
        interval = 300
    else:
        if not enabled(data):
            return
        interval = INTERVAL
    if current.timestamp() - LAST_START >= interval:
        start(data, current=current)
    elif not STATE["bars_busy"] and metadata(data, current.date().isoformat()).get("stocks"):
        threading.Thread(target=collect_bars, args=(data, current.date().isoformat()), daemon=True).start()


def chart(data, day, code, frame, live):
    m = metadata(data, day)
    stock = next((s for s in m.get("tracked", []) if s["code"] == code), None)
    if not stock:
        raise DataError("선택한 거래량 급증 날짜에 없는 종목")
    cache = root(data) / "cache"
    if live or frame in ("day", "week"):
        return chart_data.load(cache, day, code, frame, source="watchlist", name=stock["name"], live=live)
    with LOCK:
        folder = archive.day_root(root(data), day)
        record = read(folder / f"{code}.json")
        if not record:
            raise DataError("이 종목의 저장 분봉은 아직 수집되지 않았습니다.")
        raw = json.loads(gzip.decompress((folder / f"{code}.raw.json.gz").read_bytes()))
    if frame == "minute":
        return chart_data.minute_record(record, raw)
    if frame in ("minute3", "minute5"):
        return chart_data.grouped_record(record, raw, int(frame[-1]))
    raise DataError("차트 종류 오류")
