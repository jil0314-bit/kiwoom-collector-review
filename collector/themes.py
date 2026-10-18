"""Daily rising-theme top 10, kept for the latest 10 trading days. Read-only APIs.

Ranking comes from Kiwoom themes; each theme's stocks come from the user's own
Hero4 0130 watchlist group matched to it, falling back to Kiwoom members.
The user's own edits (data/themes/edits.json) are applied on top at every refresh.
"""
import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from kiwoom import DataError, Kiwoom, KST, code_of, number

TOP = 10
MIN_STOCKS = 3
LEADERS = 10
KEEP_DAYS = 10
HISTORY_LIMIT = 400
MIN_OVERLAP = 2
MIN_OVERLAP_SHARE = 0.4
QUOTE_CHUNK = 50
# Holdings, index baskets and balance-sheet screens are not themes.
NOT_THEMES = {6, 9, 10, 39, 43, 66, 98, 99}
GENERIC = {"관련주", "관련", "테마", "기타", "수혜주", "대장주"}
MAX_ADD = 30
MAX_CUSTOM = 10
MAX_CUSTOM_CODES = 30
MAX_NAME = 30
DAY_FILE = re.compile(r"\d{4}-\d{2}-\d{2}\.json")
CODE = re.compile(r"[0-9A-Z]{6}")
LOCK = threading.Lock()
LOCK_EDITS = threading.Lock()
CLIENT = None


def folder(data):
    return Path(data) / "themes"


def day_path(data, day):
    if datetime.strptime(day, "%Y-%m-%d").strftime("%Y-%m-%d") != day:
        raise ValueError("날짜 형식 오류")
    return folder(data) / f"{day}.json"


def days(data):
    root = folder(data)
    if not root.is_dir():
        return []
    return sorted((p.stem for p in root.iterdir() if p.is_file() and DAY_FILE.fullmatch(p.name)), reverse=True)


def read_day(data, day):
    path = day_path(data, day)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def manual_map(data):
    """data/themes/map.json: {"키움 테마 이름": 관심그룹번호 또는 null(키움 종목 고정)}."""
    path = folder(data) / "map.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise DataError("테마 직접 지정 파일(map.json) 형식 오류")
    return {str(k).strip(): v for k, v in raw.items()} if isinstance(raw, dict) else {}


def codes_list(raw, limit):
    if not isinstance(raw, list):
        raise ValueError("종목 목록 형식 오류")
    result = []
    for value in raw:
        code = str(value).strip().upper()
        if not CODE.fullmatch(code):
            raise ValueError(f"종목코드 형식 오류: {value}")
        if code not in result:
            result.append(code)
    if len(result) > limit:
        raise ValueError(f"종목은 최대 {limit}개까지 지정할 수 있습니다.")
    return result


def clean_name(raw):
    name = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not name or len(name) > MAX_NAME:
        raise ValueError(f"테마 이름은 1~{MAX_NAME}자로 입력하세요.")
    return name


