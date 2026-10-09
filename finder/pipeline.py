"""Standalone one-click import, candidate search, verification and incremental export."""
from dataclasses import dataclass,asdict
from datetime import datetime,timezone,timedelta
import hashlib
import csv
import itertools
import json
from pathlib import Path
import re
import time
import uuid

from . import VERSION
from .assets import ASSET_LABELS
from .hashing import PROFILES,batch_digest
from .formats import decode_cdb,iter_dictionary
from .store import Store
from .engine import create_task,run_task
from .exporter import export,prepare_saluki,SALUKI_PACKAGES
from .autoplans import build_plans
from .asset_names import parse_exported_name,PREFIX_TYPES,GENERIC_PREFIXES
from .crossassets import build_cross_asset_plans
from .registry import table_rule,DOMAINS
from .spellings import resolve_table_spelling
from .soundplans import build_sound_plans
from .soundbyte import build_final_byte_plans
from .typedplans import build_typed_plans

CROSS_ASSET_KINDS=frozenset(('xanim','sndasset','soundbank','soundbanktransient',
                           'soundbankalias','image','material'))

@dataclass
class Config:
    folder: str
    indexes: str
    output: str
    profile: str='iw-resource63'
    asset_type: str='xanim'
    game: str='COD2026'
    dictionary: str=''
    keyword: str=''
    backend: str='auto'
    exclude_material: bool=True
    low60: bool=False
    budget: int=10000000
    seconds: int=7200
    number_max: int=32
    cross_asset: bool=True
    related_folder: str=''
    hash_domain: str=''
    allow_unverified_domain: bool=False
    borrowed_dictionary: str=''
    community: bool=False
    community_cache: str=''
    community_refresh: bool=False
    anyway: bool=False
    input_mode: str='folder'
    snapshot_file: str=''

    def validate(self):
        if self.input_mode not in ('folder','snapshot'):raise ValueError('目标输入模式无效')
        if any(not isinstance(value,str) or not value.strip() for value in (self.indexes,self.output)):
            raise ValueError('请选择已有名称索引和输出目录')
        supplied=self.snapshot_file if self.input_mode=='snapshot' else self.folder
        if not isinstance(supplied,str) or not supplied.strip():
            raise ValueError('请选择资产快照' if self.input_mode=='snapshot' else '请选择哈希文件夹')
        if self.profile not in PROFILES:raise ValueError('请选择正确的哈希规则')
        if self.asset_type not in ('auto',*ASSET_LABELS):raise ValueError('请选择资产类型')
        if self.backend not in ('auto','cpu','gpu'):raise ValueError('计算后端无效')
        if not isinstance(self.cross_asset,bool):raise ValueError('跨资产名称推测开关无效')
        if any(not isinstance(getattr(self,k),bool) for k in ('community','community_refresh','anyway','allow_unverified_domain')):raise ValueError('运行开关无效')
        if self.borrowed_dictionary and not Path(self.borrowed_dictionary).exists():raise ValueError('跨作品候选词典不存在')
        # Legacy configs specify a profile explicitly. New domain selections
        # additionally prevent accidentally treating an unknown domain as fact.
        from .registry import validate_domain
        validate_domain(self.game,self.profile,self.hash_domain,allow_unverified=self.allow_unverified_domain)
        if not isinstance(self.related_folder,str):raise ValueError('其他已命名资产文件夹须为路径文本')
        if not isinstance(self.budget,int) or not 1<=self.budget<=1000000000:raise ValueError('候选预算无效')
        if not 1<=self.seconds<=86400:raise ValueError('时间预算无效')
        if not 0<=self.number_max<=999:raise ValueError('数字上限无效')
        source=Path(supplied).resolve(strict=True)
        if self.input_mode=='folder' and not source.is_dir():raise ValueError('哈希文件夹不存在')
        if self.input_mode=='snapshot' and source.is_dir() and not (source/'snapshot.json').is_file():
            raise ValueError('快照目录须包含snapshot.json')
        indexes=Path(self.indexes).resolve(strict=True)
        if not indexes.is_dir():raise ValueError('已有名称索引文件夹不存在')
        output=Path(self.output).resolve()
        if self.input_mode=='snapshot' and output.is_relative_to(source if source.is_dir() else source.parent):
            raise ValueError('输出目录请选择资产快照文件夹以外的位置')
        if (self.input_mode=='folder' and output.is_relative_to(source)) or output.is_relative_to(indexes):
            raise ValueError('输出目录请选择资产和名称索引文件夹以外的位置')
        if self.dictionary and not Path(self.dictionary).exists():raise ValueError('补充名称词典不存在')
        if self.cross_asset and self.asset_type in ('auto',*CROSS_ASSET_KINDS) and self.related_folder:
            related=Path(self.related_folder).resolve()
            if not related.is_dir():raise ValueError('其他已命名资产文件夹不存在')
            if output.is_relative_to(related):raise ValueError('输出目录请选择其他已命名资产文件夹以外的位置')
        return self

