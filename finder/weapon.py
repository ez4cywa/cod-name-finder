"""Bounded same-weapon exploration from literal seeds and observed name templates."""
import re
from .candidates import Plan

DEFAULT_ACTIONS=('fire','reload','reload_empty','raise','drop','inspect','ads','melee')
DEFAULT_SUFFIXES=('_mp','_sp','_burst','_pdw','_dunn','_fire','_reload','_reload_empty','_inspect')
EXPORT_EXTENSIONS={'.wav','.flac','.ogg','.mp3','.png','.dds','.tga','.tiff','.fbx','.obj','.gltf','.glb'}

def token_pattern(token):
    return re.compile(r'(?<![a-z0-9])'+re.escape(token)+r'(?![a-z0-9])',re.I)

def weapon_plan(seeds, corpus, keyword, options=None):
    options=dict(options or {})
    keyword=keyword.strip()
    if not re.fullmatch(r'[a-z0-9]+(?:_[a-z0-9]+)*',keyword,re.I):
        raise ValueError('同武器探索需要明确的武器代号，例如 mike4；不可留空')
    number_max=options.get('number_max',8)
    limit=options.get('max_candidates',250000)
    if isinstance(number_max,bool) or not isinstance(number_max,int) or not 0<=number_max<=999:
        raise ValueError('number_max 应为 0–999 的整数')
    if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=250000:
        raise ValueError('max_candidates 应为 1–250000 的整数')
    def values(key,default):
        value=options.get(key,default)
        if not isinstance(value,(list,tuple)) or not all(isinstance(v,str) and v and not any(c in v for c in '\x00\r\n') for v in value):
            raise ValueError(key+' 应为非空字符串组成的数组（数组本身可为空）')
        return value
    actions=values('actions',DEFAULT_ACTIONS)
    suffixes=values('suffix',DEFAULT_SUFFIXES)
    donors=values('donor_keywords',[])
    target=token_pattern(keyword)
    def clean(name):
        name=name.strip()
        if not name or any(c in name for c in '\x00\r\n') or len(name.encode('utf-8'))>1024:
            raise ValueError('种子或语料名称无效，名称不得为空、含换行或超过1024字节')
        return name
    corpus=sorted({clean(n) for n in corpus if n})
    seeds=sorted({clean(n) for n in seeds if n.strip()})
    if options.get('strip_export_extension',False):
        seeds=[n.rsplit('.',1)[0] if '.' in n and '.'+n.rsplit('.',1)[1] in EXPORT_EXTENSIONS else n for n in seeds]
    references=set(n for n in seeds if target.search(n))
    references.update(n for n in corpus if target.search(n))
    if not references:
        raise ValueError('没有包含该武器代号的种子；请粘贴已解析名称或先导入名称词典')
    candidates=set()
    def add(name):
        if not target.search(name):return
        if len(name.encode('utf-8'))>1024:return
        candidates.add(name)
        if len(candidates)>limit:
            raise ValueError('同武器候选超过上限，请缩小数字范围、种子或 donor_keywords')
    for name in sorted(references):add(name)
    def root_of(name):return re.split(r'[\\/_.]',name,maxsplit=1)[0].lower()
    source_roots={root_of(n) for n in (seeds or sorted(references)) if not target.search(root_of(n))}
    learned=set()
    weapon_anchor=re.compile(r'(?:^|[/\\])(?:[a-z0-9]+_){0,3}?(?:ar|sm|smg|lm|lmg|dm|sn|sniper|sh|shotgun|pi|pistol|me|melee|la|launcher)_([a-z][a-z0-9]*)',re.I)
    inferred_codes={m.group(1).lower() for name in corpus for m in weapon_anchor.finditer(name)}
    for name in corpus:
        if target.search(name):continue
        if source_roots and not options.get('learn_all_roots',False) and root_of(name) not in source_roots:continue
        tokens=donors or [t for t in re.split(r'[\\/_.\-]',name) if (t.lower() in inferred_codes or re.fullmatch(r'[a-z]+[a-z0-9]*\d[a-z0-9]*',t,re.I)) and not re.fullmatch(r'(?:v|lod)\d+',t,re.I)]
        for donor in tokens:
            if donor.lower()==keyword.lower():continue
            pattern=token_pattern(donor)
            if not pattern.search(name):continue
            derived=pattern.sub(lambda _:keyword,name)
            add(derived);learned.add(derived)
    # One bounded expansion pass: never recursively grow generated guesses.
    for name in sorted(candidates):
        stem,dot,extension=name.partition('.')
        tail=dot+extension
        def add_stem(value):
            add(value+tail)
            numeric=re.search(r'(\d+)$',value)
            spans=list(target.finditer(value))
            if numeric and not any(numeric.start()<m.end() and numeric.end()>m.start() for m in spans):
                for number in range(number_max+1):add(value[:numeric.start()]+str(number).zfill(len(numeric.group()))+tail)
        variant=re.sub(r'_(?:mp|sp|vm|wm|plr|npc)$','',stem)
        if target.search(variant) and target.search(variant).end()==len(variant):
            for suffix in suffixes:add(variant+suffix+tail)
        for a,b in [('_vm_','_wm_'),('_wm_','_vm_'),('_plr_','_npc_'),('_npc_','_plr_')]:
            if a in stem:add_stem(stem.replace(a,b))
        for a,b in [('_mp','_sp'),('_sp','_mp'),('_vm','_wm'),('_wm','_vm')]:
            if stem.endswith(a):add_stem(stem[:-len(a)]+b)
        numeric=re.search(r'(\d+)$',stem)
        weapon_spans=list(target.finditer(stem))
        if numeric and not any(numeric.start()<m.end() and numeric.end()>m.start() for m in weapon_spans):
            for number in range(number_max+1):add(stem[:numeric.start()]+str(number).zfill(len(numeric.group()))+tail)
        for action in sorted(actions,key=len,reverse=True):
            pattern=token_pattern(action)
            if not pattern.search(stem):continue
            if any(m.start()<w.end() and m.end()>w.start() for m in pattern.finditer(stem) for w in weapon_spans):continue
            for replacement in actions:add_stem(pattern.sub(lambda _:replacement,stem))
            break
    plan=Plan([sorted(candidates)])
    plan.metadata={'weapon':keyword,'manual_seeds':len(seeds),'reference_names':len(references),
        'template_roots':sorted(source_roots),'inferred_donor_codes':len(inferred_codes),'corpus_names':len(corpus),'transferred_templates':len(learned),'number_max':number_max,
        'strip_export_extension':bool(options.get('strip_export_extension',False)),
        'options':options,'seed_names':seeds}
    return plan
