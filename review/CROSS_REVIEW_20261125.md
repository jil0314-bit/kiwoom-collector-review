# 직접 추천 등록·공통 메모·화면 배치

기준 부모 커밋: `5f3edc040ed77d2ddf2595dc3d5eaab85735b611`. 검토 시 현재 커밋 전체 SHA를 고정하세요.

## 범위
- recommendations.add_manual: 기존 시장 마스터 검증, 서버 한국 시각 입력일, 같은 날/종목 중복 방지, 수집 병합 잠금 재사용.
- notes.latest 및 GET /api/notes/latest: 날짜별 개인 메모를 변경하지 않고 최신 수정본 표시. 기존 notes.write와 revision 충돌 계약 유지.
- POST /api/recommendations/manual: 기존 로컬 인증 적용. 기존 개인 메모를 덮어쓰지 않습니다.
- stock-tools.js/css: 8개 탭 공통 삼각형/메모장/최신 미리보기, 작은 제목/가로 날짜/접힌 설명과 같은 목록·차트 폭 비율. 시계 및 차트 동작은 유지.
- recommendations.js: 전체 시장 검색 선택→직접 등록→실제 입력일 목록→공통 메모장.

## 검증과 한계
- Python: `python -m unittest test_manual_memos test_recommendations test_search_chart test_observations test_chart_service test_chart_data` (collector 폴더, 82개).
- 브라우저: `test_common_memos_ui.cjs`, `test_recommendations_ui.cjs`, `test_search_chart_ui.cjs`; Playwright와 Chrome 필요. 브라우저 경로는 `COLLECTOR_BROWSER_EXE`로 지정합니다. 합성 요청/응답을 사용해 실제 데이터에 쓰지 않습니다.
- `node collector/test_chart_fast.cjs`: 기존 차트 캐시·경합·오류 복구 검증.
- 운영 서버: 기존 예약 작업으로 해당 프로젝트만 재시작, 새 메모 조회 API 확인. 실제 8개 탭에서 메모 버튼과 1366×768 화면 내 차트 표시, 가로 넘침 및 JS 오류 없음을 읽기 전용 확인.
- 실제 개인 자료에 시험 추천/메모를 등록하지 않았습니다. 키움 0600/실주문 검증은 이 작업 범위가 아닙니다. 원본 데이터·개인 메모·캡처·로그·인증정보는 업로드하지 않습니다.

## 우선 교차검토
1. 과거 보관 날짜 선택/한국 시각 자정/동시 등록/자동 수집 병합에서 입력일과 기존 기록이 보존되는지.
2. 모든 탭이 같은 notes.write를 사용하는지, 409 충돌 시 내용을 보존하는지, 최신 메모의 날짜가 명확한지.
3. 메모 열기가 종목 선택/영웅문 연동으로 전파되지 않는지, DOM 감시가 무한 요청을 만들지 않는지.
4. 넓은 화면과 좁은 화면의 읽기성, 시계 크기, 기존 차트 십자선·그리기 기능 보존 여부.

지적은 파일/줄/재현 조건/근거/최소 수정안으로 작성하고, 무관한 주문·수집 조건이나 원본 데이터는 변경하지 마세요.
