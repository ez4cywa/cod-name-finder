import csv
import json
from pathlib import Path
import sqlite3

import pytest

from finder.candidates import Plan
from finder.exporter import export
from finder.hashing import PROFILES, Profile
from finder.methods import (MethodExhausted, SharedLedger, method_descriptor,
                            plan_fingerprint, targets_fingerprint)
from finder.store import Store


def descriptor(**values):
    return method_descriptor({'generator':'cross-asset-v1','rule':'identity-substitution',
                              'number_max':8,**values})


def test_method_identity_stable_parameters_and_code_hash_separate():
    first=descriptor()
    second=descriptor(number_max=20)
    assert first['method_id']==second['method_id']=='crossassets.identity_substitution'
    assert first['method_version']==second['method_version']=='1'
    assert len(first['generator_sha'])==64
    assert first['generator_sha']==second['generator_sha']
    assert first['parameters']!=second['parameters']
    assert method_descriptor()==method_descriptor()


def test_fingerprint_normalizes_names_preserves_indexes_and_discards_locations():
    profile=PROFILES['iw-resource63']
    targets=[('xanim','0123456789abcdef')]
    common={'profiles':[profile],'targets':targets,'catalog_fingerprint':targets_fingerprint(targets),
            'method':descriptor(),'options':{'keyword':'mike4','low60':False}}
    first=plan_fingerprint(Plan([['REX\\'],['mike4','kilo'],['_fire']]),
        sources=[{'file':'D:/saluki/a.cdb','sha256':'a'*64}],**common)
    copied=plan_fingerprint(Plan([['rex/'],['mike4','kilo'],['_fire']]),
        sources=[{'file':'F:/copied/b.cdb','sha256':'a'*64}],**common)
    changed_order=plan_fingerprint(Plan([['rex/'],['kilo','mike4'],['_fire']]),
        sources=[{'sha256':'a'*64}],**common)
    assert first==copied and first!=changed_order


@pytest.mark.parametrize('change', ['source','mask','keyword','low60','kind','generator','version','slot'])
def test_fingerprint_semantic_changes_invalidate(change):
    profile=PROFILES['iw-resource63'].json()
    options={'keyword':'rifle','low60':False,'types':['xanim']}
    values={'profiles':[profile],'targets':[('xanim','0000000000000001')],
            'method':descriptor(),'sources':[{'sha256':'a'*64}],'options':options}
    first=plan_fingerprint(Plan([['rifle'],['_fire','_reload']]),**values)
    slots=[['rifle'],['_fire','_reload']]
    if change=='source':values['sources']=[{'sha256':'b'*64}]
    if change=='mask':profile['mask']=(1<<60)-1
    if change=='keyword':options['keyword']='pistol'
    if change=='low60':options['low60']=True
    if change=='kind':options['types']=['sndasset']
    if change=='generator':values['method']=descriptor(generator_sha='f'*64)
    if change=='version':values['method']=descriptor(method_version='2')
    if change=='slot':slots=[['rifle'],['_fire','_idle']]
    assert plan_fingerprint(Plan(slots),**values)!=first


def test_target_snapshot_is_content_based_with_type_and_no_duplicates(tmp_path):
    first=tmp_path/'first';second=tmp_path/'copied';first.mkdir();second.mkdir()
    for root in (first,second):(root/'anim_123456789abcdef0.cast').write_bytes(b'x')
    (second/'anim_123456789abcdef0.bin').write_bytes(b'copy')
    with_store=[]
    for root in (first,second):
        store=Store(tmp_path/(root.name+'.sqlite'))
        store.import_exported(root,'COD2026','iw-resource63',default_kind='xanim')
        with_store.append(store.meta('catalog_fingerprint'));store.close()
    assert with_store[0]==with_store[1]
    assert targets_fingerprint([('xanim',1)])!=targets_fingerprint([('sndasset',1)])


