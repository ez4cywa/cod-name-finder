"""Independent synthetic CODIDS fixtures for capture-local modern pool maps."""
from collections import Counter
from contextlib import closing
import shutil
import struct

import pytest

from finder.hashing import PROFILES
from finder.snapshot import MASK63, normalize_game, read_snapshot
from finder.store import Store


def capture(root, game, records, labels, *, sidecar=True):
    root.mkdir(parents=True, exist_ok=True)
    # Deliberately unrelated filename: the binary tag determines game policy.
    path = root / 'anonymous.ids'
    encoded = game.encode('utf-8')
    path.write_bytes(b'CODIDS' + struct.pack('<HH', 1, len(encoded)) + encoded +
                     struct.pack('<Q', len(records)) +
                     b''.join(struct.pack('<QH', *row) for row in sorted(records)))
    if sidecar:
        counts = Counter(pool for _, pool in records)
        rows = [f'{game} -- {len(records)} assets in {sum(bool(counts[p]) for p in labels)} filled pools',
                'index  asset type  assets']
        rows.extend(f'{pool}  {label}  {counts[pool]}' for pool, label in labels.items())
        path.with_suffix('.pools.txt').write_text('\n'.join(rows) + '\n', encoding='utf-8')
    return path


@pytest.mark.parametrize('tag,game', [
    ('MODWAR22', 'MWII'), ('YAMYAMOK', 'MWIII'), ('BLACKOP6', 'BO6'),
    ('BLACKOP7', 'BO7'), ('MODWAR7', 'COD2026'),
])
def test_modern_binary_game_tag_selects_iw_domain_with_capture_local_remapped_pool(tmp_path, tag, game):
    name = 'nf_fixture_vm_ar_alpha2_reload'
    raw = PROFILES['iw-resource63'].digest(name)
    # This appended canonical pool index is unrelated to every live adapter.
    path = capture(tmp_path / 'capture', tag, [(raw, 601)], {601: 'xanim'})
    snapshot = read_snapshot(path)
    assert normalize_game(tag.lower()) == game
    assert snapshot['game'] == game and snapshot['game_id'] == tag
    assert snapshot['pools'][601]['kind'] == 'xanim'
    assert snapshot['pools'][601]['profile'] == 'iw-resource63'
    assert snapshot['key_width'] == snapshot['pools'][601]['key_width'] == 63
    with closing(Store(tmp_path / 'work.sqlite')) as store:
        report = store.import_snapshot(path, game, 'iw-resource63', kinds=('xanim',))
        assert report['hashed_files'] == 1
        assert store.targets()[0]['hash'] == f'{raw:016x}'
        assert report['pools']['601']['import_status'] == 'included'


def test_modern_capture_map_controls_type_instead_of_live_or_legacy_pool_number(tmp_path):
    path = capture(tmp_path / 'capture', 'MODWAR7', [(1, 6), (2, 614), (2, 615)],
                   {6: 'image', 614: 'xanim', 615: 'sndasset'})
    snapshot = read_snapshot(path)
    assert snapshot['pools'][6]['kind'] == 'image'  # Live MODWAR7 pool 6 is xanim.
    assert snapshot['pools'][614]['kind'] == 'xanim'
    assert snapshot['pools'][615]['kind'] == 'sndasset'
    assert snapshot['records'] == [(1, 6), (2, 614), (2, 615)]
    moved = tmp_path / 'moved'
    moved.mkdir()
    for file in path.parent.iterdir():
        shutil.copy2(file, moved / file.name)
    assert read_snapshot(moved / path.name)['fingerprint'] == snapshot['fingerprint']


def test_modern_missing_capture_map_is_rejected_even_when_live_adapter_exists(tmp_path):
    path = capture(tmp_path / 'capture', 'MODWAR7', [(1, 6)], {}, sidecar=False)
    with pytest.raises(ValueError, match=r'\.pools\.txt'):
        read_snapshot(path)


