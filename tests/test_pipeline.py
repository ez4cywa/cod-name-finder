import json
from pathlib import Path
import pytest
from finder.pipeline import Config,run
from finder.hashing import PROFILES
from finder.formats import encode_cdb,decode_cdb
from finder.backends import devices

@pytest.mark.parametrize('backend',['cpu','gpu'])
def test_one_click_standalone_anim_import_search_name_exclusion_export(tmp_path,backend):
    if backend=='gpu' and not any('name' in d for d in devices()):pytest.skip('No GPU')
    p=PROFILES['iw-resource63'];known='existing_animation';wanted=['rex_mp_strafe_walk_1','rex_vm_misc_laser_pointer_fire']
    folder=tmp_path/'哈希动画';folder.mkdir();indexes=tmp_path/'索引';indexes.mkdir()
    for name in [known,*wanted]:(folder/f'anim_{p.digest(name):x}.cast').write_bytes(b'fixture')
    (folder/'model_123456789abcdef0.fbx').write_bytes(b'fixture')
    (folder/'sound_123456789abcdef1.wav').write_bytes(b'fixture')
    names=[known,'jup_mp_strafe_walk_1','vm_misc_laser_pointer_fire']
    old=PROFILES['fnv1a63'];(indexes/'fnv1a_xanims.cdb').write_bytes(encode_cdb({old.digest(n):n for n in names}))
    result=run(Config(str(folder),str(indexes),str(tmp_path/'输出'),backend=backend))
    assert result['status']=='completed' and result['entries']==2 and result['verified_target_matches']==3
    assert result['excluded_existing']==1 and result['saluki_exclusion_counts']['name_only']==1
    assert result['input']['models_excluded']==1 and result['input']['types_filtered']==1
    output=Path(result['path']);assert decode_cdb((output/'verified.cdb').read_bytes())=={p.digest(n):n for n in wanted}
    assert Path(result['new_names_csv']).read_bytes()==(output/'verified.csv').read_bytes()
    assert decode_cdb((output/'hash_pkg/fnv1a_xanims_v2.cdb').read_bytes())=={p.digest(n):n for n in wanted}
    assert (folder/'model_123456789abcdef0.fbx').exists()
    assert json.loads((Path(result['run_dir'])/'report.json').read_text(encoding='utf-8'))['entries']==2

def test_one_click_empty_budget_and_low60_never_certified(tmp_path):
    p=PROFILES['iw-resource63'];name='rex_mp_strafe_walk_1';folder=tmp_path/'assets';folder.mkdir();indexes=tmp_path/'indexes';indexes.mkdir()
    (folder/f'anim_{p.digest(name)&((1<<60)-1):x}.cast').write_bytes(b'fixture')
    (indexes/'fnv1a_xanims.cdb').write_bytes(encode_cdb({1:'jup_mp_strafe_walk_1'}))
    result=run(Config(str(folder),str(indexes),str(tmp_path/'out'),low60=True,backend='cpu'))
    assert result['entries']==0 and not result['full_keys']
    assert decode_cdb((Path(result['path'])/'verified.cdb').read_bytes())=={}
    limited=run(Config(str(folder),str(indexes),str(tmp_path/'limited'),budget=1,backend='cpu'))
    assert limited['status']=='partial' and limited['processed']==1
    with pytest.raises(ValueError,match='输出目录'):Config(str(folder),str(indexes),str(folder/'out')).validate()
