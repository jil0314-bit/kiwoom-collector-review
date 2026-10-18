import tempfile
import unittest
from pathlib import Path

import hero4memo


def encode(text):
    """Inverse of decode_line, for fixtures."""
    out = []
    for i, ch in enumerate(text.encode("cp949").hex().upper()):
        out.append(chr(ord(ch) + hero4memo.KEY[i % len(hero4memo.KEY)]))
    return "".join(out).encode("latin1")


class Hero4MemoTest(unittest.TestCase):
    def test_decodes_shifted_hex_lines(self):
        raw = b"\r\n".join([encode(";종목코드=메모 데이터"), encode("012160=자사주 보유\u2126\u21262/20/26/ 급등")])
        self.assertEqual(hero4memo.parse(raw), {"012160": "자사주 보유\u2126\u21262/20/26/ 급등"})

    def test_keeps_this_year_and_top_notes_only(self):
        text = "\u2126".join(["자사주 32.78% 보유", "9/2/26/ 계약 체결에 급등", "", "4/17/2026/ 코로나 테마",
                              "11/28/25/ 로봇 테마", "#로봇 관련주", "3/7/26/ 공급계약", "2/25/ 연도 없는 옛 메모"])
        self.assertEqual(hero4memo.this_year(text, 2026),
                         "자사주 32.78% 보유\n9/2/26/ 계약 체결에 급등\n4/17/2026/ 코로나 테마\n3/7/26/ 공급계약")
        self.assertEqual(hero4memo.this_year("2/25/ 연도 없음\u2126기사 본문", 2026), "")
        self.assertEqual(hero4memo.this_year("9/12.26/ 점 구분\u21262026.03.05 연월일", 2026), "9/12.26/ 점 구분\n2026.03.05 연월일")

    def test_load_filters_and_rereads_only_on_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jongMemoEnc.dat"
            path.write_bytes(b"\r\n".join([encode("000001=1/5/26/ 올해"), encode("000002=1/5/25/ 작년")]))
            self.assertEqual(hero4memo.load(path, 2026), {"000001": "1/5/26/ 올해"})
            path.write_bytes(encode("000003=2/1/26/ 새 메모 추가됨"))
            self.assertEqual(hero4memo.load(path, 2026), {"000003": "2/1/26/ 새 메모 추가됨"})
            self.assertEqual(hero4memo.load(Path(tmp) / "missing.dat", 2026), {})


if __name__ == "__main__":
    unittest.main()
