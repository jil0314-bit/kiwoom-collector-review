"""Read the selected Hero4 0130 groups without modifying Hero4 files."""
from pathlib import Path
import re

from kiwoom import DataError, code_of


# This is the 0130 profile verified on this PC. Never silently switch accounts.
SOURCE = Path(r"C:\KiwoomHero4\user\#Q2gsNx0%Eg$$\Portfolio.dat")
MASTER = Path(r"C:\KiwoomHero4\screen\bpl\JMaster.Dat")
SELECTED = tuple(i for i in range(1, 68) if i not in {1, 2, 5, 7, 8}) + (98, 99)


def groups(path=SOURCE):
    try:
        lines = path.read_text(encoding="cp949").splitlines()
    except (OSError, UnicodeError) as exc:
        raise DataError("영웅문 0130 관심종목 파일을 읽을 수 없습니다.") from exc
    parsed = {}
    group = None
    for line in lines:
        section = re.fullmatch(r"\[(\d{3})\]", line.strip())
        if section:
            number = int(section.group(1))
            group = {"number": number, "name": "", "entries": [], "expected": None}
            parsed[number] = group
        elif group is not None:
            if line.startswith("GName="):
                group["name"] = line[6:]
            elif line.startswith("ItemCnt="):
                group["expected"] = int(line[8:])
            elif re.match(r"^\d{3}=", line):
                parts = line.split("=", 1)[1].split(";")
                if parts[0] == "BLANK":
                    group["entries"].append({"type": "heading", "label": parts[2] if len(parts) > 2 else ""})
                else:
                    group["entries"].append({"type": "stock", "code": code_of(parts[0])})
    result = []
    for number in SELECTED:
        group = parsed.get(number)
        # A deleted group is not a failure of the remaining 0130 profile.
        if not group or not group["name"]:
            continue
        if group["expected"] != len(group["entries"]):
            raise DataError(f"영웅문 관심종목 {number:02d}번 그룹이 없거나 저장 개수가 맞지 않습니다.")
        result.append({"number": number, "name": group["name"], "entries": group["entries"]})
    if not result:
        raise DataError("영웅문 0130에 선택된 관심종목 그룹이 없습니다.")
    return result


def contains(code, group_number=None, path=SOURCE):
    code = code_of(code)
    return any((group_number is None or g["number"] == group_number) and
               any(e.get("code") == code for e in g["entries"])
               for g in groups(path))


def names(path=MASTER):
    """Hero4's local 33-byte code/name records; missing names remain code-only."""
    try:
        content = path.read_bytes()
    except OSError:
        return {}
    result = {}
    for offset in range(0, len(content) - 32, 33):
        row = content[offset:offset + 33]
        if row[6] == 0 and re.fullmatch(rb"[A-Z0-9]{6}", row[:6]):
            name = row[7:].split(b"\0", 1)[0].decode("cp949", errors="replace").strip()
            if name:
                result[row[:6].decode("ascii")] = name
    return result
