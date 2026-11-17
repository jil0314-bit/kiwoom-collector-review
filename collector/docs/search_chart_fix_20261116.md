# 전체 시장 검색 차트와 오류 3건 수정 · 2026-11-16

## 범위

- 오류 파일 저장 실패가 사유/메모 확인 이후의 자동 수집을 중단하지 않도록 보호한다.
- 상승률 및 테마 작업의 시작 준비/스레드 시작 실패 시 공유 잠금과 실행 상태를 해제한다.
- 거래량 분봉 재시도 성공 시 종목 목록에 남은 이전 오류를 제거하여 저장 건수/마감 완료를 정상 판정한다.
- 기존 부분 실패 보존, 종목 조건, 주문 경로, 영웅문 조회 전용 경계는 유지한다.

## 전체 시장 검색

상승률 상위와 관찰종목의 검색창에서 종목명/코드를 입력 → 검색 결과의 종목명 클릭 → 기존 차트 표시 → `＋ 관찰종목 담기` 클릭.

- 수집/관찰 이력이 없는 종목도 검색·차트 조회가 가능하다. 차트 미리보기만으로 관찰 목록에 쓰지 않는다.
- 키움 `ka10099`의 코스피·코스닥·코넥스·인프라투융자·리츠·ETF·ETN 목록을 사용한다. 순위 수집의 ETF/ETN 제외 조건은 바꾸지 않는다.
- 차트는 기존 `chart_data`의 일·주·월·1/3/5분봉 경로를 재사용한다. 거래정지·신규상장·외부 API 미제공 시 없는 봉을 만들지 않는다.
- 종목 목록 확보 실패 시 이전 시장 목록을 사용하고 기준일을 표시한다. 수집된 종목만을 전체 시장 검색 결과처럼 대체하지 않는다.
- 종목명 일치 우선, 코드 검색, 한글 검색, 중복 관찰 추가 방지, 파일 재조회 후 관찰 목록 유지.
- 주기/현재차트 전환과 자동 목록 갱신 동안 검색 종목 선택을 보존한다. 기존 목록 종목을 클릭하면 기존 차트 경로로 돌아간다.
- 보관 자료가 없는 첫 화면에서 날짜 표시가 반복 갱신되던 문제도 막았다.

## 검증

`test_search_chart.py`는 임시 폴더/모의 API로 오류 3건과 미수집 종목 차트/저장/중복/없는 코드 거부를 검사한다. `test_search_chart_ui.cjs`는 실제 요청을 차단한 브라우저에서 두 화면의 검색→차트→주기 전환→저장→새로고침 및 좁은 화면을 검사한다.

```powershell
cd collector
python -B -m unittest test_search_chart test_reliability test_volume_surge test_collector test_observations test_investor_flows test_chart_data test_chart_service test_shared_archive test_stock_profiles test_themes
$env:COLLECTOR_BROWSER_EXE='C:\Program Files\Google\Chrome\Application\chrome.exe'
node test_search_chart_ui.cjs
```

- Windows Python 회귀 검사: 142개 통과.
- 모의 브라우저: 상승률 상위/관찰종목 두 화면의 검색·차트·월봉 전환·관찰 추가·재조회·좁은 화면 통과.
- 기존 추천 화면/빠른 차트/영웅문 재시도 UI 검사 통과. 실제 0600 화면 전환은 미검증.
- 배포 manifest 94개 파일 해시 일치.

실서버/물리적 영웅문 화면 검증은 오프라인 검사와 별도로 보고한다. 기존 GitHub `fa31f50`은 수정 전 검토 버전이다.
