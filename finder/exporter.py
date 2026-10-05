import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid
from .formats import encode_cdb,decode_cdb
from .hashing import parse_hash
from . import VERSION

SALUKI_PACKAGES={
    'sndasset':'fnv1a_xsounds_v2.cdb',
    'xanim':'fnv1a_xanims_v2.cdb',
    'image':'fnv1a_ximages_v2.cdb',
    'material':'fnv1a_xmaterials_v2.cdb',
    'soundbank':'fnv1a_soundbanks_v2.cdb',
    'soundbanktransient':'fnv1a_soundbanks_v2.cdb',
    'animpkg':'fnv1a_animpkgs_v2.cdb',
    'soundbankalias':'fnv1a_soundbanks_aliases_v2.cdb','bone':'fnv1a_bones_v2.cdb',
}

def _saluki_known_matches(directory, targets, entries=None):
    """Match full keys and exact name text, without altering either hash domain."""
    targets=set(targets)
    target_names={}
    if entries is not None:
        for h,name in entries.items():
            if h in targets and name and name.strip():
                target_names.setdefault(name,set()).add(h)
    root=Path(directory)
    packages=root/'hash_pkg' if (root/'hash_pkg').is_dir() else root
    files=sorted(packages.rglob('*.cdb')) if packages.is_dir() else []
    if not files:raise ValueError('Saluki 目录没有可读取的 hash_pkg/*.cdb，无法排除已有名称')
    by_key=set();by_name=set();sources=[]
    for file in files:
        try:
            blob=file.read_bytes()
            values=decode_cdb(blob)
        except Exception as e:raise ValueError(f'Saluki 索引读取失败：{file.name}: {e}') from e
        for h,name in values.items():
            if not name.strip():continue
            if h in targets:by_key.add(h)
            by_name.update(target_names.get(name,()))
        sources.append({'file':str(file.relative_to(packages)),'sha256':hashlib.sha256(blob).hexdigest()})
    return by_key,by_name,sources


def saluki_known_keys(directory, targets, entries=None):
    """Return excluded target hashes and source fingerprints.

    The two-argument API checks full keys. Optional ``entries`` maps those
    full integer keys to names and also excludes exact existing name text,
    including names stored with old or truncated index keys. No normalization
    or current-key truncation is performed.
    """
    by_key,by_name,sources=_saluki_known_matches(directory,targets,entries)
    return by_key|by_name,sources


