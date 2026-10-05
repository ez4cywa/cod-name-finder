"""Bounded animation/audio guesses learned from readable names of other assets.

This module generates hypotheses, never hash/name evidence. The normal search
engine must hash every candidate and independently verify complete target keys.
Weapon classes and identifiers are kept together; no hash-looking filename or
texture suffix is treated as a name clue. Observed audio separators and internal
extensions remain opaque text, including repeated identifiers in directories.
"""
import re
from collections import defaultdict
from collections.abc import Mapping

from .candidates import Plan


MAX_NAME_BYTES = 1024
MAX_CROSS_CANDIDATES = 8_000_000
MAX_CROSS_PLANS = 512
TARGET_KINDS = frozenset(('xanim', 'sndasset', 'soundbank', 'soundbanktransient'))
WEAPON_CLASSES = ('ar', 'sm', 'smg', 'lm', 'lmg', 'dm', 'br', 'sn', 'sh', 'pi', 'la', 'me')
ROOTS = frozenset(('jup', 'sat', 'rex', 'mw4', 'mw3', 'iw6', 'iw7', 'iw8', 'iw9',
                   'iw10', 'iw11', 't8', 't9', 't10', 't11'))
_ROOT = re.compile(r'(?:^|[_/\\])(' + '|'.join(sorted(ROOTS)) + r')(?=[_/\\])', re.I)
_CLASS_CODE = re.compile(r'(?:^|[_/\\])(' + '|'.join(WEAPON_CLASSES) +
                         r')_([a-z][a-z0-9]{1,31})(?=[_./\\&~]|$)', re.I)
_WORDS = re.compile(r'[a-z][a-z0-9]*', re.I)
_PHONETIC = re.compile(r'(?:alpha|bravo|charlie|delta|echo|foxtrot|golf|hotel|india|'
                       r'juliet|kilo|lima|mike|november|oscar|papa|quebec|romeo|'
                       r'sierra|tango|uniform|victor|whiskey|xray|yankee|zulu)', re.I)
_PLACEHOLDER = re.compile(r'^(?:(?:x?anim|animpkg|x?sound|sndasset|sndbank|soundbank|'
                          r'soundbanktransient|x?image|x?material|x?model|hash)_)?'
                          r'(?:0x)?[0-9a-f]{8,16}(?:\.[^.]+)*$', re.I)
_ACTIONS = ('idle', 'fire', 'fire_ads', 'reload', 'reload_empty', 'raise', 'drop',
            'inspect', 'ads_up', 'ads_down')
_OBJECT_ANIM = re.compile(r'(?:^|_)vm_([a-z][a-z0-9]*(?:_[a-z][a-z0-9]*){0,3}?)_'
                          r'(?:raise|drop|idle|fire|reload|inspect|use|open|close)(?=[_.]|$)', re.I)
_EQUIPMENT = re.compile(r'(?:^|[_/\\])eqp_(?:(?:' + '|'.join(sorted(ROOTS)) + r')_)?'
                        r'([a-z][a-z0-9]*(?:_[a-z][a-z0-9]*){0,3})(?=[./\\]|$)', re.I)
_NUMBER = re.compile(r'_([0-9]{1,3})(?:_ads)?$', re.I)
_ANIMATION_NAME = re.compile(r'(?:^|[_/\\])(?:vm|wm|mp|ai)_', re.I)
_BAD_CODES = frozenset(('generic', 'npc', 'plr', 'view', 'world', 'weapon', 'weapons',
                       'idle', 'reload', 'fire', 'atmo', 'interior', 'exterior', 'cls',
                       'default', 'attachment', 'attachments', 'scope', 'grip', 'barrel'))
_CURRENT_ROOTS = ('rex', 'mw4', 'iw10', 'iw11')


def _names(values, label):
    if isinstance(values, (str, bytes)):
        raise ValueError(label + '须为名称列表')
    try:
        iterator = iter(values)
    except TypeError as error:
        raise ValueError(label + '须为名称列表') from error
    result = set()
    for value in iterator:
        if not isinstance(value, str) or not value.strip() or any(c in value for c in '\x00\r\n'):
            raise ValueError(label + '包含无效名称')
        try:
            length = len(value.encode('utf-8'))
        except UnicodeEncodeError as error:
            raise ValueError(label + '包含无法编码为 UTF-8 的字符') from error
        if length > MAX_NAME_BYTES:
            raise ValueError(label + '中的名称不得超过 1024 字节')
        basename = re.split(r'[/\\]', value)[-1]
        if not _PLACEHOLDER.fullmatch(basename):
            result.add(value)
    return sorted(result)


