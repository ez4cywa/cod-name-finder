"""GitHub tokens live only in Windows Credential Manager, never in app files."""
import ctypes
from ctypes import wintypes
import os


TARGET = 'CODNameFinder:github.com:upstream-submission'
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
MAX_TOKEN_BYTES = 2048


class GitHubCredentialsError(RuntimeError):
    pass


def validate_token(token):
    if (not isinstance(token, str) or not 1 <= len(token) <= MAX_TOKEN_BYTES
            or not token.isascii() or any(not 33 <= ord(c) <= 126 for c in token)):
        raise ValueError('GitHub 令牌须为 1–2048 个可打印 ASCII 字符，不能包含空格或换行')
    return token


class _Credential(ctypes.Structure):
    _fields_ = [
        ('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
        ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
        ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
        ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD),
        ('Attributes', ctypes.c_void_p), ('TargetAlias', wintypes.LPWSTR),
        ('UserName', wintypes.LPWSTR),
    ]


def _windows():
    return os.name == 'nt'


def _backend():
    try:
        api = ctypes.WinDLL('advapi32', use_last_error=True)
        api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.POINTER(ctypes.POINTER(_Credential))]
        api.CredReadW.restype = wintypes.BOOL
        api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree.restype = None
        return api
    except (AttributeError, OSError):
        raise GitHubCredentialsError('无法访问 Windows 凭据管理器') from None


def _last_error():
    return ctypes.get_last_error()


def get_token():
    if not _windows():
        return None
    api = _backend()
    pointer = ctypes.POINTER(_Credential)()
    if not api.CredReadW(TARGET, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        code = _last_error()
        if code == ERROR_NOT_FOUND:
            return None
        raise GitHubCredentialsError(f'无法读取 GitHub 登录凭据（Windows 错误 {code}）')
    try:
        if not pointer:
            raise ValueError('missing credential')
        credential = pointer.contents
        size = credential.CredentialBlobSize
        if not 1 <= size <= MAX_TOKEN_BYTES or not credential.CredentialBlob:
            raise ValueError('invalid credential size')
        token = ctypes.string_at(credential.CredentialBlob, size).decode('ascii')
        return validate_token(token)
    except (UnicodeError, ValueError):
        raise GitHubCredentialsError('保存的 GitHub 凭据无效，请重新登录') from None
    finally:
        if pointer:
            api.CredFree(pointer)


def save_token(token):
    token = validate_token(token)
    if not _windows():
        raise GitHubCredentialsError('此平台暂不支持安全保存 GitHub 令牌；请在 Windows 中使用此功能')
    api = _backend()
    buffer = ctypes.create_string_buffer(token.encode('ascii'))
    credential = _Credential()
    credential.Type = CRED_TYPE_GENERIC
    credential.TargetName = TARGET
    credential.Comment = 'COD Name Finder GitHub upstream submissions'
    credential.CredentialBlobSize = len(token)
    credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = 'github.com'
    try:
        if not api.CredWriteW(ctypes.byref(credential), 0):
            raise GitHubCredentialsError(f'无法保存 GitHub 登录凭据（Windows 错误 {_last_error()}）')
    finally:
        ctypes.memset(buffer, 0, ctypes.sizeof(buffer))


def delete_token():
    if not _windows():
        return
    api = _backend()
    if not api.CredDeleteW(TARGET, CRED_TYPE_GENERIC, 0):
        code = _last_error()
        if code != ERROR_NOT_FOUND:
            raise GitHubCredentialsError(f'无法删除 GitHub 登录凭据（Windows 错误 {code}）')
