"""Bounded naming hypotheses learned from verified, typed target conventions.

Callers must verify source-table spellings before supplying either corpus and
must additionally establish that each target template is held in the selected
game's matching asset pool. This module receives names, not proof, and never
authenticates a hash or broadens a hash domain. Every emitted candidate still
requires an independent complete-key match in the normal search engine.

The implementation learns two small relationships: animation cores inside
sound aliases, and whole weapon identities inside image/material templates.
It preserves literal namespaces and correlates repeated weapon identities.
"""
from bisect import bisect_right
from collections import defaultdict, deque
from collections.abc import Mapping
import re

from .candidates import Plan


MAX_CANDIDATES = 1_000_000
MAX_PLANS = 64
MAX_NAME_BYTES = 1024
SOURCE_KINDS = frozenset(('xanim', 'image', 'material', 'soundbankalias'))
TARGET_KINDS = frozenset(('image', 'material', 'soundbankalias'))
_CLASSES = ('ar', 'br', 'dm', 'la', 'lm', 'lmg', 'me', 'pi', 'sh', 'sm', 'smg', 'sn')
_WEAPON = re.compile(r'(?<![a-z0-9])(' + '|'.join(sorted(_CLASSES, key=lambda s: (-len(s), s))) +
                     r')_([a-z][a-z0-9]*)(?![a-z0-9])', re.I)
_ASCII_LOWER = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')
_SEPARATORS = '_/\\'


class _Cancelled(Exception):
    pass


def _names(values, check):
    if isinstance(values, (str, bytes)):
        raise ValueError('已核验名称须按资产类型提供名称列表')
    try:
        iterator = iter(values)
    except TypeError as error:
        raise ValueError('已核验名称须为名称列表') from error
    result = set()
    for name in iterator:
        check()
        if not isinstance(name, str) or not name.strip() or any(c in name for c in '\x00\r\n'):
            raise ValueError('已核验名称包含空名称、NUL或换行')
        try:
            size = len(name.encode('utf-8'))
        except UnicodeEncodeError as error:
            raise ValueError('已核验名称无法编码为UTF-8') from error
        if size > MAX_NAME_BYTES:
            raise ValueError('已核验名称最多1024字节')
        result.add(name)
    return tuple(sorted(result))


def _animation_core(name):
    words = name.split('_')
    if words[0].lower() in ('vm', 'wm'):
        start = 1
    elif (len(words) > 2 and words[0].isascii() and words[0].isalnum()
          and words[1].lower() in ('vm', 'wm')):
        start = 2
    else:
        return None
    core = '_'.join(words[start:])
    return core if len(core) >= 4 else None


def _take_splits(name):
    """The literal ending, followed by at most two observed numeric takes."""
    yield name, ''
    stem = name
    for _ in range(2):
        front, separator, take = stem.rpartition('_')
        if not separator or not 1 <= len(take) <= 3 or not take.isascii() or not take.isdigit():
            break
        stem = front
        yield stem, name[len(stem):]


def _alias_frames(source, target, check):
    cores = tuple(sorted({core for name in source if (core := _animation_core(name)) is not None}))
    if not cores:
        return []
    comparison = {core.translate(_ASCII_LOWER) for core in cores}
    lengths = sorted(len(core.encode('utf-8')) for core in cores)
    prefixes, tails = set(), set()
    represented = 0
    for name in target:
        check()
        matched = False
        for stem, tail in _take_splits(name):
            positions = [0]
            for index, character in enumerate(stem):
                if character == '_':
                    positions.append(index + 1)
                    if len(positions) == 6:
                        break
            for start in positions:
                if stem[start:].translate(_ASCII_LOWER) in comparison:
                    prefixes.add(stem[:start])
                    tails.add(tail)
                    matched = True
        represented += matched
    if not prefixes or not tails:
        return []
    # Equal-size endings share one safe Cartesian slot. Longer names do not
    # disqualify a valid short spelling just because another ending is longer.
    ending_groups = defaultdict(list)
    for tail in sorted(tails):
        ending_groups[len(tail.encode('utf-8'))].append(tail)
    result = []
    for prefix in sorted(prefixes):
        check()
        for tail_bytes, endings in sorted(ending_groups.items()):
            allowance = MAX_NAME_BYTES - len(prefix.encode('utf-8')) - tail_bytes
            count = bisect_right(lengths, allowance)
            if count:
                result.append({'kind': 'soundbankalias', 'rule': 'animation-core-alias',
                    'category': '', 'prefix': prefix, 'suffix': '', 'middles': (),
                    'values': cores, 'value_max_bytes': allowance, 'value_count': count,
                    'endings': tuple(endings), 'capacity': count * len(endings),
                    'observed_templates': represented, 'source_identities': len(cores),
                    'observed_prefixes': len(prefixes), 'observed_endings': len(tails)})
    return result


