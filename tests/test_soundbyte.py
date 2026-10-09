from dataclasses import replace

import pytest

from finder.hashing import PROFILES
from finder.soundbyte import build_final_byte_plans


TAIL = '.lnn.75.48000.all'


def values(plans):
    return {plan.at(i) for _, plan in plans for i in range(plan.total)}


@pytest.mark.parametrize('profile_id', ['iw-resource63', 'fnv1a63', 'fnv1a64', 'fnv1a63-no-fold'])
def test_recovers_new_basename_letter_with_target_observed_ending(profile_id):
    profile = PROFILES[profile_id]
    donor = r'rex\weapons\ar_kilo2\fire_a' + TAIL
    desired = r'rex\weapons\ar_kilo2\fire_b' + TAIL
    anchor = r'rex\weapons\ar_kilo2\reload_01' + TAIL
    plans, report = build_final_byte_plans([donor], [anchor], [profile.digest(desired)], profile)
    assert desired not in (donor, anchor)
    assert values(plans) == {desired}
    assert report['processed_target_tail_pairs'] == 1
    assert report['omitted_prefixes'] == 0
    assert report['preparation_byte_operations'] < 200
    assert plans[0][1].metadata['target_kinds'] == ['sndasset']


def test_low63_ring_handles_full_hash_with_top_bit_set():
    profile = PROFILES['iw-resource63']
    full = replace(profile, mask=(1 << 64) - 1)
    desired = next('rex/fire_' + chr(i) + TAIL for i in range(97, 123)
                   if full.digest('rex/fire_' + chr(i) + TAIL) >> 63)
    plans, _ = build_final_byte_plans(['rex/fire_0' + TAIL], ['rex/anchor' + TAIL],
                                     [profile.digest(desired)], profile)
    assert desired in values(plans)


def test_only_target_endings_are_used_and_unknown_keys_are_not_names():
    profile = PROFILES['iw-resource63']
    donor = 'rex/fire_a.lnn.85.44100.all'
    desired = 'rex/fire_b' + TAIL
    foreign = 'rex/fire_c.lnn.85.44100.all'
    plans, _ = build_final_byte_plans([donor], ['rex/anchor' + TAIL],
                                     [profile.digest(desired), profile.digest(foreign)], profile)
    assert values(plans) == {desired}


def test_literal_utf8_prefix_and_legacy_encoding_are_preserved():
    profile = PROFILES['fnv1a63-no-fold']
    tail = '.rn75.pc.en.snd'
    desired = '目录\\sound\\fire_b' + tail
    plans, _ = build_final_byte_plans(['目录\\sound\\fire_a' + tail],
                                     ['目录\\sound\\other_01' + tail], [profile.digest(desired)], profile)
    assert values(plans) == {desired}


def test_equivalent_source_case_prefixes_are_deduplicated_before_bucket_queries():
    profile=PROFILES['iw-resource63'];desired='rex/sound/fire_z'+TAIL
    plans,report=build_final_byte_plans(['rex/SOUND/fire_a'+TAIL,'REX/sound/fire_a'+TAIL,
        'rex/sound/fire_a'+TAIL],['rex/anchor'+TAIL],[profile.digest(desired)],profile)
    assert {profile.normalize(name) for name in values(plans)}=={desired}
    assert report['source_prefixes']==3 and report['normalized_source_prefixes']==1
    assert report['deduplicated_prefix_spellings']==2 and report['bucket_probes']==1
    assert report['preparation_work_units']==report['preparation_byte_operations']+1


@pytest.mark.parametrize('profile_id', ['bo6-script64', 'fnv1a60', 'fnv1a32', 'bo4-bocw-script32', 'sab-sdbm32'])
def test_other_domains_and_lost_bit_search_do_not_use_the_inverse(profile_id):
    profile = PROFILES[profile_id]
    plans, report = build_final_byte_plans([], [], [], profile)
    assert not plans and not report['enabled']


def test_preparation_bound_is_explicit_and_deterministic():
    profile = PROFILES['iw-resource63']
    sources = ['rex/source_' + str(i) + '_a' + TAIL for i in range(20)]
    targets = [profile.digest('rex/fire_b' + TAIL), profile.digest('rex/fire_c' + TAIL)]
    first = build_final_byte_plans(sources, ['rex/anchor' + TAIL], targets, profile,
                                   max_byte_operations=100, max_prefixes=2)
    second = build_final_byte_plans(reversed(sources), ['rex/anchor' + TAIL], reversed(targets), profile,
                                    max_byte_operations=100, max_prefixes=2)
    assert values(first[0]) == values(second[0]) and first[1] == second[1]
    assert first[1]['preparation_byte_operations'] <= 100
    assert first[1]['indexed_prefixes'] == 2
    assert first[1]['omitted_prefixes'] > 0
    assert first[1]['limit_reached']


def test_stop_discards_partial_candidate_plan():
    profile = PROFILES['iw-resource63']
    calls = 0

    def control():
        nonlocal calls
        calls += 1
        return 'run' if calls < 5 else 'stop'

    plans, report = build_final_byte_plans(['rex/fire_a' + TAIL], ['rex/anchor' + TAIL],
                                         [profile.digest('rex/fire_b' + TAIL)], profile, control=control)
    assert report['cancelled'] and plans == []


def test_stop_during_last_cpu_verification_discards_the_final_plan():
    profile=PROFILES['iw-resource63'];stopped=False

    class StopAtDigest:
        def __getattr__(self,key):return getattr(profile,key)
        def digest(self,name):
            nonlocal stopped
            stopped=True
            return profile.digest(name)

    desired='rex/fire_b'+TAIL
    plans,report=build_final_byte_plans(['rex/fire_a'+TAIL],['rex/anchor'+TAIL],
        [profile.digest(desired)],StopAtDigest(),control=lambda:'stop' if stopped else 'run')
    assert plans==[] and report['cancelled']


@pytest.mark.parametrize('bad', [True, 0, -1, 1.2])
def test_invalid_preparation_limit_is_rejected(bad):
    with pytest.raises(ValueError):
        build_final_byte_plans([], [], [], PROFILES['iw-resource63'], max_byte_operations=bad)


def test_unrecognized_codec_or_non_ascii_last_character_is_not_guessed():
    profile = PROFILES['iw-resource63']
    plans, report = build_final_byte_plans(['rex/fire_字' + TAIL, 'rex/file.wav'],
                                         ['rex/anchor' + TAIL], [1], profile)
    assert plans == [] and report['source_prefixes'] == 0
