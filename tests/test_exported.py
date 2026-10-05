import csv
import json
from pathlib import Path
import pytest
from finder.store import Store
from finder.hashing import PROFILES
from finder.candidates import Plan,automatic_plan
from finder.engine import create_task,run_task
from finder.formats import decode_cdb
from finder.exporter import export,prepare_saluki
from finder.process import isolated

def test_exported_keyword_discovery_and_process_isolation(tmp_path):
    profile=PROFILES['fnv1a64'];name='weapons/rifle_fire_05.snd'
    folder=tmp_path/'files';folder.mkdir()
    target=profile.digest(name)
    (folder/f'sound_{target:016x}.wav').write_bytes(b'test')
    (folder/'original_readable_name.wav').write_bytes(b'test')
    (folder/'xmodel_123456789abcdef0.cast').write_bytes(b'test')
    s=Store(tmp_path/'work.sqlite')
    r=s.import_exported(folder,'corresponding-game','fnv1a64')
    assert r['hashed_files']==1 and r['models_excluded']==1 and r['unrecognized']==1
    plan=automatic_plan(['weapons/rifle_fire_01.snd'],'rifle',10)
    task=create_task(s,plan,['fnv1a64'],keyword='rifle',backend='cpu',duty=100)
    s.close()
    done=isolated(tmp_path/'work.sqlite',task,lambda *_:None,lambda:'run')
    assert done['status']=='completed'
    s=Store(tmp_path/'work.sqlite')
    out=export(s,tmp_path/'out')
    assert decode_cdb((Path(out['path'])/'verified.cdb').read_bytes())=={target:name}
    assert s.db.execute('SELECT path FROM asset_files').fetchone()[0].endswith('.wav')
    s.close()

def test_low60_candidate_never_formal_export(tmp_path):
    p=PROFILES['iw-resource63'];name='weapons/rifle_fire_05.snd';h=p.digest(name)
    folder=tmp_path/'files';folder.mkdir();(folder/f'sound_{h&((1<<60)-1):015x}.wav').write_bytes(b'x')
    s=Store(tmp_path/'work.sqlite');s.import_exported(folder,'game',p.id,truncated=True)
    task=create_task(s,Plan([[name]]),[p.id],backend='cpu',duty=100);s.close()
    run_task(tmp_path/'work.sqlite',task)
    s=Store(tmp_path/'work.sqlite')
    assert s.db.execute('SELECT method FROM evidence').fetchone()[0]=='partial_match'
    with pytest.raises(ValueError):export(s,tmp_path/'out')
    s.close()

def test_saluki_merge_preserves_existing_conflicts(tmp_path):
    from finder.formats import encode_cdb
    incoming=tmp_path/'incoming/hash_pkg';incoming.mkdir(parents=True)
    install=tmp_path/'saluki/hash_pkg';install.mkdir(parents=True)
    (incoming/'fnv1a_xsounds_v2.cdb').write_bytes(encode_cdb({1:'new',2:'new2'}))
    original=encode_cdb({1:'old',3:'old3'});(install/'fnv1a_xsounds_v2.cdb').write_bytes(original)
    r=prepare_saluki(tmp_path/'incoming',tmp_path/'saluki',tmp_path/'merged')
    assert r['conflicts'] and (install/'fnv1a_xsounds_v2.cdb').read_bytes()==original
    assert decode_cdb((tmp_path/'merged/hash_pkg/fnv1a_xsounds_v2.cdb').read_bytes())=={1:'old',2:'new2',3:'old3'}


