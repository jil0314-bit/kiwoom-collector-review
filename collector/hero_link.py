"""Display-only 0600 linkage. No orders, clipboard or global keyboard input."""
import ctypes
from ctypes import wintypes
import re
import threading
import sys
import json
import hashlib
import secrets
import time
from pathlib import Path

LOCK = threading.RLock()
TARGET_FILE = Path(__file__).resolve().parent / 'data' / 'hero_link_target.json'
IMAGE_CACHE = {}
ACCOUNT_CONTROLS = {}
ACCOUNT_DISCOVERY_TTL = 1.0


def process_path(pid):
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        buf, size = ctypes.create_unicode_buffer(2048), wintypes.DWORD(2048)
        if not k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        path = Path(buf.value)
        return str(path).lower() if path.name.lower() == 'nkrunlite.exe' else None
    finally:
        k.CloseHandle(handle)


def process_image(pid):
    """Legacy executable digest retained for migration of existing confirmations."""
    name = process_path(pid)
    if not name:
        return None
    try:
        path = Path(name)
        stat = path.stat()
        key = (name, stat.st_mtime_ns, stat.st_size)
        if key not in IMAGE_CACHE:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            IMAGE_CACHE.clear()
            IMAGE_CACHE[key] = hashlib.sha256((name + ':' + digest).encode()).hexdigest()
        return IMAGE_CACHE[key]
    except OSError:
        return None


def preferred(w=None, charts=None):
    try:
        saved = json.loads(TARGET_FILE.read_text(encoding='utf-8'))
        handle = str(saved['handle'])
        w = w or Windows()
        charts = authorized_charts(w) if charts is None else charts
        handle = str(json.loads(TARGET_FILE.read_text(encoding='utf-8'))['handle'])
        if int(handle) in charts:
            return handle
        # A chart may be reopened within the verified Hero4 process.
        if len(charts) == 1:
            return str(charts[0])
        # Never silently choose another chart when the selected chart is closed.
        return ''
    except (OSError, ValueError, KeyError):
        return ''


def process_start(pid):
    """Creation timestamp of a running process; exited handles retain old timestamps."""
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k.OpenProcess(0x101000, False, pid)  # QUERY_LIMITED_INFORMATION | SYNCHRONIZE
    if not handle:
        return None
    try:
        if k.WaitForSingleObject(handle, 0) != 0x102:  # WAIT_TIMEOUT: still running
            return None
        created, exited, kernel, user = [wintypes.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                 ctypes.byref(kernel), ctypes.byref(user)):
            return None
        if k.WaitForSingleObject(handle, 0) != 0x102:
            return None
        return (created.dwHighDateTime << 32) | created.dwLowDateTime
    finally:
        k.CloseHandle(handle)


def authorized_charts(w):
    """Only charts owned by the user-confirmed 0311 Hero4 login session."""
    try:
        saved = json.loads(TARGET_FILE.read_text(encoding='utf-8'))
        pid = int(saved['pid'])
        if saved.get('account_suffix') != '0311':
            return []
        if process_start(pid) == int(saved['process_start']):
            # A login can change accounts without changing the process or its PID.
            if saved.get('account_digest') and not w.matches_identity(pid, saved):
                return []
        else:
            with LOCK:
                candidates = w.charts()
                matches = [p for p in {w.pid(h) for h in candidates}
                           if w.matches_identity(p, saved)]
                if len(matches) != 1:
                    return []
                pid = matches[0]
                charts = [h for h in candidates if w.pid(h) == pid
                          and w.rect(h)[3] - w.rect(h)[1] > 110
]
                if len(charts) != 1 or len(w.edits(charts[0])) != 1:
                    return []
                start = process_start(pid)
                if start is None:
                    return []
                if process_start(pid) != start or w.pid(charts[0]) != pid:
                    return []
                saved.update(pid=pid, process_start=start, handle=str(charts[0]))
                save_target(saved)
        return [h for h in w.charts() if w.pid(h) == pid]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def save_target(target):
    temp = TARGET_FILE.with_suffix('.tmp')
    temp.write_text(json.dumps(target), encoding='utf-8')
    temp.replace(TARGET_FILE)


