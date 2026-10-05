"""Coverage keeps pool provenance and raw counts distinct from imported keys."""
from copy import deepcopy
import json

from finder.coverage import snapshot_coverage
from finder.formats import encode_cdb
from finder.hashing import PROFILES
from finder.snapshot import MASK63,MASK64,_pool_registry
from finder.store import Store
from test_snapshot import enhanced,legacy


def indexes(root,known):
    root.mkdir();(root/'fixture.cdb').write_bytes(encode_cdb(known));return root


def test_folder_coverage_retains_existing_fields_and_directory_counts(tmp_path):
    folder=tmp_path/'exports';(folder/'copies').mkdir(parents=True)
    for path in (folder/'anim_12345678.cast',folder/'copies'/'anim_12345678.cast',folder/'image_22345678.png'):
        path.write_bytes(b'exported fixture')
    store=Store(tmp_path/'work.sqlite')
    try:
        store.import_exported(folder,'COD2026','iw-resource63')
        report=snapshot_coverage(store,indexes(tmp_path/'indexes',{0x12345678:'known'}))
        assert report['known_keys']==1 and report['unknown_keys']==1
        assert report['scope']=='full-key Saluki difference'
        assert report['refresh']=='folder contents and dictionary contents are fingerprinted on every run'
        assert report['pools']==[
            {'kind':'image','export_directory':'.','files':1},
            {'kind':'xanim','export_directory':'.','files':1},
            {'kind':'xanim','export_directory':'copies','files':1}]
        assert 'snapshot_fingerprint' not in report and 'provenance' not in report
    finally:store.close()


def test_legacy_pool_counts_include_skipped_records_without_promoting_scope(tmp_path):
    path=legacy(tmp_path/'old.ids',[(1,3),(1,9),(2,4),(3,6),(4,171),(5,999)])
    store=Store(tmp_path/'work.sqlite')
    try:
        store.import_snapshot(path,'BO4','fnv1a63')
        report=snapshot_coverage(store,indexes(tmp_path/'indexes',{1:'known'}))
        assert report['records']==6 and report['included_records']==2
        assert report['unique_targets']==2 and report['known_keys']==1 and report['unknown_keys']==0
        assert report['skipped_records']=={'material_excluded':1,'model_excluded':1,'unknown_domain':1,'unknown_pool':1}
        assert report['complete'] is True and report['whole_game_complete'] is False
        assert report['whole_snapshot_stable'] is None and report['verified_scope_pools'] is None
        assert report['complete_scope']=='legacy loaded set; whole-game completeness unproven'
        pools={item['pool']:item for item in report['pools']}
        assert pools[3]['kind']=='xanim' and pools[9]['kind']=='image'
        assert pools[3]['targets']==pools[9]['targets']==1
        assert pools[999]['kind'] is None and pools[999]['targets']==0
        assert pools[171]['import_status']=='unknown_domain'
        assert all('export_directory' not in item for item in pools.values())
        assert report['provenance']['source_files'][0]['file']==str(path)
        assert report['warnings']
    finally:store.close()


def test_raw64_masked_collisions_count_once_and_compare_canonical_keys(tmp_path):
    key=PROFILES['iw-resource63'].digest('coverage_mask_fixture')
    path=enhanced(tmp_path/'capture',[(key,'xanim',6),(key|(1<<63),'xanim',6),
        (key|(1<<63),'image',14),(2,'',999)],strings=['coverage_mask_fixture'])
    store=Store(tmp_path/'work.sqlite')
    try:
        store.import_snapshot(path,'COD2026','iw-resource63')
        report=snapshot_coverage(store,indexes(tmp_path/'indexes',{key:'known'}))
        assert report['records']==4 and report['included_records']==3
        assert report['unique_targets']==2 and report['known_keys']==1 and report['unknown_keys']==0
        pools={item['pool']:item for item in report['pools']}
        assert pools[6]['raw_records']==2 and pools[6]['included_records']==2
        assert pools[6]['targets']==pools[6]['saluki_known']==1
        assert pools[14]['targets']==pools[14]['saluki_known']==1
        assert pools[10]['raw_records']==pools[10]['targets']==0 and pools[10]['import_status']=='empty'
        assert pools[6]['profile_id']=='iw-resource63' and pools[6]['stored_mask']==f'{MASK63:016x}'
        assert report['verified_scope_pools']==sorted(map(int,_pool_registry()['COD2026']['pools']))
        assert report['scope']=='full-key Saluki difference in current loaded snapshot set'
        assert report['complete_scope']=='all supported mapped pools in current loaded set; whole-game completeness unproven'
        assert report['whole_snapshot_stable'] is True and report['whole_game_complete'] is False
        assert report['loaded_scope']==['fixture.ff']
        assert report['formal_export_eligible'] is True
        sources=report['provenance']['source_files']
        assert {'snapshot-manifest','snapshot','snapshot-strings'}<={item['role'] for item in sources}
        assert all(len(item['sha256'])==64 for item in sources)
        assert report['provenance']['build_fingerprints']==json.loads(path.read_text())['build_fingerprints']
        assert report['refresh'].startswith('snapshot,') and 'folder contents' not in report['refresh']
    finally:store.close()


