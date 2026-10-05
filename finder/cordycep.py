"""Read-only Cordycep capture and a portable snapshot file boundary.

This is an independent implementation of the loader's public state/layout
contract. No process writes, injections or game-function calls are used.
"""
from collections import Counter, OrderedDict
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime,timezone
import csv
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import struct
import subprocess
import sys
import threading
import time
import uuid

POOL_COUNT=512
POOL_STRIDE=40
NODE_SIZE=96
LAYOUT_ID='cordycep-pool40-node96-v1'
_EXECUTABLES=frozenset(('cordycep.exe','cordycep.cli.exe'))
_GAME_IDS={'COD2026':('MODWAR7',),'BO7':('BLACKOP7',)}
_SCRIPTS={'COD2026':'RunMW7Beta.bat','BO7':'RunBO7.bat'}


def _pointer(value,size=1):
    if type(value) is not int or value<0x10000 or size<1 or value+size>0x0000800000000000:
        raise ValueError('Cordycep 提供了无效的64位内存地址')
    return value


class _ProcessEntry(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('usage',wintypes.DWORD),('pid',wintypes.DWORD),
        ('heap',ctypes.c_size_t),('module',wintypes.DWORD),('threads',wintypes.DWORD),
        ('parent',wintypes.DWORD),('priority',wintypes.LONG),('flags',wintypes.DWORD),
        ('name',wintypes.WCHAR*260)]


class _MemoryInfo(ctypes.Structure):
    _fields_=[('base',ctypes.c_void_p),('allocation',ctypes.c_void_p),('allocation_protect',wintypes.DWORD),
        ('region_size',ctypes.c_size_t),('state',wintypes.DWORD),('protect',wintypes.DWORD),('type',wintypes.DWORD)]


def _kernel():
    if os.name!='nt' or ctypes.sizeof(ctypes.c_void_p)!=8:
        raise ValueError('Cordycep 捕获需要64位 Windows；离线快照计算不需要加载器')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    signatures={
        'OpenProcess':([wintypes.DWORD,wintypes.BOOL,wintypes.DWORD],wintypes.HANDLE),
        'CloseHandle':([wintypes.HANDLE],wintypes.BOOL),
        'ReadProcessMemory':([wintypes.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)],wintypes.BOOL),
        'VirtualQueryEx':([wintypes.HANDLE,ctypes.c_void_p,ctypes.POINTER(_MemoryInfo),ctypes.c_size_t],ctypes.c_size_t),
        'QueryFullProcessImageNameW':([wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)],wintypes.BOOL),
        'GetProcessTimes':([wintypes.HANDLE,ctypes.POINTER(wintypes.FILETIME),ctypes.POINTER(wintypes.FILETIME),ctypes.POINTER(wintypes.FILETIME),ctypes.POINTER(wintypes.FILETIME)],wintypes.BOOL),
        'CreateToolhelp32Snapshot':([wintypes.DWORD,wintypes.DWORD],wintypes.HANDLE),
        'Process32FirstW':([wintypes.HANDLE,ctypes.POINTER(_ProcessEntry)],wintypes.BOOL),
        'Process32NextW':([wintypes.HANDLE,ctypes.POINTER(_ProcessEntry)],wintypes.BOOL),
    }
    for name,(args,result) in signatures.items():
        function=getattr(kernel,name);function.argtypes=args;function.restype=result
    return kernel


