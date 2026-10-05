"""Boundary tests use fake process memory only; no loader or game is started."""
from collections import Counter
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import struct
import subprocess
from types import SimpleNamespace

import pytest

from finder import cordycep
from finder.snapshot import read_snapshot


TABLE=0x100000
NODE=0x200000
HEADER=0x300000
STRINGS=0x400000


class FakeKernel:
    def __init__(self,image):
        self.image=str(image);self.opened=[];self.closed=[];self.short_read=False
    def OpenProcess(self,rights,inherit,pid):
        self.opened.append((rights,inherit,pid));return 91
    def CloseHandle(self,handle):self.closed.append(handle);return True
    def QueryFullProcessImageNameW(self,handle,flags,buffer,length):
        buffer.value=self.image;return True
    def GetProcessTimes(self,handle,*times):
        stamp=int((1000+11644473600)*10000000)
        value=ctypes.cast(times[0],ctypes.POINTER(wintypes.FILETIME)).contents
        value.dwLowDateTime=stamp&0xffffffff;value.dwHighDateTime=stamp>>32
        return True
    def ReadProcessMemory(self,handle,address,buffer,size,count):
        actual=size-1 if self.short_read else size
        ctypes.memmove(buffer,b'A'*actual,actual)
        ctypes.cast(count,ctypes.POINTER(ctypes.c_size_t)).contents.value=actual
        return True
    def VirtualQueryEx(self,handle,address,pointer,size):
        value=ctypes.cast(pointer,ctypes.POINTER(cordycep._MemoryInfo)).contents
        value.base=address;value.region_size=4096;value.state=0x1000;value.protect=4
        return size


def test_memory_reader_opens_only_read_rights_and_releases_handle(tmp_path,monkeypatch):
    kernel=FakeKernel(tmp_path/'Cordycep.CLI.exe')
    monkeypatch.setattr(cordycep,'_kernel',lambda:kernel)
    with cordycep.MemoryReader(321,tmp_path) as reader:
        assert reader.read(NODE,8)==b'AAAAAAAA'
        assert reader.region(NODE)==(NODE,4096,True)
        assert reader.created==1000
    assert kernel.opened==[(0x0410,False,321)]
    assert kernel.closed==[91]
    reader.close()
    assert kernel.closed==[91]


@pytest.mark.parametrize('image',['elsewhere/Cordycep.CLI.exe','not-a-loader.exe'])
def test_memory_reader_rejects_unrelated_process_path(tmp_path,monkeypatch,image):
    kernel=FakeKernel(tmp_path/image)
    monkeypatch.setattr(cordycep,'_kernel',lambda:kernel)
    with pytest.raises(ValueError,match='PID'):cordycep.MemoryReader(321,tmp_path)
    assert kernel.closed==[91]


@pytest.mark.parametrize('address,size',[(0,8),(True,8),(NODE,0),(NODE,8*1024*1024+1),((1<<47)-2,8)])
def test_memory_read_rejects_invalid_bounds_before_windows_call(tmp_path,monkeypatch,address,size):
    kernel=FakeKernel(tmp_path/'Cordycep.CLI.exe')
    monkeypatch.setattr(cordycep,'_kernel',lambda:kernel)
    with cordycep.MemoryReader(321,tmp_path) as reader:
        with pytest.raises(ValueError):reader.read(address,size)


def test_short_process_read_is_never_returned_as_full_record(tmp_path,monkeypatch):
    kernel=FakeKernel(tmp_path/'Cordycep.CLI.exe');kernel.short_read=True
    monkeypatch.setattr(cordycep,'_kernel',lambda:kernel)
    with cordycep.MemoryReader(321,tmp_path) as reader:
        with pytest.raises(ValueError,match='不完整'):reader.read(NODE,96)


class Blocks:
    def __init__(self,blocks):self.blocks=blocks;self.reads=[]
    def read(self,address,size):
        self.reads.append((address,size))
        for base,blob in self.blocks.items():
            if base<=address and address+size<=base+len(blob):
                return blob[address-base:address-base+size]
        raise ValueError('fake unreadable memory')
    def region(self,address):return address,0,False


