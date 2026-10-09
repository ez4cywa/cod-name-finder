"""Local method provenance and transactional, content-addressed sweep reuse.

This implementation is independent of upstream code. A sweep only becomes
reusable after its independently verified hits have been saved in the same
transaction. Reusing a sweep restores those hits before a new run exports.
"""
import hashlib
from functools import lru_cache
import json
import math
from pathlib import Path
import sqlite3
import time
import uuid

from .hashing import PROFILES, Profile, parse_hash
from .scanidentity import scan_signature

FINGERPRINT_VERSION = 1
METHOD_VERSION = '1'
_SOURCE_MODULES = {
    'sound-observed': 'soundplans.py', 'sound-final-byte': 'soundbyte.py', 'typed-observed': 'typedplans.py',
    'cross-asset': 'crossassets.py', 'local-observed': 'autoplans.py',
    'weapon': 'weapon.py', 'catalog': 'store.py', 'prior': 'store.py',
}
_PATH_KEYS = frozenset(('file','path','folder','output','indexes','dictionary',
                       'related_folder','catalog_path','saluki_dir','run_dir',
                       'task','run_id','source_path'))


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


@lru_cache(maxsize=32)
def _generator_sha(filename,mtime_ns,size):
    return hashlib.sha256(Path(filename).read_bytes()).hexdigest()


