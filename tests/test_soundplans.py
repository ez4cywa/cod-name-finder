import pytest

from finder.hashing import PROFILES
from finder.soundplans import build_sound_plans, MAX_SOUND_CANDIDATES, MAX_SOUND_PLANS


def generated(plans):
    return {plan.at(i) for _, plan in plans for i in range(plan.total)}


def signature(plans):
    return [(label, plan.slots, plan.metadata) for label, plan in plans]


def test_repeated_namespace_generates_new_name_with_all_occurrences_correlated():
    donor = 'core/weapons/ar_mike4/ar_mike4/wfoly_plr_ar_mike4_reload_01.foreign.22050.all'
    target = 'core/weapons/ar_kilo2/wfoly_plr_ar_kilo2_fire_02.qnn.85.48000.all'
    plans = build_sound_plans([donor], [target], [])
    new = 'core/weapons/ar_kilo2/ar_kilo2/wfoly_plr_ar_kilo2_reload_01.qnn.85.48000.all'
    assert new in generated(plans)
    assert new not in (donor, target)
    # This is a candidate that could hit a new complete hash, not proof here.
    assert PROFILES['iw-resource63'].digest(new) not in {
        PROFILES['iw-resource63'].digest(donor), PROFILES['iw-resource63'].digest(target)}
    assert all('ar_mike4' not in value and '.foreign.' not in value for value in generated(plans))
    assert plans[0][1].metadata['repeated_occurrences'] == 3


def test_namespace_replacement_requires_directory_and_filename_whole_words():
    donor = 'core/ar_mike4/wfoly_ar_mike4x_fire_01.wav'
    target = 'core/ar_kilo2/wfoly_ar_kilo2_fire_01.qnn.85.48000.all'
    assert build_sound_plans([donor], [target], []) == []
    assert build_sound_plans(['core/ar_mike4/fire_01.wav'], [target], []) == []
    assert build_sound_plans(['ar_mike4_ar_mike4_01.wav'], [target], []) == []


def test_namespace_encoding_pairs_stay_bound_and_slash_spelling_is_untouched():
    donors = [r'core\ar_mike4\wfoly_plr_ar_mike4_reload_0007.ads.foreign']
    targets = [r'core\ar_kilo2\wfoly_plr_ar_kilo2_fire_01.qnn.85.48000.all',
               'core/ar_alpha57/wfoly_plr_ar_alpha57_fire_02.lnn.90.44100.pc']
    values = generated(build_sound_plans(donors, targets, []))
    assert r'core\ar_kilo2\wfoly_plr_ar_kilo2_reload_0007.qnn.85.48000.all' in values
    assert r'core\ar_alpha57\wfoly_plr_ar_alpha57_reload_0007.lnn.90.44100.pc' in values
    assert not any('/' in name or '.foreign' in name for name in values)
    assert not any('ar_kilo2' in name and '.lnn.' in name for name in values)
    assert not any('ar_alpha57' in name and '.qnn.' in name for name in values)


def test_nested_short_namespace_does_not_replace_partial_longer_identity():
    donor = 'weapons/ar_mike4/mike4/wfoly_ar_mike4_reload_01.wav'
    target = 'weapons/ar_kilo2/kilo2/wfoly_ar_kilo2_fire_01.qnn.85.48000.all'
    values = generated(build_sound_plans([donor], [target], []))
    assert values == {'weapons/ar_kilo2/mike4/wfoly_ar_kilo2_reload_01.qnn.85.48000.all'}
    assert not any('ar_ar_' in name for name in values)


def test_missing_alias_borrows_deepest_prefix_with_exact_target_tuples():
    targets = ['rex/wpn/fire/wpn_plr_ar_alpha_fire_001.qnn.85.48000.all',
               'rex/wpn/fire/wpn_plr_ar_alpha_fire_02.lnn.90.44100.pc',
               'rex/wpn/other/wpn_plr_sm_beta_fire_03.ogg']
    alias = 'wpn_plr_ar_alpha_reload'
    values = generated(build_sound_plans([], targets, [alias]))
    assert values == {
        'rex/wpn/fire/wpn_plr_ar_alpha_reload_001.qnn.85.48000.all',
        'rex/wpn/fire/wpn_plr_ar_alpha_reload_02.lnn.90.44100.pc'}
    assert not any('_001.lnn.' in name or '_02.qnn.' in name or '/other/' in name for name in values)
    plan = build_sound_plans([], targets, [alias])[0][1]
    assert plan.metadata['shared_prefix_tokens'] == 4
    assert plan.metadata['tuple_binding'] == 'directory+take+encoding'


