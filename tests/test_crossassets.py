import pytest

from finder.crossassets import build_cross_asset_plans, MAX_CROSS_CANDIDATES, MAX_CROSS_PLANS


def generated(plans):
    return {plan.at(i) for _, plan in plans for i in range(plan.total)}


def signature(plans):
    return [(label, plan.slots, plan.metadata) for label, plan in plans]


def test_other_assets_replace_weapon_identity_in_real_animation_and_audio_forms():
    # Actual local grammar: rex_vm_ar_mike4_* and core/fly/.../wfoly_plr_ar_mike4_*.lnn.85.48000.all.
    source = ['wpn_rex_ar_alpha57_view', 'm/att_grip_ar_kilo2_v10',
              'weapon_ar_kilo2_normal&weapon_ar_kilo2_gloss~123456789']
    targets = {'xanim': ['rex_vm_ar_mike4_reload_empty'],
               'sndasset': ['core/fly/hybrid_scope/wfoly_plr_ar_mike4_hybrid_scope_side_off.lnn.85.48000.all']}
    plans = build_cross_asset_plans(source, targets, ['xanim', 'sndasset'])
    values = generated(plans)
    assert 'rex_vm_ar_alpha57_reload_empty' in values
    assert 'rex_vm_ar_kilo2_reload_empty' in values
    assert 'core/fly/hybrid_scope/wfoly_plr_ar_alpha57_hybrid_scope_side_off.lnn.85.48000.all' in values
    assert not any('123456789' in name for name in values)
    assert all(plan.metadata['generator'] == 'cross-asset-v1' for _, plan in plans)
    assert all(plan.metadata['source_names'] == 3 for _, plan in plans)
    assert all(plan.metadata['verification_required'] == 'complete-target-hash' for _, plan in plans)
    assert {plan.metadata['target_kinds'][0] for _, plan in plans} == {'xanim', 'sndasset'}


def test_material_and_image_code_inherit_class_from_target_templates():
    sources = ['m/att_grip_mike4_v9', 'att_ammo_556n_kilo2_v1_c&att_ammo_556n_kilo2_v1_s~789']
    templates = {'xanim': ['rex_vm_ar_mike4_reload', 'rex_vm_ar_kilo2_fire']}
    values = generated(build_cross_asset_plans(sources, templates, ['xanim']))
    assert 'rex_vm_ar_mike4_fire' in values
    assert 'rex_vm_ar_kilo2_reload' in values
    assert not any('v9' in name or '~789' in name for name in values)


def test_repeat_identifiers_remain_correlated_and_audio_separators_and_extensions_opaque():
    template = r'core\weapons\ar_mike4\wfoly_plr_ar_mike4_reload_01.lnn.85.48000.all'
    plans = build_cross_asset_plans(['wpn_iw9_ar_alpha57_view', 'wpn_iw9_ar_kilo2_view'],
                                  {'sndasset': [template]}, ['sndasset'], number_max=2)
    values = generated(plans)
    assert r'core\weapons\ar_alpha57\wfoly_plr_ar_alpha57_reload_01.lnn.85.48000.all' in values
    assert r'core\weapons\ar_alpha57\wfoly_plr_ar_alpha57_reload_02.lnn.85.48000.all' in values
    assert not any(r'ar_alpha57\wfoly_plr_ar_kilo2' in name for name in values)
    assert all(name.endswith('.lnn.85.48000.all') for name in values)
    assert not any('alpha02' in name or '.lnn.02.' in name for name in values)


def test_only_requested_animation_and_sound_types_get_plans():
    source = ['wpn_rex_ar_alpha57_view']
    templates = {'xanim': ['rex_vm_ar_mike4_reload'],
                 'soundbank': ['weapon_rex_ar_mike4_plr.all'],
                 'soundbanktransient': ['weapon_rex_ar_mike4_npc.all'],
                 'image': ['weapon_rex_ar_mike4_c']}
    assert build_cross_asset_plans(source, templates, ['image', 'material', 'weapon', 'animpkg']) == []
    bank_plans = build_cross_asset_plans(source, templates, ['soundbank', 'soundbanktransient'])
    assert generated(bank_plans) == {'weapon_rex_ar_alpha57_plr.all', 'weapon_rex_ar_alpha57_npc.all'}
    assert all(p.metadata['target_kinds'][0].startswith('soundbank') for _, p in bank_plans)


