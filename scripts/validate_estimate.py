"""Measure CPU reference estimate ranges on private synthetic local fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from finder.estimate import estimate
from finder.formats import encode_cdb
from finder.hashing import PROFILES
from finder.peeling import choose_backend
from finder.pipeline import Config,prepare
from finder.store import Store


def contents(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def measure(root,profile_id,size,number_max,budget):
    root.mkdir();folder=root/'assets';folder.mkdir();indexes=root/'indexes';indexes.mkdir()
    profile=PROFILES[profile_id]
    missing='rex_estimate_unseen_target_not_in_candidate_families'
    (folder/f'anim_{profile.digest(missing):016x}.cast').write_bytes(b'private synthetic hash asset')
    names=[f'rex_vm_ar_kilo2_variant{i:04d}_fire_{i%17:02d}' for i in range(size)]
    (indexes/'fnv1a_xanims.cdb').write_bytes(encode_cdb({profile.digest(name):name for name in names}))
    config=Config(str(folder),str(indexes),str(root/'untouched-output'),profile=profile_id,
        game='manual',backend='cpu',cross_asset=False,number_max=number_max,budget=budget)
    before=contents(root);quoted=estimate(config)
    assert contents(root)==before and not Path(config.output).exists()
    store=Store(root/'measurement-only.sqlite')
    try:state=prepare(config,store)
    finally:store.close()
    assert quoted['candidate_total']==sum(plan.total for _,plan in state['plans'])
    assert quoted['budgeted_candidates']==min(config.budget,quoted['candidate_total'])
    details=[];compute=0;remaining=config.budget
    for index,(label,plan) in enumerate(state['plans']):
        count=min(remaining,plan.total)
        if count<=0:break
        tick=time.perf_counter();backend,selection=choose_backend('cpu',plan,profile,{profile.digest(missing)},4)
        setup=time.perf_counter()-tick;scanned=0;hash_seconds=0;duty_seconds=0;hits=[]
        try:
            while scanned<count:
                n=min(65536,count-scanned);tick=time.perf_counter()
                hits.extend(scanned+i for i in backend.scan(scanned,n))
                elapsed=time.perf_counter()-tick;hash_seconds+=elapsed
                duty=elapsed/3;tick=time.perf_counter();time.sleep(duty);duty_seconds+=time.perf_counter()-tick
                scanned+=n
            assert not hits
            stats=dict(backend.stats)
        finally:
            if hasattr(backend,'close'):backend.close()
        duration=setup+hash_seconds+duty_seconds;compute+=duration;remaining-=count
        details.append({'label':label,'planned_candidates':plan.total,'scanned':count,
            'setup_seconds':setup,'scan_seconds':hash_seconds,'duty_seconds':duty_seconds,
            'total_seconds':duration,'stats':stats,'selected':selection['selected']})
        assert count==quoted['stages'][index]['budgeted']
    low,high=quoted['estimated_seconds_range']
    row={'profile':profile_id,'source_names':size,'number_max':number_max,'budget':budget,
        'candidate_total':quoted['candidate_total'],'scanned_candidates':sum(r['scanned'] for r in details),
        'estimated_compute_seconds':quoted['estimated_compute_seconds'],
        'estimated_seconds_range':[low,high],'preparation_seconds':quoted['preparation_seconds'],
        'actual_compute_seconds':compute,'inside_displayed_range':low<=compute<=high,
        'ratio_actual_to_estimate':compute/max(quoted['estimated_compute_seconds'],1e-9),
        'input_and_output_unchanged_during_estimate':True,'collision_expectation':quoted['collision_expectation'],
        'effective_bits':quoted['effective_bits'],'stages':details,'benchmark':quoted['benchmark']}
    assert row['inside_displayed_range'],row
    return row


def main(output):
    with tempfile.TemporaryDirectory(prefix='estimate-validation-') as directory:
        root=Path(directory)
        cases=[('iw-resource63',512,64,1000000),('fnv1a32',512,32,1000000),
            ('fnv1a64',512,64,37),('bo6-script64',512,32,1000000),
            ('bo6-sp-script64',512,32,1000000),('kvp64',512,32,1000000)]
        rows=[measure(root/str(i),*case) for i,case in enumerate(cases)]
    report={'schema':1,'scope':'synthetic local CPU reference fixtures, current target lookup, native setup+scan+75% duty; excludes export/SQLite',
        'timing_is_sla':False,'fixed_costs_included':True,'gpu_measured':False,
        'read_only_estimates':all(r['input_and_output_unchanged_during_estimate'] for r in rows),
        'all_ranges_contain_measured_compute':all(r['inside_displayed_range'] for r in rows),
        'source_sha256':{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [ROOT/'finder/estimate.py',ROOT/'finder/peeling.py']},'cases':rows}
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(output),'cases':len(rows),'all_ranges_contain_measured_compute':report['all_ranges_contain_measured_compute'],
        'ranges':[{'profile':r['profile'],'estimated':r['estimated_compute_seconds'],
                   'actual':r['actual_compute_seconds'],'range':r['estimated_seconds_range']} for r in rows]},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default=ROOT/'validation/estimate-validation.json')
    main(parser.parse_args().output)
