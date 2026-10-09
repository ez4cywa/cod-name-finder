"""Typed observations stay hypotheses until the normal hash verifier runs."""
import pytest

from finder.typedplans import build_typed_plans


def expanded(plans):
    return {plan.at(index) for _, plan in plans for index in range(plan.total)}


def metadata(plans):
    return [plan.metadata for _, plan in plans]


def test_animation_core_relation_generates_a_new_alias_with_observed_take_only():
    sources = {'xanim': ['sat_vm_ar_alpha2_reload', 'rex_wm_ar_bravo3_reload']}
    target = {'soundbankalias': ['NPC_ar_alpha2_reload_07_02']}
    plans = build_typed_plans(sources, target, ['soundbankalias'])
    new_name = 'NPC_ar_bravo3_reload_07_02'
    assert new_name in expanded(plans)
    assert all(new_name not in names for names in [*sources.values(), *target.values()])
    assert 'NPC_ar_bravo3_reload_08_02' not in expanded(plans)
    assert 'NPC_ar_bravo3_reload_07_03' not in expanded(plans)
    assert all(row['target_kinds'] == ['soundbankalias'] for row in metadata(plans))
    assert all(row['candidate_only'] and row['verification_required'] == 'complete-target-hash'
               and row['generator'] == 'typed-observed-v1' for row in metadata(plans))


def test_bare_animation_core_and_no_take_are_used_only_when_observed():
    sources = {'xanim': ['vm_ar_alpha2_fire', 'wm_ar_bravo3_fire']}
    bare = build_typed_plans(sources, {'soundbankalias': ['ar_alpha2_fire']}, ['soundbankalias'])
    assert 'ar_bravo3_fire' in expanded(bare)
    assert 'npc_ar_bravo3_fire' not in expanded(bare)
    assert 'ar_bravo3_fire_01' not in expanded(bare)
    prefixed = build_typed_plans(sources, {'soundbankalias': ['npc_ar_alpha2_fire']}, ['soundbankalias'])
    assert 'npc_ar_bravo3_fire' in expanded(prefixed)
    assert 'ar_bravo3_fire' not in expanded(prefixed)


@pytest.mark.parametrize('target', ['npc_unrelated_reload_01', 'npc_ar_alpha2_fire_1000',
                                  'npc_ar_alpha2_fire_01.wav', 'npc_not_a_verified_core'])
def test_alias_without_measured_core_relation_has_no_rule(target):
    assert build_typed_plans({'xanim': ['sat_vm_ar_alpha2_fire']},
                             {'soundbankalias': [target]}, ['soundbankalias']) == []


def test_untyped_or_wrong_type_animation_sources_cannot_measure_alias_relationship():
    target = {'soundbankalias': ['npc_ar_alpha2_fire_01']}
    assert build_typed_plans({'image': ['sat_vm_ar_alpha2_fire']}, target, ['soundbankalias']) == []
    assert build_typed_plans({'xanim': ['sat_vm_ar_alpha2_fire']},
                             {'sndasset': target['soundbankalias']}, ['soundbankalias']) == []
    assert build_typed_plans({'xanim': ['sat_vm_ar_alpha2_fire']}, target, ['sndasset']) == []


def test_graphics_weapon_slots_keep_namespace_decorations_and_same_class():
    sources = {'xanim': ['rex_vm_ar_alpha2_fire', 'rex_vm_ar_bravo3_fire', 'sat_vm_br_charlie4_fire']}
    targets = {'image': ['UI/SAT_ar_alpha2_Icon_Diffuse'], 'material': ['Mtl/JUP_ar_alpha2_Chrome']}
    plans = build_typed_plans(sources, targets, ['image', 'material'])
    image = [item for item in plans if item[1].metadata['target_kinds'] == ['image']]
    material = [item for item in plans if item[1].metadata['target_kinds'] == ['material']]
    assert 'UI/SAT_ar_bravo3_Icon_Diffuse' in expanded(image)
    assert 'Mtl/JUP_ar_bravo3_Chrome' in expanded(material)
    assert all('br_charlie4' not in name and 'ar_charlie4' not in name for name in expanded(plans))
    assert 'Mtl/JUP_ar_bravo3_Chrome' not in expanded(image)
    assert 'UI/SAT_ar_bravo3_Icon_Diffuse' not in expanded(material)
    assert all(row['rule'] == 'typed-weapon-slot' and row['category'] == 'ar' for row in metadata(plans))


