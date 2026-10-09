"""End-to-end checks for independent upstream-inspired, target-observed rules."""
import csv
import hashlib
import json
import sqlite3
import struct
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from finder.estimate import estimate
from finder.formats import decode_cdb, encode_cdb
from finder.hashing import PROFILES
from finder.pipeline import Config, _alias_clues, prepare, run
from finder.store import Store


TAIL = '.lnn.75.48000.all'
NEW_GENERATORS = {'sound-observed-v1', 'sound-final-byte-v1', 'typed-observed-v1'}


def _config(root, kind='sndasset', profile='iw-resource63'):
    assets, indexes = root / 'assets', root / 'indexes'
    assets.mkdir(parents=True)
    indexes.mkdir()
    return Config(str(assets), str(indexes), str(root / 'output'), asset_type=kind,
                  profile=profile, backend='cpu', number_max=0, budget=100000, seconds=30,
                  exclude_material=False)


def _index(config, table, names, profile=None):
    source = PROFILES[profile or ('fnv1a64' if 'aliases' in table else 'iw-resource63')]
    path = Path(config.indexes) / (table + '.cdb')
    path.write_bytes(encode_cdb({source.digest(name): name for name in names}))
    return path


def _target(config, name, kind=None, raw=None):
    key = PROFILES[config.profile].digest(name) if raw is None else raw
    if config.low60:
        key &= (1 << 60) - 1
    (Path(config.folder) / f'{kind or config.asset_type}_{key:016x}.bin').write_bytes(b'synthetic')
    return key


def _read_output(result):
    directory = Path(result['path'])
    names = decode_cdb((directory / 'verified.cdb').read_bytes())
    with Path(result['new_names_csv']).open(encoding='utf-8', newline='') as stream:
        assert {int(key, 16): name for key, name in csv.reader(stream)} == names
    evidence = [json.loads(line) for line in (directory / 'evidence.jsonl').read_text(
        encoding='utf-8').splitlines()]
    assert all(PROFILES[row['profile']].digest(row['name']) == int(row['hash'], 16) for row in evidence)
    return names, evidence


def _assert_method(result, name, generator, rule, method_id):
    names, evidence = _read_output(result)
    assert name in names.values()
    assert any(stage['generator'] == generator and stage['rule'] == rule for stage in result['stages'])
    hit = next(row for row in evidence if row['name'] == name)
    assert hit['method'] == 'discovered' and hit['method_id'] == method_id
    assert hit['details']['candidate_generation']['generator'] == generator
    assert hit['details']['candidate_generation']['rule'] == rule
    return names, evidence


def _sound_namespace(root):
    config = _config(root)
    anchor = 'fixture/ar_new/wpn_ar_new_fire_02' + TAIL
    donors = ['fixture/ar_old/wpn_ar_old_reload_01' + TAIL,
              'fixture/ar_old/wpn_ar_old_inspect_01' + TAIL]
    desired = 'fixture/ar_new/wpn_ar_new_reload_01' + TAIL
    known = 'fixture/ar_new/wpn_ar_new_inspect_01' + TAIL
    _index(config, 'fnv1a_xsounds_v2', [anchor, *donors])
    for name in (anchor, desired, known):
        _target(config, name)
    # An unresolved display string must still exclude its already-held stored key.
    (Path(config.indexes) / 'old_resolved.cdb').write_bytes(encode_cdb({
        PROFILES[config.profile].digest(known): 'unrestorable_fixture_display'}))
    return config, anchor, donors, desired, known


def test_namespace_rule_export_exclusion_and_completed_cache_restore(tmp_path):
    config, anchor, donors, desired, known = _sound_namespace(tmp_path)
    assert desired not in [anchor, *donors, known]
    before = {path: path.read_bytes() for path in Path(config.indexes).glob('*.cdb')}
    first = run(config)
    names, _ = _assert_method(first, desired, 'sound-observed-v1', 'repeated-namespace',
                              'soundplans.repeated_namespace')
    assert names == {PROFILES[config.profile].digest(desired): desired}
    assert known not in names.values() and first['excluded_existing'] == 2
    assert first['saluki_exclusion_counts']['by_key'] == 2
    assert first['complete_cache_saved'] is True
    second = run(config)
    assert second['complete_cache_reused'] is True and second['processed'] == 0
    assert _read_output(second)[0] == names and second['excluded_existing'] == 2
    assert before == {path: path.read_bytes() for path in before}


