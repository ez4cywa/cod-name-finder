from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import zlib

import pytest

from finder.completedcache import CompletedCache, signature
from finder.exporter import export
from finder.formats import decode_cdb, encode_cdb
from finder.hashing import PROFILES
from finder.methods import SharedLedger, canonical_json
from finder.pipeline import Config
from finder.store import Store


def fixture(tmp_path, *, low60=False, add_hits=True):
    assets=tmp_path/'assets';assets.mkdir()
    indexes=tmp_path/'indexes/hash_pkg';indexes.mkdir(parents=True)
    names=['rex_vm_ar_mike4_fire','rex_vm_ar_mike4_reload']
    profile=PROFILES['iw-resource63'];mask=profile.mask & ((1<<60)-1) if low60 else profile.mask
    for name in names:
        (assets/f'anim_{profile.digest(name)&mask:016x}.cast').write_bytes(b'asset body is not a name input')
    (assets/'readable_weapon_clue.cast').write_bytes(b'x')
    (indexes/'fnv1a_xanims_v2.cdb').write_bytes(encode_cdb({profile.digest('rex_vm_ar_mike4_idle'):'rex_vm_ar_mike4_idle'}))
    config=Config(str(assets),str(indexes.parent),str(tmp_path/'output'),low60=low60)
    store=fresh(tmp_path/'work.sqlite',config)
    if add_hits:
        with store.db:
            for name in names:
                store.add_evidence(profile.digest(name)&mask,name,profile.id,'original-stage','COD2026',
                    'partial_match' if low60 else 'discovered',{'target_truncated':low60},
                    method_id='crossassets.identity_substitution',method_version='1',generator_sha='a'*64)
    return config,store,names


def fresh(path,config):
    store=Store(path)
    store.import_exported(config.folder,config.game,config.profile,default_kind=config.asset_type,
        truncated=config.low60,kinds=[config.asset_type])
    return store


def test_signature_uses_content_and_relative_names_with_no_database_decoding(tmp_path,monkeypatch):
    config,store,_=fixture(tmp_path)
    dictionary=tmp_path/'dictionary';dictionary.mkdir()
    (dictionary/'names.txt').write_text('some_rifle\n',encoding='utf-8')
    borrowed=tmp_path/'donor.csv';borrowed.write_text('1,borrowed_weapon\n',encoding='utf-8')
    related=tmp_path/'related/models';related.mkdir(parents=True)
    (related/'rex_ar_mike4_model.cast').write_bytes(b'x')
    config=replace(config,dictionary=str(dictionary),borrowed_dictionary=str(borrowed),related_folder=str(related.parent))
    def forbidden(*args,**kwargs):raise AssertionError('signature must not decode or build plans')
    monkeypatch.setattr('finder.pipeline.decode_cdb',forbidden)
    monkeypatch.setattr('finder.pipeline.build_cross_asset_plans',forbidden)
    first=signature(config,store)
    copied=tmp_path/'other-drive';copied.mkdir()
    for directory in ('assets','indexes','dictionary','related'):
        shutil.copytree(tmp_path/directory,copied/directory)
    shutil.copyfile(borrowed,copied/'renamed-donor.csv')
    moved=replace(config,folder=str(copied/'assets'),indexes=str(copied/'indexes'),
        dictionary=str(copied/'dictionary'),borrowed_dictionary=str(copied/'renamed-donor.csv'),
        related_folder=str(copied/'related'),output=str(copied/'another-output'))
    assert signature(moved,store)['key']==first['key']
    assert str(tmp_path) not in canonical_json(first['inputs'])
    assert {source['role'] for source in first['sources']}=={'index','dictionary','borrowed'}
    assert all(Path(source['file']).is_absolute() for source in first['sources'])
    assert first['inputs']['related_names']['count']==3
    assert first['inputs']['readable_names']['count']==1
    store.close()


@pytest.mark.parametrize('field,value',[
    ('game','MWIII'),('profile','fnv1a64'),('asset_type','sndasset'),
    ('exclude_material',False),('keyword','mike4'),('low60',True),('number_max',7),
    ('cross_asset',False),('hash_domain','scripts'),('allow_unverified_domain',True)])
def test_signature_semantic_options_invalidate(tmp_path,field,value):
    config,store,_=fixture(tmp_path)
    assert signature(config,store)['key']!=signature(replace(config,**{field:value}),store)['key']
    store.close()


def test_signature_runtime_budget_and_backend_do_not_change_completed_membership(tmp_path):
    config,store,_=fixture(tmp_path)
    assert signature(config,store)['key']==signature(replace(config,backend='gpu',budget=1,seconds=1,anyway=True),store)['key']
    store.close()