def diagnostic(w=None, charts=None):
    """Explain a missing target without relaxing the verified-account boundary."""
    try:
        saved = json.loads(TARGET_FILE.read_text(encoding='utf-8'))
        if saved.get('account_suffix') != '0311':
            raise ValueError()
        w = w or Windows()
        charts = authorized_charts(w) if charts is None else charts
        saved = json.loads(TARGET_FILE.read_text(encoding='utf-8'))
        start = process_start(int(saved['pid']))
        if start is None or start != int(saved['process_start']):
            return {'state': 'session_changed', 'message':
                    '영웅문 재실행 후 동일 계좌 자동 확인 대기 중입니다. 0311 계좌와 0600을 펼쳐주세요. 확인이 안 되면 재연결 버튼을 사용하세요.'}
        if not charts:
            return {'state': 'no_chart', 'message':
                    '확인된 0311 영웅문에서 보이는 0600 차트를 찾지 못했습니다. 해당 0600을 열어주세요.'}
        if len(charts) > 1 and not preferred(w, charts):
            return {'state': 'select_chart', 'message': '0600 차트가 여러 개입니다. 연동할 차트를 선택해주세요.'}
        return {'state': 'ready', 'message': '0600 연결 대상 확인됨 · 실제 종목 전환은 별도 확인 필요'}
    except (OSError, ValueError, KeyError, TypeError):
        return {'state': 'unconfirmed', 'message': '0311 계좌의 영웅문 연결 대상 확인이 필요합니다.'}


def confirm_session(account_suffix):
    """Explicit user attestation only; never infer an account from a process ID."""
    if account_suffix != '0311':
        raise ValueError('0311 계좌 확인이 필요합니다.')
    with LOCK:
        w = Windows()
        charts = w.charts()
        # Minimized MDI charts have only a title bar, not a usable chart area.
        charts = [h for h in charts if w.rect(h)[3] - w.rect(h)[1] > 110]
        if len(charts) != 1 or len(w.edits(charts[0])) != 1:
            return {'ok': False, 'message': '연결할 0311 계좌의 0600 차트 하나만 펼쳐주세요. 여러 창이면 임의 연결하지 않습니다.'}
        chart = charts[0]
        pid = w.pid(chart)
        start = process_start(pid)
        if start is None:
            return {'ok': False, 'message': '영웅문 실행 세션을 확인하지 못했습니다.'}
        if chart not in w.charts() or w.pid(chart) != pid or process_start(pid) != start:
            return {'ok': False, 'message': '확인 중 영웅문 화면이 변경되었습니다. 다시 확인해주세요.'}
        target = {'account_suffix': account_suffix, 'pid': pid, 'process_start': start,
                  'handle': str(chart), 'side': 'left' if w.rect(chart)[0] < 0 else 'right'}
        identity = w.capture_identity(pid)
        if not isinstance(identity, dict) or not all(identity.get(k) for k in
                                                      ('identity_salt', 'account_digest', 'image_digest')):
            return {'ok': False, 'message': '0311 계좌 표시를 자동 확인하지 못해 연결 대상을 저장하지 않았습니다.'}
        target.update(identity)
        save_target(target)
        return {'ok': True, 'message': '0311 계좌의 현재 0600 연결 대상을 저장했습니다. 종목을 선택해 전환을 확인해주세요.'}


def exact_chart(title):
    return '[0600]' in title and '키움종합차트' in title


def code_text(text):
    return bool(re.fullmatch(r'A?[0-9A-Z]{6}', text.strip()))


