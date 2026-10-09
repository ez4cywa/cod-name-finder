"""Content-addressed reuse of a fully completed search, with CPU revalidation.

Input checks stream file bytes and inspect readable filenames. They never
decode name databases or rebuild candidate plans. Cached evidence is a private
optimization: every row and its target type are checked before any row is
restored, and ordinary export still applies conflicts and Saluki exclusions.
"""
from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import zlib

from .asset_names import parse_exported_name
from .generated_registry import REGISTRY_SHA256
from .hashing import PROFILES, parse_hash
from .methods import canonical_json
from .scanidentity import scan_signature


SCHEMA_VERSION = 2
_MAX_PAYLOAD = 256 * 1024 * 1024
_DICTIONARY_SUFFIXES = frozenset(('.txt', '.tsv', '.csv', '.cdb', '.wni'))
_IMPLEMENTATIONS = ('autoplans.py', 'crossassets.py', 'weapon.py', 'soundplans.py', 'soundbyte.py',
                    'spellings.py', 'typedplans.py', 'community.py',
                    'candidates.py', 'completedcache.py', 'hashing.py',
                    'pipeline.py', 'engine.py', 'asset_names.py', 'methods.py','snapshot.py',
                    'backends.py', 'peeling.py', 'registry.py', 'generated_registry.py',
                    'formats.py', 'scanidentity.py', 'store.py',
                    'cordycep_profiles.json')
_SEMANTIC_FIELDS = ('game', 'profile', 'asset_type', 'exclude_material', 'keyword',
                    'low60', 'number_max', 'cross_asset', 'hash_domain',
                    'allow_unverified_domain', 'community','input_mode')
_EVIDENCE_FIELDS = ('hash', 'name', 'profile', 'source', 'source_game', 'method',
                    'details', 'method_id', 'method_version', 'generator_sha',
                    'profile_id', 'mask_used')


class _Cancelled(Exception):
    pass


def _check(control):
    if control() != 'run':
        raise _Cancelled()


def _sha_file(path, control):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        before = Path(path).stat()
        while True:
            _check(control)
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = Path(path).stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('输入内容在缓存检查期间改变')
    return digest.hexdigest()


def _files(root, suffixes, control):
    result = []
    for path in Path(root).rglob('*'):
        _check(control)
        if path.is_file() and path.suffix.lower() in suffixes:
            result.append(path)
    return sorted(result)


def _implementation_hashes(control):
    root = Path(__file__).parent
    return {name: _sha_file(root / name, control) for name in _IMPLEMENTATIONS}


def _names_signature(names):
    ordered = sorted(set(names))
    return {'count': len(ordered),
            'sha256': hashlib.sha256(canonical_json(ordered).encode('utf-8')).hexdigest()}


def _readable_names(folder, profile, control):
    names = set()
    for file in Path(folder).rglob('*'):
        _check(control)
        if file.is_file() and parse_exported_name(file, root=folder,
                min_digits=1 if profile.mask <= 0xffffffff else 8) is None:
            value = file.stem
            if value and not any(c in value for c in '\x00\r\n') and len(value.encode('utf-8')) <= 1024:
                names.add(value)
    return names