def test_saluki_raw_high_bit_key_does_not_hide_masked_target(tmp_path):
    key=PROFILES['iw-resource63'].digest('coverage_mask_lookup')
    path=enhanced(tmp_path/'capture',[(key|(1<<63),'xanim',6)])
    store=Store(tmp_path/'work.sqlite')
    try:
        store.import_snapshot(path,'COD2026','iw-resource63')
        report=snapshot_coverage(store,indexes(tmp_path/'indexes',{key|(1<<63):'raw full64'}))
        assert report['known_keys']==0 and report['unknown_keys']==1
        pool=next(item for item in report['pools'] if item['pool']==6)
        assert pool['saluki_known']==0 and pool['unknown']==1
    finally:store.close()


def test_same_kind_cross_pool_key_is_one_target_but_each_pool_has_coverage(tmp_path):
    key=PROFILES['iw-resource63'].digest('script_fixture')
    path=enhanced(tmp_path/'capture',[(key,'scriptfile',64),(key|(1<<63),'scriptfile',65)])
    metadata=json.loads(path.read_text())
    next(item for item in metadata['pools'] if item['pool']==64)['type_name']='untrusted_manifest_label'
    path.write_text(json.dumps(metadata),encoding='utf-8')
    store=Store(tmp_path/'work.sqlite')
    try:
        store.import_snapshot(path,'COD2026','iw-resource63')
        report=snapshot_coverage(store,indexes(tmp_path/'indexes',{key:'script_fixture'}))
        assert report['unique_targets']==report['known_keys']==1
        assert report['records']==report['included_records']==2
        assert report['types']==[{'kind':'scriptfile','targets':1,'saluki_known':1,'unknown':0}]
        pools={item['pool']:item for item in report['pools']}
        assert pools[64]['targets']==pools[65]['targets']==1
        assert pools[64]['saluki_known']==pools[65]['saluki_known']==1
        assert pools[64]['type_name']=='gscobj' and pools[65]['type_name']=='gscgdb'
    finally:store.close()


def test_material_coverage_filter_respects_imported_and_caller_selection(tmp_path):
    path=legacy(tmp_path/'old.ids',[(1,3),(2,6)])
    index=indexes(tmp_path/'indexes',{2:'material'})
    store=Store(tmp_path/'work.sqlite')
    try:
        store.import_snapshot(path,'BO4','fnv1a63',exclude_material=False)
        report=snapshot_coverage(store,index,True)
        assert report['unique_targets']==1 and report['included_records']==1
        assert report['skipped_records']=={'material_excluded':1}
        material=next(item for item in report['pools'] if item['pool']==6)
        assert material['kind']=='material' and material['targets']==0 and material['raw_records']==1
        assert material['import_status']=='material_excluded'
        included=snapshot_coverage(store,index,False)
        assert included['unique_targets']==2 and included['included_records']==2 and included['known_keys']==1
    finally:store.close()


def test_low60_coverage_is_explicit_pending_and_never_eligible_for_formal_export(tmp_path):
    key=PROFILES['iw-resource63'].digest('coverage_low60_fixture')
    path=enhanced(tmp_path/'capture',[(key|(1<<63),'xanim',6)])
    store=Store(tmp_path/'work.sqlite')
    try:
        store.import_snapshot(path,'COD2026','iw-resource63',truncated=True)
        report=snapshot_coverage(store,indexes(tmp_path/'indexes',{key:'full key'}))
        assert report['formal_export_eligible'] is False and report['key_comparison']=='low60-pending'
        assert report['scope']=='low60 candidate Saluki comparison; full-key difference unproven'
        assert report['included_records']==report['unique_targets']==1
        assert report['known_keys']==int(key==(key&((1<<60)-1)))
    finally:store.close()


def test_full64_snapshot_coverage_preserves_high_bit_domain_and_is_read_only(tmp_path,monkeypatch):
    profile=PROFILES['fnv1a64'];key=next(profile.digest('alias_'+str(i)) for i in range(100) if profile.digest('alias_'+str(i))>MASK63)
    adapter={'BO7':{'game_ids':['BLACKOP7'],'module_sha256':'a'*64,'config_sha256':'b'*64,
        'pools':{'88':{'kind':'soundbankalias','profile':profile.id,'key_width':64,
            'stored_mask':f'{MASK64:016x}','mapping_source':'independent full64 fixture'}}}}
    monkeypatch.setattr('finder.snapshot._pool_registry',lambda:deepcopy(adapter))
    path=enhanced(tmp_path/'capture',[(key,'soundbankalias',88)],game='BO7',profile=profile.id)
    index=indexes(tmp_path/'indexes',{key:'known full64'})
    store=Store(tmp_path/'work.sqlite')
    try:
        store.import_snapshot(path,'BO7',profile.id)
        before=list(store.db.iterdump())
        source_bytes={file:file.read_bytes() for file in path.parent.iterdir() if file.is_file()}
        report=snapshot_coverage(store,index)
        assert report['known_keys']==1 and report['pools'][0]['saluki_known']==1
        assert report['pools'][0]['profile_id']=='fnv1a64' and report['pools'][0]['pool']==88
        assert list(store.db.iterdump())==before
        assert all(file.read_bytes()==data for file,data in source_bytes.items())
    finally:store.close()