def node(*,next_node=0,key=1,kind=6,header=HEADER,temp=0,size=16):
    return struct.pack('<12Q',header,temp,next_node,0,key,kind,size,0,0,0,0,0)


def pool_memory(nodes,root=NODE,end=0,pool=6):
    return Blocks({TABLE+pool*40:struct.pack('<5Q',root,end,0,0,0),**nodes})


def test_walk_preserves_full_uint64_skips_sentinel_and_temporary_node():
    raw=(1<<63)+17
    memory=pool_memory({NODE:node(header=0,key=0,kind=0xffffffff,next_node=NODE+96),
        NODE+96:node(key=raw,next_node=NODE+192),NODE+192:node(key=23,temp=1)},end=NODE+192)
    keys,digest=cordycep.walk_pool(memory,TABLE,6)
    assert keys=={raw} and len(digest)==64


@pytest.mark.parametrize('failure',['cycle','kind','key','header','size','limit','empty_end'])
def test_walk_rejects_corrupt_pool_instead_of_certifying_partial_keys(failure):
    item=node()
    if failure=='cycle':item=node(next_node=NODE)
    if failure=='kind':item=node(kind=7)
    if failure=='key':item=node(key=0)
    if failure=='header':item=node(header=1)
    if failure=='size':item=node(size=256*1024*1024+1)
    memory=pool_memory({NODE:item},root=0 if failure=='empty_end' else NODE,end=NODE if failure=='empty_end' else 0)
    with pytest.raises(ValueError):cordycep.walk_pool(memory,TABLE,6,limit=0 if failure=='limit' else 2000000)


def test_walk_rejects_pool_boundaries_changed_during_read():
    memory=pool_memory({NODE:node()});original=memory.read;calls=0
    def read(address,size):
        nonlocal calls
        if address==TABLE+6*40:
            calls+=1
            if calls>1:return struct.pack('<5Q',NODE,99,0,0,0)
        return original(address,size)
    memory.read=read
    with pytest.raises(ValueError,match='改变'):cordycep.walk_pool(memory,TABLE,6)


def test_walk_stop_does_not_return_a_partially_verified_set():
    with pytest.raises(InterruptedError):
        cordycep.walk_pool(pool_memory({NODE:node()}),TABLE,6,control=lambda:'stop')


def test_page_cache_falls_back_when_old_partial_region_does_not_cover_later_read():
    memory=Blocks({0x10000:b'A'*64,0x10200:b'B'*8})
    memory.region=lambda address:(0x10000,64,True)
    cached=cordycep._PageReader(memory)
    assert cached.read(0x10010,8)==b'A'*8
    assert cached.read(0x10200,8)==b'B'*8
    assert memory.reads==[(0x10000,64),(0x10200,8)]


def test_page_cache_cross_page_record_is_read_exactly():
    memory=Blocks({0x1fff0:b'C'*96});cached=cordycep._PageReader(memory)
    assert cached.read(0x1fff0,96)==b'C'*96
    assert memory.reads==[(0x1fff0,96)]


def test_strings_reassemble_chunk_boundary_and_discard_invalid_or_long_fragments():
    blob=b'X'*(1024*1024-5)+b'\0weapon_alpha\0sound_beta\0bad\xffutf8\0a\tbcd\0'
    memory=Blocks({STRINGS:blob});memory.region=lambda address:(STRINGS,len(blob),True)
    names,info=cordycep.read_strings(memory,STRINGS)
    assert names=={'weapon_alpha','sound_beta'}
    assert info['complete'] and info['bytes']==len(blob) and info['dropped_fragments']>=1


def test_overlong_unterminated_string_never_becomes_a_valid_suffix_in_next_chunk():
    blob=b'Z'*(1024*1024+20)+b'weapon_fake\0weapon_real\0'
    memory=Blocks({STRINGS:blob});memory.region=lambda address:(STRINGS,len(blob),True)
    names,info=cordycep.read_strings(memory,STRINGS)
    assert names=={'weapon_real'} and info['dropped_fragments']>=1


