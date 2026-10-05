"""Read-only estimates use real preparation, widths, and cached interval costs."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from finder.candidates import Plan
from finder.estimate import budgeted_cost,estimate
from finder.formats import encode_cdb
from finder.hashing import PROFILES
from finder.methods import SharedLedger,method_descriptor,plan_fingerprint
from finder.peeling import plan_cost
from finder.pipeline import Config,prepare
from finder.store import Store


def fixture_config(root,profile_id='iw-resource63',low60=False,asset_type='xanim',**kwargs):
    folder=root/'哈希文件';folder.mkdir()
    indexes=root/'复制索引';indexes.mkdir()
    profile=PROFILES[profile_id]
    names=['existing_animation','rex_mp_strafe_walk_1','rex_vm_misc_laser_pointer_fire']
    for name in names:
        key=profile.digest(name)&((1<<60)-1) if low60 else profile.digest(name)
        prefix='anim' if asset_type=='xanim' else asset_type
        (folder/f'{prefix}_{key:x}.cast').write_bytes(b'input fixture')
    (indexes/'fnv1a_xanims.cdb').write_bytes(encode_cdb({11:'existing_animation',12:'jup_mp_strafe_walk_1',13:'vm_misc_laser_pointer_fire'}))
    config=Config(str(folder),str(indexes),str(root/'output'),game='manual',profile=profile_id,
        backend='cpu',cross_asset=False,number_max=2,low60=low60,asset_type=asset_type,**kwargs)
    return config


def snapshot(root):
    return {str(file.relative_to(root)):(hashlib.sha256(file.read_bytes()).hexdigest(),file.stat().st_mtime_ns)
            for file in root.rglob('*') if file.is_file()}


def prepared_state(config,path):
    store=Store(path)
    state=prepare(config,store)
    return store,state


def test_exact_candidate_spaces_share_execution_preparation_and_budget(tmp_path):
    config=fixture_config(tmp_path,budget=7)
    store,state=prepared_state(config,tmp_path/'private-test-store.sqlite')
    try:
        expected=[(label,plan.total) for label,plan in state['plans']]
    finally:store.close()
    before=snapshot(tmp_path)
    result=estimate(config)
    assert [(row['label'],row['total']) for row in result['stages']]==expected
    assert result['candidate_total']==sum(total for _,total in expected)
    assert result['budgeted_candidates']==min(7,result['candidate_total'])
    assert sum(row['budgeted'] for row in result['stages'])==result['budgeted_candidates']
    assert result['budgeted_candidates_are_upper_bound'] is True
    assert result['benchmark']['sample_repetitions']==3
    assert result['benchmark']['duty_cycle']==0.75
    assert result['estimated_seconds_range'][0]<=result['estimated_compute_seconds']<=result['estimated_seconds_range'][1]
    assert snapshot(tmp_path)==before
    assert not Path(config.output).exists()


@pytest.mark.parametrize('profile_id,low60,bits',[('iw-resource63',False,63),('fnv1a64',False,64),
    ('fnv1a32',False,32),('iw-resource63',True,60),('fnv1a32',True,32)])
def test_effective_collision_widths_and_low60_pending_only(tmp_path,profile_id,low60,bits):
    config=fixture_config(tmp_path,profile_id,low60,budget=4)
    result=estimate(config)
    assert result['effective_bits']==bits
    assert result['target_count']==3
    assert result['collision_expectation']==pytest.approx(result['budgeted_candidates']*3/(1<<bits))
    assert result['low60_pending_only']==low60
    if low60 and bits==60:
        assert all(row['cost']['strategy']=='forward' for row in result['stages'])


def test_cache_is_read_only_and_reported_as_lower_bound(tmp_path):
    config=fixture_config(tmp_path,budget=1000)
    store,state=prepared_state(config,tmp_path/'fixture.sqlite')
    output=Path(config.output);output.mkdir()
    targets={config.profile:sorted({row['hash'] for row in store.targets(exclude_material=True,unknown_only=True)})}
    ledger=SharedLedger(output/'.namefinder-ledger.sqlite')
    first_total=state['plans'][0][1].total
    try:
        for index,(_,plan) in enumerate(state['plans'][:2]):
            fingerprint=plan_fingerprint(plan,profiles=[PROFILES[config.profile]],targets=targets,
                catalog_fingerprint=store.meta('catalog_fingerprint'),method=method_descriptor(plan.metadata),
                sources=state['sources']+state['extra_sources'],options={'keyword':'','low60':False,
                'kinds':[],'exclude_material':True,'domain':''})
            ledger.record_sweep(fingerprint,config.profile+':',0,plan.total if index==0 else 1)
    finally:
        ledger.close();store.close()
    before=snapshot(tmp_path)
    result=estimate(config)
    assert result['cached_candidates_lower_bound']>=first_total+1
    assert result['stages'][0]['budgeted']==0
    assert result['stages'][0]['cached']==first_total
    assert result['stages'][0]['budget_cost']['fixed_byte_operations']==0
    assert snapshot(tmp_path)==before


def test_budget_cost_charges_full_peeling_preparation_and_clipped_heads():
    profile=PROFILES['iw-resource63']
    plan=Plan([[f'rex_vm_ar_kilo2_{i:06d}_' for i in range(1000)],[f'inspect_{i}' for i in range(256)]])
    cost=plan_cost(plan,profile,3)
    assert cost['strategy']=='peeled' and cost['direction']=='reverse-target-table'
    one=budgeted_cost(cost,[(37,plan.total)],1)
    assert one['fixed_byte_operations']==cost['fixed_byte_operations']
    assert one['scan_byte_operations']==cost['prefix_mean_bytes']
    assert one['byte_operations']>cost['estimated_byte_operations']/plan.total
    clipped=budgeted_cost(cost,[(255,260),(511,518)],8)
    assert clipped['budgeted_candidates']==8
    assert clipped['nominal_chunks']==2
    assert clipped['scan_byte_operations']==4*cost['prefix_mean_bytes']
    assert budgeted_cost(cost,[(0,plan.total)],0)['byte_operations']==0


def test_budget_cost_forward_head_preparation_is_not_amortized():
    profile=PROFILES['fnv1a64']
    plan=Plan([['verified_long_prefix_'+str(i)+'_' for i in range(20)],[str(i) for i in range(2000)]])
    cost=plan_cost(plan,profile,1)
    assert cost['direction']=='forward-head-table'
    work=budgeted_cost(cost,[(0,plan.total)],3)
    assert work['fixed_byte_operations']==cost['fixed_byte_operations']
    assert work['scan_byte_operations']==3*cost['suffix_mean_bytes']


def test_unknown_cod2026_domain_requires_explicit_full_samples(tmp_path):
    config=fixture_config(tmp_path,'iw-dvar64',asset_type='dvar')
    config.game='COD2026';config.hash_domain='dvar'
    before=snapshot(tmp_path)
    with pytest.raises(ValueError,match='尚未证实'):estimate(config)
    config.allow_unverified_domain=True
    with pytest.raises(ValueError,match='至少3'):estimate(config)
    assert snapshot(tmp_path)==before
    assert not Path(config.output).exists()


def test_prior_verified_complete_targets_need_zero_search_budget(tmp_path):
    config=fixture_config(tmp_path,'iw-dvar64',asset_type='dvar')
    config.game='COD2026';config.hash_domain='dvar';config.allow_unverified_domain=True
    names=['existing_animation','rex_mp_strafe_walk_1','rex_vm_misc_laser_pointer_fire']
    dictionary=tmp_path/'private-full-samples.csv'
    dictionary.write_text(''.join(f'{PROFILES[config.profile].digest(name):016x},{name}\n' for name in names),encoding='utf-8')
    config.dictionary=str(dictionary)
    result=estimate(config)
    assert result['target_count']==0 and result['budgeted_candidates']==0
    assert result['estimated_compute_seconds']==0 and result['collision_expectation']==0
    assert not Path(config.output).exists()


def test_community_estimate_requires_cached_read_only_snapshot(tmp_path,monkeypatch):
    config=fixture_config(tmp_path)
    config.community=True
    import finder.community as community
    monkeypatch.setattr(community,'_response',lambda *_:pytest.fail('estimate must not request network'))
    before=snapshot(tmp_path)
    with pytest.raises(ValueError,match='community sync'):estimate(config)
    assert snapshot(tmp_path)==before
    cache=tmp_path/'community';folder=cache/'snapshots'/('a'*40)/'csv';folder.mkdir(parents=True)
    name='community_candidate_animation'
    file=folder/'fnv1a_xanims_v2.csv'
    file.write_text(f'{PROFILES[config.profile].digest(name):016x},{name}\n',encoding='utf-8')
    (cache/'current.json').write_text(json.dumps({'commit':'a'*40,'source':'echo000/cod-name-db',
        'files':[{'name':file.name,'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'bytes':file.stat().st_size}]}),encoding='utf-8')
    config.community_cache=str(cache)
    before=snapshot(tmp_path)
    assert estimate(config)['status']=='estimated'
    assert snapshot(tmp_path)==before
    config.community_refresh=True
    with pytest.raises(ValueError,match='community sync'):estimate(config)
    assert snapshot(tmp_path)==before


def test_cancelled_estimate_leaves_no_output(tmp_path):
    config=fixture_config(tmp_path)
    before=snapshot(tmp_path)
    result=estimate(config,control=lambda:'pause')
    assert result['status']=='stopped'
    assert snapshot(tmp_path)==before
    assert not Path(config.output).exists()
