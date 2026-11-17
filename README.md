# 키움 수집기 검토 소스 · 2026-11-17

상승 사유 자동 수집 보완, 전체 시장 종목 검색·차트·관찰종목 편입, 수집 오류 수정과 필요한 통합 소스를 저장한 검토본입니다. 다른 AI는 **같은 전체 커밋 SHA**를 기준으로 검토하세요.

- [변경 범위·검증 결과·미확인 범위](review/CROSS_REVIEW_20261117.md)
- [상승 사유 운영 검증 집계](review/REASONS_DAILY_VALIDATION_20261117.json)
- [파일별 SHA-256 및 Git blob 해시](PUBLICATION_MANIFEST.json)
- [공동 검토 원칙](AGENTS.md) · [수집기 원칙](collector/AGENTS.md) · [수집기 설명](collector/README.md)

공개용 복사본에서 관련 Python 테스트 176개가 통과했습니다. 실제 PC의 사유 저장·표시 검증은 문서에 별도로 구분했습니다. 기사에 근거가 없는 종목의 상승 사유는 추측해서 채우지 않습니다.

실행 경로는 `OPEN_COLLECTOR.cmd` → `collector/start.vbs` → 기존 예약 작업 → `collector/app.py`입니다. Windows/Python 및 사용자별 키움 인증·예약 작업 설정이 필요합니다.

API 키·인증정보·개인 메모·실제 수집 데이터·원문 기사·로그·캡처·런타임·백업은 이번 업로드에서 제외했습니다. 기존 downloads의 설치 ZIP은 과거 자료이며 이번 수정이 들어간 새 배포본이 아닙니다.

> 이 커밋의 전체 SHA를 고정하고 AGENTS.md와 review/CROSS_REVIEW_20261117.md를 읽은 뒤, 기사 날짜·종목코드·누락 판정·재시도·기존 자료 보존·검색 차트·관찰종목 편입을 교차검증해 주세요. 지적마다 파일·줄·재현 조건·근거·최소 수정안·검증 방법을 적고, 실제 주문이나 원본 데이터 변경은 하지 마세요.
