"""Read-only Saluki differences with the target input's actual provenance."""
from collections import Counter
import json
from pathlib import Path

from .exporter import saluki_known_keys
from .hashing import PROFILES,parse_hash


def _pool_coverage(store,targets,known,exclude_material):
    """Count raw records and distinct imported keys separately, per engine pool.

    A raw uint64 key may collapse with another raw key after the profile's
    stored mask. The raw key is therefore never looked up directly in Saluki,
    nor counted as a second target after masking.
    """
    metadata=json.loads(store.meta('snapshot_metadata','{}'))
    sources=json.loads(store.meta('snapshot_sources','[]'))
    declared={int(pool):item for pool,item in metadata.get('pools',{}).items()}
    pools={pool:{'pool':pool,'kind':item.get('kind'),'type_name':item.get('type_name'),
        'legacy_label':item.get('label'),'profile_id':item.get('profile'),
        'key_width':item.get('key_width'),'stored_mask':item.get('stored_mask'),
        'mapping_source':item.get('mapping_source',''),'stable':item.get('stable'),
        'errors':item.get('errors',[]),'raw_records':0,'included_records':0,
        'import_status':'empty'} for pool,item in declared.items()}
    statuses={};skipped=Counter()
    for row in store.db.execute('SELECT pool,kind,profile,key_width,stored_mask,status,COUNT(*) AS n '
                                'FROM snapshot_records GROUP BY pool,kind,profile,key_width,stored_mask,status'):
        pool=row['pool'];status=row['status']
        if status=='included' and exclude_material and row['kind']=='material':status='material_excluded'
        item=pools.setdefault(pool,{'pool':pool,'mapping_source':'','stable':None,'errors':[],
                                   'raw_records':0,'included_records':0})
        item.update(kind=row['kind'] or None,profile_id=row['profile'] or None,
                    key_width=row['key_width'],stored_mask=row['stored_mask'])
        item['raw_records']+=row['n'];statuses.setdefault(pool,set()).add(status)
        if status!='included':skipped[status]+=row['n']
    keys_by_kind={}
    for row in targets:keys_by_kind.setdefault(row['kind'],set()).add(parse_hash(row['hash']))
    pool_keys={pool:set() for pool in pools};masks={}
    truncated=store.meta('target_truncated','0')=='1'
    comparison_mask=(1<<60)-1 if truncated else (1<<64)-1
    for row in store.db.execute("SELECT pool,raw_hash,kind,profile,stored_mask FROM snapshot_records WHERE status='included'"):
        if exclude_material and row['kind']=='material':continue
        mask_id=(row['profile'],row['stored_mask'])
        if mask_id not in masks:
            profile=PROFILES.get(row['profile'])
            if profile is None:raise ValueError('快照覆盖报告缺少原目标 profile，请重新导入快照')
            masks[mask_id]=profile.mask & int(row['stored_mask'],16) & comparison_mask
        key=parse_hash(row['raw_hash']) & masks[mask_id]
        if key not in keys_by_kind.get(row['kind'],()):
            skipped['target_not_imported']+=1
            statuses[row['pool']].add('target_not_imported')
            continue
        pools[row['pool']]['included_records']+=1
        pool_keys[row['pool']].add(key)
    for pool,item in pools.items():
        keys=pool_keys[pool]
        item.update(targets=len(keys),saluki_known=len(keys&known),unknown=len(keys-known),
                    import_status=next(iter(statuses[pool])) if len(statuses.get(pool,()))==1
                                  else 'mixed' if statuses.get(pool) else 'empty')
    return {'input_mode':'snapshot','snapshot_format':metadata.get('format'),
        'snapshot_game':metadata.get('game'),'snapshot_build':metadata.get('build'),
        'snapshot_fingerprint':store.meta('snapshot_fingerprint'),
        'complete':metadata.get('complete',False),'complete_scope':metadata.get('complete_scope',''),
        'verified_scope_pools':metadata.get('verified_scope_pools'),
        'loaded_scope':metadata.get('loaded_scope'),
        'whole_game_complete':False,'whole_snapshot_stable':metadata.get('whole_snapshot_stable'),
        'records':sum(item['raw_records'] for item in pools.values()),
        'included_records':sum(item['included_records'] for item in pools.values()),
        'unique_targets':len(targets),'skipped_records':dict(sorted(skipped.items())),
        'pools':[pools[pool] for pool in sorted(pools)],
        'scope':'low60 candidate Saluki comparison; full-key difference unproven' if truncated
                else 'full-key Saluki difference in current loaded snapshot set',
        'key_comparison':'low60-pending' if truncated else 'imported-profile-full-key',
        'formal_export_eligible':not truncated,
        'provenance':{'snapshot_file':store.meta('catalog_path'),'source_files':sources,
            'game_id':metadata.get('game_id'),'state_stable':metadata.get('state_stable'),
            'build_fingerprints':metadata.get('build_fingerprints')},
        'warnings':metadata.get('warnings',[]),
        'refresh':'snapshot, pool mapping and associated strings are fingerprinted on every run'}


def snapshot_coverage(store,indexes,exclude_material=True):
    targets=store.targets(exclude_material=exclude_material)
    hashes={parse_hash(row['hash']) for row in targets}
    known,sources=saluki_known_keys(indexes,hashes)
    kinds=Counter(row['kind'] for row in targets)
    known_kinds=Counter(row['kind'] for row in targets if parse_hash(row['hash']) in known)
    report={'catalog_sha256':store.meta('catalog_fingerprint'),'scope':'full-key Saluki difference',
        'unknown_keys':len(hashes-known),'known_keys':len(hashes&known),
        'types':[{'kind':k,'targets':v,'saluki_known':known_kinds[k],'unknown':v-known_kinds[k]}
                 for k,v in sorted(kinds.items(),key=lambda item:(-(item[1]-known_kinds[item[0]]),item[0]))],
        'saluki_sources':sources,'name_only_exclusions':'resolved after verified names exist',
        'refresh':'folder contents and dictionary contents are fingerprinted on every run'}
    if store.meta('input_mode')=='snapshot':
        report.update(_pool_coverage(store,targets,known,exclude_material))
    else:
        root=Path(store.meta('catalog_path'));pools=Counter()
        for row in store.db.execute('SELECT kind,hash,path FROM asset_files'):
            try:relative=Path(row['path']).relative_to(root)
            except ValueError:relative=Path(row['path']).name
            pool=str(relative.parent) if isinstance(relative,Path) else '.'
            # Export directories are provenance, not claimed engine pool IDs.
            pools[(row['kind'],pool)]+=1
        report['pools']=[{'kind':k,'export_directory':pool,'files':n} for (k,pool),n in sorted(pools.items())]
    return report