def index_files(directory):
    root=Path(directory);root=root/'hash_pkg' if (root/'hash_pkg').is_dir() else root
    files=sorted(root.rglob('*.cdb'))
    if not files:raise ValueError('已有名称索引中没有 CDB 文件')
    return files

def _index_kind(path):
    stem=path.stem.lower()
    if stem.endswith('_v2'):stem=stem[:-3]
    if stem.endswith('_soundbanks_aliases'):return 'soundbankalias'
    if stem=='fnv1a_bones':return 'bone'
    if stem.endswith('_xanims'):return 'xanim'
    if stem.endswith('_xsounds'):return 'sndasset'
    if stem=='fnv1a_soundbanks':return 'soundbank'
    return None

def _verified_index_names(path,entries,control):
    """Verify source keys in bounded native CPU batches; repair only mismatches.

    These names are vocabulary, not target evidence. A target-held template
    additionally needs the target's own profile and typed-pool membership.
    """
    rule=table_rule(path)
    if not rule or not rule.get('profile'):return set()
    profiles=[PROFILES[pid] for pid in (rule['profile'],*rule.get('alternate_profiles',[]))]
    iterator=iter(entries.items());verified=set()
    while batch:=list(itertools.islice(iterator,4096)):
        if control()!='run':return verified
        pending=[(key,name) for key,name in batch if name and not any(c in name for c in '\x00\r\n') and len(name.encode('utf-8'))<=1024]
        for profile in profiles:
            if not pending:break
            hashes=batch_digest([name for _,name in pending],profile)
            verified.update(name for (key,name),digest in zip(pending,hashes) if key==int(digest))
            pending=[row for row,digest in zip(pending,hashes) if row[0]!=int(digest)]
        if rule['kind']=='sndasset' or (rule['profile']=='fnv1a63' and not path.stem.endswith('_v2')):
            for key,name in pending:
                if control()!='run':return verified
                restored=resolve_table_spelling(path,key,name)
                if restored is not None:verified.add(restored)
    return verified


def _held_templates(store,profile,candidates_by_kind,untyped,control,game=''):
    """Learn a convention only after a full-key hit in that actual target type."""
    keys={}
    for row in store.targets(exclude_material=False):keys.setdefault(row['kind'],set()).add(int(row['hash'],16))
    held={kind:set() for kind in keys}
    for kind,wanted in keys.items():
        if kind not in CROSS_ASSET_KINDS:continue
        if game in DOMAINS and not any(row['status']=='evidence' and row['profile']==profile.id
            and kind in row['kinds'] for row in DOMAINS[game]):continue
        iterator=iter(candidates_by_kind.get(kind,set()) | untyped)
        while names:=list(itertools.islice(iterator,4096)):
            if control()!='run':return held
            hashes=batch_digest(names,profile)
            for name,digest in zip(names,hashes):
                if int(digest) in wanted and profile.digest(name)==int(digest):held[kind].add(name)
    return held


def _alias_clues(store,names,control):
    """Masked legacy aliases can teach hypotheses, never full-width evidence."""
    groups={}
    for row in store.db.execute("SELECT raw_hash,profile,stored_mask FROM snapshot_records WHERE kind='soundbankalias'"):
        pid=row['profile']
        if not pid and store.meta('build') in ('BO4','BOCW'):pid='fnv1a63'
        if pid not in ('fnv1a63','fnv1a64'):continue
        groups.setdefault((pid,int(row['stored_mask'],16)),set()).add(int(row['raw_hash'],16))
    found=set()
    for (pid,mask),keys in groups.items():
        profile=PROFILES[pid]
        for index,name in enumerate(sorted(names)):
            if index%1024==0 and control()!='run':return found
            if (profile.digest(name)&mask) in keys:found.add(name)
    return found