def test_every_verified_supported_source_type_can_supply_a_whole_weapon_identity():
    sources = {'image': ['hud_sat_ar_alpha2_icon'], 'material': ['m_jup_ar_bravo3_color'],
               'xanim': ['sat_vm_ar_charlie4_fire'], 'soundbankalias': ['npc_rex_ar_delta5_reload']}
    plans = build_typed_plans(sources, {'image': ['UI/ar_alpha2_icon']}, ['image'])
    assert expanded(plans) == {f'UI/ar_{code}_icon' for code in ('alpha2', 'bravo3', 'charlie4', 'delta5')}


def test_repeated_identity_is_one_correlated_choice_including_path_occurrences():
    sources = {'xanim': ['sat_vm_ar_alpha2_idle', 'rex_vm_ar_bravo3_idle']}
    template = 'UI/SAT_ar_alpha2/Icons_ar_alpha2_Diffuse'
    plans = build_typed_plans(sources, {'image': [template]}, ['image'])
    names = expanded(plans)
    assert 'UI/SAT_ar_bravo3/Icons_ar_bravo3_Diffuse' in names
    assert 'UI/SAT_ar_alpha2/Icons_ar_bravo3_Diffuse' not in names
    assert 'UI/SAT_ar_bravo3/Icons_ar_alpha2_Diffuse' not in names
    assert all(row['correlated_occurrences'] == 2 for row in metadata(plans))


@pytest.mark.parametrize('template', ['UI/notar_alpha2_icon', 'UI/ar_alpha2-extra_icon',
                                    'UI/ar_alpha2textureIcon', 'unrelated_image'])
def test_weapon_identifiers_require_whole_delimited_slots(template):
    sources = {'xanim': ['sat_vm_ar_alpha2_idle', 'sat_vm_ar_bravo3_idle']}
    assert build_typed_plans(sources, {'image': [template]}, ['image']) == []


def test_no_target_template_means_no_graphics_or_alias_rule():
    sources = {'xanim': ['sat_vm_ar_alpha2_idle', 'sat_vm_ar_bravo3_idle']}
    assert build_typed_plans(sources, {}, ['image', 'material', 'soundbankalias']) == []


def test_graphics_targets_cannot_unlock_unsupported_types_or_audio_templates():
    sources = {'xanim': ['sat_vm_ar_alpha2_fire', 'sat_vm_ar_bravo3_fire']}
    targets = {'image': ['UI/ar_alpha2_icon']}
    assert build_typed_plans(sources, targets, ['soundbankalias', 'xanim', 'sndasset']) == []


def test_budget_and_plan_limits_are_shared_across_rules_and_types_with_omission_metadata():
    sources = {'xanim': [f'sat_vm_ar_weapon{i}_fire' for i in range(30)]}
    targets = {'image': [f'UI/frame{i}_ar_weapon0_color' for i in range(20)],
               'material': [f'Mtl/frame{i}_ar_weapon0_color' for i in range(20)],
               'soundbankalias': ['npc_ar_weapon0_fire_01', 'plr_ar_weapon0_fire_02']}
    plans = build_typed_plans(sources, targets, ['material', 'soundbankalias', 'image'],
                              max_candidates=13, max_plans=5)
    emitted = sum(plan.total for _, plan in plans)
    assert 0 < emitted <= 13 and len(plans) <= 5
    assert {tuple(row['target_kinds']) for row in metadata(plans)} == {
        ('image',), ('material',), ('soundbankalias',)}
    for row in metadata(plans):
        assert row['emitted_combinations'] == emitted
        assert row['omitted_combinations_upper_bound'] == row['unbounded_combinations_upper_bound'] - emitted
        assert row['omitted_combinations_upper_bound'] > 0
        assert row['omitted_plan_count'] > 0 and row['bounded_search']