class MemoryReader:
    """Only QUERY_INFORMATION and VM_READ rights on a validated loader image."""
    def __init__(self,pid,directory):
        self.kernel=_kernel();self.handle=None;self.pid=int(pid)
        handle=self.kernel.OpenProcess(0x0410,False,self.pid)
        if not handle:raise ValueError(f'无法只读访问 Cordycep PID {pid}（Windows错误 {ctypes.get_last_error()}）；请核对实例和运行权限')
        self.handle=handle
        try:
            text=ctypes.create_unicode_buffer(32768);length=wintypes.DWORD(len(text))
            if not self.kernel.QueryFullProcessImageNameW(handle,0,text,ctypes.byref(length)):
                raise ValueError('无法核对 Cordycep 进程路径')
            self.image=Path(text.value).resolve()
            if self.image.name.lower() not in _EXECUTABLES or self.image.parent!=Path(directory).resolve():
                raise ValueError('状态文件 PID 不属于所选目录中的 Cordycep 实例')
            times=[wintypes.FILETIME() for _ in range(4)]
            if not self.kernel.GetProcessTimes(handle,*[ctypes.byref(item) for item in times]):
                raise ValueError('无法核对 Cordycep 实例启动时间')
            self.created=((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime)/10000000-11644473600
        except Exception:
            self.close();raise

    def read(self,address,size):
        _pointer(address,size)
        if size>8*1024*1024:raise ValueError('单次内存读取超过界限')
        buffer=ctypes.create_string_buffer(size);count=ctypes.c_size_t()
        if not self.kernel.ReadProcessMemory(self.handle,address,buffer,size,ctypes.byref(count)) or count.value!=size:
            raise ValueError(f'资产池读取不完整：地址0x{address:x}，需要{size}字节，读取{count.value}字节')
        return buffer.raw

    def region(self,address):
        _pointer(address);info=_MemoryInfo()
        if not self.kernel.VirtualQueryEx(self.handle,address,ctypes.byref(info),ctypes.sizeof(info)):
            raise ValueError('无法查询字符串池内存范围')
        readable=info.state==0x1000 and not info.protect&(0x100|0x01) and bool(info.protect&0xfe)
        return int(info.base or 0),int(info.region_size),readable

    def close(self):
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None
    def __enter__(self):return self
    def __exit__(self,*_):self.close()


class _PageReader:
    def __init__(self,reader):self.reader=reader;self.pages=OrderedDict()
    def read(self,address,size):
        _pointer(address,size);base=address&~65535;offset=address-base
        if offset+size>65536:return self.reader.read(address,size)
        blob=self.pages.get(base)
        if blob is None:
            try:
                region,length,readable=self.reader.region(address)
                if not readable or base<region:return self.reader.read(address,size)
                amount=min(65536,region+length-base)
                if amount<offset+size:return self.reader.read(address,size)
                blob=self.reader.read(base,amount)
            except ValueError:return self.reader.read(address,size)
            self.pages[base]=blob
            if len(self.pages)>512:self.pages.popitem(last=False)
        else:
            self.pages.move_to_end(base)
            if len(blob)<offset+size:return self.reader.read(address,size)
        return blob[offset:offset+size]


def process_ids():
    kernel=_kernel();handle=kernel.CreateToolhelp32Snapshot(2,0)
    if handle in (None,ctypes.c_void_p(-1).value):raise ValueError('无法枚举 Cordycep 实例')
    try:
        entry=_ProcessEntry();entry.size=ctypes.sizeof(entry);result=[]
        valid=kernel.Process32FirstW(handle,ctypes.byref(entry))
        while valid:
            if entry.name.lower() in _EXECUTABLES:result.append(int(entry.pid))
            valid=kernel.Process32NextW(handle,ctypes.byref(entry))
        return result
    finally:kernel.CloseHandle(handle)


def _game_id(value):
    if isinstance(value,int) and 0<=value<1<<64:value=value.to_bytes(8,'little').decode('ascii')
    if not isinstance(value,str):raise ValueError('Cordycep 游戏ID无效')
    value=value.rstrip('\x00 ')
    if not re.fullmatch(r'[A-Z0-9_-]{1,16}',value):raise ValueError('Cordycep 游戏ID无效')
    return value


def handler_state(directory,reader):
    root=Path(directory)/'Data';json_path=root/'CurrentHandler.json';binary_path=root/'CurrentHandler.csi'
    if json_path.is_file():
        try:state=json.loads(json_path.read_text(encoding='utf-8-sig'))
        except (ValueError,OSError) as error:raise ValueError('Cordycep 正在更新状态文件，请加载结束后重试') from error
        if not isinstance(state,dict) or any(key not in state for key in ('pid','game_id','pools_addr','strings_addr')):
            raise ValueError('Cordycep 状态文件缺少必要字段，请等待加载完成')
        if type(state['pid']) is not int or state['pid']<=0:
            raise ValueError('Cordycep 状态文件 PID 无效')
        if not isinstance(state.get('flags',[]),list) or any(not isinstance(flag,str) for flag in state.get('flags',[])):
            raise ValueError('Cordycep 状态文件标记无效')
        if state.get('pid')==reader.pid:
            if json_path.stat().st_mtime<reader.created-2:raise ValueError('Cordycep 状态文件早于当前实例，拒绝使用过期地址')
            state={**state,'game_id':_game_id(state['game_id']),'state_file':str(json_path.resolve())}
            _pointer(state['pools_addr'],POOL_COUNT*POOL_STRIDE);_pointer(state['strings_addr'])
            return state
        # PID-bearing JSON is authoritative; do not use anonymous CSI to hide a mismatch.
        if json_path.stat().st_mtime>=reader.created-2:
            raise ValueError('Cordycep 状态文件属于另一个 PID，请选择对应实例')
    if reader.image.name.lower()!='cordycep.cli.exe' or not binary_path.is_file():
        raise ValueError('Cordycep 尚未加载游戏，或没有属于当前实例的状态文件')
    if binary_path.stat().st_mtime<reader.created-2:raise ValueError('Cordycep CLI 状态过期，请重新初始化加载器')
    raw=binary_path.read_bytes()
    if len(raw)<24:raise ValueError('Cordycep CLI 状态文件不完整')
    game=_game_id(raw[:8].decode('ascii'));pools,strings=struct.unpack_from('<QQ',raw,8)
    _pointer(pools,POOL_COUNT*POOL_STRIDE);_pointer(strings)
    state={'pid':reader.pid,'game_id':game,'pools_addr':pools,'strings_addr':strings,
        'flags':[],'state_file':str(binary_path.resolve()),'anonymous_state':True}
    if len(raw)>24:
        offset=24
        def text_field():
            nonlocal offset
            if offset+4>len(raw):raise ValueError('Cordycep CLI 扩展状态不完整')
            length=struct.unpack_from('<I',raw,offset)[0];offset+=4
            if length>32768 or offset+length>len(raw):raise ValueError('Cordycep CLI 扩展状态长度无效')
            value=raw[offset:offset+length].decode('utf-8');offset+=length
            return value
        state['game_dir']=text_field()
        if offset+4>len(raw):raise ValueError('Cordycep CLI 标记列表不完整')
        count=struct.unpack_from('<I',raw,offset)[0];offset+=4
        if count>64:raise ValueError('Cordycep CLI 标记数量无效')
        state['flags']=[text_field() for _ in range(count)]
        if offset!=len(raw):raise ValueError('Cordycep CLI 状态包含未知扩展，需更新适配')
    return state


def discover(directory,pid=None):
    directory=Path(directory).resolve(strict=True)
    candidates=[int(pid)] if pid else process_ids();instances=[];errors=[]
    for candidate in candidates:
        try:
            with MemoryReader(candidate,directory) as reader:
                state=handler_state(directory,reader)
                instances.append({'pid':candidate,'game_id':state['game_id'],'executable':str(reader.image),
                    'game_dir':state.get('game_dir',''),'flags':state.get('flags',[]),'state_file':state['state_file']})
        except ValueError as error:errors.append({'pid':candidate,'message':str(error)})
    return {'instances':instances,'errors':errors,'directory':str(directory)}


def _check(control):
    if control()!='run':raise InterruptedError('已停止捕获，已读取部分会保存为不完整快照')


def walk_pool(reader,address,pool,control=lambda:'run',limit=2000000):
    """Return raw keys only after linked-list, kind and header sanity checks."""
    base=_pointer(address,POOL_COUNT*POOL_STRIDE)+pool*POOL_STRIDE
    before=reader.read(base,POOL_STRIDE);root,end,_,_,_=struct.unpack('<5Q',before)
    if not root:
        if end:raise ValueError(f'池 {pool} 的空表首尾不一致')
        return set(),hashlib.sha256(before[:16]).hexdigest()
    cached=_PageReader(reader);seen=set();keys=set();node=root
    while node:
        if len(seen)%1024==0:_check(control)
        if node in seen:raise ValueError(f'池 {pool} 链表循环')
        if len(seen)>=limit:raise ValueError(f'池 {pool} 超过读取上限，快照不完整')
        seen.add(node);fields=struct.unpack('<12Q',cached.read(node,NODE_SIZE))
        header,temp,next_node,previous,key,kind,header_size,*_=fields
        if header and not temp:
            _pointer(header)
            if kind!=pool:raise ValueError(f'池 {pool} 节点类型 {kind} 不匹配，不能按错误布局捕获')
            if not key or header_size>256*1024*1024:raise ValueError(f'池 {pool} 节点布局无效')
            keys.add(key)
        node=next_node
    after=reader.read(base,POOL_STRIDE)
    if after[:16]!=before[:16]:raise ValueError(f'池 {pool} 在捕获中改变，请等待加载结束')
    digest=hashlib.sha256(before[:16]+b''.join(struct.pack('<Q',key) for key in sorted(keys))).hexdigest()
    return keys,digest


def read_strings(reader,address,control=lambda:'run',limit=256*1024*1024,recorded_size=None):
    """Read only the declared contiguous readable string region; clues are unverified."""
    base,size,readable=reader.region(address)
    if not readable:raise ValueError('字符串池地址不可读')
    available=base+size-address
    if recorded_size is not None:
        if not isinstance(recorded_size,int) or not 0<recorded_size<=available:raise ValueError('字符串池已记录长度与可读内存范围不一致')
        available=recorded_size
    length=min(available,limit);names=set();carry=b'';offset=0;dropped=0;discarding=False
    while offset<length:
        _check(control);amount=min(1024*1024,length-offset)
        data=carry+reader.read(address+offset,amount);parts=data.split(b'\0');carry=parts.pop()
        if discarding:
            if parts:parts.pop(0);discarding=False
            else:carry=b''
        for part in parts:
            if not 4<=len(part)<=1024:continue
            try:value=part.decode('utf-8')
            except UnicodeDecodeError:dropped+=1;continue
            if all(c.isprintable() for c in value) and not any(c in value for c in '\r\n\t'):
                names.add(value)
        if len(carry)>1024:carry=b'';dropped+=1;discarding=True
        offset+=amount
    return names,{'bytes':length,'complete':available<=limit,'recorded_size':recorded_size,'dropped_fragments':dropped,
        'scope':'loader string-pool readable region; candidate clues only'}


def _profiles(game):
    path=Path(__file__).with_name('cordycep_profiles.json')
    if not path.is_file():raise ValueError('软件缺少 Cordycep 作品适配资料')
    data=json.loads(path.read_text(encoding='utf-8'))
    if game not in data['profiles']:raise ValueError('请选择已适配的 Cordycep 作品')
    return data['profiles'][game]


def _fingerprint_file(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def validate_local_build(directory,game,state,reader):
    """A numeric pool label is accepted only for the researched local build."""
    profile=_profiles(game);root=Path(directory).resolve()
    data=json.loads(Path(__file__).with_name('cordycep_profiles.json').read_text(encoding='utf-8'))
    layout=data.get('layout',{})
    expected_pools={'root':0,'end':8,'lookup_table':16,'header_memory':24,'asset_memory':32}
    expected_nodes={'header':0,'temp':8,'next':16,'previous':24,'raw_id':32,'kind':40,'header_size':48,
        'extended_data_pointer_offset':56,'extended_data_size':64,'first_child':72,'last_child':80,'owner':88}
    if (layout.get('id',LAYOUT_ID)!=LAYOUT_ID or layout.get('pool_count')!=POOL_COUNT
        or layout.get('pool_stride')!=POOL_STRIDE or layout.get('node_prefix_size')!=NODE_SIZE
        or layout.get('pool_fields')!=expected_pools or layout.get('node_fields')!=expected_nodes):
        raise ValueError('Cordycep 资产池布局适配与当前读取器不一致，请更新完整软件')
    try:loader_sha=_fingerprint_file(reader.image)
    except OSError as error:raise ValueError('无法核对本地 Cordycep 程序指纹') from error
    builds=data.get('loader_builds')
    if builds is None:
        legacy=data['loader'];builds=[{**legacy,'adapter':LAYOUT_ID,'games':{
            name:{field:row[field] for field in ('config_sha256','module_sha256')}
            for name,row in data['profiles'].items()}}]
    if not isinstance(builds,list) or any(not isinstance(build,dict) for build in builds):
        raise ValueError('Cordycep 版本适配资料无效')
    matches=[build for build in builds if build.get('sha256')==loader_sha]
    if len(matches)!=1:
        raise ValueError('Cordycep 程序指纹不属于唯一已适配版本：'+loader_sha+'；请更新软件适配资料')
    build=matches[0];games=build.get('games');binding=games.get(game) if isinstance(games,dict) else None
    filename=build.get('filename')
    if (build.get('adapter')!=LAYOUT_ID or not isinstance(filename,str) or filename.lower()!=reader.image.name.lower()
        or not isinstance(binding,dict) or any(binding.get(field)!=profile[field] for field in ('config_sha256','module_sha256'))):
        raise ValueError('Cordycep 程序、作品模块与资产池布局的版本组合未获适配')
    configuration=root/'Data/Configs'/profile['config'];module=root/profile['module']
    try:matched=_fingerprint_file(configuration)==binding['config_sha256'] and _fingerprint_file(module)==binding['module_sha256']
    except OSError as error:raise ValueError('找不到可核对的作品配置或游戏模块，请检查所选 Cordycep 目录') from error
    if not matched:
        raise ValueError('作品配置或加载模块与已核实版本不同，拒绝套用旧池编号')
    if state.get('game_module_path') and Path(state['game_module_path']).resolve()!=module.resolve():
        raise ValueError('状态文件的游戏模块不属于所选作品配置')
    if game=='COD2026' and 'beta' not in state.get('flags',[]) and not state.get('anonymous_state'):
        raise ValueError('MW7 Beta 状态没有 beta 标记')
    state.update(loader_sha256=loader_sha,loader_file_version=build.get('file_version',''),loader_adapter=LAYOUT_ID)
    return profile


def _write_snapshot(destination,game,state,profile,pools,records,strings,string_info,complete,message,scope):
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=False)
    records_path=destination/'records.csv'
    with records_path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['raw_hash','type','pool'])
        writer.writerows((f'{key:016x}',pools[pool].get('kind') or '',pool) for key,pool in sorted(records))
    text_path=destination/'strings.txt';text_path.write_text(''.join(name+'\n' for name in sorted(strings)),encoding='utf-8')
    manifest={'format':'CODSNAP2','version':2,'game':game,'game_id':state['game_id'],
        'build':'sha256:'+profile['module_sha256'],'build_fingerprints':{
            'module_sha256':profile['module_sha256'],'config_sha256':profile['config_sha256']},
        'adapter':profile.get('adapter','cordycep-pool40-node96-v1'),
        'captured_at':datetime.now(timezone.utc).isoformat(),'raw_key_width':64,'complete':bool(complete),
        'message':message,'loaded_scope':scope,'pid':state['pid'],
        'records':{'file':'records.csv','sha256':hashlib.sha256(records_path.read_bytes()).hexdigest(),'count':len(records)},
        'strings':{'file':'strings.txt','sha256':hashlib.sha256(text_path.read_bytes()).hexdigest(),'count':len(strings),
            **string_info,'source_read_bytes':string_info.get('bytes',0),'bytes':text_path.stat().st_size},
        'pools':[{'pool':pool,**metadata} for pool,metadata in sorted(pools.items())],
        'loader':{'executable':state.get('executable',''),'state_file':state.get('state_file',''),
            'sha256':state.get('loader_sha256'),'file_version':state.get('loader_file_version'),
            'adapter':state.get('loader_adapter'),'startup_script':state.get('_startup_script'),
            'game_directory':state.get('game_dir',''),'flags':state.get('flags',[])},
        'key_policy':'raw uint64 retained; comparison domain and mask are per pool'}
    manifest['state_stable']=state.get('_capture_state_stable',False)
    manifest['verified_scope_pools']=sorted(int(p) for p in profile['pools'])
    manifest['whole_snapshot_stable']=all(row['stable'] and not row['errors'] for row in pools.values())
    manifest_path=destination/'snapshot.json';temporary=destination/'snapshot.json.tmp'
    temporary.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(manifest_path)
    with (destination/'pools-report.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['pool','kind','count','profile','key_width','stable','errors'])
        writer.writerows((pool,row.get('kind') or 'unknown',row['count'],row.get('profile') or '',row.get('key_width',64),row['stable'],'; '.join(row['errors'])) for pool,row in sorted(pools.items()))
    # Interchange copy for original tools. This file is explicitly masked63;
    # the lossless enhanced records remain the authoritative input here.
    legacy=sorted({(key&((1<<63)-1),pool) for key,pool in records});game_bytes=state['game_id'].encode('utf-8')
    legacy_counts=Counter(pool for _,pool in legacy)
    with (destination/'snapshot.pools.txt').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['pool','label','ids'])
        writer.writerows((pool,row.get('kind') or 'unknown',legacy_counts[pool])
            for pool,row in sorted(pools.items()) if row['count'])
    with (destination/'snapshot.ids').open('wb') as stream:
        stream.write(b'CODIDS'+struct.pack('<HH',1,len(game_bytes))+game_bytes+struct.pack('<Q',len(legacy)))
        for key,pool in legacy:stream.write(struct.pack('<QH',key,pool))
    return {'status':'completed' if complete else 'partial','snapshot_file':str(manifest_path),
        'records':len(records),'strings':len(strings),'complete':bool(complete),'message':message,
        'pid':state['pid'],'game':game,'legacy_ids':str(destination/'snapshot.ids')}


