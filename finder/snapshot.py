"""Independent, strict readers for CODIDS v1 and native CODSNAP2 snapshots.

BO4/BOCW use documented legacy pool numbers. Modern CODIDS files require their
capture-local pool labels: merged indexes are never live-loader pool indexes.
CODIDS uint64 fields have already lost bit 63; their width is never promoted.
New manifests carry explicit pool domains and retain the original uint64 key.
"""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re
import struct

from .assets import ASSET_LABELS
from .generated_registry import DOMAINS
from .hashing import PROFILES
from .methods import canonical_json

MASK64=(1<<64)-1
MASK63=(1<<63)-1
MAX_RECORDS=10_000_000
MAX_MANIFEST=4*1024*1024
LEGACY_SOURCE='hash-slinging-slasher pool facts @10108fa4c54509989143e8c8028c7a76ab57d28a'
# Numeric facts, independently expressed for the supported types. BO4 sound
# pool 10 contains banks; 170/171 are appended offline sound/alias records.
LEGACY_POOLS={
 'BO4':{3:'xanim',4:'xmodel',6:'material',9:'image',10:'soundbank',16:'localize',
        20:'weapon',27:'attachment',28:'attachment',41:'rawfile',43:'stringtable',
        44:'structuredtable',48:'scriptfile',49:'scriptfile',50:'scriptfile',
        51:'keyvaluepairs',63:'scriptbundle',170:'sndasset',171:'soundbankalias'},
 'BOCW':{5:'xanim',6:'xmodel',10:'material',16:'image',18:'soundbank',19:'sndasset',
         29:'localize',33:'weapon',44:'attachment',45:'attachment',59:'rawfile',
         60:'rawfile',61:'rawfile',63:'stringtable',64:'structuredtable',68:'scriptfile',
         69:'scriptfile',75:'keyvaluepairs',87:'scriptbundle',221:'soundbankalias'},
}
GAME_ALIASES={'BLKOPS04':'BO4','BLKOPSCW':'BOCW','T8':'BO4','T9':'BOCW',
              'MODWAR22':'MWII','YAMYAMOK':'MWIII','BLACKOP6':'BO6',
              'MODWAR7':'COD2026','MW7BETA':'COD2026','BLACKOP7':'BO7'}
MODERN_GAMES=frozenset(('MWII','MWIII','BO6','BO7','COD2026'))
MODERN_SOURCE='hash-slinging-slasher capture-local labels @dbe25197cee05b8315b4effff1841ed4868152f0'
# A name is a pool-type fact, not permission to reinterpret a nested symbol.
# In particular bone, scriptfield, dvar and omnvar are not ordinary asset pools.
MODERN_POOL_KINDS={kind:kind for kind in (
    'xmodel','xanim','material','image','sndasset','soundbank',
    'soundbanktransient','animpkg','rawfile','scriptfile','scriptbundle',
    'stringtable','localize','weapon','attachment','structuredtable','keyvaluepairs')}
MODERN_POOL_KINDS.update(sound_asset='sndasset',sound_alias='soundbankalias')


class _Cancelled(Exception):pass


def _check(control):
    if control()!='run':raise _Cancelled()


def normalize_game(value):
    if not isinstance(value,str) or not value or len(value)>128 or any(c in value for c in '\x00\r\n'):
        raise ValueError('快照游戏标识无效')
    return GAME_ALIASES.get(value.upper(),value.upper())


def _integer(value,maximum,label):
    if type(value) is not int or not 0<=value<=maximum:raise ValueError('快照'+label+'无效')
    return value


def _sha(path,control):
    digest=hashlib.sha256()
    before=path.stat()
    with path.open('rb') as stream:
        while True:
            _check(control);chunk=stream.read(1024*1024)
            if not chunk:break
            digest.update(chunk)
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise ValueError('快照文件在读取期间改变')
    return digest.hexdigest()


def _hex(value,label):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-fA-F]{16}',value):
        raise ValueError('快照'+label+'须为16位十六进制')
    return int(value,16)


def _relative_file(root,name):
    if not isinstance(name,str) or not name or '\\' in name or ':' in name:
        raise ValueError('快照数据文件路径无效')
    relative=Path(name)
    if relative.is_absolute() or any(part in ('.','..') for part in relative.parts):
        raise ValueError('快照数据文件不可越过快照目录')
    path=(root/relative).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('快照数据文件不可越过快照目录')
    return path


