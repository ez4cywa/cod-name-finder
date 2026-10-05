import csv
import hashlib
import json
from pathlib import Path

import pytest

from finder.backends import devices
from finder.formats import decode_cdb, encode_cdb
from finder.hashing import PROFILES
from finder.pipeline import Config, related_file_names, run


def cross_fixture(tmp_path):
    profile=PROFILES['iw-resource63']
    old=PROFILES['fnv1a63']
    folder=tmp_path/'哈希目标';folder.mkdir()
    indexes=tmp_path/'名称索引';indexes.mkdir()
    related=tmp_path/'已命名模型';related.mkdir()
    known='iw9_vm_ar_mike4_reload_empty'
    animation='iw9_vm_ar_alpha57_reload_empty'
    pistol='iw9_vm_pi_kilo5_reload_empty'
    sound=r'core\weapons\ar_alpha57\wfoly_plr_ar_alpha57_reload_01.lnn.85.48000.all'
    sound_template=r'core\weapons\ar_mike4\wfoly_plr_ar_mike4_reload_01.lnn.85.48000.all'
    for name in (known,animation,pistol):
        (folder/f'anim_{profile.digest(name):016x}.cast').write_bytes(b'animation fixture')
    (folder/f'sound_{profile.digest(sound):016x}.wav').write_bytes(b'sound fixture')
    (indexes/'fnv1a_xanims_v2.cdb').write_bytes(encode_cdb({old.digest(n):n for n in (known,'iw9_vm_pi_papa320_reload_empty')}))
    (indexes/'fnv1a_xsounds_v2.cdb').write_bytes(encode_cdb({old.digest(sound_template):sound_template}))
    (indexes/'fnv1a_xmodels.cdb').write_bytes(encode_cdb({123:'wpn_iw9_ar_alpha57_view'}))
    (related/'wpn_iw9_pi_kilo5_view.bin').write_bytes(b'names only')
    (related/'model_123456789abcdef0.fbx').write_bytes(b'no name clue')
    expected={profile.digest(n):profile.normalize(n) for n in (animation,pistol,sound)}
    return folder,indexes,related,known,expected


@pytest.mark.parametrize('backend',['cpu','gpu'])
def test_cross_asset_pipeline_verified_incremental_exports(tmp_path,backend):
    if backend=='gpu' and not any('name' in d for d in devices()):pytest.skip('No GPU')
    folder,indexes,related,known,expected=cross_fixture(tmp_path)
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for root in (folder,indexes,related) for p in root.rglob('*') if p.is_file()}
    result=run(Config(str(folder),str(indexes),str(tmp_path/'result'),asset_type='auto',related_folder=str(related),backend=backend))
    assert result['status']=='completed' and result['entries']==3
    assert result['verified_target_matches']==4 and result['excluded_existing']==1
    assert result['cross_asset']['enabled'] and result['cross_asset']['plans']>0
    assert result['cross_asset']['related_files']==2
    assert any(stage['generator']=='cross-asset-v1' for stage in result['stages'])
    output=Path(result['path'])
    assert decode_cdb((output/'verified.cdb').read_bytes())==expected
    with Path(result['new_names_csv']).open(encoding='utf-8',newline='') as stream:
        assert {int(key,16):name for key,name in csv.reader(stream)}==expected
    assert known not in expected.values()
    evidence=[json.loads(line) for line in (output/'evidence.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(evidence)==3 and all(row['method']=='discovered' for row in evidence)
    for filename in ('fnv1a_xanims_v2.cdb','fnv1a_xsounds_v2.cdb'):
        old=decode_cdb((indexes/filename).read_bytes())
        incoming=decode_cdb((output/'hash_pkg'/filename).read_bytes())
        merged=decode_cdb((Path(result['saluki_ready'])/'hash_pkg'/filename).read_bytes())
        assert merged=={**old,**incoming}
    assert before=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for root in (folder,indexes,related) for p in root.rglob('*') if p.is_file()}


def test_cross_asset_switch_off_and_keyword_after_match(tmp_path):
    folder,indexes,related,known,expected=cross_fixture(tmp_path)
    disabled=run(Config(str(folder),str(indexes),str(tmp_path/'off'),asset_type='auto',related_folder=str(related),cross_asset=False,backend='cpu'))
    assert disabled['entries']==0 and disabled['verified_target_matches']==1
    assert disabled['excluded_existing']==1 and not disabled['cross_asset']['enabled']
    filtered=run(Config(str(folder),str(indexes),str(tmp_path/'keyword'),asset_type='auto',related_folder=str(related),keyword='alpha57',backend='cpu'))
    assert filtered['verified_target_matches']==2 and filtered['entries']==2
    assert decode_cdb((Path(filtered['path'])/'verified.cdb').read_bytes())=={h:n for h,n in expected.items() if 'alpha57' in n}


def test_cross_asset_folder_validation_and_hash_placeholders(tmp_path):
    folder,indexes,related,_,_=cross_fixture(tmp_path)
    with pytest.raises(ValueError,match='其他已命名资产文件夹不存在'):
        Config(str(folder),str(indexes),str(tmp_path/'out'),related_folder=str(tmp_path/'missing')).validate()
    with pytest.raises(ValueError,match='输出目录'):
        Config(str(folder),str(indexes),str(related/'out'),related_folder=str(related)).validate()
    Config(str(folder),str(indexes),str(tmp_path/'out'),cross_asset=False,related_folder=str(tmp_path/'missing')).validate()
    names,files,complete=related_file_names(related)
    assert complete and files==2 and 'wpn_iw9_pi_kilo5_view' in names
    assert not any('123456789abcdef0' in name for name in names)
    assert related_file_names(related,lambda:'pause')==(set(),0,False)
    (related/'fe_gunsmith_weapon_placement_mike4.cast').write_bytes(b'filename only')
    names,_,_=related_file_names(related)
    assert 'fe_gunsmith_weapon_placement_mike4' in names