def capture(directory,game,output,pid=None,launch=False,load_all=False,progress=lambda *_:None,control=lambda:'run',script=None):
    directory=Path(directory).resolve(strict=True);profile=_profiles(game);owned=None
    if script and not launch:raise ValueError('选择 BAT 启动脚本时须使用启动模式；读取已有实例不运行脚本')
    if launch:
        if directory_running(directory):raise ValueError('所选目录已有加载器正在运行，请使用“读取已加载实例”或先自行退出后再启动')
        owned=LoaderSession(directory,game,progress,control,script=script or _SCRIPTS[game])
        try:owned.start(load_all=load_all);pid=owned.pid
        except Exception:owned.close();raise
    try:
        instances=discover(directory,pid)['instances']
        matches=[row for row in instances if row['game_id'] in profile.get('game_ids',_GAME_IDS[game])]
        if len(matches)!=1:raise ValueError('未找到唯一且与所选作品相符的已加载 Cordycep；请核对作品、PID和加载状态')
        instance=matches[0];destination=Path(output)/('capture-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
        records=set();pools={};strings=set();string_info={'bytes':0,'complete':False};complete=True;message='当前加载集合两次捕获一致'
        with MemoryReader(instance['pid'],directory) as reader:
            state=handler_state(directory,reader);state['executable']=str(reader.image)
            if owned and owned.script:state['_startup_script']=str(Path(directory)/owned.script)
            profile=validate_local_build(directory,game,state,reader)
            initial_table=reader.read(state['pools_addr'],POOL_COUNT*POOL_STRIDE)
            initial_signature=(state['pid'],state['game_id'],state['pools_addr'],state['strings_addr'])
            instance_stable=True
            for pool in range(POOL_COUNT):
                metadata=dict(profile.get('pools',{}).get(str(pool),{}))
                metadata.setdefault('kind',None);metadata.setdefault('profile',None);metadata.setdefault('key_width',64)
                metadata.setdefault('stored_mask','ffffffffffffffff');metadata.setdefault('mapping_source','unclassified pool')
                metadata.update(count=0,stable=False,errors=[])
                pools[pool]=metadata
                if pool in profile.get('excluded_model_pool_ids',[]):
                    metadata.update(kind='xmodel',profile=None,count=0,stable=True,excluded=True,mapping_source='models excluded by application scope')
                    continue
                try:
                    for attempt in range(3):
                        try:
                            _check(control);keys,first=walk_pool(reader,state['pools_addr'],pool,control)
                            repeated,second=walk_pool(reader,state['pools_addr'],pool,control)
                            if first!=second or keys!=repeated:raise ValueError(f'池 {pool} 两次读取不一致')
                            break
                        except ValueError:
                            if attempt==2:raise
                            _check(control);time.sleep(0.05)
                    if len(records)+len(keys)>5000000:raise ValueError('资产数量超过500万读取上限，快照不完整')
                    records.update((key,pool) for key in keys);metadata.update(count=len(keys),stable=True)
                except (ValueError,InterruptedError) as error:
                    complete=False;metadata['errors'].append(str(error));message=str(error)
                    if isinstance(error,InterruptedError):break
                if pool%16==0 or metadata['kind'] and metadata['count']:progress(len(records),f'读取资产池 {pool+1}/{POOL_COUNT} · {len(records):,} 个完整原始键')
            if control()=='run':
                try:
                    recorded_size=struct.unpack('<Q',reader.read(state['str_pool_size_addr'],8))[0] if state.get('str_pool_size_addr') else None
                    strings,string_info=read_strings(reader,state['strings_addr'],control,recorded_size=recorded_size)
                except (ValueError,InterruptedError) as error:string_info['message']=str(error)
            else:complete=False
            try:
                latest=handler_state(directory,reader)
                final_table=reader.read(state['pools_addr'],POOL_COUNT*POOL_STRIDE)
                changed=[p for p in range(POOL_COUNT) if p not in profile.get('excluded_model_pool_ids',[])
                    and initial_table[p*40:p*40+16]!=final_table[p*40:p*40+16]]
                table_stable=not changed
                for p in changed:
                    pools[p]['stable']=False;pools[p]['errors'].append('pool list boundaries changed across full capture')
                if (latest['pid'],latest['game_id'],latest['pools_addr'],latest['strings_addr'])!=initial_signature or not table_stable:
                    complete=False;message='捕获期间加载器状态或资产池改变，快照不完整：'+', '.join(map(str,changed))
                if (latest['pid'],latest['game_id'],latest['pools_addr'],latest['strings_addr'])!=initial_signature:instance_stable=False
            except ValueError as error:complete=False;instance_stable=False;message=str(error)
            state['_capture_state_stable']=instance_stable
        scope=['loadall requested' if owned and load_all else 'current loaded fast files; not asserted entire game','model pools excluded']
        if not records:complete=False;message='没有读取到稳定资产键，请先在 Cordycep 加载 fast file'
        elif control()=='run':
            supported=sorted(int(p) for p in profile['pools'])
            # Unsupported pools are retained for diagnosis and can never
            # supply targets. Their churn cannot certify or invalidate the
            # separately checked, supported asset set.
            complete=instance_stable and all(p in pools and pools[p]['stable'] and not pools[p]['errors'] for p in supported)
            if complete:message='已适配非模型资产池两次读取一致；未知池只保留诊断，不参与名称计算'
            scope.append('verified scope: supported non-model pools '+','.join(map(str,supported)))
        progress(len(records),'写出原始键快照、池报告与候选字符串；保留完整64位键')
        if control()!='run':complete=False;message='已停止捕获；保留诊断文件，不完整快照不能进入名称计算'
        result=_write_snapshot(destination,game,state,profile,pools,records,strings,string_info,complete,message,scope)
        if control()!='run':result['status']='stopped'
        return result
    finally:
        if owned:owned.close()


def directory_running(directory):
    """An initializing CLI also owns its state directory before JSON is ready."""
    for pid in process_ids():
        try:
            with MemoryReader(pid,directory) as reader:
                if reader.image.name.lower()=='cordycep.cli.exe':return True
                try:handler_state(directory,reader);return True
                except ValueError:pass
        except ValueError:pass
    return False


def startup_scripts(directory):
    root=Path(directory).resolve(strict=True)
    if not root.is_dir():raise ValueError('Cordycep 目录不存在')
    return {'directory':str(root),'scripts':sorted(p.name for p in root.iterdir() if p.is_file() and p.suffix.lower()=='.bat' and p.resolve().parent==root)}


def launch_arguments(directory,game):
    """Read the named local startup script, accepting its specific loader command."""
    directory=Path(directory).resolve(strict=True);path=directory/_SCRIPTS[game]
    if not path.is_file():raise ValueError('找不到作品启动脚本：'+str(path))
    text=path.read_text(encoding='utf-8-sig').strip()
    if '\n' in text or re.search(r'[&|<>%]',text):raise ValueError('启动脚本不是受支持的单行 Cordycep 命令，请自行启动后读取实例')
    tokens=re.findall(r'"([^"\r\n]*)"|(\S+)',text);args=[quoted or plain for quoted,plain in tokens]
    if not args or Path(args[0]).name.lower()!='cordycep.cli.exe':raise ValueError('启动脚本必须调用当前目录 Cordycep.CLI.exe')
    expected='mw7' if game=='COD2026' else 'bo7'
    if args[1:3]!=['sethandler',expected] or 'init' not in args or args[-1]!='loadcommonfiles':
        raise ValueError('启动脚本作品或加载流程与选择不一致')
    if game=='COD2026' and args[3:5]!=['setflag','beta']:raise ValueError('MW7 Beta 启动脚本未设置 beta 标记')
    position=5 if game=='COD2026' else 3
    if len(args)!=position+5 or args[position]!='init' or args[position+2:position+4]!=['setlocaleprefix','eng_']:
        raise ValueError('启动脚本参数与已核实流程不同，请自行启动后读取实例')
    game_directory=Path(args[position+1]).resolve(strict=True)
    if not game_directory.is_dir():raise ValueError('启动脚本里的游戏文件夹不存在')
    return [str(directory/'Cordycep.CLI.exe'),*args[1:]]


class LoaderSession:
    """Own only the loader started by this request; always reap its pipes."""
    def __init__(self,directory,game,progress,control,script=None):
        self.directory=Path(directory);self.game=game;self.progress=progress;self.control=control
        self.script=script;self.child=None;self.lines=queue.Queue();self.pid=None;self.output_tail=b''
    def start(self,load_all=False,timeout=1800):
        if self.script:
            from .batch_loader import OwnedBatchProcess
            self.child=OwnedBatchProcess(self.directory,self.script)
        else:
            args=launch_arguments(self.directory,self.game)
            self.child=subprocess.Popen(args,cwd=self.directory,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,bufsize=0)
        self.pid=self.child.pid
        def consume():
            while True:
                chunk=self.child.stdout.read(4096)
                if not chunk:break
                self.lines.put(chunk)
            self.lines.put(None)
        threading.Thread(target=consume,daemon=True).start();self._wait_prompt(timeout)
        if self.script:
            matches=[row for row in discover(self.directory)['instances']
                if row['game_id'] in _GAME_IDS[self.game] and self.child.owns(row['pid'])]
            if len(matches)!=1:raise ValueError('所选 BAT 没有启动唯一且匹配作品的本次加载器；请检查脚本、作品和加载状态')
            self.pid=matches[0]['pid']
        if load_all:
            self.child.stdin.write(b'loadall\r\n');self.child.stdin.flush();self._wait_prompt(timeout)
        return self.pid
    def _wait_prompt(self,timeout):
        started=time.monotonic();buffer=b'';last=started
        while True:
            _check(self.control)
            if time.monotonic()-started>timeout:raise ValueError('Cordycep 加载超时；请检查加载器日志及所需游戏文件')
            if time.monotonic()-last>=2:
                self.progress(0,'Cordycep 正在加载所选作品，等待命令完成');last=time.monotonic()
            root_exited=self.child.poll() is not None
            descendants_alive=self.script and root_exited and getattr(self.child,'has_live_processes',lambda:False)()
            if root_exited and not descendants_alive:raise ValueError(f'Cordycep 在加载完成前退出（代码 {self.child.returncode}），请检查其本地日志、运行要求和其它加载实例')
            try:chunk=self.lines.get(timeout=0.1)
            except queue.Empty:continue
            if chunk is None:raise ValueError('Cordycep 没有返回可核对的完成提示，请在本地手动启动后使用“读取已加载实例”')
            buffer=(buffer+chunk)[-65536:]
            self.output_tail=buffer
            # The CLI ends a command sequence with its input prompt. Confirm
            # actual strings against the local release during validation.
            plain=re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]',b'',buffer).rstrip()
            if re.search(rb'(?:Cordycep[^\r\n]{0,50}>|Enter (?:a )?command[^\r\n]*:|\r?\n>)$',plain,re.I):return
    def close(self):
        if self.child is None:return
        if self.child.poll() is None:
            try:self.child.stdin.write(b'exit\r\n');self.child.stdin.flush();self.child.wait(timeout=3)
            except (OSError,subprocess.TimeoutExpired):self.child.terminate();self.child.wait(timeout=10)
        for stream in (self.child.stdin,self.child.stdout):
            if stream:
                try:stream.close()
                except OSError:pass
        if self.script:self.child.close()
