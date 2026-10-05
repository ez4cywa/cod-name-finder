"""Read-only preflight: exact candidate spaces and measured CPU time ranges."""
from dataclasses import replace
import math
from pathlib import Path
import tempfile
import time

from . import VERSION
from .backends import CPU
from .candidates import Plan
from .hashing import PROFILES
from .methods import SharedLedger,method_descriptor,plan_fingerprint
from .peeling import plan_cost
from .pipeline import Config,prepare,import_snapshot,usable_complete_record
from .store import Store


def budgeted_cost(cost,intervals,budget):
    """Fixed native preparation is charged once, even for a one-item budget.

    Keep interval edges and the nominal 65536 chunk size, rather than spreading
    table setup evenly over an entire space which may never be searched.
    """
    consumed=0;scan_work=0;chunks=0
    for begin,end in intervals:
        stop=min(end,begin+max(0,budget-consumed))
        position=begin
        while position<stop:
            count=min(65536,stop-position);chunks+=1
            if cost['strategy']=='peeled' and cost['direction']=='reverse-target-table':
                tails=cost['tails']
                heads=(position+count-1)//tails-position//tails+1
                scan_work+=heads*cost['prefix_mean_bytes']
            elif cost['strategy']=='peeled':
                queries=min(count,cost['tails'])*cost['target_variants']
                scan_work+=queries*cost['suffix_mean_bytes']
            else:
                scan_work+=cost['forward_byte_operations']*count/max(cost['equivalent_candidates'],1)
            position+=count;consumed+=count
        if consumed>=budget:break
    fixed=cost.get('fixed_byte_operations',0) if consumed and cost['strategy']=='peeled' else 0
    return {'budgeted_candidates':consumed,'fixed_byte_operations':fixed,
            'scan_byte_operations':scan_work,'byte_operations':fixed+scan_work,'nominal_chunks':chunks}