def signature(config, store, control=lambda: 'run'):
    """Return a path-independent input key and current-path provenance, or None.

    Run only after importing the target snapshot. A cancelled check, missing
    input, or an optional community snapshot requiring synchronization is a
    cache miss; the caller can then stop or use ordinary preparation.
    Runtime choices such as backend, time and candidate budgets do not change a
    completed search's membership. A partial search must never be saved.
    """
    values = asdict(config) if is_dataclass(config) else dict(config)
    try:
        _check(control)
        profile = PROFILES[values['profile']]
        sources = []
        indexes = Path(values['indexes'])
        indexes = indexes / 'hash_pkg' if (indexes / 'hash_pkg').is_dir() else indexes
        index_rows = []
        for path in _files(indexes, ('.cdb',), control):
            row = {'logical_name': path.relative_to(indexes).as_posix(),
                   'sha256': _sha_file(path, control)}
            index_rows.append(row)
            sources.append({'file': str(path.resolve()), 'role': 'index', **row})
        if not index_rows or not store.meta('catalog_fingerprint'):
            return None
        dictionary_rows = {}
        for field, role in (('dictionary', 'dictionary'), ('borrowed_dictionary', 'borrowed')):
            supplied = values.get(field, '')
            rows = []
            if supplied:
                root = Path(supplied)
                files = _files(root, _DICTIONARY_SUFFIXES, control) if root.is_dir() else [root]
                if not files:
                    return None
                for path in files:
                    _check(control)
                    row = {'suffix': path.suffix.lower(), 'sha256': _sha_file(path, control)}
                    rows.append(row)
                    sources.append({'file': str(path.resolve()), 'role': role,
                        'logical_name': path.relative_to(root).as_posix() if root.is_dir() else path.name,
                        **row})
            # Candidate dictionaries are sets of text; their disk names and
            # directory traversal order do not change name membership.
            dictionary_rows[role] = sorted(rows, key=canonical_json)
        community = {'enabled': bool(values.get('community'))}
        if community['enabled']:
            if values.get('community_refresh'):
                return None
            cache = Path(values.get('community_cache') or Path(values['output']) / '.community-cache')
            metadata = json.loads((cache / 'current.json').read_text(encoding='utf-8'))
            commit = metadata.get('commit', '')
            if not re.fullmatch(r'[0-9a-f]{40}', commit):
                return None
            files = metadata.get('files')
            if not isinstance(files, list) or not files:
                return None
            rows = []
            for item in files:
                _check(control)
                name = item['name']
                if not re.fullmatch(r'[A-Za-z0-9_-]+\.csv', name):
                    return None
                path = cache / 'snapshots' / commit / 'csv' / name
                digest = _sha_file(path, control)
                if digest != item['sha256']:
                    return None
                row = {'logical_name': name, 'sha256': digest}
                rows.append(row)
                sources.append({'file': str(path.resolve()), 'role': 'community', **row})
            community.update(commit=commit, files=sorted(rows, key=canonical_json))
        snapshot_rows=[]
        if values.get('input_mode','folder')=='snapshot':
            if store.meta('input_mode')!='snapshot' or not store.meta('snapshot_fingerprint'):
                return None
            for original in json.loads(store.meta('snapshot_sources','[]')):
                path=Path(original['file'])
                digest=_sha_file(path,control)
                row={'role':original['role'],'logical_name':original['logical_name'],'sha256':digest}
                snapshot_rows.append(row)
                sources.append({'file':str(path.resolve()),**row})
            readable=_names_signature(())
        else:
            readable = _names_signature(_readable_names(values['folder'], profile, control))
        related = _names_signature(())
        if values.get('cross_asset') and values.get('related_folder'):
            # Shared helper examines only relative filenames, never asset bytes.
            from .pipeline import related_file_names
            names, _, loaded = related_file_names(values['related_folder'], control)
            if not loaded:
                return None
            related = _names_signature(names)
        payload = {'schema_version': SCHEMA_VERSION, 'registry_sha256': REGISTRY_SHA256,
            'scanner': scan_signature(),
            'profile': profile.json(), 'implementations': _implementation_hashes(control),
            'catalog_fingerprint': store.meta('catalog_fingerprint'),
            'snapshot':snapshot_rows,
            'options': {field: values.get(field) for field in _SEMANTIC_FIELDS},
            'indexes': index_rows, 'dictionaries': dictionary_rows,
            'readable_names': readable, 'related_names': related, 'community': community}
        _check(control)
        return {'key': hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest(),
                'sources': sources, 'inputs': payload}
    except (_Cancelled, OSError, ValueError, TypeError, KeyError):
        return None


