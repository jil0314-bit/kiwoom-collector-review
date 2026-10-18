"""Display-only 0600 linkage. No orders, clipboard or global keyboard input."""
import ctypes
from ctypes import wintypes
import re
import threading
import sys
import json
from pathlib import Path

LOCK = threading.Lock()
TARGET_FILE = Path(__file__).resolve().parent / 'data' / 'hero_link_target.json'


def preferred():
    try:
        saved = json.loads(TARGET_FILE.read_text(encoding='utf-8'))
        handle = str(saved['handle'])
        w = Windows()
        charts = w.charts()
        if int(handle) in charts:
            return handle
        side = saved.get('side')
        matches = [h for h in charts if (w.rect(h)[0] < 0) == (side == 'left')] if side in ('left', 'right') else []
        return str(matches[0]) if len(matches) == 1 else ''
    except (OSError, ValueError, KeyError):
        return ''


def exact_chart(title):
    return '[0600]' in title and '키움종합차트' in title


def code_text(text):
    return bool(re.fullmatch(r'A?[0-9A-Z]{6}', text.strip()))


class Windows:
    def __init__(self):
        if sys.platform != 'win32':
            raise ValueError('영웅문 연동은 Windows에서만 가능합니다.')
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.u.EnumWindows.argtypes = [self.callback, wintypes.LPARAM]
        self.u.EnumChildWindows.argtypes = [wintypes.HWND, self.callback, wintypes.LPARAM]
        for fn in ['IsWindow', 'IsWindowVisible', 'IsWindowEnabled']:
            getattr(self.u, fn).argtypes = [wintypes.HWND]
        self.u.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
        self.u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.u.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                               wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                               ctypes.POINTER(ctypes.c_size_t)]
        self.u.SendMessageTimeoutW.restype = ctypes.c_size_t
        self.u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    def enum(self, parent=None):
        result = []
        callback = self.callback(lambda h, _: result.append(int(h)) or True)
        if parent is None:
            self.u.EnumWindows(callback, 0)
        else:
            self.u.EnumChildWindows(parent, callback, 0)
        return result

    def text(self, handle):
        # WM_GETTEXT also reads child Edit controls owned by another process.
        buf = ctypes.create_unicode_buffer(256)
        result = ctypes.c_size_t()
        if not self.u.SendMessageTimeoutW(handle, 0x000D, 256, ctypes.addressof(buf),
                                          2, 150, ctypes.byref(result)):
            return ''
        return buf.value.strip()

    def title(self, handle):
        buf = ctypes.create_unicode_buffer(512)
        self.u.GetWindowTextW(handle, buf, 512)
        return buf.value

    def rect(self, handle):
        r = wintypes.RECT()
        self.u.GetWindowRect(handle, ctypes.byref(r))
        return r.left, r.top, r.right, r.bottom

    def charts(self):
        found = []
        for root in self.enum():
            if not self.u.IsWindowVisible(root):
                continue
            title = self.title(root)
            if '영웅문' not in title and 'Kiwoom' not in title:
                continue
            for h in [root] + self.enum(root):
                if self.u.IsWindowVisible(h) and exact_chart(self.title(h)):
                    found.append(h)
        return list(dict.fromkeys(found))

    def edits(self, chart):
        left, top, right, bottom = self.rect(chart)
        found = []
        for h in self.enum(chart):
            buf = ctypes.create_unicode_buffer(128)
            self.u.GetClassNameW(h, buf, 128)
            x, y, r, b = self.rect(h)
            if (buf.value.lower() == 'edit' and self.u.IsWindowVisible(h)
                    and self.u.IsWindowEnabled(h) and self.u.IsChild(chart, h)
                    and left <= x < min(right, left + 260) and top <= y < min(bottom, top + 110)
                    and 30 <= r-x <= 160 and 10 <= b-y <= 45 and code_text(self.text(h))):
                found.append(h)
        return found


def targets():
    w = Windows()
    return [{'handle': str(h), 'label': '[0600] ' + ('왼쪽' if w.rect(h)[0] < 0 else '오른쪽')
             + ' · 위치 ' + str(w.rect(h)[0]) + ' · ' + (w.text(e[0]) if len(e := w.edits(h)) == 1 else '입력칸 확인 필요')}
            for h in w.charts()]


def send(code, windows=None, chart_handle=None):
    if not re.fullmatch(r'[0-9A-Z]{6}', str(code)):
        raise ValueError('종목코드 형식 오류')
    with LOCK:
        w = windows or Windows()
        charts = w.charts()
        chart_handle = chart_handle or (preferred() if windows is None else '')
        if chart_handle:
            chosen = int(chart_handle)
            if chosen not in charts:
                return {'ok': False, 'message': '선택한 0600 차트가 닫혔습니다. 연동 차트를 다시 선택해주세요.'}
            charts = [chosen]
        if len(charts) != 1:
            return {'ok': False, 'message': '차트 위에서 연동할 영웅문 0600을 선택해주세요.' if charts else '영웅문 [0600] 키움종합차트를 열어주세요.'}
        chart = charts[0]
        edits = w.edits(chart)
        if len(edits) != 1:
            return {'ok': False, 'message': '0600 종목코드 입력칸을 정확히 식별하지 못했습니다. 전송하지 않았습니다.'}
        target = edits[0]
        # Revalidate immediately before writing, never fall back to another window.
        if not exact_chart(w.title(chart)) or w.edits(chart) != [target]:
            return {'ok': False, 'message': '0600 화면이 변경되어 전송하지 않았습니다.'}
        buf = ctypes.create_unicode_buffer(code)
        result = ctypes.c_size_t()
        if not w.u.SendMessageTimeoutW(target, 0x000C, 0, ctypes.addressof(buf), 2, 200, ctypes.byref(result)):
            error = ctypes.get_last_error()
            return {'ok': False, 'message': 'Windows가 영웅문 입력을 차단했습니다. 수집기 관리자 실행이 필요합니다.'
                    if error == 5 else '영웅문 응답 실패 · Windows 오류 ' + str(error)}
        if w.text(target) != code:
            return {'ok': False, 'message': '0600 종목코드 입력 확인 실패'}
        down = w.u.PostMessageW(target, 0x0100, 13, 0x001C0001)
        up = w.u.PostMessageW(target, 0x0101, 13, 0xC01C0001)
        return {'ok': bool(down and up), 'code': code, 'verified': False,
                'message': code + ' · 영웅문 0600 전송' if down and up else '0600 Enter 전달 실패'}