@pytest.mark.parametrize('sidecar', [
    'pool,type,count\n601,xanim,2\n',
    'pool,type,count\n601,xanim,1\n602,image,1\n',
    'pool,type,count\n602,xanim,1\n',
    'pool,type,count\n601,xanim,1\n601,image,0\n',
    'pool,type,count\n601,xanim,1\n602,xanim,0\n',
    'pool,type,count\n601,sndasset,1\n602,sound_asset,0\n',
    'BLACKOP7 -- 1 assets in 1 filled pools\n601 xanim 1\n',
    'MODWAR7 -- 1 assets in 2 filled pools\n601 xanim 1\n',
])
def test_modern_counts_game_and_duplicate_mappings_must_agree(tmp_path, sidecar):
    path = capture(tmp_path / 'capture', 'MODWAR7', [(1, 601)], {601: 'xanim'})
    path.with_suffix('.pools.txt').write_text(sidecar, encoding='utf-8')
    with pytest.raises(ValueError, match='池清单'):
        read_snapshot(path)


def test_modern_unknown_models_nested_symbols_and_lost_alias_bits_never_become_targets(tmp_path):
    labels = {601: 'xanim', 602: 'xmodel', 603: 'material', 604: 'bone',
              605: 'scriptfield', 606: 'dvar', 607: 'omnvar',
              608: 'sound_alias', 609: 'xanimsetalias', 610: 'future_asset'}
    records = [(index, pool) for index, pool in enumerate(labels, 1)]
    path = capture(tmp_path / 'capture', 'MODWAR7', records, labels)
    snapshot = read_snapshot(path)
    assert snapshot['pools'][608]['kind'] == 'soundbankalias'
    assert snapshot['pools'][608]['profile'] == 'fnv1a64'
    assert snapshot['pools'][608]['key_width'] == 63
    assert snapshot['pools'][608]['stored_mask'] == f'{MASK63:016x}'
    assert any('原始64位' in warning for warning in snapshot['warnings'])
    for pool in (604, 605, 606, 607, 609, 610):
        assert snapshot['pools'][pool]['kind'] is None
        assert snapshot['pools'][pool]['profile'] is None
    with closing(Store(tmp_path / 'ordinary.sqlite')) as store:
        report = store.import_snapshot(path, 'COD2026', 'iw-resource63')
        assert report['hashed_files'] == 1
        assert report['models_excluded'] == report['materials_excluded'] == 1
        assert report['pools']['608']['import_status'] == 'profile_mismatch'
        assert report['skipped_counts']['unknown_pool'] == 6
        assert {row['kind'] for row in store.targets()} == {'xanim'}
    with closing(Store(tmp_path / 'alias.sqlite')) as store:
        with pytest.raises(ValueError, match='domain_lost_bits'):
            store.import_snapshot(path, 'COD2026', 'fnv1a64', kinds=('soundbankalias',))
        assert store.db.execute('SELECT COUNT(*) FROM assets').fetchone()[0] == 0


def test_modern_alias_high_bit_cannot_be_recovered_from_codids(tmp_path):
    profile = PROFILES['fnv1a64']
    name = next(f'nf_fixture_alias_{i}' for i in range(100) if profile.digest(f'nf_fixture_alias_{i}') > MASK63)
    path = capture(tmp_path / 'capture', 'BLACKOP6', [(profile.digest(name) & MASK63, 610)], {610: 'sound_alias'})
    snapshot = read_snapshot(path)
    assert snapshot['records'][0][0] != profile.digest(name)
    with closing(Store(tmp_path / 'work.sqlite')) as store:
        with pytest.raises(ValueError, match='domain_lost_bits'):
            store.import_snapshot(path, 'BO6', profile.id)


def test_modern_labels_cannot_enable_a_profile_without_game_domain_evidence(tmp_path, monkeypatch):
    path = capture(tmp_path / 'capture', 'MODWAR7', [(1, 601)], {601: 'scriptfile'})
    monkeypatch.setattr('finder.snapshot._evidence_profile', lambda *args: False)
    snapshot = read_snapshot(path)
    assert snapshot['pools'][601]['kind'] == 'scriptfile'
    assert snapshot['pools'][601]['profile'] is None
    assert any('没有对应作品已证名称域' in warning for warning in snapshot['warnings'])
