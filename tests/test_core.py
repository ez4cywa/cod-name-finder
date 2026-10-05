import csv
import json
import sqlite3
import struct
import random
from pathlib import Path
import pytest
from finder.hashing import PROFILES,Profile,batch_digest,parse_hash
from finder.candidates import Plan,audio_plan
from finder.backends import CPU,GPU,devices
from finder.formats import encode_cdb,decode_cdb,iter_dictionary
from finder.store import Store
from finder.engine import create_task,run_task
from finder.exporter import export

P=PROFILES['iw-resource63']

def catalog(tmp_path,names=None):
    path=tmp_path/'catalog.sqlite'
    db=sqlite3.connect(path)
    db.execute('CREATE TABLE assets(asset_type TEXT,name_hash TEXT,name TEXT,package TEXT)')
    names=names or [('sndasset','weapons/rifle_fire_01.snd'),('xanim','rifle_fire'),('material','rifle_mat'),('xmodel','rifle_model')]
    for kind,name in names:
        db.execute('INSERT INTO assets VALUES (?,?,?,?)',(kind,f'{P.digest(name):016x}',name,'test.ff'))
    db.commit();db.close()
    work=tmp_path/'work.sqlite';s=Store(work);s.import_catalog(path,'test-build')
    return s,path

def test_reference_vectors_and_native_unicode():
    assert PROFILES['fnv1a64-raw'].digest('hello')==0xa430d84680aabd0b
    names=['hello','A\\B','测试_声音','İß','a/b', '0','weapons/rifle_fire_01.snd']
    for p in PROFILES.values():
        assert list(batch_digest(names,p,3))==[p.digest(n) for n in names]
    assert P.digest('A\\B')==P.digest('a/b')
    assert P.normalize('İ')=='İ'  # ASCII case behavior is explicit.

def test_parse_strict():
    assert parse_hash('0xFFFFFFFFFFFFFFFF')==(1<<64)-1
    for h in ['-1','g','10000000000000000','']:
        with pytest.raises(ValueError):parse_hash(h)

def test_cdb_independent_layout():
    values={0:'a',0xffffffffffffffff:'中文',12:'comma,name'}
    blob=encode_cdb(values)
    assert decode_cdb(blob)==values
    import lz4.block
    magic,n,packed,size=struct.unpack_from('<4sIII',blob)
    assert magic==b'PNDB' and n==3
    raw=lz4.block.decompress(blob[16:],uncompressed_size=size)
    names=raw[:-8*n].split(b'\0')[:-1]
    hashes=struct.unpack('<3Q',raw[-24:])
    assert dict(zip(hashes,[n.decode() for n in names]))==values
    for bad in [blob[:10],blob+b'x',b'BAD!'+blob[4:]]:
        with pytest.raises(ValueError):decode_cdb(bad)
    assert decode_cdb(encode_cdb({}))=={}

def test_audio_preserves_underscore_and_extension_candidates():
    plan=audio_plan('weapons_rifle_fire_01.wav',['weapons'],['.snd','.rn75.pc.en.snd'])
    names={plan.at(i) for i in range(plan.total)}
    assert 'weapons/rifle_fire_01.snd' in names
    assert 'weapons_rifle_fire_01.snd' in names
    assert 'weapons/rifle_fire_01.rn75.pc.en.snd' in names
    with pytest.raises(ValueError):audio_plan('_'.join(['a']*15)+'.wav',[],['.snd'])

def test_combinations_exact_full_keys():
    p=Plan([['A/','测试/'],['rifle','pistol'],['_fire_01','.snd']])
    targets={P.digest(p.at(0)),P.digest(p.at(7))}
    cpu=CPU(p,P,targets,3)
    assert cpu.scan(0,p.total)==[0,7]
    assert cpu.scan(4,4)==[3]
    wrong={h^0x1000000000000000 for h in targets}
    assert CPU(p,P,wrong).scan(0,p.total)==[]