def test_methods_guard_zero_streak_override_and_positive_reset(tmp_path):
    with SharedLedger(tmp_path/'.namefinder-ledger.sqlite') as ledger:
        item=descriptor();target='t'*64
        for i in range(3):
            run=ledger.start_run(item,target,profile='iw-resource63')
            ledger.finish_run(run,candidates=100,names=0,duration=.25)
        with pytest.raises(MethodExhausted,match='--anyway'):
            ledger.start_run(item,target,profile='iw-resource63')
        assert ledger.report()['methods'][0]['zero_streak']==3
        overridden=ledger.start_run(item,target,profile='iw-resource63',anyway=True)
        ledger.finish_run(overridden,candidates=100,names=2,duration=.5)
        report=ledger.report()['methods'][0]
        assert report['zero_streak']==0 and not report['exhausted']
        assert report['names']==2 and report['runs']==4 and report['candidates']==400
        assert report['names_per_million_candidates']==5000
        assert report['recent_runs'][0]['anyway']==1
        assert report['first_run']<=report['last_run']


def test_paused_and_failed_do_not_prove_method_exhausted(tmp_path):
    with SharedLedger(tmp_path/'ledger.sqlite') as ledger:
        for state in ('paused','cancelled','failed'):
            run=ledger.start_run(descriptor(),'t',profile='iw-resource63')
            assert ledger.finish_run(run,candidates=50,status=state)
            assert not ledger.finish_run(run,candidates=50,status=state)
        assert ledger.report()['methods'][0]['zero_streak']==0
        for _ in range(3):
            run=ledger.start_run(descriptor(),'t',profile='iw-resource63')
            ledger.finish_run(run)
        # Better generator version, parameters or target content gets its own scope.
        for item,target in [(descriptor(method_version='2'),'t'),(descriptor(number_max=30),'t'),(descriptor(),'new-target')]:
            ledger.start_run(item,target,profile='iw-resource63')


def test_legacy_store_migration_preserves_evidence_tasks_and_exports(tmp_path):
    profile=PROFILES['fnv1a64'];name='legacy_rifle';key=f'{profile.digest(name):016x}'
    path=tmp_path/'old.sqlite'
    db=sqlite3.connect(path)
    db.execute('CREATE TABLE evidence(hash TEXT,name TEXT,profile TEXT,source TEXT,source_game TEXT,method TEXT,details TEXT,UNIQUE(hash,name,profile,source,method))')
    db.execute('INSERT INTO evidence VALUES (?,?,?,?,?,?,?)',(key,name,profile.id,'old','game','discovered','{}'))
    db.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY,config TEXT,position INTEGER,total INTEGER,status TEXT,message TEXT,updated REAL)')
    db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?)',('oldtask','{}',27,100,'paused','old message',123.))
    db.commit();db.close()
    store=Store(path)
    with store.db:store.db.execute('INSERT INTO assets VALUES (?,?,?)',('xanim',key,'old.ff'))
    row=dict(store.db.execute('SELECT * FROM evidence').fetchone())
    assert row['profile_id']==profile.id and int(row['mask_used'])==(1<<64)-1
    assert row['method_id']=='legacy.discovered' and row['method_version']=='0'
    assert store.task('oldtask')['position']==27
    result=export(store,tmp_path/'output',allow_empty=True)
    exported=json.loads((Path(result['path'])/'evidence.jsonl').read_text(encoding='utf-8').strip())
    assert exported['mask_used']==(1<<64)-1
    with open(result['path']+'/evidence.csv',encoding='utf-8',newline='') as stream:
        csv_rows=list(csv.DictReader(stream))
    assert csv_rows[0]['method_id']=='legacy.discovered'
    store.close()
    reopened=Store(path)
    assert reopened.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]==1
    reopened.close()


def test_new_evidence_metadata_compatible_old_call_and_explicit_overrides(tmp_path):
    store=Store(tmp_path/'work.sqlite');profile=PROFILES['iw-resource63'];name='rifle'
    with store.db:
        store.add_evidence(profile.digest(name),name,profile.id,'old-api','game','discovered',{})
        store.add_evidence(profile.digest(name),name,profile.id,'new-api','game','discovered',{},
            method_id='custom.rule',method_version='3',generator_sha='a'*64,
            profile_id=profile.id,mask_used=profile.mask)
    rows=[dict(row) for row in store.db.execute('SELECT * FROM evidence ORDER BY source')]
    assert {row['method_id'] for row in rows}=={'custom.rule','plan.discovered'}
    assert all(int(row['mask_used'])==profile.mask for row in rows)
    assert all(json.loads(row['details'])['target_profile']==profile.json() for row in rows)
    store.close()