def test_foreign_family_cannot_hide_missing_target_family_and_existing_target_is_skipped():
    alias = 'wpn_plr_ar_alpha_reload_09'
    target = r'rex\wpn\wpn_plr_ar_alpha_fire_003_ads.qnn.85.48000.all'
    foreign = 'foreign/wpn_plr_ar_alpha_reload_01.foreign_codec'
    values = generated(build_sound_plans([foreign], [target], [alias, 'wpn_plr_ar_alpha_fire']))
    assert values == {r'rex\wpn\wpn_plr_ar_alpha_reload_003_ads.qnn.85.48000.all'}
    assert not any('foreign' in value for value in values)


def test_aliases_need_three_shared_tokens_and_target_encoding_observations():
    targets = ['audio/wpn_plr_ar_alpha_fire_01.qnn.85.48000.all']
    assert build_sound_plans([], targets, ['wpn_plr_reload', 'wpn_npc_ar_alpha_reload']) == []
    assert build_sound_plans([], ['audio/wpn_plr_ar_alpha_fire_01'], ['wpn_plr_ar_alpha_reload']) == []
    assert build_sound_plans([], targets, ['audio/wpn_plr_ar_alpha_reload', 'wpn_plr_ar_alpha_reload.wav']) == []


def test_directory_take_and_encoding_never_cross_between_target_observations():
    targets = ['one/wpn_plr_ar_alpha_fire_01.qnn.85.48000.all',
               r'two\wpn_plr_ar_alpha_idle_002.lnn.90.44100.pc']
    values = generated(build_sound_plans([], targets, ['wpn_plr_ar_alpha_reload']))
    assert values == {'one/wpn_plr_ar_alpha_reload_01.qnn.85.48000.all',
                      r'two\wpn_plr_ar_alpha_reload_002.lnn.90.44100.pc'}


def test_order_duplicates_and_input_iterators_do_not_change_output():
    donors = ['core/ar_mike4/wpn_ar_mike4_reload_01.wav',
              'core/ar_alpha57/wpn_ar_alpha57_raise_01.wav']
    targets = ['core/ar_kilo2/wpn_ar_kilo2_fire_02.qnn.85.48000.all',
               'audio/wpn_plr_ar_alpha_fire_03.wav']
    aliases = ['wpn_plr_ar_alpha_reload', 'wpn_plr_ar_alpha_inspect']
    assert signature(build_sound_plans(donors, targets, aliases)) == signature(
        build_sound_plans(reversed(donors + donors), reversed(targets), reversed(aliases)))


def test_budget_and_plan_limits_report_omitted_upper_bound():
    targets = ['dir%02d/wpn_plr_ar_alpha_fire_%02d.wav' % (i, i) for i in range(8)]
    aliases = ['wpn_plr_ar_alpha_action%03d' % i for i in range(20)]
    plans = build_sound_plans([], targets, aliases, max_candidates=23, max_plans=2)
    assert len(plans) == 2
    assert sum(plan.total for _, plan in plans) == 23
    assert plans[1][1].total == 3
    for _, plan in plans:
        assert plan.metadata['unbounded_sound_combinations_upper_bound'] == 160
        assert plan.metadata['emitted_sound_combinations'] == 23
        assert plan.metadata['omitted_sound_combinations_upper_bound'] == 137
        assert plan.metadata['max_candidates'] == 23
    assert plans[1][1].metadata['plan_limited']
    assert build_sound_plans([], targets, aliases, max_candidates=0) == []
    assert build_sound_plans([], targets, aliases, max_plans=0) == []
    capped = build_sound_plans([], targets, aliases, max_candidates=10**30, max_plans=10**30)
    assert all(plan.metadata['max_candidates'] == MAX_SOUND_CANDIDATES and
               plan.metadata['max_plans'] == MAX_SOUND_PLANS for _, plan in capped)


def test_large_alias_observation_product_is_not_materialized_before_small_budget():
    targets = ['dir%04d/wpn_plr_ar_alpha_fire_001.qnn.85.48000.all' % i for i in range(1000)]
    aliases = ['wpn_plr_ar_alpha_action%04d' % i for i in range(1000)]
    plans = build_sound_plans([], targets, aliases, max_candidates=7)
    assert len(plans) == 1 and plans[0][1].total == 7
    assert sum(len(slot) for slot in plans[0][1].slots) == 9
    assert plans[0][1].metadata['unbounded_sound_combinations_upper_bound'] == 1_000_000
    assert plans[0][1].metadata['omitted_sound_combinations_upper_bound'] == 999_993


