"""Content identity of the scanner used to prove that a sweep is complete.

The signature contains logical names and byte digests only. Locations and file
timestamps are deliberately absent: copying an installation preserves its
identity, while changing its Python scanner or native engine invalidates reuse.
"""
from functools import lru_cache
import hashlib
from pathlib import Path

from .hashing import native_path


_SOURCE_ROOT = Path(__file__).resolve().parent
_SOURCES = ('backends.py', 'peeling.py', 'registry.py', 'generated_registry.py',
            'formats.py', 'hashing.py', 'scanidentity.py', 'candidates.py',
            'engine.py', 'store.py')


@lru_cache(maxsize=128)
def _byte_digest(filename, mtime_ns, size):
    """Use stat data only to avoid rereading unchanged bytes, never as identity."""
    digest = hashlib.sha256()
    with Path(filename).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _resource_digest(path):
    path = Path(path)
    try:
        before = path.stat()
        if not path.is_file():
            raise OSError('not a regular file')
        digest = _byte_digest(str(path.resolve()), before.st_mtime_ns, before.st_size)
        after = path.stat()
    except OSError as error:
        raise ValueError(f'软件缺少扫描器校验资源 {path.name}；请重新安装完整发布包') from error
    if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
        raise ValueError(f'扫描器校验资源 {path.name} 在检查期间改变；不能复用缓存')
    return digest


def scan_signature():
    """Return the installed Python/native scanner identity, or reject reuse.

    Resolve the DLL exactly as hashing.native() does, without loading it. This
    keeps cache inspection read-only and avoids initializing a compute backend.
    A partial installation cannot prove that an old sweep is still complete.
    """
    dll = Path(native_path())
    if not dll.exists():
        dll = _SOURCE_ROOT.parent / 'native' / 'target' / 'release' / 'finder_native.dll'
    return {'version': 1,
            'native_sha256': _resource_digest(dll),
            'sources': {name: _resource_digest(_SOURCE_ROOT / name) for name in _SOURCES}}
