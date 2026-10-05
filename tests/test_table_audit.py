import csv
import json
from pathlib import Path
import pytest
from finder.hashing import PROFILES
from finder.community import import_community, iter_community, sync_community
from finder.tableaudit import audit_tables


def write(path, rows):
    with path.open('w', encoding='utf-8', newline='') as stream:
        csv.writer(stream).writerows(rows)


def test_verified_quarantine_borrowed_are_isolated(tmp_path):
    p = PROFILES['iw-resource63']
    good = 'rex_vm_ar_mike4_fire'
    wrong = 'iw9/amb/rex_emitters_reconstructed_name'
    write(tmp_path / 'fnv1a_xanims_v2.csv', [(f'{p.digest(good):x}', good), ('1234', wrong), ('xyz', 'invalid_key')])
    write(tmp_path / 'unregistered.csv', [(f'{p.digest(good):x}', good)])
    rows = list(iter_community(tmp_path))
    assert [r.status for r in rows] == ['verified', 'quarantined', 'quarantined', 'quarantined']
    assert rows[0].profile == 'iw-resource63'
    assert all(r.profile is None for r in rows[1:])
    borrowed = list(iter_community(tmp_path, borrowed=True))
    assert borrowed[0].status == 'borrowed' and borrowed[0].profile is None
    assert borrowed[2].status == 'quarantined'
    result = import_community(tmp_path, output_dir=tmp_path / 'imported')
    assert result['counts'] == dict(verified=1, quarantined=3, borrowed=0)
    assert json.loads(Path(result['files']['verified']).read_text())['name'] == good


def test_table_audit_masks_family_rates_and_reconstructed_names(tmp_path):
    iw = PROFILES['iw-resource63']
    trey = PROFILES['fnv1a64']
    sixty = PROFILES['fnv1a60']
    write(tmp_path / 'fnv1a_xsounds_v2.csv', [(f'{iw.digest("rex/weapons/fire.all"):x}', 'rex/weapons/fire.all'),
                                             ('ffff', 'iw9/amb/rex_emitters.all')])
    name = 'wfoly_rex_plr_ar_kilo2_inspect'
    write(tmp_path / 'fnv1a_soundbanks_aliases_v2.csv', [(f'{trey.digest(name):x}', name)])
    write(tmp_path / 'fnv1a_strings.csv', [(f'{sixty.digest("notify_weapon_fire"):x}', 'notify_weapon_fire')])
    result = audit_tables(tmp_path, ['iw-resource63', 'fnv1a64', 'fnv1a60'])
    tables = {t['table']: t for t in result['tables']}
    sounds = tables['fnv1a_xsounds_v2']
    assert sounds['profiles']['iw-resource63']['rate'] == 0.5
    assert sounds['groups']['path:rex']['profiles']['iw-resource63']['rate'] == 1
    assert sounds['groups']['path:iw9']['profiles']['iw-resource63']['rate'] == 0
    assert tables['fnv1a_soundbanks_aliases_v2']['profiles']['fnv1a64']['width'] == 64
    assert tables['fnv1a_strings']['profiles']['fnv1a60']['width'] == 60
    assert len(list(iter_community(tmp_path, selected_profile='fnv1a60'))) == 1
    assert audit_tables(tmp_path, ['iw-resource63'], name_filter='rex', sample_limit=1)['complete'] is False


def test_disabled_sync_does_not_access_network_or_files(monkeypatch, tmp_path):
    def forbidden(*args):
        raise AssertionError('Network must stay disabled')
    monkeypatch.setattr('finder.community._json_url', forbidden)
    result = sync_community(tmp_path / 'nonexistent', enabled=False)
    assert result['enabled'] is False and result['csv_dir'] is None
    assert not (tmp_path / 'nonexistent').exists()


def test_cache_commit_paths_and_hashes_are_checked_without_network(tmp_path):
    commit = 'a' * 40
    folder = tmp_path / 'snapshots' / commit / 'csv'
    folder.mkdir(parents=True)
    (folder / 'fnv1a_strings.csv').write_text('bad-cache', encoding='utf-8')
    metadata = dict(commit=commit, files=[dict(name='fnv1a_strings.csv', sha256='0' * 64)])
    (tmp_path / 'current.json').write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match='cache changed'):
        sync_community(tmp_path, enabled=True)
    metadata['files'][0]['name'] = '../escape.csv'
    (tmp_path / 'current.json').write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match='path'):
        sync_community(tmp_path, enabled=True)


def test_synthetic_reference_tables_remain_verified_on_import(tmp_path):
    # Table names exercise real routing; all contained asset names are original placeholders.
    fixture = json.loads((Path(__file__).parent / 'fixtures/community-table-vectors.json').read_text(encoding='utf-8'))
    assert fixture['synthetic'] is True
    for table in fixture['tables']:
        write(tmp_path / (table['table'] + '.csv'), [(r['hash'], r['name']) for r in table['rows']])
    rows = list(iter_community(tmp_path))
    assert rows and all(r.status == 'verified' for r in rows)
    report = audit_tables(tmp_path)
    for table in report['tables']:
        assert table['profiles'][table['expected']['profile']]['rate'] == 1

