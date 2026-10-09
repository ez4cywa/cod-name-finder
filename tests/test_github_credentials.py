"""Exercise Credential Manager ownership and cleanup without touching real credentials."""
import ctypes
from types import SimpleNamespace

import pytest

from finder import github_credentials as credentials


@pytest.mark.parametrize('value', ['', None, 123, 'x' * 2049, ' token', 'token ',
                                    'a\nb', 'a\rb', 'a\0b', 'a\tb', '中文'])
def test_rejects_invalid_tokens_without_echoing_them(value):
    with pytest.raises(ValueError) as caught:
        credentials.validate_token(value)
    if isinstance(value, str) and len(value) > 10:
        assert value not in str(caught.value)


def test_non_windows_does_not_store_token_in_files_or_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(credentials, '_windows', lambda: False)
    monkeypatch.chdir(tmp_path)
    assert credentials.get_token() is None
    credentials.delete_token()
    with pytest.raises(credentials.GitHubCredentialsError, match='Windows'):
        credentials.save_token('test_token_only')
    assert list(tmp_path.iterdir()) == []


def test_save_uses_generic_local_machine_and_clears_transient_buffer(monkeypatch):
    captured = {}

    def write(pointer, flags):
        credential = ctypes.cast(pointer, ctypes.POINTER(credentials._Credential)).contents
        captured.update(target=credential.TargetName, kind=credential.Type,
                        persist=credential.Persist, flags=flags,
                        size=credential.CredentialBlobSize,
                        pointer=credential.CredentialBlob,
                        secret=ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize))
        return True

    # Intercept zeroing while the owning buffer is still alive.
    real_memset = ctypes.memset

    def clear(buffer, value, length):
        result = real_memset(buffer, value, length)
        captured['cleared'] = bytes(buffer) == b'\0' * length
        return result

    monkeypatch.setattr(credentials, '_windows', lambda: True)
    monkeypatch.setattr(credentials, '_backend', lambda: SimpleNamespace(CredWriteW=write))
    monkeypatch.setattr(credentials.ctypes, 'memset', clear)
    credentials.save_token('test_token_only')
    assert captured['target'] == credentials.TARGET
    assert captured['kind'] == 1 and captured['persist'] == 2 and captured['flags'] == 0
    assert captured['size'] == 15 and captured['secret'] == b'test_token_only'
    assert captured['cleared']


def _reader(monkeypatch, blob, *, declared_size=None):
    buffer = ctypes.create_string_buffer(blob)
    credential = credentials._Credential()
    credential.CredentialBlobSize = len(blob) if declared_size is None else declared_size
    credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    pointer = ctypes.pointer(credential)
    freed = []

    def read(target, kind, flags, output):
        assert (target, kind, flags) == (credentials.TARGET, 1, 0)
        ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(credentials._Credential)))[0] = pointer
        return True

    monkeypatch.setattr(credentials, '_windows', lambda: True)
    monkeypatch.setattr(credentials, '_backend', lambda: SimpleNamespace(CredReadW=read, CredFree=lambda p: freed.append(p)))
    return freed, buffer, credential


def test_read_decodes_and_always_frees_win32_allocation(monkeypatch):
    freed, _, _ = _reader(monkeypatch, b'test_token_only')
    assert credentials.get_token() == 'test_token_only'
    assert len(freed) == 1


@pytest.mark.parametrize('blob,size', [(b'a\nb', None), (b'\xff', None), (b'x', 2049), (b'', 0)])
def test_invalid_saved_credential_is_freed_and_rejected(monkeypatch, blob, size):
    freed, _, _ = _reader(monkeypatch, blob, declared_size=size)
    with pytest.raises(credentials.GitHubCredentialsError, match='重新登录'):
        credentials.get_token()
    assert len(freed) == 1


def test_missing_credential_is_none_and_delete_is_idempotent(monkeypatch):
    calls = []
    monkeypatch.setattr(credentials, '_windows', lambda: True)
    monkeypatch.setattr(credentials, '_last_error', lambda: 1168)
    monkeypatch.setattr(credentials, '_backend', lambda: SimpleNamespace(
        CredReadW=lambda *args: False, CredDeleteW=lambda *args: calls.append(args) or False))
    assert credentials.get_token() is None
    credentials.delete_token()
    assert calls == [(credentials.TARGET, 1, 0)]


@pytest.mark.parametrize('operation', ['get_token', 'save_token', 'delete_token'])
def test_win32_errors_do_not_include_the_secret(monkeypatch, operation):
    monkeypatch.setattr(credentials, '_windows', lambda: True)
    monkeypatch.setattr(credentials, '_last_error', lambda: 5)
    monkeypatch.setattr(credentials, '_backend', lambda: SimpleNamespace(
        CredReadW=lambda *args: False, CredWriteW=lambda *args: False, CredDeleteW=lambda *args: False))
    with pytest.raises(credentials.GitHubCredentialsError) as caught:
        getattr(credentials, operation)(*(['test_token_only'] if operation == 'save_token' else []))
    assert 'test_token_only' not in str(caught.value)
    assert '5' in str(caught.value)
