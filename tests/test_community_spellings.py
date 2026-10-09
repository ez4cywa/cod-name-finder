"""Community provenance follows restored source spellings and complete table keys."""
import csv
import json
from pathlib import Path

from finder.community import import_community, iter_community


def _write(path, rows):
    with path.open('w', encoding='utf-8', newline='') as output:
        csv.writer(output).writerows((f'{key:x}', name) for key, name in rows)


def test_restored_modern_audio_is_verified_and_persisted(tmp_path):
    key = 0x01174ff141e57b27
    display = 'nf_fixture/dir.with.dots/audio_clip/lnn/75/48000/all'
    original = 'nf_fixture/dir.with.dots/audio_clip.lnn.75.48000.all'
    _write(tmp_path / 'fnv1a_xsounds_v2.csv', [(key, display)])
    row, = iter_community(tmp_path)
    assert (row.key, row.name, row.kind, row.profile, row.status) == (
        key, original, 'sndasset', 'iw-resource63', 'verified')
    result = import_community(tmp_path, output_dir=tmp_path / 'imported')
    assert result['counts'] == {'verified': 1, 'quarantined': 0, 'borrowed': 0}
    persisted = json.loads(Path(result['files']['verified']).read_text(encoding='utf-8'))
    assert persisted['key'] == key and persisted['name'] == original


def test_wrong_key_and_other_asset_type_keep_original_display_quarantined(tmp_path):
    display = 'nf_fixture/dir/audio_clip/lnn/75/48000/all'
    wrong = 0x74a070f7a6208042
    _write(tmp_path / 'fnv1a_xsounds_v2.csv', [(wrong, display)])
    _write(tmp_path / 'fnv1a_ximages_v2.csv', [(0x74a070f7a6208043, display)])
    rows = list(iter_community(tmp_path))
    assert len(rows) == 2
    assert all(row.name == display and row.status == 'quarantined'
               and row.profile is None and row.reason == 'name-hash-mismatch' for row in rows)
    assert {row.key for row in rows} == {wrong, 0x74a070f7a6208043}


def test_modern_alias_requires_complete_64_bit_source_key(tmp_path):
    name, key = 'nf_fixture_alias_10', 0xc0d698f2c26e502c
    low = key & ((1 << 63) - 1)
    _write(tmp_path / 'fnv1a_soundbanks_aliases_v2.csv', [(key, name), (low, name)])
    full, truncated = iter_community(tmp_path)
    assert (full.key, full.profile, full.status) == (key, 'fnv1a64', 'verified')
    assert truncated.key == low and truncated.name == name
    assert truncated.status == 'quarantined' and truncated.profile is None


def test_borrowed_mode_does_not_certify_or_rewrite_source_display(tmp_path):
    display = 'nf_fixture/dir.with.dots/audio_clip/lnn/75/48000/all'
    _write(tmp_path / 'fnv1a_xsounds_v2.csv', [
        (0x01174ff141e57b27, display), (0x01174ff141e57b26, display)])
    rows = list(iter_community(tmp_path, borrowed=True))
    assert len(rows) == 2
    assert all(row.status == 'borrowed' and row.profile is None
               and row.reason == 'candidate-only-cross-title' and row.name == display for row in rows)
    report = import_community(tmp_path, borrowed=True)
    assert report['counts'] == {'verified': 0, 'quarantined': 0, 'borrowed': 2}


def test_legacy_original_directories_use_declared_no_fold_alternate(tmp_path):
    display = 'nf_fixture/prefix.with.dots/audio_clip/rn75/pc/en/snd'
    original = r'nf_fixture\prefix.with.dots\audio_clip.rn75.pc.en.snd'
    _write(tmp_path / 'fnv1a_xsounds.csv', [(0x12e4952d9bfd6931, display)])
    row, = iter_community(tmp_path, selected_profile='fnv1a63-no-fold')
    assert row.status == 'verified' and row.name == original
    assert row.profile == 'fnv1a63-no-fold'
