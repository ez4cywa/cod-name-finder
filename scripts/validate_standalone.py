"""Relocate the portable distribution; use only self-contained synthetic inputs."""
import json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from finder.hashing import PROFILES
from finder.formats import encode_cdb,decode_cdb
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=PROFILES['iw-resource63'];names=['weapons/standalone_old.snd','weapons/standalone_new.snd']
    pairs={p.digest(n):n for n in names};old=p.digest(names[0]);new=p.digest(names[1])
    runs=[]
    with tempfile.TemporaryDirectory(prefix='finder-independent-') as temp:
        base=Path(temp);portable=base/'Portable App';shutil.copytree(ROOT/'dist/1.0.2/CODNameFinder',portable)
        exe=portable/'CODNameFinder.exe';env=os.environ.copy()
        for key in ['PYTHONPATH','PYTHONHOME']:env.pop(key,None)
        env['PATH']=str(Path(env.get('SystemRoot',env.get('SYSTEMROOT',r'C:\Windows')))/'System32')
        def run(*args):
            result=subprocess.run([str(exe),*map(str,args)],cwd=base,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
            assert result.returncode==0,result.stdout+result.stderr
            runs.append({'command':[str(a) for a in args],'exit_code':result.returncode})
            return result.stdout
        indexes=base/'Copied Indexes';indexes.mkdir();(indexes/'existing.cdb').write_bytes(encode_cdb({old:names[0]}))
        files=base/'Hashed Assets';files.mkdir()
        for h in pairs:(files/f'xsound_{h:016x}.wav').write_bytes(b'fixture')
        dictionary=base/'previous.csv';dictionary.write_text(f'{old:016x},{names[0]}\n',encoding='utf-8')
        for mode in ['cpu','gpu']:
            work=base/(mode+'.sqlite')
            run('--work',work,'import-exported',files,'--game','BO6 standalone','--profile',p.id)
            run('--work',work,'reuse',dictionary,'--game','previous','--profiles',p.id)
            config=base/(mode+'.json');config.write_text(json.dumps({'slots':[['weapons/standalone_'],['old','new'],['.snd']],'backend':mode,'duty':100}),encoding='utf-8')
            run('--work',work,'search',config)
            result=json.loads(run('--work',work,'export',base/(mode+'-out'),'--saluki-dir',indexes))
            assert result['entries']==1 and result['excluded_saluki_existing_keys']==1
            assert decode_cdb((Path(result['path'])/'verified.cdb').read_bytes())=={new:names[1]}
        run('--work',base/'cpu.sqlite','screenshot',ROOT/'validation/standalone-gui.png')
    report={'version':'1.0.2','relocated_distribution':True,'no_original_research_inputs':True,'no_original_saluki_inputs':True,'system_only_path':True,'cpu_gpu_verified':True,'copied_index_dedup_verified':True,'gui_startup_verified':True,'commands':runs}
    (ROOT/'validation/standalone-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Relocated package passed CPU/GPU search, dictionary reuse, copied-index filtering and GUI startup')
if __name__=='__main__':main()
