"""Synthetic source-key vectors exercise recovery, not path-display assumptions."""
from pathlib import Path

import pytest

from finder.hashing import PROFILES, Profile
from finder.spellings import resolve_table_spelling


# Fixed synthetic FNV-1a vectors use the registered source seed and complete
# table mask. Every recovery below changes spelling before that comparison.
@pytest.mark.parametrize('table,key,display,original', [
    ('fnv1a_xsounds_v2', 0x01174ff141e57b27,
     'nf_fixture/dir.with.dots/audio_clip/lnn/75/48000/all',
     'nf_fixture/dir.with.dots/audio_clip.lnn.75.48000.all'),
    ('fnv1a_xsounds_v2', 0x01174ff141e57b27,
     r'nf_fixture/dir.with.dots/audio_clip\lnn/75\48000/all',
     'nf_fixture/dir.with.dots/audio_clip.lnn.75.48000.all'),
    ('fnv1a_xsounds_v2', 0x5271afe62cab00c1,
     'nf_fixture/prefix/audio.part.clip/ln2/100/44100/en_us',
     'nf_fixture/prefix/audio.part.clip.ln2.100.44100.en_us'),
    ('fnv1a_xsounds_v2', 0x1aa4877463c890d7,
     'nf_fixture/dir/audio_clip/lnn/75/48000/all',
     'nf_fixture.dir.audio_clip.lnn.75.48000.all'),
    ('fnv1a_xsounds', 0x12e4952d9bfd6931,
     'nf_fixture/prefix.with.dots/audio_clip/rn75/pc/en/snd',
     r'nf_fixture\prefix.with.dots\audio_clip.rn75.pc.en.snd'),
    ('fnv1a_english_xsounds', 0x1717800498e148d5,
     'nf_fixture/prefix/audio_clip/ln100/pc/snd',
     r'nf_fixture\prefix\audio_clip.ln100.pc.snd'),
    ('fnv1a_xsounds', 0x1b8e6cdebdb7fb93,
     'nf_fixture/prefix/audio_clip/rn75/pc/en/snd',
     'nf_fixture/prefix/audio_clip.rn75.pc.en.snd'),
])
def test_recovers_only_spelling_proven_by_source_key(table, key, display, original):
    assert display != original
    assert resolve_table_spelling(table, key, display) == original
    assert resolve_table_spelling(table, key ^ 1, display) is None


def test_original_case_and_literal_spelling_win():
    original = 'NF_fixture/Dir/Audio_CLIP.LNN.75.48000.ALL'
    assert resolve_table_spelling(Path('csv/fnv1a_xsounds_v2.csv'),
                                  '74a070f7a6208043', original) == original
    legacy = r'nf_fixture\prefix.with.dots\audio_clip.rn75.pc.en.snd'
    assert resolve_table_spelling('fnv1a_xsounds', 0x12e4952d9bfd6931, legacy) == legacy


def test_audio_recovery_never_applies_to_other_table_domains():
    original = 'nf_fixture/dir/audio_clip.lnn.75.48000.all'
    display = 'nf_fixture/dir/audio_clip/lnn/75/48000/all'
    assert resolve_table_spelling('fnv1a_ximages_v2', 0x74a070f7a6208043, display) is None
    assert resolve_table_spelling('fnv1a_ximages_v2', 0x74a070f7a6208043, original) == original


def test_full_width_alias_does_not_accept_low_63_bit_key():
    name, key = 'nf_fixture_alias_10', 0xc0d698f2c26e502c
    assert resolve_table_spelling('fnv1a_soundbanks_aliases_v2', key, name) == name
    assert resolve_table_spelling('fnv1a_soundbanks_aliases_v2', key & ((1 << 63) - 1), name) is None
    assert resolve_table_spelling('fnv1a_soundbanks_aliases', key, name) is None


@pytest.mark.parametrize('table', ['unknown.csv', 'bo2_ipak.csv', None])
def test_unknown_table_cannot_create_verified_spelling(table):
    assert resolve_table_spelling(table, 0x74a070f7a6208043,
                                  'nf_fixture/dir/audio_clip.lnn.75.48000.all') is None


@pytest.mark.parametrize('key', [-1, 1 << 64, True, 1.5, 'xyz', '12345678901234567'])
def test_rejects_malformed_keys(key):
    assert resolve_table_spelling('fnv1a_xsounds_v2', key, 'nf_fixture') is None


@pytest.mark.parametrize('name', ['', 'a\0b', 'a\rb', 'a\nb', '\ud800', 'a' * 1025, '汉' * 342])
def test_rejects_invalid_or_overlong_utf8_names(name):
    assert resolve_table_spelling('fnv1a_xsounds_v2', 0, name) is None


@pytest.mark.parametrize('name', ['a' * 1024, '汉' * 341])
def test_limit_counts_utf8_bytes_and_accepts_boundary(name):
    key = PROFILES['iw-resource63'].digest(name)
    assert resolve_table_spelling('fnv1a_xsounds_v2', key, name) == name


def test_variants_are_bounded_and_repeat_in_the_same_order(monkeypatch):
    calls = []
    digest = Profile.digest

    def record(profile, name):
        calls.append((profile.id, name))
        return digest(profile, name)

    monkeypatch.setattr(Profile, 'digest', record)
    display = 'nf_fixture/prefix.with.dots/audio_clip/rn75/pc/en/snd'
    assert resolve_table_spelling('fnv1a_xsounds', 0, display) is None
    first = list(calls)
    calls.clear()
    assert resolve_table_spelling('fnv1a_xsounds', 0, display) is None
    assert calls == first
    assert len({name for _, name in calls}) <= 24
    assert len(calls) <= 24 * 8  # Two declared source rules, case and old-mask variants.


@pytest.mark.parametrize('table,key,name', [
    ('fnv1a_ximages', 0x25a28967201206bb, 'nf_fixture_ui_icon_BPS1_058'),
    ('fnv1a_ximages', 0x05a28967201206bb, 'nf_fixture_ui_icon_BPS1_058'),
    ('fnv1a_xanims', 0x0c4b2ad0d36357ba, 'nf_fixture_legacy_animation'),
    ('fnv1a_xanims', 0x068178673f4e823a, 'NF_fixture_legacy_animation'),
])
def test_historical_case_and_60_bit_source_rows_never_change_target_profiles(table, key, name):
    before = PROFILES['fnv1a63'].json()
    assert resolve_table_spelling(table, key, name) == name
    assert resolve_table_spelling(table, key ^ 1, name) is None
    # A valid historical row remains vocabulary, not a current-target match.
    assert PROFILES['fnv1a63'].digest(name) != key
    assert PROFILES['fnv1a63'].json() == before


def test_historical_source_case_is_literal_and_modern_tables_keep_their_masks():
    name = 'nf_fixture_ui_icon_BPS1_058'
    assert resolve_table_spelling('fnv1a_ximages', 0x25a28967201206bb, name.lower()) is None
    # Modern resource tables do not inherit the old table's case/60-bit rules.
    assert resolve_table_spelling('fnv1a_ximages_v2', 0x25a28967201206bb, name) is None
    assert resolve_table_spelling('fnv1a_xanims_v2', 0x0c4b2ad0d36357ba,
                                  'nf_fixture_legacy_animation') is None
