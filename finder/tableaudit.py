"""Stream table archaeology: exact profile matches, masks and name-family groups."""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
from .community import iter_csv_rows
from .hashing import PROFILES
from .registry import REGISTRY_SHA256, table_rule


def name_group(name):
    if '/' in name or '\\' in name:
        return 'path:' + name.replace('\\', '/').split('/', 1)[0].lower()
    if name.startswith('rex_'):
        return 'rex_prefix'
    if 'rex_' in name:
        return 'rex_embedded'
    if 'rex' in name:
        return 'rex_substring'
    return 'other'


def audit_tables(csv_dir, profiles=None, name_filter=None, sample_limit=None):
    """Return JSON-ready table/profile/group rates; no row is inferred from its table.

    With profiles=None every registered candidate is tried (including 60/full64
    and no-fold exceptions); sample_limit is explicit and reported as incomplete.
    Path groups expose reconstructed display names which fail exact re-hashing.
    """
    ids = list(profiles if profiles is not None else PROFILES)
    if not ids or any(pid not in PROFILES for pid in ids):
        raise ValueError('请选择至少一个已注册的表考古规则')
    if sample_limit is not None and sample_limit <= 0:
        raise ValueError('sample_limit 必须大于 0')
    folder = Path(csv_dir)
    if not folder.is_dir():
        raise ValueError('表考古 CSV 目录不存在')
    tables = []
    for path in sorted(folder.glob('*.csv')):
        counts = defaultdict(int)
        groups = {}
        total, invalid, scanned, truncated = 0, 0, 0, False
        for _, key, name, error in iter_csv_rows(path):
            scanned += 1
            if name_filter and name_filter not in name:
                continue
            if sample_limit is not None and total >= sample_limit:
                truncated = True
                break
            if error:
                invalid += 1
                continue
            total += 1
            group = groups.setdefault(name_group(name), {'rows': 0, 'matches': defaultdict(int)})
            group['rows'] += 1
            for pid in ids:
                if PROFILES[pid].digest(name) == key:
                    counts[pid] += 1
                    group['matches'][pid] += 1
        def rates(matches, rows):
            return {pid: {'matches': matches[pid], 'rows': rows,
                          'rate': matches[pid] / rows if rows else 0.0,
                          'mask': f'{PROFILES[pid].mask:016x}', 'width': PROFILES[pid].mask.bit_length()}
                    for pid in ids}
        for group in groups.values():
            group['profiles'] = rates(group.pop('matches'), group['rows'])
        tables.append({'table': path.stem, 'rows': total, 'invalid_rows': invalid, 'scanned_rows': scanned,
                       'truncated': truncated, 'expected': table_rule(path), 'profiles': rates(counts, total),
                       'groups': groups})
    return {'registry_sha256': REGISTRY_SHA256, 'source': str(folder.resolve()), 'name_filter': name_filter,
            'sample_limit': sample_limit, 'profiles': ids, 'tables': tables,
            'complete': not any(t['truncated'] for t in tables),
            'note': 'Exact stored-key rehash only; reconstructed display names remain candidates, not verified names.'}