def test_repeated_namespace_product_obeys_same_shared_budget_and_bounds():
    donors = ['core/ar_old%02d/wpn_ar_old%02d_reload_take%02d_01.wav' % (i, i, i) for i in range(20)]
    targets = ['core/ar_new%02d/wpn_ar_new%02d_fire_02.qnn.85.48000.all' % (i, i) for i in range(30)]
    plans = build_sound_plans(donors, targets, [], max_candidates=31, max_plans=2)
    assert len(plans) == 2 and sum(plan.total for _, plan in plans) == 31
    assert len(generated(plans)) == 31
    assert all(plan.metadata['unbounded_sound_combinations_upper_bound'] == 600 for _, plan in plans)
    assert all(plan.metadata['omitted_sound_combinations_upper_bound'] == 569 for _, plan in plans)
    assert plans[-1][1].metadata['plan_limited']


def test_identical_donor_frames_are_coalesced_before_the_search_budget_is_spent():
    donors = ['core/ar_old%02d/wpn_ar_old%02d_reload_01.wav' % (i, i) for i in range(20)]
    target = 'core/ar_new/wpn_ar_new_fire_02.qnn.85.48000.all'
    plans = build_sound_plans(donors, [target], [])
    assert len(plans) == 1 and plans[0][1].total == 1
    assert generated(plans) == {'core/ar_new/wpn_ar_new_reload_01.qnn.85.48000.all'}
    assert plans[0][1].metadata['unbounded_sound_combinations_upper_bound'] == 1


def test_many_alias_groups_leave_a_quarter_of_default_plan_slots_for_namespaces():
    targets = ['dir%03d/wpn_plr_ar_alpha_fire_01.qnn.85.48000.all' % i for i in range(160)]
    targets.append('core/ar_kilo2/wpn_ar_kilo2_fire_01.qnn.85.48000.all')
    donors = ['core/ar_mike4/wpn_ar_mike4_reload_action%02d_01.wav' % i for i in range(40)]
    aliases = ['wpn_plr_ar_alpha_reload', 'wpn_plr_ar_alpha_inspect']
    plans = build_sound_plans(donors, targets, aliases)
    report = plans[0][1].metadata
    assert len(plans) == 128
    assert report['emitted_plans_by_rule'] == {'alias-missing-family': 96, 'repeated-namespace': 32}
    assert report['reserved_namespace_plans'] == 32
    assert plans[0][1].metadata['rule'] == 'alias-missing-family'
    assert report['unbounded_sound_combinations_upper_bound'] == 360
    assert report['emitted_sound_combinations'] == 224
    assert report['omitted_sound_combinations_upper_bound'] == 136
    assert sum(plan.total for _, plan in plans) == len(generated(plans)) == 224


def test_candidate_reservation_preserves_namespace_when_alias_family_alone_fills_budget():
    targets = ['d/wpn_plr_ar_alpha_fire_01.wav', 'core/ar_kilo2/wpn_ar_kilo2_fire_01.wav']
    donors = ['core/ar_mike4/wpn_ar_mike4_reload_action%02d_01.wav' % i for i in range(8)]
    aliases = ['wpn_plr_ar_alpha_action%02d' % i for i in range(20)]
    plans = build_sound_plans(donors, targets, aliases, max_candidates=8, max_plans=8)
    report = plans[0][1].metadata
    assert report['reserved_namespace_candidates'] == 2
    assert report['reserved_namespace_plans'] == 2
    assert report['emitted_candidates_by_rule'] == {'alias-missing-family': 6, 'repeated-namespace': 2}
    assert sum(plan.total for _, plan in plans) == len(generated(plans)) == 8
    assert report['unbounded_sound_combinations_upper_bound'] == 28
    assert report['omitted_sound_combinations_upper_bound'] == 20


