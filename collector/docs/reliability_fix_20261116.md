# 수집기 반복 오류 수리 · 종목검색 → 관찰종목 담기 (2026-11-16, Claude)

사용자(형) 승인 내용: ① 반복 오류 수리 진행 ② 끝내 실패한 종목은 누락 표시하고 나머지는 저장 ③ 전용 앱키는 나중(지금은 대시보드와 같은 키 유지) ④ 상승률 상위·관찰종목 탭에서 검색한 종목을 바로 관찰종목에 담기.
수정 전 기준: 커밋 c772b07 + 미커밋 작업본(2026-11-16 09:38 app.py 기준). 순위 조건·테마·수급·추천·영웅문 연동·화면 디자인은 바꾸지 않았다.

## 1. 왜 자주 깨졌나 (수리 전)
1. 3분마다 100종목을 통째로 받아 **1종목만 실패해도 회차 전체 폐기**(`build_snapshot`). 11/10 최종본 없음, 11/12 최종 23:56, 10/26 최종 21:43.
2. 분봉 검사가 한 줄만 어긋나도 종목 전체 실패: 밀리초가 붙은 시각, 진행 중인 봉이 페이지 사이에 자란 경우("같은 시각 분봉 값 충돌").
3. 실패 원인이 남지 않음: `last_error.json` 1건 덮어쓰기 + DataError가 아니면 "파일 권한·디스크 상태" 한 문장으로 가림.
4. 윈도우 파일: `os.replace`가 읽는 중인 파일에서 PermissionError → 재시도 없음. 깨진 JSON을 읽으면 그대로 예외.
5. 수집 한 바퀴(110~220초)가 주기(180초)보다 길어 쉬는 틈 없이 조회 → 다른 탭·자동매매 대시보드와 조회 한도 경쟁.
6. 20:05 최종 수집은 5회 실패하면 그날 포기.
7. 같은 앱키를 자동매매 대시보드와 같이 써서 토큰이 서로 무효화(코드 3)되면 즉시 재발급 → 서로 되뺏기.

## 2. 무엇을 바꿨나
| 파일 | 변경 |
|---|---|
| `safeio.py` (신규) | `replace`(PermissionError 6회 짧게 재시도), `load_json`(깨진 파일은 `.bad`로 옮기고 fallback), `log_error`(오류 일지 `data/logs/errors-YYYY-MM-DD.jsonl`, 45일 보관). 단위시험 중에는 실제 일지에 쓰지 않음 |
| `kiwoom.py` | `parse_bar`: 15~20자리 숫자 시각은 앞 14자리 사용. `minute_bars`: 형식이 깨진 행은 종목당 3개까지 제외·기록(`raw.dropped_rows`), 4개부터 실패. 진행 중인 봉이 자란 경우(시가 같고 고가↑·저가↓·거래량↑)는 최신 값 채택, 그 외 충돌은 기존대로 실패. 재시도·토큰 무효를 일지에 기록. 코드 3 재발급 전 2초 대기 |
| `app.py` | `build_snapshot`: 실패 종목만 최대 2회 재시도(실패 30종목 초과면 장애로 보고 재시도 안 함) → 실패가 10% 이하면 게시. 실패 종목은 직전 스냅샷의 분봉을 이어 받아 `carried: true`, 직전 자료도 없으면 `status: error`. `index.json`에 `missing: [{code,name,error,carried}]`, `saved`=새로 받은 수. 10% 초과면 기존대로 교체 보류. 첫 종목 확인은 상위 3종목 중 하나만 성공하면 통과. 스케줄: 끝난 뒤 40초 휴식(`REST_AFTER_FINISH`), 최종 수집은 횟수 제한 없이 21:55까지(3회까지 15분, 이후 20분 간격), 누락이 있는 최종본은 총 3회까지 다시 시도. `safe_error`는 실제 예외 종류·내용 표시. 스케줄러가 삼키던 예외를 모두 일지에 기록. `GET /api/errors?day=` 추가 |
| `archive.py` | `latest.json`이 깨졌으면 가장 최근 완료 스냅샷으로 대체 |
| `investor_flows.py` `volume_surge.py` `chart_data.py` `stock_profiles.py` `stock_sectors.py` `themes.py` `notes.py` `observations.py` | `os.replace` → `safeio.replace`. 수급·거래량은 JSON 읽기도 `safeio.load_json`, 실패를 일지에 기록 |
| `stock_search.py` (신규) | ka10099(코스피·코스닥, 조회 전용)로 전체 종목 목록을 하루 1회 받아 `data/stock_master.json`에 보관. 실패 시 이전 목록 + 수집기가 이미 아는 종목명으로 검색, 10분 뒤 재시도 |
| `observations.py` | 출처 `search`(표시 "종목 검색") 추가 |
| `web/stock-search-add.js` `.css` (신규), `index.html`, `observations.html` | 검색창에 2글자 이상 입력하면 아래에 전체 종목 검색 결과와 "＋ 관찰종목 담기" 버튼. 기존 목록 걸러보기 동작은 그대로 |
| `test_reliability.py` (신규 20개), `test_collector.py`(최종 재시도 시험 1개를 새 기준으로 수정) | |

