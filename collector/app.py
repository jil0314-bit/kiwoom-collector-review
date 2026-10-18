"""Local, read-only daily market archive. No trading/order endpoints."""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import secrets
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from kiwoom import DataError, Kiwoom, KST, code_of, credentials
import archive
import volume_surge
import investor_flows
from window import open_dashboard

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PORT = 8766
IDENTITY = "kiwoom-top100-archive-v1"
TOKEN = secrets.token_urlsafe(32)
GUARD = threading.Lock()
CONTROL = threading.RLock()
STATE = {"busy": False, "queued": False, "message": "대기 중", "done": 0, "total": 0}
INTERVAL = 180
LAST_OPEN = 0.0


def now():
    return datetime.now(KST)


def stamp():
    return now().isoformat(timespec="seconds")


def atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)


def save(path, obj):
    atomic(path, json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"))


def read(path, fallback=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else fallback


def location(day, kind):
    if datetime.strptime(day, "%Y-%m-%d").strftime("%Y-%m-%d") != day:
        raise ValueError("날짜 형식 오류")
    if kind == "latest":
        return archive.active(DATA, day)
    if kind not in ("final", "preview"):
        raise ValueError("자료 종류 오류")
    return DATA / day / kind


def csv_bytes(rows, fields):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def safe_error(exc):
    return str(exc) if isinstance(exc, DataError) else "저장 또는 처리 오류: 파일 권한·디스크 상태를 확인하세요."


def collect(day, kind=None, api=None):
    current = now()
    if day != current.date().isoformat():
        raise DataError("과거 날짜는 조회만 가능합니다. 현재 순위로 과거 자료를 바꾸지 않습니다.")
    if current.strftime("%H:%M") < "08:00":
        raise DataError("08:00 이후 수집합니다. 이전 날짜 자료는 그대로 보관합니다.")
    kind = "final" if current.strftime("%H:%M") >= "20:00" else "preview"
    revision = uuid.uuid4().hex
    folder = archive.day_root(DATA, day) / ("snapshot-" + revision)
    try:
        return build_snapshot(day, kind, folder, revision, api)
    finally:
        # Failed replacements never become the current snapshot.
        with archive.LOCK:
            if archive.active(DATA, day) != folder:
                archive.remove_snapshot(DATA, day, folder)


def build_snapshot(day, kind, folder, revision, api=None):
    api = api or Kiwoom()
    STATE.update(message="상승률 순위 조회 중", done=0, total=0)
    ranking_at = stamp()
    stocks, raw_rank = api.ranking()
    # Date-stamped bars corroborate that an undated ranking is not simply stale.
    first_bars, first_raw = api.minute_bars(stocks[0]["code"], day)
    if now().date().isoformat() != day:
        raise DataError("수집 도중 날짜가 바뀌었습니다. 기존 자료를 유지합니다.")
    meta = {"day": day, "kind": kind, "revision": revision, "ranking_at": ranking_at,
            "market": "KRX+NXT 통합", "filter": "ETF·ETN 제외 / 양의 상승률",
            "session": "08:00~20:00 KST", "status": "running", "attempts": 0,
            "stocks": [{**s, "status": "pending"} for s in stocks],
            "coverage_notice": "API 반환 분봉만 저장. 비거래 시간과 데이터 미제공은 분봉만으로 구분할 수 없습니다."}
    atomic(folder / "ranking.raw.json.gz", gzip.compress(json.dumps(raw_rank, ensure_ascii=False).encode()))
    atomic(folder / "ranking.csv", csv_bytes(stocks, ["rank", "code", "name", "rate", "price"]))
    save(folder / "index.json", meta)
    prefetched = {stocks[0]["code"]: (first_bars, first_raw)}
    meta.update(status="running", started_at=stamp(), attempts=meta.get("attempts", 0) + 1)
    save(folder / "index.json", meta)
    STATE.update(total=len(meta["stocks"]))
    for pos, stock in enumerate(meta["stocks"]):
        code = stock["code"]
        STATE.update(done=pos, message=f"{pos + 1}/{len(meta['stocks'])} {stock['name']} 수집")
        try:
            bars, raw = prefetched.pop(code) if code in prefetched else api.minute_bars(code, day)
            record = {"day": day, "kind": kind, "revision": revision, "stock": {k: stock[k] for k in ("code", "name", "rank", "rate", "price")},
                      "collected_at": stamp(), "price_basis": "비수정 / API 원본 시각 / KRX+NXT 통합",
                      "bars": bars}
            save(folder / f"{code}.json", record)
            atomic(folder / f"{code}.csv", csv_bytes(bars, ["ts", "open", "high", "low", "close", "volume", "ma5", "ma10", "ma20", "ma60"]))
            atomic(folder / f"{code}.raw.json.gz", gzip.compress(json.dumps(raw, ensure_ascii=False).encode()))
            stock.update(status="saved", count=len(bars), first=bars[0]["ts"], last=bars[-1]["ts"],
                         pre=sum(b["ts"][11:16] < "09:00" for b in bars),
                         regular=sum("09:00" <= b["ts"][11:16] <= "15:30" for b in bars),
                         after=sum(b["ts"][11:16] > "15:30" for b in bars))
            stock.pop("error", None)
        except Exception as exc:
            stock.update(status="error", error=safe_error(exc))
        save(folder / "index.json", meta)
    count = sum(s.get("status") == "saved" for s in meta["stocks"])
    meta.update(status="saved" if count == len(meta["stocks"]) else "partial",
                finished_at=stamp(), saved=count, expected=len(meta["stocks"]))
    save(folder / "index.json", meta)
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()
                if p.is_file() and p.name != "manifest.json" and not p.name.endswith(".tmp")}
    save(folder / "manifest.json", {"generated_at": stamp(), "sha256": manifest})
    if count != len(meta["stocks"]):
        failed = [s["code"] for s in meta["stocks"] if s.get("status") != "saved"]
        raise DataError(f"{count}/{len(meta['stocks'])}종목 수신: 새 자료 교체 보류, 기존 자료 유지. 실패 종목: {', '.join(failed)}")
    pending = archive.publish(DATA, day, folder, save)
    message = f"{count}/{len(meta['stocks'])}종목 최신 자료로 교체 · {ranking_at[11:19]} 기준"
    if pending:
        message += " · 일부 이전 파일 삭제 보류"
    STATE.update(done=len(meta["stocks"]), message=message)
    return meta


def monitor_enabled():
    return bool(read(DATA / "monitor.json", {}).get("enabled", False))


def set_monitor(enabled):
    with CONTROL:
        save(DATA / "monitor.json", {"enabled": bool(enabled), "updated_at": stamp()})


def start(day, kind=None, source="manual"):
    current = now()
    if day != current.date().isoformat():
        raise DataError("수집은 오늘 날짜만 가능합니다. 과거 자료는 그대로 보관합니다.")
    if current.weekday() >= 5 or current.strftime("%H:%M") < "08:00":
        STATE["message"] = "장 시작 대기 · 평일 08:00부터 자동 갱신"
        return "waiting"
    with CONTROL:
        if not GUARD.acquire(blocking=False):
            if source in ("manual", "open"):
                STATE["queued"] = True
            return "queued" if STATE["queued"] else "running"
        journal = read(DATA / "schedule.json", {})
        if journal.get("day") != day:
            journal = {"day": day}
        journal["last_start_epoch"] = current.timestamp()
        if current.strftime("%H:%M") >= "20:05":
            journal["final_attempts"] = journal.get("final_attempts", 0) + 1
            journal["last_final_epoch"] = current.timestamp()
        try:
            save(DATA / "schedule.json", journal)
        except Exception:
            GUARD.release()
            raise
        STATE.update(busy=True, queued=False, message="최신 순위와 분봉 수집 시작", done=0, total=0)
    def worker():
        try:
            collect(day)
        except Exception as exc:
            STATE.update(message=safe_error(exc))
            save(DATA / "last_error.json", {"at": stamp(), "day": day, "kind": kind, "message": safe_error(exc)})
        else:
            update_themes(day)
        finally:
            with CONTROL:
                queued = STATE.get("queued", False)
                STATE.update(busy=False, queued=False)
                GUARD.release()
                if queued:
                    start(now().date().isoformat(), source="queued")
    threading.Thread(target=worker, daemon=True).start()
    return "started"


def update_themes(day):
    # Theme failures must never affect the committed minute snapshot.
    import themes
    try:
        themes.refresh(DATA, day)
    except Exception as exc:
        save(DATA / "themes" / "last_error.json", {"at": stamp(), "day": day, "message": safe_error(exc)})


def refresh_themes_now():
    """After an edit: recompute today's themes at once if the collector is idle."""
    import themes
    day = now().date().isoformat()
    # Only days whose minute collection already succeeded get a theme file.
    if themes.read_day(DATA, day) is None:
        return "saved"
    with CONTROL:
        if not GUARD.acquire(blocking=False):
            return "queued"
        STATE.update(busy=True, message="편집한 테마 다시 계산 중")

    def worker():
        try:
            update_themes(day)
        finally:
            with CONTROL:
                queued = STATE.get("queued", False)
                STATE.update(busy=False, queued=False, message="편집한 테마 반영 완료")
                GUARD.release()
                if queued:
                    start(now().date().isoformat(), source="queued")
    threading.Thread(target=worker, daemon=True).start()
    return "started"


def edit_directory():
    import themes
    import watchlists
    names = watchlists.names()
    with archive.LOCK:
        for entry in reversed(catalog()):
            meta = archive.metadata(archive.active(DATA, entry["day"]))
            names.update({s["code"]: s["name"] for s in meta.get("stocks", [])})
    try:
        groups, note = watchlists.groups(), ""
    except DataError as exc:
        groups, note = [], str(exc)
    usable = {g["number"] for g in themes.theme_groups(groups)}
    stocks = {}
    for g in groups:
        for item in g["entries"]:
            if item["type"] == "stock":
                stocks.setdefault(item["code"], []).append(g["number"])
    return {"groups": [{"number": g["number"], "name": g["name"], "usable": g["number"] in usable,
                        "codes": [e["code"] for e in g["entries"] if e["type"] == "stock"]} for g in groups],
            "names": {c: names.get(c, c) for c in stocks}, "note": note}


def opened():
    global LAST_OPEN
    with CONTROL:
        set_monitor(True)
        epoch = time.monotonic()
        # A duplicate tab opened by the same click should not double the work.
        if epoch - LAST_OPEN < 10:
            return "running" if STATE["busy"] else "debounced"
        LAST_OPEN = epoch
        return start(now().date().isoformat(), source="open")


def scheduler_tick(current=None):
    current = current or now()
    if current.weekday() >= 5 or current.strftime("%H:%M") < "08:00" or STATE["busy"]:
        return
    day = current.date().isoformat()
    journal = read(DATA / "schedule.json", {})
    if journal.get("day") != day:
        journal = {"day": day}
    if current.strftime("%H:%M") >= "20:05":
        with archive.LOCK:
            meta = archive.metadata(archive.active(DATA, day))
        finalized = meta.get("status") == "saved" and meta.get("ranking_at", "")[:16] >= day + "T20:05"
        if not finalized and journal.get("final_attempts", 0) < 3 and current.timestamp() - journal.get("last_final_epoch", 0) >= 900:
            start(day, source="final")
    elif current.strftime("%H:%M") < "20:00" and monitor_enabled():
        if current.timestamp() - journal.get("last_start_epoch", 0) >= INTERVAL:
            start(day, source="auto")


NEWS_RUNS = {}
NEWS_SLOTS = ("17:30", "18:00", "18:30", "20:10")
SUMMARY_RUNS = {"busy": False}
MEMO_SYNC = {"busy": False, "last": 0.0}


def sync_reason_memos(day):
    try:
        import reason_memos
        reason_memos.sync_all(DATA, day, mark_unknown=now().strftime('%H:%M') >= '18:30')
    except Exception as exc:
        save(DATA / 'hero4_daily_memo' / 'sync_error.json', {'at': stamp(), 'message': str(exc)[:300]})
    finally:
        MEMO_SYNC['busy'] = False


def memo_tick():
    # This PC's existing safe memo importer; do not redirect portable installations.
    import watchlists
    import hero4memo
    if watchlists.SOURCE.parent != hero4memo.HERO4_MEMO.parent or not (ROOT.parent / 'hero4_daily_memo.py').is_file():
        return
    if not MEMO_SYNC['busy'] and time.monotonic() - MEMO_SYNC['last'] >= 60:
        MEMO_SYNC.update(busy=True, last=time.monotonic())
        threading.Thread(target=sync_reason_memos, args=(now().date().isoformat(),), daemon=True).start()


def collect_summary(day, slot):
    import reasons
    try:
        items = reasons.fetch_summary(DATA, day, day_names(day))
        save(DATA / "reasons" / "summary_status.json", {"day": day, "at": stamp(),
             "state": "saved" if items else "waiting_for_article", "count": len(items)})
    except Exception as exc:
        save(DATA / "reasons" / "summary_status.json", {"day": day, "at": stamp(),
             "state": "error", "message": str(exc)[:300]})
    finally:
        SUMMARY_RUNS["busy"] = False


def day_names(day):
    import watchlists
    names = watchlists.names()
    with archive.LOCK:
        meta = archive.metadata(archive.active(DATA, day))
    names.update({s["code"]: s["name"] for s in meta.get("stocks", [])})
    return names


def collect_news(day, slot):
    import reasons
    try:
        with archive.LOCK:
            meta = archive.metadata(archive.active(DATA, day))
        reasons.fetch_news(DATA, day, [{"code": s["code"], "name": s["name"]} for s in meta.get("stocks", [])])
    except Exception as exc:
        save(DATA / "reasons" / "last_error.json", {"at": stamp(), "day": day, "slot": slot, "message": str(exc)[:300]})
    finally:
        NEWS_RUNS["busy"] = False


def reasons_tick(current=None):
    """Local article every five seconds; public summary and stock news after publication."""
    import reasons
    reasons.watch_hero4(DATA, day_names)
    current = current or now()
    day, hhmm = current.date().isoformat(), current.strftime("%H:%M")
    if current.weekday() < 5 and "17:00" <= hhmm <= "22:00" and not SUMMARY_RUNS["busy"]:
        interval = 600 if hhmm <= "18:30" else 1800
        if current.timestamp() - SUMMARY_RUNS.get(day, 0) >= interval:
            SUMMARY_RUNS[day] = current.timestamp()
            SUMMARY_RUNS["busy"] = True
            threading.Thread(target=collect_summary, args=(day, hhmm), daemon=True).start()
    if current.weekday() >= 5 or hhmm < NEWS_SLOTS[0] or NEWS_RUNS.get("busy"):
        return
    with archive.LOCK:
        if not archive.metadata(archive.active(DATA, day)).get("stocks"):
            return
    slot = max(s for s in NEWS_SLOTS if s <= hhmm)
    fetched = reasons.read_day(DATA, day).get("news", {}).get("fetched_at", "")
    if fetched[:10] == day and fetched[11:16] >= slot:
        return
    tries, last = NEWS_RUNS.get((day, slot), (0, 0.0))
    if tries >= 3 or current.timestamp() - last < 900:
        return
    NEWS_RUNS[(day, slot)] = (tries + 1, current.timestamp())
    NEWS_RUNS["busy"] = True
    threading.Thread(target=collect_news, args=(day, slot), daemon=True).start()


def scheduler():
    while True:
        try:
            scheduler_tick()
        except Exception as exc:
            STATE["message"] = safe_error(exc)
        try:
            reasons_tick()
        except Exception as exc:
            save(DATA / "reasons" / "watch_error.json", {"at": stamp(), "message": str(exc)[:300]})
        try:
            memo_tick()
        except Exception as exc:
            save(DATA / 'hero4_daily_memo' / 'sync_error.json', {'at': stamp(), 'message': str(exc)[:300]})
        try:
            volume_surge.tick(DATA)
        except Exception:
            volume_surge.STATE["message"] = "거래량 자동 수집 확인 필요"
        try:
            investor_flows.tick(DATA, GUARD)
        except Exception:
            investor_flows.STATE["message"] = "외국인·기관 자동 수집 확인 필요"
        time.sleep(5)


def catalog():
    result = []
    with archive.LOCK:
        for p in sorted(DATA.glob("????-??-??"), reverse=True):
            m = archive.metadata(archive.active(DATA, p.name))
            if not m:
                continue
            row = {k: m.get(k) for k in ("day", "status", "ranking_at", "saved", "expected", "revision")}
            row.update(kind="latest", phase=m.get("kind"))
            result.append(row)
    return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Avoid query strings and auth values in logs.

    def respond(self, body, status=200, mime="application/json; charset=utf-8", filename=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        return self.headers.get("Host") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def do_GET(self):
        if not self.valid_host():
            return self.respond({"error": "로컬 접속만 허용"}, 403)
        parsed = urlparse(self.path)
        q = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/investors/status":
                return self.respond({"now": stamp(), "token": TOKEN,
                                     "state": dict(investor_flows.STATE),
                                     "days": investor_flows.days(DATA),
                                     "periods": investor_flows.periods(DATA),
                                     "enabled": investor_flows.enabled(DATA),
                                     "last_error": read(DATA / "investor_flows" / "last_error.json")})
            if parsed.path in ("/api/investors/day", "/api/investors/csv", "/api/investors/period", "/api/investors/period-csv"):
                period = parsed.path in ("/api/investors/period", "/api/investors/period-csv")
                doc = (investor_flows.read_period(DATA, q["start"][0], q["end"][0]) if period
                       else investor_flows.read_day(DATA, q["day"][0]))
                if not doc:
                    return self.respond({"error": "저장된 외국인·기관 자료 없음"}, 404)
                if parsed.path.endswith("csv"):
                    return self.respond(investor_flows.csv_bytes(doc), mime="text/csv; charset=utf-8",
                                        filename=(doc["period_start"] + "_" + doc["period_end"] if period else doc["day"]) + "_investors.csv")
                # Raw response stays in the archive, not in the dashboard payload.
                return self.respond({k: v for k, v in doc.items() if k != "raw"})
            if parsed.path == "/api/volume/status":
                try:
                    credentials()
                    auth = True
                except (DataError, OSError):
                    auth = False
                return self.respond({"now": stamp(), "token": TOKEN, "credentials": auth,
                                     "state": dict(volume_surge.STATE), "catalog": volume_surge.catalog(DATA),
                                     "monitor": {"enabled": volume_surge.enabled(DATA), "interval_seconds": 60}})
            if parsed.path == "/api/volume/day":
                return self.respond(volume_surge.metadata(DATA, q["day"][0]))
            if parsed.path == "/api/status":
                try:
                    credentials()
                    auth = True
                except (DataError, OSError):
                    auth = False
                return self.respond({"identity": IDENTITY, "now": stamp(), "token": TOKEN,
                                     "credentials": auth, "state": dict(STATE), "catalog": catalog(),
                                     "last_error": read(DATA / "last_error.json"),
                                     "monitor": {"enabled": monitor_enabled(), "interval_seconds": INTERVAL},
                                     "schedule": "열 때 갱신 · 3분 간격 갱신 · 20:05 최종 수집"})
            if parsed.path == "/api/themes":
                import themes
                available = themes.days(DATA)
                day = q.get("day", [available[0] if available else now().date().isoformat()])[0]
                record = themes.read_day(DATA, day)
                top100 = {}
                if record:
                    with archive.LOCK:
                        meta = archive.metadata(archive.active(DATA, day))
                    top100 = {s["code"]: s["rank"] for s in meta.get("stocks", [])}
                return self.respond({"days": available, "day": day, "record": record, "top100": top100,
                                     "keep_days": themes.KEEP_DAYS, "interval_seconds": INTERVAL,
                                     "monitor": monitor_enabled(), "now": stamp(),
                                     "last_error": read(DATA / "themes" / "last_error.json")})
            if parsed.path == "/api/theme-edits":
                import themes
                return self.respond({"edits": themes.read_edits(DATA), **edit_directory(),
                                     "limits": {"add": themes.MAX_ADD, "pin": themes.LEADERS, "custom": themes.MAX_CUSTOM,
                                                "custom_codes": themes.MAX_CUSTOM_CODES, "name": themes.MAX_NAME}})
            if parsed.path == "/api/notes":
                import hero4memo
                import notes
                import reasons
                return self.respond({"day": q["day"][0], "notes": notes.read_day(DATA, q["day"][0]),
                                     "reasons": {**reasons.read_day(DATA, q["day"][0]),
                                                 "history": reasons.recent_history(DATA, q["day"][0])}, "hero4": hero4memo.load()})
            if parsed.path == "/api/quotes":
                import chart_data
                codes = [code_of(c) for c in q.get("codes", [""])[0].split(",") if c]
                return self.respond({"quotes": chart_data.current_quotes(codes)})
            if parsed.path == "/api/hero-targets":
                import hero_link
                return self.respond({"targets": hero_link.targets(), "preferred": hero_link.preferred()})
            if parsed.path == "/api/watchlists":
                import watchlists
                names = watchlists.names()
                with archive.LOCK:
                    for entry in reversed(catalog()):
                        meta = archive.metadata(archive.active(DATA, entry["day"]))
                        names.update({s["code"]: s["name"] for s in meta.get("stocks", [])})
                groups = watchlists.groups()
                for group in groups:
                    for item in group["entries"]:
                        if item["type"] == "stock":
                            item["name"] = names.get(item["code"], item["code"])
                return self.respond({"groups": groups, "source_updated_at": datetime.fromtimestamp(watchlists.SOURCE.stat().st_mtime, KST).isoformat(timespec="seconds")})
            if parsed.path in ("/api/chart", "/api/chart.csv", "/api/chart.png"):
                import chart_data
                day = q["day"][0]
                code = code_of(q["code"][0])
                frame = q.get("frame", ["minute"])[0]
                source = q.get("source", ["ranking"])[0]
                name = None
                if source == "watchlist":
                    import watchlists
                    group_number = int(q["group"][0])
                    group = next((g for g in watchlists.groups() if g["number"] == group_number), None)
                    if not group or not any(item.get("code") == code for item in group["entries"]):
                        return self.respond({"error": "선택한 관심종목 그룹에 없는 종목입니다."}, 404)
                    name = watchlists.names().get(code, code)
                elif source == "theme":
                    import themes
                    saved = themes.read_day(DATA, day) or {}
                    leader = next((s for t in saved.get("themes", []) + saved.get("custom", []) for s in t.get("leaders", []) if s["code"] == code), None)
                    if not leader:
                        return self.respond({"error": "선택한 날짜의 상승테마 주도주가 아닙니다."}, 404)
                    # Theme leaders reuse the on-demand watchlist chart cache; no new fetch logic.
                    name, source = leader["name"], "watchlist"
                elif source != "ranking" and source != "volume":
                    return self.respond({"error": "차트 출처 오류"}, 400)
                try:
                    live = q.get("live", ["0"])[0] == "1"
                    revision = q.get("rev", [None])[0]
                    def load_chart():
                        if source == "volume":
                            return volume_surge.chart(DATA, day, code, frame, live)
                        return chart_data.load(DATA, day, code, frame, revision, source=source, name=name, live=live)
                    if parsed.path == "/api/chart" and q.get("fast", ["0"])[0] == "1":
                        import chart_service
                        key = (str(DATA), day, code, frame, source, name, live, None if live else revision)
                        result = chart_service.get(key, load_chart,
                            lambda: chart_service.seed(DATA, day, code, frame, source, name, live, revision), 15 if live else 300,
                            wait=q.get("async", ["0"])[0] != "1", prefetch=q.get("prefetch", ["0"])[0] == "1")
                    else:
                        result = load_chart()
                except (DataError, OSError) as exc:
                    return self.respond({"error": safe_error(exc)}, 503)
                if parsed.path.endswith(".png"):
                    from chart import render
                    return self.respond(render(result, q.get("minute", [None])[0]), mime="image/png", filename=f"{day}_{code}_{frame}.png")
                if parsed.path.endswith(".csv"):
                    fields = ["ts", "open", "high", "low", "close", "volume"] + [f"ma{n}" for n in chart_data.PERIODS[frame]]
                    return self.respond(csv_bytes(result["bars"], fields), mime="text/csv; charset=utf-8", filename=f"{day}_{code}_{frame}.csv")
                return self.respond(result)
            if parsed.path in ("/api/day", "/api/bars", "/api/csv", "/api/png"):
                day = q["day"][0]
                if parsed.path == "/api/day":
                    payload, _ = archive.payload(DATA, day)
                    return self.respond(payload if payload else {"stocks": []})
                code = code_of(q["code"][0])
                payload, stale = archive.payload(DATA, day, code, ".csv" if parsed.path == "/api/csv" else ".json", q.get("rev", [None])[0])
                if stale:
                    return self.respond({"error": "최신 자료로 교체되었습니다. 화면 갱신 후 다시 선택하세요."}, 409)
                if payload is None:
                    return self.respond({"error": "저장된 자료가 없습니다."}, 404)
                if parsed.path == "/api/png":
                    from chart import render
                    return self.respond(render(json.loads(payload), q.get("minute", [None])[0]), mime="image/png", filename=f"{day}_{code}_1m.png")
                if parsed.path == "/api/csv":
                    return self.respond(payload, mime="text/csv; charset=utf-8", filename=f"{day}_{code}.csv")
                return self.respond(payload)
            investor_files = {"/investors": ("investors.html", "text/html"),
                              "/investors.js": ("investors.js", "text/javascript"),
                              "/investors.css": ("investors.css", "text/css")}
            if parsed.path in investor_files:
                name, mime = investor_files[parsed.path]
                return self.respond((ROOT / "web" / name).read_bytes(), mime=mime + "; charset=utf-8")
            files = {"/": "index.html", "/app.js": "app.js", "/notes.js": "notes.js", "/style.css": "style.css", "/mascot.png": "mascot.png",
                     "/themes": "themes.html", "/themes.js": "themes.js", "/themes.css": "themes.css",
                     "/volume": "volume.html", "/volume.js": "volume.js", "/volume-notes.js": "volume-notes.js", "/volume.css": "volume.css"}
            if parsed.path in files:
                mime = {"/": "text/html", "/app.js": "text/javascript", "/notes.js": "text/javascript", "/style.css": "text/css", "/mascot.png": "image/png",
                        "/themes": "text/html", "/themes.js": "text/javascript", "/themes.css": "text/css",
                        "/volume": "text/html", "/volume.js": "text/javascript", "/volume-notes.js": "text/javascript", "/volume.css": "text/css"}[parsed.path]
                return self.respond((ROOT / "web" / files[parsed.path]).read_bytes(), mime=mime + "; charset=utf-8")
            self.respond({"error": "없는 경로"}, 404)
        except (ValueError, KeyError, DataError):
            self.respond({"error": "날짜·종목 입력을 확인하세요."}, 400)

    def do_POST(self):
        origin = self.headers.get("Origin", "")
        if not self.valid_host() or self.headers.get("X-Collector-Token") != TOKEN or (origin and origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}")):
            return self.respond({"error": "로컬 인증 실패"}, 403)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > (400000 if self.path == "/api/reasons" else 128000 if self.path in ("/api/notes", "/api/theme-edits") else 2048):
                raise ValueError()
            body = json.loads(self.rfile.read(length))
            if self.path in ("/api/investors/collect", "/api/investors/monitor"):
                if self.path.endswith("monitor"):
                    investor_flows.set_enabled(DATA, body.get("enabled"))
                    result = investor_flows.start(DATA, GUARD) if body["enabled"] else "paused"
                else:
                    result = investor_flows.start(DATA, GUARD, manual=True)
                return self.respond({"ok": True, "state": result}, 202)
            if self.path in ("/api/volume/open", "/api/volume/collect", "/api/volume/monitor"):
                if self.path.endswith("monitor"):
                    if not isinstance(body.get("enabled"), bool):
                        raise ValueError()
                    volume_surge.set_enabled(DATA, body["enabled"])
                    result = volume_surge.start(DATA) if body["enabled"] else "paused"
                else:
                    result = volume_surge.start(DATA, manual=True)
                return self.respond({"ok": True, "state": result}, 202)
            if self.path == "/api/hero-link":
                import hero_link
                if not isinstance(body, dict):
                    raise ValueError()
                result = hero_link.send(code_of(body.get("code", "")), chart_handle=body.get("chart"))
                return self.respond(result)
            if self.path == "/api/reasons":
                import reasons
                if not isinstance(body, dict):
                    raise ValueError()
                day = str(body.get("day", ""))
                try:
                    reasons.path(DATA, day)
                    items = reasons.save_infostock(DATA, day, body.get("text"), day_names(day))
                except ValueError as exc:
                    return self.respond({"error": str(exc) or "입력 형식 오류"}, 400)
                return self.respond({"ok": True, "count": len(items), "reasons": reasons.read_day(DATA, day)})
            if self.path == "/api/theme-edits":
                import themes
                if not isinstance(body, dict):
                    raise ValueError()
                try:
                    doc = themes.save_edits(DATA, body.get("edits"), str(body.get("revision", "")))
                except ValueError as exc:
                    return self.respond({"error": str(exc) or "편집 형식 오류"}, 400)
                except themes.Conflict as exc:
                    return self.respond({"error": str(exc), "edits": themes.read_edits(DATA)}, 409)
                except OSError:
                    return self.respond({"error": "편집 저장 실패: 디스크·파일 권한을 확인하세요."}, 500)
                return self.respond({"ok": True, "edits": doc, "refresh": refresh_themes_now()})
            if self.path == "/api/notes":
                import notes
                try:
                    note = notes.write(DATA, body["day"], body["code"], body["text"], body.get("revision", ""), body.get("name", ""))
                except notes.Conflict as exc:
                    return self.respond({"error": str(exc)}, 409)
                except OSError:
                    return self.respond({"error": "메모 저장 실패: 디스크·파일 권한을 확인하세요. 작성 내용은 화면에 유지됩니다."}, 500)
                return self.respond({"ok": True, "note": note})
            if self.path == "/api/open":
                return self.respond({"ok": True, "state": opened()}, 202)
            if self.path == "/api/monitor":
                if not isinstance(body.get("enabled"), bool):
                    raise ValueError()
                set_monitor(body["enabled"])
                if body["enabled"]:
                    result = start(now().date().isoformat())
                else:
                    result = "paused"
                return self.respond({"ok": True, "state": result})
            if self.path != "/api/collect":
                return self.respond({"error": "없는 경로"}, 404)
            day = body.get("day", now().date().isoformat())
            self.respond({"ok": True, "state": start(day)}, 202)
        except (ValueError, KeyError, DataError) as exc:
            self.respond({"error": str(exc) if isinstance(exc, DataError) else "입력 형식 오류"}, 400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    DATA.mkdir(exist_ok=True)
    # An OS-level lock prevents two collectors even if the HTTP port is changed later.
    import msvcrt
    lock = (DATA / "server.lock").open("a+b", buffering=0)
    # Windows also blocks reads of another process's locked byte. Lock first;
    # locking a byte beyond EOF is supported and needs no initialization read.
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        if args.open:
            open_dashboard(f"http://127.0.0.1:{PORT}")
        return
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=scheduler, daemon=True).start()
    if args.open:
        open_dashboard(f"http://127.0.0.1:{PORT}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        lock.close()


if __name__ == "__main__":
    main()