def _file_metadata(root,item,label,control):
    if not isinstance(item,dict):raise ValueError('快照'+label+'元数据无效')
    path=_relative_file(root,item.get('file'))
    expected=item.get('sha256')
    if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected):
        raise ValueError('快照'+label+'缺少内容SHA256')
    digest=_sha(path,control)
    if digest!=expected:raise ValueError('快照'+label+'内容SHA256不一致')
    if 'bytes' in item and _integer(item['bytes'],1<<40,label+'字节数')!=path.stat().st_size:
        raise ValueError('快照'+label+'字节数不一致')
    return path,digest


def _pool_sidecar(path,control,*,expected_game=None):
    entries={};declared_total=None;declared_filled=None;labels=set()
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        _check(control);text=line.strip()
        if not text:continue
        total=re.search(r'--\s*(\d+)\s+assets\s+in\s+(\d+)\s+filled\s+pools',text,re.I)
        if total:
            if expected_game is not None:
                if declared_total is not None:raise ValueError('池清单出现重复总计')
                tag=text[:total.start()].strip()
                if normalize_game(tag)!=expected_game:raise ValueError('池清单所属作品与快照不一致')
                declared_filled=int(total[2])
            declared_total=int(total[1]);continue
        if re.match(r'^(?:index|pool(?:_index)?)[,\s]',text,re.I):continue
        if ',' in text:
            columns=next(csv.reader([text]))
            if len(columns)!=3:raise ValueError('池清单CSV必须为池号、类型、计数三列')
            pool,label,count=(column.strip() for column in columns)
            if not pool.isdecimal() or not count.isdecimal():raise ValueError('池清单池号或计数无效')
        else:
            match=re.fullmatch(r'(\d+)\s+(\S+)\s+(\d+)',text)
            if not match:raise ValueError('池清单定宽文本格式无效')
            pool,label,count=match.groups()
        pool=_integer(int(pool),65535,'池号');count=_integer(int(count),MAX_RECORDS,'池计数')
        if pool in entries:raise ValueError('池清单出现重复池号')
        if not label or any(c in label for c in '\x00\r\n'):raise ValueError('池清单标签无效')
        if expected_game is not None and label in labels:raise ValueError('池清单出现重复类型标签')
        labels.add(label)
        entries[pool]={'label':label,'count':count}
    if not entries:raise ValueError('池清单没有有效条目')
    if declared_total is not None and sum(item['count'] for item in entries.values())!=declared_total:
        raise ValueError('池清单总计数不一致')
    if declared_filled is not None and sum(item['count']>0 for item in entries.values())!=declared_filled:
        raise ValueError('池清单非空池数量不一致')
    return entries


def _evidence_profile(game,kind,profile):
    return bool(profile in PROFILES and any(row['status']=='evidence' and row['profile']==profile
        and kind in row['kinds'] for row in DOMAINS.get(game,())))


def _pool_registry():
    path=Path(__file__).with_name('cordycep_profiles.json')
    if not path.is_file():raise ValueError('软件缺少离线资产池适配资料，请重新安装完整发布包')
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('version')!=1 or not isinstance(data.get('profiles'),dict):
        raise ValueError('离线资产池适配资料无效')
    return data['profiles']


def _finish(result,control):
    counts=Counter(pool for _,pool in result['records'])
    for pool,item in result['pools'].items():
        if item['count']!=counts.get(pool,0):raise ValueError(f'快照池 {pool} 的记录计数不一致')
    if set(counts)-set(result['pools']):raise ValueError('快照记录引用未声明的池')
    semantic_pools=[]
    for pool,item in sorted(result['pools'].items()):
        source=item.get('mapping_source','')
        if re.match(r'^[A-Za-z]:[\\/]|^/',source):source=Path(source.replace('\\','/')).name
        semantic_pools.append({'pool':pool,**{key:item[key] for key in
            ('kind','profile','key_width','stored_mask','count','stable','errors')},'mapping_source':source})
    digest=hashlib.sha256(canonical_json({'format':result['format'],'game':result['game'],
        'game_id':result['game_id'],'build':result['build'],'pools':semantic_pools,
        'build_fingerprints':result.get('build_fingerprints'),
        'strings_sha256':result.get('strings_sha256')}).encode('utf-8'))
    for index,(raw,pool) in enumerate(result['records']):
        if index%8192==0:_check(control)
        digest.update(struct.pack('<QH',raw,pool))
    result['fingerprint']=digest.hexdigest()
    return result