def export(store,directory,kinds=(),exclude_material=True,keyword='',new_only=False,saluki_dir=None,allow_empty=False,profile_id=None):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    target={r['hash'] for r in store.targets(kinds,exclude_material)}
    conflicts={r[0] for r in store.db.execute('SELECT hash FROM evidence GROUP BY hash '
                                           'HAVING COUNT(DISTINCT name)>1')}
    rows=[dict(r) for r in store.db.execute('SELECT * FROM evidence ORDER BY name,hash')
          if r['hash'] in target and r['hash'] not in conflicts
          and r['method'] not in ('prior_partial','partial_match')
          and (not keyword or keyword.lower() in r['name'].lower())
          and (not new_only or r['method']!='catalog_verified')]
    entries={parse_hash(r['hash']):r['name'] for r in rows}
    if not entries and not allow_empty:
        raise ValueError('没有符合筛选且无冲突的已验证结果')
    excluded=set();saluki_sources=[];excluded_by_key=set();excluded_by_name=set()
    if saluki_dir is not None:
        excluded_by_key,excluded_by_name,saluki_sources=_saluki_known_matches(saluki_dir,set(entries),entries)
        excluded=excluded_by_key|excluded_by_name
        entries={h:n for h,n in entries.items() if h not in excluded}
        rows=[r for r in rows if parse_hash(r['hash']) not in excluded]
    name=time.strftime('names-%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
    staging=Path(tempfile.mkdtemp(prefix='.export-',dir=directory))
    try:
        cdb=encode_cdb(entries)
        if decode_cdb(cdb)!=entries:
            raise RuntimeError('CDB 回读集合不一致')
        (staging/'verified.cdb').write_bytes(cdb)
        by_package={}
        for asset in store.targets(kinds,exclude_material):
            h=parse_hash(asset['hash'])
            if h in entries:
                package=SALUKI_PACKAGES.get(asset['kind'],'fnv1a_strings.cdb')
                if asset['kind']=='bone' and profile_id=='fnv1a32':package='fnv1a_bones.cdb'
                elif asset['kind']=='bone' and profile_id=='fnv1a60':package='fnv1a_strings.cdb'
                elif asset['kind']=='soundbankalias' and store.meta('build') not in ('BO4','BOCW'):
                    package='fnv1a_soundbanks_aliases_v2.cdb'
                elif asset['kind']=='bone' and profile_id=='fnv1a64':package='fnv1a_bones_v2.cdb'
                elif profile_id in ('fnv1a63','fnv1a64','fnv1a64-raw','sab-fnv1a64'):package=package.replace('_v2.cdb','.cdb')
                by_package.setdefault(package,{})[h]=entries[h]
        package_dir=staging/'hash_pkg';package_dir.mkdir()
        for package,values in by_package.items():
            blob=encode_cdb(values)
            if decode_cdb(blob)!=values:raise RuntimeError('分类 CDB 回读失败')
            (package_dir/package).write_bytes(blob)
        with (staging/'verified.csv').open('w',encoding='utf-8',newline='') as f:
            writer=csv.writer(f)
            writer.writerows((f'{h:016x}',n) for h,n in sorted(entries.items()))
        shutil.copy2(staging/'verified.csv',staging/'new_names.csv')
        with (staging/'evidence.jsonl').open('w',encoding='utf-8') as f:
            for r in rows:
                r['details']=json.loads(r['details'])
                if r.get('mask_used') not in (None,''):r['mask_used']=int(r['mask_used'])
                f.write(json.dumps(r,ensure_ascii=False)+'\n')
        # The Saluki two-column CSV stays unchanged. Provenance has its own
        # headed CSV so downstream auditing can inspect method and mask fields.
        with (staging/'evidence.csv').open('w',encoding='utf-8',newline='') as f:
            fields=['hash','name','profile','source','source_game','method','method_id',
                    'method_version','generator_sha','profile_id','mask_used','details']
            writer=csv.DictWriter(f,fieldnames=fields)
            writer.writeheader()
            for r in rows:
                item={field:r.get(field,'') for field in fields}
                item['details']=json.dumps(item['details'],ensure_ascii=False,sort_keys=True)
                writer.writerow(item)
        manifest={'version':VERSION,'build':store.meta('build'),'catalog_sha256':store.meta('catalog_fingerprint'),
            'entries':len(entries),'excluded_conflict_keys':len(conflicts & target),'keyword':keyword,
            'types':list(kinds) or 'all-non-model','exclude_material':exclude_material,
            'excluded_saluki_existing_keys':len(excluded),'saluki_dir':str(saluki_dir) if saluki_dir is not None else None,
            'saluki_exclusion_counts':{'by_key':len(excluded_by_key),'by_name':len(excluded_by_name),
                'both':len(excluded_by_key&excluded_by_name),'key_only':len(excluded_by_key-excluded_by_name),
                'name_only':len(excluded_by_name-excluded_by_key),'total':len(excluded)},
            'saluki_index_sources':saluki_sources,'new_only':new_only,'full_keys':True,'roundtrip_verified':True,
            'target_profile':profile_id,'new_names_csv':'new_names.csv','saluki_live_verified':False,'package_layout':'Saluki 0.2.42 binary-observed names; live check required',
            'files':{}}
        for path in staging.rglob('*'):
            if path.is_file():manifest['files'][path.relative_to(staging).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
        (staging/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        final=directory/name
        os.replace(staging,final)
        return {'path':str(final),**manifest,'new_names_csv':str((final/'new_names.csv').resolve())}
    except BaseException:
        shutil.rmtree(staging)
        raise

def prepare_saluki(export_dir,saluki_dir,output):
    """Prepare merged indexes without overwriting the user's existing installation."""
    source=Path(export_dir)/'hash_pkg'
    destination=Path(output)
    if destination.exists():raise ValueError('准备目录已存在，请使用新目录')
    incoming=list(source.glob('*.cdb'))
    if not incoming:raise ValueError('导出目录缺少分类 CDB')
    parent=destination.parent;parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.saluki-',dir=parent))
    report={'saluki_dir':str(saluki_dir),'live_verified':False,'files':[],'conflicts':[]}
    try:
        pkg=staging/'hash_pkg';pkg.mkdir()
        for file in incoming:
            new=decode_cdb(file.read_bytes())
            old_root=Path(saluki_dir)
            old_root=old_root/'hash_pkg' if (old_root/'hash_pkg').is_dir() else old_root
            old_path=old_root/file.name
            old=decode_cdb(old_path.read_bytes()) if old_path.exists() else {}
            conflicts=[f'{h:016x}' for h,n in new.items() if h in old and old[h]!=n]
            if conflicts:
                report['conflicts'].append({'file':file.name,'hashes':conflicts})
                # Keep old mappings intact, and explicitly omit incompatible incoming pairs.
                new={h:n for h,n in new.items() if f'{h:016x}' not in set(conflicts)}
            merged={**old,**new}
            blob=encode_cdb(merged,allow_existing_names=True)
            if decode_cdb(blob)!=merged:raise RuntimeError('合并索引回读失败')
            (pkg/file.name).write_bytes(blob)
            report['files'].append({'file':file.name,'old_entries':len(old),'incoming_entries':len(new),
                'merged_entries':len(merged),'original_sha256':hashlib.sha256(old_path.read_bytes()).hexdigest() if old_path.exists() else None,
                'sha256':hashlib.sha256(blob).hexdigest()})
        (staging/'merge-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        (staging/'使用说明.txt').write_text('关闭 Saluki 后先备份原 hash_pkg 中的同名文件，再复制本目录 hash_pkg 中的文件。\n'
            '这是本地已有索引与新结果的合并文件，不应公开再分发。Saluki 自动更新可能覆盖手工索引。\n'
            '未完成 Saluki 界面实时加载验收，请查看 merge-report.json。\n',encoding='utf-8')
        os.replace(staging,destination)
        return dict(report,path=str(destination))
    except BaseException:
        shutil.rmtree(staging);raise