def test_strings_recorded_size_and_limit_are_explicit_candidate_scope():
    blob=b'first_name\0second_name\0';memory=Blocks({STRINGS:blob})
    memory.region=lambda address:(STRINGS,len(blob),True)
    names,info=cordycep.read_strings(memory,STRINGS,recorded_size=11)
    assert names=={'first_name'} and info['bytes']==11 and info['recorded_size']==11
    names,info=cordycep.read_strings(memory,STRINGS,limit=11)
    assert names=={'first_name'} and not info['complete']
    with pytest.raises(ValueError):cordycep.read_strings(memory,STRINGS,recorded_size=len(blob)+1)
    with pytest.raises(InterruptedError):cordycep.read_strings(memory,STRINGS,control=lambda:'stop')


def state_reader(root):
    return SimpleNamespace(pid=321,created=1000,image=root/'Cordycep.CLI.exe')


def write_state(root,**changes):
    (root/'Data').mkdir(exist_ok=True)
    state={'pid':321,'game_id':'MODWAR7\0','pools_addr':TABLE,'strings_addr':STRINGS,'flags':['beta'],**changes}
    path=root/'Data/CurrentHandler.json';path.write_text(json.dumps(state),encoding='utf-8')
    os.utime(path,(1000,1000));return path


def csi(root,*,game=b'MODWAR7\0',suffix=b''):
    (root/'Data').mkdir(exist_ok=True)
    path=root/'Data/CurrentHandler.csi';path.write_bytes(game+struct.pack('<QQ',TABLE,STRINGS)+suffix)
    os.utime(path,(1000,1000));return path


def text_field(value):
    raw=value.encode('utf-8');return struct.pack('<I',len(raw))+raw


def test_json_state_is_bound_to_pid_start_time_and_validated_pointers(tmp_path):
    path=write_state(tmp_path)
    state=cordycep.handler_state(tmp_path,state_reader(tmp_path))
    assert state['game_id']=='MODWAR7' and state['state_file']==str(path.resolve())
    write_state(tmp_path,pools_addr=1)
    with pytest.raises(ValueError):cordycep.handler_state(tmp_path,state_reader(tmp_path))
    write_state(tmp_path);os.utime(path,(990,990))
    with pytest.raises(ValueError,match='过期'):cordycep.handler_state(tmp_path,state_reader(tmp_path))


def test_authoritative_fresh_json_pid_mismatch_never_falls_back_to_anonymous_csi(tmp_path):
    write_state(tmp_path,pid=999);csi(tmp_path)
    with pytest.raises(ValueError,match='PID'):cordycep.handler_state(tmp_path,state_reader(tmp_path))


def test_stale_other_pid_json_allows_fresh_local_csi_with_full_extension(tmp_path):
    path=write_state(tmp_path,pid=999);os.utime(path,(990,990))
    csi(tmp_path,suffix=text_field('E:/game files/测试')+struct.pack('<I',2)+text_field('beta')+text_field('eng'))
    state=cordycep.handler_state(tmp_path,state_reader(tmp_path))
    assert state['anonymous_state'] and state['pid']==321
    assert state['flags']==['beta','eng'] and state['game_dir']=='E:/game files/测试'


@pytest.mark.parametrize('suffix',[
    b'\x01',struct.pack('<I',32769),text_field('game'),
    text_field('game')+struct.pack('<I',65),
    text_field('game')+struct.pack('<I',1)+struct.pack('<I',3)+b'\xff\xff\xff',
    text_field('game')+struct.pack('<I',0)+b'trailer'])
def test_csi_invalid_extensions_are_rejected(tmp_path,suffix):
    csi(tmp_path,suffix=suffix)
    with pytest.raises((ValueError,UnicodeError)):cordycep.handler_state(tmp_path,state_reader(tmp_path))


def test_csi_legacy_header_is_read_only_and_cannot_bind_another_executable(tmp_path):
    csi(tmp_path);reader=state_reader(tmp_path)
    assert cordycep.handler_state(tmp_path,reader)['anonymous_state']
    reader.image=tmp_path/'Cordycep.exe'
    with pytest.raises(ValueError):cordycep.handler_state(tmp_path,reader)


