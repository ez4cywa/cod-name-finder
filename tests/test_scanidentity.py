import hashlib
import json
import os
from pathlib import Path

import pytest

from finder import completedcache, scanidentity
from finder.candidates import Plan
from finder.hashing import PROFILES
from finder.methods import plan_fingerprint


def install(root):
    sources = root / 'finder'
    sources.mkdir(parents=True)
    for name in scanidentity._SOURCES:
        (sources / name).write_bytes(('scanner source ' + name).encode())
    (root / 'finder_native.dll').write_bytes(b'installed native scanner')
    return sources


@pytest.fixture
def scanner(tmp_path, monkeypatch):
    root = tmp_path / 'installation'
    sources = install(root)
    monkeypatch.setattr(scanidentity, '_SOURCE_ROOT', sources)
    monkeypatch.setattr(scanidentity, 'native_path', lambda: root / 'finder_native.dll')
    scanidentity._byte_digest.cache_clear()
    return root


def fingerprint():
    return plan_fingerprint(Plan([['weapon'], ['_fire', '_reload']]),
        profiles=[PROFILES['iw-resource63']], targets=[('xanim', 123)],
        method={'method_id': 'observed', 'method_version': '1', 'generator_sha': 'a' * 64})


class Catalog:
    def meta(self, name, default=None):
        return 'catalog-content' if name == 'catalog_fingerprint' else default


def config(tmp_path):
    assets = tmp_path / 'assets'
    indexes = tmp_path / 'indexes'
    assets.mkdir()
    indexes.mkdir()
    (indexes / 'fnv1a_xanims.cdb').write_bytes(b'index content; no decoding required')
    return {'profile': 'iw-resource63', 'folder': str(assets), 'indexes': str(indexes)}


def change_bytes(path):
    before = path.stat()
    content = path.read_bytes()
    # Preserve byte count, so the test exercises the mtime part of the LRU key.
    path.write_bytes(bytes([content[0] ^ 1]) + content[1:])
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))


@pytest.mark.parametrize('resource', ['finder_native.dll', *scanidentity._SOURCES])
def test_source_and_native_byte_changes_invalidate_both_cache_fingerprints(
        scanner, tmp_path, resource):
    values = config(tmp_path)
    before_plan = fingerprint()
    before_complete = completedcache.signature(values, Catalog())
    assert before_complete
    path = scanner / resource if resource.endswith('.dll') else scanner / 'finder' / resource
    change_bytes(path)
    assert fingerprint() != before_plan
    after_complete = completedcache.signature(values, Catalog())
    assert after_complete and after_complete['key'] != before_complete['key']


def test_identical_content_at_different_install_paths_has_identical_signatures(
        scanner, tmp_path, monkeypatch):
    values = config(tmp_path)
    first = scanidentity.scan_signature()
    first_plan = fingerprint()
    first_complete = completedcache.signature(values, Catalog())['key']
    copied = tmp_path / 'a different installation'
    sources = install(copied)
    monkeypatch.setattr(scanidentity, '_SOURCE_ROOT', sources)
    monkeypatch.setattr(scanidentity, 'native_path', lambda: copied / 'finder_native.dll')
    assert scanidentity.scan_signature() == first
    assert fingerprint() == first_plan
    assert completedcache.signature(values, Catalog())['key'] == first_complete
    assert str(tmp_path) not in json.dumps(first)


def test_native_resolution_prefers_installed_dll_then_release_fallback(scanner):
    fallback = scanner / 'native' / 'target' / 'release' / 'finder_native.dll'
    fallback.parent.mkdir(parents=True)
    fallback.write_bytes(b'release fallback scanner')
    installed = scanner / 'finder_native.dll'
    assert scanidentity.scan_signature()['native_sha256'] == hashlib.sha256(installed.read_bytes()).hexdigest()
    installed.unlink()
    assert scanidentity.scan_signature()['native_sha256'] == hashlib.sha256(fallback.read_bytes()).hexdigest()


@pytest.mark.parametrize('resource', ['finder_native.dll', *scanidentity._SOURCES])
def test_missing_resources_reject_sweep_reuse_and_make_complete_cache_miss(
        scanner, tmp_path, resource):
    values = config(tmp_path)
    assert completedcache.signature(values, Catalog())
    path = scanner / resource if resource.endswith('.dll') else scanner / 'finder' / resource
    path.unlink()
    with pytest.raises(ValueError, match='扫描器校验资源.*完整发布包'):
        fingerprint()
    assert completedcache.signature(values, Catalog()) is None


def test_stat_changes_only_optimize_byte_reads_and_never_change_identity(scanner):
    first = scanidentity.scan_signature()
    first_cache = scanidentity._byte_digest.cache_info()
    assert scanidentity.scan_signature() == first
    assert scanidentity._byte_digest.cache_info().hits == first_cache.hits + len(scanidentity._SOURCES) + 1
    source = scanner / 'finder' / 'backends.py'
    before = source.stat()
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
    assert scanidentity.scan_signature() == first


def test_changed_resource_during_digest_is_rejected(scanner, monkeypatch):
    digest = scanidentity._byte_digest
    def unstable(filename, mtime_ns, size):
        value = digest(filename, mtime_ns, size)
        os.utime(filename, ns=(mtime_ns, mtime_ns + 1_000_000_000))
        return value
    monkeypatch.setattr(scanidentity, '_byte_digest', unstable)
    with pytest.raises(ValueError, match='检查期间改变'):
        scanidentity.scan_signature()


def test_signature_hashes_native_bytes_without_initializing_compute(scanner, monkeypatch):
    def forbidden():
        raise AssertionError('scanner identity must not initialize native or GPU')
    monkeypatch.setattr('finder.hashing.native', forbidden)
    assert len(scanidentity.scan_signature()['native_sha256']) == 64


def test_complete_signature_implementation_inventory_includes_scanner_sources():
    assert set(scanidentity._SOURCES) <= set(completedcache._IMPLEMENTATIONS)
