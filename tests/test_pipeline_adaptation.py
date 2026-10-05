import csv
import sqlite3
from dataclasses import asdict
from pathlib import Path

import pytest

from finder.formats import encode_cdb,decode_cdb
from finder.hashing import PROFILES
from finder.pipeline import Config,run,prepare
from finder.store import Store


def fixture(tmp_path,profile_id='iw-resource63',kind='xanim',names=('rex_vm_ar_mike4_reload',)):
    p=PROFILES[profile_id];assets=tmp_path/'assets';assets.mkdir();indexes=tmp_path/'indexes';indexes.mkdir()
    for n in names:(assets/f'{kind}_{p.digest(n):016x}.bin').write_bytes(b'not media')
    (indexes/'names.cdb').write_bytes(encode_cdb({1:'unrelated_previous_name'}))
    return Config(str(assets),str(indexes),str(tmp_path/'results'),profile=profile_id,asset_type=kind,backend='cpu',cross_asset=False),p


def test_pipeline_repeated_search_restores_output_without_rescanning(tmp_path):
    config,p=fixture(tmp_path)
    dictionary=tmp_path/'names.txt';dictionary.write_text('jup_vm_ar_mike4_reload\n',encoding='utf-8');config.dictionary=str(dictionary)
    first=run(config);second=run(config)
    assert first['entries']==second['entries']==1
    assert first['processed']>0 and second['processed']==0
    assert second['cached_hits']>=1 and second['skipped_candidates']>0
    assert decode_cdb((Path(first['path'])/'verified.cdb').read_bytes())==decode_cdb((Path(second['path'])/'verified.cdb').read_bytes())
    # New targets refresh the content-addressed snapshot and cannot be skipped.
    (Path(config.folder)/f'xanim_{p.digest("rex_vm_ar_mike4_fire"):016x}.bin').write_bytes(b'new patch')
    third=run(config);assert third['processed']>0
    assert third['input']['unique_assets']==2


def test_borrowed_names_stay_out_of_observed_templates_and_calibration(tmp_path):
    config,p=fixture(tmp_path);borrowed=tmp_path/'borrowed.csv'
    borrowed.write_text(f'{p.digest("jup_vm_ar_mike4_reload"):016x},jup_vm_ar_mike4_reload\n',encoding='utf-8')
    config.borrowed_dictionary=str(borrowed)
    with_store=Store(tmp_path/'prepare.sqlite')
    try:
        state=prepare(config,with_store)
        assert 'jup_vm_ar_mike4_reload' not in state['names']
        assert any(plan.metadata.get('borrowed') for _,plan in state['plans'])
        assert not with_store.db.execute('SELECT * FROM evidence').fetchall()
        assert all(row[2]==0 for row in with_store.db.execute('SELECT * FROM calibration'))
    finally:with_store.close()
    result=run(config);assert result['entries']==1
    with sqlite3.connect(Path(result['run_dir'])/'work.sqlite') as db:
        assert {row[0] for row in db.execute('SELECT name FROM words')}=={'rex_vm_ar_mike4_reload'}


def test_cod2026_unknown_domain_requires_real_same_kind_samples(tmp_path):
    names=tuple(f'rex_unknown_script_symbol_{i}' for i in range(3))
    config,p=fixture(tmp_path,'bo6-script64','scriptfield',names)
    config.hash_domain='script'
    with pytest.raises(ValueError,match='尚未证实'):config.validate()
    config.allow_unverified_domain=True
    with pytest.raises(ValueError,match='至少3'):run(config)
    samples=tmp_path/'samples.csv'
    samples.write_text(''.join(f'{p.digest(n):016x},{n}\n' for n in names),encoding='utf-8');config.dictionary=str(samples)
    result=run(config)
    assert result['entries']==result['verified_target_matches']==3
    assert result['domain_evidence']['status']=='unknown'
    with (Path(result['path'])/'evidence.jsonl').open(encoding='utf-8') as stream:assert len(stream.readlines())>=3
    # Animation file samples cannot unlock a script-symbol domain.
    config.asset_type='auto'
    for path in Path(config.folder).glob('scriptfield_*'):path.rename(path.with_name(path.name.replace('scriptfield_','anim_')))
    with pytest.raises(ValueError,match='对应类型'):run(config)


def test_full64_alias_uses_modern_saluki_alias_package(tmp_path):
    config,p=fixture(tmp_path,'fnv1a64','soundbankalias',('rex_weapon_alias_a',))
    config.hash_domain='soundbankalias';config.dictionary=str(tmp_path/'alias.txt')
    Path(config.dictionary).write_text('rex_weapon_alias_a\n',encoding='utf-8')
    result=run(config);package=Path(result['path'])/'hash_pkg/fnv1a_soundbanks_aliases_v2.cdb'
    assert decode_cdb(package.read_bytes())=={p.digest('rex_weapon_alias_a'):'rex_weapon_alias_a'}


def test_verified_string60_domain_selects_string_corpus_and_stays_full_stored_key(tmp_path):
    config,p=fixture(tmp_path,'fnv1a60','bone',('rex_bone_entry',))
    config.game='BOCW';config.hash_domain='bone'
    (Path(config.indexes)/'fnv1a_strings.cdb').write_bytes(encode_cdb({p.digest('jup_bone_entry'):'jup_bone_entry'}))
    (Path(config.indexes)/'fnv1a_bones_v2.cdb').write_bytes(encode_cdb({2:'irrelevant_bone64_template'}))
    result=run(config);assert result['corpus_names']==1 and result['entries']==1 and result['full_keys'] is True
    assert result['pending_low60_candidates']==0
    assert decode_cdb((Path(result['path'])/'hash_pkg/fnv1a_strings.cdb').read_bytes())=={p.digest('rex_bone_entry'):'rex_bone_entry'}
