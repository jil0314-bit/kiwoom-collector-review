"""Read-only Kiwoom REST adapter. Secrets and tokens never enter archives/logs."""
from __future__ import annotations
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
HOST = "https://api.kiwoom.com"
ROUTES = {"ka10023": "/api/dostk/rkinfo", "ka10027": "/api/dostk/rkinfo", "ka10080": "/api/dostk/chart", "ka10081": "/api/dostk/chart",
          "ka90001": "/api/dostk/thme", "ka90002": "/api/dostk/thme", "ka10095": "/api/dostk/stkinfo",
          "ka90009": "/api/dostk/rkinfo"}


class DataError(Exception):
    pass


def credentials():
    """Read existing user credentials; do not import/execute the trading program."""
    candidates = []
    explicit = os.environ.get("TOP100_CREDENTIAL_FILE", "")
    if explicit:
        candidates.append(Path(explicit))
    pointer = Path.home() / ".v75_last_credentials_path.txt"
    if pointer.is_file():
        candidates.append(Path(pointer.read_text(encoding="utf-8-sig").strip()))
    candidates += [Path.home() / "Desktop/기타/.env",
                   Path.home() / "Desktop/코딩관련파일들/키움REST/.env",
                   Path.home() / "Downloads/v73_keys.env"]
    sources = [("환경변수", dict(os.environ))]
    for path in candidates:
        if not path.is_file():
            continue
        values = {}
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.removeprefix("export ").split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
        sources.append(("기존 키움 인증 파일", values))
    for label, values in sources:
        key = values.get("KIWOOM_APP_KEY") or values.get("APP_KEY")
        secret = (values.get("KIWOOM_SECRET_KEY") or values.get("KIWOOM_APP_SECRET")
                  or values.get("APP_SECRET") or values.get("SECRET_KEY"))
        if key and secret:
            return key, secret, label
    raise DataError("키움 REST 인증 없음: 기존 인증 파일 또는 KIWOOM_APP_KEY / KIWOOM_SECRET_KEY가 필요합니다.")


def code_of(value):
    value = str(value).strip()
    value = re.sub(r"_(AL|NX)$", "", value)
    if value.startswith("A") and len(value) == 7:
        value = value[1:]
    if not re.fullmatch(r"[0-9A-Z]{6}", value):
        raise DataError("응답 종목코드 형식 오류")
    return value


def number(value, *, price=False):
    text = str(value).replace(",", "").strip()
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        raise DataError("응답 숫자 형식 오류")
    n = float(text)
    if price:
        n = abs(n)  # Kiwoom's sign is a direction marker, not a negative price.
    return int(n) if n.is_integer() else n


def parse_bar(row):
    stamp = str(row.get("cntr_tm", ""))
    try:
        dt = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=KST)
    except ValueError:
        raise DataError("분봉 시각 형식 오류") from None
    if dt.second:
        raise DataError("1분봉에 초 단위 시각이 포함됨")
    try:
        o, h, l, c = [number(row[k], price=True) for k in
                      ("open_pric", "high_pric", "low_pric", "cur_prc")]
        v = number(row["trde_qty"])
    except KeyError:
        raise DataError("분봉 필수 가격·거래량 누락") from None
    if min(o, h, l, c) <= 0 or not (l <= min(o, c) <= max(o, c) <= h) or v < 0:
        raise DataError("분봉 OHLC 범위 또는 거래량 오류")
    return {"ts": dt.strftime("%Y-%m-%d %H:%M:%S"), "open": o,
            "high": h, "low": l, "close": c, "volume": v}


