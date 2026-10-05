"""A complete run reuses verified names without decoding/planning/hash scanning."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import zlib

import pytest

import finder.pipeline as pipeline
import finder.estimate as estimate_module
from finder.formats import decode_cdb,encode_cdb
from finder.hashing import PROFILES


def configured(root,*,low60=False,budget=500000):
    folder=root/'hashed';folder.mkdir()
    indexes=root/'indexes';indexes.mkdir()
    related=root/'related';related.mkdir()
    profile=PROFILES['iw-resource63'];old=PROFILES['fnv1a63']
    names=['existing_animation','rex_mp_strafe_walk_1','rex_vm_misc_laser_pointer_fire',
           'rex_cache_target_outside_current_candidate_families']
    for name in names:
        key=profile.digest(name)&((1<<60)-1) if low60 else profile.digest(name)
        (folder/f'anim_{key:016x}.cast').write_bytes(b'private asset fixture')
    previous=['existing_animation','jup_mp_strafe_walk_1','vm_misc_laser_pointer_fire']
    (indexes/'fnv1a_xanims.cdb').write_bytes(encode_cdb({old.digest(name):name for name in previous}))
    dictionary=root/'extra.txt';dictionary.write_text('supplemental_observed_unmatched_1\n',encoding='utf-8')
    borrowed=root/'borrowed.txt';borrowed.write_text('borrowed_observed_unmatched_1\n',encoding='utf-8')
    (related/'wpn_rex_ar_kilo2_view.cast').write_bytes(b'only its name is used')
    return pipeline.Config(str(folder),str(indexes),str(root/'output'),backend='cpu',cross_asset=True,
        related_folder=str(related),dictionary=str(dictionary),borrowed_dictionary=str(borrowed),
        number_max=2,low60=low60,budget=budget)


def snapshot(root):
    return {str(file.relative_to(root)):(hashlib.sha256(file.read_bytes()).hexdigest(),file.stat().st_mtime_ns)
            for file in root.rglob('*') if file.is_file()}


def exported(report):
    directory=Path(report['path'])
    cdb=decode_cdb((directory/'verified.cdb').read_bytes())
    csv=Path(report['new_names_csv']).read_bytes()
    merged={str(file.relative_to(Path(report['saluki_ready']))):file.read_bytes()
            for file in Path(report['saluki_ready']).rglob('*.cdb')} if report['saluki_ready'] else {}
    return cdb,csv,merged


def fail_replanning(*args,**kwargs):
    pytest.fail('complete cache secretly decoded/replanned/rescanned instead of revalidating evidence')


def forbid_planning(monkeypatch,*,estimate=False):
    for name in ('prepare','corpus_from_indexes','build_plans','build_cross_asset_plans','run_task','decode_cdb'):
        monkeypatch.setattr(pipeline,name,fail_replanning)
    if estimate:
        monkeypatch.setattr(estimate_module,'prepare',fail_replanning)
        monkeypatch.setattr(estimate_module,'CPU',fail_replanning)


def test_complete_run_fast_path_exports_identical_csv_cdb_and_preserves_old_indexes(tmp_path,monkeypatch):
    config=configured(tmp_path)
    initial_indexes=snapshot(Path(config.indexes))
    first=pipeline.run(config)
    assert first['status']=='completed' and first['entries']==2
    assert first['processed']>0 and not first['complete_cache_reused']
    expected=exported(first)
    forbid_planning(monkeypatch)
    second=pipeline.run(config)
    assert second['complete_cache_reused'] is True
    assert second['status']=='completed' and second['processed']==0
    assert second['skipped_candidates']==first['processed']+first['skipped_candidates']
    assert second['entries']==first['entries'] and second['excluded_existing']==first['excluded_existing']
    assert exported(second)==expected
    assert snapshot(Path(config.indexes))==initial_indexes
    assert second['saluki_live_verified'] is False


def test_completed_estimate_is_read_only_and_bypasses_candidate_preparation(tmp_path,monkeypatch):
    config=configured(tmp_path)
    first=pipeline.run(config)
    assert first['status']=='completed'
    before=snapshot(tmp_path)
    forbid_planning(monkeypatch,estimate=True)
    result=estimate_module.estimate(config)
    assert result['complete_cache_reused'] is True
    assert result['status']=='estimated' and result['budgeted_candidates']==0
    assert result['cached_candidates_lower_bound']==first['processed']+first['skipped_candidates']
    assert result['benchmark']['sample_candidates']==0
    assert result['estimated_compute_seconds']==0 and result['collision_expectation']==0
    assert snapshot(tmp_path)==before


@pytest.mark.parametrize('changed',['index','dictionary','borrowed','related_name','decoded_name','target','keyword','number_max'])
def test_semantic_source_and_option_changes_invalidate_complete_cache(tmp_path,monkeypatch,changed):
    config=configured(tmp_path)
    first=pipeline.run(config)
    assert first['status']=='completed'
    if changed=='index':
        path=Path(config.indexes)/'fnv1a_xanims.cdb'
        entries=decode_cdb(path.read_bytes());name='jup_cache_new_template_fire_1'
        entries[PROFILES['fnv1a63'].digest(name)]=name;path.write_bytes(encode_cdb(entries))
    elif changed in ('dictionary','borrowed'):
        path=Path(config.dictionary if changed=='dictionary' else config.borrowed_dictionary)
        path.write_text(path.read_text(encoding='utf-8')+'additional_semantic_candidate_2\n',encoding='utf-8')
    elif changed=='related_name':
        path=Path(config.related_folder)/'wpn_rex_ar_kilo2_view.cast'
        path.rename(path.with_name('wpn_rex_ar_alpha57_view.cast'))
    elif changed=='decoded_name':
        (Path(config.folder)/'rex_vm_ar_alpha57_named_clue.cast').write_bytes(b'decoded clue')
    elif changed=='target':
        key=PROFILES[config.profile].digest('a_genuinely_new_unresolved_target')
        (Path(config.folder)/f'anim_{key:016x}.cast').write_bytes(b'new target')
    elif changed=='keyword':config.keyword='laser'
    else:config.number_max+=1
    original=pipeline.prepare;called=[]
    def tracked(*args,**kwargs):
        called.append(True);return original(*args,**kwargs)
    monkeypatch.setattr(pipeline,'prepare',tracked)
    second=pipeline.run(config)
    assert second['complete_cache_reused'] is False
    assert called


def test_unrelated_asset_payload_and_execution_budget_do_not_change_name_semantics(tmp_path,monkeypatch):
    config=configured(tmp_path)
    first=pipeline.run(config)
    expected=exported(first)
    (Path(config.related_folder)/'wpn_rex_ar_kilo2_view.cast').write_bytes(b'different mesh bytes, identical clue name')
    next(Path(config.folder).glob('anim_*.cast')).write_bytes(b'different animation bytes, identical target key')
    config.budget=1;config.seconds=1
    forbid_planning(monkeypatch)
    second=pipeline.run(config)
    assert second['complete_cache_reused'] is True and second['processed']==0
    assert exported(second)==expected


def test_partial_budget_is_not_published_as_complete_cache(tmp_path,monkeypatch):
    config=configured(tmp_path,budget=1)
    first=pipeline.run(config)
    assert first['status']=='partial' and first['processed']==1
    original=pipeline.prepare;called=[]
    def tracked(*args,**kwargs):called.append(True);return original(*args,**kwargs)
    monkeypatch.setattr(pipeline,'prepare',tracked)
    config.budget=500000
    second=pipeline.run(config)
    assert second['complete_cache_reused'] is False and called
    assert second['status']=='completed' and second['entries']==2
    forbid_planning(monkeypatch)
    third=pipeline.run(config)
    assert third['complete_cache_reused'] is True
    assert exported(third)==exported(second)


def test_complete_low60_cache_restores_pending_candidates_and_never_formal_names(tmp_path,monkeypatch):
    config=configured(tmp_path,low60=True)
    first=pipeline.run(config)
    assert first['status']=='completed' and first['entries']==0
    assert first['pending_low60_candidates']>=2 and not first['full_keys']
    before=snapshot(tmp_path)
    forbid_planning(monkeypatch,estimate=True)
    quoted=estimate_module.estimate(config)
    assert quoted['complete_cache_reused'] is True and quoted['low60_pending_only'] is True
    assert quoted['effective_bits']==60 and quoted['budgeted_candidates']==0
    assert snapshot(tmp_path)==before
    second=pipeline.run(config)
    assert second['complete_cache_reused'] is True and second['processed']==0
    assert second['entries']==0 and not second['full_keys']
    assert second['pending_low60_candidates']==first['pending_low60_candidates']
    assert decode_cdb((Path(second['path'])/'verified.cdb').read_bytes())=={}
    assert Path(second['new_names_csv']).read_bytes()==b''
    pending=Path(second['run_dir'])/'pending-low60.csv'
    assert pending.is_file() and b'UNVERIFIED_LOW60' in pending.read_bytes()


def test_integrity_valid_but_hash_invalid_cache_record_is_rejected_before_export(tmp_path,monkeypatch):
    config=configured(tmp_path)
    first=pipeline.run(config);expected=exported(first)
    with closing(sqlite3.connect(first['ledger'])) as connection:
        key,compressed=connection.execute('SELECT key,payload FROM complete_runs').fetchone()
        record=json.loads(zlib.decompress(compressed))
        assert record['evidence']
        record['evidence'][0]['name']='poisoned_name_not_matching_cached_target'
        blob=json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
        # Recompute the transport SHA to exercise independent name verification,
        # rather than merely checking that damaged compressed bytes are ignored.
        with connection:
            connection.execute('UPDATE complete_runs SET payload=?,payload_sha256=? WHERE key=?',
                (zlib.compress(blob),hashlib.sha256(blob).hexdigest(),key))
    original=pipeline.prepare;called=[]
    def tracked(*args,**kwargs):called.append(True);return original(*args,**kwargs)
    monkeypatch.setattr(pipeline,'prepare',tracked)
    second=pipeline.run(config)
    assert not second['complete_cache_reused'] and called
    assert exported(second)==expected
    assert b'poisoned_name' not in Path(second['new_names_csv']).read_bytes()