def corpus_from_indexes(directory,kinds,progress,control,related_names=None,target_names_by_kind=None,profile_id=None,
                        verified_names_by_kind=None):
    names=set();sources=[]
    markers={Path('fnv1a_strings.cdb' if kind=='bone' and profile_id=='fnv1a60' else
                  SALUKI_PACKAGES.get(kind,'fnv1a_strings.cdb')).stem.replace('_v2','') for kind in kinds}
    files=index_files(directory)
    typed=[p for p in files if any(p.stem==marker or p.stem==marker+'_v2' for marker in markers)]
    # A copied single generic index is also a usable candidate source.
    selected=typed or files
    selected_paths=set(selected)
    if related_names is not None:selected=files
    for i,path in enumerate(selected):
        if control()!='run':return names,sources,False
        blob=path.read_bytes()
        try:entries=decode_cdb(blob)
        except Exception as e:raise ValueError(f'名称索引无法读取：{path.name}: {e}') from e
        values={n for n in entries.values() if n and not any(c in n for c in '\x00\r\n') and len(n.encode('utf-8'))<=1024}
        if verified_names_by_kind is not None:
            rule=table_rule(path)
            if rule and rule['kind'] in CROSS_ASSET_KINDS:
                verified=_verified_index_names(path,entries,control)
                verified_names_by_kind.setdefault(rule['kind'],set()).update(verified)
                if path in selected_paths:values.update(verified)
        if path in selected_paths:names.update(values)
        if related_names is not None:related_names.update(values)
        if target_names_by_kind is not None:
            kind=_index_kind(path)
            if kind in kinds:target_names_by_kind.setdefault(kind,set()).update(values)
            if kind=='soundbank' and 'soundbanktransient' in kinds:
                target_names_by_kind.setdefault('soundbanktransient',set()).update(values)
        sources.append({'file':str(path),'sha256':hashlib.sha256(blob).hexdigest(),'entries':len(entries),'candidate_corpus':path in selected_paths})
        count=len(related_names) if related_names is not None else len(names)
        progress(0,f'读取名称语料 {i+1}/{len(selected)} · {count:,} 个名称')
    return names,sources,True

