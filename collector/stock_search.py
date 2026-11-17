"""Whole-market stock name/code search for adding any stock to 관찰종목.

Added 2026-11-16 at the user's request: a stock found by search can be saved to
the observation list even when it is not in today's ranking.

The listed-stock/ETF/ETN master comes from ka10099 (read-only), is cached once a
day in ``data/stock_master.json`` and is reused when today's lookup fails.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

import safeio
from kiwoom import DataError, KST, code_of

LOCK = threading.Lock()
MARKETS = (("0", "코스피"), ("10", "코스닥"), ("50", "코넥스"),
           ("2", "인프라투융자"), ("6", "리츠"), ("8", "ETF"),
           ("60", "ETN"), ("70", "손실제한 ETN"), ("90", "변동성 ETN"))
MASTER_SCHEMA = 2
_memory_root = None
RETRY_SECONDS = 600
_last_attempt = 0.0
_memory = {"day": "", "items": {}}


def _path(data):
    return data / "stock_master.json"


def fetch(call):
    items = {}
    for market, label in MARKETS:
        cursor, seen = "", set()
        for _ in range(100):
            payload, header = call("ka10099", {"mrkt_tp": market}, cursor)
            if payload.get("return_code", 0) not in (0, "0"):
                raise DataError(label + " 종목 목록 조회 실패")
            header = {k.lower(): v for k, v in header.items()}
            rows = payload.get("list")
            if not isinstance(rows, list):
                raise DataError(label + " 종목 목록 확인 실패")
            for row in rows:
                try:
                    code = code_of(row.get("code", ""))
                except DataError:
                    continue
                name = str(row.get("name", "")).strip()
                if name:
                    items.setdefault(code, {"name": name[:60], "market": label})
            if header.get("cont-yn") != "Y":
                break
            cursor = str(header.get("next-key", ""))
            if not cursor or cursor in seen:
                raise DataError(label + " 종목 목록 연속조회 키 누락·반복")
            seen.add(cursor)
        else:
            raise DataError(label + " 종목 목록 연속조회 한도 초과")
    if len(items) < 500:
        raise DataError("종목 목록이 비정상적으로 적습니다. 기존 목록 유지")
    return items


def master(data, call=None, today=None):
    """Today's master if obtainable, otherwise the last saved one (possibly empty)."""
    global _last_attempt, _memory_root
    today = today or datetime.now(KST).strftime("%Y-%m-%d")
    with LOCK:
        location = str(data.resolve())
        if _memory_root != location:
            _memory_root = location
            _memory.clear()
            _memory.update(day="", items={})
            _last_attempt = 0.0
        if _memory["day"] != today or not _memory["items"]:
            saved = safeio.load_json(_path(data), None, root=data) or {}
            if saved.get("items") and (saved.get("day", "") >= _memory["day"] or not _memory["items"]):
                _memory.update(day=saved.get("day", ""), items=saved["items"], schema=saved.get("schema"))
        if _memory["day"] == today and _memory["items"] and _memory.get("schema") == MASTER_SCHEMA:
            return _memory["items"], today
        if time.monotonic() - _last_attempt < RETRY_SECONDS and _last_attempt:
            return _memory["items"], _memory["day"]
        _last_attempt = time.monotonic()
        try:
            if call is None:
                import volume_surge
                call = volume_surge.request
            items = fetch(call)
            import json
            safeio.write_bytes(_path(data), json.dumps({"schema": MASTER_SCHEMA, "day": today, "items": items}, ensure_ascii=False).encode("utf-8"))
            _memory.update(day=today, items=items, schema=MASTER_SCHEMA)
        except Exception as exc:
            safeio.log_error("search.master", exc, root=data)
        return _memory["items"], _memory["day"]


def lookup(data, code, call=None, extra=None):
    code = code_of(code)
    items, _ = master(data, call)
    if code in items:
        return {"code": code, **items[code]}
    return None


def search(data, query, limit=12, call=None, extra=None):
    """Search the exchange master independently of collected/observed stocks."""
    text = str(query or "").strip().upper()
    if len(text) < 2:
        return [], ""
    items, day = master(data, call)
    pool = items
    found = []
    for code, info in pool.items():
        name = info["name"].upper()
        if code == text or name == text:
            score = 0
        elif name.startswith(text) or code.startswith(text):
            score = 1
        elif text in name:
            score = 2
        else:
            continue
        found.append((score, len(name), info["name"], code, info.get("market", "")))
    found.sort()
    return [{"code": code, "name": name, "market": market} for _, _, name, code, market in found[:limit]], day