def _weapon_frames(source, targets, kinds, check):
    donors = defaultdict(set)
    for name in source:
        check()
        for match in _WEAPON.finditer(name):
            donors[match[1].lower()].add(match[0])
    donors = {category: tuple(sorted(values)) for category, values in donors.items()}
    known = {category: {value.translate(_ASCII_LOWER) for value in values}
             for category, values in donors.items()}
    lengths = {category: sorted(len(value.encode('utf-8')) for value in values)
               for category, values in donors.items()}
    frames = defaultdict(set)
    for kind in sorted(set(kinds).intersection(('image', 'material'))):
        for name in targets.get(kind, ()):
            check()
            occurrences = list(_WEAPON.finditer(name))
            identities = {match[0].translate(_ASCII_LOWER): match[1].lower() for match in occurrences}
            for identity, category in sorted(identities.items()):
                if category not in donors or identity not in known[category]:
                    continue
                same = [match for match in occurrences if match[0].translate(_ASCII_LOWER) == identity]
                # A whole identity occupies a separator-delimited slot. The
                # namespace and all decorations outside that slot stay literal.
                if any((match.start() and name[match.start()-1] not in _SEPARATORS)
                       or (match.end() < len(name) and name[match.end()] not in _SEPARATORS)
                       for match in same):
                    continue
                prefix, suffix = name[:same[0].start()], name[same[-1].end():]
                middles = tuple(name[left.end():right.start()] for left, right in zip(same, same[1:]))
                frames[kind, category, prefix, middles, suffix].add(name)
    result = []
    for (kind, category, prefix, middles, suffix), observed in sorted(frames.items()):
        check()
        fixed_bytes = sum(len(part.encode('utf-8')) for part in (prefix, *middles, suffix))
        allowance = (MAX_NAME_BYTES - fixed_bytes) // (len(middles) + 1)
        count = bisect_right(lengths[category], allowance)
        if count:
            result.append({'kind': kind, 'rule': 'typed-weapon-slot', 'category': category,
                'prefix': prefix, 'suffix': suffix, 'middles': middles,
                'values': donors[category], 'value_max_bytes': allowance, 'value_count': count,
                'endings': (suffix,), 'capacity': count,
                'observed_templates': len(observed), 'source_identities': len(donors[category])})
    return result


def _interleave(frames):
    queues = defaultdict(deque)
    for frame in frames:
        queues[frame['kind']].append(frame)
    result = []
    while any(queues.values()):
        for kind in sorted(queues):
            if queues[kind]:
                result.append(queues[kind].popleft())
    return result