class Windows:
    def __init__(self):
        if sys.platform != 'win32':
            raise ValueError('영웅문 연동은 Windows에서만 가능합니다.')
        self._chart_snapshot = None
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

    def account_values(self, pid):
        # Cache control handles, never account numbers or a positive identity verdict.
        # Each use rereads visible values, so an in-process account switch is rejected.
        session = process_start(pid)
        if session is None:
            return []
        key = (pid, session)
        cached = ACCOUNT_CONTROLS.get(key)
        def read(handles):
            values = []
            for h in handles:
                if not self.u.IsWindow(h) or self.pid(h) != pid or not self.u.IsWindowVisible(h):
                    continue
                value = self.text(h)
                if re.fullmatch(r'\d{4}-\d{4}', value) and value.endswith('0311'):
                    values.append(value)
            return values
        if cached:
            values = read(cached['handles'])
            if values or time.monotonic() - cached['at'] < ACCOUNT_DISCOVERY_TTL:
                return values
        handles, values = [], []
        deadline = time.monotonic() + 1.5
        for root in self.enum():
            if self.pid(root) != pid or '영웅문' not in self.title(root):
                continue
            for h in self.enum(root):
                if time.monotonic() > deadline:
                    break
                buf = ctypes.create_unicode_buffer(128)
                self.u.GetClassNameW(h, buf, 128)
                if buf.value.lower() != 'edit' or not self.u.IsWindowVisible(h):
                    continue
                value = self.text(h)
                if re.fullmatch(r'\d{4}-\d{4}', value) and value.endswith('0311'):
                    handles.append(h)
                    values.append(value)
        if session is not None:
            if len(ACCOUNT_CONTROLS) > 8:
                ACCOUNT_CONTROLS.clear()
            ACCOUNT_CONTROLS[key] = {'handles': handles, 'at': time.monotonic()}
        return values

    def capture_identity(self, pid):
        values = self.account_values(pid)
        # User-approved convenience policy: one visible matching account display.
        accounts = set(values)
        image = process_image(pid)
        if len(accounts) != 1 or not image:
            return {}
        salt = secrets.token_hex(16)
        return {'identity_salt': salt,
                'account_digest': hashlib.sha256((salt + accounts.pop()).encode()).hexdigest(),
                'image_digest': image, 'image_path': process_path(pid)}

    def matches_identity(self, pid, saved):
        if not all(saved.get(k) for k in ('identity_salt','account_digest','image_digest')):
            return False
        current_path = process_path(pid)
        if saved.get('image_path'):
            if not current_path or current_path != saved['image_path']:
                return False
        elif process_image(pid) != saved['image_digest']:
            return False
        elif current_path:
            # Migrate the already-matching legacy digest to the user-approved path policy.
            saved['image_path'] = current_path
            save_target(saved)
        values = self.account_values(pid)
        return any(secrets.compare_digest(
            hashlib.sha256((saved['identity_salt'] + v).encode()).hexdigest(),
            saved['account_digest']) for v in set(values))

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

    def pid(self, handle):
        pid = wintypes.DWORD()
        self.u.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        return pid.value

    def charts(self):
        if self._chart_snapshot is not None:
            return list(self._chart_snapshot)
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
        self._chart_snapshot = list(dict.fromkeys(found))
        return list(self._chart_snapshot)

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


def targets(w=None, charts=None):
    w = w or Windows()
    charts = authorized_charts(w) if charts is None else charts
    return [{'handle': str(h), 'label': '[0600] ' + ('왼쪽' if w.rect(h)[0] < 0 else '오른쪽')
             + ' · 위치 ' + str(w.rect(h)[0]) + ' · ' + (w.text(e[0]) if len(e := w.edits(h)) == 1 else '입력칸 확인 필요')}
            for h in charts]


def connection_state():
    with LOCK:
        w = Windows()
        charts = authorized_charts(w)
        return {'targets': targets(w, charts), 'preferred': preferred(w, charts),
                'diagnostic': diagnostic(w, charts)}


def send(code, windows=None, chart_handle=None):
    if not re.fullmatch(r'[0-9A-Z]{6}', str(code)):
        raise ValueError('종목코드 형식 오류')
    with LOCK:
        w = windows or Windows()
        charts = authorized_charts(w) if windows is None else w.charts()
        chart_handle = chart_handle or (preferred(w, charts) if windows is None else '')
        if chart_handle:
            try:
                chosen = int(chart_handle)
            except (TypeError, ValueError):
                chosen = -1
            if chosen not in charts:
                if windows is None and charts:
                    replacement = preferred(w, charts)
                    if not replacement:
                        return {'ok': False, 'message': '기존 0600 창이 닫혔습니다. 연동할 차트를 다시 선택해주세요.'}
                    chosen = int(replacement)
                else:
                    return {'ok': False, 'message': '0311 계좌의 영웅문 0600을 확인할 수 없습니다. 다시 확인해주세요.'}
            charts = [chosen]
        if len(charts) != 1:
            return {'ok': False, **diagnostic()} if windows is None else {'ok': False, 'message': '0311 계좌의 연동 차트를 선택해주세요.' if charts else '0311 계좌의 영웅문 연결을 다시 확인해주세요.'}
        chart = charts[0]
        edits = w.edits(chart)
        if len(edits) != 1:
            return {'ok': False, 'message': '0600 종목코드 입력칸을 정확히 식별하지 못했습니다. 전송하지 않았습니다.'}
        target = edits[0]
        # Revalidate immediately before writing, never fall back to another window.
        if (not exact_chart(w.title(chart)) or w.edits(chart) != [target]
                or (windows is None and chart not in authorized_charts(w))):
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
