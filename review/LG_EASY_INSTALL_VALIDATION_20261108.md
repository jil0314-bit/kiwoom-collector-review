# LG그램 간편 설치 개선 (2026-11-08)
기존 Python 수동 설치·venv/pip 설치 단계를 없앤 배포본을 추가한다. 공식 Python3.14.10 embeddable x64와 Pillow13.0.0 cp314 wheel을 SHA256 검증 후 전용 .runtime에 포함한다. pip·개발도구·프로젝트 테스트·사무실 데이터·인증정보는 ZIP에 넣지 않는다. Python 라이선스와 Pillow 라이선스는 포함한다.
내장 Python은 tkinter가 없어, 새 설정 창은 Windows 기본 WinForms를 사용한다. 비밀값은 마스킹해 입력하고 .NET CurrentUser DPAPI로 암호화한다. Python 복호화 형식과 호환된다. Python configure_lg.py는 --check일 때 tkinter를 불러오지 않도록 바꿨다. 일반 Python 설치 경로의 기존 설정창은 유지한다.
기존 수집기와 같은 자동 실행 예약·0311 제한·초기 노트북 메모 쓰기 차단을 보존했다. 사무실에 .runtime이 없으면 실행 경로는 기존과 같으며 사무실 예약/프로세스를 재등록/재시작하지 않았다. 다른 경로의 수집기 예약은 덮어쓰지 않는다. 새 설치 완료 후 화면을 자동으로 연다. 허용IP 등록은 대신 자동 처리하지 않고 설정 창에서 공식 페이지 링크를 제공한다.
간편 ZIP은 1_처음설치.cmd / 2_수집기열기.cmd / 먼저읽기 안내와 현재 실행 필수 파일만 포함한다. 실행 환경 원본과 SHA256, ZIP 파일별 manifest와 전체 SHA256을 기록한다. 실제 LG그램 설치/UAC/키움 인증/0600은 별도 현장 확인이 필요하다.

## 완료한 검증
- ZIP에 넣은 실제 CPython3.14.10/Pillow13 실행 환경으로 전체208개 통과. Python3.14의 모의HTTP 객체 정리 ResourceWarning은 일부 기존 테스트에서 발생했으나 테스트 실패 없음.
- PowerShell4개 AST, 새 WinForms 창 생성(표시·인증 접근 없음), 공통0600 재시도 검사 통과.
- 공식 Python 배포 SHA256과 PyPI wheel SHA256 일치. Python/Pillow 라이선스 포함.
- 압축 해제된219개 파일 전체 manifest 일치. 과거자료·개인메모·인증정보·자체 테스트·pip·빌드 도구·이전 실행환경을 포함하지 않음.
- 별도 폴더로 압축 해제하고 PATH에서 설치된Python을 제외한 환경에서 포함 실행파일만으로 모든 모듈 import/로컬HTTP/API/정상 종료 확인. 실제 키움 호출·프로세스 종료·예약 변경 없음.
- .NET CurrentUser DPAPI로 가짜 값 암호화 후 포함된Python에서 복호화·JSON 일치를 확인. 실제 비밀값은 사용하지 않음.
- LG그램에서의 실제 UAC 설치, 허용IP/키움 인증,0311 실물0600/메모 쓰기는 여전히 미검증. 사무실 서버는 재시작하지 않았다.

소스 fe3ffd0 →0a6863e. ZIP SHA256: 024d220059457ea1b2e0046fd8575766e1823b1f587a712a2797e795c51cb3a4