def _plausible_code(code, name):
    if code.casefold() in _BAD_CODES or re.fullmatch(r'[0-9a-f]{8,}', code, re.I):
        return False
    # Explicit weapon stems allow a novel textual code; untyped material/image
    # names require a recognisable phonetic code or a code containing digits.
    return bool(_PHONETIC.search(code) or re.search(r'[0-9]', code) or
                re.search(r'(?:^|[_/\\])(?:wpn|weapon|weap|vm|wm)(?=[_/\\])', name, re.I))


def _equipment(name):
    match = _EQUIPMENT.search(name)
    if not match:
        return None
    parts = match.group(1).split('_')
    while parts and parts[-1].lower() in ('view', 'world', 'model', 'mat', 'material',
                                         'col', 'color', 'diffuse', 'normal', 'spec'):
        parts.pop()
    return '_'.join(parts) if parts else None


def _frame(name, code):
    """Separate every occurrence of one identity, preserving its correlation."""
    matches = list(re.finditer(r'(?<![a-z0-9])' + re.escape(code) + r'(?![a-z0-9])', name, re.I))
    if not matches:
        return None
    prefix = name[:matches[0].start()]
    middles = tuple(name[a.end():b.start()] for a, b in zip(matches, matches[1:]))
    suffix = name[matches[-1].end():]
    return prefix, middles, suffix


