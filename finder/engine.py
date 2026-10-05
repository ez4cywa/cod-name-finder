import json
import time
from .store import Store
from .hashing import PROFILES,Profile,parse_hash
from .candidates import Plan
from .backends import CPU
from .peeling import choose_backend,forward_backend
from .methods import SharedLedger,method_descriptor,plan_fingerprint,targets_fingerprint

def create_task(store,plan,profiles,kinds=(),exclude_material=True,package='',backend='auto',
                budget=1000000,seconds=3600,threads=4,device=0,duty=100,keyword='',details=None,unknown_only=True,
                ledger_path=None,anyway=False):
    targets=store.targets(kinds,exclude_material,package,unknown_only=unknown_only)
    if not targets:
        raise ValueError('筛选范围没有资产')
    if budget <= 0 or seconds <= 0 or not 1 <= duty <= 100:
        raise ValueError('预算/时间/占空比无效')
    if not profiles or any(p not in PROFILES for p in profiles):
        raise ValueError('选择至少一个有效哈希配置')
    # Only use profiles demonstrated by known target names of the same asset type.
    calibrated={(r['kind'],r['profile']) for r in store.db.execute('SELECT * FROM calibration')}
    eligible={p:sorted({r['hash'] for r in targets if (r['kind'],p) in calibrated}) for p in profiles}
    eligible={p:h for p,h in eligible.items() if h}
    unsupported=sorted({r['kind'] for r in targets if not any((r['kind'],p) in calibrated for p in profiles)})
    if not eligible:
        raise ValueError('所选类型尚无真实名称回算样本，不能自动认证该哈希配置；先导入有证据的目录')
    cfg={'slots':plan.slots,'profiles':list(eligible),'profile_configs':{p:PROFILES[p].json() for p in eligible},'targets':eligible,'unsupported_types':unsupported,
         'kinds':list(kinds),'exclude_material':exclude_material,'package':package,
         'backend':backend,'budget':int(budget),'seconds':float(seconds),'threads':int(threads),
         'device':device,'duty':duty,'keyword':keyword,'details':details or {},'total':plan.total}
    cfg['unknown_only']=unknown_only
    cfg['target_truncated']=store.meta('target_truncated','0')=='1'
    cfg['ledger_path']=str(ledger_path) if ledger_path else ''
    cfg['anyway']=anyway
    cfg['method_descriptor']=method_descriptor(getattr(plan,'metadata',None) or cfg['details'].get('candidate_generation'))
    return store.new_task(cfg)

