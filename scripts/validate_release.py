"""Run packaged binaries outside the source directory: CPU/GPU and export roundtrip."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from finder.hashing import PROFILES
from finder.formats import decode_cdb,encode_cdb

ROOT=Path(__file__).resolve().parents[1]
EXE=ROOT/'dist/CODNameFinder/CODNameFinder.exe'
def main():
    results=[]
    with tempfile.TemporaryDirectory(prefix='finder-release-test-') as folder:
        folder=Path(folder)
        def run(*args):
            proc=subprocess.run([str(EXE),*map(str,args)],cwd=folder,capture_output=True,text=True,
                                encoding='utf-8',errors='replace',timeout=90)
            results.append({'command':[str(a) for a in args],'exit_code':proc.returncode,
                            'stdout':proc.stdout[-3000:],'stderr':proc.stderr[-1000:]})
            if proc.returncode:raise RuntimeError(proc.stdout+proc.stderr)
            return proc.stdout
        existing=folder/'existing-indexes';existing.mkdir();(existing/'names.cdb').write_bytes(encode_cdb({}))
        run('devices')
        for mode in ('cpu','gpu'):
            files=folder/mode;files.mkdir()
            name='weapons/release_test_fire_01.snd';h=PROFILES['iw-resource63'].digest(name)
            (files/f'sound_{h:016x}.wav').write_bytes(b'fixture')
            previous_name='image_release_previous';previous_hash=PROFILES['fnv1a63'].digest(previous_name)
            (files/f'image_{previous_hash:016x}.dds').write_bytes(b'fixture')
            work=folder/(mode+'.sqlite')
            run('--work',work,'import-exported',files,'--game','release-test','--profile','iw-resource63')
            prior=folder/(mode+'-prior.csv');prior.write_text(f'{previous_hash:016x},{previous_name}\n',encoding='utf-8')
            run('--work',work,'reuse',prior,'--game','previous-test','--profiles','fnv1a63')
            config=folder/(mode+'.json');config.write_text(json.dumps({'slots':[['weapons/'],['release_test'],['_fire_01.snd']],
                'backend':mode,'duty':100,'unknown_only':True}),encoding='utf-8')
            run('--work',work,'search',config)
            run('--work',work,'export',folder/(mode+'-out'),'--saluki-dir',existing)
            output=next((folder/(mode+'-out')).glob('names-*'))
            values=decode_cdb((output/'verified.cdb').read_bytes())
            assert values=={h:name,previous_hash:previous_name}
            rust=subprocess.check_output([EXE.parent/'_internal/cdb-inspect.exe',output/'verified.cdb'])
            assert json.loads(rust)=={f'{k:016x}':v for k,v in values.items()}
        # Verify every shipped algorithm through both packaged backends.
        for pid,profile in PROFILES.items():
            for mode in ('cpu','gpu'):
                tag=pid+'-'+mode;files=folder/tag;files.mkdir()
                name='weapons/release_test_fire_01.snd';h=profile.digest(name)
                (files/f'xsound_{h:016x}.wav').write_bytes(b'fixture')
                work=folder/(tag+'.sqlite')
                run('--work',work,'import-exported',files,'--game','algorithm-reference','--profile',pid)
                config=folder/(tag+'.json');config.write_text(json.dumps({'slots':[['weapons/'],['release_test'],['_fire_01.snd']],
                    'backend':mode,'duty':100}),encoding='utf-8')
                run('--work',work,'search',config)
                run('--work',work,'export',folder/(tag+'-out'),'--saluki-dir',existing)
                output=next((folder/(tag+'-out')).glob('names-*'))
                assert decode_cdb((output/'verified.cdb').read_bytes())=={h:name}
        run('--work',folder/'cpu.sqlite','screenshot',ROOT/'validation/packaged-gui.png')
    report={'executable':str(EXE),'sha256':hashlib.sha256(EXE.read_bytes()).hexdigest(),
            'outside_source_directory':True,'cpu_gpu_export_verified':True,'results':results}
    (ROOT/'validation/packaged-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Packaged CLI / GPU / CPU / source reuse / CDB / GUI startup checks passed')
if __name__=='__main__':main()
