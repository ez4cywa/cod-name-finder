from dataclasses import replace
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import shutil
import struct

import pytest

from finder.completedcache import signature
from finder.formats import decode_cdb,encode_cdb
from finder.hashing import PROFILES
from finder.pipeline import Config,import_snapshot,prepare,run
from finder.snapshot import read_snapshot,MASK63,MASK64
from finder.store import Store


def legacy(path,records,game='BLKOPS04',sidecar=None):
    data=game.encode('utf-8')
    path.write_bytes(b'CODIDS'+struct.pack('<HH',1,len(data))+data+struct.pack('<Q',len(records))+
        b''.join(struct.pack('<QH',raw,pool) for raw,pool in records))
    if sidecar is not None:path.with_suffix('.pools.txt').write_text(sidecar,encoding='utf-8')
    return path


def enhanced(root,records,*,game='COD2026',profile='iw-resource63',strings=None,extra_pools=()):
    from finder.snapshot import _pool_registry
    root.mkdir()
    adapter=_pool_registry()[game]
    pools={int(pool):{**deepcopy(item),'pool':int(pool),'count':0,'stable':True,'errors':[]}
           for pool,item in adapter['pools'].items()}
    for raw,kind,pool in records:
        item=pools.setdefault(pool,{'pool':pool,'kind':kind or None,'profile':profile if kind else None,
            'key_width':64,'stored_mask':f'{MASK64:016x}','count':0,'stable':True,'errors':[],
            'mapping_source':'local-verified-fixture-build'})
        item['count']+=1
    for item in extra_pools:pools[item['pool']]=item
    records_path=root/'records.csv'
    with records_path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['raw_hash','type','pool'])
        writer.writerows((f'{raw:016x}',kind,pool) for raw,kind,pool in sorted(records,key=lambda row:(row[0],row[2])))
    metadata={'format':'CODSNAP2','version':2,'game':game,'game_id':adapter['game_ids'][0],
        'build':'sha256:'+adapter['module_sha256'],
        'build_fingerprints':{key:adapter[key] for key in ('module_sha256','config_sha256')},
        'verified_scope_pools':[int(pool) for pool in adapter['pools']],
        'state_stable':True,'whole_snapshot_stable':True,
        'adapter':'fixture-independent','raw_key_width':64,'complete':True,'loaded_scope':['fixture.ff'],
        'records':{'file':'records.csv','sha256':hashlib.sha256(records_path.read_bytes()).hexdigest(),'count':len(records)},
        'pools':list(pools.values())}
    if strings is not None:
        strings_path=root/'strings.txt';strings_path.write_text(''.join(value+'\n' for value in strings),encoding='utf-8')
        metadata['strings']={'file':'strings.txt','sha256':hashlib.sha256(strings_path.read_bytes()).hexdigest(),
            'count':len(strings),'bytes':strings_path.stat().st_size,'complete':True}
    path=root/'snapshot.json';path.write_text(json.dumps(metadata),encoding='utf-8')
    return path


def mutate(path,change):
    metadata=json.loads(path.read_text(encoding='utf-8'));change(metadata)
    path.write_text(json.dumps(metadata),encoding='utf-8')


def test_validated_current_loaded_scope_survives_import(tmp_path):
    path=enhanced(tmp_path/'source',[(1,'xanim',6)])
    mutate(path,lambda metadata:next(pool for pool in metadata['pools'] if pool['pool']==6).update(type_name='untrusted label'))
    assert read_snapshot(path)['loaded_scope']==['fixture.ff']
    assert read_snapshot(path)['pools'][6]['type_name']=='xanim'
    store=Store(tmp_path/'scope.sqlite')
    try:
        report=store.import_snapshot(path,'COD2026','iw-resource63',kinds=('xanim',))
        assert report['loaded_scope']==['fixture.ff']
        assert json.loads(store.meta('snapshot_metadata'))['loaded_scope']==['fixture.ff']
    finally:store.close()


@pytest.mark.parametrize('scope',['entire game',[1],['bad\nvalue'],['bad\x00value']])
def test_invalid_loaded_scope_is_rejected(tmp_path,scope):
    path=enhanced(tmp_path/'source',[(1,'xanim',6)])
    mutate(path,lambda metadata:metadata.update(loaded_scope=scope))
    with pytest.raises(ValueError,match='loaded_scope'):read_snapshot(path)


@pytest.mark.parametrize('sidecar',[
    'BLKOPS04 -- 4 assets in 3 filled pools\nindex  asset type  assets\n3  xanim  2\n9  image  1\n999  pool_999  1\n',
    'pool,type,count\n3,xanim,2\n9,image,1\n999,pool_999,1\n'])