def _read_v1(path,control,pools_file):
    if path.stat().st_size>18+65535+MAX_RECORDS*10:raise ValueError('CODIDS快照超过支持的记录上限')
    with path.open('rb') as stream:
        header=stream.read(10)
        if len(header)!=10 or header[:6]!=b'CODIDS':raise ValueError('不是CODIDS快照')
        version,length=struct.unpack('<HH',header[6:])
        if version!=1:raise ValueError('不支持的CODIDS快照版本')
        game_bytes=stream.read(length);count_bytes=stream.read(8)
        if len(game_bytes)!=length or len(count_bytes)!=8:raise ValueError('CODIDS快照头部被截断')
        game_id=game_bytes.decode('utf-8',errors='strict');game=normalize_game(game_id)
        count=_integer(struct.unpack('<Q',count_bytes)[0],MAX_RECORDS,'记录数量')
        if path.stat().st_size!=18+length+count*10:raise ValueError('CODIDS快照长度/计数不一致')
        records=[];previous=None
        while block:=stream.read(8192*10):
            _check(control)
            for raw,pool in struct.iter_unpack('<QH',block):
                record=(raw,pool)
                if raw>MASK63:raise ValueError('旧CODIDS v1声明masked63，不能含最高位完整键')
                if previous is not None and record<=previous:raise ValueError('CODIDS记录未排序或存在同池重复键')
                records.append(record);previous=record
    sources=[{'file':str(path),'sha256':_sha(path,control),'role':'snapshot','logical_name':path.name}]
    sidecar=Path(pools_file).resolve(strict=True) if pools_file else path.with_suffix('.pools.txt')
    modern=game in MODERN_GAMES
    if modern and not sidecar.is_file():
        raise ValueError('现代CODIDS快照必须附带同名.pools.txt池清单，不能借用实时加载器池号')
    entries=_pool_sidecar(sidecar,control,expected_game=game if modern else None) if sidecar.is_file() else {}
    if entries:sources.append({'file':str(sidecar),'sha256':_sha(sidecar,control),'role':'snapshot-pools','logical_name':sidecar.name})
    counts=Counter(pool for _,pool in records)
    if entries and (set(counts)-set(entries) or any(item['count']!=counts.get(pool,0) for pool,item in entries.items())):
        raise ValueError('CODIDS记录与池清单计数不一致')
    pools={};warnings=[];mapped_kinds=set()
    for pool in sorted(set(counts)|set(entries)):
        label=entries.get(pool,{}).get('label','')
        kind=MODERN_POOL_KINDS.get(label) if modern else LEGACY_POOLS.get(game,{}).get(pool)
        if modern:
            profile='fnv1a64' if kind=='soundbankalias' else 'iw-resource63' if kind and kind!='xmodel' else None
            if profile and not _evidence_profile(game,kind,profile):profile=None
            if kind:
                if kind in mapped_kinds:raise ValueError('池清单出现同一资产类型的重复映射')
                mapped_kinds.add(kind)
        else:
            profile='fnv1a63' if kind and _evidence_profile(game,kind,'fnv1a63') else None
        pools[pool]={'kind':kind,'profile':profile,'key_width':63,'stored_mask':f'{MASK63:016x}',
            'count':counts.get(pool,0),'stable':True,'errors':[],
            'mapping_source':(MODERN_SOURCE if modern else LEGACY_SOURCE) if kind else '',
            'label':label}
        if kind is None:warnings.append(f'pool {pool} 没有已证分类，保留原始记录并排除计算')
        elif modern and kind=='soundbankalias':
            warnings.append(f'pool {pool} 声音别名仅保留63位；完整64位名称域不能正式计算或导出，请重新捕获原始64位键')
        elif modern and profile is None and kind!='xmodel':
            warnings.append(f'pool {pool} 的 {kind} 没有对应作品已证名称域，保留原始记录并排除计算')
    return _finish({'format':'CODIDSv1','game':game,'game_id':game_id,
        'build':'upstream-capture-unversioned' if modern else 'legacy-unversioned',
        'key_width':63,'records':records,'pools':pools,'complete':True,
        'complete_scope':('capture-local declared loaded set; whole-game completeness unproven' if modern else
                          'legacy loaded set; whole-game completeness unproven'),
        'source_files':sources,'strings_path':'','warnings':warnings},control)


