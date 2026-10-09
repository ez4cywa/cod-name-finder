"""Read-only extraction of independently verified, typed discovery contributions.

Private run files are evidence inputs, never submission attachments. The return
value is a strict whitelist; filenames, corpus contents and search parameters
are deliberately not propagated to the public contribution layer.
"""
from collections import Counter, defaultdict
from contextlib import closing
import csv
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import sqlite3
import struct

from .exporter import SALUKI_PACKAGES
from .formats import decode_cdb
from .generated_registry import DOMAINS
from .hashing import BUILTIN_IDS, PROFILES
from .snapshot import normalize_game


MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_ROWS = 10_000
_HEX = re.compile(r'^[0-9a-f]{16}$')
_SHA = re.compile(r'^[0-9a-f]{64}$')
_ID = re.compile(r'^[A-Za-z0-9_.-]{1,96}$')
_FIELDS = ('hash', 'name', 'profile', 'source', 'source_game', 'method',
           'method_id', 'method_version', 'generator_sha', 'profile_id',
           'mask_used', 'details')
_FIXED_FILES = frozenset(('verified.csv', 'new_names.csv', 'verified.cdb',
                          'evidence.jsonl', 'evidence.csv'))


def _fail(message):
    raise ValueError('贡献证据校验失败：' + message)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail('JSON 包含重复字段')
        result[key] = value
    return result


def _json(value):
    def invalid(_):
        _fail('JSON 包含非有限数字')
    try:
        return json.loads(value, object_pairs_hook=_object, parse_constant=invalid)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('贡献证据校验失败：JSON 格式无效') from error


def _read(path):
    """Bound a whole-file read and reject concurrent replacement or mutation."""
    path = Path(path)
    try:
        before = path.stat()
        if not path.is_file() or path.is_symlink():
            _fail('证据输入须为普通文件')
        if before.st_size > MAX_FILE_BYTES:
            _fail('证据文件超过 32MB 上限')
        with path.open('rb') as stream:
            value = stream.read(MAX_FILE_BYTES + 1)
        after = path.stat()
        if len(value) > MAX_FILE_BYTES:
            _fail('证据文件超过 32MB 上限')
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_ino, after.st_size, after.st_mtime_ns):
            _fail('证据文件在读取期间改变')
        return value
    except OSError as error:
        raise ValueError('贡献证据校验失败：缺少完整运行所需文件或文件不可读') from error


def _integer(value, label):
    if type(value) is not int or not 0 <= value <= (1 << 63) - 1:
        _fail(label + '须为非负整数')
    return value


def _number(value, label):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        _fail(label + '须为非负有限数字')
    return value