def test_legacy_binary_and_both_pool_lists_preserve_cross_pool_keys(tmp_path,sidecar):
    path=legacy(tmp_path/'legacy.ids',[(1,3),(1,9),(2,3),(3,999)],sidecar=sidecar)
    snapshot=read_snapshot(path)
    assert snapshot['game']=='BO4' and snapshot['format']=='CODIDSv1' and snapshot['key_width']==63
    assert snapshot['records'][:2]==[(1,3),(1,9)]
    assert snapshot['pools'][3]['kind']=='xanim' and snapshot['pools'][9]['kind']=='image'
    assert snapshot['pools'][999]['kind'] is None and snapshot['warnings']
    copied=tmp_path/'other';copied.mkdir()
    shutil.copy2(path,copied/path.name);shutil.copy2(path.with_suffix('.pools.txt'),copied/path.with_suffix('.pools.txt').name)
    assert read_snapshot(copied/path.name)['fingerprint']==snapshot['fingerprint']


@pytest.mark.parametrize('change',['truncated','trailer','version','ordering','duplicate','highbit','count','utf8'])
def test_legacy_corruption_is_rejected_before_import(tmp_path,change):
    path=legacy(tmp_path/'bad.ids',[(1,3),(2,3)])
    data=bytearray(path.read_bytes())
    if change=='truncated':data=data[:-1]
    if change=='trailer':data+=b'trailer'
    if change=='version':data[6:8]=struct.pack('<H',2)
    if change=='ordering':path=legacy(path,[(2,3),(1,3)]);data=path.read_bytes()
    if change=='duplicate':path=legacy(path,[(1,3),(1,3)]);data=path.read_bytes()
    if change=='highbit':path=legacy(path,[(1<<63,3)]);data=path.read_bytes()
    if change=='count':data[18:26]=struct.pack('<Q',0xffffffffffffffff)
    if change=='utf8':data[10]=0xff
    path.write_bytes(data)
    with pytest.raises(ValueError,match='快照'):read_snapshot(path)


@pytest.mark.parametrize('sidecar',[
    'pool,type,count\n3,xanim,1\n3,xanim,1\n',
    'pool,type,count\n3,xanim,2\n',
    'pool,type,count\n3,xanim,1\n9,image,1\n',
    'pool,type,count\n3,xanim,not-count\n'])
def test_legacy_invalid_pool_counts_and_duplicate_pool_metadata_rejected(tmp_path,sidecar):
    path=legacy(tmp_path/'legacy.ids',[(1,3)],sidecar=sidecar)
    with pytest.raises(ValueError,match='池清单'):read_snapshot(path)


def test_legacy_game_specific_mapping_never_uses_coldwar_labels_for_bo4(tmp_path):
    path=legacy(tmp_path/'legacy.ids',[(1,3),(2,5)],sidecar='pool,type,count\n3,physconstraints,1\n5,xanim,1\n')
    snapshot=read_snapshot(path)
    assert snapshot['pools'][3]['kind']=='xanim'
    assert snapshot['pools'][5]['kind'] is None
    cw=legacy(tmp_path/'cw.ids',[(2,5)],game='BLKOPSCW')
    assert read_snapshot(cw)['pools'][5]['kind']=='xanim'


def test_snapshot_store_filters_models_materials_unknown_and_incompatible_profiles(tmp_path):
    path=legacy(tmp_path/'source.ids',[(1,3),(1,9),(2,4),(3,6),(4,171),(5,999)])
    store=Store(tmp_path/'work.sqlite')
    report=store.import_snapshot(path,'BO4','fnv1a63',exclude_material=True)
    assert report['unique_assets']==2 and report['hashed_files']==2
    assert report['models_excluded']==1 and report['materials_excluded']==1
    assert report['skipped_counts']['unknown_domain']==1 and report['skipped_counts']['unknown_pool']==1
    assert store.db.execute('SELECT COUNT(*) FROM snapshot_records').fetchone()[0]==6
    assert {row['kind'] for row in store.targets()}=={'xanim','image'}
    assert store.db.execute('SELECT COUNT(*) FROM words').fetchone()[0]==0
    with pytest.raises(ValueError,match='作品'):store.import_snapshot(path,'BOCW','fnv1a63')
    with pytest.raises(ValueError,match='兼容'):store.import_snapshot(path,'BO4','fnv1a64')
    assert store.db.execute('SELECT COUNT(*) FROM snapshot_records').fetchone()[0]==6
    store.close()


