# LG그램 간편 설치 개선 (2026-11-08)
기존 Python 수동 설치·venv/pip 설치 단계를 없앤 배포본을 추가한다. 공식 Python3.14.10 embeddable x64와 Pillow13.0.0 cp314 wheel을 SHA256 검증 후 전용 .runtime에 포함한다. pip·개발도구·프로젝트 테스트·사무실 데이터·인증정보는 ZIP에 넣지 않는다. Python 라이선스와 Pillow 라이선스는 포함한다.
내장 Python은 tkinter가 없어, 새 설정 창은 Windows 기본 WinForms를 사용한다. 비밀값은 마스킹해 입력하고 .NET CurrentUser DPAPI로 암호화한다. Python 복호화 형식과 호환된다. Python configure_lg.py는 --check일 때 tkinter를 불러오지 않도록 바꿨다. 일반 Python 설치 경로의 기존 설정창은 유지한다.
기존 수집기와 같은 자동 실행 예약·0311 제한·초기 노트북 메모 쓰기 차단을 보존했다. 사무실에 .runtime이 없으면 실행 경로는 기존과 같으며 사무실 예약/프로세스를 재등록/재시작하지 않았다. 다른 경로의 수집기 예약은 덮어쓰지 않는다. 새 설치 완료 후 화면을 자동으로 연다. 허용IP 등록은 대신 자동 처리하지 않고 설정 창에서 공식 페이지 링크를 제공한다.
간편 ZIP은 1_처음설치.cmd / 2_수집기열기.cmd / 먼저읽기 안내와 현재 실행 필수 파일만 포함한다. 실행 환경 원본과 SHA256, ZIP 파일별 manifest와 전체 SHA256을 기록한다. 실제 LG그램 설치/UAC/키움 인증/0600은 별도 현장 확인이 필요하다.
