"""Bounded single-byte sound-name recovery using independent FNV arithmetic.

Source spellings must already have passed their source-table hash check. Only
names held in the target sound pool may supply encoding endings. This module
returns candidate Plans, never evidence; the ordinary engine checks each full
target key again before export. Low-60 searches and non-FNV domains skip it.
"""
from collections import Counter, defaultdict
import re

from .candidates import Plan


_ENDING = re.compile(
    r'(?:\.[a-z]{1,4}[0-9]*\.[0-9]+\.[0-9]+\.[a-z_]+|'
    r'\.[a-z]{1,3}[0-9]+\.pc\.[a-z_]+\.snd)$', re.I | re.ASCII)
_CHARACTERS = frozenset(range(32, 127)) - {ord('/'), ord('\\')}


def _names(values):
    if isinstance(values, (str, bytes)):
        raise ValueError('声音名称须为字符串列表')
    result = set()
    for name in values:
        if not isinstance(name, str) or not name or any(c in name for c in '\x00\r\n'):
            raise ValueError('声音名称无效')
        try:
            size = len(name.encode('utf-8'))
        except UnicodeEncodeError as error:
            raise ValueError('声音名称无法编码为 UTF-8') from error
        if size > 1024:
            raise ValueError('声音名称不得超过 1024 字节')
        result.add(name)
    return sorted(result)


def build_final_byte_plans(source_names, target_sound_names, target_keys, profile, *,
                           max_byte_operations=8_000_000, max_prefixes=80_000,
                           max_candidates=10_000, control=lambda: 'run'):
    """Recover an ASCII basename byte before target-observed encoding endings.

    Low 63 bits form a closed modular ring; inverting there is equivalent to
    checking both possible full-width lifts. Prefixes are indexed by all but
    their low byte. After stripping an ending and one FNV multiplication from
    a target, only the matching bucket can yield a byte in 0..255. Thus no
    alphabet-times-prefix-times-target Cartesian product is materialized.

    Preparation has a separate byte-operation bound, exposed in metadata and
    the returned report. Half is reserved for inverse queries. Source/target
    order is deterministic, and stopping returns no partial candidate plan.
    """
    for value in (max_byte_operations, max_prefixes, max_candidates):
        if type(value) is not int or value < 1:
            raise ValueError('声音末字节搜索上限须为正整数')
    report = {'enabled': False, 'bounded_search': True, 'cancelled': False,
              'preparation_byte_operations': 0, 'operation_limit': max_byte_operations,
              'bucket_probes': 0, 'preparation_work_units': 0,
              'source_prefixes': 0, 'indexed_prefixes': 0, 'omitted_prefixes': 0,
              'target_tail_pairs': 0, 'processed_target_tail_pairs': 0,
              'omitted_target_tail_pairs': 0, 'candidates': 0}
    if (profile.algorithm != 'fnv' or profile.mask not in ((1 << 63) - 1, (1 << 64) - 1)
            or profile.prime % 2 != 1):
        report['reason'] = 'requires full sound FNV63/FNV64 domain'
        return [], report
    report['enabled'] = True
    if control() != 'run':
        return [], dict(report, cancelled=True)
    sources = _names(source_names)
    targets = sorted(set(target_keys))
    if any(type(key) is not int or not 0 <= key <= profile.mask for key in targets):
        raise ValueError('声音末字节搜索目标须为完整域内整数键')
    endings = Counter()
    for index, name in enumerate(_names(target_sound_names)):
        if index % 1024 == 0 and control() != 'run':
            return [], dict(report, cancelled=True)
        match = _ENDING.search(name)
        if match:
            endings[match.group()] += 1
    prefixes = set()
    for index, name in enumerate(sources):
        if index % 1024 == 0 and control() != 'run':
            return [], dict(report, cancelled=True)
        match = _ENDING.search(name)
        if match and match.start() and ord(name[match.start() - 1]) in _CHARACTERS:
            prefix = name[:match.start() - 1]
            # A directory without a basename is not an observed sound stem.
            if prefix and not prefix.endswith(('/', '\\')):
                prefixes.add(prefix)
    report['source_prefixes'] = len(prefixes)
    normalized = {}
    for index,prefix in enumerate(sorted(prefixes)):
        if index % 1024 == 0 and control() != 'run':
            return [], dict(report, cancelled=True)
        normalized.setdefault(profile.normalize(prefix),prefix)
    report['normalized_source_prefixes'] = len(normalized)
    report['deduplicated_prefix_spellings'] = len(prefixes) - len(normalized)
    buckets = defaultdict(list)
    operations = 0;probes = 0
    for index, (canonical,prefix) in enumerate(sorted(normalized.items(), key=lambda pair: (len(pair[0]), pair))):
        if index % 1024 == 0 and control() != 'run':
            return [], dict(report, cancelled=True)
        data = canonical.encode('utf-8')
        if len(data) + operations > max_byte_operations // 2 or index >= max_prefixes:
            break
        state = profile.seed & profile.mask
        for byte in data:
            state = ((state ^ byte) * profile.prime) & profile.mask
        operations += len(data)
        buckets[state >> 8].append((prefix, state))
        report['indexed_prefixes'] += 1
    report['omitted_prefixes'] = len(normalized) - report['indexed_prefixes']
    report['target_tail_pairs'] = len(targets) * len(endings)
    inverse = pow(profile.prime, -1, profile.mask + 1)
    candidates = set()
    exhausted = False
    for ending in sorted(endings, key=lambda value: (-endings[value], value)):
        suffix = profile.normalize(ending).encode('utf-8')
        for index, target in enumerate(targets):
            if index % 1024 == 0 and control() != 'run':
                return [], dict(report, cancelled=True)
            if operations + probes + len(suffix) + 1 > max_byte_operations:
                exhausted = True
                break
            state = target
            for byte in reversed(suffix):
                state = ((state * inverse) & profile.mask) ^ byte
            previous = (state * inverse) & profile.mask
            operations += len(suffix) + 1
            report['processed_target_tail_pairs'] += 1
            for prefix, forward in buckets.get(previous >> 8, ()):
                if probes % 256 == 0 and control() != 'run':
                    return [], dict(report, cancelled=True)
                if operations + probes + 1 > max_byte_operations:
                    exhausted = True
                    break
                probes += 1
                byte = forward ^ previous
                if byte not in _CHARACTERS:
                    continue
                name = prefix + chr(byte) + ending
                size = len(name.encode('utf-8'))
                if size > 1024:
                    continue
                if operations + probes + size > max_byte_operations:
                    exhausted = True
                    break
                operations += size
                if profile.digest(name) == target:
                    candidates.add(name)
                    if len(candidates) >= max_candidates:
                        exhausted = True
                        break
            if exhausted:
                break
        if exhausted:
            break
    report.update(preparation_byte_operations=operations, candidates=len(candidates),
                  bucket_probes=probes, preparation_work_units=operations+probes,
                  omitted_target_tail_pairs=report['target_tail_pairs'] - report['processed_target_tail_pairs'],
                  limit_reached=exhausted or bool(report['omitted_prefixes']))
    if control() != 'run':
        return [], dict(report, cancelled=True)
    if not candidates:
        return [], report
    plan = Plan([sorted(candidates)])
    plan.metadata = {'generator': 'sound-final-byte-v1', 'rule': 'final-basename-byte',
                     'target_kinds': ['sndasset'], 'candidate_only': True,
                     'verification_required': 'complete-target-hash', **report}
    return [('声音编码尾前的末字节反解', plan)], report
