from dataclasses import asdict
from contextlib import closing
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import struct

import pytest

from finder import contribution_evidence as contribution
from finder.exporter import export
from finder.formats import decode_cdb, encode_cdb
from finder.hashing import PROFILES
from finder.pipeline import Config
from finder.store import Store


def fixture(tmp_path, *, game='COD2026', profile='iw-resource63',
            targets=None, method='discovered', status='completed', typed=None,
            snapshot=False, snapshot_width=None, snapshot_mask=None):
    targets = targets or [('xanim', 'rex_vm_ar_fixture_fire')]
    assets = tmp_path / 'private-assets'
    indexes = tmp_path / 'private-indexes'
    run = tmp_path / 'run-private-keyword'
    assets.mkdir(); indexes.mkdir(); run.mkdir()
    p = PROFILES[profile]
    for kind, name in targets:
        (assets / f'{kind}_{p.digest(name):016x}.bin').write_bytes(b'private asset data')
    (indexes / 'fnv1a_xanims_v2.cdb').write_bytes(encode_cdb({123: 'already-known'}))
    config = Config(str(assets), str(indexes), str(tmp_path / 'output'), game=game,
                    profile=profile, asset_type='auto', exclude_material=False,
                    keyword='private-keyword', input_mode='snapshot' if snapshot else 'folder')
    store = Store(run / 'work.sqlite')
    store.import_exported(assets, game, profile)
    with store.db:
        if snapshot:
            store.setmeta('input_mode', 'snapshot')
            store.setmeta('snapshot_fingerprint', 'f' * 64)
            for index, (kind, name) in enumerate(targets):
                store.db.execute('INSERT INTO snapshot_records VALUES (?,?,?,?,?,?,?)',
                    (index, f'{p.digest(name):016x}', kind, profile,
                     snapshot_width if snapshot_width is not None else p.mask.bit_length(),
                     f'{snapshot_mask if snapshot_mask is not None else p.mask:016x}', 'included'))
        for kind, name in sorted(set(targets)):
            details = {'target_profile': p.json(), 'candidate_generation': {
                'generator': 'private-keyword', 'source_names': ['private-source-name'],
                **({'target_kinds': typed} if typed is not None else {})},
                'index_sources': [{'file': str(indexes), 'sha256': 'a' * 64}],
                'target_input_mode': config.input_mode}
            if snapshot:
                details['snapshot_fingerprint'] = 'f' * 64
            store.add_evidence(p.digest(name), name, profile, 'private-task-id', 'private-source-game', method,
                details, method_id='soundplans.observed', method_version='1', generator_sha='a' * 64)
    result = export(store, run, exclude_material=False, profile_id=profile, saluki_dir=indexes, allow_empty=True)
    store.close()
    report = {'version': result['version'], 'status': status, 'entries': result['entries'],
              'processed': 321, 'seconds': 1.25, 'full_keys': True,
              'skipped_candidates': 10, 'cached_hits': 1, 'complete_cache_reused': False,
              'verified_target_matches': len(set(name for _, name in targets)),
              'private': str(assets), 'keyword': 'private-keyword'}
    (run / 'report.json').write_text(json.dumps(report), encoding='utf-8')
    (run / 'configuration.json').write_text(json.dumps(asdict(config)), encoding='utf-8')
    return Path(result['path'])


def rehash(root):
    path = root / 'manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    manifest['files'] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                         for name in manifest['files']}
    path.write_text(json.dumps(manifest), encoding='utf-8')


def evidence_rows(root):
    return [json.loads(line) for line in (root / 'evidence.jsonl').read_text(encoding='utf-8').splitlines()]


def replace_evidence(root, rows, *, database=False):
    (root / 'evidence.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    with (root / 'evidence.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=contribution._FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row | {'details': json.dumps(row['details'])})
    if database:
        with closing(sqlite3.connect(root.parent / 'work.sqlite')) as db, db:
            for row in rows:
                db.execute('UPDATE evidence SET ' + ','.join(field + '=?' for field in contribution._FIELDS)
                    + ' WHERE hash=? AND source=?',
                    [json.dumps(row[field]) if field == 'details' else str(row[field])
                     for field in contribution._FIELDS] + [row['hash'], row['source']])
    rehash(root)


def mutate_json(path, **values):
    data = json.loads(path.read_text(encoding='utf-8'))
    path.write_text(json.dumps(data | values), encoding='utf-8')


