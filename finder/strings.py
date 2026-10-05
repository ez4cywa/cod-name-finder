from pathlib import Path
from .candidates import Plan

def string_plan(path,keyword='',limit=250000):
    values=set()
    with Path(path).open(encoding='utf-8-sig',errors='strict') as f:
        for line in f:
            line=line.rstrip('\r\n')
            # Existing research TSV: take the final field, preserving name underscores.
            value=line.split('\t')[-1]
            if not value or '\x00' in value or len(value.encode('utf-8'))>1024:continue
            if keyword and keyword.lower() not in value.lower():continue
            values.add(value)
            if len(values)>limit:raise ValueError('字符串候选超过上限，请缩小关键词')
    if not values:raise ValueError('字符串文件没有符合条件的候选')
    return Plan([sorted(values)])
