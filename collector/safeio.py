"""Shared file-safety helpers and the persistent collector error journal.

Added 2026-11-16 (reliability repair). Three recurring Windows failure modes are
handled here once so every collector module behaves the same way:

1. os.replace() raises PermissionError while the dashboard (or antivirus/backup)
   has the destination open. -> retry briefly instead of failing the collection.
2. A JSON file is unreadable (power loss, half-synced copy). -> keep a ``.bad``
   copy for inspection, log it, and let the caller fall back instead of crashing.
3. Errors used to live only in a single overwritten ``last_error.json``.
   -> every error is appended to ``data/logs/errors-YYYY-MM-DD.jsonl``.

Nothing here talks to the network. Secrets never enter the journal: callers pass
only API ids, stock codes and exception text; messages are length-limited.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
LOG_ROOT = Path(__file__).resolve().parent / "data"
_DEFAULT_ROOT = LOG_ROOT
LOG_KEEP_DAYS = 45
_LOG_LOCK = threading.Lock()
_PRUNED_DAY = ""
REPLACE_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.5)


def replace(tmp, path):
    """os.replace with short retries for transient Windows sharing violations."""
    last = None
    for delay in (0.0, *REPLACE_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            last = exc
    log_error("file.replace", last, file=Path(path).name)
    raise last


def write_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(content)
    replace(tmp, path)


def load_json(path, fallback=None, *, root=None):
    """Read JSON; a corrupt file is set aside as ``.bad`` and ``fallback`` returned."""
    path = Path(path)
    last = None
    for delay in (0.0, 0.1, 0.3):
        if delay:
            time.sleep(delay)
        try:
            if not path.is_file():
                return fallback
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError as exc:      # being replaced right now
            last = exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            last = exc
    if isinstance(last, PermissionError):
        log_error("file.read", last, root=root, file=path.name)
        raise last
    bad = path.with_name(path.name + ".bad")
    try:
        os.replace(path, bad)
    except OSError:
        pass
    log_error("file.corrupt", last, root=root, file=path.name, moved_to=bad.name)
    return fallback


def describe(exc):
    """Short, secret-free text for an exception."""
    text = str(exc).replace("\n", " ").strip()
    return f"{type(exc).__name__}: {text}"[:300] if text else type(exc).__name__


def log_error(where, error, *, root=None, **fields):
    """Append one line to the daily error journal. Never raises."""
    global _PRUNED_DAY
    try:
        if root is None and LOG_ROOT == _DEFAULT_ROOT and "unittest" in sys.modules:
            return   # offline tests must not write into the real journal
        at = datetime.now(KST)
        folder = Path(root or LOG_ROOT) / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        entry = {"at": at.isoformat(timespec="seconds"), "where": str(where)[:60],
                 "error": describe(error) if isinstance(error, BaseException) else str(error)[:300]}
        entry.update({k: (v if isinstance(v, (int, float, bool)) or v is None else str(v)[:200])
                      for k, v in fields.items()})
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        day = at.strftime("%Y-%m-%d")
        with _LOG_LOCK:
            with open(folder / f"errors-{day}.jsonl", "a", encoding="utf-8") as handle:
                handle.write(line)
            if _PRUNED_DAY != day:
                _PRUNED_DAY = day
                limit = (at - timedelta(days=LOG_KEEP_DAYS)).strftime("%Y-%m-%d")
                for old in folder.glob("errors-*.jsonl"):
                    if old.stem[7:] < limit:
                        try:
                            old.unlink()
                        except OSError:
                            pass
    except Exception:
        pass


def recent_errors(root=None, limit=200, day=None):
    folder = Path(root or LOG_ROOT) / "logs"
    day = day or datetime.now(KST).strftime("%Y-%m-%d")
    path = folder / f"errors-{day}.jsonl"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows
