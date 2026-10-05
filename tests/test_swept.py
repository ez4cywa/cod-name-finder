from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3

import pytest

from finder.exporter import export
from finder.formats import decode_cdb
from finder.hashing import PROFILES
from finder.methods import SharedLedger, method_descriptor
from finder.store import Store


def evidence(name='rex_vm_ar_mike4_fire',partial=False):
    profile=PROFILES['iw-resource63'];descriptor=method_descriptor({'generator':'local-observed-v1','rule':'literal'})
    mask=(1<<60)-1 if partial else profile.mask
    return {'hash':f'{profile.digest(name)&mask:016x}','name':name,'profile':profile.id,
            'source':'first-task','source_game':'COD2026','method':'partial_match' if partial else 'discovered',
            'details':{'target_profile':profile.json(),'target_truncated':partial},
            **{key:descriptor[key] for key in ('method_id','method_version','generator_sha')},
            'profile_id':profile.id,'mask_used':mask}


def target_store(tmp_path,hit):
    folder=tmp_path/'assets';folder.mkdir(exist_ok=True)
    (folder/('anim_'+hit['hash']+'.cast')).write_bytes(b'x')
    store=Store(tmp_path/'work.sqlite')
    store.import_exported(folder,'COD2026','iw-resource63',default_kind='xanim',
                          truncated=hit['method']=='partial_match')
    return store


def test_sweep_half_open_merge_and_remaining(tmp_path):
    with SharedLedger(tmp_path/'ledger.sqlite') as ledger:
        assert ledger.remaining('plan','scope',0,100)==[(0,100)]
        ledger.record_sweep('plan','scope',20,30)
        ledger.record_sweep('plan','scope',40,50)
        assert ledger.remaining('plan','scope',0,60)==[(0,20),(30,40),(50,60)]
        ledger.record_sweep('plan','scope',30,40)
        ledger.record_sweep('plan','scope',12,23)
        assert list(map(tuple,ledger.db.execute('SELECT begin_index,end_index FROM swept')))==[(12,50)]
        assert ledger.remaining('plan','scope',15,45)==[]
        assert ledger.remaining('plan','other',0,60)==[(0,60)]
        assert ledger.remaining('other','scope',0,60)==[(0,60)]
        assert ledger.remaining('plan','scope',0,0)==[]
        with pytest.raises(ValueError):ledger.record_sweep('plan','scope',3,3)


def test_cached_hits_restore_full_export_in_new_run_and_no_duplicate(tmp_path):
    hit=evidence()
    with SharedLedger(tmp_path/'ledger.sqlite') as ledger:
        ledger.record_sweep('plan','iw-resource63:xanim',0,100,hits=[hit])
    # Separate invocation reopens the ledger; a fully skipped sweep still exports names.
    with SharedLedger(tmp_path/'ledger.sqlite') as ledger:
        assert ledger.remaining('plan','iw-resource63:xanim',0,100)==[]
        store=target_store(tmp_path,hit)
        restored=ledger.restore_hits('plan','iw-resource63:xanim',store)
        assert restored=={'inserted':1,'verified':1,'pending_low60':0,'total':1}
        assert ledger.restore_hits('plan','iw-resource63:xanim',store)['inserted']==0
        result=export(store,tmp_path/'output')
        assert decode_cdb((Path(result['path'])/'verified.cdb').read_bytes())=={int(hit['hash'],16):hit['name']}
        row=json.loads((Path(result['path'])/'evidence.jsonl').read_text(encoding='utf-8').strip())
        assert row['generator_sha']==hit['generator_sha']
        assert row['method_id']=='autoplans.literal'
        store.close()


def test_low60_cached_names_never_become_formal(tmp_path):
    hit=evidence(partial=True)
    with SharedLedger(tmp_path/'ledger.sqlite') as ledger:
        ledger.record_sweep('plan','scope',0,1,hits=[hit])
        store=target_store(tmp_path,hit)
        assert ledger.restore_hits('plan','scope',store)['pending_low60']==1
        result=export(store,tmp_path/'output',allow_empty=True)
        assert result['entries']==0 and decode_cdb((Path(result['path'])/'verified.cdb').read_bytes())=={}
        assert store.db.execute('SELECT method FROM evidence').fetchone()[0]=='partial_match'
        store.close()


def test_invalid_cached_hit_cannot_mark_sweep_completed(tmp_path):
    hit=evidence();hit['hash']='0000000000000001'
    with SharedLedger(tmp_path/'ledger.sqlite') as ledger:
        with pytest.raises(ValueError,match='独立 Python 回算'):
            ledger.record_sweep('plan','scope',0,100,hits=[hit])
        assert ledger.remaining('plan','scope',0,100)==[(0,100)]
        assert ledger.db.execute('SELECT COUNT(*) FROM sweep_hits').fetchone()[0]==0


def test_hit_and_sweep_are_one_transaction(tmp_path):
    with SharedLedger(tmp_path/'ledger.sqlite') as ledger:
        ledger.db.execute("CREATE TRIGGER abort_sweep BEFORE INSERT ON swept BEGIN SELECT RAISE(ABORT,'injected interruption'); END")
        with pytest.raises(sqlite3.IntegrityError,match='injected interruption'):
            ledger.record_sweep('plan','scope',0,100,hits=[evidence()])
        assert ledger.db.execute('SELECT COUNT(*) FROM sweep_hits').fetchone()[0]==0
        assert ledger.remaining('plan','scope',0,100)==[(0,100)]