def test_default_hard_plan_limit_and_cancelled_generation_return_no_partial_set():
    sources = {'xanim': ['sat_vm_ar_alpha2_fire', 'sat_vm_ar_bravo3_fire']}
    targets = {'image': [f'UI/frame{i}_ar_alpha2_icon' for i in range(100)]}
    assert len(build_typed_plans(sources, targets, ['image'])) == 64
    assert build_typed_plans(sources, targets, ['image'], control=lambda: 'cancel') == []
    calls = 0

    def later_cancel():
        nonlocal calls
        calls += 1
        return 'run' if calls < 150 else 'stop'

    assert build_typed_plans(sources, targets, ['image'], control=later_cancel) == []
    assert calls == 150


def test_input_order_and_duplicates_do_not_change_plans_or_measurements():
    sources = {'xanim': ['sat_vm_ar_alpha2_fire', 'rex_vm_ar_bravo3_fire']}
    targets = {'image': ['UI/ar_alpha2_icon'], 'soundbankalias': ['npc_ar_alpha2_fire_01']}
    first = build_typed_plans(sources, targets, ['image', 'soundbankalias'])
    second = build_typed_plans({k: list(reversed(v)) * 2 for k, v in sources.items()},
                               {k: list(reversed(v)) * 2 for k, v in reversed(list(targets.items()))},
                               ['soundbankalias', 'image', 'image'])
    assert [(label, plan.slots, plan.metadata) for label, plan in first] == [
        (label, plan.slots, plan.metadata) for label, plan in second]


def test_utf8_name_limit_preserves_short_identity_without_overstating_plan_width():
    # A long donor is valid on its own but cannot fit this observed namespace.
    sources = {'image': ['ar_short', 'ar_' + 'x' * 1000]}
    target = '界' * 20 + '/ar_short_icon'
    plans = build_typed_plans(sources, {'image': [target]}, ['image'])
    assert expanded(plans) == {target}
    assert all(len(name.encode('utf-8')) <= 1024 for name in expanded(plans))


def test_alias_name_limit_keeps_valid_short_core_without_promoting_long_one():
    short_core = 'ar_alpha2_fire'
    long_core = 'ar_' + 'x' * 1008 + '_fire'
    sources = {'xanim': ['vm_' + short_core, 'vm_' + long_core]}
    prefix = 'NPC_' + 'x' * 30 + '_'
    target = prefix + short_core + '_01_02'
    plans = build_typed_plans(sources, {'soundbankalias': [target]}, ['soundbankalias'])
    assert target in expanded(plans)
    assert all(long_core not in name for name in expanded(plans))
    assert all(len(name.encode('utf-8')) <= 1024 for name in expanded(plans))


def test_default_candidate_limit_caps_large_observed_products():
    sources = {'xanim': [f'sat_vm_ar_weapon{i}_fire' for i in range(20_000)]}
    targets = {'image': [f'UI/frame{i}_ar_weapon0_color' for i in range(80)]}
    plans = build_typed_plans(sources, targets, ['image'])
    assert len(plans) == 64
    assert sum(plan.total for _, plan in plans) == 1_000_000
    assert plans[0][1].metadata['unbounded_combinations_upper_bound'] == 1_600_000
    assert plans[0][1].metadata['omitted_combinations_upper_bound'] == 600_000


@pytest.mark.parametrize('arguments', [
    {'source_names_by_kind': []}, {'target_names_by_kind': []}, {'target_kinds': 'image'},
    {'source_names_by_kind': {'xanim': 'vm_ar_alpha2_fire'}},
    {'source_names_by_kind': {'xanim': ['bad\nname']}},
    {'source_names_by_kind': {'xanim': ['x' * 1025]}},
    {'max_candidates': 0}, {'max_candidates': 1_000_001}, {'max_candidates': True},
    {'max_plans': 0}, {'max_plans': 65}, {'max_plans': True},
])
def test_invalid_inputs_cannot_silently_enlarge_or_relabel_the_search(arguments):
    kwargs = {'source_names_by_kind': {}, 'target_names_by_kind': {}, 'target_kinds': ['image']}
    kwargs.update(arguments)
    with pytest.raises(ValueError):
        build_typed_plans(**kwargs)
