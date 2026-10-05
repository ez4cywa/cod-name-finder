import json
from pathlib import Path
import pytest
from finder.weapon import weapon_plan
from finder.hashing import PROFILES
from finder.backends import devices
from finder.engine import create_task,run_task
from finder.store import Store
from finder.formats import encode_cdb,decode_cdb
from finder.exporter import export

def names(plan):return {plan.at(i) for i in range(plan.total)}

def test_same_weapon_templates_numeric_actions_and_internal_suffix():
    corpus=['rex_stock_sierra4','rex_attachments/rex_bar_sierra4','rex_stock_mike40']
    plan=weapon_plan(['rex_ar_mike4_mp','weapons/mike4/fire_01.qnn.85.48000.all'],corpus,'mike4',{'number_max':2})
    found=names(plan)
    assert {'rex_ar_mike4_sp','rex_stock_mike4','rex_attachments/rex_bar_mike4',
        'weapons/mike4/reload_02.qnn.85.48000.all'}<=found
    assert all('mike4' in n and 'mike40' not in n for n in found)
    assert not any('mike0' in n or 'mike1' in n or 'mike2' in n for n in found)
    assert plan.metadata['transferred_templates']>=2
    assert plan.slots==weapon_plan(['rex_ar_mike4_mp','weapons/mike4/fire_01.qnn.85.48000.all'],reversed(corpus),'mike4',{'number_max':2}).slots

def test_manual_simple_seed_export_extension_and_limits():
    plan=weapon_plan(['rex_ar_mike4_mp.png'],[],'mike4',{'strip_export_extension':True})
    assert 'rex_ar_mike4_sp' in names(plan)
    assert all(not n.endswith('.png') for n in names(plan))
    with pytest.raises(ValueError,match='没有包含'):weapon_plan(['rex_ar_mike40_mp'],[],'mike4')
    with pytest.raises(ValueError,match='武器代号'):weapon_plan(['seed'],[],'')
    with pytest.raises(ValueError,match='上限'):weapon_plan(['weapons/mike4/fire_01.snd'],[],'mike4',{'max_candidates':2})
    with pytest.raises(ValueError,match='number_max'):weapon_plan(['mike4'],[],'mike4',{'number_max':1000})

def test_explicit_donor_keyword_for_non_number_weapon():
    plan=weapon_plan(['rex_ar_mike4'],['rex_stock_rifle'],'mike4',{'donor_keywords':['rifle']})
    assert 'rex_stock_mike4' in names(plan)

@pytest.mark.parametrize('backend',['cpu','gpu'])
def test_weapon_discovery_verification_and_incremental_export(tmp_path,backend):
    if backend=='gpu' and not any('name' in d for d in devices()):pytest.skip('No GPU')
    p=PROFILES['iw-resource63']
    hidden=['rex_ar_mike4_sp','rex_stock_mike4','rex_attachments/rex_bar_mike4','weapons/mike4/reload_02.snd']
    files=tmp_path/'assets';files.mkdir()
    for name in hidden:(files/f'xsound_{p.digest(name):016x}.wav').write_bytes(b'fixture')
    (files/f'xmodel_{p.digest("rex_ar_mike4_mp"):016x}.fbx').write_bytes(b'fixture')
    store=Store(tmp_path/'work.sqlite');report=store.import_exported(files,'weapon-test',p.id)
    assert report['models_excluded']==1
    plan=weapon_plan(['rex_ar_mike4_mp','weapons/mike4/fire_01.snd'],['rex_stock_sierra4','rex_attachments/rex_bar_sierra4'],'mike4',{'number_max':2})
    task=create_task(store,plan,[p.id],backend=backend,duty=100,details={'weapon_exploration':plan.metadata})
    store.close();assert run_task(tmp_path/'work.sqlite',task)['status']=='completed'
    store=Store(tmp_path/'work.sqlite')
    found={r[0] for r in store.db.execute("SELECT name FROM evidence WHERE method='discovered'")}
    assert found==set(hidden)
    indexes=tmp_path/'existing';indexes.mkdir();(indexes/'names.cdb').write_bytes(encode_cdb({p.digest(hidden[0]):hidden[0]}))
    result=export(store,tmp_path/'out',saluki_dir=indexes)
    assert result['entries']==3 and result['excluded_saluki_existing_keys']==1
    assert decode_cdb((Path(result['path'])/'verified.cdb').read_bytes())=={p.digest(n):n for n in hidden[1:]}
    frozen=json.loads(store.task(task)['config']);assert frozen['details']['weapon_exploration']['weapon']=='mike4'
    store.close()