def test_final_basename_byte_is_discovered_by_its_own_verified_stage(tmp_path):
    config = _config(tmp_path)
    donor = 'fixture/audio/fire_a' + TAIL
    anchor = 'fixture/audio/reload_01' + TAIL
    desired = 'fixture/audio/fire_b' + TAIL
    _index(config, 'fnv1a_xsounds_v2', [donor, anchor])
    for name in (anchor, desired):
        _target(config, name)
    assert desired not in (donor, anchor)
    result = run(config)
    _assert_method(result, desired, 'sound-final-byte-v1', 'final-basename-byte',
                   'soundbyte.final_basename_byte')
    assert result['cross_asset']['observed']['final_byte']['candidates'] >= 1


@pytest.mark.parametrize('kind,table,anchor,desired', [
    ('image', 'fnv1a_ximages_v2', 'ui/fixture_ar_alpha2_icon', 'ui/fixture_ar_bravo3_icon'),
    ('material', 'fnv1a_xmaterials_v2', 'mtl/fixture_ar_alpha2_chrome', 'mtl/fixture_ar_bravo3_chrome'),
])
def test_typed_weapon_identity_creates_new_graphics_names(tmp_path, kind, table, anchor, desired):
    config = _config(tmp_path, kind)
    animations = ['sat_vm_ar_alpha2_reload', 'sat_vm_ar_bravo3_reload']
    _index(config, 'fnv1a_xanims_v2', animations)
    _index(config, table, [anchor])
    for name in (anchor, desired):
        _target(config, name)
    assert desired not in [anchor, *animations]
    result = run(config)
    names, evidence = _assert_method(result, desired, 'typed-observed-v1', 'typed-weapon-slot',
                                     'typedplans.typed_weapon_slot')
    assert names == {PROFILES[config.profile].digest(desired): desired}
    assert evidence[0]['details']['candidate_generation']['target_kinds'] == [kind]
    with sqlite3.connect(Path(result['run_dir']) / 'work.sqlite') as db:
        configs = [json.loads(row[0]) for row in db.execute('SELECT config FROM tasks')]
    assert any(row['kinds'] == [kind] and row['details']['candidate_generation']['generator']
               == 'typed-observed-v1' for row in configs)


def test_verified_animation_cores_create_full_width_alias_names(tmp_path):
    config = _config(tmp_path, 'soundbankalias', 'fnv1a64')
    config.hash_domain = 'soundbankalias'
    animations = ['sat_vm_ar_alpha2_reload', 'sat_vm_ar_bravo3_reload']
    anchor, desired = 'npc_ar_alpha2_reload_07_02', 'npc_ar_bravo3_reload_07_02'
    _index(config, 'fnv1a_xanims_v2', animations)
    _index(config, 'fnv1a_soundbanks_aliases_v2', [anchor])
    for name in (anchor, desired):
        _target(config, name)
    assert desired not in [anchor, *animations]
    result = run(config)
    names, _ = _assert_method(result, desired, 'typed-observed-v1', 'animation-core-alias',
                              'typedplans.animation_core_alias')
    package = Path(result['path']) / 'hash_pkg/fnv1a_soundbanks_aliases_v2.cdb'
    assert decode_cdb(package.read_bytes()) == names