def _quotas(frames, limit):
    """Share a bounded budget across selected conventions before expansion."""
    amounts = [0] * len(frames)
    remaining = limit
    active = list(range(len(frames)))
    while remaining and active:
        share = max(1, remaining // len(active))
        for index in active:
            take = min(share, frames[index]['capacity'] - amounts[index], remaining)
            amounts[index] += take
            remaining -= take
            if not remaining:
                break
        active = [index for index in active if amounts[index] < frames[index]['capacity']]
    return amounts


def build_typed_plans(source_names_by_kind, target_names_by_kind, target_kinds, *,
                      max_candidates=MAX_CANDIDATES, max_plans=MAX_PLANS, control=lambda: 'run'):
    """Build finite, candidate-only plans from verified typed input names.

    Source and target corpora use canonical finder kinds. Unknown kinds do not
    unlock additional rules. Target templates must already be source-verified
    AND held in their matching target pool; the caller owns those checks.
    No observed relation produces no plan. Cancellation returns no partial set.
    Limits apply across both rules and all requested types, including repeats
    across different templates. Omission counts are upper bounds, not distinct
    name counts or claims of exhaustive reversal.
    """
    if not isinstance(source_names_by_kind, Mapping) or not isinstance(target_names_by_kind, Mapping):
        raise ValueError('已核验名称须按资产类型分组')
    if isinstance(target_kinds, (str, bytes)):
        raise ValueError('目标类型须为类型列表')
    try:
        requested = tuple(sorted(set(target_kinds)))
    except (TypeError, ValueError) as error:
        raise ValueError('目标类型须为类型列表') from error
    if any(not isinstance(kind, str) for kind in requested):
        raise ValueError('目标类型须为字符串')
    for value, maximum, label in ((max_candidates, MAX_CANDIDATES, '候选'), (max_plans, MAX_PLANS, '规则')):
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f'{label}上限须为1–{maximum}的整数')

    def check():
        if control() != 'run':
            raise _Cancelled()

    try:
        check()
        kinds = set(requested).intersection(TARGET_KINDS)
        if not kinds:
            return []
        sources = {kind: _names(source_names_by_kind.get(kind, ()), check) for kind in sorted(SOURCE_KINDS)}
        targets = {kind: _names(target_names_by_kind.get(kind, ()), check) for kind in sorted(kinds)}
        frames = []
        if 'soundbankalias' in kinds:
            frames.extend(_alias_frames(sources['xanim'], targets['soundbankalias'], check))
        weapon_sources = sorted({name for names in sources.values() for name in names})
        frames.extend(_weapon_frames(weapon_sources, targets, kinds, check))
        frames.sort(key=lambda frame: (frame['kind'], frame['rule'], frame['category'],
                                      frame['prefix'], frame['middles'], frame['endings']))
        upper_bound = sum(frame['capacity'] for frame in frames)
        selected = _interleave(frames)[:max_plans]
        quotas = _quotas(selected, max_candidates)
        plans = []
        for frame, quota in zip(selected, quotas):
            check()
            if not quota:
                continue
            body = []
            # A repeated identity is one correlated string slot, never several
            # independent choices in a Cartesian product.
            for value in frame['values']:
                check()
                if len(value.encode('utf-8')) > frame['value_max_bytes']:
                    continue
                body.append(value + ''.join(middle + value for middle in frame['middles']))
                if len(body) == min(frame['value_count'], quota):
                    break
            endings = frame['endings'][:max(1, quota // len(body))]
            plan = Plan([[frame['prefix']], body, list(endings)])
            plan.metadata = {'generator': 'typed-observed-v1', 'rule': frame['rule'],
                'target_kinds': [frame['kind']], 'category': frame['category'],
                'candidate_only': True, 'hypothesis': True, 'verification_required': 'complete-target-hash',
                'input_requirement': 'source-table-rehash-and-matching-target-pool',
                'source_identities': frame['source_identities'], 'observed_templates': frame['observed_templates'],
                'correlated_occurrences': len(frame['middles']) + 1,
                'unbounded_plan_combinations': frame['capacity'], 'plan_limited': plan.total < frame['capacity'],
                'candidate_limit': max_candidates, 'plan_limit': max_plans}
            if frame['rule'] == 'animation-core-alias':
                plan.metadata.update(observed_prefixes=frame['observed_prefixes'], observed_endings=frame['observed_endings'])
            label = ('观测动画核心推测声音别名' if frame['rule'] == 'animation-core-alias'
                     else '同类武器名称替换' + '（' + frame['kind'] + ' · ' + frame['category'] + '）')
            plans.append((label, plan))
        emitted = sum(plan.total for _, plan in plans)
        for _, plan in plans:
            plan.metadata.update(bounded_search=True,
                unbounded_combinations_upper_bound=upper_bound, emitted_combinations=emitted,
                omitted_combinations_upper_bound=max(0, upper_bound - emitted),
                observed_plan_count=len(frames), omitted_plan_count=max(0, len(frames) - len(plans)))
        check()
        return plans
    except _Cancelled:
        return []