def normalize_edits(raw):
    """Validates the editor document. group: absent = 자동 짝짓기, None = 키움 종목, number = 관심그룹, "c:id" = 내 테마."""
    if not isinstance(raw, dict):
        raise ValueError("편집 자료 형식 오류")
    result = {"themes": {}, "custom": []}
    for name, edit in (raw.get("themes") or {}).items():
        name = str(name).strip()
        if not name or len(name) > 60 or not isinstance(edit, dict):
            raise ValueError("테마 편집 형식 오류")
        item = {"add": codes_list(edit.get("add", []), MAX_ADD), "remove": codes_list(edit.get("remove", []), 200),
                "pin": codes_list(edit.get("pin", []), LEADERS)}
        if "group" in edit and edit["group"] != "auto":
            group = edit["group"]
            if group in (None, "kiwoom"):
                item["group"] = None
            elif isinstance(group, int) and not isinstance(group, bool) and 1 <= group <= 99:
                item["group"] = group
            elif isinstance(group, str) and re.fullmatch(r"c:[a-z0-9]{1,32}", group):
                item["group"] = group
            else:
                raise ValueError("관심그룹 번호 오류")
        item["remove"] = [c for c in item["remove"] if c not in item["add"] and c not in item["pin"]]
        if "group" in item or item["add"] or item["remove"] or item["pin"]:
            result["themes"][name] = item
    if len(result["themes"]) > 200:
        raise ValueError("편집한 테마가 너무 많습니다.")
    custom = raw.get("custom") or []
    if not isinstance(custom, list) or len(custom) > MAX_CUSTOM:
        raise ValueError(f"내 테마는 최대 {MAX_CUSTOM}개까지 만들 수 있습니다.")
    for entry in custom:
        if not isinstance(entry, dict):
            raise ValueError("내 테마 형식 오류")
        ident = str(entry.get("id") or "")
        if not re.fullmatch(r"[a-z0-9]{1,32}", ident) or any(c["id"] == ident for c in result["custom"]):
            ident = uuid.uuid4().hex[:12]
        codes = codes_list(entry.get("codes", []), MAX_CUSTOM_CODES)
        pins = [c for c in codes_list(entry.get("pin", []), LEADERS) if c in codes]
        result["custom"].append({"id": ident, "name": clean_name(entry.get("name")), "codes": codes, "pin": pins})
    alive = {"c:" + c["id"] for c in result["custom"]}
    for name, item in list(result["themes"].items()):
        if isinstance(item.get("group"), str) and item["group"] not in alive:
            del item["group"]
            if not (item["add"] or item["remove"] or item["pin"]):
                del result["themes"][name]
    return result


def edits_path(data):
    return folder(data) / "edits.json"


def read_edits(data):
    path = edits_path(data)
    if not path.is_file():
        return {"themes": {}, "custom": [], "revision": "", "updated_at": ""}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        doc = normalize_edits(raw)
    except (OSError, ValueError) as exc:
        raise DataError("테마 편집 파일(edits.json) 형식 오류") from exc
    doc.update(revision=str(raw.get("revision", "")), updated_at=str(raw.get("updated_at", "")))
    return doc


class Conflict(Exception):
    pass


