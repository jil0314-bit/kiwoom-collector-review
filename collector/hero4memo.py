"""Hero4 종목 메모(jongMemoEnc.dat), read only. Only this year's dated lines are shown."""
import re
import threading
from datetime import datetime
from pathlib import Path

from kiwoom import KST

HERO4_MEMO = Path(r"C:\KiwoomHero4\user\#Q2gsNx0%Eg$$\jongMemoEnc.dat")
KEY = (1, 1, 0, 0, 0, 0, 0, 0, 0, 0)
ENTRY = re.compile(r"^([0-9A-Z]{6})=(.*)$", re.S)
BREAK = re.compile("\u2126+")
MDY = re.compile(r"^\s*\d{1,2}\s*[/.]\s*\d{1,2}\s*[/.]\s*(\d{4}|\d{2})(?!\d)")
YMD = re.compile(r"^\s*(20\d{2})\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{1,2}(?!\d)")
NO_YEAR = re.compile(r"^\s*\d{1,2}\s*[/.]\s*\d{1,2}\s*[/.]?(?!\d)")
LOCK = threading.Lock()
CACHE = {"stamp": None, "memos": {}}


def decode_line(line):
    """Each byte is two hex characters; some positions are shifted up by one character."""
    out = bytearray()
    for i in range(0, len(line) - 1, 2):
        pair = []
        for j in (i, i + 1):
            v = line[j] - KEY[j % len(KEY)]
            pair.append((v - 48 if v <= 57 else v - 55) & 15)
        out.append(pair[0] << 4 | pair[1])
    return out.decode("cp949", errors="replace")


def parse(raw):
    memos = {}
    for line in raw.split(b"\r\n"):
        m = ENTRY.match(decode_line(line))
        if m:
            memos[m.group(1)] = m.group(2)
    return memos


def line_year(line):
    m = MDY.match(line) or YMD.match(line)
    if m:
        year = int(m.group(1))
        return year + 2000 if year < 100 else year
    return 0 if NO_YEAR.match(line) else None


def this_year(text, year):
    """Undated lines above the first date are kept; undated lines below a date are older notes."""
    kept, dated = [], False
    for line in BREAK.split(text):
        line = line.rstrip()
        if not line.strip():
            continue
        found = line_year(line)
        if found is None:
            if not dated:
                kept.append(line)
            continue
        dated = True
        if found == year:
            kept.append(line)
    return "\n".join(kept)


def load(path=HERO4_MEMO, year=None):
    """Re-reads the file only when Hero4 changed it."""
    year = year or datetime.now(KST).year
    try:
        st = path.stat()
    except OSError:
        return {}
    stamp = (st.st_mtime_ns, st.st_size, year)
    with LOCK:
        if CACHE["stamp"] != stamp:
            try:
                raw = path.read_bytes()
            except OSError:
                return CACHE["memos"]
            memos = {}
            for code, text in parse(raw).items():
                kept = this_year(text, year)
                if kept:
                    memos[code] = kept
            CACHE.update(stamp=stamp, memos=memos)
        return CACHE["memos"]