def build_cross_asset_plans(source_names, target_names_by_kind, target_kinds, number_max=32):
    """Return deterministic labelled Plans for observed cross-asset guesses.

    ``source_names`` can be readable models, materials, images, weapons, local
    filenames or dictionary names. ``target_names_by_kind`` maps canonical
    target kinds to existing animation/audio templates. Only the four kinds in
    TARGET_KINDS participate. Empty or unrelated readable sources return [].

    Actual templates supply actions, paths, view prefixes and codec extensions.
    A source's explicit title root can migrate the leading title of a template.
    When no animation template exists for a class, ten conventional actions are
    tried with VM/WM and only roots actually present in source names. These are
    labelled as finite hypotheses. Audio never invents a codec or sample rate.
    Final isolated numeric takes are varied inclusively through number_max;
    weapon code digits and digits in audio extensions remain untouched.

    Slots store identifiers and observed tails separately. A repeated identity
    in an audio path is one correlated value, not independent directory/file
    guesses. Metadata records counts rather than complete source corpora.
    The cross-asset search is capped at 8 million combinations and 512 plans.
    Current-title templates, same-title identities and clearly weapon-related
    source names precede older templates. Metadata exposes the upper bound of
    omitted combinations; exhausting these bounded plans is not exhaustive
    reversal of the name hash.
    """
    if isinstance(number_max, bool) or not isinstance(number_max, int) or not 0 <= number_max <= 999:
        raise ValueError('number_max 应为 0–999 的整数')
    if not isinstance(target_names_by_kind, Mapping):
        raise ValueError('目标模板须按资产类型分组')
    if isinstance(target_kinds, (str, bytes)):
        raise ValueError('目标类型须为列表')
    try:
        requested = sorted(set(target_kinds))
    except TypeError as error:
        raise ValueError('目标类型须为列表') from error
    if any(not isinstance(kind, str) for kind in requested):
        raise ValueError('目标类型须为字符串')
    kinds = [kind for kind in requested if kind in TARGET_KINDS]
    sources = _names(source_names, '线索名称')
    templates = {kind: _names(target_names_by_kind.get(kind, []), '目标模板') for kind in kinds}
    if not sources or not kinds:
        return []

    # Learn class associations first. A material such as att_grip_mike4_v9
    # inherits ar from an observed ar_mike4 animation/audio template.
    associations = defaultdict(set)
    for name in [n for values in templates.values() for n in values] + sources:
        for match in _CLASS_CODE.finditer(name):
            kind, code = match.groups()
            if _plausible_code(code, name):
                associations[code.casefold()].add(kind.casefold())
    identities = defaultdict(set)
    roots = defaultdict(set)
    identity_roots = defaultdict(lambda: defaultdict(set))
    identity_quality = defaultdict(dict)
    for name in sources:
        words = set(_WORDS.findall(name))
        clues = [(category, word) for word in words
                 for category in associations.get(word.casefold(), ())]
        equipment = _equipment(name) if 'eqp_' in name.lower() else None
        if not clues and not equipment:
            continue
        title_roots = {m.group(1).lower() for m in _ROOT.finditer(name)}
        quality = (0 if re.search(r'(?:^|[_/\\])(?:wpn|weapon|weap)(?=[_/\\])', name, re.I)
                   else 1 if re.search(r'(?:^|[_/\\])(?:att|m|mtl|material|image|icon|hud)(?=[_/\\])', name, re.I)
                   else 2)
        for category, word in clues:
            identities[category].add(word)
            roots[category].update(title_roots)
            identity_roots[category][word].update(title_roots)
            identity_quality[category][word] = min(quality, identity_quality[category].get(word, 2))
        if equipment:
            identities['eqp'].add(equipment)
            roots['eqp'].update(title_roots)
            identity_roots['eqp'][equipment].update(title_roots)
            identity_quality['eqp'][equipment] = min(quality, identity_quality['eqp'].get(equipment, 2))
    if not identities:
        return []

    groups = defaultdict(set)
    template_counts = defaultdict(int)
    observed_classes = defaultdict(set)
    for kind in kinds:
        for name in templates[kind]:
            if kind == 'xanim' and not _ANIMATION_NAME.search(name):
                continue
            if kind != 'xanim' and '.' not in name:
                continue
            matches = [(m.group(1).lower(), m.group(2)) for m in _CLASS_CODE.finditer(name)
                       if _plausible_code(m.group(2), name)]
            if kind == 'xanim':
                obj = _OBJECT_ANIM.search(name)
                if obj and not any(obj.group(1).lower().startswith(c + '_') for c in WEAPON_CLASSES):
                    matches.append(('eqp', obj.group(1)))
            elif kind in ('soundbank', 'soundbanktransient'):
                obj = _equipment(name)
                if obj:
                    matches.append(('eqp', obj))
            seen = set()
            for category, code in matches:
                if category not in identities or (category, code.casefold()) in seen:
                    continue
                seen.add((category, code.casefold()))
                frame = _frame(name, code)
                if not frame:
                    continue
                prefix, middles, suffix = frame
                groups[kind, category, prefix, middles, 'observed-identity'].add(suffix)
                template_counts[kind, category] += 1
                observed_classes[kind].add(category)
                # Change only an explicit leading title component. Directory
                # components elsewhere stay literal rather than guessing all
                # underscore-to-separator combinations.
                title, separator, tail = prefix.partition('_')
                if separator and title.lower() in ROOTS:
                    for root in sorted(roots[category]):
                        if root != title.lower():
                            groups[kind, category, root + '_' + tail, middles,
                                   'observed-title-identity'].add(suffix)

    if 'xanim' in kinds:
        for category in sorted(identities):
            if category in observed_classes['xanim']:
                continue
            # No global guessed title list, arbitrary actions or numeric weapon
            # variants: only source-observed roots and a small explicit family.
            for root in sorted(roots[category]) or ['']:
                for view in ('vm', 'wm'):
                    prefix = (root + '_' if root else '') + view + '_'
                    if category != 'eqp':
                        prefix += category + '_'
                    groups['xanim', category, prefix, (), 'finite-animation-actions'].update(
                        '_' + action for action in _ACTIONS)

    plans = []
    source_identity_count = sum(len(values) for values in identities.values())
    emitted_by_rule_kind = defaultdict(int)
    plans_by_rule = defaultdict(int)
    # Reserve search space for migration and numeric hypotheses rather than
    # letting a huge historical audio corpus consume all available stages.
    rule_limits = {'observed-identity': (6_000_000, 376),
                   'observed-title-identity': (1_480_000, 96),
                   'finite-animation-actions': (20_000, 8),
                   'observed-identity-number': (500_000, 32)}
    unbounded_upper_bound = sum(len(identities[key[1]]) * len(tails) for key, tails in groups.items())

    def frame_priority(key):
        kind, category, prefix, middles, rule = key
        title = _ROOT.search(prefix)
        root = title.group(1).lower() if title else ''
        rank = _CURRENT_ROOTS.index(root) if root in _CURRENT_ROOTS else 4
        return rank, ('xanim', 'sndasset', 'soundbank', 'soundbanktransient').index(kind), category, prefix, middles

    def tail_priority(tail):
        stem = tail.partition('.')[0]
        return (0 if re.match(r'^_(?:reload_empty|reload|fire|idle|raise|drop|inspect|ads_up|ads_down)(?:_|$)', stem)
                else 1, len(stem), tail)

    def append(kind, category, prefix, middles, tails, rule, extra_slots=None):
        rule_budget, rule_plan_limit = rule_limits[rule]
        remaining = rule_budget // len(kinds) - emitted_by_rule_kind[rule, kind]
        if remaining <= 0 or plans_by_rule[rule] >= rule_plan_limit or len(plans) >= MAX_CROSS_PLANS:
            return
        title = _ROOT.search(prefix)
        root = title.group(1).lower() if title else ''
        codes = sorted(identities[category], key=lambda code: (
            0 if root and root in identity_roots[category][code] else 1,
            identity_quality[category].get(code, 2),
            0 if identity_roots[category][code].intersection(_CURRENT_ROOTS) else 1, code))
        body = [code + ''.join(middle + code for middle in middles) for code in codes]
        # Rare near-limit names may accept only short identities. Group tails
        # by the exact compatible body set so Plan never overstates its byte
        # limit and valid short candidates are retained.
        compatible = defaultdict(list)
        extras = extra_slots or []
        fixed_bytes = len(prefix.encode('utf-8')) + sum(max(len(v.encode('utf-8')) for v in s) for s in extras)
        for tail in sorted(tails, key=tail_priority):
            allowed = tuple(value for value in body
                            if fixed_bytes + len(value.encode('utf-8')) + len(tail.encode('utf-8')) <= MAX_NAME_BYTES)
            if allowed:
                compatible[allowed].append(tail)
        for allowed, safe_tails in sorted(compatible.items()):
            remaining = rule_budget // len(kinds) - emitted_by_rule_kind[rule, kind]
            if remaining <= 0 or plans_by_rule[rule] >= rule_plan_limit or len(plans) >= MAX_CROSS_PLANS:
                return
            slots = [[prefix], list(allowed), safe_tails, *extras]
            original_total = 1
            for slot in slots:
                original_total *= len(slot)
            # Keep identities broad and shorten lower-priority observed actions
            # first. Then shrink remaining independent slots only as needed.
            for index in [2, 1, *range(3, len(slots))]:
                total = 1
                for slot in slots:
                    total *= len(slot)
                if total <= remaining:
                    break
                other = total // len(slots[index])
                slots[index] = slots[index][:max(1, remaining // other)]
            total = 1
            for slot in slots:
                total *= len(slot)
            if total > remaining:
                return
            plan = Plan(slots)
            plan.metadata = {
                'generator': 'cross-asset-v1', 'rule': rule, 'target_kinds': [kind],
                'source_names': len(sources), 'source_identities': source_identity_count,
                'class_source_identities': len(identities[category]),
                'template_names': template_counts[kind, category], 'category': category,
                'number_max': number_max,
                'hypothesis': True, 'verification_required': 'complete-target-hash',
                'unbounded_plan_combinations': original_total,
                'plan_limited': plan.total < original_total,
                'candidate_limit': MAX_CROSS_CANDIDATES, 'plan_limit': MAX_CROSS_PLANS,
            }
            description = '有限动画动作推测' if rule == 'finite-animation-actions' else '已有动画/声音模板替换标识'
            if rule == 'observed-title-identity':
                description = '已有模板迁移作品前缀并替换标识'
            elif rule == 'observed-identity-number':
                description = '已有模板替换标识并扩展数字'
            plans.append((description + '（' + kind + ' · ' + category + '）', plan))
            emitted_by_rule_kind[rule, kind] += plan.total
            plans_by_rule[rule] += 1

    # Actual templates precede inferred title/action and number variants.
    priorities = {'observed-identity': 0, 'observed-title-identity': 1, 'finite-animation-actions': 2}
    for (kind, category, prefix, middles, rule), tails in sorted(
            groups.items(), key=lambda item: (priorities[item[0][-1]], frame_priority(item[0]))):
        append(kind, category, prefix, middles, tails, rule)
    numeric = defaultdict(set)
    for (kind, category, prefix, middles, rule), tails in sorted(groups.items()):
        if rule != 'observed-identity':
            continue
        for tail in tails:
            stem, dot, extension = tail.partition('.')
            match = _NUMBER.search(stem)
            if match:
                numeric[kind, category, prefix, middles, len(match.group(1)),
                        stem[match.end(1):] + dot + extension].add(stem[:match.start(1)])
    for (kind, category, prefix, middles, width, tail), starts in sorted(numeric.items()):
        lengths = defaultdict(list)
        for value in range(number_max + 1):
            text = str(value).zfill(width)
            lengths[len(text)].append(text)
        for numbers in lengths.values():
            append(kind, category, prefix, middles, starts, 'observed-identity-number', [numbers, [tail]])
        unbounded_upper_bound += len(identities[category]) * len(starts) * (number_max + 1)
    emitted_total = sum(plan.total for _, plan in plans)
    for _, plan in plans:
        plan.metadata.update({
            'unbounded_cross_combinations_upper_bound': unbounded_upper_bound,
            'emitted_cross_combinations': emitted_total,
            'omitted_cross_combinations_upper_bound': max(0, unbounded_upper_bound - emitted_total),
            'bounded_search': True,
        })
    return plans
