"""Bounded name-family plans learned entirely from the supplied local corpus.

The caller supplies decoded dictionary names, not research-project paths. Each
returned Plan keeps independent variations in mixed-radix slots, so task budgets
and checkpoints can consume a small prefix of a large search space. Keyword
matching selects source names; it does not constrain variants after generation.
"""
import re
from collections import defaultdict

from .candidates import Plan


# These are observed naming roots, not claims about a title's hash algorithm.
SOURCE_ROOTS = frozenset(('jup', 'iw9', 'sat', 't10', 't9', 't8', 'rex'))
TARGET_ROOTS = ('rex', 'mw4', 'iw10', 'iw11')
ANIMATION_TYPES = frozenset(('xanim', 'anim', 'animation', 'animations', 'all', 'auto'))
MAX_NAME_BYTES = 1024
_NUMBER = re.compile(r'_([0-9]{1,3})(?:_ads)?$', re.I)
_WEAPON_VIEW = re.compile(r'(?:^|_)(vm|wm)_(?:ar|sm|lm|dm|br|sn|sh|pi|la|me)_', re.I)


def build_plans(names, asset_type='xanim', keyword='', number_max=32):
    """Return deterministic ``[(Chinese label, Plan), ...]`` for local names.

    All names must be nonblank UTF-8 strings of at most 1024 bytes and contain
    no NUL or line break. Their actual characters, separators, capitalization,
    and internal extensions remain intact. Empty or unmatched corpora fail
    explicitly rather than silently starting an empty search.

    ``number_max`` is an inclusive 0..999 limit. Only a final, isolated ASCII
    integer component is varied, optionally before ``_ads`` and the original
    internal extension. Weapon codes such as ``mike4`` remain unchanged.

    Duplicate candidates can occur between separate rules. This avoids a
    potentially million-string global set; verification deduplicates matches.
    No rule creates the unsuccessful vm_pNN numeric family from the audit.
    """
    if (not isinstance(asset_type, str) or any(c in asset_type for c in '\x00\r\n')
            or not re.fullmatch(r'[a-z][a-z0-9_]*', asset_type.strip().lower())):
        raise ValueError('资产类型须为有效名称，例如 xanim 或 sndasset')
    kind = asset_type.strip().lower()
    if not isinstance(keyword, str) or any(c in keyword for c in '\x00\r\n'):
        raise ValueError('关键词须为不含 NUL 或换行的字符串')
    query = keyword.strip()
    if isinstance(number_max, bool) or not isinstance(number_max, int) or not 0 <= number_max <= 999:
        raise ValueError('number_max 应为 0–999 的整数')
    if isinstance(names, (str, bytes)):
        raise ValueError('名称词典须为字符串列表，不能直接传入文件路径或文本')
    try:
        iterator = iter(names)
    except TypeError as error:
        raise ValueError('请提供本地名称词典') from error
    unique = set()
    for name in iterator:
        if not isinstance(name, str) or not name.strip() or any(c in name for c in '\x00\r\n'):
            raise ValueError('名称词典包含空名称、非字符串、NUL 或换行')
        try:
            length = len(name.encode('utf-8'))
        except UnicodeEncodeError as error:
            raise ValueError('名称词典包含无法编码为 UTF-8 的字符') from error
        if length > MAX_NAME_BYTES:
            raise ValueError('名称词典中的名称不得超过 1024 字节')
        unique.add(name)
    if not unique:
        raise ValueError('没有本地名称词典，请先选择 Saluki 索引或导入 TXT/CSV 名称')
    corpus = sorted(n for n in unique if not query or query.casefold() in n.casefold())
    if not corpus:
        raise ValueError('名称词典中没有匹配关键词的名称，请缩短或清空关键词')
    plans = []

    def append(label, slots, rule, **details):
        plan = Plan(slots)
        plan.metadata = {
            'generator': 'local-observed-v1', 'asset_type': kind,
            'keyword': query, 'source_names': len(corpus),
            'rule': rule, 'number_max': number_max, **details,
        }
        plans.append((label, plan))

    append('本地词典原始名称', [corpus], 'literal')

    # Four root values times distinct observed suffixes, stored separately.
    roots = [root + '_' for root in TARGET_ROOTS]

    def rooted(label, bases, rule):
        compatible = defaultdict(list)
        for base in bases:
            length = len(base.encode('utf-8'))
            allowed = tuple(root for root in roots if len(root) + length <= MAX_NAME_BYTES)
            if allowed:
                compatible[allowed].append(base)
        # Normally a single group contains all four prefixes; a rare long name
        # may still accept the shorter prefixes without discarding that search.
        for allowed, bases in sorted(compatible.items(), key=lambda item: (-len(item[0]), item[0])):
            suffix = '' if len(allowed) == len(roots) else '（%d 个可用前缀）' % len(allowed)
            append(label + suffix, [list(allowed), sorted(bases)], rule,
                   roots=[root[:-1] for root in allowed])

    suffixes = set()
    for name in corpus:
        source, separator, suffix = name.partition('_')
        if separator and source.lower() in SOURCE_ROOTS and suffix:
            suffixes.add(suffix)
    if suffixes:
        rooted('已有作品名称前缀迁移', suffixes, 'title-root')

    if kind in ANIMATION_TYPES:
        generic = [n for n in corpus if n.lower().startswith(('vm_', 'wm_'))]
        if generic:
            rooted('通用动画添加作品前缀', generic, 'generic-animation-root')

    # Split on the first period only: e.g. .qnn.85.48000.all is one opaque tail.
    # Grouping lets each Plan combine original prefixes and bounded numbers
    # without constructing every complete candidate string in Python.
    groups = defaultdict(set)
    for name in corpus:
        stem, dot, extension = name.partition('.')
        match = _NUMBER.search(stem)
        if match:
            width = len(match.group(1))
            tail = stem[match.end(1):] + dot + extension
            groups[width, tail].add(stem[:match.start(1)])
    for (width, tail), prefixes in sorted(groups.items()):
        number_groups = defaultdict(list)
        for number in range(number_max + 1):
            value = str(number).zfill(width)
            number_groups[len(value)].append(value)
        for digits, numbers in sorted(number_groups.items()):
            remaining = MAX_NAME_BYTES - digits - len(tail.encode('utf-8'))
            safe_prefixes = sorted(n for n in prefixes if len(n.encode('utf-8')) <= remaining)
            if safe_prefixes:
                append('末尾数字扩展（原宽度 %d、数字 %d 位%s）' % (width, digits, '、保留后缀' if tail else ''),
                       [safe_prefixes, numbers, [tail]], 'final-number', width=width, digits=digits, tail=tail)

    if kind in ANIMATION_TYPES:
        variants = set()
        for name in corpus:
            match = _WEAPON_VIEW.search(name)
            if match:
                replacement = 'wm' if match.group(1).lower() == 'vm' else 'vm'
                variants.add(name[:match.start(1)] + replacement + name[match.end(1):])
        if variants:
            append('武器动画 VM/WM 视角转换', [sorted(variants)], 'weapon-view')
    return plans