def additional_names(path,progress,control):
    names=set();sources=[]
    if not path:return names,sources
    path=Path(path)
    files=sorted(p for p in path.rglob('*') if p.suffix.lower() in ('.txt','.tsv','.csv','.cdb','.wni')) if path.is_dir() else [path]
    if not files:raise ValueError('补充词典没有受支持的文件')
    for file in files:
        if control()!='run':break
        if file.suffix.lower() in ('.txt','.tsv'):
            with file.open(encoding='utf-8-sig') as stream:
                values=(line.rstrip('\r\n').split('\t')[-1] for line in stream)
                names.update(n for n in values if n and not any(c in n for c in '\x00\r\n') and len(n.encode('utf-8'))<=1024)
        else:
            names.update(n for h,n in iter_dictionary(file) if h is not None and n and not any(c in n for c in '\x00\r\n') and len(n.encode('utf-8'))<=1024)
        sources.append({'file':str(file),'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
        progress(0,f'读取补充候选：{file.name}')
    return names,sources

def readable_names(folder,profile_id='iw-resource63'):
    names=set()
    for file in Path(folder).rglob('*'):
        if file.is_file() and parse_exported_name(file,root=folder,min_digits=1 if PROFILES[profile_id].mask<=0xffffffff else 8) is None:
            value=file.stem
            if value and not any(c in value for c in '\x00\r\n') and len(value.encode('utf-8'))<=1024:names.add(value)
    return names

def related_file_names(folder,control=lambda:'run'):
    """Use decoded filenames only; never parse asset contents or hash placeholders."""
    names=set();files=0;root=Path(folder)
    for file in root.rglob('*'):
        if control()!='run':return names,files,False
        if not file.is_file():continue
        files+=1
        if parse_exported_name(file,root=root,min_digits=8) is not None:continue
        explicit=any(file.name.lower().startswith(prefix+'_') for prefix in (*PREFIX_TYPES,*GENERIC_PREFIXES))
        if explicit and parse_exported_name(file,root=root,min_digits=1) is not None:continue
        if re.fullmatch(r'(?:0x)?[0-9a-f]{1,16}',file.stem,re.I):continue
        relative=file.relative_to(root).with_name(file.stem)
        for value in (file.stem,relative.as_posix(),str(relative).replace('/','\\')):
            if value and not any(c in value for c in '\x00\r\n') and len(value.encode('utf-8'))<=1024:names.add(value)
    return names,files,True


def usable_complete_record(record):
    """Treat a damaged report payload as a cache miss before restoring evidence."""
    if not isinstance(record,dict):return None
    summary=record.get('summary')
    if not isinstance(summary,dict) or summary.get('status')!='completed':return None
    if any(type(summary.get(key)) is not int or summary[key]<0 for key in ('processed','corpus_names')):return None
    if type(summary.get('skipped_candidates',0)) is not int or summary.get('skipped_candidates',0)<0:return None
    if not isinstance(summary.get('community'),dict) or not isinstance(summary.get('cross_asset'),dict):return None
    if type(summary['cross_asset'].get('enabled')) is not bool:return None
    return record

def import_snapshot(config,store,progress=lambda *_:None,control=lambda:'run'):
    """Import current targets and validate the selected domain before any reuse."""
    progress(0,'导入资产快照' if config.input_mode=='snapshot' else '导入哈希文件清单')
    chosen=[] if config.asset_type=='auto' else [config.asset_type]
    if config.input_mode=='snapshot':
        imported=store.import_snapshot(config.snapshot_file,config.game,config.profile,kinds=chosen,
            exclude_material=config.exclude_material,truncated=config.low60,
            progress=lambda n,m:progress(0,m),cancelled=lambda:control()!='run')
    else:
        imported=store.import_exported(config.folder,config.game,config.profile,
            config.asset_type if chosen else 'sndasset',config.low60,lambda n,m:progress(0,m),
            lambda:control()!='run',kinds=chosen)
    if imported.get('cancelled'):return {'cancelled':True,'input':imported}
    progress(0,f'扫描 {imported["files"]:,} 个文件 · 导入 {imported["hashed_files"]:,} 个哈希目标 · 未识别 {imported["unrecognized"]:,} 个 · 类型过滤 {imported["types_filtered"]:,} 个')
    targets=store.targets(exclude_material=config.exclude_material)
    if not targets:raise ValueError('导入后没有符合范围的非模型资产')
    if config.low60 and any(int(r['hash'],16)>=(1<<60) for r in targets):raise ValueError('文件名包含高于低60位的值，请取消低60位选项')
    kinds=sorted({r['kind'] for r in targets})
    from .registry import validate_domain
    domain=validate_domain(
        config.game,config.profile,config.hash_domain,allow_unverified=config.allow_unverified_domain)
    if domain.get('status')=='unknown':
        allowed=set(domain.get('kinds',()))
        if not allowed:
            from .generated_registry import DOMAINS
            allowed={kind for row in DOMAINS.get(config.game,()) if row['id']==config.hash_domain for kind in row['kinds']}
            if not config.hash_domain:
                allowed={'dvar'} if config.profile=='iw-dvar64' else {'omnvar'} if config.profile=='bo6-omnvar64' else {'scriptfield'}
        if not set(kinds)<=allowed:raise ValueError('未证实名称域须选择对应类型目标（'+', '.join(sorted(allowed))+'），不能用其他类型样本解锁')
        # Unknown symbol domains need actual full-key/name samples in this
        # private snapshot. Merely selecting a profile is no calibration.
        sample_paths=sorted(p for p in Path(config.dictionary).rglob('*') if p.suffix.lower() in ('.csv','.cdb','.wni')) if config.dictionary and Path(config.dictionary).is_dir() else [Path(config.dictionary)] if config.dictionary else []
        if not sample_paths or config.low60:raise ValueError('未证实域须提供至少3个当前目标的完整哈希/真实名称样本（CSV/CDB/WNI），不能用低60位或跨作品借用词典解锁')
        store.import_dictionary(sample_paths,config.game,[config.profile],exclude_material=config.exclude_material)
        count=store.db.execute("SELECT COUNT(DISTINCT hash) FROM evidence WHERE method='prior_verified' AND profile=?",(config.profile,)).fetchone()[0]
        if count<3:raise ValueError(f'未证实域仅回算通过 {count} 个当前目标，至少需要3个独立完整键样本')
        domain={**domain,'local_verified_samples':count,'local_scope':store.meta('catalog_fingerprint'),
                'local_validation':'full target keys independently rehashed; official game domain remains unknown'}
    return dict(imported=imported,chosen=chosen,kinds=kinds,domain=domain)


def prepare(config,store,progress=lambda *_:None,control=lambda:'run',snapshot=None):
    """One shared preparation path for estimates and execution."""
    snapshot=snapshot or import_snapshot(config,store,progress,control)
    if snapshot.get('cancelled'):return snapshot
    imported=snapshot['imported'];chosen=snapshot['chosen'];kinds=snapshot['kinds'];domain=snapshot['domain']
    targets=store.targets(exclude_material=config.exclude_material)
    cross_enabled=config.cross_asset and bool(CROSS_ASSET_KINDS.intersection(kinds))
    related_names=set();target_names_by_kind={};verified_names_by_kind={}
    names,sources,loaded=corpus_from_indexes(config.indexes,kinds,progress,control,
        related_names if cross_enabled else None,target_names_by_kind if cross_enabled else None,profile_id=config.profile,
        verified_names_by_kind=verified_names_by_kind if cross_enabled and not config.low60 else None)
    extras,extra_sources=additional_names(config.dictionary,progress,control)
    readable=readable_names(config.folder,config.profile) if config.input_mode=='folder' else set()
    if config.input_mode=='snapshot':
        snapshot_dictionary=store.meta('snapshot_dictionary')
        snapshot_names,snapshot_name_sources=additional_names(snapshot_dictionary,progress,control)
        extras.update(snapshot_names)
        snapshot_sources=json.loads(store.meta('snapshot_sources','[]'))
        extra_sources.extend(row for row in snapshot_sources if row.get('role')!='snapshot-strings')
        for row in snapshot_name_sources:row['role']='snapshot-strings'
        extra_sources.extend(snapshot_name_sources)
    names.update(extras);names.update(readable)
    community_summary={'enabled':False}
    community_candidate_names=set()
    if config.community:
        from .community import sync_community,iter_community
        progress(0,'读取可选社区表并逐行回算；未匹配行仅用作候选')
        cache=config.community_cache or str(Path(config.output)/'.community-cache')
        community_summary=sync_community(cache,enabled=True,refresh=config.community_refresh)
        for source in community_summary['files']:
            extra_sources.append({'sha256':source['sha256'],'community':True})
        counts={'verified':0,'quarantined':0,'borrowed':0}
        wanted={int(row['hash'],16) for row in targets}
        for row in iter_community(community_summary['csv_dir'],selected_profile=config.profile):
            if control()!='run':loaded=False;break
            counts[row.status]+=1
            if not row.name or any(c in row.name for c in '\x00\r\n') or len(row.name.encode('utf-8'))>1024:continue
            if row.status=='verified' and row.profile==config.profile and row.key in wanted:
                names.add(row.name)
                if not config.low60:
                    with store.db:store.add_evidence(row.key,PROFILES[config.profile].normalize(row.name),config.profile,
                        community_summary['commit'],config.game,'prior_verified',
                        {'table':row.table,'row':row.row,'community_commit':community_summary['commit'],
                         'source_profile':PROFILES[config.profile].json(),'target_present':True})
            else:community_candidate_names.add(row.name)
        community_summary={**community_summary,'counts':counts}
    related_files=0
    if cross_enabled:
        related_names.update(extras);related_names.update(readable)
        if config.related_folder:
            local_names,related_files,related_loaded=related_file_names(config.related_folder,control)
            related_names.update(local_names);loaded=loaded and related_loaded
            progress(0,f'读取其他已命名资产 · 扫描 {related_files:,} 个文件 · {len(local_names):,} 个名称线索')
        # An untyped copied index or supplemental dictionary can still supply
        # observed target templates; the generator validates their grammar.
        for kind in CROSS_ASSET_KINDS.intersection(kinds):
            target_names_by_kind.setdefault(kind,set()).update(names)

    cross_summary={'enabled':cross_enabled,'source_names':len(related_names),
        'related_folder':config.related_folder if cross_enabled else '', 'related_files':related_files}
    progress(0,f'生成候选规则 · {len(names):,} 个名称语料')
    plans=build_plans(sorted(names),config.asset_type,keyword='',number_max=config.number_max) if names else []
    borrowed,borrowed_sources=additional_names(config.borrowed_dictionary,progress,control)
    borrowed.update(community_candidate_names)
    for source in borrowed_sources:source['borrowed']=True
    extra_sources.extend(borrowed_sources)
    if borrowed:
        borrowed_plans=build_plans(sorted(borrowed),config.asset_type,keyword='',number_max=config.number_max)
        for _,plan in borrowed_plans:plan.metadata['borrowed']=True
        # Separate plans allow respelling while protecting observed target
        # naming templates from unverified cross-title donor conventions.
        plans.extend(('跨作品候选 · '+label,plan) for label,plan in borrowed_plans)
    cross_plans=build_cross_asset_plans(related_names,target_names_by_kind,kinds,number_max=config.number_max) if cross_enabled else []
    if cross_enabled and not config.low60 and control()=='run':
        profile=PROFILES[config.profile]
        held=_held_templates(store,profile,verified_names_by_kind,extras|readable,control,config.game)
        for kind,values in held.items():verified_names_by_kind.setdefault(kind,set()).update(values)
        observed_plans=build_typed_plans(verified_names_by_kind,held,kinds,control=control)
        byte_report={'enabled':False};aliases=set()
        if 'sndasset' in kinds:
            aliases=_alias_clues(store,verified_names_by_kind.get('soundbankalias',set())|extras,control)
            aliases.update(held.get('soundbankalias',set()) if config.profile in ('fnv1a63','fnv1a64') else set())
            sound_donors=verified_names_by_kind.get('sndasset',set())
            target_sounds=held.get('sndasset',set())
            observed_plans.extend(build_sound_plans(sound_donors,target_sounds,aliases,control=control))
            sound_keys={int(row['hash'],16) for row in targets if row['kind']=='sndasset'}
            byte_plans,byte_report=build_final_byte_plans(sound_donors,target_sounds,sound_keys,profile,control=control)
            observed_plans[0:0]=byte_plans
        cross_summary['observed']={'source_verified_names':{kind:len(values) for kind,values in verified_names_by_kind.items()},
            'target_held_names':{kind:len(values) for kind,values in held.items()},
            'target_alias_clues':len(aliases),'alias_clue_policy':'capture-stored-width; candidate-only',
            'plans':len(observed_plans),'candidates':sum(plan.total for _,plan in observed_plans),
            'final_byte':byte_report}
        # Target-measured methods precede broad cross-asset hypotheses.
        cross_plans[0:0]=observed_plans
    if control()!='run':loaded=False
    cross_summary.update({'plans':len(cross_plans),'candidates':sum(plan.total for _,plan in cross_plans)})
    if cross_plans:
        limits=next((plan.metadata for _,plan in cross_plans if 'unbounded_cross_combinations_upper_bound' in plan.metadata),{})
        cross_summary.update({key:limits[key] for key in ('bounded_search','unbounded_cross_combinations_upper_bound',
            'emitted_cross_combinations','omitted_cross_combinations_upper_bound') if key in limits})
        # Preserve the fast literal/title checks, then explore cross-asset
        # clues before spending the remaining budget on numeric expansion.
        split=next((i for i,(_,plan) in enumerate(plans) if plan.metadata['rule'] not in ('literal','title-root','generic-animation-root')),len(plans))
        plans[split:split]=cross_plans
        progress(0,f'跨资产名称推测 · {len(related_names):,} 个线索名称 · {len(cross_plans):,} 条规则 · {cross_summary["candidates"]:,} 次候选计算')
    from .coverage import snapshot_coverage
    coverage=snapshot_coverage(store,config.indexes,config.exclude_material)
    return dict(imported=imported,chosen=chosen,kinds=kinds,names=names,sources=sources,extra_sources=extra_sources,
        plans=plans,loaded=loaded,cross_summary=cross_summary,coverage=coverage,community=community_summary,domain=domain)

def run(config,progress=lambda *_:None,control=lambda:'run'):
    config=Config(**config) if isinstance(config,dict) else config
    config.validate()
    stamp=datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d-%H%M%S')
    directory=Path(config.output).resolve()/('run-'+stamp+'-'+uuid.uuid4().hex[:6]);directory.mkdir(parents=True)
    (directory/'configuration.json').write_text(json.dumps(asdict(config),ensure_ascii=False,indent=2),encoding='utf-8')
    store=Store(directory/'work.sqlite');processed=0;stage_results=[];start=time.monotonic();cache=None
    def announce(n,message):progress(processed+n,message)
    try:
        from .completedcache import signature,CompletedCache
        snapshot=import_snapshot(config,store,progress,control)
        if snapshot.get('cancelled'):return {'status':'stopped','run_dir':str(directory),'processed':0,'entries':0}
        progress(0,'检查输入内容与完整运行缓存')
        cache=CompletedCache(Path(config.output)/'.namefinder-ledger.sqlite')
        cache_signature=signature(config,store,control)
        cached_record=usable_complete_record(cache.lookup(cache_signature['key'])) if cache_signature else None
        restored=cache.restore(cached_record,store,config.profile,config.low60) if cached_record else None
        cache_reused=restored is not None
        if control()!='run':return {'status':'stopped','run_dir':str(directory),'processed':0,'entries':0}
        if cache_reused:
            from .coverage import snapshot_coverage
            previous=cached_record['summary']
            skipped=previous['processed']+previous.get('skipped_candidates',0)
            stage_results=[{'label':'完整运行复用 · 所有名称再次独立回算','task':None,'total':skipped,
                'processed':0,'position':skipped,'skipped':skipped,'cached_hits':restored['total'],
                'backend_stats':{},'status':'completed','generator':'complete-run-cache','rule':'content-fingerprint'}]
            prepared={**snapshot,'names':None,'corpus_names':previous['corpus_names'],
                'sources':[row for row in cache_signature['sources'] if row.get('role')=='index'],
                'extra_sources':[row for row in cache_signature['sources'] if row.get('role')!='index'],
                'plans':[],'loaded':True,'cross_summary':previous['cross_asset'],
                'coverage':snapshot_coverage(store,config.indexes,config.exclude_material),
                'community':previous['community']}
            # Current paths are provenance, while the reusable content key is path-free.
            prepared['cross_summary']={**prepared['cross_summary'],'related_folder':config.related_folder if prepared['cross_summary']['enabled'] else ''}
            progress(0,f'复用完整计划 · 跳过 {skipped:,} 次计算 · 独立回算 {restored["total"]:,} 条名称证据')
        else:
            prepared=prepare(config,store,progress,control,snapshot=snapshot)
            # A community refresh may have changed the content during prepare.
            if config.community and (config.community_refresh or cache_signature is None):
                cache_signature=signature(Config(**{**asdict(config),'community_refresh':False}),store,control)
        if prepared.get('cancelled'):return {'status':'stopped','run_dir':str(directory),'processed':0,'entries':0}
        imported=prepared['imported'];chosen=prepared['chosen'];names=prepared['names'];sources=prepared['sources']
        extra_sources=prepared['extra_sources'];plans=prepared['plans'];loaded=prepared['loaded'];cross_summary=prepared['cross_summary']
        (directory/'coverage.json').write_text(json.dumps(prepared['coverage'],ensure_ascii=False,indent=2),encoding='utf-8')
        # Candidate-only corpora stay in plans. Only independently verified
        # source rows or target hits enter the persistent words table.
        corpus_names=prepared.get('corpus_names',len(names) if names is not None else 0)
        (directory/'corpus-sources.json').write_text(json.dumps({'indexes':sources,'extra':extra_sources,'names':corpus_names,'cross_asset':cross_summary},ensure_ascii=False,indent=2),encoding='utf-8')
        complete=cache_reused or (loaded and bool(plans));stop_reason=''
        for i,(label,plan) in enumerate(plans):
            remaining=config.budget-processed;seconds=config.seconds-(time.monotonic()-start)
            if control()!='run' or remaining<=0 or seconds<=0:
                complete=False;stop_reason='已停止' if control()!='run' else '本次预算耗尽';break
            progress(processed,f'阶段 {i+1}/{len(plans)}：{label} · {plan.total:,} 次候选计算')
            if not store.targets(exclude_material=config.exclude_material,unknown_only=True):break
            plan_kinds=plan.metadata.get('target_kinds',[])
            if not store.targets(kinds=plan_kinds,exclude_material=config.exclude_material,unknown_only=True):continue
            task=create_task(store,plan,[config.profile],kinds=plan_kinds,exclude_material=config.exclude_material,
                backend=config.backend,budget=remaining,seconds=max(1,seconds),threads=4,duty=75,
                keyword=config.keyword,ledger_path=Path(config.output)/'.namefinder-ledger.sqlite',anyway=config.anyway,
                details={'one_click':True,'stage':label,'index_sources':sources,'content_sources':sources+extra_sources,
                         'target_input_mode':config.input_mode,'snapshot_fingerprint':store.meta('snapshot_fingerprint'),
                         'hash_domain':config.hash_domain,'candidate_generation':plan.metadata})
            result=run_task(store.path,task,announce,control)
            stage_results.append({'label':label,'task':task,'total':plan.total,'processed':result['scanned_candidates'],
                'position':result['position'],'skipped':result['skipped_candidates'],'cached_hits':result['cached_hits'],
                'backend_stats':result['backend_stats'],'status':result['status'],
                'generator':plan.metadata.get('generator'),'rule':plan.metadata.get('rule')})
            processed+=result['scanned_candidates']
            if result['status']!='completed':complete=False;stop_reason=result['message'] or result['status'];break
        if not plans and not cache_reused:complete=False;stop_reason='没有可用候选语料'
        progress(processed,'独立验证已完成，排除 Saluki 已有名称并生成增量文件')
        exported=export(store,directory,kinds=chosen,exclude_material=config.exclude_material,
            keyword=config.keyword,saluki_dir=config.indexes,allow_empty=True,profile_id=config.profile)
        ready=None
        if exported['entries']:
            progress(processed,'准备可复制到 Saluki 的合并索引，保留旧条目')
            ready=prepare_saluki(exported['path'],config.indexes,directory/'saluki-ready')
        pending_count=store.db.execute("SELECT COUNT(DISTINCT hash||name) FROM evidence WHERE method='partial_match'").fetchone()[0]
        if pending_count:
            with (directory/'pending-low60.csv').open('w',encoding='utf-8',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['truncated_hash','candidate_name','status'])
                writer.writerows((r['hash'],r['name'],'UNVERIFIED_LOW60') for r in store.db.execute("SELECT DISTINCT hash,name FROM evidence WHERE method='partial_match'"))
        matched=store.db.execute("SELECT COUNT(DISTINCT hash) FROM evidence WHERE method NOT IN ('partial_match','prior_partial')").fetchone()[0]
        report={'version':VERSION,'status':'completed' if complete else 'partial','reason':stop_reason,
            'run_dir':str(directory),'path':exported['path'],'processed':processed,'stages':stage_results,
            'new_names_csv':exported['new_names_csv'],
            'input':imported,'coverage':prepared['coverage'],'hash_domain':config.hash_domain,
            'community':prepared['community'],
            'domain_evidence':prepared['domain'],
            'ledger':str(Path(config.output)/'.namefinder-ledger.sqlite'),
            'skipped_candidates':sum(stage['skipped'] for stage in stage_results),
            'cached_hits':sum(stage['cached_hits'] for stage in stage_results),
            'corpus_names':corpus_names,'verified_target_matches':matched,'cross_asset':cross_summary,
            'complete_cache_reused':cache_reused,
            'saluki_ready':ready['path'] if ready else None,'pending_low60_candidates':pending_count,'entries':exported['entries'],'excluded_existing':exported['excluded_saluki_existing_keys'],
            'saluki_exclusion_counts':exported['saluki_exclusion_counts'],'full_keys':not config.low60,
            'saluki_live_verified':False,'seconds':round(time.monotonic()-start,3)}
        if complete and not cache_reused and cache_signature:
            # Do not attach completed evidence to inputs replaced during a run.
            final_signature=signature(Config(**{**asdict(config),'community_refresh':False}),store,control)
            used_sources={str(Path(row['file']).resolve()):row['sha256'] for row in sources+extra_sources if row.get('file')}
            current_sources={str(Path(row['file']).resolve()):row['sha256'] for row in final_signature['sources']} if final_signature else {}
            stable_sources=all(current_sources.get(path)==digest for path,digest in used_sources.items())
            stable_sources=stable_sources and all(row['sha256'] in current_sources.values()
                for row in extra_sources if row.get('community'))
            if final_signature and final_signature['key']==cache_signature['key'] and stable_sources:
                cache.save(cache_signature['key'],store,report)
                report['complete_cache_saved']=True
            else:report['complete_cache_saved']=False
        (directory/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        progress(processed,f'输出 {report["entries"]} 项，排除已有 {report["excluded_existing"]} 项')
        return report
    finally:
        if cache:cache.close()
        store.close()
