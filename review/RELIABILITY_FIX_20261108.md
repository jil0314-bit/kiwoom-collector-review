# 수집기 신뢰·시작 권한·원문 누락 보완 (2026-11-08)

## 기준과 사용자 결정
수정 전 커밋: f912e18. 매매·순위·거래량 조건·GUI 디자인·개인 메모는 변경하지 않는다.
연동은 끝자리 0311 계좌만 해당한다. 사용자가 계좌 표시 1곳과 기존 지문 일치 허용, 동일 실행 경로 업데이트 자동 신뢰, 이 작업 하나의 72시간 제한 해제를 명시적으로 선택했다. 다른 계좌·경로·다중 복구 후보는 거부한다.

## 수정
- hero_link.py: 계좌 값 대신 컨트롤 핸들만 캐시하고 매번 값을 다시 읽는다. API 상태 조회에서 한 번만 인가 후보를 구하며 같은 요청의 차트 탐색 결과를 재사용한다. 같은 계좌·프로세스의 유일한 펼쳐진 0600은 모니터 위치와 무관하게 복구한다. 기존 확인 기록에 경로가 없으면 이전 실행파일 지문이 일치할 때 경로 정책으로 이행하고, 이행 전 업데이트로 지문이 달라졌다면 최초 1회 계좌 재확인이 필요하다.
- hero-reconnect.js 및 app/volume/themes/rank-chart/investors.js: 7개 탭의 0600 전송이 공통 최대 2회 일시적 재시도와 이전 선택 취소를 사용한다. 403 거절은 토큰 갱신 후 별도 1회 재전송한다. 계좌 확인 실패는 재시도하지 않는다.
- start.vbs/install_schedule.ps1/window.py/admin_restart.ps1: 서버는 Highest 예약 작업으로 실행하고 화면 실행과 분리한다. 시작 명령은 이미 실행 중이면 작업을 다시 호출하지 않는다. 비관리자 재시작은 기존 서버를 종료하기 전에 거부한다. 작업 실행 시간 제한은 사용자 승인에 따라 PT0S로 설정한다.
- reasons.py/app.py/notes.js: 파싱 성공 종목을 보존하고 실패 코드를 missing_codes로 남긴다. 부분 저장은 전체 완료가 아니며 재시도한다. 로그인 폴더들의 최신 News.html을 선택하고 본문의 기사 날짜로 저장한다. 0158S0 같은 영문 혼합 코드를 검증한다.
- recommendations.py: 자막 없음은 기존처럼 발언·추천으로 추정하지 않는다. RSS 15건 포화 시 공개 동영상 목록 최대60건을 보충하고 원문 게시일 확인 후 기존 최근3일 범위를 유지한다. 범위 제한·보충 실패·MTN 0건은 확인 필요로 표시한다. MTN 공개 정리기사 우선, 유튜브 자막 보조 원칙을 문서화한다.

## 검증
- Python 오프라인 199개 통과.
- 공통 재시도: 최대2회·계좌 오류 중단·이전 선택 취소·토큰 갱신·탭 호출 통일 검사 통과.
- 기존 notes 표시 8개 및 보관 사유 151건의 함수 검사 통과.
- JavaScript 11개, PowerShell 2개 문법 검사 통과.
- 실제 예약 작업은 Highest, Python 직접 실행, PT0S, 동일 프로젝트 경로로 확인했다.
- 실제 예약 경로 재시작 성공. 시작 명령 재실행 후 동일 서버 PID 유지. 실행 서버의 관리자 토큰 True 확인.
- 수정 후 /api/hero-targets 약88ms, /api/status 정상, 11/6 사유 13건 API 제공 유지.

## 미확인·한계
현재 펼쳐진 인가 대상 0600이 없어 실제 영웅문 차트 전환·실물 계좌 전환·모니터 이동·영웅문 업데이트는 현장 재현하지 못했다. 이 부분은 모의 창·프로세스 회귀검사와 실제 상태 조회까지이며 실물 전환 성공으로 주장하지 않는다.
RSS 보충도 공개 초기 목록 범위이며 전체 과거 회차를 보장하지 않는다. 외부 페이지 변경·미공개 자막·통신 단절을 정상 성공으로 처리하지 않는다. 11/9 17:15 실제 자동수집은 별도 예약 검증 대상이다.

## 변경 파일 22개

- collector/README.md
- collector/admin_restart.ps1
- collector/app.py
- collector/docs/reliability_fix_20261108.md
- collector/hero_link.py
- collector/install_schedule.ps1
- collector/reasons.py
- collector/recommendations.py
- collector/release_manifest.json
- collector/start.vbs
- collector/test_hero_link.py
- collector/test_hero_retry.cjs
- collector/test_reasons.py
- collector/test_recommendations.py
- collector/web/app.js
- collector/web/hero-reconnect.js
- collector/web/investors.js
- collector/web/notes.js
- collector/web/rank-chart.js
- collector/web/themes.js
- collector/web/volume.js
- collector/window.py