def build_fingerprints(monkeypatch,root,game='COD2026'):
    profile=cordycep._profiles(game)
    loader=json.loads(Path(cordycep.__file__).with_name('cordycep_profiles.json').read_text(encoding='utf-8'))['loader']['sha256']
    fingerprints={str((root/'Cordycep.CLI.exe').resolve()):loader,
        str((root/'Data/Configs'/profile['config']).resolve()):profile['config_sha256'],
        str((root/profile['module']).resolve()):profile['module_sha256']}
    monkeypatch.setattr(cordycep,'_fingerprint_file',lambda path:fingerprints[str(Path(path).resolve())])
    return profile,fingerprints


@pytest.mark.parametrize('changed',['loader','configuration','module','module_path','beta'])
def test_build_binding_rejects_incorrect_version_or_game_module(tmp_path,monkeypatch,changed):
    profile,hashes=build_fingerprints(monkeypatch,tmp_path)
    state={'flags':['beta']};reader=state_reader(tmp_path)
    assert cordycep.validate_local_build(tmp_path,'COD2026',state,reader)==profile
    target={'loader':reader.image,'configuration':tmp_path/'Data/Configs'/profile['config'],
        'module':tmp_path/profile['module']}.get(changed)
    if target:hashes[str(target.resolve())]='0'*64
    elif changed=='module_path':state['game_module_path']=str(tmp_path/'different.exe')
    else:state['flags']=[]
    with pytest.raises(ValueError):cordycep.validate_local_build(tmp_path,'COD2026',state,reader)


def supported_pools(profile):
    pools={int(pool):dict(row,count=0,stable=True,errors=[]) for pool,row in profile['pools'].items()}
    for pool in profile['excluded_model_pool_ids']:
        pools[pool]={'kind':'xmodel','profile':None,'key_width':64,'stored_mask':'ffffffffffffffff',
            'count':0,'stable':True,'errors':[],'excluded':True}
    return pools


def test_writer_preserves_raw64_and_separates_lossy_legacy_interchange(tmp_path):
    profile=cordycep._profiles('COD2026');pools=supported_pools(profile)
    pools[6]['count']=2
    pools[42]={'kind':None,'profile':None,'key_width':64,'stored_mask':'ffffffffffffffff',
        'count':1,'stable':False,'errors':['unclassified churn']}
    state={'pid':321,'game_id':'MODWAR7','_capture_state_stable':True}
    result=cordycep._write_snapshot(tmp_path/'capture','COD2026',state,profile,pools,
        {(17,6),((1<<63)+17,6),(23,42)},{'weapon_alpha'},
        {'bytes':65536,'complete':False},True,'supported scope stable',['current loaded test.ff'])
    snapshot=read_snapshot(result['snapshot_file'])
    assert snapshot['records']==[(17,6),(23,42),((1<<63)+17,6)]
    assert len(snapshot['verified_scope_pools'])==16 and not snapshot['whole_snapshot_stable']
    assert snapshot['loaded_scope']==['current loaded test.ff']
    assert snapshot['pools'][7]['kind']=='xmodel' and snapshot['pools'][42]['profile'] is None
    manifest=json.loads(Path(result['snapshot_file']).read_text(encoding='utf-8'))
    assert manifest['strings']['bytes']==Path(snapshot['strings_path']).stat().st_size
    assert manifest['strings']['source_read_bytes']==65536
    legacy=read_snapshot(result['legacy_ids'])
    assert legacy['key_width']==63 and legacy['records']==[(17,6),(23,42)]