def test_saluki_existing_keys_excluded_from_every_output(tmp_path):
    from finder.formats import encode_cdb
    p=PROFILES['iw-resource63'];names=['old_sound','new_sound','old_different_name']
    pairs={p.digest(n):n for n in names}
    folder=tmp_path/'assets';folder.mkdir()
    for h in pairs:(folder/f'sound_{h:016x}.wav').write_bytes(b'fixture')
    s=Store(tmp_path/'work.sqlite');s.import_exported(folder,'test',p.id)
    for h,n in pairs.items():s.add_evidence(h,n,p.id,'test','test','match',{})
    s.db.commit()
    pkg=tmp_path/'saluki/hash_pkg';pkg.mkdir(parents=True)
    old={p.digest(names[0]):names[0],p.digest(names[2]):'another_verified_old_name'}
    (pkg/'first.cdb').write_bytes(encode_cdb(old))
    (pkg/'second.cdb').write_bytes(encode_cdb({p.digest(names[0]):names[0]}))
    before=(pkg/'first.cdb').read_bytes()
    result=export(s,tmp_path/'out',saluki_dir=pkg.parent)
    assert result['excluded_saluki_existing_keys']==2 and result['entries']==1
    out=Path(result['path']);assert decode_cdb((out/'verified.cdb').read_bytes())=={p.digest(names[1]):names[1]}
    assert len((out/'evidence.jsonl').read_text(encoding='utf-8').splitlines())==1
    for cdb in (out/'hash_pkg').glob('*.cdb'):assert not set(decode_cdb(cdb.read_bytes())) & set(old)
    assert (pkg/'first.cdb').read_bytes()==before
    copied=tmp_path/'copied-indexes';copied.mkdir()
    (copied/'names.cdb').write_bytes(before)
    direct=export(s,tmp_path/'direct-out',saluki_dir=copied)
    assert direct['excluded_saluki_existing_keys']==2
    (pkg/'all.cdb').write_bytes(encode_cdb(pairs))
    empty=export(s,tmp_path/'empty',saluki_dir=pkg.parent)
    assert empty['entries']==0 and empty['excluded_saluki_existing_keys']==3
    assert decode_cdb((Path(empty['path'])/'verified.cdb').read_bytes())=={}
    (pkg/'bad.cdb').write_bytes(b'broken')
    with pytest.raises(ValueError,match='索引读取失败'):export(s,tmp_path/'bad-out',saluki_dir=pkg.parent)
    with pytest.raises(ValueError,match='没有可读取'):export(s,tmp_path/'missing-out',saluki_dir=tmp_path/'missing')
    s.close()


def test_import_asset_type_filters_known_types_and_classifies_unknown(tmp_path):
    files=tmp_path/'mixed';files.mkdir()
    for name in ['XSOUND_1111111111111111.wav','ximage_2222222222222222.dds','3333333333333333.bin','xmodel_4444444444444444.cast']:
        (files/name).write_bytes(b'fixture')
    s=Store(tmp_path/'typed.sqlite')
    result=s.import_exported(files,'test','iw-resource63',default_kind='image',kinds=['image'])
    assert result['hashed_files']==2 and result['types_filtered']==1 and result['models_excluded']==1
    assert result['selected_types']==['image']
    assert {r[0] for r in s.db.execute('SELECT DISTINCT kind FROM assets')}=={'image'}
    s.close()


def test_saluki_prefixes_without_x_keep_type_and_model_exclusion(tmp_path):
    files=tmp_path/'saluki';files.mkdir()
    for name in ['sound_1111111111111111.wav','xsound_2222222222222222.wav','anim_3333333333333333.cast','xanim_4444444444444444.cast','model_5555555555555555.fbx','xmodel_6666666666666666.fbx','ANIM_7777777777777777.bin']:
        (files/name).write_bytes(b'fixture')
    store=Store(tmp_path/'work.sqlite');result=store.import_exported(files,'saluki','iw-resource63')
    assert result['hashed_files']==5 and result['models_excluded']==2
    types={r['hash']:r['kind'] for r in store.db.execute('SELECT * FROM assets')}
    assert types['1111111111111111']=='sndasset' and types['2222222222222222']=='sndasset'
    assert types['3333333333333333']=='xanim' and types['4444444444444444']=='xanim' and types['7777777777777777']=='xanim'
    filtered=store.import_exported(files,'saluki','iw-resource63',default_kind='xanim',kinds=['xanim'])
    assert filtered['hashed_files']==3 and filtered['types_filtered']==2 and filtered['models_excluded']==2
    store.close()