def test_model_names_are_clues_but_not_animation_audio_templates():
    plans = build_cross_asset_plans(['wpn_rex_ar_alpha57_view'],
                                  {'xanim': ['wpn_rex_ar_mike4_view'],
                                   'sndasset': ['wpn_rex_ar_mike4_view']}, ['xanim', 'sndasset'])
    values = generated(plans)
    assert 'rex_vm_ar_alpha57_reload_empty' in values
    assert not any(name.startswith('wpn_') for name in values)
    assert {p.metadata['rule'] for _, p in plans} == {'finite-animation-actions'}
    assert sum(p.total for _, p in plans) == 20


def test_no_readable_identity_and_no_hash_placeholder_pollution():
    placeholders = ['hash_0123456789abcdef', 'anim_123456789abcdef0.seanim',
                    'xanim_123456789abcdef0', 'sound_0123456789abcdef.wav',
                    'xsound_123456789abcdef0', 'sndbank_123456789abcdef0.json',
                    'animpkg_123456789abcdef0.bin', 'image_123456789abcdef0.dds',
                    'material_123456789abcdef0', 'model_123456789abcdef0', '0123456789abcdef']
    assert build_cross_asset_plans(placeholders, {'xanim': ['rex_vm_ar_mike4_reload']}, ['xanim']) == []
    assert build_cross_asset_plans(['prop_crate_blue', 'material_diffuse_col'], {}, ['xanim']) == []
    assert build_cross_asset_plans([], {}, ['xanim']) == []
    assert generated(build_cross_asset_plans(['wpn_rex_ar_alpha57_view', *placeholders],
                     {'xanim': ['rex_vm_ar_mike4_reload', *placeholders]}, ['xanim'])) == {'rex_vm_ar_alpha57_reload'}


def test_source_title_can_migrate_only_leading_observed_title():
    plans = build_cross_asset_plans(['wpn_rex_pi_kilo5_view'],
                                  {'xanim': ['iw9_vm_pi_papa320_reload_empty'],
                                   'sndasset': ['core/iw9/wpn_pi_papa320_reload.lnn.85.48000.all']},
                                  ['xanim', 'sndasset'])
    values = generated(plans)
    assert 'rex_vm_pi_kilo5_reload_empty' in values
    assert 'iw9_vm_pi_kilo5_reload_empty' in values
    assert 'core/iw9/wpn_pi_kilo5_reload.lnn.85.48000.all' in values
    assert not any(name.startswith('core/rex/') for name in values)


def test_equipment_object_identity_from_model_and_observed_templates():
    sources = ['wpn_t9_eqp_ascender_world', 'wpn_rex_eqp_bottle_world']
    plans = build_cross_asset_plans(sources,
                                  {'xanim': ['vm_ascender_raise'],
                                   'soundbank': ['eqp_rex_ascender.all']}, ['xanim', 'soundbank'])
    assert 'vm_bottle_raise' in generated(plans)
    assert 'eqp_rex_bottle.all' in generated(plans)
    assert not any('_world' in value for value in generated(plans))


def test_long_names_prune_only_invalid_length_and_unicode_is_utf8_valid():
    prefix = '目录/' + 'a' * 969 + '/wpn_ar_'
    template = prefix + 'mike4_reload.lnn.85.48000.all'
    assert len(template.encode('utf-8')) <= 1024
    plans = build_cross_asset_plans(['wpn_rex_ar_kilo2_view', 'wpn_rex_ar_alpha57longlonglong_view'],
                                  {'sndasset': [template]}, ['sndasset'])
    values = generated(plans)
    assert prefix + 'kilo2_reload.lnn.85.48000.all' in values
    assert all(len(value.encode('utf-8')) <= 1024 for value in values)
    assert not any('alpha57longlonglong' in value for value in values)