def fingerprint_tree(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


def test_collect_returns_typed_discovery_without_private_metadata_and_is_readonly(tmp_path):
    root = fixture(tmp_path)
    before = fingerprint_tree(tmp_path)
    result = contribution.collect_export(root)
    assert result['game'] == 'COD2026' and result['profile'] == 'iw-resource63'
    assert result['rows'] == [{'kind': 'xanim', 'hash': f'{PROFILES["iw-resource63"].digest("rex_vm_ar_fixture_fire"):016x}',
        'name': 'rex_vm_ar_fixture_fire', 'profile': 'iw-resource63',
        'method_id': 'soundplans.observed', 'method_version': '1', 'generator_sha': 'a' * 64}]
    assert result['stats']['processed'] == 321 and result['stats']['seconds'] == 1.25
    assert result['stats']['accepted_rows'] == 1 and result['rejected'] == {}
    text = json.dumps(result)
    assert all(private not in text for private in (str(tmp_path), 'private-keyword', 'private-source-name', 'private-task-id', 'private-source-game', 'details'))
    assert fingerprint_tree(tmp_path) == before


@pytest.mark.parametrize('status', ['completed', 'partial'])
def test_finished_and_partial_runs_keep_complete_rows(tmp_path, status):
    root = fixture(tmp_path, status=status)
    assert contribution.collect_export(root)['stats']['status'] == status


@pytest.mark.parametrize('method', ['catalog_verified', 'prior_verified', 'prior_partial', 'partial_match'])
def test_only_discovered_sources_are_contributed(tmp_path, method):
    root = fixture(tmp_path, method=method)
    result = contribution.collect_export(root)
    assert result['rows'] == []
    assert result['rejected'] == ({'not_discovered': 1} if 'partial' not in method else {})


def test_mixed_supported_and_unsupported_domains_are_counted_per_name(tmp_path):
    root = fixture(tmp_path, targets=[('xanim', 'rex_vm_ar_fixture_fire'), ('dvar', 'unsupported_setting')])
    result = contribution.collect_export(root)
    assert [row['kind'] for row in result['rows']] == ['xanim']
    assert result['rejected'] == {'unsupported_domain': 1}


def test_ambiguous_hash_in_two_types_is_not_guessed(tmp_path):
    root = fixture(tmp_path, targets=[('xanim', 'shared_resource_name'), ('sndasset', 'shared_resource_name')])
    assert contribution.collect_export(root)['rejected'] == {'ambiguous_kind': 1}


def test_observed_target_kind_resolves_hash_ambiguity(tmp_path):
    root = fixture(tmp_path, targets=[('xanim', 'shared_resource_name'), ('sndasset', 'shared_resource_name')], typed=['xanim'])
    assert [row['kind'] for row in contribution.collect_export(root)['rows']] == ['xanim']


@pytest.mark.parametrize('profile,game,kind', [('fnv1a64', 'BO7', 'soundbankalias'),
    ('iw-resource63', 'COD2026', 'sndasset'), ('fnv1a32', 'MWII', 'bone'), ('fnv1a60', 'BOCW', 'bone')])
def test_registered_full_domains_include_32_60_63_and_highbit64(tmp_path, profile, game, kind):
    p = PROFILES[profile]
    name = next('alias_' + str(index) for index in range(10000) if profile != 'fnv1a64' or p.digest('alias_' + str(index)) >> 63)
    root = fixture(tmp_path, profile=profile, game=game, targets=[(kind, name)])
    assert contribution.collect_export(root)['rows'][0]['hash'] == f'{p.digest(name):016x}'


def test_snapshot_included_full63_target_is_accepted(tmp_path):
    root = fixture(tmp_path, snapshot=True)
    assert len(contribution.collect_export(root)['rows']) == 1


@pytest.mark.parametrize('mutation', ['lost_mask', 'lost_width', 'not_included', 'wrong_profile', 'wrong_raw'])
def test_snapshot_must_prove_full_width_included_key(tmp_path, mutation):
    root = fixture(tmp_path, profile='fnv1a64', game='BO7', targets=[('soundbankalias', 'fixture_alias')], snapshot=True)
    changes = {'lost_mask': ('stored_mask', f'{(1 << 63) - 1:016x}'),
        'lost_width': ('key_width', 63), 'not_included': ('status', 'domain_lost_bits'),
        'wrong_profile': ('profile', 'fnv1a63'), 'wrong_raw': ('raw_hash', '0000000000000001')}
    field, value = changes[mutation]
    with closing(sqlite3.connect(root.parent / 'work.sqlite')) as db, db:
        db.execute('UPDATE snapshot_records SET ' + field + '=?', (value,))
    with pytest.raises(ValueError, match='快照记录'):
        contribution.collect_export(root)


@pytest.mark.parametrize('file', ['new_names.csv', 'verified.csv', 'verified.cdb', 'evidence.jsonl', 'evidence.csv'])
def test_manifest_content_digest_mismatch_rejects_whole_export(tmp_path, file):
    root = fixture(tmp_path)
    path = root / file
    path.write_bytes(path.read_bytes() + b'tampered')
    with pytest.raises(ValueError, match='SHA256'):
        contribution.collect_export(root)


def test_consistently_rehashed_different_csv_is_still_rejected(tmp_path):
    root = fixture(tmp_path)
    (root / 'new_names.csv').write_text('0000000000000001,forged\n', encoding='utf-8')
    rehash(root)
    with pytest.raises(ValueError, match='名称集合'):
        contribution.collect_export(root)


def test_export_evidence_must_match_database_even_if_manifest_rehashed(tmp_path):
    root = fixture(tmp_path)
    rows = evidence_rows(root)
    rows[0]['method_id'] = 'forged.method'
    replace_evidence(root, rows)
    with pytest.raises(ValueError, match='工作数据库不一致'):
        contribution.collect_export(root)


@pytest.mark.parametrize('change', ['mask', 'profile', 'configuration', 'method', 'typed_kind', 'snapshot_fingerprint'])
def test_discovered_evidence_metadata_is_rechecked_after_db_agreement(tmp_path, change):
    root = fixture(tmp_path)
    rows = evidence_rows(root)
    row = rows[0]
    if change == 'mask': row['mask_used'] = (1 << 60) - 1
    if change == 'profile': row['profile_id'] = 'fnv1a63'
    if change == 'configuration': row['details']['target_profile']['ascii_lower'] = False
    if change == 'method': row['method_id'] = 'private/path'
    if change == 'typed_kind': row['details']['candidate_generation']['target_kinds'] = ['image']
    if change == 'snapshot_fingerprint': row['details']['snapshot_fingerprint'] = 'unexpected'
    replace_evidence(root, rows, database=True)
    with pytest.raises(ValueError):
        contribution.collect_export(root)


def test_full_cpu_rehash_catches_consistent_forged_name(tmp_path):
    root = fixture(tmp_path)
    rows = evidence_rows(root)
    rows[0]['name'] = 'forged_complete_name'
    for name in ('new_names.csv', 'verified.csv'):
        (root / name).write_text(rows[0]['hash'] + ',forged_complete_name\n', encoding='utf-8')
    for path in [root / 'verified.cdb', *root.glob('hash_pkg/*.cdb')]:
        path.write_bytes(encode_cdb({int(rows[0]['hash'], 16): 'forged_complete_name'}))
    replace_evidence(root, rows, database=True)
    with pytest.raises(ValueError, match='独立完整键回算'):
        contribution.collect_export(root)


@pytest.mark.parametrize('field,value', [('processed', -1), ('processed', True), ('seconds', -1),
    ('seconds', float('inf')), ('seconds', float('nan')), ('seconds', 10 ** 400),
    ('processed', 1 << 100), ('cached_hits', 1.5), ('complete_cache_reused', 1)])
def test_stats_accept_only_nonnegative_finite_numbers_and_real_booleans(tmp_path, field, value):
    root = fixture(tmp_path)
    mutate_json(root.parent / 'report.json', **{field: value})
    with pytest.raises(ValueError):
        contribution.collect_export(root)


def test_complete_cache_metrics_do_not_claim_original_discovery_cost(tmp_path):
    root = fixture(tmp_path)
    mutate_json(root.parent / 'report.json', processed=0, skipped_candidates=123456, complete_cache_reused=True)
    result = contribution.collect_export(root)
    assert result['stats']['processed'] == 0 and result['stats']['cache_reused'] is True
    assert result['stats']['skipped_candidates'] == 123456


@pytest.mark.parametrize('missing', ['work.sqlite', 'configuration.json', 'report.json'])
def test_incomplete_run_is_rejected(tmp_path, missing):
    root = fixture(tmp_path)
    (root.parent / missing).unlink()
    with pytest.raises(ValueError):
        contribution.collect_export(root)


@pytest.mark.parametrize('change', ['catalog', 'game', 'profile', 'low60', 'kind', 'material'])
def test_run_meta_and_manifest_must_agree(tmp_path, change):
    root = fixture(tmp_path)
    if change == 'catalog': mutate_json(root / 'manifest.json', catalog_sha256='b' * 64)
    if change == 'game': mutate_json(root.parent / 'configuration.json', game='BO7')
    if change == 'profile': mutate_json(root.parent / 'configuration.json', profile='fnv1a64')
    if change == 'low60': mutate_json(root.parent / 'configuration.json', low60=True)
    if change == 'kind': mutate_json(root / 'manifest.json', types=['image'])
    if change == 'material': mutate_json(root / 'manifest.json', exclude_material=True)
    with pytest.raises(ValueError):
        contribution.collect_export(root)


def test_manifest_cannot_read_paths_outside_allowlist(tmp_path):
    root = fixture(tmp_path)
    manifest = json.loads((root / 'manifest.json').read_text())
    manifest['files']['../work.sqlite'] = 'a' * 64
    (root / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='文件路径'):
        contribution.collect_export(root)


def test_compressed_cdb_cannot_expand_above_file_limit(tmp_path):
    root = fixture(tmp_path)
    path = root / 'verified.cdb'
    blob = bytearray(path.read_bytes())
    struct.pack_into('<I', blob, 12, contribution.MAX_FILE_BYTES + 1)
    path.write_bytes(blob)
    rehash(root)
    with pytest.raises(ValueError, match='32MB'):
        contribution.collect_export(root)


def test_whole_file_limit_is_explicit(tmp_path, monkeypatch):
    root = fixture(tmp_path)
    monkeypatch.setattr(contribution, 'MAX_FILE_BYTES', 8)
    with pytest.raises(ValueError, match='32MB'):
        contribution.collect_export(root)


def test_submit_row_limit_rejects_whole_preparation(tmp_path, monkeypatch):
    root = fixture(tmp_path, targets=[('xanim', 'fixture_a'), ('xanim', 'fixture_b')])
    monkeypatch.setattr(contribution, 'MAX_ROWS', 1)
    with pytest.raises(ValueError, match='10000'):
        contribution.collect_export(root)


@pytest.mark.parametrize('name', [' fixture', 'fixture ', 'fixture\tname', 'fixture\x01name', 'fixture\x7fname'])
def test_upstream_trim_and_control_names_are_rejected(tmp_path, name):
    root = fixture(tmp_path, targets=[('xanim', name)])
    with pytest.raises(ValueError, match='名称格式'):
        contribution.collect_export(root)


def test_comma_names_remain_exact_strings(tmp_path):
    root = fixture(tmp_path, targets=[('xanim', 'fixture,name')])
    assert contribution.collect_export(root)['rows'][0]['name'] == 'fixture,name'


def test_uncheckpointed_wal_is_not_ignored(tmp_path):
    root = fixture(tmp_path)
    db = sqlite3.connect(root.parent / 'work.sqlite')
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute("UPDATE meta SET value='changed' WHERE key='catalog_fingerprint'")
        db.commit()
        with pytest.raises(ValueError, match='WAL'):
            contribution.collect_export(root)
    finally:
        db.close()


def test_candidate_nofold_domain_is_skipped_without_overriding_registry(tmp_path):
    root = fixture(tmp_path, game='BO4', profile='fnv1a63-no-fold', targets=[('sndasset', 'Sound\\Exact')])
    result = contribution.collect_export(root)
    assert result['rows'] == [] and result['rejected'] == {'unsupported_domain': 1}


def test_work_database_conflicting_names_are_never_contributed(tmp_path):
    root = fixture(tmp_path)
    row = evidence_rows(root)[0]
    with closing(sqlite3.connect(root.parent / 'work.sqlite')) as db, db:
        fields = list(contribution._FIELDS)
        values = [json.dumps(row[key]) if key == 'details' else row[key] for key in fields]
        values[fields.index('name')] = 'conflicting_resource'
        db.execute('INSERT INTO evidence (' + ','.join(fields) + ') VALUES ('
                   + ','.join('?' for _ in fields) + ')', values)
    with pytest.raises(ValueError, match='名称冲突'):
        contribution.collect_export(root)


def test_duplicate_jsonl_records_are_rejected_even_with_consistent_manifest(tmp_path):
    root = fixture(tmp_path)
    row = evidence_rows(root)[0]
    replace_evidence(root, [row, row])
    with pytest.raises(ValueError, match='重复记录'):
        contribution.collect_export(root)


def test_swapped_classified_cdb_cannot_claim_another_asset_type(tmp_path):
    root = fixture(tmp_path)
    source = root / 'hash_pkg/fnv1a_xanims_v2.cdb'
    target = source.with_name('fnv1a_ximages_v2.cdb')
    source.rename(target)
    manifest = json.loads((root / 'manifest.json').read_text())
    manifest['files']['hash_pkg/' + target.name] = manifest['files'].pop('hash_pkg/' + source.name)
    (root / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='分类 CDB.*类型'):
        contribution.collect_export(root)


def test_readonly_collector_never_invokes_native_compute(tmp_path, monkeypatch):
    root = fixture(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('contribution verification must use independent CPU Profile.digest')
    monkeypatch.setattr('finder.hashing.native', forbidden)
    monkeypatch.setattr('finder.hashing.batch_digest', forbidden)
    assert contribution.collect_export(root)['stats']['accepted_rows'] == 1


def test_invalid_lz4_is_reported_as_validation_error(tmp_path):
    root = fixture(tmp_path)
    path = root / 'verified.cdb'
    blob = path.read_bytes()
    path.write_bytes(blob[:16] + b'\xff' * (len(blob) - 16))
    rehash(root)
    with pytest.raises(ValueError, match='CDB 无效'):
        contribution.collect_export(root)