def estimate(config,progress=lambda *_:None,control=lambda:'run'):
    config=Config(**config) if isinstance(config,dict) else config
    config.validate();start=time.perf_counter()
    if config.community:
        community_cache=Path(config.community_cache or Path(config.output)/'.community-cache')
        if config.community_refresh or not (community_cache/'current.json').is_file():
            raise ValueError('只读估算不下载或刷新社区表；请先使用 community sync 同步缓存，或关闭社区表选项再估算')
    with tempfile.TemporaryDirectory(prefix='namefinder-estimate-') as temporary:
        store=Store(Path(temporary)/'estimate.sqlite')
        try:
            from .completedcache import CompletedCache,signature
            snapshot=import_snapshot(config,store,progress,control)
            if snapshot.get('cancelled') or control()!='run':return {'status':'stopped','version':VERSION}
            ledger_path=Path(config.output)/'.namefinder-ledger.sqlite'
            cache_signature=signature(config,store,control) if ledger_path.is_file() else None
            if cache_signature:
                with CompletedCache(ledger_path,readonly=True) as cache:
                    record=usable_complete_record(cache.lookup(cache_signature['key']))
                    restored=cache.restore(record,store,config.profile,config.low60) if record else None
                if restored is not None:
                    from .coverage import snapshot_coverage
                    previous=record['summary'];profile=PROFILES[config.profile]
                    bits=min(profile.mask.bit_length(),60) if config.low60 else profile.mask.bit_length()
                    covered=previous['processed']+previous.get('skipped_candidates',0)
                    coverage=snapshot_coverage(store,config.indexes,config.exclude_material)
                    preparation=time.perf_counter()-start
                    return {'version':VERSION,'status':'estimated','profile':config.profile,'hash_domain':config.hash_domain,
                        'target_count':len(store.targets(exclude_material=config.exclude_material)),
                        'effective_bits':bits,'candidate_total':covered,'candidate_budget':config.budget,
                        'budgeted_candidates':0,'budgeted_candidates_are_upper_bound':False,
                        'cached_candidates_lower_bound':covered,'collision_expectation':0,
                        'collision_formula':'new candidates * targets / 2^effective_bits',
                        'estimated_compute_seconds':0,'estimated_seconds_range':[0,round(preparation,6)],
                        'estimate_scope':'complete plan reused; CPU revalidation done; file I/O and incremental export still required',
                        'range_kind':'no new hashing; export duration unmeasured',
                        'estimated_total_seconds_including_preparation':round(preparation,6),
                        'time_budget_seconds':config.seconds,'time_budget_may_limit':False,
                        'benchmark':{'sample_candidates':0,'seconds':0,'cpu_candidates_per_second':0,
                            'scope':'complete run cache; no scan benchmark required'},
                        'preparation_seconds':round(preparation,6),
                        'stages':[{'label':'完整运行复用','total':covered,'cached':covered,'budgeted':0,'uncovered_upper_bound':0}],
                        'coverage':coverage,'uncertainty':'Input content is unchanged; output excludes current Saluki entries again.',
                        'low60_pending_only':config.low60,'cross_asset':{**previous['cross_asset'],'related_folder':config.related_folder},
                        'complete_cache_reused':True}
            state=prepare(config,store,progress,control,snapshot=snapshot)
            if state.get('cancelled') or control()!='run':return {'status':'stopped','version':VERSION}
            preparation=time.perf_counter()-start
            profile=PROFILES[config.profile]
            if config.low60:profile=replace(profile,mask=profile.mask&((1<<60)-1))
            targets={profile.id:sorted({row['hash'] for row in store.targets(
                exclude_material=config.exclude_material,unknown_only=True)})}
            target_count=len(targets[profile.id])
            plans=state['plans'];rows=[];remaining=0;operations=0;candidate_total=0
            ledger_path=Path(config.output)/'.namefinder-ledger.sqlite'
            ledger=SharedLedger(ledger_path,readonly=True) if ledger_path.is_file() else None
            try:
                for label,plan in plans:
                    if control()!='run':return {'status':'stopped','version':VERSION}
                    cost=plan_cost(plan,profile,target_count)
                    if config.backend=='gpu':
                        cost={**cost,'strategy':'forward-gpu','estimated_forward_hashes':plan.total,
                              'estimated_byte_operations':cost['forward_byte_operations']}
                    cost.setdefault('estimated_byte_operations',cost['forward_byte_operations'])
                    descriptor=method_descriptor(plan.metadata)
                    fingerprint=plan_fingerprint(plan,profiles=[profile],targets=targets,
                        catalog_fingerprint=store.meta('catalog_fingerprint'),method=descriptor,
                        sources=state['sources']+state['extra_sources'],
                        options={'keyword':config.keyword,'low60':config.low60,'kinds':[],
                                 'exclude_material':config.exclude_material,'domain':config.hash_domain})
                    uncovered=ledger.remaining(fingerprint,profile.id+':',0,plan.total) if ledger else [(0,plan.total)]
                    fresh=sum(end-begin for begin,end in uncovered)
                    budget_work=budgeted_cost(cost,uncovered,max(0,config.budget-remaining)) if target_count else {
                        'budgeted_candidates':0,'fixed_byte_operations':0,'scan_byte_operations':0,
                        'byte_operations':0,'nominal_chunks':0}
                    active=budget_work['budgeted_candidates'];remaining+=active
                    candidate_total+=plan.total
                    operations+=budget_work['byte_operations']
                    rows.append({'label':label,'total':plan.total,'uncovered_upper_bound':fresh,
                        'cached':plan.total-fresh,'budgeted':active,'method':descriptor,'cost':cost,
                        'budget_cost':budget_work,
                        'vocabulary_bytes':sum(len(value.encode('utf-8')) for slot in plan.slots for value in slot)})
            finally:
                if ledger:ledger.close()
            # A bounded sample uses the same native forward engine as execution.
            sample_names=sorted(state['names'])[:8192] or ['rex_estimate_probe_'+str(i) for i in range(1024)]
            sample=Plan([sample_names]);tick=time.perf_counter()
            backend=CPU(sample,profile,{int(h,16) for h in targets[profile.id]},4)
            sample_setup=max(time.perf_counter()-tick,1e-6)
            trials=[]
            for _ in range(3):
                tick=time.perf_counter();backend.scan(0,sample.total)
                trials.append(max(time.perf_counter()-tick,1e-6))
            elapsed=sorted(trials)[1]
            sample_bytes=sum(len(profile.normalize(n).encode('utf-8')) for n in sample_names)
            finish_bytes=len(profile.secret) if profile.algorithm in ('secure','suffix') else int(profile.algorithm=='t7-script')
            avg_bytes=sample_bytes/sample.total+finish_bytes
            rate=sample.total/elapsed;byte_rate=rate*max(avg_bytes,1)
            # Includes the pipeline's 75% duty cycle. Preparation, index export,
            # table setup and GPU rates vary; publish an interval, never an SLA.
            setup_bytes=sum(row['vocabulary_bytes'] for row in rows if row['budgeted'])
            setup_estimate=setup_bytes/max(sample_bytes,1)*sample_setup
            predicted=operations/max(byte_rate,1)/0.75+setup_estimate
            bits=profile.mask.bit_length()
            collision=remaining*target_count/(1<<bits)
            return {'version':VERSION,'status':'estimated','profile':config.profile,'hash_domain':config.hash_domain,
                'target_count':target_count,'effective_bits':bits,'candidate_total':candidate_total,
                'candidate_budget':config.budget,'budgeted_candidates':remaining,
                'budgeted_candidates_are_upper_bound':True,
                'cached_candidates_lower_bound':sum(row['cached'] for row in rows),
                'collision_expectation':collision,'collision_formula':'budgeted_candidates * targets / 2^effective_bits',
                'estimated_compute_seconds':round(predicted,6),
                # Tiny samples pay thread startup per name; large products and
                # peeled prefix loops amortize it. A wide heuristic lower bound
                # deliberately allows that observed 4x+ speed departure.
                'estimated_seconds_range':[round(predicted*0.1,6),round(predicted*4+preparation,6)],
                'estimate_scope':'CPU reference preparation+hash scanning+75% duty; excludes export/SQLite and unmeasured GPU startup',
                'range_kind':'heuristic planning interval, not a confidence interval or SLA',
                'estimated_total_seconds_including_preparation':round(predicted+preparation,6),
                'time_budget_seconds':config.seconds,'time_budget_may_limit':predicted+preparation>config.seconds,
                'benchmark':{'sample_candidates':sample.total,'seconds':elapsed,'cpu_candidates_per_second':rate,
                             'mean_bytes':avg_bytes,'scope':'native forward CPU with current target lookup; GPU speed not measured',
                             'includes_profile_secret':profile.algorithm in ('secure','suffix'),
                             'estimated_byte_operations':operations,'duty_cycle':0.75,
                             'sample_repetitions':3,'sample_seconds':trials,
                             'sample_vocabulary_bytes':sample_bytes,'sample_setup_seconds':sample_setup,
                             'estimated_native_setup_seconds':setup_estimate},
                'preparation_seconds':round(preparation,6),'stages':rows,'coverage':state['coverage'],
                'uncertainty':'Timing is an estimate. Unknown targets shrink after hits; cached coverage may increase during execution.',
                'low60_pending_only':config.low60,'cross_asset':state['cross_summary']}
        finally:store.close()