def test_unused_namespace_reservation_returns_to_alias_without_repeating_partial_family():
    targets = ['d/wpn_plr_ar_alpha_fire_01.wav', 'core/ar_kilo2/wpn_ar_kilo2_reload_01.wav']
    donors = ['core/ar_mike4/wpn_ar_mike4_reload_01.wav']
    aliases = ['wpn_plr_ar_alpha_action%02d' % i for i in range(20)]
    # The sole namespace candidate is already target-held and is skipped.
    plans = build_sound_plans(donors, targets, aliases, max_candidates=10, max_plans=4)
    report = plans[0][1].metadata
    assert report['reserved_namespace_candidates'] == report['reserved_namespace_plans'] == 1
    assert report['emitted_candidates_by_rule'] == {'alias-missing-family': 10}
    assert sum(plan.total for _, plan in plans) == len(generated(plans)) == 10
    assert report['unbounded_sound_combinations_upper_bound'] == 21
    assert report['omitted_sound_combinations_upper_bound'] == 11


def test_single_method_uses_full_quota_and_tiny_shared_budget_is_alias_first():
    alias_target = 'd/wpn_plr_ar_alpha_fire_01.wav'
    namespace_target = 'core/ar_kilo2/wpn_ar_kilo2_fire_01.wav'
    donors = ['core/ar_mike4/wpn_ar_mike4_reload_action%02d_01.wav' % i for i in range(8)]
    aliases = ['wpn_plr_ar_alpha_action%02d' % i for i in range(20)]
    alias_only = build_sound_plans([], [alias_target], aliases, max_candidates=8, max_plans=1)
    assert len(alias_only) == 1 and alias_only[0][1].total == 8
    assert alias_only[0][1].metadata['reserved_namespace_plans'] == 0
    namespace_only = build_sound_plans(donors, [namespace_target], [], max_candidates=8, max_plans=8)
    assert sum(plan.total for _, plan in namespace_only) == 8
    assert namespace_only[0][1].metadata['reserved_namespace_candidates'] == 0
    tiny = build_sound_plans(donors, [alias_target, namespace_target], aliases,
                             max_candidates=8, max_plans=1)
    assert len(tiny) == 1 and tiny[0][1].total == 8
    assert tiny[0][1].metadata['rule'] == 'alias-missing-family'
    assert tiny[0][1].metadata['reserved_namespace_plans'] == 0


def test_cancel_discards_partial_preparation_and_partial_plans():
    targets = ['dir%02d/wpn_plr_ar_alpha_fire_01.wav' % i for i in range(20)]
    aliases = ['wpn_plr_ar_alpha_action%02d' % i for i in range(20)]
    for threshold in (1, 25, 70, 100, 200):
        count = 0
        def control():
            nonlocal count
            count += 1
            return 'cancel' if count >= threshold else 'run'
        assert build_sound_plans([], targets, aliases, control=control) == []
        assert count == threshold


def test_utf8_width_pruning_keeps_short_valid_aliases_without_truncating_strings():
    directory = '目录/' + 'a' * 940 + '/'
    target = directory + 'wpn_plr_ar_alpha_fire_01.qnn.85.48000.all'
    assert len(target.encode('utf-8')) <= 1024
    aliases = ['wpn_plr_ar_alpha_idle', 'wpn_plr_ar_alpha_' + 'z' * 70]
    values = generated(build_sound_plans([], [target], aliases))
    assert values == {directory + 'wpn_plr_ar_alpha_idle_01.qnn.85.48000.all'}
    assert all(len(value.encode('utf-8')) <= 1024 for value in values)


@pytest.mark.parametrize('bad', [None, 'dictionary.txt', [''], [' '], [1], ['a\n'], ['a\x00b'], ['\ud800'], ['a' * 1025]])
@pytest.mark.parametrize('position', [0, 1, 2])
def test_invalid_inputs_have_clear_errors(bad, position):
    values = [[], [], []]
    values[position] = bad
    with pytest.raises(ValueError):
        build_sound_plans(*values)


@pytest.mark.parametrize('field', ['max_candidates', 'max_plans'])
@pytest.mark.parametrize('bad', [True, -1, 1.5, '2', None])
def test_invalid_limits_are_rejected(field, bad):
    with pytest.raises(ValueError):
        build_sound_plans([], [], [], **{field: bad})


def test_metadata_names_only_sound_candidates_and_never_evidence():
    plans = build_sound_plans([], ['d/wpn_plr_ar_alpha_fire_01.wav'], ['wpn_plr_ar_alpha_reload'])
    assert plans
    for _, plan in plans:
        assert plan.metadata['generator'] == 'sound-observed-v1'
        assert plan.metadata['target_kinds'] == ['sndasset']
        assert plan.metadata['candidate_only'] is True
        assert plan.metadata['verification_required'] == 'complete-target-hash'