## 3. 검증
- 오프라인 시험: test_reliability 20, test_collector 19, test_kiwoom_coordination 4, test_volume_surge 10, test_investor_flows 29, test_themes 13, test_observations 4, test_stock_profiles 6, test_stock_sectors 5, test_volume_top 7, test_reasons 21, test_recommendations 33, test_shared_archive 3, test_hero4memo 3, test_chart_service 8 — 모두 통과 (Linux, Python 3.12).
- 화면: 가짜 자료로 서버를 띄워 상승률 상위·관찰종목 두 탭에서 검색 → 담기 → 목록 반영을 브라우저로 확인.
- Windows 전용 모듈(msvcrt, PIL, hero4_daily_memo)이 필요한 시험은 이 환경에서 수정 전에도 실행 불가였다: test_notes, test_reason_memos, test_hero_link, test_chart_data, test_notes_display.cjs.

## 4. 확인하지 못한 것 (정직하게)
- **실제 키움 서버 응답으로는 검증하지 못했다.** 수리 후 첫 장중 하루의 `data/logs/errors-*.jsonl`로 확인해야 한다.
- 밀리초 시각(`cntr_tm` 17자리)은 자동매매 대시보드 쪽 API 기록에서 본 것이고, 수집기에서 직접 터진 기록은 없다(기록 자체가 없었음).
- ka10099 응답의 `code`·`name` 필드는 기존 `volume_top.py` 사용 방식과 키움 문서 기준이며 실서버 확인 전이다. 실패해도 수집에는 영향이 없고 검색만 "이미 아는 종목"으로 좁아진다.
- 제안했던 "늘어난 분봉만 받기"와 "다음날 전날 최종본 자동 보충"은 넣지 않았다. 앞의 것은 이동평균 계산이 바뀔 위험 대비 절감이 작고(종목당 1~2회 조회), 뒤의 것은 과거 날짜 순위를 다시 받을 수 없어 실서버 검증 없이는 위험하다. 대신 휴식 간격과 21:55까지 재시도로 대응했다.
- 토큰 되뺏기는 완화일 뿐이다. 근본 해결은 수집기 전용 앱키.

## 5. 다른 AI에게
- 종목 1개 실패로 스냅샷 전체를 버리는 방식으로 되돌리지 말 것. `index.json`의 `missing`·`carried`를 읽어 표시를 개선하는 것은 환영.
- 파일 교체는 `safeio.replace`, 상태 JSON 읽기는 `safeio.load_json`, 오류는 `safeio.log_error(where, exc, root=DATA, ...)`를 쓸 것.
- 오류를 볼 때는 `data/logs/errors-날짜.jsonl` 또는 `http://127.0.0.1:8766/api/errors?day=YYYY-MM-DD`.
- 줄바꿈: `app.py` `kiwoom.py` `investor_flows.py` `chart_data.py` `stock_sectors.py` `test_collector.py` `web/observations.html`은 CRLF, 나머지 수정 파일은 LF 그대로 유지했다.
