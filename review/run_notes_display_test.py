"""Run the exact archived UI test against temporary synthetic fixtures, never private data."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="collector-review-") as temp:
    root = Path(temp)
    (root / "web").mkdir()
    shutil.copyfile(ROOT / "collector" / "test_notes_display.cjs", root / "test_notes_display.cjs")
    shutil.copyfile(ROOT / "collector" / "web" / "notes.js", root / "web" / "notes.js")
    folder = root / "data" / "reasons"
    folder.mkdir(parents=True)
    for day, count in [("2026-11-02", 42), ("2026-11-03", 17), ("2026-11-04", 54),
                       ("2026-11-05", 25), ("2026-11-06", 13)]:
        items = {f"{i:06d}": {"reason": f"합성 검증 종목 {i}의 수주 소식에 급등", "source": "synthetic"}
                 for i in range(count)}
        (folder / (day + ".json")).write_text(
            json.dumps({"infostock": {"items": items}}, ensure_ascii=False), encoding="utf-8")
    print("Synthetic fixtures only; this is not a live-market/article verification.", flush=True)
    result = subprocess.run(["node", str(root / "test_notes_display.cjs")], check=False)
    raise SystemExit(result.returncode)