def test_evidence_metadata_migration_runs_once_and_preserves_old_data(tmp_path, monkeypatch):
    path=tmp_path/'legacy.sqlite';profile=PROFILES['iw-resource63']
    original=sqlite3.connect(path)
    original.execute('CREATE TABLE evidence(hash TEXT,name TEXT,profile TEXT,source TEXT,source_game TEXT,method TEXT,details TEXT,UNIQUE(hash,name,profile,source,method))')
    original.execute('INSERT INTO evidence VALUES (?,?,?,?,?,?,?)',
        (f'{profile.digest("rifle"):016x}','rifle',profile.id,'old','game','discovered','{}'))
    original.commit();original.close()
    statements=[];connect=sqlite3.connect
    def traced_connect(*args, **kwargs):
        connection=connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection
    monkeypatch.setattr(sqlite3,'connect',traced_connect)
    migrated=Store(path)
    row=dict(migrated.db.execute('SELECT * FROM evidence').fetchone())
    assert row['profile_id']==profile.id and int(row['mask_used'])==profile.mask
    assert any(statement.startswith('UPDATE evidence SET') for statement in statements)
    migrated.close();statements.clear()
    reopened=Store(path)
    assert dict(reopened.db.execute('SELECT * FROM evidence').fetchone())==row
    assert not any(statement.startswith(('UPDATE evidence SET','SELECT DISTINCT profile,method FROM evidence'))
                   for statement in statements)
    assert reopened.meta('evidence_metadata_schema')=='2'
    reopened.close()


@pytest.mark.parametrize('already_expanded', [False,True])
def test_evidence_migration_loads_custom_profile_and_partial_mask_first(tmp_path, monkeypatch, already_expanded):
    path=tmp_path/'custom-legacy.sqlite'
    profile=Profile(**(PROFILES['fnv1a64'].json()|{'id':'old-custom-migration','mask':(1<<63)-1}))
    monkeypatch.delitem(PROFILES,profile.id,raising=False)
    db=sqlite3.connect(path)
    db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
    db.execute('INSERT INTO meta VALUES (?,?)',('custom_profiles',json.dumps([profile.json()])))
    # The schema must be checked even if an interrupted/external upgrade left a marker.
    if not already_expanded:db.execute('INSERT INTO meta VALUES (?,?)',('evidence_metadata_schema','2'))
    db.execute('CREATE TABLE evidence(hash TEXT,name TEXT,profile TEXT,source TEXT,source_game TEXT,method TEXT,details TEXT,UNIQUE(hash,name,profile,source,method))')
    for method in ('discovered','partial_match'):
        db.execute('INSERT INTO evidence VALUES (?,?,?,?,?,?,?)',('0000000000000001',method,profile.id,'old','game',method,'{}'))
    if already_expanded:
        for field in ('method_id','method_version','generator_sha','profile_id','mask_used'):
            db.execute(f"ALTER TABLE evidence ADD COLUMN {field} TEXT NOT NULL DEFAULT ''")
    db.commit();db.close()
    store=Store(path)
    rows={row['method']:dict(row) for row in store.db.execute('SELECT * FROM evidence')}
    assert rows['discovered']['mask_used']==str(profile.mask)
    assert rows['partial_match']['mask_used']==str((1<<60)-1)
    assert all(row['profile_id']==profile.id and row['method_id']=='legacy.'+method for method,row in rows.items())
    assert store.meta('evidence_metadata_schema')=='2'
    store.close()
    # Store loads persisted custom profiles into the process registry.
    PROFILES.pop(profile.id)


