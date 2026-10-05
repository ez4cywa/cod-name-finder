import json
from pathlib import Path
import subprocess
import sys
import time
from finder.store import Store
from finder.hashing import PROFILES
from finder.candidates import Plan
from finder.engine import create_task,run_task

def test_process_termination_keeps_committed_checkpoint(tmp_path):
    p=PROFILES['iw-resource63'];folder=tmp_path/'exports';folder.mkdir()
    name='rifle_0000_fire_0000.snd'
    (folder/f'sound_{p.digest(name):016x}.wav').write_bytes(b'x')
    s=Store(tmp_path/'work.sqlite');s.import_exported(folder,'game',p.id)
    plan=Plan([['rifle_'],[f'{i:04}' for i in range(2000)],['_fire_'],[f'{i:04}' for i in range(2000)],['.snd']])
    task=create_task(s,plan,[p.id],backend='cpu',duty=1,budget=plan.total)
    s.close()
    control=tmp_path/'control.txt';control.write_text('run')
    proc=subprocess.Popen([sys.executable,'-m','finder','--work',str(tmp_path/'work.sqlite'),'worker',task,str(control)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    deadline=time.monotonic()+15;position=0
    while time.monotonic()<deadline:
        s=Store(tmp_path/'work.sqlite');position=s.task(task)['position'];s.close()
        if position>0:break
        time.sleep(.03)
    assert position>0
    proc.terminate();proc.wait(timeout=5);proc.stderr.close()
    s=Store(tmp_path/'work.sqlite')
    before=s.task(task)['position'];names=s.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]
    assert before>=position and names==1
    cfg=json.loads(s.task(task)['config']);cfg['budget']=1;cfg['duty']=100
    s.db.execute('UPDATE tasks SET config=? WHERE id=?',(json.dumps(cfg),task));s.db.commit();s.close()
    resumed=run_task(tmp_path/'work.sqlite',task)
    assert resumed['position']==before+1
    s=Store(tmp_path/'work.sqlite');assert s.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]==1;s.close()
