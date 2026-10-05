import itertools
import math
import re
from pathlib import Path

MAX_SPACE = (1 << 63) - 1

class Plan:
    def __init__(self, slots):
        self.slots = [list(dict.fromkeys(s)) for s in slots]
        if not self.slots or any(not s for s in self.slots) or len(slots) > 32:
            raise ValueError('规则需要 1–32 个非空插槽')
        if any(any(c in v for c in '\x00\r\n') for s in self.slots for v in s):
            raise ValueError('插槽包含 NUL 或换行')
        if sum(max(len(v.encode('utf-8')) for v in s) for s in self.slots) > 1024:
            raise ValueError('候选名称最多 1024 字节')
        self.total = math.prod(len(s) for s in self.slots)
        if self.total > MAX_SPACE:
            raise ValueError('候选空间超出 63 位范围，请缩小规则')

    def at(self, index):
        if not 0 <= index < self.total:
            raise IndexError(index)
        parts = []
        for slot in reversed(self.slots):
            index, digit = divmod(index, len(slot))
            parts.append(slot[digit])
        return ''.join(reversed(parts))

    @classmethod
    def template(cls, text, vocabulary):
        parts = re.split(r'(\{[A-Za-z_][A-Za-z_0-9]*\})',text)
        slots = []
        for p in parts:
            if not p:
                continue
            if p.startswith('{') and p.endswith('}'):
                name = p[1:-1]
                if name not in vocabulary:
                    raise ValueError('缺少插槽：'+name)
                values = vocabulary[name]
                if not isinstance(values,list) or not all(isinstance(v,str) for v in values):
                    raise ValueError('插槽值必须是字符串数组')
                slots.append(values)
            else:
                slots.append([p])
        return cls(slots)

def family_plan(names, keyword, replacements):
    if not keyword:
        raise ValueError('家族扩展需要关键词')
    candidates = set()
    for name in names:
        if keyword.lower() in name.lower():
            for replacement in replacements:
                candidates.add(re.sub(re.escape(keyword),lambda _: replacement,name,flags=re.I))
    if not candidates:
        raise ValueError('词典没有该关键词家族，请使用模板或音频路径恢复')
    return Plan([sorted(candidates)])

def automatic_plan(names,keyword,number_max=32,max_candidates=250000):
    """Learn literal name families, bounded numeric and view variations from known names."""
    if not keyword:raise ValueError('自动发现需要关键词')
    candidates=set()
    for name in names:
        if keyword.lower() not in name.lower():continue
        candidates.add(name)
        # Keep internal audio suffixes; vary only the final numeric stem component.
        stem,dot,extension=name.partition('.')
        match=re.search(r'(\d+)$',stem)
        if match:
            width=len(match.group())
            prefix=stem[:match.start()]
            for i in range(number_max+1):
                candidates.add(prefix+str(i).zfill(width)+(dot+extension if dot else ''))
        for a,b in [('_vm_','_wm_'),('_wm_','_vm_'),('_plr_','_npc_'),('_npc_','_plr_')]:
            if a in name:candidates.add(name.replace(a,b))
        if len(candidates)>max_candidates:
            raise ValueError('自动家族候选超过 250,000，请缩小关键词或用显式模板')
    if not candidates:raise ValueError('词典中没有该关键词，请先复用名称数据库或填写显式模板')
    return Plan([sorted(candidates)])

def audio_plan(filename, prefixes, suffixes, max_boundaries=10):
    filename = Path(filename.replace('\\','/')).name
    stem = filename.rsplit('.',1)[0] if '.' in filename else filename
    if not stem:
        raise ValueError('音频导出名为空')
    candidates = set()
    if prefixes:
        for prefix in prefixes:
            prefix = prefix.replace('\\','/').strip('/')
            flat = prefix.replace('/','_') + '_'
            if stem.lower().startswith(flat.lower()):
                candidates.add(prefix + '/' + stem[len(flat):])
            else:
                candidates.add(prefix + '/' + stem)
    # Conservative literal candidate remains useful when underscores were original.
    candidates.add(stem)
    n = stem.count('_')
    if n <= max_boundaries:
        pieces = stem.split('_')
        for joins in itertools.product(('_','/'),repeat=n):
            candidates.add(pieces[0]+''.join(j+p for j,p in zip(joins,pieces[1:])))
    elif not prefixes:
        raise ValueError('不确定目录边界过多，请提供已知目录前缀')
    return Plan([sorted(candidates), suffixes or ['']])
