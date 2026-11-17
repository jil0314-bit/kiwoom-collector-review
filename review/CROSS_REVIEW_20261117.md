# 2026-11-17 검토용 갱신

기준 부모: `fa31f50c3e4ecc8b34b71aa9f2e7b6fe0b795a2a`. 검토할 때는 이 문서가 포함된 최종 커밋의 전체 SHA를 고정하세요.

## 포함 내용
- 상승 사유: 키움/공개 급등 기사의 원문 코드와 저장 수 대조, 로컬 파일 실패와 공개 조회 분리, 작업 시작 실패 후 잠금 상태 해제, 최근 10개 저장 거래일 재확인, 코스피·코스닥 특징 기사에서 상승 종목 사유 추가.
- 전체 시장 종목 검색 → 차트 미리보기 → 명시적인 관찰종목 추가. 수집 이력이 없는 종목도 조회하며 6개 봉 주기를 재사용한다.
- 이전 검토에서 재현한 수집 오류 3건: 오류 기록 실패로 스케줄러 종료, 작업 준비/스레드 시작 실패로 잠금 고정, 거래량 재수집 성공 후 과거 오류 잔존.
- 수정본이 사용하는 기존 신뢰성 보완(safeio, 부분 실패 보존, 재시도)과 관련 화면/테스트를 작업 폴더의 현재 통합 소스로 함께 보관한다. 변경된 파일 모두가 이번 상승 사유 작업에서 새로 작성된 것은 아니다.

## 이 공개용 복사본에서 실행한 검사
```powershell
cd collector
python -B -m unittest test_reasons test_reason_memos test_notes test_search_chart test_collector test_reliability test_observations test_volume_surge test_investor_flows test_chart_data test_chart_service test_themes
```
176개 통과. 임시 폴더/모의 응답을 사용했다. 운영 데이터는 넣지 않았다.

메모 표시 검사는 저장소 루트의 `python -B review/run_notes_display_test.py`로 합성 자료를 만들어 실행할 수 있다. `collector/test_notes_display.cjs`를 직접 실행하면 비공개 과거 데이터가 없어 실패할 수 있다.

검색 화면은 Playwright와 Chromium/Chrome이 있는 환경에서 `node collector/test_search_chart_ui.cjs`로 검사한다. 실제 브라우저 경로를 `COLLECTOR_BROWSER_EXE`로 지정할 수 있다. 요청은 합성 응답으로 대체되며 주문이나 실제 관찰 목록 쓰기는 수행하지 않는다.

## 11월 17일 운영 PC에서 별도 확인한 결과
- 캡처 급등 기사 31종목의 사유 저장·표시 일치. 추가 특징 기사로 당일 56종목 사유 확보.
- 최근 7거래일 날짜별 총 427건, 기존 대비 133건 추가. 급등 기사 원문 기대 280건/저장 280건/누락 0건.
- 실제 화면 날짜 탭 전환 및 427건 표시 대조에서 누락/자바스크립트 오류 0건. 날짜별 첫/마지막 종목 메모 팝업 확인.
- 검증 시점 오늘 상위 100종목 중 확정 기사 사유는 44종목이다. 56건을 상위 100종목 전체 사유 확보로 해석하면 안 된다.
- 수집기 재시작과 거래량 자동수집 설정 복구를 확인했다. 물리적 0600 화면 표시·Hero4 메모 쓰기·다른 PC 설치·미래 무중단 동작은 검증하지 않았다.
- `REASONS_DAILY_VALIDATION_20261117.json`에는 날짜별 집계와 표시 검사 결과만 포함했다. 기사 원문, 종목별 개인 메모, 운영 로그는 제외했다.

## 범위와 재현성
`collector/docs/reasons_daily_fix_20261117.md`, `collector/docs/search_chart_fix_20261116.md`, `collector/docs/reliability_fix_20261116.md`에 세부 범위가 있다. 공개본의 release_manifest와 PUBLICATION_MANIFEST는 실제 업로드 파일로 재계산했다. 인증/수집 데이터, 로그, 캡처, 런타임 및 새 ZIP은 포함하지 않는다. 기존 downloads와 이전 review 문서는 과거 자료이며 이번 수정이 포함된 새 설치 ZIP을 뜻하지 않는다.
