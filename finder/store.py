import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid
import re

from .hashing import PROFILES, Profile, BUILTIN_IDS,ALGORITHMS,parse_hash, batch_digest
from .formats import iter_dictionary
from .asset_names import parse_exported_name

def fingerprint(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=60)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=60000')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS assets(kind TEXT,hash TEXT,packages TEXT,
            PRIMARY KEY(kind,hash));
        CREATE INDEX IF NOT EXISTS assets_hash ON assets(hash);
        CREATE TABLE IF NOT EXISTS evidence(hash TEXT,name TEXT,profile TEXT,
            source TEXT,source_game TEXT,method TEXT,details TEXT,
            UNIQUE(hash,name,profile,source,method));
        CREATE INDEX IF NOT EXISTS evidence_hash ON evidence(hash);
        CREATE TABLE IF NOT EXISTS words(name TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS calibration(kind TEXT,profile TEXT,samples INTEGER,
            PRIMARY KEY(kind,profile));
        CREATE TABLE IF NOT EXISTS asset_files(kind TEXT,hash TEXT,path TEXT,
            PRIMARY KEY(kind,hash,path));
        CREATE TABLE IF NOT EXISTS snapshot_records(pool INTEGER,raw_hash TEXT,kind TEXT,
            profile TEXT,key_width INTEGER,stored_mask TEXT,status TEXT,
            PRIMARY KEY(pool,raw_hash));
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,config TEXT,position INTEGER,
            total INTEGER,status TEXT,message TEXT,updated REAL);
        ''')
        # Load persisted profiles before a legacy mask is backfilled.
        for item in json.loads(self.meta('custom_profiles','[]')):
            p=Profile(**item)
            PROFILES[p.id]=p
        # This runs once, including upgrades whose columns predate the marker.
        # Scanning the large evidence payload at every task open defeats reuse.
        fields=('method_id','method_version','generator_sha','profile_id','mask_used')
        evidence_columns={row[1] for row in self.db.execute('PRAGMA table_info(evidence)')}
        if not set(fields)<=evidence_columns or self.meta('evidence_metadata_schema')!='2':
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                # A second opener may have completed the migration while this
                # connection waited for the write lock.
                evidence_columns={row[1] for row in self.db.execute('PRAGMA table_info(evidence)')}
                if not set(fields)<=evidence_columns or self.meta('evidence_metadata_schema')!='2':
                    for field in fields:
                        if field not in evidence_columns:
                            self.db.execute(f"ALTER TABLE evidence ADD COLUMN {field} TEXT NOT NULL DEFAULT ''")
                    self.db.execute("UPDATE evidence SET profile_id=profile WHERE profile_id=''")
                    self.db.execute("UPDATE evidence SET method_id='legacy.'||method,method_version='0' WHERE method_id=''")
                    for row in self.db.execute("SELECT DISTINCT profile,method FROM evidence WHERE mask_used=''"):
                        profile=PROFILES.get(row['profile'])
                        if profile is not None:
                            mask=profile.mask & ((1<<60)-1) if row['method'] in ('partial_match','prior_partial') else profile.mask
                            self.db.execute("UPDATE evidence SET mask_used=? WHERE profile=? AND method=? AND mask_used=''",
                                            (str(mask),row['profile'],row['method']))
                    self.setmeta('evidence_metadata_schema','2')

    def import_exported(self, folder, game, profile_id, default_kind='sndasset', truncated=False,
                        progress=lambda *_:None, cancelled=lambda:False,kinds=()):
        folder=Path(folder).resolve(strict=True)
        if not folder.is_dir():raise ValueError('请选择导出资产文件夹')
        if profile_id not in PROFILES:raise ValueError('请选择对应作品的哈希规则')
        if self.db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]:
            raise ValueError('已有任务不能替换目标文件夹，请新建工作库')
        records=[];report={'files':0,'recognized_files':0,'hashed_files':0,'unrecognized':0,
            'models_excluded':0,'types_filtered':0,'detected_type_counts':{},'unrecognized_examples':[]}
        for path in folder.rglob('*'):
            if not path.is_file():continue
            if cancelled():return dict(report,cancelled=True)
            report['files']+=1
            parsed=parse_exported_name(path,default_kind,root=folder,min_digits=1 if PROFILES[profile_id].mask<=0xffffffff else 8)
            if not parsed:
                report['unrecognized']+=1
                if len(report['unrecognized_examples'])<5:report['unrecognized_examples'].append(path.name)
                continue
            kind,h=parsed;report['recognized_files']+=1
            report['detected_type_counts'][kind]=report['detected_type_counts'].get(kind,0)+1
            if kind=='xmodel':report['models_excluded']+=1;continue
            if kinds and kind not in kinds:
                report['types_filtered']+=1;continue
            records.append((kind,f'{h:016x}',str(path)))
            report['hashed_files']+=1
            if report['files']%1000==0:progress(report['files'],'扫描已导出的哈希资产')
        if not records:
            if not report['files']:raise ValueError('所选文件夹没有文件，请选择已导出哈希资产的文件夹')
            if report['recognized_files']:
                types='、'.join(f'{k}: {v}' for k,v in sorted(report['detected_type_counts'].items()))
                raise ValueError(f'已识别 {report["recognized_files"]} 个哈希文件，但没有符合所选类型的非模型目标。识别类型：{types}；请核对资产类型，模型始终排除')
            examples='、'.join(report['unrecognized_examples'])
            digits='1至16' if PROFILES[profile_id].mask<=0xffffffff else '8至16'
            raise ValueError(f'扫描 {report["files"]} 个文件，未识别出哈希文件名。支持所有下拉资产类型的前缀，例如 sndbank_<hex>、sound_<hex>、anim_<hex>、rawfile_<hex>，以及 hash_<hex> 或裸哈希；当前规则接受{digits}位十六进制。文件名示例：{examples}')
        # The private snapshot identifies target contents, not disk letters or
        # duplicate exported copies. Paths remain available in asset_files.
        from .methods import targets_fingerprint
        snapshot=targets_fingerprint([(kind,h) for kind,h,_ in records])
        with self.db:
            for table in ('assets','asset_files','evidence','calibration','words','snapshot_records'):
                self.db.execute('DELETE FROM '+table)
            self.db.executemany('INSERT OR IGNORE INTO asset_files VALUES (?,?,?)',records)
            self.db.execute('INSERT INTO assets SELECT kind,hash,GROUP_CONCAT(path) FROM asset_files GROUP BY kind,hash')
            self.db.executemany('INSERT INTO calibration VALUES (?,?,?)',
                [(kind,profile_id,0) for kind in sorted({r[0] for r in records})])
            self.setmeta('catalog_fingerprint',snapshot)
            self.setmeta('catalog_path',folder)
            self.setmeta('build',game)
            self.setmeta('input_mode','exported-files')
            self.setmeta('exported_profile',json.dumps(PROFILES[profile_id].json()))
            self.setmeta('target_truncated',int(truncated))
            for key in ('snapshot_fingerprint','snapshot_dictionary','snapshot_sources','snapshot_metadata'):
                self.setmeta(key,'')
        return dict(report,unique_assets=self.db.execute('SELECT COUNT(*) FROM assets').fetchone()[0],
                    profile=profile_id,truncated=truncated,selected_types=list(kinds) or 'auto')

    def import_snapshot(self, path, game, profile_id, *, kinds=(), exclude_material=True,
                        truncated=False, progress=lambda *_:None, cancelled=lambda:False):
        """Import verified pool domains; preserve skipped raw keys for inspection."""
        from collections import Counter
        from .snapshot import read_snapshot,normalize_game,_Cancelled
        from .methods import canonical_json
        if profile_id not in PROFILES:raise ValueError('请选择对应作品的哈希规则')
        if self.db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]:
            raise ValueError('已有任务不能替换快照，请新建工作库')
        source=read_snapshot(path,control=lambda:'stop' if cancelled() else 'run')
        if source is None:return {'cancelled':True}
        if normalize_game(game)!=source['game']:raise ValueError('快照所属作品与所选作品不一致')
        profile=PROFILES[profile_id];pools=source['pools'];statuses={};detected=Counter();skipped=Counter()
        for pool,item in pools.items():
            kind=item['kind'];status='included'
            if kind is None:status='unknown_pool'
            elif kind=='xmodel':status='model_excluded'
            elif exclude_material and kind=='material':status='material_excluded'
            elif kinds and kind not in kinds:status='type_filtered'
            elif item['profile'] is None:status='unknown_domain'
            elif item['profile']!=profile_id:status='profile_mismatch'
            elif profile.mask & int(item['stored_mask'],16)!=profile.mask or profile.mask.bit_length()>item['key_width']:
                status='domain_lost_bits'
            statuses[pool]=status
            if kind:detected[kind]+=item['count']
            if status!='included':skipped[status]+=item['count']
        report={'files':len(source['records']),'recognized_files':len(source['records']),
            'hashed_files':sum(item['count'] for pool,item in pools.items() if statuses[pool]=='included'),
            'unrecognized':skipped['unknown_pool']+skipped['unknown_domain'],
            'models_excluded':skipped['model_excluded'],'types_filtered':skipped['type_filtered'],
            'materials_excluded':skipped['material_excluded'],'detected_type_counts':dict(detected),
            'skipped_counts':dict(skipped),'format':source['format'],'input_mode':'snapshot',
            'key_width':source['key_width'],'snapshot_fingerprint':source['fingerprint'],
            'snapshot_game':source['game'],'snapshot_build':source['build'],
            'complete':source['complete'],'complete_scope':source['complete_scope'],
            'loaded_scope':source.get('loaded_scope',[]),
            'verified_scope_pools':source.get('verified_scope_pools'),
            'whole_snapshot_stable':source.get('whole_snapshot_stable'),
            'warnings':source['warnings'],'pools':{str(pool):item|{'import_status':statuses[pool]} for pool,item in pools.items()}}
        if not report['hashed_files']:
            reasons='、'.join(f'{key}: {value}' for key,value in sorted(skipped.items()))
            raise ValueError('快照没有与所选作品、类型、完整键算法兼容的非模型目标；'+reasons)
        compare_mask=(1<<60)-1 if truncated else (1<<64)-1
        origin=Path(path).resolve();fingerprint=source['fingerprint']
        metadata={key:source[key] for key in ('format','game','game_id','build','key_width','complete','complete_scope','warnings','pools')}
        metadata.update({key:source[key] for key in ('loaded_scope','verified_scope_pools','whole_snapshot_stable','state_stable','build_fingerprints') if key in source})
        def raw_rows():
            for index,(raw,pool) in enumerate(source['records']):
                if index%8192==0:
                    if cancelled():raise _Cancelled()
                    progress(index,'导入快照原始键与资产池')
                item=pools[pool]
                yield (pool,f'{raw:016x}',item['kind'] or '',item['profile'] or '',
                       item['key_width'],item['stored_mask'],statuses[pool])
        try:
            with self.db:
                for table in ('assets','asset_files','evidence','calibration','words','snapshot_records'):
                    self.db.execute('DELETE FROM '+table)
                self.db.executemany('INSERT INTO snapshot_records VALUES (?,?,?,?,?,?,?)',raw_rows())
                targets=[]
                for index,(raw,pool) in enumerate(source['records']):
                    if index%8192==0 and cancelled():raise _Cancelled()
                    if statuses[pool]!='included':continue
                    item=pools[pool];key=raw & profile.mask & int(item['stored_mask'],16) & compare_mask
                    targets.append((item['kind'],f'{key:016x}',f'snapshot:{fingerprint}:pool={pool}:raw={raw:016x}'))
                    if len(targets)==8192:
                        self.db.executemany('INSERT OR IGNORE INTO asset_files VALUES (?,?,?)',targets);targets.clear()
                if targets:self.db.executemany('INSERT OR IGNORE INTO asset_files VALUES (?,?,?)',targets)
                self.db.execute('INSERT INTO assets SELECT kind,hash,GROUP_CONCAT(path) FROM asset_files GROUP BY kind,hash')
                included=sorted({item['kind'] for pool,item in pools.items() if statuses[pool]=='included' and item['count']})
                self.db.executemany('INSERT INTO calibration VALUES (?,?,?)',[(kind,profile_id,0) for kind in included])
                # Full raw contents and pool domains scope reuse, including
                # duplicate hashes held by different pools; no drive letters.
                self.setmeta('catalog_fingerprint',fingerprint)
                self.setmeta('catalog_path',origin)
                self.setmeta('build',source['game'])
                self.setmeta('input_mode','snapshot')
                self.setmeta('exported_profile',json.dumps(profile.json()))
                self.setmeta('target_truncated',int(truncated))
                self.setmeta('snapshot_fingerprint',fingerprint)
                self.setmeta('snapshot_dictionary',source['strings_path'])
                self.setmeta('snapshot_sources',json.dumps(source['source_files']))
                self.setmeta('snapshot_metadata',canonical_json(metadata))
        except _Cancelled:return dict(report,cancelled=True)
        return dict(report,unique_assets=self.db.execute('SELECT COUNT(*) FROM assets').fetchone()[0],
                    profile=profile_id,truncated=truncated,selected_types=list(kinds) or 'auto')

    def save_profiles(self, items):
        profiles=[]
        for item in items:
            p=Profile(**item)
            if not p.id or not 0<=p.seed<1<<64 or not 0<p.mask<1<<64:
                raise ValueError('自定义 profile 标识/种子/掩码无效')
            if p.id in BUILTIN_IDS:
                raise ValueError('内置配置不能覆盖；请使用新的 profile 标识')
            if p.algorithm not in ALGORITHMS or not 0<p.prime<1<<64:
                raise ValueError('算法或乘数无效')
            p.secret.encode('ascii')
            existing=PROFILES.get(p.id)
            if existing and existing!=p:
                raise ValueError('已有配置不可改变算法，请使用新标识以保留验证来源')
            profiles.append(p)
        with self.db:
            self.setmeta('custom_profiles',json.dumps([p.json() for p in profiles]))
        for p in profiles:PROFILES[p.id]=p

    def close(self):
        self.db.close()

    def meta(self, key, default=''):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return row[0] if row else default

    def setmeta(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, str(value)))

    def add_evidence(self, h, name, profile, source, game, method, details, *,
                     method_id=None, method_version=None, generator_sha=None,
                     profile_id=None, mask_used=None):
        from .methods import method_descriptor
        details = dict(details or {})
        descriptor = method_descriptor(details.get('candidate_generation') or {'generator': method})
        snapshot = details.get('target_profile') or details.get('source_profile')
        known_profile = PROFILES.get(profile)
        if snapshot is None and known_profile is not None:
            snapshot = known_profile.json()
            details['target_profile'] = snapshot
        if mask_used is None:
            mask_used = snapshot.get('mask') if isinstance(snapshot,dict) else None
            if mask_used is None and known_profile is not None:
                mask_used = known_profile.mask
            if mask_used is not None and (method in ('partial_match','prior_partial') or details.get('target_truncated')):
                mask_used &= (1 << 60) - 1
        self.db.execute('INSERT OR IGNORE INTO evidence '
            '(hash,name,profile,source,source_game,method,details,method_id,method_version,generator_sha,profile_id,mask_used) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (f'{h:016x}', name, profile, source, game, method,
             json.dumps(details, ensure_ascii=False, sort_keys=True),
             method_id if method_id is not None else descriptor['method_id'],
             str(method_version if method_version is not None else descriptor['method_version']),
             generator_sha if generator_sha is not None else descriptor['generator_sha'],
             profile_id or profile, '' if mask_used is None else str(mask_used)))

    def import_catalog(self, path, build, progress=lambda *_: None):
        path = Path(path).resolve(strict=True)
        source = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        try:
            columns = {r[1] for r in source.execute('PRAGMA table_info(assets)')}
            if not {'asset_type','name_hash','name','package'} <= columns:
                raise ValueError('需要包含 assets(asset_type,name_hash,name,package) 的目录数据库')
            digest = fingerprint(path)
            if self.meta('catalog_fingerprint') == digest:
                return {'unchanged': True}
            if self.db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]:
                raise ValueError('已有任务的工作库不能替换目录，请新建工作库以保留任务快照')
            profiles = list(PROFILES.values())
            report = {'assets': 0, 'known_verified': 0, 'unverified': 0}
            calibration = {}
            with self.db:
                self.db.execute('DELETE FROM assets')
                self.db.execute('DELETE FROM evidence')
                self.db.execute('DELETE FROM calibration')
                self.db.execute('DELETE FROM words')
                self.db.execute('DELETE FROM asset_files')
                self.db.execute('DELETE FROM snapshot_records')
                cursor = source.execute('SELECT asset_type,name_hash,name,GROUP_CONCAT(DISTINCT package) '
                    'FROM assets GROUP BY asset_type,name_hash,name')
                while rows := cursor.fetchmany(8192):
                    named = [(k, parse_hash(h), n, pk) for k,h,n,pk in rows if n]
                    hashes = [batch_digest([r[2] for r in named], p) for p in profiles] if named else []
                    for kind,h,name,packages in rows:
                        key = parse_hash(h)
                        self.db.execute('INSERT OR IGNORE INTO assets VALUES (?,?,?)',
                                        (kind, f'{key:016x}', packages))
                        report['assets'] += 1
                    for i,(kind,h,name,packages) in enumerate(named):
                        self.db.execute('INSERT OR IGNORE INTO words VALUES (?)', (name,))
                        matching = [p for j,p in enumerate(profiles) if int(hashes[j][i]) == h]
                        if not matching:
                            report['unverified'] += 1
                        for p in matching:
                            normalized = p.normalize(name)
                            self.add_evidence(h, normalized, p.id, digest, build, 'catalog_verified',
                                              {'catalog': str(path), 'asset_type': kind})
                            calibration[(kind,p.id)] = calibration.get((kind,p.id), 0) + 1
                            report['known_verified'] += 1
                    progress(report['assets'], '导入资产目录并回算已有名称')
                self.db.executemany('INSERT INTO calibration VALUES (?,?,?)',
                    [(k,p,n) for (k,p),n in calibration.items()])
                self.setmeta('catalog_fingerprint', digest)
                self.setmeta('catalog_path', path)
                self.setmeta('build', build)
                self.setmeta('input_mode','catalog')
                self.setmeta('target_truncated',0)
                for key in ('snapshot_fingerprint','snapshot_dictionary','snapshot_sources','snapshot_metadata'):
                    self.setmeta(key,'')
            return report
        finally:
            source.close()

    def targets(self, kinds=(), exclude_material=True, package='', unknown_only=False):
        clauses = ["kind != 'xmodel'"]
        args = []
        if exclude_material:
            clauses.append("kind != 'material'")
        if kinds:
            clauses.append('kind IN (' + ','.join('?' for _ in kinds) + ')')
            args.extend(kinds)
        if package:
            clauses.append('instr(packages,?) > 0')
            args.append(package)
        if unknown_only:
            clauses.append('NOT EXISTS(SELECT 1 FROM evidence e WHERE e.hash=assets.hash)')
        return list(self.db.execute('SELECT * FROM assets WHERE ' + ' AND '.join(clauses), args))

    def import_dictionary(self, paths, game, profile_ids, kinds=(), exclude_material=True,
                          keyword='', progress=lambda *_: None, cancelled=lambda: False):
        if not game.strip():
            raise ValueError('请填写来源作品/词典标签')
        profiles = [PROFILES[p] for p in profile_ids]
        targets = {parse_hash(r['hash']) for r in self.targets(kinds, exclude_material)}
        partial=self.meta('target_truncated','0')=='1'
        compare_mask=(1<<60)-1 if partial else (1<<64)-1
        report = {'rows':0,'verified':0,'target_matches':0,'rejected':0,'files':0}
        for path in paths:
            path = Path(path)
            digest = fingerprint(path)
            pending = []
            def flush():
                if not pending:
                    return
                names = [n for _,n in pending]
                sums = [batch_digest(names,p) for p in profiles]
                with self.db:
                    for i,(h,n) in enumerate(pending):
                        matching = [p for j,p in enumerate(profiles) if int(sums[j][i]) == h]
                        if not matching:
                            report['rejected'] += 1
                            continue
                        report['verified'] += 1
                        self.db.execute('INSERT OR IGNORE INTO words VALUES (?)', (n,))
                        target_hash=h & compare_mask
                        if target_hash not in targets or (keyword and keyword.lower() not in n.lower()):
                            continue
                        report['target_matches'] += 1
                        for p in matching:
                            self.add_evidence(target_hash,p.normalize(n),p.id,digest,game,'prior_partial' if partial else 'prior_verified',
                                {'file':str(path),'source_sha256':digest,'source_hash':f'{h:016x}',
                                 'source_profile':p.json(),'target_build':self.meta('build'),
                                 'target_present':True,'full_source_hash':f'{h:016x}',
                                 'target_truncated':partial})
                pending.clear()
                progress(report['rows'], json.dumps(report, ensure_ascii=False))
            for h,name in iter_dictionary(path):
                if cancelled():
                    flush()
                    return dict(report, cancelled=True)
                report['rows'] += 1
                if h is None or not name or any(c in name for c in '\x00\r\n'):
                    report['rejected'] += 1
                    continue
                pending.append((h,name))
                if len(pending) >= 8192:
                    flush()
            flush()
            report['files'] += 1
        return report

    def results(self, kinds=(), exclude_material=True, keyword='', limit=250, offset=0):
        clauses=["a.kind != 'xmodel'",'a.hash=e.hash']
        args=[keyword.lower()]
        if exclude_material:clauses.append("a.kind != 'material'")
        if kinds:
            clauses.append('a.kind IN ('+','.join('?' for _ in kinds)+')')
            args.extend(kinds)
        base=(' FROM evidence e WHERE instr(lower(e.name),?)>0 AND EXISTS '
              '(SELECT 1 FROM assets a WHERE '+' AND '.join(clauses)+') GROUP BY e.hash,e.name')
        n=self.db.execute('SELECT COUNT(*) FROM (SELECT e.hash'+base+')',args).fetchone()[0]
        rows=self.db.execute('SELECT e.hash,e.name,GROUP_CONCAT(DISTINCT e.method) methods,'
            'GROUP_CONCAT(DISTINCT e.profile) profiles,COUNT(DISTINCT e.source) sources'+base+
            ' ORDER BY e.name,e.hash LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
        filtered=[]
        for r in rows:
            item=dict(r)
            item['conflict']=self.db.execute('SELECT COUNT(DISTINCT name) FROM evidence WHERE hash=?',
                                            (r['hash'],)).fetchone()[0]>1
            filtered.append(item)
        return n,filtered

    def new_task(self, config):
        if not self.meta('catalog_fingerprint'):
            raise ValueError('请先导入资产目录')
        config['catalog_fingerprint'] = self.meta('catalog_fingerprint')
        config['build'] = self.meta('build')
        task = uuid.uuid4().hex
        self.db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?)',
            (task,json.dumps(config,ensure_ascii=False),0,config['total'],'queued','',time.time()))
        self.db.commit()
        return task

    def task(self, task):
        r = self.db.execute('SELECT * FROM tasks WHERE id=?',(task,)).fetchone()
        if not r:
            raise ValueError('任务不存在')
        return dict(r)

    def status(self, task, state, message='', position=None):
        if position is None:
            self.db.execute('UPDATE tasks SET status=?,message=?,updated=? WHERE id=?',
                            (state,message,time.time(),task))
        else:
            self.db.execute('UPDATE tasks SET status=?,message=?,position=?,updated=? WHERE id=?',
                            (state,message,position,time.time(),task))