def test_evidence_migration_marker_and_backfill_are_atomic(tmp_path, monkeypatch):
    path=tmp_path/'interrupted.sqlite';profile=PROFILES['iw-resource63']
    db=sqlite3.connect(path)
    db.execute('CREATE TABLE evidence(hash TEXT,name TEXT,profile TEXT,source TEXT,source_game TEXT,method TEXT,details TEXT,UNIQUE(hash,name,profile,source,method))')
    db.execute('INSERT INTO evidence VALUES (?,?,?,?,?,?,?)',('0000000000000001','old',profile.id,'old','game','discovered','{}'))
    db.commit();db.close()
    class InterruptedMigration(sqlite3.Connection):
        def execute(self, statement, *args, **kwargs):
            if statement=='INSERT OR REPLACE INTO meta VALUES (?,?)' and args[0][0]=='evidence_metadata_schema':
                raise sqlite3.OperationalError('simulated migration interruption')
            return super().execute(statement,*args,**kwargs)
    connect=sqlite3.connect
    monkeypatch.setattr(sqlite3,'connect',lambda *args,**kwargs:connect(*args,factory=InterruptedMigration,**kwargs))
    with pytest.raises(sqlite3.OperationalError,match='simulated migration interruption'):Store(path)
    monkeypatch.setattr(sqlite3,'connect',connect)
    db=connect(path)
    assert db.execute("SELECT value FROM meta WHERE key='evidence_metadata_schema'").fetchone() is None
    assert 'profile_id' not in {row[1] for row in db.execute('PRAGMA table_info(evidence)')}
    db.close()
    recovered=Store(path)
    assert recovered.meta('evidence_metadata_schema')=='2'
    assert recovered.db.execute('SELECT profile_id FROM evidence').fetchone()[0]==profile.id
    recovered.close()


def test_weapon_generator_is_identified_without_mutating_existing_metadata():
    original={'weapon':'mike4','seed_names':['rex_vm_ar_mike4_fire'],'number_max':8}
    descriptor_value=method_descriptor(original)
    assert descriptor_value['method_id']=='weapon.observed_family'
    assert 'generator' not in original


def test_concurrent_finishes_do_not_double_count_one_run(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path=tmp_path/'ledger.sqlite'
    with SharedLedger(path) as ledger:run=ledger.start_run(descriptor(),'target')
    def finish(_):
        with SharedLedger(path) as ledger:return ledger.finish_run(run,candidates=100,names=1,duration=1)
    with ThreadPoolExecutor(max_workers=4) as executor:completed=list(executor.map(finish,range(4)))
    assert completed.count(True)==1
    with SharedLedger(path) as ledger:
        report=ledger.report()
        assert report['methods'][0]['runs']==1
        assert report['summary'][0]['candidates']==100 and report['summary'][0]['names']==1


def test_readonly_ledger_does_not_create_or_modify_files(tmp_path):
    import hashlib
    path=tmp_path/'ledger.sqlite'
    with SharedLedger(path) as ledger:ledger.record_sweep('plan','xanim',0,100)
    before={file.name:(hashlib.sha256(file.read_bytes()).hexdigest(),file.stat().st_mtime_ns)
            for file in tmp_path.iterdir()}
    with SharedLedger(path,readonly=True) as ledger:
        assert ledger.remaining('plan','xanim',0,200)==[(100,200)]
        assert ledger.report()['methods']==[]
        with pytest.raises(ValueError,match='只读'):ledger.record_sweep('plan','xanim',100,200)
        with pytest.raises(ValueError,match='只读'):ledger.start_run(descriptor(),'target')
    after={file.name:(hashlib.sha256(file.read_bytes()).hexdigest(),file.stat().st_mtime_ns)
           for file in tmp_path.iterdir()}
    assert after==before
    absent=tmp_path/'missing/ledger.sqlite'
    with pytest.raises(FileNotFoundError):SharedLedger(absent,readonly=True)
    assert not absent.parent.exists()


def test_readonly_ledger_sees_live_writer_wal_commits(tmp_path):
    with SharedLedger(tmp_path/'ledger.sqlite') as writer:
        writer.record_sweep('plan','xanim',0,100)
        with SharedLedger(writer.path,readonly=True) as reader:
            assert reader.remaining('plan','xanim',0,200)==[(100,200)]