def save_edits(data, raw, revision):
    """Whole-document save; a stale revision means another window saved first."""
    doc = normalize_edits(raw)
    with LOCK_EDITS:
        if read_edits(data)["revision"] != (revision or ""):
            raise Conflict("다른 창에서 먼저 저장했습니다. 새로 불러온 뒤 다시 편집하세요.")
        doc.update(revision=uuid.uuid4().hex, updated_at=datetime.now(KST).isoformat(timespec="seconds"))
        path = edits_path(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    return doc


def arrange(stocks, pins, limit):
    """Pinned stocks first (by rate), then the rest by rate, up to the limit."""
    ordered = sorted(stocks, key=lambda s: -s["rate"])
    pinned = [dict(s, pinned=True) for s in ordered if s["code"] in pins]
    rest = [s for s in ordered if s["code"] not in pins]
    return (pinned + rest)[:max(limit, len(pinned))]


def ranking(api):
    data, _ = api.request("ka90001", {"qry_tp": "0", "stk_cd": "", "date_tp": "1", "thema_nm": "",
                                      "flu_pl_amt_tp": "3", "stex_tp": "3"})
    rows = data.get("thema_grp")
    if not isinstance(rows, list):
        raise DataError("테마 순위 목록 누락")
    themes = []
    for row in rows:
        count = int(number(row.get("stk_num", "0")))
        rate = number(row.get("flu_rt", "0"))
        if count < MIN_STOCKS or rate <= 0:
            continue
        themes.append({"code": str(row.get("thema_grp_cd", "")), "name": str(row.get("thema_nm", "")),
                       "rate": rate, "stocks": count,
                       "rising": int(number(row.get("rising_stk_num", "0"))),
                       "falling": int(number(row.get("fall_stk_num", "0")))})
    themes.sort(key=lambda t: -t["rate"])
    return themes[:TOP]


def members(api, theme_code):
    data, _ = api.request("ka90002", {"date_tp": "1", "thema_grp_cd": theme_code, "stex_tp": "3"})
    rows = data.get("thema_comp_stk")
    if not isinstance(rows, list):
        raise DataError("테마 구성종목 목록 누락")
    stocks = [{"code": code_of(r.get("stk_cd", "")), "name": str(r.get("stk_nm", "")),
               "price": number(r.get("cur_prc", "0"), price=True), "rate": number(r.get("flu_rt", "0")),
               "volume": int(number(r.get("acc_trde_qty", "0")))} for r in rows]
    stocks.sort(key=lambda s: -s["rate"])
    return stocks


def quotes(api, codes):
    result = {}
    codes = list(dict.fromkeys(codes))
    for start in range(0, len(codes), QUOTE_CHUNK):
        data, _ = api.request("ka10095", {"stk_cd": "|".join(codes[start:start + QUOTE_CHUNK])})
        rows = next((v for v in data.values() if isinstance(v, list)), None)
        if rows is None:
            raise DataError("관심종목 시세 목록 누락")
        for r in rows:
            try:
                code = code_of(r.get("stk_cd", ""))
                result[code] = {"code": code, "name": str(r.get("stk_nm", code)).strip(),
                                "price": number(r.get("cur_prc", "0"), price=True), "rate": number(r.get("flu_rt", "0")),
                                "volume": int(number(r.get("trde_qty", "0")))}
            except DataError:
                continue
    return result


def theme_groups(groups):
    """Watchlist groups usable as themes, with searchable name text."""
    result = []
    for g in groups:
        if g["number"] in NOT_THEMES:
            continue
        codes = [e["code"] for e in g["entries"] if e.get("type") == "stock"]
        text = " ".join([g["name"]] + [e.get("label", "") for e in g["entries"] if e.get("type") == "heading"])
        result.append({"number": g["number"], "name": g["name"], "codes": codes, "text": text.replace(" ", "")})
    return result


def keywords(theme_name):
    return [w for w in re.split(r"[_/.,·()\s]+", theme_name) if len(w) >= 2 and w not in GENERIC]


def match(theme_name, member_codes, groups, manual, mine=None):
    """Manual map (관심그룹 or 내 테마 "c:id") → name keyword (with ≥1 shared stock) → stock overlap (≥2 and ≥40%) → None."""
    members_set = set(member_codes)
    by_number = {g["number"]: g for g in groups}
    if theme_name in manual:
        chosen = manual[theme_name]
        if chosen in (None, 0, "", False):
            return None, "직접 지정: 키움 종목"
        if isinstance(chosen, str) and chosen.startswith("c:"):
            g = (mine or {}).get(chosen)
            if g:
                return g, "직접 지정 · 내가 만든 테마"
        else:
            g = by_number.get(int(chosen))
            if g:
                return g, "직접 지정"
    overlap = lambda g: len(members_set & set(g["codes"]))
    named = [g for g in groups if overlap(g) >= 1 and any(w in g["text"] for w in keywords(theme_name))]
    if named:
        best = max(named, key=lambda g: (overlap(g), -g["number"]))
        return best, f"이름 일치 · 겹침 {overlap(best)}/{len(members_set)}"
    ranked = sorted(groups, key=lambda g: (-overlap(g), g["number"]))
    if ranked:
        best = ranked[0]
        shared = overlap(best)
        if shared >= MIN_OVERLAP and shared >= MIN_OVERLAP_SHARE * max(1, len(members_set)):
            return best, f"종목 겹침 {shared}/{len(members_set)}"
    return None, "관심종목 없음"


def candidates(base, edit, prices):
    """Base pool plus added stocks; returns (kept after removals, everything for the editor)."""
    known = {s["code"]: s for s in base}
    for code in edit.get("add", []):
        if code not in known and code in prices:
            known[code] = dict(prices[code], added=True)
    every = list(known.values())
    return [s for s in every if s["code"] not in edit.get("remove", [])], every


def build(api, groups, manual, edits=None):
    edits = edits or {"themes": {}, "custom": []}
    top = ranking(api)
    usable = theme_groups(groups)
    choices = {**manual, **{name: e["group"] for name, e in edits["themes"].items() if "group" in e}}
    mine = {"c:" + e["id"]: {"number": "c:" + e["id"], "name": e["name"], "codes": e["codes"]} for e in edits["custom"]}
    matched = []
    for theme in top:
        kiwoom_stocks = members(api, theme["code"])
        group, reason = match(theme["name"], [s["code"] for s in kiwoom_stocks], usable, choices, mine)
        theme["member_codes"] = [s["code"] for s in kiwoom_stocks]
        matched.append((theme, kiwoom_stocks, group, reason))
    wanted = [c for _, _, g, _ in matched if g for c in g["codes"]]
    wanted += [c for e in edits["themes"].values() for c in e["add"]] + [c for e in edits["custom"] for c in e["codes"]]
    prices = quotes(api, wanted)
    for theme, kiwoom_stocks, group, reason in matched:
        edit = edits["themes"].get(theme["name"], {})
        if group:
            kept, every = candidates([prices[c] for c in group["codes"] if c in prices], edit, prices)
            theme.update(source="watchlist", group={"number": group["number"], "name": group["name"],
                         "size": len(group["codes"]), "reason": reason},
                         leaders=arrange(kept, edit.get("pin", []), LEADERS))
        if not group or not theme["leaders"]:
            kept, every = candidates(kiwoom_stocks, edit, prices)
            theme.update(source="kiwoom", group=None, match_note=reason, leaders=arrange(kept, edit.get("pin", []), LEADERS))
        theme["candidates"] = [{k: s[k] for k in ("code", "name", "rate")} for s in every]
        if edit:
            theme["edited"] = {"group": "group" in edit, "add": len(edit["add"]), "remove": len(edit["remove"]), "pin": len(edit["pin"])}
    return top, custom_themes(edits["custom"], prices)


def custom_themes(entries, prices):
    result = []
    for entry in entries:
        stocks = [prices[c] for c in entry["codes"] if c in prices]
        rates = [s["rate"] for s in stocks]
        result.append({"code": "c:" + entry["id"], "id": entry["id"], "name": entry["name"], "source": "custom",
                       "rate": round(sum(rates) / len(rates), 2) if rates else 0.0, "stocks": len(stocks),
                       "rising": sum(r > 0 for r in rates), "falling": sum(r < 0 for r in rates),
                       "leaders": arrange(stocks, entry["pin"], MAX_CUSTOM_CODES)})
    result.sort(key=lambda t: -t["rate"])
    return result


def write(data, day, snapshot):
    path = day_path(data, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = read_day(data, day) or {}
    history = previous.get("history", [])
    moment = {"at": snapshot["updated_at"][11:16],
              "themes": [{"code": t["code"], "name": t["name"], "rate": t["rate"]} for t in snapshot["themes"]]}
    if history and history[-1]["at"] == moment["at"]:
        history[-1] = moment
    else:
        history.append(moment)
    record = {**snapshot, "day": day, "history": history[-HISTORY_LIMIT:]}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    prune(data)
    return record


def prune(data):
    """Only dated theme files inside data/themes are ever removed."""
    root = folder(data).resolve()
    for day in days(data)[KEEP_DAYS:]:
        path = (root / f"{day}.json").resolve()
        if path.parent == root and path.is_file() and not path.is_symlink():
            path.unlink()


def refresh(data, day):
    """Called only after the same day's minute collection succeeded, so holidays are never stored."""
    global CLIENT
    import watchlists
    with LOCK:
        CLIENT = CLIENT or Kiwoom()
        try:
            groups, note = watchlists.groups(), ""
        except DataError as exc:
            groups, note = [], f"관심종목을 읽지 못해 키움 종목으로 표시: {exc}"
        edits = read_edits(data)
        top, custom = build(CLIENT, groups, manual_map(data), edits)
        if datetime.now(KST).date().isoformat() != day:
            raise DataError("테마 수집 도중 날짜가 바뀌었습니다.")
        snapshot = {"updated_at": datetime.now(KST).isoformat(timespec="seconds"),
                    "rule": f"테마 평균 등락률 상위 · 구성 {MIN_STOCKS}종목 이상 · 상승 테마만 · 종목은 내 관심종목 그룹 등락률 상위 {LEADERS}",
                    "watchlist_note": note, "themes": top, "custom": custom, "edits_revision": edits["revision"]}
        return write(data, day, snapshot)