def run_task(path,task_id,progress=lambda *_:None,control=lambda:'run'):
    store=Store(path)
    ledger=None;backends=[];runs={};measurements={};start=time.perf_counter();scanned=0;skipped=0;restored=0
    def result():
        item=dict(store.task(task_id))
        item.update(scanned_candidates=scanned,skipped_candidates=skipped,cached_hits=restored,
                    backend_stats=[getattr(b,'stats',{}) for _,_,b in backends if b is not None])
        return item
    try:
        task=store.task(task_id)
        cfg=json.loads(task['config'])
        if cfg['catalog_fingerprint']!=store.meta('catalog_fingerprint'):
            raise ValueError('目录快照改变，无法恢复旧任务')
        plan=Plan(cfg['slots'])
        position=task['position']
        if task['status']=='cancelled':
            raise ValueError('取消任务不能恢复，请新建任务')
        profiles=[Profile(**cfg['profile_configs'][p]) for p in cfg['profiles']]
        if cfg.get('target_truncated'):
            from dataclasses import replace
            profiles=[replace(p,mask=p.mask&((1<<60)-1)) for p in profiles]
            progress(position,'目标只有低 60 位；命中保存为待核验候选，不进入正式导出')
        descriptor=cfg.get('method_descriptor') or method_descriptor(cfg['details'].get('candidate_generation'))
        if cfg.get('ledger_path'):ledger=SharedLedger(cfg['ledger_path'])
        fingerprints={};scopes={}
        if cfg['unsupported_types']:
            progress(position,'以下类型缺少目标算法样本，本次不自动搜索：'+','.join(cfg['unsupported_types']))
        for profile in profiles:
            targets={parse_hash(h) for h in cfg['targets'][profile.id]}
            scopes[profile.id]=profile.id+':'+','.join(sorted(cfg['kinds']))
            fingerprints[profile.id]=plan_fingerprint(plan,profiles=[profile],targets={profile.id:cfg['targets'][profile.id]},
                catalog_fingerprint=cfg['catalog_fingerprint'],method=descriptor,
                sources=cfg['details'].get('content_sources',cfg['details'].get('index_sources',[])),
                options={'keyword':cfg['keyword'],'low60':bool(cfg.get('target_truncated')),
                         'kinds':cfg['kinds'],'exclude_material':cfg['exclude_material'],
                         'domain':cfg['details'].get('hash_domain','')})
            if ledger:
                cached=ledger.restore_hits(fingerprints[profile.id],scopes[profile.id],store,asset_kinds=cfg['kinds'])
                restored+=cached['total']
            backends.append((profile,targets,None))
        with store.db:
            store.status(task_id,'running',position=position)
        hits_count=0
        batch=65536
        while position<plan.total:
            # The logical cursor may cross cached ranges without spending the
            # caller's budget. Only newly scanned candidate positions count.
            ranges={p.id:(ledger.remaining(fingerprints[p.id],scopes[p.id],position,plan.total)
                         if ledger else [(position,plan.total)]) for p,_,_ in backends}
            begins=[r[0][0] for r in ranges.values() if r]
            next_begin=min(begins) if begins else plan.total
            if next_begin>position:
                skipped+=next_begin-position;position=next_begin
                with store.db:store.status(task_id,'running',f'复用已扫区间，恢复 {restored} 项命中',position)
                progress(scanned,f'跳过已扫候选 {skipped:,} 项 · 恢复 {restored} 项命中')
            if position==plan.total:break
            if scanned>=cfg['budget']:break
            action=control()
            if action in ('pause','cancel'):
                with store.db:
                    store.status(task_id,'paused' if action=='pause' else 'cancelled',position=position)
                return result()
            if time.perf_counter()-start>=cfg['seconds']:
                with store.db:
                    store.status(task_id,'budget_exhausted','本次时间预算耗尽，可恢复',position)
                return result()
            active={p.id for p,_,_ in backends if ranges[p.id] and ranges[p.id][0][0]<=position<ranges[p.id][0][1]}
            boundaries=[r[0][1] if r[0][0]<=position else r[0][0] for r in ranges.values() if r]
            n=min(batch,plan.total-position,cfg['budget']-scanned,min(boundaries)-position)
            tick=time.perf_counter()
            pending=[]
            for j,(profile,targets,backend) in enumerate(backends):
                if profile.id not in active:continue
                if backend is None:
                    if ledger:
                        runs[profile.id]=ledger.start_run(descriptor,targets_fingerprint({profile.id:cfg['targets'][profile.id]}),
                            profile=profile.json(),parameters={**descriptor['parameters'],'plan_sha256':fingerprints[profile.id]},anyway=cfg.get('anyway',False))
                        measurements[profile.id]={'candidates':0,'names':0}
                    backend,info=choose_backend(cfg['backend'],plan,profile,targets,cfg['threads'],cfg['device'])
                    backends[j]=(profile,targets,backend)
                    progress(scanned,json.dumps(info,ensure_ascii=False))
                try:
                    hits=backend.scan(position,n)
                except Exception as error:
                    if isinstance(backend,CPU) and backend.name=='Rust CPU':
                        raise
                    backend=forward_backend(plan,profile,targets,cfg['threads'])
                    backends[j]=(profile,targets,backend)
                    progress(scanned,'计算后端故障，当前批次以 CPU 重跑：'+str(error))
                    hits=backend.scan(position,n)
                for local in hits:
                    name=plan.at(position+local)
                    if not name:continue
                    # Keyword controls candidate membership, never guesses unknown target names.
                    if cfg['keyword'] and cfg['keyword'].lower() not in name.lower():
                        continue
                    h=profile.digest(name)
                    if h not in targets:
                        raise RuntimeError('后端命中未通过独立 CPU 回算')
                    pending.append((h,profile.normalize(name),profile))
            elapsed=time.perf_counter()-tick
            next_position=position+n
            before={tuple(row) for row in store.db.execute('SELECT DISTINCT hash,name FROM evidence')}
            with store.db:
                for h,name,p in pending:
                    store.add_evidence(h,name,p.id,task_id,cfg['build'],'partial_match' if cfg.get('target_truncated') else 'discovered',
                        {'candidate_range':[position,next_position],'task':task_id,
                         'target_profile':p.json(),**cfg['details']},**{k:descriptor[k] for k in ('method_id','method_version','generator_sha')},
                        profile_id=p.id,mask_used=p.mask)
                    store.db.execute('INSERT OR IGNORE INTO words VALUES (?)',(name,))
                store.status(task_id,'running',f'新增命中 {len(pending)}',next_position)
            for p,_,_ in backends:
                if p.id in measurements and p.id in active:
                    measurements[p.id]['candidates']+=n
                    measurements[p.id]['names']+=len({(f'{h:016x}',name) for h,name,pr in pending if pr.id==p.id}-before)
            if ledger:
                for p,_,_ in backends:
                    if p.id in active:
                        evidence=[dict(row) for row in store.db.execute('SELECT * FROM evidence WHERE source=? AND profile=?',(task_id,p.id))
                                  if json.loads(row['details']).get('candidate_range')==[position,next_position]]
                        ledger.record_sweep(fingerprints[p.id],scopes[p.id],position,next_position,hits=evidence,run_id=runs.get(p.id))
            hits_count+=len(pending)
            position=next_position
            scanned+=n
            progress(scanned,f'{position:,}/{plan.total:,} · {n/max(elapsed,1e-6):,.0f} 候选/秒 · '
                     f'本次命中 {hits_count} · '+','.join(b.name for _,_,b in backends if b is not None))
            # Keep display GPU batches short and cooperate with pause requests.
            if elapsed>0.15 and batch>1024:
                batch=max(1024,batch//2)
            if cfg['duty']<100:
                sleep_until=time.perf_counter()+elapsed*(100-cfg['duty'])/cfg['duty']
                while control()=='run':
                    # Control-file IO or a scheduling delay can cross the deadline.
                    # Sample after the callback, then use that same positive duration.
                    remaining=sleep_until-time.perf_counter()
                    if remaining<=0:break
                    time.sleep(min(0.05,remaining))
        state='completed' if position==plan.total else 'budget_exhausted'
        with store.db:
            store.status(task_id,state,'候选空间已覆盖' if state=='completed' else '本次候选预算耗尽，可恢复',position)
        return result()
    except Exception as error:
        with store.db:
            store.status(task_id,'failed',str(error))
        raise
    finally:
        for _,_,backend in backends:
            if backend is not None and hasattr(backend,'close'):backend.close()
        if ledger:
            status=store.task(task_id)['status']
            for profile_id,run_id in runs.items():
                ledger.finish_run(run_id,**measurements[profile_id],duration=time.perf_counter()-start,status=status)
            ledger.close()
        store.close()