def test_large_observed_actions_stay_in_separate_small_slots():
    sources = ['wpn_rex_ar_alpha%d_view' % i for i in range(1000)]
    templates = {'xanim': ['rex_vm_ar_mike4_custom_action_%04d' % i for i in range(1000)]}
    plans = build_cross_asset_plans(sources, templates, ['xanim'], number_max=0)
    observed = [p for _, p in plans if p.metadata['rule'] == 'observed-identity']
    assert len(observed) == 1
    assert observed[0].total == 1_000_000
    assert sum(len(slot) for slot in observed[0].slots) == 2001
    assert observed[0].at(0) == 'rex_vm_ar_alpha0_custom_action_0000'
    assert observed[0].at(observed[0].total - 1) == 'rex_vm_ar_alpha999_custom_action_0999'


def test_deterministic_independent_of_corpus_and_type_order():
    sources = ['wpn_rex_ar_alpha57_view', 'wpn_iw9_pi_kilo5_view']
    templates = {'xanim': ['iw9_vm_pi_papa320_fire', 'rex_vm_ar_mike4_reload'],
                 'sndasset': ['weapons/wpn_pi_papa320_fire_01.qnn.85.48000.all']}
    assert signature(build_cross_asset_plans(sources, templates, ['xanim', 'sndasset'])) == signature(
        build_cross_asset_plans(reversed(sources), {k: list(reversed(v)) for k, v in templates.items()},
                                ['sndasset', 'xanim']))


def test_bounded_search_reports_omitted_combinations_and_prioritises_recent_templates():
    sources = ['wpn_rex_ar_alpha%d_view' % i for i in range(1000)]
    templates = {'xanim': ['rex_vm_ar_mike4_action_%04d' % i for i in range(10000)]}
    plans = build_cross_asset_plans(sources, templates, ['xanim'], number_max=0)
    total = sum(plan.total for _, plan in plans)
    assert total <= MAX_CROSS_CANDIDATES
    assert len(plans) <= MAX_CROSS_PLANS
    assert total < 10_000_000
    assert all(p.metadata['unbounded_cross_combinations_upper_bound'] == 10_000_000 for _, p in plans)
    assert all(p.metadata['emitted_cross_combinations'] == total for _, p in plans)
    assert all(p.metadata['omitted_cross_combinations_upper_bound'] == 10_000_000 - total for _, p in plans)
    assert any(p.metadata['plan_limited'] for _, p in plans)

    frames = {'xanim': ['path%04d/rex_vm_ar_mike4_fire' % i for i in range(1000)] +
                      ['iw9_vm_ar_mike4_fire']}
    many_plans = build_cross_asset_plans(sources, frames, ['xanim'])
    assert len(many_plans) <= MAX_CROSS_PLANS
    assert 'rex_vm_ar' in many_plans[0][1].at(0)
    assert all(p.metadata['bounded_search'] for _, p in many_plans)


@pytest.mark.parametrize('source', [None, 'path.txt', [''], ['\x00'], ['a\nb'], [12], ['\ud800'], ['a' * 1025]])
def test_invalid_source_inputs_fail_clearly(source):
    with pytest.raises(ValueError):
        build_cross_asset_plans(source, {}, ['xanim'])


@pytest.mark.parametrize('number_max', [True, -1, 1000, 1.5])
def test_numeric_limit_is_validated(number_max):
    with pytest.raises(ValueError):
        build_cross_asset_plans(['wpn_rex_ar_alpha57_view'], {}, ['xanim'], number_max=number_max)


@pytest.mark.parametrize('templates,kinds', [(None, ['xanim']), ({}, 'xanim'), ({}, None),
                                          ({}, [12]), ({'xanim': ['a\nb']}, ['xanim'])])
def test_template_and_type_inputs_are_validated(templates, kinds):
    with pytest.raises(ValueError):
        build_cross_asset_plans(['wpn_rex_ar_alpha57_view'], templates, kinds)
