"""Real source cross-checks, held-out family recovery, GPU parity and Saluki package QA."""
import csv
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from finder.store import Store
from finder.hashing import PROFILES
from finder.candidates import automatic_plan,audio_plan,Plan
from finder.backends import CPU,GPU,devices
from finder.engine import create_task,run_task
from finder.exporter import export,prepare_saluki
from finder.formats import decode_cdb

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'validation'
SOURCE=Path(r'E:\ghidra_12.1.3_PUBLIC_20260817\analysis\asset-catalog\assets.sqlite')
SALUKI=Path(r'D:\_tiqu\Saluki')
def main():
    OUT.mkdir(exist_ok=True)
    report={'devices':devices(),'source_catalog':str(SOURCE),'saluki_version':'0.2.42',
            'saluki_live_ui_verified':False,'soak_8h_completed':False}
    s=Store(OUT/'work.sqlite')
    if not s.meta('catalog_fingerprint'):s.import_catalog(SOURCE,'COD26 Beta CL28635235 Build9183177')
    report['imported_assets']=s.db.execute('SELECT COUNT(*) FROM assets').fetchone()[0]
    report['catalog_verified_keys']=s.db.execute('SELECT COUNT(DISTINCT hash) FROM evidence').fetchone()[0]
    report['calibrated_types']=s.db.execute('SELECT COUNT(DISTINCT kind) FROM calibration').fetchone()[0]
    previous=Path(r'E:\ghidra_12.1.3_PUBLIC_20260817\analysis\cod-name-db\csv')
    sourcefiles=list(previous.glob('*xanims*.csv'))+list(previous.glob('*xsounds_v2*.csv'))
    report['reuse']=s.import_dictionary(sourcefiles,'cod-name-db source files',
         ['iw-resource63','fnv1a63','fnv1a64'],keyword='mike4')
    # Hold out complete names, including their word-table copies. Training only sees other siblings.
    db=sqlite3.connect(SOURCE.as_uri()+'?mode=ro',uri=True)
    names=sorted({r[0] for r in db.execute("SELECT name FROM assets WHERE asset_type='sndasset' AND name LIKE '%mike4%' AND name IS NOT NULL")})
    db.close()
    holdout=[n for n in names if '_05.' in n][:20]
    train=[n for n in names if n not in holdout]
    if not holdout:raise RuntimeError('No real audio holdout examples')
    small=OUT/'holdout-catalog.sqlite'
    if not small.exists():
        d=sqlite3.connect(small);d.execute('CREATE TABLE assets(asset_type TEXT,name_hash TEXT,name TEXT,package TEXT)')
        for n in names:d.execute('INSERT INTO assets VALUES (?,?,?,?)',('sndasset',f"{PROFILES['iw-resource63'].digest(n):016x}",None if n in holdout else n,'real-audio-holdout'))
        d.commit();d.close()
    holdwork=OUT/'holdout-work.sqlite'
    h=Store(holdwork)
    if not h.meta('catalog_fingerprint'):h.import_catalog(small,'COD26 actual-name holdout')
    plan=automatic_plan(train,'mike4',32)
    task=create_task(h,plan,['iw-resource63'],kinds=['sndasset'],backend='gpu',budget=plan.total,duty=100,unknown_only=False)
    h.close();run_task(holdwork,task)
    h=Store(holdwork)
    found={r[0] for r in h.db.execute("SELECT name FROM evidence WHERE method='discovered'")}
    report['holdout']={'training_names':len(train),'held_out':len(holdout),'recovered':len(found & set(holdout)),
        'candidate_count':plan.total,'held_names_absent_from_training':not bool(set(train)&set(holdout)),
        'note':'same-family numeric holdout; not an unseen-family recall estimate'}
    h.close()
    # Actual audio path roundtrip: convert one known path to exported underscore stem.
    name=holdout[0];stem=name.split('.',1)[0];flat=stem.replace('/','_')+'.wav'
    ap=audio_plan(flat,[stem.rsplit('/',1)[0]],['.'+name.split('.',1)[1]])
    target={PROFILES['iw-resource63'].digest(name)}
    hits=GPU(ap,PROFILES['iw-resource63'],target).scan(0,ap.total)
    recovered=[ap.at(i) for i in hits]
    report['audio_path']={'source':name,'simulated_exported':flat,'candidates':ap.total,'recovered':recovered,
                          'real_export_pair_verified':False}
    # End-to-end CPU/GPU candidate generation, not just hash-loop timing.
    bp=Plan([['rex/wpn/ar_mike4/'],[f'weap_rex_mike4_fire_plr_{i:02}' for i in range(200)],
             [f'.variant{j:03}.48000.all' for j in range(1000)]])
    targets={PROFILES['iw-resource63'].digest(bp.at(i)) for i in [1,25000,199999]}
    bench={};outputs=[]
    for cls in [CPU,GPU]:
        start=time.perf_counter();backend=cls(bp,PROFILES['iw-resource63'],targets,4)
        setup=time.perf_counter()-start;start=time.perf_counter();matches=[]
        for base in range(0,bp.total,65536):matches.extend(base+i for i in backend.scan(base,min(65536,bp.total-base)))
        duration=time.perf_counter()-start;outputs.append(matches)
        bench[backend.name]={'setup_seconds':setup,'scan_seconds':duration,'candidates':bp.total,
                             'end_to_end_candidates_per_second':bp.total/(setup+duration),'hits':matches}
    if outputs[0]!=outputs[1]:raise RuntimeError('Real device benchmark parity failed')
    report['benchmark']=bench
    exported=export(s,OUT/'exports',keyword='mike4',new_only=False)
    report['export']=exported
    inspect=ROOT/'native/target/release/cdb-inspect.exe'
    rust=json.loads(subprocess.check_output([inspect,Path(exported['path'])/'verified.cdb']))
    python={f'{k:016x}':v for k,v in decode_cdb((Path(exported['path'])/'verified.cdb').read_bytes()).items()}
    if rust!=python:raise RuntimeError('Independent Rust CDB reader differs')
    report['independent_rust_reader_verified']=True
    report['saluki_existing_cdb_files']=len(list((SALUKI/'hash_pkg').glob('*.cdb')))
    for path in (SALUKI/'hash_pkg').glob('*.cdb'):decode_cdb(path.read_bytes())
    merged=OUT/('saluki-merged-'+time.strftime('%Y%m%d-%H%M%S'))
    report['saluki_merge']=prepare_saluki(exported['path'],SALUKI,merged)
    s.close()
    (OUT/'real-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