def _target_pairs(store):
    return sorted({(str(row['kind']), str(row['hash'])) for row in
                   store.db.execute('SELECT kind,hash FROM assets')})


def _validated_evidence(record, store, profile_id, low60):
    if (record.get('schema_version') != SCHEMA_VERSION or not isinstance(record.get('summary'), dict)
            or record['summary'].get('status') != 'completed'):
        raise ValueError('不兼容的完整任务缓存')
    profile = PROFILES[profile_id]
    if record['profile'] != profile.json() or record['low60'] is not bool(low60):
        raise ValueError('完整任务缓存的 profile 或低60位模式不一致')
    current_profile = json.loads(store.meta('exported_profile'))
    if current_profile != profile.json() or (store.meta('target_truncated', '0') == '1') != bool(low60):
        raise ValueError('当前目标的 profile 或比较掩码不一致')
    pairs = _target_pairs(store)
    cached_pairs = sorted({(str(kind), str(key)) for kind, key in record['targets']})
    if cached_pairs != pairs or any(kind == 'xmodel' for kind, _ in cached_pairs):
        raise ValueError('完整任务缓存的目标类型/完整键集合不一致')
    kinds_by_hash = {}
    for kind, key in pairs:
        kinds_by_hash.setdefault(key, set()).add(kind)
    mask = profile.mask & ((1 << 60) - 1) if low60 else profile.mask
    effective = profile.json() | {'mask': mask}
    evidence = record['evidence']
    if not isinstance(evidence, list):
        raise ValueError('完整任务缓存缺少证据列表')
    validated = []
    for original in evidence:
        hit = dict(original)
        if not all(field in hit for field in _EVIDENCE_FIELDS):
            raise ValueError('完整任务缓存缺少证据元数据')
        if any(not isinstance(hit[field], str) for field in _EVIDENCE_FIELDS if field != 'details'):
            raise ValueError('完整任务缓存的证据类型无效')
        h = parse_hash(hit['hash'])
        key = f'{h:016x}'
        if key not in kinds_by_hash or set(hit['_asset_kinds']) != kinds_by_hash[key]:
            raise ValueError('缓存证据未对应当前目标类型')
        if hit['profile'] != profile_id or hit['profile_id'] != profile_id or hit['mask_used'] != str(mask):
            raise ValueError('缓存证据的 profile 或掩码被改变')
        details = json.loads(hit['details']) if isinstance(hit['details'], str) else dict(hit['details'])
        configuration = details.get('target_profile') or details.get('source_profile')
        if configuration not in (profile.json(), effective):
            raise ValueError('缓存证据的独立 profile 快照不一致')
        if details.get('asset_type') and details['asset_type'] not in kinds_by_hash[key]:
            raise ValueError('缓存证据资产类型不一致')
        partial = hit['method'] in ('partial_match', 'prior_partial') or bool(details.get('target_truncated'))
        if partial != bool(low60) or low60 and hit['method'] not in ('partial_match', 'prior_partial'):
            raise ValueError('待核验低60位证据不可作为完整名称恢复')
        if not hit['name'] or len(hit['name'].encode('utf-8')) > 1024 or profile.digest(hit['name']) & mask != h:
            raise ValueError('缓存证据未通过独立 Python 哈希验证')
        hit.update(hash=key, details=details)
        validated.append(hit)
    return validated