def semantic_parameters(value):
    """Remove location/bookkeeping keys; retain actual candidate name strings."""
    if isinstance(value, dict):
        return {str(key): semantic_parameters(item) for key,item in value.items()
                if str(key) not in _PATH_KEYS and not str(key).endswith('_path')}
    if isinstance(value, (list, tuple)):
        return [semantic_parameters(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((semantic_parameters(item) for item in value), key=canonical_json)
    if isinstance(value, Path):
        raise ValueError('方法指纹不可包含文件路径，请使用内容 SHA256')
    return value


def method_descriptor(metadata=None):
    """Stable rule identity, implementation version/hash, and semantic parameters."""
    metadata = dict(metadata or {})
    if 'generator' not in metadata and 'weapon' in metadata and 'seed_names' in metadata:
        metadata.update(generator='weapon-observed-v1',rule='observed-family')
    generator = str(metadata.get('generator', 'explicit-plan'))
    rule = str(metadata.get('rule', generator))
    family = next((key for key in _SOURCE_MODULES if generator.startswith(key)), 'explicit')
    identifiers = {
        'sound-observed': 'soundplans', 'sound-final-byte': 'soundbyte', 'typed-observed': 'typedplans',
        'cross-asset': 'crossassets', 'local-observed': 'autoplans',
        'catalog': 'catalog', 'prior': 'prior', 'weapon': 'weapon', 'explicit': 'plan',
    }
    # The name has no transient stage labels, task IDs or absolute paths.
    method_id = metadata.get('method_id') or identifiers[family] + '.' + rule.replace('-', '_')
    source = Path(__file__).with_name(_SOURCE_MODULES.get(family, 'candidates.py'))
    try:stat = source.stat()
    except FileNotFoundError as error:
        raise ValueError(f'软件缺少生成器校验资源 {source.name}；请重新安装完整发布包') from error
    generator_sha = metadata.get('generator_sha') or _generator_sha(str(source),stat.st_mtime_ns,stat.st_size)
    return {
        'method_id': str(method_id),
        'method_version': str(metadata.get('method_version', METHOD_VERSION)),
        'generator_sha': str(generator_sha),
        'parameters': semantic_parameters(metadata),
    }


def source_fingerprints(sources):
    """Index paths are intentionally absent; file content changes invalidate reuse."""
    normalized = []
    for source in sources or ():
        if isinstance(source,str):
            normalized.append({'sha256': source})
        else:
            digest = source.get('sha256') or source.get('source_sha256')
            if not digest:
                raise ValueError('语料来源缺少 SHA256，不能安全复用扫掠')
            normalized.append({key: source[key] for key in
                ('candidate_corpus', 'borrowed', 'verified', 'domain', 'kind') if key in source}
                | {'sha256': digest})
    return sorted(normalized, key=canonical_json)


def targets_fingerprint(targets):
    """Hash unique type/profile + complete target keys, independent of export paths."""
    pairs = set()
    if isinstance(targets,dict):
        for kind,hashes in targets.items():
            pairs.update((str(kind), f'{int(h) if isinstance(h,int) else parse_hash(h):016x}') for h in hashes)
    else:
        for target in targets:
            if hasattr(target,'keys'):
                kind,h = target['kind'],target['hash']
            else:
                kind,h = target[:2]
            pairs.add((str(kind), f'{int(h) if isinstance(h,int) else parse_hash(h):016x}'))
    return _digest(sorted(pairs))


def plan_fingerprint(plan, *, profiles, targets, catalog_fingerprint='',
                     method=None, sources=(), options=None):
    """Include every input affecting membership/verification, excluding locations.

    Slot order is retained because sweep indexes refer to mixed-radix positions.
    Per-profile normalization is included but never collapses equal slots: doing
    so could make an old interval refer to different candidates.
    """
    profile_objects = [p if isinstance(p,Profile) else Profile(**p) for p in profiles]
    profile_objects.sort(key=lambda p:p.id)
    normalized = [{
        'profile': p.json(),
        'slots': [[p.normalize(value) if value else '' for value in slot] for slot in plan.slots],
    } for p in profile_objects]
    descriptor = method or method_descriptor(getattr(plan,'metadata',None))
    return _digest({
        'fingerprint_version': FINGERPRINT_VERSION,
        'scanner': scan_signature(),
        'normalized_plan': normalized,
        'targets_sha256': targets_fingerprint(targets),
        'catalog_fingerprint': catalog_fingerprint,
        'method': semantic_parameters(descriptor),
        'sources': source_fingerprints(sources),
        'options': semantic_parameters(options or {}),
    })


class MethodExhausted(ValueError):
    pass


class SharedLedger:
    """One ledger per user-selected output root; no global or research dependency."""
    def __init__(self,path,*,readonly=False):
        self.path = Path(path)
        self.readonly = bool(readonly)
        if self.readonly:
            self.path = self.path.resolve(strict=True)
            # A closed WAL DB without a journal can be read immutably, avoiding
            # creation of auxiliary files during a dry-run estimate. If a live
            # writer has a WAL, normal read-only mode must see its commits.
            immutable = '&immutable=1' if not Path(str(self.path)+'-wal').exists() else ''
            self.db = sqlite3.connect(self.path.as_uri()+'?mode=ro'+immutable,uri=True,timeout=60)
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA busy_timeout=60000')
            self.db.execute('PRAGMA query_only=ON')
            return
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db = sqlite3.connect(self.path,timeout=60)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA busy_timeout=60000')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS ledger_meta(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS swept(plan_sha256 TEXT,kind TEXT,
            begin_index INTEGER,end_index INTEGER,
            PRIMARY KEY(plan_sha256,kind,begin_index),
            CHECK(begin_index>=0 AND end_index>begin_index));
        CREATE TABLE IF NOT EXISTS sweep_hits(plan_sha256 TEXT,kind TEXT,hash TEXT,
            name TEXT,profile TEXT,method TEXT,evidence TEXT,
            PRIMARY KEY(plan_sha256,kind,hash,name,profile,method));
        CREATE TABLE IF NOT EXISTS methods(scope_sha256 TEXT PRIMARY KEY,
            method_id TEXT,version TEXT,generator_sha TEXT,profile TEXT,
            targets TEXT,parameters TEXT,candidates INTEGER DEFAULT 0,
            names INTEGER DEFAULT 0,duration REAL DEFAULT 0,runs INTEGER DEFAULT 0,
            zero_streak INTEGER DEFAULT 0,first_run REAL,last_run REAL);
        CREATE TABLE IF NOT EXISTS method_runs(run_id TEXT PRIMARY KEY,
            scope_sha256 TEXT,started REAL,finished REAL,status TEXT,
            candidates INTEGER DEFAULT 0,names INTEGER DEFAULT 0,duration REAL DEFAULT 0,
            anyway INTEGER DEFAULT 0);
        CREATE INDEX IF NOT EXISTS method_runs_scope ON method_runs(scope_sha256,started);
        ''')
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO ledger_meta VALUES ('schema_version','1')")

    def close(self):
        self.db.close()

    def _writable(self):
        if self.readonly:raise ValueError('只读账本不可写入方法或扫掠数据')

    def __enter__(self):
        return self

    def __exit__(self,*_):
        self.close()

    def remaining(self,plan_sha256,kind,begin,end):
        begin,end = self._range(begin,end,allow_empty=True)
        if begin==end:return []
        missing=[];cursor=begin
        for row in self.db.execute('SELECT begin_index,end_index FROM swept '
                'WHERE plan_sha256=? AND kind=? AND end_index>? AND begin_index<? '
                'ORDER BY begin_index',(plan_sha256,kind,begin,end)):
            if row[0]>cursor:missing.append((cursor,min(row[0],end)))
            cursor=max(cursor,row[1])
            if cursor>=end:break
        if cursor<end:missing.append((cursor,end))
        return missing

    @staticmethod
    def _range(begin,end,allow_empty=False):
        if (isinstance(begin,bool) or isinstance(end,bool) or not isinstance(begin,int)
                or not isinstance(end,int) or not 0<=begin<=end<1<<63
                or (begin==end and not allow_empty)):
            raise ValueError('扫掠区间须为有效的 63 位半开区间')
        return begin,end

    @staticmethod
    def _verified_evidence(hit):
        hit = dict(hit)
        details = hit.get('details',{})
        if isinstance(details,str):details=json.loads(details)
        details=dict(details)
        profile_id=hit.get('profile_id') or hit['profile']
        configuration=details.get('target_profile') or details.get('source_profile')
        profile=Profile(**configuration) if configuration else PROFILES.get(profile_id)
        if profile is None:raise ValueError('缓存证据缺少可独立回算的 profile')
        h=int(hit['hash']) if isinstance(hit['hash'],int) else parse_hash(hit['hash'])
        partial=hit['method'] in ('partial_match','prior_partial') or bool(details.get('target_truncated'))
        mask=profile.mask & ((1<<60)-1) if partial else profile.mask
        if profile.digest(hit['name']) & mask != h:
            raise ValueError('缓存命中未通过独立 Python 回算，扫掠不得标记完成')
        if not partial and hit.get('mask_used') not in (None,'',mask,str(mask)):
            raise ValueError('缓存完整键证据的比较掩码不一致')
        details['target_profile']=profile.json()
        if partial:
            details['target_truncated']=True
            if hit['method'] not in ('partial_match','prior_partial'):hit['method']='partial_match'
        hit.update(hash=f'{h:016x}',details=details,profile_id=profile_id,mask_used=mask)
        return hit

    def record_sweep(self,plan_sha256,kind,begin,end,*,hits=(),run_id=None):
        """Caller must pass only a fully completed batch, never a planned interval."""
        self._writable()
        begin,end=self._range(begin,end)
        verified=[self._verified_evidence(hit) for hit in hits]
        # Acquire the writer before reading intervals, avoiding two concurrent
        # writers computing merges from stale snapshots.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            for hit in verified:
                self.db.execute('INSERT OR IGNORE INTO sweep_hits VALUES (?,?,?,?,?,?,?)',
                    (plan_sha256,kind,hit['hash'],hit['name'],hit['profile'],hit['method'],canonical_json(hit)))
            overlaps=list(self.db.execute('SELECT begin_index,end_index FROM swept '
                'WHERE plan_sha256=? AND kind=? AND end_index>=? AND begin_index<=?',
                (plan_sha256,kind,begin,end)))
            if overlaps:
                begin=min(begin,min(row[0] for row in overlaps))
                end=max(end,max(row[1] for row in overlaps))
                self.db.execute('DELETE FROM swept WHERE plan_sha256=? AND kind=? '
                    'AND end_index>=? AND begin_index<=?',(plan_sha256,kind,begin,end))
            self.db.execute('INSERT INTO swept VALUES (?,?,?,?)',(plan_sha256,kind,begin,end))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return len(verified)

    def restore_hits(self,plan_sha256,kind,store,*,asset_kinds=()):
        """Revalidate cached names and only restore keys present in this work DB."""
        if asset_kinds:
            placeholders=','.join('?' for _ in asset_kinds)
            target_rows=store.db.execute('SELECT hash FROM assets WHERE kind IN ('+placeholders+')',list(asset_kinds))
        else:
            # Ledger kind may be a profile/type scope, rather than asset kind.
            # Exact target membership is already included in plan_sha256.
            target_rows=store.db.execute('SELECT hash FROM assets')
        targets={row['hash'] for row in target_rows}
        inserted=0;verified=0;pending=0
        with store.db:
            for row in self.db.execute('SELECT evidence FROM sweep_hits WHERE plan_sha256=? AND kind=? '
                    'ORDER BY hash,name',(plan_sha256,kind)):
                hit=self._verified_evidence(json.loads(row[0]))
                if hit['hash'] not in targets:continue
                if hit['method'] in ('partial_match','prior_partial'):pending+=1
                else:verified+=1
                hit['details'].update(shared_ledger_cache=True,cache_plan_sha256=plan_sha256)
                before=store.db.total_changes
                store.add_evidence(parse_hash(hit['hash']),hit['name'],hit['profile'],
                    hit.get('source','shared-ledger'),hit.get('source_game',store.meta('build')),
                    hit['method'],hit['details'],method_id=hit.get('method_id'),
                    method_version=hit.get('method_version'),generator_sha=hit.get('generator_sha'),
                    profile_id=hit['profile_id'],mask_used=hit['mask_used'])
                inserted += store.db.total_changes-before
        return {'inserted':inserted,'verified':verified,'pending_low60':pending,'total':verified+pending}

    def guard(self,scope_sha256,*,anyway=False):
        row=self.db.execute('SELECT method_id,zero_streak FROM methods WHERE scope_sha256=?',(scope_sha256,)).fetchone()
        if row and row['zero_streak']>=3 and not anyway:
            raise MethodExhausted(f'方法 {row["method_id"]} 对相同目标连续 {row["zero_streak"]} 次没有新名称；使用 --anyway 可继续')
        return True

    def start_run(self,descriptor,targets_sha256,*,profile='',parameters=None,run_id=None,anyway=False):
        self._writable()
        parameters=semantic_parameters(parameters if parameters is not None else descriptor.get('parameters',{}))
        profile=canonical_json(profile) if not isinstance(profile,str) else profile
        scope=_digest({'method_id':descriptor['method_id'],'version':descriptor['method_version'],
            'generator_sha':descriptor['generator_sha'],'profile':profile,
            'targets':targets_sha256,'parameters':parameters})
        run_id=run_id or uuid.uuid4().hex
        now=time.time()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.guard(scope,anyway=anyway)
            self.db.execute('INSERT OR IGNORE INTO methods '
                '(scope_sha256,method_id,version,generator_sha,profile,targets,parameters,first_run,last_run) '
                'VALUES (?,?,?,?,?,?,?,?,?)',(scope,descriptor['method_id'],descriptor['method_version'],
                 descriptor['generator_sha'],profile,targets_sha256,canonical_json(parameters),now,now))
            self.db.execute('INSERT INTO method_runs(run_id,scope_sha256,started,status,anyway) VALUES (?,?,?,?,?)',
                (run_id,scope,now,'running',int(bool(anyway))))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return run_id

    def finish_run(self,run_id,*,candidates=0,names=0,duration=0,status='completed'):
        self._writable()
        if (any(isinstance(value,bool) or not isinstance(value,int) or value<0 for value in (candidates,names))
                or not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<0):
            raise ValueError('方法度量不能为负数')
        now=time.time()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT * FROM method_runs WHERE run_id=?',(run_id,)).fetchone()
            if row is None:raise ValueError('方法运行记录不存在')
            if row['finished'] is not None:
                self.db.rollback()
                return False
            self.db.execute('UPDATE method_runs SET finished=?,status=?,candidates=?,names=?,duration=? WHERE run_id=?',
                (now,status,candidates,names,duration,run_id))
            # Paused, cancelled and failed runs do not prove a method exhausted.
            zero_update='zero_streak+1' if status=='completed' and names==0 else ('0' if names else 'zero_streak')
            self.db.execute('UPDATE methods SET candidates=candidates+?,names=names+?,duration=duration+?,runs=runs+1,'
                f'zero_streak={zero_update},last_run=? WHERE scope_sha256=?',
                (candidates,names,duration,now,row['scope_sha256']))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return True

    def report(self):
        rows=[]
        for row in self.db.execute('SELECT * FROM methods ORDER BY last_run DESC,method_id,scope_sha256'):
            item=dict(row)
            item['parameters']=json.loads(item['parameters'])
            item['names_per_million_candidates']=round(item['names']*1e6/item['candidates'],6) if item['candidates'] else 0
            item['candidates_per_second']=round(item['candidates']/item['duration'],3) if item['duration'] else 0
            item['exhausted']=item['zero_streak']>=3
            item['recent_runs']=[dict(run) for run in self.db.execute('SELECT run_id,started,finished,status,candidates,names,duration,anyway '
                'FROM method_runs WHERE scope_sha256=? ORDER BY started DESC LIMIT 3',(item['scope_sha256'],))]
            rows.append(item)
        grouped={}
        for item in rows:
            key=item['method_id'],item['version'],item['generator_sha']
            total=grouped.setdefault(key,{'method_id':key[0],'version':key[1],'generator_sha':key[2],
                'scopes':0,'runs':0,'candidates':0,'names':0,'duration':0,
                'first_run':item['first_run'],'last_run':item['last_run'],'exhausted_scopes':0})
            for field in ('runs','candidates','names','duration'):total[field]+=item[field]
            total['scopes']+=1
            total['first_run']=min(total['first_run'],item['first_run'])
            total['last_run']=max(total['last_run'],item['last_run'])
            total['exhausted_scopes']+=int(item['exhausted'])
        for item in grouped.values():
            item['names_per_million_candidates']=round(item['names']*1e6/item['candidates'],6) if item['candidates'] else 0
            item['candidates_per_second']=round(item['candidates']/item['duration'],3) if item['duration'] else 0
        return {'ledger':str(self.path.resolve()),'fingerprint_version':FINGERPRINT_VERSION,
                'methods':rows,'summary':sorted(grouped.values(),key=lambda item:(item['method_id'],item['version']))}