def capture_fakes(monkeypatch,root,*,change=None,failed_pool=None):
    profile=cordycep._profiles('COD2026');seen=[];closed=[];state_calls=[]
    state={'pid':321,'game_id':'MODWAR7','pools_addr':TABLE,'strings_addr':STRINGS,'flags':['beta']}
    class Reader:
        def __init__(self,pid,directory):self.pid=pid;self.image=root/'Cordycep.CLI.exe';self.table_reads=0
        def __enter__(self):return self
        def __exit__(self,*args):closed.append(self.pid)
        def read(self,address,size):
            assert address==TABLE and size==512*40
            self.table_reads+=1;blob=bytearray(size)
            if self.table_reads>1 and isinstance(change,int):blob[change*40]=1
            return bytes(blob)
    def handler(directory,reader):
        state_calls.append(1);result=dict(state)
        if len(state_calls)>1 and change=='state':result['strings_addr']+=0x10000
        return result
    def walk(reader,address,pool,control):
        seen.append(pool)
        if pool==failed_pool:raise ValueError('fake pool instability')
        return ({(1<<63)+17} if pool==6 else set()),'stable'
    monkeypatch.setattr(cordycep,'MemoryReader',Reader)
    monkeypatch.setattr(cordycep,'discover',lambda directory,pid=None:{'instances':[{'pid':321,'game_id':'MODWAR7'}],'errors':[]})
    monkeypatch.setattr(cordycep,'handler_state',handler)
    monkeypatch.setattr(cordycep,'validate_local_build',lambda *args:profile)
    monkeypatch.setattr(cordycep,'walk_pool',walk)
    monkeypatch.setattr(cordycep,'read_strings',lambda *args,**kwargs:({'weapon_alpha'},{'bytes':65536,'complete':True}))
    monkeypatch.setattr(cordycep.time,'sleep',lambda duration:None)
    return seen,closed


def test_attached_capture_never_starts_or_terminates_user_loader_and_excludes_models(tmp_path,monkeypatch):
    seen,closed=capture_fakes(monkeypatch,tmp_path,failed_pool=42)
    def forbidden(*args,**kwargs):raise AssertionError('attached instance must never be managed as an owned child')
    monkeypatch.setattr(cordycep,'LoaderSession',forbidden)
    monkeypatch.setattr(cordycep.subprocess,'Popen',forbidden)
    result=cordycep.capture(tmp_path,'COD2026',tmp_path/'output',pid=321)
    assert result['complete'] and closed==[321]
    assert 7 not in seen and 8 not in seen and Counter(seen)[42]==3
    snapshot=read_snapshot(result['snapshot_file'])
    assert snapshot['records']==[((1<<63)+17,6)]
    assert snapshot['pools'][42]['errors'] and len(snapshot['verified_scope_pools'])==16


@pytest.mark.parametrize('change,failed_pool,complete',[('state',None,False),(6,None,False),(42,None,True),(None,6,False)])
def test_capture_rechecks_state_and_certifies_only_mapped_stable_scope(tmp_path,monkeypatch,change,failed_pool,complete):
    capture_fakes(monkeypatch,tmp_path,change=change,failed_pool=failed_pool)
    result=cordycep.capture(tmp_path,'COD2026',tmp_path/'output',pid=321)
    assert result['complete'] is complete
    manifest=json.loads(Path(result['snapshot_file']).read_text(encoding='utf-8'))
    assert manifest['state_stable'] is (change!='state')
    if complete:assert read_snapshot(result['snapshot_file'])['complete']
    else:
        with pytest.raises(ValueError,match='完整'):read_snapshot(result['snapshot_file'])


def test_stopped_capture_preserves_diagnostic_files_without_certifying_them(tmp_path,monkeypatch):
    _,closed=capture_fakes(monkeypatch,tmp_path)
    result=cordycep.capture(tmp_path,'COD2026',tmp_path/'output',pid=321,control=lambda:'stop')
    assert result['status']=='stopped' and not result['complete'] and closed==[321]
    assert Path(result['snapshot_file']).is_file()
    with pytest.raises(ValueError,match='完整'):read_snapshot(result['snapshot_file'])


