"""Run a packaged EXE against the user's animation snapshot, then reuse sweeps."""
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='backslashreplace',line_buffering=True)
    executable=ROOT/'dist/2.1.0/CODNameFinder/CODNameFinder.exe'
    native_reader=executable.parent/'engine/_internal/cdb-inspect.exe'
    config=ROOT/'validation/adaptation-real-configuration.json'
    env=os.environ.copy();env['PATH']=str(Path(env.get('SystemRoot','C:/Windows'))/'System32')
    env['DOTNET_ROOT']=str(ROOT/'validation/no-dotnet');env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    results=[]
    for attempt in range(2):
        started=time.monotonic();last=started
        with (ROOT/f'validation/adaptation-real-run-{attempt+1}.jsonl').open('w',encoding='utf-8') as log:
            with subprocess.Popen([str(executable),'run',str(config)],cwd=ROOT/'validation',env=env,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8') as child:
                for line in child.stdout:
                    log.write(line);log.flush();item=json.loads(line)
                    if item.get('event')=='result':
                        result=item['result'];results.append(result)
                        print(json.dumps({key:result[key] for key in ('entries','processed','cached_hits','skipped_candidates','seconds','run_dir')},ensure_ascii=False),flush=True)
                    elif time.monotonic()-last>=10:
                        print(item.get('message',''),flush=True);last=time.monotonic()
                error=child.stderr.read();child.wait()
                if child.returncode:raise RuntimeError(error+' exit='+str(child.returncode))
        assert len(results)==attempt+1
    rows=[]
    for result in results:
        with Path(result['new_names_csv']).open(encoding='utf-8',newline='') as stream:rows.append(set(tuple(row) for row in csv.reader(stream)))
    baseline=ROOT/'runs/avalonia-crossasset-2.0.0/run-20261002-194813-4d18cc/names-20261002-194919-eac8fe/new_names.csv'
    with baseline.open(encoding='utf-8',newline='') as stream:old=set(tuple(row) for row in csv.reader(stream))
    assert rows[0]==rows[1] and old<=rows[0]
    assert results[1]['processed']==0 and results[1]['cached_hits']>0
    assert results[1]['complete_cache_reused'] is True
    independent_files=0
    for result,values in zip(results,rows):
        expected={key:name for key,name in values}
        paths=[Path(result['path'])/'verified.cdb',Path(result['path'])/'hash_pkg/fnv1a_xanims_v2.cdb',
            Path(result['saluki_ready'])/'hash_pkg/fnv1a_xanims_v2.cdb']
        for index,path in enumerate(paths):
            child=subprocess.run([str(native_reader),str(path)],env=env,cwd=ROOT/'validation',
                capture_output=True,text=True,encoding='utf-8',check=True,timeout=120)
            decoded=json.loads(child.stdout);independent_files+=1
            assert all(decoded.get(key)==name for key,name in expected.items())
            if index<2:assert decoded==expected
    summary={'executable_sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
        'new_names':len(rows[0]),'baseline_names':len(old),'baseline_preserved':True,
        'repeat_new_scans':results[1]['processed'],'repeat_skipped':results[1]['skipped_candidates'],
        'complete_run_cache_verified':True,'independent_cdb_files':independent_files,
        'results':results,'environment':'system32-only; no developer runtime','saluki_live_verified':False}
    (ROOT/'validation/adaptation-real-validation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('real snapshot and cached exports identical; previous names preserved',flush=True)


if __name__=='__main__':main()
