"""Validate a one-click result without a research project or original assets DB."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from finder.formats import decode_cdb
from finder.hashing import PROFILES
from finder.pipeline import index_files
from finder import VERSION
from finder.asset_names import parse_exported_name

def validate(report_path,reader=None):
    report_path=Path(report_path);report=json.loads(report_path.read_text(encoding='utf-8'))
    run=report_path.parent;config=json.loads((run/'configuration.json').read_text(encoding='utf-8'))
    output=Path(report['path']);profile=PROFILES[config['profile']]
    values=decode_cdb((output/'verified.cdb').read_bytes())
    with (output/'verified.csv').open(encoding='utf-8',newline='') as stream:
        rows=list(csv.reader(stream))
    assert all(len(row)==2 for row in rows)
    csv_values={int(h,16):name for h,name in rows}
    assert Path(report['new_names_csv']).read_bytes()==(output/'verified.csv').read_bytes()
    assert len(rows)==len(csv_values) and csv_values==values
    assert len(values)==report['entries'] and all(profile.digest(n)==h for h,n in values.items())
    targets=set()
    for file in Path(config['folder']).rglob('*'):
        if file.is_file():
            matched=parse_exported_name(file,root=config['folder'],min_digits=1 if profile.mask<=0xffffffff else 8)
            if matched and matched.kind!='xmodel':targets.add(matched.hash)
    assert set(values)<=targets
    known_keys=set();known_names=set()
    for file in index_files(config['indexes']):
        for h,n in decode_cdb(file.read_bytes()).items():
            if n.strip():known_keys.add(h);known_names.add(n)
    assert not (set(values)&known_keys) and not (set(values.values())&known_names)
    manifest=json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    index_root=Path(config['indexes']);index_root=index_root/'hash_pkg' if (index_root/'hash_pkg').is_dir() else index_root
    assert all(hashlib.sha256((index_root/s['file']).read_bytes()).hexdigest()==s['sha256'] for s in manifest['saluki_index_sources'])
    for filename,digest in manifest['files'].items():
        assert hashlib.sha256((output/filename).read_bytes()).hexdigest()==digest
    reader=Path(reader or ROOT/'dist'/VERSION/'CODNameFinder/engine/_internal/cdb-inspect.exe')
    independent=json.loads(subprocess.check_output([str(reader),str(output/'verified.cdb')],text=True,encoding='utf-8'))
    assert {int(h,16):n for h,n in independent.items()}==values
    package_values={}
    for file in (output/'hash_pkg').glob('*.cdb'):package_values.update(decode_cdb(file.read_bytes()))
    assert package_values==values
    if report['saluki_ready']:
        ready=Path(report['saluki_ready']);merge=json.loads((ready/'merge-report.json').read_text(encoding='utf-8'))
        assert not merge['conflicts']
        for item in merge['files']:
            old_path=index_root/item['file'];old=decode_cdb(old_path.read_bytes()) if old_path.exists() else {}
            incoming=decode_cdb((output/'hash_pkg'/item['file']).read_bytes())
            merged=decode_cdb((ready/'hash_pkg'/item['file']).read_bytes())
            assert merged=={**old,**incoming}
            native_merged=json.loads(subprocess.check_output([str(reader),str(ready/'hash_pkg'/item['file'])],text=True,encoding='utf-8'))
            assert {int(h,16):n for h,n in native_merged.items()}==merged
            assert item['merged_entries']==len(merged) and item['incoming_entries']==len(incoming)
    result={'version':VERSION,'report':str(report_path.resolve()),'entries':len(values),
        'target_hashes':len(targets),'csv_cdb_equal':True,'new_names_csv_verified':True,'independent_rust_reader_equal':True,
        'every_name_rehashed':True,'every_key_in_input':True,'no_saluki_existing_keys_or_names':True,
        'saluki_source_fingerprints_unchanged':True,'merged_indexes_preserve_existing':True,
        'no_research_project_required':True,'saluki_live_verified':False}
    (run/'output-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('report');parser.add_argument('--reader')
    args=parser.parse_args();validate(args.report,args.reader)