def test_missing_alias_file_family_uses_capture_local_alias_clues_and_target_directory(tmp_path):
    config = _config(tmp_path)
    profile = PROFILES['iw-resource63']
    anchor = 'fixture/target/wpn_plr_ar_alpha2_fire_03' + TAIL
    alias = 'wpn_plr_ar_alpha2_reload'
    desired = 'fixture/target/' + alias + '_03' + TAIL
    foreign = 'fixture/foreign/' + alias + '_01.lnn.85.44100.all'
    _index(config, 'fnv1a_xsounds_v2', [anchor, foreign])
    _index(config, 'fnv1a_soundbanks_aliases_v2', [alias])
    # CODIDS aliases have lost bit 63: they are bounded naming clues, never
    # full-width alias evidence. The desired sound still needs its complete key.
    records = sorted([(profile.digest(anchor), 600), (profile.digest(desired), 600),
                      (PROFILES['fnv1a64'].digest(alias) & ((1 << 63) - 1), 601)])
    capture = tmp_path / 'source'
    capture.mkdir()
    path = capture / 'fixture.ids'
    game = b'MODWAR7'
    path.write_bytes(b'CODIDS' + struct.pack('<HH', 1, len(game)) + game + struct.pack('<Q', 3)
                     + b''.join(struct.pack('<QH', *record) for record in records))
    path.with_suffix('.pools.txt').write_text(
        'MODWAR7 -- 3 assets in 2 filled pools\nindex asset type assets\n'
        '600 sound_asset 2\n601 sound_alias 1\n', encoding='utf-8')
    config.input_mode, config.snapshot_file = 'snapshot', str(path)
    assert desired not in (anchor, foreign, alias)
    result = run(config)
    names, evidence = _assert_method(result, desired, 'sound-observed-v1', 'alias-missing-family',
                                     'soundplans.alias_missing_family')
    assert names == {profile.digest(desired): desired}
    assert all(row['profile'] == 'iw-resource63' for row in evidence)
    assert result['input']['pools']['601']['import_status'] == 'type_filtered'


@pytest.mark.parametrize('damage', ['source-key', 'source-profile', 'typed-target', 'target-profile'])
def test_unverified_or_wrong_typed_templates_cannot_create_new_observed_rule(tmp_path, damage):
    config = _config(tmp_path, 'image')
    profile = PROFILES['iw-resource63']
    anchor, desired = 'ui/fixture_ar_alpha2_icon', 'ui/fixture_ar_bravo3_icon'
    _index(config, 'fnv1a_xanims_v2', ['sat_vm_ar_alpha2_reload', 'sat_vm_ar_bravo3_reload'])
    table = 'fnv1a_ximages' if damage == 'source-profile' else 'fnv1a_ximages_v2'
    # The legacy table deliberately carries a key from the modern source domain.
    key = profile.digest(anchor) ^ int(damage == 'source-key')
    (Path(config.indexes) / (table + '.cdb')).write_bytes(encode_cdb({key: anchor}))
    _target(config, desired, 'image')
    if damage == 'typed-target':
        config.asset_type = 'auto'
        _target(config, anchor, 'material')
    elif damage == 'target-profile':
        _target(config, anchor, 'image', raw=PROFILES['fnv1a63'].digest(anchor))
    else:
        _target(config, anchor, 'image')
    with closing(Store(tmp_path / 'prepare.sqlite')) as store:
        state = prepare(config, store)
        assert not any(plan.metadata.get('generator') in NEW_GENERATORS for _, plan in state['plans'])
        assert state['cross_summary']['observed']['target_held_names'].get('image', 0) == 0
        assert store.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0] == 0


@pytest.mark.parametrize('option', ['cross-disabled', 'low60'])
def test_new_observed_rules_are_disabled_when_requested_or_keys_are_truncated(tmp_path, option):
    config, _, _, _, _ = _sound_namespace(tmp_path)
    if option == 'cross-disabled':
        config.cross_asset = False
    else:
        config.low60 = True
        for path in Path(config.folder).glob('*.bin'):
            key = int(path.stem.rsplit('_', 1)[1], 16) & ((1 << 60) - 1)
            path.rename(path.with_name(f'sndasset_{key:016x}.bin'))
    with closing(Store(tmp_path / 'prepare.sqlite')) as store:
        state = prepare(config, store)
        assert not any(plan.metadata.get('generator') in NEW_GENERATORS for _, plan in state['plans'])
        assert 'observed' not in state['cross_summary']
        assert store.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0] == 0


def test_estimate_prepares_new_methods_without_evidence_or_output_mutation(tmp_path, monkeypatch):
    config, _, _, _, _ = _sound_namespace(tmp_path)
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob('*') if path.is_file()}

    def forbidden(*args, **kwargs):
        raise AssertionError('Read-only estimates must not create evidence')

    monkeypatch.setattr(Store, 'add_evidence', forbidden)
    result = estimate(config)
    assert result['status'] == 'estimated' and result['cross_asset']['observed']['plans'] > 0
    assert any(row['method']['method_id'] == 'soundplans.repeated_namespace' for row in result['stages'])
    assert not Path(config.output).exists()
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob('*') if path.is_file()}


