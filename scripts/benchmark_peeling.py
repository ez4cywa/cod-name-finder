"""Reproducible local measurements; no upstream implementation is used."""
import argparse
import hashlib
import json
import platform
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from finder.backends import CPU
from finder.candidates import Plan
from finder.hashing import PROFILES,native
from finder.peeling import choose_backend


def run(output,heads=32768,tails=256,threads=4,repeats=3):
    profile=PROFILES['iw-resource63']
    plan=Plan([[f'rex_vm_ar_kilo2_{i:06d}_' for i in range(heads)],
               [f'inspect_empty_{i:03d}' for i in range(tails)]])
    expected=sorted({0,tails-1,tails,103001,plan.total-1})
    targets={profile.digest(plan.at(i)) for i in expected}
    fingerprint=hashlib.sha256(json.dumps(plan.slots,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    results={}
    native()  # Exclude process-wide DLL loading; both paths remain fully prepared.
    for label,constructor in [('forward',lambda: (CPU(plan,profile,targets,threads),{})),
                              ('peeled',lambda: choose_backend('cpu',plan,profile,targets,threads))]:
        trials=[]
        for _ in range(repeats):
            tick=time.perf_counter();backend,info=constructor();prepared=time.perf_counter()-tick
            hits=[];tick=time.perf_counter()
            for base in range(0,plan.total,65536):
                count=min(65536,plan.total-base)
                hits.extend(base+i for i in backend.scan(base,count))
            duration=time.perf_counter()-tick
            assert hits==expected,(label,hits)
            stats=dict(getattr(backend,'stats',{'equivalent_candidates':plan.total,
                'actual_forward_hashes':plan.total,'reverse_steps':0,'hash_ratio':1.0}))
            trials.append({'preparation_seconds':prepared,'scan_seconds':duration,
                'total_seconds':prepared+duration,'hits':hits,**stats,
                'equivalent_candidates_per_second':plan.total/(prepared+duration),
                'actual_forward_hashes_per_second':stats['actual_forward_hashes']/(prepared+duration),
                'selection':info})
            if hasattr(backend,'close'):backend.close()
        results[label]={**sorted(trials,key=lambda row:row['total_seconds'])[len(trials)//2],
                        'timing_basis':'median total duration of repeated fully prepared runs',
                        'trials':[{'preparation_seconds':r['preparation_seconds'],
                            'scan_seconds':r['scan_seconds'],'total_seconds':r['total_seconds']} for r in trials]}
    # Measure the old Python materialization seam separately on a bounded sample:
    # native slot scanning never generates these full candidate strings.
    sample=min(262144,plan.total)
    tick=time.perf_counter();byte_count=0
    for i in range(sample):byte_count+=len(plan.at(i).encode('utf-8'))
    generated=time.perf_counter()-tick
    # A large target set and two tails must reject peeling: compare choice to
    # ordinary forward on the same sample instead of claiming a universal gain.
    no_gain=Plan([[str(i) for i in range(2048)],['a','b']])
    dense_targets=set(range(20000))|{profile.digest(no_gain.at(1))}
    fallback,why=choose_backend('cpu',no_gain,profile,dense_targets,threads)
    tick=time.perf_counter();fallback_hits=fallback.scan(0,no_gain.total);fallback_time=time.perf_counter()-tick
    ordinary=CPU(no_gain,profile,dense_targets,threads)
    tick=time.perf_counter();ordinary_hits=ordinary.scan(0,no_gain.total);ordinary_time=time.perf_counter()-tick
    assert fallback_hits==ordinary_hits
    report={'schema':1,'implementation':'independent modular inverse and mixed-radix native search',
        'machine':platform.platform(),'processor':platform.processor(),'logical_cpu_count':os.cpu_count(),
        'python':platform.python_version(),'threads':threads,'repeats':repeats,
        'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [ROOT/'native/src/lib.rs',ROOT/'native/src/registry_generated.rs',ROOT/'finder/peeling.py']},
        'profile':profile.json(),'geometry':{'heads':heads,'tails':tails,'equivalent_candidates':plan.total,
        'target_count':len(targets),'plan_sha256':fingerprint},'results':results,
        'actual_forward_reduction':results['forward']['actual_forward_hashes']/results['peeled']['actual_forward_hashes'],
        'wall_time_speedup_including_preparation':results['forward']['total_seconds']/results['peeled']['total_seconds'],
        'python_generator_sample':{'names':sample,'bytes':byte_count,'seconds':generated,
            'names_per_second':sample/generated,'native_hot_path_materialized_full_names':0,
            'measurement_scope':'Plan.at and UTF8 only, not hashing; sample is not a full-run extrapolation'},
        'no_gain_fallback':{'selection':why,'scan_seconds':fallback_time,'plain_forward_seconds':ordinary_time,
            'matching_hits':fallback_hits,'actual_forward_hashes':fallback.stats['actual_forward_hashes']}}
    assert report['actual_forward_reduction']>=100
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(output),'actual_forward_reduction':report['actual_forward_reduction'],
        'wall_time_speedup_including_preparation':report['wall_time_speedup_including_preparation'],
        'forward_seconds':results['forward']['total_seconds'],'peeled_seconds':results['peeled']['total_seconds'],
        'python_names_per_second':sample/generated,'fallback':why['peeling_cost']['reason']},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default=ROOT/'validation/peel-benchmark.json')
    parser.add_argument('--threads',type=int,default=4)
    parser.add_argument('--repeats',type=int,default=3)
    args=parser.parse_args();run(args.output,threads=args.threads,repeats=args.repeats)
