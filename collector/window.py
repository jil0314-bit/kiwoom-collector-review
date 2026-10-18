"""Open the local dashboard in a separate Edge app window, without browser tabs."""
import os
import subprocess
from pathlib import Path


def command(url):
    if url != 'http://127.0.0.1:8766':
        raise ValueError('Only the local collector address is allowed')
    roots = [os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)'),
             os.environ.get('ProgramFiles', 'C:/Program Files'),
             os.environ.get('LOCALAPPDATA', '')]
    candidates = [Path(root) / 'Microsoft/Edge/Application/msedge.exe' for root in roots if root]
    edge = next((p for p in candidates if p.is_file()), None)
    if edge is None:
        raise FileNotFoundError('Microsoft Edge 실행 파일을 찾지 못했습니다.')
    profile = Path(__file__).resolve().parent / '.window-profile'
    return [str(edge), '--app=' + url, '--user-data-dir=' + str(profile),
            '--window-size=1440,1000', '--no-first-run', '--no-default-browser-check']


def open_dashboard(url):
    try:
        subprocess.Popen(command(url), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, ValueError):
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,
            '별도 대시보드 창을 열지 못했습니다. Microsoft Edge 설치 상태를 확인하세요.',
            '챗GPT 상승률·분봉 수집기', 0x10)
