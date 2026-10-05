"""Exercise portable snapshots through the installed AOT/worker boundary.

The fixture is explicitly synthetic; live capture is validated separately.
"""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from finder.cordycep import _profiles, _write_snapshot
from finder.formats import encode_cdb, decode_cdb
from finder.hashing import PROFILES


def validate(executable, base, environment):
    base=Path(base)/'Portable Snapshot';base.mkdir()
    profile=PROFILES['iw-resource63'];adapter=_profiles('COD2026')
    names={6:'mw7_fixture_portable_animation',186:'mw7_fixture_portable_sound',
        26:'mw7_fixture_portable_bank',87:'mw7_fixture_portable_animpkg'}
    expected={profile.digest(name):name for pool,name in names.items() if pool!=26}
    pools={int(pool):{**item,'count':int(int(pool) in names),'stable':True,'errors':[]}
        for pool,item in adapter['pools'].items()}
    pools[200]={'kind':None,'profile':None,'key_width':64,'stored_mask':'ffffffffffffffff',
        'mapping_source':'synthetic diagnostic pool','count':1,'stable':False,'errors':['fixture churn']}
    raw={(profile.digest(name)|(1<<63),pool) for pool,name in names.items()}
    raw.add((0xfedcba9876543210,200))
    snapshot=_write_snapshot(base/'Original Snapshot','COD2026',
        {'pid':1234,'game_id':'MODWAR7','_capture_state_stable':True},adapter,pools,raw,
        set(names.values()),{'bytes':123,'complete':True},True,'synthetic installer fixture',
        ['fixture current loaded set; not the whole game'])
    portable=base/'New Computer Snapshot';shutil.copytree(Path(snapshot['snapshot_file']).parent,portable)
    indexes=base/'Copied Saluki Indexes';indexes.mkdir()
    known={profile.digest(names[26]):names[26],1:'portable_unrelated_preserved'}
    (indexes/'fnv1a_strings.cdb').write_bytes(encode_cdb(known))
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in portable.iterdir() if p.is_file()}
    configuration={'input_mode':'snapshot','snapshot_file':str(portable/'snapshot.json'),
        'folder':'','indexes':str(indexes),'output':str(base/'Output'),'asset_type':'auto',
        'game':'COD2026','profile':profile.id,'cross_asset':False,'backend':'cpu',
        'number_max':0,'budget':100000,'seconds':120}
    config=base/'configuration.json';config.write_text(json.dumps(configuration,ensure_ascii=False),encoding='utf-8')
    commands=[]
    def execute(*args):
        result=subprocess.run([str(executable),*map(str,args)],cwd=base,env=environment,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding='utf-8',timeout=180)
        assert result.returncode==0,(args,result.stderr,result.stdout[-2000:])
        assert 'Traceback' not in result.stdout+result.stderr
        rows=[json.loads(row) for row in result.stdout.splitlines() if row.strip()]
        commands.append({'args':list(map(str,args)),'exit_code':result.returncode})
        return rows[-1].get('result',rows[-1].get('estimate',rows[-1]))
    quote=execute('estimate',config)
    assert quote['target_count']==4
    run=execute('run',config)
    assert run['verified_target_matches']==4 and run['excluded_existing']==1
    output=Path(run['path']);values=decode_cdb((output/'verified.cdb').read_bytes())
    assert values==expected
    with (output/'new_names.csv').open(encoding='utf-8',newline='') as stream:
        assert {int(key,16):name for key,name in csv.reader(stream)}==expected
    for key,name in values.items():assert profile.digest(name)==key
    packages={6:'fnv1a_xanims_v2.cdb',186:'fnv1a_xsounds_v2.cdb',87:'fnv1a_animpkgs_v2.cdb'}
    reader=Path(executable).parent/'engine/_internal/cdb-inspect.exe'
    for pool,package in packages.items():
        path=output/'hash_pkg'/package
        actual=subprocess.run([str(reader),str(path)],env=environment,cwd=base,
            capture_output=True,encoding='utf-8',timeout=30,check=True)
        assert {int(key,16):name for key,name in json.loads(actual.stdout).items()}=={
            profile.digest(names[pool]):names[pool]}
    assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in portable.iterdir() if p.is_file()}
    assert decode_cdb((indexes/'fnv1a_strings.cdb').read_bytes())==known
    incomplete=json.loads((portable/'snapshot.json').read_text(encoding='utf-8'));incomplete['complete']=False
    partial=portable/'partial.json';partial.write_text(json.dumps(incomplete),encoding='utf-8')
    configuration['snapshot_file']=str(partial);config.write_text(json.dumps(configuration),encoding='utf-8')
    rejected=subprocess.run([str(executable),'run',str(config)],env=environment,cwd=base,
        capture_output=True,encoding='utf-8',timeout=60)
    errors=[json.loads(line) for line in rejected.stdout.splitlines() if line.strip()]
    assert rejected.returncode!=0 and errors[-1]['event']=='error'
    assert '完整' in errors[-1]['message'] and 'Traceback' not in rejected.stderr
    return {'synthetic_fixture':True,'live_cordycep_test':False,'raw64_portability_verified':True,
        'unknown_pool_diagnostic_only':True,'target_count':4,'new_names':len(expected),
        'saluki_existing_excluded':1,'independent_rust_cdb_files':len(packages),
        'partial_snapshot_rejected':True,'source_files_unchanged':True,
        'no_system_python_or_dotnet':True,'commands':commands}
