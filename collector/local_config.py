"""Opt-in per-Windows-user notebook settings. No secrets in source or archives."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path


def config_root():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'KiwoomCollector'


def settings():
    path = config_root() / 'settings.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def profile_file(name, fallback):
    local = settings()
    folder = local.get('hero4_profile')
    if folder:
        return Path(folder) / name
    return config_root() / 'unconfigured' / name if local.get('notebook_install') else fallback


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def crypt(body, decrypt=False):
    if os.name != 'nt':
        raise OSError('인증정보 암호화는 Windows에서만 지원합니다.')
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel.LocalFree.restype = wintypes.HLOCAL
    buffer = ctypes.create_string_buffer(body)
    source = Blob(len(body), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError('Windows 인증정보 암호화/해독 실패. 저장한 Windows 계정에서 다시 설정하세요.')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, wintypes.HLOCAL))


def save_credentials(key, secret):
    if not key.strip() or not secret.strip() or any(c in key + secret for c in '\r\n\x00'):
        raise ValueError('App Key와 App Secret을 각각 한 줄로 입력하세요.')
    path = config_root() / 'credentials.dpapi'
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_bytes(crypt(json.dumps({'key':key.strip(), 'secret':secret.strip()}).encode()))
    temp.replace(path)


def read_credentials():
    path = config_root() / 'credentials.dpapi'
    if not path.is_file():
        return None
    try:
        value = json.loads(crypt(path.read_bytes(), decrypt=True))
        if not value.get('key') or not value.get('secret'):
            raise ValueError()
        return value['key'], value['secret'], 'Windows 암호화 인증정보'
    except (OSError, ValueError, KeyError):
        raise ValueError('노트북 인증정보를 읽지 못했습니다. 인증정보 설정을 다시 실행하세요.') from None