@pytest.mark.parametrize('change',['index_bytes','index_name','dictionary','borrowed','stem','relative_related','targets','profile','registry','implementation'])
def test_signature_input_mutations_invalidate(tmp_path,monkeypatch,change):
    config,store,_=fixture(tmp_path)
    dictionary=tmp_path/'names.txt';dictionary.write_text('alpha',encoding='utf-8')
    borrowed=tmp_path/'borrowed.txt';borrowed.write_text('bravo',encoding='utf-8')
    related=tmp_path/'related/sub';related.mkdir(parents=True)
    clue=related/'rex_ar_mike4.cast';clue.write_bytes(b'x')
    config=replace(config,dictionary=str(dictionary),borrowed_dictionary=str(borrowed),related_folder=str(related.parent))
    first=signature(config,store)['key']
    index=Path(config.indexes)/'hash_pkg/fnv1a_xanims_v2.cdb'
    if change=='index_bytes':index.write_bytes(index.read_bytes()+b'changed')
    if change=='index_name':index.rename(index.with_name('other_xanims.cdb'))
    if change=='dictionary':dictionary.write_text('charlie',encoding='utf-8')
    if change=='borrowed':borrowed.write_text('delta',encoding='utf-8')
    if change=='stem':(Path(config.folder)/'readable_weapon_clue.cast').rename(Path(config.folder)/'changed_weapon_clue.cast')
    if change=='relative_related':clue.rename(related.parent/'rex_ar_mike4.cast')
    if change=='targets':
        with store.db:store.setmeta('catalog_fingerprint','b'*64)
    if change=='profile':monkeypatch.setitem(PROFILES,config.profile,replace(PROFILES[config.profile],seed=123))
    if change=='registry':monkeypatch.setattr('finder.completedcache.REGISTRY_SHA256','c'*64)
    if change=='implementation':monkeypatch.setattr('finder.completedcache._implementation_hashes',lambda control:{'new-source':'d'*64})
    assert signature(config,store)['key']!=first
    store.close()


def test_signature_cancelled_during_streaming_is_a_cache_miss(tmp_path):
    config,store,_=fixture(tmp_path)
    dictionary=tmp_path/'large.txt';dictionary.write_bytes(b'a'*(4*1024*1024))
    count=0
    def control():
        nonlocal count
        count+=1
        return 'run' if count<8 else 'stop'
    assert signature(replace(config,dictionary=str(dictionary)),store,control) is None
    assert count==8
    store.close()


def test_signature_validated_community_snapshot_is_opt_in_and_content_pinned(tmp_path):
    config,store,_=fixture(tmp_path)
    cache=tmp_path/'community';commit='a'*40
    table=cache/'snapshots'/commit/'csv/t10_xanim.csv';table.parent.mkdir(parents=True)
    table.write_text('0000000000000001,community_name\n',encoding='utf-8')
    metadata={'commit':commit,'files':[{'name':table.name,'sha256':hashlib.sha256(table.read_bytes()).hexdigest()}]}
    (cache/'current.json').write_text(json.dumps(metadata),encoding='utf-8')
    enabled=replace(config,community=True,community_cache=str(cache))
    result=signature(enabled,store)
    assert result and any(source['role']=='community' for source in result['sources'])
    assert result['key']!=signature(config,store)['key']
    assert signature(replace(enabled,community_refresh=True),store) is None
    table.write_text('changed',encoding='utf-8')
    assert signature(enabled,store) is None
    assert signature(replace(config,community_cache=str(cache)),store)['key']==signature(config,store)['key']
    assert signature(replace(enabled,community_cache=str(tmp_path/'missing')),store) is None
    store.close()


