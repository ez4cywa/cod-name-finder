import pytest

from finder.autoplans import build_plans
from finder.hashing import PROFILES


def generated(plans):
    return {plan.at(i) for _, plan in plans for i in range(plan.total)}


def rule(plans, value):
    return [plan for _, plan in plans if plan.metadata['rule'] == value]


def test_local_animation_rules_recover_real_audit_examples():
    corpus = ['iw9_mp_strafe_walk_8', 'vm_ascender_raise', 'rex_vm_pi_kilo5_fire']
    plans = build_plans(corpus, number_max=2)
    found = generated(plans)
    # Three complete hashes observed in the user's exported animation set.
    expected = {
        'rex_mp_strafe_walk_8': 0x7a28575b1c9c0146,
        'rex_vm_ascender_raise': 0x7742df9821c3b61e,
        'rex_wm_pi_kilo5_fire': 0x0252320427346808,
    }
    assert expected.keys() <= found
    for name, target in expected.items():
        assert PROFILES['iw-resource63'].digest(name) == target
    assert set(corpus) <= found
    assert 'iw9_mp_strafe_walk_0' in found
    assert 'rex_vm_pi_kilo0_fire' not in found
    assert len(rule(plans, 'title-root')) == 1
    assert rule(plans, 'title-root')[0].slots == [
        ['rex_', 'mw4_', 'iw10_', 'iw11_'], ['mp_strafe_walk_8', 'vm_pi_kilo5_fire']]


def test_numbers_preserve_actual_paths_case_and_internal_suffixes():
    name = r'weapons\Mike4\Fire_01_ads.qnn.85.48000.all'
    plans = build_plans([name], 'sndasset', number_max=3)
    found = generated(plans)
    assert name in found
    assert r'weapons\Mike4\Fire_03_ads.qnn.85.48000.all' in found
    assert not any('Mike0' in n or '.qnn.03.' in n for n in found)
    assert not rule(plans, 'generic-animation-root')
    assert not rule(plans, 'weapon-view')


def test_order_is_deterministic_and_keyword_selects_source_family():
    names = ['vm_ascender_raise', 'jup_mp_foo_02', 'jup_mp_foo_02', 'sat_mp_bar_01']
    forward = build_plans(names, keyword='FOO', number_max=1)
    backward = build_plans(reversed(names), keyword='FOO', number_max=1)
    assert [(label, p.slots, p.metadata) for label, p in forward] == [
        (label, p.slots, p.metadata) for label, p in backward]
    assert rule(forward, 'literal')[0].slots == [['jup_mp_foo_02']]
    assert 'jup_mp_foo_01' in generated(forward)
    assert not any('bar' in n or 'ascender' in n for n in generated(forward))
    # A number-containing query selects the family rather than removing variants.
    assert 'jup_mp_foo_01' in generated(build_plans(names, keyword='foo_02', number_max=1))


def test_large_numeric_product_stays_in_small_mixed_radix_slots():
    corpus = ['custom_action_%04d_take_001' % i for i in range(1000)]
    plans = build_plans(corpus, 'sndasset', number_max=999)
    numbers = rule(plans, 'final-number')[0]
    assert numbers.total == 1_000_000
    assert sum(len(slot) for slot in numbers.slots) == 2001
    assert numbers.at(0) == 'custom_action_0000_take_000'
    assert numbers.at(numbers.total - 1) == 'custom_action_0999_take_999'
    # No known-unsuccessful pNN Cartesian family is generated.
    vm = build_plans(['vm_p24_pi_golf17_reload'])
    assert sum(p.total for _, p in vm) == 5
    assert not any('p00' in n or 'p99' in n for n in generated(vm))


def test_near_maximum_length_keeps_original_without_invalid_expansion():
    original = 'vm_' + 'a' * 1021
    plans = build_plans([original])
    assert generated(plans) == {original}
    numeric = 'a' * 1022 + '_9'
    # Widening a one-digit field must not exceed the Plan byte limit.
    plans = build_plans([numeric], number_max=999)
    assert generated(plans) == {'a' * 1022 + '_' + str(i) for i in range(10)}
    # The shorter valid roots remain available at the byte boundary.
    short_root_only = 'vm_' + 'a' * 1017
    plans = build_plans([short_root_only])
    assert generated(plans) == {short_root_only, 'rex_' + short_root_only, 'mw4_' + short_root_only}


@pytest.mark.parametrize('names', [[], None, 'dictionary.txt', [''], ['  '], ['a\nb'], ['a\x00b'], [12], ['a' * 1025], ['\ud800']])
def test_invalid_or_missing_local_corpus_has_clear_error(names):
    with pytest.raises(ValueError):
        build_plans(names)


@pytest.mark.parametrize('options', [
    {'asset_type': ''}, {'asset_type': 12}, {'asset_type': 'xanim\n'},
    {'keyword': 12}, {'keyword': 'a\nb'}, {'number_max': True},
    {'number_max': -1}, {'number_max': 1000}, {'number_max': 2.5},
])
def test_invalid_configuration_is_rejected(options):
    with pytest.raises(ValueError):
        build_plans(['name'], **options)


def test_unmatched_keyword_is_not_an_empty_background_task():
    with pytest.raises(ValueError, match='关键词'):
        build_plans(['vm_ascender_raise'], keyword='missing')


@pytest.mark.parametrize('asset_type', ['anim', 'animation', 'animations', 'all', 'auto'])
def test_animation_type_aliases(asset_type):
    assert rule(build_plans(['vm_ascender_raise'], asset_type), 'generic-animation-root')