class CompletedCache:
    """Compressed completed-run records beside ordinary sweep ledger tables."""
    def __init__(self, path, readonly=False):
        self.path = Path(path)
        self.readonly = bool(readonly)
        if self.readonly:
            self.path = self.path.resolve(strict=True)
            immutable = '&immutable=1' if not Path(str(self.path) + '-wal').exists() else ''
            self.db = sqlite3.connect(self.path.as_uri() + '?mode=ro' + immutable, uri=True, timeout=60)
            self.db.execute('PRAGMA query_only=ON')
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(self.path, timeout=60)
            self.db.execute('PRAGMA journal_mode=WAL')
            with self.db:
                self.db.execute('CREATE TABLE IF NOT EXISTS complete_runs('
                    'key TEXT PRIMARY KEY,payload BLOB,payload_sha256 TEXT,created REAL)')
        self.db.execute('PRAGMA busy_timeout=60000')

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def lookup(self, key):
        try:
            row = self.db.execute('SELECT payload,payload_sha256 FROM complete_runs WHERE key=?', (key,)).fetchone()
            if row is None:
                return None
            decompressor = zlib.decompressobj()
            blob = decompressor.decompress(row[0], _MAX_PAYLOAD + 1)
            if (len(blob) > _MAX_PAYLOAD or decompressor.unconsumed_tail or not decompressor.eof
                    or decompressor.unused_data or hashlib.sha256(blob).hexdigest() != row[1]):
                return None
            record = json.loads(blob)
            if record.get('key') != key or record.get('schema_version') != SCHEMA_VERSION:
                return None
            if (not isinstance(record.get('summary'), dict) or record['summary'].get('status') != 'completed'
                    or not isinstance(record.get('evidence'), list)):
                return None
            return record
        except Exception:
            return None

    def save(self, key, store, summary):
        if self.readonly:
            raise ValueError('只读完整任务缓存不可写入')
        if not isinstance(summary, dict) or summary.get('status') != 'completed':
            raise ValueError('只允许保存已完成任务；暂停、失败或预算未扫完的任务不能完整复用')
        pairs = _target_pairs(store)
        kinds_by_hash = {}
        for kind, target in pairs:
            kinds_by_hash.setdefault(target, set()).add(kind)
        evidence = []
        for row in store.db.execute('SELECT * FROM evidence ORDER BY hash,name,profile,source,method'):
            hit = dict(row)
            hit['_asset_kinds'] = sorted(kinds_by_hash.get(hit['hash'], ()))
            evidence.append(hit)
        record = {'schema_version': SCHEMA_VERSION, 'key': key, 'summary': dict(summary),
            'targets': pairs, 'profile': json.loads(store.meta('exported_profile')),
            'low60': store.meta('target_truncated', '0') == '1', 'evidence': evidence}
        _validated_evidence(record, store, record['profile']['id'], record['low60'])
        blob = canonical_json(record).encode('utf-8')
        if len(blob) > _MAX_PAYLOAD:
            return
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO complete_runs VALUES (?,?,?,?)',
                (key, zlib.compress(blob), hashlib.sha256(blob).hexdigest(), time.time()))

    @staticmethod
    def restore(record, store, profile_id, low60=False):
        """Validate the whole package first, then restore in one savepoint."""
        try:
            evidence = _validated_evidence(record, store, profile_id, low60)
        except Exception:
            return None
        inserted = 0
        try:
            store.db.execute('SAVEPOINT completed_cache_restore')
            for hit in evidence:
                details = hit['details'] | {'completed_run_cache': True, 'completed_cache_key': record.get('key')}
                before = store.db.total_changes
                store.add_evidence(parse_hash(hit['hash']), hit['name'], hit['profile'], hit['source'],
                    hit['source_game'], hit['method'], details, method_id=hit['method_id'],
                    method_version=hit['method_version'], generator_sha=hit['generator_sha'],
                    profile_id=hit['profile_id'], mask_used=int(hit['mask_used']))
                inserted += store.db.total_changes - before
                if not low60:
                    store.db.execute('INSERT OR IGNORE INTO words VALUES (?)', (hit['name'],))
            store.db.execute('RELEASE SAVEPOINT completed_cache_restore')
        except Exception:
            try:
                store.db.execute('ROLLBACK TO SAVEPOINT completed_cache_restore')
                store.db.execute('RELEASE SAVEPOINT completed_cache_restore')
            except sqlite3.Error:
                pass
            return None
        return {'inserted': inserted, 'verified': 0 if low60 else len(evidence),
                'pending_low60': len(evidence) if low60 else 0, 'total': len(evidence)}