def test_completed_cache_restores_metadata_cpu_verified_words_and_saluki_difference(tmp_path,monkeypatch):
    config,source,names=fixture(tmp_path);key=signature(config,source)['key']
    summary={'status':'completed','processed':10,'stages':[{'status':'completed'}],'custom':{'any':True}}
    with SharedLedger(tmp_path/'ledger.sqlite') as ledger:ledger.record_sweep('other-plan','xanim',0,8)
    with CompletedCache(tmp_path/'ledger.sqlite') as cache:
        cache.save(key,source,summary);record=cache.lookup(key)
    assert record['summary']==summary
    assert len(record['evidence'])==2 and all(len(hit['generator_sha'])==64 for hit in record['evidence'])
    restored=fresh(tmp_path/'restored.sqlite',config)
    def forbidden(*args,**kwargs):raise AssertionError('native/GPU hashing must not be used for cache verification')
    monkeypatch.setattr('finder.hashing.batch_digest',forbidden)
    monkeypatch.setattr('finder.hashing.native',forbidden)
    stats=CompletedCache.restore(record,restored,config.profile)
    assert stats=={'inserted':2,'verified':2,'pending_low60':0,'total':2}
    rows=[dict(row) for row in restored.db.execute('SELECT * FROM evidence')]
    assert {row['name'] for row in rows}==set(names)
    assert all(row['method_id']=='crossassets.identity_substitution' and row['source']=='original-stage' for row in rows)
    assert all(json.loads(row['details'])['completed_run_cache'] for row in rows)
    assert restored.db.execute('SELECT COUNT(*) FROM words').fetchone()[0]==2
    index=Path(config.indexes)/'hash_pkg/fnv1a_xanims_v2.cdb'
    index.write_bytes(encode_cdb({PROFILES[config.profile].digest(names[0]):names[0]}))
    result=export(restored,tmp_path/'export',saluki_dir=config.indexes)
    assert result['entries']==1 and result['excluded_saluki_existing_keys']==1
    assert decode_cdb((Path(result['path'])/'verified.cdb').read_bytes())=={PROFILES[config.profile].digest(names[1]):names[1]}
    with SharedLedger(tmp_path/'ledger.sqlite',readonly=True) as ledger:
        assert ledger.remaining('other-plan','xanim',0,8)==[]
    source.close();restored.close()


@pytest.mark.parametrize('change',['name','hash','profile','mask','snapshot','kind','target_type','mode','missing_field','corrupt_details'])
def test_completed_cache_rejects_entire_tampered_package_before_writing(tmp_path,change):
    config,source,_=fixture(tmp_path)
    with CompletedCache(tmp_path/'ledger.sqlite') as cache:
        cache.save('key',source,{'status':'completed'});record=cache.lookup('key')
    hit=record['evidence'][-1]
    if change=='name':hit['name']='unverified_candidate'
    if change=='hash':hit['hash']='0000000000000001'
    if change=='profile':hit['profile']='fnv1a64'
    if change=='mask':hit['mask_used']=str((1<<60)-1)
    if change=='snapshot':hit['details']=json.dumps({'target_profile':PROFILES['fnv1a64'].json()})
    if change=='kind':hit['_asset_kinds']=['sndasset']
    if change=='target_type':record['targets'][-1][0]='sndasset'
    if change=='mode':record['low60']=True
    if change=='missing_field':hit.pop('method_id')
    if change=='corrupt_details':hit['details']='not JSON'
    restored=fresh(tmp_path/'restored.sqlite',config)
    assert CompletedCache.restore(record,restored,config.profile) is None
    assert restored.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]==0
    assert restored.db.execute('SELECT COUNT(*) FROM words').fetchone()[0]==0
    source.close();restored.close()


def test_completed_cache_insertion_failure_rolls_back_every_restored_row(tmp_path,monkeypatch):
    config,source,names=fixture(tmp_path)
    with CompletedCache(tmp_path/'ledger.sqlite') as cache:
        cache.save('key',source,{'status':'completed'});record=cache.lookup('key')
    restored=fresh(tmp_path/'restored.sqlite',config);profile=PROFILES[config.profile]
    with restored.db:restored.add_evidence(profile.digest(names[0]),names[0],profile.id,'pre-existing','COD2026','prior_verified',{})
    original_rows=[dict(row) for row in restored.db.execute('SELECT * FROM evidence')]
    insert=restored.add_evidence;calls=0
    def interrupted(*args,**kwargs):
        nonlocal calls
        calls+=1
        if calls==2:raise sqlite3.OperationalError('simulated full restore interruption')
        return insert(*args,**kwargs)
    monkeypatch.setattr(restored,'add_evidence',interrupted)
    assert CompletedCache.restore(record,restored,profile.id) is None
    assert calls==2
    assert [dict(row) for row in restored.db.execute('SELECT * FROM evidence')]==original_rows
    assert restored.db.execute('SELECT COUNT(*) FROM words').fetchone()[0]==0
    source.close();restored.close()


def test_completed_cache_low60_stays_pending_and_never_formally_exports(tmp_path):
    config,source,_=fixture(tmp_path,low60=True)
    with CompletedCache(tmp_path/'ledger.sqlite') as cache:
        cache.save('partial-key',source,{'status':'completed'});record=cache.lookup('partial-key')
    restored=fresh(tmp_path/'restored.sqlite',config)
    assert CompletedCache.restore(record,restored,config.profile,low60=True)=={
        'inserted':2,'verified':0,'pending_low60':2,'total':2}
    assert restored.db.execute('SELECT COUNT(*) FROM words').fetchone()[0]==0
    assert export(restored,tmp_path/'export',allow_empty=True)['entries']==0
    assert CompletedCache.restore(record,restored,config.profile,low60=False) is None
    source.close();restored.close()