class Kiwoom:
    def __init__(self, interval=1.1, transport=None):
        self.interval = interval
        self.transport = transport or self._http
        self.token = ""
        self.expires = datetime.min.replace(tzinfo=KST)
        self.last_request = 0.0

    def _http(self, path, body, headers):
        req = urllib.request.Request(HOST + path, json.dumps(body).encode(),
                                     {"Content-Type": "application/json;charset=UTF-8", **headers})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read()), dict(response.headers)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504):
                raise ConnectionError("일시적인 API 통신 오류") from None
            raise DataError(f"키움 HTTP 오류 {exc.code}: 인증·허용 IP를 확인하세요.") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise ConnectionError("키움 통신 실패 또는 응답 형식 오류") from None

    def _send(self, path, body, headers):
        for attempt in range(5):
            time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                data, response_headers = self.transport(path, body, headers)
                if not isinstance(data, dict):
                    raise DataError("키움 응답 객체 형식 오류")
                rc = str(data.get("return_code", ""))
                if rc in ("1700", "429"):
                    raise ConnectionError("API 호출 제한")
                if rc != "0":
                    raise DataError(f"키움 응답 오류 코드 {rc[:12]}")
                return data, {k.lower(): v for k, v in response_headers.items()}
            except ConnectionError:
                if attempt == 4:
                    raise DataError("API 통신·호출 제한: 5회 재시도 실패") from None
                time.sleep(min(20, 2 ** (attempt + 1)))

    def authorize(self):
        if self.token and datetime.now(KST) < self.expires - timedelta(minutes=5):
            return
        key, secret, _ = credentials()
        data, _ = self._send("/oauth2/token", {"grant_type": "client_credentials",
                             "appkey": key, "secretkey": secret}, {})
        if not data.get("token"):
            raise DataError("접근토큰 발급 실패")
        self.token = data["token"]
        try:
            self.expires = datetime.strptime(data["expires_dt"], "%Y%m%d%H%M%S").replace(tzinfo=KST)
        except (KeyError, ValueError):
            self.expires = datetime.now(KST) + timedelta(minutes=30)

    def request(self, api, body, cursor=""):
        if api not in ROUTES:
            raise DataError("허용되지 않은 API: 이 앱은 시세 조회 전용입니다.")
        self.authorize()
        headers = lambda: {"authorization": "Bearer " + self.token, "api-id": api,
                           "cont-yn": "Y" if cursor else "N", "next-key": cursor}
        try:
            return self._send(ROUTES[api], body, headers())
        except DataError as exc:
            # A newer token issued elsewhere on the same app key revokes this one (return code 3).
            if str(exc) != "키움 응답 오류 코드 3":
                raise
            self.token = ""
            self.authorize()
            return self._send(ROUTES[api], body, headers())

    def quotes(self, codes):
        codes = list(dict.fromkeys(code_of(c) for c in codes))
        result = {}
        for offset in range(0, len(codes), 10):
            batch = codes[offset:offset+10]
            data, _ = self.request("ka10095", {"stk_cd": "|".join(c+"_AL" for c in batch)})
            for row in data.get("atn_stk_infr", []):
                code = code_of(row.get("stk_cd", ""))
                if code not in batch:
                    raise DataError("현재가 요청·응답 종목코드 불일치")
                price = number(row.get("cur_prc", ""), price=True)
                if price <= 0:
                    continue
                result[code] = {"price": price, "rate": number(row.get("flu_rt", "")),
                                "date": str(row.get("dt", "")), "time": str(row.get("cntr_tm", "")),
                                "fetched_at": datetime.now(KST).isoformat(timespec="seconds")}
        return result

    def quote(self, code):
        code = code_of(code)
        result = self.quotes([code])
        if code not in result:
            raise DataError("현재가 응답 없음")
        return result[code]

    def ranking(self, limit=100):
        body = {"mrkt_tp": "000", "sort_tp": "1", "trde_qty_cnd": "0000",
                "stk_cnd": "16", "crd_cnd": "0", "updown_incls": "1",
                "pric_cnd": "0", "trde_prica_cnd": "0", "stex_tp": "3"}
        cursor, seen, records, raw = "", set(), {}, []
        for page in range(30):
            data, hdr = self.request("ka10027", body, cursor)
            raw.append(data)
            items = data.get("pred_pre_flu_rt_upper")
            if not isinstance(items, list):
                raise DataError("순위 목록 누락")
            for item in items:
                code = code_of(item.get("stk_cd", ""))
                rate = number(item.get("flu_rt", ""))
                if rate <= 0:
                    continue
                if code not in records:
                    records[code] = {"code": code, "name": str(item.get("stk_nm", code)),
                                     "rate": rate, "price": number(item.get("cur_prc", ""), price=True)}
            if len(records) >= limit or hdr.get("cont-yn") != "Y":
                break
            cursor = str(hdr.get("next-key", ""))
            if not cursor or cursor in seen:
                raise DataError("순위 연속조회 키 누락·반복")
            seen.add(cursor)
        else:
            raise DataError("순위 연속조회 한도 초과")
        result = sorted(records.values(), key=lambda x: (-x["rate"], x["code"]))[:limit]
        for rank, item in enumerate(result, 1):
            item["rank"] = rank
        if not result:
            raise DataError("상승 종목 순위가 비어 있습니다.")
        return result, {"request": body, "pages": raw}

    def daily_bars(self, code, day, count=300):
        """Daily chart history only; never changes the minute collection path."""
        code = code_of(code)
        datetime.strptime(day, "%Y-%m-%d")
        body = {"stk_cd": code + "_AL", "base_dt": day.replace("-", ""), "upd_stkpc_tp": "0"}
        cursor, seen, rows, pages = "", set(), {}, []
        for _ in range(20):
            data, hdr = self.request("ka10081", body, cursor)
            if code_of(data.get("stk_cd", code)) != code:
                raise DataError("일봉 요청·응답 종목코드 불일치")
            items = data.get("stk_dt_pole_chart_qry")
            if not isinstance(items, list):
                raise DataError("일봉 목록 누락")
            parsed = []
            for item in items:
                bar = parse_bar({**item, "cntr_tm": str(item.get("dt", "")) + "000000"})
                bar["ts"] = bar["ts"][:10]
                if bar["ts"] > day:
                    raise DataError("기준일 이후 일봉 반환")
                parsed.append(bar)
                if bar["ts"] in rows and rows[bar["ts"]] != bar:
                    raise DataError("일봉 연속조회 값 충돌")
                rows[bar["ts"]] = bar
            if parsed != sorted(parsed, key=lambda b: b["ts"], reverse=True):
                raise DataError("일봉 응답 날짜 정렬 오류")
            pages.append(data)
            if len(rows) >= count or hdr.get("cont-yn") != "Y":
                break
            cursor = str(hdr.get("next-key", ""))
            if not parsed or not cursor or cursor in seen:
                raise DataError("일봉 연속조회 데이터·키 누락 또는 반복")
            seen.add(cursor)
        else:
            raise DataError("일봉 연속조회 한도 초과")
        if not rows:
            raise DataError("조회 가능한 일봉이 없습니다.")
        return sorted(rows.values(), key=lambda b: b["ts"]), {"request": body, "pages": pages}

    def minute_bars(self, code, day, *, on_page=None):
        code = code_of(code)
        datetime.strptime(day, "%Y-%m-%d")
        body = {"stk_cd": code + "_AL", "tic_scope": "1", "upd_stkpc_tp": "0",
                "base_dt": day.replace("-", "")}
        cursor, seen, rows, pages = "", set(), {}, []
        cutoff = day + " 08:00:00"
        for page in range(40):
            data, hdr = self.request("ka10080", body, cursor)
            if code_of(data.get("stk_cd", code)) != code:
                raise DataError("요청·응답 종목코드 불일치")
            raw_rows = data.get("stk_min_pole_chart_qry")
            if not isinstance(raw_rows, list):
                raise DataError("분봉 목록 누락")
            parsed = [parse_bar(item) for item in raw_rows]
            if parsed != sorted(parsed, key=lambda b: b["ts"], reverse=True):
                raise DataError("분봉 응답 시간 역순 정렬 위반")
            pages.append(data)
            for bar in parsed:
                previous = rows.get(bar["ts"])
                if previous and previous != bar:
                    raise DataError("연속조회 중 같은 시각의 분봉 값 충돌")
                rows[bar["ts"]] = bar
            if on_page:
                on_page(page + 1)
            # Include earlier history from the last page for causal MAs.
            if (parsed and parsed[-1]["ts"] < cutoff) or hdr.get("cont-yn") != "Y":
                break
            cursor = str(hdr.get("next-key", ""))
            if not parsed or not cursor or cursor in seen:
                raise DataError("분봉 연속조회 데이터·키 누락 또는 반복")
            seen.add(cursor)
        else:
            raise DataError("분봉 40페이지 한도 도달: 미완료")
        ordered = sorted(rows.values(), key=lambda b: b["ts"])
        # Never insert bars for minutes without a returned trade bar.
        selected = [b for b in ordered if cutoff <= b["ts"] <= day + " 20:00:00"]
        if not selected:
            raise DataError("해당 날짜 08:00~20:00 분봉 없음")
        if any(b["ts"][:10] > day for b in ordered):
            raise DataError("요청일 이후 분봉 반환: 기준일 응답 확인 필요")
        closes = [b["close"] for b in ordered]
        for i, bar in enumerate(ordered):
            for n in (5, 10, 20, 60):
                bar[f"ma{n}"] = sum(closes[i + 1 - n:i + 1]) / n if i + 1 >= n else None
        return selected, {"request": body, "pages": pages,
                          "earlier_bar_count": sum(b["ts"] < cutoff for b in ordered)}
