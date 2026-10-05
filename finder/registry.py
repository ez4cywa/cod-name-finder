"""Packaged, generated game/domain and table metadata; never reads research paths."""
from fnmatch import fnmatchcase
from pathlib import Path
from .generated_registry import ALGORITHMS, DOMAINS, GAME_DOMAINS, PROFILES as PROFILE_DATA, TABLES, REGISTRY_SHA256

PROFILE_CONFIG_KEYS = ('id', 'seed', 'mask', 'ascii_lower', 'slash', 'prime', 'algorithm', 'secret')
ALGORITHM_IDS = {name: entry['native_id'] for name, entry in ALGORITHMS.items()}


def validate_domain(game, profile_id, kind='', domain=None, allow_unverified=False):
    """Require an evidence domain when a game is selected; manual calibrated mode is retained.

    ``domain`` is the name-domain id (asset, alias, scriptfield, dvar...), distinct
    from an exported file type. Script *files* remain assets, not script symbols.
    The explicit override only permits selection: engine sample calibration still
    controls execution and is never bypassed by this metadata function.
    """
    if not game or game in ('手动 / 已校准', 'manual'):
        return {'game': game or 'manual', 'profile': profile_id, 'status': 'candidate', 'domain': domain or kind}
    if game not in DOMAINS:
        raise ValueError('未知作品：' + str(game))
    selected = domain or kind
    # Legacy configurations carried an explicit profile but no name-domain id.
    # Preserve their independent sample calibration, except clearly unproven
    # COD2026 symbol hashes which must remain opt-in.
    if not selected:
        unknown_profile = game == 'COD2026' and profile_id in (
            'mwii-mwiii-script64', 'mwii-mwiii-script63', 'bo6-script64',
            'bo6-sp-script64', 'bo6-omnvar64', 'iw-dvar64')
        if unknown_profile and not allow_unverified:
            raise ValueError('COD2026 脚本 / Dvar / Omnvar 规则尚未证实；请提供真实样本后显式启用未证实域')
        match = next((d for d in DOMAINS[game] if d['profile'] == profile_id and d['status'] == 'evidence'), None)
        return {'game': game, **match} if match else {'game': game, 'profile': profile_id,
                'status': 'unknown' if unknown_profile else 'candidate', 'requires_calibration': True}
    if selected == 'assets':
        selected = 'asset'
    rows = [d for d in DOMAINS[game] if selected == 'auto' or selected == d['id'] or selected == d['label'] or selected in d['kinds']]
    matched = next((d for d in rows if d['status'] == 'evidence' and d['profile'] == profile_id), None)
    if matched:
        return {'game': game, **matched}
    if allow_unverified:
        return {'game': game, 'profile': profile_id, 'status': 'unknown', 'domain': domain or kind,
                'requires_calibration': True, 'source': 'Explicit user override; no inferred game algorithm'}
    if any(d['status'] == 'unknown' for d in rows):
        raise ValueError(f'{game} 的 {selected} 名称域尚未证实，须提供该域的真实名称/哈希样本后显式启用')
    raise ValueError(f'{game} 的 {selected} 名称域与规则 {profile_id} 不匹配；请检查名称域或选择手动校准')


def table_rule(path):
    stem = Path(path).stem.lower()
    # Exact exception tables win over broad language patterns.
    return next((t for t in TABLES if t['pattern'] == stem),
                next((t for t in TABLES if fnmatchcase(stem, t['pattern'])), None))