def test_completed_cache_preserves_conflicts_and_empty_completed_search(tmp_path):
    config,source,names=fixture(tmp_path)
    profile=PROFILES[config.profile]
    with source.db:source.add_evidence(profile.digest(names[0]),names[0].upper(),profile.id,'conflicting-text','COD2026','discovered',{})
    with CompletedCache(tmp_path/'ledger.sqlite') as cache:
        cache.save('conflict-key',source,{'status':'completed'});record=cache.lookup('conflict-key')
    restored=fresh(tmp_path/'restored.sqlite',config)
    assert CompletedCache.restore(record,restored,config.profile)['total']==3
    result=export(restored,tmp_path/'export')
    assert result['entries']==1 and result['excluded_conflict_keys']==1
    with source.db:source.db.execute('DELETE FROM evidence')
    with CompletedCache(tmp_path/'ledger.sqlite') as cache:
        cache.save('empty-key',source,{'status':'completed'});empty=cache.lookup('empty-key')
    assert empty['evidence']==[]
    empty_store=fresh(tmp_path/'empty.sqlite',config)
    assert CompletedCache.restore(empty,empty_store,config.profile)=={'inserted':0,'verified':0,'pending_low60':0,'total':0}
    source.close();restored.close();empty_store.close()


def test_completed_cache_readonly_does_not_change_files_or_require_new_table(tmp_path):
    config,source,_=fixture(tmp_path)
    ledger_path=tmp_path/'ledger.sqlite'
    with SharedLedger(ledger_path):pass
    before={file.name:(hashlib.sha256(file.read_bytes()).hexdigest(),file.stat().st_mtime_ns)
            for file in tmp_path.iterdir() if file.is_file()}
    with CompletedCache(ledger_path,readonly=True) as cache:
        assert cache.lookup('not-yet-saved') is None
        with pytest.raises(ValueError,match='只读'):cache.save('key',source,{})
    after={file.name:(hashlib.sha256(file.read_bytes()).hexdigest(),file.stat().st_mtime_ns)
           for file in tmp_path.iterdir() if file.is_file()}
    assert after==before
    missing=tmp_path/'missing/ledger.sqlite'
    with pytest.raises(FileNotFoundError):CompletedCache(missing,readonly=True)
    assert not missing.parent.exists()
    with CompletedCache(ledger_path) as cache:cache.save('key',source,{'status':'completed','saved':True})
    with CompletedCache(ledger_path,readonly=True) as cache:assert cache.lookup('key')['summary']=={'status':'completed','saved':True}
    source.close()


def test_completed_cache_bad_compression_checksum_and_cpu_tamper_are_misses(tmp_path):
    config,source,_=fixture(tmp_path)
    with CompletedCache(tmp_path/'ledger.sqlite') as cache:
        cache.save('key',source,{'status':'completed'});record=deepcopy(cache.lookup('key'))
        with cache.db:cache.db.execute('UPDATE complete_runs SET payload=? WHERE key=?',(b'broken','key'))
        assert cache.lookup('key') is None
        cache.save('key',source,{'status':'completed'})
        with cache.db:cache.db.execute("UPDATE complete_runs SET payload_sha256='wrong' WHERE key='key'")
        assert cache.lookup('key') is None
        # A rewritten checksum is not trusted as name validation.
        record['evidence'][-1]['name']='forged-name'
        blob=canonical_json(record).encode('utf-8')
        with cache.db:cache.db.execute('UPDATE complete_runs SET payload=?,payload_sha256=? WHERE key=?',
            (zlib.compress(blob),hashlib.sha256(blob).hexdigest(),'key'))
        found=cache.lookup('key')
    restored=fresh(tmp_path/'restored.sqlite',config)
    assert found is not None and CompletedCache.restore(found,restored,config.profile) is None
    assert restored.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]==0
    source.close();restored.close()


@pytest.mark.parametrize('status',['paused','stopped','failed','budget_exhausted',None])
def test_completed_cache_never_publishes_incomplete_tasks(tmp_path,status):
    config,source,_=fixture(tmp_path)
    with CompletedCache(tmp_path/'ledger.sqlite') as cache:
        with pytest.raises(ValueError,match='已完成'):
            cache.save('partial',source,{'status':status})
        assert cache.lookup('partial') is None
        cache.save('key',source,{'status':'completed'});record=cache.lookup('key')
        record['summary']['status']=status
        blob=canonical_json(record).encode('utf-8')
        with cache.db:cache.db.execute('UPDATE complete_runs SET payload=?,payload_sha256=? WHERE key=?',
            (zlib.compress(blob),hashlib.sha256(blob).hexdigest(),'key'))
        assert cache.lookup('key') is None
    source.close()
