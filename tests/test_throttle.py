"""Deterministic replay of a batch deadline crossed before time.sleep."""
from types import SimpleNamespace
import pytest
from finder.candidates import Plan
from finder.hashing import PROFILES
from finder.store import Store
import finder.engine as engine

class DeadlineClock:
    def __init__(self):
        self.values=iter([0.0,0.0,0.0,0.03,0.04,0.049,0.051])
        self.last=0.0;self.sleeps=[]
    def perf_counter(self):
        self.last=next(self.values,self.last+0.001)
        return self.last
    def sleep(self,seconds):
        if seconds<0:raise ValueError('sleep length must be non-negative')
        self.sleeps.append(seconds)

@pytest.mark.parametrize('duty',[75,100])
@pytest.mark.parametrize('slow_control',[False,True])
def test_deadline_crossed_between_wait_check_and_sleep_keeps_completed_match(tmp_path,monkeypatch,duty,slow_control):
    profile=PROFILES['iw-resource63'];name='weapons/test_sleep_deadline.snd'
    folder=tmp_path/'exports';folder.mkdir()
    (folder/f'sound_{profile.digest(name):016x}.wav').write_bytes(b'fixture')
    store=Store(tmp_path/'work.sqlite')
    store.import_exported(folder,'test',profile.id)
    task=engine.create_task(store,Plan([[name]]),[profile.id],backend='cpu',duty=duty)
    store.close()
    clock=DeadlineClock()
    monkeypatch.setattr(engine,'time',SimpleNamespace(perf_counter=clock.perf_counter,sleep=clock.sleep))
    def control():
        if slow_control and clock.last>=0.04:clock.values=iter([0.06])
        return 'run'
    result=engine.run_task(tmp_path/'work.sqlite',task,control=control)
    assert result['status']=='completed' and result['position']==1
    assert all(0<seconds<=0.05 for seconds in clock.sleeps)
    if duty==100 or slow_control:assert clock.sleeps==[]
    store=Store(tmp_path/'work.sqlite')
    try:
        evidence=store.db.execute('SELECT hash,name,method FROM evidence').fetchone()
        assert int(evidence['hash'],16)==profile.digest(name)
        assert evidence['name']==name and evidence['method']=='discovered'
    finally:store.close()

@pytest.mark.parametrize('action,expected',[('pause','paused'),('cancel','cancelled')])
def test_stop_during_throttle_retains_committed_batch(tmp_path,monkeypatch,action,expected):
    profile=PROFILES['iw-resource63'];name='sleep_stop_0.snd'
    folder=tmp_path/'exports';folder.mkdir()
    (folder/f'sound_{profile.digest(name):016x}.wav').write_bytes(b'fixture')
    store=Store(tmp_path/'work.sqlite');store.import_exported(folder,'test',profile.id)
    plan=Plan([['sleep_stop_'],[str(i) for i in range(65537)],['.snd']])
    task=engine.create_task(store,plan,[profile.id],backend='cpu',duty=75);store.close()
    clock=DeadlineClock()
    monkeypatch.setattr(engine,'time',SimpleNamespace(perf_counter=clock.perf_counter,sleep=clock.sleep))
    control=lambda:action if clock.last>=0.04 else 'run'
    result=engine.run_task(tmp_path/'work.sqlite',task,control=control)
    assert result['status']==expected and result['position']==65536 and clock.sleeps==[]
    store=Store(tmp_path/'work.sqlite')
    try:assert store.db.execute('SELECT COUNT(*) FROM evidence WHERE name=?',(name,)).fetchone()[0]==1
    finally:store.close()