def test_enhanced_raw_high_bit_is_preserved_and_resource_key_correctly_masked(tmp_path):
    profile=PROFILES['iw-resource63'];key=profile.digest('rex_vm_ar_mike4_fire')
    path=enhanced(tmp_path/'capture',[(key|(1<<63),'xanim',6),(1,'',999)],strings=['rex_vm_ar_mike4_fire'])
    snapshot=read_snapshot(path)
    assert snapshot['key_width']==64 and snapshot['records'][-1][0]==key|(1<<63)
    assert Path(snapshot['strings_path']).read_text(encoding='utf-8').strip()=='rex_vm_ar_mike4_fire'
    store=Store(tmp_path/'work.sqlite');report=store.import_snapshot(path,'COD2026',profile.id,kinds=['xanim'])
    assert report['unique_assets']==1
    assert store.targets()[0]['hash']==f'{key:016x}'
    assert store.db.execute('SELECT raw_hash FROM snapshot_records WHERE pool=6').fetchone()[0]==f'{key|(1<<63):016x}'
    assert store.meta('snapshot_dictionary')==snapshot['strings_path']
    store.close()


@pytest.mark.parametrize('change',['sha','count','path','pool_duplicate','pool_count','record_type','partial','unstable','errors','width','unknown_type','gameid','strings_sha','strings_count'])
def test_enhanced_strict_manifest_and_csv_validation(tmp_path,change):
    path=enhanced(tmp_path/'capture',[(1,'xanim',6)],strings=['clue'])
    def alter(metadata):
        if change=='sha':metadata['records']['sha256']='0'*64
        if change=='count':metadata['records']['count']=2
        if change=='path':metadata['records']['file']='../outside.csv'
        if change=='pool_duplicate':metadata['pools'].append(dict(metadata['pools'][0]))
        if change=='pool_count':metadata['pools'][0]['count']=2
        if change=='record_type':metadata['pools'][0]['kind']='image'
        if change=='partial':metadata['complete']=False
        if change=='unstable':metadata['pools'][0]['stable']=False
        if change=='errors':metadata['pools'][0]['errors']=['read failed']
        if change=='width':metadata['pools'][0]['key_width']=64
        if change=='unknown_type':metadata['pools'][0]['kind']='invented_asset'
        if change=='gameid':metadata['game_id']='BO4'
        if change=='strings_sha':metadata['strings']['sha256']='0'*64
        if change=='strings_count':metadata['strings']['count']=2
    mutate(path,alter)
    with pytest.raises(ValueError,match='快照'):read_snapshot(path)


def test_enhanced_full64_alias_is_compatible_only_when_independent_adapter_exists(tmp_path,monkeypatch):
    profile=PROFILES['fnv1a64'];name=next('alias_'+str(i) for i in range(100) if profile.digest('alias_'+str(i))>MASK63)
    adapted={'BO7':{'game_ids':['BLACKOP7'],'module_sha256':'a'*64,'config_sha256':'b'*64,
        'pools':{'88':{'kind':'soundbankalias','profile':profile.id,'key_width':64,
            'stored_mask':f'{MASK64:016x}','mapping_source':'independent full64 domain fixture'}}}}
    monkeypatch.setattr('finder.snapshot._pool_registry',lambda:adapted)
    path=enhanced(tmp_path/'capture',[(profile.digest(name),'soundbankalias',88)],game='BO7',profile=profile.id)
    store=Store(tmp_path/'work.sqlite')
    report=store.import_snapshot(path,'BO7',profile.id,kinds=['soundbankalias'])
    assert report['unique_assets']==1 and int(store.targets()[0]['hash'],16)>MASK63
    with pytest.raises(ValueError,match='兼容'):store.import_snapshot(path,'BO7','iw-resource63')
    # A future independently approved 63-bit storage source must still not
    # authenticate the original 64-bit alias domain.
    adapted['BO7']['pools']['88'].update(key_width=63,stored_mask=f'{MASK63:016x}')
    mutate(path,lambda metadata:metadata['pools'][0].update(key_width=63,stored_mask=f'{MASK63:016x}'))
    with pytest.raises(ValueError,match='domain_lost_bits'):store.import_snapshot(path,'BO7',profile.id)
    store.close()


def test_snapshot_cancellation_and_replacement_preserve_existing_work(tmp_path):
    path=legacy(tmp_path/'source.ids',[(1,3),(2,3)])
    assert read_snapshot(path,control=lambda:'stop') is None
    store=Store(tmp_path/'work.sqlite')
    assert store.import_snapshot(path,'BO4','fnv1a63',cancelled=lambda:True)=={'cancelled':True}
    store.import_snapshot(path,'BO4','fnv1a63')
    before=[dict(row) for row in store.db.execute('SELECT * FROM assets')]
    def progress(count,message):store.setmeta('cancel_probe','yes')
    store.db.commit()
    result=store.import_snapshot(path,'BO4','fnv1a63',progress=progress,
        cancelled=lambda:store.meta('cancel_probe')=='yes')
    assert result['cancelled']
    assert [dict(row) for row in store.db.execute('SELECT * FROM assets')]==before
    assert store.meta('cancel_probe')==''
    store.close()