def _name(value):
    if (not isinstance(value, str) or not value or value.strip() != value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        _fail('名称格式无效')
    try:
        size = len(value.encode('utf-8'))
    except UnicodeError as error:
        raise ValueError('贡献证据校验失败：名称 UTF-8 无效') from error
    if size > 1024:
        _fail('名称超过 1024 字节')
    return value


def _csv_rows(blob):
    try:
        values = list(csv.reader(io.StringIO(blob.decode('utf-8'), newline=''), strict=True))
    except (UnicodeError, csv.Error) as error:
        raise ValueError('贡献证据校验失败：CSV 格式无效') from error
    result = {}
    for row in values:
        if len(row) != 2 or not _HEX.fullmatch(row[0]):
            _fail('新增 CSV 须为完整16位哈希与名称两列')
        if row[0] in result:
            _fail('新增 CSV 包含重复键')
        result[row[0]] = _name(row[1])
    return result


def _cdb(blob):
    if len(blob) < 16 or struct.unpack_from('<I', blob, 12)[0] > MAX_FILE_BYTES:
        _fail('CDB 解压内容超过 32MB 上限或头部无效')
    try:
        return {f'{key:016x}': _name(name) for key, name in decode_cdb(blob).items()}
    except Exception as error:
        raise ValueError('贡献证据校验失败：CDB 无效') from error


def _evidence(row):
    if not isinstance(row, dict) or not all(key in row for key in _FIELDS):
        _fail('证据记录缺少字段')
    result = {key: row[key] for key in _FIELDS}
    if any(not isinstance(result[key], str) for key in _FIELDS if key not in ('details', 'mask_used')):
        _fail('证据字段类型无效')
    if not _HEX.fullmatch(result['hash']):
        _fail('证据须保留完整16位哈希')
    _name(result['name'])
    mask = result['mask_used']
    if isinstance(mask, str) and re.fullmatch(r'[0-9]{1,20}', mask):
        mask = int(mask)
    if type(mask) is not int or not 0 <= mask < 1 << 64:
        _fail('证据比较掩码无效')
    result['mask_used'] = mask
    if isinstance(result['details'], str):
        result['details'] = _json(result['details'])
    if not isinstance(result['details'], dict):
        _fail('证据 details 须为对象')
    return result


def _evidence_key(row):
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _load_export(root):
    manifest = _json(_read(root / 'manifest.json'))
    if not isinstance(manifest, dict):
        _fail('导出清单无效')
    files = manifest.get('files')
    if not isinstance(files, dict) or not _FIXED_FILES <= set(files):
        _fail('导出清单缺少 CSV/CDB/证据文件')
    blobs = {}
    for name, digest in files.items():
        if not isinstance(name, str) or not isinstance(digest, str) or not _SHA.fullmatch(digest):
            _fail('导出清单 SHA256 无效')
        relative = PurePosixPath(name)
        package = (len(relative.parts) == 2 and relative.parts[0] == 'hash_pkg'
                   and re.fullmatch(r'[A-Za-z0-9_-]+\.cdb', relative.parts[1]))
        if name not in _FIXED_FILES and not package:
            _fail('导出清单包含非允许文件路径')
        path = root.joinpath(*relative.parts)
        if not path.resolve().is_relative_to(root):
            _fail('导出清单路径越界')
        blob = _read(path)
        if hashlib.sha256(blob).hexdigest() != digest:
            _fail('导出文件 SHA256 与清单不一致')
        blobs[name] = blob
    names = _csv_rows(blobs['new_names.csv'])
    if _csv_rows(blobs['verified.csv']) != names or _cdb(blobs['verified.cdb']) != names:
        _fail('CSV 与 CDB 名称集合不一致')
    if _integer(manifest.get('entries'), '导出条目数') != len(names):
        _fail('导出清单条目数不一致')
    evidence = []
    try:
        text = blobs['evidence.jsonl'].decode('utf-8')
    except UnicodeError as error:
        raise ValueError('贡献证据校验失败：证据 UTF-8 无效') from error
    for line in text.splitlines():
        if not line:
            _fail('JSONL 证据包含空记录')
        evidence.append(_evidence(_json(line)))
    if len(evidence) != len(set(map(_evidence_key, evidence))):
        _fail('JSONL 证据包含重复记录')
    if {(row['hash'], row['name']) for row in evidence} != set(names.items()):
        _fail('新增名称与证据集合不一致')
    try:
        reader = csv.DictReader(io.StringIO(blobs['evidence.csv'].decode('utf-8'), newline=''), strict=True)
        if reader.fieldnames != list(_FIELDS):
            _fail('证据 CSV 字段不一致')
        csv_evidence = [_evidence(row) for row in reader]
    except (UnicodeError, csv.Error) as error:
        raise ValueError('贡献证据校验失败：证据 CSV 无效') from error
    if Counter(map(_evidence_key, csv_evidence)) != Counter(map(_evidence_key, evidence)):
        _fail('CSV 与 JSONL 证据不一致')
    packages = {name.split('/')[1]: _cdb(blob) for name, blob in blobs.items() if name.startswith('hash_pkg/')}
    merged = {}
    for values in packages.values():
        for key, value in values.items():
            if key in merged and merged[key] != value:
                _fail('分类 CDB 名称冲突')
            merged[key] = value
    if merged != names:
        _fail('分类 CDB 与新增名称集合不一致')
    return manifest, names, evidence, packages


def _stats(report, manifest):
    if not isinstance(report, dict) or report.get('status') not in ('completed', 'partial'):
        _fail('须从已保存结果的完整或部分完成运行准备贡献')
    if report.get('version') != manifest.get('version') or _integer(report.get('entries'), '报告条目数') != manifest['entries']:
        _fail('运行报告与导出清单不一致')
    if type(report.get('full_keys')) is not bool or not report['full_keys']:
        _fail('运行报告不是完整键结果')
    result = {'processed': _integer(report.get('processed'), '实际候选数'),
              'seconds': _number(report.get('seconds'), '运行耗时'),
              'status': report['status']}
    for key in ('skipped_candidates', 'cached_hits', 'verified_target_matches', 'pending_low60_candidates'):
        result[key] = _integer(report.get(key, 0), key)
    reused = report.get('complete_cache_reused', False)
    if type(reused) is not bool:
        _fail('缓存复用标记无效')
    result['cache_reused'] = reused
    result['exported_rows'] = manifest['entries']
    return result


def _package(kind, profile, game):
    value = SALUKI_PACKAGES.get(kind, 'fnv1a_strings.cdb')
    if kind == 'bone' and profile == 'fnv1a32':
        return 'fnv1a_bones.cdb'
    if kind == 'bone' and profile == 'fnv1a60':
        return 'fnv1a_strings.cdb'
    if kind == 'soundbankalias' and game not in ('BO4', 'BOCW'):
        return 'fnv1a_soundbanks_aliases_v2.cdb'
    if kind == 'bone' and profile == 'fnv1a64':
        return 'fnv1a_bones_v2.cdb'
    return value.replace('_v2.cdb', '.cdb') if profile in ('fnv1a63', 'fnv1a64', 'fnv1a64-raw', 'sab-fnv1a64') else value


def _database(db, names, evidence, manifest, config):
    meta = dict(db.execute('SELECT key,value FROM meta'))
    if (meta.get('catalog_fingerprint') != manifest.get('catalog_sha256')
            or not isinstance(meta.get('catalog_fingerprint'), str)
            or not _SHA.fullmatch(meta['catalog_fingerprint'])):
        _fail('目标输入指纹与工作数据库不一致')
    if meta.get('build') != manifest.get('build'):
        _fail('目标作品与工作数据库不一致')
    if meta.get('target_truncated') != '0' or config.get('low60') is not False:
        _fail('低60位待核验结果不能贡献')
    if manifest.get('full_keys') is not True or manifest.get('roundtrip_verified') is not True:
        _fail('导出清单缺少完整键回读验证')
    pid = manifest.get('target_profile')
    if not isinstance(pid, str) or config.get('profile') != pid:
        _fail('目标 profile 与运行配置不一致')
    stored_profile = _json(meta.get('exported_profile', 'null'))
    if not isinstance(stored_profile, dict) or stored_profile.get('id') != pid:
        _fail('工作数据库缺少独立 profile 快照')
    game = normalize_game(config.get('game'))
    if normalize_game(meta['build']) != game:
        _fail('运行配置目标作品不一致')
    if game in ('MANUAL', '手动 / 已校准'):
        game = 'manual'
    elif game not in DOMAINS:
        _fail('目标作品不是已知本地规范标识')
    expected_mode = {'folder': 'exported-files', 'snapshot': 'snapshot'}.get(config.get('input_mode', 'folder'))
    if expected_mode is None or meta.get('input_mode') != expected_mode:
        _fail('运行配置输入模式与工作数据库不一致')
    if type(config.get('exclude_material')) is not bool or manifest.get('exclude_material') is not config['exclude_material']:
        _fail('运行配置材质过滤与导出清单不一致')
    selected = 'all-non-model' if config.get('asset_type') == 'auto' else [config.get('asset_type')]
    if manifest.get('types') != selected:
        _fail('运行配置目标类型与导出清单不一致')
    profile = PROFILES.get(pid) if pid in BUILTIN_IDS else None
    if profile is not None and stored_profile != profile.json():
        _fail('工作数据库 profile 配置被改变')
    by_hash = defaultdict(set)
    actual_evidence = set()
    names_by_hash = defaultdict(set)
    keys = sorted(names)
    for begin in range(0, len(keys), 400):
        batch = keys[begin:begin + 400]
        placeholders = ','.join('?' for _ in batch)
        for kind, key in db.execute('SELECT kind,hash FROM assets WHERE hash IN (' + placeholders + ')', batch):
            by_hash[key].add(kind)
        for row in db.execute('SELECT ' + ','.join(_FIELDS) + ' FROM evidence WHERE hash IN (' + placeholders + ')', batch):
            item = _evidence(dict(zip(_FIELDS, row)))
            names_by_hash[item['hash']].add(item['name'])
            actual_evidence.add(_evidence_key(item))
    if any(len(values) != 1 for values in names_by_hash.values()):
        _fail('工作数据库中的导出键存在名称冲突')
    for row in evidence:
        if _evidence_key(row) not in actual_evidence or not by_hash[row['hash']]:
            _fail('导出证据与工作数据库不一致')
    snapshot_valid = set()
    if profile is not None and meta['input_mode'] == 'snapshot':
        for kind, raw, record_profile, width, mask, status in db.execute(
                'SELECT kind,raw_hash,profile,key_width,stored_mask,status FROM snapshot_records'):
            if (status == 'included' and record_profile == pid and type(width) is int
                    and profile.mask.bit_length() <= width <= 64 and isinstance(mask, str)
                    and _HEX.fullmatch(mask) and int(mask, 16) & profile.mask == profile.mask
                    and isinstance(raw, str) and _HEX.fullmatch(raw)):
                key = f'{int(raw, 16) & profile.mask:016x}'
                if key in names and kind in by_hash[key]:
                    snapshot_valid.add((kind, key))
    return meta, game, pid, profile, by_hash, snapshot_valid


def _eligible_kind(db, row, kinds, meta, profile, snapshot_valid):
    details = row['details']
    generation = details.get('candidate_generation', {})
    if not isinstance(generation, dict):
        _fail('生成器证据无效')
    selected = generation.get('target_kinds', [])
    if not isinstance(selected, list) or any(not isinstance(kind, str) for kind in selected):
        _fail('生成器目标类型无效')
    allowed = set(kinds)
    if selected:
        if not set(selected) & allowed:
            _fail('生成器目标类型与实际目标不一致')
        allowed &= set(selected)
    task = db.execute('SELECT config FROM tasks WHERE id=?', (row['source'],)).fetchone()
    if task:
        cfg = _json(task[0])
        if not isinstance(cfg, dict):
            _fail('发现任务配置无效')
        task_kinds = cfg.get('kinds', [])
        if not isinstance(task_kinds, list) or any(not isinstance(kind, str) for kind in task_kinds):
            _fail('任务目标类型无效')
        if task_kinds:
            if not set(task_kinds) & kinds:
                _fail('任务目标类型与实际目标不一致')
            allowed &= set(task_kinds)
            if not allowed:
                _fail('发现证据与任务目标类型不一致')
    if len(allowed) != 1:
        return None, 'ambiguous_kind'
    kind = next(iter(allowed))
    if meta.get('input_mode') == 'snapshot' and (kind, row['hash']) not in snapshot_valid:
        _fail('快照记录未证明该类型的完整键与完整比较掩码')
    return kind, None


def collect_export(export_dir):
    """Validate a complete local run and return only safe discovery evidence.

    ``partial`` runs are accepted: every contributed row must still prove a
    complete key. Unsupported types/domains and non-discovery sources are
    counted and skipped. Inconsistent artifacts or more than 10,000 eligible
    rows reject the entire preparation. SQLite is queried in a read-only
    transaction, not loaded as a whole file or opened through migrating Store.
    """
    try:
        root = Path(export_dir).resolve(strict=True)
        if not root.is_dir():
            _fail('请选择完整 names 导出目录')
        manifest, names, evidence, packages = _load_export(root)
        run = root.parent
        report = _json(_read(run / 'report.json'))
        config = _json(_read(run / 'configuration.json'))
        if not isinstance(config, dict):
            _fail('运行配置无效')
        stats = _stats(report, manifest)
        database = run / 'work.sqlite'
        if not database.is_file() or database.is_symlink():
            _fail('需要相邻完整运行的只读工作数据库')
        wal = Path(str(database) + '-wal')
        if wal.exists() and wal.stat().st_size:
            _fail('工作数据库仍有未合并 WAL；请结束运行后重试')
        before_db = database.stat()
        # The worker closes/checkpoints its DB before a saved run is reviewed.
        # immutable avoids creating WAL/SHM files in the private source folder.
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1',
                uri=True, isolation_level=None, timeout=5)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            meta, game, pid, profile, kinds_by_hash, snapshot_valid = _database(db, names, evidence, manifest, config)
            expected_packages = defaultdict(dict)
            for key, name in names.items():
                for kind in kinds_by_hash[key]:
                    if kind == 'xmodel' or manifest.get('exclude_material') and kind == 'material':
                        continue
                    selected = manifest.get('types')
                    if isinstance(selected, list) and kind not in selected:
                        continue
                    expected_packages[_package(kind, pid, meta['build'])][key] = name
            if dict(expected_packages) != packages:
                _fail('分类 CDB 与工作数据库目标类型不一致')
            rejected = Counter()
            groups = defaultdict(list)
            for row in evidence:
                groups[(row['hash'], row['name'])].append(row)
            rows = []
            for (key, name), choices in sorted(groups.items()):
                discovered = [row for row in choices if row['method'] == 'discovered']
                if not discovered:
                    rejected['not_discovered'] += 1
                    continue
                if profile is None:
                    rejected['unsupported_profile'] += 1
                    continue
                accepted = []
                reasons = []
                for row in discovered:
                    details = row['details']
                    if (row['profile'] != pid or row['profile_id'] != pid
                            or row['mask_used'] != profile.mask
                            or details.get('target_profile') != profile.json()
                            or details.get('target_truncated')):
                        _fail('发现证据的完整 profile 或掩码不一致')
                    if profile.digest(name) != int(key, 16):
                        _fail('发现名称未通过独立完整键回算')
                    if (not _ID.fullmatch(row['method_id']) or not _ID.fullmatch(row['method_version'])
                            or not _SHA.fullmatch(row['generator_sha'])):
                        _fail('发现方法元数据无效')
                    input_mode = 'snapshot' if meta.get('input_mode') == 'snapshot' else 'folder'
                    if details.get('target_input_mode', input_mode) != input_mode:
                        _fail('发现证据目标输入模式不一致')
                    if details.get('snapshot_fingerprint') not in (None, meta.get('snapshot_fingerprint')):
                        _fail('发现证据快照指纹不一致')
                    kind, reason = _eligible_kind(db, row, kinds_by_hash[key], meta, profile, snapshot_valid)
                    if reason:
                        reasons.append(reason)
                    elif game not in DOMAINS:
                        reasons.append('unsupported_game')
                    elif kind == 'xmodel' or not any(domain['status'] == 'evidence'
                            and domain['profile'] == pid and kind in domain['kinds'] for domain in DOMAINS[game]):
                        reasons.append('unsupported_domain')
                    else:
                        accepted.append({'kind': kind, 'hash': key, 'name': name, 'profile': pid,
                            'method_id': row['method_id'], 'method_version': row['method_version'],
                            'generator_sha': row['generator_sha']})
                accepted_kinds = {row['kind'] for row in accepted}
                if len(accepted_kinds) > 1:
                    rejected['ambiguous_kind'] += 1
                elif accepted:
                    rows.append(min(accepted, key=lambda row: (row['method_id'], row['method_version'], row['generator_sha'])))
                else:
                    rejected[sorted(reasons)[0]] += 1
                if len(rows) > MAX_ROWS:
                    _fail('可提交名称超过 10000 条上限，请拆分后重试')
            stats['accepted_rows'] = len(rows)
            stats['rejected_rows'] = sum(rejected.values())
            after_db = database.stat()
            if (before_db.st_ino, before_db.st_size, before_db.st_mtime_ns) != (
                    after_db.st_ino, after_db.st_size, after_db.st_mtime_ns) or wal.exists() and wal.stat().st_size:
                _fail('工作数据库在读取期间改变')
            return {'game': game, 'profile': pid if profile else 'unsupported', 'rows': rows, 'stats': stats,
                    'rejected': dict(sorted(rejected.items()))}
    except sqlite3.Error as error:
        raise ValueError('贡献证据校验失败：只读工作数据库结构或内容无效') from error
    except OSError as error:
        raise ValueError('贡献证据校验失败：完整运行目录不可读') from error