def _read_v2(path,control):
    if path.stat().st_size>MAX_MANIFEST:raise ValueError('CODSNAP2 manifest过大')
    metadata=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(metadata,dict) or metadata.get('format')!='CODSNAP2' or metadata.get('version')!=2:
        raise ValueError('不支持的CODSNAP2 manifest格式/版本')
    game=normalize_game(metadata.get('game'));game_id=metadata.get('game_id',metadata['game'])
    recorded_game=normalize_game(game_id)
    if recorded_game in DOMAINS and recorded_game!=game:
        raise ValueError('快照game_id与所声明作品不一致')
    build=metadata.get('build')
    if not isinstance(build,str) or not build or len(build)>256 or any(c in build for c in '\x00\r\n'):
        raise ValueError('CODSNAP2必须记录对应build')
    if metadata.get('raw_key_width')!=64:raise ValueError('CODSNAP2须保存原始uint64键')
    if metadata.get('complete') is not True:raise ValueError('快照未完整完成，请重新捕获后计算')
    loaded_scope=metadata.get('loaded_scope',[])
    if (not isinstance(loaded_scope,list) or len(loaded_scope)>512 or any(
            not isinstance(value,str) or len(value)>1024 or any(c in value for c in '\x00\r\n')
            for value in loaded_scope)):
        raise ValueError('快照loaded_scope须为有效范围说明列表')
    adapter=_pool_registry().get(game)
    adapted={int(pool):item for pool,item in adapter.get('pools',{}).items()} if adapter else {}
    excluded=set(adapter.get('excluded_model_pool_ids',())) if adapter else set()
    if adapter:
        if metadata.get('state_stable') is not True:raise ValueError('捕获时加载器状态不稳定，不能计算快照')
        fingerprints=metadata.get('build_fingerprints')
        if not isinstance(fingerprints,dict) or any(fingerprints.get(key)!=adapter[key] for key in ('module_sha256','config_sha256')):
            raise ValueError('快照build SHA256与已适配资产池版本不一致')
        if game_id not in adapter['game_ids']:raise ValueError('快照game_id不属于已适配作品')
        if 'verified_scope_pools' in metadata:
            scope=metadata['verified_scope_pools']
            if (not isinstance(scope,list) or any(type(pool) is not int for pool in scope)
                    or len(scope)!=len(set(scope)) or set(scope)!=set(adapted)):
                raise ValueError('快照已验证池范围与本地适配表不一致')
    declared=metadata.get('pools')
    if not isinstance(declared,list) or not declared:raise ValueError('快照缺少池元数据')
    pools={};warnings=[]
    for item in declared:
        _check(control)
        if not isinstance(item,dict):raise ValueError('快照池元数据无效')
        pool=_integer(item.get('pool'),65535,'池号')
        if pool in pools:raise ValueError('快照manifest出现重复池号')
        width=_integer(item.get('key_width'),64,'键位宽')
        if width not in (32,60,63,64):raise ValueError('快照键位宽不受支持')
        mask=_hex(item.get('stored_mask'),'池存储掩码')
        if not mask or mask>(1<<width)-1:raise ValueError('快照池位宽和掩码不一致')
        kind=item.get('kind');profile=item.get('profile')
        if kind not in (None,'',*ASSET_LABELS,'xmodel'):raise ValueError('快照池资产类型无效')
        if profile is not None and profile not in PROFILES:raise ValueError('快照池profile无效')
        if not isinstance(item.get('mapping_source',''),str):raise ValueError('快照池mapping来源无效')
        if type(item.get('stable')) is not bool or not isinstance(item.get('errors'),list) or any(not isinstance(error,str) for error in item['errors']):
            raise ValueError('快照池稳定性/读取错误元数据无效')
        item={**item,'kind':kind or None,'count':_integer(item.get('count'),MAX_RECORDS,'池计数')}
        if pool in adapted:
            expected=adapted[pool]
            if any(item.get(key)!=expected[key] for key in ('kind','profile','key_width','stored_mask')):
                raise ValueError(f'快照pool {pool} 分类/profile/掩码与已证池适配表不一致')
            if not _evidence_profile(game,kind,profile):raise ValueError('快照池名称域未获对应作品证据支持')
            if item['stable'] is not True or item['errors']:
                raise ValueError(f'快照已适配pool {pool} 不稳定或读取失败，必须重新捕获')
            item['mapping_source']=expected['mapping_source']
            if 'type_name' in expected:item['type_name']=expected['type_name']
        elif pool in excluded:
            if kind not in (None,'','xmodel') or profile is not None:
                raise ValueError('快照模型池不得改成可计算名称域')
            item.update(kind='xmodel',profile=None)
        else:
            if kind not in (None,'') or profile is not None:
                raise ValueError(f'快照pool {pool} 没有已证分类，不能凭manifest标签认证')
            warnings.append(f'pool {pool} 未适配，仅保留诊断原始键，不计算')
            if item['errors'] or not item['stable']:
                warnings.append(f'pool {pool} 诊断读取不完整，已从正式目标范围排除')
        pools[pool]=item
    if set(adapted)-set(pools):raise ValueError('快照缺少已适配池，无法声明所选范围完整')
    root=path.parent
    records_path,records_sha=_file_metadata(root,metadata.get('records'),'records',control)
    expected=_integer(metadata['records'].get('count'),MAX_RECORDS,'记录数量')
    records=[];previous=None
    with records_path.open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.reader(stream)
        if next(reader,None)!=['raw_hash','type','pool']:raise ValueError('快照records.csv列头须为raw_hash,type,pool')
        for line,columns in enumerate(reader,2):
            if line%8192==2:_check(control)
            if len(columns)!=3 or not columns[2].isdecimal():raise ValueError(f'快照records.csv第{line}行无效')
            raw=_hex(columns[0],'原始键');pool=_integer(int(columns[2]),65535,'池号')
            if pool not in pools or columns[1]!=(pools[pool]['kind'] or ''):raise ValueError('快照记录类型/池号与manifest不一致')
            record=(raw,pool)
            if previous is not None and record<=previous:raise ValueError('快照记录未排序或存在同池重复键')
            records.append(record);previous=record
            if len(records)>expected:raise ValueError('快照记录数量超过manifest')
    if len(records)!=expected:raise ValueError('快照记录数量与manifest不一致')
    if _sha(records_path,control)!=records_sha:raise ValueError('快照记录在解析期间改变')
    sources=[{'file':str(path),'sha256':_sha(path,control),'role':'snapshot-manifest','logical_name':path.name},
        {'file':str(records_path),'sha256':records_sha,'role':'snapshot','logical_name':metadata['records']['file']}]
    mapping_path=Path(__file__).with_name('cordycep_profiles.json')
    sources.append({'file':str(mapping_path.resolve()),'sha256':_sha(mapping_path,control),
        'role':'pool-mapping','logical_name':mapping_path.name})
    strings_path='';strings_sha=None
    if metadata.get('strings') is not None:
        strings,strings_sha=_file_metadata(root,metadata['strings'],'strings',control)
        if strings.suffix.lower() not in ('.txt','.tsv'):raise ValueError('快照字符串候选须为TXT/TSV')
        count=_integer(metadata['strings'].get('count'),MAX_RECORDS,'字符串数量')
        actual=0
        with strings.open(encoding='utf-8-sig') as stream:
            for line in stream:
                if actual%8192==0:_check(control)
                value=line.rstrip('\r\n')
                if not value or any(c in value for c in '\x00\r\n') or len(value.encode('utf-8'))>1024:
                    raise ValueError('快照字符串候选包含无效名称')
                actual+=1
        if actual!=count:raise ValueError('快照字符串数量与manifest不一致')
        if _sha(strings,control)!=strings_sha:raise ValueError('快照字符串在解析期间改变')
        strings_path=str(strings)
        sources.append({'file':strings_path,'sha256':strings_sha,'role':'snapshot-strings','logical_name':metadata['strings']['file']})
    return _finish({'format':'CODSNAP2','game':game,'game_id':game_id,'build':build,
        'build_fingerprints':metadata.get('build_fingerprints'),
        'state_stable':metadata.get('state_stable'),
        'key_width':64,'records':records,'pools':pools,'complete':True,
        'complete_scope':'all supported mapped pools in current loaded set; whole-game completeness unproven',
        'loaded_scope':loaded_scope,
        'verified_scope_pools':sorted(adapted),'whole_snapshot_stable':metadata.get('whole_snapshot_stable'),
        'source_files':sources,'strings_path':strings_path,'strings_sha256':strings_sha,
        'warnings':warnings},control)


def read_snapshot(path,control=lambda:'run',pools_file=None):
    """Validate completely before import; cancellation returns None, never rows."""
    try:
        _check(control);path=Path(path).resolve(strict=True)
        if path.is_dir():path=path/'snapshot.json'
        if not path.is_file():raise ValueError('请选择快照文件或包含snapshot.json的目录')
        with path.open('rb') as stream:magic=stream.read(6)
        return _read_v1(path,control,pools_file) if magic==b'CODIDS' else _read_v2(path,control)
    except _Cancelled:return None
    except (UnicodeError,ValueError,TypeError,KeyError,OSError,struct.error) as error:
        raise ValueError('资产快照读取失败：'+str(error)) from error