def test_stopping_during_optional_strings_keeps_stable_keys_diagnostic_only(tmp_path,monkeypatch):
    _,closed=capture_fakes(monkeypatch,tmp_path);control=['run']
    def strings(*args,**kwargs):
        control[0]='stop'
        raise InterruptedError('fake stop in strings')
    monkeypatch.setattr(cordycep,'read_strings',strings)
    result=cordycep.capture(tmp_path,'COD2026',tmp_path/'output',pid=321,control=lambda:control[0])
    assert result['status']=='stopped' and result['records']==1 and not result['complete'] and closed==[321]
    with pytest.raises(ValueError,match='完整'):read_snapshot(result['snapshot_file'])


@pytest.mark.parametrize('game,handler,flag',[('COD2026','mw7','setflag beta '),('BO7','bo7','')])
def test_startup_arguments_are_an_argument_vector_with_quoted_game_path(tmp_path,game,handler,flag):
    game_path=tmp_path/'game files';game_path.mkdir()
    script=tmp_path/cordycep._SCRIPTS[game]
    script.write_text(f'Cordycep.CLI.exe sethandler {handler} {flag}init "{game_path}" setlocaleprefix eng_ loadcommonfiles',encoding='utf-8')
    args=cordycep.launch_arguments(tmp_path,game)
    assert args[0]==str(tmp_path/'Cordycep.CLI.exe') and str(game_path) in args
    assert args[-1]=='loadcommonfiles'


@pytest.mark.parametrize('extra',[' & calc.exe',' | other.exe','\nother.exe',' %PATH%',' > output.txt'])
def test_startup_script_shell_expansion_or_multiple_commands_are_rejected(tmp_path,extra):
    (tmp_path/'RunMW7Beta.bat').write_text('Cordycep.CLI.exe sethandler mw7 setflag beta init "x" setlocaleprefix eng_ loadcommonfiles'+extra,encoding='utf-8')
    with pytest.raises(ValueError):cordycep.launch_arguments(tmp_path,'COD2026')


class Pipe:
    def __init__(self):self.writes=[];self.closed=False
    def write(self,data):self.writes.append(data)
    def flush(self):pass
    def close(self):self.closed=True


class Child:
    pid=765
    def __init__(self,*,exit_code=None,timeout=False):
        self.returncode=exit_code;self.stdin=Pipe();self.stdout=Pipe();self.terminated=False;self.timeout=timeout
    def poll(self):return self.returncode
    def wait(self,timeout):
        if self.timeout and not self.terminated:raise subprocess.TimeoutExpired('fake owned loader',timeout)
        self.returncode=0;return 0
    def terminate(self):self.terminated=True


@pytest.mark.parametrize('chunks',[
    [b'loading\r\nCordy',b'cep > '],
    [b'loading\r\n',b'\x1b[32m> \x1b[0m'],
    [b'loading\r\nEnter a ',b'command: ']])
def test_prompt_confirmation_supports_chunked_and_ansi_local_prompts(tmp_path,chunks):
    session=cordycep.LoaderSession(tmp_path,'COD2026',lambda *args:None,lambda:'run')
    session.child=Child()
    for chunk in chunks:session.lines.put(chunk)
    session._wait_prompt(1)
    assert session.output_tail.endswith(chunks[-1])


@pytest.mark.parametrize('reason',['exit','eof','stop'])
def test_no_prompt_never_confirms_loading(tmp_path,reason):
    session=cordycep.LoaderSession(tmp_path,'COD2026',lambda *args:None,lambda:'stop' if reason=='stop' else 'run')
    session.child=Child(exit_code=1 if reason=='exit' else None)
    if reason=='eof':session.lines.put(None)
    with pytest.raises(InterruptedError if reason=='stop' else ValueError):session._wait_prompt(1)


@pytest.mark.parametrize('timeout',[False,True])
def test_session_close_manages_only_its_own_child_and_reaps_pipes(tmp_path,timeout):
    session=cordycep.LoaderSession(tmp_path,'COD2026',lambda *args:None,lambda:'run');session.child=Child(timeout=timeout)
    session.close()
    assert session.child.stdin.writes==[b'exit\r\n']
    assert session.child.terminated is timeout
    assert session.child.stdin.closed and session.child.stdout.closed
    session.close()
    assert session.child.stdin.writes==[b'exit\r\n']
