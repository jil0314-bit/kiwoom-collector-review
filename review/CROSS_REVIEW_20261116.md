# 2026-11-16 교차검증 안내

## 버전과 범위

- 원본 로컬 Git 기준 커밋: `c772b074f7400905f0e61d1112748d771fc78645`. 이번 공개본은 그 뒤의 **미커밋 작업 파일**까지 복사한 현재 스냅샷입니다. 기준 커밋만 checkout하면 최신 수정이 나오지 않습니다.
- GitHub 기준 부모: `3de6d019707be2bb7b7f37aad29e720d633590f0`.
- 최종 검토 버전은 이 문서가 포함된 GitHub 전체 커밋 SHA입니다.
- 원본 114개 파일을 선택했습니다. 소스/화면/테스트는 바이트 그대로 복사하고, 공개본의 `collector/release_manifest.json`만 검토본에 맞게 새로 생성했습니다. 공개용 README, 검토 규칙과 무시 목록, 이 문서, PUBLICATION_MANIFEST를 포함합니다.
- 현재 서버 재시작, 인증 설정 변경, 주문/매매 경로 변경은 이번 저장 작업에 포함하지 않았습니다. 프로세스 경로 재조회는 현재 샌드박스에서 접근 거부되어 재확인하지 못했습니다. 로컬 실행 스크립트의 경로는 읽어 확인했습니다.

## 이번 저장 과정에서 재실행한 검사

공개용 복사본의 `collector` 폴더에서:

```powershell
python -B -m unittest test_collector test_volume_surge test_investor_flows test_chart_data test_chart_service test_themes test_recommendations
```

- 136개 통과. 모의 응답/임시 폴더를 사용하는 관련 검사입니다.
- Python 파일 51개 AST 문법 검사 통과.
- JavaScript/CJS 18개 `node --check` 통과.
- `node collector/test_chart_fast.cjs`, `node collector/test_hero_retry.cjs` 통과(저장소 루트에서 실행).
- `node collector/test_notes_display.cjs`는 실제 과거 자료 `collector/data/reasons/2026-11-02.json` 부재로 ENOENT 종료했습니다. 이 테스트는 전체 성공으로 계산하지 않았고, 개인/수집 데이터를 공개해서 통과시키지 않았습니다.
- API 키/토큰/개인키의 흔한 리터럴 패턴 검사에서 후보가 발견되지 않았습니다. 파일은 명시적으로 선택했으며 runtime/data/인증 파일을 수집하지 않았습니다.
- 모든 테스트를 이번 작업에서 재실행한 것은 아닙니다. 이전 작업의 Windows DPAPI 환경 관련 실패도 해결되었다고 주장하지 않습니다.

## 중점 검토 경로

1. `app.py`: 장중 100개 미만의 검증된 당일 순위 저장, 더 완전한 자료/최종본 보호, 상승률 실패와 테마 수집 분리, `ranking_and_investor_tick`의 장중 수급 우선 및 20:05 최종 수집 우선 순서.
2. `volume_surge.py`: 새 순위 저장과 과거 보관 정리를 분리하여 읽기 전용 과거 폴더 오류가 오늘 수집을 막지 않는지, 일별 정리 경고/스레드 시작 실패/잠금 해제.
3. `investor_flows.py`: 시장별 잠정 목록, 원본 전체 빈 응답, 기존 정상/완료 자료 보존, 재시도 간격, 날짜·단위·출처. 미제공 수치를 임의로 0으로 채우지 않는지.
4. `chart_data.py`, `chart_service.py`, `chart.py`: 월봉/분봉/일봉/주봉, 180/240/360/480 이동평균과 준비 구간, 선택일 이후 자료가 과거 차트로 새지 않는지.
5. `web/stock-tools.js`, `web/stock-tools.css`와 각 탭: 공통 십자선/수치 팝업/드래그 선택, 도형별 지우개, 종목·주기별 도형 저장, 입력과 차트 이벤트 충돌, 화면 폭 대응, 추천 날짜의 주말 허용.
6. 방송 추천 모듈과 `recommendations.py`: 자막/OCR 미확인, 발견일과 원문 날짜, 추천과 단순 언급, 실패 장부, 중복 및 재시도.
7. `hero_link.py`, `hero4_daily_memo.py`, `hero4_memo_import.py`: 기존 조회 전용 0600 경로, 계좌 대상 검증, 메모 잠금/대기/개인 메모 보존. 기존 코드의 대상 식별 접미사와 PC 경로는 유지되어 있으며 전체 계좌번호나 인증정보를 업로드하지 않습니다.

## 이전 작업에서 보고된 실제 관찰과 제한

다음은 앞선 11월 16일 복구 작업 당시의 관찰 기록이며 이번 업로드에서 새로 실시간 조회한 결과가 아닙니다.

- 재시작 후 당일 상승률 100종목, 테마 10개, 거래량 급증 순위 100종목과 추적 분봉 파일 저장을 확인했습니다.
- 09:47 수급 잠정 응답은 외국인 KOSPI 39/KOSDAQ 50, 기관 두 시장 원본 0행이었습니다. 이후 수급 상태는 이 문서로 보증하지 않습니다.
- 11월 9~13일 거래량 급증 원본 보관 누락은 이번 수정으로 소급 복원되지 않았습니다. 당시 원본이나 백업이 필요한 문제입니다.
- 방송 자막/영상 접근 실패, 실제 물리적 0600 표시 일치, 다른 PC 설치, 향후 장중/마감 자동 수집 지속 여부는 별도 확인 대상입니다.

## 파일 일치 재검증

저장소 루트에서 다음 코드를 Python으로 실행하면 공개본 전체 목록의 SHA-256을 확인할 수 있습니다. manifest 자체는 자기 참조를 피하기 위해 목록에서 제외합니다.

```python
import hashlib, json
from pathlib import Path
manifest = json.loads(Path('PUBLICATION_MANIFEST.json').read_text(encoding='utf-8'))
for item in manifest['files']:
    body = Path(item['path']).read_bytes()
    assert len(body) == item['bytes'], item['path']
    assert hashlib.sha256(body).hexdigest() == item['sha256'], item['path']
print('PASS', len(manifest['files']))
```

검토 결과에는 확인한 커밋 SHA와 검사 환경을 먼저 적고, 파일·줄·재현 조건·근거·영향·최소 변경안·검증 방법을 포함하세요. 제안과 실제 수정은 구분하세요.