def test_prior_source_profile_not_target_profile(tmp_path):
    s,path=catalog(tmp_path)
    other=PROFILES['fnv1a63'];name='from_previous_game'
    h=other.digest(name)
    s.db.execute('INSERT INTO assets VALUES (?,?,?)',('sndasset',f'{h:016x}','test.ff'));s.db.commit()
    csvpath=tmp_path/'prior.csv'
    with csvpath.open('w',newline='') as f:csv.writer(f).writerows([(f'{h:x}',name),(f'{h^1:x}',name),(f'{P.digest("rifle_mat"):x}','rifle_mat')])
    r=s.import_dictionary([csvpath],'previous-game',['fnv1a63'])
    assert r['target_matches']==1 and r['rejected']==2
    assert P.digest(name)!=h
    out=export(s,tmp_path/'exports',new_only=True)
    assert decode_cdb((Path(out['path'])/'verified.cdb').read_bytes())=={h:name}
    s.close()

def test_fullkey_no_low60_reuse(tmp_path):
    s,path=catalog(tmp_path)
    name='previous';h=P.digest(name)
    s.db.execute('INSERT INTO assets VALUES (?,?,?)',('sndasset',f'{h^0x1000000000000000:016x}','test.ff'));s.db.commit()
    f=tmp_path/'names.csv';f.write_text(f'{h:x},{name}\n')
    assert s.import_dictionary([f],'previous',['iw-resource63'])['target_matches']==0
    s.close()

def test_conflict_export_and_filter(tmp_path):
    s,path=catalog(tmp_path)
    h=P.digest('weapons/rifle_fire_01.snd')
    s.add_evidence(h,'collision-other','iw-resource63','another','test','prior_verified',{})
    s.db.commit()
    out=export(s,tmp_path/'out')
    values=decode_cdb((Path(out['path'])/'verified.cdb').read_bytes())
    assert h not in values
    assert P.digest('rifle_mat') not in values
    assert P.digest('rifle_model') not in values
    assert values=={P.digest('rifle_fire'):'rifle_fire'}
    assert out['excluded_conflict_keys']==1
    _,rows=s.results(keyword='rifle');assert any(r['conflict'] for r in rows)
    s.close()

def test_pause_resume_budget_idempotence(tmp_path):
    s,path=catalog(tmp_path)
    plan=Plan([['weapons/'],['rifle'],['_fire_01','_fire_02'],['.snd']])
    task=create_task(s,plan,['iw-resource63'],backend='cpu',budget=1,duty=100,unknown_only=False)
    s.close()
    r=run_task(tmp_path/'work.sqlite',task,control=lambda:'pause')
    assert r['position']==0 and r['status']=='paused'
    r=run_task(tmp_path/'work.sqlite',task)
    assert r['status']=='budget_exhausted' and r['position']==1
    r=run_task(tmp_path/'work.sqlite',task)
    assert r['status']=='completed' and r['position']==2
    s=Store(tmp_path/'work.sqlite')
    assert s.db.execute("SELECT COUNT(*) FROM evidence WHERE method='discovered'").fetchone()[0]==1
    s.close()

def test_unproven_type_rejected(tmp_path):
    s,path=catalog(tmp_path)
    s.db.execute('INSERT INTO assets VALUES (?,?,?)',('unknown_domain','0000000000000001','t'));s.db.commit()
    with pytest.raises(ValueError):create_task(s,Plan([['test']]),['iw-resource63'],kinds=['unknown_domain'])
    s.close()

@pytest.mark.skipif(not any('name' in d for d in devices()),reason='no GPU')
def test_gpu_native_reference_parity():
    plan=Plan([['a/','测试/','A\\'],[f'weapon_{i}' for i in range(75)],['_fire','_reload','_01.snd']])
    for profile in PROFILES.values():
        indexes=[0,22,100,plan.total-1]
        targets={profile.digest(plan.at(i)) for i in indexes}
        expected=[i for i in range(plan.total) if profile.digest(plan.at(i)) in targets]
        assert CPU(plan,profile,targets).scan(0,plan.total)==expected
        assert GPU(plan,profile,targets).scan(0,plan.total)==expected