def test_estimate_keeps_different_live_target_sets_separate_and_partial_run_can_resume(tmp_path):
    config, _, _, _, _ = _sound_namespace(tmp_path)
    # Three literal names and one byte-solved candidate precede the first
    # correlated namespace plan in this fixture.
    partial = run(replace(config, budget=5))
    assert partial['status'] == 'partial' and not partial['complete_cache_reused']
    assert any(stage['generator'] == 'sound-observed-v1' and stage['processed'] == 1
               for stage in partial['stages'])
    ledger = Path(partial['ledger'])
    before = hashlib.sha256(ledger.read_bytes()).hexdigest()
    result = estimate(config)
    observed = [row for row in result['stages']
                if row['method']['method_id'] == 'soundplans.repeated_namespace']
    # Execution's literal stage resolved the anchor before the observed stage.
    # A fresh estimate has not replayed those hits, so its wider target set
    # must not share that stage's fingerprint merely because the rule matches.
    assert observed and sum(row['cached'] for row in observed) == 0
    assert hashlib.sha256(ledger.read_bytes()).hexdigest() == before
    resumed = run(config)
    assert not resumed['complete_cache_reused']
    assert any(stage['generator'] == 'sound-observed-v1' and stage['skipped'] == 1
               and stage['cached_hits'] >= 1 for stage in resumed['stages'])
    assert _read_output(resumed)[0] == {
        PROFILES[config.profile].digest('fixture/ar_new/wpn_ar_new_reload_01' + TAIL):
        'fixture/ar_new/wpn_ar_new_reload_01' + TAIL}


def test_recovered_sound_index_spelling_reaches_literal_and_stored_key_remains_excluded(tmp_path):
    config = _config(tmp_path)
    original = 'nf_fixture/dir.with.dots/audio_clip.lnn.75.48000.all'
    display = 'nf_fixture/dir.with.dots/audio_clip/lnn/75/48000/all'
    key = 0x01174ff141e57b27
    (Path(config.indexes) / 'fnv1a_xsounds_v2.cdb').write_bytes(encode_cdb({key: display}))
    _target(config, original)
    result = run(config)
    assert result['entries'] == 0 and result['excluded_existing'] == 1
    assert result['saluki_exclusion_counts']['by_key'] == 1
    assert _read_output(result)[0] == {}
    with sqlite3.connect(Path(result['run_dir']) / 'work.sqlite') as db:
        rows = list(db.execute('SELECT name,method_id FROM evidence'))
    assert (original, 'autoplans.literal') in rows


@pytest.mark.parametrize('game', ['BO4', 'BOCW'])
def test_legacy_declared_alias_pool_without_formal_profile_can_supply_only_clues(tmp_path, game):
    name = 'nf_fixture_alias_10'
    full = 0xc0d698f2c26e502c
    raw = full & ((1 << 63) - 1)
    with closing(Store(tmp_path / 'aliases.sqlite')) as store:
        with store.db:
            store.setmeta('build', game)
            # Models an imported, known legacy alias pool whose separate name
            # domain has not been enabled as a formal calculation target.
            store.db.execute('INSERT INTO snapshot_records VALUES (?,?,?,?,?,?,?)',
                             (221, f'{raw:016x}', 'soundbankalias', '', 63,
                              '7fffffffffffffff', 'unknown_domain'))
        assert _alias_clues(store, {name, 'nf_fixture_wrong_alias'}, lambda: 'run') == {name}
        assert raw != full and store.db.execute('SELECT raw_hash FROM snapshot_records').fetchone()[0] == f'{raw:016x}'
        assert store.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0] == 0
        assert store.db.execute('SELECT COUNT(*) FROM calibration').fetchone()[0] == 0
        assert store.db.execute('SELECT COUNT(*) FROM assets').fetchone()[0] == 0


@pytest.mark.parametrize('game', ['COD2026', 'BO7', 'unrecognised'])
def test_empty_alias_profile_is_not_inferred_for_other_games(tmp_path, game):
    name = 'nf_fixture_alias_10'
    with closing(Store(tmp_path / 'aliases.sqlite')) as store:
        with store.db:
            store.setmeta('build', game)
            store.db.execute('INSERT INTO snapshot_records VALUES (?,?,?,?,?,?,?)',
                             (221, '40d698f2c26e502c', 'soundbankalias', '', 63,
                              '7fffffffffffffff', 'unknown_domain'))
        assert _alias_clues(store, {name}, lambda: 'run') == set()
        assert store.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0] == 0