def test_completed_chunk_only_keeps_unprocessed_paused_range(tmp_path):
    with SharedLedger(tmp_path/'ledger.sqlite') as ledger:
        ledger.record_sweep('plan','scope',0,64,hits=[evidence()])
        # Control asks to pause before the next scan; no planned range is committed.
        assert ledger.remaining('plan','scope',0,200)==[(64,200)]


def test_concurrent_sweep_writers_merge_without_losing_hits(tmp_path):
    path=tmp_path/'ledger.sqlite'
    with SharedLedger(path):pass
    def write(index):
        with SharedLedger(path) as ledger:
            ledger.record_sweep('plan','scope',index*10,(index+1)*10,hits=[evidence('rifle_'+str(index))])
    with ThreadPoolExecutor(max_workers=4) as executor:list(executor.map(write,range(12)))
    with SharedLedger(path) as ledger:
        assert ledger.remaining('plan','scope',0,120)==[]
        assert list(map(tuple,ledger.db.execute('SELECT begin_index,end_index FROM swept')))==[(0,120)]
        assert ledger.db.execute('SELECT COUNT(*) FROM sweep_hits').fetchone()[0]==12


def test_restore_rejects_corrupted_cache_independently(tmp_path):
    hit=evidence()
    with SharedLedger(tmp_path/'ledger.sqlite') as ledger:
        ledger.record_sweep('plan','scope',0,1,hits=[hit])
        corrupt=dict(hit,name='different_name')
        with ledger.db:ledger.db.execute('UPDATE sweep_hits SET evidence=?',(json.dumps(corrupt),))
        store=target_store(tmp_path,hit)
        with pytest.raises(ValueError,match='独立 Python 回算'):ledger.restore_hits('plan','scope',store)
        assert store.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]==0
        store.close()


def test_engine_reuses_complete_sweep_and_restores_export_on_copied_target(tmp_path,monkeypatch):
    import finder.engine as engine
    from finder.candidates import Plan
    profile=PROFILES['iw-resource63'];name='rex_vm_ar_mike4_fire'
    plan=Plan([[f'not_a_hit_{i}' for i in range(99)]+[name]])
    ledger_path=tmp_path/'.namefinder-ledger.sqlite'
    source_fingerprints=[{'file':'D:/saluki/original.cdb','sha256':'a'*64}]
    paths=[]
    for index in range(2):
        root=tmp_path/f'copy-{index}';root.mkdir()
        (root/f'anim_{profile.digest(name):016x}.cast').write_bytes(b'x')
        work=tmp_path/f'work-{index}.sqlite';paths.append(work)
        store=Store(work);store.import_exported(root,'COD2026',profile.id,default_kind='xanim')
        task=engine.create_task(store,plan,[profile.id],kinds=['xanim'],backend='cpu',budget=100,duty=100,
            ledger_path=ledger_path,details={'content_sources':source_fingerprints})
        store.close()
        if index:
            def no_scan(*_):raise AssertionError('cached sweep must not initialize a hashing backend')
            monkeypatch.setattr(engine,'choose_backend',no_scan)
        result=engine.run_task(work,task)
        assert result['status']=='completed'
        if not index:assert result['scanned_candidates']==100 and result['skipped_candidates']==0
        else:
            assert result['scanned_candidates']==0 and result['skipped_candidates']==100 and result['cached_hits']==1
            reopened=Store(work)
            output=export(reopened,tmp_path/'export')
            assert decode_cdb((Path(output['path'])/'verified.cdb').read_bytes())=={profile.digest(name):name}
            reopened.close()


def test_engine_partial_sweep_leaves_unprocessed_indexes_and_resumes(tmp_path):
    from finder.candidates import Plan
    from finder.engine import create_task,run_task
    hit=evidence();store=target_store(tmp_path,hit)
    values=[f'unrelated_{index}' for index in range(100)]
    values[37]=hit['name'];plan=Plan([values]);ledger_path=tmp_path/'ledger.sqlite'
    task=create_task(store,plan,['iw-resource63'],kinds=['xanim'],unknown_only=False,
                     backend='cpu',budget=20,duty=100,ledger_path=ledger_path)
    store.close()
    first=run_task(tmp_path/'work.sqlite',task)
    second=run_task(tmp_path/'work.sqlite',task)
    assert first['status']=='budget_exhausted' and first['position']==20
    assert second['status']=='budget_exhausted' and second['position']==40
    assert first['scanned_candidates']==second['scanned_candidates']==20
    with SharedLedger(ledger_path,readonly=True) as ledger:
        assert all(item['zero_streak']==0 for item in ledger.report()['methods'])
        interval=list(ledger.db.execute('SELECT plan_sha256,kind FROM swept'))[0]
        assert ledger.remaining(interval[0],interval[1],0,100)==[(40,100)]
    reopened=Store(tmp_path/'work.sqlite')
    assert reopened.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]==1
    reopened.close()