def test_pipeline_snapshot_strings_are_candidates_and_complete_cache_can_reuse(tmp_path):
    profile=PROFILES['iw-resource63'];name='rex_vm_ar_mike4_fire'
    path=enhanced(tmp_path/'capture',[(profile.digest(name),'xanim',6)],strings=[name])
    indexes=tmp_path/'indexes';indexes.mkdir()
    (indexes/'fnv1a_xanims_v2.cdb').write_bytes(encode_cdb({profile.digest('rex_vm_ar_mike4_idle'):'rex_vm_ar_mike4_idle'}))
    config=Config('',str(indexes),str(tmp_path/'output'),input_mode='snapshot',snapshot_file=str(path),
        profile=profile.id,asset_type='xanim',game='COD2026',backend='cpu',cross_asset=False,number_max=0)
    config.validate()
    store=Store(tmp_path/'probe.sqlite');snapshot=import_snapshot(config,store);prepared=prepare(config,store,snapshot=snapshot)
    assert name in prepared['names'] and store.db.execute('SELECT COUNT(*) FROM words').fetchone()[0]==0
    assert any(source.get('role')=='snapshot-strings' for source in prepared['extra_sources'])
    first_signature=signature(config,store)
    copied=tmp_path/'copied';shutil.copytree(path.parent,copied)
    moved=replace(config,snapshot_file=str(copied/'snapshot.json'),output=str(tmp_path/'another-output'))
    moved_store=Store(tmp_path/'moved.sqlite');import_snapshot(moved,moved_store)
    assert signature(moved,moved_store)['key']==first_signature['key']
    store.close();moved_store.close()
    first=run(config);second=run(config)
    assert first['entries']==second['entries']==1
    assert second['complete_cache_reused'] and second['processed']==0
    assert decode_cdb((Path(second['path'])/'verified.cdb').read_bytes())=={profile.digest(name):name}


def test_unknown_unstable_diagnostic_pool_does_not_promote_to_formal_target(tmp_path):
    path=enhanced(tmp_path/'capture',[(1,'xanim',6),(2,'',999)])
    def diagnostics(metadata):
        unknown=next(pool for pool in metadata['pools'] if pool['pool']==999)
        unknown.update(stable=False,errors=['diagnostic-only boundary changed'])
        metadata['whole_snapshot_stable']=False
    mutate(path,diagnostics)
    snapshot=read_snapshot(path)
    assert snapshot['complete'] and snapshot['whole_snapshot_stable'] is False
    assert any('不完整' in warning for warning in snapshot['warnings'])
    store=Store(tmp_path/'work.sqlite');report=store.import_snapshot(path,'COD2026','iw-resource63')
    assert report['unique_assets']==1
    assert store.db.execute('SELECT status FROM snapshot_records WHERE pool=999').fetchone()[0]=='unknown_pool'
    store.close()


@pytest.mark.parametrize('change',['module','config','fingerprints_missing','state','scope_missing_pool','scope_extra_pool',
                                  'scope_duplicate','declared_pool_removed','numeric_mapping','profile','mask','unmapped_alias'])
def test_manifest_cannot_claim_unproven_build_or_pool_scope(tmp_path,change):
    path=enhanced(tmp_path/'capture',[(1,'xanim',6)])
    def forged(metadata):
        if change=='module':metadata['build_fingerprints']['module_sha256']='0'*64
        if change=='config':metadata['build_fingerprints']['config_sha256']='0'*64
        if change=='fingerprints_missing':metadata.pop('build_fingerprints')
        if change=='state':metadata['state_stable']=False
        if change=='scope_missing_pool':metadata['verified_scope_pools'].pop()
        if change=='scope_extra_pool':metadata['verified_scope_pools'].append(999)
        if change=='scope_duplicate':metadata['verified_scope_pools'].append(6)
        if change=='declared_pool_removed':metadata['pools'].pop()
        if change=='numeric_mapping':metadata['pools'][0]['kind']='image'
        if change=='profile':metadata['pools'][0]['profile']='fnv1a64'
        if change=='mask':metadata['pools'][0]['stored_mask']=f'{MASK64:016x}'
        if change=='unmapped_alias':metadata['pools'].append({'pool':999,'kind':'soundbankalias','profile':'fnv1a64',
            'stored_mask':f'{MASK64:016x}','key_width':64,'count':0,'stable':True,'errors':[],
            'mapping_source':'arbitrary manifest assertion'})
    mutate(path,forged)
    with pytest.raises(ValueError,match='快照'):read_snapshot(path)
